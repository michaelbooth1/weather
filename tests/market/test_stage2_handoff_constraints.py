"""Cheapest falsifiers for mission 09-80a; no client or credential is opened."""

from decimal import Decimal

import pytest

from weather.market.mm_pilot_capital import (
    collateral_backs_pilot_budget,
    pilot_capital_limit,
)


@pytest.mark.parametrize("cash", ["275.48", "447.01397", "489.60767"])
def test_recorded_stage1_cash_fails_the_restored_isolated_wallet_contract(cash):
    # Published item-67 amounts, not an account read. Evaluate the real validator
    # with both declarations; never patch a control or relabel the old wallet.
    allocation = {
        "pilot_capital_mode": "existing_wallet_test_allocation",
        "pilot_test_allocation_pusd": 100,
        "isolated_pilot_wallet": False,
        "pilot_wallet_max_funding_usdc": None,
    }
    isolated = {"isolated_pilot_wallet": True, "pilot_wallet_max_funding_usdc": 100}
    assert collateral_backs_pilot_budget(
        allocation, balance=Decimal(cash), allowance=1000, requested_budget=10,
    )
    assert not collateral_backs_pilot_budget(
        isolated, balance=Decimal(cash), allowance=1000, requested_budget=10,
    )
    with pytest.raises(ValueError, match="inconsistent"):
        pilot_capital_limit({**allocation, "isolated_pilot_wallet": True})


def test_dedicated_wallet_can_back_a_fresh_request_without_relaxation():
    assert collateral_backs_pilot_budget(
        {"isolated_pilot_wallet": True, "pilot_wallet_max_funding_usdc": 100},
        balance=50, allowance=50, requested_budget=10,
    )
