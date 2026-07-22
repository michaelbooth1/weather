from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import inspect
import json

import pytest

import weather.market.live_taker_simulation as simulation_module
from weather.market.live_taker_exchange import (
    AccountSnapshot,
    AdapterCapabilities,
    BookLevel,
    BookSnapshot,
    EvidenceGrade,
    FixtureLiveTakerExchange,
    FokSubmissionOutcome,
    FokYesBuyRequest,
    InvalidExchangeData,
    NullLiveTakerExchange,
    REVIEWED_RISK_POLICY_SHA256,
    SubmissionMode,
    SubmissionReceipt,
)
from weather.market.live_taker_risk import CanaryStage
from weather.market.live_taker_simulation import (
    OneShotFokYesBuySimulation,
    SimulationDecision,
    SimulationExecutionResult,
    SimulationModeRequired,
    SimulationOutcome,
    SimulationRunnerConsumed,
    run_one_fok_yes_buy_simulation,
)
from weather.market.live_taker_state import AuthorityState, assert_secret_safe


NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
TOKEN_ID = "12345678901234567890"
EVENT_ID = "highest-temperature-simulation-event"


def valid_account(**overrides: object) -> AccountSnapshot:
    values = {
        "platform": "polymarket_global",
        "account_identity_redacted": "sha256:" + "a" * 64,
        "observed_at_utc": NOW - timedelta(seconds=5),
        "snapshot_sha256": "b" * 64,
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


def valid_book(**overrides: object) -> BookSnapshot:
    values = {
        "platform": "polymarket_global",
        "event_id": EVENT_ID,
        "token_id": TOKEN_ID,
        "observed_at_utc": NOW - timedelta(seconds=1),
        "closes_at_utc": NOW + timedelta(hours=1),
        "snapshot_sha256": "c" * 64,
        "active": True,
        "accepting_orders": True,
        "tick_size_usdc_per_share": Decimal("0.01"),
        "minimum_order_quantity_shares": Decimal("0.1"),
        "quantity_step_shares": Decimal("0.1"),
        "bids": (BookLevel(Decimal("0.89"), Decimal("100")),),
        "asks": (BookLevel(Decimal("0.90"), Decimal("100")),),
    }
    values.update(overrides)
    return BookSnapshot(**values)


def valid_request(**overrides: object) -> FokYesBuyRequest:
    # The complete simulated debit is below the reviewed $0.50 lifecycle cap.
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
        "release_manifest_sha256": "e" * 64,
        "input_snapshot_sha256": "f" * 64,
        "risk_policy_sha256": REVIEWED_RISK_POLICY_SHA256,
        "risk_decision_sha256": "1" * 64,
    }
    values.update(overrides)
    return FokYesBuyRequest.build(**values)


def receipt_for(
    request: FokYesBuyRequest,
    outcome: FokSubmissionOutcome,
) -> SubmissionReceipt:
    values: dict[str, object] = {
        "adapter_id": "fixture-source",
        "platform": request.platform,
        # Receipt identity always comes from the fully formed request.
        "idempotency_key": request.idempotency_key,
        "request_sha256": request.request_sha256,
        "outcome": outcome,
        "submitted_at_utc": NOW,
        "acknowledged_at_utc": NOW + timedelta(milliseconds=100),
        "reason_code": f"FOK_{outcome.value}",
        "evidence_grade": EvidenceGrade.SIMULATION,
        "simulation_only": True,
    }
    if outcome is FokSubmissionOutcome.FILLED:
        values.update(
            {
                "exchange_order_id": "sim-order-filled",
                "filled_quantity_shares": request.approved_quantity_shares,
                "filled_principal_usdc": request.fok_buy_amount_usdc,
                "average_fill_price_usdc_per_share": Decimal("0.90"),
                "fee_paid_usdc": request.fee_reserve_usdc,
                "total_debit_usdc": request.max_total_debit_usdc,
            }
        )
    elif outcome is FokSubmissionOutcome.PARTIAL:
        values.update(
            {
                "exchange_order_id": "sim-order-partial",
                "filled_quantity_shares": Decimal("0.2"),
                "filled_principal_usdc": Decimal("0.18"),
                "average_fill_price_usdc_per_share": Decimal("0.90"),
                "fee_paid_usdc": Decimal("0.005"),
                "total_debit_usdc": Decimal("0.185"),
            }
        )
    return SubmissionReceipt(**values)


def fixture_with_receipts(
    request: FokYesBuyRequest,
    *receipts: SubmissionReceipt,
) -> FixtureLiveTakerExchange:
    return FixtureLiveTakerExchange(
        platform=request.platform,
        account=request.account,
        books={request.token_id: request.book},
        submission_receipts=receipts,
    )


