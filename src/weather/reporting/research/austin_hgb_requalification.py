"""Austin HGB requalification and fail-closed serving packet."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("austin_hgb_requalification")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "austin_hgb_requalification.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "austin_hgb_requalification_report.md"
DEFAULT_PROMOTION_REFRESH = DEFAULT_BACKTEST_ROOT / "f_family_promotion_refresh.json"
DEFAULT_PROOF_PACKET = DEFAULT_BACKTEST_ROOT / "weather_only_model_proof_packet.json"
DEFAULT_EXACT_DISTANCE = DEFAULT_BACKTEST_ROOT / "exact_band_distance_zero_calibration.json"
DEFAULT_PER_LOCATION_QUARANTINE = DEFAULT_BACKTEST_ROOT / "per_location_artifact_quarantine.json"
MARKET_ID = "austin"

HARD_SLICE = {
    "slice_id": "austin_2026_06_22_high_disagreement",
    "market_id": MARKET_ID,
    "target_date": "2026-06-22",
    "source": "docs/roadmap/items/item-250-austin-hgb-per-location-requalification.md",
    "description": (
        "Austin active-day disagreement case where the HGB path concentrated "
        "96-97F while market and independent fair value favored 94-95F."
    ),
    "required_for_promotion": True,
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    path = Path(path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _market_row(rows: list[dict[str, Any]], market_id: str = MARKET_ID) -> dict[str, Any]:
    for row in rows or []:
        if row.get("market_id") == market_id:
            return row
    return {}


def _promotion_decision(payload: dict[str, Any]) -> dict[str, Any]:
    return _market_row(((payload.get("decisions") or {}).get("markets") or []))


def _allowlist_row(payload: dict[str, Any]) -> dict[str, Any]:
    return _market_row(((payload.get("promotion_allowlist") or {}).get("markets") or []))


def _proof_market_row(payload: dict[str, Any]) -> dict[str, Any]:
    return _market_row(payload.get("market_dispositions") or [])


def _austin_artifacts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in payload.get("artifacts") or []
        if row.get("market_id") == MARKET_ID and row.get("artifact_kind") in {"hgb_model", "coefs_model"}
    ]


def _metric(row: dict[str, Any], name: str) -> float | None:
    metrics = row.get("metrics") or {}
    return _safe_float(row.get(name) if name in row else metrics.get(name))


def _candidate_cutover_allowed(candidate: dict[str, Any]) -> bool:
    verdict = str(candidate.get("verdict") or "").upper()
    cutover = str(candidate.get("cutover_decision") or "").upper()
    return verdict not in {"BLOCK", "FAIL", "FAILED", "ERROR"} and cutover not in {
        "DO_NOT_CUT_OVER",
        "BLOCK",
        "BLOCKED",
    }


def _gate(name: str, status: str, detail: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "gate": name,
        "status": status,
        "detail": detail,
        "evidence": evidence or {},
    }


def _local_market_replay_gate(decision: dict[str, Any]) -> dict[str, Any]:
    delta_market = _metric(decision, "delta_vs_market")
    blocked_validation = decision.get("blocked_validation") or {}
    validation_ok = blocked_validation.get("passed") is True or blocked_validation.get("verdict") == "PASS"
    action = decision.get("action")
    passed = action == "PROMOTE_CANDIDATE" and validation_ok and delta_market is not None and delta_market <= 0
    if passed:
        detail = "Austin active-artifact replay beats market and clears blocked validation"
    elif not decision:
        detail = "missing Austin promotion-refresh decision row"
    elif delta_market is None:
        detail = "Austin replay is missing market-relative Brier evidence"
    elif delta_market > 0:
        detail = f"Austin candidate trails market by {fmt_signed(delta_market)}; requalification requires <= 0"
    elif not validation_ok:
        detail = "Austin blocked-validation evidence is not PASS"
    else:
        detail = f"Austin action is {action or 'missing'}, not PROMOTE_CANDIDATE"
    return _gate(
        "local_market_replay",
        "PASS" if passed else "BLOCK",
        detail,
        {
            "action": action,
            "verdict": decision.get("verdict"),
            "candidate_brier": _metric(decision, "candidate_brier"),
            "current_brier": _metric(decision, "current_brier"),
            "market_brier": _metric(decision, "market_brier"),
            "delta_vs_current": _metric(decision, "delta_vs_current"),
            "delta_vs_market": delta_market,
            "blocked_validation": blocked_validation,
        },
    )


def _exact_gate(exact: dict[str, Any]) -> dict[str, Any]:
    status = str(exact.get("status") or "").upper()
    passed = status == "PASS"
    first = exact.get("first_blocker") or {}
    detail = (
        "exact-band and settlement-distance-0 replay is PASS"
        if passed
        else first.get("detail") or "exact-band and settlement-distance-0 replay is not clear"
    )
    return _gate(
        "exact_band_distance_zero_replay",
        "PASS" if passed else "BLOCK",
        detail,
        {
            "schema_version": exact.get("schema_version"),
            "status": exact.get("status"),
            "first_blocker": first,
        },
    )


def _proof_gate(proof_row: dict[str, Any]) -> dict[str, Any]:
    disposition = proof_row.get("disposition")
    passed = disposition == "PROMOTE"
    detail = (
        "Austin proof-packet disposition is PROMOTE"
        if passed
        else f"Austin proof-packet disposition is {disposition or 'missing'}"
    )
    return _gate("proof_packet_market_disposition", "PASS" if passed else "BLOCK", detail, proof_row)


def _per_location_gate(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    active_promotable = [row for row in artifacts if row.get("active_candidate") and row.get("promotable")]
    stale_active = [row for row in artifacts if row.get("active_candidate") and not row.get("promotable")]
    passed = not active_promotable and not stale_active
    if passed:
        detail = "Austin per-location HGB artifacts are historical-only or non-promotable"
    elif stale_active:
        detail = "Austin has active per-location artifacts that are not promotable"
    else:
        detail = "Austin has promotable per-location artifacts that still need local requalification"
    return _gate(
        "per_location_artifact_state",
        "PASS" if passed else "BLOCK",
        detail,
        {
            "artifact_count": len(artifacts),
            "disposition_counts": dict(Counter(row.get("disposition") for row in artifacts)),
            "artifacts": artifacts,
        },
    )


def _allowlist_summary(promotion: dict[str, Any], allowlist_row: dict[str, Any]) -> dict[str, Any]:
    candidate = promotion.get("candidate") or {}
    cutover_allowed = _candidate_cutover_allowed(candidate)
    stored_allowed = allowlist_row.get("candidate_permission_allowed")
    effective_state = allowlist_row.get("effective_promotion_state")
    if not effective_state:
        if allowlist_row.get("action") == "BLOCK_CANDIDATE":
            effective_state = "BLOCK"
        elif stored_allowed is False or not cutover_allowed:
            effective_state = "SHADOW"
        elif allowlist_row.get("action") == "PROMOTE_CANDIDATE":
            effective_state = "PASS"
        else:
            effective_state = "SHADOW"
    return {
        "candidate_verdict": candidate.get("verdict"),
        "candidate_cutover_decision": candidate.get("cutover_decision"),
        "candidate_cutover_allowed": cutover_allowed,
        "stored_candidate_permission_allowed": stored_allowed,
        "stored_candidate_serving_allowed": allowlist_row.get("candidate_serving_allowed"),
        "effective_promotion_state": effective_state,
        "serving_behavior": allowlist_row.get("serving_behavior") or (
            "candidate" if effective_state == "PASS" else "current_or_shadow"
        ),
        "permission_behavior": allowlist_row.get("permission_behavior") or (
            "candidate_candidate_only" if effective_state == "PASS" else "current_or_harvest_only"
        ),
        "blocker_reason": allowlist_row.get("blocker_reason") or allowlist_row.get("reason") or "",
        "row": allowlist_row,
    }


def _serving_disposition(requalification_passed: bool, proof_row: dict[str, Any], allowlist: dict[str, Any]) -> str:
    if requalification_passed and proof_row.get("disposition") == "PROMOTE" and allowlist.get("effective_promotion_state") == "PASS":
        return "LIVE_CANDIDATE"
    if proof_row.get("disposition") == "BLOCK" or allowlist.get("effective_promotion_state") == "BLOCK":
        return "BLOCK"
    return "SHADOW"


def _serving_gate(
    *,
    requalification_passed: bool,
    serving_disposition: str,
    allowlist: dict[str, Any],
) -> dict[str, Any]:
    passed = requalification_passed or serving_disposition in {"BLOCK", "SHADOW"}
    detail = (
        "Austin HGB is fail-closed outside live candidate serving until local requalification passes"
        if passed
        else "Austin HGB can serve live without a passing local requalification packet"
    )
    return _gate(
        "serving_fail_closed",
        "PASS" if passed else "BLOCK",
        detail,
        {
            "requalification_passed": requalification_passed,
            "serving_disposition": serving_disposition,
            "effective_promotion_state": allowlist.get("effective_promotion_state"),
            "stored_candidate_permission_allowed": allowlist.get("stored_candidate_permission_allowed"),
            "serving_behavior": allowlist.get("serving_behavior"),
            "permission_behavior": allowlist.get("permission_behavior"),
        },
    )


def build_payload(
    *,
    promotion_refresh: str | Path = DEFAULT_PROMOTION_REFRESH,
    proof_packet: str | Path = DEFAULT_PROOF_PACKET,
    exact_distance: str | Path = DEFAULT_EXACT_DISTANCE,
    per_location_quarantine: str | Path = DEFAULT_PER_LOCATION_QUARANTINE,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    promotion = read_json(promotion_refresh)
    proof = read_json(proof_packet)
    exact = read_json(exact_distance)
    per_location = read_json(per_location_quarantine)
    decision = _promotion_decision(promotion)
    proof_row = _proof_market_row(proof)
    allowlist = _allowlist_summary(promotion, _allowlist_row(promotion))
    artifacts = _austin_artifacts(per_location)

    requalification_gates = [
        _local_market_replay_gate(decision),
        _exact_gate(exact),
        _proof_gate(proof_row),
        _per_location_gate(artifacts),
    ]
    requalification_blockers = [gate for gate in requalification_gates if gate["status"] != "PASS"]
    requalification_passed = not requalification_blockers
    serving_disposition = _serving_disposition(requalification_passed, proof_row, allowlist)
    enforcement_gates = [
        _gate("hard_slice_registered", "PASS", "Austin 2026-06-22 disagreement case is registered", HARD_SLICE),
        _serving_gate(
            requalification_passed=requalification_passed,
            serving_disposition=serving_disposition,
            allowlist=allowlist,
        ),
    ]
    enforcement_blockers = [gate for gate in enforcement_gates if gate["status"] != "PASS"]
    status = "PASS" if not enforcement_blockers else "BLOCK"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "status": status,
        "market_id": MARKET_ID,
        "requalification_verdict": "PASS" if requalification_passed else "BLOCK",
        "serving_disposition": serving_disposition,
        "blocker_count": len(enforcement_blockers),
        "requalification_blocker_count": len(requalification_blockers),
        "first_blocker": enforcement_blockers[0] if enforcement_blockers else None,
        "first_requalification_blocker": requalification_blockers[0] if requalification_blockers else None,
        "summary": {
            "hard_slice_id": HARD_SLICE["slice_id"],
            "serving_disposition": serving_disposition,
            "requalification_verdict": "PASS" if requalification_passed else "BLOCK",
            "local_delta_vs_market": _metric(decision, "delta_vs_market"),
            "proof_packet_disposition": proof_row.get("disposition"),
            "promotion_refresh_action": decision.get("action"),
            "exact_distance_status": exact.get("status"),
            "effective_promotion_state": allowlist.get("effective_promotion_state"),
        },
        "policy": {
            "live_candidate_requires": [
                "Austin local market replay delta_vs_market <= 0",
                "Austin blocked-validation evidence PASS",
                "exact-band and settlement-distance-0 replay PASS",
                "weather-only proof-packet Austin disposition PROMOTE",
                "candidate allowlist effective_promotion_state PASS",
            ],
            "otherwise": "Austin HGB remains BLOCK or SHADOW and cannot trade live on broad F-family permission alone.",
        },
        "inputs": {
            "promotion_refresh": str(promotion_refresh),
            "proof_packet": str(proof_packet),
            "exact_distance": str(exact_distance),
            "per_location_quarantine": str(per_location_quarantine),
        },
        "hard_slices": [HARD_SLICE],
        "promotion_decision": decision,
        "proof_packet_market_disposition": proof_row,
        "promotion_allowlist": allowlist,
        "per_location_artifacts": artifacts,
        "requalification_gates": requalification_gates,
        "enforcement_gates": enforcement_gates,
        "requalification_blockers": requalification_blockers,
        "enforcement_blockers": enforcement_blockers,
    }


def render_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    first_requal = payload.get("first_requalification_blocker") or {}
    lines = [
        "# Austin HGB Requalification",
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
            ["Market", payload.get("market_id")],
            ["Serving disposition", payload.get("serving_disposition")],
            ["Requalification verdict", payload.get("requalification_verdict")],
            ["First requalification blocker", first_requal.get("detail") or "-"],
            ["Promotion action", summary.get("promotion_refresh_action")],
            ["Proof-packet disposition", summary.get("proof_packet_disposition")],
            ["Effective promotion state", summary.get("effective_promotion_state")],
            ["Local delta vs market", fmt_signed(summary.get("local_delta_vs_market"))],
            ["Exact-distance status", summary.get("exact_distance_status")],
        ],
    )
    lines += ["", "## Enforcement Gates", ""]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [[row.get("gate"), row.get("status"), row.get("detail")] for row in payload.get("enforcement_gates") or []],
    )
    lines += ["", "## Requalification Gates", ""]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [[row.get("gate"), row.get("status"), row.get("detail")] for row in payload.get("requalification_gates") or []],
    )
    hard_slices = payload.get("hard_slices") or []
    lines += ["", "## Hard Slices", ""]
    lines += markdown_table(
        ["Slice", "Market", "Target Date", "Required", "Description"],
        [
            [
                row.get("slice_id"),
                row.get("market_id"),
                row.get("target_date"),
                row.get("required_for_promotion"),
                row.get("description"),
            ]
            for row in hard_slices
        ],
    )
    decision = payload.get("promotion_decision") or {}
    metrics = decision.get("metrics") or {}
    lines += ["", "## Austin Replay Metrics", ""]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Action", decision.get("action")],
            ["Verdict", decision.get("verdict")],
            ["Candidate Brier", fmt_num(metrics.get("candidate_brier"))],
            ["Current Brier", fmt_num(metrics.get("current_brier"))],
            ["Market Brier", fmt_num(metrics.get("market_brier"))],
            ["Delta vs current", fmt_signed(metrics.get("delta_vs_current"))],
            ["Delta vs market", fmt_signed(metrics.get("delta_vs_market"))],
            ["Reason", decision.get("reason") or "-"],
        ],
    )
    allowlist = payload.get("promotion_allowlist") or {}
    lines += ["", "## Serving Contract", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Candidate verdict", allowlist.get("candidate_verdict")],
            ["Candidate cutover", allowlist.get("candidate_cutover_decision")],
            ["Candidate cutover allowed", allowlist.get("candidate_cutover_allowed")],
            ["Stored candidate permission", allowlist.get("stored_candidate_permission_allowed")],
            ["Stored candidate serving", allowlist.get("stored_candidate_serving_allowed")],
            ["Effective promotion state", allowlist.get("effective_promotion_state")],
            ["Serving behavior", allowlist.get("serving_behavior")],
            ["Permission behavior", allowlist.get("permission_behavior")],
            ["Blocker reason", allowlist.get("blocker_reason") or "-"],
        ],
    )
    policy = payload.get("policy") or {}
    lines += ["", "## Promotion Policy", ""]
    lines.append("Live Austin HGB candidate serving requires all of:")
    for item in policy.get("live_candidate_requires") or []:
        lines.append(f"- {item}")
    lines += ["", policy.get("otherwise") or ""]
    return "\n".join(lines).rstrip() + "\n"


def write_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description="Build the Austin HGB requalification packet.")
    parser.add_argument("--promotion-refresh", default=str(DEFAULT_PROMOTION_REFRESH))
    parser.add_argument("--proof-packet", default=str(DEFAULT_PROOF_PACKET))
    parser.add_argument("--exact-distance", default=str(DEFAULT_EXACT_DISTANCE))
    parser.add_argument("--per-location-quarantine", default=str(DEFAULT_PER_LOCATION_QUARANTINE))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)

    payload = build_payload(
        promotion_refresh=args.promotion_refresh,
        proof_packet=args.proof_packet,
        exact_distance=args.exact_distance,
        per_location_quarantine=args.per_location_quarantine,
    )
    out_path = write_json(args.out, payload)
    report_path = write_report(args.report, payload)
    print(
        "Austin HGB requalification: "
        f"{payload['status']} serving={payload['serving_disposition']} "
        f"requalification={payload['requalification_verdict']}"
    )
    print(f"JSON written to {out_path}")
    print(f"Report written to {report_path}")
    return payload


if __name__ == "__main__":
    main()
