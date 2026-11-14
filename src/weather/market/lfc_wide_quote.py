"""Pure wide normal proposal and scoring evidence. Proposals grant no authority."""
from decimal import Decimal

from weather.market.lfc_accounting import quantity
from weather.market.reward_quote import QuoteRefused, price_sized_reward_quote
from weather.market.reward_share_estimate import order_score


CORRIDOR = (Decimal('2.5'), Decimal('4.5'))


def distance(mid, leg, price):
    return ((quantity(mid) if leg == 0 else 1 - quantity(mid)) - quantity(price)) * 100


def entry_allowed(mid, prices, legs, maximum):
    """Entry is open at 4.5c, even if a venue declares a wider spread."""
    maximum = min(quantity(maximum), CORRIDOR[1])
    return all(CORRIDOR[0] <= distance(mid, leg, prices[leg]) < maximum for leg in legs)


def requote_legs(mid, prices, legs):
    """Resting legs keep the inclusive band; new entries use entry_allowed."""
    return [leg for leg in legs if not CORRIDOR[0] <= distance(mid, leg, prices[leg]) <= CORRIDOR[1]]


def price_quote(*, quote_offset_mode='standard', wide_offset_cents='3.0', **inputs):
    if quote_offset_mode == 'standard':
        return price_sized_reward_quote(**inputs)
    if quote_offset_mode != 'wide' or quantity(wide_offset_cents) != 3:
        raise QuoteRefused('unsupported_wide_quote_policy')
    quote = price_sized_reward_quote(**{**inputs, 'quote_offset': '.030', 'distance_window': CORRIDOR})
    if not entry_allowed(quote.adjusted_mid, (quote.yes_buy, quote.no_buy),
                         inputs.get('trade_legs', (0, 1)), inputs['reward_max_spread_cents']):
        raise QuoteRefused('wide_entry_outside_reward_corridor')
    return quote


def order_evidence(*, mid, leg, price, size, minimum, maximum, mode, offset):
    actual = distance(mid, leg, price)
    return {'quote_offset_mode': mode, 'quote_offset_cents': str(quantity(offset) * 100),
            'scoring_distance_cents': str(actual),
            'native_leg_reward_score': order_score(float(quantity(size)), float(actual),
                float(quantity(maximum)), float(quantity(minimum)))}
