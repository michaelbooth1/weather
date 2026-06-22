"""Forecast radiation and insolation gate for roadmap item 187."""

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


SCHEMA_VERSION = "forecast_radiation_gate_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_CANDIDATE_JSON = DEFAULT_BACKTEST_ROOT / "item134_forecast_profile_all_hours_replay.json"
DEFAULT_HGB_PERMUTATION = DEFAULT_BACKTEST_ROOT / "input_variable_significance_2026_06_18_hgb_permutation.csv"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item187_forecast_radiation_gate.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item187_forecast_radiation_gate_report.md"
DEFAULT_CURRENT_TOL = 0.003

ISOLATED_RADIATION_SUBSETS = {
    "forecast_cloud_solar_radiation",
    "forecast_radiation",
    "forecast_shortwave_insolation",
}
RADIATION_FEATURES = (
    "forecast_remaining_solar_sum",
    "forecast_next_3h_solar_mean",
    "forecast_remaining_direct_radiation_sum",
    "forecast_remaining_diffuse_radiation_sum",
    "forecast_next_3h_direct_radiation_mean",
    "forecast_next_3h_diffuse_radiation_mean",
    "forecast_remaining_direct_radiation_share",
    "forecast_next_3h_direct_radiation_share",
)
CLOUD_PROXY_FEATURES = (
    "forecast_total_cloud_mean",
    "forecast_total_cloud_max",
    "forecast_low_cloud_mean",
    "forecast_low_cloud_max",
    "forecast_mid_cloud_mean",
    "forecast_high_cloud_mean",
    "forecast_cloud_trend_3h",
)
EXPECTED_FEATURES = RADIATION_FEATURES + CLOUD_PROXY_FEATURES
DIRECT_DIFFUSE_FEATURES = tuple(
    feature
    for feature in RADIATION_FEATURES
    if "direct" in feature or "diffuse" in feature
)
CONTEXT_FEATURE_FAMILIES = {"market_climate_context", "forecast_relative_band_geometry"}
FORECAST_PROFILE_FAMILIES = {"open_meteo_forecast_profile", "forecast_source_state"}


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


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _regime_rows(candidate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row.get("group"): row
        for row in candidate.get("by_cutoff_regime") or []
        if row.get("group")
    }


def isolated_radiation_artifact(candidate: dict[str, Any]) -> dict[str, Any]:
    artifact = candidate.get("artifact") or {}
    subset = artifact.get("feature_subset")
    contract = artifact.get("feature_subset_contract") or {}
    contract_name = contract.get("name")
    allowed_families = set(contract.get("allowed_feature_families") or [])

    reasons = []
    if subset in ISOLATED_RADIATION_SUBSETS:
        reasons.append(f"feature_subset={subset}")
    if contract_name in ISOLATED_RADIATION_SUBSETS:
        reasons.append(f"feature_subset_contract.name={contract_name}")
    if allowed_families and allowed_families <= ({"forecast_cloud_solar_radiation"} | CONTEXT_FEATURE_FAMILIES):
        reasons.append("feature_subset_contract.allowed_feature_families isolates forecast_cloud_solar_radiation")

    return {
        "isolated": bool(reasons),
        "basis": reasons,
        "feature_subset": subset,
        "contract_name": contract_name,
        "allowed_feature_families": sorted(allowed_families),
    }


