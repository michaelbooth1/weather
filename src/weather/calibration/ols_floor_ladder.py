"""Lane L9 research: the simple-model ingredient ladder on lane L3's OLS + hard floor.

Offline, weather-only research. Nothing in serving, capture, release or Scheduler imports this
module. The import refuses on the dedicated capture host, through lane L3's
``refuse_production_import``, which this module imports first.

Pre-declared rule: ``C:\\t\\l9\\rule.md`` (its sha256 is recorded beside it before any row exists).
Rows are L3's (the R0 trainer's records and LOYO splits, via
``weather.calibration.r0_ols_floor_challenger.build_r0_records``) at several non-overlapping
centres in Aug-Sep and Oct-Dec of 2021-2025. BASE is L3's ``ols_floor`` bit for bit. An arm adds
or swaps one ingredient, and everything else is identical.

Subcommands:

* ``build`` (heavy: record builds): per (market, centre), write every trainer record's needed
  fields, with the overnight low derived from the same history rows as ``high_so_far``;
* ``nbm-corpus`` (light): parse lane L9's NBP station-block fetch with parser v2 into a PIT NBM
  corpus file whose sha256 is the corpus id;
* ``score``: per-row losses of BASE and the arms on identical rows; the date-clustered bootstrap
  and the KEEP rule;
* ``control``: the positive control against L3's per-row ``ols_floor_log_loss``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather.calibration import r0_ols_floor_challenger as l3  # refuses on the capture host

ALL_MARKETS = l3.ALL_MARKETS
PRIMARY_MARKETS = l3.PRIMARY_MARKETS
HOURS = tuple(range(7, 21))
BLOCKS = {"07-12": tuple(range(7, 13)), "12-16": tuple(range(12, 17)), "17-20": tuple(range(17, 21))}
CENTRES = {
    "aug-sep": ("08-08", "08-23", "09-07", "09-22"),
    "oct-dec": ("10-10", "10-25", "11-09", "11-24", "12-09"),
}
CENTRE_YEAR = 2026
LAST_ALLOWED = date(2026, 9, 29)
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261025
MDE_FACTOR = 2.80
NBM_STATIONS = {
    "atlanta": "KATL", "austin": "KAUS", "chicago": "KORD", "dallas": "KDAL", "denver": "KBKF",
    "houston": "KHOU", "los-angeles": "KLAX", "miami": "KMIA", "nyc": "KLGA",
    "san-francisco": "KSFO", "seattle": "KSEA",
}
NBM_CYCLE_PREFERENCE = ("07", "01", "00")
PLACEBO_SALT = "l9-placebo-20261025"
CACHE_FIELDS = ("forecast_high", "high_so_far", "current_temp", "dewpoint_c")


class LadderError(RuntimeError):
    """The research run cannot proceed honestly."""


def season_of(day):
    return "aug-sep" if int(str(day)[5:7]) in (8, 9) else "oct-dec"


# ---------------------------------------------------------------- build

def overnight_lows(rows, record_date, hour, prev_rows, record_high):
    """(low since local midnight, low since 18:00 of the previous date or None).

    Same row set as the trainer's ``high_so_far`` (minute_of_day <= cutoff*60). The max over it
    is asserted equal to the record's high_so_far.
    """
    from weather.model.feature_store import row_temp_native

    cutoff = int(hour) * 60
    temps = [row_temp_native(r) for r in rows
             if r.get("minute_of_day") is not None and int(r["minute_of_day"]) <= cutoff]
    temps = [t for t in temps if t is not None]
    if not temps:
        raise LadderError(f"{record_date} h{hour}: no temperature at or before the cutoff")
    if record_high is not None and abs(max(temps) - float(record_high)) > 1e-9:
        raise LadderError(f"{record_date} h{hour}: row set differs from high_so_far's")
    low = min(temps)
    prev = None
    if prev_rows:
        evening = [row_temp_native(r) for r in prev_rows
                   if r.get("minute_of_day") is not None and int(r["minute_of_day"]) >= 18 * 60]
        evening = [t for t in evening if t is not None]
        if evening:
            prev = min(low, min(evening))
    return low, prev


def build_market_centre(market_id, centre, manifests):
    target = date.fromisoformat(f"{CENTRE_YEAR}-{centre}")
    built = l3.build_r0_records(market_id, target, manifests)
    model = built["model"]
    by_date = model.historical_target_cache()["by_date"]
    out = {"market_id": market_id, "centre": centre, "target_date": target.isoformat(),
           "bucket_space": [int(b) for b in built["bucket_space"]],
           "corpus_ids": built["corpus_ids"], "day_counts": built["day_counts"],
           "timezone": model.spec.timezone, "hours": {}}
    for hour in sorted(built["records"]):
        records = built["records"][hour]
        from weather.calibration.feature_model import feature_blocked_validation_plan

        plan = feature_blocked_validation_plan(records)
        train_by_val = plan["train_indices_by_validation_index"]
        rows = []
        for idx, rec in enumerate(records):
            d = rec["target_date"]
            d = d if isinstance(d, date) else date.fromisoformat(str(d))
            if d > LAST_ALLOWED:
                raise LadderError(f"record after {LAST_ALLOWED}: {d}")
            year = d.year
            train = train_by_val.get(idx) or []
            expected = [i for i, r in enumerate(records) if str(r["target_date"])[:4] != str(year)]
            scored = bool(train) and len({records[i]["final_bucket"] for i in train}) >= 2
            if train and sorted(train) != expected:
                raise LadderError(f"{market_id} {centre} h{hour}: LOYO train set is not year != {year}")
            low, low_prev = overnight_lows(by_date.get(d, []), d, hour,
                                           by_date.get(d - timedelta(days=1)), rec.get("high_so_far"))
            row = {"date": d.isoformat(), "year": year, "actual": int(rec["final_bucket"]),
                   "scored": scored, "low_so_far": low, "low_prev_evening": low_prev}
            for name in CACHE_FIELDS:
                v = rec.get(name)
                row[name] = None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)
            rows.append(row)
        out["hours"][str(hour)] = rows
    return out


def _build_command(args):
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    centres = args.centres.split(",") if args.centres else [c for s in CENTRES.values() for c in s]
    for market in args.markets.split(","):
        for centre in centres:
            path = out_dir / f"cache_{market}_{centre}.json"
            if path.exists() and not args.overwrite:
                print(f"skip {path.name}", flush=True)
                continue
            payload = build_market_centre(market, centre, args.pit_forecast_corpus_manifest)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            tmp.replace(path)
            n = sum(len(v) for v in payload["hours"].values())
            print(f"built {market} {centre} records={n}", flush=True)
    return 0


# ---------------------------------------------------------------- NBM corpus

def _cutoff_instant(day, hour, tz):
    from zoneinfo import ZoneInfo

    local = datetime(day.year, day.month, day.day, int(hour), 0, tzinfo=ZoneInfo(tz))
    return local.astimezone(timezone.utc)


def _nbm_corpus_command(args):
    from weather.sources.nbm_probabilistic_tmax import parse_nbp_station_tmax

    rows = []
    for path in args.blocks:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            day = date.fromisoformat(rec["utc_date"])
            if day > LAST_ALLOWED:
                raise LadderError(f"NBM block after {LAST_ALLOWED}: {day}")
            obj = rec.get("object")
            for market, station in NBM_STATIONS.items():
                base = {"market_id": market, "station_id": station, "target_date": day.isoformat(),
                        "cycle": rec["cycle"], "key": rec["key"],
                        "last_modified": obj and obj["last_modified"], "etag": obj and obj["etag"]}
                block = (rec.get("stations") or {}).get(station)
                if not obj or not block:
                    rows.append({**base, "available": False,
                                 "reason": "object_missing" if not obj else "station_missing"})
                    continue
                p = parse_nbp_station_tmax(block["block"], station, day)
                rows.append({**base, "available": bool(p["available"]), "reason": p.get("reason"),
                             "issued_at": p.get("issued_at"), "valid_time_utc": p.get("valid_time_utc"),
                             "mean": p.get("mean_native"), "sd": p.get("stddev_native"),
                             "p10": (p.get("percentiles") or {}).get("10"),
                             "p50": (p.get("percentiles") or {}).get("50"),
                             "p90": (p.get("percentiles") or {}).get("90"),
                             "parser_version": p.get("parser_version"),
                             "product_version": p.get("product_version"),
                             "block_sha256": hashlib.sha256(block["block"].encode()).hexdigest()})
    rows.sort(key=lambda r: (r["market_id"], r["target_date"], r["cycle"]))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode("utf-8")
    corpus_id = hashlib.sha256(body).hexdigest()
    (out / "nbm_pit_corpus_rows.jsonl").write_bytes(body)
    coverage = defaultdict(lambda: {"available": 0, "missing": 0})
    reasons = defaultdict(int)
    for r in rows:
        k = f"{r['market_id']}:{r['target_date'][:4]}:{r['cycle']}"
        coverage[k]["available" if r["available"] else "missing"] += 1
        if not r["available"]:
            reasons[r["reason"]] += 1
    manifest = {"record": "l9_nbm_pit_corpus", "corpus_id": corpus_id, "rows": len(rows),
                "source": "noaa-nbm-grib2-pds blend_nbptx (NBP), parser v2",
                "blocks_files": [str(p) for p in args.blocks],
                "missing": [f"{r['market_id']} {r['target_date']} {r['cycle']} {r['reason']}"
                            for r in rows if not r["available"]],
                "missing_reasons": dict(reasons), "coverage": dict(coverage)}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({"corpus_id": corpus_id, "rows": len(rows), "missing_reasons": dict(reasons)}))
    return 0


def load_nbm(path):
    """{(market, date): [(cycle, last_modified_utc, mean), ...]} for available rows."""
    table = defaultdict(list)
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if not r["available"] or r["mean"] is None:
            continue
        lm = datetime.fromisoformat(r["last_modified"].replace("Z", "+00:00"))
        table[(r["market_id"], r["target_date"])].append((r["cycle"], lm, float(r["mean"])))
    return table


def nbm_at_cutoff(table, market, day, hour, tz):
    """Newest preferred cycle whose LastModified is <= the cutoff instant, else None."""
    instant = _cutoff_instant(date.fromisoformat(day), hour, tz)
    options = {c: (lm, v) for c, lm, v in table.get((market, day), [])}
    for cycle in NBM_CYCLE_PREFERENCE:
        if cycle in options and options[cycle][0] <= instant:
            return options[cycle][1], cycle
    return None, None


# ---------------------------------------------------------------- arms

def placebo(market, day, hour):
    h = hashlib.sha256(f"{PLACEBO_SALT}|{market}|{day}|{hour}".encode()).digest()
    u1 = (int.from_bytes(h[:8], "big") + 0.5) / 2 ** 64
    u2 = (int.from_bytes(h[8:16], "big") + 0.5) / 2 ** 64
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def raw_feature(name, row):
    """Value or None. ``fc_or_nbm`` is N2's 'instead' column."""
    if name == "fc_or_nbm":
        return row["nbm_mean"] if row.get("nbm_mean") is not None else row["forecast_high"]
    if name == "dewpoint":
        return row.get("dewpoint_c")
    return row.get(name)


