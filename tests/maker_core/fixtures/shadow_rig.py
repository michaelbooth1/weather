"""Fixture rig for the shadow runner: one quoting band, CLOB-shaped public replies, guard wallet books.

Synthetic values only (no production data). The book/terms numbers reproduce the
blind-width ``informed_v0`` QUOTE case of ``test_policy``.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

from maker_core.contracts import MarketDescriptor
from maker_core.contracts.portfolio import CAMPAIGNS_SCHEMA, SNAPSHOT_SCHEMA
from maker_core.portfolio.ledger import build_book
from maker_core.runtime import guard_latch
from maker_core.runtime.guard import GUARD_SCHEMA, OrderGate
from maker_core.shadow.runner import ShadowCancelPort, ShadowMarket, ShadowRunner
from maker_core.shadow.tape import PROFILES
from maker_core.contracts import Unavailable

NOW = datetime(2026, 9, 28, 14, 0, tzinfo=timezone.utc)
CONDITION = "0x" + "a" * 64
YES, NO = "111", "222"
ACCOUNT = "0x" + "2" * 40
START = "2026-09-22T00:00:00+00:00"
POLICY = dict(schema_version=GUARD_SCHEMA, campaign_id="weather-maker", max_cash_age_seconds=3600)
CAPS = {"cash": "200", "band_cap": "75", "order_cap": "60", "wallet_cap": "200", "event_cap": "150"}


def campaigns():
    return dict(schema_version=CAMPAIGNS_SCHEMA, account_id=ACCOUNT, default_campaign="owner-discretionary",
                unattributed_cash_pusd="100",
                campaigns=[dict(id="weather-maker", start_utc=START, bleed_limit_pusd="40",
                                contributions=[dict(id="wm-capital", at_utc=START, amount_pusd="100")]),
                           dict(id="owner-discretionary", start_utc=START, contributions=[])],
                lot_overrides=[], rules=[dict(campaign="weather-maker", event_slug_prefix="highest-temperature-in-")])


def wallet_book(*, complete=True, as_of=NOW):
    snap = dict(schema_version=SNAPSHOT_SCHEMA, account_id=ACCOUNT, as_of_utc=as_of.isoformat(), cash_pusd="200",
                positions=[], trades=[], positions_complete=complete, history_complete=complete,
                history_start_utc=START)
    return build_book([snap], campaigns())


def descriptor(condition=CONDITION, yes=YES, no=NO, event="highest-temperature-in-fixture"):
    return MarketDescriptor("weather", event, condition, {"YES": yes, "NO": no}, D(".01"), D(5), None,
                            NOW + timedelta(days=1), None, "F", "fixture", {})


def public_book(asset, condition=CONDITION, bids=(("0.49", "75"),), asks=(("0.51", "75"),)):
    return {"market": condition, "asset_id": asset, "timestamp": "1759068000000", "tick_size": "0.01",
            "min_order_size": "5", "bids": [{"price": p, "size": s} for p, s in bids],
            "asks": [{"price": p, "size": s} for p, s in asks]}


def reward_record(condition=CONDITION):
    return {"condition_id": condition, "rewards_max_spread": 5, "rewards_min_size": 20,
            "rewards_config": [{"rate_per_day": 100, "start_date": "2026-09-01", "end_date": "2500-12-31"}]}


class Reads:
    """In-memory ``PublicReads``; counts calls, has no other method."""

    def __init__(self, books=None, rewards=None):
        self.books = books or {YES: public_book(YES), NO: public_book(NO, bids=(("0.49", "100"),),
                                                                       asks=(("0.51", "100"),))}
        self.rewards = rewards if rewards is not None else {CONDITION: reward_record()}
        self.calls = 0

    def book(self, asset_id):
        self.calls += 1
        return self.books[asset_id]

    def reward_terms(self, condition_id):
        self.calls += 1
        return self.rewards.get(condition_id)


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


def rig(tmp_path, *, wallet=None, reads=None, init_latch=True, placement=None, gate=None, port=None):
    state = tmp_path / "latch"
    clock = Clock()
    if init_latch and not state.exists():
        guard_latch.initialize(state, NOW)
    port = port or ShadowCancelPort()
    gate = gate or OrderGate(state_dir=state, pause_file=tmp_path / "PAUSE", policy=POLICY, campaigns=campaigns(),
                             clock=clock, cancel_port=port)
    book = {"value": wallet if wallet is not None else wallet_book()}
    runner = ShadowRunner(reads=reads or Reads(), gate=gate, cancel_port=port, wallet_book=lambda: book["value"],
                          fair_value=lambda d, now: Unavailable("fixture_no_view", now), clock=clock, caps=CAPS,
                          hazard_per_minute=0.001, adverse_markout=0.0043, profile=PROFILES["informed-v0"],
                          placement=placement)
    return runner, gate, port, clock, book


MARKETS = (ShadowMarket(descriptor(), 1),)
