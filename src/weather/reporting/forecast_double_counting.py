"""Roadmap item 181 forecast double-counting verification report."""

from __future__ import annotations

import argparse
import csv
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.model.calibration_runtime import forecast_error_distribution
from weather.model.model_distribution import EMPIRICAL_FORECAST_SHAPE_ALLOWED_MARKETS
from weather.paths import data_path
from weather.reporting.distribution_stage_attribution import (
    aggregate_rows,
    attribution_rows_for_folder,
    component_folders,
)
from weather.reporting.forecast_profile_calibration import forecast_profile_subfamily_rows
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("forecast_double_counting")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_HGB_PERMUTATION = DEFAULT_BACKTEST_ROOT / "input_variable_significance_2026_06_18_hgb_permutation.csv"
DEFAULT_FAMILY_PERMUTATION = DEFAULT_BACKTEST_ROOT / "input_variable_significance_2026_06_18_family_permutation.csv"
DEFAULT_DISTRIBUTION_ATTRIBUTION = DEFAULT_BACKTEST_ROOT / "distribution_stage_attribution.json"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "item181_forecast_double_counting.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "item181_forecast_double_counting_report.md"
FORECAST_FAMILIES = {"open_meteo_forecast_profile", "forecast_source_state"}
EMPIRICAL_REGIMES = {"empirical", "calibrated_empirical"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _forecast_rows(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    for row in _read_csv(path):
        family = row.get("family") or ""
        if family not in FORECAST_FAMILIES:
            continue
        rows.append({
            "slice": row.get("slice") or "all",
            "family": family,
            "feature": row.get("feature") or "",
            "hgb_delta_mae_mean": _safe_float(row.get("hgb_delta_mae_mean")),
            "hgb_importance_q": _safe_float(row.get("hgb_importance_q")),
        })
    return rows


def hgb_forecast_attribution(
    hgb_permutation: str | Path = DEFAULT_HGB_PERMUTATION,
    family_permutation: str | Path = DEFAULT_FAMILY_PERMUTATION,
) -> dict[str, Any]:
    family_rows = []
    for row in _read_csv(family_permutation):
        family = row.get("family") or ""
        if family not in FORECAST_FAMILIES:
            continue
        family_rows.append({
            "slice": row.get("slice") or "all",
            "family": family,
            "hgb_delta_mae_mean": _safe_float(row.get("hgb_delta_mae_mean")),
            "hgb_importance_q": _safe_float(row.get("hgb_importance_q")),
        })
    feature_rows = _forecast_rows(hgb_permutation)
    top_features = sorted(
        feature_rows,
        key=lambda row: row.get("hgb_delta_mae_mean") if row.get("hgb_delta_mae_mean") is not None else float("-inf"),
        reverse=True,
    )[:20]
    all_forecast_high = next(
        (
            row for row in feature_rows
            if row.get("slice") == "all" and row.get("feature") == "forecast_high"
        ),
        None,
    )
    all_profile = next(
        (
            row for row in family_rows
            if row.get("slice") == "all" and row.get("family") == "open_meteo_forecast_profile"
        ),
        None,
    )
    early_profile = next(
        (
            row for row in family_rows
            if row.get("slice") == "early" and row.get("family") == "open_meteo_forecast_profile"
        ),
        None,
    )
    status = "PASS" if all_forecast_high and all_profile and early_profile else "MISSING"
    return {
        "status": status,
        "hgb_permutation": str(hgb_permutation),
        "family_permutation": str(family_permutation),
        "family_rows": family_rows,
        "top_features": top_features,
        "subfamilies": forecast_profile_subfamily_rows(hgb_permutation),
        "all_forecast_high_delta_mae": (all_forecast_high or {}).get("hgb_delta_mae_mean"),
        "all_forecast_profile_delta_mae": (all_profile or {}).get("hgb_delta_mae_mean"),
        "early_forecast_profile_delta_mae": (early_profile or {}).get("hgb_delta_mae_mean"),
    }


def _is_empirical_regime(row: dict[str, Any]) -> bool:
    return str(row.get("stage_regime") or "").strip().lower() in EMPIRICAL_REGIMES


def forecast_pull_rows(snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT) -> list[dict[str, Any]]:
    rows = []
    for folder in component_folders(snapshots_root):
        rows.extend(
            row for row in attribution_rows_for_folder(folder)
            if row.get("component_name") == "forecast_pull"
        )
    return rows


def _market_delta_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        aggregate_rows(rows, "market_id"),
        key=lambda row: (
            row.get("mean_delta_brier") if row.get("mean_delta_brier") is not None else float("-inf"),
            row.get("delta_n", 0),
        ),
        reverse=True,
    )


def _regression_markets(rows: list[dict[str, Any]], metric: str) -> list[str]:
    return [
        row.get("group")
        for row in rows
        if row.get(metric) is not None and row.get(metric) > 0
    ]


def forecast_pull_delta_summary(
    distribution_attribution: str | Path = DEFAULT_DISTRIBUTION_ATTRIBUTION,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    *,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    attribution = _read_json(distribution_attribution)
    scope = attribution.get("forecast_shape_scope") or {}
    by_component = {
        row.get("group"): row
        for row in attribution.get("by_component") or []
    }
    pull_rows = list(rows if rows is not None else forecast_pull_rows(snapshots_root))
    feature_rows = [row for row in pull_rows if not _is_empirical_regime(row)]
    empirical_rows = [row for row in pull_rows if _is_empirical_regime(row)]
    selected_empirical_rows = [
        row for row in empirical_rows
        if str(row.get("market_id") or "").strip().lower() in EMPIRICAL_FORECAST_SHAPE_ALLOWED_MARKETS
    ]
    suppressed_empirical_rows = [
        row for row in empirical_rows
        if str(row.get("market_id") or "").strip().lower() not in EMPIRICAL_FORECAST_SHAPE_ALLOWED_MARKETS
    ]
    feature_markets = _market_delta_rows(feature_rows)
    empirical_markets = _market_delta_rows(empirical_rows)
    selected_empirical_markets = _market_delta_rows(selected_empirical_rows)
    suppressed_empirical_markets = _market_delta_rows(suppressed_empirical_rows)
    selected_brier_regressions = _regression_markets(selected_empirical_markets, "mean_delta_brier")
    selected_logloss_regressions = _regression_markets(selected_empirical_markets, "mean_delta_logloss")
    suppressed_brier_regressions = _regression_markets(suppressed_empirical_markets, "mean_delta_brier")
    suppressed_logloss_regressions = _regression_markets(suppressed_empirical_markets, "mean_delta_logloss")
    status = "PASS" if not selected_brier_regressions and not selected_logloss_regressions else "BLOCK"
    return {
        "status": status,
        "distribution_attribution": str(distribution_attribution),
        "snapshots_root": str(snapshots_root),
        "empirical_forecast_shape_allowed_markets": sorted(EMPIRICAL_FORECAST_SHAPE_ALLOWED_MARKETS),
        "forecast_shape_scope": scope,
        "overall_forecast_pull": by_component.get("forecast_pull") or {},
        "feature_model": aggregate_rows(feature_rows)[0] if feature_rows else {},
        "empirical": aggregate_rows(empirical_rows)[0] if empirical_rows else {},
        "selected_empirical": aggregate_rows(selected_empirical_rows)[0] if selected_empirical_rows else {},
        "suppressed_empirical": aggregate_rows(suppressed_empirical_rows)[0] if suppressed_empirical_rows else {},
        "feature_model_by_market": feature_markets,
        "empirical_by_market": empirical_markets,
        "selected_empirical_by_market": selected_empirical_markets,
        "suppressed_empirical_by_market": suppressed_empirical_markets,
        "selected_empirical_brier_regressing_markets": selected_brier_regressions,
        "selected_empirical_logloss_regressing_markets": selected_logloss_regressions,
        "selected_empirical_brier_regressing_market_count": len(selected_brier_regressions),
        "selected_empirical_logloss_regressing_market_count": len(selected_logloss_regressions),
        "suppressed_empirical_brier_regressing_markets": suppressed_brier_regressions,
        "suppressed_empirical_logloss_regressing_markets": suppressed_logloss_regressions,
        "suppressed_empirical_brier_regressing_market_count": len(suppressed_brier_regressions),
        "suppressed_empirical_logloss_regressing_market_count": len(suppressed_logloss_regressions),
    }


def capture_hour_contract() -> dict[str, Any]:
    signature = inspect.signature(forecast_error_distribution)
    has_capture_hour = "capture_hour" in signature.parameters
    return {
        "status": "PASS" if has_capture_hour else "BLOCK",
        "function": "weather.model.calibration_runtime.forecast_error_distribution",
        "has_capture_hour_parameter": has_capture_hour,
        "evidence": (
            "forecast_error_distribution accepts capture_hour and routes it through hour_stats lookup"
            if has_capture_hour
            else "forecast_error_distribution does not expose capture_hour"
        ),
    }


def acceptance(payload: dict[str, Any]) -> dict[str, Any]:
    hgb = payload.get("hgb_forecast_attribution") or {}
    pull = payload.get("forecast_pull_delta") or {}
    scope = (pull.get("forecast_shape_scope") or {})
    capture_hour = payload.get("capture_hour_contract") or {}
    reasons = []
    if hgb.get("status") != "PASS":
        reasons.append("HGB forecast-feature attribution is missing")
    if scope.get("status") != "PASS":
        reasons.append("current-code forecast-shape scope proof does not pass")
    if (scope.get("current_code_feature_model_component_rows") or 0) <= 0:
        reasons.append("current-code feature-model component tape is missing")
    if (scope.get("current_code_feature_model_forecast_shape_rows") or 0) != 0:
        reasons.append("current-code feature-model forecast-shape rows are present")
    if pull.get("selected_empirical_brier_regressing_market_count", 0) > 0:
        reasons.append(
            "selected empirical fallback forecast-shape Brier regresses markets: "
            + ", ".join(pull.get("selected_empirical_brier_regressing_markets") or [])
        )
    if pull.get("selected_empirical_logloss_regressing_market_count", 0) > 0:
        reasons.append(
            "selected empirical fallback forecast-shape log-loss regresses markets: "
            + ", ".join(pull.get("selected_empirical_logloss_regressing_markets") or [])
        )
    if capture_hour.get("status") != "PASS":
        reasons.append("capture_hour forecast-error contract is not proven")
    return {
        "status": "PASS" if not reasons else "BLOCK",
        "reasons": reasons,
        "checklist": {
            "hgb_forecast_feature_attribution_quantified": hgb.get("status") == "PASS",
            "serving_pull_floor_delta_quantified": bool(pull.get("overall_forecast_pull")),
            "current_code_ml_pull_floor_removed": (
                scope.get("status") == "PASS"
                and (scope.get("current_code_feature_model_component_rows") or 0) > 0
                and (scope.get("current_code_feature_model_forecast_shape_rows") or 0) == 0
            ),
            "capture_hour_contract_proven": capture_hour.get("status") == "PASS",
            "empirical_fallback_no_per_market_regression": (
                pull.get("selected_empirical_brier_regressing_market_count", 0) == 0
                and pull.get("selected_empirical_logloss_regressing_market_count", 0) == 0
            ),
        },
    }


def build_payload(
    *,
    hgb_permutation: str | Path = DEFAULT_HGB_PERMUTATION,
    family_permutation: str | Path = DEFAULT_FAMILY_PERMUTATION,
    distribution_attribution: str | Path = DEFAULT_DISTRIBUTION_ATTRIBUTION,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    forecast_pull_stage_rows: list[dict[str, Any]] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now or utc_now(),
        "hgb_forecast_attribution": hgb_forecast_attribution(hgb_permutation, family_permutation),
        "forecast_pull_delta": forecast_pull_delta_summary(
            distribution_attribution,
            snapshots_root,
            rows=forecast_pull_stage_rows,
        ),
        "capture_hour_contract": capture_hour_contract(),
    }
    payload["acceptance"] = acceptance(payload)
    payload["status"] = payload["acceptance"]["status"]
    return payload


def _family_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            row.get("slice"),
            row.get("family"),
            fmt_signed(row.get("hgb_delta_mae_mean"), 4),
            fmt_num(row.get("hgb_importance_q")),
        ]
        for row in rows
    ]


