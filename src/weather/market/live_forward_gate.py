"""Live-forward countability reconciliation for market-making runs."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from weather.market.market_making_preflight import REMEDIATION_RULES
from weather.market.mm_policy import bool_value, maybe_float, parse_time


SCHEMA_VERSION = "live_forward_gate_v0.2"
MODEL_REVIEW_REQUIRED_GATES = (
    "active_event",
    "snapshot_model_rows",
    "model_freshness",
    "source_status_rows",
)


def utc_now(value=None):
    parsed = parse_time(value)
    return parsed or datetime.now(timezone.utc)


def _iso(value):
    parsed = parse_time(value)
    return parsed.isoformat() if parsed else None


def _age_seconds(last_good, now):
    parsed = parse_time(last_good)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def _threshold_seconds(gate_name, policy_config):
    policy_config = policy_config or {}
    if gate_name == "model_freshness":
        return maybe_float(policy_config.get("max_model_age_seconds"))
    if gate_name in {"clob_freshness", "clob_books", "clob_features", "reward_metadata"}:
        return maybe_float(policy_config.get("max_book_age_seconds"))
    if gate_name == "observation_trigger":
        return maybe_float(policy_config.get("max_watcher_age_seconds"))
    return None


def _last_good_timestamp(gate_name, market, preflight):
    if gate_name in {"active_event", "snapshot_model_rows", "model_freshness"}:
        return market.get("latest_capture_utc")
    if gate_name in {"source_status_rows", "source_status_fresh"}:
        return market.get("source_status_latest_utc") or market.get("latest_capture_utc")
    if gate_name in {"clob_tokens", "clob_books", "clob_features", "clob_freshness", "reward_metadata"}:
        return ((market.get("book_audit") or {}).get("last_capture_utc"))
    if gate_name == "observation_trigger":
        return (preflight.get("observation_status") or {}).get("last_heartbeat")
    return None


def _gate_age(gate_name, market, preflight, now):
    if gate_name == "model_freshness":
        return maybe_float(market.get("model_age_seconds"))
    if gate_name in {"clob_freshness", "clob_books", "clob_features", "reward_metadata"}:
        return maybe_float((market.get("book_audit") or {}).get("trailing_age_seconds"))
    if gate_name == "observation_trigger":
        observation = preflight.get("observation_status") or {}
        return maybe_float(observation.get("watcher_age_seconds"))
    return _age_seconds(_last_good_timestamp(gate_name, market, preflight), now)


def _rule(gate_name):
    return REMEDIATION_RULES.get(gate_name) or {
        "root_cause": gate_name or "unknown_preflight_failure",
        "owner": "unknown",
        "suggested_command": "inspect preflight.json",
    }


def enriched_gate(gate, market, preflight, policy_config, now):
    gate_name = gate.get("name")
    rule = _rule(gate_name)
    last_good = _last_good_timestamp(gate_name, market, preflight)
    threshold = _threshold_seconds(gate_name, policy_config)
    return {
        "name": gate_name,
        "ok": bool(gate.get("ok")),
        "severity": gate.get("severity"),
        "detail": gate.get("detail"),
        "owner": rule.get("owner"),
        "root_cause": rule.get("root_cause"),
        "suggested_command": rule.get("suggested_command"),
        "last_good_timestamp": _iso(last_good),
        "current_timestamp": now.isoformat(),
        "age_seconds": _gate_age(gate_name, market, preflight, now),
        "stale_threshold_seconds": threshold,
    }


def first_failing_gate(gates):
    for gate in gates:
        if not gate.get("ok"):
            return gate
    return None


def gate_ok(gates_by_name, name):
    gate = gates_by_name.get(name)
    return bool(gate and gate.get("ok"))


def countability_for_market(market, gates):
    gates_by_name = {gate.get("name"): gate for gate in gates}
    model_blockers = [
        name for name in MODEL_REVIEW_REQUIRED_GATES
        if not gate_ok(gates_by_name, name)
    ]
    paper_blockers = [
        gate.get("name") for gate in gates
        if not gate.get("ok")
    ]
    live_gate = market.get("live_gate") or {}
    mode = market.get("mode")
    live_blockers = list(paper_blockers)
    if mode != "live-pilot":
        live_blockers.append("mode_not_live_pilot")
    elif not bool_value(live_gate.get("ok"), False):
        live_blockers.append("live_account_gate")
    return {
        "model_review_evidence": {
            "counts": not model_blockers,
            "blocking_gates": model_blockers,
        },
        "paper_trading_evidence": {
            "counts": not paper_blockers,
            "blocking_gates": paper_blockers,
        },
        "live_trade_permission_evidence": {
            "counts": not live_blockers,
            "blocking_gates": live_blockers,
        },
    }


def market_gate_row(market, preflight, policy_config, now):
    market_with_mode = {**market, "mode": preflight.get("mode")}
    gates = [
        enriched_gate(gate, market_with_mode, preflight, policy_config, now)
        for gate in market.get("gates") or []
    ]
    first_failure = first_failing_gate(gates)
    countability = countability_for_market(market_with_mode, gates)
    stale_recovery = None
    if first_failure:
        stale_recovery = {
            "status": "queued_before_next_tick",
            "market_id": market.get("market_id"),
            "gate": first_failure.get("name"),
            "owner": first_failure.get("owner"),
            "root_cause": first_failure.get("root_cause"),
            "suggested_command": first_failure.get("suggested_command"),
            "last_good_timestamp": first_failure.get("last_good_timestamp"),
            "age_seconds": first_failure.get("age_seconds"),
            "stale_threshold_seconds": first_failure.get("stale_threshold_seconds"),
        }
    return {
        "market_id": market.get("market_id"),
        "city": market.get("city"),
        "event_slug": market.get("event_slug"),
        "target_date": market.get("target_date"),
        "preflight_status": market.get("status"),
        "first_failing_gate": first_failure,
        "current_owner": first_failure.get("owner") if first_failure else None,
        "stale_recovery": stale_recovery,
        "countability": countability,
        "counts_toward_live_forward_gate": countability["paper_trading_evidence"]["counts"],
        "gates": gates,
    }


def evidence_summary(markets, evidence_key):
    countable = [row for row in markets if ((row.get("countability") or {}).get(evidence_key) or {}).get("counts")]
    return {
        "market_count": len(markets),
        "countable_market_count": len(countable),
        "blocked_market_count": len(markets) - len(countable),
        "all_selected_markets_count": len(countable) == len(markets) and bool(markets),
    }


def build_live_forward_gate(preflight, policy_config=None, now=None):
    now = utc_now(now or (preflight or {}).get("generated_at_utc"))
    useful_work_liveness = (preflight or {}).get("useful_work_liveness") or {}
    markets = [
        market_gate_row(market, preflight or {}, policy_config or {}, now)
        for market in (preflight or {}).get("markets") or []
    ]
    first_failures = [
        row.get("first_failing_gate") for row in markets
        if row.get("first_failing_gate")
    ]
    first_failure_counts = Counter(row.get("name") for row in first_failures)
    evidence = {
        "model_review_evidence": evidence_summary(markets, "model_review_evidence"),
        "paper_trading_evidence": evidence_summary(markets, "paper_trading_evidence"),
        "live_trade_permission_evidence": evidence_summary(markets, "live_trade_permission_evidence"),
    }
    run_level_ok = (
        not useful_work_liveness.get("enforced")
        or bool(useful_work_liveness.get("ok"))
    )
    counts_toward_live_forward_gate = (
        evidence["paper_trading_evidence"]["all_selected_markets_count"]
        and run_level_ok
    )
    run_level_failures = {}
    if not run_level_ok:
        run_level_failures["useful_work_liveness"] = int(useful_work_liveness.get("blocker_count") or 1)
        first_failure_counts["useful_work_liveness"] = (
            first_failure_counts.get("useful_work_liveness", 0) + 1
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": (preflight or {}).get("run_id"),
        "target_date": (preflight or {}).get("target_date"),
        "mode": (preflight or {}).get("mode"),
        "status": "PASS" if counts_toward_live_forward_gate else "BLOCK",
        "counts_toward_live_forward_gate": counts_toward_live_forward_gate,
        "evidence": evidence,
        "useful_work_liveness": useful_work_liveness,
        "summary": {
            "market_count": len(markets),
            "first_failing_gate_counts": dict(sorted(first_failure_counts.items())),
            "blocked_market_count": sum(1 for row in markets if row.get("first_failing_gate")),
            "run_level_ok": run_level_ok,
            "run_level_failure_counts": dict(sorted(run_level_failures.items())),
        },
        "markets": markets,
    }
