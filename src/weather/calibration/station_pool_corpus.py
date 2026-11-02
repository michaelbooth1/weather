"""Lane L48: station-pooled training corpus for P3d_N_fix (offline research, rows 108 C / 109 K).

Frozen rule: ``docs/research/station-pooled-corpus-2026-11-01/rule_station_pool.md`` (sha256 in RULE_SHA256).
The model code is master's B-bound ``pooled_residual_model`` (imported read-only, never edited): every arm calls
``fit_pooled(train, market_id=False, doy=True, raw_columns=False)``, ``MeanModel.predict`` and
``predictive_distribution``, which is P3d_N_fix's form. Only the training rows change.

Subcommands (heavy; run only through ``scripts/ops/workstation_heavy.ps1 -Kind weather_heavy -Queue``):

  build  -- pool NBM corpus (canonical parser v2, IEM zone injected in-process), venue-rule labels, cutoff
            features, controls C-a, C-c, C-d and D-x (pool side), coverage; publishes corpora/<sha256>/.
  precheck -- before the corpus exists: C-b and the base arm's C-0 on hour 07.
  loyo   -- arms P3d_N_11m (R-A's rows), P3d_N_pool (+300, gating) and P3d_N_pool100 (+100, descriptive);
            controls C-0 and C-b; the frozen kill gate (rule section 7). No dev data is read.

Outputs always land outside the repository. Nothing dated after 2026-09-29 is read.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

RULE_SHA256 = "33d5c67ab499e7efde18b7a9f08cd970134df7d0416853925335eea0b1210938"
L9_CORPUS_SHA256 = "1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd"
YEARS = (2021, 2022, 2023, 2024, 2025)
HOURS = (7, 8, 9, 10, 11, 12)
LAST_ALLOWED = date(2026, 9, 29)
LABEL_GAP_MINUTES = 180
KILL_POINT = -0.0005
SPEC_TEMPLATE = "atlanta"  # a built-in US F market; only id, icao and timezone are replaced
ARMS = ("P3d_N_11m", "P3d_N_pool", "P3d_N_pool100")


class StationPoolError(RuntimeError):
    pass


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def season_dates(years=YEARS):
    out = []
    for year in years:
        day = date(year, 8, 1)
        while day <= date(year, 9, 29):
            if day > LAST_ALLOWED:
                raise StationPoolError(f"date after {LAST_ALLOWED}")
            out.append(day)
            day += timedelta(days=1)
    return out


def _read_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


# ------------------------------------------------------------------ station specs and reports

def station_candidate(icao, tz_name, spec=None):
    """Duck-typed candidate for ``new_city_corpus``: a built-in US F spec with this station's id, ICAO and zone."""
    from weather.market.market_registry import spec_for_id

    if spec is None:
        spec = replace(spec_for_id(SPEC_TEMPLATE), id=icao.lower(), icao=icao, timezone=tz_name)
    return SimpleNamespace(
        spec=spec, iem_special_schedule_minute=None, print_cutoff=None,
        label_source=SimpleNamespace(name="metar_venue_rule_l48", complete_day_max_gap_minutes=LABEL_GAP_MINUTES))


def station_files(raw_root, icao):
    base = Path(raw_root) / icao.lower()
    routine = [base / "routine" / f"{y}.csv" for y in YEARS if (base / "routine" / f"{y}.csv").exists()]
    special = [base / "special" / f"{y}.csv" for y in YEARS if (base / "special" / f"{y}.csv").exists()]
    return routine, special


def station_labels(raw_root, candidate):
    """{local date: label row} under the venue rule; only Aug 01..Sep 29 dates are kept."""
    from weather.calibration import new_city_corpus as ncc

    routine, special = station_files(raw_root, candidate.spec.icao)
    records, counts = ncc.venue_routine_records(routine, special, candidate, last_date="2025-09-29")
    labels = ncc.daily_labels(records, candidate, last_date="2025-09-29")
    keep = {d.isoformat() for d in season_dates()}
    return {k: v for k, v in labels.items() if k in keep}, counts