class StructurallyConformingCapitalAdapter:
    def __init__(self) -> None:
        self.submit_calls = 0
        self._capabilities = AdapterCapabilities(
            adapter_id="capital-shaped",
            platform="polymarket_global",
            submission_mode=SubmissionMode.CAPITAL,
            can_produce_capital_grade_evidence=True,
        )

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    def read_account(self):
        raise AssertionError("capital adapter must not be called")

    def read_book(self, token_id: str):
        raise AssertionError("capital adapter must not be called")

    def read_order(self, exchange_order_id: str):
        raise AssertionError("capital adapter must not be called")

    def read_open_orders(self):
        raise AssertionError("capital adapter must not be called")

    def submit_fok_yes_buy(
        self,
        request: FokYesBuyRequest,
        *,
        submitted_at_utc: datetime,
    ) -> SubmissionReceipt:
        self.submit_calls += 1
        raise AssertionError("capital adapter must not be called")


class SecretThrowingSimulationAdapter(StructurallyConformingCapitalAdapter):
    def __init__(self) -> None:
        super().__init__()
        self._capabilities = AdapterCapabilities(
            adapter_id="secret-throwing-simulation",
            platform="polymarket_global",
            submission_mode=SubmissionMode.SIMULATION,
            can_produce_capital_grade_evidence=False,
        )

    def submit_fok_yes_buy(
        self,
        request: FokYesBuyRequest,
        *,
        submitted_at_utc: datetime,
    ) -> SubmissionReceipt:
        self.submit_calls += 1
        raise RuntimeError("private_key=never-copy-this-secret")


def test_module_has_no_network_sdk_environment_or_filesystem_dependencies():
    tree = ast.parse(inspect.getsource(simulation_module))
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
    assert "open(" not in inspect.getsource(simulation_module)


def test_null_and_structurally_conforming_capital_adapters_are_refused():
    with pytest.raises(SimulationModeRequired, match="only a SIMULATION"):
        OneShotFokYesBuySimulation(NullLiveTakerExchange())

    capital_adapter = StructurallyConformingCapitalAdapter()
    with pytest.raises(SimulationModeRequired, match="only a SIMULATION"):
        OneShotFokYesBuySimulation(capital_adapter)
    assert capital_adapter.submit_calls == 0


def test_constructed_simulation_evidence_rejects_internal_contradictions():
    with pytest.raises(InvalidExchangeData, match="requires one attempted"):
        SimulationDecision(
            outcome=SimulationOutcome.FILLED,
            reason_code="SIMULATION_FILLED",
            authority_state=AuthorityState.EXPOSED,
            known_terminal=True,
            submission_attempted=False,
        )

    request = valid_request()
    mismatched = AdapterCapabilities(
        adapter_id="fixture-us",
        platform="polymarket_us",
        submission_mode=SubmissionMode.SIMULATION,
        can_produce_capital_grade_evidence=False,
    )
    with pytest.raises(InvalidExchangeData, match="platform does not match"):
        SimulationExecutionResult(
            adapter_capabilities=mismatched,
            request=request,
            submitted_at_utc=NOW,
            decision=SimulationDecision(
                outcome=SimulationOutcome.HALTED,
                reason_code="SIMULATION_PLATFORM_MISMATCH",
                authority_state=AuthorityState.HALTED,
                known_terminal=False,
                submission_attempted=False,
            ),
            receipt=None,
        )

    matching = AdapterCapabilities(
        adapter_id="fixture-source",
        platform=request.platform,
        submission_mode=SubmissionMode.SIMULATION,
        can_produce_capital_grade_evidence=False,
    )
    with pytest.raises(InvalidExchangeData, match="retained receipt requires"):
        SimulationExecutionResult(
            adapter_capabilities=matching,
            request=request,
            submitted_at_utc=NOW,
            decision=SimulationDecision(
                outcome=SimulationOutcome.HALTED,
                reason_code="SIMULATION_UNKNOWN_HALT",
                authority_state=AuthorityState.HALTED,
                known_terminal=False,
                submission_attempted=False,
            ),
            receipt=receipt_for(request, FokSubmissionOutcome.UNKNOWN),
        )


def test_fixture_filled_maps_to_known_terminal_simulation_result():
    request = valid_request()
    assert request.max_total_debit_usdc <= Decimal("0.50")
    adapter = fixture_with_receipts(
        request,
        receipt_for(request, FokSubmissionOutcome.FILLED),
    )

    result = run_one_fok_yes_buy_simulation(
        adapter,
        request,
        submitted_at_utc=NOW,
    )

    assert result.decision.outcome is SimulationOutcome.FILLED
    assert result.decision.authority_state is AuthorityState.EXPOSED
    assert result.decision.known_terminal is True
    assert result.decision.new_orders_enabled is False
    assert result.receipt is not None
    assert result.receipt.simulation_only is True
    assert result.receipt.evidence_grade is EvidenceGrade.SIMULATION
    assert result.receipt.capital_grade_evidence is False
    assert adapter.submitted_requests == (request,)
    with pytest.raises(FrozenInstanceError):
        result.receipt = None


