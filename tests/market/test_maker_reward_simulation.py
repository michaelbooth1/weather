from dataclasses import replace
from decimal import Decimal, localcontext
import hashlib
from pathlib import Path

import pytest

import weather.market.maker_reward_simulation as simulator
from weather.market.maker_opportunity_capture import parse_json_bytes

D = Decimal


def test_published_formula_and_self_in_denominator():
    result = simulator.simulate(replace(simulator.Simulation(), other_q="20"))
    assert float(result["submitted_q_min"]) == pytest.approx(80 / 27)
    assert float(result["horizons"][-1]["sample_share"]) == pytest.approx(4 / 31)
    assert float(result["horizons"][-1]["gross_reward"]) == pytest.approx(176 / 31)
    assert result["live_order_authority"] is False
    assert result["paid_rewards"] is None and result["realized_pnl"] is None


def test_two_buy_sides_boost_score_but_require_simultaneous_backing():
    solo = simulator.simulate(simulator.Simulation())
    both = simulator.simulate(replace(simulator.Simulation(), plan="BOTH"))
    assert float(both["submitted_q_min"]) == pytest.approx(float(solo["submitted_q_min"]) * 3)
    assert "capital:order_cap" in both["blockers"]["capital"]
    assert both["horizons"][-1]["gross_reward"] is None
    backed = simulator.simulate(replace(simulator.Simulation(), plan="BOTH", order_cap="20"))
    assert backed["modeled_feasible"]
    assert backed["capital"]["total_with_cleanup"] == D("29.6")


def test_partial_fill_below_cutoff_erases_score_without_freeing_inventory_capital():
    result = simulator.simulate(replace(simulator.Simulation(), yes_remaining=".99", other_q="20"))
    assert result["remaining_q_min"] == 0
    assert result["horizons"][-1]["gross_reward"] == 0
    capital = result["capital"]
    assert capital["filled_inventory_cost"] == D(".078")
    assert capital["remaining_order_reserves"] == D("7.722")
    assert capital["total_with_cleanup"] == D("17.8")
    assert result["modeled_cost_collateral"] == D(".254")


def test_minimum_applies_to_separate_completed_days_without_carry():
    result = simulator.simulate(simulator.Simulation())
    assert D(0) < result["horizons"][-1]["gross_reward"] < D(1)
    assert all(row["modeled_day_payout"] == 0 for row in result["horizons"])
    assert result["horizons"][-1]["net_collateral"] == D("-.25")
    above = simulator.simulate(replace(simulator.Simulation(), other_q="20"))
    assert above["horizons"][0]["modeled_day_payout"] == 0
    assert above["horizons"][-1]["modeled_day_payout"] > 1


@pytest.mark.parametrize("midpoint,positive", [(".09", False), (".10", True), (".90", True), (".91", False)])
def test_midpoint_edges_apply_documented_one_sided_rule(midpoint, positive):
    # Wider scenario spread keeps the chosen quote inside the reward band.
    result = simulator.simulate(replace(simulator.Simulation(), midpoint=midpoint, max_spread_cents="90"))
    assert (result["submitted_q_min"] > 0) is positive


def test_participation_and_conversion_are_explicit_not_observed_parity():
    full = simulator.simulate(replace(simulator.Simulation(), other_q="20", payout_minimum="0"))
    half = simulator.simulate(replace(simulator.Simulation(), other_q="20", participation=".5", reward_to_collateral=".8", payout_minimum="0"))
    day = half["horizons"][-1]
    assert float(day["gross_reward"]) == pytest.approx(float(full["horizons"][-1]["gross_reward"]) / 2)
    assert float(day["net_collateral"]) == pytest.approx(float(day["gross_reward"]) * .8 - .25)
    assert day["zero_payment_net_collateral"] == D("-.25")


@pytest.mark.parametrize("changes", [
    {"yes_price": ".391"}, {"yes_price": ".41"}, {"yes_price": ".01"},
    {"yes_shares": "4"}, {"wallet": "5"},
])
def test_invalid_or_ineligible_plan_has_no_positive_reward_estimate(changes):
    result = simulator.simulate(replace(simulator.Simulation(), **changes))
    assert not result["modeled_feasible"]
    assert all(row["gross_reward"] is None for row in result["horizons"])


@pytest.mark.parametrize("changes", [
    {"other_q": "NaN"}, {"midpoint": "Infinity"}, {"participation": "1.01"},
    {"reward_to_collateral": "0"}, {"yes_remaining": "-.1"}, {"pool": "0"},
])
def test_bad_inputs_fail_closed(changes):
    with pytest.raises(ValueError):
        simulator.simulate(replace(simulator.Simulation(), **changes))


def test_decimal_context_does_not_change_reproduction():
    expected = simulator.simulate(simulator.Simulation())
    with localcontext() as ctx:
        ctx.prec = 6
        actual = simulator.simulate(simulator.Simulation())
    assert actual == expected


def test_zero_competition_and_zero_participation_are_bounded():
    full = simulator.simulate(replace(simulator.Simulation(), other_q="0"))
    assert full["horizons"][-1]["gross_reward"] == 44
    absent = simulator.simulate(replace(simulator.Simulation(), participation="0"))
    assert all(row["gross_reward"] == 0 for row in absent["horizons"])


@pytest.mark.parametrize("body", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'])
def test_uploaded_capture_parser_rejects_ambiguous_json(body):
    with pytest.raises(ValueError):
        parse_json_bytes(body)


def test_uploaded_capture_parser_has_exact_byte_limit():
    assert parse_json_bytes(b"{}", max_bytes=2) == {}
    with pytest.raises(ValueError):
        parse_json_bytes(b"{}", max_bytes=1)


def test_simulation_import_witness():
    root = Path(__file__).resolve().parents[2]
    path = Path(simulator.__file__).resolve()
    assert path == root / "src/weather/market/maker_reward_simulation.py"
    print({"module": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
