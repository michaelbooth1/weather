"""Read-only helpers for retained taker and paper-maker evidence.

The taker bot and the paper market maker were retired on 2026-09-29 (owner
decision 3 of the 2026-09-26 repo-health audit) and their runtime code was
deleted.  Their run folders under ``mm_runs``/``taker_runs`` and the last
``mm_paper_report.json`` remain retained evidence.  This module only *reads*
that evidence for ``weather.reporting.market.trading_evidence``: the functions
below are verbatim copies of the former owners
(``weather.market.taker_evidence_starvation``,
``weather.market.taker_profitability_artifact_verification``,
``weather.market.taker_bot_artifact_projection`` and
``weather.market.mm_paper_scoring``), so the trading-evidence payload is
unchanged.  Nothing here writes, finalizes, scores or quotes; do not add
producers here.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from weather.io import (
    iter_csv_rows,
    read_json,
    read_pretty_json_top_level_values,
)
from weather.market.value_helpers import bool_value
from weather.paths import data_path
from weather.schema_registry import schema_version


DEFAULT_MM_RUNS_ROOT = data_path() / "mm_runs"
DEFAULT_MM_PAPER_JSON = data_path() / "backtest" / "mm_paper_report.json"


# --- Taker latest-tick evidence starvation (from taker_evidence_starvation) ---


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
    last_nonzero_scored_tick = summary.get("last_nonzero_scored_tick") or {}
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
    restart_recommended = (
        classification == "scoring_crash"
        and not diagnostic
    )
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
        "last_nonzero_scored_tick": last_nonzero_scored_tick,
        "countability_status": counterfactual_countability,
        "blocks_taker_evidence_countability": bool(blocking),
        "countability_blockers": blockers,
        "restart_recommended": bool(restart_recommended),
        "root_cause_class": root,
        "first_failing_gate": first_gate,
        "first_failing_dependency": upstream.get("first_failing_dependency"),
        "detail": detail,
        "remediation_command": remediation,
        "upstream_dependency_status": upstream,
        "diagnostic": diagnostic,
    }


# --- Settled finalization projection reader (from taker_bot_artifact_projection) ---


DEFAULT_PROJECTION_MAX_BYTES = 16 * 1024 * 1024


SETTLED_FINALIZATION_PROJECTION_FILENAME = "settled_finalization_projection.json"


SETTLED_FINALIZATION_PROJECTION_SCHEMA_VERSION = (
    schema_version("taker_settled_finalization_projection")
)


def settled_finalization_projection_path(settled_path: str | Path) -> Path:
    return Path(settled_path).with_name(SETTLED_FINALIZATION_PROJECTION_FILENAME)


def load_settled_finalization_projection(
    settled_path: str | Path,
    *,
    max_projection_bytes: int = DEFAULT_PROJECTION_MAX_BYTES,
) -> dict[str, Any] | None:
    """Load a small finalization projection bound by source size and mtime."""

    source_path = Path(settled_path)
    projection_path = settled_finalization_projection_path(source_path)
    try:
        before = projection_path.stat()
    except OSError:
        return None
    if before.st_size > max_projection_bytes:
        return None
    projection = read_json(projection_path, None)
    try:
        after = projection_path.stat()
    except OSError:
        return None
    if not _same_file_version(before, after) or not isinstance(projection, dict):
        return None
    if (
        projection.get("projection_schema_version")
        != SETTLED_FINALIZATION_PROJECTION_SCHEMA_VERSION
    ):
        return None
    binding = projection.get("source_artifact_binding") or {}
    try:
        source_stat = source_path.stat()
    except OSError:
        return None
    if not (
        binding.get("filename") == source_path.name
        and type(binding.get("size_bytes")) is int
        and binding.get("size_bytes") == source_stat.st_size
        and type(binding.get("mtime_ns")) is int
        and binding.get("mtime_ns") == source_stat.st_mtime_ns
        and isinstance(projection.get("summary"), dict)
        and isinstance(projection.get("strategies"), list)
        and all(isinstance(row, dict) for row in projection.get("strategies"))
        and isinstance(projection.get("exchange_economics_gate"), dict)
    ):
        return None
    return projection


def _same_file_version(left, right) -> bool:
    return bool(
        left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
    )


# --- Taker profitability artifact verification (from taker_profitability_artifact_verification) ---


TAKER_PROFITABILITY_VERIFICATION_SCHEMA_VERSION = schema_version("taker_profitability_artifact_verification")


ORDER_OPPORTUNITY_FIELDS = (
    "fee_usdc",
    "pnl_fee_basis",
    "executable_depth_model_version",
    "executable_depth_mode",
    "executable_depth_size",
    "expected_profit_after_friction_per_share",
)


FILLED_ORDER_FIELDS = (
    "fee_pnl_usdc",
    "slippage_usdc",
    "executable_net_pnl_usdc",
)


STRATEGY_FIELDS = (
    "after_fee_pnl_scored",
    "after_slippage_pnl_scored",
    "live_profitability_evidence_basis",
    "market_benchmark_status",
    "market_smarter_slice_count",
    "market_benchmark_no_trade_net_pnl_usdc",
    "market_benchmark_avoided_loss_usdc",
    "market_benchmark_missed_gain_usdc",
)


BENCHMARK_FIELDS = (
    "market_smarter_slice_count",
    "no_trade_recommendation_count",
    "avoided_loss_usdc",
    "missed_gain_usdc",
)


EXCHANGE_ECONOMICS_FIELDS = (
    "exchange_economics_snapshot_id",
    "exchange_economics_hash",
    "exchange_economics_evidence_basis",
)


def _read_small_json(path):
    path = Path(path)
    try:
        if path.stat().st_size > DEFAULT_PROJECTION_MAX_BYTES:
            return {}
    except OSError:
        return {}
    return read_json(path, {}) or {}


def _small_enough_to_materialize(path):
    try:
        return Path(path).stat().st_size <= DEFAULT_PROJECTION_MAX_BYTES
    except OSError:
        return False


def _current_strategy_summary_for_large_daily(
    strategy_summary_path,
    daily_pnl_path,
):
    """Return a compact summary only when it is newer and identity-aligned."""

    if not _small_enough_to_materialize(strategy_summary_path):
        return {}
    summary = _read_small_json(strategy_summary_path)
    try:
        summary_stat = Path(strategy_summary_path).stat()
        daily_stat = Path(daily_pnl_path).stat()
    except OSError:
        return {}
    if summary_stat.st_mtime_ns < daily_stat.st_mtime_ns:
        return {}
    daily_identity = read_pretty_json_top_level_values(
        daily_pnl_path,
        ("run_id", "target_date"),
    )
    if not all(
        summary.get(field) not in (None, "")
        and str(summary.get(field)) == str(daily_identity.get(field))
        for field in ("run_id", "target_date")
    ):
        return {}
    if summary.get("schema_version") != schema_version("taker_strategy_report"):
        return {}
    return summary


def _present(value) -> bool:
    return value is not None and str(value).strip() != ""


def _check(code, status, detail, **extra):
    row = {"code": code, "status": status, "detail": detail}
    row.update(extra)
    return row


class _FieldPresence:
    """Fixed field-presence state for a streamed row population."""

    def __init__(self, fields):
        self.fields = tuple(fields)
        self.row_count = 0
        self.key_seen = {field: False for field in self.fields}
        self.value_seen = {field: False for field in self.fields}

    def add(self, row):
        self.row_count += 1
        for field in self.fields:
            if field in row:
                self.key_seen[field] = True
                if _present(row.get(field)):
                    self.value_seen[field] = True


def _field_checks_from_presence(presence, *, scope):
    if not presence.row_count:
        return [_check(f"{scope}_rows_missing", "FAIL", f"No rows available for {scope}.")]
    checks = []
    for field in presence.fields:
        if not presence.key_seen[field]:
            checks.append(_check(
                f"{scope}_{field}_missing",
                "FAIL",
                f"{scope} field {field!r} is absent.",
                field=field,
            ))
            continue
        if not presence.value_seen[field]:
            checks.append(_check(
                f"{scope}_{field}_null_only",
                "FAIL",
                f"{scope} field {field!r} is present but null-only.",
                field=field,
            ))
    return checks


def _field_checks(rows, fields, *, scope):
    presence = _FieldPresence(fields)
    for row in rows or []:
        presence.add(row)
    return _field_checks_from_presence(presence, scope=scope)


def _streamed_order_presence(path):
    fields = tuple(dict.fromkeys(
        ORDER_OPPORTUNITY_FIELDS + FILLED_ORDER_FIELDS + EXCHANGE_ECONOMICS_FIELDS
    ))
    all_orders = _FieldPresence(fields)
    filled_orders = _FieldPresence(fields)
    for row in iter_csv_rows(path):
        all_orders.add(row)
        if str(row.get("order_status") or "").upper() == "FILLED":
            filled_orders.add(row)
    return all_orders, filled_orders


def _presence_subset(presence, fields):
    subset = _FieldPresence(fields)
    subset.row_count = presence.row_count
    for field in subset.fields:
        subset.key_seen[field] = presence.key_seen.get(field, False)
        subset.value_seen[field] = presence.value_seen.get(field, False)
    return subset


def _bool_value(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _int_value(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _rows_with_fills(rows):
    return [
        row
        for row in rows or []
        if _int_value(row.get("filled_order_count") or row.get("order_rows")) > 0
    ]


def _bool_field_passes(rows, field):
    rows = list(rows or [])
    if not rows:
        return True
    return all(_bool_value(row.get(field)) for row in rows)


def _basis_is_after_fee(value):
    return str(value or "").strip().lower() in {
        "after_fee",
        "fees_included",
        "net_after_fee",
        "executable_after_fee_after_slippage",
    }


def _strategy_rows(payload):
    if not payload:
        return []
    return list(
        payload.get("by_strategy")
        or (payload.get("pnl") or {}).get("by_strategy")
        or payload.get("strategies")
        or []
    )


def _strategy_comparison(payload):
    payload = payload or {}
    return (
        payload.get("strategy_comparison")
        or (payload.get("pnl") or {}).get("strategy_comparison")
        or payload.get("comparison")
        or {}
    )


def _settled_summary_from_strategy_payload(payload):
    """Recover finalization-wide checks from the compact settled strategy artifact."""

    payload = payload or {}
    summary = dict(payload.get("summary") or {})
    strategy_rows = _strategy_rows(payload)
    filled_rows = [
        row for row in strategy_rows
        if _int_value(row.get("filled_order_count")) > 0
    ]
    after_fee = bool(filled_rows) and _bool_field_passes(
        filled_rows,
        "after_fee_pnl_scored",
    )
    after_slippage = bool(filled_rows) and _bool_field_passes(
        filled_rows,
        "after_slippage_pnl_scored",
    )
    summary.setdefault("filled_order_count", sum(
        _int_value(row.get("filled_order_count")) for row in strategy_rows
    ))
    summary.setdefault("after_fee_pnl_scored", after_fee)
    summary.setdefault("after_slippage_pnl_scored", after_slippage)
    summary.setdefault(
        "live_profitability_evidence_basis",
        "executable_after_fee_after_slippage" if after_fee else "paper_no_fee",
    )
    gate = payload.get("exchange_economics_gate") or {}
    exchange_values = {
        "exchange_economics_snapshot_id": gate.get("snapshot_id"),
        "exchange_economics_hash": (
            gate.get("snapshot_hash") or gate.get("exchange_economics_hash")
        ),
        "exchange_economics_evidence_basis": gate.get("evidence_basis"),
    }
    for field in EXCHANGE_ECONOMICS_FIELDS:
        summary.setdefault(field, payload.get(field) or exchange_values.get(field))
    return summary


def _exchange_gate_from_payloads(*payloads):
    for payload in payloads:
        payload = payload or {}
        gate = payload.get("exchange_economics_gate")
        if gate:
            return gate
        summary = payload.get("summary") or {}
        snapshot_id = (
            payload.get("exchange_economics_snapshot_id")
            or summary.get("exchange_economics_snapshot_id")
        )
        economics_hash = (
            payload.get("exchange_economics_hash")
            or summary.get("exchange_economics_hash")
        )
        status = (
            payload.get("exchange_economics_status")
            or summary.get("exchange_economics_gate_status")
        )
        if snapshot_id or economics_hash or status:
            return {
                "status": status or "PASS",
                "ok": status in {None, "", "PASS"},
                "snapshot_id": snapshot_id,
                "snapshot_hash": economics_hash,
                "reason": summary.get("exchange_economics_gate_reason"),
            }
    return {}


def verify_taker_profitability_artifacts(run_folder, exchange_economics_gate=None):
    run_folder = Path(run_folder)
    orders_path = run_folder / "orders_long.csv"
    run_config_path = run_folder / "run_config.json"
    daily_pnl_path = run_folder / "daily_pnl.json"
    strategy_summary_path = run_folder / "strategy_summary.json"
    settled_pnl_path = run_folder / "settled_pnl.json"
    if not any(path.exists() for path in (
        orders_path,
        daily_pnl_path,
        strategy_summary_path,
        settled_pnl_path,
    )):
        return {
            "schema_version": TAKER_PROFITABILITY_VERIFICATION_SCHEMA_VERSION,
            "run_folder": str(run_folder),
            "status": "SKIP",
            "check_count": 1,
            "failed_check_count": 0,
            "checks": [
                _check(
                    "taker_profitability_artifacts_absent",
                    "SKIP",
                    "No taker profitability artifacts are present in this run folder.",
                )
            ],
        }
    run_config = _read_small_json(run_config_path)
    daily_payload = {}
    strategy_summary_payload = {}
    if daily_pnl_path.exists() and _small_enough_to_materialize(daily_pnl_path):
        daily_payload = _read_small_json(daily_pnl_path)
        strategy_summary_payload = _read_small_json(strategy_summary_path)
    elif daily_pnl_path.exists():
        strategy_summary_payload = _current_strategy_summary_for_large_daily(
            strategy_summary_path,
            daily_pnl_path,
        )
    else:
        strategy_summary_payload = _read_small_json(strategy_summary_path)
    settled_payload = (
        load_settled_finalization_projection(settled_pnl_path)
        if settled_pnl_path.exists()
        else None
    )
    if settled_payload is not None:
        settled_summary = _settled_summary_from_strategy_payload(settled_payload)
    else:
        settled_payload = _read_small_json(settled_pnl_path)
        settled_summary = (
            (settled_payload.get("pnl") or {}).get("summary")
            or settled_payload.get("summary")
            or {}
        )
    strategy_rows = _strategy_rows(daily_payload) or _strategy_rows(
        strategy_summary_payload
    )
    comparison = _strategy_comparison(daily_payload) or _strategy_comparison(
        strategy_summary_payload
    )
    benchmark_summary = comparison.get("market_benchmark_summary") or {}

    checks = []
    exchange_gate = exchange_economics_gate or _exchange_gate_from_payloads(
        run_config,
        daily_payload,
        strategy_summary_payload,
        settled_payload,
    )
    gate_status = str(exchange_gate.get("status") or "").upper()
    exchange_required = exchange_gate.get("required") is not False
    if not exchange_gate:
        checks.append(_check(
            "exchange_economics_gate_missing",
            "FAIL",
            "Taker profitability artifacts do not cite an exchange-economics gate.",
        ))
    elif not exchange_required:
        checks.append(_check(
            "exchange_economics_gate_not_required",
            "SKIP",
            "Exchange-economics gate was not required for this non-production artifact root.",
        ))
    elif gate_status == "BLOCK" or exchange_gate.get("ok") is False:
        checks.append(_check(
            "exchange_economics_gate_blocked",
            "FAIL",
            exchange_gate.get("reason") or "Exchange-economics gate is not current.",
            exchange_economics_snapshot_id=exchange_gate.get("snapshot_id"),
            exchange_economics_hash=exchange_gate.get("snapshot_hash"),
        ))
    elif not (exchange_gate.get("snapshot_id") and (exchange_gate.get("snapshot_hash") or exchange_gate.get("exchange_economics_hash"))):
        checks.append(_check(
            "exchange_economics_snapshot_identity_missing",
            "FAIL",
            "Exchange-economics gate does not include snapshot id and hash.",
        ))
    if not orders_path.exists():
        checks.append(_check("orders_tape_missing", "FAIL", f"Missing orders tape: {orders_path}"))
    else:
        all_orders, filled_orders = _streamed_order_presence(orders_path)
        order_scope = filled_orders if filled_orders.row_count else all_orders
        checks.extend(_field_checks_from_presence(
            _presence_subset(order_scope, ORDER_OPPORTUNITY_FIELDS),
            scope="orders",
        ))
        if exchange_required:
            checks.extend(_field_checks_from_presence(
                _presence_subset(order_scope, EXCHANGE_ECONOMICS_FIELDS),
                scope="orders_exchange_economics",
            ))
        if filled_orders.row_count:
            checks.extend(_field_checks_from_presence(
                _presence_subset(filled_orders, FILLED_ORDER_FIELDS),
                scope="orders",
            ))
        else:
            checks.append(_check(
                "orders_realized_profitability_fields_skipped_no_fills",
                "SKIP",
                "No filled orders are present; realized fee/slippage/net-P&L fields are not required.",
            ))
    if not daily_pnl_path.exists() and not strategy_summary_path.exists():
        checks.append(_check(
            "strategy_summary_missing",
            "FAIL",
            "Missing daily_pnl.json and strategy_summary.json for taker run.",
        ))
    else:
        checks.extend(_field_checks(strategy_rows, STRATEGY_FIELDS, scope="strategy"))
        if exchange_required:
            checks.extend(_field_checks(strategy_rows, EXCHANGE_ECONOMICS_FIELDS, scope="strategy_exchange_economics"))
        checks.extend(_field_checks([benchmark_summary], BENCHMARK_FIELDS, scope="market_benchmark"))

    if settled_pnl_path.exists():
        settled_strategy_rows = _strategy_rows(settled_payload)
        checks.extend(_field_checks([settled_summary], ("live_profitability_evidence_basis",), scope="finalization"))
        if exchange_required:
            checks.extend(_field_checks([settled_summary], EXCHANGE_ECONOMICS_FIELDS, scope="finalization_exchange_economics"))
        if not _basis_is_after_fee(settled_summary.get("live_profitability_evidence_basis")):
            checks.append(_check(
                "finalization_live_profitability_basis_not_after_fee_slippage",
                "FAIL",
                "Finalization live_profitability_evidence_basis is not executable after-fee/after-slippage.",
                value=settled_summary.get("live_profitability_evidence_basis"),
            ))
        if not _bool_field_passes([settled_summary], "after_fee_pnl_scored"):
            checks.append(_check(
                "finalization_after_fee_pnl_not_scored",
                "FAIL",
                "Finalization summary does not mark after-fee PnL as scored.",
            ))
        if not _bool_field_passes([settled_summary], "after_slippage_pnl_scored"):
            checks.append(_check(
                "finalization_after_slippage_pnl_not_scored",
                "FAIL",
                "Finalization summary does not mark after-slippage PnL as scored.",
            ))
        settled_strategy_rows = _rows_with_fills(settled_strategy_rows)
        if not _bool_field_passes(settled_strategy_rows, "after_fee_pnl_scored"):
            checks.append(_check(
                "finalization_strategy_after_fee_pnl_not_scored",
                "FAIL",
                "At least one finalization strategy row lacks after-fee scoring.",
            ))
        if not _bool_field_passes(settled_strategy_rows, "after_slippage_pnl_scored"):
            checks.append(_check(
                "finalization_strategy_after_slippage_pnl_not_scored",
                "FAIL",
                "At least one finalization strategy row lacks after-slippage scoring.",
            ))
    else:
        checks.append(_check(
            "finalization_payload_absent",
            "SKIP",
            "No settled_pnl.json is present; finalization-specific checks were skipped.",
        ))

    failed = [row for row in checks if row.get("status") == "FAIL"]
    return {
        "schema_version": TAKER_PROFITABILITY_VERIFICATION_SCHEMA_VERSION,
        "run_folder": str(run_folder),
        "orders_path": str(orders_path),
        "run_config_path": str(run_config_path),
        "daily_pnl_path": str(daily_pnl_path),
        "strategy_summary_path": str(strategy_summary_path),
        "settled_pnl_path": str(settled_pnl_path),
        "status": "BLOCK" if failed else "PASS",
        "exchange_economics_gate": exchange_gate,
        "check_count": len(checks),
        "failed_check_count": len(failed),
        "checks": checks,
    }


# --- Maker paper-score freshness (from mm_paper_scoring) ---


ACTIVE_DAY_EVIDENCE_MODE = "active_day_live_forward"


def _read_maker_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def discover_run_folders(runs_root=DEFAULT_MM_RUNS_ROOT, run_folders=None):
    if run_folders:
        return [Path(item) for item in run_folders]
    root = Path(runs_root)
    if not root.exists():
        return []
    return sorted(
        [folder for folder in root.glob("*/*") if folder.is_dir() and (folder / "quote_intents_long.csv").exists()],
        key=lambda path: str(path),
    )


def _path_mtime_iso(path):
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return ""


def _run_folder_freshness_row(folder):
    folder = Path(folder)
    summary_path = folder / "run_summary.json"
    summary = _read_maker_json(summary_path, {}) or {}
    run_config = _read_maker_json(folder / "run_config.json", {}) or {}
    live_gate = summary.get("live_forward_gate") or {}
    evidence_mode = summary.get("evidence_mode") or live_gate.get("evidence_mode")
    target_date = summary.get("target_date") or run_config.get("target_date") or folder.parent.name
    run_id = summary.get("run_id") or run_config.get("run_id") or folder.name
    completed = summary_path.exists() and (folder / "quote_intents_long.csv").exists()
    return {
        "run_folder": str(folder),
        "run_id": run_id,
        "target_date": target_date,
        "mode": summary.get("mode") or run_config.get("mode"),
        "evidence_mode": evidence_mode,
        "completed": completed,
        "active_day": evidence_mode == ACTIVE_DAY_EVIDENCE_MODE,
        "counts_toward_live_forward_gate": bool_value(
            summary.get("counts_toward_live_forward_gate")
            if summary.get("counts_toward_live_forward_gate") is not None
            else live_gate.get("counts_toward_live_forward_gate"),
            False,
        ),
        "generated_at_utc": summary.get("generated_at_utc") or summary.get("started_at_utc") or "",
        "run_summary_mtime_utc": _path_mtime_iso(summary_path),
    }


def _run_freshness_sort_key(row):
    return (
        str(row.get("target_date") or ""),
        str(row.get("generated_at_utc") or ""),
        str(row.get("run_summary_mtime_utc") or ""),
        str(row.get("run_id") or ""),
        str(row.get("run_folder") or ""),
    )


def maker_paper_score_freshness(candidate_run_folders, covered_run_folders=None, *, report_generated_at_utc=None):
    covered = {str(Path(folder)) for folder in covered_run_folders or []}
    rows = [_run_folder_freshness_row(folder) for folder in candidate_run_folders or []]
    active_completed = [
        row for row in rows
        if row.get("active_day") and row.get("completed")
    ]
    covered_active = [
        row for row in active_completed
        if row.get("run_folder") in covered
    ]
    latest_completed = max(active_completed, key=_run_freshness_sort_key, default={})
    latest_covered = max(covered_active, key=_run_freshness_sort_key, default={})
    if not latest_completed:
        status = "NO_ACTIVE_DAY"
        reason = "no completed active-day maker run found"
    elif latest_covered.get("run_folder") == latest_completed.get("run_folder"):
        status = "PASS"
        reason = "standard maker paper score covers the latest completed active day"
    else:
        status = "STALE"
        reason = "standard maker paper score does not cover the latest completed active day"
    return {
        "status": status,
        "reason": reason,
        "report_generated_at_utc": report_generated_at_utc,
        "latest_completed_active_day": latest_completed.get("target_date"),
        "latest_completed_active_run_id": latest_completed.get("run_id"),
        "latest_completed_active_run_folder": latest_completed.get("run_folder"),
        "latest_covered_active_day": latest_covered.get("target_date"),
        "latest_covered_active_run_id": latest_covered.get("run_id"),
        "latest_covered_active_run_folder": latest_covered.get("run_folder"),
        "completed_active_run_count": len(active_completed),
        "covered_active_run_count": len(covered_active),
        "live_forward_day_count": len({row.get("target_date") for row in covered_active if row.get("target_date")}),
        "blocks_maker_evidence_countability": status == "STALE",
        "covered_run_folders": sorted(covered),
    }


def maker_paper_score_freshness_from_report(runs_root=DEFAULT_MM_RUNS_ROOT, report_json=DEFAULT_MM_PAPER_JSON):
    candidate_run_folders = discover_run_folders(runs_root)
    payload = _read_maker_json(report_json, {}) or {}
    summary = payload.get("summary") or {}
    freshness = summary.get("paper_score_freshness") or {}
    covered = freshness.get("covered_run_folders")
    if covered is None:
        covered = list((payload.get("run_configs") or {}).keys())
    result = maker_paper_score_freshness(
        candidate_run_folders,
        covered,
        report_generated_at_utc=payload.get("generated_at_utc"),
    )
    result["report_json"] = str(Path(report_json))
    result["report_exists"] = Path(report_json).exists()
    if not result["report_exists"] and result.get("status") == "PASS":
        result["status"] = "STALE"
        result["reason"] = "standard maker paper score JSON is missing"
        result["blocks_maker_evidence_countability"] = True
    return result
