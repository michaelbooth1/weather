"""Additive-only domain plugin contracts v0.1. No prices, IO or venue ownership."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import math
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence, runtime_checkable

CONTRACTS_VERSION = "0.1"


def utc_time(value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError("datetime must be UTC-aware")


def probability(value: float) -> None:
    if isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("probability must be finite and in [0, 1]")


def _freeze(instance, name):
    value = getattr(instance, name)
    if value is not None:
        object.__setattr__(instance, name, MappingProxyType(dict(value)))


@dataclass(frozen=True)
class MarketDescriptor:
    domain_id: str
    event_id: str
    condition_id: str
    outcome_tokens: Mapping[str, str]
    tick: Decimal
    min_order_size: Decimal
    neg_risk_group: str | None
    close_at_utc: datetime
    settle_at_utc: datetime | None
    native_unit: str | None
    plugin_version: str
    source_hashes: Mapping[str, str]

    def __post_init__(self):
        utc_time(self.close_at_utc)
        if self.settle_at_utc is not None:
            utc_time(self.settle_at_utc)
            if self.settle_at_utc < self.close_at_utc:
                raise ValueError("settlement precedes close")
        if not self.tick.is_finite() or not 0 < self.tick < 1:
            raise ValueError("invalid tick")
        if not self.min_order_size.is_finite() or self.min_order_size <= 0:
            raise ValueError("invalid minimum order size")
        if set(self.outcome_tokens) != {"YES", "NO"} or len(set(self.outcome_tokens.values())) != 2:
            raise ValueError("distinct YES and NO tokens required")
        if not all((self.domain_id, self.event_id, self.condition_id, self.plugin_version,
                    *self.outcome_tokens.values())):
            raise ValueError("identities must be nonempty")
        _freeze(self, "outcome_tokens")
        _freeze(self, "source_hashes")


@dataclass(frozen=True)
class UniverseSnapshot:
    markets: tuple[MarketDescriptor, ...]
    as_of_utc: datetime
    source_hashes: Mapping[str, str]

    def __post_init__(self):
        utc_time(self.as_of_utc)
        object.__setattr__(self, "markets", tuple(self.markets))
        if len({m.condition_id for m in self.markets}) != len(self.markets):
            raise ValueError("duplicate condition")
        _freeze(self, "source_hashes")


@dataclass(frozen=True)
class OutcomeView:
    condition_id: str
    p_yes: float
    stdev: float
    joint: Mapping[str, float] | None
    as_of_utc: datetime
    valid_until_utc: datetime
    inputs_hash: str
    model_id: str
    calibration_grade: str

    def __post_init__(self):
        probability(self.p_yes)
        if not math.isfinite(self.stdev) or self.stdev <= 0:
            raise ValueError("stdev must be finite and positive")
        utc_time(self.as_of_utc)
        utc_time(self.valid_until_utc)
        if self.valid_until_utc <= self.as_of_utc:
            raise ValueError("valid_until must follow as_of")
        if self.calibration_grade not in {"none", "shadow", "scored"}:
            raise ValueError("unknown calibration grade")
        if not all((self.condition_id, self.inputs_hash, self.model_id)):
            raise ValueError("view provenance required")
        if self.joint is not None:
            for p in self.joint.values():
                probability(p)
            if abs(math.fsum(self.joint.values()) - 1) > 1e-9:
                raise ValueError("joint must sum to one")
            if self.condition_id in self.joint and abs(self.joint[self.condition_id] - self.p_yes) > 1e-9:
                raise ValueError("joint disagrees with marginal")
        _freeze(self, "joint")


@dataclass(frozen=True)
class Unavailable:
    reason: str
    as_of_utc: datetime

    def __post_init__(self):
        utc_time(self.as_of_utc)
        if not self.reason:
            raise ValueError("unavailability needs a reason")


@dataclass(frozen=True)
class InfoEvent:
    kind: str
    scheduled_at_utc: datetime | None
    observed_at_utc: datetime | None
    detected_at_utc: datetime | None
    affects: tuple[str, ...]
    severity: float
    decided: Mapping[str, float] | None
    action_hint: str

    def __post_init__(self):
        for t in (self.scheduled_at_utc, self.observed_at_utc, self.detected_at_utc):
            if t is not None:
                utc_time(t)
        if self.observed_at_utc and self.detected_at_utc and self.detected_at_utc < self.observed_at_utc:
            raise ValueError("detection precedes observation")
        probability(self.severity)
        if self.action_hint not in {"pull", "widen", "recentre", "observe"}:
            raise ValueError("unknown action hint")
        if self.decided is not None:
            for p in self.decided.values():
                probability(p)
        object.__setattr__(self, "affects", tuple(self.affects))
        _freeze(self, "decided")


@dataclass(frozen=True)
class SettlementFact:
    condition_id: str
    p_yes: float
    as_of_utc: datetime
    source_hashes: Mapping[str, str]
    reconciliation_status: str

    def __post_init__(self):
        probability(self.p_yes)
        utc_time(self.as_of_utc)
        if not self.condition_id or not self.source_hashes or not self.reconciliation_status:
            raise ValueError("settlement provenance required")
        _freeze(self, "source_hashes")


@dataclass(frozen=True)
class Pending:
    reason: str
    as_of_utc: datetime

    def __post_init__(self):
        utc_time(self.as_of_utc)
        if not self.reason:
            raise ValueError("pending needs a reason")


@runtime_checkable
class MarketUniverse(Protocol):
    def discover(self, as_of_utc: datetime, horizon_days: int) -> UniverseSnapshot: ...
    def describe(self, condition_id: str, as_of_utc: datetime) -> MarketDescriptor: ...


@runtime_checkable
class FairValueProvider(Protocol):
    def evaluate(self, market: MarketDescriptor, as_of_utc: datetime) -> OutcomeView | Unavailable: ...


@runtime_checkable
class InformationClock(Protocol):
    def upcoming(self, markets: Sequence[MarketDescriptor], from_utc: datetime, to_utc: datetime) -> tuple[InfoEvent, ...]: ...
    def observe(self, markets: Sequence[MarketDescriptor], as_of_utc: datetime) -> tuple[InfoEvent, ...]: ...


@runtime_checkable
class SettlementResolver(Protocol):
    def resolve(self, market: MarketDescriptor, as_of_utc: datetime) -> SettlementFact | Pending: ...


@runtime_checkable
class ExposureModel(Protocol):
    def factors(self, market: MarketDescriptor) -> Mapping[str, float]: ...
