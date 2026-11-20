"""Synthetic shared-wallet activity.

Guards: B090-L7b, exclusive heartbeat keys, scoped cancellation and bounded owner proofs.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_f2_capital import MAKER
from tests.market.test_lfc_f2_personal_cash_b081 import account_guard
from tests.market.test_lfc_owner_external_close import (
    ATTEMPT, FOREIGN, MARKET, ORDER, TX, activity_page, fixture_trade,
)
from weather.market.lfc_capital import CapitalBook, CapitalRefused
from weather.market.lfc_f2_controller import ScopedVenue
from weather.market.lfc_f2_order_scope import gate, mark_open_orders
from weather.market.lfc_f2_owner_notice import NOTICE, OVERLAP, scope
from weather.market.lfc_f2_owner_postcheck import ActivityPending, Budget, prove
from weather.market.lfc_f2_runtime import stream_factory
from weather.market.mm_stage2_hold import digest
from weather.market.re1_attended import SecretGuard


KEY = '00000000-0000-4000-8000-000000000001'
OTHER_KEY = '00000000-0000-4000-8000-000000000002'


def test_scope_uses_bound_leg_conditions_and_omits_absent_conditions():
    ledger = SimpleNamespace(rows=[{'event': 'session_start'},
        {'event': 'leg_intent', 'condition_id': MARKET.upper(), 'token_id': '201'}])
    assert scope(ledger) == ({MARKET}, {'201'})
    assert scope(ledger, 1) == (set(), set())


def frame(kind):
    if kind == 'trade':
        return dict(event_type=kind, market=FOREIGN, maker_address=MAKER, status='MATCHED',
                    id='trade-1', taker_order_id=ORDER, asset_id='90', maker_orders=[])
    return dict(event_type=kind, condition_id=FOREIGN, proxy_wallet=MAKER, txn_hash=TX)


@pytest.mark.parametrize('kind', ['trade', 'auto_redeem', 'redeem', 'deposit', 'withdrawal', 'reward',
                                  'rebate', 'maker_rebate', 'merge'])
def test_stream_notice_stays_out_of_fills_without_transport(tmp_path, monkeypatch, kind):
    def forbidden(*_, **__):
        pytest.fail('native receipt called on quote loop')
    monkeypatch.setattr('weather.market.lfc_capital_native.rpc_read', forbidden)
    monkeypatch.setattr('weather.market.lfc_owner_external_close.rpc_read', forbidden)
    pair = stream_factory({}, owner_activity_scope=lambda: ({MARKET}, {'201', '202'}))
    stream = pair(tokens=('201', '202'), guard=SecretGuard(), api_key=KEY, secret='inert',
                  passphrase='inert', maker_address=MAKER, condition_id=MARKET,
                  journal_path=tmp_path/'ws.jsonl')
    received = stream._normalize_event(frame(kind))
    assert len(received) == 1 and received[0]['event_type'] == NOTICE
    assert received[0]['raw_event_sha256'] == digest(frame(kind))
    notices, current = [], {'event_type': 'trade'}
    raw = SimpleNamespace(events=lambda: [*received, current])
    venue = ScopedVenue(raw, SimpleNamespace(note_owner_activity=notices.append), 'inert')
    assert venue.account_events() == [current] and notices == received


def test_overlap_is_money_contradiction_and_missing_confirmation_defers(tmp_path, account_guard):
    runtime, ledger, read, _, receipt = fixture_trade(tmp_path, example=True, shared_wallet=True)
    traded = runtime.account_read_preflight(ledger, read)
    budget = SimpleNamespace(public_get=lambda *_: activity_page([]), rpc=lambda *_: receipt)
    prior = ledger.path.read_bytes(), ledger.previous, CapitalBook(ledger).figures()
    assert prove(runtime, ledger, ATTEMPT, read, traded, [(OVERLAP, None)], budget)['money_contradiction']
    with pytest.raises(ActivityPending, match='owner_activity_confirmation_pending'):
        prove(runtime, ledger, ATTEMPT, read, traded, [(NOTICE, digest(['trade', 'not-in-rest']))], budget)
    own = read['trades'][-1]
    own.update(condition_id=MARKET, market=MARKET)
    assert prove(runtime, ledger, ATTEMPT, read, traded, [], budget)['money_contradiction']
    assert (ledger.path.read_bytes(), ledger.previous, CapitalBook(ledger).figures()) == prior


def test_deadline_does_not_admit_next_chain_request(tmp_path, account_guard, monkeypatch):
    runtime, _, _, _, _ = fixture_trade(tmp_path, example=True)
    calls = []
    monkeypatch.setattr('weather.market.lfc_capital_native.rpc_read', lambda *a, **k: calls.append(k['timeout']))
    budget = Budget(runtime.clock, seconds=4)
    budget.rpc('eth_chainId', [])
    runtime.clock.value += timedelta(seconds=5)
    with pytest.raises(ActivityPending, match='owner_activity_proof_deadline'):
        budget.rpc('eth_chainId', [])
    assert calls == [4]


def test_non_campaign_order_checks_key_scope_and_campaign_spendable(tmp_path, account_guard):
    _, ledger, read, _, _ = fixture_trade(tmp_path, example=True, shared_wallet=True, deposit=20)
    order = dict(id=ORDER, market=FOREIGN, asset_id='90', owner=OTHER_KEY, maker_address=MAKER,
                 side='BUY', status='LIVE', price='.5', original_size='40', size_matched='8')
    book = CapitalBook(ledger)
    cash = str(book.expected_cash() / 1_000_000)
    marked = mark_open_orders([order], KEY)
    assert 'owner' not in marked[0] and marked[0]['heartbeat_key_isolated']
    assert gate(ledger, marked, cash=cash, reserve=95)['segregated_external_cash_native'] == 20_000_000
    with pytest.raises(CapitalRefused, match='foreign_open_order_heartbeat_scope'):
        gate(ledger, mark_open_orders([order | {'owner': KEY}], KEY), cash=cash, reserve=95)
    with pytest.raises(CapitalRefused, match='foreign_open_order_campaign_overlap'):
        gate(ledger, [marked[0] | {'asset_id': '201'}], cash=cash, reserve=95)
    with pytest.raises(CapitalRefused, match='capital_spendable_cash'):
        gate(ledger, [marked[0] | {'original_size': '50'}], cash=cash, reserve=100)


def test_shared_band_cancel_requires_the_exact_campaign_order():
    class NeverUsed:
        def cancel(self, oid):
            pytest.fail('an unbound order could reach a cancellation client')
    from weather.market.mm_stage2_hold import HoldEnd
    from weather.market.lfc_f2_controller import F2Coordinator
    coordinator = object.__new__(F2Coordinator)
    coordinator.ledger = SimpleNamespace(legs={'inferred': {'session_id': 'fixture'}},
        by_order={ORDER: 'inferred'}, event_rows=lambda *args, **kwargs: [])
    venue = ScopedVenue(NeverUsed(), coordinator, 'fixture')
    # Inferred or adopted matching terms still have no submit acknowledgment.
    with pytest.raises(HoldEnd, match='campaign_cancel_order_unbound'):
        venue.cancel(ORDER)


def test_readiness_heartbeat_checks_scope_before_sender():
    from weather.market.re1_transport import OwnerVenue
    venue = object.__new__(OwnerVenue)
    venue.readonly = venue.preflight = True
    rows = [{'id': ORDER}]
    sent, checked = [], []
    venue.open_orders = lambda: rows
    venue.sender = SimpleNamespace(send=lambda: sent.append(True))
    with pytest.raises(RuntimeError, match='preflight_heartbeat_requires_empty_account'):
        venue.heartbeat()
    venue.preflight_order_scope = checked.append
    venue.heartbeat()
    assert checked == [rows] and sent == [True]
    def refuse(_):
        raise CapitalRefused('foreign_open_order_heartbeat_scope')
    venue.preflight_order_scope = refuse
    with pytest.raises(CapitalRefused, match='foreign_open_order_heartbeat_scope'):
        venue.heartbeat()
    assert sent == [True]


def test_deposit_wallet_order_read_uses_all_pages_with_documented_cursor():
    from weather.market.re1_transport import wallet_open_orders

    pages = {None: {'data': [], 'next_cursor': 'first'},
             'first': {'data': [{'id': ORDER}], 'next_cursor': ''}}
    calls = []
    def get(path, params):
        assert path == '/data/wallet-open-orders'
        calls.append(params)
        return pages[params.get('cursor')]
    assert wallet_open_orders(get) == [{'id': ORDER}]
    assert calls == [{}, {'cursor': 'first'}]
    pages['first']['next_cursor'] = 'first'
    with pytest.raises(ConnectionError, match='wallet_open_orders_unavailable'):
        wallet_open_orders(get)
    pages['first'].pop('next_cursor')
    with pytest.raises(ConnectionError, match='wallet_open_orders_unavailable'):
        wallet_open_orders(get)


def test_wallet_order_with_withheld_key_binds_a_distinct_signer():
    signer, other = '0x' + '1'*40, '0x' + '2'*40
    rows = [{'owner': None, 'signer_address': other}, {'owner': None, 'signer_address': signer}]
    left, right = mark_open_orders(rows, KEY, signer)
    assert left['heartbeat_key_isolated'] and not right['heartbeat_key_isolated']
    assert 'owner' not in left and 'owner' not in right


def test_exclusive_heartbeat_attestation_rejects_unbound_and_rotated_keys():
    from weather.market.lfc_campaign import TransientPrecheck
    from weather.market.lfc_campaign_release import HEARTBEAT_BINDING, f2_heartbeat_key_hash, require_f2_heartbeat_key
    seal = {HEARTBEAT_BINDING: f2_heartbeat_key_hash(KEY)}
    require_f2_heartbeat_key(seal, {'API_KEY': KEY})
    for release, fields in (({}, {'API_KEY': KEY}), (seal, {'API_KEY': OTHER_KEY}), (seal, {})):
        with pytest.raises(TransientPrecheck, match='f2_heartbeat_key_not_bound'):
            require_f2_heartbeat_key(release, fields)
