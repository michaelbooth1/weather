"""Maker-fee class rule of the live-fill calibration campaign (C8 replacement; EF section 10o; LFC-FEE-CHECK).

The CLOB V2 order signed by polymarket-client 0.6.0 carries no fee field; the venue charges fees at match time. The
public /fee-rate `base_fee`, Gamma `makerBaseFee`/`takerBaseFee` and CLOB `/clob-markets` `mbf`/`tbf` read 1000 on
weather markets and are NOT the maker charge: they are recorded, never compared to zero. What proves a maker pays 0:

  WEATHER_TAKER_ONLY  Gamma feesEnabled is true, feeType == "weather_fees", feeSchedule.takerOnly is true and CLOB
                      fd.to is true (it must agree with takerOnly). The schedule coefficients (rate, exponent,
                      rebateRate) are recorded and cross-checked between Gamma and CLOB, never required to equal
                      0.05 / 1 / 0.25. The base fields must agree: every token's base_fee == takerBaseFee == tbf and
                      makerBaseFee == mbf.
  FEE_FREE            Gamma feesEnabled is false; feeType, feeSchedule and CLOB fd are absent or null; makerBaseFee,
                      takerBaseFee, mbf and tbf are absent or 0; base_fee == 0 for every token.

Anything else refuses (fail closed) with one code:
  fee_fields_unreadable    a read failed, G or C is missing, a field has the wrong JSON type or a required field is
                           missing;
  fee_fields_inconsistent  Gamma, CLOB and /fee-rate disagree (or a FEE_FREE market carries a fee field);
  fee_schedule_unknown     an unknown feeType, schedule key or fd key;
  maker_fee_nonzero        takerOnly/fd.to false, any explicit non-zero maker fee field, or a negative (charged)
                           maker rebate;
  builder_fee_nonzero      any non-zero builder field on the market (absent = 0, recorded).
The signed order is guarded separately (guard_signed_orders): no builder or fee argument in the request and
signed.builder == bytes32 zero, else order_builder_nonzero / order_fee_field_present.
"""
from __future__ import annotations

import dataclasses
import json
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urlsplit

from weather.market import lfc_constants as LFC
from weather.market.mm_stage2_hold import utc

GAMMA_HOST = 'gamma-api.polymarket.com'
EVENTS_PATH = '/events/slug/'
CLOB_MARKETS_URL = 'https://clob.polymarket.com/clob-markets/'
CLOB_MARKETS_PATH = r'/clob-markets/0x[0-9a-f]{64}'
BYTES32_ZERO = '0x' + '0' * 64

WEATHER_TAKER_ONLY = 'WEATHER_TAKER_ONLY'
FEE_FREE = 'FEE_FREE'

SCHEDULE_KEYS = frozenset({'rate', 'exponent', 'takerOnly', 'rebateRate'})
FD_KEYS = frozenset({'r', 'e', 'to'})
# Recorded, never gated on as the maker rate (they read 1000 on weather markets).
GAMMA_BASE_KEYS = ('makerBaseFee', 'takerBaseFee')
CLOB_BASE_KEYS = ('mbf', 'tbf')
_KNOWN_GAMMA = {'feesEnabled', 'feeType', 'feeSchedule', *GAMMA_BASE_KEYS}
_KNOWN_CLOB = {'fd', *CLOB_BASE_KEYS}


class FeeRefused(Exception):
    pass


def _captured(key):
    key = str(key).lower()
    return 'fee' in key or 'builder' in key or 'rebate' in key


def gamma_fee_fields(market):
    """The Gamma market fields the rule reads or records (every fee/builder/rebate key)."""
    if not isinstance(market, dict):
        raise ValueError('gamma market is not an object')
    return {k: market[k] for k in sorted(market) if _captured(k)}


def clob_fee_fields(payload):
    """The CLOB /clob-markets fields the rule reads or records: fd, mbf, tbf and every fee/builder/rebate key."""
    if not isinstance(payload, dict):
        raise ValueError('clob market is not an object')
    return {k: payload[k] for k in sorted(payload) if k in _KNOWN_CLOB or _captured(k)}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise FeeRefused('fee_fields_unreadable')
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise FeeRefused('fee_fields_unreadable') from None
    if not result.is_finite():
        raise FeeRefused('fee_fields_unreadable')
    return result


