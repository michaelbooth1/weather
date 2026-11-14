"""B057 policy and durable band-day gates; no exchange or task capability.

The explicit v0.3 policy preserves the v0.2 snapshot/retirement contract.
Its filled-day limit reserves prospective exposure as well as proved fills.
"""
from copy import deepcopy
from datetime import date
import hashlib

from weather.market.lfc_accounting import quantity
from weather.market.lfc_capital import CEILING, CapitalRefused, native
from weather.market import lfc_f2_policy as legacy
from weather.market.lfc_campaign_policy import ZONE, exact_keys
from weather.market.market_registry import BUILTIN_SPECS, REGISTRY


SCHEMA = 'lfc_campaign_policy_v0.3'
PROTOCOL = 'lfc_autostart_v3'
CONTINUE = 'cancel_reconcile_cooldown_and_requote_same_band'
RETIRE = legacy.FIXED['on_first_band_fill']
FIELDS = frozenset({'per_band_daily_filled_cap_pusd', 'fill_cooldown_seconds', 'learning_quote_offsets_pusd'})


def captured_market_ids():
    # The repository capture traverses all_specs(). Only built-in registry
    # members belong to this qualified lane; an arbitrary external ID refuses.
    return sorted(spec.id for spec in BUILTIN_SPECS if spec.id in REGISTRY)


def enabled(policy):
    return policy.raw.get('schema_version') in {SCHEMA, 'lfc_campaign_policy_v0.4'}


def economic_fields(policy):
    fields = legacy.ECONOMIC_FIELDS | (FIELDS if enabled(policy) else frozenset())
    from weather.market.lfc_f2_pinb import enabled as pinb, FIELDS as PINB_FIELDS
    if pinb(policy):
        fields |= PINB_FIELDS
    return fields if 'sleeve_loss_basis' in policy.raw else fields - {'sleeve_loss_basis'}


def parse_breadth(row):
    exact_keys(row, legacy.field_keys(row) | FIELDS)
    if row['schema_version'] != SCHEMA:
        legacy.refuse('policy_identity')
    markets = row['market_ids']
    if (not isinstance(markets, list) or not markets or any(not isinstance(m, str) for m in markets) or
            markets != sorted(set(markets)) or not set(markets) <= set(captured_market_ids())):
        legacy.refuse('unsupported_market_ids')
    count = row['band_limit_session']
    if (type(count) is not int or not 1 <= count <= len(markets) or
            type(row['band_limit_concurrent']) is not int or row['band_limit_concurrent'] != count):
        legacy.refuse('unsupported_band_limits')
    if row['on_first_band_fill'] not in (CONTINUE, RETIRE):
        legacy.refuse('unsupported_on_first_band_fill')
    try:
        cap = native(row['per_band_daily_filled_cap_pusd'])
        values = [quantity(v) for v in row['learning_quote_offsets_pusd']]
    except (ValueError, TypeError):
        legacy.refuse('unsupported_breadth_quantity')
    if not 0 < cap <= CEILING:
        legacy.refuse('unsupported_per_band_daily_filled_cap_pusd')
    if type(row['fill_cooldown_seconds']) is not int or not 60 <= row['fill_cooldown_seconds'] <= 3600:
        legacy.refuse('unsupported_fill_cooldown_seconds')
    offsets = row['learning_quote_offsets_pusd']
    if (not isinstance(offsets, list) or not 1 <= len(offsets) <= 2 or
            any(not isinstance(v, str) for v in offsets)):
        legacy.refuse('unsupported_learning_quote_offsets_pusd')
    if values != sorted(set(values)) or not set(values) <= {quantity('.015'), quantity('.025')}:
        legacy.refuse('unsupported_learning_quote_offsets_pusd')
    # Validate every unchanged field through its existing contract. The three
    # widened fields above are separately validated, never silently narrowed.
    reference = deepcopy({key: value for key, value in row.items() if key not in FIELDS})
    reference.update(schema_version=legacy.SCHEMA, market_ids=['denver', 'toronto'],
                     band_limit_session=1, band_limit_concurrent=1, on_first_band_fill=RETIRE)
    baseline = legacy.parse_f2(reference)
    return legacy.F2Campaign(deepcopy(row), baseline.entries)


def example_policy():
    markets = captured_market_ids()
    return {**legacy.example_policy(), 'schema_version': SCHEMA, 'enabled': False,
        'policy_name': 'Builtin-T1-Paired20-Continue40', 'policy_revision': 4,
        'market_ids': markets, 'band_limit_session': len(markets), 'band_limit_concurrent': len(markets),
        'on_first_band_fill': CONTINUE, 'per_band_daily_filled_cap_pusd': '40',
        'fill_cooldown_seconds': 60, 'learning_quote_offsets_pusd': ['0.015', '0.025']}