def test_fixture_rejected_maps_to_known_terminal_halted_result():
    request = valid_request()
    adapter = fixture_with_receipts(
        request,
        receipt_for(request, FokSubmissionOutcome.REJECTED),
    )

    result = run_one_fok_yes_buy_simulation(
        adapter,
        request,
        submitted_at_utc=NOW,
    )

    assert result.decision.outcome is SimulationOutcome.REJECTED
    assert result.decision.authority_state is AuthorityState.HALTED
    assert result.decision.known_terminal is True
    assert result.receipt is not None
    assert result.receipt.outcome is FokSubmissionOutcome.REJECTED


def test_fixture_unknown_and_partial_fail_closed_as_halted():
    request = valid_request()
    unknown_adapter = fixture_with_receipts(request)
    partial_adapter = fixture_with_receipts(
        request,
        receipt_for(request, FokSubmissionOutcome.PARTIAL),
    )

    unknown = run_one_fok_yes_buy_simulation(
        unknown_adapter,
        request,
        submitted_at_utc=NOW,
    )
    partial = run_one_fok_yes_buy_simulation(
        partial_adapter,
        request,
        submitted_at_utc=NOW,
    )

    assert unknown.decision.outcome is SimulationOutcome.HALTED
    assert unknown.decision.authority_state is AuthorityState.HALTED
    assert unknown.decision.known_terminal is False
    assert unknown.decision.reason_code == "SIMULATION_UNKNOWN_HALT"
    assert unknown.receipt is not None
    assert unknown.receipt.outcome is FokSubmissionOutcome.UNKNOWN
    assert partial.decision.outcome is SimulationOutcome.HALTED
    assert partial.decision.reason_code == "SIMULATION_PARTIAL_HALT"
    assert partial.receipt is not None
    assert partial.receipt.outcome is FokSubmissionOutcome.PARTIAL


def test_stale_request_halts_without_calling_adapter_and_consumes_runner():
    request = valid_request()
    adapter = fixture_with_receipts(
        request,
        receipt_for(request, FokSubmissionOutcome.FILLED),
    )
    runner = OneShotFokYesBuySimulation(adapter)

    result = runner.execute(
        request,
        submitted_at_utc=NOW + timedelta(seconds=2),
    )

    assert runner.consumed is True
    assert result.decision.outcome is SimulationOutcome.HALTED
    assert result.decision.reason_code == "STALE_REQUEST"
    assert result.decision.submission_attempted is False
    assert result.receipt is None
    assert adapter.submitted_requests == ()
    with pytest.raises(SimulationRunnerConsumed, match="already consumed"):
        runner.execute(request, submitted_at_utc=NOW)


def test_public_projection_is_bounded_decimal_normalized_and_secret_safe():
    request = valid_request()
    adapter = fixture_with_receipts(
        request,
        receipt_for(request, FokSubmissionOutcome.FILLED),
    )
    result = run_one_fok_yes_buy_simulation(
        adapter,
        request,
        submitted_at_utc=NOW,
    )

    payload = result.as_public_dict()
    assert_secret_safe(payload)
    assert payload["adapter"]["submission_mode"] == "SIMULATION"
    assert payload["decision"]["new_orders_enabled"] is False
    assert payload["request"]["fok_buy_amount_usdc"] == "0.45"
    assert payload["request"]["max_total_debit_usdc"] == "0.46"
    assert payload["request"]["intent_sequence"] == 1
    assert payload["request"]["risk_stage"] == "LIFECYCLE"
    assert payload["request"]["risk_policy_sha256"] == REVIEWED_RISK_POLICY_SHA256
    assert payload["request"]["risk_decision_sha256"] == "1" * 64
    assert payload["request"]["reviewed_risk_policy_bound"] is True
    assert payload["receipt"]["idempotency_key"] == request.idempotency_key
    assert payload["receipt"]["request_sha256"] == request.request_sha256
    assert not any(
        marker in json.dumps(payload).lower()
        for marker in ("raw_response", "signed_order", "private_key", "credential")
    )


def test_adapter_exception_text_cannot_escape_through_public_projection():
    request = valid_request()
    adapter = SecretThrowingSimulationAdapter()

    result = run_one_fok_yes_buy_simulation(
        adapter,
        request,
        submitted_at_utc=NOW,
    )
    payload_text = json.dumps(result.as_public_dict())

    assert adapter.submit_calls == 1
    assert result.decision.outcome is SimulationOutcome.HALTED
    assert result.decision.reason_code == "SIMULATION_ADAPTER_UNCLASSIFIED_ERROR"
    assert "never-copy-this-secret" not in payload_text
    assert "private_key" not in payload_text
