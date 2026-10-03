from decimal import Decimal as D
import pytest

from maker_core.replay import _fill89a
from maker_core.replay.bundle import BundleError
from maker_core.replay.engine import ReplayConfig, replay
from tests.maker_core.fixtures import fill89a_reference
from .fixtures.replay_scenario import Scenario


@pytest.mark.parametrize("rule", ["conservative", "optimistic"])
def test_lifted_simulate_matches_frozen_89a_callbacks(rule):
    def run(module):
        fills, exposure, quotes, diagnostics = [], [], [], {}
        books = [module.Book(t, ((.49, 100),), ((.51, 100),), .01) for t in (0, 60, 180)]
        prints = [module.Print(t, price, size) for t, price, size in
                  ((1, .48, 5), (2, .47, 8), (3, .53, 30), (60, .47, 50), (75, .52, 10), (190, .53, 2))]
        module.simulate(books, prints, start=0, end=240,
                        terms_at=lambda t: module.Terms(0, 100, 20, 5), windows=[], band="a",
                        distance=1.5, rule=rule, exposure=lambda *x: exposure.append(x),
                        fill=lambda *x: fills.append(x), diagnostics=diagnostics,
                        quote_record=lambda *x: quotes.append(x))
        return fills, exposure, quotes, diagnostics
    assert run(_fill89a) == run(fill89a_reference)


@pytest.mark.parametrize("bound", ["strictly_through", "at_price"])
def test_fill_bounds_at_price_and_sibling_cancel(tmp_path, bound):
    s = Scenario(markets=("a",), minutes=2)
    s.book("a", 0)
    s.trade("a", 5, ".48", "7")
    s.trade("a", 6, ".53", "100")
    result = replay((s.bundle(tmp_path / "bundle"),), ReplayConfig(hazard_per_minute=.001, fill_bound=bound))
    assert len(result.fills) == 1
    if bound == "at_price":
        assert result.fills[0].size == D(7)
        assert result.fills[0].outcome == "YES"
        assert result.final_cash == D("96.64")
        assert not any(span.legs for span in result.spans if span.start >= s.at(5))
    else:
        assert result.fills[0].at == s.at(6)
        assert result.fills[0].outcome == "NO"
        assert result.fills[0].size == D(30)


def test_equal_time_trade_hits_old_quote_before_replacement(tmp_path):
    s = Scenario(markets=("a",), minutes=3)
    s.book("a", 0)
    s.book("a", 60, mid=D(".52"))
    s.trade("a", 60, ".47", "100")
    result = replay((s.bundle(tmp_path / "bundle"),), ReplayConfig(hazard_per_minute=.001))
    assert len(result.fills) == 1
    assert result.fills[0].price == D(".48")
    assert not any(d.at == s.at(60) and d.decision.action == "QUOTE" for d in result.decisions)


def test_missing_trade_health_is_excluded_not_zero_fills(tmp_path):
    s = Scenario(markets=("a",), minutes=2)
    s.book("a", 0)
    s.records = [r for r in s.records if r["kind"] != "coverage"]
    s.trade("a", 10)
    result = replay((s.bundle(tmp_path / "bundle"),), ReplayConfig(hazard_per_minute=.001))
    assert not result.fills
    assert all(not span.covered and not span.legs for span in result.spans)


def test_concurrent_markets_cannot_spend_or_reserve_more_than_cash(tmp_path):
    s = Scenario(minutes=3)
    for market in s.markets:
        s.book(market, 0)
        s.trade(market, 10, ".47", "100")
        s.book(market, 60)
    result = replay((s.bundle(tmp_path / "bundle"),),
                    ReplayConfig(hazard_per_minute=.001, initial_cash=D(40), wallet_cap=D(40)))
    assert len(result.fills) == 1
    assert sum(fill.cost for fill in result.fills) <= D(40)
    assert result.final_cash >= 0
    for at in {span.start for span in result.spans}:
        spans = [span for span in result.spans if span.start == at]
        assert sum(span.reserved + span.inventory_cost for span in spans) <= D(40)


def test_duplicate_print_does_not_fill_again_and_conflict_refuses(tmp_path):
    s = Scenario(markets=("a",), minutes=3)
    s.book("a", 0)
    s.trade("a", 10, trade_id="same")
    original = s.records[-1]
    from copy import deepcopy
    duplicate = deepcopy(original)
    duplicate["sequence"] += 1
    duplicate["captured_at"] = s.at(61).isoformat()
    s.records.append(duplicate)
    s.book("a", 60)
    result = replay((s.bundle(tmp_path / "ok"),), ReplayConfig(hazard_per_minute=.001))
    assert len(result.fills) == 1
    duplicate["payload"]["size"] = "11"
    from maker_core.evidence.journal import canonical_bytes
    from maker_core.replay.bundle import sha256
    duplicate["payload_sha256"] = sha256(canonical_bytes(duplicate["payload"]))
    with pytest.raises(BundleError, match="conflicting_duplicate_trade"):
        replay((s.bundle(tmp_path / "bad"),), ReplayConfig(hazard_per_minute=.001))
