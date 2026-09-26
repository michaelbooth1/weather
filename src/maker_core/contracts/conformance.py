"""Offline plugin checks. Fixtures must include a real missing-input instant.

Finite fixtures cannot prove absence of hidden IO or leakage; source review and
the import ratchet remain required. The clock is injected, never wall time.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from maker_core.contracts import (
    MarketUniverse, FairValueProvider, InformationClock, SettlementResolver,
    OutcomeView, Unavailable, Pending, SettlementFact, utc_time,
)


@dataclass(frozen=True)
class FixtureClock:
    now: datetime
    missing_at: datetime
    later_at: datetime

    def __post_init__(self):
        for t in (self.now, self.missing_at, self.later_at):
            utc_time(t)
        if not self.missing_at < self.now < self.later_at:
            raise ValueError("fixture clock must span missing, available, later")


def check_conformance(*, universe: MarketUniverse, fair_value: FairValueProvider,
                      information: InformationClock, settlement: SettlementResolver,
                      clock: FixtureClock,
                      advance_inputs: Callable[[], None] = lambda: None) -> None:
    """Raise AssertionError on a violation; advance_inputs exposes future records.

    Plugins should supply a callback that makes a later captured record available,
    proving historical queries still return their original answer after ingestion.
    Unknown ``market_price`` must be refused (TypeError/ValueError) or ignored.
    """
    for provider, protocol in ((universe, MarketUniverse), (fair_value, FairValueProvider),
                               (information, InformationClock), (settlement, SettlementResolver)):
        assert isinstance(provider, protocol)
    snapshot = universe.discover(clock.now, 2)
    assert snapshot.as_of_utc <= clock.now and snapshot.markets
    assert snapshot == universe.discover(clock.now, 2)
    baseline = []
    for market in snapshot.markets:
        assert universe.describe(market.condition_id, clock.now) == market
        missing = fair_value.evaluate(market, clock.missing_at)
        assert isinstance(missing, Unavailable), "missing inputs must not become a guess"
        assert missing.as_of_utc <= clock.missing_at
        view = fair_value.evaluate(market, clock.now)
        assert isinstance(view, OutcomeView), "available fixture must exercise a view"
        view.__post_init__()
        assert view.condition_id == market.condition_id
        assert view.as_of_utc <= clock.now < view.valid_until_utc
        for price in (0.01, 0.99):
            try:
                contaminated = fair_value.evaluate(market, clock.now, market_price=price)
            except (TypeError, ValueError):
                pass
            else:
                assert contaminated == view, "market price changed fair value"
        expired = fair_value.evaluate(market, max(clock.later_at, view.valid_until_utc))
        assert isinstance(expired, Unavailable) or (
            expired.as_of_utc <= max(clock.later_at, view.valid_until_utc) < expired.valid_until_utc
        ), "expired view reused"
        fact = settlement.resolve(market, clock.now)
        assert isinstance(fact, (SettlementFact, Pending)) and fact.as_of_utc <= clock.now
        if isinstance(fact, SettlementFact):
            assert fact.condition_id == market.condition_id
        baseline.append((market, view, fact))
    observed = information.observe(snapshot.markets, clock.now)
    upcoming = information.upcoming(snapshot.markets, clock.now, clock.later_at)
    for event in observed:
        assert event.detected_at_utc is not None and event.detected_at_utc <= clock.now
        assert event.observed_at_utc is None or event.observed_at_utc <= clock.now
    for event in upcoming:
        assert event.scheduled_at_utc is not None
        assert clock.now <= event.scheduled_at_utc <= clock.later_at
    advance_inputs()
    assert universe.discover(clock.now, 2) == snapshot
    assert information.observe(snapshot.markets, clock.now) == observed
    assert information.upcoming(snapshot.markets, clock.now, clock.later_at) == upcoming
    for market, view, fact in baseline:
        assert fair_value.evaluate(market, clock.now) == view
        assert settlement.resolve(market, clock.now) == fact
