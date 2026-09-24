"""84h payment treatment: pure sizing, never an exchange capability."""
from decimal import Decimal

from weather.market.reward_quote import QuoteRefused, _decimal, price_sized_reward_quote

SIZES = (Decimal(20), Decimal(30), Decimal(50), Decimal(75))


def reserve_budget(available_collateral):
    wallet = _decimal(available_collateral)
    # Owner 2026-09-23: the testing wallet may hold up to 200 pUSD; the reserve ceiling stays 75.
    if not 0 <= wallet <= 200:
        raise QuoteRefused('testing_wallet_cap')
    return min(wallet - 10, Decimal(75))


def session_caps(size, available_collateral):
    size = _decimal(size)
    if size not in SIZES:
        raise QuoteRefused('invalid_treatment_size')
    return Decimal('.79') * size, min(Decimal('.98') * size, reserve_budget(available_collateral))


def sized_quote(snapshot, available_collateral):
    """Take the largest affordable size; all proposals use the same estimator."""
    budget = reserve_budget(available_collateral)
    for size in reversed(SIZES):
        # Price first: affordability depends on the two outward-snapped prices.
        # A smaller size cannot cure any non-capital pricing refusal.
        quote = price_sized_reward_quote(**snapshot['quote_inputs'], size=size,
                                   per_order_ceiling=Decimal('.8') * size,
                                   per_band_ceiling=size)
        if quote.reserve_pusd <= budget:
            return quote
    raise QuoteRefused('insufficient_size_reserve')