def _zeroish(value):
    """Absent/null/false/empty/0/bytes32-zero; anything else (including unparseable) is not zero."""
    if value is None or value is False or value == '' or value == [] or value == {}:
        return True
    if isinstance(value, str) and re.fullmatch(r'0x0*', value.lower()):
        return True
    try:
        return not isinstance(value, bool) and Decimal(str(value)) == 0
    except (InvalidOperation, ValueError):
        return False


def _base_fee(value):
    result = _number(value)
    if result < 0 or result != result.to_integral_value():
        raise FeeRefused('fee_fields_unreadable')
    return result


def _maker_extras(fields, known):
    """Any extra maker-named fee field must be zero; a maker rebate may not be negative (a charge)."""
    for key, value in fields.items():
        if key in known or 'maker' not in key.lower():
            continue
        if 'rebate' in key.lower():
            if not _zeroish(value) and _number(value) < 0:
                raise FeeRefused('maker_fee_nonzero')
        elif not _zeroish(value):
            raise FeeRefused('maker_fee_nonzero')


def _schedule(value, keys, names):
    """(taker_only, rate, exponent, rebate) of a Gamma feeSchedule or CLOB fd object."""
    if not isinstance(value, dict):
        raise FeeRefused('fee_fields_unreadable')
    extra = set(value) - keys
    _maker_extras({k: value[k] for k in extra}, set())
    if extra:
        raise FeeRefused('fee_schedule_unknown')
    if keys - set(value):
        raise FeeRefused('fee_fields_unreadable')
    taker_only = value[names[0]]
    if type(taker_only) is not bool:
        raise FeeRefused('fee_fields_unreadable')
    numbers = [_number(value[n]) for n in names[1:]]
    if any(n < 0 for n in numbers[:2]):
        raise FeeRefused('fee_schedule_unknown')
    if len(numbers) == 3 and numbers[2] < 0:
        raise FeeRefused('maker_fee_nonzero')  # a negative rebate charges the maker
    return (taker_only, *numbers)


def classify(snapshot, tokens):
    """(fee_class, record) or raise FeeRefused(code). Pure: reads snapshot['fee_evidence'] and snapshot['rules']."""
    try:
        evidence, rules = snapshot['fee_evidence'], snapshot['rules']
        gamma, clob = evidence['gamma'], evidence['clob']
        raw_base = [rules[t]['fee_rate_bps'] for t in tokens]
    except (KeyError, TypeError):
        raise FeeRefused('fee_fields_unreadable') from None
    if evidence.get('error') or not isinstance(gamma, dict) or not isinstance(clob, dict) or not raw_base:
        raise FeeRefused('fee_fields_unreadable')
    base = [_base_fee(v) for v in raw_base]
    record = {'base_fee': {t: str(v) for t, v in zip(tokens, base)},
              'builder_fields': {f'gamma.{k}': v for k, v in gamma.items() if 'builder' in k.lower()} |
              {f'clob.{k}': v for k, v in clob.items() if 'builder' in k.lower()},
              **{k: gamma.get(k) for k in GAMMA_BASE_KEYS}, **{k: clob.get(k) for k in CLOB_BASE_KEYS}}
    if not all(_zeroish(v) for v in record['builder_fields'].values()):
        raise FeeRefused('builder_fee_nonzero')
    _maker_extras(gamma, _KNOWN_GAMMA)
    _maker_extras(clob, _KNOWN_CLOB)
    enabled = gamma.get('feesEnabled')
    if type(enabled) is not bool:
        raise FeeRefused('fee_fields_unreadable')
    if enabled is False:
        if any(gamma.get(k) is not None for k in ('feeType', 'feeSchedule')) or clob.get('fd') is not None:
            raise FeeRefused('fee_fields_inconsistent')
        for value in [gamma.get(k) for k in GAMMA_BASE_KEYS] + [clob.get(k) for k in CLOB_BASE_KEYS]:
            if value is not None and _number(value) != 0:
                raise FeeRefused('fee_fields_inconsistent')
        if any(b != 0 for b in base):
            raise FeeRefused('fee_fields_inconsistent')
        return FEE_FREE, {'fee_class': FEE_FREE, **record}
    fee_type = gamma.get('feeType')
    if not isinstance(fee_type, str):
        raise FeeRefused('fee_fields_unreadable')
    if fee_type != LFC.WEATHER_FEE_TYPE:
        raise FeeRefused('fee_schedule_unknown')
    if gamma.get('feeSchedule') is None:
        raise FeeRefused('fee_schedule_unknown')
    taker_only, rate, exponent, rebate = _schedule(gamma['feeSchedule'], SCHEDULE_KEYS,
                                                   ('takerOnly', 'rate', 'exponent', 'rebateRate'))
    if clob.get('fd') is None:
        raise FeeRefused('fee_fields_unreadable')
    to, r, e = _schedule(clob['fd'], FD_KEYS, ('to', 'r', 'e'))
    if to is not taker_only:
        raise FeeRefused('fee_fields_inconsistent')
    if taker_only is not True:
        raise FeeRefused('maker_fee_nonzero')
    if (r, e) != (rate, exponent):
        raise FeeRefused('fee_fields_inconsistent')
    if any(gamma.get(k) is None for k in GAMMA_BASE_KEYS) or any(clob.get(k) is None for k in CLOB_BASE_KEYS):
        raise FeeRefused('fee_fields_unreadable')
    maker, taker = (_number(gamma[k]) for k in GAMMA_BASE_KEYS)
    mbf, tbf = (_number(clob[k]) for k in CLOB_BASE_KEYS)
    if any(b != taker for b in base) or taker != tbf or maker != mbf:
        raise FeeRefused('fee_fields_inconsistent')
    return WEATHER_TAKER_ONLY, {'fee_class': WEATHER_TAKER_ONLY, 'fee_type': fee_type, 'taker_only': True,
                                'taker_rate': str(rate), 'exponent': str(exponent), 'rebate_rate': str(rebate),
                                **record}