def arm(policy, local_date, market):
    """A band-day keeps its arm across retries; later dates use one frozen value."""
    offset = policy.raw['quote_offset_pusd']
    if not enabled(policy):
        return {'quote_offset_pusd': str(offset), 'quote_arm': None}
    day = date.fromisoformat(local_date)
    first, last = map(date.fromisoformat, policy.raw['learning_dates'])
    learning = first <= day <= last
    if learning:
        choices = policy.raw['learning_quote_offsets_pusd']
        key = ('lfc-distance-v1|' + local_date + '|' + market).encode()
        offset = choices[int.from_bytes(hashlib.sha256(key).digest()[:8], 'big') % len(choices)]
    offset = format(quantity(offset), '.3f')
    result = {'quote_offset_pusd': offset, 'quote_arm': ('learning-' if learning else 'fixed-') + offset,
              'arm_date_toronto': local_date, 'arm_market_id': market}
    from weather.market.lfc_f2_pinb import enabled as pinb
    if pinb(policy):
        leg_arm = policy.raw['confirmation_leg_arm']
        if learning:
            choices = policy.raw['learning_leg_arms']
            key = ('lfc-leg-v1|' + local_date + '|' + market).encode()
            leg_arm = choices[int.from_bytes(hashlib.sha256(key).digest()[:8], 'big') % len(choices)]
        result.update(leg_arm=leg_arm, leg_arm_assignment=('learning-' if learning else 'fixed-')+leg_arm)
    return result


def row_arm(policy, now, market):
    return arm(policy, now.astimezone(ZONE).date().isoformat(), market)


def arm_field_keys(policy):
    keys = ('quote_offset_pusd', 'quote_arm', 'arm_date_toronto', 'arm_market_id')
    from weather.market.lfc_f2_pinb import enabled as pinb
    return keys + (('leg_arm', 'leg_arm_assignment') if pinb(policy) else ())


def band_market(start):
    market = start.get('market_id')
    if market is None:
        slug = start.get('event_slug') or ''
        market = next((spec.id for spec in BUILTIN_SPECS if slug.startswith(spec.slug_prefix + '-')), None)
    return market


def band_day_usage(ledger, market, utc_day):
    """Gross basis from replay-indexed legs, without re-scanning history."""
    filled = resting = unmapped = 0
    for leg, unknown_market in ledger.band_day_legs(market, utc_day):
        terminal = leg['status'] == 'terminal'
        cost = native(quantity(leg['price']) * quantity(leg['size_matched'] if terminal else leg['size']), ceil=True)
        if terminal:
            filled += cost
        else:
            resting += cost
        if unknown_market:
            unmapped += cost  # Unknown legacy scope is conservatively charged to this band-day.
    return {'filled_native': filled, 'resting_native': resting, 'unmapped_legacy_native': unmapped}


def daily_gate(ledger, start, *, reserve, own_resting=0, journal=None):
    if start.get('protocol') != PROTOCOL:
        return None
    market, day = start.get('market_id'), start.get('quote_day_utc')
    if (market not in captured_market_ids() or not isinstance(day, str) or
            date.fromisoformat(day).isoformat() != day or day != start['recorded_at_utc'][:10]):
        raise CapitalRefused('band_day_scope')
    cap = native(start['per_band_daily_filled_cap_pusd'])
    if not 0 < cap <= CEILING:
        raise CapitalRefused('band_day_cap')
    used = band_day_usage(ledger, market, day)
    reserve, own = native(reserve, ceil=True), native(own_resting, ceil=True)
    if own > used['resting_native']:
        raise CapitalRefused('band_day_own_reserve')
    if used['filled_native'] + used['resting_native'] - own + reserve > cap:
        detail = {key: used[key] for key in ('filled_native', 'resting_native')}
        detail.update(own_native=own, proposed_native=reserve, cap_native=cap,
                      headroom_native=cap - used['filled_native'] - used['resting_native'] + own)
        if journal is not None:
            journal.record('per_band_daily_filled_cap', **detail)
        raise CapitalRefused('per_band_daily_filled_cap')
    return {**used, 'cap_native': cap, 'prospective_native': reserve,
            'remaining_native': cap - used['filled_native'] - used['resting_native'] + own - reserve}


def support_table():
    return {'schema_version': SCHEMA, 'fields': sorted(set(legacy.FIXED) | legacy.VARIABLE | FIELDS),
            'market_ids': captured_market_ids(), 'one_band_per_city_day': True,
            'band_limits': [1, len(captured_market_ids())], 'concurrent_equals_session': True,
            'on_first_band_fill': [RETIRE, CONTINUE], 'per_band_daily_filled_cap_pusd': {'exclusive_min': '0', 'max': '300'},
            'fill_cooldown_seconds': [60, 3600], 'learning_quote_offsets_pusd': ['0.015', '0.025'],
            'confirmation_offset_field': 'quote_offset_pusd', 'daily_cap_reserves_prospective_exposure': True}
