"""Guards: T076 Monday normalized venue structures at F2 transport boundaries.

The source file is a redacted shape inventory, not raw HTTP or a coherent
account. Inversions and synthetic controls are identified in the helper.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from types import SimpleNamespace

import pytest
from polymarket import UnexpectedResponseError
from polymarket.models.clob.account import OpenOrder
from polymarket.models.clob.cancel import CancelOrdersResponse

from tests.market.real_reply_shapes import (SHAPES, SHAPE_PATH, SHAPE_SHA, mapped_venue,
    offline, order_model, page, shape, trade_model)
from weather.market.lfc_ledger import traded_shares
from weather.market.mm_account_reads import AmbiguousAccountRead, order_terminal
from weather.market.mm_official_adapter import plain_sdk_value
from weather.market.mm_stage2_hold import cancel_ack_ids, exact_open_orders, HoldEnd
from weather.market.re1_attended import SecretGuard


def test_exact_supplied_inventory_is_retained_without_inventing_missing_samples():
    assert hashlib.sha256(SHAPE_PATH.read_bytes()).hexdigest() == SHAPE_SHA
    assert {key for key in SHAPES if not key.startswith('_')} == {
        'submit_ack', 'cancel_ack', 'open_orders_row', 'terminal_order_row',
        'order_read_after_cancel_row', 'user_stream_fill_event',
        'fill_journal_user_event', 'positions_row', 'trades_row'}
    assert SHAPES['terminal_order_row'] is None and SHAPES['positions_row'] is None
    assert SHAPES['user_stream_fill_event'] == SHAPES['fill_journal_user_event']


@pytest.mark.parametrize('key', ['open_orders_row', 'order_read_after_cancel_row'])
def test_normalized_sdk_order_roundtrip_preserves_supplied_fields(key):
    row = shape(key)
    owner = mapped_venue(SimpleNamespace(get_order=lambda **kwargs: order_model(row)))
    result = owner.order(row['id'])
    assert SecretGuard(['inert-redacted-owner']).clean(result) == row
    assert order_terminal(result, order_id=row['id'], size='11') is (key == 'order_read_after_cancel_row')


def test_null_terminal_sample_maps_actual_sdk_decode_failure_to_retryable_order_read():
    def get_order(**kwargs):
        return OpenOrder.parse_response(shape('terminal_order_row'))
    owner = mapped_venue(SimpleNamespace(get_order=get_order))
    with pytest.raises(TimeoutError, match='^order_read_undecodable$') as caught:
        owner.order(shape('open_orders_row')['id'])
    assert isinstance(caught.value.__cause__, UnexpectedResponseError)
    assert not order_terminal(None, order_id=shape('open_orders_row')['id'], size='11')


def test_real_cancel_ack_passes_transport_and_both_f2_cancel_consumers():
    from weather.market.lfc_f2_controller import F2Band
    row = shape('cancel_ack'); oid = row['canceled'][0]
    model = CancelOrdersResponse.model_validate(row)
    owner = mapped_venue(SimpleNamespace(cancel_order=lambda **kw: model, cancel_all=lambda: model))
    assert owner.cancel(oid) == owner.cancel_all() == row
    assert cancel_ack_ids(owner.cancel(oid)) == {oid}
    band = object.__new__(F2Band)
    band.check_requote_cancel_response(oid, owner.cancel(oid))
    records = []
    band.session_id = 'inert-band'
    band.venue = SimpleNamespace(open_orders=lambda: [{'id': oid}], cancel=owner.cancel)
    band.progress = lambda: None
    band._retain = lambda event, **fields: records.append((event, fields))
    assert band.cancel_remaining()
    assert any(event == 'cleanup_cancel_response' and fields['response'] == row for event, fields in records)


def test_submit_ack_through_actual_owner_transport_without_a_signer():
    from polymarket.models.clob.order_response import AcceptedOrder
    row = shape('submit_ack'); order = shape('open_orders_row')
    calls = []
    request = dict(token_id=order['token_id'], side='BUY', size='20', price='.30',
                   post_only=True, order_type='GTD', expiration=1800021600)
    maker = order['maker_address']
    # A value object stands in for the SDK's signed object; no signing function
    # or key exists in this test. The production binding checks still execute.
    signed = SimpleNamespace(maker=maker, signer=maker, signature_type=3,
        token_id=request['token_id'], side='BUY', order_type='GTD', post_only=True,
        expiration=request['expiration'], taker_amount=20_000_000, maker_amount=6_000_000)
    def posted(value):
        assert value is signed
        calls.append('post')
        return AcceptedOrder.model_validate(row)
    client = SimpleNamespace(create_limit_order=lambda **kw: signed, post_order=posted,
        get_order_book=lambda **kw: {'token_id': request['token_id'], 'market': order['market'],
                                    'asks': [{'price': '.50', 'size': '20'}]})
    owner = mapped_venue(client)
    owner.maker, owner.condition, owner.tokens = maker, order['market'], (request['token_id'],)
    owner.fields, owner.size, owner.reserve_cap = {'SIGNATURE_TYPE': '3'}, Decimal(20), Decimal('19.6')
    owner.before_post = lambda value: calls.append('intent')
    assert owner.submit(request, checkpoint=lambda: calls.append('checkpoint')) == row
    assert calls == ['checkpoint', 'intent', 'post']


@pytest.mark.parametrize('known', [True, False])
def test_open_order_row_matches_bound_fields_and_rejects_foreign_identity(known):
    row = shape('open_orders_row')
    # The literal sample reports one matched share. A LIVE partial fill must
    # signal fill, never be certified as a zero-fill resting order.
    client = SimpleNamespace(list_open_orders=lambda: page([order_model(row)]))
    owner = mapped_venue(client)
    rows = owner.open_orders()
    assert SecretGuard(['inert-redacted-owner']).clean(rows) == [row]
    with pytest.raises(HoldEnd):
        exact_open_orders(rows, {row['id'] if known else 'foreign':
            (row['token_id'], Decimal(row['price']), 11)}, maker=row['maker_address'], condition=row['condition_id'])
    zero = dict(row, size_matched='0')
    exact_open_orders([zero], {zero['id']: (zero['token_id'], Decimal(zero['price']), 11)},
                     maker=zero['maker_address'], condition=zero['condition_id'])


def test_open_orders_missing_pagination_never_means_empty_account():
    owner = mapped_venue(SimpleNamespace(list_open_orders=lambda: []))
    with pytest.raises(AmbiguousAccountRead, match='account_terminal_missing'):
        owner.open_orders()


def test_mined_trade_roundtrip_and_maker_allocation_do_not_credit_owner_cash():
    row = shape('trades_row')
    owner = mapped_venue(SimpleNamespace(list_account_trades=lambda **kwargs: page([trade_model(row)])))
    assert owner.trades() == [row]
    # All redacted order ids coincide. Rebind only the unrelated taker identity
    # before testing maker-only attribution; the literal is not a real account.
    distinct = deepcopy(row); distinct['taker_order_id'] = 'unrelated-taker'
    assert traded_shares([distinct], {row['maker_orders'][0]['order_id']}) == {
        row['maker_orders'][0]['order_id']: '1.11'}


def test_legacy_normalized_fill_needs_f2_wire_trade_identity():
    from weather.market.lfc_f2_repost import filtered_events
    band = SimpleNamespace(observed_trade_ids=set(), proven_trade_ids=set(),
        note_evidence_fault=lambda code: None, journal=SimpleNamespace(record=lambda *a, **k: None))
    with pytest.raises(HoldEnd, match='repost_trade_identity_unproven'):
        filtered_events(band, [shape('user_stream_fill_event')])
    assert 'trade_id' not in shape('fill_journal_user_event')


@pytest.mark.parametrize('name', [key for key in SHAPES if not key.startswith('_')])
def test_every_supplied_shape_survives_the_actual_transport_evidence_writer(tmp_path, name):
    import httpx
    from tests.market.test_lfc_f2_controller import NOW
    from weather.market.re1_attended import GuardedJournal
    from weather.market.lfc_recording_io import strict_json
    payload = shape(name)
    http = httpx.Client(base_url='https://clob.polymarket.com', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=json.dumps(payload).encode())))
    journal = GuardedJournal(tmp_path / 'journal.jsonl', clock=lambda: NOW,
                            scope={'fixture': 'T076'}, mode='rehearsal', guard=SecretGuard())
    owner = mapped_venue(SimpleNamespace(_ctx=SimpleNamespace(
        secure_clob=SimpleNamespace(_client=http))))
    try:
        owner.set_journal(journal)
        response = http.get('/inert-shape/' + name)
        assert response.json() == payload and not getattr(owner, 'journal_failed', False)
    finally:
        http.close(); journal.close()
    records = [strict_json(line) for line in journal.path.read_bytes().splitlines()]
    retained = next(row for row in records if row['event'] == 'sdk_response')
    assert retained['response'] == payload
    assert retained['sha256'] == hashlib.sha256(response.content).hexdigest()
    assert retained['length'] == len(response.content) and retained['status'] == 200
