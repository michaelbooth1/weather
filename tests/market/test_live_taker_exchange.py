from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import inspect

import pytest

import weather.market.live_taker_exchange as exchange_module
from weather.market.live_taker_exchange import (
    AccountSnapshot,
    AdapterCapabilities,
    BookLevel,
    BookSnapshot,
    EvidenceGrade,
    ExchangeBoundaryError,
    FixtureLiveTakerExchange,
    FokSubmissionOutcome,
    FokYesBuyRequest,
    InvalidExchangeData,
    LiveTakerExchange,
    NullLiveTakerExchange,
    OrderSnapshot,
    OrderStatus,
    REVIEWED_RISK_POLICY_SHA256,
    SimulationEvidenceOnly,
    StaleExchangeSnapshot,
    SubmissionDisabled,
    SubmissionMode,
    SubmissionReceipt,
    UncertainSubmission,
)
from weather.market.live_taker_risk import CanaryStage


NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
TOKEN_ID = "12345678901234567890"
EVENT_ID = "highest-temperature-test-event"
ACCOUNT_DIGEST = "sha256:" + "a" * 64
ACCOUNT_SHA = "b" * 64
BOOK_SHA = "c" * 64
REQUEST_SHA = "d" * 64
RELEASE_SHA = "e" * 64
INPUT_SHA = "f" * 64
POLICY_SHA = REVIEWED_RISK_POLICY_SHA256
RISK_DECISION_SHA = "9" * 64
IDEMPOTENCY_KEY = "capital-canary:" + "2" * 64


def valid_account(**overrides):
    values = {
        "platform": "polymarket_global",
        "account_identity_redacted": ACCOUNT_DIGEST,
        "observed_at_utc": NOW - timedelta(seconds=5),
        "snapshot_sha256": ACCOUNT_SHA,
        "reconciled": True,
        "external_flows_reconciled": True,
        "collateral_balance_usdc": Decimal("75"),
        "cash_available_usdc": Decimal("75"),
        "allowance_usdc": Decimal("75"),
        "open_order_count": 0,
        "unsettled_position_count": 0,
    }
    values.update(overrides)
    return AccountSnapshot(**values)


def valid_book(**overrides):
    values = {
        "platform": "polymarket_global",
        "event_id": EVENT_ID,
        "token_id": TOKEN_ID,
        "observed_at_utc": NOW - timedelta(seconds=1),
        "closes_at_utc": NOW + timedelta(hours=1),
        "snapshot_sha256": BOOK_SHA,
        "active": True,
        "accepting_orders": True,
        "tick_size_usdc_per_share": Decimal("0.01"),
        "minimum_order_quantity_shares": Decimal("0.1"),
        "quantity_step_shares": Decimal("0.1"),
        "bids": (
            BookLevel(Decimal("0.89"), Decimal("100")),
            BookLevel(Decimal("0.88"), Decimal("100")),
        ),
        "asks": (
            BookLevel(Decimal("0.90"), Decimal("100")),
            BookLevel(Decimal("0.91"), Decimal("100")),
        ),
    }
    values.update(overrides)
    return BookSnapshot(**values)


def valid_request(**overrides):
    values = {
        "intent_sequence": 1,
        "risk_stage": CanaryStage.LIFECYCLE,
        "created_at_utc": NOW,
        "account": valid_account(),
        "book": valid_book(),
        "approved_quantity_shares": Decimal("0.5"),
        "fok_buy_amount_usdc": Decimal("0.45"),
        "worst_price_usdc_per_share": Decimal("0.91"),
        "fee_reserve_usdc": Decimal("0.01"),
        "max_total_debit_usdc": Decimal("0.46"),
        "release_manifest_sha256": RELEASE_SHA,
        "input_snapshot_sha256": INPUT_SHA,
        "risk_policy_sha256": POLICY_SHA,
        "risk_decision_sha256": RISK_DECISION_SHA,
    }
    identity_overrides = {
        key: overrides.pop(key)
        for key in ("idempotency_key", "request_sha256")
        if key in overrides
    }
    values.update(overrides)
    request = FokYesBuyRequest.build(**values)
    return replace(request, **identity_overrides) if identity_overrides else request