# Missing-value rule per feature: "fc" = forecast_high (L3's _x_of rule), "mean" = fold mean.
IMPUTE = {"forecast_high": "fc", "high_so_far": "fc", "current_temp": "fc", "nbm_mean": "fc",
          "fc_or_nbm": "fc", "low_so_far": "mean", "low_prev_evening": "mean", "dewpoint": "mean",
          "placebo": "mean"}

BASE_FEATURES = ("forecast_high", "high_so_far", "current_temp")


def arm_features(arm, base):
    base = tuple(base)
    if arm == "BASE":
        return base
    if arm == "N1":
        return base + ("nbm_mean",)
    if arm == "N2":
        return tuple("fc_or_nbm" if f == "forecast_high" else f for f in base)
    if arm == "L1":
        return base + ("low_so_far",)
    if arm == "L1b":
        return base + ("low_prev_evening",)
    if arm == "DP":
        return base + ("dewpoint",)
    if arm == "P":
        return base + ("placebo",)
    if arm in ("PH", "PM"):
        return base
    raise LadderError(f"unknown arm {arm}")


def design(rows, features, means=None):
    import numpy as np

    cols = []
    for name in features:
        vals = []
        for r in rows:
            v = raw_feature(name, r)
            if v is None:
                v = r["forecast_high"] if IMPUTE[name] == "fc" else (means or {}).get(name)
            vals.append(np.nan if v is None else float(v))
        cols.append(vals)
    return np.asarray(cols, dtype=float).T


