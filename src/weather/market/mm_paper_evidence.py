"""Run eligibility and per-market evidence policy for MM paper scoring."""

from __future__ import annotations

import json
from pathlib import Path

from weather.market.mm_policy import bool_value


COMPATIBLE_RUN_SCHEMA_VERSIONS = {"mm_run_v0.2"}
LIVE_FORWARD_EVIDENCE_CLASSES = (
    "model_review_evidence",
    "paper_trading_evidence",
    "live_trade_permission_evidence",
)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def live_forward_gate_path_for_folder(folder, summary=None):
    summary = summary or {}
    path = summary.get("live_forward_gate_path")
    if path:
        return Path(path)
    return Path(folder) / "live_forward_gate.json"


def per_market_evidence_credit_rows(folder, gate_payload=None):
    gate = gate_payload if gate_payload is not None else read_json(Path(folder) / "live_forward_gate.json", {}) or {}
    rows = []
    for market in gate.get("markets") or []:
        first_failure = market.get("first_failing_gate") or {}
        recovery = market.get("stale_recovery") or {}
        countability = market.get("countability") or {}
        for evidence_class in LIVE_FORWARD_EVIDENCE_CLASSES:
            item = countability.get(evidence_class) or {}
            rows.append({
                "run_folder": str(folder),
                "run_id": gate.get("run_id"),
                "target_date": gate.get("target_date"),
                "mode": gate.get("mode"),
                "market_id": market.get("market_id"),
                "evidence_class": evidence_class,
                "counts": bool(item.get("counts")),
                "blocking_gates": item.get("blocking_gates") or [],
                "first_failing_gate": first_failure.get("name"),
                "owner": first_failure.get("owner"),
                "root_cause": first_failure.get("root_cause"),
                "suggested_command": first_failure.get("suggested_command"),
                "stale_recovery": recovery,
            })
    return rows


def summarize_per_market_evidence(rows):
    summary = {}
    for evidence_class in LIVE_FORWARD_EVIDENCE_CLASSES:
        class_rows = [row for row in rows if row.get("evidence_class") == evidence_class]
        markets = {row.get("market_id") for row in class_rows if row.get("market_id")}
        countable = {row.get("market_id") for row in class_rows if row.get("market_id") and row.get("counts")}
        blocked = sorted(markets - countable)
        first_blocked = next(
            (row for row in class_rows if row.get("market_id") in blocked and not row.get("counts")),
            None,
        )
        summary[evidence_class] = {
            "market_count": len(markets),
            "countable_market_count": len(countable),
            "blocked_market_count": len(blocked),
            "countable_markets": sorted(countable),
            "blocked_markets": blocked,
            "all_selected_markets_count": bool(markets) and len(countable) == len(markets),
            "first_blocked_market": (first_blocked or {}).get("market_id"),
            "first_blocked_gate": (first_blocked or {}).get("first_failing_gate"),
            "first_blocked_owner": (first_blocked or {}).get("owner"),
            "first_blocked_command": (first_blocked or {}).get("suggested_command"),
        }
    return summary


def run_folder_eligibility(folder):
    folder = Path(folder)
    summary = read_json(folder / "run_summary.json", {}) or {}
    run_config = read_json(folder / "run_config.json", {}) or {}
    schema_version = summary.get("schema_version") or run_config.get("schema_version")
    reasons = []
    if schema_version and schema_version not in COMPATIBLE_RUN_SCHEMA_VERSIONS:
        reasons.append(f"incompatible_schema:{schema_version}")
    live_gate_path = live_forward_gate_path_for_folder(folder, summary)
    live_gate = read_json(live_gate_path, {}) or {}
    remediation = summary.get("preflight_remediation")
    if remediation is None:
        remediation = read_json(folder / "preflight_remediation.json", {}) or {}
    counts_toward_gate = None
    if live_gate:
        counts_toward_gate = bool_value(live_gate.get("counts_toward_live_forward_gate"), False)
    elif remediation:
        counts_toward_gate = bool_value(remediation.get("counts_toward_live_forward_gate"), False)
    elif summary.get("preflight_status"):
        counts_toward_gate = summary.get("preflight_status") == "PASS"
    credit_rows = per_market_evidence_credit_rows(folder, live_gate) if live_gate else []
    return {
        "run_folder": str(folder),
        "schema_version": schema_version or "unknown",
        "scoreable": not reasons,
        "live_forward_gate_counts": bool(counts_toward_gate) if counts_toward_gate is not None else True,
        "live_forward_gate_status": live_gate.get("status") or (summary.get("live_forward_gate") or {}).get("status"),
        "live_forward_gate_path": str(live_gate_path) if live_gate_path.exists() else None,
        "per_market_evidence_credits": credit_rows,
        "per_market_evidence_summary": summarize_per_market_evidence(credit_rows),
        "non_scoreable_reasons": reasons,
        "preflight_status": summary.get("preflight_status"),
        "remediation_counts_toward_live_forward_gate": counts_toward_gate,
        "policy_hash": summary.get("policy_hash") or run_config.get("policy_hash"),
        "run_id": summary.get("run_id") or run_config.get("run_id") or folder.name,
    }


def split_run_folders_by_eligibility(run_folders):
    eligibility = {str(Path(folder)): run_folder_eligibility(folder) for folder in run_folders}
    scoreable = [Path(folder) for folder in run_folders if eligibility[str(Path(folder))]["scoreable"]]
    excluded = [
        item
        for item in eligibility.values()
        if not item.get("scoreable")
    ]
    return scoreable, eligibility, excluded
