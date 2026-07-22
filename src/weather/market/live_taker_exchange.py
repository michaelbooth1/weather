"""Credential-free normalized exchange boundary for the capital canary.

There are no network, SDK, environment, or filesystem dependencies. The only
mutation is one immediate FOK YES buy. Venue BUY dollars and risk-approved
shares stay separate and must both reconcile.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
import re
from typing import Protocol, runtime_checkable

from weather.market.live_taker_risk import CanaryRiskPolicy, CanaryStage, policy_hash
from weather.market.live_taker_state import canonical_sha256, make_idempotency_key


ZERO = Decimal("0")
ONE = Decimal("1")
ABSOLUTE_CAPITAL_CEILING_USDC = Decimal("75")
_REVIEWED_RISK_POLICY = CanaryRiskPolicy()
REVIEWED_RISK_POLICY_SHA256 = policy_hash(_REVIEWED_RISK_POLICY)
MAX_ACCOUNT_AGE = timedelta(seconds=15)
MAX_BOOK_AGE = timedelta(seconds=2)
MAX_ORDER_STATE_AGE = timedelta(seconds=15)
MAX_FUTURE_SKEW = timedelta(seconds=1)
MIN_TIME_TO_CLOSE = timedelta(minutes=10)
MAX_SPREAD_USDC_PER_SHARE = Decimal("0.01")
MAX_TOP_ASK_FRACTION = Decimal("0.10")

SUPPORTED_PLATFORMS = frozenset({"polymarket_global", "polymarket_us"})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_ID_RE = re.compile(r"^[0-9]{1,128}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_ACCOUNT_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDEMPOTENCY_RE = re.compile(r"^capital-canary:[0-9a-f]{64}$")
_REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")


class ExchangeBoundaryError(RuntimeError): """Fail-closed exchange boundary error."""


class InvalidExchangeData(ExchangeBoundaryError, ValueError): """Invalid normalized data."""


class StaleExchangeSnapshot(ExchangeBoundaryError): """Snapshot is not current enough."""


class SubmissionDisabled(ExchangeBoundaryError): """Adapter cannot submit capital."""


class UncertainSubmission(ExchangeBoundaryError): """FOK result is not reconciled."""


class SimulationEvidenceOnly(ExchangeBoundaryError): """Evidence is simulation-only."""


class SubmissionMode(StrEnum):
    DISABLED = "DISABLED"
    SIMULATION = "SIMULATION"
    CAPITAL = "CAPITAL"


class OrderStatus(StrEnum):
    OPEN = "OPEN"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELED = "CANCELED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class FokSubmissionOutcome(StrEnum):
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class EvidenceGrade(StrEnum):
    SIMULATION = "SIMULATION"
    UNVERIFIED = "UNVERIFIED"
    RECONCILED = "RECONCILED"


def _decimal(
    value: object,
    *,
    field: str,
    minimum: Decimal | None = None,
    maximum: Decimal | None = None,
    inclusive_minimum: bool = True,
    inclusive_maximum: bool = True,
) -> Decimal:
    if not isinstance(value, Decimal):
        raise InvalidExchangeData(f"{field} must be a Decimal")
    if not value.is_finite():
        raise InvalidExchangeData(f"{field} must be finite")
    if minimum is not None:
        too_small = value < minimum if inclusive_minimum else value <= minimum
        if too_small:
            raise InvalidExchangeData(f"{field} is below its allowed minimum")
    if maximum is not None:
        too_large = value > maximum if inclusive_maximum else value >= maximum
        if too_large:
            raise InvalidExchangeData(f"{field} exceeds its allowed maximum")
    return value


def _optional_decimal(
    value: object,
    *,
    field: str,
    minimum: Decimal = ZERO,
) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, field=field, minimum=minimum)


def _count(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidExchangeData(f"{field} must be a non-negative integer or null")
    return value


def _utc(value: object, *, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise InvalidExchangeData(f"{field} must be a timezone-aware datetime")
    offset = value.utcoffset()
    if offset is None:
        raise InvalidExchangeData(f"{field} must have a valid UTC offset")
    return value.astimezone(timezone.utc)


def _safe_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise InvalidExchangeData(f"{field} is malformed")
    return value


def _token_id(value: object) -> str:
    if not isinstance(value, str) or not _TOKEN_ID_RE.fullmatch(value):
        raise InvalidExchangeData("token_id must be a decimal CLOB token identifier")
    return value


def _sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise InvalidExchangeData(f"{field} must be a lowercase SHA-256 digest")
    return value


def _reason_code(value: object) -> str:
    if not isinstance(value, str) or not _REASON_CODE_RE.fullmatch(value):
        raise InvalidExchangeData("reason_code must be a bounded machine-readable code")
    return value


def _platform(value: object) -> str:
    if not isinstance(value, str) or value not in SUPPORTED_PLATFORMS:
        raise InvalidExchangeData("platform is unsupported")
    return value


def _ensure_fresh(
    observed_at_utc: datetime,
    at_utc: datetime,
    *,
    max_age: timedelta,
    label: str,
) -> None:
    observed = _utc(observed_at_utc, field=f"{label}_observed_at_utc")
    current = _utc(at_utc, field="at_utc")
    if observed > current + MAX_FUTURE_SKEW:
        raise StaleExchangeSnapshot(f"{label} observation is implausibly in the future")
    if current - observed > max_age:
        raise StaleExchangeSnapshot(f"{label} observation is stale")


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _fok_request_idempotency_key(
    *,
    account: AccountSnapshot,
    book: BookSnapshot,
    approved_quantity_shares: Decimal,
    worst_price_usdc_per_share: Decimal,
    release_manifest_sha256: str,
    input_snapshot_sha256: str,
    risk_policy_sha256: str,
    risk_decision_sha256: str,
    intent_sequence: int,
) -> str:
    return make_idempotency_key(
        platform=account.platform,
        account_identity_redacted=account.account_identity_redacted,
        event_id=book.event_id,
        token_id=book.token_id,
        side="BUY_YES",
        limit_price=worst_price_usdc_per_share,
        quantity=approved_quantity_shares,
        release_hash=release_manifest_sha256,
        snapshot_hash=input_snapshot_sha256,
        policy_hash=risk_policy_sha256,
        sequence=intent_sequence,
        risk_decision_hash=risk_decision_sha256,
    )


def _fok_request_content_sha256(
    *,
    idempotency_key: str,
    intent_sequence: int,
    risk_stage: CanaryStage,
    created_at_utc: datetime,
    account: AccountSnapshot,
    book: BookSnapshot,
    approved_quantity_shares: Decimal,
    fok_buy_amount_usdc: Decimal,
    worst_price_usdc_per_share: Decimal,
    fee_reserve_usdc: Decimal,
    max_total_debit_usdc: Decimal,
    release_manifest_sha256: str,
    input_snapshot_sha256: str,
    risk_policy_sha256: str,
    risk_decision_sha256: str,
) -> str:
    return canonical_sha256(
        {
            "contract": "capital_canary_fok_yes_buy_v1",
            "idempotency_key": idempotency_key,
            "intent_sequence": intent_sequence,
            "risk_stage": risk_stage.value,
            "created_at_utc": created_at_utc.isoformat(),
            "platform": account.platform,
            "account_identity_redacted": account.account_identity_redacted,
            "account_snapshot_sha256": account.snapshot_sha256,
            "event_id": book.event_id,
            "token_id": book.token_id,
            "book_snapshot_sha256": book.snapshot_sha256,
            "approved_quantity_shares": _decimal_text(approved_quantity_shares),
            "fok_buy_amount_usdc": _decimal_text(fok_buy_amount_usdc),
            "worst_price_usdc_per_share": _decimal_text(
                worst_price_usdc_per_share
            ),
            "fee_reserve_usdc": _decimal_text(fee_reserve_usdc),
            "max_total_debit_usdc": _decimal_text(max_total_debit_usdc),
            "release_manifest_sha256": release_manifest_sha256,
            "input_snapshot_sha256": input_snapshot_sha256,
            "risk_policy_sha256": risk_policy_sha256,
            "risk_decision_sha256": risk_decision_sha256,
        }
    )


@dataclass(frozen=True)
class AdapterCapabilities:
    adapter_id: str
    platform: str | None
    submission_mode: SubmissionMode
    can_produce_capital_grade_evidence: bool

    def __post_init__(self) -> None:
        _safe_id(self.adapter_id, field="adapter_id")
        if self.platform is not None:
            _platform(self.platform)
        if not isinstance(self.submission_mode, SubmissionMode):
            raise InvalidExchangeData("submission_mode must be a SubmissionMode")
        if not isinstance(self.can_produce_capital_grade_evidence, bool):
            raise InvalidExchangeData("capital-grade capability must be boolean")
        if self.submission_mode is not SubmissionMode.CAPITAL and (
            self.can_produce_capital_grade_evidence
        ):
            raise InvalidExchangeData(
                "a disabled or simulation adapter cannot produce capital-grade evidence"
            )

    @property
    def simulation_only(self) -> bool:
        return self.submission_mode is SubmissionMode.SIMULATION

    @property
    def supports_capital_submission(self) -> bool:
        return self.submission_mode is SubmissionMode.CAPITAL


@dataclass(frozen=True)
class AccountSnapshot:
    platform: str
    account_identity_redacted: str
    observed_at_utc: datetime
    snapshot_sha256: str
    reconciled: bool
    external_flows_reconciled: bool
    collateral_balance_usdc: Decimal | None
    cash_available_usdc: Decimal | None
    allowance_usdc: Decimal | None
    open_order_count: int | None
    unsettled_position_count: int | None

    def __post_init__(self) -> None:
        _platform(self.platform)
        if not isinstance(self.account_identity_redacted, str) or not (
            _ACCOUNT_DIGEST_RE.fullmatch(self.account_identity_redacted)
        ):
            raise InvalidExchangeData(
                "account_identity_redacted must be a full SHA-256 digest label"
            )
        object.__setattr__(
            self,
            "observed_at_utc",
            _utc(self.observed_at_utc, field="account_observed_at_utc"),
        )
        _sha256(self.snapshot_sha256, field="account_snapshot_sha256")
        if not isinstance(self.reconciled, bool) or not isinstance(
            self.external_flows_reconciled,
            bool,
        ):
            raise InvalidExchangeData("account reconciliation fields must be boolean")
        for field in (
            "collateral_balance_usdc",
            "cash_available_usdc",
            "allowance_usdc",
        ):
            _optional_decimal(getattr(self, field), field=field)
        _count(self.open_order_count, field="open_order_count")
        _count(self.unsettled_position_count, field="unsettled_position_count")
        if (
            self.collateral_balance_usdc is not None
            and self.cash_available_usdc is not None
            and self.cash_available_usdc > self.collateral_balance_usdc
        ):
            raise InvalidExchangeData("available cash exceeds collateral balance")

    def require_submission_ready(self, *, at_utc: datetime) -> None:
        _ensure_fresh(
            self.observed_at_utc,
            at_utc,
            max_age=MAX_ACCOUNT_AGE,
            label="account",
        )
        if not self.reconciled or not self.external_flows_reconciled:
            raise InvalidExchangeData("account state is not fully reconciled")
        if any(
            value is None
            for value in (
                self.collateral_balance_usdc,
                self.cash_available_usdc,
                self.allowance_usdc,
                self.open_order_count,
                self.unsettled_position_count,
            )
        ):
            raise InvalidExchangeData("account state contains unknown submission inputs")
        if self.open_order_count != 0:
            raise InvalidExchangeData("open exchange orders must reconcile to zero")


@dataclass(frozen=True)
class BookLevel:
    price_usdc_per_share: Decimal
    quantity_shares: Decimal

    def __post_init__(self) -> None:
        _decimal(
            self.price_usdc_per_share,
            field="price_usdc_per_share",
            minimum=ZERO,
            maximum=ONE,
            inclusive_minimum=False,
            inclusive_maximum=False,
        )
        _decimal(
            self.quantity_shares,
            field="quantity_shares",
            minimum=ZERO,
            inclusive_minimum=False,
        )


@dataclass(frozen=True)
class BookSnapshot:
    platform: str
    event_id: str
    token_id: str
    observed_at_utc: datetime
    closes_at_utc: datetime
    snapshot_sha256: str
    active: bool
    accepting_orders: bool
    tick_size_usdc_per_share: Decimal
    minimum_order_quantity_shares: Decimal
    quantity_step_shares: Decimal
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]

    def __post_init__(self) -> None:
        _platform(self.platform)
        _safe_id(self.event_id, field="event_id")
        _token_id(self.token_id)
        observed = _utc(self.observed_at_utc, field="book_observed_at_utc")
        closes = _utc(self.closes_at_utc, field="closes_at_utc")
        object.__setattr__(self, "observed_at_utc", observed)
        object.__setattr__(self, "closes_at_utc", closes)
        _sha256(self.snapshot_sha256, field="book_snapshot_sha256")
        if not isinstance(self.active, bool) or not isinstance(
            self.accepting_orders,
            bool,
        ):
            raise InvalidExchangeData("book activity fields must be boolean")
        tick = _decimal(
            self.tick_size_usdc_per_share,
            field="tick_size_usdc_per_share",
            minimum=ZERO,
            maximum=ONE,
            inclusive_minimum=False,
            inclusive_maximum=False,
        )
        _decimal(
            self.minimum_order_quantity_shares,
            field="minimum_order_quantity_shares",
            minimum=ZERO,
            inclusive_minimum=False,
        )
        _decimal(
            self.quantity_step_shares,
            field="quantity_step_shares",
            minimum=ZERO,
            inclusive_minimum=False,
        )
        if not isinstance(self.bids, tuple) or not isinstance(self.asks, tuple):
            raise InvalidExchangeData("book levels must be immutable tuples")
        if any(not isinstance(level, BookLevel) for level in (*self.bids, *self.asks)):
            raise InvalidExchangeData("book levels must be BookLevel values")
        bid_prices = [level.price_usdc_per_share for level in self.bids]
        ask_prices = [level.price_usdc_per_share for level in self.asks]
        if bid_prices != sorted(bid_prices, reverse=True) or len(set(bid_prices)) != len(
            bid_prices
        ):
            raise InvalidExchangeData("bid levels must have unique descending prices")
        if ask_prices != sorted(ask_prices) or len(set(ask_prices)) != len(ask_prices):
            raise InvalidExchangeData("ask levels must have unique ascending prices")
        for price in (*bid_prices, *ask_prices):
            if price % tick != ZERO:
                raise InvalidExchangeData("book level price is not aligned to tick size")
        if bid_prices and ask_prices and bid_prices[0] >= ask_prices[0]:
            raise InvalidExchangeData("book is crossed or locked")
        if self.active and closes <= observed:
            raise InvalidExchangeData("active book closes no later than its observation")

    @property
    def best_bid(self) -> BookLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> BookLevel | None:
        return self.asks[0] if self.asks else None

    @property
    def spread_usdc_per_share(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask.price_usdc_per_share - self.best_bid.price_usdc_per_share

    def require_submission_ready(self, *, at_utc: datetime) -> None:
        current = _utc(at_utc, field="at_utc")
        _ensure_fresh(
            self.observed_at_utc,
            current,
            max_age=MAX_BOOK_AGE,
            label="book",
        )
        if not self.active or not self.accepting_orders:
            raise InvalidExchangeData("market is not active and accepting orders")
        if self.best_bid is None or self.best_ask is None:
            raise InvalidExchangeData("two-sided direct book is required")
        if self.spread_usdc_per_share is None or (
            self.spread_usdc_per_share > MAX_SPREAD_USDC_PER_SHARE
        ):
            raise InvalidExchangeData("book spread exceeds the final boundary")
        if self.closes_at_utc - current < MIN_TIME_TO_CLOSE:
            raise InvalidExchangeData("market is too close to its close time")


@dataclass(frozen=True)
class FokYesBuyRequest:
    """One fully bound FOK BUY request.

    ``approved_quantity_shares`` is the risk-engine share limit.
    ``fok_buy_amount_usdc`` is the venue request unit for a BUY.  They are
    deliberately not aliases and neither may be inferred from the other's
    field name.
    """

    idempotency_key: str
    request_sha256: str
    intent_sequence: int
    risk_stage: CanaryStage
    created_at_utc: datetime
    account: AccountSnapshot
    book: BookSnapshot
    approved_quantity_shares: Decimal
    fok_buy_amount_usdc: Decimal
    worst_price_usdc_per_share: Decimal
    fee_reserve_usdc: Decimal
    max_total_debit_usdc: Decimal
    release_manifest_sha256: str
    input_snapshot_sha256: str
    risk_policy_sha256: str
    risk_decision_sha256: str

    @classmethod
    def build(
        cls,
        *,
        intent_sequence: int,
        risk_stage: CanaryStage,
        created_at_utc: datetime,
        account: AccountSnapshot,
        book: BookSnapshot,
        approved_quantity_shares: Decimal,
        fok_buy_amount_usdc: Decimal,
        worst_price_usdc_per_share: Decimal,
        fee_reserve_usdc: Decimal,
        max_total_debit_usdc: Decimal,
        release_manifest_sha256: str,
        input_snapshot_sha256: str,
        risk_decision_sha256: str,
        risk_policy_sha256: str = REVIEWED_RISK_POLICY_SHA256,
    ) -> FokYesBuyRequest:
        """Build identifiers from the exact immutable request content."""

        if (
            isinstance(intent_sequence, bool)
            or not isinstance(intent_sequence, int)
            or intent_sequence <= 0
        ):
            raise InvalidExchangeData("intent_sequence must be a positive integer")
        if not isinstance(risk_stage, CanaryStage):
            raise InvalidExchangeData("risk_stage must be a CanaryStage")
        created = _utc(created_at_utc, field="created_at_utc")
        idempotency_key = _fok_request_idempotency_key(
            account=account,
            book=book,
            approved_quantity_shares=approved_quantity_shares,
            worst_price_usdc_per_share=worst_price_usdc_per_share,
            release_manifest_sha256=release_manifest_sha256,
            input_snapshot_sha256=input_snapshot_sha256,
            risk_policy_sha256=risk_policy_sha256,
            risk_decision_sha256=risk_decision_sha256,
            intent_sequence=intent_sequence,
        )
        request_sha256 = _fok_request_content_sha256(
            idempotency_key=idempotency_key,
            intent_sequence=intent_sequence,
            risk_stage=risk_stage,
            created_at_utc=created,
            account=account,
            book=book,
            approved_quantity_shares=approved_quantity_shares,
            fok_buy_amount_usdc=fok_buy_amount_usdc,
            worst_price_usdc_per_share=worst_price_usdc_per_share,
            fee_reserve_usdc=fee_reserve_usdc,
            max_total_debit_usdc=max_total_debit_usdc,
            release_manifest_sha256=release_manifest_sha256,
            input_snapshot_sha256=input_snapshot_sha256,
            risk_policy_sha256=risk_policy_sha256,
            risk_decision_sha256=risk_decision_sha256,
        )
        return cls(
            idempotency_key=idempotency_key,
            request_sha256=request_sha256,
            intent_sequence=intent_sequence,
            risk_stage=risk_stage,
            created_at_utc=created,
            account=account,
            book=book,
            approved_quantity_shares=approved_quantity_shares,
            fok_buy_amount_usdc=fok_buy_amount_usdc,
            worst_price_usdc_per_share=worst_price_usdc_per_share,
            fee_reserve_usdc=fee_reserve_usdc,
            max_total_debit_usdc=max_total_debit_usdc,
            release_manifest_sha256=release_manifest_sha256,
            input_snapshot_sha256=input_snapshot_sha256,
            risk_policy_sha256=risk_policy_sha256,
            risk_decision_sha256=risk_decision_sha256,
        )

    def __post_init__(self) -> None:
        if not isinstance(self.idempotency_key, str) or not _IDEMPOTENCY_RE.fullmatch(
            self.idempotency_key
        ):
            raise InvalidExchangeData("idempotency_key is malformed")
        _sha256(self.request_sha256, field="request_sha256")
        if (
            isinstance(self.intent_sequence, bool)
            or not isinstance(self.intent_sequence, int)
            or self.intent_sequence <= 0
        ):
            raise InvalidExchangeData("intent_sequence must be a positive integer")
        if not isinstance(self.risk_stage, CanaryStage):
            raise InvalidExchangeData("risk_stage must be a CanaryStage")
        created = _utc(self.created_at_utc, field="created_at_utc")
        object.__setattr__(self, "created_at_utc", created)
        if not isinstance(self.account, AccountSnapshot) or not isinstance(
            self.book,
            BookSnapshot,
        ):
            raise InvalidExchangeData("request requires normalized account and book snapshots")
        quantity = _decimal(
            self.approved_quantity_shares,
            field="approved_quantity_shares",
            minimum=ZERO,
            inclusive_minimum=False,
        )
        buy_amount = _decimal(
            self.fok_buy_amount_usdc,
            field="fok_buy_amount_usdc",
            minimum=ZERO,
            inclusive_minimum=False,
        )
        worst_price = _decimal(
            self.worst_price_usdc_per_share,
            field="worst_price_usdc_per_share",
            minimum=ZERO,
            maximum=ONE,
            inclusive_minimum=False,
            inclusive_maximum=False,
        )
        fee_reserve = _decimal(
            self.fee_reserve_usdc,
            field="fee_reserve_usdc",
            minimum=ZERO,
        )
        total = _decimal(
            self.max_total_debit_usdc,
            field="max_total_debit_usdc",
            minimum=ZERO,
            maximum=ABSOLUTE_CAPITAL_CEILING_USDC,
            inclusive_minimum=False,
        )
        for field in (
            "release_manifest_sha256",
            "input_snapshot_sha256",
            "risk_policy_sha256",
            "risk_decision_sha256",
        ):
            _sha256(getattr(self, field), field=field)
        if self.risk_policy_sha256 != REVIEWED_RISK_POLICY_SHA256:
            raise InvalidExchangeData("request does not bind the reviewed canary risk policy")
        if self.account.platform != self.book.platform:
            raise InvalidExchangeData("account and book platforms do not match")
        if quantity < self.book.minimum_order_quantity_shares:
            raise InvalidExchangeData("approved quantity is below the venue minimum")
        if quantity % self.book.quantity_step_shares != ZERO:
            raise InvalidExchangeData("approved quantity is not aligned to the venue step")
        if worst_price % self.book.tick_size_usdc_per_share != ZERO:
            raise InvalidExchangeData("worst price is not aligned to the venue tick")
        if not (
            _REVIEWED_RISK_POLICY.min_limit_price
            <= worst_price
            <= _REVIEWED_RISK_POLICY.max_limit_price
        ):
            raise InvalidExchangeData("worst price is outside the reviewed canary lane")
        if total != buy_amount + fee_reserve:
            raise InvalidExchangeData("max total debit must exactly equal BUY amount plus fee reserve")
        stage_cap = (
            _REVIEWED_RISK_POLICY.lifecycle_max_order_loss_usdc
            if self.risk_stage is CanaryStage.LIFECYCLE
            else _REVIEWED_RISK_POLICY.alpha_max_order_loss_usdc
        )
        if total > stage_cap:
            raise InvalidExchangeData("max total debit exceeds the reviewed stage order cap")
        self.require_submission_ready(submitted_at_utc=created)
        unsettled = self.account.unsettled_position_count
        if self.risk_stage is CanaryStage.LIFECYCLE and unsettled != 0:
            raise InvalidExchangeData("lifecycle request requires zero unsettled positions")
        if (
            self.risk_stage is CanaryStage.ALPHA
            and unsettled is not None
            and unsettled >= _REVIEWED_RISK_POLICY.alpha_max_unsettled_positions
        ):
            raise InvalidExchangeData("alpha unsettled-position cap is already full")
        expected_idempotency_key = _fok_request_idempotency_key(
            account=self.account,
            book=self.book,
            approved_quantity_shares=self.approved_quantity_shares,
            worst_price_usdc_per_share=self.worst_price_usdc_per_share,
            release_manifest_sha256=self.release_manifest_sha256,
            input_snapshot_sha256=self.input_snapshot_sha256,
            risk_policy_sha256=self.risk_policy_sha256,
            risk_decision_sha256=self.risk_decision_sha256,
            intent_sequence=self.intent_sequence,
        )
        if self.idempotency_key != expected_idempotency_key:
            raise InvalidExchangeData("idempotency_key does not bind the request content")
        expected_request_sha256 = _fok_request_content_sha256(
            idempotency_key=self.idempotency_key,
            intent_sequence=self.intent_sequence,
            risk_stage=self.risk_stage,
            created_at_utc=self.created_at_utc,
            account=self.account,
            book=self.book,
            approved_quantity_shares=self.approved_quantity_shares,
            fok_buy_amount_usdc=self.fok_buy_amount_usdc,
            worst_price_usdc_per_share=self.worst_price_usdc_per_share,
            fee_reserve_usdc=self.fee_reserve_usdc,
            max_total_debit_usdc=self.max_total_debit_usdc,
            release_manifest_sha256=self.release_manifest_sha256,
            input_snapshot_sha256=self.input_snapshot_sha256,
            risk_policy_sha256=self.risk_policy_sha256,
            risk_decision_sha256=self.risk_decision_sha256,
        )
        if self.request_sha256 != expected_request_sha256:
            raise InvalidExchangeData("request_sha256 does not bind the request content")

    @property
    def platform(self) -> str:
        return self.account.platform

    @property
    def event_id(self) -> str:
        return self.book.event_id

    @property
    def token_id(self) -> str:
        return self.book.token_id

    def require_submission_ready(self, *, submitted_at_utc: datetime) -> None:
        submitted = _utc(submitted_at_utc, field="submitted_at_utc")
        if submitted + MAX_FUTURE_SKEW < self.created_at_utc:
            raise InvalidExchangeData("submission time predates request creation")
        self.account.require_submission_ready(at_utc=submitted)
        self.book.require_submission_ready(at_utc=submitted)
        best_ask = self.book.best_ask
        if best_ask is None:  # Defensive after the readiness call.
            raise InvalidExchangeData("direct book has no ask")
        if best_ask.price_usdc_per_share > self.worst_price_usdc_per_share:
            raise InvalidExchangeData("best ask exceeds the hard worst price")
        if self.fok_buy_amount_usdc > (
            self.approved_quantity_shares * best_ask.price_usdc_per_share
        ):
            raise InvalidExchangeData(
                "venue BUY dollar amount can acquire more than the approved shares at best ask"
            )
        minimum_shares_at_worst_price = (
            self.fok_buy_amount_usdc / self.worst_price_usdc_per_share
        )
        if minimum_shares_at_worst_price < self.book.minimum_order_quantity_shares:
            raise InvalidExchangeData("venue BUY amount is below the minimum at worst price")
        potential_shares_at_best = self.fok_buy_amount_usdc / (
            best_ask.price_usdc_per_share
        )
        if potential_shares_at_best > (
            best_ask.quantity_shares * MAX_TOP_ASK_FRACTION
        ):
            raise InvalidExchangeData("FOK BUY exceeds ten percent of top ask quantity")
        principal_capacity = sum(
            level.price_usdc_per_share * level.quantity_shares
            for level in self.book.asks
            if level.price_usdc_per_share <= self.worst_price_usdc_per_share
        )
        if principal_capacity < self.fok_buy_amount_usdc:
            raise InvalidExchangeData("book cannot fill the BUY dollar amount at the worst price")
        cash = self.account.cash_available_usdc
        allowance = self.account.allowance_usdc
        if cash is None or cash < self.max_total_debit_usdc:
            raise InvalidExchangeData("reconciled available cash is insufficient")
        if allowance is None or allowance < self.max_total_debit_usdc:
            raise InvalidExchangeData("reconciled allowance is insufficient")


@dataclass(frozen=True)
class OrderSnapshot:
    adapter_id: str
    platform: str
    exchange_order_id: str
    token_id: str
    observed_at_utc: datetime
    snapshot_sha256: str
    status: OrderStatus
    idempotency_key: str | None = None
    request_sha256: str | None = None
    filled_quantity_shares: Decimal | None = None
    filled_principal_usdc: Decimal | None = None
    average_fill_price_usdc_per_share: Decimal | None = None
    fee_paid_usdc: Decimal | None = None

    def __post_init__(self) -> None:
        _safe_id(self.adapter_id, field="adapter_id")
        _platform(self.platform)
        _safe_id(self.exchange_order_id, field="exchange_order_id")
        _token_id(self.token_id)
        object.__setattr__(
            self,
            "observed_at_utc",
            _utc(self.observed_at_utc, field="order_observed_at_utc"),
        )
        _sha256(self.snapshot_sha256, field="order_snapshot_sha256")
        if not isinstance(self.status, OrderStatus):
            raise InvalidExchangeData("status must be an OrderStatus")
        if self.idempotency_key is not None and not _IDEMPOTENCY_RE.fullmatch(
            self.idempotency_key
        ):
            raise InvalidExchangeData("order idempotency_key is malformed")
        if self.request_sha256 is not None:
            _sha256(self.request_sha256, field="order_request_sha256")
        for field in (
            "filled_quantity_shares",
            "filled_principal_usdc",
            "average_fill_price_usdc_per_share",
            "fee_paid_usdc",
        ):
            _optional_decimal(getattr(self, field), field=field)
        if self.average_fill_price_usdc_per_share is not None and not (
            ZERO < self.average_fill_price_usdc_per_share < ONE
        ):
            raise InvalidExchangeData("average fill price must be between zero and one")
        filled_values = (
            self.filled_quantity_shares,
            self.filled_principal_usdc,
            self.average_fill_price_usdc_per_share,
        )
        any_fill = any(value not in (None, ZERO) for value in filled_values)
        if any_fill and any(value is None for value in filled_values):
            raise InvalidExchangeData("filled order values must be complete")
        if any_fill and (
            self.filled_quantity_shares * self.average_fill_price_usdc_per_share
            != self.filled_principal_usdc
        ):
            raise InvalidExchangeData("filled order arithmetic does not reconcile")
        if self.status is OrderStatus.FILLED:
            if not any_fill or any(value is None for value in filled_values):
                raise InvalidExchangeData(
                    "filled order requires complete positive fill values"
                )
            if self.fee_paid_usdc is None:
                raise InvalidExchangeData("filled order requires a reported fee")
        elif self.status is OrderStatus.PARTIAL:
            if not any_fill or any(value is None for value in filled_values):
                raise InvalidExchangeData(
                    "partial order requires complete positive fill values"
                )
        elif self.status in {
            OrderStatus.OPEN,
            OrderStatus.REJECTED,
            OrderStatus.CANCELED,
        }:
            if any_fill or (
                self.fee_paid_usdc is not None and self.fee_paid_usdc > ZERO
            ):
                raise InvalidExchangeData(
                    f"{self.status.value.lower()} FOK order cannot contain a fill"
                )

    def require_known_fok_terminal(self, *, at_utc: datetime) -> None:
        _ensure_fresh(
            self.observed_at_utc,
            at_utc,
            max_age=MAX_ORDER_STATE_AGE,
            label="order",
        )
        if self.status in {OrderStatus.OPEN, OrderStatus.PARTIAL, OrderStatus.UNKNOWN}:
            raise UncertainSubmission("FOK order state is not a known terminal outcome")


@dataclass(frozen=True)
class SubmissionReceipt:
    """Secret-free normalized receipt; raw exchange responses never belong here."""

    adapter_id: str
    platform: str
    idempotency_key: str
    request_sha256: str
    outcome: FokSubmissionOutcome
    submitted_at_utc: datetime
    acknowledged_at_utc: datetime
    reason_code: str
    evidence_grade: EvidenceGrade
    simulation_only: bool
    exchange_order_id: str | None = None
    filled_quantity_shares: Decimal = ZERO
    filled_principal_usdc: Decimal = ZERO
    average_fill_price_usdc_per_share: Decimal | None = None
    fee_paid_usdc: Decimal = ZERO
    total_debit_usdc: Decimal = ZERO

    def __post_init__(self) -> None:
        _safe_id(self.adapter_id, field="adapter_id")
        _platform(self.platform)
        if not isinstance(self.idempotency_key, str) or not _IDEMPOTENCY_RE.fullmatch(
            self.idempotency_key
        ):
            raise InvalidExchangeData("receipt idempotency_key is malformed")
        _sha256(self.request_sha256, field="receipt_request_sha256")
        if not isinstance(self.outcome, FokSubmissionOutcome):
            raise InvalidExchangeData("outcome must be a FokSubmissionOutcome")
        submitted = _utc(self.submitted_at_utc, field="submitted_at_utc")
        acknowledged = _utc(self.acknowledged_at_utc, field="acknowledged_at_utc")
        object.__setattr__(self, "submitted_at_utc", submitted)
        object.__setattr__(self, "acknowledged_at_utc", acknowledged)
        if acknowledged + MAX_FUTURE_SKEW < submitted:
            raise InvalidExchangeData("receipt acknowledgement predates submission")
        _reason_code(self.reason_code)
        if not isinstance(self.evidence_grade, EvidenceGrade):
            raise InvalidExchangeData("evidence_grade must be an EvidenceGrade")
        if not isinstance(self.simulation_only, bool):
            raise InvalidExchangeData("simulation_only must be boolean")
        if self.simulation_only and self.evidence_grade is not EvidenceGrade.SIMULATION:
            raise InvalidExchangeData("simulation receipt must have simulation evidence grade")
        if not self.simulation_only and self.evidence_grade is EvidenceGrade.SIMULATION:
            raise InvalidExchangeData("live receipt cannot claim simulation evidence grade")
        if self.outcome in {
            FokSubmissionOutcome.PARTIAL,
            FokSubmissionOutcome.UNKNOWN,
        } and self.evidence_grade is EvidenceGrade.RECONCILED:
            raise InvalidExchangeData("uncertain FOK outcome cannot be reconciled evidence")
        if self.exchange_order_id is not None:
            _safe_id(self.exchange_order_id, field="exchange_order_id")
        quantity = _decimal(
            self.filled_quantity_shares,
            field="filled_quantity_shares",
            minimum=ZERO,
        )
        principal = _decimal(
            self.filled_principal_usdc,
            field="filled_principal_usdc",
            minimum=ZERO,
        )
        fee = _decimal(self.fee_paid_usdc, field="fee_paid_usdc", minimum=ZERO)
        total = _decimal(self.total_debit_usdc, field="total_debit_usdc", minimum=ZERO)
        average = _optional_decimal(
            self.average_fill_price_usdc_per_share,
            field="average_fill_price_usdc_per_share",
        )
        if average is not None and not ZERO < average < ONE:
            raise InvalidExchangeData("average fill price must be between zero and one")
        if quantity > ZERO or principal > ZERO:
            if quantity <= ZERO or principal <= ZERO or average is None:
                raise InvalidExchangeData("receipt fill fields must be complete")
            if quantity * average != principal:
                raise InvalidExchangeData("receipt fill arithmetic does not reconcile")
        elif average is not None:
            raise InvalidExchangeData("zero-fill receipt cannot have an average fill price")
        if total != principal + fee:
            raise InvalidExchangeData("receipt total debit does not reconcile")
        if self.outcome is FokSubmissionOutcome.FILLED:
            if self.exchange_order_id is None or quantity <= ZERO:
                raise InvalidExchangeData("filled receipt requires an order ID and positive fill")
        elif self.outcome is FokSubmissionOutcome.REJECTED:
            if any(value != ZERO for value in (quantity, principal, fee, total)):
                raise InvalidExchangeData("rejected receipt cannot contain a debit or fill")
        elif self.outcome is FokSubmissionOutcome.PARTIAL and quantity <= ZERO:
            raise InvalidExchangeData("partial receipt requires a positive observed fill")

    @property
    def capital_grade_evidence(self) -> bool:
        return (
            not self.simulation_only
            and self.evidence_grade is EvidenceGrade.RECONCILED
            and self.outcome
            in {FokSubmissionOutcome.FILLED, FokSubmissionOutcome.REJECTED}
        )

    def assert_bound_to(self, request: FokYesBuyRequest) -> None:
        if not isinstance(request, FokYesBuyRequest):
            raise InvalidExchangeData("receipt binding requires a FokYesBuyRequest")
        if self.platform != request.platform:
            raise InvalidExchangeData("receipt platform does not match request")
        if self.idempotency_key != request.idempotency_key:
            raise InvalidExchangeData("receipt idempotency key does not match request")
        if self.request_sha256 != request.request_sha256:
            raise InvalidExchangeData("receipt request hash does not match request")
        if self.submitted_at_utc + MAX_FUTURE_SKEW < request.created_at_utc:
            raise InvalidExchangeData("receipt submission predates request")
        if self.filled_quantity_shares > request.approved_quantity_shares:
            raise UncertainSubmission("filled shares exceed the approved share limit")
        if self.filled_principal_usdc > request.fok_buy_amount_usdc:
            raise UncertainSubmission("filled principal exceeds the venue BUY amount")
        if self.fee_paid_usdc > request.fee_reserve_usdc:
            raise UncertainSubmission("paid fee exceeds the reserved fee cap")
        if self.total_debit_usdc > request.max_total_debit_usdc:
            raise UncertainSubmission("total debit exceeds the approved cap")
        if (
            self.average_fill_price_usdc_per_share is not None
            and self.average_fill_price_usdc_per_share
            > request.worst_price_usdc_per_share
        ):
            raise UncertainSubmission("average fill price exceeds the hard worst price")
        if self.outcome is FokSubmissionOutcome.FILLED and (
            self.filled_principal_usdc != request.fok_buy_amount_usdc
        ):
            raise UncertainSubmission("FOK filled less than the complete BUY dollar amount")

    def require_capital_terminal(self, request: FokYesBuyRequest) -> None:
        self.assert_bound_to(request)
        if self.outcome in {
            FokSubmissionOutcome.PARTIAL,
            FokSubmissionOutcome.UNKNOWN,
        }:
            raise UncertainSubmission("FOK submission is not a known terminal outcome")
        if not self.capital_grade_evidence:
            raise SimulationEvidenceOnly("receipt is not independently reconciled capital evidence")

    def as_public_dict(self) -> dict[str, object]:
        """Return a bounded normalized representation with no raw response field."""

        return {
            "adapter_id": self.adapter_id,
            "platform": self.platform,
            "idempotency_key": self.idempotency_key,
            "request_sha256": self.request_sha256,
            "outcome": self.outcome.value,
            "submitted_at_utc": self.submitted_at_utc.isoformat(),
            "acknowledged_at_utc": self.acknowledged_at_utc.isoformat(),
            "reason_code": self.reason_code,
            "evidence_grade": self.evidence_grade.value,
            "simulation_only": self.simulation_only,
            "capital_grade_evidence": self.capital_grade_evidence,
            "exchange_order_id": self.exchange_order_id,
            "filled_quantity_shares": _decimal_text(self.filled_quantity_shares),
            "filled_principal_usdc": _decimal_text(self.filled_principal_usdc),
            "average_fill_price_usdc_per_share": _decimal_text(
                self.average_fill_price_usdc_per_share
            ),
            "fee_paid_usdc": _decimal_text(self.fee_paid_usdc),
            "total_debit_usdc": _decimal_text(self.total_debit_usdc),
        }


@runtime_checkable
class LiveTakerExchange(Protocol):
    """Minimal exchange surface consumed by a future capital worker."""

    @property
    def capabilities(self) -> AdapterCapabilities: ...

    def read_account(self) -> AccountSnapshot: ...

    def read_book(self, token_id: str) -> BookSnapshot: ...

    def read_order(self, exchange_order_id: str) -> OrderSnapshot | None: ...

    def read_open_orders(self) -> tuple[OrderSnapshot, ...]: ...

    def submit_fok_yes_buy(
        self,
        request: FokYesBuyRequest,
        *,
        submitted_at_utc: datetime,
    ) -> SubmissionReceipt: ...


class NullLiveTakerExchange:
    """No-network, no-evidence adapter that can never submit."""

    _CAPABILITIES = AdapterCapabilities(
        adapter_id="null",
        platform=None,
        submission_mode=SubmissionMode.DISABLED,
        can_produce_capital_grade_evidence=False,
    )

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self._CAPABILITIES

    def _unavailable(self) -> None:
        raise SubmissionDisabled("no exchange adapter is configured")

    def read_account(self) -> AccountSnapshot:
        self._unavailable()

    def read_book(self, token_id: str) -> BookSnapshot:
        _token_id(token_id)
        self._unavailable()

    def read_order(self, exchange_order_id: str) -> OrderSnapshot | None:
        _safe_id(exchange_order_id, field="exchange_order_id")
        self._unavailable()

    def read_open_orders(self) -> tuple[OrderSnapshot, ...]:
        self._unavailable()

    def submit_fok_yes_buy(
        self,
        request: FokYesBuyRequest,
        *,
        submitted_at_utc: datetime,
    ) -> SubmissionReceipt:
        if not isinstance(request, FokYesBuyRequest):
            raise InvalidExchangeData("submission requires a FokYesBuyRequest")
        _utc(submitted_at_utc, field="submitted_at_utc")
        raise SubmissionDisabled("NullLiveTakerExchange cannot submit orders")


class FixtureLiveTakerExchange:
    """Deterministic simulation adapter for tests and offline state exercises.

    Every receipt is forcibly downgraded to ``SIMULATION`` regardless of the
    supplied fixture.  Consequently this adapter cannot manufacture a capital-
    grade acknowledgement or reconciliation artifact.
    """

    def __init__(
        self,
        *,
        platform: str,
        account: AccountSnapshot,
        books: Mapping[str, BookSnapshot],
        orders: Sequence[OrderSnapshot] = (),
        submission_receipts: Sequence[SubmissionReceipt] = (),
        adapter_id: str = "fixture",
    ) -> None:
        platform = _platform(platform)
        adapter_id = _safe_id(adapter_id, field="adapter_id")
        if not isinstance(account, AccountSnapshot) or account.platform != platform:
            raise InvalidExchangeData("fixture account does not match fixture platform")
        copied_books: dict[str, BookSnapshot] = {}
        for token, book in dict(books).items():
            normalized_token = _token_id(token)
            if not isinstance(book, BookSnapshot):
                raise InvalidExchangeData("fixture book must be a BookSnapshot")
            if book.token_id != normalized_token or book.platform != platform:
                raise InvalidExchangeData("fixture book identity does not match its key")
            copied_books[normalized_token] = book
        copied_orders = tuple(orders)
        if any(
            not isinstance(order, OrderSnapshot) or order.platform != platform
            for order in copied_orders
        ):
            raise InvalidExchangeData("fixture orders must match the fixture platform")
        copied_receipts = tuple(submission_receipts)
        if any(not isinstance(receipt, SubmissionReceipt) for receipt in copied_receipts):
            raise InvalidExchangeData("fixture receipts must be SubmissionReceipt values")
        self._capabilities = AdapterCapabilities(
            adapter_id=adapter_id,
            platform=platform,
            submission_mode=SubmissionMode.SIMULATION,
            can_produce_capital_grade_evidence=False,
        )
        self._account = account
        self._books = copied_books
        self._orders = copied_orders
        self._receipts = copied_receipts
        self._receipt_index = 0
        self._submitted_requests: list[FokYesBuyRequest] = []

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    @property
    def submitted_requests(self) -> tuple[FokYesBuyRequest, ...]:
        return tuple(self._submitted_requests)

    def read_account(self) -> AccountSnapshot:
        return self._account

    def read_book(self, token_id: str) -> BookSnapshot:
        token = _token_id(token_id)
        try:
            return self._books[token]
        except KeyError as exc:
            raise ExchangeBoundaryError("fixture has no normalized book for token") from exc

    def read_order(self, exchange_order_id: str) -> OrderSnapshot | None:
        order_id = _safe_id(exchange_order_id, field="exchange_order_id")
        matches = [order for order in self._orders if order.exchange_order_id == order_id]
        if len(matches) > 1:
            raise InvalidExchangeData("fixture contains duplicate exchange order IDs")
        return matches[0] if matches else None

    def read_open_orders(self) -> tuple[OrderSnapshot, ...]:
        return tuple(
            order
            for order in self._orders
            if order.status in {OrderStatus.OPEN, OrderStatus.PARTIAL, OrderStatus.UNKNOWN}
        )

    def submit_fok_yes_buy(
        self,
        request: FokYesBuyRequest,
        *,
        submitted_at_utc: datetime,
    ) -> SubmissionReceipt:
        if not isinstance(request, FokYesBuyRequest):
            raise InvalidExchangeData("submission requires a FokYesBuyRequest")
        submitted = _utc(submitted_at_utc, field="submitted_at_utc")
        if request.platform != self._capabilities.platform:
            raise InvalidExchangeData("request platform does not match fixture platform")
        request.require_submission_ready(submitted_at_utc=submitted)
        self._submitted_requests.append(request)

        if self._receipt_index < len(self._receipts):
            source = self._receipts[self._receipt_index]
            self._receipt_index += 1
            receipt = replace(
                source,
                adapter_id=self._capabilities.adapter_id,
                platform=request.platform,
                evidence_grade=EvidenceGrade.SIMULATION,
                simulation_only=True,
            )
        else:
            receipt = SubmissionReceipt(
                adapter_id=self._capabilities.adapter_id,
                platform=request.platform,
                idempotency_key=request.idempotency_key,
                request_sha256=request.request_sha256,
                outcome=FokSubmissionOutcome.UNKNOWN,
                submitted_at_utc=submitted,
                acknowledged_at_utc=submitted,
                reason_code="FIXTURE_RESPONSE_MISSING",
                evidence_grade=EvidenceGrade.SIMULATION,
                simulation_only=True,
            )
        receipt.assert_bound_to(request)
        return receipt


__all__ = [
    "ABSOLUTE_CAPITAL_CEILING_USDC", "AccountSnapshot", "AdapterCapabilities",
    "BookLevel", "BookSnapshot", "EvidenceGrade", "ExchangeBoundaryError",
    "FixtureLiveTakerExchange", "FokSubmissionOutcome", "FokYesBuyRequest",
    "InvalidExchangeData", "LiveTakerExchange", "NullLiveTakerExchange",
    "OrderSnapshot", "OrderStatus", "SimulationEvidenceOnly",
    "REVIEWED_RISK_POLICY_SHA256",
    "StaleExchangeSnapshot", "SubmissionDisabled", "SubmissionMode",
    "SubmissionReceipt", "UncertainSubmission",
]
