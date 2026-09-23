"""89b: opt-in public collection and offline rebuild of observation timing.

Run --help. One serial process per cache. Network hard-stops at the mission's
absolute deadline; a STOP file also stops collection. No venue endpoints.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import requests
from weather.paths import data_path
from weather.market.market_registry import BUILTIN_SPECS
from weather.sources.metar_history import IEM_ASOS_URL
from weather.sources.asos_one_minute import IEM_ASOS_1MIN_URL
from weather.market.observation_clock import (
    Observation, RemainingRiseEstimator, clock_table, day_grid,
    historical_dead_probability,
)
from weather.units import c_to_native, round_half_up, to_float

ROOT = data_path("observation_clock_89b")
START, END = date(2026, 6, 1), date(2026, 9, 22)
CUTOFF = datetime(2026, 9, 23, 23, 45, tzinfo=timezone.utc)
SPECS = sorted(BUILTIN_SPECS, key=lambda s: s.id)
SPLIT = date(2026, 9, 1)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def network_allowed(now=None):
    if (now or datetime.now(timezone.utc)) >= CUTOFF:
        raise RuntimeError("network deadline passed; no resumption authorized")
    if (ROOT / "STOP").exists():
        raise RuntimeError("STOP sentinel: network prohibited")


def cache_metadata(root):
    for path in sorted((root / "cache").glob("*.json")):
        meta = json.loads(path.read_text(encoding="utf-8"))
        parsed = urlparse(meta["url"])
        if parsed.hostname != "mesonet.agron.iastate.edu" or parsed.path not in {
            "/cgi-bin/request/asos.py", "/cgi-bin/request/asos1min.py"
        }:
            continue
        if meta.get("status") != 200:
            continue
        body = path.with_suffix(".body")
        if sha(body.read_bytes()) != meta["sha256"]:
            raise ValueError(f"cache integrity failed: {path.name}")
        yield path, meta


def reuse(source):
    count = 0
    (ROOT / "cache").mkdir(parents=True, exist_ok=True)
    for path, meta in cache_metadata(source):
        # Only public weather bodies; never copy Rules or venue responses.
        dest = ROOT / "cache" / path.name
        if dest.exists():
            continue
        shutil.copyfile(path.with_suffix(".body"), dest.with_suffix(".body"))
        dump(dest, {**meta, "reused_from": "86a", "original_metadata_sha256": sha(path.read_bytes())})
        count += 1
    print(f"Reused {count} verified public IEM responses", flush=True)


class Cache:
    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False

    def get(self, url, params):
        if url not in (IEM_ASOS_URL, IEM_ASOS_1MIN_URL):
            raise ValueError("only the two public IEM endpoints are allowed")
        prepared = requests.Request("GET", url, params=params).prepare()
        key = sha(prepared.url.encode())
        path = ROOT / "cache" / f"{key}.json"
        if path.exists():
            meta = json.loads(path.read_text())
            if sha(path.with_suffix(".body").read_bytes()) != meta["sha256"]:
                raise ValueError("cache integrity failed")
            if meta["status"] != 200:
                raise RuntimeError("retained HTTP failure; no automatic retry")
            return
        network_allowed()
        stamp = ROOT / "last_request.json"
        previous = json.loads(stamp.read_text())["completed"] if stamp.exists() else 0
        while time.time() < previous + 15:
            network_allowed()
            time.sleep(0.1)
        if (CUTOFF - datetime.now(timezone.utc)).total_seconds() < 65:
            raise RuntimeError("insufficient time before network deadline")
        meta = {"url": prepared.url, "fetched_at_utc": datetime.now(timezone.utc).isoformat()}
        pieces = []
        with self.session.get(prepared.url, timeout=(15, 30), stream=True,
                              allow_redirects=False,
                              headers={"User-Agent": "weather-observation-clock-research/89b"}) as response:
            meta["status"] = response.status_code
            for piece in response.iter_content(65536):
                network_allowed()
                pieces.append(piece)
                if sum(map(len, pieces)) > 64 * 1024 * 1024:
                    raise RuntimeError("response exceeds 64 MiB bound")
        raw = b"".join(pieces)
        meta.update(sha256=sha(raw), bytes=len(raw), completed_at_utc=datetime.now(timezone.utc).isoformat())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.with_suffix(".body").write_bytes(raw)
        dump(path, meta)
        dump(stamp, {"completed": time.time()})
        print(f"HTTP {meta['status']} {len(raw)} bytes {prepared.url}", flush=True)
        if meta["status"] != 200:
            raise RuntimeError("HTTP failure retained; stopping without retry")


def collect():
    network_allowed()
    # Also interrupts blocked DNS/header/body reads at the absolute deadline.
    timer = threading.Timer((CUTOFF - datetime.now(timezone.utc)).total_seconds(), lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        cache = Cache()
        for kind in (3, 4):
            cache.get(IEM_ASOS_URL, [("data", "tmpc"), ("data", "metar"),
                ("tz", "Etc/UTC"), ("format", "onlycomma"), ("latlon", "no"),
                ("missing", "M"), ("report_type", str(kind))] +
                [("station", s.icao) for s in SPECS] +
                [("sts", "2026-06-01T00:00:00Z"), ("ets", "2026-09-23T08:00:00Z")])
        # 86a already covers July 1 through September 21. Without that cache,
        # request bounded month chunks as well. Empty recent ASOS is evidence.
        ranges = [("2026-06-01", "2026-06-16"), ("2026-06-16", "2026-07-01"),
                  ("2026-09-22", "2026-09-23")]
        has_reuse = any(m.get("reused_from") == "86a" and "asos1min" in m["url"]
                        for _, m in cache_metadata(ROOT))
        if not has_reuse:
            ranges += [("2026-07-01", "2026-07-29"), ("2026-07-29", "2026-08-26"),
                       ("2026-08-26", "2026-09-22")]
        for start, end in ranges:
            for stations in ("ATL,AUS,ORD", "DAL,BKF,HOU", "LAX,MIA,LGA", "SFO,SEA"):
                cache.get(IEM_ASOS_1MIN_URL, {"station": stations, "tz": "Etc/UTC",
                    "format": "onlycomma", "vars": "tmpf", "sample": "1min",
                    "what": "download", "delim": "comma", "gis": "no",
                    "sts": start + "T00:00:00Z", "ets": end + "T08:00:00Z"})
    finally:
        timer.cancel()


def csv_write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_observations():
    """Stream retained responses; retain one-minute data as compact day maps."""
    aliases = {}
    for spec in SPECS:
        aliases[spec.icao] = spec
        aliases[spec.icao[1:] if spec.icao.startswith("K") else spec.icao] = spec
    typed, untyped = defaultdict(dict), defaultdict(dict)
    minute_days = defaultdict(dict)
    provenance, conflicts = [], Counter()
    ambiguous_days = set()
    for path, meta in cache_metadata(ROOT):
        query = parse_qs(urlparse(meta["url"]).query)
        minute_source = "asos1min.py" in meta["url"]
        if not minute_source and "metar" not in query.get("data", []):
            continue
        kind = {("3",): "routine", ("4",): "special"}.get(tuple(query.get("report_type", [])), "unknown")
        provenance.append({"cache": path.name, **meta})
        with path.with_suffix(".body").open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or not any(k.startswith("valid") for k in reader.fieldnames):
                raise ValueError(f"no timestamp column in {path.name}")
            time_key = next(k for k in reader.fieldnames if k.startswith("valid"))
            for raw in reader:
                spec = aliases.get(raw["station"].upper())
                if spec is None:
                    raise ValueError("unexpected station")
                valid = datetime.fromisoformat(raw[time_key]).replace(tzinfo=timezone.utc)
                local = valid.astimezone(spec.tz)
                if not START <= local.date() <= END:
                    continue
                if minute_source:
                    temp = to_float(raw.get("tmpf"))
                    if temp is None:
                        continue
                    values = minute_days[(spec.id, local.date())]
                    minute = local.hour * 60 + local.minute
                    if minute in values and values[minute] != temp:
                        conflicts["asos_temperature_revision"] += 1
                        values[minute] = None
                        ambiguous_days.add(("asos", spec.id, local.date()))
                    else:
                        values[minute] = temp
                else:
                    temp = to_float(raw.get("tmpc"))
                    temp = None if temp is None else c_to_native(temp, spec.unit)
                    obs = Observation(valid, temp, kind)
                    target = untyped if kind == "unknown" else typed
                    key = (valid, kind)
                    if key in target[spec.id] and target[spec.id][key].temperature != temp:
                        conflicts[f"{kind}_temperature_revision"] += 1
                        ambiguous_days.add((kind, spec.id, local.date()))
                        obs = Observation(valid, None, kind)
                    target[spec.id][key] = obs
        print(f"Parsed {path.name[:12]} {'asos' if minute_source else kind}", flush=True)
    reuse_check = Counter()
    for spec in SPECS:
        # Reuse the cached temperature on exact matches. Typed fetches add
        # classification, June and Sep 22; revisions remain explicitly counted.
        prior = {r.valid: r for r in untyped[spec.id].values()}
        for key, obs in list(typed[spec.id].items()):
            if obs.valid in prior:
                if obs.temperature != prior[obs.valid].temperature:
                    reuse_check["temperature_revision"] += 1
                else:
                    typed[spec.id][key] = Observation(obs.valid, prior[obs.valid].temperature, obs.kind)
                    reuse_check["matched_reused"] += 1
        if not typed[spec.id]:
            raise ValueError(f"no typed history: {spec.id}")
        by_valid = defaultdict(list)
        for row in typed[spec.id].values():
            by_valid[row.valid].append(row)
        for valid, same_time in by_valid.items():
            if len({r.temperature for r in same_time if r.temperature is not None}) > 1:
                conflicts["cross_type_temperature_revision"] += 1
                ambiguous_days.add(("routine", spec.id, valid.astimezone(spec.tz).date()))
    return typed, minute_days, provenance, dict(conflicts), dict(reuse_check), ambiguous_days


def crossed_summary(rows, field, *, draws=2000):
    """Exploratory percentile CI of a date x market cell mean."""
    import numpy as np
    dates = sorted({r["date"] for r in rows})
    markets = sorted({r["market"] for r in rows})
    ds, ms = {d: i for i, d in enumerate(dates)}, {m: i for i, m in enumerate(markets)}
    matrix = np.zeros((len(dates), len(markets)))
    mask = np.zeros_like(matrix)
    for row in rows:
        if row[field] is not None:
            i, j = ds[row["date"]], ms[row["market"]]
            matrix[i, j] = row[field]
            mask[i, j] = 1
    if not mask.sum():
        return {"mean": None, "n": 0}
    rng = np.random.default_rng(890923)
    dw = rng.multinomial(len(dates), np.full(len(dates), 1 / len(dates)), draws)
    mw = rng.multinomial(len(markets), np.full(len(markets), 1 / len(markets)), draws)
    den = np.einsum("bi,ij,bj->b", dw, mask, mw)
    num = np.einsum("bi,ij,bj->b", dw, matrix, mw)
    boot = num[den > 0] / den[den > 0]
    se = float(boot.std(ddof=1))
    return {"mean": float(matrix.sum() / mask.sum()), "n": int(mask.sum()),
            "dates": len(dates), "markets": len(markets),
            "low": float(np.quantile(boot, .025)), "high": float(np.quantile(boot, .975)),
            "se": se, "mde80_normal_approx": 2.8016 * se}


def analyze():
    import numpy as np
    typed, minute_days, provenance, conflicts, reuse_check, ambiguous_days = read_observations()
    clocks, station_days, curves, scored, training, comparisons = [], [], [], [], [], []
    hourly_curves = []
    hour_changes, clock_minutes = [], []
    curve_groups = defaultdict(list)
    calibration_groups = defaultdict(list)
    dates = [START + timedelta(days=i) for i in range((END - START).days + 1)]
    for spec in SPECS:
        rows = list(typed[spec.id].values())
        by_date = defaultdict(list)
        for obs in rows:
            by_date[obs.valid.astimezone(spec.tz).date()].append(obs)
        clock = clock_table(rows, spec.timezone)
        modal_minute = max(clock["routine_minutes"], key=clock["routine_minutes"].get)
        day_counts = [{"market": spec.id, "date": str(d),
                       "special_count": sum(r.kind == "special" for r in by_date[d]),
                       "modal_fraction": (
                           sum(r.kind == "routine" and r.valid.astimezone(spec.tz).minute == modal_minute for r in by_date[d])
                           / sum(r.kind == "routine" for r in by_date[d]))
                       if any(r.kind == "routine" for r in by_date[d]) else None}
                      for d in dates]
        clock["special_daily_ci"] = crossed_summary(day_counts, "special_count")
        clock["modal_daily_ci"] = crossed_summary(day_counts, "modal_fraction")
        clocks.append({"market": spec.id, "station": spec.icao, "unit": spec.unit, **clock})
        for minute, n in clock["routine_minutes"].items():
            clock_minutes.append({"market": spec.id, "station": spec.icao, "minute": minute,
                                  "count": n, "fraction": n / clock["routine_count"]})
        for hour in range(24):
            for change in ("lt1", "1to2", "2to4", "ge4", "unknown"):
                n = sum(r["count"] for r in clock["special_hour_change"] if r["hour"] == hour and r["change"] == change)
                hour_changes.append({"market": spec.id, "hour": hour, "change_native": change,
                    "count": n, "requested_date_hours": len(dates),
                    "reports_per_requested_date_hour": n / len(dates)})
        definitions = {}
        for definition in ("all", "hourly"):
            days = [day_grid(by_date[d], spec.icao, spec.timezone, d, hourly=definition == "hourly") for d in dates]
            for day, (summary, _) in zip(dates, days):
                summary["ambiguous_revision"] = any((kind, spec.id, day) in ambiguous_days for kind in ("routine", "special"))
                if summary["ambiguous_revision"]:
                    summary["complete_hours"] = False
            definitions[definition] = days
            fit_days = [day for day in days if day[0]["date"] < SPLIT.isoformat()]
            estimator = RemainingRiseEstimator.fit(fit_days, before=SPLIT)
            fit_y = [r["decided"] for summary, grid in fit_days if summary["complete_hours"]
                     for r in grid if r["decided"] is not None]
            baseline = sum(fit_y) / len(fit_y) if fit_y else None
            highs = [s["final_degree"] for s, _ in fit_days if s["complete_hours"]]
            uppers = sorted(set(int(np.quantile(highs, q, method="nearest")) for q in (.25, .5, .75)))
            train_losses = []
            for summary, grid in days:
                station_days.append({"market": spec.id, "station": spec.icao, "unit": spec.unit,
                                     "definition": definition, **summary})
                if not summary["complete_hours"]:
                    continue
                day_date = date.fromisoformat(summary["date"])
                for hour in range(24):
                    hour_rows = [r for r in grid if r["minute"] // 60 == hour and r["decided"] is not None]
                    if hour_rows:
                        hourly_curves.append({"market": spec.id, "date": str(day_date),
                            "definition": definition, "hour": hour,
                            "decided": float(np.mean([r["decided"] for r in hour_rows]))})
                for row in grid:
                    if row["decided"] is None:
                        continue
                    curve_groups[(spec.id, definition, str(day_date)[:7], row["minute"])].append(
                        {**row, "date": str(day_date), "market": spec.id, "band_uppers": uppers})
                    if day_date < SPLIT:
                        values = estimator.rises.get(row["minute"], ())
                        p = sum(r == 0 for r in values) / len(values)
                        train_losses.append((p - row["decided"]) ** 2)
                    else:
                        upper = uppers[len(uppers)//2]
                        pred = estimator.predict(row["minute"], row["running_degree"], target_date=day_date,
                                                 band_upper=upper)
                        if pred["p_decided"] is None:
                            continue
                        p, y = pred["p_decided"], row["decided"]
                        y_above = int(summary["final_degree"] > upper)
                        score = {"market": spec.id, "date": str(day_date), "definition": definition,
                            "minute": row["minute"], "train_n": pred["n"], "p": p, "y": y,
                            "brier": (p-y)**2, "baseline_brier": (baseline-y)**2,
                            "delta_brier": (p-y)**2-(baseline-y)**2,
                            "band_upper": upper, "dead": pred["dead"],
                            "p_final_above": pred["p_final_above"], "final_above": y_above,
                            "above_brier": (pred["p_final_above"] - y_above)**2}
                        scored.append(score)
                        calibration_groups[(spec.id, definition, min(9, int(p*10)))].append(score)
                        calibration_groups[("fleet", definition, min(9, int(p*10)))].append(score)
            training.append({"market": spec.id, "definition": definition, "n": len(train_losses),
                             "brier": float(np.mean(train_losses)), "constant_p": baseline,
                             "band_uppers": uppers})
        for i, day in enumerate(dates):
            a, ag = definitions["all"][i]
            h, hg = definitions["hourly"][i]
            minutes = {m: v for m, v in minute_days[(spec.id, day)].items() if v is not None}
            mmax = max(minutes.values(), default=None)
            metar_cross = min((r.valid.astimezone(spec.tz).hour*60+r.valid.astimezone(spec.tz).minute
                              for r in by_date[day] if r.temperature is not None
                              and round_half_up(r.temperature) == a["final_degree"]), default=None)
            minute_cross = min((m for m, v in minutes.items() if round_half_up(v) >= a["final_degree"]), default=None) if a["final_degree"] is not None else None
            paired = [(ar, hr) for ar, hr in zip(ag, hg) if ar["decided"] is not None and hr["decided"] is not None]
            comparisons.append({"market": spec.id, "date": str(day), "unit": spec.unit,
                "both_complete_hours": a["complete_hours"] and h["complete_hours"],
                "all_degree": a["final_degree"], "hourly_degree": h["final_degree"],
                "degree_diff": None if a["final_degree"] is None or h["final_degree"] is None else a["final_degree"]-h["final_degree"],
                "decidedness_difference_fraction": sum(ar["decided"] != hr["decided"] for ar, hr in paired)/len(paired) if paired else None,
                "asos_samples": len(minutes), "asos_hours": len({m//60 for m in minutes}),
                "asos_ge90pct": len(minutes) >= 1296 and len({m//60 for m in minutes}) == 24 and ("asos", spec.id, day) not in ambiguous_days,
                "asos_degree": None if mmax is None else round_half_up(mmax),
                "asos_minus_metar": None if mmax is None or a["final_degree"] is None else round_half_up(mmax)-a["final_degree"],
                "asos_cross_lead_minutes": None if minute_cross is None or metar_cross is None else metar_cross-minute_cross})
    for (market, definition, month, minute), rows in sorted(curve_groups.items()):
        hist = Counter(r["running_degree"] for r in rows)
        ci = crossed_summary(rows, "decided", draws=1000)
        dead_probabilities = {str(b): historical_dead_probability(hist, b) for b in rows[0]["band_uppers"]}
        dead_intervals = {}
        for upper, probability in dead_probabilities.items():
            # One binary observation/date, one fixed market.
            draws = np.random.default_rng(890923).binomial(len(rows), probability, 1000) / len(rows)
            dead_intervals[upper] = [float(np.quantile(draws, .025)), float(np.quantile(draws, .975))]
        curves.append({"market": market, "definition": definition, "month": month,
            "minute": minute, "local_time": f"{minute//60:02}:{minute%60:02}",
            "n_dates": len(rows), "p_decided": ci["mean"], "low": ci["low"], "high": ci["high"],
            "p_decided_exact": sum(r["decided_exact"] for r in rows)/len(rows),
            "running_degree_counts": json.dumps(dict(sorted(hist.items()))),
            "band_dead_probabilities": json.dumps(dead_probabilities),
            "band_dead_intervals": json.dumps(dead_intervals)})
    reliability = []
    for (market, definition, bin_id), rows in sorted(calibration_groups.items()):
        cells = defaultdict(list)
        for row in rows:
            cells[(row["date"], row["market"])].append(row)
        gaps = [{"date": d, "market": m, "gap": float(np.mean([r["y"]-r["p"] for r in group]))}
                for (d, m), group in cells.items()]
        ci = crossed_summary(gaps, "gap")
        reliability.append({"market": market, "definition": definition, "bin": bin_id,
            "grid_rows": len(rows), "p_mean": float(np.mean([r["p"] for r in rows])),
            "observed": float(np.mean([r["y"] for r in rows])),
            "cell_gap": ci["mean"], "gap_low": ci["low"], "gap_high": ci["high"],
            "date_clusters": ci["dates"], "market_clusters": ci["markets"]})
    scores = []
    for definition in ("all", "hourly"):
        for market in [s.id for s in SPECS] + ["fleet"]:
            cells = defaultdict(list)
            for row in scored:
                if row["definition"] == definition and (market == "fleet" or row["market"] == market):
                    cells[(row["date"], row["market"])].append(row)
            means = [{"date": d, "market": m, **{field: float(np.mean([r[field] for r in group]))
                      for field in ("brier", "delta_brier", "above_brier")}}
                     for (d, m), group in cells.items()]
            scores.append({"market": market, "definition": definition,
                           **{field: crossed_summary(means, field) for field in ("brier", "delta_brier", "above_brier")}})
    out = ROOT / "results"
    hour_groups = defaultdict(list)
    for row in hourly_curves:
        hour_groups[(row["market"], row["definition"], row["date"][:7], row["hour"])].append(row)
    hours = []
    for (market, definition, month, hour), rows in sorted(hour_groups.items()):
        ci = crossed_summary(rows, "decided", draws=1000)
        hours.append({"market": market, "definition": definition, "month": month, "hour": hour,
                      "n_dates": ci["n"], "p_decided": ci["mean"], "low": ci["low"], "high": ci["high"]})
    for name, rows in (("routine_minutes", clock_minutes), ("special_hour_change", hour_changes),
                       ("station_days", station_days), ("curves", curves), ("heldout_predictions", scored),
                       ("calibration", reliability), ("rule_and_asos", comparisons), ("hourly_curves", hours)):
        csv_write(out / f"{name}.csv", rows)
    dump(out / "summary.json", {"start": str(START), "end": str(END), "split": str(SPLIT),
        "clocks": clocks, "training": training, "scores": scores,
        "conflicts": conflicts, "reuse_check": reuse_check,
        "ambiguous_days": sorted((kind, market, str(day)) for kind, market, day in ambiguous_days),
        "provenance": provenance, "files": {p.name: sha(p.read_bytes()) for p in sorted(out.glob("*.csv"))}})
    print(f"Wrote {len(curves)} curves, {len(scored)} held-out rows and {len(station_days)} station-definition-days", flush=True)


REPORT = "agent-report-2026-09-89b-observation-clock-and-band-decidedness"


def report(destination):
    """Render measured tables and static figures, entirely offline."""
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    destination.mkdir(parents=True, exist_ok=True)
    results = ROOT / "results"
    summary = json.loads((results / "summary.json").read_text())
    def read(name):
        with (results / f"{name}.csv").open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    curves, comparisons, calibration = read("curves"), read("rule_and_asos"), read("calibration")
    days = read("station_days")
    for name in ("routine_minutes", "special_hour_change", "curves", "hourly_curves",
                 "station_days", "calibration", "rule_and_asos"):
        shutil.copyfile(results / f"{name}.csv", destination / f"{REPORT}-{name}.csv")
    dump(destination / f"{REPORT}-provenance.json", summary)
    fig, axes = plt.subplots(4, 3, figsize=(13, 12), sharex=True, sharey=True)
    colors = {"2026-06": "#2563eb", "2026-07": "#d97706", "2026-08": "#16a34a", "2026-09": "#a855f7"}
    for ax, spec in zip(axes.flat, SPECS):
        for month, color in colors.items():
            for definition, style in (("all", "-"), ("hourly", "--")):
                rows = [r for r in curves if r["market"] == spec.id and r["month"] == month and r["definition"] == definition]
                ax.plot([int(r["minute"])/60 for r in rows], [float(r["p_decided"]) for r in rows],
                        style, color=color, linewidth=1.5, label=f"{month[5:]} {definition}")
        ax.set_title(f"{spec.city_label} · {spec.icao}", fontsize=10)
        ax.grid(alpha=.18)
        ax.set_xlim(0, 24)
        ax.set_ylim(0, 1)
        ax.set_xticks([0, 6, 12, 18, 24])
    fig.supxlabel("Station local time (archive-valid time; availability lag unknown)")
    fig.supylabel("P(final whole-degree maximum already reached)")
    fig.suptitle("Observation-only decidedness · June–September 22, 2026", fontsize=16)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(.5, .96), ncol=4, fontsize=9)
    fig.tight_layout(rect=(.025, .025, 1, .91))
    fig.savefig(destination / f"{REPORT}-curves.png", dpi=160)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(6.5, 5))
    for definition, color in (("all", "#2563eb"), ("hourly", "#d97706")):
        rows = [r for r in calibration if r["market"] == "fleet" and r["definition"] == definition]
        ax.plot([float(r["p_mean"]) for r in rows], [float(r["observed"]) for r in rows], "o-", label=definition, color=color)
    ax.plot([0, 1], [0, 1], "--", color="#64748b")
    ax.set(xlabel="Mean predicted probability", ylabel="Observed fraction", xlim=(0, 1), ylim=(0, 1),
           title="Held-out September decidedness calibration")
    ax.grid(alpha=.2)
    ax.legend()
    fig.tight_layout()
    fig.savefig(destination / f"{REPORT}-calibration.png", dpi=160)
    plt.close(fig)
    def interval(ci, digits=4):
        return f"{ci['mean']:.{digits}f} [{ci['low']:.{digits}f}, {ci['high']:.{digits}f}]"
    lines = [f"""# 89b — Observation clock and band decidedness