def maker_fee_refusal(snapshot, tokens, *, require_fee_free=False):
    """(code or None, record). Session 0 (require_fee_free) refuses a fee-enabled class as session0_not_fee_free."""
    try:
        fee_class, record = classify(snapshot, list(tokens))
    except FeeRefused as exc:
        return str(exc), {'fee_class': None, 'refusal': str(exc)}
    if require_fee_free and fee_class != FEE_FREE:
        return 'session0_not_fee_free', {**record, 'refusal': 'session0_not_fee_free'}
    return None, record


def require_maker_fee_zero(table, *, require_fee_free=False):
    """Preflight and live selection (both profiles): the selected market must classify (session 0: FEE_FREE)."""
    if table.get('selected_condition_id'):
        selected = next(r for r in table['rows'] if r['condition_id'] == table['selected_condition_id'])
        try:
            snapshot, tokens = selected['snapshot'], selected['token_ids']
        except (KeyError, TypeError):
            raise RuntimeError('fee_fields_unreadable') from None
        code, _ = maker_fee_refusal(snapshot, tokens, require_fee_free=require_fee_free)
        if code:
            raise RuntimeError(code)
    return table


def fee_key(snapshot, tokens):
    """Every fee field the rule reads, for the per-minute comparison (an unreadable one never equals another)."""
    try:
        evidence = snapshot['fee_evidence']
        return (json.dumps(evidence['gamma'], sort_keys=True), json.dumps(evidence['clob'], sort_keys=True),
                tuple(str(snapshot['rules'][t]['fee_rate_bps']) for t in tokens))
    except Exception:
        return ('unreadable', object())  # never equal to any other key


def sibling_fee_refusal(event_fee_fields):
    """Session 0: every open market of the event must be fee-free on its Gamma fields."""
    if not isinstance(event_fee_fields, dict) or not event_fee_fields:
        return 'fee_fields_unreadable'
    for fields in event_fee_fields.values():
        if not isinstance(fields, dict) or type(fields.get('feesEnabled')) is not bool:
            return 'fee_fields_unreadable'
        if (fields['feesEnabled'] or any(fields.get(k) is not None for k in ('feeType', 'feeSchedule')) or
                not all(_zeroish(fields.get(k)) for k in GAMMA_BASE_KEYS) or
                not all(_zeroish(v) for k, v in fields.items() if 'builder' in k.lower())):
            return 'session0_event_not_fee_free'
    return None


