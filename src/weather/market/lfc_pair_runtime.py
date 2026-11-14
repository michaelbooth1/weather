"""Minimal complete-pairs hooks for the existing guarded F2 band runtime.

No order adapter, account client or alternate submit path lives here. These
helpers prepare prices/legs and journal evidence; ordinary controls own actions.
"""
from decimal import Decimal

from weather.market.lfc_pair_completion import COMPLETE_PAIRS, SIZE, inventory, mode, quote
from weather.market.mm_stage2_hold import HoldEnd, digest


WAIT = 'completion_price_wait'


def enabled(band):
    return mode(band.campaign_policy.raw) == COMPLETE_PAIRS


def transport_legs(policy, normal_legs):
    """An exact token pair lets the cheap arm buy its expensive complement."""
    return (0, 1) if mode(policy.raw) == COMPLETE_PAIRS else tuple(normal_legs)


def initialize(band):
    if not enabled(band):
        return
    from weather.market.lfc_capital import CapitalBook
    band.normal_trade_legs = tuple(band.TRADE_LEGS)
    band.pair_state = inventory((), campaign_id=band.campaign_policy.raw['campaign_id'], condition_id=band.condition)
    if any(lot['condition_id'] == band.condition and lot['remaining_quantity']
           for lot in CapitalBook(band.ledger).lots.values()):
        band.pair_state = None  # Fresh canonical own-trade proof must restore U.
    band.pair_latest_trades, band.pair_completion_orders, band.pair_seen_fills = None, set(), set()
    band.pair_since, band.pair_elapsed, band.pair_state_sha = None, Decimal(0), None
    band.pair_last_quote = None
    band.scope['post_fill_mode'] = COMPLETE_PAIRS


def require_state(band):
    state = getattr(band, 'pair_state', None)
    if state is None:
        raise HoldEnd('completion_inventory_unproven')
    return state


def elapsed(band):
    if band.pair_since is None:
        return band.pair_elapsed
    now = min(band.clock.now(), band.end)
    return band.pair_elapsed+Decimal(str(max(0, (now-band.pair_since).total_seconds())))


def accept_inventory(band, state, records):
    """Called only after existing inventory/terminal proof, including cleanup."""
    now = min(band.clock.now(), band.end)
    identity = digest({'state': state.evidence(), 'fills': [
        {key: value for key, value in row.items() if key != 'provenance'} for row in records]})
    if identity == band.pair_state_sha:
        return
    if state.completing and band.pair_since is None:
        earliest = min((lot.at_utc for lot, _ in state.residuals), default=now)
        band.pair_since = min(now, max(band.start, earliest))
        band.journal.record('pair_completion_entered', completion_since_utc=band.pair_since.isoformat())
    elif not state.completing and band.pair_since is not None:
        band.pair_elapsed = elapsed(band)
        band.pair_since = None
        band.journal.record('pair_completion_exited', completion_seconds=str(band.pair_elapsed))
    band.pair_state, band.pair_state_sha = state, identity
    band.TRADE_LEGS = (state.completion_leg,) if state.completing else band.normal_trade_legs
    for row in records:
        key = row['trade_id'], row['own_order_id']
        if (row['condition_id'] == band.condition and row['money_counted'] and
                key not in band.pair_seen_fills and row['own_order_id'] in band.pair_completion_orders):
            band.journal.record('pair_completion_fill', fill=row, **state.evidence())
        if row['money_counted']:
            band.pair_seen_fills.add(key)
    band.journal.record('pair_completion_inventory', **state.evidence(),
        effective_trade_legs=list(band.TRADE_LEGS), normal_trade_legs=list(band.normal_trade_legs),
        completion_seconds=str(elapsed(band)), pair_allocations=[p.evidence() for p in state.pairs],
        canonical_own_fills=[r for r in records if r['condition_id'] == band.condition])


def refresh_from_read(band, read):
    if not enabled(band):
        return
    from weather.market.lfc_pair_inventory import from_read
    state, records = from_read(band.ledger, read, campaign_id=band.campaign_policy.raw['campaign_id'],
                               condition_id=band.condition, tokens=band.tokens)
    band.pair_latest_trades = read['trades']
    accept_inventory(band, state, records)


def remember_trades(band, rows, *, source):
    if enabled(band) and source == 'rest':
        band.pair_latest_trades = rows


def completion_quote(band, normal_prices, snapshot=None):
    state = require_state(band)
    if not state.completing:
        return None
    values = snapshot['quote_inputs'] if snapshot is not None else {}
    rules = snapshot['rules'][band.tokens[state.completion_leg]] if snapshot is not None else {}
    result = quote(state, normal_prices, tick=rules.get('tick_size', '.01'),
        leg_bounds=band.LEG_PRICE_RANGE, min_order_size=rules.get('min_order_size', 0),
        reward_min_size=values.get('reward_min_size', SIZE))
    band.pair_last_quote = result
    band.journal.record('pair_completion_quote', **(state.evidence() | result.evidence()),
                        completion_seconds=str(elapsed(band)))
    if not result.allowed:
        raise HoldEnd(WAIT)
    return result


def observe(band, snapshot, observation):
    """Keep all ordinary screens; avoid requoting an unchanged binding cap."""
    if not enabled(band):
        return observation
    from weather.market.re1_attended import replacement_price
    normal = [replacement_price(observation['adjusted_mid'], leg, band.OFFSET) for leg in (0, 1)]
    result = completion_quote(band, normal, snapshot)
    if result is not None:
        observation['requote_legs'] = [result.leg] if band.prices[result.leg] != result.price else []
    return observation


def cap_prices(band):
    if enabled(band):
        result = completion_quote(band, band.prices)
        if result is not None:
            band.prices[result.leg] = result.price


def submit_price(band, leg, price):
    if not enabled(band):
        return price
    state = require_state(band)
    if not state.completing:
        return price
    if leg != state.completion_leg:
        raise HoldEnd('completion_overheld_side')
    normal = list(band.prices)
    normal[leg] = price
    result = completion_quote(band, normal)
    band.prices[leg] = result.price
    return result.price


def authorize(band, leg, price, size):
    """Additional economic screen before the existing guarded submit boundary."""
    if not enabled(band):
        return
    state = require_state(band)
    if state.completing:
        if leg != state.completion_leg or size != SIZE:
            raise HoldEnd('completion_overheld_side_or_size')
        if (band.pair_last_quote is None or not band.pair_last_quote.allowed or
                band.pair_last_quote.leg != state.completion_leg or
                price > band.pair_last_quote.price or price > 1-state.average_cost-Decimal('.015')):
            raise HoldEnd(WAIT)


def posted(band, oid):
    if enabled(band) and require_state(band).completing:
        band.pair_completion_orders.add(oid)
        band.journal.record('pair_completion_order', order_id=oid,
                            **(band.pair_last_quote.evidence() | band.pair_state.evidence()))


def cycle(band, base_steps, *, rehearsal_seconds=None):
    if require_state(band).completing:
        band.refresh_repost_prices()
    yield from base_steps(rehearsal_seconds=rehearsal_seconds)


def terminal_extra(band):
    if not enabled(band):
        return {}
    if band.inventory_proven and band.pair_latest_trades is not None:
        refresh_from_read(band, {'trades': band.pair_latest_trades, 'ended_at_utc': band.clock.now().isoformat()})
    state = require_state(band)
    return {'post_fill_mode': COMPLETE_PAIRS, 'pair_completion': {
        **state.evidence(), 'completion_seconds': str(elapsed(band)),
        'completion_order_ids': sorted(band.pair_completion_orders),
        'pair_allocations': [p.evidence() for p in state.pairs]}}