def station_all_reports(raw_root, candidate):
    """Every report (routine and special) after ``select_reports`` corrections, with its venue value in F."""
    from weather.backtesting import venue_rule_labels as venue

    routine, special = station_files(raw_root, candidate.spec.icao)
    spec = candidate.spec
    reports = []
    for paths, declared in ((routine, 3), (special, 4)):
        for path in paths:
            text = Path(path).read_text(encoding="utf-8")
            reports.extend(venue.reports_from_csv(text, spec, spec.icao, declared_report_type=declared))
    reports.sort(key=lambda r: r["valid_time_utc"])
    selected, _ = venue.select_reports(reports)
    by_date = defaultdict(list)
    for r in selected:
        if r["temperature_c"] is None:
            continue
        by_date[r["local_date"]].append((r["valid_time_utc"], venue.native_value(r["temperature_c"], "F")))
    for rows in by_date.values():
        rows.sort()
    return by_date


def cutoff_features(by_date, day, hour, tz):
    """(F, x_current_temp) in WU whole F at the local cutoff, or (None, None) with no report before it."""
    from weather.calibration.new_city_corpus import cutoff_instant_utc
    from weather.calibration.pooled_residual_model import wu_whole_f

    instant = cutoff_instant_utc(day, hour, tz)
    admitted = [v for t, v in by_date.get(day, []) if t <= instant]
    if not admitted:
        return None, None
    return wu_whole_f(max(admitted), "half_up"), wu_whole_f(admitted[-1], "half_up")


# ------------------------------------------------------------------ NBM

def nbm_pool_rows(blocks_path, stations):
    """L9-format NBM rows (``ols_floor_ladder._nbm_corpus_command``) for ``stations`` {icao: tz}; market_id = ICAO."""
    from weather.sources import nbm_probabilistic_tmax as npt

    for icao, tz in stations.items():
        npt.NBM_NBP_STATION_TIMEZONES.setdefault(icao, tz)  # in-process injection; the module file is unchanged
    rows = []
    for rec in _read_jsonl(blocks_path):
        day = date.fromisoformat(rec["utc_date"])
        if day > LAST_ALLOWED:
            raise StationPoolError(f"NBM block after {LAST_ALLOWED}: {day}")
        obj = rec.get("object")
        for icao in sorted(stations):
            base = {"market_id": icao, "station_id": icao, "target_date": day.isoformat(), "cycle": rec["cycle"],
                    "key": rec["key"], "last_modified": obj and obj["last_modified"], "etag": obj and obj["etag"]}
            block = (rec.get("stations") or {}).get(icao)
            if not obj or not block:
                rows.append({**base, "available": False, "reason": "object_missing" if not obj else "station_missing"})
                continue
            p = npt.parse_nbp_station_tmax(block["block"], icao, day)
            rows.append({**base, "available": bool(p["available"]), "reason": p.get("reason"),
                         "issued_at": p.get("issued_at"), "valid_time_utc": p.get("valid_time_utc"),
                         "mean": p.get("mean_native"), "sd": p.get("stddev_native"),
                         "parser_version": p.get("parser_version"), "product_version": p.get("product_version"),
                         "block_sha256": hashlib.sha256(block["block"].encode()).hexdigest()})
    rows.sort(key=lambda r: (r["market_id"], r["target_date"], r["cycle"]))
    return rows


def control_cd_blocks(blocks_path, l9_corpus):
    """C-d gating: every extracted market block's sha256 equals L9's block_sha256 for the same (market, date)."""
    from weather.calibration.ols_floor_ladder import NBM_STATIONS

    l9 = {}
    for r in _read_jsonl(l9_corpus):
        if r.get("cycle") == "07" and r.get("block_sha256"):
            l9[(r["station_id"], r["target_date"])] = r["block_sha256"]
    compared = mismatched = mine_only = l9_only = 0
    examples = []
    seen = set()
    for rec in _read_jsonl(blocks_path):
        for station in NBM_STATIONS.values():
            block = (rec.get("stations") or {}).get(station)
            key = (station, rec["utc_date"])
            seen.add(key)
            ref = l9.get(key)
            if block and ref:
                compared += 1
                if hashlib.sha256(block["block"].encode()).hexdigest() != ref:
                    mismatched += 1
                    examples.append(list(key))
            elif block:
                mine_only += 1
            elif ref:
                l9_only += 1
    return {"compared": compared, "mismatched": mismatched, "examples": examples[:20], "mine_only": mine_only,
            "l9_only": l9_only, "pass": compared > 0 and mismatched == 0}


# ------------------------------------------------------------------ base frame (R-A's rows)

