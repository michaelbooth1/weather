"""Forecast radiation and insolation gate for roadmap item 187."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.calibration.pooled_candidate_replay_diagnostics import forecast_profile_guardrails
from weather.calibration.pooled_candidate_scoring import (
    blocked_candidate_validation_gate,
    candidate_comparison,
    daily_first_candidate_comparison,
    grouped_candidate_comparison,
)
from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table


SCHEMA_VERSION = "forecast_radiation_gate_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_CANDIDATE_JSON = DEFAULT_BACKTEST_ROOT / "item134_forecast_profile_all_hours_replay.json"
DEFAULT_HGB_PERMUTATION = DEFAULT_BACKTEST_ROOT / "input_variable_significance_2026_06_18_hgb_permutation.csv"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item187_forecast_radiation_gate.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item187_forecast_radiation_gate_report.md"
DEFAULT_CURRENT_TOL = 0.003
DEFAULT_MARKET_TOL = 0.003
DEFAULT_MIN_DAYS = 2

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


def _safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _market_list(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    items = value.split(",") if isinstance(value, str) else list(value)
    return sorted({str(item).strip() for item in items if str(item).strip()})


def _regime_rows(candidate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row.get("group"): row
        for row in candidate.get("by_cutoff_regime") or []
        if row.get("group")
    }


def candidate_rows_from_variant_csv(path: str | Path | None) -> list[dict[str, Any]]:
    """Convert an Item-69-style candidate variant CSV back into replay rows."""
    if not path:
        return []
    rows = []
    for row in _read_csv(path):
        candidate_p = _safe_float(row.get("probability"))
        replayed_p = _safe_float(row.get("current_probability"))
        recorded_p = _safe_float(row.get("recorded_probability"))
        market_yes = _safe_float(row.get("market_yes"))
        outcome = _safe_int(row.get("outcome"))
        if (
            candidate_p is None
            or replayed_p is None
            or recorded_p is None
            or market_yes is None
            or outcome is None
        ):
            continue
        cutoff_hour = _safe_int(row.get("cutoff_hour"))
        cutoff_regime = row.get("cutoff_regime") or ""
        bin_type = row.get("bin_type") or row.get("bin_kind") or ""
        rows.append({
            "market_id": row.get("market_id") or "",
            "target_date": row.get("target_date") or "",
            "snapshot_id": row.get("snapshot_id") or "",
            "candidate_p": candidate_p,
            "replayed_p": replayed_p,
            "recorded_p": recorded_p,
            "market_yes": market_yes,
            "outcome": outcome,
            "candidate_cutoff_hour": cutoff_hour,
            "cutoff_hour": cutoff_hour,
            "candidate_cutoff_regime": cutoff_regime,
            "cutoff_regime": cutoff_regime,
            "bin_type": bin_type,
            "band_kind": bin_type,
            "settlement_distance_bucket": row.get("settlement_distance_bucket") or "",
            "source_freshness_state": row.get("source_freshness_state") or "",
            "forecast_source_count_bucket": row.get("forecast_source_count_bucket") or "",
            "forecast_disagreement_bucket": row.get("forecast_disagreement_bucket") or "",
            "forecast_bucket_pressure": row.get("forecast_bucket_pressure") or "",
        })
    return rows


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


def _cutoff_current_lift_passes(rows: list[dict[str, Any]], *, current_tol: float) -> bool:
    regimes = {
        row.get("group"): row
        for row in grouped_candidate_comparison(rows, "candidate_cutoff_regime")
        if row.get("group")
    }
    for label in ("early", "midday"):
        delta = (regimes.get(label) or {}).get("delta_vs_current")
        if delta is None or delta >= 0:
            return False
    late_delta = (regimes.get("late") or {}).get("delta_vs_current")
    if late_delta is None or late_delta > current_tol:
        return False
    return True


def _market_gate_row(
    market_id: str,
    rows: list[dict[str, Any]],
    *,
    current_tol: float,
    market_tol: float,
    min_days: int,
) -> dict[str, Any]:
    validation = blocked_candidate_validation_gate(
        rows,
        current_tol=current_tol,
        market_tol=market_tol,
        min_days=min_days,
    )
    guardrails = forecast_profile_guardrails(rows)
    allowed = validation.get("passed") is True and not (guardrails.get("blocked_markets") or [])
    return {
        "market_id": market_id,
        "decision": "allow" if allowed else "quarantine",
        "validation": validation,
        "guardrails": guardrails,
        "daily_first": validation.get("daily_first") or {},
        "reasons": validation.get("reasons") or guardrails.get("blocked_markets") or [],
    }


def select_positive_market_lane(
    rows: list[dict[str, Any]],
    *,
    requested_markets: list[str] | None = None,
    current_tol: float = DEFAULT_CURRENT_TOL,
    market_tol: float = DEFAULT_MARKET_TOL,
    min_days: int = DEFAULT_MIN_DAYS,
) -> dict[str, Any]:
    by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        market_id = str(row.get("market_id") or "")
        if market_id:
            by_market[market_id].append(row)

    market_rows = [
        _market_gate_row(
            market_id,
            market_rows,
            current_tol=current_tol,
            market_tol=market_tol,
            min_days=min_days,
        )
        for market_id, market_rows in sorted(by_market.items())
    ]
    if requested_markets:
        allowed = sorted(set(requested_markets))
        policy = "requested_markets"
        reason = "Requested lane markets were supplied by the caller."
    else:
        candidates = sorted(row["market_id"] for row in market_rows if row.get("decision") == "allow")
        best: tuple[int, float, float, tuple[str, ...]] | None = None
        for size in range(1, len(candidates) + 1):
            for combo in itertools.combinations(candidates, size):
                combo_set = set(combo)
                subset = [row for row in rows if row.get("market_id") in combo_set]
                validation = blocked_candidate_validation_gate(
                    subset,
                    current_tol=current_tol,
                    market_tol=market_tol,
                    min_days=min_days,
                )
                daily = validation.get("daily_first") or {}
                if validation.get("passed") is not True:
                    continue
                if not _cutoff_current_lift_passes(subset, current_tol=current_tol):
                    continue
                score = (
                    len(combo),
                    -float(daily.get("delta_vs_market") or 0.0),
                    -float(daily.get("candidate_brier") or 0.0),
                    tuple(combo),
                )
                if best is None or score > best:
                    best = score
        allowed = list(best[3]) if best else []
        policy = "positive_markets_only"
        reason = (
            "Allowed markets individually pass daily-first validation and high-disagreement "
            "guardrails; the selected lane also preserves early/midday current lift with no "
            "late current regression."
        )

    all_markets = sorted(by_market)
    quarantined = sorted(market for market in all_markets if market not in set(allowed))
    lane_rows = [row for row in rows if row.get("market_id") in set(allowed)]
    validation = (
        blocked_candidate_validation_gate(
            lane_rows,
            current_tol=current_tol,
            market_tol=market_tol,
            min_days=min_days,
        )
        if lane_rows else {}
    )
    guardrails = forecast_profile_guardrails(lane_rows) if lane_rows else {}
    status = (
        "PARTIAL_POSITIVE_MARKET_SHADOW_LANE"
        if allowed and quarantined else
        "BROAD_POSITIVE_MARKET_SHADOW_LANE"
        if allowed else
        "BLOCKED_NO_POSITIVE_MARKETS"
    )
    return {
        "schema_version": "forecast_radiation_promotion_lane_v0.1",
        "status": status,
        "policy": policy,
        "reason": reason,
        "allowed_markets": allowed,
        "quarantined_markets": quarantined,
        "allowed_market_count": len(allowed),
        "quarantined_market_count": len(quarantined),
        "market_count": len(all_markets),
        "validation": validation,
        "cutoff_current_lift_passed": (
            _cutoff_current_lift_passes(lane_rows, current_tol=current_tol) if lane_rows else False
        ),
        "guardrails": guardrails,
        "markets": market_rows,
        "action": (
            "Allow forecast_cloud_solar_radiation influence only for allowed markets; keep "
            "quarantined markets on the no-radiation path until their daily-first validation "
            "and high-disagreement guardrails pass."
        ),
    }


def lane_scoped_candidate(
    candidate: dict[str, Any],
    rows: list[dict[str, Any]],
    lane: dict[str, Any],
    *,
    current_tol: float = DEFAULT_CURRENT_TOL,
    market_tol: float = DEFAULT_MARKET_TOL,
    min_days: int = DEFAULT_MIN_DAYS,
) -> dict[str, Any]:
    allowed = set(lane.get("allowed_markets") or [])
    scoped_rows = [row for row in rows if row.get("market_id") in allowed]
    output = dict(candidate)
    artifact = dict(output.get("artifact") or {})
    artifact["forecast_radiation_promotion_lane"] = lane
    artifact["source_family_lanes"] = {
        **(artifact.get("source_family_lanes") or {}),
        "forecast_cloud_solar_radiation": lane,
    }
    output["artifact"] = artifact
    output["promotion_lane"] = lane
    output["aggregate"] = candidate_comparison(scoped_rows) or {}
    output["daily_first"] = daily_first_candidate_comparison(scoped_rows) or {}
    output["by_cutoff_regime"] = grouped_candidate_comparison(scoped_rows, "candidate_cutoff_regime")
    output["by_market"] = grouped_candidate_comparison(scoped_rows, "market_id")
    output["forecast_profile_guardrails"] = forecast_profile_guardrails(scoped_rows)
    output["blocked_validation"] = (
        blocked_candidate_validation_gate(
            scoped_rows,
            current_tol=current_tol,
            market_tol=market_tol,
            min_days=min_days,
        )
        if scoped_rows else {
            "passed": False,
            "verdict": "BLOCK",
            "reasons": ["no allowed market rows"],
        }
    )
    output["verdict"] = "PASS" if output["blocked_validation"].get("passed") is True else "BLOCK"
    output["cutover_decision"] = (
        "POSITIVE_MARKET_LANE_READY"
        if output["verdict"] == "PASS" and not (output["forecast_profile_guardrails"].get("blocked_markets") or [])
        else "DO_NOT_CUT_OVER"
    )
    return output


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
    market_tol: float = DEFAULT_MARKET_TOL,
    min_days: int = DEFAULT_MIN_DAYS,
    candidate_variant_csv: str | Path | None = None,
    lane_allowed_markets: list[str] | str | None = None,
) -> dict[str, Any]:
    candidate = _read_json(candidate_json)
    variant_rows = candidate_rows_from_variant_csv(candidate_variant_csv)
    lane = {}
    if variant_rows:
        lane = select_positive_market_lane(
            variant_rows,
            requested_markets=_market_list(lane_allowed_markets),
            current_tol=current_tol,
            market_tol=market_tol,
            min_days=min_days,
        )
        candidate = lane_scoped_candidate(
            candidate,
            variant_rows,
            lane,
            current_tol=current_tol,
            market_tol=market_tol,
            min_days=min_days,
        )
    evidence = permutation_evidence(hgb_permutation)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "candidate_json": str(candidate_json),
            "hgb_permutation": str(hgb_permutation),
            "candidate_variant_csv": str(candidate_variant_csv) if candidate_variant_csv else None,
            "lane_allowed_markets": _market_list(lane_allowed_markets),
        },
        "candidate": {
            "artifact": candidate.get("artifact") or {},
            "aggregate": candidate.get("aggregate") or {},
            "daily_first": candidate.get("daily_first") or {},
            "by_cutoff_regime": candidate.get("by_cutoff_regime") or [],
            "forecast_profile_guardrails": candidate.get("forecast_profile_guardrails") or {},
            "blocked_validation": candidate.get("blocked_validation") or {},
            "promotion_lane": candidate.get("promotion_lane") or lane,
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


def _next_unblock_text(blockers: list[dict[str, Any]]) -> str:
    codes = {blocker.get("code") for blocker in blockers}
    structural = {
        "candidate_replay_missing",
        "isolated_radiation_replay_missing",
        "permutation_evidence_missing",
        "direct_diffuse_permutation_evidence_missing",
        "peak_window_cloud_permutation_evidence_missing",
    }
    if not blockers:
        return "No unblock remains; the isolated radiation replay and permutation evidence satisfy the gate."
    if codes & structural:
        return (
            "Train/replay an isolated forecast_cloud_solar_radiation candidate, then regenerate the "
            "HGB permutation artifact with the current feature schema so direct/diffuse radiation "
            "and direct-share rows are present."
        )
    remaining = "; ".join(
        f"{blocker.get('code')}: {blocker.get('detail')}"
        for blocker in blockers
        if blocker.get("code")
    )
    return (
        "Tune or quarantine the isolated forecast_cloud_solar_radiation lane until daily-first "
        "market-tolerance validation and high-disagreement market guardrails pass. "
        f"Remaining blockers: {remaining}."
    )


def write_markdown_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    candidate = payload.get("candidate") or {}
    artifact = candidate.get("artifact") or {}
    acceptance_payload = payload.get("acceptance") or {}
    evidence = payload.get("permutation_evidence") or {}
    artifact_scope = acceptance_payload.get("artifact_scope") or {}
    blockers = acceptance_payload.get("blockers") or []
    lane = candidate.get("promotion_lane") or artifact.get("forecast_radiation_promotion_lane") or {}

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
            ["Promotion lane", lane.get("status") or "-"],
            ["Allowed markets", ", ".join(lane.get("allowed_markets") or []) or "-"],
            ["Quarantined markets", ", ".join(lane.get("quarantined_markets") or []) or "-"],
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
        _next_unblock_text(blockers),
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run(args: argparse.Namespace) -> dict[str, Any]:
    payload = build_report_payload(
        args.candidate_json,
        args.hgb_permutation,
        current_tol=args.current_tol,
        market_tol=args.market_tol,
        min_days=args.min_days,
        candidate_variant_csv=args.candidate_variant_csv,
        lane_allowed_markets=args.lane_allowed_markets,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown_report(args.report, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build roadmap item 187 forecast radiation/insolation gate.")
    parser.add_argument("--candidate-json", default=str(DEFAULT_CANDIDATE_JSON))
    parser.add_argument("--hgb-permutation", default=str(DEFAULT_HGB_PERMUTATION))
    parser.add_argument("--candidate-variant-csv", default=None)
    parser.add_argument("--lane-allowed-markets", default=None,
                        help="Comma-separated market ids for an explicit lane. Omit to auto-select positive markets.")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--current-tol", type=float, default=DEFAULT_CURRENT_TOL)
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--min-days", type=int, default=DEFAULT_MIN_DAYS)
    return parser


def main(argv: list[str] | None = None) -> int:
    payload = run(build_parser().parse_args(argv))
    print(f"Forecast radiation gate: {payload['acceptance']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
