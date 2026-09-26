"""Frozen reward kernels copied from reward_share_estimate at 2190e64e; no IO."""
import math

SINGLE_SIDED_MIDRANGE_DIVISOR = 3.0
TWO_SIDED_REQUIRED_OUTSIDE = (0.10, 0.90)
DEFAULT_TICK = 0.01
QUOTE_SIZES = (20.0, 100.0)
QUOTE_DISTANCES_CENTS = (1.0, 2.0, 3.0)

def order_score(size, distance_cents, max_spread_cents, min_size, multiplier=1.0):
    """S(v, s) = ((v - s) / v)^2 * size; 0 below min size or at/beyond v.

    Float port of ``maker_incentive_feasibility._order_score`` (PR 55 /
    ``codex/48h-maker-integration-20260912``). That version takes a BuyQuote and
    Decimal market terms and measures distance in probability units; this one
    takes the distance directly, in cents. Same zero conditions, same quadratic.
    """

    if size is None or distance_cents is None:
        return 0.0
    if not max_spread_cents or max_spread_cents <= 0:
        return 0.0
    if size <= 0 or size < min_size:
        return 0.0
    distance = abs(distance_cents)
    if distance >= max_spread_cents:
        return 0.0
    return size * ((max_spread_cents - distance) / max_spread_cents) ** 2 * multiplier


def q_min(
    q_one,
    q_two,
    midpoint,
    divisor=SINGLE_SIDED_MIDRANGE_DIVISOR,
    interval=TWO_SIDED_REQUIRED_OUTSIDE,
):
    """Float port of ``maker_incentive_feasibility._q_min`` (inclusive interval)."""

    both = min(q_one, q_two)
    if interval[0] <= midpoint <= interval[1]:
        return max(both, max(q_one, q_two) / divisor)
    return both


def share_of(own_q, competing_q):
    if own_q <= 0:
        return 0.0
    return own_q / (own_q + max(competing_q, 0.0))


def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def parse_levels(raw_levels):
    """Return ([(price, size), ...], malformed_level_count)."""

    levels = []
    malformed = 0
    if not isinstance(raw_levels, (list, tuple)):
        return levels, (0 if raw_levels is None else 1)
    for level in raw_levels:
        if not isinstance(level, dict):
            malformed += 1
            continue
        price = _num(level.get("price"))
        size = _num(level.get("size"))
        if price is None or size is None or not (0.0 < price < 1.0) or size <= 0:
            malformed += 1
            continue
        levels.append((price, size))
    return levels, malformed


def best_prices(bids, asks, size_cutoff=0.0):
    bid_prices = [price for price, size in bids if size >= size_cutoff]
    ask_prices = [price for price, size in asks if size >= size_cutoff]
    return (max(bid_prices) if bid_prices else None, min(ask_prices) if ask_prices else None)


def side_score(levels, midpoint, max_spread_cents, min_size):
    """Competing qualifying score and qualifying displayed size on one side."""

    total = 0.0
    qualifying_size = 0.0
    for price, size in levels:
        score = order_score(size, (price - midpoint) * 100.0, max_spread_cents, min_size)
        if score > 0:
            total += score
            qualifying_size += size
    return total, qualifying_size


def _floor_to_tick(value, tick):
    return round(math.floor(value / tick + 1e-9) * tick, 9)


def _ceil_to_tick(value, tick):
    return round(math.ceil(value / tick - 1e-9) * tick, 9)


def hypothetical_quote(midpoint, distance_cents, tick=DEFAULT_TICK):
    """Two-sided quote at >= ``distance_cents`` from mid, snapped outward to tick.

    A side that cannot be priced inside (0, 1) is absent (price None).
    """

    tick = tick if tick and tick > 0 else DEFAULT_TICK
    bid = _floor_to_tick(midpoint - distance_cents / 100.0, tick)
    ask = _ceil_to_tick(midpoint + distance_cents / 100.0, tick)
    if bid < tick - 1e-12:
        bid = None
    if ask > 1.0 - tick + 1e-12:
        ask = None
    return {
        "bid_price": bid,
        "ask_price": ask,
        "bid_distance_cents": None if bid is None else round((midpoint - bid) * 100.0, 9),
        "ask_distance_cents": None if ask is None else round((ask - midpoint) * 100.0, 9),
    }


def quote_capital(size, bid_price, ask_price):
    """YES bid costs N * p_bid; the ask-equivalent NO bid costs N * (1 - p_ask)."""

    capital = 0.0
    if bid_price is not None:
        capital += size * bid_price
    if ask_price is not None:
        capital += size * (1.0 - ask_price)
    return capital


def evaluate_sample(
    bids,
    asks,
    *,
    max_spread_cents,
    min_size,
    tick=DEFAULT_TICK,
    sizes=QUOTE_SIZES,
    distances_cents=QUOTE_DISTANCES_CENTS,
    min_size_for_mid=False,
):
    """Score one displayed YES book and our hypothetical quotes against it."""

    cutoff = min_size if min_size_for_mid else 0.0
    best_bid, best_ask = best_prices(bids, asks, cutoff)
    if best_bid is None or best_ask is None:
        return {"status": "one_sided_book"}
    if best_bid >= best_ask:
        return {"status": "crossed_book"}
    midpoint = (best_bid + best_ask) / 2.0
    comp_one, size_one = side_score(bids, midpoint, max_spread_cents, min_size)
    comp_two, size_two = side_score(asks, midpoint, max_spread_cents, min_size)
    competing_single = q_min(comp_one, comp_two, midpoint)
    competing_many = (comp_one + comp_two) / 2.0
    quotes = {}
    for size in sizes:
        if size < min_size:
            continue
        for distance in distances_cents:
            quote = hypothetical_quote(midpoint, distance, tick)
            own_one = order_score(size, quote["bid_distance_cents"], max_spread_cents, min_size)
            own_two = order_score(size, quote["ask_distance_cents"], max_spread_cents, min_size)
            own_q = q_min(own_one, own_two, midpoint)
            quotes[(float(size), float(distance))] = {
                **quote,
                "own_q_min": own_q,
                "share_single": share_of(own_q, competing_single),
                "share_many": share_of(own_q, competing_many),
                "capital_pusd": quote_capital(size, quote["bid_price"], quote["ask_price"]),
                "two_sided": quote["bid_price"] is not None and quote["ask_price"] is not None,
            }
    return {
        "status": "ok",
        "midpoint": midpoint,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "competing_q_one": comp_one,
        "competing_q_two": comp_two,
        "competing_single": competing_single,
        "competing_many": competing_many,
        "qualifying_size_one": size_one,
        "qualifying_size_two": size_two,
        "quotes": quotes,
    }


# --------------------------------------------------------------------------
