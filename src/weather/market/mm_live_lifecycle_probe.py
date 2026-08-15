"""Dedicated first-order lifecycle probe for International Polymarket.

This module accepts an already-authenticated, fail-closed adapter plus a passing
``mm_platform_bootstrap_v0.2`` gate. The bounded operator CLI wires that narrow
surface to credential references; the ordinary maker runner never calls it.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from weather.market.market_making_run_constants import MAX_OPERATOR_PILOT_BUDGET_USDC
from weather.market.mm_official_adapter import (
    CONDITION_ID_RE,
    EVM_ADDRESS_RE,
    MAX_STAGE1_ORDER_NOTIONAL,
    exact_current_positions_evidence,
)


SCHEMA_VERSION = "mm_live_lifecycle_probe_v0.1"
JOURNAL_SCHEMA_VERSION = "mm_live_lifecycle_probe_journal_v0.1"
LIFECYCLE_BUNDLE_SCHEMA_VERSION = "mm_stage1_lifecycle_bundle_v0.1"
CONFIRMATION = "INTERNATIONAL_POLYMARKET_STAGE1_LIFECYCLE_PROBE"
CANCELLATION_MODES = {"cancel_all", "dead_man"}
OFFICIAL_HEARTBEAT_INTERVAL_SECONDS = 5.0
OFFICIAL_DEAD_MAN_TIMEOUT_SECONDS = 10.0
OFFICIAL_DEAD_MAN_MAX_CHECK_DELAY_SECONDS = 5.0


def _utc_iso():
    return datetime.now(timezone.utc).isoformat()


def _canonical_hash(payload):
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class LifecycleProbeJournal:
    """Append-only, flush-on-event evidence for the first live mutation."""

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise FileExistsError(f"lifecycle probe journal already exists: {self.path}")
        self.record("journal_opened")

    def record(self, event_type, **fields):
        row = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "recorded_at_utc": _utc_iso(),
            "event_type": str(event_type),
            **fields,
        }
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def sha256(self):
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


def _value(payload, *names):
    for name in names:
        value = payload.get(name) if isinstance(payload, dict) else getattr(payload, name, None)
        if value is not None and value != "":
            return value
    return None


def _order_id(payload):
    value = _value(payload, "orderID", "order_id", "id")
    return str(value) if value else None


def _contains_order(rows, order_id):
    return any(_order_id(row) == order_id for row in rows or [])


def _contains_terminal_cancel(rows, order_id):
    terminal = {"cancel", "canceled", "cancelled", "cancellation", "expired"}
    for row in rows or []:
        if _order_id(row) != order_id:
            continue
        states = {
            str(_value(row, name) or "").strip().lower()
            for name in ("event_type", "type", "status")
        }
        if states.intersection(terminal):
            return True
    return False


def _contains_trade_lifecycle(rows, order_id):
    """Detect every scoped trade state, including not-yet-confirmed matches."""

    trade_event_types = {"trade", "trade_pending", "rejected"}
    for row in rows or []:
        if _order_id(row) != order_id:
            continue
        if (
            str(_value(row, "official_event_type") or "").strip().lower()
            == "trade"
            or str(_value(row, "event_type") or "").strip().lower()
            in trade_event_types
        ):
            return True
    return False


def _minimum_probe_intent(market_rules):
    tick_size = Decimal(str(market_rules["tick_size"]))
    min_order_size = Decimal(str(market_rules["min_order_size"]))
    best_ask_raw = market_rules.get("best_ask")
    best_ask = Decimal(str(best_ask_raw)) if best_ask_raw is not None else None
    if best_ask is not None and tick_size >= best_ask:
        raise RuntimeError("no non-crossing minimum-tick BUY exists for the selected token")
    return {
        "token_id": str(market_rules["token_id"]),
        "price": float(tick_size),
        "size": float(min_order_size),
        "side": "BUY",
    }


def _validate_bootstrap_binding(adapter, bootstrap_gate):
    checks = bootstrap_gate.get("checks")
    try:
        requested_budget = Decimal(str(bootstrap_gate.get("requested_budget_usdc")))
        wallet_cap = Decimal(str(bootstrap_gate.get("pilot_wallet_max_funding_usdc")))
    except (ArithmeticError, TypeError, ValueError):
        requested_budget = wallet_cap = None
    operator_cap = Decimal(str(MAX_OPERATOR_PILOT_BUDGET_USDC))
    required = {
        "required": bootstrap_gate.get("required") is True,
        "ok": bootstrap_gate.get("ok") is True,
        "schema": bootstrap_gate.get("schema_version") == "mm_platform_bootstrap_v0.2",
        "status": bootstrap_gate.get("status") == "PASS",
        "platform": bootstrap_gate.get("platform") == "polymarket_global",
        "settlement_unit": bootstrap_gate.get("settlement_unit") == "pUSD",
        "checks": (
            isinstance(checks, dict)
            and bool(checks)
            and all(value is True for value in checks.values())
        ),
        "missing": bootstrap_gate.get("missing") == [],
        "account_snapshot": len(str(bootstrap_gate.get("account_snapshot_sha256") or "")) == 64,
        "geoblock_evidence": len(
            str(bootstrap_gate.get("geoblock_evidence_sha256") or "")
        ) == 64,
        "geoblock_country": bool(
            str(bootstrap_gate.get("geoblock_country") or "").strip()
        ),
        "token": str(getattr(adapter, "token_id", ""))
        == str(bootstrap_gate.get("token_id") or ""),
        "token_format": str(bootstrap_gate.get("token_id") or "").isdigit()
        and int(str(bootstrap_gate.get("token_id"))) > 0,
        "condition": str(getattr(adapter, "condition_id", "") or "").lower()
        == str(bootstrap_gate.get("condition_id") or "").lower(),
        "maker": str(getattr(adapter, "maker_address", "") or "").lower()
        == str(bootstrap_gate.get("funder_address") or "").lower(),
        "condition_format": CONDITION_ID_RE.fullmatch(
            str(bootstrap_gate.get("condition_id") or "")
        ) is not None,
        "wallet_cap": (
            wallet_cap is not None
            and wallet_cap.is_finite()
            and Decimal("0") < wallet_cap <= operator_cap
        ),
        "requested_budget": (
            requested_budget is not None
            and requested_budget.is_finite()
            and Decimal("0") < requested_budget <= operator_cap
            and wallet_cap is not None
            and requested_budget <= wallet_cap
        ),
        "maker_format": EVM_ADDRESS_RE.fullmatch(
            str(bootstrap_gate.get("funder_address") or "")
        ) is not None,
        "sdk": str(getattr(adapter, "sdk_version", "") or "")
        == str(bootstrap_gate.get("sdk_version") or ""),
    }
    missing = [name for name, valid in required.items() if not valid]
    if missing:
        raise RuntimeError(
            "Stage 1 adapter/bootstrap binding failed: " + ", ".join(missing)
        )


def _verified_exact_positions(adapter):
    positions = adapter.positions()
    evidence = adapter.position_evidence(positions)
    valid = exact_current_positions_evidence(
        evidence,
        maker_address=getattr(adapter, "maker_address", ""),
        condition_id=getattr(adapter, "condition_id", ""),
        rows=positions,
    )
    if not valid:
        raise RuntimeError("Stage 1 position read lacks exact-scope response evidence")
    return positions, evidence


def execute_stage1_lifecycle_probe(
    adapter,
    bootstrap_gate,
    *,
    confirmation,
    cancellation_mode,
    journal_path,
    monotonic_clock=None,
    sleeper=None,
    observation_timeout_seconds=10.0,
    dead_man_timeout_seconds=15.0,
    poll_interval_seconds=0.25,
    heartbeat_interval_seconds=OFFICIAL_HEARTBEAT_INTERVAL_SECONDS,
):
    """Place one minimum-tick order and prove one cancellation mechanism.

    A caller must execute both cancellation modes in separate runs before
    constructing full platform verification. Every failure attempts
    cancel-all and returns no permission to continue.
    """

    if confirmation != CONFIRMATION:
        raise RuntimeError("Stage 1 lifecycle probe requires the exact confirmation token")
    if cancellation_mode not in CANCELLATION_MODES:
        raise ValueError("cancellation_mode must be cancel_all or dead_man")
    if not isinstance(bootstrap_gate, dict) or not bootstrap_gate.get("ok"):
        raise RuntimeError("Stage 1 lifecycle probe requires a passing platform bootstrap gate")
    if not getattr(adapter, "supports_trading", False):
        raise RuntimeError("Stage 1 lifecycle probe requires a mutation-capable official adapter")
    _validate_bootstrap_binding(adapter, bootstrap_gate)
    if not journal_path:
        raise RuntimeError("Stage 1 lifecycle probe requires a durable journal path")
    heartbeat_interval = float(heartbeat_interval_seconds)
    if not 0 < heartbeat_interval <= OFFICIAL_HEARTBEAT_INTERVAL_SECONDS:
        raise RuntimeError("Stage 1 heartbeat interval must be in (0, 5] seconds")
    dead_man_timeout = float(dead_man_timeout_seconds)
    if cancellation_mode == "dead_man" and dead_man_timeout < (
        OFFICIAL_DEAD_MAN_TIMEOUT_SECONDS
        + OFFICIAL_DEAD_MAN_MAX_CHECK_DELAY_SECONDS
    ):
        raise RuntimeError("Stage 1 dead-man observation window must be at least 15 seconds")

    clock = monotonic_clock or time.monotonic
    sleep = sleeper or time.sleep
    poll_interval = max(0.01, float(poll_interval_seconds))
    journal = LifecycleProbeJournal(journal_path)
    bootstrap_hash = _canonical_hash(bootstrap_gate)
    journal.record(
        "probe_authorized",
        platform="polymarket_global",
        cancellation_mode=cancellation_mode,
        bootstrap_schema_version=bootstrap_gate.get("schema_version"),
        bootstrap_sha256=bootstrap_hash,
        condition_id=bootstrap_gate.get("condition_id"),
        token_id=bootstrap_gate.get("token_id"),
        requested_budget_usdc=bootstrap_gate.get("requested_budget_usdc"),
        geoblock_country=bootstrap_gate.get("geoblock_country"),
        geoblock_region=bootstrap_gate.get("geoblock_region"),
        geoblock_evidence_sha256=bootstrap_gate.get("geoblock_evidence_sha256"),
        confirmation_matched=True,
        secret_values_redacted=True,
    )
    starting_orders = adapter.open_orders()
    if starting_orders:
        journal.record("probe_blocked", phase="starting_order_check", open_order_count=len(starting_orders))
        raise RuntimeError("Stage 1 lifecycle probe requires zero open orders at start")
    starting_positions, starting_position_evidence = _verified_exact_positions(adapter)
    if starting_positions:
        journal.record(
            "probe_blocked",
            phase="starting_position_check",
            position_count=len(starting_positions),
        )
        raise RuntimeError("Stage 1 lifecycle probe requires zero positions at start")
    journal.record(
        "starting_state_verified",
        zero_open_orders=True,
        zero_positions=True,
        position_response_sha256=starting_position_evidence["response_sha256"],
    )

    response = None
    order_id = None
    observed_open = False
    observed_user_event = False
    phase = "heartbeat"
    try:
        phase = "stage1_capability"
        stage1_capability = adapter.authorize_stage1_lifecycle(bootstrap_gate)
        journal.record(
            "stage1_capability_issued",
            bootstrap_sha256=bootstrap_hash,
            single_submit=True,
        )
        phase = "heartbeat"
        first_heartbeat = adapter.heartbeat()
        if first_heartbeat != {"status": "ok"}:
            raise RuntimeError("Stage 1 did not receive the current heartbeat acknowledgment")
        last_heartbeat_at = clock()
        journal.record(
            "heartbeat_acknowledged",
            status_ok=True,
        )
        phase = "market_rules"
        rules = adapter.refresh_market_rules()
        if str(rules["token_id"]) != str(bootstrap_gate["token_id"]):
            raise RuntimeError("fresh market rules do not match the bootstrap token")
        intent = _minimum_probe_intent(rules)
        notional = Decimal(str(intent["price"])) * Decimal(str(intent["size"]))
        requested_budget = Decimal(str(bootstrap_gate["requested_budget_usdc"]))
        if notional > requested_budget:
            raise RuntimeError("minimum valid probe order exceeds the requested pilot budget")
        journal.record(
            "intent_prepared",
            token_id=intent["token_id"],
            side=intent["side"],
            price=intent["price"],
            size=intent["size"],
            order_notional_usdc=float(notional),
            post_only_required=True,
        )
        phase = "placement"
        response = adapter.place_order(intent, stage1_capability=stage1_capability)
        geo_diagnostics = adapter.diagnostics()
        if not all((
            geo_diagnostics.get("geoblock_allows_orders") is True,
            str(geo_diagnostics.get("geoblock_country") or "").upper()
            == str(bootstrap_gate.get("geoblock_country") or "").upper(),
            str(geo_diagnostics.get("geoblock_region") or "").upper()
            == str(bootstrap_gate.get("geoblock_region") or "").upper(),
            len(str(geo_diagnostics.get("geoblock_evidence_sha256") or "")) == 64,
            len(str(geo_diagnostics.get("stage1_geoblock_evidence_sha256") or "")) == 64,
        )):
            raise RuntimeError("Stage 1 placement lacks current official geoblock evidence")
        order_id = _order_id(response)
        if not order_id:
            raise RuntimeError("Stage 1 placement response did not carry an order id")
        journal.record(
            "order_accepted",
            order_id=order_id,
            placement_status=str(_value(response, "status") or "").lower(),
            geoblock_country=geo_diagnostics["geoblock_country"],
            geoblock_region=geo_diagnostics["geoblock_region"],
            capability_geoblock_evidence_sha256=geo_diagnostics[
                "stage1_geoblock_evidence_sha256"
            ],
            submission_geoblock_evidence_sha256=geo_diagnostics[
                "geoblock_evidence_sha256"
            ],
        )

        phase = "authoritative_order_observation"
        observation_deadline = clock() + float(observation_timeout_seconds)
        while clock() <= observation_deadline:
            if clock() - last_heartbeat_at >= heartbeat_interval:
                continued_heartbeat = adapter.heartbeat()
                if continued_heartbeat != {"status": "ok"}:
                    raise RuntimeError("Stage 1 continuation heartbeat was not acknowledged")
                last_heartbeat_at = clock()
                journal.record(
                    "heartbeat_continued",
                    phase=phase,
                    status_ok=True,
                )
            observed_open = _contains_order(adapter.open_orders(), order_id)
            user_events = adapter.user_events()
            if _contains_trade_lifecycle(user_events, order_id):
                raise RuntimeError("Stage 1 order received an unexpected trade lifecycle event")
            observed_user_event = _contains_order(user_events, order_id)
            if observed_open and observed_user_event:
                break
            sleep(poll_interval)
        if not observed_open or not observed_user_event:
            raise RuntimeError(
                "Stage 1 order was not observed in both open orders and the authoritative user stream"
            )
        journal.record(
            "order_observed",
            order_id=order_id,
            open_order_observed=True,
            authoritative_user_event_observed=True,
        )

        phase = "cancellation"
        journal.record("cancellation_started", order_id=order_id, mode=cancellation_mode)
        pre_cancel_heartbeat = adapter.heartbeat()
        if pre_cancel_heartbeat != {"status": "ok"}:
            raise RuntimeError("Stage 1 pre-cancellation heartbeat was not acknowledged")
        last_heartbeat_at = clock()
        if not _contains_order(adapter.open_orders(), order_id):
            raise RuntimeError("Stage 1 order was not live immediately before cancellation proof")
        journal.record(
            "pre_cancellation_heartbeat_acknowledged",
            order_id=order_id,
            mode=cancellation_mode,
            status_ok=True,
        )
        if cancellation_mode == "cancel_all":
            cancel_response = adapter.cancel_all()
            cancellation_observed = True
            cancellation_elapsed_seconds = 0.0
        else:
            cancel_response = None
            cancellation_observed = False
            dead_man_lapse_started = last_heartbeat_at
            dead_man_deadline = dead_man_lapse_started + min(
                dead_man_timeout,
                OFFICIAL_DEAD_MAN_TIMEOUT_SECONDS
                + OFFICIAL_DEAD_MAN_MAX_CHECK_DELAY_SECONDS,
            )
            while clock() <= dead_man_deadline:
                if not _contains_order(adapter.open_orders(), order_id):
                    cancellation_observed = True
                    break
                sleep(poll_interval)
            if not cancellation_observed:
                raise RuntimeError("dead-man heartbeat lapse did not remove the Stage 1 order")
            cancellation_elapsed_seconds = clock() - dead_man_lapse_started
            if cancellation_elapsed_seconds < OFFICIAL_DEAD_MAN_TIMEOUT_SECONDS:
                raise RuntimeError("order disappeared before the documented dead-man timeout")
            if cancellation_elapsed_seconds > (
                OFFICIAL_DEAD_MAN_TIMEOUT_SECONDS
                + OFFICIAL_DEAD_MAN_MAX_CHECK_DELAY_SECONDS
            ):
                raise RuntimeError("order remained live beyond the documented dead-man check window")

        phase = "zero_open_orders_check"
        remaining = adapter.open_orders()
        if remaining:
            raise RuntimeError("Stage 1 cancellation was not followed by zero open orders")
        phase = "terminal_user_event_observation"
        terminal_event_observed = False
        terminal_deadline = clock() + float(observation_timeout_seconds)
        while clock() <= terminal_deadline:
            user_events = adapter.user_events()
            if _contains_trade_lifecycle(user_events, order_id):
                raise RuntimeError("Stage 1 order received an unexpected trade lifecycle event")
            if _contains_terminal_cancel(user_events, order_id):
                terminal_event_observed = True
                break
            sleep(poll_interval)
        if not terminal_event_observed:
            raise RuntimeError("Stage 1 cancellation was not observed on the authoritative user stream")
        ending_positions, ending_position_evidence = _verified_exact_positions(adapter)
        if ending_positions:
            raise RuntimeError("Stage 1 ended with unexpected outcome inventory")
        if _contains_trade_lifecycle(adapter.user_events(), order_id):
            raise RuntimeError("Stage 1 order received an unexpected trade lifecycle event")
        journal.record(
            "cancellation_verified",
            order_id=order_id,
            mode=cancellation_mode,
            cancellation_observed=cancellation_observed,
            terminal_user_event_observed=True,
            zero_open_orders_verified=True,
            zero_positions_verified=True,
            cancellation_elapsed_seconds=cancellation_elapsed_seconds,
            position_response_sha256=ending_position_evidence["response_sha256"],
        )
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "completed_at_utc": _utc_iso(),
            "platform": "polymarket_global",
            "settlement_unit": "pUSD",
            "cancellation_mode": cancellation_mode,
            "bootstrap_schema_version": bootstrap_gate.get("schema_version"),
            "condition_id": bootstrap_gate.get("condition_id"),
            "token_id": bootstrap_gate.get("token_id"),
            "heartbeat_acknowledged": first_heartbeat == {"status": "ok"},
            "starting_zero_open_orders_verified": True,
            "starting_zero_positions_verified": True,
            "intent": intent,
            "order_notional_usdc": float(notional),
            "order_id": order_id,
            "placement_status": str(_value(response, "status") or "").lower(),
            "geoblock_country": geo_diagnostics["geoblock_country"],
            "geoblock_region": geo_diagnostics["geoblock_region"],
            "capability_geoblock_evidence_sha256": geo_diagnostics[
                "stage1_geoblock_evidence_sha256"
            ],
            "submission_geoblock_evidence_sha256": geo_diagnostics[
                "geoblock_evidence_sha256"
            ],
            "open_order_observed": observed_open,
            "authoritative_user_event_observed": observed_user_event,
            "cancellation_observed": cancellation_observed,
            "cancellation_elapsed_seconds": cancellation_elapsed_seconds,
            "terminal_user_event_observed": terminal_event_observed,
            "no_trade_lifecycle_event_observed": True,
            "cancel_response_present": cancel_response is not None,
            "zero_open_orders_verified": True,
            "zero_positions_verified": True,
            "secret_values_redacted": True,
            "bootstrap_sha256": bootstrap_hash,
            "journal_path": str(journal.path),
        }
        journal.record(
            "probe_passed",
            order_id=order_id,
            cancellation_mode=cancellation_mode,
            zero_open_orders_verified=True,
            zero_positions_verified=True,
        )
        result["journal_sha256"] = journal.sha256()
        return result
    except Exception as exc:
        cleanup_succeeded = False
        cleanup_zero_open_orders = False
        cleanup_zero_positions = False
        try:
            adapter.cancel_all()
            cleanup_zero_open_orders = not bool(adapter.open_orders())
            cleanup_positions, _ = _verified_exact_positions(adapter)
            cleanup_zero_positions = not bool(cleanup_positions)
            cleanup_succeeded = cleanup_zero_open_orders and cleanup_zero_positions
        except Exception:
            cleanup_succeeded = False
        try:
            journal.record(
                "probe_failed",
                phase=phase,
                exception_type=type(exc).__name__,
                order_id=order_id,
                cleanup_attempted=True,
                cleanup_succeeded=cleanup_succeeded,
                cleanup_zero_open_orders=cleanup_zero_open_orders,
                cleanup_zero_positions=cleanup_zero_positions,
            )
        except Exception:
            pass
        raise


def _verified_probe_journal(result):
    path = Path(str(result.get("journal_path") or ""))
    if not path.is_file():
        raise RuntimeError("Stage 1 lifecycle journal is missing")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != str(result.get("journal_sha256") or ""):
        raise RuntimeError("Stage 1 lifecycle journal hash does not match content")
    try:
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Stage 1 lifecycle journal is invalid JSONL") from exc
    if not rows or any(
        not isinstance(row, dict)
        or row.get("schema_version") != JOURNAL_SCHEMA_VERSION
        for row in rows
    ):
        raise RuntimeError("Stage 1 lifecycle journal schema is invalid")
    event_types = [row.get("event_type") for row in rows]
    if "probe_failed" in event_types:
        raise RuntimeError("Stage 1 lifecycle journal contains a failed probe")
    required_types = {
        "journal_opened",
        "probe_authorized",
        "starting_state_verified",
        "stage1_capability_issued",
        "heartbeat_acknowledged",
        "intent_prepared",
        "order_accepted",
        "order_observed",
        "cancellation_started",
        "pre_cancellation_heartbeat_acknowledged",
        "cancellation_verified",
        "probe_passed",
    }
    if not required_types.issubset(event_types):
        raise RuntimeError("Stage 1 lifecycle journal is missing required events")

    def matching(event_type):
        return [row for row in rows if row.get("event_type") == event_type]

    order_id = str(result.get("order_id") or "")
    mode = str(result.get("cancellation_mode") or "")
    bootstrap_sha256 = str(result.get("bootstrap_sha256") or "")
    authorized = matching("probe_authorized")
    starts = matching("starting_state_verified")
    accepted = matching("order_accepted")
    observed = matching("order_observed")
    cancelled = matching("cancellation_verified")
    passed = matching("probe_passed")
    valid = all((
        len(authorized) == 1,
        authorized[0].get("bootstrap_sha256") == bootstrap_sha256,
        authorized[0].get("cancellation_mode") == mode,
        len(starts) == 1,
        starts[0].get("zero_open_orders") is True,
        starts[0].get("zero_positions") is True,
        any(row.get("order_id") == order_id for row in accepted),
        any(
            row.get("order_id") == order_id
            and row.get("open_order_observed") is True
            and row.get("authoritative_user_event_observed") is True
            for row in observed
        ),
        any(
            row.get("order_id") == order_id
            and row.get("mode") == mode
            and row.get("cancellation_observed") is True
            and row.get("terminal_user_event_observed") is True
            and row.get("zero_open_orders_verified") is True
            and row.get("zero_positions_verified") is True
            for row in cancelled
        ),
        any(
            row.get("order_id") == order_id
            and row.get("cancellation_mode") == mode
            and row.get("zero_open_orders_verified") is True
            and row.get("zero_positions_verified") is True
            for row in passed
        ),
    ))
    if not valid:
        raise RuntimeError("Stage 1 lifecycle journal does not bind the reported result")
    return {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "row_count": len(rows),
    }


def build_stage1_lifecycle_bundle(bootstrap_gate, cancel_all_result, dead_man_result):
    """Bind two distinct Stage 1 cancellation proofs into no-fill evidence."""

    if not isinstance(bootstrap_gate, dict) or not bootstrap_gate.get("ok"):
        raise RuntimeError("Stage 1 lifecycle bundle requires a passing bootstrap gate")
    bootstrap_sha256 = _canonical_hash(bootstrap_gate)
    results = {
        "cancel_all": dict(cancel_all_result or {}),
        "dead_man": dict(dead_man_result or {}),
    }
    journal_evidence = {}
    requested_budget = Decimal(str(bootstrap_gate.get("requested_budget_usdc")))
    wallet_cap = Decimal(str(bootstrap_gate.get("pilot_wallet_max_funding_usdc")))
    operator_cap = Decimal(str(MAX_OPERATOR_PILOT_BUDGET_USDC))
    if not all((
        requested_budget.is_finite(),
        wallet_cap.is_finite(),
        Decimal("0") < requested_budget <= wallet_cap <= operator_cap,
    )):
        raise RuntimeError("Stage 1 lifecycle bundle exceeds the operator wallet or budget cap")
    for mode, result in results.items():
        try:
            notional = Decimal(str(result.get("order_notional_usdc")))
            elapsed = Decimal(str(result.get("cancellation_elapsed_seconds")))
        except Exception as exc:
            raise RuntimeError("Stage 1 lifecycle result has invalid numeric evidence") from exc
        checks = {
            "schema": result.get("schema_version") == SCHEMA_VERSION,
            "status": result.get("status") == "PASS",
            "platform": result.get("platform") == "polymarket_global",
            "settlement_unit": result.get("settlement_unit") == "pUSD",
            "mode": result.get("cancellation_mode") == mode,
            "bootstrap_schema": result.get("bootstrap_schema_version")
            == bootstrap_gate.get("schema_version"),
            "bootstrap_hash": result.get("bootstrap_sha256") == bootstrap_sha256,
            "condition": str(result.get("condition_id") or "").lower()
            == str(bootstrap_gate.get("condition_id") or "").lower(),
            "token": str(result.get("token_id") or "")
            == str(bootstrap_gate.get("token_id") or ""),
            "country": str(result.get("geoblock_country") or "").upper()
            == str(bootstrap_gate.get("geoblock_country") or "").upper(),
            "region": str(result.get("geoblock_region") or "").upper()
            == str(bootstrap_gate.get("geoblock_region") or "").upper(),
            "capability_geo_hash": len(
                str(result.get("capability_geoblock_evidence_sha256") or "")
            ) == 64,
            "submission_geo_hash": len(
                str(result.get("submission_geoblock_evidence_sha256") or "")
            ) == 64,
            "heartbeat": result.get("heartbeat_acknowledged") is True,
            "starting_orders": result.get("starting_zero_open_orders_verified") is True,
            "starting_positions": result.get("starting_zero_positions_verified") is True,
            "live_order": result.get("placement_status") == "live",
            "order_id": bool(str(result.get("order_id") or "")),
            "notional": (
                notional.is_finite()
                and Decimal("0") < notional <= requested_budget
                and notional <= MAX_STAGE1_ORDER_NOTIONAL
            ),
            "open_observation": result.get("open_order_observed") is True,
            "user_observation": result.get("authoritative_user_event_observed") is True,
            "cancellation": result.get("cancellation_observed") is True,
            "terminal": result.get("terminal_user_event_observed") is True,
            "no_trade": result.get("no_trade_lifecycle_event_observed") is True,
            "ending_orders": result.get("zero_open_orders_verified") is True,
            "ending_positions": result.get("zero_positions_verified") is True,
            "redacted": result.get("secret_values_redacted") is True,
            "journal_hash": len(str(result.get("journal_sha256") or "")) == 64,
            "mode_response": (
                result.get("cancel_response_present") is True
                if mode == "cancel_all"
                else result.get("cancel_response_present") is False
            ),
            "dead_man_elapsed": mode != "dead_man"
            or (
                elapsed >= Decimal(str(OFFICIAL_DEAD_MAN_TIMEOUT_SECONDS))
                and elapsed
                <= Decimal(str(
                    OFFICIAL_DEAD_MAN_TIMEOUT_SECONDS
                    + OFFICIAL_DEAD_MAN_MAX_CHECK_DELAY_SECONDS
                ))
            ),
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            raise RuntimeError(
                f"Stage 1 {mode} result failed bundle checks: " + ", ".join(failed)
            )
        journal_evidence[mode] = _verified_probe_journal(result)

    if results["cancel_all"]["order_id"] == results["dead_man"]["order_id"]:
        raise RuntimeError("Stage 1 cancellation modes must use distinct orders")
    if journal_evidence["cancel_all"]["path"] == journal_evidence["dead_man"]["path"]:
        raise RuntimeError("Stage 1 cancellation modes must use distinct journals")
    if journal_evidence["cancel_all"]["sha256"] == journal_evidence["dead_man"]["sha256"]:
        raise RuntimeError("Stage 1 cancellation journals must have distinct content")

    payload = {
        "schema_version": LIFECYCLE_BUNDLE_SCHEMA_VERSION,
        "status": "PASS",
        "created_at_utc": _utc_iso(),
        "platform": "polymarket_global",
        "settlement_unit": "pUSD",
        "bootstrap_schema_version": bootstrap_gate.get("schema_version"),
        "bootstrap_sha256": bootstrap_sha256,
        "condition_id": bootstrap_gate.get("condition_id"),
        "token_id": bootstrap_gate.get("token_id"),
        "funder_address": bootstrap_gate.get("funder_address"),
        "requested_budget_usdc": float(requested_budget),
        "geoblock_country": bootstrap_gate.get("geoblock_country"),
        "geoblock_region": bootstrap_gate.get("geoblock_region"),
        "lifecycle_results": results,
        "journal_evidence": journal_evidence,
        "derived_platform_evidence": {
            "starting_open_orders_rest_verified": True,
            "order_update_verified": True,
            "fill_event_verified": False,
            "no_fill_lifecycle_verified": True,
            "final_state_reconciliation_verified": True,
            "cancel_all_request_verified": True,
            "cancel_all_zero_open_orders_verified": True,
            "dead_man_automatic_cancel_verified": True,
            "heartbeat_acknowledgment_verified": True,
        },
        "secret_values_redacted": True,
    }
    payload["bundle_sha256"] = _canonical_hash(payload)
    return payload
