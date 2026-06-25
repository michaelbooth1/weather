"""Cutoff-regime forecast/observation weighting report for roadmap item 135."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.scoring.metrics import expected_calibration_error, score_rows


SCHEMA_VERSION = "cutoff_regime_weighting_v0.1"
VARIANT_ID = "item135_regime_weighted_forecast_observation_v0_1"
VARIANT_FAMILY = "cutoff_regime_forecast_observation_weighting"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_FAMILY_PERMUTATION = DEFAULT_BACKTEST_ROOT / "input_variable_significance_2026_06_18_family_permutation.csv"
DEFAULT_SHADOW_VARIANTS = DEFAULT_BACKTEST_ROOT / "item134_forecast_profile_shadow_variants.csv"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item135_cutoff_regime_weighting.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item135_cutoff_regime_weighting_report.md"
DEFAULT_VARIANT_OUT = DEFAULT_BACKTEST_ROOT / "item135_regime_weighted_shadow_variants.csv"

FAMILY_ORDER = (
    "open_meteo_forecast_profile",
    "observed_temp_path",
    "forecast_source_state",
    "time_context",
    "surface_weather",
)
REGIME_ORDER = ("early", "midday", "late", "final_lock_in")
REGIME_SOURCE_SLICE = {
    "early": "early",
    "midday": "midday",
    "late": "late",
    "final_lock_in": "late",
}
REGIME_THRESHOLDS = {
    "early": {
        "max_delta_vs_current": 0.0,
        "max_delta_vs_market": 0.003,
        "min_market_days": 2,
        "intent": "forecast-heavy candidate must improve current before the day develops",
    },
    "midday": {
        "max_delta_vs_current": 0.0,
        "max_delta_vs_market": 0.003,
        "min_market_days": 2,
        "intent": "transition regime must improve current while forecast and observations both matter",
    },
    "late": {
        "max_delta_vs_current": 0.003,
        "max_delta_vs_market": 0.003,
        "min_market_days": 2,
        "intent": "observation-heavy regime may not materially degrade late-day replay",
    },
    "final_lock_in": {
        "max_delta_vs_current": 0.001,
        "max_delta_vs_market": 0.003,
        "min_market_days": 2,
        "intent": "final lock-in rows require tighter current-regression tolerance",
    },
}
OUTPUT_COLUMNS = [
    "variant_id",
    "variant_family",
    "uses_market_features",
    "is_control",
    "market_id",
    "target_date",
    "snapshot_id",
    "band_key",
    "probability",
    "current_probability",
    "recorded_probability",
    "market_yes",
    "outcome",
    "artifact_hash",
    "postprocess_config_hash",
    "experiment_start_date",
    "captured_at_local",
    "range_label",
    "bin_type",
    "bin_value",
    "cutoff_hour",
    "cutoff_regime",
    "forecast_component_weight",
    "observed_component_weight",
    "source_variant_id",
]


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def cutoff_regime(hour: Any) -> str:
    value = _safe_int(hour)
    if value is None:
        return "unknown"
    if value <= 10:
        return "early"
    if value <= 14:
        return "midday"
    if value <= 17:
        return "late"
    return "final_lock_in"


def family_weight_rows(family_permutation_path: str | Path = DEFAULT_FAMILY_PERMUTATION) -> list[dict[str, Any]]:
    by_slice_family: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _read_csv(family_permutation_path):
        family = row.get("family") or ""
        if family not in FAMILY_ORDER:
            continue
        delta = _safe_float(row.get("hgb_delta_mae_mean"))
        if delta is None:
            continue
        by_slice_family[(row.get("slice") or "all", family)] = {
            "delta_mae": delta,
            "q": _safe_float(row.get("hgb_importance_q")),
            "features": _safe_int(row.get("n_features")) or 0,
        }

    rows = []
    for regime in REGIME_ORDER:
        source_slice = REGIME_SOURCE_SLICE[regime]
        family_values = {
            family: max(0.0, (by_slice_family.get((source_slice, family)) or {}).get("delta_mae") or 0.0)
            for family in FAMILY_ORDER
        }
        total = sum(family_values.values())
        forecast = family_values.get("open_meteo_forecast_profile", 0.0)
        observed = family_values.get("observed_temp_path", 0.0)
        blend_denominator = forecast + observed
        rows.append({
            "regime": regime,
            "source_slice": source_slice,
            "evidence_status": "direct" if regime != "final_lock_in" else "late_slice_proxy_until_final_rows_exist",
            "forecast_component_weight": forecast / blend_denominator if blend_denominator > 0 else 0.0,
            "observed_component_weight": observed / blend_denominator if blend_denominator > 0 else 1.0,
            "family_weights": {
                family: (family_values[family] / total if total > 0 else 0.0)
                for family in FAMILY_ORDER
            },
            "family_delta_mae": family_values,
            "family_q": {
                family: (by_slice_family.get((source_slice, family)) or {}).get("q")
                for family in FAMILY_ORDER
            },
        })
    return rows


def weights_by_regime(weight_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["regime"]: row for row in weight_rows}


def _scored_row(row: dict[str, Any], probability_field: str) -> dict[str, Any] | None:
    probability = _safe_float(row.get(probability_field))
    market = _safe_float(row.get("market_yes"))
    outcome = _safe_int(row.get("outcome"))
    if probability is None or market is None or outcome not in {0, 1}:
        return None
    return {
        **row,
        "model_probability": _clamp_probability(probability),
        "market_yes": _clamp_probability(market),
        "outcome": int(outcome),
    }


def comparison(rows: list[dict[str, Any]], probability_field: str = "regime_weighted_probability") -> dict[str, Any] | None:
    model_rows = [
        scored
        for row in rows
        if (scored := _scored_row(row, probability_field)) is not None
    ]
    current_rows = [
        scored
        for row in rows
        if (scored := _scored_row(row, "current_probability")) is not None
    ]
    if not model_rows or not current_rows:
        return None
    model = score_rows(model_rows)
    current = score_rows(current_rows)
    if not model or not current:
        return None
    return {
        "n": model["n"],
        "candidate_brier": model["model_brier"],
        "current_brier": current["model_brier"],
        "market_brier": model["market_brier"],
        "candidate_logloss": model["model_logloss"],
        "current_logloss": current["model_logloss"],
        "market_logloss": model["market_logloss"],
        "candidate_ece": expected_calibration_error(model_rows, "model_probability"),
        "delta_vs_current": model["model_brier"] - current["model_brier"],
        "delta_vs_market": model["model_brier"] - model["market_brier"],
        "candidate_skill": model["brier_skill_score"],
        "base_rate": model["base_rate"],
    }


def daily_first_comparison(
    rows: list[dict[str, Any]],
    probability_field: str = "regime_weighted_probability",
) -> dict[str, Any] | None:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (str(row.get("market_id") or ""), str(row.get("target_date") or ""))
        if key[0] and key[1]:
            grouped[key].append(row)
    day_scores = [comparison(day_rows, probability_field=probability_field) for day_rows in grouped.values()]
    day_scores = [score for score in day_scores if score]
    if not day_scores:
        return None

    def avg(key: str) -> float | None:
        values = [score.get(key) for score in day_scores if score.get(key) is not None]
        return sum(values) / len(values) if values else None

    return {
        "n_days": len(day_scores),
        "n": sum(int(score.get("n") or 0) for score in day_scores),
        "candidate_brier": avg("candidate_brier"),
        "current_brier": avg("current_brier"),
        "market_brier": avg("market_brier"),
        "candidate_logloss": avg("candidate_logloss"),
        "current_logloss": avg("current_logloss"),
        "market_logloss": avg("market_logloss"),
        "candidate_ece": avg("candidate_ece"),
        "delta_vs_current": (
            avg("candidate_brier") - avg("current_brier")
            if avg("candidate_brier") is not None and avg("current_brier") is not None
            else None
        ),
        "delta_vs_market": (
            avg("candidate_brier") - avg("market_brier")
            if avg("candidate_brier") is not None and avg("market_brier") is not None
            else None
        ),
        "base_rate": avg("base_rate"),
    }


def grouped_comparison(
    rows: list[dict[str, Any]],
    group_key: str,
    probability_field: str = "regime_weighted_probability",
    *,
    daily_first: bool = False,
) -> list[dict[str, Any]]:
    grouped: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row.get(group_key) or "unknown"].append(row)
    output = []
    for group, group_rows in sorted(grouped.items(), key=lambda item: str(item[0])):
        comp = (
            daily_first_comparison(group_rows, probability_field=probability_field)
            if daily_first
            else comparison(group_rows, probability_field=probability_field)
        )
        if comp:
            output.append({"group": group, **comp})
    return output


def build_regime_weighted_rows(
    shadow_variant_path: str | Path = DEFAULT_SHADOW_VARIANTS,
    weight_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    weight_lookup = weights_by_regime(weight_rows or family_weight_rows())
    output = []
    for row in _read_csv(shadow_variant_path):
        forecast_probability = _safe_float(row.get("probability"))
        current_probability = _safe_float(row.get("current_probability"))
        if forecast_probability is None or current_probability is None:
            continue
        regime = cutoff_regime(row.get("cutoff_hour"))
        weights = weight_lookup.get(regime) or {}
        forecast_weight = float(weights.get("forecast_component_weight") or 0.0)
        observed_weight = 1.0 - forecast_weight
        regime_probability = (forecast_weight * forecast_probability) + (observed_weight * current_probability)
        output.append({
            **row,
            "source_variant_id": row.get("variant_id") or "",
            "variant_id": VARIANT_ID,
            "variant_family": VARIANT_FAMILY,
            "uses_market_features": "False",
            "is_control": "False",
            "forecast_profile_probability": forecast_probability,
            "probability": regime_probability,
            "regime_weighted_probability": regime_probability,
            "current_probability": current_probability,
            "market_yes": _safe_float(row.get("market_yes")),
            "outcome": _safe_int(row.get("outcome")),
            "cutoff_regime": regime,
            "forecast_component_weight": forecast_weight,
            "observed_component_weight": observed_weight,
        })
    return output


def no_leakage_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    market_days = {
        (row.get("market_id"), row.get("target_date"))
        for row in rows
        if row.get("market_id") and row.get("target_date")
    }
    snapshots = {
        (row.get("market_id"), row.get("target_date"), row.get("snapshot_id"))
        for row in rows
        if row.get("market_id") and row.get("target_date") and row.get("snapshot_id")
    }
    duplicate_keys = len(rows) - len({
        (
            row.get("market_id"),
            row.get("target_date"),
            row.get("snapshot_id"),
            row.get("band_key"),
        )
        for row in rows
    })
    return {
        "schema_version": "cutoff_regime_market_day_leakage_audit_v0.1",
        "status": "PASS" if market_days and duplicate_keys == 0 else "WARN",
        "primary_evidence_unit": "market_day",
        "market_days": len(market_days),
        "snapshots": len(snapshots),
        "rows": len(rows),
        "duplicate_observation_keys": duplicate_keys,
        "row_to_market_day_ratio": (len(rows) / len(market_days)) if market_days else None,
        "note": "Daily-first metrics equal-weight market-days before averaging repeated snapshot rows.",
    }


def threshold_assessment(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for regime in REGIME_ORDER:
        regime_rows = [row for row in rows if row.get("cutoff_regime") == regime]
        comp = daily_first_comparison(regime_rows)
        threshold = REGIME_THRESHOLDS[regime]
        reasons = []
        if not comp:
            reasons.append("missing scored rows")
        elif (comp.get("n_days") or 0) < threshold["min_market_days"]:
            reasons.append(f"market-days {comp.get('n_days') or 0} < {threshold['min_market_days']}")
        else:
            delta_current = comp.get("delta_vs_current")
            delta_market = comp.get("delta_vs_market")
            if delta_current is None or delta_current > threshold["max_delta_vs_current"]:
                reasons.append(
                    "delta_vs_current "
                    f"{fmt_signed(delta_current, 4)} > {threshold['max_delta_vs_current']:+.4f}"
                )
            if delta_market is None or delta_market > threshold["max_delta_vs_market"]:
                reasons.append(
                    "delta_vs_market "
                    f"{fmt_signed(delta_market, 4)} > {threshold['max_delta_vs_market']:+.4f}"
                )
        output.append({
            "regime": regime,
            "status": "pass" if not reasons else "blocked",
            "threshold": threshold,
            "daily_first": comp or {},
            "reasons": reasons,
        })
    return output


def disagreement_casebook(rows: list[dict[str, Any]], *, min_probability_gap: float = 0.02, limit: int = 25) -> list[dict[str, Any]]:
    cases = []
    for row in rows:
        probability = _safe_float(row.get("regime_weighted_probability"))
        current = _safe_float(row.get("current_probability"))
        outcome = _safe_int(row.get("outcome"))
        if probability is None or current is None or outcome not in {0, 1}:
            continue
        gap = probability - current
        if abs(gap) < min_probability_gap:
            continue
        current_brier = (current - outcome) ** 2
        candidate_brier = (probability - outcome) ** 2
        cases.append({
            "market_id": row.get("market_id"),
            "target_date": row.get("target_date"),
            "snapshot_id": row.get("snapshot_id"),
            "band_key": row.get("band_key"),
            "cutoff_regime": row.get("cutoff_regime"),
            "cutoff_hour": _safe_int(row.get("cutoff_hour")),
            "outcome": outcome,
            "regime_weighted_probability": probability,
            "current_probability": current,
            "forecast_profile_probability": _safe_float(row.get("forecast_profile_probability")),
            "market_yes": _safe_float(row.get("market_yes")),
            "probability_gap_vs_current": gap,
            "brier_delta_vs_current": candidate_brier - current_brier,
            "reason": (
                "regime candidate raised probability versus current"
                if gap > 0 else
                "regime candidate lowered probability versus current"
            ),
        })
    return sorted(
        cases,
        key=lambda row: (
            -abs(float(row.get("brier_delta_vs_current") or 0.0)),
            -abs(float(row.get("probability_gap_vs_current") or 0.0)),
        ),
    )[:limit]


def acceptance(thresholds: list[dict[str, Any]]) -> dict[str, Any]:
    blocked = [row for row in thresholds if row.get("status") != "pass"]
    return {
        "status": "pass" if not blocked else "blocked",
        "blocked_regimes": [row["regime"] for row in blocked],
        "reasons": [
            f"{row['regime']}: " + "; ".join(row.get("reasons") or [])
            for row in blocked
        ],
    }


def write_variant_csv(path: str | Path | None, rows: list[dict[str, Any]]) -> str | None:
    if not path:
        return None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return str(path)


def build_report_payload(
    family_permutation: str | Path = DEFAULT_FAMILY_PERMUTATION,
    shadow_variants: str | Path = DEFAULT_SHADOW_VARIANTS,
    *,
    variant_out: str | Path | None = DEFAULT_VARIANT_OUT,
) -> dict[str, Any]:
    weights = family_weight_rows(family_permutation)
    rows = build_regime_weighted_rows(shadow_variants, weights)
    variant_path = write_variant_csv(variant_out, rows)
    thresholds = threshold_assessment(rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "family_permutation": str(family_permutation),
            "source_shadow_variants": str(shadow_variants),
        },
        "variant": {
            "variant_id": VARIANT_ID,
            "variant_family": VARIANT_FAMILY,
            "path": variant_path,
            "rows": len(rows),
            "uses_market_features": False,
            "is_control": False,
        },
        "regime_family_weights": weights,
        "aggregate": comparison(rows) or {},
        "daily_first": daily_first_comparison(rows) or {},
        "by_cutoff_regime": grouped_comparison(rows, "cutoff_regime"),
        "daily_first_by_cutoff_regime": grouped_comparison(rows, "cutoff_regime", daily_first=True),
        "by_market": grouped_comparison(rows, "market_id", daily_first=True),
        "no_leakage_audit": no_leakage_audit(rows),
        "regime_thresholds": thresholds,
        "casebook": disagreement_casebook(rows),
        "acceptance": acceptance(thresholds),
    }


def _comparison_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            row.get("group") or "-",
            row.get("n_days") or "-",
            row.get("n", 0),
            fmt_num(row.get("candidate_brier")),
            fmt_num(row.get("current_brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("delta_vs_current"), 4),
            fmt_signed(row.get("delta_vs_market"), 4),
        ]
        for row in rows
    ]


def write_markdown_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    acceptance_payload = payload.get("acceptance") or {}
    audit = payload.get("no_leakage_audit") or {}
    lines = [
        "# Cutoff-Regime Forecast/Observation Weighting",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Acceptance: `{acceptance_payload.get('status')}`",
        "",
        "## Variant",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Variant", (payload.get("variant") or {}).get("variant_id") or "-"],
            ["Family", (payload.get("variant") or {}).get("variant_family") or "-"],
            ["Rows", (payload.get("variant") or {}).get("rows", 0)],
            ["Shadow CSV", (payload.get("variant") or {}).get("path") or "-"],
            ["Acceptance blockers", "; ".join(acceptance_payload.get("reasons") or []) or "-"],
        ],
    )
    lines += ["", "## Regime Family Weights", ""]
    lines += markdown_table(
        [
            "Regime",
            "Evidence",
            "Forecast Blend",
            "Observed Blend",
            "Forecast Family",
            "Observed Path",
            "Source State",
            "Time",
            "Surface",
        ],
        [
            [
                row.get("regime"),
                row.get("evidence_status"),
                fmt_num(row.get("forecast_component_weight")),
                fmt_num(row.get("observed_component_weight")),
                fmt_num((row.get("family_weights") or {}).get("open_meteo_forecast_profile")),
                fmt_num((row.get("family_weights") or {}).get("observed_temp_path")),
                fmt_num((row.get("family_weights") or {}).get("forecast_source_state")),
                fmt_num((row.get("family_weights") or {}).get("time_context")),
                fmt_num((row.get("family_weights") or {}).get("surface_weather")),
            ]
            for row in payload.get("regime_family_weights") or []
        ],
    )
    lines += ["", "## Market-Day Leakage Audit", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", audit.get("status") or "-"],
            ["Primary evidence unit", audit.get("primary_evidence_unit") or "-"],
            ["Market-days", audit.get("market_days", 0)],
            ["Snapshots", audit.get("snapshots", 0)],
            ["Rows", audit.get("rows", 0)],
            ["Duplicate observation keys", audit.get("duplicate_observation_keys", 0)],
            ["Row/market-day ratio", fmt_num(audit.get("row_to_market_day_ratio"))],
            ["Note", audit.get("note") or "-"],
        ],
    )
    lines += ["", "## Daily-First Replay By Cutoff Regime", ""]
    lines += markdown_table(
        ["Regime", "Market-days", "Rows", "Candidate Brier", "Current Brier", "Market Brier", "Delta Current", "Delta Market"],
        _comparison_rows(payload.get("daily_first_by_cutoff_regime") or []),
    )
    lines += ["", "## Separate Regime Thresholds", ""]
    lines += markdown_table(
        ["Regime", "Status", "Market-days", "Max Current Delta", "Max Market Delta", "Actual Current Delta", "Actual Market Delta", "Reasons"],
        [
            [
                row.get("regime"),
                row.get("status"),
                (row.get("daily_first") or {}).get("n_days") or 0,
                f"{(row.get('threshold') or {}).get('max_delta_vs_current', 0):+.4f}",
                f"{(row.get('threshold') or {}).get('max_delta_vs_market', 0):+.4f}",
                fmt_signed((row.get("daily_first") or {}).get("delta_vs_current"), 4),
                fmt_signed((row.get("daily_first") or {}).get("delta_vs_market"), 4),
                "; ".join(row.get("reasons") or []) or "-",
            ]
            for row in payload.get("regime_thresholds") or []
        ],
    )
    lines += ["", "## Disagreement Casebook", ""]
    lines += markdown_table(
        [
            "Market",
            "Date",
            "Snapshot",
            "Band",
            "Regime",
            "Outcome",
            "Regime P",
            "Current P",
            "Forecast P",
            "Gap",
            "Brier Delta",
        ],
        [
            [
                row.get("market_id"),
                row.get("target_date"),
                row.get("snapshot_id"),
                row.get("band_key"),
                row.get("cutoff_regime"),
                row.get("outcome"),
                fmt_num(row.get("regime_weighted_probability")),
                fmt_num(row.get("current_probability")),
                fmt_num(row.get("forecast_profile_probability")),
                fmt_signed(row.get("probability_gap_vs_current"), 4),
                fmt_signed(row.get("brier_delta_vs_current"), 4),
            ]
            for row in payload.get("casebook") or []
        ],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run(args: argparse.Namespace) -> dict[str, Any]:
    payload = build_report_payload(
        args.family_permutation,
        args.shadow_variants,
        variant_out=None if args.variant_out == "" else args.variant_out,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown_report(args.report, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build roadmap item 135 cutoff-regime weighting report.")
    parser.add_argument("--family-permutation", default=str(DEFAULT_FAMILY_PERMUTATION))
    parser.add_argument("--shadow-variants", default=str(DEFAULT_SHADOW_VARIANTS))
    parser.add_argument("--variant-out", default=str(DEFAULT_VARIANT_OUT))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    return parser


def main(argv: list[str] | None = None) -> int:
    payload = run(build_parser().parse_args(argv))
    print(f"Cutoff-regime weighting: {payload['acceptance']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