def base_frame(records_root, l9_corpus):
    """R-A's training frame: dev_training_frame + attach_training_nbm (L9 PIT corpus), hours 07..12."""
    from weather.calibration import ols_floor_ladder as l9
    from weather.calibration import pooled_residual_model as prm
    from weather.market.market_registry import spec_for_id

    if _sha256_file(l9_corpus) != L9_CORPUS_SHA256:
        raise StationPoolError("L9 NBM corpus sha256 differs from the frozen rule")
    timezones = {m: spec_for_id(m).timezone for m in prm.R0_MARKETS}
    frame, buckets = prm.dev_training_frame(records_root, prm.R0_MARKETS)
    if frame["year"].max() >= 2026:
        raise StationPoolError("a base training row is from 2026")
    records_frame = frame
    frame, stats = prm.attach_training_nbm(frame, l9.load_nbm(l9_corpus), l9.nbm_at_cutoff, timezones)
    frame = frame[frame["hour"].isin(HOURS)].reset_index(drop=True)
    records_frame = records_frame[records_frame["hour"].isin(HOURS)].reset_index(drop=True)
    return frame, buckets, stats, records_frame


# ------------------------------------------------------------------ build

def _describe(values):
    import numpy as np

    v = np.asarray([x for x in values if x is not None and math.isfinite(x)], dtype=float)
    if not len(v):
        return {"n": 0}
    return {"n": int(len(v)), "mean": float(v.mean()), "sd": float(v.std(ddof=1)) if len(v) > 1 else 0.0,
            "p10": float(np.percentile(v, 10)), "p50": float(np.percentile(v, 50)), "p90": float(np.percentile(v, 90))}


