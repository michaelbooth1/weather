"""Viability audit for Item 160 early-hour remediation candidates."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("item160_candidate_viability_audit")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item160_candidate_viability_audit.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item160_candidate_viability_audit_report.md"


DEFAULT_CANDIDATES = [
    {
        "candidate_id": "configured_predawn_repair",
        "variant_id": "pooled_f_candidate_miami_current_fallback_predawn_repair_v0_1",
        "replay": DEFAULT_BACKTEST_ROOT / "pooled_f_candidate_miami_current_fallback_predawn_repair_replay_summary.json",
        "hourly": DEFAULT_BACKTEST_ROOT / "pooled_f_candidate_miami_current_fallback_predawn_repair_hourly_candidate_performance.json",
        "ten_minute": DEFAULT_BACKTEST_ROOT / "pooled_f_candidate_miami_current_fallback_predawn_repair_ten_minute_performance.json",
        "basis": "configured_item160_gate_candidate",
    },
    {
        "candidate_id": "item147_time_split_alpha",
        "variant_id": "item147_time_split_alpha",
        "replay": DEFAULT_BACKTEST_ROOT / "item160_item147_time_split_alpha_replay_summary.json",
        "hourly": DEFAULT_BACKTEST_ROOT / "item147_time_split_alpha_hourly_candidate_performance.json",
        "ten_minute": DEFAULT_BACKTEST_ROOT / "ten_minute_model_performance.json",
        "basis": "early_hour_shadow_baseline",
    },
    {
        "candidate_id": "route_composite_v0_1",
        "variant_id": "item224_no_market_market_route_composite_v0_1",
        "replay": DEFAULT_BACKTEST_ROOT / "item224_no_market_market_route_composite_replay_summary.json",
        "hourly": DEFAULT_BACKTEST_ROOT / "item224_no_market_market_route_composite_hourly_candidate_performance.json",
        "ten_minute": DEFAULT_BACKTEST_ROOT / "item224_no_market_market_route_composite_ten_minute_performance.json",
        "countability_probe": DEFAULT_BACKTEST_ROOT / "item160_forced_active_route_countability_probe.json",
        "basis": "diagnostic_market_route",
    },
    {
        "candidate_id": "route_composite_v0_2",
        "variant_id": "item224_no_market_market_route_composite_v0_2",
        "replay": DEFAULT_BACKTEST_ROOT / "item224_no_market_market_route_composite_v0_2_replay_summary.json",
        "hourly": DEFAULT_BACKTEST_ROOT / "item224_no_market_market_route_composite_v0_2_hourly_candidate_performance.json",
        "ten_minute": DEFAULT_BACKTEST_ROOT / "item224_no_market_market_route_composite_v0_2_ten_minute_performance.json",
        "basis": "diagnostic_same_corpus_missingness_route",
    },
    {
        "candidate_id": "active_source_route_v0_1",
        "variant_id": "item224_active_source_route_composite_v0_1",
        "replay": DEFAULT_BACKTEST_ROOT / "item224_active_source_route_composite_replay_summary.json",
        "hourly": DEFAULT_BACKTEST_ROOT / "item224_active_source_route_composite_hourly_gate.json",
        "ten_minute": DEFAULT_BACKTEST_ROOT / "item224_active_source_route_composite_ten_minute_performance.json",
        "basis": "active_contract_source_route_probe",
    },
    {
        "candidate_id": "active_timesplit_logistic_v0_1",
        "variant_id": "item224_active_timesplit_logistic_repair_v0_1",
        "replay": DEFAULT_BACKTEST_ROOT / "item224_active_timesplit_logistic_repair_replay_summary.json",
        "hourly": DEFAULT_BACKTEST_ROOT / "item224_active_timesplit_logistic_repair_hourly_gate.json",
        "ten_minute": DEFAULT_BACKTEST_ROOT / "item224_active_timesplit_logistic_repair_ten_minute.json",
        "served_distribution": DEFAULT_BACKTEST_ROOT / "item160_active_timesplit_served_distribution_contract.json",
        "positive_gate": DEFAULT_BACKTEST_ROOT / "item160_active_timesplit_positive_daily_first_gate.json",
        "basis": "active_contract_timesplit_repair",
    },
]


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: str | Path | None) -> dict[str, Any] | None:
    if path in (None, ""):
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
    return str(value or "").upper() in {"PASS", "READY", "PROVEN", "ALLOW", "ALLOWED"}


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_blocker(payload: dict[str, Any] | None) -> str:
    payload = payload or {}
    first = payload.get("first_blocker") or {}
    if isinstance(first, dict) and first.get("detail"):
        return str(first.get("detail"))
    blockers = payload.get("blockers") or []
    if blockers and isinstance(blockers[0], dict):
        return str(blockers[0].get("detail") or blockers[0].get("gate") or blockers[0].get("category") or "")
    return ""


def replay_summary(path: str | Path | None) -> dict[str, Any]:
    payload = _read_json(path)
    blocked = (payload or {}).get("blocked_validation") or {}
    aggregate = (payload or {}).get("aggregate") or {}
    shadow = (payload or {}).get("candidate_shadow_variants") or {}
    market_blocks = [
        row.get("market_id")
        for row in (payload or {}).get("market_rows") or []
        if row.get("verdict") == "BLOCK" and row.get("market_id")
    ]
    return {
        "path": str(path) if path else None,
        "exists": Path(path).exists() if path else False,
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "variant_id": shadow.get("variant_id"),
        "validation_evidence": (payload or {}).get("validation_evidence") or blocked.get("validation_evidence"),
        "registry_contract": shadow.get("registry_contract"),
        "verdict": (payload or {}).get("verdict"),
        "cutover_decision": (payload or {}).get("cutover_decision"),
        "candidate_market_verdict": (payload or {}).get("candidate_market_verdict"),
        "metric_passed": bool(blocked.get("metric_passed") or (payload or {}).get("row_export_metric_passed")),
        "blocked_validation_passed": blocked.get("passed"),
        "blocked_validation_reasons": blocked.get("reasons") or [],
        "delta_vs_current": aggregate.get("delta_vs_current"),
        "delta_vs_market": aggregate.get("delta_vs_market"),
        "market_block_count": len(market_blocks),
        "blocked_markets": sorted(set(market_blocks)),
    }


def hourly_summary(path: str | Path | None) -> dict[str, Any]:
    payload = _read_json(path)
    gate = (payload or {}).get("candidate_hourly_gate") or {}
    early = gate.get("early_morning") or {}
    return {
        "path": str(path) if path else None,
        "exists": Path(path).exists() if path else False,
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": gate.get("status"),
        "blocker_count": gate.get("blocker_count", len(gate.get("blockers") or [])),
        "first_blocker": _first_blocker(gate),
        "delta_vs_current": early.get("delta_vs_current"),
        "delta_vs_market": early.get("delta_vs_market"),
        "logloss_delta_vs_market": early.get("logloss_delta_vs_market"),
    }


def ten_minute_summary(path: str | Path | None) -> dict[str, Any]:
    payload = _read_json(path)
    gate = (payload or {}).get("candidate_ten_minute_gate") or {}
    overlap = gate.get("weak_slot_overlap") or {}
    return {
        "path": str(path) if path else None,
        "exists": Path(path).exists() if path else False,
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": gate.get("status"),
        "blocker_count": gate.get("blocker_count", len(gate.get("blockers") or [])),
        "first_blocker": _first_blocker(gate),
        "delta_vs_current": overlap.get("delta_vs_current"),
        "delta_vs_market": overlap.get("delta_vs_market"),
        "logloss_delta_vs_market": overlap.get("logloss_delta_vs_market"),
    }


def countability_probe_summary(path: str | Path | None) -> dict[str, Any]:
    payload = _read_json(path)
    return {
        "path": str(path) if path else None,
        "exists": Path(path).exists() if path else False,
        "status": (payload or {}).get("status"),
        "exception": (payload or {}).get("exception"),
    }


def gate_artifact_summary(path: str | Path | None) -> dict[str, Any]:
    payload = _read_json(path)
    gates = (payload or {}).get("gates") or []
    blockers = (payload or {}).get("blockers") or [
        row for row in gates if row.get("status") == "BLOCK"
    ]
    return {
        "path": str(path) if path else None,
        "exists": Path(path).exists() if path else False,
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": (payload or {}).get("status"),
        "acceptance_passed": (payload or {}).get("acceptance_passed"),
        "blocker_count": (payload or {}).get("blocker_count", len(blockers)),
        "first_blocker": _first_blocker(payload),
        "blocking_gates": [
            str(row.get("gate") or row.get("category") or "")
            for row in blockers
            if isinstance(row, dict)
        ],
    }


def _model_candidate_ready(row: dict[str, Any]) -> bool:
    replay = row["replay"]
    hourly = row["hourly"]
    ten = row["ten_minute"]
    return (
        replay.get("validation_evidence") == "active_replay_contract"
        and bool(replay.get("registry_contract"))
        and replay.get("blocked_validation_passed") is True
        and _passes(hourly.get("status"))
        and _passes(ten.get("status"))
    )


def classify_candidate(row: dict[str, Any]) -> tuple[str, str, list[str]]:
    replay = row["replay"]
    hourly = row["hourly"]
    ten = row["ten_minute"]
    probe = row["countability_probe"]
    served = row["served_distribution"]
    positive = row["positive_gate"]
    blockers = []

    if not replay.get("exists"):
        blockers.append("replay evidence missing")
    if not hourly.get("exists"):
        blockers.append("candidate hourly evidence missing")
    if not ten.get("exists"):
        blockers.append("candidate ten-minute evidence missing")
    if blockers:
        return "EVIDENCE_MISSING", "; ".join(blockers), blockers

    if not _passes(hourly.get("status")):
        blockers.append(hourly.get("first_blocker") or "candidate hourly gate is not clear")
    if not _passes(ten.get("status")):
        blockers.append(ten.get("first_blocker") or "candidate ten-minute gate is not clear")
    if replay.get("validation_evidence") != "active_replay_contract" or not replay.get("registry_contract"):
        blockers.append("replay evidence is not active replay/export contract evidence")
    if replay.get("validation_evidence") == "active_replay_contract" and replay.get("blocked_validation_passed") is not True:
        blockers.append("; ".join(replay.get("blocked_validation_reasons") or []) or "active replay contract validation blocks")
    if replay.get("validation_evidence") != "active_replay_contract" and replay.get("metric_passed") is not True:
        blockers.append("; ".join(replay.get("blocked_validation_reasons") or []) or "candidate replay metrics block")
    if probe.get("status") == "EXPECTED_REJECTED":
        blockers.append("forced active countability probe rejects source lineage")

    if not blockers:
        if served.get("exists") and not _passes(served.get("status")):
            served_blockers = served.get("blocking_gates") or []
            detail = served.get("first_blocker") or "served-distribution contract is not clear"
            if served_blockers == ["broad_claim_gate"] or "broad_claim_gate" in served_blockers:
                return "PRODUCTION_READINESS_BLOCKED", detail, [detail]
            return "SERVED_DISTRIBUTION_BLOCKED", detail, [detail]
        if positive.get("exists") and not _passes(positive.get("status")):
            detail = positive.get("first_blocker") or "positive daily-first gate is not clear"
            progress_gates = {
                "rolling_daily_first_non_negative",
                "positive_daily_first_days",
                "promotion_grade_market_days",
                "progress_claim_allowed",
                "progress_audit_refreshed_after_candidate",
            }
            readiness_gates = {
                "production_readiness_gate",
                "served_distribution_contract",
            }
            blocking_gates = set(positive.get("blocking_gates") or [])
            if blocking_gates & progress_gates and blocking_gates & readiness_gates:
                return "READINESS_AND_PROGRESS_BLOCKED", detail, [detail]
            if blocking_gates & readiness_gates:
                return "PRODUCTION_READINESS_BLOCKED", detail, [detail]
            if blocking_gates & progress_gates:
                return "PROGRESS_TREND_BLOCKED", detail, [detail]
            return "ACCEPTANCE_GATE_BLOCKED", detail, [detail]
        return "PROMOTION_READY_CANDIDATE", "all item-160 candidate evidence gates clear", []

    metric_shape_ok = (
        replay.get("metric_passed") is True
        and _passes(hourly.get("status"))
        and _passes(ten.get("status"))
    )
    if metric_shape_ok and (
        replay.get("validation_evidence") != "active_replay_contract"
        or probe.get("status") == "EXPECTED_REJECTED"
    ):
        return "COUNTABILITY_BLOCKED", blockers[0], blockers
    if replay.get("validation_evidence") == "active_replay_contract":
        return "PERFORMANCE_BLOCKED", blockers[0], blockers
    return "MIXED_BLOCKED", blockers[0], blockers


def summarize_candidate(spec: dict[str, Any]) -> dict[str, Any]:
    row = {
        "candidate_id": spec.get("candidate_id"),
        "variant_id": spec.get("variant_id"),
        "basis": spec.get("basis"),
        "replay": replay_summary(spec.get("replay")),
        "hourly": hourly_summary(spec.get("hourly")),
        "ten_minute": ten_minute_summary(spec.get("ten_minute")),
        "countability_probe": countability_probe_summary(spec.get("countability_probe")),
        "served_distribution": gate_artifact_summary(spec.get("served_distribution")),
        "positive_gate": gate_artifact_summary(spec.get("positive_gate")),
    }
    status, next_action, blockers = classify_candidate(row)
    row["status"] = status
    row["next_action"] = next_action
    row["blockers"] = blockers
    return row


def _best_by_delta(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    scored = [
        row
        for row in candidates
        if _safe_float((row.get("replay") or {}).get("delta_vs_market")) is not None
    ]
    if not scored:
        return None
    return min(scored, key=lambda row: _safe_float((row.get("replay") or {}).get("delta_vs_market")))


def build_payload(candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    specs = candidates or DEFAULT_CANDIDATES
    rows = [summarize_candidate(spec) for spec in specs]
    ready = [row for row in rows if row.get("status") == "PROMOTION_READY_CANDIDATE"]
    metric_ready = [
        row
        for row in rows
        if row.get("replay", {}).get("metric_passed")
        and _passes(row.get("hourly", {}).get("status"))
        and _passes(row.get("ten_minute", {}).get("status"))
    ]
    active_countable = [
        row
        for row in rows
        if row.get("replay", {}).get("validation_evidence") == "active_replay_contract"
        and row.get("replay", {}).get("registry_contract")
    ]
    model_ready = [row for row in rows if _model_candidate_ready(row)]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": "PASS" if ready else "BLOCK",
        "promotion_ready_candidate_count": len(ready),
        "model_ready_candidate_count": len(model_ready),
        "metric_ready_candidate_count": len(metric_ready),
        "active_countable_candidate_count": len(active_countable),
        "best_metric_candidate": (_best_by_delta(metric_ready) or {}).get("candidate_id"),
        "best_countable_candidate": (_best_by_delta(active_countable) or {}).get("candidate_id"),
        "best_model_ready_candidate": (_best_by_delta(model_ready) or {}).get("candidate_id"),
        "summary": {
            "candidate_count": len(rows),
            "statuses": {
                status: sum(1 for row in rows if row.get("status") == status)
                for status in sorted({row.get("status") for row in rows})
            },
        },
        "candidates": rows,
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Item 160 Candidate Viability Audit",
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
            ["Promotion-ready candidates", payload.get("promotion_ready_candidate_count")],
            ["Model-ready candidates", payload.get("model_ready_candidate_count")],
            ["Metric-ready candidates", payload.get("metric_ready_candidate_count")],
            ["Active-countable candidates", payload.get("active_countable_candidate_count")],
            ["Best metric candidate", payload.get("best_metric_candidate") or "-"],
            ["Best countable candidate", payload.get("best_countable_candidate") or "-"],
            ["Best model-ready candidate", payload.get("best_model_ready_candidate") or "-"],
        ],
    )
    lines += ["", "## Candidates", ""]
    lines += markdown_table(
        [
            "Candidate",
            "Status",
            "Replay evidence",
            "Replay dM",
            "Hourly",
            "Hourly dM",
            "10-min",
            "10-min dM",
            "Next action",
        ],
        [
            [
                row.get("candidate_id"),
                row.get("status"),
                (row.get("replay") or {}).get("validation_evidence") or "-",
                fmt_num((row.get("replay") or {}).get("delta_vs_market"), 4),
                (row.get("hourly") or {}).get("status") or "-",
                fmt_num((row.get("hourly") or {}).get("delta_vs_market"), 4),
                (row.get("ten_minute") or {}).get("status") or "-",
                fmt_num((row.get("ten_minute") or {}).get("delta_vs_market"), 4),
                row.get("next_action"),
            ]
            for row in payload.get("candidates") or []
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
    parser = argparse.ArgumentParser(description="Audit Item 160 early-hour candidate viability.")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_payload()
    json_path, report_path = write_outputs(payload, args.out, args.report)
    print(
        "Item 160 candidate viability audit: "
        f"{payload['status']} ({payload['promotion_ready_candidate_count']} ready candidate(s))"
    )
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
