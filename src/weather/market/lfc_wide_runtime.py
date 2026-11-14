"""W screens/evidence for existing guarded band hooks; no exchange adapter."""
from weather.market.lfc_accounting import quantity
from weather.market.lfc_wide_policy import configured
from weather.market.lfc_wide_quote import CORRIDOR, entry_allowed, order_evidence, requote_legs
from weather.market.mm_stage2_hold import HoldEnd


WAIT = 'wide_price_wait'
ARM_FIELDS = ('quote_offset_mode', 'wide_offset_cents', 'offset_assignment_source', 'standard_quote_offset_pusd')


def is_wide(band):
    return band.scope.get('quote_offset_mode', 'standard') == 'wide'


def completing(band):
    return bool(getattr(getattr(band, 'pair_state', None), 'completing', False))


def initialize(band, chosen):
    if configured(band.campaign_policy.raw):
        band.scope.update({key: chosen[key] for key in ARM_FIELDS})
        if is_wide(band):
            band.REQUOTE_WINDOW = CORRIDOR
            band.scope['requote_distance_cents'] = list(map(str, CORRIDOR))


def observe(band, snapshot, observation):
    """W keeps the inclusive band; completion still owns its capped target."""
    if is_wide(band):
        affected = requote_legs(observation['adjusted_mid'], band.prices, band.TRADE_LEGS)
        if completing(band):
            observation['requote_legs'] = [leg for leg in observation['requote_legs'] if leg in affected]
            return observation
        from weather.market.re1_attended import replacement_price
        mid = observation['adjusted_mid']
        normal = [replacement_price(mid, leg, band.OFFSET) for leg in (0, 1)]
        observation['requote_legs'] = [leg for leg in affected if normal[leg] != band.prices[leg] and
            entry_allowed(mid, normal, (leg,), snapshot['quote_inputs']['reward_max_spread_cents'])]
    return observation


def check_entry(band, snapshot, mid, prices, legs):
    if is_wide(band) and not completing(band) and not entry_allowed(
            mid, prices, legs, snapshot['quote_inputs']['reward_max_spread_cents']):
        raise HoldEnd(WAIT)


def authorize(band, leg, price, size):
    """Check the actual rounded order at the existing fresh-submit boundary."""
    if not configured(band.campaign_policy.raw):
        return
    from weather.market.re1_attended import observe as observe_book
    snapshot = band.submit_snapshot
    observation = observe_book(snapshot, band.prices, size, band.SIZES,
        window=band.REQUOTE_WINDOW, trade_legs=band.TRADE_LEGS, min_reward_rate=band.MIN_REWARD_RATE)
    check_entry(band, snapshot, observation['adjusted_mid'], band.prices, (leg,))
    values = snapshot['quote_inputs']
    evidence = order_evidence(mid=observation['adjusted_mid'], leg=leg, price=price, size=size,
        minimum=values['reward_min_size'], maximum=values['reward_max_spread_cents'],
        mode=band.scope['quote_offset_mode'], offset=band.OFFSET)
    band.wide_order_evidence = {'leg': leg, 'price': str(quantity(price)),
        'adjusted_mid': observation['adjusted_mid'],
        'reward_max_spread_cents': str(values['reward_max_spread_cents']),
        'reward_min_size': str(values['reward_min_size']), 'size': str(quantity(size)),
        'completion': completing(band), 'offset_assignment_source': band.scope['offset_assignment_source'],
        **evidence}
    band.journal.record('quote_scoring_proposal', **band.wide_order_evidence)


def posted(band, oid):
    if configured(band.campaign_policy.raw):
        band.journal.record('quote_scoring_order', order_id=oid, **band.wide_order_evidence)
