"""Taker latest-tick evidence starvation classification helpers."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone


SNAPSHOT_REMEDIATION_COMMAND = "python -m weather.collection.snapshot_tracker --status"
CLOB_REMEDIATION_COMMAND = "python -m weather.market.market_microstructure ensure"

SNAPSHOT_GATE_NAMES = {
    "snapshot_model_rows",
    "source_status_rows",
    "source_status_fresh",
}
CLOB_GATE_NAMES = {
    "clob_books",
    "clob_features",
    "clob_discovery",
}
DEAD_STATES = {"DEAD", "ERRORING", "UNKNOWN", "STALE_CODE"}
BLOCKING_CLASSES = {
    "infra_starved_snapshot",
    "infra_starved_clob",
    "latest_tick_empty",
    "scoring_crash",
}
POLICY_GUARDRAIL_REASONS = {
    "NO_TRADE_EDGE_NOT_PERMISSIONED",
    "NO_TRADE_ADVERSE_SELECTION_EDGE_CAP",
    "NO_TRADE_BAD_TAIL_NO_GO",
    "NO_TRADE_MARKET_CENTERED_WARM_TAIL",
    "NO_TRADE_MARKET_CENTERED_WARM_TAIL_CAP",
    "NO_TRADE_EARLY_HOUR_DAILY_POSITION_LIMIT",
    "NO_TRADE_CORRELATED_REGIME_EXPOSURE_CAP",
    "NO_TRADE_WEAK_SLOT_KILL_SWITCH",
    "NO_TRADE_CURRENT_HIGH_TRUST_GATE",
    "NO_TRADE_CURRENT_HIGH_NOT_TRUSTED",
    "NO_TRADE_STRATEGY_DISABLED",
    "NO_TRADE_DISABLED",
    "NO_TRADE_PAPER_ONLY",
}
RISK_CLEAN_REASONS = {
    "NO_TRADE_EDGE_TOO_SMALL",
    "NO_TRADE_AFTER_COST_EV_TOO_SMALL",
    "NO_TRADE_MARKET_BENCHMARK_NO_TRADE",
    "NO_TRADE_PRICE_OUT_OF_RANGE",
    "NO_TRADE_NO_ASK_SIZE",
    "NO_TRADE_INSUFFICIENT_ASK_DEPTH",
}
SNAPSHOT_INFRA_REASONS = {
    "NO_TRADE_STALE_MODEL",
    "NO_TRADE_SNAPSHOT_CADENCE_DEGRADED",
    "NO_TRADE_STALE_SOURCE_STATUS",
    "NO_TRADE_OBSERVATION_TRIGGER_STALE",
    "NO_TRADE_SOURCE_STALE",
}
CLOB_INFRA_REASONS = {
    "NO_TRADE_STALE_BOOK",
    "NO_TRADE_MISSING_BOOK",
    "NO_TRADE_MISSING_TOKEN",
    "NO_TRADE_MISSING_PREFLIGHT",
    "NO_TRADE_MISSING_ASK",
}


def int_value(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_utc(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _max_iso(values):
    parsed = [_parse_utc(value) for value in values if value not in (None, "")]
    parsed = [value for value in parsed if value is not None]
    if not parsed:
        return None
    return max(parsed).isoformat()


def _dependency_status(failed_count, market_count):
    if market_count <= 0:
        return "UNKNOWN"
    if failed_count >= market_count:
        return "BLOCK"
    if failed_count > 0:
        return "WARN"
    return "PASS"


def first_failing_dependency_for_gate(gate_name):
    if gate_name in SNAPSHOT_GATE_NAMES:
        return "snapshot"
    if gate_name in CLOB_GATE_NAMES:
        return "clob"
    return None


def remediation_command_for_dependency(dependency):
    if dependency == "snapshot":
        return SNAPSHOT_REMEDIATION_COMMAND
    if dependency == "clob":
        return CLOB_REMEDIATION_COMMAND
    return CLOB_REMEDIATION_COMMAND


def reason_count(reason_counts, reason):
    return int_value((reason_counts or {}).get(reason))


def _reason_total(reason_counts, reasons):
    reason_counts = reason_counts or {}
    return sum(int_value(reason_counts.get(reason)) for reason in reasons)


def build_taker_upstream_dependency_status(markets=None, loop_statuses=None):
    markets = list(markets or [])
    loop_statuses = loop_statuses or {}
    market_count = len(markets)
    gate_failure_counts = Counter()
    first_failing_gate = None
    first_failing_dependency = None
    first_failing_detail = None
    status_counts = Counter(str(row.get("status") or "UNKNOWN") for row in markets)
    latest_snapshot_id = None
    latest_snapshot_at = None
    latest_source_status_at = None
    snapshot_failures = 0
    source_status_failures = 0
    clob_failures = 0
    snapshot_rows_total = 0
    book_rows_total = 0
    clob_feature_rows_total = 0

    for market in markets:
        gates = market.get("gates") or []
        failed_names = {
            str(gate.get("name"))
            for gate in gates
            if not gate.get("ok")
        }
        for name in failed_names:
            gate_failure_counts[name] += 1
        first_gate = market.get("first_failing_gate") or {}
        first_name = first_gate.get("name")
        if first_name and first_failing_gate is None:
            first_failing_gate = first_name
            first_failing_dependency = first_failing_dependency_for_gate(first_name)
            first_failing_detail = first_gate.get("detail")
        if failed_names & SNAPSHOT_GATE_NAMES:
            snapshot_failures += 1
        if failed_names & {"source_status_rows", "source_status_fresh"}:
            source_status_failures += 1
        if failed_names & CLOB_GATE_NAMES:
            clob_failures += 1
        snapshot_rows_total += int_value(market.get("snapshot_rows"))
        book_rows_total += int_value(market.get("book_rows"))
        clob_feature_rows_total += int_value(market.get("clob_feature_rows"))

    latest_snapshot_at = _max_iso(row.get("latest_capture_utc") for row in markets)
    if latest_snapshot_at:
        latest_dt = _parse_utc(latest_snapshot_at)
        for market in markets:
            if _parse_utc(market.get("latest_capture_utc")) == latest_dt:
                latest_snapshot_id = market.get("latest_snapshot_id")
                break
    latest_source_status_at = _max_iso(row.get("source_status_latest_utc") for row in markets)

    snapshot_loop = (loop_statuses or {}).get("snapshot_loop") or {}
    clob_loop = (loop_statuses or {}).get("clob_loop") or {}
    snapshot_loop_state = str(snapshot_loop.get("state") or "").upper()
    clob_loop_state = str(clob_loop.get("state") or "").upper()
    if snapshot_loop_state in DEAD_STATES and first_failing_dependency is None:
        first_failing_dependency = "snapshot"
        first_failing_gate = "snapshot_loop"
    if clob_loop_state in DEAD_STATES and first_failing_dependency is None:
        first_failing_dependency = "clob"
        first_failing_gate = "clob_loop"

    snapshot_status = _dependency_status(snapshot_failures, market_count)
    source_status = _dependency_status(source_status_failures, market_count)
    clob_status = _dependency_status(clob_failures, market_count)
    if snapshot_loop_state in DEAD_STATES:
        snapshot_status = "BLOCK"
    if clob_loop_state in DEAD_STATES:
        clob_status = "BLOCK"

    dependency_statuses = {snapshot_status, source_status, clob_status}
    if "BLOCK" in dependency_statuses:
        status = "BLOCK"
    elif "WARN" in dependency_statuses:
        status = "WARN"
    elif market_count <= 0:
        status = "UNKNOWN"
    else:
        status = "PASS"

    return {
        "status": status,
        "market_count": market_count,
        "market_status_counts": dict(sorted(status_counts.items())),
        "gate_failure_counts": dict(sorted(gate_failure_counts.items())),
        "first_failing_gate": first_failing_gate,
        "first_failing_dependency": first_failing_dependency,
        "first_failing_detail": first_failing_detail,
        "remediation_command": remediation_command_for_dependency(first_failing_dependency),
        "latest_snapshot_id": latest_snapshot_id,
        "newest_snapshot_timestamp_utc": latest_snapshot_at,
        "latest_source_status_utc": latest_source_status_at,
        "snapshot_rows": snapshot_rows_total,
        "book_rows": book_rows_total,
        "clob_feature_rows": clob_feature_rows_total,
        "dependencies": {
            "snapshot": {
                "status": snapshot_status,
                "failed_market_count": snapshot_failures,
                "row_count": snapshot_rows_total,
                "loop_state": snapshot_loop.get("state"),
                "heartbeat_age_seconds": snapshot_loop.get("heartbeat_age_seconds")
                or snapshot_loop.get("heartbeat_age_min"),
            },
            "source_status": {
                "status": source_status,
                "failed_market_count": source_status_failures,
                "latest_utc": latest_source_status_at,
            },
            "clob": {
                "status": clob_status,
                "failed_market_count": clob_failures,
                "book_rows": book_rows_total,
                "feature_rows": clob_feature_rows_total,
                "loop_state": clob_loop.get("state"),
                "heartbeat_age_seconds": clob_loop.get("heartbeat_age_seconds"),
            },
        },
    }


def _is_diagnostic(summary, payload=None):
    payload = payload or {}
    text = " ".join(
        str(value or "")
        for value in (
            summary.get("mode"),
            summary.get("experiment_id"),
            payload.get("mode"),
            payload.get("experiment_id"),
            summary.get("run_type"),
        )
    ).lower()
    return bool(summary.get("diagnostic") or payload.get("diagnostic") or "diagnostic" in text)


def _dependency_from_upstream(upstream):
    upstream = upstream or {}
    dependency = upstream.get("first_failing_dependency")
    if dependency:
        return dependency
    dependencies = upstream.get("dependencies") or {}
    for name in ("snapshot", "source_status", "clob"):
        dep = dependencies.get(name) or {}
        if str(dep.get("status") or "").upper() == "BLOCK":
            return "snapshot" if name == "source_status" else name
        if str(dep.get("loop_state") or "").upper() in DEAD_STATES:
            return "snapshot" if name == "source_status" else name
    return None


def classify_taker_evidence_starvation(summary=None, *, markets=None, payload=None, loop_statuses=None):
    summary = summary or {}
    payload = payload or {}
    upstream = (
        summary.get("upstream_dependency_status")
        or payload.get("upstream_dependency_status")
        or build_taker_upstream_dependency_status(markets, loop_statuses=loop_statuses)
    )
    reason_counts = summary.get("reason_counts") or {}
    latest_rows_present = summary.get("latest_tick_rows") not in (None, "")
    latest_rows = int_value(summary.get("latest_tick_rows"))
    latest_fills = int_value(summary.get("latest_tick_filled_orders"))
    cumulative_fills = int_value(summary.get("cumulative_filled_orders"))
    counterfactual_rows = int_value(
        summary.get("latest_tick_counterfactual_rows"),
        int_value(summary.get("cumulative_counterfactual_rows")),
    )
    counterfactual_would_buy = int_value(
        summary.get("latest_tick_counterfactual_would_buy_count"),
        int_value(summary.get("cumulative_counterfactual_would_buy_count")),
    )
    root = summary.get("root_cause_class")
    first_gate = summary.get("first_failing_gate")
    diagnostic = _is_diagnostic(summary, payload)
    dependency = _dependency_from_upstream(upstream)

    snapshot_reason_count = _reason_total(reason_counts, SNAPSHOT_INFRA_REASONS)
    clob_reason_count = _reason_total(reason_counts, CLOB_INFRA_REASONS)
    policy_guardrail_count = _reason_total(reason_counts, POLICY_GUARDRAIL_REASONS)
    risk_clean_count = _reason_total(reason_counts, RISK_CLEAN_REASONS)

    # A first-failing dependency of "clob"/"snapshot" is not on its own evidence
    # of collection infra starvation. The upstream check flags the dependency for
    # *any* failing gate in its family -- including market-availability gates like
    # `clob_discovery` -- so an order book that was read but has no ask-side
    # liquidity (NO_TRADE_NO_ASK_SIZE) or an out-of-range price
    # (NO_TRADE_PRICE_OUT_OF_RANGE) maps the dependency to "clob" even though the
    # CLOB collection loop is healthy and the book data is fresh. Those are
    # RISK_CLEAN reasons: the taker successfully read the book and correctly did
    # not trade. Only treat the dependency as starved when the no-trade evidence
    # actually carries that dependency's infra reasons (stale/missing book or
    # model/source). When the no-trade is clean (risk-clean reasons, no infra
    # reasons for that dependency), fall through to the clean/no-edge
    # classification so a no-liquidity day is countable rather than mislabeled
    # as infra starvation.
    clob_evidence_clean = risk_clean_count > 0 and clob_reason_count == 0
    snapshot_evidence_clean = risk_clean_count > 0 and snapshot_reason_count == 0

    if root == "crashed_before_scoring" or first_gate == "scoring":
        classification = "scoring_crash"
        detail = "run summary reports a scoring failure before latest-tick rows were emitted"
    elif latest_rows_present and latest_rows <= 0:
        classification = "latest_tick_empty"
        detail = "latest-tick scoring emitted zero rows"
    elif dependency == "clob" and latest_fills <= 0 and not clob_evidence_clean:
        classification = "infra_starved_clob"
        detail = "CLOB dependency is blocking or dead for the latest taker run"
    elif dependency == "snapshot" and latest_fills <= 0 and not snapshot_evidence_clean:
        classification = "infra_starved_snapshot"
        detail = "snapshot/source-status dependency is blocking or dead for the latest taker run"
    elif root in {"blocked_by_clob_books", "stale_book_input"} or clob_reason_count:
        classification = "infra_starved_clob"
        detail = "no-trade evidence is dominated by stale or missing CLOB book input"
    elif root in {"stale_model_input"} or snapshot_reason_count:
        classification = "infra_starved_snapshot"
        detail = "no-trade evidence is dominated by stale model/snapshot input"
    elif cumulative_fills > 0 or latest_fills > 0:
        classification = "filled"
        detail = "taker run emitted filled orders"
    elif policy_guardrail_count:
        classification = "policy_guardrail_no_trade"
        detail = "zero-trade result was caused by explicit policy guardrails"
    elif risk_clean_count or root == "policy_no_edge":
        classification = "risk_clean_no_edge"
        detail = "zero-trade result was caused by no-edge/risk-clean policy rejection"
    else:
        classification = "market_unresolved_pending"
        detail = "zero-trade result lacks enough settled or policy detail to count as clean evidence"

    blocking = classification in BLOCKING_CLASSES and not diagnostic
    remediation = remediation_command_for_dependency(
        "clob" if classification in {"infra_starved_clob", "latest_tick_empty", "scoring_crash"} else
        "snapshot" if classification == "infra_starved_snapshot" else
        dependency
    )
    counterfactual_countability = "NON_COUNTABLE" if blocking else "COUNTABLE"
    zero_would_buy_classification = (
        classification
        if counterfactual_rows > 0 and counterfactual_would_buy <= 0 else
        "would_buy_present"
        if counterfactual_would_buy > 0 else
        None
    )
    blockers = []
    if blocking:
        blockers.append(f"taker_day_classification={classification}")
        if latest_rows_present and latest_rows <= 0:
            blockers.append("latest_tick_rows=0")
        if upstream.get("first_failing_dependency"):
            blockers.append(f"upstream_dependency={upstream.get('first_failing_dependency')}")

    return {
        "status": "DIAGNOSTIC" if diagnostic else ("BLOCK" if blocking else "PASS"),
        "classification": classification,
        "taker_day_classification": classification,
        "zero_would_buy_classification": zero_would_buy_classification,
        "latest_tick_rows": latest_rows,
        "latest_tick_filled_orders": latest_fills,
        "latest_tick_counterfactual_rows": counterfactual_rows,
        "latest_tick_counterfactual_would_buy_count": counterfactual_would_buy,
        "countability_status": counterfactual_countability,
        "blocks_taker_evidence_countability": bool(blocking),
        "countability_blockers": blockers,
        "restart_recommended": bool(blocking),
        "root_cause_class": root,
        "first_failing_gate": first_gate,
        "first_failing_dependency": upstream.get("first_failing_dependency"),
        "detail": detail,
        "remediation_command": remediation,
        "upstream_dependency_status": upstream,
        "diagnostic": diagnostic,
    }