def fold_means(rows, features):
    import numpy as np

    out = {}
    for name in features:
        vals = [raw_feature(name, r) for r in rows]
        vals = [float(v) for v in vals if v is not None]
        out[name] = float(np.mean(vals)) if vals else 0.0
    return out


def score_rows(caches, nbm, arms, base_features, log=print):
    """Per-row losses for each arm on identical rows (scored, with a forecast)."""
    import numpy as np

    out = []
    stats = defaultdict(int)
    # Attach derived values once.
    for c in caches:
        for hour, rows in c["hours"].items():
            for r in rows:
                r["placebo"] = placebo(c["market_id"], r["date"], int(hour))
                if nbm is not None:
                    v, cyc = nbm_at_cutoff(nbm, c["market_id"], r["date"], int(hour), c["timezone"])
                    r["nbm_mean"], r["nbm_cycle"] = v, cyc
    pooled = {}
    if "PM" in arms:
        pooled = pooled_market_predictions(caches, base_features)
    for c in caches:
        market, support = c["market_id"], c["bucket_space"]
        ph = pooled_hour_predictions(c, base_features) if "PH" in arms else {}
        for hour in sorted(c["hours"], key=int):
            rows = c["hours"][hour]
            usable = [r for r in rows if r["forecast_high"] is not None]
            fits = {}
            for r in rows:
                if not r["scored"]:
                    continue
                if r["forecast_high"] is None:
                    stats["excluded_no_forecast"] += 1
                    continue
                train = [t for t in usable if t["year"] != r["year"]]
                floor = l3.floor_of({"high_so_far": r["high_so_far"]})
                lo, hi = l3.bucket_grid(support, floor)
                row = {"market_id": market, "centre": c["centre"], "hour": int(hour), "validation_date": r["date"],
                       "season": season_of(r["date"]), "actual": r["actual"], "floor": floor,
                       "nbm_cycle": r.get("nbm_cycle"), "nbm_missing": r.get("nbm_mean") is None}
                for arm in arms:
                    if arm in ("PH", "PM"):
                        mu, sd = (ph if arm == "PH" else pooled)[(market, c["centre"], int(hour), r["date"])]
                    else:
                        feats = arm_features(arm, base_features)
                        key = (arm, r["year"])
                        if key not in fits:
                            means = fold_means(train, feats)
                            x = design(train, feats, means)
                            y = [float(t["actual"]) for t in train]
                            beta, sd = l3.ols_fit(x, y)
                            fits[key] = (beta, sd, means)
                        beta, sd, means = fits[key]
                        mu = l3.ols_predict(beta, design([r], feats, means)[0])
                    probs = l3.discretised_normal(mu, sd, lo, hi, floor)
                    row[f"{arm}_log_loss"] = l3.log_loss(probs, r["actual"])
                    row[f"{arm}_brier"] = l3.brier(probs, r["actual"])
                if any(r.get(k) is None for k in ("dewpoint_c",)):
                    stats["dewpoint_missing"] += 1
                if r.get("nbm_mean") is None:
                    stats["nbm_missing"] += 1
                out.append(row)
    return out, dict(stats)