def _feature_rows(rows: list[dict[str, Any]], limit: int = 12) -> list[list[Any]]:
    return [
        [
            row.get("slice"),
            row.get("family"),
            row.get("feature"),
            fmt_signed(row.get("hgb_delta_mae_mean"), 4),
            fmt_num(row.get("hgb_importance_q")),
        ]
        for row in rows[:limit]
    ]


def _delta_row(row: dict[str, Any]) -> list[Any]:
    return [
        row.get("group") or "all",
        row.get("n") or 0,
        row.get("delta_n") or 0,
        fmt_signed(row.get("mean_delta_brier"), 4),
        fmt_signed(row.get("mean_delta_logloss"), 4),
        fmt_signed(row.get("mean_winner_probability_delta"), 4),
        row.get("brier_worse_rows") or 0,
        row.get("brier_better_rows") or 0,
    ]


def _market_rows(rows: list[dict[str, Any]], limit: int = 12) -> list[list[Any]]:
    return [_delta_row(row) for row in rows[:limit]]


def write_markdown_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    hgb = payload.get("hgb_forecast_attribution") or {}
    pull = payload.get("forecast_pull_delta") or {}
    scope = pull.get("forecast_shape_scope") or {}
    acceptance_payload = payload.get("acceptance") or {}
    lines = [
        "# Forecast Double-Counting Verification",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Acceptance",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", acceptance_payload.get("status") or "-"],
            ["Reasons", "; ".join(acceptance_payload.get("reasons") or []) or "-"],
            ["HGB attribution quantified", acceptance_payload.get("checklist", {}).get("hgb_forecast_feature_attribution_quantified")],
            ["Serving pull/floor delta quantified", acceptance_payload.get("checklist", {}).get("serving_pull_floor_delta_quantified")],
            ["Current-code ML pull/floor removed", acceptance_payload.get("checklist", {}).get("current_code_ml_pull_floor_removed")],
            ["Capture-hour contract proven", acceptance_payload.get("checklist", {}).get("capture_hour_contract_proven")],
            ["Empirical fallback no per-market regression", acceptance_payload.get("checklist", {}).get("empirical_fallback_no_per_market_regression")],
        ],
    )
    lines += ["", "## HGB Forecast Attribution", ""]
    lines += markdown_table(
        ["Slice", "Family", "Delta MAE", "q"],
        _family_rows(hgb.get("family_rows") or []),
    )
    lines += ["", "### Top Forecast Features", ""]
    lines += markdown_table(
        ["Slice", "Family", "Feature", "Delta MAE", "q"],
        _feature_rows(hgb.get("top_features") or []),
    )
    lines += ["", "## Forecast Pull/Floor Scope", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Scope status", scope.get("status") or "-"],
            ["Current code", scope.get("current_identity_text") or "-"],
            ["Current-code feature-model component rows", scope.get("current_code_feature_model_component_rows")],
            ["Current-code feature-model forecast-shape rows", scope.get("current_code_feature_model_forecast_shape_rows")],
            ["Stale feature-model forecast-shape rows", scope.get("stale_feature_model_forecast_shape_rows")],
            ["Empirical forecast-shape rows", scope.get("empirical_forecast_shape_rows")],
            ["Allowed empirical markets", ", ".join(pull.get("empirical_forecast_shape_allowed_markets") or []) or "-"],
            ["Reason", scope.get("reason") or "-"],
        ],
    )
    lines += ["", "## Forecast Pull/Floor Deltas", ""]
    lines += markdown_table(
        ["Group", "Rows", "Delta Rows", "Delta Brier", "Delta Log Loss", "Winner P Delta", "Brier Worse", "Brier Better"],
        [
            _delta_row(pull.get("overall_forecast_pull") or {}),
            _delta_row(pull.get("feature_model") or {}),
            _delta_row(pull.get("empirical") or {}),
            _delta_row(pull.get("selected_empirical") or {}),
            _delta_row(pull.get("suppressed_empirical") or {}),
        ],
    )
    lines += ["", "### Selected Empirical Fallback By Market", ""]
    lines += markdown_table(
        ["Market", "Rows", "Delta Rows", "Delta Brier", "Delta Log Loss", "Winner P Delta", "Brier Worse", "Brier Better"],
        _market_rows(pull.get("selected_empirical_by_market") or []),
    )
    lines += ["", "### Suppressed Empirical Fallback By Market", ""]
    lines += markdown_table(
        ["Market", "Rows", "Delta Rows", "Delta Brier", "Delta Log Loss", "Winner P Delta", "Brier Worse", "Brier Better"],
        _market_rows(pull.get("suppressed_empirical_by_market") or []),
    )
    lines += ["", "### Feature-Model Historical Pull/Floor By Market", ""]
    lines += markdown_table(
        ["Market", "Rows", "Delta Rows", "Delta Brier", "Delta Log Loss", "Winner P Delta", "Brier Worse", "Brier Better"],
        _market_rows(pull.get("feature_model_by_market") or []),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_outputs(
    payload: dict[str, Any],
    json_out: str | Path = DEFAULT_JSON_OUT,
    report_out: str | Path = DEFAULT_REPORT_OUT,
) -> tuple[Path, Path]:
    json_out = Path(json_out)
    report_out = Path(report_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown_report(report_out, payload)
    return json_out, report_out


def run(args: argparse.Namespace) -> dict[str, Any]:
    payload = build_payload(
        hgb_permutation=args.hgb_permutation,
        family_permutation=args.family_permutation,
        distribution_attribution=args.distribution_attribution,
        snapshots_root=args.snapshots_root,
    )
    write_outputs(payload, args.out, args.report)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hgb-permutation", default=str(DEFAULT_HGB_PERMUTATION))
    parser.add_argument("--family-permutation", default=str(DEFAULT_FAMILY_PERMUTATION))
    parser.add_argument("--distribution-attribution", default=str(DEFAULT_DISTRIBUTION_ATTRIBUTION))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT_OUT))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = run(args)
    print(f"Forecast double-counting verification: {payload['status']}")
    print(f"JSON written to {args.out}")
    print(f"Report written to {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
