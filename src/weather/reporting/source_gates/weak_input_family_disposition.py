"""Weak input-family disposition and regime-backfill report.

Roadmap item 138 keeps weak or sparse weather-input families out of active
evidence claims until they have broad or predeclared regime-specific settlement
evidence.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from weather.io import read_csv_rows, read_json, write_json_atomic
from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.source_gates.source_family_consumer_contract import (
    source_family_inventory_consumer_contract,
)
from weather.reporting.source_gates.source_artifact_binding import (
    load_verified_current_json_artifact,
    stable_json_artifact,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("weak_input_family_disposition")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_FAMILY_PERMUTATION = DEFAULT_BACKTEST_ROOT / "input_variable_significance_2026_06_18_family_permutation.csv"
DEFAULT_COVERAGE = DEFAULT_BACKTEST_ROOT / "input_variable_significance_2026_06_18_coverage.csv"
DEFAULT_SOURCE_FAMILY_INVENTORY = DEFAULT_BACKTEST_ROOT / "source_family_inventory.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item138_weak_input_family_disposition.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item138_weak_input_family_disposition_report.md"

SIGNIFICANT_Q_THRESHOLD = 0.10
MIN_FAMILY_DELTA = 0.0
LOW_COVERAGE_THRESHOLD = 0.35
NEAR_CONSTANT_UNIQUE_MAX = 2
MIN_BACKFILL_DAYS = 45

CORE_SERVED_FAMILIES = {
    "observed_temp_path",
    "open_meteo_forecast_profile",
    "forecast_source_state",
    "time_context",
}
WEAK_DIAGNOSTIC_FAMILIES = {"surface_weather"}
REGIME_BACKFILL_FAMILIES = {
    "marine_microclimate",
    "radar_precip",
    "official_multimodel_guidance",
}
DIAGNOSTIC_DISPOSITIONS = {"diagnostic_only", "regime_backfill", "remove"}

BACKFILL_PLANS = {
    "surface_weather": {
        "regimes": ["extreme_heat", "dry_air", "wind_shift", "gust_front"],
        "target_features": [
            "dewpoint_c",
            "humidity",
            "pressure_trend_3h",
            "wind_gust_kmh",
            "wind_shift_3h_degrees",
        ],
        "minimum_market_days": 60,
        "decision_rule": "Require a predeclared regime replay with positive Brier/log-loss lift before active use.",
    },
    "marine_microclimate": {
        "regimes": ["lake_breeze_reversal", "marine_layer", "onshore_flow"],
        "target_features": [
            "lake_breeze_proxy",
            "onshore_flow",
            "onshore_wind_speed_kmh",
            "marine_post_cutoff_onshore_reversal",
        ],
        "minimum_market_days": 45,
        "decision_rule": "Keep lake/marine fields diagnostic until a coastal/lake regime replay clears coverage and lift.",
    },
    "radar_precip": {
        "regimes": ["precip_interruption", "convective_cooling", "rain_rate_spike"],
        "target_features": [
            "mrms_row_count",
            "mrms_precip_rate_max",
            "mrms_precip_after_cutoff_sum",
            "mrms_interruption_flag",
        ],
        "minimum_market_days": 40,
        "decision_rule": "Backfill MRMS precipitation-interruption rows before training influence.",
    },
    "official_multimodel_guidance": {
        "regimes": ["early_forecast_dominant", "toronto_eccc_gridded", "official_qpf_pop"],
        "target_features": [
            "nws_grid_high",
            "nws_grid_qpf_after_cutoff_sum",
            "open_meteo_nam_high_delta",
            "eccc_gem_high",
            "eccc_gem_precip_after_cutoff_sum",
        ],
        "minimum_market_days": 60,
        "decision_rule": "Use item 137 coverage and replay gates before official guidance can leave diagnostic-only status.",
    },
}

SURFACE_WEATHER_FEATURES = {
    "dewpoint_c",
    "humidity",
    "pressure",
    "pressure_trend_3h",
    "wind_speed_kmh",
    "wind_gust_kmh",
    "wind_shift_3h_degrees",
    "cloud_group",
    "wind_group",
}
OBSERVED_TEMP_FEATURES = {
    "high_so_far",
    "current_temp",
    "rise_from_7am",
    "warming_rate_2h",
    "hours_at_peak",
    "live_reading_temp",
    "live_reading_minus_high",
}
TIME_CONTEXT_FEATURES = {"cutoff_hour", "minutes_since_cutoff"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def source_family_ids_for_feature(feature: str, input_family: str | None = None) -> list[str]:
    feature = feature or ""
    if feature.startswith("nws_grid") or feature.startswith("nws_hourly"):
        return ["nws_grid"]
    if feature.startswith("open_meteo_"):
        return ["multi_model_guidance"]
    if feature.startswith("eccc_gem") or feature.startswith("eccc_hrdps"):
        return ["eccc_gridded"]
    if feature.startswith("mrms_"):
        return ["mrms_precip"]
    if feature.startswith(("marine_", "onshore_", "lake_breeze")):
        return ["marine_context"]
    if input_family in {"observed_temp_path", "surface_weather", "time_context"}:
        return ["settlement_observation"]
    if input_family == "open_meteo_forecast_profile":
        return ["open_meteo_expanded"]
    if input_family == "forecast_source_state":
        return ["forecast_baseline"]
    return []


def input_family_for_model_feature(feature_name: str) -> str | None:
    name = feature_name or ""
    if name.startswith("cloud_group_") or name.startswith("wind_group_"):
        return "surface_weather"
    if name in SURFACE_WEATHER_FEATURES:
        return "surface_weather"
    if name in OBSERVED_TEMP_FEATURES or name.startswith("band_mid_minus_high_so_far"):
        return "observed_temp_path"
    if name in TIME_CONTEXT_FEATURES:
        return "time_context"
    if name in {"forecast_source_count", "forecast_disagreement"}:
        return "forecast_source_state"
    if name.startswith("forecast_") or name.startswith("band_mid_minus_forecast"):
        return "open_meteo_forecast_profile"
    if name.startswith(("marine_", "onshore_", "lake_breeze")):
        return "marine_microclimate"
    if name.startswith("mrms_"):
        return "radar_precip"
    if name.startswith(("nws_grid", "nws_hourly", "open_meteo_", "eccc_gem", "eccc_hrdps")):
        return "official_multimodel_guidance"
    return None


def _inventory_by_family(
    path: str | Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    payload, receipt = stable_json_artifact(path)
    rows = {
        row.get("family_id"): row
        for row in payload.get("inventory") or []
        if row.get("family_id")
    }
    return rows, source_family_inventory_consumer_contract(payload), receipt


def _family_permutation_by_family(path: str | Path) -> dict[str, dict[str, dict[str, Any]]]:
    rows = read_csv_rows(path)
    by_family: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        family = row.get("family")
        if not family:
            continue
        slice_name = row.get("slice") or "all"
        by_family[family][slice_name] = {
            "slice": slice_name,
            "hgb_delta_mae_mean": _float(row.get("hgb_delta_mae_mean")),
            "hgb_delta_mae_ci_low": _float(row.get("hgb_delta_mae_ci_low")),
            "hgb_delta_mae_ci_high": _float(row.get("hgb_delta_mae_ci_high")),
            "hgb_importance_q": _float(row.get("hgb_importance_q")),
            "n_features": _int(row.get("n_features")),
        }
    return by_family


def _coverage_by_family(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    rows = read_csv_rows(path)
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        family = row.get("family")
        feature = row.get("feature")
        if not family or not feature:
            continue
        parsed = {
            "feature": feature,
            "kind": row.get("kind") or "",
            "family": family,
            "n_rows_non_missing": _int(row.get("n_rows_non_missing")),
            "row_coverage": _float(row.get("row_coverage")),
            "n_days_non_missing": _int(row.get("n_days_non_missing")),
            "n_markets_non_missing": _int(row.get("n_markets_non_missing")),
            "n_unique_raw": _int(row.get("n_unique_raw")),
            "n_rows_within_market_variation": _int(row.get("n_rows_within_market_variation")),
            "analyzable": _truthy(row.get("analyzable")),
            "source_family_ids": source_family_ids_for_feature(feature, family),
        }
        by_family[family].append(parsed)
    return by_family


def _family_gate(family: str, slices: dict[str, dict[str, Any]]) -> dict[str, Any]:
    all_slice = slices.get("all") or {}
    best_slice = None
    positive_slices = []
    for row in slices.values():
        delta = row.get("hgb_delta_mae_mean")
        q_value = row.get("hgb_importance_q")
        if delta is not None and q_value is not None and delta > MIN_FAMILY_DELTA and q_value <= SIGNIFICANT_Q_THRESHOLD:
            positive_slices.append(row)
        if delta is not None and (best_slice is None or delta > (best_slice.get("hgb_delta_mae_mean") or float("-inf"))):
            best_slice = row
    all_delta = all_slice.get("hgb_delta_mae_mean")
    all_q = all_slice.get("hgb_importance_q")
    all_ci_low = all_slice.get("hgb_delta_mae_ci_low")
    all_pass = (
        all_delta is not None
        and all_q is not None
        and all_delta > MIN_FAMILY_DELTA
        and all_q <= SIGNIFICANT_Q_THRESHOLD
        and (all_ci_low is None or all_ci_low > MIN_FAMILY_DELTA)
    )
    return {
        "family": family,
        "all_slice": all_slice,
        "best_slice": best_slice,
        "positive_slice_count": len(positive_slices),
        "positive_slices": positive_slices,
        "passes_broad_family_gate": bool(all_pass),
    }


def _coverage_summary(features: list[dict[str, Any]]) -> dict[str, Any]:
    coverages = [row["row_coverage"] for row in features if row.get("row_coverage") is not None]
    sparse = [
        row
        for row in features
        if (row.get("row_coverage") is not None and row["row_coverage"] < LOW_COVERAGE_THRESHOLD)
        or row.get("n_days_non_missing", 0) < MIN_BACKFILL_DAYS
    ]
    near_constant = [
        row
        for row in features
        if row.get("n_unique_raw", 0) <= NEAR_CONSTANT_UNIQUE_MAX
        or row.get("n_rows_within_market_variation", 0) == 0
        or not row.get("analyzable")
    ]
    return {
        "feature_count": len(features),
        "analyzable_feature_count": sum(1 for row in features if row.get("analyzable")),
        "min_row_coverage": min(coverages) if coverages else None,
        "median_row_coverage": median(coverages) if coverages else None,
        "max_row_coverage": max(coverages) if coverages else None,
        "max_days_non_missing": max((row.get("n_days_non_missing", 0) for row in features), default=0),
        "max_markets_non_missing": max((row.get("n_markets_non_missing", 0) for row in features), default=0),
        "low_coverage_feature_count": len(sparse),
        "near_constant_feature_count": len(near_constant),
        "low_coverage_features": [row["feature"] for row in sorted(sparse, key=lambda item: item["feature"])],
        "near_constant_features": [row["feature"] for row in sorted(near_constant, key=lambda item: item["feature"])],
    }


def _inventory_summary(
    source_family_ids: list[str],
    inventory: dict[str, dict[str, Any]],
    inventory_contract: dict[str, Any],
) -> dict[str, Any]:
    rows = [inventory[family_id] for family_id in source_family_ids if family_id in inventory]
    active_columns = sorted({
        column
        for row in rows
        for column in (row.get("active_model_feature_columns") or [])
    })
    active_statuses = sorted({row.get("active_model_usage_status") or "UNKNOWN" for row in rows})
    lineage_statuses = sorted({row.get("lineage_status") or "UNKNOWN" for row in rows})
    promotion_statuses = sorted({
        (row.get("promotion_decision") or {}).get("status") or "UNKNOWN"
        for row in rows
    })
    return {
        "operational_contract": inventory_contract,
        "source_family_ids": source_family_ids,
        "active_model_usage_statuses": active_statuses,
        "active_model_feature_columns": active_columns,
        "active_model_feature_count": len(active_columns),
        "lineage_statuses": lineage_statuses,
        "promotion_statuses": promotion_statuses,
    }


def _family_disposition(
    family: str,
    gate: dict[str, Any],
    coverage: dict[str, Any],
    inventory_summary: dict[str, Any],
) -> tuple[str, list[str]]:
    blockers = []
    if (inventory_summary.get("operational_contract") or {}).get("status") != "PASS":
        blockers.append("source-family inventory integrity contract is not PASS")
        return "diagnostic_only", blockers
    if coverage["low_coverage_feature_count"]:
        blockers.append(f"{coverage['low_coverage_feature_count']} low-coverage/sparse feature(s)")
    if coverage["near_constant_feature_count"]:
        blockers.append(f"{coverage['near_constant_feature_count']} near-constant or unanalyzable feature(s)")
    if not gate.get("passes_broad_family_gate"):
        blockers.append("no positive broad family permutation gate")
    if any(status not in {"PASS", "PRESENT"} for status in inventory_summary.get("lineage_statuses") or []):
        blockers.append("source lineage or parity is incomplete")

    if family in CORE_SERVED_FAMILIES:
        if gate.get("passes_broad_family_gate"):
            return "served", blockers
        return "shadow", blockers
    if family in WEAK_DIAGNOSTIC_FAMILIES:
        if gate.get("passes_broad_family_gate") and not coverage["near_constant_feature_count"]:
            return "shadow", blockers
        return "diagnostic_only", blockers
    if family in REGIME_BACKFILL_FAMILIES:
        if gate.get("passes_broad_family_gate") and not coverage["low_coverage_feature_count"]:
            return "shadow", blockers
        return "regime_backfill", blockers
    if coverage["feature_count"] and not gate.get("passes_broad_family_gate"):
        return "diagnostic_only", blockers
    return "shadow", blockers


def _family_rows(
    family_permutation: dict[str, dict[str, dict[str, Any]]],
    coverage: dict[str, list[dict[str, Any]]],
    inventory: dict[str, dict[str, Any]],
    inventory_contract: dict[str, Any],
) -> list[dict[str, Any]]:
    families = sorted(set(family_permutation) | set(coverage))
    rows = []
    for family in families:
        feature_rows = coverage.get(family) or []
        source_family_ids = sorted({
            source_id
            for feature in feature_rows
            for source_id in (feature.get("source_family_ids") or [])
        })
        gate = _family_gate(family, family_permutation.get(family) or {})
        coverage_info = _coverage_summary(feature_rows)
        inventory_info = _inventory_summary(
            source_family_ids,
            inventory,
            inventory_contract,
        )
        disposition, blockers = _family_disposition(family, gate, coverage_info, inventory_info)
        plan = BACKFILL_PLANS.get(family)
        rows.append({
            "family": family,
            "disposition": disposition,
            "model_role": (
                "active_model_evidence" if disposition == "served"
                else "shadow_candidate" if disposition == "shadow"
                else "diagnostic_only_until_regime_gate" if disposition == "regime_backfill"
                else "diagnostic_only"
            ),
            "blockers": blockers,
            "coverage": coverage_info,
            "family_permutation": gate,
            "source_inventory": inventory_info,
            "backfill_plan": plan,
            "feature_rows": feature_rows,
        })
    return rows


def weak_input_training_preflight(
    feature_names: list[str] | tuple[str, ...] | set[str],
    disposition_payload: dict[str, Any] | None = None,
    *,
    report_path: str | Path = DEFAULT_OUT,
) -> dict[str, Any]:
    """Fail closed when candidate-family policy is missing or non-current."""
    if disposition_payload is None:
        disposition_payload = read_json(report_path, default=None)
    if not disposition_payload:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "BLOCK",
            "serving_or_release_authorization": False,
            "reason": "weak input-family disposition report is not available",
            "feature_count": len(feature_names or []),
            "diagnostic_only_families": [],
            "warnings": [],
            "authorization_blockers": [
                "weak input-family disposition report is not available"
            ],
        }

    disposition_payload = (
        disposition_payload if isinstance(disposition_payload, dict) else {}
    )
    inputs = disposition_payload.get("inputs")
    inputs = inputs if isinstance(inputs, dict) else {}
    inventory_contract = inputs.get("source_family_inventory_contract")
    inventory_contract = (
        inventory_contract if isinstance(inventory_contract, dict) else {}
    )
    summary = disposition_payload.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    authorization_blockers = []
    inventory_receipt = inputs.get("source_family_inventory_receipt")
    current_inventory, inventory_verification = (
        load_verified_current_json_artifact(
            inventory_receipt,
            label="weak input-family source inventory",
        )
    )
    current_inventory_contract = source_family_inventory_consumer_contract(
        current_inventory
    )
    authorization_blockers.extend(inventory_verification.get("blockers") or [])
    if inventory_verification.get("status") != "PASS" and not (
        inventory_verification.get("blockers")
    ):
        authorization_blockers.append(
            "current weak input-family source inventory receipt is not PASS"
        )
    if current_inventory_contract != inventory_contract:
        authorization_blockers.append(
            "stored source-family inventory contract differs from current verified input"
        )
    if disposition_payload.get("schema_version") != SCHEMA_VERSION:
        authorization_blockers.append(
            f"schema_version must equal {SCHEMA_VERSION}"
        )
    if disposition_payload.get("serving_or_release_authorization") is not False:
        authorization_blockers.append(
            "serving_or_release_authorization must be explicitly false"
        )
    if inventory_contract.get("status") != "PASS":
        authorization_blockers.append(
            "current source-family inventory contract is not PASS"
        )
    if inventory_contract.get("serving_or_release_authorization") is not False:
        authorization_blockers.append(
            "source-family inventory contract is missing its non-authorization marker"
        )
    if summary.get("status") not in {"PASS", "WARN"}:
        authorization_blockers.append(
            "weak input-family disposition summary is missing or BLOCK"
        )

    family_rows = disposition_payload.get("families")
    if not isinstance(family_rows, list) or not family_rows:
        authorization_blockers.append(
            "weak input-family disposition families must be a non-empty list"
        )
        family_rows = []
    policy = {
        row.get("family"): row
        for row in family_rows
        if isinstance(row, dict) and row.get("family")
    }
    features_by_family: dict[str, list[str]] = defaultdict(list)
    for feature in sorted(set(feature_names or [])):
        family = input_family_for_model_feature(feature)
        if family:
            features_by_family[family].append(feature)

    warnings = []
    diagnostic_families = []
    for family, features in sorted(features_by_family.items()):
        row = policy.get(family)
        if not row:
            authorization_blockers.append(
                f"no disposition row for referenced feature family {family}"
            )
            warnings.append({
                "family": family,
                "disposition": "MISSING",
                "feature_count": len(features),
                "features": features,
                "reasons": ["referenced feature family is absent from policy"],
            })
            continue
        coverage = row.get("coverage") or {}
        disposition = row.get("disposition")
        reasons = []
        if disposition in DIAGNOSTIC_DISPOSITIONS:
            reasons.append(f"family disposition is {disposition}")
            diagnostic_families.append(family)
        if coverage.get("low_coverage_feature_count"):
            reasons.append(f"{coverage.get('low_coverage_feature_count')} low-coverage feature(s)")
        if coverage.get("near_constant_feature_count"):
            reasons.append(f"{coverage.get('near_constant_feature_count')} near-constant feature(s)")
        if any("no positive broad family" in blocker for blocker in (row.get("blockers") or [])):
            reasons.append("no positive broad family permutation result")
        if reasons:
            warnings.append({
                "family": family,
                "disposition": disposition,
                "feature_count": len(features),
                "features": features,
                "reasons": reasons,
            })

    return {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "BLOCK"
            if authorization_blockers
            else "WARN" if warnings else "PASS"
        ),
        "serving_or_release_authorization": False,
        "feature_count": len(feature_names or []),
        "diagnostic_only_families": sorted(set(diagnostic_families)),
        "warnings": warnings,
        "authorization_blockers": authorization_blockers,
    }


def build_report_payload(
    family_permutation: str | Path = DEFAULT_FAMILY_PERMUTATION,
    coverage: str | Path = DEFAULT_COVERAGE,
    source_family_inventory: str | Path = DEFAULT_SOURCE_FAMILY_INVENTORY,
) -> dict[str, Any]:
    permutation_by_family = _family_permutation_by_family(family_permutation)
    coverage_by_family = _coverage_by_family(coverage)
    inventory, inventory_contract, inventory_receipt = _inventory_by_family(
        source_family_inventory
    )
    families = _family_rows(
        permutation_by_family,
        coverage_by_family,
        inventory,
        inventory_contract,
    )
    disposition_counts = Counter(row["disposition"] for row in families)

    active_feature_names = sorted({
        feature
        for row in families
        for feature in ((row.get("source_inventory") or {}).get("active_model_feature_columns") or [])
    })
    training_preflight = weak_input_training_preflight(
        active_feature_names,
        {
            "schema_version": SCHEMA_VERSION,
            "serving_or_release_authorization": False,
            "inputs": {
                "source_family_inventory_contract": inventory_contract,
                "source_family_inventory_receipt": inventory_receipt,
            },
            "summary": {
                "status": (
                    "PASS" if inventory_contract.get("status") == "PASS" else "BLOCK"
                ),
            },
            "families": families,
        },
    )
    diagnostic = [row["family"] for row in families if row["disposition"] in DIAGNOSTIC_DISPOSITIONS]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _utc_now(),
        "serving_or_release_authorization": False,
        "authorization_note": (
            "Detached report only; runtime current-input revalidation is required "
            "before serving or release authorization."
        ),
        "inputs": {
            "family_permutation": str(family_permutation),
            "coverage": str(coverage),
            "source_family_inventory": str(source_family_inventory),
            "source_family_inventory_contract": inventory_contract,
            "source_family_inventory_receipt": inventory_receipt,
        },
        "thresholds": {
            "significant_q_threshold": SIGNIFICANT_Q_THRESHOLD,
            "min_family_delta": MIN_FAMILY_DELTA,
            "low_coverage_threshold": LOW_COVERAGE_THRESHOLD,
            "near_constant_unique_max": NEAR_CONSTANT_UNIQUE_MAX,
            "min_backfill_days": MIN_BACKFILL_DAYS,
        },
        "summary": {
            "status": (
                "BLOCK"
                if training_preflight["status"] == "BLOCK"
                else "WARN" if training_preflight["status"] == "WARN" else "PASS"
            ),
            "family_count": len(families),
            "disposition_counts": dict(sorted(disposition_counts.items())),
            "diagnostic_or_backfill_families": sorted(diagnostic),
            "training_preflight_status": training_preflight["status"],
        },
        "training_preflight": training_preflight,
        "families": families,
    }
    return payload


def write_markdown_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    summary = payload.get("summary") or {}
    lines = [
        "# Weak Input-Family Disposition",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "Serving/release authorization: `false`",
        (
            "This detached report cannot authorize serving or release; runtime "
            "current-input revalidation is required."
        ),
        "",
        "## Summary",
        "",
        *markdown_table(
            ["Metric", "Value"],
            [
                ["Status", summary.get("status")],
                ["Families", summary.get("family_count")],
                ["Disposition counts", summary.get("disposition_counts")],
                ["Training preflight", summary.get("training_preflight_status")],
            ],
        ),
        "",
        "## Disposition Table",
        "",
        *markdown_table(
            [
                "Family",
                "Disposition",
                "Broad delta",
                "Broad q",
                "Features",
                "Sparse",
                "Near-constant",
                "Source families",
                "Blockers",
            ],
            [
                [
                    row["family"],
                    row["disposition"],
                    fmt_signed(((row.get("family_permutation") or {}).get("all_slice") or {}).get("hgb_delta_mae_mean")),
                    fmt_num(((row.get("family_permutation") or {}).get("all_slice") or {}).get("hgb_importance_q")),
                    (row.get("coverage") or {}).get("feature_count"),
                    (row.get("coverage") or {}).get("low_coverage_feature_count"),
                    (row.get("coverage") or {}).get("near_constant_feature_count"),
                    ", ".join((row.get("source_inventory") or {}).get("source_family_ids") or []) or "-",
                    "; ".join(row.get("blockers") or []) or "-",
                ]
                for row in payload.get("families") or []
            ],
        ),
        "",
        "## Training Preflight Warnings",
        "",
    ]
    warnings = (payload.get("training_preflight") or {}).get("warnings") or []
    if warnings:
        lines.extend(markdown_table(
            ["Family", "Disposition", "Features", "Reasons"],
            [
                [
                    row.get("family"),
                    row.get("disposition"),
                    row.get("feature_count"),
                    "; ".join(row.get("reasons") or []),
                ]
                for row in warnings
            ],
        ))
    else:
        lines.append("- No weak-family training warnings.")

    lines.extend(["", "## Regime Backfill Plans", ""])
    plan_rows = []
    for row in payload.get("families") or []:
        plan = row.get("backfill_plan") or {}
        if not plan:
            continue
        plan_rows.append([
            row["family"],
            ", ".join(plan.get("regimes") or []),
            ", ".join(plan.get("target_features") or []),
            plan.get("minimum_market_days"),
            plan.get("decision_rule"),
        ])
    lines.extend(markdown_table(
        ["Family", "Regimes", "Target Features", "Min Days", "Decision Rule"],
        plan_rows,
    ))

    lines.extend(["", "## Diagnostic Feature Blockers", ""])
    feature_rows = []
    for row in payload.get("families") or []:
        coverage = row.get("coverage") or {}
        blocked = sorted(set((coverage.get("low_coverage_features") or []) + (coverage.get("near_constant_features") or [])))
        for feature in blocked[:20]:
            reasons = []
            if feature in (coverage.get("low_coverage_features") or []):
                reasons.append("sparse")
            if feature in (coverage.get("near_constant_features") or []):
                reasons.append("near_constant_or_unanalyzable")
            feature_rows.append([row["family"], feature, row["disposition"], ", ".join(reasons)])
    lines.extend(markdown_table(["Family", "Feature", "Disposition", "Reason"], feature_rows))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description="Build weak input-family disposition and backfill report.")
    parser.add_argument("--family-permutation", default=str(DEFAULT_FAMILY_PERMUTATION))
    parser.add_argument("--coverage", default=str(DEFAULT_COVERAGE))
    parser.add_argument("--source-family-inventory", default=str(DEFAULT_SOURCE_FAMILY_INVENTORY))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)

    payload = build_report_payload(args.family_permutation, args.coverage, args.source_family_inventory)
    write_json_atomic(args.out, payload, trailing_newline=True)
    write_markdown_report(args.report, payload)
    print(f"Weak input-family disposition: {payload['summary']['status']}")
    return payload


if __name__ == "__main__":
    main()
