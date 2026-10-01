from decimal import Decimal as D
import pytest

from maker_core.replay.engine import replay, ReplayConfig
from maker_core.replay.score import score, nominal_rebate
from .fixtures.replay_scenario import Scenario


def test_rewards_terms_change_and_half_sensitivity(tmp_path):
    s = Scenario(markets=("a",), minutes=2)
    s.book("a", 0)
    s.book("a", 60)
    s.terms("a", 60, rate=D(50))
    result = replay([s.bundle(tmp_path/"b")], ReplayConfig(hazard_per_minute=0))
    r, = score(result)
    shares = [x.share_many for x in result.spans if x.legs]
    assert r["reward_k1"] == (D(100)*D(str(shares[0])) + D(50)*D(str(shares[1]))) / 1440
    assert r["reward_k05"] == r["reward_k1"] / 2
    assert r["covered_seconds"] == 120
    assert r["maker_fees"] == 0


def test_settlement_and_markouts_do_not_double_count(tmp_path):
    s = Scenario(markets=("a",), minutes=40)
    for minute in range(40):
        s.book("a", minute*60)
    s.trade("a", 30)
    s.settle("a", 2400)
    result = replay([s.bundle(tmp_path/"b")], ReplayConfig(hazard_per_minute=0))
    r, = score(result)
    f, = result.fills
    assert r["settled_inventory_pnl"] == f.size * (1-f.price)
    assert r["nominal_rebate"] == nominal_rebate(f.price) * f.size
    for h in ("1m", "5m", "30m"):
        assert r["markouts"][h]["per_share"] == D(".5") - f.price
    assert r["markouts"]["settlement"]["pnl"] == r["settled_inventory_pnl"]
    assert r["modeled_net_k1"] == r["reward_k1"] + r["nominal_rebate"] + r["settled_inventory_pnl"]
    assert r["inventory_cash_hours"] == f.cost * D(2370) / 3600
    assert result.final_cash == result.config.initial_cash + r["settled_inventory_pnl"]


def test_gaps_and_unsettled_fills_are_not_zero(tmp_path):
    s = Scenario(markets=("a",), minutes=5)
    s.book("a", 0)
    s.trade("a", 30)
    result = replay([s.bundle(tmp_path/"b")], ReplayConfig(hazard_per_minute=0))
    r, = score(result)
    assert r["excluded_seconds"] == 240
    assert r["status"] == "PARTIAL"
    assert r["unresolved_fills"] == 1
    assert r["modeled_net_k1"] is None
    assert r["markouts"]["1m"]["per_share"] is None
    assert r["markouts"]["settlement"]["missing_fills"] == 1
    # Inventory remains tied up after the quote window, through the closed-day boundary.
    assert r["inventory_cash_hours"] == result.fills[0].cost * D(86400-30) / 3600


@pytest.mark.parametrize("price", [D(".1"), D(".5"), D(".9")])
def test_nominal_rebate_matches_owning_module(price):
    from weather.market.execution_tape_markout import maker_rebate_per_share, maker_markout
    assert float(nominal_rebate(price)) == pytest.approx(maker_rebate_per_share(float(price)))
    assert float(D(".6")-price) == pytest.approx(maker_markout("bought", float(price), .6))
