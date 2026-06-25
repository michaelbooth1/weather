"""Late-day lock-in saturation validation."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.hourly.hourly_model_performance import (
    DEFAULT_LABELS_CSV,
    DEFAULT_QUALITY_GRADES,
    DEFAULT_SNAPSHOTS_ROOT,
    discover_labeled_folders,
    score_folder,
    summarize_rows,
)
from weather.reporting.hourly.ten_minute_model_performance import (
    summarize_by_slot,
    ten_minute_checkpoint_rows,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("late_day_lock_in_repair")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_TEN_MINUTE_REPORT = DEFAULT_BACKTEST_ROOT / "ten_minute_model_performance.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "late_day_lock_in_repair.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "late_day_lock_in_repair_report.md"
DEFAULT_FACTOR_GRID = (1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0)
DEFAULT_MARKET_TOL = 0.003
DEFAULT_MIN_CURRENT_IMPROVEMENT = 0.001
DEFAULT_MIN_MARKET_GAP_SHRINK = 0.003
DEFAULT_TOP_SLOTS = 12
CALIBRATOR_C = 0.03
CALIBRATOR_BLEND = 1.0
CALIBRATOR_EXTRAPOLATION = 1.25
CALIBRATOR_POWER = 3.0
SAFE_FORECAST_GAP_MAX = -1.0
SAFE_HOURS_AT_PEAK_MIN = 0.5
SAFE_WARMING_RATE_MAX = 0.0
SAFE_LIVE_READING_MINUS_HIGH_MAX = 0.0
SAFE_WU_HISTORY_HIGH_TOLERANCE = 0.1
SAFE_MIN_SLOT = 17 * 60
CALIBRATOR_NUMERIC_FEATURES = [
    "model_probability",
    "model_logit",
    "time_slot_minute",
    "hour",
    "minute",
    "bin_value",
    "bin_minus_high_so_far",
    "abs_bin_minus_high_so_far",
    "bin_covers_high_so_far",
    "bin_minus_forecast_high",
    "abs_bin_minus_forecast_high",
    "high_so_far",
    "current_temp",
    "forecast_high",
    "forecast_gap",
    "hours_at_peak",
    "warming_rate_2h",
    "rise_from_7am",
    "live_reading_minus_high",
    "minutes_since_cutoff",
    "raw_wu_history_high_c",
    "raw_wu_max_since_7am_c",
    "raw_open_meteo_max_c",
    "raw_weather_forecast_max_c",
]
CALIBRATOR_CATEGORICAL_FEATURES = [
    "market_id",
    "bin_type",
    "forecast_gap_bucket",
    "cloud_group",
    "wind_group",
    "live_reading_gap_bucket",
    "minutes_since_cutoff_bucket",
]
LATE_DAY_FEATURE_CONTRACT = [
    "model_probability",
    "time_slot_minute",
    "market_id",
    "bin_type",
    "bin_value",
    "bin_minus_high_so_far",
    "bin_covers_high_so_far",
    "feature_high_so_far",
    "feature_current_temp",
    "feature_forecast_high",
    "feature_forecast_gap",
    "feature_hours_at_peak",
    "feature_warming_rate_2h",
    "feature_rise_from_7am",
    "feature_live_reading_minus_high",
    "feature_minutes_since_cutoff",
    "raw_wu_history_high_minus_feature_high",
    "feature_forecast_gap_bucket",
    "feature_cloud_group",
    "feature_wind_group",
    "raw_wu_history_high_c",
    "raw_wu_max_since_7am_c",
    "raw_open_meteo_max_c",
    "raw_weather_forecast_max_c",
]


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _read_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def late_blocker_slots(report_path: str | Path, top_slots: int = DEFAULT_TOP_SLOTS) -> set[int]:
    payload = _read_json(report_path)
    by_slot = payload.get("by_slot") or []
    rows = [
        row for row in by_slot
        if int(row.get("time_slot_minute") or 0) >= 15 * 60 and int(row.get("n") or 0) >= 30
    ]
    selected = sorted(rows, key=lambda row: safe_float(row.get("brier_delta")) or 0.0)[: int(top_slots)]
    return {int(row["time_slot_minute"]) for row in selected if row.get("time_slot_minute") is not None}


def bin_covers_value(row: dict[str, Any], value: float | None) -> bool:
    if value is None:
        return False
    kind = row.get("bin_kind") or row.get("bin_type")
    lo = safe_float(row.get("bin_value_c"))
    hi = safe_float(row.get("bin_value_hi"))
    if lo is None:
        return False
    if kind == "lte":
        return value <= lo
    if kind == "gte":
        return value >= lo
    if hi is not None and hi != lo:
        return lo <= value <= hi
    return abs(value - lo) <= 0.51


def bin_mid(row: dict[str, Any]) -> float | None:
    lo = safe_float(row.get("bin_value_c") or row.get("bin_value"))
    hi = safe_float(row.get("bin_value_hi"))
    if lo is None:
        return None
    if hi is not None and hi != lo:
        return (lo + hi) / 2.0
    return lo


def probability_logit(value: Any) -> float:
    probability = safe_float(value)
    if probability is None:
        probability = 0.0
    probability = min(1.0 - 1e-6, max(1e-6, probability))
    return math.log(probability / (1.0 - probability))


def _feature_float(row: dict[str, Any], key: str, *fallbacks: str) -> float | None:
    for candidate in (key, *fallbacks):
        value = safe_float(row.get(candidate))
        if value is not None:
            return value
    return None


def calibrator_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    records = []
    for row in rows:
        probability = safe_float(row.get("model_probability")) or 0.0
        slot = int(row.get("time_slot_minute") or 0)
        value = bin_mid(row)
        high_so_far = _feature_float(row, "feature_high_so_far", "high_so_far")
        forecast_high = _feature_float(row, "feature_forecast_high", "forecast_high")
        bin_minus_high = value - high_so_far if value is not None and high_so_far is not None else 0.0
        bin_minus_forecast = value - forecast_high if value is not None and forecast_high is not None else 0.0
        records.append({
            "model_probability": probability,
            "model_logit": probability_logit(probability),
            "time_slot_minute": float(slot),
            "hour": float(slot // 60),
            "minute": float(slot % 60),
            "bin_value": float(value or 0.0),
            "bin_minus_high_so_far": float(bin_minus_high),
            "abs_bin_minus_high_so_far": abs(float(bin_minus_high)),
            "bin_covers_high_so_far": 1.0 if bin_covers_value(row, high_so_far) else 0.0,
            "bin_minus_forecast_high": float(bin_minus_forecast),
            "abs_bin_minus_forecast_high": abs(float(bin_minus_forecast)),
            "high_so_far": float(high_so_far or 0.0),
            "current_temp": float(_feature_float(row, "feature_current_temp", "current_temp") or 0.0),
            "forecast_high": float(forecast_high or 0.0),
            "forecast_gap": float(_feature_float(row, "feature_forecast_gap", "forecast_gap") or 0.0),
            "hours_at_peak": float(_feature_float(row, "feature_hours_at_peak", "hours_at_peak") or 0.0),
            "warming_rate_2h": float(_feature_float(row, "feature_warming_rate_2h", "warming_rate_2h") or 0.0),
            "rise_from_7am": float(_feature_float(row, "feature_rise_from_7am", "rise_from_7am") or 0.0),
            "live_reading_minus_high": float(
                _feature_float(row, "feature_live_reading_minus_high", "live_reading_minus_high") or 0.0
            ),
            "minutes_since_cutoff": float(
                _feature_float(row, "feature_minutes_since_cutoff", "minutes_since_cutoff") or 0.0
            ),
            "raw_wu_history_high_c": float(_feature_float(row, "raw_wu_history_high_c") or 0.0),
            "raw_wu_max_since_7am_c": float(_feature_float(row, "raw_wu_max_since_7am_c") or 0.0),
            "raw_open_meteo_max_c": float(_feature_float(row, "raw_open_meteo_max_c") or 0.0),
            "raw_weather_forecast_max_c": float(_feature_float(row, "raw_weather_forecast_max_c") or 0.0),
            "market_id": row.get("market_id") or "",
            "bin_type": row.get("bin_type") or row.get("bin_kind") or "",
            "forecast_gap_bucket": row.get("feature_forecast_gap_bucket") or row.get("forecast_gap_bucket") or "",
            "cloud_group": row.get("feature_cloud_group") or row.get("cloud_group") or "",
            "wind_group": row.get("feature_wind_group") or row.get("wind_group") or "",
            "live_reading_gap_bucket": (
                row.get("feature_live_reading_gap_bucket") or row.get("live_reading_gap_bucket") or ""
            ),
            "minutes_since_cutoff_bucket": (
                row.get("feature_minutes_since_cutoff_bucket") or row.get("minutes_since_cutoff_bucket") or ""
            ),
        })
    return pd.DataFrame.from_records(records)


def fit_late_day_calibrator(train_rows: list[dict[str, Any]]):
    outcomes = [int(row.get("outcome") or 0) for row in train_rows]
    if len(train_rows) < 4 or len(set(outcomes)) < 2:
        return None
    transformer = ColumnTransformer(
        [
            ("numeric", StandardScaler(), CALIBRATOR_NUMERIC_FEATURES),
            ("categorical", OneHotEncoder(handle_unknown="ignore"), CALIBRATOR_CATEGORICAL_FEATURES),
        ]
    )
    model = make_pipeline(
        transformer,
        LogisticRegression(C=CALIBRATOR_C, max_iter=5000),
    )
    model.fit(calibrator_frame(train_rows), outcomes)
    return model


def safe_lock_in_group(rows: list[dict[str, Any]], slots: set[int]) -> bool:
    if not rows:
        return False
    row = rows[0]
    slot = int(row.get("time_slot_minute") or 0)
    if slot not in slots or slot < SAFE_MIN_SLOT:
        return False
    forecast_gap = _feature_float(row, "feature_forecast_gap", "forecast_gap")
    if forecast_gap is None or forecast_gap > SAFE_FORECAST_GAP_MAX:
        return False
    high_so_far = _feature_float(row, "feature_high_so_far", "high_so_far")
    wu_history_high = _feature_float(row, "raw_wu_history_high_c")
    if (
        high_so_far is not None
        and wu_history_high is not None
        and wu_history_high > high_so_far + SAFE_WU_HISTORY_HIGH_TOLERANCE
    ):
        return False
    hours_at_peak = _feature_float(row, "feature_hours_at_peak", "hours_at_peak")
    if hours_at_peak is not None and hours_at_peak < SAFE_HOURS_AT_PEAK_MIN:
        return False
    warming_rate = _feature_float(row, "feature_warming_rate_2h", "warming_rate_2h")
    if warming_rate is not None and warming_rate > SAFE_WARMING_RATE_MAX:
        return False
    live_gap = _feature_float(row, "feature_live_reading_minus_high", "live_reading_minus_high")
    if live_gap is not None and live_gap > SAFE_LIVE_READING_MINUS_HIGH_MAX:
        return False
    return True


def group_gated_calibrator_rows(
    rows: list[dict[str, Any]],
    slots: set[int],
    model,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[
            (
                row.get("market_id"),
                row.get("target_date"),
                row.get("snapshot_id"),
                row.get("time_slot_minute"),
            )
        ].append(row)
    output = []
    safe_groups = 0
    changed_groups = 0
    changed_rows = 0
    for snapshot_rows in grouped.values():
        if model is None or not safe_lock_in_group(snapshot_rows, slots):
            output.extend(dict(row) for row in snapshot_rows)
            continue
        safe_groups += 1
        probabilities = model.predict_proba(calibrator_frame(snapshot_rows))[:, 1]
        weights = []
        for row, probability in zip(snapshot_rows, probabilities):
            current = safe_float(row.get("model_probability")) or 0.0
            blended = ((1.0 - CALIBRATOR_BLEND) * current) + (CALIBRATOR_BLEND * float(probability))
            extrapolated = current + (CALIBRATOR_EXTRAPOLATION * (blended - current))
            weights.append(max(0.0, extrapolated) ** CALIBRATOR_POWER)
        total = sum(weights)
        if total <= 0:
            output.extend(dict(row) for row in snapshot_rows)
            continue
        group_changed = False
        for row, weight in zip(snapshot_rows, weights):
            item = dict(row)
            candidate_probability = max(0.0, float(weight)) / total
            current_probability = safe_float(row.get("model_probability")) or 0.0
            item["model_probability"] = candidate_probability
            if abs(candidate_probability - current_probability) > 1e-12:
                group_changed = True
                changed_rows += 1
            output.append(item)
        if group_changed:
            changed_groups += 1
    metadata = {
        "calibrator_enabled": model is not None,
        "total_snapshot_groups": len(grouped),
        "safe_snapshot_groups": safe_groups,
        "changed_snapshot_groups": changed_groups,
        "changed_rows": changed_rows,
        "numeric_features": list(CALIBRATOR_NUMERIC_FEATURES),
        "categorical_features": list(CALIBRATOR_CATEGORICAL_FEATURES),
        "logistic_c": CALIBRATOR_C,
        "blend_with_logistic_probability": CALIBRATOR_BLEND,
        "extrapolation_from_current": CALIBRATOR_EXTRAPOLATION,
        "partition_power": CALIBRATOR_POWER,
        "safe_gate": {
            "min_time_slot_minute": SAFE_MIN_SLOT,
            "max_forecast_gap": SAFE_FORECAST_GAP_MAX,
            "min_hours_at_peak_when_present": SAFE_HOURS_AT_PEAK_MIN,
            "max_warming_rate_2h_when_present": SAFE_WARMING_RATE_MAX,
            "max_live_reading_minus_high_when_present": SAFE_LIVE_READING_MINUS_HIGH_MAX,
            "max_wu_history_high_above_feature_high": SAFE_WU_HISTORY_HIGH_TOLERANCE,
        },
    }
    return output, metadata


def lock_in_candidate_rows(rows: list[dict[str, Any]], slots: set[int], factor: float) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[
            (
                row.get("market_id"),
                row.get("target_date"),
                row.get("snapshot_id"),
                row.get("time_slot_minute"),
            )
        ].append(row)
    output = []
    for snapshot_rows in grouped.values():
        slot = snapshot_rows[0].get("time_slot_minute")
        if slot not in slots or float(factor) == 1.0:
            output.extend(dict(row) for row in snapshot_rows)
            continue
        weights = []
        for row in snapshot_rows:
            high_so_far = safe_float(row.get("feature_high_so_far"))
            match = bin_covers_value(row, high_so_far)
            weight = max(0.0, float(row.get("model_probability") or 0.0))
            if match:
                weight *= float(factor)
            weights.append(weight)
        total = sum(weights)
        for row, weight in zip(snapshot_rows, weights):
            item = dict(row)
            if total > 0:
                item["model_probability"] = weight / total
            output.append(item)
    return output


def split_dates(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    dates = sorted({row.get("target_date") for row in rows if row.get("target_date")})
    if len(dates) <= 1:
        return {"train_dates": dates, "eval_dates": dates}
    cut = max(1, len(dates) // 2)
    return {"train_dates": dates[:cut], "eval_dates": dates[cut:]}


def rows_for_dates(rows: list[dict[str, Any]], dates: list[str]) -> list[dict[str, Any]]:
    date_set = set(dates)
    return [row for row in rows if row.get("target_date") in date_set]


def compare_summary(current_rows: list[dict[str, Any]], candidate_rows: list[dict[str, Any]]) -> dict[str, Any]:
    current = summarize_rows(current_rows) or {}
    candidate = summarize_rows(candidate_rows) or {}
    current_delta_vs_market = (
        current.get("model_brier") - current.get("market_brier")
        if current.get("model_brier") is not None and current.get("market_brier") is not None
        else None
    )
    candidate_delta_vs_market = (
        candidate.get("model_brier") - current.get("market_brier")
        if candidate.get("model_brier") is not None and current.get("market_brier") is not None
        else None
    )
    current_logloss_delta_vs_market = (
        current.get("model_logloss") - current.get("market_logloss")
        if current.get("model_logloss") is not None and current.get("market_logloss") is not None
        else None
    )
    candidate_logloss_delta_vs_market = (
        candidate.get("model_logloss") - current.get("market_logloss")
        if candidate.get("model_logloss") is not None and current.get("market_logloss") is not None
        else None
    )
    return {
        "n": candidate.get("n", current.get("n", 0)),
        "market_days": candidate.get("market_days", current.get("market_days")),
        "candidate_brier": candidate.get("model_brier"),
        "current_brier": current.get("model_brier"),
        "market_brier": current.get("market_brier"),
        "delta_vs_current": (
            candidate.get("model_brier") - current.get("model_brier")
            if candidate.get("model_brier") is not None and current.get("model_brier") is not None
            else None
        ),
        "current_delta_vs_market": current_delta_vs_market,
        "delta_vs_market": candidate_delta_vs_market,
        "market_gap_shrink": (
            current_delta_vs_market - candidate_delta_vs_market
            if current_delta_vs_market is not None and candidate_delta_vs_market is not None
            else None
        ),
        "candidate_logloss": candidate.get("model_logloss"),
        "current_logloss": current.get("model_logloss"),
        "market_logloss": current.get("market_logloss"),
        "logloss_delta_vs_current": (
            candidate.get("model_logloss") - current.get("model_logloss")
            if candidate.get("model_logloss") is not None and current.get("model_logloss") is not None
            else None
        ),
        "current_logloss_delta_vs_market": current_logloss_delta_vs_market,
        "logloss_delta_vs_market": candidate_logloss_delta_vs_market,
        "market_logloss_gap_shrink": (
            current_logloss_delta_vs_market - candidate_logloss_delta_vs_market
            if current_logloss_delta_vs_market is not None and candidate_logloss_delta_vs_market is not None
            else None
        ),
        "winner_candidate_probability": candidate.get("winner_model_probability"),
        "winner_current_probability": current.get("winner_model_probability"),
        "winner_market_probability": current.get("winner_market_probability"),
    }


def select_factor(rows: list[dict[str, Any]], slots: set[int], factors: tuple[float, ...]) -> dict[str, Any]:
    candidates = []
    for factor in factors:
        transformed = lock_in_candidate_rows(rows, slots, factor)
        summary = compare_summary(rows, transformed)
        candidates.append({"factor": float(factor), "summary": summary})
    best = min(
        candidates,
        key=lambda item: (
            safe_float(item["summary"].get("candidate_brier")) if item["summary"].get("candidate_brier") is not None else math.inf,
            abs(float(item["factor"]) - 1.0),
        ),
    )
    return {"selected_factor": best["factor"], "candidates": candidates, "selected_summary": best["summary"]}


def overlock_guardrail(rows: list[dict[str, Any]], slots: set[int], factor: float) -> dict[str, Any]:
    risky_groups = []
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("time_slot_minute") not in slots:
            continue
        grouped[(row.get("market_id"), row.get("target_date"), row.get("snapshot_id"))].append(row)
    for key, snapshot_rows in grouped.items():
        high_rows = [
            row for row in snapshot_rows
            if bin_covers_value(row, safe_float(row.get("feature_high_so_far")))
        ]
        if not high_rows:
            continue
        if not any(int(row.get("outcome") or 0) == 1 for row in high_rows):
            risky_groups.append(key)
    current_rows = [
        row for key in risky_groups for row in grouped.get(key, [])
    ]
    candidate_rows = lock_in_candidate_rows(current_rows, slots, factor)
    summary = compare_summary(current_rows, candidate_rows)
    return {
        "risky_snapshot_count": len(risky_groups),
        "summary": summary,
        "status": "PASS" if not risky_groups or (summary.get("delta_vs_current") or 0.0) <= 0.0 else "BLOCK",
    }


def row_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("market_id"),
        row.get("target_date"),
        row.get("snapshot_id"),
        row.get("time_slot_minute"),
        row.get("band_key"),
        row.get("bin_kind") or row.get("bin_type"),
        row.get("bin_value_c") or row.get("bin_value"),
        row.get("bin_value_hi"),
    )


def replace_rows(
    source_rows: list[dict[str, Any]],
    replacement_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    replacements = {row_key(row): row for row in replacement_rows}
    return [dict(replacements.get(row_key(row), row)) for row in source_rows]


def overlock_candidate_guardrail(
    current_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    slots: set[int],
) -> dict[str, Any]:
    risky_keys = []
    current_grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    candidate_grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in current_rows:
        if row.get("time_slot_minute") not in slots:
            continue
        current_grouped[
            (
                row.get("market_id"),
                row.get("target_date"),
                row.get("snapshot_id"),
                row.get("time_slot_minute"),
            )
        ].append(row)
    for row in candidate_rows:
        if row.get("time_slot_minute") not in slots:
            continue
        candidate_grouped[
            (
                row.get("market_id"),
                row.get("target_date"),
                row.get("snapshot_id"),
                row.get("time_slot_minute"),
            )
        ].append(row)
    for key, snapshot_rows in current_grouped.items():
        high_rows = [
            row for row in snapshot_rows
            if bin_covers_value(row, safe_float(row.get("feature_high_so_far")))
        ]
        if not high_rows:
            continue
        if not any(int(row.get("outcome") or 0) == 1 for row in high_rows):
            risky_keys.append(key)
    risky_current_rows = [
        row for key in risky_keys for row in current_grouped.get(key, [])
    ]
    risky_candidate_rows = [
        row for key in risky_keys for row in candidate_grouped.get(key, current_grouped.get(key, []))
    ]
    summary = compare_summary(risky_current_rows, risky_candidate_rows)
    current_by_key = {row_key(row): row for row in risky_current_rows}
    changed_rows = 0
    for row in risky_candidate_rows:
        current = current_by_key.get(row_key(row))
        if current is None:
            continue
        candidate_probability = safe_float(row.get("model_probability")) or 0.0
        current_probability = safe_float(current.get("model_probability")) or 0.0
        if abs(candidate_probability - current_probability) > 1e-12:
            changed_rows += 1
    return {
        "risky_snapshot_count": len(risky_keys),
        "changed_risky_rows": changed_rows,
        "summary": summary,
        "status": "PASS" if not risky_keys or (summary.get("delta_vs_current") or 0.0) <= 0.0 else "BLOCK",
    }


def scope_guardrails(
    current_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    slots: set[int],
) -> list[dict[str, Any]]:
    output = []
    for name, predicate in (
        ("predawn", lambda row: int(row.get("time_slot_minute") or 0) < 6 * 60),
        ("ramp_midday", lambda row: row.get("time_slot_regime") == "ramp_midday"),
        ("non_selected_late_day", lambda row: int(row.get("time_slot_minute") or 0) >= 15 * 60),
    ):
        current_slice = [
            row for row in current_rows
            if predicate(row) and row.get("time_slot_minute") not in slots
        ]
        if not current_slice:
            continue
        keys = {row_key(row) for row in current_slice}
        candidate_slice = [row for row in candidate_rows if row_key(row) in keys]
        summary = compare_summary(current_slice, candidate_slice)
        output.append({
            "slice": name,
            "rows": summary.get("n", 0),
            "market_days": summary.get("market_days"),
            "delta_vs_current": summary.get("delta_vs_current"),
            "logloss_delta_vs_current": summary.get("logloss_delta_vs_current"),
            "status": (
                "PASS"
                if abs(safe_float(summary.get("delta_vs_current")) or 0.0) <= 1e-12
                and abs(safe_float(summary.get("logloss_delta_vs_current")) or 0.0) <= 1e-12
                else "BLOCK"
            ),
            "reason": "candidate is scoped to selected late-day slots",
        })
    return output


def build_scored_rows(
    labels_csv=DEFAULT_LABELS_CSV,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    quality_grades=DEFAULT_QUALITY_GRADES,
) -> list[dict[str, Any]]:
    labels, _skipped = discover_labeled_folders(
        labels_csv=labels_csv,
        snapshots_root=snapshots_root,
        quality_grades=quality_grades,
        markets=[],
        start_date=None,
        end_date=None,
    )
    rows = []
    for item in labels:
        scored, _day = score_folder(item["folder"], item["label"])
        rows.extend(scored)
    return ten_minute_checkpoint_rows(rows)


def build_payload(
    *,
    ten_minute_report=DEFAULT_TEN_MINUTE_REPORT,
    labels_csv=DEFAULT_LABELS_CSV,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    factor_grid=DEFAULT_FACTOR_GRID,
    top_slots=DEFAULT_TOP_SLOTS,
    market_tol=DEFAULT_MARKET_TOL,
    min_current_improvement=DEFAULT_MIN_CURRENT_IMPROVEMENT,
    min_market_gap_shrink=DEFAULT_MIN_MARKET_GAP_SHRINK,
) -> dict[str, Any]:
    checkpoint_rows = build_scored_rows(labels_csv=labels_csv, snapshots_root=snapshots_root)
    slots = late_blocker_slots(ten_minute_report, top_slots=top_slots)
    target_rows = [row for row in checkpoint_rows if row.get("time_slot_minute") in slots]
    split = split_dates(target_rows)
    train_rows = rows_for_dates(target_rows, split["train_dates"])
    eval_rows = rows_for_dates(target_rows, split["eval_dates"])
    model = fit_late_day_calibrator(train_rows)
    candidate_target_rows, calibration_metadata = group_gated_calibrator_rows(target_rows, slots, model)
    candidate_all_rows = replace_rows(checkpoint_rows, candidate_target_rows)
    candidate_train_rows = rows_for_dates(candidate_target_rows, split["train_dates"])
    candidate_eval_rows = rows_for_dates(candidate_target_rows, split["eval_dates"])
    all_summary = compare_summary(target_rows, candidate_target_rows)
    train_summary = compare_summary(train_rows, candidate_train_rows)
    eval_summary = compare_summary(eval_rows, candidate_eval_rows)
    guardrail = overlock_candidate_guardrail(target_rows, candidate_target_rows, slots)
    scoped_guardrails = scope_guardrails(checkpoint_rows, candidate_all_rows, slots)
    scoped_blockers = [row for row in scoped_guardrails if row.get("status") != "PASS"]
    blockers = []
    if (safe_float(eval_summary.get("delta_vs_current")) or 0.0) > -float(min_current_improvement):
        blockers.append({
            "gate": "late_day_current_improvement",
            "detail": (
                f"eval Brier delta vs current {fmt_signed(eval_summary.get('delta_vs_current'))} "
                f"does not clear {-float(min_current_improvement):+.4f}"
            ),
        })
    if (safe_float(eval_summary.get("logloss_delta_vs_current")) or 0.0) >= 0.0:
        blockers.append({
            "gate": "late_day_current_logloss_improvement",
            "detail": (
                "eval log-loss delta vs current "
                f"{fmt_signed(eval_summary.get('logloss_delta_vs_current'))} is not negative"
            ),
        })
    if (safe_float(eval_summary.get("market_gap_shrink")) or 0.0) < float(min_market_gap_shrink):
        blockers.append({
            "gate": "late_day_market_gap_shrink",
            "detail": (
                f"eval Brier market-gap shrink {fmt_signed(eval_summary.get('market_gap_shrink'))} "
                f"does not clear +{float(min_market_gap_shrink):.4f}; remaining gap is "
                f"{fmt_signed(eval_summary.get('delta_vs_market'))}"
            ),
        })
    if (safe_float(eval_summary.get("market_logloss_gap_shrink")) or 0.0) <= 0.0:
        blockers.append({
            "gate": "late_day_market_logloss_gap_shrink",
            "detail": (
                "eval log-loss market-gap shrink "
                f"{fmt_signed(eval_summary.get('market_logloss_gap_shrink'))} is not positive"
            ),
        })
    if (
        safe_float(eval_summary.get("winner_candidate_probability")) is None
        or safe_float(eval_summary.get("winner_current_probability")) is None
        or safe_float(eval_summary.get("winner_candidate_probability"))
        <= safe_float(eval_summary.get("winner_current_probability"))
    ):
        blockers.append({
            "gate": "late_day_winner_probability_lift",
            "detail": "eval winner probability did not increase versus current",
        })
    if guardrail.get("status") != "PASS":
        blockers.append({
            "gate": "overlock_guardrail",
            "detail": f"{guardrail.get('risky_snapshot_count')} high-so-far mismatch snapshot(s) regress under candidate",
        })
    if scoped_blockers:
        blockers.append({
            "gate": "late_day_scope_guardrail",
            "detail": f"{len(scoped_blockers)} untouched-scope guardrail row(s) blocked",
        })
    slot_summaries = [
        row for row in summarize_by_slot(checkpoint_rows)
        if row.get("time_slot_minute") in slots
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": "PASS" if not blockers else "BLOCK",
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else {},
        "blockers": blockers,
        "candidate_policy": {
            "variant_id": "late_day_group_gated_logistic_lock_in",
            "uses_market_features": False,
            "scope": (
                "fit a no-market logistic scorer on selected late-day train rows, then normalize only "
                "safe late-day groups where forecast and observed-high evidence say the high has likely stood"
            ),
            "slot_labels": [row.get("time_slot_label") for row in sorted(slot_summaries, key=lambda item: item["time_slot_minute"])],
            "feature_contract": LATE_DAY_FEATURE_CONTRACT,
            "calibration": calibration_metadata,
        },
        "inputs": {
            "ten_minute_report": str(ten_minute_report),
            "top_slots": int(top_slots),
            "legacy_factor_grid": list(factor_grid),
            "legacy_market_tolerance_reference": float(market_tol),
            "min_current_improvement": float(min_current_improvement),
            "min_market_gap_shrink": float(min_market_gap_shrink),
        },
        "split": split,
        "train_summary": train_summary,
        "all_summary": all_summary,
        "eval_summary": eval_summary,
        "overlock_guardrail": guardrail,
        "scope_guardrails": scoped_guardrails,
        "slot_casebook": slot_summaries,
    }


def _summary_rows(payload: dict[str, Any]) -> list[list[Any]]:
    policy = payload.get("candidate_policy") or {}
    calibration = policy.get("calibration") or {}
    return [
        ["Status", payload.get("status")],
        ["Blockers", payload.get("blocker_count")],
        ["First blocker", (payload.get("first_blocker") or {}).get("gate") or "-"],
        ["Variant", policy.get("variant_id")],
        ["Calibrator enabled", calibration.get("calibrator_enabled")],
        ["Safe groups changed", calibration.get("changed_snapshot_groups")],
        ["Rows changed", calibration.get("changed_rows")],
        ["Slots", ", ".join(policy.get("slot_labels") or [])],
        ["Train dates", ", ".join((payload.get("split") or {}).get("train_dates") or [])],
        ["Eval dates", ", ".join((payload.get("split") or {}).get("eval_dates") or [])],
    ]


def _metric_rows(rows: list[tuple[str, dict[str, Any]]]) -> list[list[Any]]:
    return [
        [
            label,
            summary.get("n"),
            summary.get("market_days"),
            fmt_num(summary.get("candidate_brier")),
            fmt_num(summary.get("current_brier")),
            fmt_num(summary.get("market_brier")),
            fmt_signed(summary.get("delta_vs_current")),
            fmt_signed(summary.get("delta_vs_market")),
            fmt_signed(summary.get("market_gap_shrink")),
            fmt_signed(summary.get("logloss_delta_vs_current")),
            fmt_signed(summary.get("market_logloss_gap_shrink")),
            fmt_num(summary.get("winner_candidate_probability")),
            fmt_num(summary.get("winner_current_probability")),
            fmt_num(summary.get("winner_market_probability")),
        ]
        for label, summary in rows
    ]


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Late-Day Lock-In Repair Validation",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(["Field", "Value"], _summary_rows(payload))
    lines += ["", "## Candidate Metrics", ""]
    lines += markdown_table(
        [
            "Slice",
            "Rows",
            "Days",
            "Candidate Brier",
            "Current Brier",
            "Market Brier",
            "Delta Current",
            "Delta Market",
            "Market Gap Shrink",
            "LogLoss Delta Current",
            "LogLoss Gap Shrink",
            "Winner Candidate P",
            "Winner Current P",
            "Winner Market P",
        ],
        _metric_rows([
            ("all selected slots", payload.get("all_summary") or {}),
            ("train selected slots", payload.get("train_summary") or {}),
            ("eval selected slots", payload.get("eval_summary") or {}),
            ("overlock guardrail", (payload.get("overlock_guardrail") or {}).get("summary") or {}),
        ]),
    )
    if payload.get("scope_guardrails"):
        lines += ["", "## Scope Guardrails", ""]
        lines += markdown_table(
            ["Slice", "Rows", "Days", "Brier Delta Current", "LogLoss Delta Current", "Status"],
            [
                [
                    row.get("slice"),
                    row.get("rows"),
                    row.get("market_days"),
                    fmt_signed(row.get("delta_vs_current")),
                    fmt_signed(row.get("logloss_delta_vs_current")),
                    row.get("status"),
                ]
                for row in payload.get("scope_guardrails") or []
            ],
        )
    if payload.get("blockers"):
        lines += ["", "## Blockers", ""]
        lines += markdown_table(
            ["Gate", "Detail"],
            [[row.get("gate"), row.get("detail")] for row in payload.get("blockers") or []],
        )
    lines += ["", "## Slot Casebook", ""]
    lines += markdown_table(
        ["Slot", "Rows", "Days", "Model Brier", "Market Brier", "Brier Delta", "Winner Model P", "Winner Market P"],
        [
            [
                row.get("time_slot_label"),
                row.get("n"),
                row.get("market_days"),
                fmt_num(row.get("model_brier")),
                fmt_num(row.get("market_brier")),
                fmt_signed(row.get("brier_delta")),
                fmt_num(row.get("winner_model_probability")),
                fmt_num(row.get("winner_market_probability")),
            ]
            for row in payload.get("slot_casebook") or []
        ],
    )
    return "\n".join(lines)


def write_outputs(payload: dict[str, Any], json_out=DEFAULT_OUT, report_out=DEFAULT_REPORT) -> tuple[Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate late-day lock-in saturation repair.")
    parser.add_argument("--ten-minute-report", default=str(DEFAULT_TEN_MINUTE_REPORT))
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--factor-grid", default=",".join(str(item) for item in DEFAULT_FACTOR_GRID))
    parser.add_argument("--top-slots", type=int, default=DEFAULT_TOP_SLOTS)
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--min-current-improvement", type=float, default=DEFAULT_MIN_CURRENT_IMPROVEMENT)
    parser.add_argument("--min-market-gap-shrink", type=float, default=DEFAULT_MIN_MARKET_GAP_SHRINK)
    parser.add_argument("--json-out", default=str(DEFAULT_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT))
    return parser


def _parse_factor_grid(value: str) -> tuple[float, ...]:
    return tuple(float(item.strip()) for item in str(value).split(",") if item.strip())


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_payload(
        ten_minute_report=args.ten_minute_report,
        labels_csv=args.labels_csv,
        snapshots_root=args.snapshots_root,
        factor_grid=_parse_factor_grid(args.factor_grid),
        top_slots=args.top_slots,
        market_tol=args.market_tol,
        min_current_improvement=args.min_current_improvement,
        min_market_gap_shrink=args.min_market_gap_shrink,
    )
    json_out, report_out = write_outputs(payload, args.json_out, args.report_out)
    print(f"Wrote {json_out}")
    print(f"Wrote {report_out}")
    print(f"Late-day lock-in repair validation: {payload['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
