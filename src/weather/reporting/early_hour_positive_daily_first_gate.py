"""Positive daily-first gate for early-hour model-skill remediation."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("early_hour_positive_daily_first_gate")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_PROGRESS_AUDIT = DEFAULT_BACKTEST_ROOT / "progress_audit.json"
DEFAULT_CONTRACT = DEFAULT_BACKTEST_ROOT / "item160_active_timesplit_served_distribution_contract.json"
DEFAULT_CANDIDATE_HOURLY = (
    DEFAULT_BACKTEST_ROOT / "item224_active_timesplit_logistic_repair_hourly_gate.json"
)
DEFAULT_CANDIDATE_TEN_MINUTE = (
    DEFAULT_BACKTEST_ROOT / "item224_active_timesplit_logistic_repair_ten_minute.json"
)
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "early_hour_positive_daily_first_gate.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "early_hour_positive_daily_first_gate_report.md"
DEFAULT_MIN_POSITIVE_DAILY_FIRST_DAYS = 3
DEFAULT_MIN_PROMOTION_GRADE_MARKET_DAYS = 84


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


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    value = _safe_float(value)
    return int(value) if value is not None else None


def _passes(value: Any) -> bool:
    return str(value or "").upper() in {"PASS", "READY", "PROVEN", "ALLOW", "ALLOWED"}


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


def _progress_refresh_gate(
    *,
    progress: dict[str, Any],
    contract: dict[str, Any],
    hourly: dict[str, Any],
    ten_minute: dict[str, Any],
) -> dict[str, Any]:
    accepted_candidate_evidence = (
        _passes(hourly.get("status"))
        and _passes(ten_minute.get("status"))
        and _contract_model_acceptance_passed(contract)
    )
    dependencies = [
        ("served_distribution_contract", contract),
        ("candidate_hourly", hourly),
        ("candidate_ten_minute", ten_minute),
    ]
    dependency_rows = []
    for name, payload in dependencies:
        generated = payload.get("generated_at_utc")
        parsed = _parse_datetime(generated)
        dependency_rows.append({
            "name": name,
            "generated_at_utc": generated,
            "parsed_at_utc": parsed.isoformat() if parsed else None,
        })
    progress_generated = progress.get("generated_at_utc")
    progress_dt = _parse_datetime(progress_generated)
    evidence = {
        "accepted_candidate_evidence_complete": accepted_candidate_evidence,
        "progress_generated_at_utc": progress_generated,
        "progress_parsed_at_utc": progress_dt.isoformat() if progress_dt else None,
        "dependencies": dependency_rows,
    }
    if not accepted_candidate_evidence:
        return _gate(
            "progress_audit_refreshed_after_candidate",
            "PASS",
            "progress refresh check waits for accepted candidate evidence",
            evidence,
        )

    missing = [row["name"] for row in dependency_rows if not row.get("parsed_at_utc")]
    if progress_dt is None:
        return _gate(
            "progress_audit_refreshed_after_candidate",
            "BLOCK",
            "progress audit generated_at_utc is missing or invalid after accepted candidate evidence",
            evidence,
        )
    if missing:
        return _gate(
            "progress_audit_refreshed_after_candidate",
            "BLOCK",
            "accepted candidate evidence is missing generated_at_utc: " + ", ".join(missing),
            evidence,
        )

    latest_name, latest_dt = max(
        (
            (row["name"], _parse_datetime(row["generated_at_utc"]))
            for row in dependency_rows
        ),
        key=lambda item: item[1],
    )
    evidence["latest_candidate_dependency"] = {
        "name": latest_name,
        "generated_at_utc": latest_dt.isoformat() if latest_dt else None,
    }
    if latest_dt is not None and progress_dt >= latest_dt:
        return _gate(
            "progress_audit_refreshed_after_candidate",
            "PASS",
            "progress audit was regenerated after accepted candidate evidence",
            evidence,
        )
    return _gate(
        "progress_audit_refreshed_after_candidate",
        "BLOCK",
        (
            "progress audit is stale: generated_at_utc="
            f"{progress_generated or 'missing'} before latest accepted candidate evidence "
            f"{latest_name}={latest_dt.isoformat() if latest_dt else 'missing'}"
        ),
        evidence,
    )


def progress_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    claim = (payload or {}).get("core_model_trend_claim") or {}
    summary = claim.get("summary") or {}
    ledger = (payload or {}).get("daily_progress_ledger_latest") or {}
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": claim.get("status"),
        "claim_allowed": claim.get("claim_allowed"),
        "threshold_failures": claim.get("threshold_failures") or [],
        "next_evidence_needed": claim.get("next_evidence_needed") or [],
        "positive_daily_first_days": _safe_int(summary.get("positive_daily_first_days")),
        "positive_skill_days": _safe_int(summary.get("positive_skill_days")),
        "rolling_daily_first_brier_skill": _safe_float(summary.get("rolling_daily_first_brier_skill")),
        "promotion_grade_market_days": _safe_int(summary.get("promotion_grade_market_days")),
        "runtime_identity_status": summary.get("runtime_identity_status"),
        "ledger_broad_improvement_claim_allowed": ledger.get("broad_improvement_claim_allowed"),
    }


def contract_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    model_acceptance = (payload or {}).get("model_acceptance_passed")
    if model_acceptance is None:
        model_acceptance = (payload or {}).get("acceptance_passed")
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": (payload or {}).get("schema_version"),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": (payload or {}).get("status"),
        "acceptance_passed": (payload or {}).get("acceptance_passed"),
        "model_served_distribution_status": (payload or {}).get("model_served_distribution_status"),
        "model_acceptance_passed": model_acceptance,
        "broad_core_model_claim_allowed": (payload or {}).get("broad_core_model_claim_allowed"),
        "production_readiness_status": (payload or {}).get("production_readiness_status"),
        "production_readiness_blocker_count": (payload or {}).get("production_readiness_blocker_count"),
        "production_readiness_blockers": (payload or {}).get("production_readiness_blockers") or [],
        "blocker_count": (payload or {}).get("blocker_count", len((payload or {}).get("blockers") or [])),
        "first_blocker": _first_blocker(payload),
    }


def _contract_model_acceptance_passed(contract: dict[str, Any]) -> bool:
    if contract.get("model_served_distribution_status") not in (None, ""):
        return _passes(contract.get("model_served_distribution_status")) and contract.get("model_acceptance_passed") is True
    return _passes(contract.get("status")) and contract.get("acceptance_passed") is True


def _contract_production_readiness_gate(contract: dict[str, Any]) -> dict[str, Any]:
    status = contract.get("production_readiness_status")
    if status in (None, ""):
        return _gate(
            "production_readiness_gate",
            "PASS",
            "served-distribution contract has no separate production-readiness blocker",
            contract,
        )
    if _passes(status):
        return _gate(
            "production_readiness_gate",
            "PASS",
            "production readiness gate passed for served-distribution evidence",
            contract,
        )
    readiness_blockers = contract.get("production_readiness_blockers") or []
    if readiness_blockers and isinstance(readiness_blockers[0], dict):
        detail = str(
            readiness_blockers[0].get("detail")
            or readiness_blockers[0].get("gate")
            or f"production readiness is {status}; broad core-model claim remains blocked"
        )
        return _gate("production_readiness_gate", "BLOCK", detail, contract)
    detail = (
        contract.get("first_blocker")
        or f"production readiness is {status}; broad core-model claim remains blocked"
    )
    return _gate("production_readiness_gate", "BLOCK", detail, contract)


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
        "winner_variant_probability": early.get("winner_variant_probability"),
        "winner_market_probability": early.get("winner_market_probability"),
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
        "winner_variant_probability": overlap.get("winner_variant_probability"),
        "winner_market_probability": overlap.get("winner_market_probability"),
    }


def build_gates(
    *,
    progress: dict[str, Any],
    contract: dict[str, Any],
    hourly: dict[str, Any],
    ten_minute: dict[str, Any],
    min_positive_daily_first_days: int,
    min_promotion_grade_market_days: int,
) -> list[dict[str, Any]]:
    gates = []
    gates.append(_gate(
        "candidate_hourly_early_gate",
        "PASS" if _passes(hourly.get("status")) else "BLOCK",
        (
            "candidate hourly early gate passed"
            if _passes(hourly.get("status"))
            else hourly.get("first_blocker") or "candidate hourly early gate is not clear"
        ),
        hourly,
    ))
    gates.append(_gate(
        "candidate_weak_slot_ten_minute_gate",
        "PASS" if _passes(ten_minute.get("status")) else "BLOCK",
        (
            "candidate 10-minute weak-slot gate passed"
            if _passes(ten_minute.get("status"))
            else ten_minute.get("first_blocker") or "candidate 10-minute weak-slot gate is not clear"
        ),
        ten_minute,
    ))
    gates.append(_gate(
        "served_distribution_contract",
        "PASS" if _contract_model_acceptance_passed(contract) else "BLOCK",
        (
            "served-distribution calibration contract passed"
            if _contract_model_acceptance_passed(contract)
            else contract.get("first_blocker") or "served-distribution calibration contract is not clear"
        ),
        contract,
    ))
    gates.append(_contract_production_readiness_gate(contract))
    gates.append(_progress_refresh_gate(
        progress=progress,
        contract=contract,
        hourly=hourly,
        ten_minute=ten_minute,
    ))
    rolling = progress.get("rolling_daily_first_brier_skill")
    gates.append(_gate(
        "rolling_daily_first_non_negative",
        "PASS" if rolling is not None and rolling >= 0 else "BLOCK",
        (
            f"rolling daily-first skill is non-negative: {rolling:+.4f}"
            if rolling is not None and rolling >= 0
            else (
                "rolling daily-first skill is unavailable"
                if rolling is None
                else f"rolling daily-first skill is {rolling:+.4f}"
            )
        ),
        {"rolling_daily_first_brier_skill": rolling},
    ))
    positive_days = progress.get("positive_daily_first_days")
    gates.append(_gate(
        "positive_daily_first_days",
        "PASS" if positive_days is not None and positive_days >= min_positive_daily_first_days else "BLOCK",
        (
            f"positive daily-first days {positive_days} >= {min_positive_daily_first_days}"
            if positive_days is not None and positive_days >= min_positive_daily_first_days
            else f"need {min_positive_daily_first_days} positive daily-first days; have {positive_days or 0}"
        ),
        {"positive_daily_first_days": positive_days, "required": min_positive_daily_first_days},
    ))
    market_days = progress.get("promotion_grade_market_days")
    gates.append(_gate(
        "promotion_grade_market_days",
        "PASS" if market_days is not None and market_days >= min_promotion_grade_market_days else "BLOCK",
        (
            f"promotion-grade market-days {market_days} >= {min_promotion_grade_market_days}"
            if market_days is not None and market_days >= min_promotion_grade_market_days
            else f"need {min_promotion_grade_market_days} promotion-grade market-days; have {market_days or 0}"
        ),
        {"promotion_grade_market_days": market_days, "required": min_promotion_grade_market_days},
    ))
    gates.append(_gate(
        "progress_claim_allowed",
        "PASS" if progress.get("claim_allowed") is True and _passes(progress.get("status")) else "BLOCK",
        (
            "progress audit allows the core model claim"
            if progress.get("claim_allowed") is True and _passes(progress.get("status"))
            else "; ".join(progress.get("threshold_failures") or []) or "progress audit does not allow the claim"
        ),
        progress,
    ))
    return gates


def build_payload(
    *,
    progress_audit: str | Path = DEFAULT_PROGRESS_AUDIT,
    served_distribution_contract: str | Path = DEFAULT_CONTRACT,
    candidate_hourly: str | Path = DEFAULT_CANDIDATE_HOURLY,
    candidate_ten_minute: str | Path = DEFAULT_CANDIDATE_TEN_MINUTE,
    min_positive_daily_first_days: int = DEFAULT_MIN_POSITIVE_DAILY_FIRST_DAYS,
    min_promotion_grade_market_days: int = DEFAULT_MIN_PROMOTION_GRADE_MARKET_DAYS,
) -> dict[str, Any]:
    progress = progress_summary(progress_audit)
    contract = contract_summary(served_distribution_contract)
    hourly = candidate_hourly_summary(candidate_hourly)
    ten = candidate_ten_minute_summary(candidate_ten_minute)
    gates = build_gates(
        progress=progress,
        contract=contract,
        hourly=hourly,
        ten_minute=ten,
        min_positive_daily_first_days=min_positive_daily_first_days,
        min_promotion_grade_market_days=min_promotion_grade_market_days,
    )
    blockers = [gate for gate in gates if gate.get("status") == "BLOCK"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": "PASS" if not blockers else "BLOCK",
        "acceptance_passed": not blockers,
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else None,
        "thresholds": {
            "min_positive_daily_first_days": int(min_positive_daily_first_days),
            "min_promotion_grade_market_days": int(min_promotion_grade_market_days),
        },
        "inputs": {
            "progress_audit": str(progress_audit),
            "served_distribution_contract": str(served_distribution_contract),
            "candidate_hourly": str(candidate_hourly),
            "candidate_ten_minute": str(candidate_ten_minute),
        },
        "progress_audit": progress,
        "served_distribution_contract": contract,
        "candidate_hourly": hourly,
        "candidate_ten_minute": ten,
        "gates": gates,
        "blockers": blockers,
    }


def render_report(payload: dict[str, Any]) -> str:
    first = payload.get("first_blocker") or {}
    progress = payload.get("progress_audit") or {}
    hourly = payload.get("candidate_hourly") or {}
    ten = payload.get("candidate_ten_minute") or {}
    lines = [
        "# Early-Hour Positive Daily-First Gate",
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
            ["Acceptance passed", payload.get("acceptance_passed")],
            ["Blockers", payload.get("blocker_count")],
            ["First blocker", first.get("detail") or "-"],
            ["Progress status", progress.get("status")],
            ["Claim allowed", progress.get("claim_allowed")],
            ["Rolling daily-first skill", fmt_num(progress.get("rolling_daily_first_brier_skill"))],
            ["Positive daily-first days", progress.get("positive_daily_first_days")],
            ["Promotion-grade market-days", progress.get("promotion_grade_market_days")],
            ["Candidate hourly status", hourly.get("status")],
            ["Early-hour delta vs market", fmt_num(hourly.get("delta_vs_market"))],
            ["Candidate 10-minute status", ten.get("status")],
            ["Weak-slot delta vs market", fmt_num(ten.get("delta_vs_market"))],
            ["Production readiness", (payload.get("served_distribution_contract") or {}).get("production_readiness_status") or "-"],
        ],
    )
    lines += ["", "## Gates", ""]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [[row.get("gate"), row.get("status"), row.get("detail")] for row in payload.get("gates") or []],
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
    parser = argparse.ArgumentParser(description="Gate early-hour remediation on positive daily-first evidence.")
    parser.add_argument("--progress-audit", default=str(DEFAULT_PROGRESS_AUDIT))
    parser.add_argument("--served-distribution-contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--candidate-hourly", default=str(DEFAULT_CANDIDATE_HOURLY))
    parser.add_argument("--candidate-ten-minute", default=str(DEFAULT_CANDIDATE_TEN_MINUTE))
    parser.add_argument("--min-positive-daily-first-days", type=int, default=DEFAULT_MIN_POSITIVE_DAILY_FIRST_DAYS)
    parser.add_argument("--min-promotion-grade-market-days", type=int, default=DEFAULT_MIN_PROMOTION_GRADE_MARKET_DAYS)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_payload(
        progress_audit=args.progress_audit,
        served_distribution_contract=args.served_distribution_contract,
        candidate_hourly=args.candidate_hourly,
        candidate_ten_minute=args.candidate_ten_minute,
        min_positive_daily_first_days=args.min_positive_daily_first_days,
        min_promotion_grade_market_days=args.min_promotion_grade_market_days,
    )
    json_path, report_path = write_outputs(payload, args.out, args.report)
    print(f"Early-hour positive daily-first gate: {payload['status']} ({payload['blocker_count']} blocker(s))")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
