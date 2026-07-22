"""One-shot, credential-free FOK simulation for the capital canary.

This module is deliberately narrower than an execution worker.  It accepts an
already-sized :class:`FokYesBuyRequest`, calls a simulation-only adapter at
most once, and returns an immutable public-safe result.  It has no credential,
network, environment, filesystem, persistence, retry, or loop capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
import re

from weather.market.live_taker_exchange import (
    AdapterCapabilities,
    EvidenceGrade,
    ExchangeBoundaryError,
    FokSubmissionOutcome,
    FokYesBuyRequest,
    InvalidExchangeData,
    LiveTakerExchange,
    REVIEWED_RISK_POLICY_SHA256,
    StaleExchangeSnapshot,
    SubmissionMode,
    SubmissionReceipt,
)
from weather.market.live_taker_state import AuthorityState, assert_secret_safe


_REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")


class SimulationModeRequired(ExchangeBoundaryError):
    """Raised when a one-shot runner is given a non-simulation adapter."""


class SimulationRunnerConsumed(ExchangeBoundaryError):
    """Raised when a one-shot runner is asked to execute more than once."""


class SimulationOutcome(StrEnum):
    """Fail-closed outcome exposed by the simulation slice."""

    FILLED = "FILLED"
    REJECTED = "REJECTED"
    HALTED = "HALTED"


def _utc(value: object, *, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise InvalidExchangeData(f"{field} must be a timezone-aware datetime")
    if value.utcoffset() is None:
        raise InvalidExchangeData(f"{field} must have a valid UTC offset")
    return value.astimezone(timezone.utc)


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


@dataclass(frozen=True)
class SimulationDecision:
    """Normalized decision with explicit authority and terminal semantics."""

    outcome: SimulationOutcome
    reason_code: str
    authority_state: AuthorityState
    known_terminal: bool
    submission_attempted: bool
    new_orders_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, SimulationOutcome):
            raise InvalidExchangeData("simulation outcome is invalid")
        if not isinstance(self.reason_code, str) or not _REASON_CODE_RE.fullmatch(
            self.reason_code
        ):
            raise InvalidExchangeData("simulation reason_code is malformed")
        if not isinstance(self.authority_state, AuthorityState):
            raise InvalidExchangeData("simulation authority_state is invalid")
        if not isinstance(self.known_terminal, bool) or not isinstance(
            self.submission_attempted, bool
        ):
            raise InvalidExchangeData("simulation decision flags must be boolean")
        if self.new_orders_enabled is not False:
            raise InvalidExchangeData("simulation cannot enable new orders")

        expected = {
            SimulationOutcome.FILLED: (AuthorityState.EXPOSED, True),
            SimulationOutcome.REJECTED: (AuthorityState.HALTED, True),
            SimulationOutcome.HALTED: (AuthorityState.HALTED, False),
        }[self.outcome]
        if (self.authority_state, self.known_terminal) != expected:
            raise InvalidExchangeData("simulation outcome invariants do not reconcile")
        if self.known_terminal and not self.submission_attempted:
            raise InvalidExchangeData(
                "a known simulation submission outcome requires one attempted submission"
            )

    def as_public_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "authority_state": self.authority_state.value,
            "known_terminal": self.known_terminal,
            "submission_attempted": self.submission_attempted,
            "new_orders_enabled": False,
        }


@dataclass(frozen=True)
class SimulationExecutionResult:
    """Immutable, secret-free evidence from one simulation execution attempt."""

    adapter_capabilities: AdapterCapabilities
    request: FokYesBuyRequest
    submitted_at_utc: datetime
    decision: SimulationDecision
    receipt: SubmissionReceipt | None

    def __post_init__(self) -> None:
        if not isinstance(self.adapter_capabilities, AdapterCapabilities):
            raise InvalidExchangeData("result requires normalized adapter capabilities")
        if self.adapter_capabilities.submission_mode is not SubmissionMode.SIMULATION:
            raise SimulationModeRequired("result cannot record a non-simulation adapter")
        if self.adapter_capabilities.can_produce_capital_grade_evidence:
            raise SimulationModeRequired("simulation result cannot claim capital evidence")
        if not isinstance(self.request, FokYesBuyRequest):
            raise InvalidExchangeData("result requires a FokYesBuyRequest")
        if self.adapter_capabilities.platform != self.request.platform:
            raise InvalidExchangeData("result adapter platform does not match request")
        object.__setattr__(
            self,
            "submitted_at_utc",
            _utc(self.submitted_at_utc, field="submitted_at_utc"),
        )
        if not isinstance(self.decision, SimulationDecision):
            raise InvalidExchangeData("result requires a SimulationDecision")

        receipt = self.receipt
        if receipt is not None:
            if not isinstance(receipt, SubmissionReceipt):
                raise InvalidExchangeData("result receipt must be normalized")
            if (
                not receipt.simulation_only
                or receipt.evidence_grade is not EvidenceGrade.SIMULATION
                or receipt.capital_grade_evidence
            ):
                raise SimulationModeRequired(
                    "simulation result cannot retain non-simulation evidence"
                )
            if receipt.adapter_id != self.adapter_capabilities.adapter_id:
                raise InvalidExchangeData("receipt adapter does not match capabilities")
            if receipt.submitted_at_utc != self.submitted_at_utc:
                raise InvalidExchangeData("receipt submission time does not match invocation")
            receipt.assert_bound_to(self.request)
            if not self.decision.submission_attempted:
                raise InvalidExchangeData(
                    "a retained receipt requires one attempted submission"
                )

        if self.decision.outcome is SimulationOutcome.FILLED:
            expected_receipt_outcome = FokSubmissionOutcome.FILLED
        elif self.decision.outcome is SimulationOutcome.REJECTED:
            expected_receipt_outcome = FokSubmissionOutcome.REJECTED
        else:
            expected_receipt_outcome = None

        if expected_receipt_outcome is not None:
            if receipt is None or receipt.outcome is not expected_receipt_outcome:
                raise InvalidExchangeData(
                    "known simulation outcome requires its matching receipt"
                )
        elif receipt is not None and receipt.outcome not in {
            FokSubmissionOutcome.PARTIAL,
            FokSubmissionOutcome.UNKNOWN,
        }:
            raise InvalidExchangeData("halted result cannot retain a terminal receipt")

    def as_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "adapter": {
                "adapter_id": self.adapter_capabilities.adapter_id,
                "platform": self.adapter_capabilities.platform,
                "submission_mode": self.adapter_capabilities.submission_mode.value,
                "simulation_only": self.adapter_capabilities.simulation_only,
                "can_produce_capital_grade_evidence": (
                    self.adapter_capabilities.can_produce_capital_grade_evidence
                ),
            },
            "request": {
                "event_id": self.request.event_id,
                "token_id": self.request.token_id,
                "idempotency_key": self.request.idempotency_key,
                "request_sha256": self.request.request_sha256,
                "intent_sequence": self.request.intent_sequence,
                "risk_stage": self.request.risk_stage.value,
                "created_at_utc": self.request.created_at_utc.isoformat(),
                "submitted_at_utc": self.submitted_at_utc.isoformat(),
                "approved_quantity_shares": _decimal_text(
                    self.request.approved_quantity_shares
                ),
                "fok_buy_amount_usdc": _decimal_text(
                    self.request.fok_buy_amount_usdc
                ),
                "worst_price_usdc_per_share": _decimal_text(
                    self.request.worst_price_usdc_per_share
                ),
                "fee_reserve_usdc": _decimal_text(self.request.fee_reserve_usdc),
                "max_total_debit_usdc": _decimal_text(
                    self.request.max_total_debit_usdc
                ),
                "release_manifest_sha256": self.request.release_manifest_sha256,
                "input_snapshot_sha256": self.request.input_snapshot_sha256,
                "risk_policy_sha256": self.request.risk_policy_sha256,
                "risk_decision_sha256": self.request.risk_decision_sha256,
                "reviewed_risk_policy_bound": (
                    self.request.risk_policy_sha256
                    == REVIEWED_RISK_POLICY_SHA256
                ),
            },
            "decision": self.decision.as_public_dict(),
            "receipt": self.receipt.as_public_dict() if self.receipt else None,
        }
        assert_secret_safe(payload)
        return payload


class OneShotFokYesBuySimulation:
    """Consume one request through a simulation-only adapter, with no retry."""

    __slots__ = ("_adapter", "_capabilities", "_consumed")

    def __init__(self, adapter: LiveTakerExchange) -> None:
        try:
            conforms = isinstance(adapter, LiveTakerExchange)
        except Exception:
            raise SimulationModeRequired(
                "simulation adapter shape could not be verified"
            ) from None
        if not conforms:
            raise SimulationModeRequired(
                "simulation runner requires a structurally conforming adapter"
            )
        try:
            capabilities = adapter.capabilities
        except Exception:
            raise SimulationModeRequired(
                "simulation adapter capabilities are unavailable"
            ) from None
        if not isinstance(capabilities, AdapterCapabilities):
            raise SimulationModeRequired(
                "simulation adapter capabilities are not normalized"
            )
        if capabilities.submission_mode is not SubmissionMode.SIMULATION:
            raise SimulationModeRequired(
                "one-shot simulation accepts only a SIMULATION adapter"
            )
        if capabilities.can_produce_capital_grade_evidence:
            raise SimulationModeRequired(
                "simulation adapter cannot produce capital-grade evidence"
            )
        self._adapter = adapter
        self._capabilities = capabilities
        self._consumed = False

    @property
    def consumed(self) -> bool:
        return self._consumed

    def _halted(
        self,
        *,
        request: FokYesBuyRequest,
        submitted_at_utc: datetime,
        reason_code: str,
        submission_attempted: bool,
        receipt: SubmissionReceipt | None = None,
    ) -> SimulationExecutionResult:
        return SimulationExecutionResult(
            adapter_capabilities=self._capabilities,
            request=request,
            submitted_at_utc=submitted_at_utc,
            decision=SimulationDecision(
                outcome=SimulationOutcome.HALTED,
                reason_code=reason_code,
                authority_state=AuthorityState.HALTED,
                known_terminal=False,
                submission_attempted=submission_attempted,
            ),
            receipt=receipt,
        )

    def execute(
        self,
        request: FokYesBuyRequest,
        *,
        submitted_at_utc: datetime,
    ) -> SimulationExecutionResult:
        if self._consumed:
            raise SimulationRunnerConsumed("one-shot simulation runner is already consumed")
        self._consumed = True

        if not isinstance(request, FokYesBuyRequest):
            raise InvalidExchangeData("simulation requires a FokYesBuyRequest")
        submitted = _utc(submitted_at_utc, field="submitted_at_utc")

        try:
            current_capabilities = self._adapter.capabilities
        except Exception:
            return self._halted(
                request=request,
                submitted_at_utc=submitted,
                reason_code="SIMULATION_CAPABILITIES_UNAVAILABLE",
                submission_attempted=False,
            )
        if current_capabilities != self._capabilities:
            return self._halted(
                request=request,
                submitted_at_utc=submitted,
                reason_code="SIMULATION_CAPABILITIES_CHANGED",
                submission_attempted=False,
            )
        if self._capabilities.platform != request.platform:
            return self._halted(
                request=request,
                submitted_at_utc=submitted,
                reason_code="SIMULATION_PLATFORM_MISMATCH",
                submission_attempted=False,
            )

        try:
            request.require_submission_ready(submitted_at_utc=submitted)
        except StaleExchangeSnapshot:
            return self._halted(
                request=request,
                submitted_at_utc=submitted,
                reason_code="STALE_REQUEST",
                submission_attempted=False,
            )
        except InvalidExchangeData:
            return self._halted(
                request=request,
                submitted_at_utc=submitted,
                reason_code="REQUEST_NOT_SUBMISSION_READY",
                submission_attempted=False,
            )

        try:
            receipt = self._adapter.submit_fok_yes_buy(
                request,
                submitted_at_utc=submitted,
            )
        except ExchangeBoundaryError:
            return self._halted(
                request=request,
                submitted_at_utc=submitted,
                reason_code="SIMULATION_ADAPTER_ERROR",
                submission_attempted=True,
            )
        except Exception:
            return self._halted(
                request=request,
                submitted_at_utc=submitted,
                reason_code="SIMULATION_ADAPTER_UNCLASSIFIED_ERROR",
                submission_attempted=True,
            )

        if not isinstance(receipt, SubmissionReceipt):
            return self._halted(
                request=request,
                submitted_at_utc=submitted,
                reason_code="INVALID_SIMULATION_RECEIPT",
                submission_attempted=True,
            )
        if (
            not receipt.simulation_only
            or receipt.evidence_grade is not EvidenceGrade.SIMULATION
            or receipt.capital_grade_evidence
        ):
            return self._halted(
                request=request,
                submitted_at_utc=submitted,
                reason_code="NON_SIMULATION_RECEIPT",
                submission_attempted=True,
            )
        if (
            receipt.adapter_id != self._capabilities.adapter_id
            or receipt.submitted_at_utc != submitted
        ):
            return self._halted(
                request=request,
                submitted_at_utc=submitted,
                reason_code="RECEIPT_IDENTITY_MISMATCH",
                submission_attempted=True,
            )
        try:
            receipt.assert_bound_to(request)
        except ExchangeBoundaryError:
            return self._halted(
                request=request,
                submitted_at_utc=submitted,
                reason_code="RECEIPT_BINDING_FAILED",
                submission_attempted=True,
            )

        if receipt.outcome is FokSubmissionOutcome.FILLED:
            decision = SimulationDecision(
                outcome=SimulationOutcome.FILLED,
                reason_code="SIMULATION_FILLED",
                authority_state=AuthorityState.EXPOSED,
                known_terminal=True,
                submission_attempted=True,
            )
        elif receipt.outcome is FokSubmissionOutcome.REJECTED:
            decision = SimulationDecision(
                outcome=SimulationOutcome.REJECTED,
                reason_code="SIMULATION_REJECTED",
                authority_state=AuthorityState.HALTED,
                known_terminal=True,
                submission_attempted=True,
            )
        elif receipt.outcome is FokSubmissionOutcome.PARTIAL:
            return self._halted(
                request=request,
                submitted_at_utc=submitted,
                reason_code="SIMULATION_PARTIAL_HALT",
                submission_attempted=True,
                receipt=receipt,
            )
        else:
            return self._halted(
                request=request,
                submitted_at_utc=submitted,
                reason_code="SIMULATION_UNKNOWN_HALT",
                submission_attempted=True,
                receipt=receipt,
            )

        return SimulationExecutionResult(
            adapter_capabilities=self._capabilities,
            request=request,
            submitted_at_utc=submitted,
            decision=decision,
            receipt=receipt,
        )


def run_one_fok_yes_buy_simulation(
    adapter: LiveTakerExchange,
    request: FokYesBuyRequest,
    *,
    submitted_at_utc: datetime,
) -> SimulationExecutionResult:
    """Run exactly one FOK simulation without exposing a reusable authority."""

    return OneShotFokYesBuySimulation(adapter).execute(
        request,
        submitted_at_utc=submitted_at_utc,
    )


__all__ = [
    "OneShotFokYesBuySimulation",
    "SimulationDecision",
    "SimulationExecutionResult",
    "SimulationModeRequired",
    "SimulationOutcome",
    "SimulationRunnerConsumed",
    "run_one_fok_yes_buy_simulation",
]