**COMPLETE for the bounded archive measurement and inert library; NO-GO for treating these as live availability clocks or authoritative settlement probabilities. Routine minutes differ by station; hourly-rule filtering changes observed maxima. First-availability lag is unidentified.**

Historical research, 2026-09-23. Named handoff fetched at ded121ef94aeb066d1b88e5bea2291034b0bc6f7. Branch codex/observation-clock-20260923 starts at fetched origin/master 198f7ccbcd8e80271693462425582097d22b298b. Reserved-window status at execution: **NONE RESERVED**.

## Measurement contract

June 1–September 22 inclusive: 114 local dates × 12 configured settlement stations = 1,368 station-days. This is a newly downloaded public observation panel with no model-artifact regime, ledger, venue outcome or promotion-countable claim. Each station uses its own civil day and native unit (Toronto C, the other eleven F). No six-hour or 24-hour extrema enter instantaneous temperatures.

The [IEM METAR endpoint](https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?help=) distinguishes routine reports (report_type=3) and specials (4). Combined responses strip that distinction. Typed queries cover the full interval; 86a's cached temperatures supply {summary['reuse_check'].get('matched_reused', 0):,} exact matches. High-frequency type 1 is excluded. Conflicting same-time archive revisions: {json.dumps(summary['conflicts'], sort_keys=True)}. Typed conflicts exclude the entire affected day from fit, curves and calibration; partial observed maxima remain marked in the appendix. Identical timestamp/type duplicates count once.