def permutation_evidence(hgb_permutation_path: str | Path = DEFAULT_HGB_PERMUTATION) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "slices": set(),
            "families": set(),
            "positive_delta_mae_sum": 0.0,
            "delta_mae_sum": 0.0,
            "best_delta_mae": None,
            "min_hgb_importance_q": None,
        }
    )
    unexpected_rows = 0
    for row in _read_csv(hgb_permutation_path):
        feature = row.get("feature") or ""
        family = row.get("family") or ""
        if family not in FORECAST_PROFILE_FAMILIES:
            continue
        if feature not in EXPECTED_FEATURES:
            if any(token in feature for token in ("solar", "radiation", "cloud")):
                unexpected_rows += 1
            continue
        item = grouped[feature]
        item["slices"].add(row.get("slice") or "all")
        item["families"].add(family)
        delta = _safe_float(row.get("hgb_delta_mae_mean"))
        q_value = _safe_float(row.get("hgb_importance_q"))
        if delta is not None:
            item["delta_mae_sum"] += delta
            if delta > 0:
                item["positive_delta_mae_sum"] += delta
            if item["best_delta_mae"] is None or delta > item["best_delta_mae"]:
                item["best_delta_mae"] = delta
        if q_value is not None and (item["min_hgb_importance_q"] is None or q_value < item["min_hgb_importance_q"]):
            item["min_hgb_importance_q"] = q_value

    rows = []
    for feature in sorted(grouped):
        item = grouped[feature]
        rows.append({
            "feature": feature,
            "feature_kind": "radiation" if feature in RADIATION_FEATURES else "cloud_proxy",
            "slices": sorted(item["slices"]),
            "families": sorted(item["families"]),
            "positive_delta_mae_sum": item["positive_delta_mae_sum"],
            "delta_mae_sum": item["delta_mae_sum"],
            "best_delta_mae": item["best_delta_mae"],
            "min_hgb_importance_q": item["min_hgb_importance_q"],
        })

    observed = {row["feature"] for row in rows}
    missing_expected = [feature for feature in EXPECTED_FEATURES if feature not in observed]
    missing_direct_diffuse = [feature for feature in DIRECT_DIFFUSE_FEATURES if feature not in observed]
    missing_cloud_proxy = [feature for feature in CLOUD_PROXY_FEATURES if feature not in observed]
    best = max(rows, key=lambda row: row["best_delta_mae"] if row["best_delta_mae"] is not None else float("-inf"), default=None)

    return {
        "path": str(hgb_permutation_path),
        "expected_features": list(EXPECTED_FEATURES),
        "observed_expected_feature_count": len(observed),
        "missing_expected_features": missing_expected,
        "direct_diffuse_features_expected": list(DIRECT_DIFFUSE_FEATURES),
        "missing_direct_diffuse_features": missing_direct_diffuse,
        "missing_cloud_proxy_features": missing_cloud_proxy,
        "unexpected_radiation_cloud_rows": unexpected_rows,
        "best_feature": (best or {}).get("feature"),
        "best_delta_mae": (best or {}).get("best_delta_mae"),
        "rows": rows,
    }


def acceptance(
    candidate: dict[str, Any],
    evidence: dict[str, Any],
    *,
    current_tol: float = DEFAULT_CURRENT_TOL,
) -> dict[str, Any]:
    regimes = _regime_rows(candidate)
    blocked_validation = candidate.get("blocked_validation") or {}
    guardrails = candidate.get("forecast_profile_guardrails") or {}
    artifact_scope = isolated_radiation_artifact(candidate)
    blockers = []

    if not candidate:
        blockers.append({
            "code": "candidate_replay_missing",
            "detail": "missing candidate replay JSON",
        })
    if not artifact_scope["isolated"]:
        blockers.append({
            "code": "isolated_radiation_replay_missing",
            "detail": "candidate replay is not scoped to the forecast_cloud_solar_radiation family",
        })
    if evidence.get("observed_expected_feature_count", 0) == 0:
        blockers.append({
            "code": "permutation_evidence_missing",
            "detail": "no expected radiation or peak-window cloud rows were found in the HGB permutation artifact",
        })
    missing_direct_diffuse = evidence.get("missing_direct_diffuse_features") or []
    if missing_direct_diffuse:
        blockers.append({
            "code": "direct_diffuse_permutation_evidence_missing",
            "detail": ", ".join(missing_direct_diffuse),
        })
    missing_cloud_proxy = evidence.get("missing_cloud_proxy_features") or []
    if missing_cloud_proxy:
        blockers.append({
            "code": "peak_window_cloud_permutation_evidence_missing",
            "detail": ", ".join(missing_cloud_proxy),
        })
    if blocked_validation.get("passed") is not True:
        blockers.append({
            "code": "blocked_validation_failed",
            "detail": "; ".join(blocked_validation.get("reasons") or []) or "blocked validation did not pass",
        })

    for label in ("early", "midday"):
        delta = (regimes.get(label) or {}).get("delta_vs_current")
        if delta is None:
            blockers.append({"code": f"{label}_slice_missing", "detail": f"{label} cutoff slice is missing"})
        elif delta >= 0:
            blockers.append({
                "code": f"{label}_slice_no_current_lift",
                "detail": f"{label} delta_vs_current={delta:+.4f}",
            })
    late_delta = (regimes.get("late") or {}).get("delta_vs_current")
    if late_delta is None:
        blockers.append({"code": "late_slice_missing", "detail": "late cutoff slice is missing"})
    elif late_delta > current_tol:
        blockers.append({
            "code": "late_slice_regression",
            "detail": f"late delta_vs_current={late_delta:+.4f} > {current_tol:.4f}",
        })

    blocked_markets = guardrails.get("blocked_markets") or []
    if blocked_markets:
        blockers.append({
            "code": "market_guardrails_blocked",
            "detail": ", ".join(str(item) for item in blocked_markets[:12]),
        })

    return {
        "status": "PASS" if not blockers else "BLOCK",
        "current_tolerance": current_tol,
        "blockers": blockers,
        "artifact_scope": artifact_scope,
        "required_cutoff_slices": {
            "early": regimes.get("early") or {},
            "midday": regimes.get("midday") or {},
            "late": regimes.get("late") or {},
        },
    }


