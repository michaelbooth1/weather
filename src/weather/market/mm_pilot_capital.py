"""Public capital contracts for the attended International Stage 0/1 test.

An existing wallet allocation limits this test's authority, not the wallet's
balance. The sealed session still permits only two single-submit BUY probes,
each at most 10 pUSD, and stops on a fill. This is not general runner authority.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from weather.market.market_making_run_constants import MAX_OPERATOR_PILOT_BUDGET_USDC


EXISTING_WALLET_ALLOCATION = "existing_wallet_test_allocation"
ALLOCATION_KEYS = {"pilot_capital_mode", "pilot_test_allocation_pusd"}


def pilot_capital_limit(payload, *, require_wallet_declaration=True):
    """Return the test capital limit, rejecting mixed or malformed contracts.

    Legacy funding fields retain their whole-wallet meaning. Current identity
    and bootstrap artifacts and gate summaries preserve the wallet declaration.
    """

    allocation_fields = ALLOCATION_KEYS.intersection(payload)
    if allocation_fields:
        if not (
            allocation_fields == ALLOCATION_KEYS
            and payload.get("pilot_capital_mode") == EXISTING_WALLET_ALLOCATION
            and payload.get("isolated_pilot_wallet") is False
            and "pilot_wallet_max_funding_usdc" in payload
            and payload["pilot_wallet_max_funding_usdc"] is None
        ):
            raise ValueError("test allocation and wallet funding contracts are inconsistent")
        raw = payload.get("pilot_test_allocation_pusd")
    else:
        if require_wallet_declaration and payload.get("isolated_pilot_wallet") is not True:
            raise ValueError("isolated wallet declaration is required")
        raw = payload.get("pilot_wallet_max_funding_usdc")
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("pilot capital limit is invalid") from exc
    if (
        isinstance(raw, bool)
        or not amount.is_finite()
        or not Decimal("0") < amount <= Decimal(str(MAX_OPERATOR_PILOT_BUDGET_USDC))
    ):
        raise ValueError("pilot capital limit is outside the operator allocation")
    return amount


def collateral_within_capital_scope(payload, balance):
    """Enforce a whole-wallet ceiling only for the isolated-wallet contract."""

    try:
        cap = pilot_capital_limit(payload)
        amount = Decimal(str(balance))
        return (
            not isinstance(balance, bool)
            and amount.is_finite()
            and amount >= 0
            and (
                payload.get("pilot_capital_mode") == EXISTING_WALLET_ALLOCATION
                or amount <= cap
            )
        )
    except (InvalidOperation, TypeError, ValueError):
        return False


def collateral_backs_pilot_budget(payload, *, balance, allowance, requested_budget):
    """Check a collateral snapshot against the declared test allocation."""

    try:
        if any(isinstance(value, bool) for value in (balance, allowance, requested_budget)):
            return False
        cash, approved, budget = (
            Decimal(str(value)) for value in (balance, allowance, requested_budget)
        )
        return (
            all(value.is_finite() for value in (cash, approved, budget))
            and Decimal("0") < budget <= pilot_capital_limit(payload)
            and budget <= cash
            and budget <= approved
            and collateral_within_capital_scope(payload, cash)
        )
    except (InvalidOperation, TypeError, ValueError):
        return False


def capital_declaration(payload):
    """Copy the public contract without relabelling allocation as wallet funding."""

    result = {
        "isolated_pilot_wallet": payload.get("isolated_pilot_wallet"),
        "pilot_wallet_max_funding_usdc": payload.get("pilot_wallet_max_funding_usdc"),
    }
    for key in ALLOCATION_KEYS:
        if key in payload:
            result[key] = payload[key]
    return result
