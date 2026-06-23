"""Canonical proof packet for weather-only model readiness."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.calibration.pooled_feature_model import DEFAULT_BAND_ARTIFACT
from weather.paths import data_path, docs_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.pooled_f_retrain_location_gate import artifact_summary
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("weather_only_model_proof_packet")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_ROADMAP_ROOT = docs_path("roadmap")
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "weather_only_model_proof_packet.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "weather_only_model_proof_packet_report.md"
DEFAULT_ARTIFACT = DEFAULT_BAND_ARTIFACT
DEFAULT_PROMOTION_REFRESH = DEFAULT_BACKTEST_ROOT / "f_family_promotion_refresh.json"
DEFAULT_HOURLY = DEFAULT_BACKTEST_ROOT / "hourly_model_performance.json"
DEFAULT_TEN_MINUTE = DEFAULT_BACKTEST_ROOT / "ten_minute_model_performance.json"
DEFAULT_EXACT_DISTANCE = DEFAULT_BACKTEST_ROOT / "exact_band_distance_zero_calibration.json"
DEFAULT_BOTTOM_LOCATION = DEFAULT_BACKTEST_ROOT / "bottom_location_winner_centering.json"
DEFAULT_FLEET = DEFAULT_BACKTEST_ROOT / "fleet_observability.json"
DEFAULT_PROGRESS_AUDIT = DEFAULT_BACKTEST_ROOT / "progress_audit.json"
DEFAULT_DAILY_PROGRESS = DEFAULT_BACKTEST_ROOT / "daily_progress_latest.json"
DEFAULT_SERVED_DISTRIBUTION = DEFAULT_BACKTEST_ROOT / "served_distribution_calibration_contract.json"
DEFAULT_POSITIVE_DAILY_FIRST = DEFAULT_BACKTEST_ROOT / "early_hour_positive_daily_first_gate.json"
DEFAULT_AUSTIN_REQUALIFICATION = DEFAULT_BACKTEST_ROOT / "austin_hgb_requalification.json"
DEFAULT_WINNER_RANK_PARITY = DEFAULT_BACKTEST_ROOT / "winner_rank_parity.json"

MODEL_ITEM_PACKET_FIELDS = {
    48: "market_dispositions",
    147: "gates.hourly_gate",
    160: "gates.broad_claim_gate",
    178: "gates.served_distribution_contract",
    219: "gates.bottom_location_gate",
    224: "gates.active_artifact_identity",
    228: "gates.ten_minute_gate",
    230: "gates.exact_band_distance_zero_gate",
    233: "gates.served_distribution_contract",
    250: "hard_slices.austin_hgb_requalification",
    266: "gates.winner_rank_parity_gate",
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _path_exists(path: str | Path | None) -> bool:
    return bool(path) and Path(path).exists()


def _status(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _passes(value: Any) -> bool:
    return str(value or "").upper() in {"PASS", "READY", "OK", "ALLOW", "ALLOWED", "PROVEN"}


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_blocker_detail(payload: dict[str, Any] | None) -> str:
    payload = payload or {}
    first = payload.get("first_blocker") or {}
    if isinstance(first, dict):
        detail = first.get("detail") or first.get("gate") or first.get("category")
        if detail:
            return str(detail)
    blockers = payload.get("blockers") or []
    if blockers and isinstance(blockers[0], dict):
        return str(
            blockers[0].get("detail")
            or blockers[0].get("gate")
            or blockers[0].get("category")
            or ""
        )
    return ""


def _gate(
    field: str,
    status: str,
    detail: str,
    evidence: dict[str, Any] | None = None,
    *,
    supersedes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "field": f"gates.{field}",
        "gate": field,
        "status": status,
        "detail": detail,
        "evidence": evidence or {},
        "supersedes": supersedes or [],
    }


def _simple_gate_summary(path: str | Path, *, status_key: str = "status") -> dict[str, Any]:
    payload = read_json(path)
    return {
        "path": str(path),
        "exists": _path_exists(path),
        "schema_version": (payload or {}).get("schema_version"),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": _status((payload or {}).get(status_key) or (payload or {}).get("gate_status")),
        "acceptance_passed": (payload or {}).get("acceptance_passed"),
        "blocker_count": (payload or {}).get("blocker_count", len((payload or {}).get("blockers") or [])),
        "first_blocker": _first_blocker_detail(payload),
        "summary": (payload or {}).get("summary") or {},
    }


def winner_rank_parity_summary(path: str | Path) -> dict[str, Any]:
    payload = read_json(path)
    gate = (payload or {}).get("parity_gate") or {}
    summary = (payload or {}).get("summary") or {}
    primary = (payload or {}).get("primary_weather_only") or {}
    return {
        "path": str(path),
        "exists": _path_exists(path),
        "schema_version": (payload or {}).get("schema_version"),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": _status(gate.get("status") or (payload or {}).get("status")),
        "blocker_count": gate.get("blocker_count", len(gate.get("blockers") or [])),
        "first_blocker": _first_blocker_detail(gate),
        "model_top_hit_rate": summary.get("model_top_hit_rate") or primary.get("model_top_hit_rate"),
        "market_top_hit_rate": summary.get("market_top_hit_rate") or primary.get("market_top_hit_rate"),
        "market_top_model_miss_excess": (
            summary.get("market_top_model_miss_excess")
            if summary.get("market_top_model_miss_excess") is not None
            else primary.get("market_top_model_miss_excess")
        ),
        "winner_probability_gap_market_minus_model": (
            summary.get("winner_probability_gap_market_minus_model")
            if summary.get("winner_probability_gap_market_minus_model") is not None
            else primary.get("winner_probability_gap_market_minus_model")
        ),
        "brier_contribution": (
            summary.get("brier_contribution")
            if summary.get("brier_contribution") is not None
            else primary.get("model_top_miss_market_top_hit_brier_contribution")
        ),
        "summary": summary,
        "gate": gate,
    }


def austin_requalification_summary(path: str | Path) -> dict[str, Any]:
    payload = read_json(path)
    hard_slices = (payload or {}).get("hard_slices") or []
    first_slice = hard_slices[0] if hard_slices else {}
    return {
        "path": str(path),
        "exists": _path_exists(path),
        "schema_version": (payload or {}).get("schema_version"),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": _status((payload or {}).get("status")),
        "market_id": (payload or {}).get("market_id"),
        "serving_disposition": (payload or {}).get("serving_disposition"),
        "requalification_verdict": (payload or {}).get("requalification_verdict"),
        "requalification_blocker_count": (payload or {}).get("requalification_blocker_count"),
        "first_requalification_blocker": (
            ((payload or {}).get("first_requalification_blocker") or {}).get("detail")
            or ((payload or {}).get("first_requalification_blocker") or {}).get("gate")
            or ""
        ),
        "hard_slice_id": first_slice.get("slice_id"),
        "hard_slice_target_date": first_slice.get("target_date"),
        "proof_packet_disposition": ((payload or {}).get("summary") or {}).get("proof_packet_disposition"),
        "local_delta_vs_market": ((payload or {}).get("summary") or {}).get("local_delta_vs_market"),
        "exact_distance_status": ((payload or {}).get("summary") or {}).get("exact_distance_status"),
    }


def promotion_summary(path: str | Path) -> dict[str, Any]:
    payload = read_json(path)
    candidate = (payload or {}).get("candidate") or {}
    artifact = candidate.get("artifact") or {}
    shadow = candidate.get("candidate_shadow_variants") or {}
    readiness = (payload or {}).get("readiness") or {}
    source_gate = (payload or {}).get("source_missingness_location_gate") or {}
    claims = (payload or {}).get("model_skill_claims") or {}
    weather_claim = claims.get("weather_only_core_model") or {}
    quote_risk = claims.get("market_informed_quote_risk") or {}
    decisions = (payload or {}).get("decisions") or {}
    aggregate = candidate.get("aggregate") or {}
    return {
        "path": str(path),
        "exists": _path_exists(path),
        "schema_version": (payload or {}).get("schema_version"),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "candidate": {
            "verdict": candidate.get("verdict"),
            "cutover_decision": candidate.get("cutover_decision"),
            "artifact_id": artifact.get("artifact_id") or artifact.get("path"),
            "artifact_path": artifact.get("path"),
            "variant_id": shadow.get("variant_id"),
            "active_registry_contract": shadow.get("active_registry_contract") or shadow.get("registry_contract"),
            "uses_market_features": shadow.get("uses_market_features"),
            "rows": aggregate.get("rows") or aggregate.get("n"),
            "delta_vs_current": aggregate.get("delta_vs_current"),
            "delta_vs_market": aggregate.get("delta_vs_market"),
        },
        "readiness": {
            "status": readiness.get("status"),
            "blocker_count": len(readiness.get("blockers") or []),
            "first_blocker": _first_blocker_detail(readiness),
        },
        "source_missingness_location_gate": {
            "status": source_gate.get("status"),
            "blocker_count": source_gate.get("blocker_count", len(source_gate.get("blockers") or [])),
            "first_blocker": _first_blocker_detail(source_gate),
        },
        "weather_only_core_model": {
            "broad_market_skill_claim_allowed": weather_claim.get("broad_market_skill_claim_allowed"),
            "reason": weather_claim.get("reason"),
            "delta_vs_market": weather_claim.get("delta_vs_market"),
            "daily_first_passed": weather_claim.get("daily_first_passed"),
        },
        "market_informed_quote_risk": {
            "counts_toward_core_skill_claim": quote_risk.get("counts_toward_core_skill_claim"),
            "reason": quote_risk.get("reason"),
        },
        "decisions": decisions,
        "raw": payload or {},
    }


def hourly_summary(path: str | Path) -> dict[str, Any]:
    payload = read_json(path)
    gate = (payload or {}).get("hourly_performance_gate") or {}
    return {
        "path": str(path),
        "exists": _path_exists(path),
        "schema_version": (payload or {}).get("schema_version"),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": gate.get("status"),
        "blocker_count": gate.get("blocker_count", len(gate.get("blockers") or [])),
        "first_blocker": _first_blocker_detail(gate),
        "daily_summary": (payload or {}).get("daily_summary") or {},
        "early_hour_market_deltas": ((payload or {}).get("remediation_registry") or {}).get(
            "early_hour_market_deltas"
        )
        or [],
    }


def ten_minute_summary(path: str | Path) -> dict[str, Any]:
    payload = read_json(path)
    gate = (payload or {}).get("ten_minute_performance_gate") or {}
    return {
        "path": str(path),
        "exists": _path_exists(path),
        "schema_version": (payload or {}).get("schema_version"),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": gate.get("status"),
        "blocker_count": gate.get("blocker_count", len(gate.get("blockers") or [])),
        "first_blocker": _first_blocker_detail(gate),
        "weak_slots": (payload or {}).get("weak_slots") or {},
        "daily_summary": (payload or {}).get("daily_summary") or {},
    }


def fleet_live_forward_summary(path: str | Path) -> dict[str, Any]:
    payload = read_json(path)
    live_slo = (payload or {}).get("live_forward_slo") or {}
    first = live_slo.get("first_blocker") or next(iter(live_slo.get("recovery_checklist") or []), {})
    return {
        "path": str(path),
        "exists": _path_exists(path),
        "fleet_status": (payload or {}).get("status"),
        "status": live_slo.get("status"),
        "counts_toward_live_forward_gate": live_slo.get("counts_toward_live_forward_gate"),
        "reason": live_slo.get("reason"),
        "first_blocker": first,
        "summary": live_slo.get("summary") or {},
    }


def broad_claim_summary(progress_audit: str | Path, daily_progress: str | Path) -> dict[str, Any]:
    progress = read_json(progress_audit)
    daily = read_json(daily_progress)
    claim = (progress or {}).get("core_model_trend_claim") or {}
    return {
        "progress_audit": {
            "path": str(progress_audit),
            "exists": _path_exists(progress_audit),
            "status": claim.get("status"),
            "claim_allowed": claim.get("claim_allowed"),
            "threshold_failures": claim.get("threshold_failures") or [],
            "next_evidence_needed": claim.get("next_evidence_needed") or [],
            "summary": claim.get("summary") or {},
        },
        "daily_progress": {
            "path": str(daily_progress),
            "exists": _path_exists(daily_progress),
            "broad_improvement_claim_allowed": (daily or {}).get("broad_improvement_claim_allowed"),
            "broad_improvement_claim_failures": (daily or {}).get("broad_improvement_claim_failures"),
        },
    }


def evidence_class(promotion: dict[str, Any], artifact: dict[str, Any]) -> str:
    candidate = promotion.get("candidate") or {}
    if artifact.get("loaded") and candidate.get("artifact_path"):
        return "active_artifact"
    if candidate.get("active_registry_contract"):
        return "active_replay_contract"
    if candidate.get("variant_id") or candidate.get("rows"):
        return "row_export_surrogate"
    return "diagnostic_only"


def build_gates(
    *,
    artifact: dict[str, Any],
    promotion: dict[str, Any],
    hourly: dict[str, Any],
    ten_minute: dict[str, Any],
    exact_distance: dict[str, Any],
    bottom_location: dict[str, Any],
    fleet: dict[str, Any],
    broad_claim: dict[str, Any],
    served_distribution: dict[str, Any],
    positive_daily_first: dict[str, Any],
    winner_rank_parity: dict[str, Any],
) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    artifact_ok = bool(
        artifact.get("exists")
        and artifact.get("loaded")
        and artifact.get("feature_schema_version") == artifact.get("active_feature_schema_version")
    )
    gates.append(_gate(
        "active_artifact_identity",
        "PASS" if artifact_ok else "BLOCK",
        (
            f"active artifact {artifact.get('path')} matches feature schema {artifact.get('active_feature_schema_version')}"
            if artifact_ok
            else (
                f"active artifact identity is not proof-grade: loaded={artifact.get('loaded')}, "
                f"artifact_schema={artifact.get('feature_schema_version')}, "
                f"active_schema={artifact.get('active_feature_schema_version')}"
            )
        ),
        artifact,
    ))

    readiness = promotion.get("readiness") or {}
    gates.append(_gate(
        "promotion_refresh_readiness",
        "PASS" if _passes(readiness.get("status")) else "BLOCK",
        (
            "promotion refresh readiness passed"
            if _passes(readiness.get("status"))
            else readiness.get("first_blocker") or "promotion refresh readiness is not clear"
        ),
        promotion,
    ))

    gates.append(_gate(
        "hourly_gate",
        "PASS" if _passes(hourly.get("status")) else "BLOCK",
        (
            "hourly model-performance gate passed"
            if _passes(hourly.get("status"))
            else hourly.get("first_blocker") or "hourly model-performance gate is not clear"
        ),
        hourly,
    ))

    gates.append(_gate(
        "ten_minute_gate",
        "PASS" if _passes(ten_minute.get("status")) else "BLOCK",
        (
            "10-minute weak-slot gate passed"
            if _passes(ten_minute.get("status"))
            else ten_minute.get("first_blocker") or "10-minute weak-slot gate is not clear"
        ),
        ten_minute,
    ))

    gates.append(_gate(
        "exact_band_distance_zero_gate",
        "PASS" if _passes(exact_distance.get("status")) else "BLOCK",
        (
            "exact-band and settlement-distance-0 gate passed"
            if _passes(exact_distance.get("status"))
            else exact_distance.get("first_blocker") or "exact-band and settlement-distance-0 gate is not clear"
        ),
        exact_distance,
    ))

    gates.append(_gate(
        "bottom_location_gate",
        "PASS" if _passes(bottom_location.get("status")) else "BLOCK",
        (
            "bottom-location gate passed"
            if _passes(bottom_location.get("status"))
            else bottom_location.get("first_blocker") or "bottom-location gate is not clear"
        ),
        bottom_location,
    ))

    source_gate = promotion.get("source_missingness_location_gate") or {}
    gates.append(_gate(
        "source_missingness_gate",
        "PASS" if _passes(source_gate.get("status")) else "BLOCK",
        (
            "source/missingness location gate passed"
            if _passes(source_gate.get("status"))
            else source_gate.get("first_blocker") or "source/missingness location gate is not clear"
        ),
        source_gate,
    ))

    live_counts = fleet.get("counts_toward_live_forward_gate")
    live_ok = live_counts is not False and _passes(fleet.get("status"))
    gates.append(_gate(
        "live_forward_evidence_state",
        "PASS" if live_ok else "BLOCK",
        (
            "live-forward evidence counts for broad model review"
            if live_ok
            else fleet.get("reason") or "live-forward evidence is not countable"
        ),
        fleet,
    ))

    parity_ok = _passes(winner_rank_parity.get("status"))
    gates.append(_gate(
        "winner_rank_parity_gate",
        "PASS" if parity_ok else "BLOCK",
        (
            "winner-rank parity gate passed"
            if parity_ok
            else winner_rank_parity.get("first_blocker")
            or "winner-rank parity gap is above tolerance or parity report is missing"
        ),
        winner_rank_parity,
    ))

    progress = (broad_claim.get("progress_audit") or {})
    daily = (broad_claim.get("daily_progress") or {})
    progress_allowed = progress.get("claim_allowed") is True and _passes(progress.get("status"))
    daily_allowed = daily.get("broad_improvement_claim_allowed")
    daily_allowed = True if daily_allowed is None else bool(daily_allowed)
    weather_claim = promotion.get("weather_only_core_model") or {}
    promotion_allowed = weather_claim.get("broad_market_skill_claim_allowed") is True
    broad_ok = progress_allowed and daily_allowed and promotion_allowed
    gates.append(_gate(
        "broad_claim_gate",
        "PASS" if broad_ok else "BLOCK",
        (
            "promotion refresh, progress audit, and daily ledger allow the weather-only broad claim"
            if broad_ok
            else (
                weather_claim.get("reason")
                or "; ".join(progress.get("threshold_failures") or [])
                or "weather-only broad claim is not allowed"
            )
        ),
        {
            "promotion_refresh": weather_claim,
            "progress_audit": progress,
            "daily_progress": daily,
        },
    ))

    gates.append(_gate(
        "served_distribution_contract",
        "PASS" if _passes(served_distribution.get("status")) and served_distribution.get("acceptance_passed") is True else "BLOCK",
        (
            "served-distribution calibration contract passed"
            if _passes(served_distribution.get("status")) and served_distribution.get("acceptance_passed") is True
            else served_distribution.get("first_blocker") or "served-distribution calibration contract is not clear"
        ),
        served_distribution,
    ))

    gates.append(_gate(
        "positive_daily_first_gate",
        "PASS" if _passes(positive_daily_first.get("status")) and positive_daily_first.get("acceptance_passed") is True else "BLOCK",
        (
            "positive daily-first gate passed"
            if _passes(positive_daily_first.get("status")) and positive_daily_first.get("acceptance_passed") is True
            else positive_daily_first.get("first_blocker") or "positive daily-first gate is not clear"
        ),
        positive_daily_first,
    ))

    lane = promotion.get("market_informed_quote_risk") or {}
    lane_ok = lane.get("counts_toward_core_skill_claim") is not True
    gates.append(_gate(
        "weather_only_lane_separation",
        "PASS" if lane_ok else "BLOCK",
        (
            "market-informed and trading proof packets remain outside the weather-only lane"
            if lane_ok
            else "market-informed evidence is counted toward the weather-only core claim"
        ),
        {
            "market_informed_quote_risk": lane,
            "trading_taker_packet_counts_toward_weather_only": False,
            "clob_overlay_counts_toward_weather_only": False,
        },
    ))
    return gates


def _decision_metrics(row: dict[str, Any]) -> dict[str, Any]:
    metrics = row.get("metrics") or {}
    return {
        "candidate_brier": _safe_float(metrics.get("candidate_brier")),
        "current_brier": _safe_float(metrics.get("current_brier")),
        "market_brier": _safe_float(metrics.get("market_brier")),
        "delta_vs_current": _safe_float(metrics.get("delta_vs_current")),
        "delta_vs_market": _safe_float(metrics.get("delta_vs_market")),
    }


def market_dispositions(
    promotion: dict[str, Any],
    gates: list[dict[str, Any]],
    evidence_basis: str,
) -> list[dict[str, Any]]:
    decisions = (promotion.get("decisions") or {}).get("markets") or []
    global_blocker = next((gate for gate in gates if gate.get("status") == "BLOCK"), None)
    rows: list[dict[str, Any]] = []
    for decision in decisions:
        action = decision.get("action")
        metrics = _decision_metrics(decision)
        if action == "BLOCK_CANDIDATE":
            disposition = "BLOCK"
            first_blocker = decision.get("reason") or "promotion refresh blocked this market"
            blocking_slice = "promotion_refresh_market_decision"
        elif action == "PROMOTE_CANDIDATE" and global_blocker is None:
            disposition = "PROMOTE"
            first_blocker = ""
            blocking_slice = ""
        elif action == "PROMOTE_CANDIDATE":
            disposition = "SHADOW"
            first_blocker = global_blocker.get("detail") or "global proof-packet blocker"
            blocking_slice = global_blocker.get("field")
        else:
            disposition = "SHADOW"
            first_blocker = decision.get("reason") or (
                global_blocker.get("detail") if global_blocker else "kept in shadow by promotion refresh"
            )
            blocking_slice = "promotion_refresh_shadow_decision"
        rows.append({
            "market_id": decision.get("market_id"),
            "city": decision.get("city"),
            "promotion_refresh_action": action,
            "disposition": disposition,
            "first_blocking_slice": blocking_slice,
            "first_blocker": first_blocker,
            "delta_vs_current": metrics.get("delta_vs_current"),
            "delta_vs_market": metrics.get("delta_vs_market"),
            "candidate_brier": metrics.get("candidate_brier"),
            "current_brier": metrics.get("current_brier"),
            "market_brier": metrics.get("market_brier"),
            "evidence_basis": evidence_basis,
        })
    return sorted(rows, key=lambda row: str(row.get("market_id") or ""))


def ratchet_report(gates: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        {
            "gate": "pooled_f_retrain_location_gate",
            "classification": "superseded",
            "proof_packet_field": "gates.broad_claim_gate",
            "detail": "Use the packet broad-claim field as the ordering source; the source gate remains an input.",
        },
        {
            "gate": "served_distribution_calibration_contract",
            "classification": "input_gate",
            "proof_packet_field": "gates.served_distribution_contract",
            "detail": "Keep as a validate-what-you-serve input; do not order separate readiness work from it alone.",
        },
        {
            "gate": "winner_rank_parity",
            "classification": "input_gate",
            "proof_packet_field": "gates.winner_rank_parity_gate",
            "detail": "Blocks broad weather-only claims while model top-rank misses market top hits above tolerance.",
        },
        {
            "gate": "early_hour_positive_daily_first_gate",
            "classification": "input_gate",
            "proof_packet_field": "gates.positive_daily_first_gate",
            "detail": "Counts only through the proof packet until it changes a promotion disposition.",
        },
        {
            "gate": "price_free_model_learning",
            "classification": "diagnostic_only",
            "proof_packet_field": "",
            "detail": "No-market or inactive-day diagnostics can suggest repairs but cannot clear weather-only readiness.",
        },
        {
            "gate": "clob_overlay_or_taker_trading_packet",
            "classification": "separate_lane",
            "proof_packet_field": "gates.weather_only_lane_separation",
            "detail": "CLOB overlays and taker profitability stay out of the weather-only proof packet.",
        },
    ]
    proof_fields = {row.get("field") for row in gates}
    return {
        "status": "PASS" if proof_fields else "BLOCK",
        "policy": (
            "A new model-readiness gate must replace a proof-packet field or remain "
            "diagnostic-only until it changes a market disposition."
        ),
        "proof_packet_fields": sorted(field for field in proof_fields if field),
        "rows": rows,
    }


def _item_path_for_number(root: Path, number: int) -> Path | None:
    items_root = root / "items" if (root / "items").exists() else root
    matches = sorted(items_root.glob(f"item-{number}-*.md"))
    return matches[0] if matches else None


def roadmap_reference_check(
    roadmap_root: str | Path = DEFAULT_ROADMAP_ROOT,
    *,
    model_item_packet_fields: dict[int, str] | None = None,
) -> dict[str, Any]:
    root = Path(roadmap_root)
    mapping = model_item_packet_fields or MODEL_ITEM_PACKET_FIELDS
    rows = []
    for number, field in sorted(mapping.items()):
        path = _item_path_for_number(root, number)
        text = path.read_text(encoding="utf-8", errors="replace") if path and path.exists() else ""
        heading_match = re.match(r"^# \d+\. (.+?) \[([^\]]+)\]", text.splitlines()[0] if text else "")
        active = bool(heading_match and not heading_match.group(2).startswith("COMPLETE"))
        if not active:
            continue
        lower = text.lower()
        diagnostic_only = "diagnostic-only" in lower or "diagnostic_only" in lower
        references_field = field.lower() in lower
        status = "PASS" if references_field or diagnostic_only else "BLOCK"
        rows.append({
            "item": number,
            "title": heading_match.group(1) if heading_match else "",
            "status": status,
            "path": str(path) if path else "",
            "expected_packet_field": field,
            "references_packet_field": references_field,
            "diagnostic_only": diagnostic_only,
            "detail": (
                "active item references proof-packet field"
                if references_field
                else "active item is explicitly diagnostic-only"
                if diagnostic_only
                else "active model item must reference a proof-packet blocker or mark itself diagnostic-only"
            ),
        })
    counts = Counter(row["status"] for row in rows)
    return {
        "status": "PASS" if counts.get("BLOCK", 0) == 0 else "BLOCK",
        "checked_item_count": len(rows),
        "blocking_item_count": counts.get("BLOCK", 0),
        "rows": rows,
    }


def build_payload(
    *,
    artifact_path: str | Path = DEFAULT_ARTIFACT,
    promotion_refresh: str | Path = DEFAULT_PROMOTION_REFRESH,
    hourly: str | Path = DEFAULT_HOURLY,
    ten_minute: str | Path = DEFAULT_TEN_MINUTE,
    exact_distance: str | Path = DEFAULT_EXACT_DISTANCE,
    bottom_location: str | Path = DEFAULT_BOTTOM_LOCATION,
    fleet_observability: str | Path = DEFAULT_FLEET,
    progress_audit: str | Path = DEFAULT_PROGRESS_AUDIT,
    daily_progress: str | Path = DEFAULT_DAILY_PROGRESS,
    served_distribution: str | Path = DEFAULT_SERVED_DISTRIBUTION,
    positive_daily_first: str | Path = DEFAULT_POSITIVE_DAILY_FIRST,
    austin_requalification: str | Path = DEFAULT_AUSTIN_REQUALIFICATION,
    winner_rank_parity: str | Path = DEFAULT_WINNER_RANK_PARITY,
    roadmap_root: str | Path = DEFAULT_ROADMAP_ROOT,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    artifact = artifact_summary(artifact_path)
    promotion = promotion_summary(promotion_refresh)
    hourly_payload = hourly_summary(hourly)
    ten_payload = ten_minute_summary(ten_minute)
    exact_payload = _simple_gate_summary(exact_distance)
    bottom_payload = _simple_gate_summary(bottom_location)
    fleet_payload = fleet_live_forward_summary(fleet_observability)
    broad_payload = broad_claim_summary(progress_audit, daily_progress)
    served_payload = _simple_gate_summary(served_distribution)
    positive_payload = _simple_gate_summary(positive_daily_first)
    austin_payload = austin_requalification_summary(austin_requalification)
    parity_payload = winner_rank_parity_summary(winner_rank_parity)
    gates = build_gates(
        artifact=artifact,
        promotion=promotion,
        hourly=hourly_payload,
        ten_minute=ten_payload,
        exact_distance=exact_payload,
        bottom_location=bottom_payload,
        fleet=fleet_payload,
        broad_claim=broad_payload,
        served_distribution=served_payload,
        positive_daily_first=positive_payload,
        winner_rank_parity=parity_payload,
    )
    evidence_basis = evidence_class(promotion, artifact)
    dispositions = market_dispositions(promotion, gates, evidence_basis)
    blockers = [gate for gate in gates if gate.get("status") == "BLOCK"]
    disposition_counts = Counter(row.get("disposition") for row in dispositions)
    roadmap_check = roadmap_reference_check(roadmap_root)
    ratchet = ratchet_report(gates)
    status = "PASS" if not blockers and roadmap_check.get("status") == "PASS" else "BLOCK"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "status": status,
        "weather_only_lane": "weather_only_core_model",
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else None,
        "summary": {
            "gate_count": len(gates),
            "blocking_gate_count": len(blockers),
            "market_count": len(dispositions),
            "promote_count": disposition_counts.get("PROMOTE", 0),
            "shadow_count": disposition_counts.get("SHADOW", 0),
            "block_count": disposition_counts.get("BLOCK", 0),
            "evidence_basis": evidence_basis,
            "roadmap_reference_status": roadmap_check.get("status"),
            "winner_rank_parity_status": parity_payload.get("status"),
            "model_top_hit_rate": parity_payload.get("model_top_hit_rate"),
            "market_top_hit_rate": parity_payload.get("market_top_hit_rate"),
            "market_top_model_miss_excess": parity_payload.get("market_top_model_miss_excess"),
            "winner_rank_brier_contribution": parity_payload.get("brier_contribution"),
        },
        "inputs": {
            "artifact_path": str(artifact_path),
            "promotion_refresh": str(promotion_refresh),
            "hourly": str(hourly),
            "ten_minute": str(ten_minute),
            "exact_distance": str(exact_distance),
            "bottom_location": str(bottom_location),
            "fleet_observability": str(fleet_observability),
            "progress_audit": str(progress_audit),
            "daily_progress": str(daily_progress),
            "served_distribution": str(served_distribution),
            "positive_daily_first": str(positive_daily_first),
            "austin_requalification": str(austin_requalification),
            "winner_rank_parity": str(winner_rank_parity),
            "roadmap_root": str(roadmap_root),
        },
        "active_artifact_identity": artifact,
        "promotion_refresh": promotion,
        "hourly": hourly_payload,
        "ten_minute": ten_payload,
        "exact_band_distance_zero": exact_payload,
        "bottom_location": bottom_payload,
        "fleet_observability": fleet_payload,
        "broad_claim": broad_payload,
        "served_distribution": served_payload,
        "positive_daily_first": positive_payload,
        "winner_rank_parity": parity_payload,
        "hard_slices": {
            "austin_hgb_requalification": austin_payload,
        },
        "gates": gates,
        "blockers": blockers,
        "market_dispositions": dispositions,
        "roadmap_reference_check": roadmap_check,
        "gate_stack_ratchet": ratchet,
    }


def render_report(payload: dict[str, Any]) -> str:
    first = payload.get("first_blocker") or {}
    summary = payload.get("summary") or {}
    lines = [
        "# Weather-Only Model Proof Packet",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", payload.get("status")],
            ["Weather-only lane", payload.get("weather_only_lane")],
            ["Evidence basis", summary.get("evidence_basis")],
            ["Blocking gates", summary.get("blocking_gate_count")],
            ["First blocker", first.get("field") or "-"],
            ["First blocker detail", first.get("detail") or "-"],
            ["Promote markets", summary.get("promote_count")],
            ["Shadow markets", summary.get("shadow_count")],
            ["Blocked markets", summary.get("block_count")],
            ["Roadmap reference check", summary.get("roadmap_reference_status")],
            ["Winner-rank parity", summary.get("winner_rank_parity_status")],
            ["Model top-hit rate", fmt_num(summary.get("model_top_hit_rate"))],
            ["Market top-hit rate", fmt_num(summary.get("market_top_hit_rate"))],
            ["Market-top/model-miss excess", summary.get("market_top_model_miss_excess")],
            ["Parity Brier contribution", fmt_num(summary.get("winner_rank_brier_contribution"))],
        ],
    )
    lines += ["", "## Gates", ""]
    lines += markdown_table(
        ["Field", "Status", "Detail"],
        [[row.get("field"), row.get("status"), row.get("detail")] for row in payload.get("gates") or []],
    )
    lines += ["", "## Market Dispositions", ""]
    lines += markdown_table(
        [
            "Market",
            "Disposition",
            "Action",
            "Delta Current",
            "Delta Market",
            "First Blocking Slice",
            "Evidence",
        ],
        [
            [
                row.get("market_id"),
                row.get("disposition"),
                row.get("promotion_refresh_action"),
                fmt_signed(row.get("delta_vs_current")),
                fmt_signed(row.get("delta_vs_market")),
                row.get("first_blocking_slice") or "-",
                row.get("evidence_basis"),
            ]
            for row in payload.get("market_dispositions") or []
        ],
    )
    hard_slices = payload.get("hard_slices") or {}
    if hard_slices:
        lines += ["", "## Hard Slices", ""]
        lines += markdown_table(
            [
                "Field",
                "Status",
                "Market",
                "Serving",
                "Requalification",
                "Delta Market",
                "First Blocker",
            ],
            [
                [
                    f"hard_slices.{name}",
                    row.get("status"),
                    row.get("market_id"),
                    row.get("serving_disposition"),
                    row.get("requalification_verdict"),
                    fmt_signed(row.get("local_delta_vs_market")),
                    row.get("first_requalification_blocker") or "-",
                ]
                for name, row in sorted(hard_slices.items())
            ],
        )
    parity = payload.get("winner_rank_parity") or {}
    if parity:
        lines += ["", "## Winner-Rank Parity", ""]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Status", parity.get("status")],
                ["Model top-hit rate", fmt_num(parity.get("model_top_hit_rate"))],
                ["Market top-hit rate", fmt_num(parity.get("market_top_hit_rate"))],
                ["Market-top/model-miss excess", parity.get("market_top_model_miss_excess")],
                ["Winner probability gap market-model", fmt_num(parity.get("winner_probability_gap_market_minus_model"))],
                ["Top-miss Brier contribution", fmt_num(parity.get("brier_contribution"))],
                ["First blocker", parity.get("first_blocker") or "-"],
            ],
        )
    lines += ["", "## Roadmap Reference Check", ""]
    lines += markdown_table(
        ["Item", "Status", "Expected Packet Field", "Diagnostic Only", "Detail"],
        [
            [
                row.get("item"),
                row.get("status"),
                row.get("expected_packet_field"),
                row.get("diagnostic_only"),
                row.get("detail"),
            ]
            for row in (payload.get("roadmap_reference_check") or {}).get("rows") or []
        ],
    )
    lines += ["", "## Gate Stack Ratchet", ""]
    lines.append((payload.get("gate_stack_ratchet") or {}).get("policy") or "-")
    lines += markdown_table(
        ["Gate", "Classification", "Proof Packet Field", "Detail"],
        [
            [
                row.get("gate"),
                row.get("classification"),
                row.get("proof_packet_field") or "-",
                row.get("detail"),
            ]
            for row in (payload.get("gate_stack_ratchet") or {}).get("rows") or []
        ],
    )
    lines += [
        "",
        "## Lane Separation",
        "",
        "CLOB overlays, market-informed quote-risk diagnostics, and taker profitability packets do not satisfy this weather-only proof packet.",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(
    payload: dict[str, Any],
    json_out: str | Path = DEFAULT_OUT,
    report_out: str | Path = DEFAULT_REPORT,
) -> tuple[Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the canonical weather-only model proof packet.")
    parser.add_argument("--artifact-path", default=str(DEFAULT_ARTIFACT))
    parser.add_argument("--promotion-refresh", default=str(DEFAULT_PROMOTION_REFRESH))
    parser.add_argument("--hourly", default=str(DEFAULT_HOURLY))
    parser.add_argument("--ten-minute", default=str(DEFAULT_TEN_MINUTE))
    parser.add_argument("--exact-distance", default=str(DEFAULT_EXACT_DISTANCE))
    parser.add_argument("--bottom-location", default=str(DEFAULT_BOTTOM_LOCATION))
    parser.add_argument("--fleet-observability", default=str(DEFAULT_FLEET))
    parser.add_argument("--progress-audit", default=str(DEFAULT_PROGRESS_AUDIT))
    parser.add_argument("--daily-progress", default=str(DEFAULT_DAILY_PROGRESS))
    parser.add_argument("--served-distribution", default=str(DEFAULT_SERVED_DISTRIBUTION))
    parser.add_argument("--positive-daily-first", default=str(DEFAULT_POSITIVE_DAILY_FIRST))
    parser.add_argument("--austin-requalification", default=str(DEFAULT_AUSTIN_REQUALIFICATION))
    parser.add_argument("--winner-rank-parity", default=str(DEFAULT_WINNER_RANK_PARITY))
    parser.add_argument("--roadmap-root", default=str(DEFAULT_ROADMAP_ROOT))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_payload(
        artifact_path=args.artifact_path,
        promotion_refresh=args.promotion_refresh,
        hourly=args.hourly,
        ten_minute=args.ten_minute,
        exact_distance=args.exact_distance,
        bottom_location=args.bottom_location,
        fleet_observability=args.fleet_observability,
        progress_audit=args.progress_audit,
        daily_progress=args.daily_progress,
        served_distribution=args.served_distribution,
        positive_daily_first=args.positive_daily_first,
        austin_requalification=args.austin_requalification,
        winner_rank_parity=args.winner_rank_parity,
        roadmap_root=args.roadmap_root,
    )
    json_path, report_path = write_outputs(payload, args.out, args.report)
    print(
        "Weather-only model proof packet: "
        f"{payload['status']} ({payload['blocker_count']} blocker(s))"
    )
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
