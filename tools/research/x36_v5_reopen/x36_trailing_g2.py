"""Lane L47, K row 112, G2: freeze W and lam per hour from 2021-25, then the dev refutation 2026-08-15..09-29, 07-12.
Rule: docs/research/x36-v5-reopen-2026-11-01/rule_x36_trailing_final.md
(sha256 032c8dc3bf33fd7dc549a5a9e93ed04d86809678a087fc43766e272b99f077f2). Master's G2 rulings, 2026-11-01.

The G1 pieces (grid, b_recent, b_train, shift, pick, run-env binding, training frame) are imported read-only from
x36_trailing_g1.py, which is verified by sha256 first and never edited.

Subcommands, in order:
  freeze      heavy, via scripts\\ops\\workstation_heavy.ps1 -Queue. 2021-25 only. G1's inner-selection algorithm
              applied to all five years: for each year Y, fit on the other four years and predict Y's gate rows
              (Aug 15..Sep 29) with b_train from those four years; pool the five out-of-fold sets per hour; score
              every combo with the tabulated kernel, re-score the best 3 plus lam=0 exactly (table error <= 1e-6 per
              row), and pick with g1.pick (the rule's tie-break: the smaller lam, then the smaller W; ties within
              1e-12). One W and lam per hour. No other selection, no hand edits.
  dseries26   light, normal environment, only after the coordinator's go. d(m, u) = NBP 07Z mean - WU high for
              2026-07-31..09-28 only. Corpus lines outside that range are dropped on their target_date text before
              they are parsed. The sealed panel (<= 07-30) is never used.
  dev         heavy, via -Queue, only after the coordinator's go. Re-emits P3d_N_fix (BASE) and P3d_T over the v3
              layout's 07-12 snapshots with target dates 2026-08-15..09-29 (the R-A dev emit loop, read-only
              helpers). The positive control comes first: BASE must reproduce R-A's dev_P3d_N_fix.jsonl to 1e-9 on
              the same keys. Then the gate: dR = R(P3d_T) - R(P3d_N_fix), pool ALL, scope covered, group 07-12,
              date-clustered 95% interval (2000 draws, seed 20261024, as rule row 112). PASS only if the upper
              bound < 0. The dev MDE (80%) is disclosed.

Candidate in 2026: mu' = mu - lam_h * clip(b_recent(m, t; W_h) - b_train(m), +-3 F), where b_train(m) is the
2021-25 Aug 1..Sep 29 mean of d (all five years) and b_recent uses only 2026 labels dated 07-31 or later and strictly
before t. Rows with fewer than W_h prior dates get shift 0 and are counted. Width comes from the unshifted mu; the
floor is applied after the shift (both inside predictive_distribution).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
G1_SHA256 = "7b14c3191bd2651eae4ad72de5b304f3e11af11caf9bb8c9c847d2f56f7e0ecd"
RULE_SHA256 = "032c8dc3bf33fd7dc549a5a9e93ed04d86809678a087fc43766e272b99f077f2"
DEV_CORPUS_SHA256 = "85746b7a560116f632436b24f268938a0a4ec47bf6d748aacba6e0abef257727"
RA_DEV_FIX_SHA256 = "cd0034b9faec0b687e1184187feeaa39ab151c5f9f8d1c905d3a49a0e7089542"
DEV_FIRST = date(2026, 8, 15)
DEV_LAST = date(2026, 9, 29)
LABEL_FIRST = date(2026, 7, 31)
LABEL_LAST = date(2026, 9, 28)
HOURS = (7, 8, 9, 10, 11, 12)
TIE_TOL = 1e-12
DRAWS = 2000
SEED = 20261024
CONTROL_TOL = 1e-9
SCHEMA = "l47_x36_trailing_g2/1"
ARM = "P3d_T"
BASE = "P3d_N_fix"
_DATE_RE = re.compile(r'"target_date":\s*"(\d{4}-\d{2}-\d{2})')


class G2Error(RuntimeError):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_g1():
    path = HERE / "x36_trailing_g1.py"
    if sha256_file(path) != G1_SHA256:
        raise G2Error("x36_trailing_g1.py sha mismatch")
    import importlib.util

    spec = importlib.util.spec_from_file_location("x36_trailing_g1_for_g2", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ pure pieces (tested)

def dev_target_ok(day):
    d = date.fromisoformat(str(day)[:10])
    return DEV_FIRST <= d <= DEV_LAST


def label_date_ok(day):
    d = date.fromisoformat(str(day)[:10])
    return LABEL_FIRST <= d <= LABEL_LAST


def line_date(line):
    """The target_date text of a JSONL line, read before the line is parsed; None if absent."""
    m = _DATE_RE.search(line)
    return m.group(1) if m else None


def selection_record(approx, exact, combos, rows, err, pick):
    """Freeze-table entry for one hour; records every combo tied with the minimum."""
    chosen = pick(exact)
    best = min(exact.values())
    tied = [list(c) for c in combos if c in exact and exact[c] <= best + TIE_TOL]
    return {"W": chosen[0], "lam": chosen[1], "rows": rows, "approx": {f"{c[0]}|{c[1]}": approx[c] for c in combos},
            "exact": {f"{c[0]}|{c[1]}": exact[c] for c in combos if c in exact}, "tied_at_minimum": tied,
            "tie_break_applied": len(tied) > 1, "table_error_per_row": err}


def load_freeze(path, expected_sha, module_sha):
    if sha256_file(path) != expected_sha:
        raise G2Error("freeze table sha mismatch")
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if obj.get("schema") != SCHEMA + "/freeze" or obj.get("rule_sha256") != RULE_SHA256:
        raise G2Error("not a G2 freeze table for this rule")
    if obj.get("module_sha256") != module_sha:
        raise G2Error("freeze table was not written by this module")
    picks = {}
    for h in HOURS:
        e = obj["hours"][f"h{h:02d}"]
        picks[h] = (int(e["W"]), float(e["lam"]))
    return picks, obj


def terciles(values):
    """Tercile edges of ``values`` and the 0/1/2 class of each value (<= q1, <= q2, above)."""
    import numpy as np

    v = np.asarray(values, float)
    q1, q2 = (float(x) for x in np.quantile(v, [1 / 3, 2 / 3]))
    return (q1, q2), np.where(v <= q1, 0, np.where(v <= q2, 1, 2))


def mean_band_index(p, offsets, n, band_index):
    """Per snapshot: the probability-weighted mean band index (probabilities renormalised per snapshot)."""
    import numpy as np

    p = np.asarray(p, float)
    tot = np.add.reduceat(p, offsets)
    num = np.add.reduceat(p * np.asarray(band_index, float), offsets)
    return np.divide(num, tot, out=np.full(len(tot), np.nan), where=tot > 0)


def gate(upper):
    return {"rule": "PASS only if the dev dR 95% upper bound < 0", "upper": upper,
            "pass": bool(upper is not None and upper < 0),
            "verdict": "PASS (dev-selection result, not an edge)" if (upper is not None and upper < 0) else "KILL"}


# ------------------------------------------------------------------ freeze (heavy, 2021-25 only)

def run_freeze(g1, rung, prm, frame, buckets, series):
    import numpy as np
    from weather.calibration import feature_model as fm

    combos = g1.grid()
    recent = g1.recent_table(series, set(zip(frame["market"], (str(d)[:10] for d in frame["target_date"]))))
    zeros = np.zeros(len(frame))
    out = {}
    for hour in HOURS:
        mask = (frame["hour"] == hour).to_numpy()
        at_hour = frame[mask].reset_index(drop=True)
        x_hour = zeros[mask]
        years = sorted(int(y) for y in at_hour["year"].unique())
        if set(years) != set(g1.YEARS):
            raise G2Error(f"h{hour} years {years} are not 2021-25")
        rows = []
        for other in years:
            entry = rung._fit(at_hour, x_hour, frozenset({other}), "pooled")
            sel = (at_hour["year"] == other).to_numpy()
            tm = g1.b_train(series, set(years) - {other})
            for r in rung.predict_rows(entry, at_hour[sel].reset_index(drop=True), buckets, x_hour[sel], 0.0):
                if r["actual"] is None:
                    raise G2Error(f"row without an outcome: {r['market']} {r['date']} h{hour}")
                if g1.in_gate(r["date"]):
                    rows.append((r, {c: g1.shift(recent, tm, r["market"], r["date"], *c) for c in combos}))
        approx = {c: 0.0 for c in combos}
        for r, sh in rows:
            for c in combos:
                approx[c] += rung.fast_brier(r["yhat"] - sh[c], r["s"], r["F"], r["table"], r["p_clim"], r["actual"])
        order = sorted(combos, key=lambda c: (approx[c], combos.index(c)))[:g1.EXACT_TOP]
        exact = {}
        for c in sorted(set(order) | {(0, 0.0)}, key=combos.index):
            exact[c] = 0.0
            for r, sh in rows:
                dist = prm.predictive_distribution(r["yhat"] - sh[c], r["s"], r["F"], r["z"], r["buckets"],
                                                   r["p_clim"])
                exact[c] += fm.brier_score(dist, r["actual"])
        err = max(abs(exact[c] - approx[c]) / max(1, len(rows)) for c in exact)
        if err > g1.TABLE_TOL:
            raise G2Error(f"kernel table error {err} above {g1.TABLE_TOL} (h{hour})")
        out[f"h{hour:02d}"] = selection_record(approx, exact, combos, len(rows), err, g1.pick)
        print(f"freeze h{hour:02d}: W={out[f'h{hour:02d}']['W']} lam={out[f'h{hour:02d}']['lam']} rows={len(rows)}",
              flush=True)
    return out


def cmd_freeze(a):
    g1 = load_g1()
    prm, rung, env = g1.bind_run_env(a.run_env)
    out = prm.require_output_outside_repo(a.out)
    if out.exists():
        raise G2Error(f"refusing to overwrite {out}")
    series, sobj = g1.load_series(a.dseries)
    frame, buckets, finfo = g1.training_frame(prm, a.records, a.train_corpus)
    hours = run_freeze(g1, rung, prm, frame, buckets, series)
    res = {"schema": SCHEMA + "/freeze", "rule_sha256": RULE_SHA256, "module_sha256": sha256_file(__file__),
           "g1_module_sha256": G1_SHA256, "grid_tie_break_order": [list(c) for c in g1.grid()],
           "tie_break": "rule row 112: ties go to the smaller lam, then the smaller W (g1.pick, within 1e-12)",
           "selection": "G1 inner selection on all five years: per year Y, fit on the other four, predict Y's gate "
                        "rows, nested b_train from the four fit years; pooled per hour; tabulated kernel, best 3 "
                        "plus lam=0 exact",
           "inputs": {**env, **finfo, "dseries": str(a.dseries), "dseries_sha256": sha256_file(a.dseries),
                      "dseries_rows": sobj["n_rows"], "records": str(a.records),
                      "train_corpus_sha256": g1.TRAIN_CORPUS_SHA256},
           "b_train_2026": {"definition": "mean d over Aug 1..Sep 29 of all five years 2021-25, per market",
                            "values": g1.b_train(series, set(g1.YEARS))},
           "hours": hours}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({"out": str(out), "sha256": sha256_file(out),
                      "picks": {h: [v["W"], v["lam"]] for h, v in hours.items()}}), flush=True)
    return 0


# ------------------------------------------------------------------ dseries26 (light, normal environment, after go)

def cmd_dseries26(a):
    sys.path.insert(0, str(HERE))
    import x36_v5 as base

    out = Path(a.out)
    if out.exists():
        raise G2Error(f"refusing to overwrite {out}")
    if sha256_file(a.dev_corpus) != DEV_CORPUS_SHA256:
        raise G2Error("dev NBM corpus sha mismatch")
    corpus, dropped = [], 0
    for line in Path(a.dev_corpus).read_text(encoding="utf-8").splitlines():
        d = line_date(line)
        if d is None or not label_date_ok(d):
            dropped += 1
            continue
        r = json.loads(line)
        if r["target_date"] != d or r.get("cycle") != "07":
            raise G2Error(f"unexpected corpus row {d} cycle {r.get('cycle')}")
        corpus.append(r)
    labels = base.load_labels(a.repo, {2026}, lambda day: label_date_ok(day))
    for (_, d) in labels:
        if not label_date_ok(d):
            raise G2Error(f"label outside 07-31..09-28: {d}")
    ps = base.pairs(corpus, labels)
    rows = sorted(({"m": p["m"], "d": p["d"], "x": p["x"]} for p in ps), key=lambda r: (r["m"], r["d"]))
    if len({(r["m"], r["d"]) for r in rows}) != len(rows):
        raise G2Error("duplicate d row")
    per_market = defaultdict(int)
    for r in rows:
        per_market[r["m"]] += 1
    res = {"schema": SCHEMA + "/dseries26", "module_sha256": sha256_file(__file__),
           "base_module_sha256": sha256_file(base.__file__), "dev_corpus_sha256": DEV_CORPUS_SHA256,
           "window": [LABEL_FIRST.isoformat(), LABEL_LAST.isoformat()], "corpus_lines_dropped_by_date": dropped,
           "n_corpus_rows": len(corpus), "n_labels": len(labels), "n_rows": len(rows),
           "per_market": dict(per_market), "rows": rows}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, sort_keys=True), encoding="utf-8")
    print(json.dumps({"n_rows": len(rows), "per_market": dict(per_market), "dropped": dropped,
                      "sha256": sha256_file(out)}), flush=True)
    return 0


def load_d26(path):
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if obj.get("schema") != SCHEMA + "/dseries26":
        raise G2Error("not a G2 dseries26 file")
    series = defaultdict(list)
    for r in obj["rows"]:
        if not label_date_ok(r["d"]):
            raise G2Error(f"dseries26 row outside 07-31..09-28: {r['d']}")
        series[r["m"]].append((r["d"], float(r["x"])))
    return {m: sorted(v) for m, v in series.items()}, obj


# ------------------------------------------------------------------ dev (heavy, after go)

def _dists(prm, fm, entry, one, buckets, market, sh):
    """(BASE, candidate) distributions for one row: width from the unshifted mu, floor inside."""
    import numpy as np

    fitted = entry["fit"]
    yhat, X = fitted["mean"].predict(one)
    gap = np.nan_to_num(yhat - one["F"].to_numpy(float), nan=0.0)
    s = np.maximum(prm.MIN_SCALE, fitted["scale"].predict(np.column_stack([X, gap])) * math.sqrt(math.pi / 2))
    p_clim = fm.smoothed_dist(entry["train_y"][market], buckets[market], alpha=0.10)
    mu, sd, floor = float(yhat[0]), float(s[0]), float(one["F"].iat[0])
    base = prm.predictive_distribution(mu, sd, floor, fitted["z"], buckets[market], p_clim)
    cand = base if sh == 0.0 else prm.predictive_distribution(mu - sh, sd, floor, fitted["z"], buckets[market], p_clim)
    return base, cand


def emit_dev(g1, prm, layout, replay_root, frame, buckets, picks, recent, train_means, out):
    import pandas as pd
    from zoneinfo import ZoneInfo

    from weather.calibration import feature_model as fm
    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.calibration.r0_ols_floor_devfit import usable_v2_mean
    from weather.market.market_registry import spec_for_id
    from weather.model import observed_running_max

    running_max = prm._require_metar_only(observed_running_max.running_max_since_midnight)
    markets = prm.R0_MARKETS
    fits = prm.rung_fits(frame, HOURS, arms={BASE: False})
    coords = prm.station_coordinates(markets)
    snaps = pd.read_parquet(Path(layout) / "inputs_snapshots.parquet", columns=[
        "snapshot_id", "market", "target_date", "local_hour", "cutoff_hour", "v2_mean", "v2_stddev",
        "v2_available_at", "captured_at_utc"])
    days = pd.to_datetime(snaps.target_date).dt.date
    if (days > DEV_LAST).any():
        raise G2Error("layout holds a snapshot after 2026-09-29")
    snaps = snaps[(days >= DEV_FIRST).to_numpy()].reset_index(drop=True)
    snaps = snaps.assign(nbm_usable=usable_v2_mean(snaps))
    info, stats_all, checked = [], {}, False
    with open(out / f"dev_{BASE}.jsonl", "w", encoding="utf-8") as wb, \
            open(out / f"dev_{ARM}.jsonl", "w", encoding="utf-8") as wt:
        for market in markets:
            spec = spec_for_id(market)
            tz = ZoneInfo(spec.timezone)
            folders = {target: folder for slug, target, folder in l3._event_folders(replay_root)
                       if slug == market and DEV_FIRST <= target <= DEV_LAST}
            stats = defaultdict(int)
            lat, lon, elev = coords[market]
            rows = snaps[snaps.market == market].copy()
            rows["target"] = pd.to_datetime(rows.target_date).dt.date
            for target, group in rows.groupby("target"):
                if not dev_target_ok(target):
                    raise G2Error(f"dev row outside the window: {target}")
                folder = folders.get(target)
                eligible = []
                for row in group.itertuples(index=False):
                    try:
                        hour = int(str(row.cutoff_hour))
                    except ValueError:
                        hour = None
                    if hour not in HOURS:
                        stats["outside_cutoff_hours"] += 1
                    elif int(row.local_hour) < hour:
                        stats["local_hour_before_cutoff"] += 1
                    elif not math.isfinite(float(row.nbm_usable)):
                        stats["no_usable_nbm"] += 1
                    elif folder is None:
                        stats["no_replay_folder"] += 1
                    else:
                        eligible.append((row, hour))
                if not eligible:
                    continue
                with open(Path(folder) / "replay_inputs.jsonl", "rb") as handle:
                    index = prm.replay_index(handle, target, tz)
                    cache, parsed = {}, {}
                    for row, hour in eligible:
                        captured = pd.Timestamp(row.captured_at_utc)
                        captured = captured.tz_localize("UTC") if captured.tzinfo is None else captured
                        entry = prm.latest_at_or_before(index, captured.to_pydatetime())
                        if entry is None:
                            stats["no_replay_snapshot_at_or_before_capture"] += 1
                            continue
                        key = (entry[1], hour)
                        if key not in cache:
                            if entry[1] not in parsed:
                                handle.seek(entry[1])
                                try:
                                    parsed = {entry[1]: json.loads(handle.read(entry[2]))}
                                except json.JSONDecodeError:
                                    parsed = {entry[1]: None}
                            snap = parsed[entry[1]]
                            cache[key] = None if snap is None else prm.rung_inputs(
                                snap, target, tz, hour, spec.display_unit, entry[0], running_max,
                                l3.observations_at_cutoff)
                        rec = cache[key]
                        if rec is None:
                            stats["corrupt_replay_line"] += 1
                            continue
                        if rec["high_so_far"] is None or rec["current_temp"] is None:
                            stats["missing_metar_feature"] += 1
                            continue
                        doy = target.timetuple().tm_yday
                        one = pd.DataFrame([{
                            "market": market, "centre": prm.nearest_centre(target.isoformat()), "season": "aug_sep",
                            "hour": hour, "target_date": target.isoformat(), "year": target.year,
                            "y": float("nan"), "F": float(rec["high_so_far"]), "fh": float(row.nbm_usable),
                            "lat": lat, "lon": lon, "elev": elev, "doy_sin": math.sin(2 * math.pi * doy / 365.25),
                            "doy_cos": math.cos(2 * math.pi * doy / 365.25),
                            "x_high_so_far": float(rec["high_so_far"]), "x_current_temp": float(rec["current_temp"]),
                            "market_code": float(markets.index(market))}])
                        w, lam = picks[hour]
                        tkey = target.isoformat()
                        available = lam == 0.0 or recent[(market, tkey, w)] is not None
                        sh = g1.shift(recent, train_means, market, tkey, w, lam)
                        base, cand = _dists(prm, fm, fits[(BASE, hour)], one, buckets, market, sh)
                        if not checked:
                            ref = prm._dist_from_fit(fits[(BASE, hour)], one, buckets, market)[0]
                            if max(abs(base.get(k, 0.0) - ref.get(k, 0.0)) for k in set(base) | set(ref)) > 0.0:
                                raise G2Error("BASE distribution differs from prm._dist_from_fit")
                            checked = True
                        for wr, dist in ((wb, base), (wt, cand)):
                            wr.write(json.dumps({"market": market, "snapshot_id": row.snapshot_id,
                                                 "target_date": tkey,
                                                 "distribution": {str(b): p for b, p in dist.items() if p > 0}},
                                                sort_keys=True) + "\n")
                        info.append({"market": market, "snapshot_id": row.snapshot_id, "target_date": tkey,
                                     "hour": hour, "W": w, "lam": lam, "shift": sh, "available": available})
                        stats["emitted"] += 1
            stats_all[market] = dict(stats)
            print(f"g2 emit {market}: {dict(stats)}", flush=True)
    return info, stats_all


def control_dev(base_path, ra_path):
    """BASE vs R-A dev_P3d_N_fix.jsonl on target dates 08-15..09-29 (earlier lines skipped before parsing)."""
    if sha256_file(ra_path) != RA_DEV_FIX_SHA256:
        raise G2Error("R-A dev_P3d_N_fix.jsonl sha mismatch")

    def read(path, skip):
        out, skipped = {}, 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = line_date(line)
                if d is None or not dev_target_ok(d):
                    if not skip:
                        raise G2Error(f"BASE row outside the window: {d}")
                    skipped += 1
                    continue
                r = json.loads(line)
                out[(r["market"], r["snapshot_id"])] = {int(k): float(v) for k, v in r["distribution"].items()}
        return out, skipped

    mine, _ = read(base_path, False)
    ref, skipped = read(ra_path, True)
    common = set(mine) & set(ref)
    worst = 0.0
    for k in common:
        a, b = mine[k], ref[k]
        worst = max(worst, max(abs(a.get(x, 0.0) - b.get(x, 0.0)) for x in set(a) | set(b)))
    same = set(mine) == set(ref)
    return {"reference": str(ra_path), "reference_sha256": RA_DEV_FIX_SHA256, "reference_lines_skipped_by_date": skipped,
            "n_reference": len(ref), "n_base": len(mine), "same_keys": same,
            "only_base": len(set(mine) - set(ref)), "only_reference": len(set(ref) - set(mine)),
            "max_abs_diff": worst if common else None, "tolerance": CONTROL_TOL,
            "pass": bool(same and common and worst <= CONTROL_TOL)}


def score_dev(layout, base_path, arm_path, info):
    import numpy as np

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data

    start_d, end_d = data.check_range(DEV_FIRST.isoformat(), DEV_LAST.isoformat())
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    if not scored or scored[0] < DEV_FIRST.isoformat() or scored[-1] > DEV_LAST.isoformat():
        raise G2Error(f"scored population {scored[:1]}..{scored[-1:]} outside the dev window")
    table = sc.Table(lay, scored)
    market_b = table.brier(table.p_market)
    vec = {}
    for name, path in ((BASE, base_path), (ARM, arm_path)):
        frame, _ = data.distribution_predictions(data.CandidateSpec("distributions", str(path), "2025-12-31", False),
                                                 lay, folds)
        vec[name] = l3._vector(table, frame)
    bb, bt = table.brier(vec[BASE][0]), table.brier(vec[ARM][0])
    cov = vec[BASE][1] & vec[ARM][1]
    date_w = l3._date_weights([k[0] for k in table.keys], DRAWS, SEED)
    res = {"market_source": {"layout": str(layout), "file": "market.parquet (p_market_yes per band)",
                             "layout_manifest_sha256": lay.manifest_sha256, "file_sha256": lay.file_sha256,
                             "layout_dates": [lay.dates[0], lay.dates[-1]], "scored": [scored[0], scored[-1]],
                             "n_scored_dates": len(scored)},
           "coverage": {BASE: vec[BASE][2], ARM: vec[ARM][2]}, "groups": {}}
    for group, lo, hi in (("07-12", 7, 12),) + tuple((f"h{h:02d}", h, h) for h in HOURS):
        mask = cov & (table.local_hour >= lo) & (table.local_hour <= hi)
        idx, c = table.cells(bt, mask)
        _, r_ = table.cells(bb, mask)
        _, m = table.cells(market_b, mask)
        res["groups"][group] = {
            "n_market_days": int(len(idx)), "n_snapshots": int(mask.sum()),
            "n_dates": len({table.keys[i][0] for i in idx}),
            "dR": sc.ratio_interval(date_w[:, idx], c - r_, m, with_power=True),
            "R_" + ARM: sc.ratio_interval(date_w[:, idx], c, m),
            "R_" + BASE: sc.ratio_interval(date_w[:, idx], r_, m)}
    # Descriptive: remaining centre offset vs market, in bands, by tercile of the P3d_T shift (07-12, covered).
    shifts = {f"{r['market']}|{r['snapshot_id']}": r["shift"] for r in info}
    mask = cov & (table.local_hour >= 7) & (table.local_hour <= 12)
    bi = table.bands.band_index.to_numpy(int)
    centre = {name: mean_band_index(vec[name][0], table.offsets, table.n, bi) for name in (BASE, ARM)}
    centre_m = mean_band_index(table.p_market, table.offsets, table.n, bi)
    keys = table.snaps.row_key.to_numpy()
    sel = np.flatnonzero(mask)
    sv = np.array([shifts[keys[i]] for i in sel], float)
    (q1, q2), cls = terciles(sv)
    order_bad = int(sum(1 for o, n in zip(table.offsets, table.n)
                        if (np.diff(bi[o:o + n]) <= 0).any()))
    desc = {"definition": "offset = probability-weighted mean band index (arm) - same for the market (renormalised), "
                          "per covered 07-12 snapshot; terciles of the applied P3d_T shift (F, subtracted from mu)",
            "tercile_edges_shift_F": [q1, q2], "snapshots_with_non_increasing_band_index": order_bad, "terciles": {}}
    for k in range(3):
        ii = sel[cls == k]
        desc["terciles"][f"T{k + 1}"] = {
            "n_snapshots": int(len(ii)), "mean_shift_F": float(sv[cls == k].mean()) if len(ii) else None,
            **{f"offset_{name}_mean": float(np.nanmean(centre[name][ii] - centre_m[ii])) if len(ii) else None
               for name in (BASE, ARM)},
            **{f"offset_{name}_mean_abs": float(np.nanmean(np.abs(centre[name][ii] - centre_m[ii]))) if len(ii)
               else None for name in (BASE, ARM)}}
    res["centre_offset_by_tercile"] = desc
    # Scorer cross-check: the B-bound dev_score (unchanged, its own seed) on the same files; the point must agree.
    official = l3.dev_score(layout, {ARM: str(arm_path)}, start=DEV_FIRST.isoformat(), end=DEV_LAST.isoformat(),
                            with_mg1=False, references={BASE: str(base_path)})
    row = next(r for r in official["candidates"][ARM]["rows"] if r["reference"] == BASE and r["scope"] == "covered"
               and r["market"] == sc.ALL_MARKETS and r["group"] == "07-12")
    res["dev_score_crosscheck"] = {"row": row, "population": official["population"],
                                   "point_matches": abs(row["dR_date_clustered"]["estimate"]
                                                        - res["groups"]["07-12"]["dR"]["estimate"]) <= 1e-12}
    return res, official


def cmd_dev(a):
    g1 = load_g1()
    prm, rung, env = g1.bind_run_env(a.run_env)
    module_sha = sha256_file(__file__)
    picks, fobj = load_freeze(a.freeze_table, a.freeze_sha256, module_sha)
    out = prm.require_output_outside_repo(a.out)
    out.mkdir(parents=True, exist_ok=True)
    names = ("g2_result.json", "g2_rows.jsonl", f"dev_{BASE}.jsonl", f"dev_{ARM}.jsonl", "dev_score.json")
    for n in names:
        if (out / n).exists():
            raise G2Error(f"refusing to overwrite {out / n}")
    series_tr, sobj = g1.load_series(a.dseries)
    train_means = g1.b_train(series_tr, set(g1.YEARS))
    if any(abs(train_means[m] - v) > 1e-12 for m, v in fobj["b_train_2026"]["values"].items()):
        raise G2Error("b_train differs from the freeze table")
    s26, d26 = load_d26(a.d26)
    frame, buckets, finfo = g1.training_frame(prm, a.records, a.train_corpus)
    res = {"schema": SCHEMA, "rule_sha256": RULE_SHA256, "module_sha256": module_sha, "g1_module_sha256": G1_SHA256,
           "freeze": {"path": str(a.freeze_table), "sha256": a.freeze_sha256,
                      "picks": {f"h{h:02d}": list(v) for h, v in picks.items()}},
           "inputs": {**env, **finfo, "dseries_sha256": sha256_file(a.dseries), "d26": str(a.d26),
                      "d26_sha256": sha256_file(a.d26), "d26_rows": d26["n_rows"], "layout": str(a.layout),
                      "replay_root": str(a.replay_root)},
           "window": [DEV_FIRST.isoformat(), DEV_LAST.isoformat()], "kill": gate(None)["rule"]}

    def finish():
        (out / names[0]).write_text(json.dumps(res, indent=1, sort_keys=True, default=str), encoding="utf-8")
        print(json.dumps({k: res.get(k) for k in ("stopped_at", "verdict")}, default=str), flush=True)

    import pandas as pd

    snaps = pd.read_parquet(Path(a.layout) / "inputs_snapshots.parquet", columns=["market", "target_date"])
    keys = {(m, str(d)[:10]) for m, d in zip(snaps.market, snaps.target_date) if dev_target_ok(d)}
    recent = g1.recent_table(s26, keys)
    info, stats = emit_dev(g1, prm, a.layout, a.replay_root, frame, buckets, picks, recent, train_means, out)
    prm._write_jsonl(out / names[1], info)
    res["emit"] = {"per_market": stats, "files": {n: sha256_file(out / n) for n in names[2:4]}}
    short = defaultdict(int)
    for r in info:
        if not r["available"]:
            short[f"h{r['hour']:02d}"] += 1
    res["shift_counts"] = {"rows": len(info), "fewer_than_W_prior_days_shift_0": sum(short.values()),
                           "by_hour": dict(short), "nonzero_shift": sum(r["shift"] != 0.0 for r in info),
                           "mean_abs_shift": sum(abs(r["shift"]) for r in info) / max(1, len(info))}
    res["control"] = control_dev(out / names[2], a.ra_dev_fix)
    if not res["control"]["pass"]:
        res["stopped_at"] = "positive control failed (STOP, not a gate result)"
        finish()
        return 3
    score, official = score_dev(a.layout, out / names[2], out / names[3], info)
    (out / names[4]).write_text(json.dumps(official, indent=1, sort_keys=True, default=str), encoding="utf-8")
    res["score"] = score
    head = score["groups"]["07-12"]["dR"]
    res["verdict"] = gate(head["ci95"][1])
    res["verdict"].update({"point": head["estimate"], "ci95": head["ci95"], "mde80": head.get("mde80"),
                           "power_at_-0.0075": head.get("power")})
    finish()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="x36_trailing_g2")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze")
    for k in ("--run-env", "--records", "--train-corpus", "--dseries", "--out"):
        f.add_argument(k, required=True)
    d = sub.add_parser("dseries26")
    for k in ("--dev-corpus", "--repo", "--out"):
        d.add_argument(k, required=True)
    v = sub.add_parser("dev")
    for k in ("--run-env", "--records", "--train-corpus", "--dseries", "--d26", "--freeze-table", "--freeze-sha256",
              "--layout", "--replay-root", "--ra-dev-fix", "--out"):
        v.add_argument(k, required=True)
    a = ap.parse_args(argv)
    return {"freeze": cmd_freeze, "dseries26": cmd_dseries26, "dev": cmd_dev}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