An eligible day has temperature in all 24 local hours and no ambiguous typed revision. This is a sampling diagnostic, not proof that the physical high or every report was observed. All 1,368 days remain in the appendix. Eligibility is retrospective and cannot itself be a live gate. No empty prefix is carried from yesterday or converted to zero. Early-hour curve denominators condition on at least one in-day observation and can be small.

## T1: station clock

Counts are an archive census. Modal fractions use all routine reports, including rare off-minute observations. SPECI rates include all 114 requested dates. Rate intervals bootstrap dates (one fixed market: the degenerate crossed date × market case).

| Market / station | Routine reports | Modal local minute / fraction | SPECI | SPECI/day [95% CI] |
| --- | ---: | --- | ---: | --- |"""]
    for c in summary["clocks"]:
        minute = max(c["routine_minutes"], key=c["routine_minutes"].get)
        fraction = c["routine_minutes"][minute] / c["routine_count"]
        lines.append(f"| {c['market']} / {c['station']} | {c['routine_count']} | :{int(minute):02} / {100*fraction:.2f}% | {c['special_count']} | {interval(c['special_daily_ci'], 2)} |")
    lines.append(f"""
[Full routine-minute distributions]({REPORT}-routine_minutes.csv). [SPECI counts and frequencies by local hour and temperature-change bin]({REPORT}-special_hour_change.csv). Absolute change bins are [0,1), [1,2), [2,4), ≥4 native degrees relative to the immediately preceding report within 90 minutes. Missing temperatures, simultaneous reports and longer gaps are unknown. These are report-conditional changes, not P(SPECI | an unobserved physical temperature change). SPECI is not restricted to the modal minute.

