"""Forecast-profile calibration report for roadmap item 134."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table


SCHEMA_VERSION = "forecast_profile_calibration_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_CANDIDATE_JSON = DEFAULT_BACKTEST_ROOT / "item134_forecast_profile_replay.json"
DEFAULT_HGB_PERMUTATION = DEFAULT_BACKTEST_ROOT / "input_variable_significance_2026_06_18_hgb_permutation.csv"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item134_forecast_profile_calibration.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item134_forecast_profile_calibration_report.md"
DEFAULT_CURRENT_TOL = 0.003


SUBFAMILY_BY_FEATURE = {
    "forecast_high": "forecast_high_anchor",
    "forecast_gap": "forecast_gap",
    "forecast_source_count": "source_state_guardrail",
    "forecast_disagreement": "source_state_guardrail",
}


def forecast_profile_subfamily(feature: str) -> str:
    if feature in SUBFAMILY_BY_FEATURE:
        return SUBFAMILY_BY_FEATURE[feature]
    if feature.startswith("forecast_temp_") or feature in {
        "forecast_afternoon_slope",
        "forecast_remaining_degree_hours",
    }:
        return "hourly_temperature_profile"
    if any(token in feature for token in ("cloud", "solar", "radiation")):
        return "cloud_solar_radiation"
    if "ensemble" in feature or feature.endswith("_p10") or feature.endswith("_p90"):
        return "ensemble_spread"
    if "precip" in feature or "cape" in feature:
        return "precipitation_convective"
    if any(token in feature for token in ("925", "850", "lapse", "geopotential")):
        return "airmass_pressure_profile"
    if any(token in feature for token in ("soil", "vapour", "evapotranspiration")):
        return "surface_flux_soil"
    if "wind" in feature or "visibility" in feature:
        return "wind_visibility"
    if feature.startswith("forecast_"):
        return "other_forecast_profile"
    return "non_forecast"


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def forecast_profile_subfamily_rows(hgb_permutation_path: str | Path = DEFAULT_HGB_PERMUTATION) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "features": [],
            "positive_delta_sum": 0.0,
            "delta_sum": 0.0,
            "best_feature": None,
            "best_delta": None,
            "min_q": None,
        }
    )
    for row in _read_csv(hgb_permutation_path):
        feature = row.get("feature") or ""
        family = row.get("family") or ""
        if family not in {"open_meteo_forecast_profile", "forecast_source_state"}:
            continue
        subfamily = forecast_profile_subfamily(feature)
        if subfamily == "non_forecast":
            continue
        key = (row.get("slice") or "all", subfamily)
        item = grouped[key]
        delta = _safe_float(row.get("hgb_delta_mae_mean"))
        q_value = _safe_float(row.get("hgb_importance_q"))
        item["features"].append(feature)
        if delta is not None:
            item["delta_sum"] += delta
            if delta > 0:
                item["positive_delta_sum"] += delta
            if item["best_delta"] is None or delta > item["best_delta"]:
                item["best_delta"] = delta
                item["best_feature"] = feature
        if q_value is not None and (item["min_q"] is None or q_value < item["min_q"]):
            item["min_q"] = q_value

    rows = []
    for (slice_name, subfamily), item in sorted(grouped.items()):
        rows.append({
            "slice": slice_name,
            "subfamily": subfamily,
            "feature_count": len(item["features"]),
            "features": sorted(item["features"]),
            "positive_delta_mae_sum": item["positive_delta_sum"],
            "delta_mae_sum": item["delta_sum"],
            "best_feature": item["best_feature"],
            "best_feature_delta_mae": item["best_delta"],
            "min_hgb_importance_q": item["min_q"],
            "marginal_basis": (
                "anchor_feature"
                if subfamily == "forecast_high_anchor"
                else "marginal permutation with forecast_high retained in the fitted model"
            ),
        })
    return rows


def _regime_rows(candidate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row.get("group"): row
        for row in candidate.get("by_cutoff_regime") or []
        if row.get("group")
    }


def acceptance(candidate: dict[str, Any], *, current_tol: float = DEFAULT_CURRENT_TOL) -> dict[str, Any]:
    regimes = _regime_rows(candidate)
    early = regimes.get("early") or {}
    midday = regimes.get("midday") or {}
    late = regimes.get("late") or {}
    daily_first = candidate.get("daily_first") or {}
    blocked_validation = candidate.get("blocked_validation") or {}
    guardrails = candidate.get("forecast_profile_guardrails") or {}
    reasons = []
    if not candidate:
        reasons.append("missing forecast-profile candidate replay JSON")
    if (candidate.get("artifact") or {}).get("feature_subset") != "forecast_profile":
        reasons.append("candidate artifact is not a forecast_profile feature subset")
    if blocked_validation.get("passed") is not True:
        reasons.append("blocked daily-first validation did not pass")
    if daily_first.get("delta_vs_current") is None or daily_first.get("delta_vs_current") > 0:
        reasons.append("daily-first replay does not improve current replay")
    if early.get("delta_vs_current") is None or early.get("delta_vs_current") > 0:
        reasons.append("early-day slice does not improve current replay")
    for label, row in (("midday", midday), ("late", late)):
        delta = row.get("delta_vs_current")
        if delta is None:
            reasons.append(f"{label} slice is missing")
        elif delta > current_tol:
            reasons.append(f"{label} slice regresses current by {delta:+.4f} > {current_tol:.4f}")
    blocked_markets = guardrails.get("blocked_markets") or []
    if blocked_markets:
        reasons.append(
            "high-disagreement guardrail blocked "
            + ", ".join(str(item) for item in blocked_markets[:8])
        )
    return {
        "status": "pass" if not reasons else "blocked",
        "current_tolerance": current_tol,
        "reasons": reasons,
        "required_slices": {
            "early": early,
            "midday": midday,
            "late": late,
        },
    }


def build_report_payload(
    candidate_json: str | Path = DEFAULT_CANDIDATE_JSON,
    hgb_permutation: str | Path = DEFAULT_HGB_PERMUTATION,
    *,
    current_tol: float = DEFAULT_CURRENT_TOL,
) -> dict[str, Any]:
    candidate = _read_json(candidate_json)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "candidate_json": str(candidate_json),
            "hgb_permutation": str(hgb_permutation),
        },
        "candidate": {
            "artifact": candidate.get("artifact") or {},
            "aggregate": candidate.get("aggregate") or {},
            "daily_first": candidate.get("daily_first") or {},
            "by_cutoff_regime": candidate.get("by_cutoff_regime") or [],
            "by_forecast_source_count": candidate.get("by_forecast_source_count") or [],
            "by_forecast_disagreement": candidate.get("by_forecast_disagreement") or [],
            "by_forecast_bucket_pressure": candidate.get("by_forecast_bucket_pressure") or [],
            "forecast_profile_guardrails": candidate.get("forecast_profile_guardrails") or {},
            "blocked_validation": candidate.get("blocked_validation") or {},
            "verdict": candidate.get("verdict"),
            "cutover_decision": candidate.get("cutover_decision"),
        },
        "subfamilies": forecast_profile_subfamily_rows(hgb_permutation),
        "acceptance": acceptance(candidate, current_tol=current_tol),
    }


def _slice_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            row.get("group") or "-",
            row.get("n", 0),
            fmt_num(row.get("candidate_brier")),
            fmt_num(row.get("current_brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("delta_vs_current"), 4),
            fmt_signed(row.get("delta_vs_market"), 4),
        ]
        for row in rows
    ]


def _subfamily_rows(rows: list[dict[str, Any]], slice_name: str = "early") -> list[list[Any]]:
    return [
        [
            row.get("subfamily"),
            row.get("feature_count", 0),
            fmt_num(row.get("positive_delta_mae_sum")),
            fmt_num(row.get("best_feature_delta_mae")),
            row.get("best_feature") or "-",
            fmt_num(row.get("min_hgb_importance_q")),
            row.get("marginal_basis") or "-",
        ]
        for row in rows
        if row.get("slice") == slice_name
    ]


def write_markdown_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    candidate = payload.get("candidate") or {}
    artifact = candidate.get("artifact") or {}
    acceptance_payload = payload.get("acceptance") or {}
    lines = [
        "# Forecast-Profile Calibration",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Acceptance: `{acceptance_payload.get('status')}`",
        "",
        "## Candidate",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Artifact", artifact.get("path") or "-"],
            ["Schema", artifact.get("schema_version") or "-"],
            ["Feature subset", artifact.get("feature_subset") or "-"],
            ["Objective", artifact.get("objective") or "-"],
            ["Verdict", candidate.get("verdict") or "-"],
            ["Cutover decision", candidate.get("cutover_decision") or "-"],
            ["Blocked validation", (candidate.get("blocked_validation") or {}).get("verdict") or "-"],
            ["Acceptance reasons", "; ".join(acceptance_payload.get("reasons") or []) or "-"],
        ],
    )
    lines += ["", "## Cutoff-Regime Replay", ""]
    lines += markdown_table(
        ["Regime", "Rows", "Candidate Brier", "Current Brier", "Market Brier", "Delta Current", "Delta Market"],
        _slice_rows(candidate.get("by_cutoff_regime") or []),
    )
    lines += ["", "## Forecast-Profile Subfamilies After Forecast-High Anchor", ""]
    lines += markdown_table(
        [
            "Subfamily",
            "Features",
            "Positive Delta MAE Sum",
            "Best Feature Delta MAE",
            "Best Feature",
            "Min q",
            "Marginal Basis",
        ],
        _subfamily_rows(payload.get("subfamilies") or [], slice_name="all"),
    )
    lines += ["", "## Guardrail Slices", ""]
    for title, rows in [
        ("Forecast Source Count", candidate.get("by_forecast_source_count") or []),
        ("Forecast Disagreement", candidate.get("by_forecast_disagreement") or []),
        ("Forecast-Relative Bucket Pressure", candidate.get("by_forecast_bucket_pressure") or []),
    ]:
        lines += ["", f"### {title}", ""]
        lines += markdown_table(
            ["Group", "Rows", "Candidate Brier", "Current Brier", "Market Brier", "Delta Current", "Delta Market"],
            _slice_rows(rows),
        )
    guardrails = (candidate.get("forecast_profile_guardrails") or {}).get("rows") or []
    if guardrails:
        lines += ["", "## Per-Market High-Disagreement Guardrails", ""]
        lines += markdown_table(
            ["Market", "Status", "Rows", "Delta Current", "Delta Market", "Reasons"],
            [
                [
                    row.get("market_id"),
                    row.get("status"),
                    (row.get("comparison") or {}).get("n", 0),
                    fmt_signed((row.get("comparison") or {}).get("delta_vs_current"), 4),
                    fmt_signed((row.get("comparison") or {}).get("delta_vs_market"), 4),
                    "; ".join(row.get("reasons") or []) or "-",
                ]
                for row in guardrails
            ],
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run(args: argparse.Namespace) -> dict[str, Any]:
    payload = build_report_payload(
        args.candidate_json,
        args.hgb_permutation,
        current_tol=args.current_tol,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown_report(args.report, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build roadmap item 134 forecast-profile calibration report.")
    parser.add_argument("--candidate-json", default=str(DEFAULT_CANDIDATE_JSON))
    parser.add_argument("--hgb-permutation", default=str(DEFAULT_HGB_PERMUTATION))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--current-tol", type=float, default=DEFAULT_CURRENT_TOL)
    return parser


def main(argv: list[str] | None = None) -> int:
    payload = run(build_parser().parse_args(argv))
    print(f"Forecast-profile calibration: {payload['acceptance']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