def build(*, corpus_root, stations_meta, records_root, l9_corpus, out_root):
    import pandas as pd

    from weather.calibration import ols_floor_ladder as l9
    from weather.calibration import pooled_residual_model as prm
    from weather.market.market_registry import spec_for_id

    out_root = prm.require_output_outside_repo(out_root)
    corpus_root = Path(corpus_root)
    raw_root = corpus_root / "raw" / "iem"
    station_set = json.loads((corpus_root / "station_set.json").read_text(encoding="utf-8"))
    pool = list(station_set["survivors"])
    dose = list(station_set["dose_subset"])
    meta = json.loads(Path(stations_meta).read_text(encoding="utf-8"))
    blocks_path = corpus_root / "nbp_station_blocks_pool.jsonl"
    report = {"rule_sha256": RULE_SHA256, "n_pool": len(pool), "n_dose": len(dose)}

    # C-d gating first: a mismatch refuses the build.
    report["C_d_gating"] = control_cd_blocks(blocks_path, l9_corpus)
    if not report["C_d_gating"]["pass"]:
        raise StationPoolError(f"C-d refused: {report['C_d_gating']}")

    tz = {icao: meta[icao]["tz"] for icao in pool}
    nbm_rows = nbm_pool_rows(blocks_path, tz)
    nbm_body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in nbm_rows).encode("utf-8")
    nbm_tmp = out_root / "_nbm_pool_rows.jsonl"
    out_root.mkdir(parents=True, exist_ok=True)
    nbm_tmp.write_bytes(nbm_body)
    table = l9.load_nbm(nbm_tmp)
    version_of = {(r["market_id"], r["target_date"]): r.get("product_version") for r in nbm_rows}
    parse = defaultdict(lambda: {"blocks": 0, "available": 0})
    for r in nbm_rows:
        if r.get("reason") in ("object_missing", "station_missing"):
            continue
        k = f"{r['target_date'][:4]}|{r.get('product_version')}"
        parse[k]["blocks"] += 1
        parse[k]["available"] += bool(r["available"])

    rows = []
    per_station = {}
    drops = defaultdict(lambda: defaultdict(int))
    for icao in pool:
        cand = station_candidate(icao, meta[icao]["tz"])
        labels, label_counts = station_labels(raw_root, cand)
        reports = station_all_reports(raw_root, cand)
        zone = cand.spec.tz
        lat, lon, elev = float(meta[icao]["lat"]), float(meta[icao]["lon"]), float(meta[icao]["elev_m"])
        n_rows = 0
        for day in season_dates():
            key = day.isoformat()
            label = labels.get(key)
            if not label or not label["label_complete"]:
                drops[str(day.year)]["label_incomplete_days"] += 1
                continue
            centre = prm.nearest_centre(key)
            doy = day.timetuple().tm_yday
            for hour in HOURS:
                F, cur = cutoff_features(reports, key, hour, zone)
                if F is None:
                    drops[str(day.year)]["no_report_before_cutoff"] += 1
                    continue
                fh, cycle = l9.nbm_at_cutoff(table, icao, key, hour, meta[icao]["tz"])
                if fh is None:
                    drops[str(day.year)]["no_nbm"] += 1
                    continue
                rows.append({"market": icao, "centre": centre, "season": prm.season_of(centre), "hour": hour,
                             "target_date": key, "year": day.year, "y": float(label["label_native"]),
                             "F": float(F), "fh": float(fh), "lat": lat, "lon": lon, "elev": elev,
                             "doy_sin": math.sin(2 * math.pi * doy / 365.25),
                             "doy_cos": math.cos(2 * math.pi * doy / 365.25),
                             "x_high_so_far": float(F), "x_current_temp": float(cur),
                             "nbm_product_version": version_of.get((icao, key))})
                n_rows += 1
        per_station[icao] = {"rows": n_rows, "label_counts": label_counts,
                             "complete_days": sum(1 for v in labels.values() if v["label_complete"])}
        print(f"built {icao} rows={n_rows}", flush=True)

    body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode("utf-8")
    gz = gzip.compress(body, mtime=0)
    corpus_sha = hashlib.sha256(gz).hexdigest()
    final = out_root / corpus_sha
    if final.exists():
        raise StationPoolError(f"corpus {corpus_sha} already published")
    final.mkdir(parents=True)
    (final / "rows.jsonl.gz").write_bytes(gz)
    nbm_tmp.replace(final / "nbm_pool_rows.jsonl")

    pool_df = pd.DataFrame(rows)
    base, _, base_stats, records_frame = base_frame(records_root, l9_corpus)
    report["coverage"] = _coverage(pool_df, base, dose)
    report["drops"] = {k: dict(v) for k, v in drops.items()}
    report["C_d_descriptive"] = _cd_descriptive(pool_df, base, parse, l9_corpus)
    report["C_a"], report["C_c"] = _control_metar_vs_wu(raw_root, records_frame)
    report["D_x_pool_bias"] = _dx_pool_bias(pool_df)
    report["base_train_nbm"] = base_stats
    manifest = {
        "record": "l48_station_pool_corpus", "corpus_sha256": corpus_sha, "rule_sha256": RULE_SHA256,
        "rows": len(rows), "stations": pool, "dose_subset": dose,
        "inputs": {"station_set.json": _sha256_file(corpus_root / "station_set.json"),
                   "filter_log.jsonl": _sha256_file(corpus_root / "filter_log.jsonl"),
                   "nbp_station_blocks_pool.jsonl": _sha256_file(blocks_path),
                   "stations_meta": _sha256_file(stations_meta), "l9_corpus": L9_CORPUS_SHA256,
                   "receipts_iem.jsonl": _sha256_file(corpus_root / "receipts_iem.jsonl"),
                   "module_sha256": _sha256_file(__file__)},
        "files": {"rows.jsonl.gz": corpus_sha, "nbm_pool_rows.jsonl": _sha256_file(final / "nbm_pool_rows.jsonl")},
        "per_station": per_station,
    }
    (final / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    (final / "build_report.json").write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({"corpus_sha256": corpus_sha, "rows": len(rows), "coverage": report["coverage"]["totals"]}))
    return final


def _coverage(pool_df, base, dose):
    out = {"by_year_hour": {}}
    for (year, hour), part in pool_df.groupby(["year", "hour"]):
        out["by_year_hour"][f"{year}|h{hour:02d}"] = {
            "pool_rows": int(len(part)), "base_rows": int(((base["year"] == year) & (base["hour"] == hour)).sum())}
    d = pool_df[pool_df["market"].isin(dose)]
    out["totals"] = {"pool_stations": int(pool_df["market"].nunique()),
                     "pool_station_days": int(pool_df[["market", "target_date"]].drop_duplicates().shape[0]),
                     "pool_rows": int(len(pool_df)), "pool100_rows": int(len(d)), "base_rows": int(len(base)),
                     "pool_to_base_ratio": float(len(pool_df) / len(base)),
                     "pool100_to_base_ratio": float(len(d) / len(base))}
    return out