def filled_receipt(**overrides):
    request = valid_request()
    values = {
        "adapter_id": "official-client",
        "platform": "polymarket_global",
        "idempotency_key": request.idempotency_key,
        "request_sha256": request.request_sha256,
        "outcome": FokSubmissionOutcome.FILLED,
        "submitted_at_utc": NOW,
        "acknowledged_at_utc": NOW + timedelta(milliseconds=100),
        "reason_code": "FOK_FILLED",
        "evidence_grade": EvidenceGrade.RECONCILED,
        "simulation_only": False,
        "exchange_order_id": "order-123",
        "filled_quantity_shares": Decimal("0.5"),
        "filled_principal_usdc": Decimal("0.45"),
        "average_fill_price_usdc_per_share": Decimal("0.90"),
        "fee_paid_usdc": Decimal("0.01"),
        "total_debit_usdc": Decimal("0.46"),
    }
    values.update(overrides)
    return SubmissionReceipt(**values)


def rejected_receipt(**overrides):
    request = valid_request()
    values = {
        "adapter_id": "official-client",
        "platform": "polymarket_global",
        "idempotency_key": request.idempotency_key,
        "request_sha256": request.request_sha256,
        "outcome": FokSubmissionOutcome.REJECTED,
        "submitted_at_utc": NOW,
        "acknowledged_at_utc": NOW + timedelta(milliseconds=100),
        "reason_code": "FOK_REJECTED",
        "evidence_grade": EvidenceGrade.RECONCILED,
        "simulation_only": False,
    }
    values.update(overrides)
    return SubmissionReceipt(**values)


def valid_order(**overrides):
    values = {
        "adapter_id": "fixture",
        "platform": "polymarket_global",
        "exchange_order_id": "order-123",
        "token_id": TOKEN_ID,
        "observed_at_utc": NOW,
        "snapshot_sha256": "3" * 64,
        "status": OrderStatus.FILLED,
        "idempotency_key": IDEMPOTENCY_KEY,
        "request_sha256": REQUEST_SHA,
        "filled_quantity_shares": Decimal("1"),
        "filled_principal_usdc": Decimal("0.90"),
        "average_fill_price_usdc_per_share": Decimal("0.90"),
        "fee_paid_usdc": Decimal("0.01"),
    }
    status = overrides.get("status", values["status"])
    fill_fields = {
        "filled_quantity_shares",
        "filled_principal_usdc",
        "average_fill_price_usdc_per_share",
        "fee_paid_usdc",
    }
    if status in {OrderStatus.OPEN, OrderStatus.REJECTED, OrderStatus.CANCELED} and not (
        fill_fields & overrides.keys()
    ):
        values.update(
            {
                "filled_quantity_shares": None,
                "filled_principal_usdc": None,
                "average_fill_price_usdc_per_share": None,
                "fee_paid_usdc": None,
            }
        )
    values.update(overrides)
    return OrderSnapshot(**values)


def test_module_has_no_network_sdk_environment_or_filesystem_imports():
    tree = ast.parse(inspect.getsource(exchange_module))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots.isdisjoint(
        {
            "dotenv",
            "httpx",
            "os",
            "pathlib",
            "py_clob_client",
            "requests",
            "socket",
            "web3",
            "websocket",
        }
    )


def test_dtos_are_frozen_and_keep_share_and_dollar_units_separate():
    request = valid_request()

    with pytest.raises(FrozenInstanceError):
        request.fok_buy_amount_usdc = Decimal("1")

    assert request.approved_quantity_shares == Decimal("0.5")
    assert request.fok_buy_amount_usdc == Decimal("0.45")
    assert request.max_total_debit_usdc == Decimal("0.46")
    assert request.token_id == TOKEN_ID
    assert request.event_id == EVENT_ID


@pytest.mark.parametrize(
    ("factory", "field", "value"),
    [
        (BookLevel, "price_usdc_per_share", 0.9),
        (BookLevel, "quantity_shares", 1.0),
        (valid_account, "collateral_balance_usdc", 75.0),
        (valid_account, "cash_available_usdc", 75.0),
        (valid_account, "allowance_usdc", 75.0),
        (valid_request, "approved_quantity_shares", 0.5),
        (valid_request, "fok_buy_amount_usdc", 0.45),
        (valid_request, "worst_price_usdc_per_share", 0.91),
        (valid_request, "fee_reserve_usdc", 0.01),
        (valid_request, "max_total_debit_usdc", 0.46),
        (filled_receipt, "filled_quantity_shares", 0.5),
        (filled_receipt, "filled_principal_usdc", 0.45),
        (filled_receipt, "average_fill_price_usdc_per_share", 0.9),
        (filled_receipt, "fee_paid_usdc", 0.01),
        (filled_receipt, "total_debit_usdc", 0.46),
    ],
)
def test_float_money_and_quantity_are_rejected(factory, field, value):
    if factory is BookLevel:
        kwargs = {
            "price_usdc_per_share": Decimal("0.9"),
            "quantity_shares": Decimal("1"),
        }
        kwargs[field] = value
        call = lambda: factory(**kwargs)
    else:
        call = lambda: factory(**{field: value})

    with pytest.raises(InvalidExchangeData, match="Decimal"):
        call()