def _ols_with_dummies(x, dummies, y):
    import numpy as np

    levels = sorted(set(dummies))
    d = np.asarray([[1.0 if v == lv else 0.0 for lv in levels[1:]] for v in dummies]).reshape(len(dummies), -1)
    X = np.column_stack([np.ones(len(y)), x, d])
    beta, *_ = np.linalg.lstsq(X, np.asarray(y, float), rcond=None)
    return beta, levels


def _pred_dummies(beta, levels, x, level):
    import numpy as np

    d = np.asarray([1.0 if level == lv else 0.0 for lv in levels[1:]])
    return float(beta[0] + np.dot(beta[1:1 + len(x)], x) + np.dot(beta[1 + len(x):], d))


def _residual_sd(values):
    import numpy as np

    return float(np.std(values, ddof=1)) if len(values) > 1 else float("nan")


def pooled_hour_predictions(cache, features):
    """PH: per (market, centre, fold) one fit over hours 07-20 with hour fixed effects."""
    import numpy as np

    out = {}
    all_rows = [(int(h), r) for h, rows in cache["hours"].items() for r in rows if r["forecast_high"] is not None]
    for year in sorted({r["year"] for _, r in all_rows}):
        train = [(h, r) for h, r in all_rows if r["year"] != year]
        means = fold_means([r for _, r in train], features)
        x = design([r for _, r in train], features, means)
        y = [float(r["actual"]) for _, r in train]
        beta, levels = _ols_with_dummies(x, [h for h, _ in train], y)
        resid = defaultdict(list)
        for (h, r), xi, yi in zip(train, x, y):
            resid[h].append(yi - _pred_dummies(beta, levels, xi, h))
        sds = {h: _residual_sd(v) for h, v in resid.items()}
        for h, r in all_rows:
            if r["year"] == year:
                xi = design([r], features, means)[0]
                out[(cache["market_id"], cache["centre"], h, r["date"])] = (
                    _pred_dummies(beta, levels, xi, h), sds[h])
    return out


