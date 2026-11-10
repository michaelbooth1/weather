"""Inert SDK boundary for Monday's redacted normalized reply structures.

Values are explicitly rebound to internally consistent synthetic orders. Null
samples mean unavailable samples, never an observed empty account. No SDK client
is constructed, and no real signing, credentials, readers or sockets are used.
"""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from polymarket.models.clob.account import ClobTrade, OpenOrder
from polymarket.models.clob.cancel import CancelOrdersResponse

from tests.market.lfc_pinb_fixtures import pinb_row
from tests.market.test_lfc_f2_repost import fixture as breadth_fixture
from weather.market import re1_transport as transport
from weather.market.lfc_capital import ASSET, native
from weather.market.mm_official_adapter import OfficialPolymarketGlobalAdapter, plain_sdk_value
from weather.market.re1_attended import SecretGuard


SHAPE_PATH = Path(__file__).parents[1] / 'fixtures/lfc/real_reply_shapes_20261109.json'
SHAPE_SHA = '863aa943ac5821f6756795037a7816cbd5b5457eae9c7ae4970755c76ecbb24d'
SHAPES = json.loads(SHAPE_PATH.read_bytes())


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import socket
    def refused(*args, **kwargs):
        pytest.fail('T076 has no network, credential or SDK-client authority')
    monkeypatch.setattr(socket.socket, 'connect', refused)
    monkeypatch.setattr(socket, 'create_connection', refused)
    monkeypatch.setattr(transport, 'build_client', refused)
    monkeypatch.setattr(transport, 'load_owner_credentials', refused)
    monkeypatch.setattr(transport, 'urlopen', refused)
    monkeypatch.setattr(transport, 're1_user_agent', lambda: 'T076-inert')


def shape(name):
    return deepcopy(SHAPES[name])


def order_model(row):
    """Invert normalized SDK aliases only; wire payload was not supplied."""
    raw = dict(row, asset_id=row['token_id'], owner='inert-redacted-owner')
    raw['expiration'] = str(int(datetime.fromisoformat(row['expires_at']).timestamp()))
    return OpenOrder.parse_response(raw)


def trade_model(row):
    raw = dict(row, asset_id=row['token_id'], match_time=row['matched_at'], last_update=row['updated_at'])
    raw['maker_orders'] = [dict(item, asset_id=item['token_id']) for item in row['maker_orders']]
    return ClobTrade.parse_response(raw)


def rebound_order(memory_row, condition):
    row = shape('open_orders_row' if memory_row['status'] == 'LIVE' else 'order_read_after_cancel_row')
    row.update(id=memory_row['id'], market=condition, condition_id=condition,
               token_id=memory_row['asset_id'], maker_address='0x' + 'a' * 40,
               price=memory_row['price'], original_size=memory_row['original_size'],
               size_matched=memory_row['size_matched'], status=memory_row['status'],
               associate_trades=memory_row['associate_trades'])
    return row


def rebound_trade(memory_row, condition):
    row = shape('trades_row')
    row.update(id='fill-' + memory_row['id'], market=condition, condition_id=condition,
               token_id=memory_row['asset_id'], maker_address='0x' + 'a' * 40,
               taker_order_id='foreign-taker', price=memory_row['price'], size=memory_row['size_matched'])
    row['maker_orders'][0].update(order_id=memory_row['id'], token_id=memory_row['asset_id'],
        maker_address='0x' + 'a' * 40, price=memory_row['price'], matched_amount=memory_row['size_matched'], side='BUY')
    return row


def page(rows):
    return [SimpleNamespace(items=tuple(rows), has_more=False, next_cursor=None)]


def mapped_venue(client):
    """Exercise OwnerVenue methods without its credential-bearing constructor."""
    owner = object.__new__(transport.OwnerVenue)
    owner.client, owner.readonly, owner.preflight = client, False, False
    owner.condition = None
    owner.adapter = OfficialPolymarketGlobalAdapter(client, maker_address='0x' + 'a' * 40,
                                                    sdk_version='0.6.0')
    return owner