**Report-to-availability lag is not measurable at any of the twelve stations from these responses.** Archival download time is not first public availability. One-minute valid-time leads below are not publication latency.

## T3: curves and dead bands

At 00:00, 00:15, …, 23:45 local, admit only observations valid at or before the cutoff. R is the running maximum and M the final observed maximum under the same report definition. The primary decidedness indicator is round-half-up(R) = round-half-up(M), in whole settlement degrees. The exact-temperature companion requires equality of the unrounded archived values. Neither establishes physical or venue truth.

For inclusive band upper b, observed deadness is exactly 1[R_degree > b]. Across dates the requested probability is its empirical frequency. The upper-open tail is never dead; missing R stays unknown. The library accepts any b. Each curve cell retains the complete running-degree histogram, plus examples at station-specific training-high quartiles; summing histogram counts above any b reconstructs the probability for that band.

![T3 curves]({REPORT}-curves.png)

[All station × month × 15-minute curves, exact-temperature companion, intervals and dead-band histograms]({REPORT}-curves.csv). [Station × month × hour means]({REPORT}-hourly_curves.csv) average available quarter-hours within each date first. [Coverage and all station-days]({REPORT}-station_days.csv). Curves are descriptive and include both fit and holdout months; only the estimator calibration below is held out.

## Held-out estimator and calibration