# ----- public reads -------------------------------------------------------------------------------------------------
class FeeEvidenceBooks:
    """Mixin over a PublicBooks reader: every snapshot carries `fee_evidence` = the Gamma market's fee fields (from
    the event read of this selection pass, else a fresh /events/slug read) and CLOB /clob-markets/<condition>."""
    EXTRA_CLOB_PATHS = (CLOB_MARKETS_PATH,)
    GAMMA_REUSE_SECONDS = 60

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._gamma_markets, self._event_of = {}, {}

    def bind_event(self, condition, event_slug):
        self._event_of[str(condition).lower()] = str(event_slug)

    def get(self, url, **kwargs):
        value = super().get(url, **kwargs)
        parts = urlsplit(url)
        if (parts.netloc == GAMMA_HOST and parts.path.startswith(EVENTS_PATH) and isinstance(value, dict) and
                isinstance(value.get('markets'), list)):
            slug, now = parts.path[len(EVENTS_PATH):], utc(self.clock())
            for market in value['markets']:
                if isinstance(market, dict) and market.get('conditionId'):
                    condition = str(market['conditionId']).lower()
                    self._event_of[condition] = slug
                    self._gamma_markets[condition] = (now, market)
        return value

    def fee_evidence(self, condition, *, checkpoint=lambda: None):
        key = str(condition).lower()
        try:
            cached = self._gamma_markets.pop(key, None)
            if cached is None or not 0 <= (utc(self.clock()) - cached[0]).total_seconds() <= self.GAMMA_REUSE_SECONDS:
                self.get('https://' + GAMMA_HOST + EVENTS_PATH + self._event_of[key], checkpoint=checkpoint)
                cached = self._gamma_markets.pop(key)
            clob = self.get(CLOB_MARKETS_URL + str(condition), checkpoint=checkpoint)
            return {'event_slug': self._event_of[key], 'gamma': gamma_fee_fields(cached[1]),
                    'clob': clob_fee_fields(clob), 'error': None}
        except Exception as exc:
            return {'event_slug': self._event_of.get(key), 'gamma': None, 'clob': None,
                    'error': type(exc).__name__}

    def snapshot(self, condition, tokens, *, checkpoint=lambda: None, **kwargs):
        result = super().snapshot(condition, tokens, checkpoint=checkpoint, **kwargs)
        result['fee_evidence'] = self.fee_evidence(condition, checkpoint=checkpoint)
        return result


# ----- the signed order ---------------------------------------------------------------------------------------------
class SignedOrderGuard:
    """Wraps the SDK client of the live venue: create_limit_order must get no builder or fee argument and return an
    order whose builder is bytes32 zero and that has no non-zero fee field (the V2 order has none). Every other
    attribute is the wrapped client's."""

    def __init__(self, client):
        object.__setattr__(self, '_client', client)

    def __getattr__(self, name):
        return getattr(self._client, name)

    def __setattr__(self, name, value):
        setattr(self._client, name, value)

    def create_limit_order(self, **request):
        if any('builder' in k.lower() for k in request):
            raise RuntimeError('order_builder_nonzero')
        if any('fee' in k.lower() for k in request):
            raise RuntimeError('order_fee_field_present')
        signed = self._client.create_limit_order(**request)
        check_signed_order(signed)
        return signed


def check_signed_order(signed):
    if str(getattr(signed, 'builder', None)).lower() != BYTES32_ZERO:
        raise RuntimeError('order_builder_nonzero')
    names = ([f.name for f in dataclasses.fields(signed)] if dataclasses.is_dataclass(signed)
             else list(vars(signed)) if hasattr(signed, '__dict__') else [])
    if any('fee' in n.lower() and not _zeroish(getattr(signed, n)) for n in names):
        raise RuntimeError('order_fee_field_present')
    return signed


def guard_signed_orders(venue):
    venue.client = SignedOrderGuard(venue.client)
    return venue
