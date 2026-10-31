"""Lane L8 research: score the shadow ``high_so_far`` parity variant on the development window.

Offline, weather-only research. Nothing in serving, capture, release or Scheduler imports this
module, and the import itself refuses on the dedicated capture host (``refuse_production_import``).

The serving variant lives in ``weather.model.model_base`` (``high_so_far_shadow_variant =
"metar_running_max_since_midnight_v1"``; production keeps ``None``). This module:

* ``emit`` (outcome-blind): for every captured snapshot of one market on dev target dates that the
  HARNESS v3 layout carries, re-run the CURRENT serving pipeline twice on the captured inputs, once
  as is (``base``) and once with the variant on (``fix``), and write both distributions, the
  replay-vs-recorded L1 of the base run (the replay positive control), the fix-vs-base L1, and the
  ``high_so_far``-derived features and floor of both runs. Reads ``replay_inputs.jsonl`` and the
  layout's ``inputs_snapshots.parquet`` only: no label, settlement or market price.
* ``sidestep`` (outcome-blind): does MG-1 (``r-t5-inc-c1``) see the skew? Its centre is the NBM v2
  mean, never the HGB; only its floor B reads ``high_so_far``. Counts the MG-1-covered snapshots
  whose B moves under the fix.
* ``score``: the dev scorecard's rows, mask and served fallback (``weather.reporting.scorecards.
  dev_scorecard``, imported lazily: it is not on master), arms served / base / fix / MG-1 /
  MG-1+fix, R and dR with date-clustered (and crossed) 2,000-draw intervals, per block and per hour,
  the above-settlement floor census, and the verdict of the locked rule ``C:\\t\\l8\\rule.md``.

Development evidence only (dates 2026-07-31..2026-09-29; every later date is refused).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from datetime import date
from pathlib import Path


class ShadowError(RuntimeError):
    """The research run cannot proceed honestly (scope, inputs or host)."""


def refuse_production_import(os_name=None, identity=None):
    """Fail closed when imported on the dedicated capture host (same contract as lane L3's module).

    On Windows the host identity must be provable; if it cannot be read, or it matches the tracked
    capture-host id, the import fails. ``identity`` returns ``(host_id, capture_host_id)``.
    """
    if (os.name if os_name is None else os_name) != "nt":
        return
    if identity is None:
        identity = _tracked_identity
    try:
        host_id, capture_id = identity()
    except Exception as exc:  # identity not provable: refuse
        raise ImportError(
            f"high_so_far_parity_shadow refuses to import: host identity not provable ({exc})"
        ) from exc
    if not host_id or not capture_id or host_id == capture_id:
        raise ImportError(
            "high_so_far_parity_shadow is workstation research and refuses to import on the "
            "dedicated capture host (or where that cannot be ruled out)"
        )


def _tracked_identity():
    from weather.execution_host import current_execution_host_id, load_execution_host_assignment

    assignment = load_execution_host_assignment()
    return current_execution_host_id(), assignment["dedicated_capture_execution_host_id"]


refuse_production_import()

DEV_FIRST = date(2026, 7, 31)
DEV_LAST = date(2026, 9, 29)
EMIT_SCHEMA = "high_so_far_parity_shadow_emit/1"
SCORE_SCHEMA = "high_so_far_parity_shadow_score/1"
VARIANT = "metar_running_max_since_midnight_v1"
DRAWS = 2000
SEED = 20260921
FEATURES = ("high_so_far", "forecast_high", "forecast_gap", "hours_at_peak", "live_reading_minus_high",
            "live_reading_temp", "current_temp", "guidance_physical_floor")
_SNAPSHOT_ID = re.compile(rb'"snapshot_id":\s*"([^"]+)"')
_FOLDER = re.compile(r"^highest-temperature-in-(.+)-on-([a-z]+)-(\d+)-(\d{4})$")
_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"), start=1)}


def check_range(start, end):
    start, end = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    if end > DEV_LAST:
        raise ShadowError(f"refused: --to {end} is after {DEV_LAST}")
    if start < DEV_FIRST:
        raise ShadowError(f"refused: --from {start} is before {DEV_FIRST}")
    if start > end:
        raise ShadowError("refused: --from is after --to")
    return start, end


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def event_folders(replay_root, market):
    for folder in sorted(Path(replay_root, "snapshots").iterdir()):
        match = _FOLDER.match(folder.name)
        if not match or match.group(1) != market:
            continue
        _, month, day, year = match.groups()
        yield date(int(year), _MONTHS[month], int(day)), folder


def l1(left, right):
    keys = set(left) | set(right)
    return float(sum(abs(left.get(k, 0.0) - right.get(k, 0.0)) for k in keys))


def centre(dist):
    total = sum(dist.values())
    return float(sum(k * v for k, v in dist.items()) / total) if total > 0 else None


def _clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


# ----------------------------------------------------------------------------- emit

def run_once(model, record, variant):
    """One replay of ``record`` with ``variant``: (distribution, features, floor context)."""
    from weather.backtesting.replay import as_int_distribution, parse_built_at, record_target_date

    sources = record.get("sources") or {}
    model.high_so_far_shadow_variant = variant
    try:
        target = record_target_date(record)
        if target is not None:
            model.set_target_date(target)
        now = parse_built_at(record)
        result = model.estimate_distribution_result(sources, now=now)
        dist = as_int_distribution(result.distribution)
        ctx = result.calibration_context or {}
        cutoff = ctx.get("cutoff_hour")
        feats = model.extract_live_features(sources, cutoff, now=now) if cutoff is not None else None
        hgb = ((result.component_payload or {}).get("components") or {}).get("hgb_feature_model") or {}
        out_feats = {k: _clean((feats or {}).get(k)) for k in FEATURES}
        floor = {
            "cutoff_hour": cutoff,
            "observed_floor_bucket": ctx.get("observed_floor_bucket"),
            "effective_observed_high": _clean(ctx.get("effective_observed_high")),
            "effective_observed_floor_high": _clean(ctx.get("effective_observed_floor_high")),
            "effective_observed_high_source": ctx.get("effective_observed_high_source"),
            "hgb_centre": centre({int(k): float(v) for k, v in hgb.items()}) if hgb else None,
        }
        return dist, out_feats, floor
    finally:
        model.high_so_far_shadow_variant = None


def emit_market(*, layout, replay_root, market, start, end, out_dir, log=print, venue_routine_floor_from=None):
    import pandas as pd

    from weather.market.market_registry import spec_for_id
    from weather.model.toronto_model import TorontoHighTempModel

    start, end = check_range(start, end)
    snaps = pd.read_parquet(Path(layout) / "inputs_snapshots.parquet",
                            columns=["snapshot_id", "market", "target_date", "local_hour"])
    snaps = snaps[snaps.market == market]
    days = pd.to_datetime(snaps.target_date.astype(str)).dt.date
    if (days > DEV_LAST).any():
        raise ShadowError("refused: the layout carries a snapshot after 2026-09-29")
    snaps = snaps[(days >= start) & (days <= end)]
    wanted = {str(s): int(h) for s, h in zip(snaps.snapshot_id, snaps.local_hour)}
    spec_for_id(market)
    out = Path(out_dir) / market
    out.mkdir(parents=True, exist_ok=True)
    model = TorontoHighTempModel(market_id=market)
    if venue_routine_floor_from is not None:
        # fix 11 counterfactual: the routine-only floor cutover moved early on this instance only
        cutover = date.fromisoformat(venue_routine_floor_from)
        if not (DEV_FIRST <= cutover <= DEV_LAST):
            raise ShadowError(f"refused: --venue-routine-floor-from {cutover} is outside the dev window")
        model.venue_routine_floor_from = cutover
    totals = {"snapshots": 0, "errors": 0, "base_exact_recorded": 0, "fix_changed": 0, "folders": 0}
    for target, folder in event_folders(replay_root, market):
        if not (start <= target <= end):
            continue
        done = out / f"{folder.name}.jsonl"
        if done.exists():
            continue
        part = out / f"{folder.name}.part"
        t0 = time.time()
        n = 0
        with open(folder / "replay_inputs.jsonl", "rb") as src, open(part, "w", encoding="utf-8") as dst:
            for line in src:
                match = _SNAPSHOT_ID.search(line)
                if not match:
                    continue
                sid = match.group(1).decode()
                if sid not in wanted:
                    continue
                record = json.loads(line)
                if str(record.get("target_date") or target)[:10] > DEV_LAST.isoformat():
                    raise ShadowError("refused: a record after 2026-09-29")
                row = {"market": market, "snapshot_id": sid, "target_date": target.isoformat(),
                       "local_hour": wanted[sid]}
                try:
                    base, fb, cb = run_once(model, record, None)
                    fix, ff, cf = run_once(model, record, VARIANT)
                    recorded = {int(k): float(v) for k, v in (record.get("recorded_distribution") or {}).items()}
                    row.update({"base": {str(k): v for k, v in base.items()},
                                "fix": {str(k): v for k, v in fix.items()},
                                "l1_base_recorded": l1(base, recorded) if recorded else None,
                                "l1_fix_base": l1(fix, base), "feat_base": fb, "feat_fix": ff,
                                "floor_base": cb, "floor_fix": cf})
                    totals["base_exact_recorded"] += int(bool(recorded) and row["l1_base_recorded"] <= 1e-9)
                    totals["fix_changed"] += int(row["l1_fix_base"] > 1e-12)
                except Exception as exc:  # recorded, never filled
                    row["error"] = f"{type(exc).__name__}: {exc}"
                    totals["errors"] += 1
                dst.write(json.dumps(row, sort_keys=True) + "\n")
                n += 1
        os.replace(part, done)
        totals["snapshots"] += n
        totals["folders"] += 1
        log(f"TIMING folder={folder.name} snapshots={n} seconds={time.time() - t0:.1f}")
    audit = {"schema": EMIT_SCHEMA, "market": market, "range": [start.isoformat(), end.isoformat()],
             "variant": VARIANT, "venue_routine_floor_from": str(model.venue_routine_floor_from),
             "layout_snapshots_sha256": sha256_file(Path(layout) / "inputs_snapshots.parquet"),
             "module_sha256": sha256_file(__file__), "this_invocation": totals,
             "files": {p.name: sha256_file(p) for p in sorted(out.glob("*.jsonl"))}}
    (out / "_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True), encoding="utf-8")
    return audit


def read_emitted(emit_dir, markets=None):
    rows = []
    for path in sorted(Path(emit_dir).glob("*/*.jsonl")):
        if path.parent.name.startswith("_") or (markets and path.parent.name not in markets):
            continue
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    if row["target_date"] > DEV_LAST.isoformat():
                        raise ShadowError("refused: emitted row after 2026-09-29")
                    rows.append(row)
    return rows


def write_distributions(rows, arm, path):
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            if row.get("error"):
                continue
            handle.write(json.dumps({"market": row["market"], "snapshot_id": row["snapshot_id"],
                                     "target_date": row["target_date"], "distribution": row[arm]},
                                    sort_keys=True) + "\n")


# ----------------------------------------------------------------------------- MG-1

def mg1_band_probs(kind, low, high, B, mu, sig):
    """MG-1 ``r-t5-inc-c1`` (verbatim from free_source_candidates.mg1.band_probs)."""
    import numpy as np
    from scipy.special import ndtr

    kind = np.asarray(kind)
    low = np.asarray(low, float)
    high = np.asarray(high, float)
    up = np.where(kind == "gte", np.inf, high + .5)
    lo = np.where((kind == "lte") | (low <= B), -np.inf, low - .5)
    possible = (kind == "gte") | (high >= B)
    p = np.where(possible, ndtr((up - mu) / sig) - ndtr((lo - mu) / sig), 0.0)
    return np.clip(p, 0.0, None)


def mg1_frame(snaps, bands, floor_override=None):
    """MG-1 band probabilities; ``floor_override`` (row_key -> native high) raises F to max(F, it)."""
    import numpy as np
    import pandas as pd

    s = snaps.reset_index(drop=True)
    avail = pd.to_datetime(s.v2_available_at, utc=True, errors="coerce")
    t = pd.to_datetime(s.captured_at_utc, utc=True)
    mu = pd.to_numeric(s.v2_mean, errors="coerce").to_numpy(float)
    sd = pd.to_numeric(s.v2_stddev, errors="coerce").to_numpy(float)
    ok = np.isfinite(mu) & np.isfinite(sd) & avail.notna().to_numpy() & (avail <= t).fillna(False).to_numpy()
    floor = pd.to_numeric(s["floor"], errors="coerce").to_numpy(float)
    if floor_override is not None:
        extra = pd.Series(floor_override, dtype=float).reindex(s.row_key).to_numpy(float)
        floor = np.where(np.isfinite(extra), np.fmax(floor, extra), floor)
    B = np.where(np.isfinite(floor), np.floor(floor + 0.5), -np.inf)
    grouped = {k: g for k, g in bands.groupby("row_key", sort=False)}
    rk, bi, pp = [], [], []
    for i in np.flatnonzero(ok):
        g = grouped.get(s.row_key.iloc[i])
        if g is None:
            continue
        p = mg1_band_probs(g.kind.to_numpy(), g.low.to_numpy(), g.high.to_numpy(), B[i], mu[i], max(sd[i], 1.0))
        rk.extend([s.row_key.iloc[i]] * len(g))
        bi.extend(g.band_index.to_numpy(int).tolist())
        pp.extend(p.tolist())
    return pd.DataFrame({"row_key": rk, "band_index": np.asarray(bi, int), "p": np.asarray(pp, float)}), B, ok


def fix_floor_highs(rows):
    """row_key -> the fix run's effective observed floor high (only where it is finite)."""
    out = {}
    for row in rows:
        if row.get("error"):
            continue
        value = (row.get("floor_fix") or {}).get("effective_observed_floor_high")
        if value is not None:
            out[f"{row['market']}|{row['snapshot_id']}"] = float(value)
    return out


def sidestep(layout_root, emit_dir, start="2026-08-15", end="2026-09-29"):
    """Outcome-blind: how often the fix moves MG-1's floor bucket B on MG-1-covered snapshots."""
    import numpy as np
    import pandas as pd

    start, end = check_range(start, end)
    snaps = pd.read_parquet(Path(layout_root) / "inputs_snapshots.parquet")
    snaps = snaps[(pd.to_datetime(snaps.date.astype(str)).dt.date >= start)
                  & (pd.to_datetime(snaps.date.astype(str)).dt.date <= end)].reset_index(drop=True)
    bands = pd.read_parquet(Path(layout_root) / "inputs_bands.parquet",
                            columns=["row_key", "band_index", "kind", "low", "high"])
    bands = bands[bands.row_key.isin(set(snaps.row_key))]
    rows = read_emitted(emit_dir)
    over = fix_floor_highs(rows)
    _, b0, ok = mg1_frame(snaps, bands)
    _, b1, _ = mg1_frame(snaps, bands, over)
    hours = snaps.local_hour.to_numpy(int)
    moved = ok & (b1 > b0)
    out = {"mg1_covered": int(ok.sum()), "with_fix_row": int(sum(k in over for k in snaps.row_key[ok])),
           "floor_bucket_raised": int(moved.sum()), "share_raised": float(moved.sum() / max(1, ok.sum())),
           "by_block": {}}
    for name, lo, hi in (("00-05", 0, 5), ("06-09", 6, 9), ("10-12", 10, 12), ("13-16", 13, 16),
                         ("17-23", 17, 23), ("00-16", 0, 16), ("07-12", 7, 12)):
        m = ok & (hours >= lo) & (hours <= hi)
        out["by_block"][name] = {"covered": int(m.sum()), "raised": int((moved & m).sum()),
                                 "mean_raise": float(np.mean((b1 - b0)[moved & m])) if (moved & m).any() else 0.0}
    base_hsf = [r["feat_base"]["high_so_far"] for r in rows if not r.get("error")
                and r["feat_base"]["high_so_far"] is not None and r["feat_fix"]["high_so_far"] is not None]
    fix_hsf = [r["feat_fix"]["high_so_far"] for r in rows if not r.get("error")
               and r["feat_base"]["high_so_far"] is not None and r["feat_fix"]["high_so_far"] is not None]
    out["hgb_feature_shift_mean"] = float(np.mean(np.subtract(fix_hsf, base_hsf))) if fix_hsf else None
    out["hgb_feature_changed_share"] = (float(np.mean(np.abs(np.subtract(fix_hsf, base_hsf)) > 1e-9))
                                        if fix_hsf else None)
    return out


# ----------------------------------------------------------------------------- derived-feature check

def derived_feature_check(rows):
    """Every derived feature moves with high_so_far; the floor never weakens (counts violations)."""
    bad = {"floor_weaker": 0, "floor_high_weaker": 0, "forecast_gap": 0, "live_reading_minus_high": 0,
           "untouched_changed": 0}
    n = changed = 0
    for row in rows:
        if row.get("error"):
            continue
        n += 1
        fb, ff = row["feat_base"], row["feat_fix"]
        cb, cf = row["floor_base"], row["floor_fix"]
        if cb.get("observed_floor_bucket") is not None and (
                cf.get("observed_floor_bucket") is None or cf["observed_floor_bucket"] < cb["observed_floor_bucket"]):
            bad["floor_weaker"] += 1
        if cb.get("effective_observed_floor_high") is not None and (
                cf.get("effective_observed_floor_high") is None
                or cf["effective_observed_floor_high"] < cb["effective_observed_floor_high"] - 1e-9):
            bad["floor_high_weaker"] += 1
        if fb["high_so_far"] is None or ff["high_so_far"] is None:
            continue
        shift = ff["high_so_far"] - fb["high_so_far"]
        changed += int(abs(shift) > 1e-9)
        if fb["forecast_high"] is not None and ff["forecast_high"] == fb["forecast_high"] and fb["forecast_gap"] is not None:
            if abs((ff["forecast_gap"] - fb["forecast_gap"]) + shift) > 1e-6:
                bad["forecast_gap"] += 1
        if fb["live_reading_minus_high"] is not None and ff["live_reading_minus_high"] is not None:
            if abs((ff["live_reading_minus_high"] - fb["live_reading_minus_high"]) + shift) > 1e-6:
                bad["live_reading_minus_high"] += 1
        if ff["current_temp"] != fb["current_temp"] or ff["live_reading_temp"] != fb["live_reading_temp"]:
            bad["untouched_changed"] += 1
    return {"rows": n, "high_so_far_changed": changed, "violations": bad}


# ----------------------------------------------------------------------------- score

GROUPS = (("00-05", 0, 5), ("06-09", 6, 9), ("10-12", 10, 12), ("13-16", 13, 16), ("17-23", 17, 23),
          ("00-12", 0, 12), ("07-12", 7, 12), ("00-16", 0, 16), ("all", 0, 23)) + tuple(
    (f"h{h:02d}", h, h) for h in range(24))
CONTRASTS = (("fix", "base"), ("fix", "served"), ("fix", "mg1"), ("mg1_fix", "mg1"), ("mg1_fix", "served"),
             ("base", "served"), ("mg1", "served"))


def date_weights(dates, draws=DRAWS, seed=SEED):
    import numpy as np

    _, di = np.unique(np.asarray(dates), return_inverse=True)
    d = di.max() + 1
    rng = np.random.default_rng(seed)
    wd = rng.multinomial(d, np.full(d, 1 / d), size=draws)
    return wd[:, di]


def _interval(w, num, den):
    import numpy as np

    point = float(num.sum() / den.sum())
    boot = (w @ num) / (w @ den)
    lo, hi = np.quantile(boot[np.isfinite(boot)], [.025, .975])
    return {"estimate": point, "ci95": [float(lo), float(hi)]}


def score(layout_root, emit_dir, start="2026-08-01", end="2026-09-29"):
    import numpy as np

    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data

    start, end = check_range(start, end)
    layout = data.load_layout(layout_root, data.DEV_FIRST, end)
    folds = data.make_folds(layout.dates, start, end)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    table = sc.Table(layout, scored)
    rows = [r for r in read_emitted(emit_dir) if not r.get("error")]
    keys = {f"{r['market']}|{r['snapshot_id']}" for r in rows}
    tmp = Path(emit_dir) / "_score_inputs"
    tmp.mkdir(exist_ok=True)
    vectors, coverage = {"served": table.p_served}, {}
    for arm in ("base", "fix"):
        path = tmp / f"{arm}.jsonl"
        write_distributions(rows, arm, path)
        frame, _ = data.distribution_predictions(data.CandidateSpec("distributions", str(path), no_training=True),
                                                 layout, folds)
        vectors[arm], coverage[arm] = table.candidate_vector(frame)
    frame0, _, _ = mg1_frame(table.snaps, table.bands)
    vectors["mg1"], coverage["mg1"] = table.candidate_vector(frame0)
    frame1, _, _ = mg1_frame(table.snaps, table.bands, fix_floor_highs(rows))
    vectors["mg1_fix"], coverage["mg1_fix"] = table.candidate_vector(frame1)
    # The free-source screens' own MG-1 ships in this tree, so import it directly
    # (no ImportError fallback: the import-architecture ratchet forbids one).
    from weather.reporting.scorecards.free_source_candidates import mg1 as fs_mg1

    ref = fs_mg1.predict(table.snaps, table.bands)
    mg1_control = bool(ref.sort_values(["row_key", "band_index"]).reset_index(drop=True).equals(
        frame0.sort_values(["row_key", "band_index"]).reset_index(drop=True)))
    brier = {arm: table.brier(p) for arm, p in vectors.items()}
    brier["market"] = table.brier(table.p_market)
    cell_dates = [k[0] for k in table.keys]
    wd = date_weights(cell_dates)
    out_rows = []
    covered = np.isin(table.snaps.row_key.to_numpy(), list(keys))
    for market in ["ALL"] + sorted(set(table.markets)):
        for group, lo, hi in GROUPS:
            if market != "ALL" and group not in ("00-16", "07-12", "all"):
                continue
            mask = (table.local_hour >= lo) & (table.local_hour <= hi)
            if market != "ALL":
                mask &= table.markets == market
            if not mask.any():
                continue
            cells = {arm: table.cells(b, mask) for arm, b in brier.items()}
            idx = cells["market"][0]
            m = cells["market"][1]
            w_date = wd[:, idx]
            w_cross = table.w[:, idx]
            row = {"market": market, "block": group, "n_snapshots": int(mask.sum()),
                   "n_fix_covered": int((mask & covered).sum()), "n_market_days": int(len(idx)),
                   "n_dates": len({cell_dates[i] for i in idx}), "R": {}, "dR": {}, "dBrier": {}}
            for arm in vectors:
                row["R"][arm] = _interval(w_date, cells[arm][1], m)
            for a, b in CONTRASTS:
                diff = cells[a][1] - cells[b][1]
                row["dR"][f"{a}-{b}"] = {"date": _interval(w_date, diff, m)}
                row["dBrier"][f"{a}-{b}"] = {"date": _interval(w_date, diff, np.ones(len(idx)))}
                if market == "ALL":
                    row["dR"][f"{a}-{b}"]["crossed"] = _interval(w_cross, diff, m)
                    row["dBrier"][f"{a}-{b}"]["crossed"] = _interval(w_cross, diff, np.ones(len(idx)))
                    if group in ("00-16", "07-12"):
                        num = w_date @ diff / (w_date @ m)
                        row["dR"][f"{a}-{b}"]["date"].update(sc.mde80(float(diff.sum() / m.sum()), num))
            out_rows.append(row)
    census = above_settlement_census(table, layout, rows)
    return {"schema": SCORE_SCHEMA, "variant": VARIANT, "module_sha256": sha256_file(__file__),
            "scorecard_code_sha256": sc.code_sha256(), "layout_manifest_sha256": layout.manifest_sha256,
            "population": {"n_dates": len(scored), "first": scored[0], "last": scored[-1],
                           "n_markets": len(set(table.markets)), "n_snapshots": int(len(table.snaps)),
                           "n_fix_covered": int(covered.sum())},
            "coverage": coverage, "mg1_reimplementation_equals_free_source_mg1": mg1_control,
            "draws": DRAWS, "seed": SEED, "census": census, "rows": out_rows}


def above_settlement_census(table, layout, rows):
    """Snapshots whose floor bucket exceeds the settled high: base replay vs fix (the -09-72a lesson)."""
    settled = layout.labels.set_index("row_key").settlement_high.to_dict()
    in_scope = set(table.snaps.row_key)
    out = {"compared": 0, "base_above": 0, "fix_above": 0, "fix_only_above": 0, "fix_only_examples": []}
    for row in rows:
        key = f"{row['market']}|{row['snapshot_id']}"
        if key not in in_scope or settled.get(key) is None:
            continue
        s = float(settled[key])
        b, f = row["floor_base"].get("observed_floor_bucket"), row["floor_fix"].get("observed_floor_bucket")
        out["compared"] += 1
        above_b = b is not None and b > s
        above_f = f is not None and f > s
        out["base_above"] += int(above_b)
        out["fix_above"] += int(above_f)
        if above_f and not above_b:
            out["fix_only_above"] += 1
            if len(out["fix_only_examples"]) < 20:
                out["fix_only_examples"].append({"row_key": key, "floor_fix": f, "floor_base": b, "settled": s})
    return out


def verdict(result):
    """The locked rule's decision (C:\\t\\l8\\rule.md, sections 'Keep/kill rule' and 'Binding')."""
    pooled = {r["block"]: r for r in result["rows"] if r["market"] == "ALL"}
    std = ("00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all")

    def ci(contrast, block="00-16"):
        return pooled[block]["dR"][contrast]["date"]["ci95"]

    def harm(contrast):
        return [b for b in std if pooled[b]["dR"][contrast]["date"]["ci95"][0] > 0]

    served = pooled["all"]["R"]["served"]["estimate"], pooled["00-16"]["R"]["served"]["estimate"]
    control = abs(served[0] - 1.774) < 5e-4 and abs(served[1] - 1.526) < 5e-4
    mg1 = pooled.get("00-12", {}).get("dBrier", {}).get("mg1-served", {}).get("crossed", {}).get("estimate")
    mg1_ok = mg1 is None or round(mg1, 4) == -0.0153  # ledger row 4 (absent only in unit fixtures)
    control = control and mg1_ok and result.get("mg1_reimplementation_equals_free_source_mg1") in (True, None)
    out = {"positive_control_served_R": served, "positive_control_mg1_minus_served_00_12": mg1,
           "positive_control_pass": control}
    if result.get("derived", {}).get("violations", {}).get("floor_weaker") or             result.get("derived", {}).get("violations", {}).get("floor_high_weaker"):
        out["decision"] = "NO CLAIM (the floor weakened on some row)"
        return out
    if not control:
        out["decision"] = "NO CLAIM (positive control failed)"
        return out
    fix_keep = ci("fix-base")[1] < 0 and not harm("fix-base")
    out["parity_fix_vs_base"] = {"ci95_00_16": ci("fix-base"), "harm_blocks": harm("fix-base"),
                                 "decision": "KEEP" if fix_keep else "KILL"}
    safe = result["census"]["fix_only_above"] == 0
    out["floor_safety_fix_only_above"] = result["census"]["fix_only_above"]
    binds = []
    for arm in ("fix", "mg1_fix"):
        c = f"{arm}-mg1"
        beats = ci(c)[1] < 0 and not harm(c)
        out[f"{arm}_vs_mg1"] = {"ci95_00_16": ci(c), "harm_blocks": harm(c), "beats_mg1": beats}
        if beats:
            binds.append((pooled["00-16"]["dR"][c]["date"]["estimate"], arm))
    if binds and safe:
        out["decision"] = f"BIND as MG-2: {min(binds)[1]} (binding plan; one Fable review before landing)"
    elif binds:
        out["decision"] = "BEATS MG-1 but new above-settlement floor rows: needs a ruling, not bound"
    else:
        out["decision"] = "NOT BOUND (no arm beats MG-1 on 00-16)"
    return out


def markdown(result, sha):
    pooled = [r for r in result["rows"] if r["market"] == "ALL"]

    def f(entry):
        lo, hi = entry["ci95"]
        return f"{entry['estimate']:+.4f} [{lo:+.4f}, {hi:+.4f}]"

    lines = [f"# L8 high_so_far parity shadow, dev scorecard `{sha[:12]}`", "",
             "Development evidence only (dates <= 2026-09-29). R = Brier/market Brier (ratio of cell means); "
             "dR intervals date-clustered, 2,000 draws, seed 20260921.", "",
             f"Population {json.dumps(result['population'])}", "",
             f"Census {json.dumps(result['census'])[:600]}", "",
             "| block | n | R served | R base | R fix | R MG-1 | R MG-1+fix | dR fix-base | dR fix-served | "
             "dR fix-MG-1 | dR MG-1+fix - MG-1 |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in pooled:
        lines.append(f"| {r['block']} | {r['n_snapshots']} | " + " | ".join(
            f"{r['R'][a]['estimate']:.3f}" for a in ("served", "base", "fix", "mg1", "mg1_fix")) + " | " + " | ".join(
            f(r["dR"][c]["date"]) for c in ("fix-base", "fix-served", "fix-mg1", "mg1_fix-mg1")) + " |")
    lines += ["", "| market | block | dR fix-base | dR fix-MG-1 | dR MG-1+fix - MG-1 |", "| --- | --- | --- | --- | --- |"]
    for r in result["rows"]:
        if r["market"] != "ALL":
            lines.append(f"| {r['market']} | {r['block']} | " + " | ".join(
                f(r["dR"][c]["date"]) for c in ("fix-base", "fix-mg1", "mg1_fix-mg1")) + " |")
    lines += ["", "Verdict: `" + json.dumps(result.get("verdict"), default=str) + "`"]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------- CLI

def _configure_roots(data_root, config_root):
    import weather.paths

    if data_root:
        weather.paths.DATA_ROOT = Path(data_root).resolve()
    if config_root:
        weather.paths.CONFIG_ROOT = Path(config_root).resolve()


def _refuse_inside_data(path, data_root):
    out = Path(path).resolve()
    for root in {Path(data_root).resolve() if data_root else None}:
        if root is not None and (out == root or root in out.parents):
            raise ShadowError(f"refused: {out} is inside the runtime data tree {root}")
    return out


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.high_so_far_parity_shadow")
    sub = parser.add_subparsers(dest="command", required=True)
    e = sub.add_parser("emit")
    e.add_argument("--layout", required=True)
    e.add_argument("--replay-root", required=True)
    e.add_argument("--data-root", required=True)
    e.add_argument("--config-root")
    e.add_argument("--market", required=True, action="append")
    e.add_argument("--from", dest="start", default="2026-08-15")
    e.add_argument("--to", dest="end", default="2026-09-29")
    e.add_argument("--out-dir", required=True)
    e.add_argument("--venue-routine-floor-from", help="fix 11 counterfactual only: move the routine-only "
                   "floor cutover to this dev date on the replay model (default: the production cutover)")
    s = sub.add_parser("sidestep")
    s.add_argument("--layout", required=True)
    s.add_argument("--emit-dir", required=True)
    s.add_argument("--out", required=True)
    c = sub.add_parser("check")
    c.add_argument("--emit-dir", required=True)
    c.add_argument("--out", required=True)
    r = sub.add_parser("score")
    r.add_argument("--layout", required=True)
    r.add_argument("--emit-dir", required=True)
    r.add_argument("--rule", required=True)
    r.add_argument("--rule-sha256", required=True)
    r.add_argument("--out", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "emit":
        _configure_roots(args.data_root, args.config_root)
        _refuse_inside_data(args.out_dir, args.data_root)
        for market in args.market:
            audit = emit_market(layout=args.layout, replay_root=args.replay_root, market=market,
                                start=args.start, end=args.end, out_dir=args.out_dir,
                                log=lambda m: print(m, flush=True),
                                venue_routine_floor_from=args.venue_routine_floor_from)
            print(json.dumps(audit["this_invocation"] | {"market": market}), flush=True)
        return 0
    if args.command == "sidestep":
        result = sidestep(args.layout, args.emit_dir)
        Path(args.out).write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.command == "check":
        rows = read_emitted(args.emit_dir)
        result = {"derived": derived_feature_check(rows),
                  "replay_control": {
                      "rows": sum(1 for r in rows if not r.get("error")),
                      "errors": sum(1 for r in rows if r.get("error")),
                      "base_exact_recorded": sum(1 for r in rows if not r.get("error")
                                                 and (r.get("l1_base_recorded") or 0) <= 1e-9
                                                 and r.get("l1_base_recorded") is not None),
                      "fix_equals_base_where_high_so_far_and_floor_unchanged": sum(
                          1 for r in rows if not r.get("error") and r["feat_fix"] == r["feat_base"]
                          and r["floor_fix"].get("effective_observed_floor_high")
                          == r["floor_base"].get("effective_observed_floor_high") and r["l1_fix_base"] <= 1e-12),
                      "unchanged_inputs": sum(
                          1 for r in rows if not r.get("error") and r["feat_fix"] == r["feat_base"]
                          and r["floor_fix"].get("effective_observed_floor_high")
                          == r["floor_base"].get("effective_observed_floor_high"))}}
        Path(args.out).write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, sort_keys=True))
        return 0
    rule_sha = sha256_file(args.rule)
    if rule_sha != args.rule_sha256:
        raise ShadowError(f"refused: rule sha256 {rule_sha} != locked {args.rule_sha256}")
    result = score(args.layout, args.emit_dir)
    result["rule"] = {"path": str(args.rule), "sha256": rule_sha}
    result["derived"] = derived_feature_check(read_emitted(args.emit_dir))
    result["verdict"] = verdict(result)
    body = json.dumps(result, sort_keys=True, separators=(",", ":"), default=float).encode()
    sha = hashlib.sha256(body).hexdigest()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{sha}.json").write_bytes(body)
    (out / f"{sha}.md").write_text(markdown(result, sha), encoding="utf-8")
    print(json.dumps({"sha256": sha, "verdict": result["verdict"]}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