@pytest.mark.parametrize(
    "value",
    [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")],
)
def test_nonfinite_decimal_values_are_rejected(value):
    with pytest.raises(InvalidExchangeData, match="finite"):
        BookLevel(value, Decimal("1"))


def test_account_rejects_raw_or_truncated_identity_and_unknown_platform():
    with pytest.raises(InvalidExchangeData, match="full SHA-256"):
        valid_account(account_identity_redacted="0x" + "a" * 40)
    with pytest.raises(InvalidExchangeData, match="full SHA-256"):
        valid_account(account_identity_redacted="sha256:abcd")
    with pytest.raises(InvalidExchangeData, match="unsupported"):
        valid_account(platform="unknown")


def test_identifiers_and_hashes_are_strict():
    with pytest.raises(InvalidExchangeData, match="decimal CLOB token"):
        valid_book(token_id="token-123")
    with pytest.raises(InvalidExchangeData, match="event_id"):
        valid_book(event_id="event/with/path")
    with pytest.raises(InvalidExchangeData, match="SHA-256"):
        valid_book(snapshot_sha256="ABC")
    with pytest.raises(InvalidExchangeData, match="idempotency_key"):
        valid_request(idempotency_key="retry-me")
    with pytest.raises(InvalidExchangeData, match="exchange_order_id"):
        filled_receipt(exchange_order_id="order id with spaces")
    with pytest.raises(InvalidExchangeData, match="reason_code"):
        filled_receipt(reason_code="raw server said something")


def test_timestamps_must_be_timezone_aware():
    naive = NOW.replace(tzinfo=None)

    with pytest.raises(InvalidExchangeData, match="timezone-aware"):
        valid_account(observed_at_utc=naive)
    with pytest.raises(InvalidExchangeData, match="timezone-aware"):
        valid_book(observed_at_utc=naive)
    with pytest.raises(InvalidExchangeData, match="timezone-aware"):
        valid_request(created_at_utc=naive)
    with pytest.raises(InvalidExchangeData, match="timezone-aware"):
        filled_receipt(acknowledged_at_utc=naive)


def test_book_requires_immutable_sorted_unique_tick_aligned_levels():
    with pytest.raises(InvalidExchangeData, match="immutable tuples"):
        valid_book(asks=[BookLevel(Decimal("0.90"), Decimal("100"))])
    with pytest.raises(InvalidExchangeData, match="ascending"):
        valid_book(
            asks=(
                BookLevel(Decimal("0.91"), Decimal("100")),
                BookLevel(Decimal("0.90"), Decimal("100")),
            )
        )
    with pytest.raises(InvalidExchangeData, match="unique ascending"):
        valid_book(
            asks=(
                BookLevel(Decimal("0.90"), Decimal("100")),
                BookLevel(Decimal("0.90"), Decimal("50")),
            )
        )
    with pytest.raises(InvalidExchangeData, match="tick"):
        valid_book(asks=(BookLevel(Decimal("0.905"), Decimal("100")),))
    with pytest.raises(InvalidExchangeData, match="crossed or locked"):
        valid_book(bids=(BookLevel(Decimal("0.90"), Decimal("100")),))


@pytest.mark.parametrize(
    ("account_overrides", "book_overrides", "message"),
    [
        ({"observed_at_utc": NOW - timedelta(seconds=16)}, {}, "account observation is stale"),
        ({}, {"observed_at_utc": NOW - timedelta(seconds=3)}, "book observation is stale"),
        ({"observed_at_utc": NOW + timedelta(seconds=2)}, {}, "account observation is implausibly"),
        ({}, {"observed_at_utc": NOW + timedelta(seconds=2)}, "book observation is implausibly"),
    ],
)
def test_request_fails_closed_on_stale_or_future_inputs(
    account_overrides,
    book_overrides,
    message,
):
    with pytest.raises(StaleExchangeSnapshot, match=message):
        valid_request(
            account=valid_account(**account_overrides),
            book=valid_book(**book_overrides),
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"reconciled": False}, "not fully reconciled"),
        ({"external_flows_reconciled": False}, "not fully reconciled"),
        ({"cash_available_usdc": None}, "unknown submission inputs"),
        ({"allowance_usdc": None}, "unknown submission inputs"),
        ({"open_order_count": None}, "unknown submission inputs"),
        ({"unsettled_position_count": None}, "unknown submission inputs"),
        ({"open_order_count": 1}, "open exchange orders"),
        ({"cash_available_usdc": Decimal("0.45")}, "available cash is insufficient"),
        ({"allowance_usdc": Decimal("0.45")}, "allowance is insufficient"),
    ],
)
def test_request_fails_closed_on_unreconciled_or_insufficient_account(overrides, message):
    with pytest.raises(InvalidExchangeData, match=message):
        valid_request(account=valid_account(**overrides))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"active": False}, "not active"),
        ({"accepting_orders": False}, "not active"),
        ({"bids": ()}, "two-sided"),
        ({"asks": ()}, "two-sided"),
        ({"closes_at_utc": NOW + timedelta(minutes=9)}, "too close"),
        (
            {"bids": (BookLevel(Decimal("0.88"), Decimal("100")),)},
            "spread exceeds",
        ),
    ],
)
def test_request_fails_closed_on_unsafe_book(overrides, message):
    with pytest.raises(InvalidExchangeData, match=message):
        valid_request(book=valid_book(**overrides))


