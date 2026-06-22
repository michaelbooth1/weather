"""Summaries for market-making and taker paper trading evidence."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from weather.paths import data_path


DEFAULT_DATA_ROOT = data_path()
DEFAULT_MM_RUNS_ROOT = DEFAULT_DATA_ROOT / "mm_runs"
DEFAULT_TAKER_RUNS_ROOT = DEFAULT_DATA_ROOT / "taker_runs"
TAKER_QUALITY_MIN_ROLLING_RUNS = 5
TAKER_QUALITY_MIN_FILLS = 100
TAKER_QUALITY_MIN_NET_PNL_USDC = 0.0
COUNTABLE_MM_EVIDENCE_MODE = "active_day_live_forward"
MM_STARVATION_BLOCKED_FRACTION_THRESHOLD = 0.75
MM_STALE_INPUT_GATES = {"model_freshness", "clob_freshness", "observation_trigger"}
MM_PREFLIGHT_GATE_OWNER_ITEMS = {
    "model_freshness": ["161", "157"],
    "clob_freshness": ["161"],
    "observation_trigger": ["161"],
}
MM_PREFLIGHT_RECOVERY_COMMANDS = {
    "stale_model_row": "python -m weather.collection.snapshot_tracker --status",
    "missing_snapshot_model_rows": "python -m weather.collection.snapshot_tracker --status",
    "stale_source_status_row": "python -m weather.collection.snapshot_tracker --status",
    "stale_clob_book_tape": "python -m weather.market.market_microstructure ensure",
    "missing_clob_book_rows": "python -m weather.market.market_microstructure status",
    "missing_clob_feature_rows": "python -m weather.market.market_microstructure_features",
    "watcher_stale": "python -m weather.operations.observation_trigger ensure",
}
MM_PREFLIGHT_RECOVERY_CLOSEOUT_FILENAME = "preflight_recovery_closeout.json"
MM_STARVATION_REMEDIATION_BOUNDARY = (
    "producer-side loop cadence and snapshot cadence remediation belongs to "
    "ROADMAP 161/157; MM evidence-starvation detection and trend ownership "
    "belongs to ROADMAP 210; active-day supervisor recovery closeout belongs "
    "to ROADMAP 211"
)


def _read_json(path):
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_remediation_payload(path, payload):
    candidates = []
    if (payload or {}).get("preflight_remediation_path"):
        candidates.append(Path(payload["preflight_remediation_path"]))
    if path:
        candidates.append(Path(path).with_name("preflight_remediation.json"))
    for candidate in candidates:
        remediation = _read_json(candidate)
        if remediation:
            return candidate, remediation
    return None, {}


def _closeout_candidates(path, payload):
    candidates = []
    closeout = (payload or {}).get("preflight_recovery_closeout") or {}
    for key in ("path", "artifact_path", "closeout_path"):
        if closeout.get(key):
            candidates.append(Path(closeout[key]))
    if (payload or {}).get("preflight_recovery_closeout_path"):
        candidates.append(Path(payload["preflight_recovery_closeout_path"]))
    run_folder = (payload or {}).get("run_folder")
    if run_folder:
        candidates.append(Path(run_folder) / MM_PREFLIGHT_RECOVERY_CLOSEOUT_FILENAME)
    if path:
        candidates.append(Path(path).with_name(MM_PREFLIGHT_RECOVERY_CLOSEOUT_FILENAME))
    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        yield candidate


def _read_recovery_closeout(path, payload):
    for candidate in _closeout_candidates(path, payload):
        closeout = _read_json(candidate)
        if closeout:
            return candidate, closeout
    return None, {}


def _unique_commands(commands):
    rows = []
    seen = set()
    for command in commands:
        command = str(command or "").strip()
        if not command or command in seen:
            continue
        seen.add(command)
        rows.append(command)
    return rows


def _remediation_commands(path, payload, closeout):
    closeout_commands = _unique_commands(
        row.get("suggested_command")
        for row in (closeout or {}).get("command_results") or []
    )
    if closeout_commands:
        return closeout_commands
    _remediation_path, remediation = _read_remediation_payload(path, payload)
    incident_commands = _unique_commands(
        row.get("suggested_command")
        for row in (remediation or {}).get("incidents") or []
    )
    if incident_commands:
        return incident_commands
    root_counts = (((payload or {}).get("preflight_remediation") or {}).get("root_cause_counts") or {})
    return _unique_commands(MM_PREFLIGHT_RECOVERY_COMMANDS.get(root) for root in root_counts)


def _closeout_status(closeout, starved):
    if not starved:
        return "NOT_REQUIRED"
    if not closeout:
        return "MISSING"
    return closeout.get("status") or ("RECOVERED" if closeout.get("recovered") else "ATTEMPTED_UNRECOVERED")


def _latest_run_summary(root):
    root = Path(root)
    candidates = sorted(root.glob("*/*/run_summary.json"))
    if not candidates:
        return None, None
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    return latest, _read_json(latest)


def _all_run_summaries(root):
    rows = []
    for path in sorted(Path(root).glob("*/*/run_summary.json")):
        payload = _read_json(path)
        if payload:
            rows.append((path, payload))
    return rows


def _run_sort_key(path, payload):
    return (
        str(payload.get("target_date") or ""),
        str(payload.get("generated_at_utc") or ""),
        path.stat().st_mtime if Path(path).exists() else 0,
        str(payload.get("run_id") or path),
    )


def _float_value(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_value(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _first_present(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _settled_taker_payload(summary_path):
    if not summary_path:
        return None
    return _read_json(Path(summary_path).with_name("settled_pnl.json"))


def _evidence_class(payload, class_name):
    gate = payload.get("live_forward_gate") or {}
    evidence = gate.get("evidence") or {}
    return evidence.get(class_name) or {}


def _live_forward_evidence(payload, class_name):
    gate = (payload or {}).get("live_forward_gate") or {}
    evidence = gate.get("evidence") or {}
    return evidence.get(class_name) or {}


def _live_forward_summary(payload):
    return ((payload or {}).get("live_forward_gate") or {}).get("summary") or {}


def _preflight_markets(payload):
    preflight = (payload or {}).get("preflight") or {}
    markets = preflight.get("markets") or (payload or {}).get("markets") or []
    return [row for row in markets if isinstance(row, dict)]


def _preflight_blocked_markets(payload):
    markets = _preflight_markets(payload)
    return [row for row in markets if row.get("status") != "PASS"]


def _failed_preflight_gates(payload):
    rows = []
    for market in _preflight_markets(payload):
        for gate in market.get("gates") or []:
            if gate.get("ok"):
                continue
            rows.append((market, gate))
    return rows


def _seconds_from_detail(detail):
    match = re.search(r"(\d+(?:\.\d+)?)s old", str(detail or ""))
    return float(match.group(1)) if match else None


def _stale_gate_age_seconds(market, gate):
    name = gate.get("name")
    values = []
    if name == "model_freshness":
        values.append(market.get("model_age_seconds"))
    if name == "clob_freshness":
        values.append((market.get("book_audit") or {}).get("trailing_age_seconds"))
    if name == "observation_trigger":
        values.append(market.get("watcher_age_seconds"))
    values.append(_seconds_from_detail(gate.get("detail")))
    numbers = [_float_value(value, default=None) for value in values]
    numbers = [value for value in numbers if value is not None]
    return max(numbers) if numbers else None


def _owner_items_for_gates(gates):
    owner_items = []
    seen = set()
    for gate in gates:
        for item in MM_PREFLIGHT_GATE_OWNER_ITEMS.get(gate, []):
            if item in seen:
                continue
            seen.add(item)
            owner_items.append(item)
    return owner_items


def _stale_gate_summary(payload):
    gate_counts = Counter()
    owner_items = []
    max_age = None
    max_gate = None
    max_market = None
    max_detail = None
    for market, gate in _failed_preflight_gates(payload):
        name = gate.get("name")
        if name not in MM_STALE_INPUT_GATES:
            continue
        gate_counts[name] += 1
        age = _stale_gate_age_seconds(market, gate)
        if age is not None and (max_age is None or age > max_age):
            max_age = age
            max_gate = name
            max_market = market.get("market_id")
            max_detail = gate.get("detail")
    owner_items = _owner_items_for_gates(gate_counts.keys())
    if not gate_counts:
        root_counts = (((payload or {}).get("preflight_remediation") or {}).get("root_cause_counts") or {})
        inferred = []
        if root_counts.get("stale_model_row"):
            inferred.append("model_freshness")
        if root_counts.get("stale_clob_book_tape"):
            inferred.append("clob_freshness")
        if root_counts.get("watcher_stale"):
            inferred.append("observation_trigger")
        owner_items = _owner_items_for_gates(inferred)
        gate_counts.update({gate: 1 for gate in inferred})
    return {
        "stale_gate_counts": dict(sorted(gate_counts.items())),
        "max_stale_input_age_seconds": _float_value(max_age, default=None) if max_age is not None else None,
        "max_stale_input_gate": max_gate,
        "max_stale_input_market_id": max_market,
        "max_stale_input_detail": max_detail,
        "recovery_owner_items": owner_items or ["161", "157"],
    }


def mm_starvation_run_row(path, payload, *, blocked_fraction_threshold=MM_STARVATION_BLOCKED_FRACTION_THRESHOLD):
    payload = payload or {}
    live_summary = _live_forward_summary(payload)
    paper_evidence = _live_forward_evidence(payload, "paper_trading_evidence")
    live_trade_evidence = _live_forward_evidence(payload, "live_trade_permission_evidence")
    markets = _preflight_markets(payload)
    market_count = _int_value(
        live_summary.get("market_count")
        or paper_evidence.get("market_count")
        or len(markets)
    )
    blocked_market_count = _int_value(
        live_summary.get("blocked_market_count")
        or paper_evidence.get("blocked_market_count")
        or len(_preflight_blocked_markets(payload))
    )
    fraction = (blocked_market_count / market_count) if market_count else 0.0
    evidence_mode = (
        payload.get("evidence_mode")
        or ((payload.get("live_forward_gate") or {}).get("evidence_mode"))
    )
    counts_toward_live_forward = bool(_first_present(
        payload.get("counts_toward_live_forward_gate"),
        ((payload.get("live_forward_gate") or {}).get("counts_toward_live_forward_gate")),
    ))
    countable_paper = _int_value(paper_evidence.get("countable_market_count"))
    stale_summary = _stale_gate_summary(payload)
    active_day = evidence_mode == COUNTABLE_MM_EVIDENCE_MODE
    starved = bool(
        active_day
        and not counts_toward_live_forward
        and countable_paper == 0
        and fraction >= float(blocked_fraction_threshold)
    )
    closeout_path, closeout = _read_recovery_closeout(path, payload)
    recovery_status = _closeout_status(closeout, starved)
    recovery_recovered = bool(closeout.get("recovered")) if closeout else False
    recovery_attempted = bool(closeout)
    recovery_unrecovered = bool(starved and not recovery_recovered)
    if starved and recovery_recovered:
        status = "RECOVERED"
    elif starved:
        status = "CRITICAL"
    elif active_day and counts_toward_live_forward:
        status = "PASS"
    elif active_day:
        status = "WARN"
    else:
        status = "NOT_ACTIVE_DAY"
    recovery_commands = _remediation_commands(path, payload, closeout)
    recovery_command = "; ".join(recovery_commands) if recovery_commands else (
        "python -m weather.market.market_microstructure ensure; "
        "python -m weather.collection.snapshot_tracker --status"
    )
    post_repair = (closeout or {}).get("post_repair_run") or {}
    return {
        "path": str(path) if path else None,
        "run_folder": payload.get("run_folder"),
        "run_id": payload.get("run_id"),
        "target_date": payload.get("target_date"),
        "evidence_mode": evidence_mode,
        "active_day": active_day,
        "status": status,
        "starved_active_day": starved,
        "counts_toward_live_forward_gate": counts_toward_live_forward,
        "preflight_status": payload.get("preflight_status") or ((payload.get("preflight") or {}).get("status")),
        "preflight_blocked_market_count": blocked_market_count,
        "preflight_market_count": market_count,
        "preflight_blocked_market_fraction": round(fraction, 6),
        "blocked_fraction_threshold": float(blocked_fraction_threshold),
        "countable_paper_market_count": countable_paper,
        "live_trade_permission_countable_market_count": _int_value(
            live_trade_evidence.get("countable_market_count")
        ),
        "blocked_by_preflight_count": _int_value(
            ((payload.get("cumulative") or {}).get("blocked_by_preflight_count"))
            or payload.get("blocked_by_preflight_count")
        ),
        "preflight_remediation_owner_counts": (
            ((payload.get("preflight_remediation") or {}).get("owner_counts") or {})
        ),
        "preflight_remediation_root_cause_counts": (
            ((payload.get("preflight_remediation") or {}).get("root_cause_counts") or {})
        ),
        "recovery_command": recovery_command,
        "preflight_recovery_closeout_status": recovery_status,
        "preflight_recovery_closeout_path": str(closeout_path) if closeout_path else None,
        "preflight_recovery_attempted": recovery_attempted,
        "preflight_recovery_recovered": recovery_recovered,
        "preflight_recovery_unrecovered": recovery_unrecovered,
        "preflight_recovery_command_count": len((closeout or {}).get("command_results") or []),
        "post_repair_preflight_artifact_path": (
            (closeout or {}).get("post_repair_preflight_artifact_path")
            or ((payload.get("preflight_recovery_closeout") or {}).get("post_repair_preflight_artifact_path"))
        ),
        "post_repair_run_id": post_repair.get("run_id"),
        "post_repair_preflight_status": post_repair.get("preflight_status"),
        "post_repair_counts_toward_live_forward_gate": post_repair.get("counts_toward_live_forward_gate"),
        "remediation_boundary": MM_STARVATION_REMEDIATION_BOUNDARY,
        **stale_summary,
    }


def mm_evidence_starvation_summary(
    mm_runs_root=DEFAULT_MM_RUNS_ROOT,
    *,
    blocked_fraction_threshold=MM_STARVATION_BLOCKED_FRACTION_THRESHOLD,
):
    run_rows = _all_run_summaries(mm_runs_root)
    latest_by_day = {}
    for path, payload in run_rows:
        target_date = payload.get("target_date") or path.parent.name
        current = latest_by_day.get(target_date)
        if current is None or _run_sort_key(path, payload) > _run_sort_key(current[0], current[1]):
            latest_by_day[target_date] = (path, payload)
    rows = [
        mm_starvation_run_row(path, payload, blocked_fraction_threshold=blocked_fraction_threshold)
        for path, payload in sorted(latest_by_day.values(), key=lambda item: _run_sort_key(item[0], item[1]))
    ]
    active_rows = [row for row in rows if row.get("active_day")]
    streak = 0
    for row in reversed(active_rows):
        if row.get("starved_active_day"):
            streak += 1
            continue
        break
    latest = active_rows[-1] if active_rows else (rows[-1] if rows else {})
    countable_market_days = sum(int(row.get("countable_paper_market_count") or 0) for row in active_rows)
    starved_days = sum(1 for row in active_rows if row.get("starved_active_day"))
    recovered_starved_days = sum(
        1 for row in active_rows if row.get("starved_active_day") and row.get("preflight_recovery_recovered")
    )
    recovery_attempted_starved_days = sum(
        1 for row in active_rows if row.get("starved_active_day") and row.get("preflight_recovery_attempted")
    )
    unrecovered_starved_days = sum(
        1 for row in active_rows if row.get("starved_active_day") and not row.get("preflight_recovery_recovered")
    )
    latest_starved = next((row for row in reversed(active_rows) if row.get("starved_active_day")), {})
    latest_recovered_starved = next(
        (
            row for row in reversed(active_rows)
            if row.get("starved_active_day") and row.get("preflight_recovery_recovered")
        ),
        {},
    )
    latest_unrecovered_starved = next(
        (
            row for row in reversed(active_rows)
            if row.get("starved_active_day") and not row.get("preflight_recovery_recovered")
        ),
        {},
    )
    unrecovered_streak = 0
    for row in reversed(active_rows):
        if row.get("starved_active_day") and not row.get("preflight_recovery_recovered"):
            unrecovered_streak += 1
            continue
        break
    status = (
        "MISSING"
        if not rows else
        "CRITICAL"
        if unrecovered_starved_days else
        "RECOVERED"
        if recovered_starved_days else
        "PASS"
        if latest.get("status") == "PASS" else
        latest.get("status") or "WARN"
    )
    critical_alert = {}
    if latest_unrecovered_starved:
        owner_items = ",".join(latest_unrecovered_starved.get("recovery_owner_items") or []) or "161,157"
        command = (
            latest_unrecovered_starved.get("recovery_command")
            or "python -m weather.market.market_microstructure ensure"
        )
        critical_alert = {
            "severity": "critical",
            "category": "mm_evidence_starvation",
            "message": (
                f"MM active-day evidence starvation on {latest_unrecovered_starved.get('target_date')}: "
                f"{latest_unrecovered_starved.get('preflight_blocked_market_count')}/"
                f"{latest_unrecovered_starved.get('preflight_market_count')} markets blocked by stale preflight; "
                f"{latest_unrecovered_starved.get('max_stale_input_gate') or 'stale_input'} age="
                f"{latest_unrecovered_starved.get('max_stale_input_age_seconds')}s; owners={owner_items}; "
                f"recovery_status={latest_unrecovered_starved.get('preflight_recovery_closeout_status')}; "
                f"recovery_command={command}"
            ),
            "detail": latest_unrecovered_starved,
        }
    return {
        "schema_version": "mm_evidence_starvation_v0.1",
        "status": status,
        "blocked_fraction_threshold": float(blocked_fraction_threshold),
        "active_day_count": len(active_rows),
        "starved_active_day_count": starved_days,
        "recovered_starved_active_day_count": recovered_starved_days,
        "recovery_attempted_starved_active_day_count": recovery_attempted_starved_days,
        "unrecovered_starved_active_day_count": unrecovered_starved_days,
        "starved_active_day_streak": streak,
        "unrecovered_starved_active_day_streak": unrecovered_streak,
        "countable_paper_market_day_count": countable_market_days,
        "latest": latest,
        "latest_starved": latest_starved,
        "latest_recovered_starved": latest_recovered_starved,
        "latest_unrecovered_starved": latest_unrecovered_starved,
        "critical_alert": critical_alert,
        "rows": rows,
    }


def summarize_market_making_run(path, payload):
    if not payload:
        return {"exists": False}
    cumulative = payload.get("cumulative") or {}
    live_gate = payload.get("live_forward_gate") or {}
    gate_summary = live_gate.get("summary") or {}
    evidence_mode = payload.get("evidence_mode")
    evidence_mode_reason = (
        payload.get("evidence_mode_reason")
        or gate_summary.get("evidence_mode_reason")
        or ((live_gate.get("evidence_mode_gate") or {}).get("detail"))
    )
    countable_mode = evidence_mode == COUNTABLE_MM_EVIDENCE_MODE
    countable_all_markets = bool(payload.get("counts_toward_live_forward_gate"))
    reason_counts = (
        payload.get("reason_counts")
        or ((payload.get("latest_tick") or {}).get("reason_counts"))
        or {}
    )
    return {
        "exists": True,
        "path": str(path),
        "run_folder": payload.get("run_folder"),
        "run_id": payload.get("run_id"),
        "target_date": payload.get("target_date"),
        "mode": payload.get("mode"),
        "evidence_mode": evidence_mode,
        "evidence_mode_reason": evidence_mode_reason,
        "preflight_status": payload.get("preflight_status"),
        "selected_market_count": len(payload.get("markets") or []),
        "latest_tick_quote_rows": (payload.get("latest_tick") or {}).get("quote_rows"),
        "quote_rows": payload.get("cumulative_quote_permission_rows") or cumulative.get("quote_rows"),
        "paper_posted_lifecycle_legs": (
            payload.get("cumulative_paper_posted_count")
            or cumulative.get("paper_posted_lifecycle_legs")
        ),
        "live_trade_permission_rows": (
            payload.get("cumulative_live_trade_permission_rows")
            or payload.get("live_trade_permission_rows")
            or 0
        ),
        "reason_counts": reason_counts,
        "current_high_trust_no_quote_count": _int_value(
            reason_counts.get("NO_QUOTE_CURRENT_HIGH_TRUST_GATE")
        ),
        "counts_toward_live_forward_gate": countable_all_markets,
        "countable_mode": countable_mode,
        "countability_status": "COUNTABLE" if countable_all_markets else "NON_COUNTABLE",
        "countability_blockers": [] if countable_all_markets else [
            blocker for blocker in [
                None if countable_mode else f"evidence_mode={evidence_mode}",
                None if live_gate.get("status") in {"PASS", None} else f"live_forward_gate={live_gate.get('status')}",
                None if payload.get("preflight_status") in {"PASS", None} else f"preflight={payload.get('preflight_status')}",
            ]
            if blocker
        ],
        "model_review_evidence": _evidence_class(payload, "model_review_evidence"),
        "paper_trading_evidence": _evidence_class(payload, "paper_trading_evidence"),
        "live_trade_permission_evidence": _evidence_class(payload, "live_trade_permission_evidence"),
    }


def _taker_summary_fields(payload, settled_payload=None):
    summary = payload.get("summary") or {}
    pnl = (payload.get("pnl") or {}).get("summary") or {}
    pnl_payload = payload.get("pnl") or {}
    if settled_payload:
        pnl_payload = settled_payload.get("pnl") or pnl_payload
    strategy_comparison = pnl_payload.get("strategy_comparison") or {}
    by_strategy = pnl_payload.get("by_strategy") or []
    countable_candidate = strategy_comparison.get("countable_strategy_quality_candidate") or {}
    tail_quality = pnl_payload.get("tail_fill_quality") or {}
    tail_summary = tail_quality.get("summary") or {}
    strategy_fields = {
        "strategy_count": strategy_comparison.get("strategy_count") or len(by_strategy),
        "best_strategy_id": strategy_comparison.get("best_strategy_id"),
        "best_strategy_net_pnl_usdc": _float_value(strategy_comparison.get("best_strategy_net_pnl_usdc")),
        "best_settlement_scored_strategy_id": strategy_comparison.get("best_settlement_scored_strategy_id"),
        "best_settlement_scored_net_pnl_usdc": _float_value(
            strategy_comparison.get("best_settlement_scored_net_pnl_usdc")
        ),
        "strategy_quality_candidate_id": countable_candidate.get("strategy_id"),
        "strategy_quality_candidate_status": (
            strategy_comparison.get("countable_strategy_quality_candidate_status")
            or "MISSING_SETTLED_SAMPLE"
        ),
        "strategy_quality_candidate_net_pnl_usdc": _float_value(countable_candidate.get("net_pnl_usdc")),
        "strategy_comparison": strategy_comparison,
        "by_strategy": by_strategy,
        "promotion_evidence_basis": strategy_comparison.get("promotion_evidence_basis"),
        "mtm_promotion_allowed": bool(strategy_comparison.get("mtm_promotion_allowed")),
        "tail_fill_quality_status": tail_summary.get("status"),
        "low_price_tail_fill_count": _int_value(tail_summary.get("low_price_tail_fill_count")),
        "low_price_tail_fill_fraction": _float_value(tail_summary.get("low_price_tail_fill_fraction")),
        "tail_fill_alert_count": _int_value(tail_summary.get("alert_count")),
        "tail_fill_alerts": tail_summary.get("alerts") or [],
        "tail_fill_quality": tail_quality,
    }
    if settled_payload:
        settled_summary = settled_payload.get("summary") or {}
        settled_pnl = (settled_payload.get("pnl") or {}).get("summary") or {}
        reconciliation = settled_payload.get("reconciliation") or {}
        next_gate = settled_payload.get("next_run_policy_gate") or {}
        warnings = reconciliation.get("warnings") or []
        settled_count = _int_value(_first_present(
            settled_pnl.get("settled_order_count"),
            settled_summary.get("settled_order_count"),
        ))
        mtm_pnl = _float_value(_first_present(
            settled_pnl.get("mark_to_market_pnl_usdc"),
            settled_summary.get("mark_to_market_pnl_usdc"),
        ))
        pnl_source = settled_summary.get("pnl_source") or reconciliation.get("preferred_pnl_source")
        evidence_status = (
            "SETTLEMENT_SCORED"
            if settled_count > 0 else
            "PROVISIONAL_MTM_ONLY"
            if mtm_pnl != 0.0 or pnl_source == "mark_to_market" else
            "UNSCORED"
        )
        return {
            "filled_orders": _int_value(_first_present(
                settled_pnl.get("filled_order_count"),
                settled_summary.get("filled_order_count"),
            )),
            "budget_spent_usdc": _float_value(_first_present(
                settled_pnl.get("budget_spent_usdc"),
                settled_summary.get("budget_spent_usdc"),
            )),
            "net_pnl_usdc": _float_value(_first_present(
                settled_pnl.get("net_pnl_usdc"),
                settled_summary.get("net_pnl_usdc"),
            )),
            "mark_to_market_pnl_usdc": mtm_pnl,
            "settlement_pnl_usdc": _float_value(_first_present(
                settled_pnl.get("settlement_pnl_usdc"),
                settled_summary.get("settlement_pnl_usdc"),
            )),
            "settled_order_count": settled_count,
            "unsettled_order_count": _int_value(_first_present(
                settled_pnl.get("unsettled_order_count"),
                settled_summary.get("unsettled_order_count"),
            )),
            "reason_counts": settled_pnl.get("reason_counts") or settled_summary.get("reason_counts") or {},
            "current_high_trust_no_trade_count": _int_value(
                (settled_pnl.get("reason_counts") or settled_summary.get("reason_counts") or {}).get(
                    "NO_TRADE_CURRENT_HIGH_TRUST_GATE"
                )
            ),
            "root_cause_class": summary.get("root_cause_class"),
            "first_failing_gate": summary.get("first_failing_gate"),
            "pnl_source": pnl_source,
            "pnl_evidence_status": evidence_status,
            "settlement_finalization_status": "available",
            "settlement_reconciliation_status": reconciliation.get("status"),
            "settlement_reconciliation_warnings": warnings,
            "settled_pnl_path": settled_payload.get("settled_pnl_path"),
            "settled_report_path": settled_payload.get("settled_report_path"),
            "active_strategy_id": next_gate.get("active_strategy_id") or settled_summary.get("active_strategy_id"),
            "active_strategy_lifecycle": (
                next_gate.get("active_strategy_lifecycle")
                or settled_summary.get("active_strategy_lifecycle")
            ),
            "active_strategy_lifecycle_status": (
                next_gate.get("active_strategy_lifecycle_status")
                or settled_summary.get("active_strategy_lifecycle_status")
            ),
            "active_strategy_promotion_eligible": bool(_first_present(
                next_gate.get("promotion_eligible"),
                settled_summary.get("active_strategy_promotion_eligible"),
            )),
            "active_strategy_next_action": (
                next_gate.get("next_action")
                or settled_summary.get("active_strategy_next_action")
            ),
            "active_strategy_complete_label_sample_count": _int_value(_first_present(
                next_gate.get("complete_label_sample_count"),
                settled_summary.get("active_strategy_complete_label_sample_count"),
            )),
            "active_strategy_total_label_sample_count": _int_value(_first_present(
                next_gate.get("total_label_sample_count"),
                settled_summary.get("active_strategy_total_label_sample_count"),
            )),
            "active_strategy_canary_settled_order_count": _int_value(_first_present(
                next_gate.get("canary_settled_order_count"),
                settled_summary.get("active_strategy_canary_settled_order_count"),
            )),
            "active_strategy_canary_min_settled_orders": _int_value(_first_present(
                next_gate.get("canary_min_settled_orders"),
                settled_summary.get("active_strategy_canary_min_settled_orders"),
            )),
            "active_strategy_canary_settled_market_count": _int_value(_first_present(
                next_gate.get("canary_settled_market_count"),
                settled_summary.get("active_strategy_canary_settled_market_count"),
            )),
            "active_strategy_canary_min_settled_markets": _int_value(_first_present(
                next_gate.get("canary_min_settled_markets"),
                settled_summary.get("active_strategy_canary_min_settled_markets"),
            )),
            "active_strategy_canary_tail_fill_fraction": _float_value(_first_present(
                next_gate.get("canary_tail_fill_fraction"),
                settled_summary.get("active_strategy_canary_tail_fill_fraction"),
            )),
            "active_strategy_canary_max_tail_fill_fraction": _float_value(_first_present(
                next_gate.get("canary_max_tail_fill_fraction"),
                settled_summary.get("active_strategy_canary_max_tail_fill_fraction"),
            )),
            "active_strategy_canary_age_days": _int_value(_first_present(
                next_gate.get("canary_age_days"),
                settled_summary.get("active_strategy_canary_age_days"),
            )),
            "reported_net_pnl_usdc": settled_summary.get("reported_net_pnl_usdc"),
            "reported_mark_to_market_pnl_usdc": settled_summary.get("reported_mark_to_market_pnl_usdc"),
            "reported_settled_order_count": settled_summary.get("reported_settled_order_count"),
            "reported_unsettled_order_count": settled_summary.get("reported_unsettled_order_count"),
            **strategy_fields,
        }
    pnl_source = (
        "settlement" if _int_value(pnl.get("settled_order_count")) > 0 else
        "mark_to_market" if _float_value(pnl.get("mark_to_market_pnl_usdc")) != 0.0 else
        "unscored"
    )
    evidence_status = (
        "SETTLEMENT_SCORED"
        if _int_value(pnl.get("settled_order_count")) > 0 else
        "PROVISIONAL_MTM_ONLY"
        if pnl_source == "mark_to_market" else
        "UNSCORED"
    )
    return {
        "filled_orders": _int_value(summary.get("cumulative_filled_orders") or pnl.get("filled_order_count")),
        "budget_spent_usdc": _float_value(summary.get("budget_spent_usdc") or pnl.get("budget_spent_usdc")),
        "net_pnl_usdc": _float_value(summary.get("cumulative_net_pnl_usdc") or pnl.get("net_pnl_usdc")),
        "mark_to_market_pnl_usdc": _float_value(pnl.get("mark_to_market_pnl_usdc")),
        "settlement_pnl_usdc": _float_value(pnl.get("settlement_pnl_usdc")),
        "settled_order_count": _int_value(pnl.get("settled_order_count")),
        "unsettled_order_count": _int_value(pnl.get("unsettled_order_count")),
        "reason_counts": pnl.get("reason_counts") or summary.get("reason_counts") or {},
        "current_high_trust_no_trade_count": _int_value(
            (pnl.get("reason_counts") or summary.get("reason_counts") or {}).get(
                "NO_TRADE_CURRENT_HIGH_TRUST_GATE"
            )
        ),
        "root_cause_class": summary.get("root_cause_class"),
        "first_failing_gate": summary.get("first_failing_gate"),
        "pnl_source": pnl_source,
        "pnl_evidence_status": evidence_status,
        "settlement_finalization_status": "missing",
        "settlement_reconciliation_status": None,
        "settlement_reconciliation_warnings": [],
        "settled_pnl_path": None,
        "settled_report_path": None,
        "active_strategy_id": summary.get("active_strategy_id"),
        "active_strategy_lifecycle": summary.get("active_strategy_lifecycle"),
        "active_strategy_lifecycle_status": summary.get("active_strategy_lifecycle"),
        "active_strategy_promotion_eligible": False,
        "active_strategy_next_action": None,
        "active_strategy_complete_label_sample_count": 0,
        "active_strategy_total_label_sample_count": 0,
        "active_strategy_canary_settled_order_count": 0,
        "active_strategy_canary_min_settled_orders": _int_value(
            (summary.get("active_strategy_canary") or {}).get("min_settled_orders")
        ),
        "active_strategy_canary_settled_market_count": 0,
        "active_strategy_canary_min_settled_markets": 0,
        "active_strategy_canary_tail_fill_fraction": 0.0,
        "active_strategy_canary_max_tail_fill_fraction": 0.0,
        "active_strategy_canary_age_days": _int_value(
            (summary.get("active_strategy_canary") or {}).get("age_days")
        ),
        "reported_net_pnl_usdc": None,
        "reported_mark_to_market_pnl_usdc": None,
        "reported_settled_order_count": None,
        "reported_unsettled_order_count": None,
        **strategy_fields,
    }


def summarize_taker_run(path, payload, rolling_payloads=None, settled_payload=None):
    if not payload:
        return {"exists": False}
    latest = _taker_summary_fields(payload, settled_payload=settled_payload)
    rolling_payloads = rolling_payloads or []
    rolling_fields = [
        _taker_summary_fields(
            item[0],
            settled_payload=item[1] if isinstance(item, tuple) and len(item) > 1 else None,
        )
        if isinstance(item, tuple) else _taker_summary_fields(item)
        for item in rolling_payloads
    ]
    rolling_runs = len(rolling_fields)
    rolling_fills = sum(row["filled_orders"] for row in rolling_fields)
    rolling_net_pnl = sum(row["net_pnl_usdc"] for row in rolling_fields)
    rolling_mtm_pnl = sum(row["mark_to_market_pnl_usdc"] for row in rolling_fields)
    sample_ready = rolling_runs >= TAKER_QUALITY_MIN_ROLLING_RUNS and rolling_fills >= TAKER_QUALITY_MIN_FILLS
    threshold_pass = sample_ready and rolling_net_pnl >= TAKER_QUALITY_MIN_NET_PNL_USDC
    latest_negative = latest["net_pnl_usdc"] < 0
    if threshold_pass:
        quality_status = "PASS"
    elif sample_ready:
        quality_status = "BLOCK"
    elif latest_negative:
        quality_status = "SAMPLE_PENDING_NEGATIVE_LATEST"
    else:
        quality_status = "SAMPLE_PENDING"
    return {
        "exists": True,
        "path": str(path),
        "run_folder": payload.get("run_folder"),
        "run_id": payload.get("run_id"),
        "target_date": payload.get("target_date"),
        "mode": payload.get("mode"),
        **latest,
        "quality_gate": {
            "status": quality_status,
            "sample_ready": sample_ready,
            "rolling_run_count": rolling_runs,
            "rolling_filled_orders": rolling_fills,
            "rolling_net_pnl_usdc": rolling_net_pnl,
            "rolling_mark_to_market_pnl_usdc": rolling_mtm_pnl,
            "min_rolling_runs": TAKER_QUALITY_MIN_ROLLING_RUNS,
            "min_filled_orders": TAKER_QUALITY_MIN_FILLS,
            "min_net_pnl_usdc": TAKER_QUALITY_MIN_NET_PNL_USDC,
            "latest_negative": latest_negative,
            "interpretation": (
                "rolling sample clears taker quality thresholds"
                if threshold_pass else
                "rolling sample is large enough but below taker quality thresholds"
                if sample_ready else
                "latest taker P&L is diagnostic only until the rolling sample is large enough"
            ),
        },
    }


def build_trading_evidence_summary(
    mm_runs_root=DEFAULT_MM_RUNS_ROOT,
    taker_runs_root=DEFAULT_TAKER_RUNS_ROOT,
):
    mm_path, mm_payload = _latest_run_summary(mm_runs_root)
    taker_path, taker_payload = _latest_run_summary(taker_runs_root)
    taker_settled_payload = _settled_taker_payload(taker_path)
    taker_payloads = [
        (payload, _settled_taker_payload(path))
        for path, payload in _all_run_summaries(taker_runs_root)
    ]
    mm_starvation = mm_evidence_starvation_summary(mm_runs_root)
    market_making = summarize_market_making_run(mm_path, mm_payload)
    market_making["evidence_starvation"] = mm_starvation
    latest_starvation = mm_starvation.get("latest") or {}
    market_making["evidence_starvation_status"] = mm_starvation.get("status")
    market_making["starved_active_day_streak"] = mm_starvation.get("starved_active_day_streak")
    market_making["countable_paper_market_day_count"] = mm_starvation.get("countable_paper_market_day_count")
    routed_starvation = mm_starvation.get("latest_starved") or latest_starvation
    market_making["latest_preflight_blocked_market_fraction"] = latest_starvation.get(
        "preflight_blocked_market_fraction"
    )
    market_making["evidence_starvation_recovery_owner_items"] = routed_starvation.get("recovery_owner_items") or []
    return {
        "schema_version": "trading_evidence_summary_v0.1",
        "market_making": market_making,
        "taker": summarize_taker_run(
            taker_path,
            taker_payload,
            taker_payloads,
            settled_payload=taker_settled_payload,
        ),
    }
