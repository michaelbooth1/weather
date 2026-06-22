"""Validate-what-you-serve contract for early-hour calibration evidence."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("served_distribution_calibration_contract")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_SERVING_ORDINAL_GATE = DEFAULT_BACKTEST_ROOT / "serving_ordinal_smoothing_gate.json"
DEFAULT_RETRAIN_LOCATION_GATE = DEFAULT_BACKTEST_ROOT / "pooled_f_retrain_location_gate.json"
DEFAULT_REPLAY_SUMMARY = (
    DEFAULT_BACKTEST_ROOT / "pooled_f_candidate_miami_current_fallback_predawn_repair_replay_summary.json"
)
DEFAULT_CANDIDATE_HOURLY = (
    DEFAULT_BACKTEST_ROOT / "pooled_f_candidate_miami_current_fallback_predawn_repair_hourly_candidate_performance.json"
)
DEFAULT_CANDIDATE_TEN_MINUTE = (
    DEFAULT_BACKTEST_ROOT / "pooled_f_candidate_miami_current_fallback_predawn_repair_ten_minute_performance.json"
)
DEFAULT_EXACT_DISTANCE = DEFAULT_BACKTEST_ROOT / "exact_band_distance_zero_calibration.json"
DEFAULT_BOTTOM_LOCATION = DEFAULT_BACKTEST_ROOT / "bottom_location_winner_centering.json"
DEFAULT_PROMOTION_REFRESH = DEFAULT_BACKTEST_ROOT / "f_family_promotion_refresh_predawn_repair.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "served_distribution_calibration_contract.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "served_distribution_calibration_contract_report.md"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: str | Path | None) -> dict[str, Any] | None:
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


def _passes(value: Any) -> bool:
    return str(value or "").upper() in {"PASS", "READY", "ALLOW", "ALLOWED"}


def _first_blocker(payload: dict[str, Any] | None) -> str:
    payload = payload or {}
    first = payload.get("first_blocker") or {}
    if isinstance(first, dict) and first.get("detail"):
        return str(first.get("detail"))
    blockers = payload.get("blockers") or []
    if blockers and isinstance(blockers[0], dict):
        return str(blockers[0].get("detail") or blockers[0].get("gate") or blockers[0].get("category") or "")
    return ""


def _gate(name: str, status: str, detail: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "gate": name,
        "status": status,
        "detail": detail,
        "evidence": evidence or {},
    }


def contract_spec() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "lane": "weather_only_core_model",
        "validation_target": "final_served_distribution",
        "required_validation_mode": "active_replay_contract",
        "allowed_no_market_transforms": [
            "active pooled feature artifact scoring",
            "artifact-declared calibration/postprocess transforms",
            "artifact-declared ordinal smoothing only when tuned/exported by validation",
            "current-high trust fields only when present in the trained artifact schema",
        ],
        "diagnostic_only_until_absorbed": [
            "row-export predawn weak-slot repair",
            "isolated exact-band/distance-0 calibration probes",
            "market-specific residual repair manifests",
        ],
        "excluded_from_core_lane": [
            "CLOB-informed overlays",
            "market price features",
            "quote-risk permission overlays",
        ],
        "required_slices": [
            "daily_first",
            "early_hour",
            "ten_minute_weak_slot",
            "exact_band_early",
            "settlement_distance_0_early",
            "ramp",
            "late_day",
            "lock_in",
            "bottom_locations",
            "per_market",
        ],
    }


def replay_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    blocked = (payload or {}).get("blocked_validation") or {}
    aggregate = (payload or {}).get("aggregate") or {}
    shadow = (payload or {}).get("candidate_shadow_variants") or {}
    validation_evidence = (payload or {}).get("validation_evidence") or blocked.get("validation_evidence")
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": (payload or {}).get("schema_version"),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "verdict": (payload or {}).get("verdict"),
        "cutover_decision": (payload or {}).get("cutover_decision"),
        "validation_evidence": validation_evidence,
        "blocked_validation_verdict": blocked.get("verdict"),
        "blocked_validation_passed": blocked.get("passed"),
        "blocked_validation_reasons": blocked.get("reasons") or [],
        "uses_market_features": shadow.get("uses_market_features"),
        "registry_contract": shadow.get("registry_contract"),
        "variant_id": shadow.get("variant_id"),
        "delta_vs_current": aggregate.get("delta_vs_current"),
        "delta_vs_market": aggregate.get("delta_vs_market"),
        "logloss_delta_vs_market": aggregate.get("logloss_delta_vs_market"),
    }


def serving_ordinal_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": (payload or {}).get("schema_version"),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": (payload or {}).get("status"),
        "ordinal_smoothing_train_serve_skew_fixed": (payload or {}).get(
            "ordinal_smoothing_train_serve_skew_fixed"
        ),
        "acceptance_passed": (payload or {}).get("acceptance_passed"),
        "blocker_count": (payload or {}).get("blocker_count", len((payload or {}).get("blockers") or [])),
        "first_blocker": _first_blocker(payload),
    }


def retrain_location_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": (payload or {}).get("schema_version"),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": (payload or {}).get("status"),
        "broad_core_model_claim_allowed": (payload or {}).get("broad_core_model_claim_allowed"),
        "blocker_count": (payload or {}).get("blocker_count", len((payload or {}).get("blockers") or [])),
        "first_blocker": _first_blocker(payload),
    }


def candidate_hourly_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    gate = (payload or {}).get("candidate_hourly_gate") or {}
    early = gate.get("early_morning") or {}
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": gate.get("status"),
        "blocker_count": gate.get("blocker_count", len(gate.get("blockers") or [])),
        "first_blocker": _first_blocker(gate),
        "delta_vs_current": early.get("delta_vs_current"),
        "delta_vs_market": early.get("delta_vs_market"),
        "logloss_delta_vs_market": early.get("logloss_delta_vs_market"),
    }


def candidate_ten_minute_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    gate = (payload or {}).get("candidate_ten_minute_gate") or {}
    overlap = gate.get("weak_slot_overlap") or {}
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": gate.get("status"),
        "blocker_count": gate.get("blocker_count", len(gate.get("blockers") or [])),
        "first_blocker": _first_blocker(gate),
        "delta_vs_current": overlap.get("delta_vs_current"),
        "delta_vs_market": overlap.get("delta_vs_market"),
        "logloss_delta_vs_market": overlap.get("logloss_delta_vs_market"),
    }


def simple_gate_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": (payload or {}).get("schema_version"),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": (payload or {}).get("status"),
        "blocker_count": (payload or {}).get("blocker_count", len((payload or {}).get("blockers") or [])),
        "first_blocker": _first_blocker(payload),
        "summary": (payload or {}).get("summary") or {},
    }


def promotion_lane_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    claims = (payload or {}).get("model_skill_claims") or {}
    quote_risk = claims.get("market_informed_quote_risk") or {}
    core = claims.get("weather_only_core_model") or {}
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "core_broad_claim_allowed": core.get("broad_market_skill_claim_allowed"),
        "market_informed_counts_toward_core": quote_risk.get("counts_toward_core_skill_claim"),
        "market_informed_reason": quote_risk.get("reason"),
    }


def build_gates(
    *,
    contract: dict[str, Any],
    serving_ordinal: dict[str, Any],
    retrain_location: dict[str, Any],
    replay: dict[str, Any],
    hourly: dict[str, Any],
    ten_minute: dict[str, Any],
    exact_distance: dict[str, Any],
    bottom_location: dict[str, Any],
    lane: dict[str, Any],
) -> list[dict[str, Any]]:
    gates = [
        _gate(
            "contract_schema",
            "PASS",
            "served-distribution calibration contract is specified",
            contract,
        )
    ]
    gates.append(_gate(
        "serving_parity_prerequisite",
        "PASS" if serving_ordinal.get("ordinal_smoothing_train_serve_skew_fixed") is True else "BLOCK",
        (
            "serving ordinal-smoothing train/serve skew is fixed"
            if serving_ordinal.get("ordinal_smoothing_train_serve_skew_fixed") is True
            else "serving ordinal-smoothing parity prerequisite is not clear"
        ),
        serving_ordinal,
    ))
    active_replay = (
        replay.get("validation_evidence") == contract.get("required_validation_mode")
        and replay.get("verdict") == "PASS"
        and replay.get("cutover_decision") != "DO_NOT_CUT_OVER"
    )
    gates.append(_gate(
        "active_replay_contract",
        "PASS" if active_replay else "BLOCK",
        (
            "calibration head evidence is active replay-contract evidence"
            if active_replay
            else (
                f"validation_evidence={replay.get('validation_evidence') or 'missing'}, "
                f"verdict={replay.get('verdict') or 'missing'}, "
                f"cutover={replay.get('cutover_decision') or 'missing'}"
            )
        ),
        replay,
    ))
    gates.append(_gate(
        "early_hour_hourly_gate",
        "PASS" if _passes(hourly.get("status")) else "BLOCK",
        (
            "served early-hour hourly gate passed"
            if _passes(hourly.get("status"))
            else hourly.get("first_blocker") or "served early-hour hourly gate is not clear"
        ),
        hourly,
    ))
    gates.append(_gate(
        "weak_slot_ten_minute_gate",
        "PASS" if _passes(ten_minute.get("status")) else "BLOCK",
        (
            "served weak-slot 10-minute gate passed"
            if _passes(ten_minute.get("status"))
            else ten_minute.get("first_blocker") or "served weak-slot 10-minute gate is not clear"
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
    lane_separated = (
        replay.get("uses_market_features") is False
        and lane.get("market_informed_counts_toward_core") is not True
    )
    gates.append(_gate(
        "lane_separation",
        "PASS" if lane_separated else "BLOCK",
        (
            "market-informed overlays remain outside the weather-only core lane"
            if lane_separated
            else "market-informed evidence is not cleanly separated from weather-only core lane"
        ),
        {"replay": replay, "promotion_lane": lane},
    ))
    gates.append(_gate(
        "broad_claim_gate",
        "PASS" if _passes(retrain_location.get("status")) and retrain_location.get("broad_core_model_claim_allowed") else "BLOCK",
        (
            "pooled F retrain/location broad-claim gate passed"
            if _passes(retrain_location.get("status")) and retrain_location.get("broad_core_model_claim_allowed")
            else retrain_location.get("first_blocker") or "pooled F retrain/location broad-claim gate is not clear"
        ),
        retrain_location,
    ))
    return gates


def build_payload(
    *,
    serving_ordinal_gate: str | Path = DEFAULT_SERVING_ORDINAL_GATE,
    retrain_location_gate: str | Path = DEFAULT_RETRAIN_LOCATION_GATE,
    replay: str | Path = DEFAULT_REPLAY_SUMMARY,
    candidate_hourly: str | Path = DEFAULT_CANDIDATE_HOURLY,
    candidate_ten_minute: str | Path = DEFAULT_CANDIDATE_TEN_MINUTE,
    exact_distance: str | Path = DEFAULT_EXACT_DISTANCE,
    bottom_location: str | Path = DEFAULT_BOTTOM_LOCATION,
    promotion_refresh: str | Path = DEFAULT_PROMOTION_REFRESH,
) -> dict[str, Any]:
    contract = contract_spec()
    serving = serving_ordinal_summary(serving_ordinal_gate)
    retrain = retrain_location_summary(retrain_location_gate)
    replay_payload = replay_summary(replay)
    hourly = candidate_hourly_summary(candidate_hourly)
    ten = candidate_ten_minute_summary(candidate_ten_minute)
    exact = simple_gate_summary(exact_distance)
    bottom = simple_gate_summary(bottom_location)
    lane = promotion_lane_summary(promotion_refresh)
    gates = build_gates(
        contract=contract,
        serving_ordinal=serving,
        retrain_location=retrain,
        replay=replay_payload,
        hourly=hourly,
        ten_minute=ten,
        exact_distance=exact,
        bottom_location=bottom,
        lane=lane,
    )
    blockers = [gate for gate in gates if gate.get("status") == "BLOCK"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": "PASS" if not blockers else "BLOCK",
        "served_distribution_contract_specified": True,
        "acceptance_passed": not blockers,
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else None,
        "inputs": {
            "serving_ordinal_gate": str(serving_ordinal_gate),
            "retrain_location_gate": str(retrain_location_gate),
            "replay": str(replay),
            "candidate_hourly": str(candidate_hourly),
            "candidate_ten_minute": str(candidate_ten_minute),
            "exact_distance": str(exact_distance),
            "bottom_location": str(bottom_location),
            "promotion_refresh": str(promotion_refresh),
        },
        "contract": contract,
        "serving_ordinal_gate": serving,
        "retrain_location_gate": retrain,
        "replay": replay_payload,
        "candidate_hourly": hourly,
        "candidate_ten_minute": ten,
        "exact_band_distance_zero": exact,
        "bottom_location": bottom,
        "promotion_lane": lane,
        "gates": gates,
        "blockers": blockers,
    }


def render_report(payload: dict[str, Any]) -> str:
    first = payload.get("first_blocker") or {}
    replay = payload.get("replay") or {}
    hourly = payload.get("candidate_hourly") or {}
    ten = payload.get("candidate_ten_minute") or {}
    lines = [
        "# Served-Distribution Calibration Contract",
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
            ["Contract specified", payload.get("served_distribution_contract_specified")],
            ["Acceptance passed", payload.get("acceptance_passed")],
            ["Blockers", payload.get("blocker_count")],
            ["First blocker", first.get("detail") or "-"],
            ["Replay validation evidence", replay.get("validation_evidence")],
            ["Replay verdict", replay.get("verdict")],
            ["Replay delta vs market", fmt_num(replay.get("delta_vs_market"))],
            ["Hourly status", hourly.get("status")],
            ["Hourly delta vs market", fmt_num(hourly.get("delta_vs_market"))],
            ["10-minute status", ten.get("status")],
            ["10-minute delta vs market", fmt_num(ten.get("delta_vs_market"))],
        ],
    )
    lines += ["", "## Gates", ""]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [[row.get("gate"), row.get("status"), row.get("detail")] for row in payload.get("gates") or []],
    )
    contract = payload.get("contract") or {}
    lines += ["", "## Contract", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Lane", contract.get("lane")],
            ["Validation target", contract.get("validation_target")],
            ["Required validation mode", contract.get("required_validation_mode")],
            ["Required slices", ", ".join(contract.get("required_slices") or [])],
        ],
    )
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
    parser = argparse.ArgumentParser(description="Build served-distribution early-hour calibration contract gate.")
    parser.add_argument("--serving-ordinal-gate", default=str(DEFAULT_SERVING_ORDINAL_GATE))
    parser.add_argument("--retrain-location-gate", default=str(DEFAULT_RETRAIN_LOCATION_GATE))
    parser.add_argument("--replay", default=str(DEFAULT_REPLAY_SUMMARY))
    parser.add_argument("--candidate-hourly", default=str(DEFAULT_CANDIDATE_HOURLY))
    parser.add_argument("--candidate-ten-minute", default=str(DEFAULT_CANDIDATE_TEN_MINUTE))
    parser.add_argument("--exact-distance", default=str(DEFAULT_EXACT_DISTANCE))
    parser.add_argument("--bottom-location", default=str(DEFAULT_BOTTOM_LOCATION))
    parser.add_argument("--promotion-refresh", default=str(DEFAULT_PROMOTION_REFRESH))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_payload(
        serving_ordinal_gate=args.serving_ordinal_gate,
        retrain_location_gate=args.retrain_location_gate,
        replay=args.replay,
        candidate_hourly=args.candidate_hourly,
        candidate_ten_minute=args.candidate_ten_minute,
        exact_distance=args.exact_distance,
        bottom_location=args.bottom_location,
        promotion_refresh=args.promotion_refresh,
    )
    json_path, report_path = write_outputs(payload, args.out, args.report)
    print(f"Served-distribution calibration contract: {payload['status']} ({payload['blocker_count']} blocker(s))")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