Fit the empirical remaining whole-degree rise M−R for each station, definition and quarter-hour on June 1–August 31; freeze before scoring September 1–22. Minimum 20 training dates per cell or abstain. P(decided) is mass at zero; adding historical rises to today's R gives P(final > b). No weather covariates, venue prices, reconstructed publication times, seasonal refit or held-out tuning. The in-sample fit check is computed before held-out summaries. The comparator is each station's training all-hour decidedness rate: beating this deliberately weak clock-free comparator says nothing about forecast skill or market edge.

| Definition | Eligible holdout station-days; dates × markets | Decidedness Brier [95% CI] | Δ vs constant [95% CI] | Final-above-band Brier [95% CI] |
| --- | --- | --- | --- | --- |""")
    for s in summary["scores"]:
        if s["market"] == "fleet":
            b = s["brier"]
            lines.append(f"| {s['definition']} | {b['n']}; {b['dates']} × {b['markets']} | {interval(b)} | {interval(s['delta_brier'])} | {interval(s['above_brier'])} |")
    lines += ["", "| Station | Train Brier all / hourly | Holdout Brier all / hourly [95% CIs] | Eligible holdout dates |",
              "| --- | --- | --- | ---: |"]
    for spec in SPECS:
        train = {r["definition"]: r for r in summary["training"] if r["market"] == spec.id}
        score = {r["definition"]: r for r in summary["scores"] if r["market"] == spec.id}
        lines.append(f"| {spec.icao} | {train['all']['brier']:.4f} / {train['hourly']['brier']:.4f} | {interval(score['all']['brier'])} / {interval(score['hourly']['brier'])} | {score['all']['brier']['dates']} / {score['hourly']['brier']['dates']} |")
    lines.append(f"""
