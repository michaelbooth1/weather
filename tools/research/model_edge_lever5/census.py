"""Outcome-blind gating census on the 111h swarm cache (no labels, no market).

Reads ONLY these columns of ``snapshots.parquet`` (the 111h/swarm cache,
targets 2026-08-01..09-29, 11 US markets): identifiers, local hour, cutoff
hour, captured feature values. It never opens ``bands.parquet`` and never
reads ``winner``/``settlement_*``/``floor*`` or any price column; pyarrow is
given an explicit column list, so those bytes are not decoded.

Outputs (JSON):
1. Task 4 coverage: how many served snapshots carried NBM v1 feature values
   in their captured feature vector (``nbm_prob_tmax_*``), and one concrete
   Atlanta instance (identifiers and feature values only).
2. 110g afternoon centering, if re-enabled as fitted: per snapshot at local
   hour 15-18 the context the serving selector picks and its clamped shift.
   A non-zero shift changes the stage output (changed-fraction is a lower
   bound: the disagreement smoothing term is not observable here). On integer
   buckets the stage-output TV distance of a pure shift is <= |shift| (W1 >=
   TV), so |shift| is reported as the stage-level TV bound.
3. Bucket-transition prior re-pointed on the observed station high at the
   cutoff (``high_so_far``): the serving code's own sample size from the
   prior-year climatology cache, and the blend weight it would get
   (0 below ``BUCKET_TRANSITION_MIN_SAMPLE``). Stage-output TV <= weight.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import pyarrow.parquet as pq

from weather.model.calibration_runtime import select_afternoon_centering_context
from weather.model.model_distribution_constants import (
    BUCKET_TRANSITION_BLEND_MAX,
    BUCKET_TRANSITION_MIN_SAMPLE,
)

SAFE_COLUMNS = [
    "row_key", "snapshot_id", "market", "target_date", "captured_at_local",
    "local_hour", "cutoff_hour", "model_version", "features_present",
    "high_so_far", "guidance_physical_floor", "forecast_high",
    "nbm_prob_tmax_p10", "nbm_prob_tmax_p50", "nbm_prob_tmax_p90",
    "nbm_prob_tmax_mean", "nbm_prob_tmax_physical_valid_flag",
]
FORBIDDEN = {"winner", "settlement_high", "settlement_bucket", "settlement_source",
             "floor", "floor_bucket"}
LAST_DATE = date(2026, 9, 29)


def _quantiles(values):
    if not values:
        return None
    s = sorted(values)
    pick = lambda q: s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))]  # noqa: E731
    return {"n": len(s), "mean": sum(s) / len(s), "p50": pick(0.5), "p90": pick(0.9), "max": s[-1]}


def load(cache_dir):
    assert not FORBIDDEN & set(SAFE_COLUMNS)
    table = pq.read_table(Path(cache_dir) / "snapshots.parquet", columns=SAFE_COLUMNS)
    rows = table.to_pylist()
    for row in rows:
        if date.fromisoformat(str(row["target_date"])[:10]) > LAST_DATE:
            raise SystemExit("refused: row after 2026-09-29 in cache")
    return rows


def task4_coverage(rows):
    present = [r for r in rows if r["nbm_prob_tmax_p50"] is not None]
    by_market = Counter(r["market"] for r in present)
    totals = Counter(r["market"] for r in rows)
    instance = next(
        (r for r in sorted(present, key=lambda r: (r["target_date"], r["captured_at_local"]))
         if r["market"] == "atlanta" and r["local_hour"] == 8
         and str(r["target_date"])[:10] >= "2026-09-01"),
        None,
    )
    return {
        "snapshots": len(rows),
        "nbm_v1_feature_present": len(present),
        "nbm_v1_feature_present_fraction": len(present) / len(rows) if rows else None,
        "by_market": {m: [by_market[m], totals[m]] for m in sorted(totals)},
        "model_versions": dict(Counter(r["model_version"] for r in rows)),
        "atlanta_instance": instance,
    }


def centering_census(rows, artifact, market_regimes):
    cfg = artifact.get("component") or {}
    max_abs = float(cfg.get("max_abs_shift", 2.0))
    start, end = int(cfg.get("start_hour", 15)), int(cfg.get("end_hour", 18))
    in_window = [r for r in rows if r["local_hour"] is not None and start <= int(r["local_hour"]) <= end]
    shifts, keys, changed = [], Counter(), 0
    for r in in_window:
        key, ctx = select_afternoon_centering_context(
            artifact, r["market"], market_regimes.get(r["market"]), int(r["local_hour"]))
        if not ctx:
            keys["no_context"] += 1
            continue
        shift = max(-max_abs, min(max_abs, float(ctx.get("mean_residual") or 0.0)))
        keys[key.split("|")[0] + "|" + key.split("|")[1].split("=")[0]] += 1
        if abs(shift) > 1e-12:
            changed += 1
        shifts.append(abs(shift))
    return {
        "enabled_on_master": bool(cfg.get("enabled", True)),
        "hours": [start, end],
        "snapshots_total": len(rows),
        "snapshots_in_window": len(in_window),
        "changed_snapshots_lower_bound": changed,
        "changed_fraction_all_hours_lower_bound": changed / len(rows) if rows else None,
        "changed_fraction_in_window_lower_bound": changed / len(in_window) if in_window else None,
        "context_kinds": dict(keys),
        "abs_shift_stage_tv_bound": _quantiles(shifts),
    }


def bucket_transition_census(rows, model_factory):
    groups = defaultdict(list)
    for r in rows:
        if r["high_so_far"] is not None and r["cutoff_hour"] is not None:
            groups[(r["market"], str(r["target_date"])[:10])].append(r)
    weights, samples, changed, n = [], [], 0, 0
    per_market = defaultdict(lambda: [0, 0])
    models = {}
    for (market, target), group in sorted(groups.items()):
        model = models.setdefault(market, model_factory(market))
        model.set_target_date(date.fromisoformat(target))
        for r in group:
            cutoff = int(r["cutoff_hour"])
            observed = model.round_half_up(float(r["high_so_far"]))
            model.cutoff_aligned_wu_history_max_native = lambda history, ch, _v=float(r["high_so_far"]): _v
            model.effective_intraday_cutoff_hour = lambda now, rws, _c=cutoff: _c
            try:
                bt = model.bucket_transition_model({}, datetime(2000, 1, 1, cutoff, 0),
                                                   min_sample_size=BUCKET_TRANSITION_MIN_SAMPLE)
            finally:
                del model.cutoff_aligned_wu_history_max_native
                del model.effective_intraday_cutoff_hour
            assert bt["observed_bucket"] == observed
            sample = int(bt.get("sample_size") or 0)
            weight = model.bucket_transition_blend_weight(bt) if bt.get("probabilities") else 0.0
            n += 1
            per_market[market][1] += 1
            samples.append(sample)
            weights.append(weight)
            if weight > 0:
                changed += 1
                per_market[market][0] += 1
    return {
        "snapshots_with_high_so_far": n,
        "changed_snapshots": changed,
        "changed_fraction": changed / n if n else None,
        "min_sample": BUCKET_TRANSITION_MIN_SAMPLE,
        "blend_max": BUCKET_TRANSITION_BLEND_MAX,
        "sample_size": _quantiles(samples),
        "weight_stage_tv_bound": _quantiles(weights),
        "weight_when_active": _quantiles([w for w in weights if w > 0]),
        "per_market_changed_of_total": {m: v for m, v in sorted(per_market.items())},
    }


def run(cache_dir, out_path):
    from weather.model.toronto_model import TorontoHighTempModel

    out = Path(out_path)
    if out.exists():
        raise SystemExit(f"refused: {out} exists")
    rows = load(cache_dir)
    models = {}

    def factory(market):
        return models.setdefault(market, TorontoHighTempModel(market_id=market))

    regimes = {m: factory(m).afternoon_residual_regime_id() for m in sorted({r["market"] for r in rows})}
    artifact = factory(rows[0]["market"]).afternoon_residual_centering or {}
    result = {
        "columns_read": SAFE_COLUMNS,
        "task4": task4_coverage(rows),
        "centering_110g_reenabled": centering_census(rows, artifact, regimes),
        "bucket_transition_repointed": bucket_transition_census(rows, factory),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return result
