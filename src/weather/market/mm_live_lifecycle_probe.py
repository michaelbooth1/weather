"""Dedicated first-order lifecycle probe for International Polymarket.

This module accepts an already-authenticated, fail-closed adapter plus a passing
``mm_platform_bootstrap_v0.5`` gate. The bounded operator CLI wires that narrow
surface to credential references; the ordinary maker runner never calls it.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from weather.market.market_making_run_constants import MAX_OPERATOR_PILOT_BUDGET_USDC
from weather.market.mm_geographic_eligibility import (
    validate_geographic_eligibility_receipt,
)
from weather.market.mm_official_adapter import (
    CONDITION_ID_RE,
    EVM_ADDRESS_RE,
    MAX_STAGE1_ORDER_NOTIONAL,
    exact_current_positions_evidence,
)


SCHEMA_VERSION = "mm_live_lifecycle_probe_v0.3"
JOURNAL_SCHEMA_VERSION = "mm_live_lifecycle_probe_journal_v0.2"
LIFECYCLE_BUNDLE_SCHEMA_VERSION = "mm_stage1_lifecycle_bundle_v0.3"
BOOTSTRAP_SCHEMA_VERSION = "mm_platform_bootstrap_v0.5"
CONFIRMATION = "INTERNATIONAL_POLYMARKET_STAGE1_LIFECYCLE_PROBE"
CANCELLATION_MODES = {"cancel_all", "dead_man"}
OFFICIAL_HEARTBEAT_INTERVAL_SECONDS = 5.0
OFFICIAL_DEAD_MAN_TIMEOUT_SECONDS = 10.0
OFFICIAL_DEAD_MAN_MAX_CHECK_DELAY_SECONDS = 5.0
POST_CANCEL_QUIESCENCE_SECONDS = 2.0
USER_STREAM_JOURNAL_SCHEMA_VERSION = "mm_user_stream_journal_v0.1"


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


def _is_sha256(value):
    text = str(value or "")
    return len(text) == 64 and all(
        character in "0123456789abcdef" for character in text
    )


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
            matched_raw = _value(row, "size_matched", "sizeMatched")
            if matched_raw is None:
                raise RuntimeError(
                    "terminal cancellation event omitted matched-size evidence"
                )
            try:
                matched = Decimal(str(matched_raw))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise RuntimeError(
                    "terminal cancellation event has invalid matched-size evidence"
                ) from exc
            if not matched.is_finite() or matched != 0:
                raise RuntimeError(
                    "terminal cancellation event reports a nonzero matched size"
                )
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


def _trade_row_contains_order(row, order_id):
    if str(_value(row, "taker_order_id", "takerOrderId") or "") == str(order_id):
        return True
    for maker_row in _value(row, "maker_orders", "makerOrders") or []:
        if str(_value(maker_row, "order_id", "orderID", "id") or "") == str(order_id):
            return True
    return False


def _validate_terminal_rest_order(order, *, order_id, adapter):
    if not isinstance(order, dict):
        raise RuntimeError("terminal REST order evidence is not an object")
    try:
        matched = Decimal(str(_value(order, "size_matched", "sizeMatched")))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RuntimeError("terminal REST order has invalid matched-size evidence") from exc
    status = str(_value(order, "status") or "").strip().lower()
    associated_trades = _value(order, "associate_trades", "associateTrades")
    checks = (
        _order_id(order) == str(order_id),
        str(_value(order, "market", "condition_id") or "").lower()
        == str(getattr(adapter, "condition_id", "") or "").lower(),
        str(_value(order, "asset_id", "token_id") or "")
        == str(getattr(adapter, "token_id", "") or ""),
        str(_value(order, "maker_address") or "").lower()
        == str(getattr(adapter, "maker_address", "") or "").lower(),
        status in {
            "canceled",
            "cancelled",
            "expired",
            # The current official GET /order contract uses this wire value;
            # retain the shorter spellings for SDK/backward compatibility.
            "order_status_canceled",
        },
        matched.is_finite() and matched == 0,
        isinstance(associated_trades, (list, tuple)) and not associated_trades,
    )
    if not all(checks):
        raise RuntimeError("terminal REST order does not prove an exact zero-fill cancellation")
    return {
        "order_id": str(order_id),
        "status": status,
        "size_matched": str(matched),
        "response_sha256": _canonical_hash(order),
    }


def verify_stage1_user_stream_journal(path, result):
    """Parse and bind the final authenticated stream journal to one result."""

    journal_path = Path(path).resolve()
    if not journal_path.is_file():
        raise RuntimeError("Stage 1 final user-stream journal is missing")
    raw = journal_path.read_bytes()
    try:
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Stage 1 final user-stream journal is invalid JSONL") from exc
    if not rows or any(
        not isinstance(row, dict)
        or row.get("schema_version") != USER_STREAM_JOURNAL_SCHEMA_VERSION
        for row in rows
    ):
        raise RuntimeError("Stage 1 final user-stream journal schema is invalid")
    if any(row.get("event_type") == "stream_failed" for row in rows):
        raise RuntimeError("Stage 1 final user-stream journal records a stream failure")
    if (
        rows[-1].get("event_type") != "stream_stopped"
        or sum(row.get("event_type") == "stream_stopped" for row in rows) != 1
    ):
        raise RuntimeError(
            "Stage 1 final user-stream journal lacks one terminal stream_stopped event"
        )
    order_id = str((result or {}).get("order_id") or "")
    scoped = [
        row.get("payload")
        for row in rows
        if row.get("event_type") == "user_event"
        and isinstance(row.get("payload"), dict)
        and _order_id(row["payload"]) == order_id
    ]
    if not order_id or _contains_trade_lifecycle(scoped, order_id):
        raise RuntimeError("Stage 1 final user-stream journal contains a scoped trade lifecycle")
    if not _contains_terminal_cancel(scoped, order_id):
        raise RuntimeError("Stage 1 final user-stream journal lacks the exact zero-fill cancellation")
    digest = hashlib.sha256(raw).hexdigest()
    expected = str((result or {}).get("user_stream_journal_sha256") or "")
    cleanup_expected = str(
        (result or {}).get("cleanup_final_user_stream_journal_sha256") or ""
    )
    expected_path = str((result or {}).get("user_stream_journal_path") or "")
    if not _is_sha256(expected) or expected != digest:
        raise RuntimeError("Stage 1 final user-stream journal hash does not match result")
    if not _is_sha256(cleanup_expected) or cleanup_expected != digest:
        raise RuntimeError(
            "Stage 1 cleanup final user-stream journal hash does not match result"
        )
    if not expected_path or Path(expected_path).resolve() != journal_path:
        raise RuntimeError("Stage 1 final user-stream journal path does not match result")
    return {
        "path": str(journal_path),
        "sha256": digest,
        "row_count": len(rows),
        "scoped_order_event_count": len(scoped),
        "terminal_stream_stopped_verified": True,
    }


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


def _validate_candidate_fee_and_neg_risk(
    market_rules,
    *,
    expected_candidate_fee_rate,
    expected_candidate_neg_risk,
):
    try:
        candidate_fee_rate = Decimal(str(expected_candidate_fee_rate))
        current_fee_rate_bps = Decimal(str(market_rules.get("fee_rate_bps")))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RuntimeError("Stage 1 candidate/current fee binding is invalid") from exc
    if (
        not candidate_fee_rate.is_finite()
        or candidate_fee_rate < 0
        or not current_fee_rate_bps.is_finite()
        or current_fee_rate_bps < 0
        or not isinstance(expected_candidate_neg_risk, bool)
        or not isinstance(market_rules.get("neg_risk"), bool)
    ):
        raise RuntimeError("Stage 1 current market fee/neg-risk rules are invalid")
    if (
        candidate_fee_rate != current_fee_rate_bps / Decimal("10000")
        or market_rules.get("neg_risk") is not expected_candidate_neg_risk
    ):
        raise RuntimeError(
            "Stage 1 current fee/neg-risk rules differ from the sealed candidate"
        )
    return {
        "candidate_fee_rate": candidate_fee_rate,
        "current_fee_rate_bps": current_fee_rate_bps,
        "neg_risk": expected_candidate_neg_risk,
    }


def _action_time_collateral_snapshot(adapter, bootstrap_gate):
    refresh = getattr(adapter, "refresh_balance_allowance", None)
    if not callable(refresh):
        raise RuntimeError("Stage 1 adapter has no uncached collateral refresh")
    payload = refresh()
    if not isinstance(payload, dict):
        raise RuntimeError("Stage 1 current collateral response is invalid")
    allowances = payload.get("allowances")
    if not isinstance(allowances, dict) or not allowances:
        raise RuntimeError("Stage 1 current collateral allowances are incomplete")

    def atomic_amount(value, label):
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise RuntimeError(f"Stage 1 current collateral {label} is invalid") from exc
        if (
            not amount.is_finite()
            or amount < 0
            or amount != amount.to_integral_value()
        ):
            raise RuntimeError(f"Stage 1 current collateral {label} is invalid")
        return amount

    balance_atomic = atomic_amount(payload.get("balance"), "balance")
    normalized_allowances = {}
    allowance_amounts = []
    for spender, raw_amount in sorted(allowances.items(), key=lambda row: str(row[0])):
        spender_text = str(spender).strip()
        if not spender_text or spender_text in normalized_allowances:
            raise RuntimeError("Stage 1 current collateral allowance spender is invalid")
        amount = atomic_amount(raw_amount, "allowance")
        normalized_allowances[spender_text] = str(int(amount))
        allowance_amounts.append(amount)
    allowance_atomic = min(allowance_amounts)
    scale = Decimal("1000000")
    balance_usdc = balance_atomic / scale
    allowance_usdc = allowance_atomic / scale
    try:
        requested_budget = Decimal(str(bootstrap_gate.get("requested_budget_usdc")))
        wallet_cap = Decimal(
            str(bootstrap_gate.get("pilot_wallet_max_funding_usdc"))
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RuntimeError("Stage 1 collateral budget binding is invalid") from exc
    if requested_budget != MAX_STAGE1_ORDER_NOTIONAL:
        raise RuntimeError("Stage 1 action-time collateral requires the exact 10 pUSD budget")
    if (
        not wallet_cap.is_finite()
        or wallet_cap <= 0
        or wallet_cap > Decimal(str(MAX_OPERATOR_PILOT_BUDGET_USDC))
        or balance_usdc < requested_budget
        or balance_usdc > wallet_cap
        or allowance_usdc < requested_budget
    ):
        raise RuntimeError("Stage 1 action-time collateral is outside the sealed budget/cap")
    normalized = {
        "balance_atomic": str(int(balance_atomic)),
        "allowances_atomic": normalized_allowances,
    }
    return {
        "balance_usdc": balance_usdc,
        "allowance_usdc": allowance_usdc,
        "sha256": _canonical_hash(normalized),
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
        "schema": bootstrap_gate.get("schema_version") == BOOTSTRAP_SCHEMA_VERSION,
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
    submit_deadline_utc=None,
    utc_clock=None,
    pre_submit_attestor=None,
    expected_candidate_intent=None,
    expected_candidate_tick_size=None,
    expected_candidate_order_min_size=None,
    expected_candidate_fee_rate=None,
    expected_candidate_neg_risk=None,
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
    if not callable(pre_submit_attestor):
        raise RuntimeError(
            "Stage 1 lifecycle probe requires the sealed pre-submit attestor"
        )
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
    submit_deadline = None
    if submit_deadline_utc is not None:
        try:
            submit_deadline = datetime.fromisoformat(
                str(submit_deadline_utc).replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise RuntimeError("Stage 1 submit deadline is invalid") from exc
        if submit_deadline.tzinfo is None:
            raise RuntimeError("Stage 1 submit deadline must be timezone-aware")
        submit_deadline = submit_deadline.astimezone(timezone.utc)

    clock = monotonic_clock or time.monotonic
    wall_clock = utc_clock or (lambda: datetime.now(timezone.utc))
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
        stage1_capability = adapter.authorize_stage1_lifecycle(
            bootstrap_gate,
            submit_deadline_utc=submit_deadline.isoformat(),
        )
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
        candidate_rule_binding = _validate_candidate_fee_and_neg_risk(
            rules,
            expected_candidate_fee_rate=expected_candidate_fee_rate,
            expected_candidate_neg_risk=expected_candidate_neg_risk,
        )
        intent = _minimum_probe_intent(rules)
        notional = Decimal(str(intent["price"])) * Decimal(str(intent["size"]))
        candidate_intent = dict(expected_candidate_intent or {})
        try:
            candidate_price = Decimal(str(candidate_intent.get("price")))
            candidate_size = Decimal(str(candidate_intent.get("size")))
            candidate_notional = Decimal(
                str(candidate_intent.get("notional_pusd"))
            )
            candidate_tick = Decimal(str(expected_candidate_tick_size))
            candidate_minimum = Decimal(str(expected_candidate_order_min_size))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise RuntimeError("Stage 1 candidate intent binding is invalid") from exc
        if not all(
            (
                candidate_intent.get("side") == "BUY",
                candidate_intent.get("post_only") is True,
                candidate_price == Decimal(str(intent["price"])),
                candidate_size == Decimal(str(intent["size"])),
                candidate_notional == notional,
                candidate_tick == Decimal(str(rules["tick_size"])),
                candidate_minimum == Decimal(str(rules["min_order_size"])),
            )
        ):
            raise RuntimeError("fresh rules no longer match the sealed candidate intent")
        requested_budget = Decimal(str(bootstrap_gate["requested_budget_usdc"]))
        if notional > requested_budget:
            raise RuntimeError("minimum valid probe order exceeds the requested pilot budget")
        journal.record(
            "intent_prepared",
            cancellation_mode=cancellation_mode,
            token_id=intent["token_id"],
            side=intent["side"],
            price=intent["price"],
            size=intent["size"],
            order_notional_usdc=float(notional),
            post_only_required=True,
            candidate_fee_rate=float(candidate_rule_binding["candidate_fee_rate"]),
            current_fee_rate_bps=float(candidate_rule_binding["current_fee_rate_bps"]),
            candidate_neg_risk=candidate_rule_binding["neg_risk"],
            current_neg_risk=rules["neg_risk"],
        )
        phase = "placement"
        submit_rules = adapter.refresh_market_rules()
        if str(submit_rules["token_id"]) != str(bootstrap_gate["token_id"]):
            raise RuntimeError("submit-adjacent market rules changed token")
        submit_rule_binding = _validate_candidate_fee_and_neg_risk(
            submit_rules,
            expected_candidate_fee_rate=expected_candidate_fee_rate,
            expected_candidate_neg_risk=expected_candidate_neg_risk,
        )
        submit_intent = _minimum_probe_intent(submit_rules)
        if not all(
            (
                submit_intent == intent,
                Decimal(str(submit_rules["tick_size"])) == candidate_tick,
                Decimal(str(submit_rules["min_order_size"])) == candidate_minimum,
            )
        ):
            raise RuntimeError(
                "submit-adjacent market rules no longer match the sealed candidate intent"
            )
        journal.record(
            "market_rules_submit_adjacent_verified",
            cancellation_mode=cancellation_mode,
            token_id=str(submit_rules["token_id"]),
            candidate_fee_rate=float(submit_rule_binding["candidate_fee_rate"]),
            current_fee_rate_bps=float(submit_rule_binding["current_fee_rate_bps"]),
            candidate_neg_risk=submit_rule_binding["neg_risk"],
            current_neg_risk=submit_rules["neg_risk"],
        )
        phase = "submit_adjacent_collateral"
        submit_collateral = _action_time_collateral_snapshot(adapter, bootstrap_gate)
        journal.record(
            "collateral_submit_adjacent_verified",
            cancellation_mode=cancellation_mode,
            balance_usdc=float(submit_collateral["balance_usdc"]),
            allowance_usdc=float(submit_collateral["allowance_usdc"]),
            snapshot_sha256=submit_collateral["sha256"],
            requested_budget_usdc=float(requested_budget),
            wallet_cap_usdc=float(
                Decimal(str(bootstrap_gate["pilot_wallet_max_funding_usdc"]))
            ),
        )
        if submit_deadline is None or wall_clock().astimezone(timezone.utc) >= submit_deadline:
            raise RuntimeError("Stage 1 submit deadline has expired")
        journal.record(
            "submit_deadline_verified",
            cancellation_mode=cancellation_mode,
            submit_deadline_utc=submit_deadline.isoformat(),
        )
        phase = "submit_adjacent_geography"
        geographic_eligibility_receipt = pre_submit_attestor()
        journal.record("host_state_attested", cancellation_mode=cancellation_mode)
        if wall_clock().astimezone(timezone.utc) >= submit_deadline:
            raise RuntimeError(
                "Stage 1 submit deadline expired during geographic attestation"
            )
        geographic_eligibility_receipt = validate_geographic_eligibility_receipt(
            geographic_eligibility_receipt,
            now=wall_clock().astimezone(timezone.utc),
            require_fresh=True,
        )
        journal.record(
            "geographic_eligibility_submit_boundary_verified",
            cancellation_mode=cancellation_mode,
            receipt_payload_sha256=geographic_eligibility_receipt[
                "receipt_payload_sha256"
            ],
            checked_at_utc=geographic_eligibility_receipt["checked_at_utc"],
            fresh_until_utc=geographic_eligibility_receipt["fresh_until_utc"],
        )
        # The supervised geography check includes a human prompt and two host/network
        # attestations.  It can therefore outlive the short heartbeat and market-rule
        # freshness budgets.  Refresh both *after* that callback, rebind every rule to
        # the sealed candidate, and leave the heartbeat as the final network read
        # before entering the adapter's atomic signing boundary.
        phase = "submit_boundary_market_rules"
        network_boundary_rules = adapter.refresh_market_rules()
        if str(network_boundary_rules["token_id"]) != str(
            bootstrap_gate["token_id"]
        ):
            raise RuntimeError("network-boundary market rules changed token")
        network_boundary_rule_binding = _validate_candidate_fee_and_neg_risk(
            network_boundary_rules,
            expected_candidate_fee_rate=expected_candidate_fee_rate,
            expected_candidate_neg_risk=expected_candidate_neg_risk,
        )
        network_boundary_intent = _minimum_probe_intent(network_boundary_rules)
        if not all(
            (
                network_boundary_intent == intent,
                Decimal(str(network_boundary_rules["tick_size"])) == candidate_tick,
                Decimal(str(network_boundary_rules["min_order_size"]))
                == candidate_minimum,
            )
        ):
            raise RuntimeError(
                "network-boundary market rules no longer match the sealed candidate intent"
            )
        journal.record(
            "market_rules_network_boundary_verified",
            cancellation_mode=cancellation_mode,
            token_id=str(network_boundary_rules["token_id"]),
            candidate_fee_rate=float(
                network_boundary_rule_binding["candidate_fee_rate"]
            ),
            current_fee_rate_bps=float(
                network_boundary_rule_binding["current_fee_rate_bps"]
            ),
            candidate_neg_risk=network_boundary_rule_binding["neg_risk"],
            current_neg_risk=network_boundary_rules["neg_risk"],
        )
        phase = "submit_boundary_heartbeat_geography"
        geographic_eligibility_receipt = validate_geographic_eligibility_receipt(
            geographic_eligibility_receipt,
            now=wall_clock().astimezone(timezone.utc),
            require_fresh=True,
        )
        journal.record(
            "geographic_eligibility_heartbeat_boundary_verified",
            cancellation_mode=cancellation_mode,
            receipt_payload_sha256=geographic_eligibility_receipt[
                "receipt_payload_sha256"
            ],
            fresh_until_utc=geographic_eligibility_receipt["fresh_until_utc"],
        )
        phase = "submit_boundary_heartbeat"
        boundary_heartbeat = adapter.heartbeat()
        if boundary_heartbeat != {"status": "ok"}:
            raise RuntimeError(
                "Stage 1 network-boundary heartbeat was not acknowledged"
            )
        last_heartbeat_at = clock()
        journal.record(
            "heartbeat_network_boundary_acknowledged",
            cancellation_mode=cancellation_mode,
            status_ok=True,
        )
        phase = "submit_boundary_deadlines"
        boundary_now = wall_clock().astimezone(timezone.utc)
        geographic_eligibility_receipt = validate_geographic_eligibility_receipt(
            geographic_eligibility_receipt,
            now=boundary_now,
            require_fresh=True,
        )
        if boundary_now >= submit_deadline:
            raise RuntimeError(
                "Stage 1 submit deadline expired at the network boundary"
            )
        phase = "placement"
        journal.record("submit_started", cancellation_mode=cancellation_mode)
        response = adapter.place_order(
            intent,
            stage1_capability=stage1_capability,
            geographic_eligibility_fresh_until_utc=(
                geographic_eligibility_receipt["fresh_until_utc"]
            ),
        )
        submit_diagnostics = adapter.diagnostics()
        try:
            network_boundary = datetime.fromisoformat(
                str(submit_diagnostics["network_submit_boundary_utc"]).replace(
                    "Z", "+00:00"
                )
            ).astimezone(timezone.utc)
            adapter_deadline = datetime.fromisoformat(
                str(submit_diagnostics["submit_deadline_utc"]).replace(
                    "Z", "+00:00"
                )
            ).astimezone(timezone.utc)
            geographic_fresh_until = datetime.fromisoformat(
                str(
                    submit_diagnostics[
                        "geographic_eligibility_fresh_until_utc"
                    ]
                ).replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            geographic_checked_at = datetime.fromisoformat(
                str(geographic_eligibility_receipt["checked_at_utc"]).replace(
                    "Z", "+00:00"
                )
            ).astimezone(timezone.utc)
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Stage 1 adapter omitted network-boundary timing") from exc
        if not (
            submit_diagnostics.get("network_submit_deadline_passed") is True
            and submit_diagnostics.get(
                "post_sign_order_placement_boundary_verified"
            )
            is True
            and submit_diagnostics.get(
                "network_submit_geography_freshness_passed"
            )
            is True
            and adapter_deadline == submit_deadline
            and geographic_fresh_until
            == datetime.fromisoformat(
                str(geographic_eligibility_receipt["fresh_until_utc"]).replace(
                    "Z", "+00:00"
                )
            ).astimezone(timezone.utc)
            and geographic_checked_at <= network_boundary
            and network_boundary < submit_deadline
            and network_boundary < geographic_fresh_until
        ):
            raise RuntimeError(
                "Stage 1 network submit crossed its sealed time or geography deadline"
            )
        journal.record(
            "network_submit_boundary_verified",
            cancellation_mode=cancellation_mode,
            submit_deadline_utc=submit_deadline.isoformat(),
            geographic_eligibility_fresh_until_utc=(
                geographic_fresh_until.isoformat()
            ),
            network_submit_boundary_utc=network_boundary.isoformat(),
            post_sign_order_placement_boundary_verified=True,
        )
        order_id = _order_id(response)
        if not order_id:
            raise RuntimeError("Stage 1 placement response did not carry an order id")
        journal.record(
            "order_accepted",
            order_id=order_id,
            placement_status=str(_value(response, "status") or "").lower(),
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
        terminal_observed_at = None
        terminal_deadline = clock() + float(observation_timeout_seconds)
        while clock() <= terminal_deadline:
            user_events = adapter.user_events()
            if _contains_trade_lifecycle(user_events, order_id):
                raise RuntimeError("Stage 1 order received an unexpected trade lifecycle event")
            if _contains_terminal_cancel(user_events, order_id):
                terminal_event_observed = True
                if terminal_observed_at is None:
                    terminal_observed_at = clock()
                if clock() - terminal_observed_at >= POST_CANCEL_QUIESCENCE_SECONDS:
                    break
            sleep(poll_interval)
        if not terminal_event_observed:
            raise RuntimeError("Stage 1 cancellation was not observed on the authoritative user stream")
        if terminal_observed_at is None or clock() - terminal_observed_at < POST_CANCEL_QUIESCENCE_SECONDS:
            raise RuntimeError("Stage 1 cancellation did not retain the bounded no-fill quiescence interval")
        phase = "terminal_rest_reconciliation"
        terminal_order_evidence = _validate_terminal_rest_order(
            adapter.get_order(order_id),
            order_id=order_id,
            adapter=adapter,
        )
        account_trades = adapter.account_trades()
        scoped_trades = [
            row for row in account_trades or [] if _trade_row_contains_order(row, order_id)
        ]
        if scoped_trades:
            raise RuntimeError("Stage 1 terminal REST reconciliation found a scoped trade")
        ending_positions, ending_position_evidence = _verified_exact_positions(adapter)
        if ending_positions:
            raise RuntimeError("Stage 1 ended with unexpected outcome inventory")
        if _contains_trade_lifecycle(adapter.user_events(), order_id):
            raise RuntimeError("Stage 1 order received an unexpected trade lifecycle event")
        phase = "post_cancel_collateral_reconciliation"
        post_cancel_collateral = _action_time_collateral_snapshot(
            adapter,
            bootstrap_gate,
        )
        if post_cancel_collateral["sha256"] != submit_collateral["sha256"]:
            raise RuntimeError(
                "Stage 1 no-fill collateral balance/allowance did not reconcile exactly"
            )
        journal.record(
            "collateral_post_cancel_reconciled",
            cancellation_mode=cancellation_mode,
            submit_snapshot_sha256=submit_collateral["sha256"],
            post_cancel_snapshot_sha256=post_cancel_collateral["sha256"],
            exact_no_fill_reconciliation=True,
            balance_usdc=float(post_cancel_collateral["balance_usdc"]),
            allowance_usdc=float(post_cancel_collateral["allowance_usdc"]),
        )
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
            terminal_order_response_sha256=terminal_order_evidence["response_sha256"],
            account_trade_count=len(account_trades or []),
            scoped_trade_count=0,
            post_cancel_quiescence_seconds=POST_CANCEL_QUIESCENCE_SECONDS,
            collateral_snapshot_sha256=post_cancel_collateral["sha256"],
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
            "candidate_fee_rate": float(
                network_boundary_rule_binding["candidate_fee_rate"]
            ),
            "current_fee_rate_bps": float(
                network_boundary_rule_binding["current_fee_rate_bps"]
            ),
            "candidate_neg_risk": network_boundary_rule_binding["neg_risk"],
            "current_neg_risk": network_boundary_rules["neg_risk"],
            "submit_boundary_heartbeat_acknowledged": True,
            "submit_boundary_market_rules_verified": True,
            "submit_boundary_geography_before_heartbeat_verified": True,
            "post_sign_order_placement_boundary_verified": True,
            "submit_collateral_balance_usdc": float(
                submit_collateral["balance_usdc"]
            ),
            "submit_collateral_allowance_usdc": float(
                submit_collateral["allowance_usdc"]
            ),
            "submit_collateral_snapshot_sha256": submit_collateral["sha256"],
            "post_cancel_collateral_snapshot_sha256": post_cancel_collateral[
                "sha256"
            ],
            "collateral_no_fill_reconciliation_verified": True,
            "order_notional_usdc": float(notional),
            "order_id": order_id,
            "placement_status": str(_value(response, "status") or "").lower(),
            "open_order_observed": observed_open,
            "authoritative_user_event_observed": observed_user_event,
            "cancellation_observed": cancellation_observed,
            "cancellation_elapsed_seconds": cancellation_elapsed_seconds,
            "terminal_user_event_observed": terminal_event_observed,
            "no_trade_lifecycle_event_observed": True,
            "terminal_rest_order_verified": True,
            "terminal_rest_order_sha256": terminal_order_evidence["response_sha256"],
            "terminal_rest_zero_matched_verified": True,
            "account_trades_rest_verified": True,
            "scoped_account_trade_count": 0,
            "post_cancel_quiescence_seconds": POST_CANCEL_QUIESCENCE_SECONDS,
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
            terminal_rest_order_verified=True,
            account_trades_rest_verified=True,
            post_cancel_quiescence_seconds=POST_CANCEL_QUIESCENCE_SECONDS,
            collateral_no_fill_reconciliation_verified=True,
            collateral_snapshot_sha256=post_cancel_collateral["sha256"],
        )
        result["journal_sha256"] = journal.sha256()
        return result
    except BaseException as exc:
        cleanup_succeeded = False
        cleanup_zero_open_orders = False
        cleanup_zero_positions = False
        try:
            adapter.cancel_all()
            cleanup_zero_open_orders = not bool(adapter.open_orders())
            cleanup_positions, _ = _verified_exact_positions(adapter)
            cleanup_zero_positions = not bool(cleanup_positions)
            cleanup_succeeded = cleanup_zero_open_orders and cleanup_zero_positions
        except BaseException:
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
        except BaseException:
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
        "market_rules_submit_adjacent_verified",
        "collateral_submit_adjacent_verified",
        "submit_deadline_verified",
        "geographic_eligibility_submit_boundary_verified",
        "market_rules_network_boundary_verified",
        "geographic_eligibility_heartbeat_boundary_verified",
        "heartbeat_network_boundary_acknowledged",
        "submit_started",
        "network_submit_boundary_verified",
        "order_accepted",
        "order_observed",
        "cancellation_started",
        "pre_cancellation_heartbeat_acknowledged",
        "collateral_post_cancel_reconciled",
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
    intents = matching("intent_prepared")
    submit_rules = matching("market_rules_submit_adjacent_verified")
    submit_collateral = matching("collateral_submit_adjacent_verified")
    post_cancel_collateral = matching("collateral_post_cancel_reconciled")
    deadlines = matching("submit_deadline_verified")
    geographic_boundaries = matching(
        "geographic_eligibility_submit_boundary_verified"
    )
    network_rules = matching("market_rules_network_boundary_verified")
    heartbeat_geographies = matching(
        "geographic_eligibility_heartbeat_boundary_verified"
    )
    network_heartbeats = matching("heartbeat_network_boundary_acknowledged")
    submits = matching("submit_started")
    boundaries = matching("network_submit_boundary_verified")
    accepted = matching("order_accepted")
    observed = matching("order_observed")
    cancelled = matching("cancellation_verified")
    passed = matching("probe_passed")
    intent_row = intents[0] if len(intents) == 1 else {}
    deadline_row = deadlines[0] if len(deadlines) == 1 else {}
    submit_row = submits[0] if len(submits) == 1 else {}
    boundary_row = boundaries[0] if len(boundaries) == 1 else {}
    try:
        deadline_utc = datetime.fromisoformat(
            str(deadline_row.get("submit_deadline_utc")).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        boundary_utc = datetime.fromisoformat(
            str(boundary_row.get("network_submit_boundary_utc")).replace(
                "Z", "+00:00"
            )
        ).astimezone(timezone.utc)
        geographic_fresh_until_utc = datetime.fromisoformat(
            str(
                (geographic_boundaries[0] if geographic_boundaries else {}).get(
                    "fresh_until_utc"
                )
            ).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        geographic_checked_at_utc = datetime.fromisoformat(
            str(
                (geographic_boundaries[0] if geographic_boundaries else {}).get(
                    "checked_at_utc"
                )
            ).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        boundary_geographic_fresh_until_utc = datetime.fromisoformat(
            str(
                boundary_row.get("geographic_eligibility_fresh_until_utc")
            ).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    except (IndexError, TypeError, ValueError):
        deadline_utc = boundary_utc = geographic_fresh_until_utc = datetime.max.replace(
            tzinfo=timezone.utc
        )
        boundary_geographic_fresh_until_utc = datetime.max.replace(
            tzinfo=timezone.utc
        )
        geographic_checked_at_utc = datetime.min.replace(tzinfo=timezone.utc)
    event_index = {
        event_type: event_types.index(event_type)
        for event_type in required_types
        if event_types.count(event_type) == 1
    }
    valid = all((
        len(authorized) == 1,
        authorized[0].get("bootstrap_sha256") == bootstrap_sha256,
        authorized[0].get("cancellation_mode") == mode,
        len(starts) == 1,
        starts[0].get("zero_open_orders") is True,
        starts[0].get("zero_positions") is True,
        len(intents) == 1,
        intent_row.get("cancellation_mode") == mode,
        len(submit_rules) == 1,
        submit_rules[0].get("cancellation_mode") == mode,
        submit_rules[0].get("token_id") == str(result.get("token_id") or ""),
        submit_rules[0].get("candidate_fee_rate") == result.get("candidate_fee_rate"),
        submit_rules[0].get("current_fee_rate_bps") == result.get("current_fee_rate_bps"),
        submit_rules[0].get("candidate_neg_risk") is result.get("candidate_neg_risk"),
        submit_rules[0].get("current_neg_risk") is result.get("current_neg_risk"),
        len(submit_collateral) == 1,
        submit_collateral[0].get("cancellation_mode") == mode,
        submit_collateral[0].get("snapshot_sha256")
        == result.get("submit_collateral_snapshot_sha256"),
        submit_collateral[0].get("balance_usdc")
        == result.get("submit_collateral_balance_usdc"),
        submit_collateral[0].get("allowance_usdc")
        == result.get("submit_collateral_allowance_usdc"),
        len(post_cancel_collateral) == 1,
        post_cancel_collateral[0].get("cancellation_mode") == mode,
        post_cancel_collateral[0].get("exact_no_fill_reconciliation") is True,
        post_cancel_collateral[0].get("submit_snapshot_sha256")
        == result.get("submit_collateral_snapshot_sha256"),
        post_cancel_collateral[0].get("post_cancel_snapshot_sha256")
        == result.get("post_cancel_collateral_snapshot_sha256"),
        result.get("submit_collateral_snapshot_sha256")
        == result.get("post_cancel_collateral_snapshot_sha256"),
        result.get("collateral_no_fill_reconciliation_verified") is True,
        len(deadlines) == 1,
        deadline_row.get("cancellation_mode") == mode,
        len(geographic_boundaries) == 1,
        geographic_boundaries[0].get("cancellation_mode") == mode,
        _is_sha256(geographic_boundaries[0].get("receipt_payload_sha256")),
        len(network_rules) == 1,
        network_rules[0].get("cancellation_mode") == mode,
        network_rules[0].get("token_id") == str(result.get("token_id") or ""),
        network_rules[0].get("candidate_fee_rate")
        == result.get("candidate_fee_rate"),
        network_rules[0].get("current_fee_rate_bps")
        == result.get("current_fee_rate_bps"),
        network_rules[0].get("candidate_neg_risk")
        is result.get("candidate_neg_risk"),
        network_rules[0].get("current_neg_risk") is result.get("current_neg_risk"),
        len(heartbeat_geographies) == 1,
        heartbeat_geographies[0].get("cancellation_mode") == mode,
        heartbeat_geographies[0].get("receipt_payload_sha256")
        == geographic_boundaries[0].get("receipt_payload_sha256"),
        heartbeat_geographies[0].get("fresh_until_utc")
        == geographic_boundaries[0].get("fresh_until_utc"),
        len(network_heartbeats) == 1,
        network_heartbeats[0].get("cancellation_mode") == mode,
        network_heartbeats[0].get("status_ok") is True,
        result.get("submit_boundary_market_rules_verified") is True,
        result.get("submit_boundary_geography_before_heartbeat_verified") is True,
        result.get("submit_boundary_heartbeat_acknowledged") is True,
        len(submits) == 1,
        submit_row.get("cancellation_mode") == mode,
        len(boundaries) == 1,
        boundary_row.get("cancellation_mode") == mode,
        boundary_row.get("post_sign_order_placement_boundary_verified") is True,
        result.get("post_sign_order_placement_boundary_verified") is True,
        boundary_row.get("submit_deadline_utc")
        == deadline_row.get("submit_deadline_utc"),
        boundary_geographic_fresh_until_utc == geographic_fresh_until_utc,
        geographic_checked_at_utc <= boundary_utc,
        boundary_utc < deadline_utc,
        boundary_utc < geographic_fresh_until_utc,
        len(accepted) == 1,
        accepted[0].get("order_id") == order_id,
        all(
            name in event_index
            for name in (
                "intent_prepared",
                "market_rules_submit_adjacent_verified",
                "collateral_submit_adjacent_verified",
                "submit_deadline_verified",
                "geographic_eligibility_submit_boundary_verified",
                "market_rules_network_boundary_verified",
                "geographic_eligibility_heartbeat_boundary_verified",
                "heartbeat_network_boundary_acknowledged",
                "submit_started",
                "network_submit_boundary_verified",
                "order_accepted",
            )
        ),
        (
            event_index.get("intent_prepared", -1)
            < event_index.get("market_rules_submit_adjacent_verified", -1)
            < event_index.get("collateral_submit_adjacent_verified", -1)
            < event_index.get("submit_deadline_verified", -1)
            < event_index.get(
                "geographic_eligibility_submit_boundary_verified", -1
            )
            < event_index.get("market_rules_network_boundary_verified", -1)
            < event_index.get(
                "geographic_eligibility_heartbeat_boundary_verified", -1
            )
            < event_index.get("heartbeat_network_boundary_acknowledged", -1)
            < event_index.get("submit_started", -1)
            < event_index.get("network_submit_boundary_verified", -1)
            < event_index.get("order_accepted", -1)
        ),
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
            and row.get("terminal_order_response_sha256")
            == result.get("terminal_rest_order_sha256")
            and row.get("scoped_trade_count") == 0
            and row.get("post_cancel_quiescence_seconds")
            == POST_CANCEL_QUIESCENCE_SECONDS
            and row.get("collateral_snapshot_sha256")
            == result.get("post_cancel_collateral_snapshot_sha256")
            for row in cancelled
        ),
        any(
            row.get("order_id") == order_id
            and row.get("cancellation_mode") == mode
            and row.get("zero_open_orders_verified") is True
            and row.get("zero_positions_verified") is True
            and row.get("terminal_rest_order_verified") is True
            and row.get("account_trades_rest_verified") is True
            and row.get("post_cancel_quiescence_seconds")
            == POST_CANCEL_QUIESCENCE_SECONDS
            and row.get("collateral_no_fill_reconciliation_verified") is True
            and row.get("collateral_snapshot_sha256")
            == result.get("post_cancel_collateral_snapshot_sha256")
            for row in passed
        ),
        event_index.get("order_accepted", -1)
        < event_index.get("collateral_post_cancel_reconciled", -1)
        < event_index.get("cancellation_verified", -1)
        < event_index.get("probe_passed", -1),
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

    if (
        not isinstance(bootstrap_gate, dict)
        or not bootstrap_gate.get("ok")
        or bootstrap_gate.get("schema_version") != BOOTSTRAP_SCHEMA_VERSION
    ):
        raise RuntimeError("Stage 1 lifecycle bundle requires a passing bootstrap gate")
    bootstrap_sha256 = _canonical_hash(bootstrap_gate)
    results = {
        "cancel_all": dict(cancel_all_result or {}),
        "dead_man": dict(dead_man_result or {}),
    }
    journal_evidence = {}
    stream_journal_evidence = {}
    requested_budget = Decimal(str(bootstrap_gate.get("requested_budget_usdc")))
    wallet_cap = Decimal(str(bootstrap_gate.get("pilot_wallet_max_funding_usdc")))
    operator_cap = Decimal(str(MAX_OPERATOR_PILOT_BUDGET_USDC))
    if not all((
        requested_budget.is_finite(),
        wallet_cap.is_finite(),
        requested_budget == MAX_STAGE1_ORDER_NOTIONAL,
        requested_budget <= wallet_cap <= operator_cap,
    )):
        raise RuntimeError("Stage 1 lifecycle bundle exceeds the operator wallet or budget cap")
    for mode, result in results.items():
        try:
            notional = Decimal(str(result.get("order_notional_usdc")))
            elapsed = Decimal(str(result.get("cancellation_elapsed_seconds")))
            candidate_fee_rate = Decimal(str(result.get("candidate_fee_rate")))
            current_fee_rate_bps = Decimal(str(result.get("current_fee_rate_bps")))
            collateral_balance = Decimal(
                str(result.get("submit_collateral_balance_usdc"))
            )
            collateral_allowance = Decimal(
                str(result.get("submit_collateral_allowance_usdc"))
            )
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
            "heartbeat": result.get("heartbeat_acknowledged") is True,
            "submit_boundary_heartbeat": result.get(
                "submit_boundary_heartbeat_acknowledged"
            ) is True,
            "submit_boundary_market_rules": result.get(
                "submit_boundary_market_rules_verified"
            ) is True,
            "submit_boundary_geography_before_heartbeat": result.get(
                "submit_boundary_geography_before_heartbeat_verified"
            ) is True,
            "post_sign_order_placement_boundary": result.get(
                "post_sign_order_placement_boundary_verified"
            )
            is True,
            "action_time_market_rules": (
                candidate_fee_rate.is_finite()
                and candidate_fee_rate >= 0
                and current_fee_rate_bps.is_finite()
                and current_fee_rate_bps >= 0
                and candidate_fee_rate == current_fee_rate_bps / Decimal("10000")
                and isinstance(result.get("candidate_neg_risk"), bool)
                and result.get("candidate_neg_risk")
                is result.get("current_neg_risk")
            ),
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
            "action_time_collateral": (
                collateral_balance.is_finite()
                and requested_budget <= collateral_balance <= wallet_cap
                and collateral_allowance.is_finite()
                and collateral_allowance >= requested_budget
            ),
            "collateral_reconciliation": (
                result.get("collateral_no_fill_reconciliation_verified") is True
                and _is_sha256(result.get("submit_collateral_snapshot_sha256"))
                and result.get("submit_collateral_snapshot_sha256")
                == result.get("post_cancel_collateral_snapshot_sha256")
            ),
            "cancellation": result.get("cancellation_observed") is True,
            "terminal": result.get("terminal_user_event_observed") is True,
            "no_trade": result.get("no_trade_lifecycle_event_observed") is True,
            "terminal_rest_order": result.get("terminal_rest_order_verified") is True,
            "terminal_rest_order_hash": _is_sha256(
                result.get("terminal_rest_order_sha256")
            ),
            "terminal_rest_zero_matched": result.get(
                "terminal_rest_zero_matched_verified"
            ) is True,
            "account_trades_rest": result.get("account_trades_rest_verified") is True,
            "scoped_account_trades": result.get("scoped_account_trade_count") == 0,
            "quiescence": result.get("post_cancel_quiescence_seconds")
            == POST_CANCEL_QUIESCENCE_SECONDS,
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
        stream_journal_evidence[mode] = verify_stage1_user_stream_journal(
            result.get("user_stream_journal_path"),
            result,
        )
        if not all((
            type(result.get("user_stream_journal_row_count")) is int,
            result.get("user_stream_journal_row_count")
            == stream_journal_evidence[mode]["row_count"],
            type(result.get("user_stream_scoped_order_event_count")) is int,
            result.get("user_stream_scoped_order_event_count")
            == stream_journal_evidence[mode]["scoped_order_event_count"],
        )):
            raise RuntimeError(
                f"Stage 1 {mode} result does not bind the final user-stream journal counts"
            )

    if results["cancel_all"]["order_id"] == results["dead_man"]["order_id"]:
        raise RuntimeError("Stage 1 cancellation modes must use distinct orders")
    if journal_evidence["cancel_all"]["path"] == journal_evidence["dead_man"]["path"]:
        raise RuntimeError("Stage 1 cancellation modes must use distinct journals")
    if journal_evidence["cancel_all"]["sha256"] == journal_evidence["dead_man"]["sha256"]:
        raise RuntimeError("Stage 1 cancellation journals must have distinct content")
    if stream_journal_evidence["cancel_all"]["path"] == stream_journal_evidence["dead_man"]["path"]:
        raise RuntimeError("Stage 1 cancellation modes must use distinct user-stream journals")
    if stream_journal_evidence["cancel_all"]["sha256"] == stream_journal_evidence["dead_man"]["sha256"]:
        raise RuntimeError("Stage 1 user-stream journals must have distinct content")

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
        "lifecycle_results": results,
        "journal_evidence": journal_evidence,
        "user_stream_journal_evidence": stream_journal_evidence,
        "derived_platform_evidence": {
            "starting_open_orders_rest_verified": True,
            "order_update_verified": True,
            "fill_event_verified": False,
            "no_fill_lifecycle_verified": True,
            "final_state_reconciliation_verified": True,
            "terminal_order_rest_verified": True,
            "account_trades_rest_verified": True,
            "final_user_stream_journals_verified": True,
            "action_time_collateral_verified": True,
            "no_fill_collateral_reconciliation_verified": True,
            "cancel_all_request_verified": True,
            "cancel_all_zero_open_orders_verified": True,
            "dead_man_automatic_cancel_verified": True,
            "heartbeat_acknowledgment_verified": True,
        },
        "secret_values_redacted": True,
    }
    payload["bundle_sha256"] = _canonical_hash(payload)
    return payload