![Held-out calibration]({REPORT}-calibration.png)

[Reliability bins by station and fleet, including calibration-gap intervals]({REPORT}-calibration.csv). Plot p/y are row-weighted; gap intervals weight date-market cell means equally and are labelled separately. Calibration is not uniformly good: in the all-report 0.3–0.4 bin, 172 grid rows average 0.352 predicted versus 0.140 observed; its cell-weighted gap interval excludes zero. This exploratory, unadjusted bin finding is not a correction fitted to the holdout. The 0.7–0.8 bin errs the opposite way. Most other bin gaps are not distinguishable from zero. Band-upper examples use the median of distinct training-high quartiles; that fixed upper and every prediction are retained under ignored data/observation_clock_89b/results/heldout_predictions.csv and hash-bound in provenance.

Uncertainty uses independent date and market bootstrap weights, 2,000 draws (1,000 for descriptive curves), seed 890923. Each date-market cell averages its grid rows first. Per-station intervals hold one market fixed. Fleet calibration has 22 date and 12 market clusters. Adjacent weather dates may be dependent; these exploratory intervals do not guarantee seasonal generalization. Degenerate empirical intervals cannot prove population certainty. No alpha budget or promotion decision is spent.

The 80%-power normal-approximation MDE for the paired Brier delta is 2.8016 × crossed-bootstrap SE:
""")
    for s in summary["scores"]:
        if s["market"] == "fleet":
            d = s["delta_brier"]
            from statistics import NormalDist
            effect = abs(d["mean"]) / d["se"]
            power = NormalDist().cdf(effect-1.959964) + NormalDist().cdf(-effect-1.959964)
            lines.append(f"- {s['definition']}: MDE {d['mde80_normal_approx']:.4f}; plug-in power at the observed delta {100*power:.1f}%.")
    lines.append("""
