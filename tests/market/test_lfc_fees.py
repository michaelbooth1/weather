"""Maker-fee class rule of the live-fill calibration (in-memory fixtures only; no network, no credentials, no orders).

Guards: EF section 10o / LFC C8 as replaced by clarification D (LFC-FEE-CHECK section d): a market classifies as
WEATHER_TAKER_ONLY (Gamma feesEnabled, feeType weather_fees, feeSchedule.takerOnly, CLOB fd.to) or FEE_FREE (all fee
fields off, base_fee 0), else it refuses with one precise code; base_fee 1000 is recorded and never compared to 0;
the schedule coefficients are recorded, not required; any non-zero builder fee field refuses; the public reader adds
only /clob-markets/<condition> (RE-1's PublicBooks allowlist is unchanged); the signed order carries no builder or fee.
Field shapes are the public reads of LFC-FEE-CHECK section c (London weather band, netanyahu-out-before-2027).
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json

import pytest

from weather.market.lfc_fees import (BYTES32_ZERO, FEE_FREE, WEATHER_TAKER_ONLY, SignedOrderGuard, classify,
                                     clob_fee_fields, fee_key, gamma_fee_fields, maker_fee_refusal,
                                     require_maker_fee_zero, sibling_fee_refusal)
from weather.market.lfc_pilot import LfcPublicBooks, Session0Books
from weather.market.mm_stage2_selection import PublicBooks

TOKENS = ('111', '222')
CONDITION = '0x' + 'd9' * 32
SLUG = 'highest-temperature-in-london-on-october-11-2026'

# Gamma market object and CLOB /clob-markets reply of the London weather band (LFC-FEE-CHECK section c).
WEATHER_GAMMA_MARKET = {'conditionId': CONDITION, 'question': 'London 11C', 'feesEnabled': True,
                        'feeType': 'weather_fees', 'makerBaseFee': 1000, 'takerBaseFee': 1000,
                        'feeSchedule': {'rate': 0.05, 'exponent': 1, 'takerOnly': True, 'rebateRate': 0.25}}
WEATHER_CLOB = {'fd': {'r': 0.05, 'e': 1, 'to': True}, 'mbf': 1000, 'tbf': 1000, 'nr': True, 'mts': 0.001}
# netanyahu-out-before-2027: feesEnabled false, feeType null, no schedule, no fd, no base fields.
FREE_GAMMA_MARKET = {'conditionId': CONDITION, 'question': 'Netanyahu out', 'feesEnabled': False, 'feeType': None}
FREE_CLOB = {'mts': 0.01}


def snap(gamma=WEATHER_GAMMA_MARKET, clob=WEATHER_CLOB, base=('1000', '1000'), error=None):
    return {'rules': {t: {'fee_rate_bps': b} for t, b in zip(TOKENS, base)},
            'fee_evidence': {'event_slug': SLUG, 'gamma': gamma_fee_fields(deepcopy(gamma)),
                             'clob': clob_fee_fields(deepcopy(clob)), 'error': error}}


def free():
    return snap(FREE_GAMMA_MARKET, FREE_CLOB, ('0', '0'))


def code(snapshot, **kwargs):
    return maker_fee_refusal(snapshot, TOKENS, **kwargs)[0]


def gamma_with(**changes):
    value = deepcopy(WEATHER_GAMMA_MARKET)
    for key, item in changes.items():
        if item is DELETE:
            value.pop(key)
        else:
            value[key] = item
    return value


def schedule_with(**changes):
    value = dict(WEATHER_GAMMA_MARKET['feeSchedule'])
    for key, item in changes.items():
        if item is DELETE:
            value.pop(key)
        else:
            value[key] = item
    return gamma_with(feeSchedule=value)


def fd_with(**changes):
    value = deepcopy(WEATHER_CLOB)
    for key, item in changes.items():
        if item is DELETE:
            value['fd'].pop(key)
        else:
            value['fd'][key] = item
    return value


DELETE = object()


# ----- the two classes -----------------------------------------------------------------------------------------
def test_weather_band_is_taker_only_and_records_base_fee_1000_without_comparing_it_to_zero():
    fee_class, record = classify(snap(), list(TOKENS))
    assert fee_class == WEATHER_TAKER_ONLY
    assert record['base_fee'] == {'111': '1000', '222': '1000'}
    assert (record['makerBaseFee'], record['takerBaseFee'], record['mbf'], record['tbf']) == (1000, 1000, 1000, 1000)
    assert (record['taker_rate'], record['rebate_rate'], record['exponent']) == ('0.05', '0.25', '1')
    assert record['builder_fields'] == {}
    assert code(snap()) is None


def test_retuned_weather_coefficients_still_pass_and_are_recorded():
    # Master/main session: flag plus type plus record; 0.05 and 25% are not required.
    gamma = schedule_with(rate=0.06, rebateRate=0.2)
    clob = fd_with(r=0.06)
    fee_class, record = classify(snap(gamma, clob), list(TOKENS))
    assert fee_class == WEATHER_TAKER_ONLY and record['taker_rate'] == '0.06' and record['rebate_rate'] == '0.2'


def test_fee_free_market_passes_for_both_profiles():
    assert classify(free(), list(TOKENS))[0] == FEE_FREE
    assert code(free()) is None and code(free(), require_fee_free=True) is None
    explicit_zero = snap(dict(FREE_GAMMA_MARKET, makerBaseFee=0, takerBaseFee=0), dict(FREE_CLOB, mbf=0, tbf=0),
                         ('0', '0'))
    assert classify(explicit_zero, list(TOKENS))[0] == FEE_FREE


def test_session0_refuses_a_weather_class_market():
    assert code(snap(), require_fee_free=True) == 'session0_not_fee_free'


# ----- refusals -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize('snapshot', [
    snap(error='HTTPError'),
    {'rules': {t: {'fee_rate_bps': '1000'} for t in TOKENS}},
    snap(gamma=gamma_with(feesEnabled=DELETE)),
    snap(gamma=gamma_with(feesEnabled='true')),
    snap(gamma=gamma_with(feeType=DELETE)),
    snap(gamma=schedule_with(takerOnly=DELETE)),
    snap(gamma=schedule_with(takerOnly='true')),
    snap(gamma=schedule_with(rate='x')),
    snap(clob=fd_with(to=DELETE)),
    snap(clob={k: v for k, v in WEATHER_CLOB.items() if k != 'fd'}),
    snap(clob={k: v for k, v in WEATHER_CLOB.items() if k != 'tbf'}),
    snap(gamma=gamma_with(makerBaseFee=DELETE)),
    snap(base=('1000', 'x')),
    snap(base=('1000', '-1')),
], ids=['read_error', 'no_evidence', 'feesEnabled_missing', 'feesEnabled_string', 'feeType_missing',
        'takerOnly_missing', 'takerOnly_string', 'rate_not_numeric', 'fd_to_missing', 'fd_missing', 'tbf_missing',
        'makerBaseFee_missing', 'base_fee_not_numeric', 'base_fee_negative'])
def test_unreadable_or_missing_fields_refuse(snapshot):
    assert code(snapshot) == 'fee_fields_unreadable'


def test_missing_gamma_or_clob_object_refuses():
    value = snap()
    value['fee_evidence']['gamma'] = None
    assert code(value) == 'fee_fields_unreadable'
    value = snap()
    value['fee_evidence']['clob'] = None
    assert code(value) == 'fee_fields_unreadable'
    assert code(None) == 'fee_fields_unreadable'
    assert maker_fee_refusal(snap(), [])[0] == 'fee_fields_unreadable'


@pytest.mark.parametrize('snapshot', [
    snap(gamma=gamma_with(feeType='crypto_fees')),
    snap(gamma=gamma_with(feeSchedule=DELETE)),
    snap(gamma=schedule_with(extra=1)),
    snap(clob=fd_with(x=1)),
    snap(gamma=schedule_with(rate=-0.05), clob=fd_with(r=-0.05)),
], ids=['crypto_fees', 'enabled_without_schedule', 'extra_schedule_key', 'extra_fd_key', 'negative_rate'])
def test_unknown_schedule_refuses(snapshot):
    assert code(snapshot) == 'fee_schedule_unknown'


@pytest.mark.parametrize('snapshot', [
    snap(base=('1000', '1100')),
    snap(clob=dict(WEATHER_CLOB, tbf=900)),
    snap(clob=dict(WEATHER_CLOB, mbf=0)),
    snap(clob=fd_with(to=False)),
    snap(clob=fd_with(r=0.07)),
    snap(clob=fd_with(e=2)),
    snap(FREE_GAMMA_MARKET, FREE_CLOB, ('0', '5')),
    snap(FREE_GAMMA_MARKET, WEATHER_CLOB, ('0', '0')),
    snap(dict(FREE_GAMMA_MARKET, feeType='weather_fees'), FREE_CLOB, ('0', '0')),
    snap(dict(FREE_GAMMA_MARKET, makerBaseFee=1000), FREE_CLOB, ('0', '0')),
], ids=['token_base_fees_differ', 'tbf_differs', 'mbf_differs', 'fd_to_disagrees_with_takerOnly', 'fd_rate_differs',
        'fd_exponent_differs', 'fee_free_base_fee_5', 'fee_free_with_fd', 'fee_free_with_feeType',
        'fee_free_with_maker_base'])
def test_inconsistent_fields_refuse(snapshot):
    assert code(snapshot) == 'fee_fields_inconsistent'


@pytest.mark.parametrize('snapshot', [
    snap(gamma=schedule_with(takerOnly=False), clob=fd_with(to=False)),
    snap(gamma=schedule_with(rebateRate=-0.1)),
    snap(gamma=gamma_with(makerFeeRate=10)),
    snap(clob=dict(WEATHER_CLOB, makerRebateRate=-1)),
    snap(gamma=schedule_with(makerRate=0.01)),
], ids=['taker_only_false', 'negative_rebate_charges_maker', 'explicit_maker_fee', 'negative_maker_rebate_field',
        'maker_rate_in_schedule'])
def test_maker_charge_refuses(snapshot):
    assert code(snapshot) == 'maker_fee_nonzero'


@pytest.mark.parametrize('snapshot', [
    snap(gamma=gamma_with(builderFeeRate=50)),
    snap(clob=dict(WEATHER_CLOB, builder_fee_bps='25')),
    snap(dict(FREE_GAMMA_MARKET, builderCode='0x' + '1' * 64), FREE_CLOB, ('0', '0')),
], ids=['gamma_builder_rate', 'clob_builder_fee', 'fee_free_builder_code'])
def test_any_nonzero_builder_fee_field_refuses(snapshot):
    assert code(snapshot) == 'builder_fee_nonzero'


def test_absent_or_zero_builder_fields_are_recorded_as_zero():
    _, record = classify(snap(gamma=gamma_with(builderFeeRate=0), clob=dict(WEATHER_CLOB, builderCode=BYTES32_ZERO)),
                         list(TOKENS))
    assert record['builder_fields'] == {'gamma.builderFeeRate': 0, 'clob.builderCode': BYTES32_ZERO}


def test_require_maker_fee_zero_wraps_the_selected_row():
    table = {'selected_condition_id': CONDITION, 'rows': [{'condition_id': CONDITION, 'token_ids': list(TOKENS),
                                                           'snapshot': snap()}]}
    assert require_maker_fee_zero(table) is table
    with pytest.raises(RuntimeError, match='session0_not_fee_free'):
        require_maker_fee_zero(table, require_fee_free=True)
    table['rows'][0]['snapshot'] = snap(clob=fd_with(to=False))
    with pytest.raises(RuntimeError, match='fee_fields_inconsistent'):
        require_maker_fee_zero(table)
    del table['rows'][0]['snapshot']
    with pytest.raises(RuntimeError, match='fee_fields_unreadable'):
        require_maker_fee_zero(table)
    assert require_maker_fee_zero({'selected_condition_id': None, 'rows': []})['rows'] == []


def test_fee_key_changes_with_any_fee_field_and_ignores_key_order():
    base = fee_key(snap(), TOKENS)
    reordered = snap(gamma=dict(reversed(list(WEATHER_GAMMA_MARKET.items()))))
    assert fee_key(reordered, TOKENS) == base
    assert fee_key(snap(base=('1000', '1001')), TOKENS) != base
    assert fee_key(snap(gamma=schedule_with(rebateRate=0.3)), TOKENS) != base
    assert fee_key({}, TOKENS) != fee_key({}, TOKENS)


def test_session0_siblings_must_all_be_fee_free():
    free_fields = gamma_fee_fields(FREE_GAMMA_MARKET)
    assert sibling_fee_refusal({CONDITION: free_fields, '0x' + 'c' * 64: free_fields}) is None
    assert sibling_fee_refusal({CONDITION: free_fields, 'x': gamma_fee_fields(WEATHER_GAMMA_MARKET)}) == \
        'session0_event_not_fee_free'
    assert sibling_fee_refusal({CONDITION: dict(free_fields, builderFee=5)}) == 'session0_event_not_fee_free'
    assert sibling_fee_refusal({CONDITION: {}}) == 'fee_fields_unreadable'
    assert sibling_fee_refusal(None) == 'fee_fields_unreadable'


# ----- public reads ---------------------------------------------------------------------------------------------
class Clock:
    def now(self):
        return datetime(2026, 10, 20, 17, tzinfo=timezone.utc)


def fake_opener(routes, seen):
    class Response:
        status = 200
        headers = {'Content-Type': 'application/json'}

        def __init__(self, url, body):
            self.url, self.body = url, body

        def geturl(self):
            return self.url

        def read(self, _limit):
            return self.body

        def close(self):
            pass

    def opener(request, *, timeout):
        url = request.full_url
        seen.append(url)
        for prefix, payload in routes.items():
            if url.startswith(prefix):
                if isinstance(payload, Exception):
                    raise payload
                return Response(url, json.dumps(payload).encode())
        raise AssertionError('unexpected url ' + url)
    return opener


def routes(clob=WEATHER_CLOB, base=1000):
    book = {'market': CONDITION, 'tick_size': '0.01', 'min_order_size': '5', 'neg_risk': False,
            'bids': [{'price': '.4', 'size': '100'}], 'asks': [{'price': '.6', 'size': '100'}]}
    return {'https://gamma-api.polymarket.com/events/slug/' + SLUG: {'slug': SLUG, 'markets': [WEATHER_GAMMA_MARKET]},
            'https://clob.polymarket.com/book?token_id=111': dict(book, asset_id='111'),
            'https://clob.polymarket.com/book?token_id=222': dict(book, asset_id='222'),
            'https://clob.polymarket.com/fee-rate': {'base_fee': base},
            'https://clob.polymarket.com/clob-markets/' + CONDITION: clob}


REWARD = {'condition_id': CONDITION, 'rewards_min_size': '20', 'rewards_max_spread': '3', 'total_daily_rate': '50'}


def test_snapshot_reuses_the_selection_event_read_then_rereads_gamma_and_clob_markets():
    seen = []
    books = LfcPublicBooks(clock=Clock().now, opener=fake_opener(routes(), seen))
    books.get('https://gamma-api.polymarket.com/events/slug/' + SLUG)
    first = books.snapshot(CONDITION, TOKENS, reward=REWARD)
    assert classify(first, list(TOKENS))[0] == WEATHER_TAKER_ONLY
    assert sum('/events/slug/' in u for u in seen) == 1 and sum('/clob-markets/' in u for u in seen) == 1
    second = books.snapshot(CONDITION, TOKENS, reward=REWARD)  # submit / minute: a fresh Gamma read
    assert sum('/events/slug/' in u for u in seen) == 2 and sum('/clob-markets/' in u for u in seen) == 2
    assert fee_key(second, TOKENS) == fee_key(first, TOKENS)


def test_snapshot_with_a_bound_event_and_a_clob_markets_http_error_is_unreadable():
    from urllib.error import HTTPError
    seen = []
    failing = routes(clob=HTTPError('u', 503, 'down', {}, None))
    books = LfcPublicBooks(clock=Clock().now, opener=fake_opener(failing, seen))
    books.bind_event(CONDITION, SLUG)
    value = books.snapshot(CONDITION, TOKENS, reward=REWARD)
    assert value['fee_evidence']['error'] == 'HTTPError'
    assert code(value) == 'fee_fields_unreadable'
    unbound = LfcPublicBooks(clock=Clock().now, opener=fake_opener(routes(), []))
    assert code(unbound.snapshot(CONDITION, TOKENS, reward=REWARD)) == 'fee_fields_unreadable'


def test_only_clob_markets_condition_path_is_added_and_re1_allowlist_is_unchanged():
    url = 'https://clob.polymarket.com/clob-markets/' + CONDITION
    for reader in (LfcPublicBooks, Session0Books):
        assert reader(clock=Clock().now, opener=fake_opener(routes(), [])).get(url) == WEATHER_CLOB
    with pytest.raises(ValueError, match='not an allowed'):
        PublicBooks(clock=Clock().now, opener=fake_opener(routes(), [])).get(url)
    books = LfcPublicBooks(clock=Clock().now, opener=fake_opener(routes(), []))
    for bad in ('https://clob.polymarket.com/markets/' + CONDITION, 'https://clob.polymarket.com/clob-markets/0xabc',
                'https://clob.polymarket.com/clob-markets/' + CONDITION + '/x',
                'https://data-api.polymarket.com/clob-markets/' + CONDITION,
                'http://clob.polymarket.com/clob-markets/' + CONDITION):
        with pytest.raises(ValueError, match='not an allowed'):
            books.get(bad)


# ----- the signed order -----------------------------------------------------------------------------------------
@dataclass
class Signed:
    builder: str = BYTES32_ZERO
    token_id: str = '111'


class Client:
    signer = '0xsigner'

    def __init__(self, signed):
        self.signed, self.requests = signed, []

    def create_limit_order(self, **request):
        self.requests.append(request)
        return self.signed


def test_signed_order_guard_passes_a_zero_builder_and_delegates_everything_else():
    client = Client(Signed())
    guarded = SignedOrderGuard(client)
    request = {'token_id': '111', 'side': 'BUY', 'size': '40', 'price': '.3', 'post_only': True, 'expiration': 1}
    assert guarded.create_limit_order(**request) is client.signed and client.requests == [request]
    assert guarded.signer == '0xsigner'


def test_signed_order_with_a_nonzero_builder_refuses():
    with pytest.raises(RuntimeError, match='order_builder_nonzero'):
        SignedOrderGuard(Client(Signed(builder='0x' + '1' * 64))).create_limit_order(token_id='111')


def test_a_builder_or_fee_argument_refuses_before_signing():
    client = Client(Signed())
    with pytest.raises(RuntimeError, match='order_builder_nonzero'):
        SignedOrderGuard(client).create_limit_order(token_id='111', builder_code='0x' + '0' * 64)
    with pytest.raises(RuntimeError, match='order_fee_field_present'):
        SignedOrderGuard(client).create_limit_order(token_id='111', fee_rate_bps=0)
    assert client.requests == []


def test_a_signed_order_with_a_nonzero_fee_field_refuses():
    @dataclass
    class WithFee:
        builder: str = BYTES32_ZERO
        fee_rate_bps: int = 10
    with pytest.raises(RuntimeError, match='order_fee_field_present'):
        SignedOrderGuard(Client(WithFee())).create_limit_order(token_id='111')


def test_the_pinned_sdk_v2_order_has_no_fee_field_and_a_zero_default_builder():
    sdk = pytest.importorskip('polymarket.models.clob.orders')
    from dataclasses import fields
    from polymarket._internal.actions.orders.types import BYTES32_ZERO as SDK_ZERO
    names = {f.name for f in fields(sdk.SignedOrder)}
    assert 'builder' in names and not any('fee' in n.lower() for n in names)
    assert SDK_ZERO.lower() == BYTES32_ZERO