def test_request_rejects_platform_tick_step_minimum_and_unit_mismatches():
    with pytest.raises(InvalidExchangeData, match="platforms do not match"):
        valid_request(account=valid_account(platform="polymarket_us"))
    with pytest.raises(InvalidExchangeData, match="below the venue minimum"):
        valid_request(
            book=valid_book(minimum_order_quantity_shares=Decimal("2")),
        )
    with pytest.raises(InvalidExchangeData, match="venue step"):
        valid_request(
            approved_quantity_shares=Decimal("0.55"),
            fok_buy_amount_usdc=Decimal("0.45"),
        )
    with pytest.raises(InvalidExchangeData, match="venue tick"):
        valid_request(worst_price_usdc_per_share=Decimal("0.905"))
    with pytest.raises(InvalidExchangeData, match="exactly equal"):
        valid_request(max_total_debit_usdc=Decimal("0.47"))
    with pytest.raises(InvalidExchangeData, match="more than the approved shares"):
        valid_request(fok_buy_amount_usdc=Decimal("0.46"), max_total_debit_usdc=Decimal("0.47"))


def test_request_rejects_venue_buy_amount_below_minimum_at_worst_price():
    with pytest.raises(InvalidExchangeData, match="below the minimum at worst price"):
        valid_request(
            book=valid_book(minimum_order_quantity_shares=Decimal("0.5")),
            approved_quantity_shares=Decimal("1"),
            fok_buy_amount_usdc=Decimal("0.45"),
        )


def test_request_rejects_top_ask_concentration_and_reviewed_stage_cap():
    with pytest.raises(InvalidExchangeData, match="ten percent"):
        valid_request(
            book=valid_book(
                asks=(
                    BookLevel(Decimal("0.90"), Decimal("4")),
                    BookLevel(Decimal("0.91"), Decimal("100")),
                )
            )
        )
    with pytest.raises(InvalidExchangeData, match="stage order cap"):
        valid_request(
            approved_quantity_shares=Decimal("1"),
            fok_buy_amount_usdc=Decimal("0.90"),
            fee_reserve_usdc=Decimal("0"),
            max_total_debit_usdc=Decimal("0.90"),
        )


def test_request_rejects_alpha_stage_cap_and_full_position_budget():
    with pytest.raises(InvalidExchangeData, match="stage order cap"):
        valid_request(
            risk_stage=CanaryStage.ALPHA,
            approved_quantity_shares=Decimal("0.9"),
            fok_buy_amount_usdc=Decimal("0.75"),
            fee_reserve_usdc=Decimal("0.01"),
            max_total_debit_usdc=Decimal("0.76"),
        )
    with pytest.raises(InvalidExchangeData, match="position cap is already full"):
        valid_request(
            risk_stage=CanaryStage.ALPHA,
            account=valid_account(unsettled_position_count=4),
        )