def build_report_payload(
    candidate_json: str | Path = DEFAULT_CANDIDATE_JSON,
    hgb_permutation: str | Path = DEFAULT_HGB_PERMUTATION,
    *,
    current_tol: float = DEFAULT_CURRENT_TOL,
) -> dict[str, Any]:
    candidate = _read_json(candidate_json)
    evidence = permutation_evidence(hgb_permutation)
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
            "forecast_profile_guardrails": candidate.get("forecast_profile_guardrails") or {},
            "blocked_validation": candidate.get("blocked_validation") or {},
            "verdict": candidate.get("verdict"),
            "cutover_decision": candidate.get("cutover_decision"),
        },
        "permutation_evidence": evidence,
        "acceptance": acceptance(candidate, evidence, current_tol=current_tol),
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


def _permutation_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            row.get("feature"),
            row.get("feature_kind"),
            ", ".join(row.get("slices") or []),
            fmt_num(row.get("positive_delta_mae_sum"), 6),
            fmt_num(row.get("best_delta_mae"), 6),
            fmt_num(row.get("min_hgb_importance_q"), 4),
        ]
        for row in rows
    ]


def write_markdown_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    candidate = payload.get("candidate") or {}
    artifact = candidate.get("artifact") or {}
    acceptance_payload = payload.get("acceptance") or {}
    evidence = payload.get("permutation_evidence") or {}
    artifact_scope = acceptance_payload.get("artifact_scope") or {}
    blockers = acceptance_payload.get("blockers") or []

    lines = [
        "# Forecast Radiation & Insolation Gate",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Gate status: `{acceptance_payload.get('status')}`",
        "",
        "## Candidate Scope",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Artifact", artifact.get("path") or "-"],
            ["Schema", artifact.get("schema_version") or "-"],
            ["Feature subset", artifact.get("feature_subset") or "-"],
            ["Contract", (artifact.get("feature_subset_contract") or {}).get("name") or "-"],
            ["Isolated radiation replay", "yes" if artifact_scope.get("isolated") else "no"],
            ["Isolation basis", "; ".join(artifact_scope.get("basis") or []) or "-"],
            ["Verdict", candidate.get("verdict") or "-"],
            ["Cutover decision", candidate.get("cutover_decision") or "-"],
            ["Blocked validation", (candidate.get("blocked_validation") or {}).get("verdict") or "-"],
        ],
    )
    lines += ["", "## Acceptance Blockers", ""]
    if blockers:
        lines += markdown_table(
            ["Code", "Detail"],
            [[blocker.get("code"), blocker.get("detail")] for blocker in blockers],
        )
    else:
        lines += ["No blockers."]

    lines += ["", "## Cutoff-Regime Replay", ""]
    lines += markdown_table(
        ["Regime", "Rows", "Candidate Brier", "Current Brier", "Market Brier", "Delta Current", "Delta Market"],
        _slice_rows(candidate.get("by_cutoff_regime") or []),
    )

    lines += ["", "## Permutation Evidence", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Expected features", len(evidence.get("expected_features") or [])],
            ["Observed expected features", evidence.get("observed_expected_feature_count", 0)],
            ["Missing direct/diffuse features", ", ".join(evidence.get("missing_direct_diffuse_features") or []) or "-"],
            ["Missing peak-window cloud features", ", ".join(evidence.get("missing_cloud_proxy_features") or []) or "-"],
            ["Best feature", evidence.get("best_feature") or "-"],
            ["Best feature delta MAE", fmt_num(evidence.get("best_delta_mae"), 6)],
        ],
    )
    lines += ["", "### Observed Expected Rows", ""]
    lines += markdown_table(
        ["Feature", "Kind", "Slices", "Positive Delta MAE Sum", "Best Delta MAE", "Min q"],
        _permutation_rows(evidence.get("rows") or []),
    )

    lines += [
        "",
        "## Next Unblock",
        "",
        (
            "Train/replay an isolated forecast_cloud_solar_radiation candidate, then regenerate the "
            "HGB permutation artifact with the current feature schema so direct/diffuse radiation "
            "and direct-share rows are present."
        ),
    ]

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
    parser = argparse.ArgumentParser(description="Build roadmap item 187 forecast radiation/insolation gate.")
    parser.add_argument("--candidate-json", default=str(DEFAULT_CANDIDATE_JSON))
    parser.add_argument("--hgb-permutation", default=str(DEFAULT_HGB_PERMUTATION))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--current-tol", type=float, default=DEFAULT_CURRENT_TOL)
    return parser


def main(argv: list[str] | None = None) -> int:
    payload = run(build_parser().parse_args(argv))
    print(f"Forecast radiation gate: {payload['acceptance']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
