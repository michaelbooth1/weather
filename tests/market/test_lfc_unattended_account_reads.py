"""Closed SDK integration and account-read fixtures.

Guards: B018/T022 F01 complete bounded account reads, F04 normalized expiration
adoption, and F10 condition-scoped ledger reconciliation across campaign sessions.
"""
from types import SimpleNamespace

import httpx
import pytest

from weather.market.mm_account_reads import AmbiguousAccountRead, account_rows
from weather.market.mm_official_adapter import OfficialPolymarketGlobalAdapter, plain_sdk_value
from weather.market.lfc_cli import adopt_intents, reconcile_trades_bounded
from tests.market.test_lfc_cli import lost_ack, FakeVenue, EXPIRATION
from tests.market.test_lfc_rewards_record import MAKER, CONDITION, START
from weather.market.lfc_ledger import Ledger


@pytest.mark.parametrize('mode', ['python', 'json'])
def test_adoption_uses_real_sdk_dump_without_aliases(tmp_path, mode):
    from polymarket.models.clob.account import OpenOrder
    ledger = lost_ack(tmp_path, journal_ids=())
    model = OpenOrder.model_validate(dict(id='o2', market=CONDITION, asset_id='1', owner='synthetic',
        maker_address=MAKER, side='BUY', price='.5', original_size='40', size_matched='0', outcome='Yes',
        order_type='GTD', status='LIVE', created_at=1780000000, expiration=str(EXPIRATION)))
    row = model.model_dump(mode=mode, by_alias=False)
    assert 'expiration' not in row and row['expires_at'] is not None
    venue = FakeVenue([row], {'o2': row})
    adopted, refused = adopt_intents(ledger, venue, root=tmp_path, open_rows=[row])
    assert adopted == ['o2'] and refused == {}


def sdk_client(reply):
    """Use real public SDK pagination/parsing with a synthetic HTTP transport; no constructor or credentials."""
    from polymarket import SecureClient
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=reply(len(calls)), request=request)
    http = httpx.Client(base_url='https://clob.polymarket.com', transport=httpx.MockTransport(handler))
    transport = SimpleNamespace(_client=http, get_json=lambda path, params: http.get(path, params=params).json())
    client = object.__new__(SecureClient)
    client._ended = False
    client._ctx = SimpleNamespace(secure_clob=transport)
    adapter = OfficialPolymarketGlobalAdapter(client, maker_address=MAKER, sdk_version='0.6.0')
    return client, adapter, http, calls


@pytest.mark.parametrize('body', [{'data': []}, {'data': [], 'next_cursor': 'LTE='},
    {'data': [], 'next_cursor': 'LTE=', 'count': 1, 'limit': 500},
    {'data': [], 'next_cursor': None, 'count': 0, 'limit': 500},
    {'data': [{}], 'next_cursor': 'LTE=', 'count': 1, 'limit': 500}])
def test_incomplete_successful_raw_account_page_is_ambiguous(body):
    _, adapter, http, calls = sdk_client(lambda _: body)
    try:
        with pytest.raises(AmbiguousAccountRead) as error:
            adapter.open_orders()
        assert error.value.state == 'AMBIGUOUS' and len(calls) == 1
    finally:
        http.close()


def test_real_sdk_complete_empty_page_is_proven_empty():
    _, adapter, http, _ = sdk_client(lambda _: {'data': [], 'next_cursor': 'LTE=', 'count': 0, 'limit': 500})
    try:
        assert adapter.open_orders() == []
    finally:
        http.close()


def test_real_sdk_repeated_cursor_and_page_cap_are_bounded():
    client, adapter, http, calls = sdk_client(lambda _: {'data': [], 'next_cursor': 'cycle', 'count': 0, 'limit': 500})
    try:
        with pytest.raises(AmbiguousAccountRead): adapter.open_orders()
        assert len(calls) == 2
    finally:
        http.close()
    client, _, http, calls = sdk_client(lambda n: {'data': [], 'next_cursor': str(n), 'count': 0, 'limit': 500})
    try:
        with pytest.raises(AmbiguousAccountRead):
            account_rows(client.list_open_orders(), normalize=plain_sdk_value, page_cap=3)
        assert len(calls) == 3
    finally:
        http.close()


def test_later_condition_read_does_not_halt_for_prior_condition_fill(tmp_path):
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=lambda: START, maker_address=MAKER)
    for index, condition in enumerate(('0x' + 'b' * 64, CONDITION)):
        sid, oid = f'S{index}', f'order-{index}'
        ledger.record('session_start', session_id=sid, condition_id=condition, counted=True)
        ledger.intent(session_id=sid, intent_key=sid+':0', condition_id=condition, token_id=str(index+1),
                      price='.4', size='20', fee_rate_bps='0')
        ledger.ack(sid+':0', oid)
        ledger.terminal(oid, {'status': 'MATCHED', 'size_matched': '1'}, source='fixture')
    venue = SimpleNamespace(condition=CONDITION, trades=lambda: [
        {'status': 'CONFIRMED', 'maker_orders': [{'order_id': 'order-1', 'matched_amount': '1'}]}])
    traded, mismatch = reconcile_trades_bounded(ledger, venue, attempts=1)
    assert traded == {'order-1': '1'} and mismatch == []
    assert ledger.stop_reason() is None and ledger.mismatches == []


@pytest.mark.parametrize('row', [{'status': 'UNKNOWN', 'size_matched': '0'},
    {'status': 'DELAYED', 'size_matched': '0'}, {'status': 'CANCELED'},
    {'status': 'CANCELED', 'size_matched': 'NaN'}, {'status': 'CANCELED', 'size_matched': True}])
def test_unproven_terminal_read_keeps_full_reserve(tmp_path, row):
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=lambda: START, maker_address=MAKER)
    ledger.record('session_start', session_id='S1', counted=True)
    ledger.intent(session_id='S1', intent_key='S1:0', condition_id=CONDITION, token_id='1',
                  price='.4', size='20', fee_rate_bps='0')
    ledger.ack('S1:0', 'order-1')
    before = ledger.L()
    assert ledger.terminal('order-1', row, source='fixture') is None
    assert ledger.L() == before and ledger.unresolved_legs()[0]['order_id'] == 'order-1'
