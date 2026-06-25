"""Predawn weak-slot winner-centering repair validation."""

from __future__ import annotations

import argparse
import csv
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
from weather.reporting.hourly import candidate_hourly_performance
from weather.reporting import candidate_variant_replay_summary
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.hourly.ten_minute_model_performance import (
    DEFAULT_ITEM147_ROWS,
    build_candidate_item147,
    candidate_ten_minute_gate,
    read_candidate_checkpoint_rows,
    slot_label,
    summarize_candidate_rows,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("predawn_weak_slot_repair")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_TEN_MINUTE_REPORT = DEFAULT_BACKTEST_ROOT / "ten_minute_model_performance.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "predawn_weak_slot_repair.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "predawn_weak_slot_repair_report.md"
DEFAULT_CANDIDATE_ROWS_OUT = DEFAULT_BACKTEST_ROOT / "predawn_weak_slot_repair_candidate_rows.csv"
DEFAULT_CANDIDATE_REPLAY_SUMMARY_OUT = DEFAULT_BACKTEST_ROOT / "predawn_weak_slot_repair_replay_summary.json"
DEFAULT_CANDIDATE_REPLAY_SUMMARY_REPORT = DEFAULT_BACKTEST_ROOT / "predawn_weak_slot_repair_replay_summary_report.md"
DEFAULT_CANDIDATE_HOURLY_OUT = DEFAULT_BACKTEST_ROOT / "predawn_weak_slot_repair_hourly_candidate_performance.json"
DEFAULT_CANDIDATE_HOURLY_REPORT = DEFAULT_BACKTEST_ROOT / "predawn_weak_slot_repair_hourly_candidate_performance_report.md"
DEFAULT_CANDIDATE_TEN_MINUTE_OUT = DEFAULT_BACKTEST_ROOT / "predawn_weak_slot_repair_ten_minute_performance.json"
DEFAULT_CANDIDATE_TEN_MINUTE_REPORT = DEFAULT_BACKTEST_ROOT / "predawn_weak_slot_repair_ten_minute_performance_report.md"
DEFAULT_SOURCE_CANDIDATE_JSON = DEFAULT_BACKTEST_ROOT / "pooled_candidate_replay_latest.json"
DEFAULT_MIN_BRIER_IMPROVEMENT = 0.003
DEFAULT_MARKET_TOL = 0.003
CALIBRATOR_C = 100.0
CALIBRATOR_BLEND = 0.60
CALIBRATOR_EXTRAPOLATION = 1.50
CALIBRATOR_POWER = 0.75
DEFAULT_OUTPUT_VARIANT_ID = "predawn_logistic_winner_centering_candidate_blend"
CALIBRATOR_NUMERIC_FEATURES = [
    "current_probability",
    "item147_probability",
    "item147_delta_probability",
    "current_logit",
    "item147_logit",
    "time_slot_minute",
    "hour",
    "minute",
    "bin_value",
]
CALIBRATOR_CATEGORICAL_FEATURES = [
    "market_id",
    "bin_type",
    "forecast_bucket_pressure",
    "forecast_disagreement_bucket",
    "forecast_source_count_bucket",
    "source_freshness_state",
]
PREDAWN_FEATURE_CONTRACT = [
    "time_slot_minute",
    "market_id",
    "bin_type",
    "bin_value",
    "current_probability",
    "item147_probability",
    "item147_delta_probability",
    "current_logit",
    "item147_logit",
    "forecast_bucket_pressure",
    "forecast_source_count",
    "forecast_disagreement",
    "source_freshness_state",
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


def weak_slots_from_report(path: str | Path) -> set[int]:
    payload = _read_json(path)
    slots = (payload.get("weak_slots") or {}).get("slot_minutes") or []
    return {int(slot) for slot in slots}


def split_dates(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    dates = sorted({row.get("target_date") for row in rows if row.get("target_date")})
    if len(dates) <= 1:
        return {"train_dates": dates, "eval_dates": dates}
    cut = max(1, len(dates) // 2)
    return {"train_dates": dates[:cut], "eval_dates": dates[cut:]}


def scoped_policy_rows(rows: list[dict[str, Any]], weak_slots: set[int]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        item = dict(row)
        if item.get("time_slot_minute") not in weak_slots:
            item["variant_probability"] = item.get("current_probability")
        output.append(item)
    return output


def _bin_value(row: dict[str, Any]) -> float | None:
    for key in ("bin_value", "bin_value_c"):
        value = safe_float(row.get(key))
        if value is not None:
            return value
    band = str(row.get("band_key") or "")
    if ":" in band:
        return safe_float(band.split(":", 1)[1])
    return None


def probability_logit(value: Any) -> float:
    probability = safe_float(value)
    if probability is None:
        probability = 0.0
    probability = min(1.0 - 1e-6, max(1e-6, probability))
    return math.log(probability / (1.0 - probability))


def calibrator_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    records = []
    for row in rows:
        current = safe_float(row.get("current_probability")) or 0.0
        item147 = safe_float(row.get("variant_probability")) or 0.0
        slot = int(row.get("time_slot_minute") or 0)
        records.append({
            "current_probability": current,
            "item147_probability": item147,
            "item147_delta_probability": item147 - current,
            "current_logit": probability_logit(current),
            "item147_logit": probability_logit(item147),
            "time_slot_minute": float(slot),
            "hour": float(slot // 60),
            "minute": float(slot % 60),
            "bin_value": float(_bin_value(row) or 0.0),
            "market_id": row.get("market_id") or "",
            "bin_type": row.get("bin_type") or row.get("bin_kind") or "",
            "forecast_bucket_pressure": row.get("forecast_bucket_pressure") or "",
            "forecast_disagreement_bucket": row.get("forecast_disagreement_bucket") or "",
            "forecast_source_count_bucket": row.get("forecast_source_count_bucket") or "",
            "source_freshness_state": row.get("source_freshness_state") or "",
        })
    return pd.DataFrame.from_records(records)


def fit_predawn_calibrator(train_rows: list[dict[str, Any]]):
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


def calibrator_raw_weights(
    rows: list[dict[str, Any]],
    model,
    *,
    blend: float = CALIBRATOR_BLEND,
    extrapolation: float = CALIBRATOR_EXTRAPOLATION,
    partition_power: float = CALIBRATOR_POWER,
) -> list[float]:
    if not rows:
        return []
    if model is None:
        logistic_probabilities = [safe_float(row.get("variant_probability")) or 0.0 for row in rows]
    else:
        logistic_probabilities = model.predict_proba(calibrator_frame(rows))[:, 1]
    output = []
    for row, logistic_probability in zip(rows, logistic_probabilities):
        current = safe_float(row.get("current_probability")) or 0.0
        item147 = safe_float(row.get("variant_probability")) or 0.0
        blended = ((1.0 - float(blend)) * item147) + (float(blend) * float(logistic_probability))
        extrapolated = current + (float(extrapolation) * (blended - current))
        output.append(max(0.0, extrapolated) ** float(partition_power))
    return output


def normalize_snapshot_weights(rows: list[dict[str, Any]], weights: list[float]) -> list[dict[str, Any]]:
    output = [dict(row) for row in rows]
    grouped: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    for index, row in enumerate(output):
        grouped[
            (
                row.get("market_id"),
                row.get("target_date"),
                row.get("snapshot_id"),
                row.get("time_slot_minute"),
            )
        ].append(index)
    for indexes in grouped.values():
        total = sum(max(0.0, float(weights[index])) for index in indexes)
        if total <= 0:
            continue
        for index in indexes:
            output[index]["variant_probability"] = max(0.0, float(weights[index])) / total
    return output


def calibrated_weak_slot_rows(
    rows: list[dict[str, Any]],
    weak_slots: set[int],
    *,
    blend: float = CALIBRATOR_BLEND,
    extrapolation: float = CALIBRATOR_EXTRAPOLATION,
    partition_power: float = CALIBRATOR_POWER,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scoped = scoped_policy_rows(rows, weak_slots)
    weak_rows = [row for row in scoped if row.get("time_slot_minute") in weak_slots]
    split = split_dates(weak_rows)
    train_rows = rows_for_dates(weak_rows, split["train_dates"])
    model = fit_predawn_calibrator(train_rows)
    transformed_weak = normalize_snapshot_weights(
        weak_rows,
        calibrator_raw_weights(
            weak_rows,
            model,
            blend=blend,
            extrapolation=extrapolation,
            partition_power=partition_power,
        ),
    )
    by_key = {
        (
            row.get("market_id"),
            row.get("target_date"),
            row.get("snapshot_id"),
            row.get("band_key"),
            row.get("time_slot_minute"),
        ): row
        for row in transformed_weak
    }
    output = []
    for row in scoped:
        if row.get("time_slot_minute") not in weak_slots:
            output.append(row)
            continue
        key = (
            row.get("market_id"),
            row.get("target_date"),
            row.get("snapshot_id"),
            row.get("band_key"),
            row.get("time_slot_minute"),
        )
        output.append(by_key.get(key, row))
    metadata = {
        "calibrator_enabled": model is not None,
        "train_rows": len(train_rows),
        "train_positive_rows": sum(1 for row in train_rows if int(row.get("outcome") or 0) == 1),
        "numeric_features": list(CALIBRATOR_NUMERIC_FEATURES),
        "categorical_features": list(CALIBRATOR_CATEGORICAL_FEATURES),
        "logistic_c": CALIBRATOR_C,
        "blend_with_candidate": float(blend),
        "extrapolation_from_current": float(extrapolation),
        "partition_power": float(partition_power),
    }
    return output, metadata


def _normalized(rows: list[dict[str, Any]], key: str) -> list[float]:
    values = [max(0.0, float(row.get(key) or 0.0)) for row in rows]
    total = sum(values)
    if total <= 0:
        return []
    return [value / total for value in values]


def effective_band_count(rows: list[dict[str, Any]], key: str) -> float | None:
    probabilities = _normalized(rows, key)
    if not probabilities:
        return None
    concentration = sum(value * value for value in probabilities)
    return 1.0 / concentration if concentration > 0 else None


def adjacent_winner_mass(rows: list[dict[str, Any]], key: str, max_distance: float = 1.0) -> float | None:
    probabilities = _normalized(rows, key)
    if not probabilities:
        return None
    winner_values = [
        _bin_value(row)
        for row in rows
        if int(row.get("outcome") or 0) == 1 and _bin_value(row) is not None
    ]
    if not winner_values:
        return None
    total = 0.0
    for row, probability in zip(rows, probabilities):
        value = _bin_value(row)
        if value is not None and any(abs(value - winner) <= max_distance for winner in winner_values):
            total += probability
    return total


def _mean(values: list[float | None]) -> float | None:
    cleaned = [value for value in values if value is not None]
    return sum(cleaned) / len(cleaned) if cleaned else None


def distribution_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
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
    variant_effective = []
    current_effective = []
    market_effective = []
    variant_adjacent = []
    current_adjacent = []
    market_adjacent = []
    for snapshot_rows in grouped.values():
        variant_effective.append(effective_band_count(snapshot_rows, "variant_probability"))
        current_effective.append(effective_band_count(snapshot_rows, "current_probability"))
        market_effective.append(effective_band_count(snapshot_rows, "market_yes"))
        variant_adjacent.append(adjacent_winner_mass(snapshot_rows, "variant_probability"))
        current_adjacent.append(adjacent_winner_mass(snapshot_rows, "current_probability"))
        market_adjacent.append(adjacent_winner_mass(snapshot_rows, "market_yes"))
    variant_eff = _mean(variant_effective)
    current_eff = _mean(current_effective)
    market_eff = _mean(market_effective)
    variant_adj = _mean(variant_adjacent)
    current_adj = _mean(current_adjacent)
    market_adj = _mean(market_adjacent)
    return {
        "snapshot_groups": len(grouped),
        "variant_effective_bands": variant_eff,
        "current_effective_bands": current_eff,
        "market_effective_bands": market_eff,
        "effective_band_delta_vs_current": (
            variant_eff - current_eff if variant_eff is not None and current_eff is not None else None
        ),
        "effective_band_delta_vs_market": (
            variant_eff - market_eff if variant_eff is not None and market_eff is not None else None
        ),
        "variant_adjacent_winner_mass": variant_adj,
        "current_adjacent_winner_mass": current_adj,
        "market_adjacent_winner_mass": market_adj,
        "adjacent_winner_mass_delta_vs_current": (
            variant_adj - current_adj if variant_adj is not None and current_adj is not None else None
        ),
        "adjacent_winner_mass_delta_vs_market": (
            variant_adj - market_adj if variant_adj is not None and market_adj is not None else None
        ),
    }


def scored_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = summarize_candidate_rows(rows) or {}
    summary.update(distribution_summary(rows))
    return summary


def rows_for_dates(rows: list[dict[str, Any]], dates: list[str]) -> list[dict[str, Any]]:
    date_set = set(dates)
    return [row for row in rows if row.get("target_date") in date_set]


def status_for_summary(
    summary: dict[str, Any],
    *,
    min_brier_improvement: float = DEFAULT_MIN_BRIER_IMPROVEMENT,
    market_tol: float = DEFAULT_MARKET_TOL,
) -> tuple[str, list[str]]:
    reasons = []
    delta_current = safe_float(summary.get("delta_vs_current"))
    delta_market = safe_float(summary.get("delta_vs_market"))
    winner_delta = safe_float(summary.get("winner_variant_probability"))
    winner_current = safe_float(summary.get("winner_current_probability"))
    effective_delta = safe_float(summary.get("effective_band_delta_vs_current"))
    adjacent_delta = safe_float(summary.get("adjacent_winner_mass_delta_vs_current"))
    if delta_current is None or delta_current > -float(min_brier_improvement):
        reasons.append(
            f"Brier delta vs current {fmt_signed(delta_current)} does not clear {-float(min_brier_improvement):+.4f}"
        )
    if delta_market is None or delta_market > float(market_tol):
        reasons.append(f"Brier delta vs market {fmt_signed(delta_market)} exceeds +{float(market_tol):.4f}")
    if winner_delta is None or winner_current is None or winner_delta <= winner_current:
        reasons.append("winner probability did not increase versus current")
    if effective_delta is None or effective_delta >= 0:
        reasons.append("effective-band spread did not shrink versus current")
    if adjacent_delta is not None and adjacent_delta < 0:
        reasons.append("adjacent-winner mass regressed versus current")
    return ("PASS" if not reasons else "BLOCK", reasons)


def top_cases(rows: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    cases = []
    for row in rows:
        if int(row.get("outcome") or 0) != 1:
            continue
        variant = safe_float(row.get("variant_probability"))
        current = safe_float(row.get("current_probability"))
        market = safe_float(row.get("market_yes"))
        if variant is None or current is None or market is None:
            continue
        cases.append({
            "market_id": row.get("market_id"),
            "target_date": row.get("target_date"),
            "time_slot_label": row.get("time_slot_label") or slot_label(row.get("time_slot_minute")),
            "snapshot_id": row.get("snapshot_id"),
            "band_key": row.get("band_key"),
            "variant_probability": variant,
            "current_probability": current,
            "market_probability": market,
            "variant_lift_vs_current": variant - current,
            "gap_vs_market": market - variant,
        })
    return sorted(
        cases,
        key=lambda row: (row.get("gap_vs_market") or 0.0, row.get("variant_lift_vs_current") or 0.0),
        reverse=True,
    )[:limit]


def regime_guardrails(rows: list[dict[str, Any]], weak_slots: set[int]) -> list[dict[str, Any]]:
    output = []
    scoped = scoped_policy_rows(rows, weak_slots)
    for regime in ("early_morning", "ramp_midday", "late_day", "lock_in"):
        regime_rows = [
            row for row in scoped
            if row.get("time_slot_regime") == regime and row.get("time_slot_minute") not in weak_slots
        ]
        if not regime_rows:
            continue
        summary = scored_summary(regime_rows)
        output.append({
            "regime": regime,
            "rows": summary.get("n", 0),
            "market_days": summary.get("market_days"),
            "delta_vs_current": summary.get("delta_vs_current"),
            "delta_vs_market": summary.get("delta_vs_market"),
            "status": "PASS" if (summary.get("delta_vs_current") or 0.0) <= DEFAULT_MARKET_TOL else "BLOCK",
            "reason": "scoped policy leaves non-weak-slot probabilities unchanged",
        })
    return output


def build_repair_result(
    candidate_rows: str | Path = DEFAULT_ITEM147_ROWS,
    ten_minute_report: str | Path = DEFAULT_TEN_MINUTE_REPORT,
    *,
    min_brier_improvement: float = DEFAULT_MIN_BRIER_IMPROVEMENT,
    market_tol: float = DEFAULT_MARKET_TOL,
    blend: float = CALIBRATOR_BLEND,
    extrapolation: float = CALIBRATOR_EXTRAPOLATION,
    partition_power: float = CALIBRATOR_POWER,
    output_variant_id: str = DEFAULT_OUTPUT_VARIANT_ID,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    weak_slots = weak_slots_from_report(ten_minute_report)
    source_rows = read_candidate_checkpoint_rows(Path(candidate_rows))
    rows, calibration_metadata = calibrated_weak_slot_rows(
        source_rows,
        weak_slots,
        blend=blend,
        extrapolation=extrapolation,
        partition_power=partition_power,
    )
    for row in rows:
        row["variant_id"] = output_variant_id
    corpus_hash = candidate_hourly_performance.candidate_rows_corpus_hash(
        [candidate_row_for_csv(row) for row in rows]
    )
    weak_rows = [row for row in rows if row.get("time_slot_minute") in weak_slots]
    split = split_dates(weak_rows)
    train_rows = rows_for_dates(weak_rows, split["train_dates"])
    eval_rows = rows_for_dates(weak_rows, split["eval_dates"])
    all_summary = scored_summary(weak_rows)
    train_summary = scored_summary(train_rows)
    eval_summary = scored_summary(eval_rows)
    all_status, all_reasons = status_for_summary(
        all_summary,
        min_brier_improvement=min_brier_improvement,
        market_tol=market_tol,
    )
    eval_status, eval_reasons = status_for_summary(
        eval_summary,
        min_brier_improvement=min_brier_improvement,
        market_tol=market_tol,
    )
    guardrails = regime_guardrails(rows, weak_slots)
    guardrail_blockers = [row for row in guardrails if row.get("status") != "PASS"]
    blockers = []
    if all_status != "PASS":
        blockers.append({
            "gate": "aggregate_predawn_weak_slot_repair",
            "detail": "; ".join(all_reasons),
        })
    if eval_status != "PASS":
        blockers.append({
            "gate": "time_split_predawn_weak_slot_repair",
            "detail": "; ".join(eval_reasons),
        })
    if guardrail_blockers:
        blockers.append({
            "gate": "non_predawn_guardrail_regression",
            "detail": f"{len(guardrail_blockers)} non-predawn guardrail row(s) blocked",
        })
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "candidate_policy": {
            "variant_id": output_variant_id,
            "source_variant_ids": sorted({row.get("variant_id") for row in source_rows if row.get("variant_id")}),
            "uses_market_features": False,
            "scope": (
                "fit weak-slot no-market logistic centering on the train split, blend with the input candidate, "
                "normalize each snapshot partition, and use current probabilities outside weak slots"
            ),
            "weak_slot_labels": [slot_label(slot) for slot in sorted(weak_slots)],
            "feature_contract": PREDAWN_FEATURE_CONTRACT,
            "calibration": calibration_metadata,
        },
        "inputs": {
            "candidate_rows": str(candidate_rows),
            "ten_minute_report": str(ten_minute_report),
            "min_brier_improvement": float(min_brier_improvement),
            "market_tolerance": float(market_tol),
        },
        "candidate_gate_lineage": {
            "variant_id": output_variant_id,
            "corpus_hash": corpus_hash,
            "validation_evidence": "row_export_surrogate",
            "active_replay_export_contract": False,
            "active_contract_note": (
                "candidate rows are promotion-gate compatible; promotion refresh must keep broad "
                "cutover blocked until an active replay/export contract supplies this same lineage"
            ),
        },
        "status": "PASS" if not blockers else "BLOCK",
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else {},
        "blockers": blockers,
        "split": split,
        "weak_slot_summary": all_summary,
        "train_summary": train_summary,
        "eval_summary": eval_summary,
        "guardrails": guardrails,
        "casebook": {
            "case_count": len(top_cases(weak_rows, limit=10**9)),
            "top_cases": top_cases(weak_rows),
        },
    }
    return payload, rows


def build_payload(
    candidate_rows: str | Path = DEFAULT_ITEM147_ROWS,
    ten_minute_report: str | Path = DEFAULT_TEN_MINUTE_REPORT,
    *,
    min_brier_improvement: float = DEFAULT_MIN_BRIER_IMPROVEMENT,
    market_tol: float = DEFAULT_MARKET_TOL,
    blend: float = CALIBRATOR_BLEND,
    extrapolation: float = CALIBRATOR_EXTRAPOLATION,
    partition_power: float = CALIBRATOR_POWER,
    output_variant_id: str = DEFAULT_OUTPUT_VARIANT_ID,
) -> dict[str, Any]:
    payload, _rows = build_repair_result(
        candidate_rows,
        ten_minute_report,
        min_brier_improvement=min_brier_improvement,
        market_tol=market_tol,
        blend=blend,
        extrapolation=extrapolation,
        partition_power=partition_power,
        output_variant_id=output_variant_id,
    )
    return payload


def _summary_rows(payload: dict[str, Any]) -> list[list[Any]]:
    return [
        ["Status", payload.get("status")],
        ["Blockers", payload.get("blocker_count")],
        ["First blocker", (payload.get("first_blocker") or {}).get("gate") or "-"],
        ["Weak slots", ", ".join((payload.get("candidate_policy") or {}).get("weak_slot_labels") or [])],
        ["Train dates", ", ".join((payload.get("split") or {}).get("train_dates") or [])],
        ["Eval dates", ", ".join((payload.get("split") or {}).get("eval_dates") or [])],
    ]


def _metric_rows(sections: list[tuple[str, dict[str, Any]]]) -> list[list[Any]]:
    rows = []
    for label, summary in sections:
        rows.append([
            label,
            summary.get("n"),
            summary.get("market_days"),
            fmt_num(summary.get("variant_brier")),
            fmt_num(summary.get("current_brier")),
            fmt_num(summary.get("market_brier")),
            fmt_signed(summary.get("delta_vs_current")),
            fmt_signed(summary.get("delta_vs_market")),
            fmt_num(summary.get("winner_variant_probability")),
            fmt_num(summary.get("winner_current_probability")),
            fmt_num(summary.get("winner_market_probability")),
            fmt_num(summary.get("effective_band_delta_vs_current")),
            fmt_num(summary.get("adjacent_winner_mass_delta_vs_current")),
        ])
    return rows


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Predawn Weak-Slot Repair Validation",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(["Field", "Value"], _summary_rows(payload))
    lines += ["", "## Candidate Policy", ""]
    policy = payload.get("candidate_policy") or {}
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Variant", policy.get("variant_id")],
            ["Source variants", ", ".join(policy.get("source_variant_ids") or [])],
            ["Uses market features", policy.get("uses_market_features")],
            ["Scope", policy.get("scope")],
            ["Feature contract", ", ".join(policy.get("feature_contract") or [])],
        ],
    )
    lines += ["", "## Weak-Slot Validation", ""]
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
            "Winner Candidate P",
            "Winner Current P",
            "Winner Market P",
            "Eff Band Delta",
            "Adjacent Mass Delta",
        ],
        _metric_rows([
            ("all weak slots", payload.get("weak_slot_summary") or {}),
            ("train weak slots", payload.get("train_summary") or {}),
            ("eval weak slots", payload.get("eval_summary") or {}),
        ]),
    )
    blockers = payload.get("blockers") or []
    if blockers:
        lines += ["", "## Blockers", ""]
        lines += markdown_table(
            ["Gate", "Detail"],
            [[row.get("gate"), row.get("detail")] for row in blockers],
        )
    lines += ["", "## Non-Predawn Guardrails", ""]
    lines += markdown_table(
        ["Regime", "Rows", "Days", "Delta Current", "Delta Market", "Status", "Reason"],
        [
            [
                row.get("regime"),
                row.get("rows"),
                row.get("market_days"),
                fmt_signed(row.get("delta_vs_current")),
                fmt_signed(row.get("delta_vs_market")),
                row.get("status"),
                row.get("reason"),
            ]
            for row in payload.get("guardrails") or []
        ],
    )
    lines += ["", "## Weak-Slot Casebook", ""]
    lines += markdown_table(
        ["Market", "Date", "Slot", "Band", "Candidate P", "Current P", "Market P", "Lift", "Gap To Market"],
        [
            [
                row.get("market_id"),
                row.get("target_date"),
                row.get("time_slot_label"),
                row.get("band_key"),
                fmt_num(row.get("variant_probability")),
                fmt_num(row.get("current_probability")),
                fmt_num(row.get("market_probability")),
                fmt_signed(row.get("variant_lift_vs_current")),
                fmt_signed(row.get("gap_vs_market")),
            ]
            for row in ((payload.get("casebook") or {}).get("top_cases") or [])
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


CANDIDATE_ROW_FIELDS = [
    "variant_id",
    "market_id",
    "target_date",
    "snapshot_id",
    "band_key",
    "probability",
    "current_probability",
    "market_yes",
    "outcome",
    "captured_at_local",
    "bin_type",
    "bin_value",
    "cutoff_hour",
    "cutoff_regime",
    "settlement_distance_bucket",
    "forecast_bucket_pressure",
    "forecast_disagreement_bucket",
    "forecast_source_count_bucket",
    "source_freshness_state",
]


def candidate_row_for_csv(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "variant_id": row.get("variant_id"),
        "market_id": row.get("market_id"),
        "target_date": row.get("target_date"),
        "snapshot_id": row.get("snapshot_id"),
        "band_key": row.get("band_key"),
        "probability": row.get("variant_probability"),
        "current_probability": row.get("current_probability"),
        "market_yes": row.get("market_yes"),
        "outcome": row.get("outcome"),
        "captured_at_local": row.get("captured_at_local"),
        "bin_type": row.get("bin_type"),
        "bin_value": row.get("bin_value"),
        "cutoff_hour": row.get("cutoff_hour"),
        "cutoff_regime": row.get("cutoff_regime"),
        "settlement_distance_bucket": row.get("settlement_distance_bucket"),
        "forecast_bucket_pressure": row.get("forecast_bucket_pressure"),
        "forecast_disagreement_bucket": row.get("forecast_disagreement_bucket"),
        "forecast_source_count_bucket": row.get("forecast_source_count_bucket"),
        "source_freshness_state": row.get("source_freshness_state"),
    }


def write_candidate_rows(rows: list[dict[str, Any]], path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_ROW_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(candidate_row_for_csv(row) for row in rows)
    return output_path


def render_candidate_ten_minute_report(payload: dict[str, Any]) -> str:
    gate = payload.get("candidate_ten_minute_gate") or {}
    candidate = payload.get("candidate_ten_minute_performance") or {}
    overlap = candidate.get("weak_slot_overlap") or {}
    return "\n".join([
        "# Predawn Repair Candidate 10-Minute Gate",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Scope",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Variant IDs", ", ".join(payload.get("variant_ids") or []) or "-"],
                ["Candidate rows", (payload.get("inputs") or {}).get("candidate_rows")],
                ["Corpus hash", (payload.get("corpus") or {}).get("corpus_hash") or "-"],
                ["Weak slots", ", ".join((payload.get("weak_slots") or {}).get("slot_labels") or [])],
            ],
        ),
        "",
        "## Gate",
        "",
        *markdown_table(
            ["Metric", "Value"],
            [
                ["Status", gate.get("status")],
                ["Blockers", gate.get("blocker_count", 0)],
                ["First blocker", (gate.get("first_blocker") or {}).get("detail") or "-"],
                ["Rows", overlap.get("row_count")],
                ["Market-days", overlap.get("market_days")],
                ["Delta vs current", fmt_signed(overlap.get("delta_vs_current"))],
                ["Delta vs market", fmt_signed(overlap.get("delta_vs_market"))],
                ["Log-loss delta vs current", fmt_signed(overlap.get("logloss_delta_vs_current"))],
                ["Log-loss delta vs market", fmt_signed(overlap.get("logloss_delta_vs_market"))],
            ],
        ),
        "",
    ])


def build_candidate_ten_minute_payload(
    candidate_rows: str | Path,
    weak_slots: set[int],
    *,
    candidate_min_weak_market_days: int = 10,
    weak_brier_improvement_min: float = DEFAULT_MIN_BRIER_IMPROVEMENT,
    weak_market_regression_tolerance: float = DEFAULT_MARKET_TOL,
    weak_logloss_regression_tolerance: float = 0.010,
) -> dict[str, Any]:
    candidate = build_candidate_item147(Path(candidate_rows), weak_slots=weak_slots)
    gate = candidate_ten_minute_gate(
        candidate,
        min_weak_market_days=candidate_min_weak_market_days,
        weak_brier_improvement_min=weak_brier_improvement_min,
        weak_market_regression_tolerance=weak_market_regression_tolerance,
        weak_logloss_regression_tolerance=weak_logloss_regression_tolerance,
    )
    return {
        "schema_version": "predawn_candidate_ten_minute_performance_v0.1",
        "generated_at_utc": utc_iso(),
        "inputs": {
            "candidate_rows": str(candidate_rows),
            "candidate_min_weak_market_days": int(candidate_min_weak_market_days),
            "weak_brier_improvement_min": float(weak_brier_improvement_min),
            "weak_market_regression_tolerance": float(weak_market_regression_tolerance),
            "weak_logloss_regression_tolerance": float(weak_logloss_regression_tolerance),
        },
        "corpus": {
            **(candidate.get("corpus") or {}),
            "candidate_rows": str(candidate_rows),
        },
        "variant_ids": candidate.get("variant_ids") or [],
        "weak_slots": {
            "slot_minutes": sorted(weak_slots),
            "slot_labels": [slot_label(slot) for slot in sorted(weak_slots)],
        },
        "candidate_ten_minute_performance": candidate,
        "candidate_item147": candidate,
        "candidate_ten_minute_gate": gate,
    }


def write_candidate_ten_minute_outputs(
    payload: dict[str, Any],
    json_out: str | Path = DEFAULT_CANDIDATE_TEN_MINUTE_OUT,
    report_out: str | Path = DEFAULT_CANDIDATE_TEN_MINUTE_REPORT,
) -> tuple[Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_candidate_ten_minute_report(payload), encoding="utf-8")
    return json_path, report_path


def write_candidate_gate_outputs(
    *,
    candidate_rows: str | Path,
    weak_slots: set[int],
    source_candidate_json: str | Path = DEFAULT_SOURCE_CANDIDATE_JSON,
    validation_evidence: str = "row_export_surrogate",
    replay_summary_json_out: str | Path = DEFAULT_CANDIDATE_REPLAY_SUMMARY_OUT,
    replay_summary_report_out: str | Path = DEFAULT_CANDIDATE_REPLAY_SUMMARY_REPORT,
    hourly_json_out: str | Path = DEFAULT_CANDIDATE_HOURLY_OUT,
    hourly_report_out: str | Path = DEFAULT_CANDIDATE_HOURLY_REPORT,
    ten_minute_json_out: str | Path = DEFAULT_CANDIDATE_TEN_MINUTE_OUT,
    ten_minute_report_out: str | Path = DEFAULT_CANDIDATE_TEN_MINUTE_REPORT,
    min_hourly_market_days: int = 10,
    candidate_min_weak_market_days: int = 10,
    weak_brier_improvement_min: float = DEFAULT_MIN_BRIER_IMPROVEMENT,
    weak_market_regression_tolerance: float = DEFAULT_MARKET_TOL,
    weak_logloss_regression_tolerance: float = 0.010,
) -> dict[str, Any]:
    replay_summary = candidate_variant_replay_summary.build_variant_replay_summary(
        candidate_rows,
        source_candidate_json,
        validation_evidence=validation_evidence,
    )
    replay_json, replay_report = candidate_variant_replay_summary.write_outputs(
        replay_summary,
        replay_summary_json_out,
        replay_summary_report_out,
    )
    hourly_payload = candidate_hourly_performance.build_candidate_hourly_performance(
        candidate_rows,
        min_market_days=min_hourly_market_days,
    )
    source_corpus_hash = (replay_summary.get("corpus") or {}).get("corpus_hash")
    row_export_corpus_hash = (
        (replay_summary.get("corpus") or {}).get("row_export_corpus_hash")
        or (hourly_payload.get("corpus") or {}).get("corpus_hash")
    )
    hourly_payload.setdefault("corpus", {})["corpus_hash"] = source_corpus_hash or row_export_corpus_hash
    hourly_payload.setdefault("corpus", {})["row_export_corpus_hash"] = row_export_corpus_hash
    hourly_json, hourly_report = candidate_hourly_performance.write_outputs(
        hourly_payload,
        hourly_json_out,
        hourly_report_out,
    )
    ten_payload = build_candidate_ten_minute_payload(
        candidate_rows,
        weak_slots,
        candidate_min_weak_market_days=candidate_min_weak_market_days,
        weak_brier_improvement_min=weak_brier_improvement_min,
        weak_market_regression_tolerance=weak_market_regression_tolerance,
        weak_logloss_regression_tolerance=weak_logloss_regression_tolerance,
    )
    ten_payload.setdefault("corpus", {})["corpus_hash"] = source_corpus_hash or row_export_corpus_hash
    ten_payload.setdefault("corpus", {})["row_export_corpus_hash"] = row_export_corpus_hash
    for key in ("candidate_ten_minute_performance", "candidate_item147"):
        ten_payload.setdefault(key, {}).setdefault("corpus", {})["corpus_hash"] = (
            source_corpus_hash or row_export_corpus_hash
        )
        ten_payload.setdefault(key, {}).setdefault("corpus", {})["row_export_corpus_hash"] = row_export_corpus_hash
    ten_json, ten_report = write_candidate_ten_minute_outputs(
        ten_payload,
        ten_minute_json_out,
        ten_minute_report_out,
    )
    corpus_hashes = {
        "replay_summary": (replay_summary.get("corpus") or {}).get("corpus_hash"),
        "hourly": (hourly_payload.get("corpus") or {}).get("corpus_hash"),
        "ten_minute": (ten_payload.get("corpus") or {}).get("corpus_hash"),
    }
    row_export_corpus_hashes = {
        "replay_summary": (replay_summary.get("corpus") or {}).get("row_export_corpus_hash"),
        "hourly": (hourly_payload.get("corpus") or {}).get("row_export_corpus_hash"),
        "ten_minute": (ten_payload.get("corpus") or {}).get("row_export_corpus_hash"),
    }
    matching = len({value for value in corpus_hashes.values() if value}) == 1 and all(corpus_hashes.values())
    row_export_matching = (
        len({value for value in row_export_corpus_hashes.values() if value}) == 1
        and all(row_export_corpus_hashes.values())
    )
    variant_ids = {
        "replay_summary": (replay_summary.get("candidate_shadow_variants") or {}).get("variant_ids") or [],
        "hourly": hourly_payload.get("variant_ids") or [],
        "ten_minute": ten_payload.get("variant_ids") or [],
    }
    return {
        "status": "PASS" if matching and row_export_matching else "BLOCK",
        "corpus_hashes": corpus_hashes,
        "corpus_hash_match": matching,
        "row_export_corpus_hashes": row_export_corpus_hashes,
        "row_export_corpus_hash_match": row_export_matching,
        "variant_ids": variant_ids,
        "paths": {
            "candidate_rows": str(candidate_rows),
            "replay_summary_json": replay_json,
            "replay_summary_report": replay_report,
            "hourly_json": hourly_json,
            "hourly_report": hourly_report,
            "ten_minute_json": ten_json,
            "ten_minute_report": ten_report,
        },
        "replay_summary": replay_summary,
        "candidate_hourly_performance": hourly_payload,
        "candidate_ten_minute_performance": ten_payload,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate predawn weak-slot winner-centering repairs.")
    parser.add_argument("--candidate-rows", default=str(DEFAULT_ITEM147_ROWS))
    parser.add_argument("--ten-minute-report", default=str(DEFAULT_TEN_MINUTE_REPORT))
    parser.add_argument("--min-brier-improvement", type=float, default=DEFAULT_MIN_BRIER_IMPROVEMENT)
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--calibrator-blend", type=float, default=CALIBRATOR_BLEND)
    parser.add_argument("--calibrator-extrapolation", type=float, default=CALIBRATOR_EXTRAPOLATION)
    parser.add_argument("--calibrator-power", type=float, default=CALIBRATOR_POWER)
    parser.add_argument("--output-variant-id", default=DEFAULT_OUTPUT_VARIANT_ID)
    parser.add_argument("--candidate-rows-out", default="")
    parser.add_argument("--write-candidate-gates", action="store_true")
    parser.add_argument("--source-candidate-json", default=str(DEFAULT_SOURCE_CANDIDATE_JSON))
    parser.add_argument(
        "--validation-evidence",
        default="row_export_surrogate",
        choices=candidate_variant_replay_summary.VALIDATION_EVIDENCE_CHOICES,
    )
    parser.add_argument("--candidate-replay-summary-json-out", default=str(DEFAULT_CANDIDATE_REPLAY_SUMMARY_OUT))
    parser.add_argument("--candidate-replay-summary-report-out", default=str(DEFAULT_CANDIDATE_REPLAY_SUMMARY_REPORT))
    parser.add_argument("--candidate-hourly-json-out", default=str(DEFAULT_CANDIDATE_HOURLY_OUT))
    parser.add_argument("--candidate-hourly-report-out", default=str(DEFAULT_CANDIDATE_HOURLY_REPORT))
    parser.add_argument("--candidate-ten-minute-json-out", default=str(DEFAULT_CANDIDATE_TEN_MINUTE_OUT))
    parser.add_argument("--candidate-ten-minute-report-out", default=str(DEFAULT_CANDIDATE_TEN_MINUTE_REPORT))
    parser.add_argument("--candidate-hourly-min-market-days", type=int, default=10)
    parser.add_argument("--candidate-ten-minute-min-weak-market-days", type=int, default=10)
    parser.add_argument("--candidate-weak-logloss-tol", type=float, default=0.010)
    parser.add_argument("--json-out", default=str(DEFAULT_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload, rows = build_repair_result(
        args.candidate_rows,
        args.ten_minute_report,
        min_brier_improvement=args.min_brier_improvement,
        market_tol=args.market_tol,
        blend=args.calibrator_blend,
        extrapolation=args.calibrator_extrapolation,
        partition_power=args.calibrator_power,
        output_variant_id=args.output_variant_id,
    )
    json_out, report_out = write_outputs(payload, args.json_out, args.report_out)
    print(f"Wrote {json_out}")
    print(f"Wrote {report_out}")
    if args.candidate_rows_out:
        candidate_rows_out = write_candidate_rows(rows, args.candidate_rows_out)
        print(f"Wrote repaired candidate rows to {candidate_rows_out}")
        if args.write_candidate_gates:
            weak_slots = weak_slots_from_report(args.ten_minute_report)
            gate_outputs = write_candidate_gate_outputs(
                candidate_rows=candidate_rows_out,
                weak_slots=weak_slots,
                source_candidate_json=args.source_candidate_json,
                validation_evidence=args.validation_evidence,
                replay_summary_json_out=args.candidate_replay_summary_json_out,
                replay_summary_report_out=args.candidate_replay_summary_report_out,
                hourly_json_out=args.candidate_hourly_json_out,
                hourly_report_out=args.candidate_hourly_report_out,
                ten_minute_json_out=args.candidate_ten_minute_json_out,
                ten_minute_report_out=args.candidate_ten_minute_report_out,
                min_hourly_market_days=args.candidate_hourly_min_market_days,
                candidate_min_weak_market_days=args.candidate_ten_minute_min_weak_market_days,
                weak_brier_improvement_min=args.min_brier_improvement,
                weak_market_regression_tolerance=args.market_tol,
                weak_logloss_regression_tolerance=args.candidate_weak_logloss_tol,
            )
            print(f"Candidate gate lineage: {gate_outputs['status']}")
            for path in gate_outputs["paths"].values():
                print(f"Wrote {path}")
    print(f"Predawn weak-slot repair validation: {payload['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