def pinb_fixture(tmp_path, monkeypatch, *, lag=0, lag_phase='cleanup', fills=True,
                 trade_status='MINED', heartbeat_miss=False):
    # Change only the pre-existing TEST factory's policy source. All production
    # classes, cancellation, capital, continuation and evidence logic are real.
    from tests.market import test_lfc_f2_repost as fixtures
    with monkeypatch.context() as patch:
        patch.setattr(fixtures, 'example_policy', pinb_row)
        result = breadth_fixture(tmp_path, enrolled=True, seconds=600)
    controller, account, status, ledger, clock, runtime, read = result
    account.fills_enabled = fills
    trace = {'mapped_reads': [], 'cancel_replies': [], 'events': [], 'heartbeats': [], 'balances': []}
    started = []
    for raw in account.raws:
        original_submit, original_cancel = raw.submit, raw.cancel
        original_cancel_all = raw.cancel_all
        original_balances = raw.balances
        client = SimpleNamespace()
        owner = mapped_venue(client)
        owner.condition = raw.memory.condition
        owner.journal = controller.bands[raw.index].journal
        raw.set_journal = lambda journal, owner=owner: setattr(owner, 'journal', journal)
        raw.shape_owner = owner

        def get_order(*, order_id, raw=raw):
            account.advance()
            if lag_phase == 'fill' and account.fill_times and not started:
                started.append(clock.seconds)
                account.fills_enabled = False
            if raw.index == 0 and started and clock.seconds - started[0] < lag:
                trace['mapped_reads'].append((clock.seconds, order_id, 'undecodable'))
                # The sample is null: an actual SDK parse failure, then the
                # production OwnerVenue.order mapping, rather than a fake timeout.
                return OpenOrder.parse_response(shape('terminal_order_row'))
            row = rebound_order(raw.memory.orders[order_id], raw.memory.condition)
            trace['mapped_reads'].append((clock.seconds, order_id, row['status']))
            return order_model(row)

        def list_open_orders(raw=raw):
            return page([order_model(rebound_order(row, row['market'])) for row in account.open_orders()])

        def cancel_order(*, order_id, raw=raw, cancel=original_cancel):
            cancel(order_id)
            if raw.index == 0 and lag_phase == 'cleanup' and account.fill_times and not started:
                started.append(clock.seconds)
                account.fills_enabled = False
            reply = shape('cancel_ack'); reply['canceled'] = [order_id]
            trace['cancel_replies'].append(reply)
            return CancelOrdersResponse.model_validate(reply)

        def cancel_all(cancel=original_cancel_all):
            return CancelOrdersResponse.model_validate(cancel())

        def trades(raw=raw, **kwargs):
            rows = [rebound_trade(row, raw.memory.condition) for row in raw.memory.orders.values()
                    if Decimal(row['size_matched'])]
            for row in rows:
                row['status'] = trade_status
            return page([trade_model(row) for row in rows])

        client.get_order, client.list_open_orders, client.cancel_order = get_order, list_open_orders, cancel_order
        client.cancel_all, client.list_account_trades = cancel_all, trades
        raw.order, raw.open_orders, raw.cancel = owner.order, owner.open_orders, owner.cancel
        raw.cancel_all, raw.trades = owner.cancel_all, owner.trades

        def submit(request, *, checkpoint, submit=original_submit):
            reply = shape('submit_ack')
            reply['order_id'] = submit(request, checkpoint=checkpoint)['order_id']
            return plain_sdk_value(reply)
        raw.submit = submit

        def events(raw=raw):
            account.advance()
            emitted = getattr(raw, 'emitted', set())
            rows = []
            from tests.market.test_lfc_f2_repost import campaign_stream
            for memory_row in raw.memory.orders.values():
                tid = 'fill-' + memory_row['id']
                if Decimal(memory_row['size_matched']) and tid not in emitted:
                    emitted.add(tid)
                    # Inferred wire preimage: F0's supplied normalized event has
                    # no wire id. F2's actual factory adds trade_id from that id.
                    supplied = shape('user_stream_fill_event')
                    supplied.update(order_id=memory_row['id'], condition_id=raw.memory.condition,
                        clob_token_id=memory_row['asset_id'], fill_price=memory_row['price'],
                        fill_size=memory_row['size_matched'])
                    wire = dict(event_type='trade', id=tid, market=raw.memory.condition,
                        status=supplied['official_trade_status'], maker_orders=[dict(
                            order_id=supplied['order_id'], asset_id=supplied['clob_token_id'],
                            maker_address=raw.maker, price=supplied['fill_price'], matched_amount=supplied['fill_size'],
                            side=supplied['side'], outcome=supplied['outcome'])])
                    normalized = campaign_stream(raw)._normalize_event(wire)
                    trace['events'].extend(normalized)
                    rows.extend(normalized)
            raw.emitted = emitted
            return rows
        raw.events = events

        # No heartbeat/capital samples exist in the supplied file. These are
        # explicit synthetic controls at their production transport boundaries.
        owner.sender = transport.Re1Heartbeat(signer_address=raw.maker, api_key='inert',
            api_secret='aW5lcnQ=', api_passphrase='inert', clock=lambda: clock.now().timestamp())
        def mapped_heartbeat(raw=raw, owner=owner):
            owner.heartbeat_journal = getattr(raw, 'heartbeat_journal', owner.journal)
            return owner.heartbeat()
        raw.heartbeat = mapped_heartbeat
        owner.maker, owner.timeouts, owner.reserve_cap = raw.maker, {}, Decimal(20)
        owner.fixture_cash = original_balances
        owner.adapter.refresh_balance_allowance = lambda owner=owner: {
            'balance': str(native(owner.fixture_cash()['available_collateral'])),
            'allowances': {'fixture-spender': '300000000'}}
        def balances(owner=owner):
            # RPC transport is mocked below; select this band's synthetic cash.
            current_owner[:] = [owner]
            value = owner.balances()
            trace['balances'].append(value)
            return value
        raw.balances = balances
    current_owner = []
    def rpc(url, *, body, **kwargs):
        cash = current_owner[0].fixture_cash()['available_collateral']
        return {'jsonrpc': '2.0', 'id': body['id'], 'result': '0x' + format(native(cash), '064x')}
    def heartbeat(request, **kwargs):
        trace['heartbeats'].append(json.loads(request.data))
        if heartbeat_miss and len(trace['heartbeats']) == 3:
            raise TimeoutError('single synthetic heartbeat miss')
        return {'heartbeat_id': 'inert-' + str(len(trace['heartbeats']))}
    monkeypatch.setattr(transport, 'json_read', rpc)
    monkeypatch.setattr(transport, '_open_json', heartbeat)
    runtime.lease = SimpleNamespace(check=lambda: None)
    runtime.control_root = tmp_path / 'control'
    runtime.read_account = read
    return (*result, trace, started)


def close_claim(controller, account, status, ledger, clock, runtime):
    from weather.market.lfc_campaign_proof import local_money_proof
    outcome = status.finish(success=True)
    local = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                             attempt_id=controller.attempt_id, outcome=outcome)
    runtime.save_result(account.claim, {'session_id': controller.session_id,
        'private_evidence_directory': controller.directory.name, 'outcome': outcome,
        'local_money_proof': local, 'evidence_complete': True, 'inventory_proven': True,
        'unknown_submit': False})
    proof = runtime.postcheck(account.claim, runtime.saved_result(account.claim))
    assert proof['money_accounting_complete'] and proof['cleanup_proven'], proof
    runtime.state.close(account.claim, proof, clock.now())
    runtime.state.require_retained_evidence()
    assert not runtime.state.pending() and not runtime.state.incidents()
    return outcome, local, proof