def _cd_descriptive(pool_df, base, parse, l9_corpus):
    out = {"pool_parse_by_year_version": {k: {**v, "rate": v["available"] / v["blocks"] if v["blocks"] else None}
                                          for k, v in sorted(parse.items())}}
    h7 = pool_df[pool_df["hour"] == 7]
    out["pool_y_minus_fh_h07_by_year"] = {str(y): _describe((p["y"] - p["fh"]).tolist())
                                          for y, p in h7.groupby("year")}
    out["pool_y_minus_fh_h07_by_version"] = {str(v): _describe((p["y"] - p["fh"]).tolist())
                                             for v, p in h7.groupby(h7["nbm_product_version"].fillna("none"))}
    b7 = base[base["hour"] == 7]
    out["markets_y_minus_fh_h07_by_year"] = {str(y): _describe((p["y"] - p["fh"]).tolist())
                                             for y, p in b7.groupby("year")}
    return out


def _control_metar_vs_wu(raw_root, records_frame):
    """C-a: METAR-path F vs records F on the 11; C-c: METAR venue label vs WU label (R-A's y)."""
    from weather.calibration import pooled_residual_model as prm
    from weather.market.market_registry import spec_for_id

    ca = defaultdict(list)
    cc = []
    for market in prm.R0_MARKETS:
        spec = spec_for_id(market)
        cand = station_candidate(spec.icao, spec.timezone, spec=spec)
        labels, _ = station_labels(raw_root, cand)
        reports = station_all_reports(raw_root, cand)
        part = records_frame[records_frame["market"] == market]
        for day, grp in part.groupby("target_date"):
            label = labels.get(str(day)[:10])
            if label and label["label_complete"]:
                cc.append(float(label["label_native"]) - float(grp["y"].iloc[0]))
            for hour, F_wu in zip(grp["hour"], grp["F"]):
                F_m, _ = cutoff_features(reports, str(day)[:10], int(hour), spec.tz)
                if F_m is not None and F_wu == F_wu:
                    ca[int(hour)].append(F_m - float(F_wu))
    c_a = {}
    for hour, diffs in sorted(ca.items()):
        c_a[f"h{hour:02d}"] = {**_describe(diffs), "exact_match_share": sum(d == 0 for d in diffs) / len(diffs)}
    c_c = {**_describe(cc), "agreement_share": (sum(d == 0 for d in cc) / len(cc)) if cc else None}
    return c_a, c_c


def _dx_pool_bias(pool_df):
    h7 = pool_df[pool_df["hour"] == 7]
    bias = (h7["y"] - h7["fh"]).groupby(h7["market"]).mean()
    return {"per_station_mean_y_minus_fh_h07": _describe(bias.tolist()),
            "share_beyond_1F": float((bias.abs() > 1.0).mean()) if len(bias) else None,
            "n_stations": int(len(bias))}


# ------------------------------------------------------------------ LOYO

def load_pool_frame(corpus_dir):
    import pandas as pd

    corpus_dir = Path(corpus_dir)
    manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    gz = (corpus_dir / "rows.jsonl.gz").read_bytes()
    if hashlib.sha256(gz).hexdigest() != manifest["corpus_sha256"] or corpus_dir.name != manifest["corpus_sha256"]:
        raise StationPoolError("corpus sha256 mismatch")
    if manifest["rule_sha256"] != RULE_SHA256:
        raise StationPoolError("corpus built under another rule")
    rows = [json.loads(line) for line in gzip.decompress(gz).decode("utf-8").splitlines() if line.strip()]
    frame = pd.DataFrame(rows).drop(columns=["nbm_product_version"])
    if frame["year"].max() >= 2026:
        raise StationPoolError("a pool row is from 2026")
    return frame, manifest


def _score_arm(train, val, buckets):
    """P3d_N_fix fit on ``train``; {(market, date): (brier, log, yhat)} for the 11 markets' ``val`` rows."""
    import numpy as np

    from weather.calibration import feature_model as fm
    from weather.calibration import pooled_residual_model as prm

    fitted = prm.fit_pooled(train, market_id=False, doy=True, raw_columns=False)
    out = {}
    for market in sorted(val["market"].unique()):
        part = val[val["market"] == market].reset_index(drop=True)
        yhat, X = fitted["mean"].predict(part)
        gap = np.nan_to_num(yhat - part["F"].to_numpy(float), nan=0.0)
        s = np.maximum(prm.MIN_SCALE, fitted["scale"].predict(np.column_stack([X, gap])) * math.sqrt(math.pi / 2))
        train_y = [int(v) for v in train.loc[train["market"] == market, "y"]]
        p_clim = fm.smoothed_dist(train_y, buckets[market], alpha=0.10)
        for i in range(len(part)):
            dist = prm.predictive_distribution(float(yhat[i]), float(s[i]), float(part["F"].iat[i]), fitted["z"],
                                               buckets[market], p_clim)
            actual = int(part.at[i, "y"])
            out[(market, str(part.at[i, "target_date"])[:10])] = (
                fm.brier_score(dist, actual), fm.log_loss(dist, actual), float(yhat[i]), float(actual))
    return out


