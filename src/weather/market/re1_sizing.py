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


def pilot_quote(snapshot, *, size, l_total, l_resting, available_collateral, budget,
                share_range=(Decimal('.15'), Decimal('.70')), leg_range=(Decimal('.17'), Decimal('.80'))):
    """Live-fill calibration campaign (lfc_constants): one fixed size, priced exactly as RE-1 prices it.

    Signed pre-registration sections 3 and 6: L + reserve <= budget with reserve = size x (p_yes + p_no); available
    cash >= L_resting + reserve; predicted share_many inside share_range; both leg prices inside leg_range (each leg
    cost <= 0.8 x size is the per-order ceiling). Never an exchange capability.
    """
    size, l_total, l_resting, cash, budget = map(_decimal, (size, l_total, l_resting, available_collateral, budget))
    if not 0 <= l_resting <= l_total:
        raise QuoteRefused('ledger_figures_invalid')
    quote = price_sized_reward_quote(**snapshot['quote_inputs'], size=size,
                                     per_order_ceiling=Decimal('.8') * size, per_band_ceiling=size)
    if not share_range[0] <= Decimal(str(quote.share_many)) <= share_range[1]:
        raise QuoteRefused('share_many_outside_range')
    if not all(leg_range[0] <= price <= leg_range[1] for price in (quote.yes_buy, quote.no_buy)):
        raise QuoteRefused('leg_price_outside_range')
    if l_total + quote.reserve_pusd > budget:
        raise QuoteRefused('l_budget_refused')
    if cash < l_resting + quote.reserve_pusd:
        raise QuoteRefused('cash_below_l_resting_plus_reserve')
    return quote
