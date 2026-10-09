"""Capital allocation regressions; all balances and identities are fixtures."""
from decimal import Decimal

import pytest

from weather.market.mm_pilot_capital import (
    collateral_backs_pilot_budget,
    collateral_within_capital_scope,
    pilot_capital_limit,
)


def allocation_contract():
    return {
        "pilot_capital_mode": "existing_wallet_test_allocation",
        "pilot_test_allocation_pusd": 100,
        "isolated_pilot_wallet": False,
        "pilot_wallet_max_funding_usdc": None,
    }


def test_existing_wallet_balance_is_distinct_from_testing_allocation():
    contract = allocation_contract()
    assert pilot_capital_limit(contract, require_wallet_declaration=True) == Decimal("100")
    assert collateral_within_capital_scope(contract, Decimal("275.48"))
    assert contract["pilot_wallet_max_funding_usdc"] is None


@pytest.mark.parametrize("amount", [100.01, 0, -1, True, None, "NaN", "Infinity", "-Infinity"])
def test_invalid_allocations_fail_closed(amount):
    contract = allocation_contract()
    contract["pilot_test_allocation_pusd"] = amount
    with pytest.raises(ValueError):
        pilot_capital_limit(contract)
    assert not collateral_within_capital_scope(contract, 275.48)


@pytest.mark.parametrize("mutation", [
    {"pilot_capital_mode": "unknown"},
    {"isolated_pilot_wallet": True},
    {"pilot_wallet_max_funding_usdc": 100},
])
def test_mixed_contracts_fail_closed(mutation):
    contract = {**allocation_contract(), **mutation}
    with pytest.raises(ValueError):
        pilot_capital_limit(contract)
    assert not collateral_within_capital_scope(contract, 275.48)


@pytest.mark.parametrize("key", list(allocation_contract()))
def test_incomplete_allocation_contracts_fail_closed(key):
    contract = allocation_contract()
    del contract[key]
    with pytest.raises(ValueError):
        pilot_capital_limit(contract, require_wallet_declaration=True)


def test_isolated_wallet_keeps_its_whole_balance_ceiling():
    contract = {"isolated_pilot_wallet": True, "pilot_wallet_max_funding_usdc": 100}
    assert pilot_capital_limit(contract, require_wallet_declaration=True) == 100
    assert collateral_within_capital_scope(contract, 100)
    assert not collateral_within_capital_scope(contract, 100.01)


@pytest.mark.parametrize("balance", [True, None, -1, "NaN", "Infinity", "-Infinity"])
def test_invalid_cash_never_passes_an_allocation_contract(balance):
    assert not collateral_within_capital_scope(allocation_contract(), balance)


@pytest.mark.parametrize("balance, allowance, budget, passes", [
    (275.48, 10, 10, True),
    (10, 10, 10, True),
    (9.99, 100, 10, False),
    (275.48, 9.99, 10, False),
    (275.48, 1000, 100.01, False),
    (275.48, 1000, 0, False),
])
def test_snapshot_backs_the_budget_without_capping_existing_wallet_cash(
    balance, allowance, budget, passes
):
    assert collateral_backs_pilot_budget(
        allocation_contract(), balance=balance, allowance=allowance, requested_budget=budget
    ) is passes


@pytest.mark.parametrize("field", ["balance", "allowance", "requested_budget"])
@pytest.mark.parametrize("invalid", [True, None, "NaN", "Infinity", "-Infinity", ""])
def test_snapshot_rejects_invalid_numeric_evidence(field, invalid):
    values = {"balance": 275.48, "allowance": 1000, "requested_budget": 10}
    values[field] = invalid
    assert not collateral_backs_pilot_budget(allocation_contract(), **values)


def test_snapshot_keeps_the_isolated_wallet_ceiling():
    contract = {"isolated_pilot_wallet": True, "pilot_wallet_max_funding_usdc": 100}
    assert collateral_backs_pilot_budget(contract, balance=100, allowance=1000, requested_budget=10)
    assert not collateral_backs_pilot_budget(contract, balance=100.01, allowance=1000, requested_budget=10)