def loyo_rows(base, pools, buckets, hours=HOURS, years=None, arms=ARMS):
    """Blocked LOYO per hour; ``pools`` maps arm -> pool frame (None for the base arm). Base rows identical."""
    import pandas as pd

    rows = []
    for hour in hours:
        at_hour = base[base["hour"] == hour]
        for year in sorted(at_hour["year"].unique()) if years is None else years:
            val = at_hour[at_hour["year"] == year].reset_index(drop=True)
            base_train = at_hour[at_hour["year"] != year]
            scored = {}
            for arm in arms:
                pool = pools.get(arm)
                if pool is None:
                    train = base_train.reset_index(drop=True)
                else:
                    extra = pool[(pool["hour"] == hour) & (pool["year"] != year)]
                    train = pd.concat([base_train, extra[base_train.columns.intersection(extra.columns)]],
                                      ignore_index=True)
                scored[arm] = _score_arm(train, val, buckets)
                print(f"loyo h{hour:02d} held {year} {arm} train={len(train)}", flush=True)
            for key in scored[arms[0]]:
                row = {"hour": int(hour), "year": int(year), "market": key[0], "date": key[1],
                       "y": scored[arms[0]][key][3]}
                for arm in arms:
                    b, lg, yh, _ = scored[arm][key]
                    row.update({f"{arm}_brier": b, f"{arm}_log": lg, f"{arm}_yhat": yh})
                rows.append(row)
    return rows


def _date_sums(rows, a, b, metric):
    by_date = defaultdict(lambda: [0.0, 0])
    for r in rows:
        acc = by_date[r["date"]]
        acc[0] += r[f"{a}_{metric}"] - r[f"{b}_{metric}"]
        acc[1] += 1
    dates = sorted(by_date)
    import numpy as np

    return dates, np.array([by_date[d][0] for d in dates]), np.array([by_date[d][1] for d in dates], dtype=float)


def clustered_ci(rows, a, b, metric="brier", draws=2000, seed=20261024):
    import numpy as np

    dates, sums, counts = _date_sums(rows, a, b, metric)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(dates), size=(draws, len(dates)))
    boot = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    return float(sums.sum() / counts.sum()), [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]


def block3_ci(rows, a, b, metric="brier", draws=2000, seed=20261024, block=3):
    """Moving blocks of 3 consecutive target dates within a year, resampled to the same date count."""
    import numpy as np

    dates, sums, counts = _date_sums(rows, a, b, metric)
    pos = {d: i for i, d in enumerate(dates)}
    starts = []
    for year in sorted({d[:4] for d in dates}):
        ys = [d for d in dates if d[:4] == year]
        for i in range(len(ys) - block + 1):
            day0 = date.fromisoformat(ys[i])
            if all(date.fromisoformat(ys[i + k]) == day0 + timedelta(days=k) for k in range(block)):
                starts.append([pos[ys[i + k]] for k in range(block)])
    blocks = np.array(starts)
    bsum, bcnt = sums[blocks].sum(axis=1), counts[blocks].sum(axis=1)
    n_blocks = int(math.ceil(len(dates) / block))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(blocks), size=(draws, n_blocks))
    boot = bsum[idx].sum(axis=1) / bcnt[idx].sum(axis=1)
    return [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))], {"blocks": int(len(blocks)),
                                                                                "blocks_per_draw": n_blocks}