def test_request_rejects_lifecycle_position_and_price_outside_reviewed_lane():
    with pytest.raises(InvalidExchangeData, match="zero unsettled positions"):
        valid_request(account=valid_account(unsettled_position_count=1))
    with pytest.raises(InvalidExchangeData, match="reviewed canary lane"):
        valid_request(worst_price_usdc_per_share=Decimal("0.98"))


def test_request_requires_reviewed_policy_and_exact_risk_decision_binding():
    with pytest.raises(InvalidExchangeData, match="reviewed canary risk policy"):
        valid_request(risk_policy_sha256="8" * 64)
    with pytest.raises((InvalidExchangeData, ValueError), match="risk_decision"):
        valid_request(risk_decision_sha256="not-a-hash")

    request = valid_request()
    with pytest.raises(InvalidExchangeData, match="idempotency_key does not bind"):
        replace(request, risk_decision_sha256="7" * 64)


def test_request_rejects_well_formed_but_content_mismatched_identifiers():
    with pytest.raises(InvalidExchangeData, match="idempotency_key does not bind"):
        valid_request(idempotency_key="capital-canary:" + "7" * 64)
    with pytest.raises(InvalidExchangeData, match="request_sha256 does not bind"):
        valid_request(request_sha256="7" * 64)


def test_request_is_revalidated_at_submission_time():
    request = valid_request()

    request.require_submission_ready(submitted_at_utc=NOW + timedelta(seconds=1))
    with pytest.raises(StaleExchangeSnapshot, match="book observation is stale"):
        request.require_submission_ready(submitted_at_utc=NOW + timedelta(seconds=2))


def test_order_snapshot_reconciles_decimal_fill_and_rejects_uncertain_terminal_state():
    filled = valid_order()
    filled.require_known_fok_terminal(at_utc=NOW + timedelta(seconds=1))

    for status in (OrderStatus.OPEN, OrderStatus.PARTIAL, OrderStatus.UNKNOWN):
        uncertain = valid_order(status=status)
        with pytest.raises(UncertainSubmission, match="not a known terminal"):
            uncertain.require_known_fok_terminal(at_utc=NOW)

    with pytest.raises(StaleExchangeSnapshot, match="order observation is stale"):
        filled.require_known_fok_terminal(at_utc=NOW + timedelta(seconds=16))
    with pytest.raises(InvalidExchangeData, match="arithmetic"):
        valid_order(filled_principal_usdc=Decimal("0.89"))


def test_order_snapshot_status_cannot_hide_or_invent_fok_fills():
    with pytest.raises(InvalidExchangeData, match="filled order requires"):
        valid_order(
            status=OrderStatus.FILLED,
            filled_quantity_shares=None,
            filled_principal_usdc=None,
            average_fill_price_usdc_per_share=None,
            fee_paid_usdc=None,
        )
    with pytest.raises(InvalidExchangeData, match="partial order requires"):
        valid_order(
            status=OrderStatus.PARTIAL,
            filled_quantity_shares=None,
            filled_principal_usdc=None,
            average_fill_price_usdc_per_share=None,
            fee_paid_usdc=None,
        )
    for status in (OrderStatus.OPEN, OrderStatus.REJECTED, OrderStatus.CANCELED):
        with pytest.raises(InvalidExchangeData, match="cannot contain a fill"):
            valid_order(status=status, filled_quantity_shares=Decimal("1"))


def test_filled_and_rejected_receipts_can_be_known_reconciled_terminal_results():
    request = valid_request()
    filled = filled_receipt()
    rejected = rejected_receipt()

    filled.require_capital_terminal(request)
    rejected.require_capital_terminal(request)
    assert filled.capital_grade_evidence is True
    assert rejected.capital_grade_evidence is True


