"""Guards: LOW-ASK-1 finality, fixed-population verdicts and family p-values."""
from datetime import timedelta
from decimal import Decimal

import pytest

from weather.backtesting.low_ask.contracts import CITIES, DATE_COUNT, FIRST
from weather.backtesting.low_ask.inference import ALPHA, evaluate


def make_ledger(cell):
    decisions = []
    for day in range(DATE_COUNT):
        for city_index, city in enumerate(sorted(CITIES)):
            for hour in (17, 18):
                status, net = cell(day, city_index, hour)
                decisions.append({"city": city, "target_date": (FIRST+timedelta(days=day)).isoformat(),
                                  "cut": hour, "status": status, "conservative_net": str(net),
                                  "shares": "5"})
    return {"decisions": decisions, "unresolved": sum(d["status"] == "filled" for d in decisions),
            "doubtful_fills": 0}


def run(ledger, critical=3):
    return evaluate(ledger, calibration={"status": "CALIBRATED", "critical_value": str(critical)},
                    family_pvalues={"F3-SIM-1": .0375}, claimants=["F3-SIM-1", "LOW-ASK-1"],
                    resamples=128)


@pytest.mark.parametrize("critical", [3, 6.375678963765057])
def test_same_verdict_at_two_extreme_payouts_does_not_prove_all_completions(critical):
    # Each unresolved city's two slots hold its same YES token. A given
    # event must pay both slots equally, and cities can resolve differently.
    a = Decimal(".85")
    b = Decimal(".001")
    def cost(ask):
        return 5*(ask+Decimal(".05")*ask*(1-ask)+Decimal(".01"))
    def panel(payout):
        def cell(day, city, hour):
            if 30*(day+1)//DATE_COUNT == 30*day//DATE_COUNT:
                return "resolved", 5-cost(a)
            if payout is None:
                return "filled", -cost(b)
            return "resolved", 5*payout(city)-cost(b)
        return make_ledger(cell)

    assert run(panel(lambda city: 0), critical)["verdict"] == "SUCCESS"
    assert run(panel(lambda city: 1), critical)["verdict"] == "SUCCESS"
    mixed = run(panel(lambda city: int(city == 0)), critical)
    assert mixed["lower"] < 0 and mixed["verdict"] == "NOT_KILLED"
    pending = run(panel(None), critical)
    assert pending["adequate_dates"] == 68 and pending["both_executable_city_days"] == 816
    assert pending["verdict"] == "DESCRIBE" and pending["pvalue"] == 1
    assert pending["all_zero_payout_pvalue"] == ALPHA
    assert not pending["family_holm_pass"]


@pytest.mark.parametrize(("base", "city_shift", "expected"), [
    (.65, 0, "SUCCESS"),
    (-.6, 0, "KILL_POSITIVE_PROFIT"),
    (.14, 0, "KILL_ECONOMIC_MINIMUM"),
    (.20, .12, "NOT_KILLED"),
])
def test_sparse_unknown_retains_certified_verdict_and_conservative_family_p(base, city_shift, expected):
    # A synthetic unresolved fill can finish with any permitted fractional
    # payout. The positive controls ensure missingness alone is no veto.
    def ledger(payout):
        def cell(day, city, hour):
            if (day, city, hour) == (67, 0, 18):
                if payout is None:
                    return "filled", -.11
                return "resolved", 5*payout-.11
            return "resolved", (base+city_shift*(1 if city < 6 else -1))/2
        return make_ledger(cell)

    pending = run(ledger(None))
    assert pending["verdict"] == expected
    bounds = pending["unknown_payout_bounds"]
    assert pending["pvalue"] == bounds["pvalue_upper"]
    for payoff in (0, .175, .5, .875, 1):
        complete = run(ledger(payoff))
        assert complete["verdict"] == expected
        assert bounds["lower_min"] <= complete["lower"] <= bounds["lower_max"]
        assert bounds["upper_min"] <= complete["upper"] <= bounds["upper_max"]
        assert complete["pvalue"] <= pending["pvalue"]
        assert "unknown_payout_bounds" not in complete