def gate(rows, cand="P3d_N_pool", base_arm="P3d_N_11m"):
    """Rule section 7 kill gate plus the reported tables."""
    point, ci = clustered_ci(rows, cand, base_arm)
    b3, b3info = block3_ci(rows, cand, base_arm)
    upper = max(ci[1], b3[1])
    per_market = {}
    for market in sorted({r["market"] for r in rows}):
        p, c = clustered_ci([r for r in rows if r["market"] == market], cand, base_arm)
        per_market[market] = {"d": p, "ci95": c, "n": sum(1 for r in rows if r["market"] == market)}
    per_year = {}
    for year in sorted({r["year"] for r in rows}):
        rs = [r for r in rows if r["year"] == year]
        p, c = clustered_ci(rs, cand, base_arm)
        per_year[str(year)] = {"d": p, "ci95": c, "n": len(rs)}
    per_hour = {}
    for hour in sorted({r["hour"] for r in rows}):
        rs = [r for r in rows if r["hour"] == hour]
        p, c = clustered_ci(rs, cand, base_arm)
        per_hour[f"h{hour:02d}"] = {"d": p, "ci95": c, "n": len(rs)}
    log_point, log_ci = clustered_ci(rows, cand, base_arm, metric="log")
    kills = {
        "1_point_ge_-0.0005": point >= KILL_POINT,
        "2_wider_upper_ge_0": upper >= 0,
        "3_market_ci_worse": [m for m, v in per_market.items() if v["ci95"][0] > 0],
        "4_years_d_gt_0_more_than_1": sum(1 for v in per_year.values() if v["d"] > 0) > 1,
    }
    killed = kills["1_point_ge_-0.0005"] or kills["2_wider_upper_ge_0"] or bool(kills["3_market_ci_worse"]) \
        or kills["4_years_d_gt_0_more_than_1"]
    return {"candidate": cand, "base": base_arm, "d_brier": point, "ci95_clustered": ci, "ci95_block3": b3,
            "block3": b3info, "wider_upper": upper, "kills": kills, "verdict": "KILL" if killed else "PASS",
            "per_market": per_market, "per_year": per_year, "per_hour": per_hour,
            "log_loss": {"d": log_point, "ci95_clustered": log_ci},
            "base_brier_mean": sum(r[f"{base_arm}_brier"] for r in rows) / len(rows), "n": len(rows),
            "n_dates": len({r["date"] for r in rows})}


def control_c0(rows, ra_rows_path):
    ra = {(r["hour"], r["market"], r["date"]): r["P3d_N_fix_brier"] for r in _read_jsonl(ra_rows_path)}
    mine = {(r["hour"], r["market"], r["date"]): r["P3d_N_11m_brier"] for r in rows}
    same_keys = set(ra) == set(mine)
    worst = max((abs(mine[k] - ra[k]) for k in mine if k in ra), default=float("inf"))
    return {"ra_rows": len(ra), "rows": len(mine), "identical_keys": same_keys, "max_abs_diff": worst,
            "pass": same_keys and worst <= 1e-9, "ra_sha256": _sha256_file(ra_rows_path)}


def control_cb(base, buckets):
    """Zero-pool identity on (h07, held-out 2021): the pool path with an empty pool equals the base arm."""
    empty = base.iloc[0:0].copy()
    rows = loyo_rows(base, {"P3d_N_11m": None, "P3d_N_pool": empty}, buckets, hours=(7,), years=(2021,),
                     arms=("P3d_N_11m", "P3d_N_pool"))
    worst = max(abs(r["P3d_N_pool_brier"] - r["P3d_N_11m_brier"]) for r in rows)
    return {"rows": len(rows), "max_abs_diff": worst, "pass": worst == 0.0}


def dx_residuals(rows, arms=ARMS):
    out = {}
    for market in sorted({r["market"] for r in rows}):
        rs = [r for r in rows if r["market"] == market]
        res = {arm: sum(r["y"] - r[f"{arm}_yhat"] for r in rs) / len(rs) for arm in arms}
        res["pool_minus_11m"] = res["P3d_N_pool"] - res["P3d_N_11m"]
        out[market] = res
    return out