@pytest.mark.parametrize("outcome", [FokSubmissionOutcome.UNKNOWN, FokSubmissionOutcome.PARTIAL])
def test_unknown_and_partial_receipts_fail_closed(outcome):
    request = valid_request()
    values = {
        "adapter_id": "official-client",
        "platform": "polymarket_global",
        "idempotency_key": request.idempotency_key,
        "request_sha256": request.request_sha256,
        "outcome": outcome,
        "submitted_at_utc": NOW,
        "acknowledged_at_utc": NOW,
        "reason_code": f"FOK_{outcome.value}",
        "evidence_grade": EvidenceGrade.UNVERIFIED,
        "simulation_only": False,
    }
    if outcome is FokSubmissionOutcome.PARTIAL:
        values.update(
            {
                "exchange_order_id": "order-partial",
                "filled_quantity_shares": Decimal("0.5"),
                "filled_principal_usdc": Decimal("0.45"),
                "average_fill_price_usdc_per_share": Decimal("0.90"),
                "fee_paid_usdc": Decimal("0.005"),
                "total_debit_usdc": Decimal("0.455"),
            }
        )
    receipt = SubmissionReceipt(**values)

    assert receipt.capital_grade_evidence is False
    with pytest.raises(UncertainSubmission, match="not a known terminal"):
        receipt.require_capital_terminal(request)


def test_uncertain_receipt_cannot_claim_reconciled_evidence():
    with pytest.raises(InvalidExchangeData, match="uncertain FOK"):
        SubmissionReceipt(
            adapter_id="official-client",
            platform="polymarket_global",
            idempotency_key=IDEMPOTENCY_KEY,
            request_sha256=REQUEST_SHA,
            outcome=FokSubmissionOutcome.UNKNOWN,
            submitted_at_utc=NOW,
            acknowledged_at_utc=NOW,
            reason_code="FOK_UNKNOWN",
            evidence_grade=EvidenceGrade.RECONCILED,
            simulation_only=False,
        )


def test_receipt_binding_checks_both_share_and_dollar_caps():
    request = valid_request()

    with pytest.raises(UncertainSubmission, match="shares exceed"):
        filled_receipt(
            filled_quantity_shares=Decimal("1"),
            average_fill_price_usdc_per_share=Decimal("0.45"),
        ).assert_bound_to(request)
    with pytest.raises(UncertainSubmission, match="complete BUY dollar amount"):
        filled_receipt(
            filled_quantity_shares=Decimal("0.25"),
            filled_principal_usdc=Decimal("0.225"),
            average_fill_price_usdc_per_share=Decimal("0.90"),
            fee_paid_usdc=Decimal("0.005"),
            total_debit_usdc=Decimal("0.230"),
        ).assert_bound_to(request)
    with pytest.raises(UncertainSubmission, match="reserved fee"):
        filled_receipt(
            fee_paid_usdc=Decimal("0.02"),
            total_debit_usdc=Decimal("0.47"),
        ).assert_bound_to(request)
    with pytest.raises(InvalidExchangeData, match="request hash"):
        filled_receipt(request_sha256="4" * 64).assert_bound_to(request)


def test_rejected_receipt_cannot_hide_fill_or_debit():
    with pytest.raises(InvalidExchangeData, match="cannot contain"):
        rejected_receipt(fee_paid_usdc=Decimal("0.01"), total_debit_usdc=Decimal("0.01"))


def test_public_receipt_is_bounded_normalized_and_contains_no_raw_payload():
    payload = filled_receipt().as_public_dict()

    assert payload["filled_quantity_shares"] == "0.5"
    assert payload["filled_principal_usdc"] == "0.45"
    assert payload["fee_paid_usdc"] == "0.01"
    assert payload["capital_grade_evidence"] is True
    assert not any("raw" in key or "secret" in key or "signature" in key for key in payload)


def test_adapter_capabilities_cannot_upgrade_simulation_to_capital_grade():
    with pytest.raises(InvalidExchangeData, match="cannot produce capital-grade"):
        AdapterCapabilities(
            adapter_id="fixture",
            platform="polymarket_global",
            submission_mode=SubmissionMode.SIMULATION,
            can_produce_capital_grade_evidence=True,
        )


def test_null_adapter_is_protocol_compatible_and_can_never_read_or_submit():
    adapter = NullLiveTakerExchange()

    assert isinstance(adapter, LiveTakerExchange)
    assert adapter.capabilities.submission_mode is SubmissionMode.DISABLED
    assert adapter.capabilities.supports_capital_submission is False
    with pytest.raises(SubmissionDisabled):
        adapter.read_account()
    with pytest.raises(SubmissionDisabled):
        adapter.read_book(TOKEN_ID)
    with pytest.raises(SubmissionDisabled):
        adapter.read_order("order-123")
    with pytest.raises(SubmissionDisabled):
        adapter.read_open_orders()
    with pytest.raises(SubmissionDisabled, match="cannot submit"):
        adapter.submit_fok_yes_buy(valid_request(), submitted_at_utc=NOW)