def pooled_market_predictions(caches, features):
    """PM: per (centre, hour, fold) one fit over all markets with market fixed effects."""
    out = {}
    by_ch = defaultdict(list)
    for c in caches:
        for h, rows in c["hours"].items():
            for r in rows:
                if r["forecast_high"] is not None:
                    by_ch[(c["centre"], int(h))].append((c["market_id"], r))
    for (centre, h), items in by_ch.items():
        for year in sorted({r["year"] for _, r in items}):
            train = [(m, r) for m, r in items if r["year"] != year]
            means = fold_means([r for _, r in train], features)
            x = design([r for _, r in train], features, means)
            y = [float(r["actual"]) for _, r in train]
            beta, levels = _ols_with_dummies(x, [m for m, _ in train], y)
            resid = defaultdict(list)
            for (m, r), xi, yi in zip(train, x, y):
                resid[m].append(yi - _pred_dummies(beta, levels, xi, m))
            sds = {m: _residual_sd(v) for m, v in resid.items()}
            for m, r in items:
                if r["year"] == year:
                    xi = design([r], features, means)[0]
                    out[(m, centre, h, r["date"])] = (_pred_dummies(beta, levels, xi, m), sds[m])
    return out


# ---------------------------------------------------------------- statistics

def date_weights(dates, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED):
    import numpy as np

    rng = np.random.default_rng(seed)
    n = len(dates)
    idx = rng.integers(0, n, size=(draws, n))
    w = np.zeros((draws, n))
    for k in range(draws):
        np.add.at(w[k], idx[k], 1.0)
    return w