Plug-in power is descriptive, not independent or prospective evidence. Both deltas are distinguishable from zero against the weak constant comparator. Power against venue truth or market forecasts is unidentified: neither outcome is in this study.

## Hourly-rule sensitivity and one-minute comparison

86a's retained Rules check says current Rules use WRH Hourly Data. The [WRH help](https://www.weather.gov/wrh/timeseries?site=klga) specifies :51–:59 for NWS/FAA platforms and :56–:04 for others. We retain 86a's proxy mapping (K-prefixed configured stations use the former, CYYZ the latter); WRH's platform assignment, especially military KBKF, is not independently verified here. Applying the filter to IEM does not reproduce WRH feed selection, precision, revisions or settlement cutoff. No venue call rechecked Rules; this is not an adopted resolution source.

| Station | Eligible days all / hourly | Different degrees / common days | ASOS days any / ≥90%+24h | Median ASOS−METAR degree on adequate common pairs | Median valid-time lead, min |
| --- | ---: | ---: | ---: | ---: | ---: |""")
    for spec in SPECS:
        ds = [r for r in days if r["market"] == spec.id]
        counts = {definition: sum(r["definition"] == definition and r["complete_hours"] == "True" for r in ds) for definition in ("all", "hourly")}
        cs = [r for r in comparisons if r["market"] == spec.id]
        paired = [r for r in cs if r["both_complete_hours"] == "True"]
        adequate = [r for r in paired if r["asos_ge90pct"] == "True"]
        delta = f"{np.median([float(r['asos_minus_metar']) for r in adequate]):g}" if adequate else "—"
        leads = [float(r["asos_cross_lead_minutes"]) for r in adequate if r["asos_cross_lead_minutes"]]
        lead = f"{np.median(leads):g} (n={len(leads)})" if leads else "—"
        lines.append(f"| {spec.icao} | {counts['all']} / {counts['hourly']} | {sum(float(r['degree_diff']) != 0 for r in paired)} / {len(paired)} | {sum(int(r['asos_samples'])>0 for r in cs)} / {sum(r['asos_ge90pct']=='True' for r in cs)} | {delta} (n={len(adequate)}) | {lead} |")
    paired = [r for r in comparisons if r["both_complete_hours"] == "True"]
    lines.append(f"""