def test_fixture_adapter_is_deterministic_simulation_only_and_never_capital_grade():
    account = valid_account()
    book = valid_book()
    open_order = valid_order(exchange_order_id="order-open", status=OrderStatus.OPEN)
    closed_order = valid_order(exchange_order_id="order-closed", status=OrderStatus.CANCELED)
    configured_live_receipt = filled_receipt()
    adapter = FixtureLiveTakerExchange(
        platform="polymarket_global",
        account=account,
        books={TOKEN_ID: book},
        orders=(open_order, closed_order),
        submission_receipts=(configured_live_receipt,),
    )

    assert isinstance(adapter, LiveTakerExchange)
    assert adapter.capabilities.simulation_only is True
    assert adapter.capabilities.supports_capital_submission is False
    assert adapter.capabilities.can_produce_capital_grade_evidence is False
    assert adapter.read_account() is account
    assert adapter.read_book(TOKEN_ID) is book
    assert adapter.read_order("order-closed") is closed_order
    assert adapter.read_order("missing-order") is None
    assert adapter.read_open_orders() == (open_order,)

    request = valid_request()
    receipt = adapter.submit_fok_yes_buy(request, submitted_at_utc=NOW)

    assert adapter.submitted_requests == (request,)
    assert receipt.outcome is FokSubmissionOutcome.FILLED
    assert receipt.evidence_grade is EvidenceGrade.SIMULATION
    assert receipt.simulation_only is True
    assert receipt.capital_grade_evidence is False
    with pytest.raises(SimulationEvidenceOnly, match="not independently reconciled"):
        receipt.require_capital_terminal(request)


def test_fixture_without_configured_receipt_returns_auditable_unknown_not_fake_success():
    adapter = FixtureLiveTakerExchange(
        platform="polymarket_global",
        account=valid_account(),
        books={TOKEN_ID: valid_book()},
    )
    request = valid_request()

    receipt = adapter.submit_fok_yes_buy(request, submitted_at_utc=NOW)

    assert receipt.outcome is FokSubmissionOutcome.UNKNOWN
    assert receipt.reason_code == "FIXTURE_RESPONSE_MISSING"
    assert receipt.capital_grade_evidence is False
    with pytest.raises(UncertainSubmission):
        receipt.require_capital_terminal(request)


def test_fixture_revalidates_freshness_before_recording_simulated_submission():
    adapter = FixtureLiveTakerExchange(
        platform="polymarket_global",
        account=valid_account(),
        books={TOKEN_ID: valid_book()},
    )
    request = valid_request()

    with pytest.raises(StaleExchangeSnapshot, match="book observation is stale"):
        adapter.submit_fok_yes_buy(
            request,
            submitted_at_utc=NOW + timedelta(seconds=2),
        )
    assert adapter.submitted_requests == ()


def test_fixture_rejects_identity_mismatches_and_missing_books():
    with pytest.raises(InvalidExchangeData, match="account does not match"):
        FixtureLiveTakerExchange(
            platform="polymarket_us",
            account=valid_account(),
            books={},
        )
    with pytest.raises(InvalidExchangeData, match="book identity"):
        FixtureLiveTakerExchange(
            platform="polymarket_global",
            account=valid_account(),
            books={"999": valid_book()},
        )

    adapter = FixtureLiveTakerExchange(
        platform="polymarket_global",
        account=valid_account(),
        books={TOKEN_ID: valid_book()},
    )
    with pytest.raises(ExchangeBoundaryError, match="no normalized book"):
        adapter.read_book("999")


def test_fixture_does_not_rewrite_a_mismatched_receipt_binding():
    mismatched = filled_receipt(request_sha256="4" * 64)
    adapter = FixtureLiveTakerExchange(
        platform="polymarket_global",
        account=valid_account(),
        books={TOKEN_ID: valid_book()},
        submission_receipts=(mismatched,),
    )

    with pytest.raises(InvalidExchangeData, match="request hash"):
        adapter.submit_fok_yes_buy(valid_request(), submitted_at_utc=NOW)