def block_stat(rows, arm, ref, metric, hours, markets, season, dates, weights):
    """Point D, CI, SE for the equal-weight market mean of per-market mean deltas."""
    import numpy as np

    pos = {d: i for i, d in enumerate(dates)}
    S = np.zeros((len(markets), len(dates)))
    N = np.zeros((len(markets), len(dates)))
    mi = {m: i for i, m in enumerate(markets)}
    for r in rows:
        if r["market_id"] not in mi or r["hour"] not in hours or (season != "pooled" and r["season"] != season):
            continue
        j = pos[r["validation_date"]]
        S[mi[r["market_id"]], j] += r[f"{arm}_{metric}"] - r[f"{ref}_{metric}"]
        N[mi[r["market_id"]], j] += 1
    keep = N.sum(axis=1) > 0
    S, N = S[keep], N[keep]
    if not len(S):
        return None
    point = float(np.mean(S.sum(axis=1) / N.sum(axis=1)))
    num = weights @ S.T
    den = weights @ N.T
    with np.errstate(invalid="ignore", divide="ignore"):
        per = num / den
    boot = np.nanmean(per, axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    se = float(np.std(boot, ddof=1))
    return {"D": point, "lo": float(lo), "hi": float(hi), "se": se, "mde": MDE_FACTOR * se,
            "n_rows": int(N.sum()), "n_markets": int(keep.sum())}


def per_market(rows, arm, ref, metric, hours, dates, weights):
    return {m: block_stat(rows, arm, ref, metric, hours, (m,), "pooled", dates, weights)
            for m in ALL_MARKETS}


def evaluate(rows, arm, ref):
    dates = sorted({r["validation_date"] for r in rows})
    w = date_weights(dates)
    res = {"arm": arm, "ref": ref, "blocks": {}, "hours": {}, "per_market_07_12": {}}
    for mset_name, mset in (("11", ALL_MARKETS), ("5", PRIMARY_MARKETS)):
        for season in ("pooled", "aug-sep", "oct-dec"):
            for bname, hours in BLOCKS.items():
                res["blocks"][f"log_loss|{mset_name}|{season}|{bname}"] = block_stat(
                    rows, arm, ref, "log_loss", hours, mset, season, dates, w)
                res["blocks"][f"brier|{mset_name}|{season}|{bname}"] = block_stat(
                    rows, arm, ref, "brier", hours, mset, season, dates, w)
            for h in HOURS:
                res["hours"][f"log_loss|{mset_name}|{season}|{h:02d}"] = block_stat(
                    rows, arm, ref, "log_loss", (h,), mset, season, dates, w)
    res["per_market_07_12"] = per_market(rows, arm, ref, "log_loss", BLOCKS["07-12"], dates, w)
    primary = res["blocks"]["log_loss|11|pooled|07-12"]
    guard_keys = [f"log_loss|{m}|{s}|{b}" for m in ("11", "5") for s in ("pooled", "aug-sep", "oct-dec")
                  for b in BLOCKS] + ["brier|11|pooled|07-12"]
    worse = [k for k in guard_keys if res["blocks"].get(k) and res["blocks"][k]["lo"] > 0]
    res["primary"] = primary
    res["ci_worse_blocks"] = worse
    res["keep"] = bool(primary and primary["D"] < 0 and primary["hi"] < 0 and not worse)
    return res


# ---------------------------------------------------------------- commands

def load_caches(cache_dir, markets, centres):
    caches = []
    for m in markets:
        for c in centres:
            p = Path(cache_dir) / f"cache_{m}_{c}.json"
            if not p.exists():
                raise LadderError(f"missing cache {p}")
            caches.append(json.loads(p.read_text(encoding="utf-8")))
    return caches


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _score_command(args):
    markets = args.markets.split(",")
    centres = args.centres.split(",") if args.centres else [c for s in CENTRES.values() for c in s]
    caches = load_caches(args.cache_dir, markets, centres)
    nbm = load_nbm(args.nbm_corpus) if args.nbm_corpus else None
    arms = ["BASE"] + [a for a in args.arms.split(",") if a and a != "BASE"]
    base = tuple(args.base_features.split(","))
    rows, stats = score_rows(caches, nbm, arms, base)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "ladder_rows.jsonl").open("w", encoding="utf-8") as sink:
        for r in rows:
            sink.write(json.dumps(r, sort_keys=True) + "\n")
    summary = {"record": "l9_ladder_summary", "rule_sha256": _sha(args.rule) if args.rule else None,
               "base_features": base, "arms": arms, "markets": markets, "centres": centres,
               "nbm_corpus": args.nbm_corpus and _sha(args.nbm_corpus), "stats": stats,
               "n_rows": len(rows), "results": {}}
    for arm in arms[1:]:
        summary["results"][arm] = evaluate(rows, arm, "BASE")
    nbm_cycles = defaultdict(int)
    for r in rows:
        nbm_cycles[str(r.get("nbm_cycle"))] += 1
    summary["nbm_cycles"] = dict(nbm_cycles)
    (out / "ladder_summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True), encoding="utf-8")
    for arm, res in summary["results"].items():
        p = res["primary"]
        print(f"{arm}: D07-12={p['D']:+.4f} [{p['lo']:+.4f},{p['hi']:+.4f}] mde={p['mde']:.4f} "
              f"keep={res['keep']} worse={res['ci_worse_blocks']}")
    return 0


def _control_command(args):
    """BASE per-row log loss vs L3's ols_floor_log_loss within 1e-9, identical row sets."""
    out = {}
    ok_all = True
    for market in args.markets.split(","):
        cache = load_caches(args.cache_dir, [market], [args.centre])
        rows, _ = score_rows(cache, None, ["BASE"], BASE_FEATURES)
        mine = {(r["hour"], r["validation_date"]): r for r in rows}
        theirs = {}
        for line in (Path(args.l3_dir) / f"challenger_rows_{market}.jsonl").read_text().splitlines():
            t = json.loads(line)
            theirs[(int(t["hour"]), t["validation_date"])] = t
        keys_equal = set(mine) == set(theirs)
        common = set(mine) & set(theirs)
        diffs = [abs(mine[k]["BASE_log_loss"] - theirs[k]["ols_floor_log_loss"]) for k in common]
        bdiffs = [abs(mine[k]["BASE_brier"] - theirs[k]["ols_floor_brier"]) for k in common]
        ok = keys_equal and diffs and max(diffs) <= 1e-9
        ok_all &= bool(ok)
        out[market] = {"rows_mine": len(mine), "rows_l3": len(theirs), "row_sets_equal": keys_equal,
                       "max_abs_log_loss_diff": max(diffs) if diffs else None,
                       "max_abs_brier_diff": max(bdiffs) if bdiffs else None, "pass": bool(ok)}
        print(market, out[market], flush=True)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"centre": args.centre, "l3_dir": args.l3_dir, "pass": ok_all,
                                          "markets": out}, indent=1), encoding="utf-8")
    print("PASS" if ok_all else "FAIL")
    return 0 if ok_all else 2


