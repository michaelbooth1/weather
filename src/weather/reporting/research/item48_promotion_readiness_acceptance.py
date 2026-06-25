"""Item 48 F-family promotion-readiness acceptance finalizer."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_signed, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("item48_promotion_readiness_acceptance")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_PROMOTION_REFRESH = DEFAULT_BACKTEST_ROOT / "item224_active_timesplit_logistic_repair_promotion_refresh.json"
DEFAULT_PROOF_PACKET = DEFAULT_BACKTEST_ROOT / "weather_only_model_proof_packet.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item48_promotion_readiness_acceptance.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item48_promotion_readiness_acceptance_report.md"
DEFAULT_MARKET_TOLERANCE = 0.003


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    source = Path(path)
    if not source.exists():
        return {}
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _passes(value: Any) -> bool:
    return str(value or "").upper() in {"PASS", "READY", "OK", "ALLOW", "ALLOWED", "PROVEN"}


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _candidate_summary(promotion: dict[str, Any]) -> dict[str, Any]:
    candidate = promotion.get("candidate") or {}
    shadow = candidate.get("candidate_shadow_variants") or {}
    registry = shadow.get("active_registry_contract") or shadow.get("registry_contract") or {}
    aggregate = candidate.get("aggregate") or {}
    blocked_validation = candidate.get("blocked_validation") or {}
    claims = (promotion.get("model_skill_claims") or {}).get("weather_only_core_model") or {}
    source_gate = promotion.get("source_missingness_location_gate") or {}
    readiness = promotion.get("readiness") or {}
    hourly = readiness.get("hourly_performance_mitigation") or {}
    ten_minute = readiness.get("ten_minute_performance_mitigation") or {}
    return {
        "variant_id": shadow.get("variant_id") or (promotion.get("promotion_allowlist") or {}).get("candidate_id"),
        "verdict": candidate.get("verdict"),
        "cutover_decision": candidate.get("cutover_decision"),
        "rows": aggregate.get("rows") or aggregate.get("n"),
        "delta_vs_current": aggregate.get("delta_vs_current"),
        "delta_vs_market": aggregate.get("delta_vs_market"),
        "blocked_validation_passed": blocked_validation.get("passed") is True or _passes(blocked_validation.get("verdict")),
        "weather_only_core_claim_allowed": claims.get("broad_market_skill_claim_allowed") is True,
        "weather_only_core_claim_reason": claims.get("reason") or "",
        "uses_market_features": shadow.get("uses_market_features"),
        "active_registry_contract_present": bool(registry),
        "active_registry_variant_id": registry.get("variant_id"),
        "source_missingness_status": source_gate.get("status"),
        "source_missingness_blocker_count": source_gate.get("blocker_count", len(source_gate.get("blockers") or [])),
        "candidate_hourly_mitigation_applied": hourly.get("applied") is True and _passes(hourly.get("candidate_hourly_status")),
        "candidate_hourly_status": hourly.get("candidate_hourly_status"),
        "candidate_hourly_variant_id": hourly.get("candidate_variant_id"),
        "candidate_ten_minute_mitigation_applied": (
            ten_minute.get("applied") is True and _passes(ten_minute.get("candidate_ten_minute_status"))
        ),
        "candidate_ten_minute_status": ten_minute.get("candidate_ten_minute_status"),
        "candidate_ten_minute_variant_id": ten_minute.get("candidate_variant_id"),
    }


def _market_metrics(row: dict[str, Any]) -> dict[str, float | None]:
    metrics = row.get("metrics") or {}
    return {
        "candidate_brier": _safe_float(row.get("candidate_brier", metrics.get("candidate_brier"))),
        "current_brier": _safe_float(row.get("current_brier", metrics.get("current_brier"))),
        "market_brier": _safe_float(row.get("market_brier", metrics.get("market_brier"))),
        "delta_vs_current": _safe_float(row.get("delta_vs_current", metrics.get("delta_vs_current"))),
        "delta_vs_market": _safe_float(row.get("delta_vs_market", metrics.get("delta_vs_market"))),
    }


def _market_rows(promotion: dict[str, Any], *, market_tolerance: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    allowlist = promotion.get("promotion_allowlist") or {}
    rows = allowlist.get("markets") or (promotion.get("decisions") or {}).get("markets") or []
    market_rows: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for row in rows:
        metrics = _market_metrics(row)
        blocked_validation = row.get("blocked_validation") or {}
        market_id = row.get("market_id") or row.get("market")
        action = row.get("action")
        item = {
            "market_id": market_id,
            "action": action,
            "serving_behavior": row.get("serving_behavior"),
            "permission_behavior": row.get("permission_behavior"),
            "candidate_permission_allowed": row.get("candidate_permission_allowed"),
            "candidate_serving_allowed": row.get("candidate_serving_allowed"),
            "blocked_validation_passed": blocked_validation.get("passed") is True or _passes(blocked_validation.get("verdict")),
            "reason": row.get("reason") or row.get("blocker_reason") or "",
            **metrics,
        }
        market_rows.append(item)

        if action != "PROMOTE_CANDIDATE":
            blockers.append({
                "category": "market_action",
                "market_id": market_id,
                "detail": f"{market_id} action is {action or 'missing'}, expected PROMOTE_CANDIDATE",
            })
        if item["candidate_permission_allowed"] is False or item["candidate_serving_allowed"] is False:
            blockers.append({
                "category": "serving_permission",
                "market_id": market_id,
                "detail": f"{market_id} candidate serving/permission is not allowed",
            })
        if item["blocked_validation_passed"] is not True:
            blockers.append({
                "category": "market_blocked_validation",
                "market_id": market_id,
                "detail": f"{market_id} blocked validation did not pass",
            })
        if item["delta_vs_current"] is None or item["delta_vs_current"] > 0.0:
            blockers.append({
                "category": "market_current_regression",
                "market_id": market_id,
                "detail": f"{market_id} candidate is not better than current: {fmt_signed(item['delta_vs_current'])}",
            })
        if item["delta_vs_market"] is None or item["delta_vs_market"] > market_tolerance:
            blockers.append({
                "category": "market_market_tolerance",
                "market_id": market_id,
                "detail": (
                    f"{market_id} candidate trails market by {fmt_signed(item['delta_vs_market'])} "
                    f"> +{market_tolerance:.4f}"
                ),
            })
    if not market_rows:
        blockers.append({
            "category": "market_actions_missing",
            "detail": "promotion refresh has no market action rows",
        })
    return market_rows, blockers


def _candidate_blockers(summary: dict[str, Any]) -> list[dict[str, Any]]:
    checks = [
        ("candidate_verdict", _passes(summary.get("verdict")), "candidate verdict is not PASS"),
        ("blocked_validation", summary.get("blocked_validation_passed") is True, "candidate blocked validation did not pass"),
        (
            "weather_only_core_claim",
            summary.get("weather_only_core_claim_allowed") is True,
            "weather-only core model skill claim is not allowed",
        ),
        ("active_registry_contract", summary.get("active_registry_contract_present") is True, "active registry contract is missing"),
        ("weather_only_lane", summary.get("uses_market_features") is False, "candidate uses market features"),
        ("source_missingness_location_gate", _passes(summary.get("source_missingness_status")), "source/missingness gate is not PASS"),
        (
            "candidate_hourly_mitigation",
            summary.get("candidate_hourly_mitigation_applied") is True,
            "candidate hourly mitigation is not applied/pass",
        ),
        (
            "candidate_ten_minute_mitigation",
            summary.get("candidate_ten_minute_mitigation_applied") is True,
            "candidate 10-minute mitigation is not applied/pass",
        ),
    ]
    return [
        {"category": category, "detail": detail}
        for category, passed, detail in checks
        if not passed
    ]


def _external_blockers(promotion: dict[str, Any], proof_packet: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for blocker in (promotion.get("readiness") or {}).get("blockers") or []:
        if isinstance(blocker, dict):
            output.append({
                "source": "promotion_refresh.readiness",
                "category": blocker.get("category"),
                "severity": blocker.get("severity"),
                "detail": blocker.get("detail"),
            })
    for gate in proof_packet.get("gates") or []:
        if isinstance(gate, dict) and not _passes(gate.get("status")):
            output.append({
                "source": "weather_only_model_proof_packet.gates",
                "category": gate.get("gate"),
                "severity": "block",
                "detail": gate.get("detail"),
            })
    seen = set()
    unique = []
    for item in output:
        key = (item.get("source"), item.get("category"), item.get("detail"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _proof_packet_action_summary(proof_packet: dict[str, Any]) -> dict[str, Any]:
    rows = proof_packet.get("market_dispositions") or []
    actions = {}
    dispositions = {}
    for row in rows:
        actions[row.get("promotion_refresh_action")] = actions.get(row.get("promotion_refresh_action"), 0) + 1
        dispositions[row.get("disposition")] = dispositions.get(row.get("disposition"), 0) + 1
    return {
        "rows": len(rows),
        "promotion_refresh_action_counts": actions,
        "proof_packet_disposition_counts": dispositions,
    }


def build_payload(
    promotion_refresh: str | Path = DEFAULT_PROMOTION_REFRESH,
    proof_packet: str | Path = DEFAULT_PROOF_PACKET,
    *,
    market_tolerance: float = DEFAULT_MARKET_TOLERANCE,
) -> dict[str, Any]:
    promotion = read_json(promotion_refresh)
    packet = read_json(proof_packet)
    candidate = _candidate_summary(promotion)
    markets, market_blockers = _market_rows(promotion, market_tolerance=float(market_tolerance))
    blockers = [
        *_candidate_blockers(candidate),
        *market_blockers,
    ]
    external = _external_blockers(promotion, packet)
    promote_count = sum(1 for row in markets if row.get("action") == "PROMOTE_CANDIDATE")
    status = "PASS" if not blockers else "BLOCK"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": status,
        "item48_acceptance_passed": status == "PASS",
        "serving_parity_status": "PASS" if not market_blockers else "BLOCK",
        "production_cutover_status": "READY" if status == "PASS" and not external else "BLOCK",
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else None,
        "blockers": blockers,
        "external_production_blocker_count": len(external),
        "external_production_blockers": external,
        "inputs": {
            "promotion_refresh": str(promotion_refresh),
            "proof_packet": str(proof_packet),
            "market_tolerance": float(market_tolerance),
        },
        "candidate": candidate,
        "summary": {
            "family_unit": promotion.get("family_unit"),
            "market_count": len(markets),
            "promote_count": promote_count,
            "shadow_or_block_count": len(markets) - promote_count,
            "all_markets_promoted": bool(markets) and promote_count == len(markets),
            "external_production_blockers_preserved": bool(external),
            "proof_packet_actions": _proof_packet_action_summary(packet),
        },
        "market_rows": sorted(markets, key=lambda row: str(row.get("market_id") or "")),
    }


def render_report(payload: dict[str, Any]) -> str:
    candidate = payload.get("candidate") or {}
    summary = payload.get("summary") or {}
    lines = [
        "# Item 48 Promotion Readiness Acceptance",
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
            ["Item 48 acceptance passed", payload.get("item48_acceptance_passed")],
            ["Serving parity status", payload.get("serving_parity_status")],
            ["Production cutover status", payload.get("production_cutover_status")],
            ["Blockers", payload.get("blocker_count")],
            ["External production blockers preserved", payload.get("external_production_blocker_count")],
            ["Variant", candidate.get("variant_id")],
            ["Candidate verdict", candidate.get("verdict")],
            ["Aggregate delta vs current", fmt_signed(candidate.get("delta_vs_current"))],
            ["Aggregate delta vs market", fmt_signed(candidate.get("delta_vs_market"))],
            ["Markets promoted", f"{summary.get('promote_count')}/{summary.get('market_count')}"],
            ["Proof-packet action counts", json.dumps((summary.get("proof_packet_actions") or {}).get("promotion_refresh_action_counts") or {}, sort_keys=True)],
            ["Proof-packet disposition counts", json.dumps((summary.get("proof_packet_actions") or {}).get("proof_packet_disposition_counts") or {}, sort_keys=True)],
        ],
    )
    lines += ["", "## Candidate Gates", ""]
    lines += markdown_table(
        ["Gate", "Value"],
        [
            ["Blocked validation", candidate.get("blocked_validation_passed")],
            ["Weather-only core claim", candidate.get("weather_only_core_claim_allowed")],
            ["Uses market features", candidate.get("uses_market_features")],
            ["Active registry contract", candidate.get("active_registry_contract_present")],
            ["Source/missingness", candidate.get("source_missingness_status")],
            ["Candidate hourly mitigation", candidate.get("candidate_hourly_mitigation_applied")],
            ["Candidate 10-minute mitigation", candidate.get("candidate_ten_minute_mitigation_applied")],
        ],
    )
    lines += ["", "## Market Actions", ""]
    lines += markdown_table(
        [
            "Market",
            "Action",
            "Serving",
            "Permission",
            "Delta Current",
            "Delta Market",
            "Blocked Validation",
        ],
        [
            [
                row.get("market_id"),
                row.get("action"),
                row.get("serving_behavior"),
                row.get("permission_behavior"),
                fmt_signed(row.get("delta_vs_current")),
                fmt_signed(row.get("delta_vs_market")),
                row.get("blocked_validation_passed"),
            ]
            for row in payload.get("market_rows") or []
        ],
    )
    if payload.get("blockers"):
        lines += ["", "## Item 48 Blockers", ""]
        lines += markdown_table(
            ["Category", "Market", "Detail"],
            [
                [row.get("category"), row.get("market_id") or "-", row.get("detail")]
                for row in payload.get("blockers") or []
            ],
        )
    if payload.get("external_production_blockers"):
        lines += ["", "## External Production Blockers", ""]
        lines += markdown_table(
            ["Source", "Category", "Detail"],
            [
                [row.get("source"), row.get("category"), row.get("detail")]
                for row in payload.get("external_production_blockers") or []
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
    parser = argparse.ArgumentParser(description="Finalize Item 48 F-family promotion-readiness acceptance.")
    parser.add_argument("--promotion-refresh", default=str(DEFAULT_PROMOTION_REFRESH))
    parser.add_argument("--proof-packet", default=str(DEFAULT_PROOF_PACKET))
    parser.add_argument("--market-tolerance", type=float, default=DEFAULT_MARKET_TOLERANCE)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_payload(
        args.promotion_refresh,
        args.proof_packet,
        market_tolerance=args.market_tolerance,
    )
    json_path, report_path = write_outputs(payload, args.out, args.report)
    print(f"Item 48 promotion-readiness acceptance: {payload['status']} ({payload['blocker_count']} blocker(s))")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