Of {len(paired)} common eligible station-days, {sum(float(r['degree_diff'])!=0 for r in paired)} have different whole-degree maxima. [Every day and difference]({REPORT}-rule_and_asos.csv) includes the fraction of paired grid points with different decidedness, even when final degrees agree. All-report maxima cannot be below the hourly subset.

ASOS lead compares the first one-minute observation reaching the **METAR day's final degree** with the first METAR reaching that same threshold. Positive means an earlier archived observation, not earlier public availability. The medians are descriptive census summaries with pair counts, not inferential equivalence claims. ASOS adequate pairs require ≥1,296 minutes and all 24 hours; gaps can still hide a maximum.

The [IEM one-minute service](https://mesonet.agron.iastate.edu/cgi-bin/request/asos1min.py?help=) is an NCEI archive, not the MADIS minute feed, and documents about 24 hours of availability delay. Actual retained coverage is incomplete. Toronto is unsupported by the existing US-only resolver; KBKF returned no usable minute temperatures. The September 22 requests returned only earlier UTC-envelope rows for some stations and no local September 22 minute observations. Empty responses are missingness, not weather.

## Proposed calendar diff — not applied

The library exposes the dated historical STATION_ROUTINE_MINUTES table and a pure clock_table builder. A future reviewed change should resolve the station, permit explicit per-station overrides and preserve other source configuration. Keep existing pre/post buffers until prospective first-seen evidence can calibrate them. Modal minutes never imply SPECI-free periods.

~~~diff
--- a/src/weather/market/info_event_calendar.py
+++ b/src/weather/market/info_event_calendar.py
@@ imports
+from weather.market.observation_clock import STATION_ROUTINE_MINUTES
@@ def _scheduled_hourly_events(...):
-    minutes = [int(value) for value in spec_config.get("minutes") or []]
+    configured = spec_config.get("minutes") or []
+    if source == "metar":
+        station = spec_for_id(market_id).icao.upper()
+        overrides = spec_config.get("station_minutes") or {{}}
+        configured = overrides.get(station, STATION_ROUTINE_MINUTES.get(station, configured))
+    minutes = [int(value) for value in configured]
~~~

This is a review proposal only; info_event_calendar.py and its config are unchanged. Unknown stations retain a clearly labelled fallback. A future change needs override/fallback tests, table freshness policy, latency evidence and production roll qualification.

## Reproduction and provenance

From this branch's repository root, choose the installed project interpreter as $python. The worktree used the main checkout's venv by absolute path. Ignored cache is not guaranteed in a clean checkout; a later recollection needs new owner authority and a new mission deadline, not guard removal.

~~~powershell
& $python tools/observation_clock_20260923.py --help
# Optional verified reuse; supply the actual 86a cache root:
& $python tools/observation_clock_20260923.py reuse --reuse-root <86a-cache-root>
# Only inside this mission's authorized network window:
& $python tools/observation_clock_20260923.py collect --network
# Offline rebuild:
& $python tools/observation_clock_20260923.py analyze
& $python tools/observation_clock_20260923.py report
~~~

One serial foreground collector, ≥15 seconds after request completion between IEM requests, hash-verified cache, no automatic retries or redirects, no ambient netrc/proxy credentials, 64 MiB response bound and socket timeouts. A process timer terminates blocked requests at 2026-09-23 19:45 ET. data/observation_clock_89b/STOP prevents new requests. No background collector or schedule remains.

[Source URLs, hashes, timestamps, training/held-out estimates and artifact hashes]({REPORT}-provenance.json). Raw bodies and detailed held-out predictions remain under this worktree's ignored data/observation_clock_89b. Report CSV/JSON appendices use LF.

## Handback boundary

No .env, credential, venue call, RE-1 worktree access, model work beyond the requested timing estimator, candidate, serving, floor, gate, ledger, config, release or production write; no registration, restart or merge. The original checkout and other worktrees were preserved. Exact instrument commit, verification and tool-derived roll result follow in the addendum; the final report commit cannot embed its own hash.
""")
    (destination / f"{REPORT}.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"Report rendered to {destination}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("reuse", "collect", "analyze", "report"))
    parser.add_argument("--reuse-root", type=Path)
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "report")
    args = parser.parse_args()
    if args.command == "reuse":
        if not args.reuse_root:
            parser.error("reuse needs --reuse-root")
        reuse(args.reuse_root)
    elif args.command == "collect":
        if not args.network:
            parser.error("collection requires --network")
        collect()
    elif args.command == "analyze":
        analyze()
    else:
        report(args.report_dir)


if __name__ == "__main__":
    main()