def loyo(*, corpus_dir, records_root, l9_corpus, ra_loyo_rows, out_dir):
    from weather.calibration import pooled_residual_model as prm

    out = prm.require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name in ("loyo_rows.jsonl", "loyo_report.json"):
        if (out / name).exists():
            raise StationPoolError(f"refusing to overwrite {out / name}")
    pool, manifest = load_pool_frame(corpus_dir)
    base, buckets, base_stats, _ = base_frame(records_root, l9_corpus)
    pool = pool[base.columns.intersection(pool.columns)]
    missing = [c for c in ("F", "fh", "y", "x_high_so_far", "x_current_temp", "centre", "season") if c not in pool]
    if missing:
        raise StationPoolError(f"pool frame lacks {missing}")
    report = {"rule_sha256": RULE_SHA256, "corpus_sha256": manifest["corpus_sha256"],
              "module_sha256": _sha256_file(__file__), "base_rows": int(len(base)), "base_train_nbm": base_stats}
    report["C_b"] = control_cb(base, buckets)
    if not report["C_b"]["pass"]:
        raise StationPoolError(f"C-b refused: {report['C_b']}")
    dose = set(manifest["dose_subset"])
    pools = {"P3d_N_11m": None, "P3d_N_pool": pool, "P3d_N_pool100": pool[pool["market"].isin(dose)]}
    report["pool_rows"] = {arm: int(len(p)) for arm, p in pools.items() if p is not None}
    rows = loyo_rows(base, pools, buckets)
    _write_jsonl(out / "loyo_rows.jsonl", rows)
    report["C_0"] = control_c0(rows, ra_loyo_rows)
    if report["C_0"]["pass"]:
        report["gate_pool"] = gate(rows, "P3d_N_pool")
        report["descriptive_pool100"] = gate(rows, "P3d_N_pool100")
        report["descriptive_pool100"]["verdict"] = "descriptive only (never gating)"
        report["D_x_residuals"] = dx_residuals(rows)
        report["verdict"] = report["gate_pool"]["verdict"]
    else:
        report["verdict"] = "REFUSED (C-0 failed)"
    report["loyo_rows_sha256"] = _sha256_file(out / "loyo_rows.jsonl")
    (out / "loyo_report.json").write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    summary = {"verdict": report["verdict"], "C_0": report["C_0"], "C_b": report["C_b"]}
    if "gate_pool" in report:
        g = report["gate_pool"]
        summary.update({k: g[k] for k in ("d_brier", "ci95_clustered", "ci95_block3", "kills")})
    print(json.dumps(summary, default=str))
    return report


def precheck(*, records_root, l9_corpus, ra_loyo_rows, out_dir, hour=7):
    """Before the corpus exists: C-b and the base arm's C-0 on one hour (all five held-out years)."""
    from weather.calibration import pooled_residual_model as prm

    out = prm.require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base, buckets, base_stats, _ = base_frame(records_root, l9_corpus)
    report = {"rule_sha256": RULE_SHA256, "module_sha256": _sha256_file(__file__), "hour": hour,
              "base_rows": int(len(base)), "base_train_nbm": base_stats, "C_b": control_cb(base, buckets)}
    rows = loyo_rows(base, {"P3d_N_11m": None}, buckets, hours=(hour,), arms=("P3d_N_11m",))
    ra = {(r["hour"], r["market"], r["date"]): r["P3d_N_fix_brier"] for r in _read_jsonl(ra_loyo_rows)
          if r["hour"] == hour}
    mine = {(r["hour"], r["market"], r["date"]): r["P3d_N_11m_brier"] for r in rows}
    worst = max((abs(mine[k] - ra[k]) for k in mine if k in ra), default=float("inf"))
    report["C_0_one_hour"] = {"ra_rows": len(ra), "rows": len(mine), "identical_keys": set(ra) == set(mine),
                              "max_abs_diff": worst, "pass": set(ra) == set(mine) and worst <= 1e-9}
    (out / "precheck_report.json").write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, default=str))
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--corpus-root", required=True)
    b.add_argument("--stations-meta", required=True)
    b.add_argument("--records-root", required=True)
    b.add_argument("--l9-corpus", required=True)
    b.add_argument("--out-root", required=True, help="corpora root; the corpus lands in <out-root>/<sha256>")
    lo = sub.add_parser("loyo")
    lo.add_argument("--corpus-dir", required=True)
    lo.add_argument("--records-root", required=True)
    lo.add_argument("--l9-corpus", required=True)
    lo.add_argument("--ra-loyo-rows", required=True)
    lo.add_argument("--out-dir", required=True)
    pc = sub.add_parser("precheck")
    pc.add_argument("--records-root", required=True)
    pc.add_argument("--l9-corpus", required=True)
    pc.add_argument("--ra-loyo-rows", required=True)
    pc.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "precheck":
        precheck(records_root=args.records_root, l9_corpus=args.l9_corpus, ra_loyo_rows=args.ra_loyo_rows,
                 out_dir=args.out_dir)
    elif args.cmd == "build":
        build(corpus_root=args.corpus_root, stations_meta=args.stations_meta, records_root=args.records_root,
              l9_corpus=args.l9_corpus, out_root=args.out_root)
    else:
        loyo(corpus_dir=args.corpus_dir, records_root=args.records_root, l9_corpus=args.l9_corpus,
             ra_loyo_rows=args.ra_loyo_rows, out_dir=args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