def build_parser():
    ap = argparse.ArgumentParser(prog="weather.calibration.ols_floor_ladder", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--markets", default=",".join(ALL_MARKETS))
    b.add_argument("--centres", default="")
    b.add_argument("--pit-forecast-corpus-manifest", action="append", required=True)
    b.add_argument("--out-dir", required=True)
    b.add_argument("--overwrite", action="store_true")
    n = sub.add_parser("nbm-corpus")
    n.add_argument("--blocks", action="append", required=True)
    n.add_argument("--out-dir", required=True)
    s = sub.add_parser("score")
    s.add_argument("--cache-dir", required=True)
    s.add_argument("--markets", default=",".join(ALL_MARKETS))
    s.add_argument("--centres", default="")
    s.add_argument("--nbm-corpus", default="")
    s.add_argument("--arms", required=True)
    s.add_argument("--base-features", default=",".join(BASE_FEATURES))
    s.add_argument("--rule", default="")
    s.add_argument("--out-dir", required=True)
    c = sub.add_parser("control")
    c.add_argument("--cache-dir", required=True)
    c.add_argument("--markets", default=",".join(ALL_MARKETS))
    c.add_argument("--centre", required=True)
    c.add_argument("--l3-dir", required=True)
    c.add_argument("--out", required=True)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    return {"build": _build_command, "nbm-corpus": _nbm_corpus_command, "score": _score_command,
            "control": _control_command}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
