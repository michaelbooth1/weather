"""Synthetic Data API v2 cash bridge; official fields, no service calls.

Guards: B036 reconciled legacy bridge, exact cursor walks and segregated credits.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from tests.market.test_lfc_f2_capital import MAKER, filled, ledger_at
from weather.market.lfc_capital import ASSET, CapitalBook, CapitalRefused
from weather.market.lfc_capital_reads import read_activity, synchronize
from weather.market.lfc_ledger import take_baseline, write_baseline
from weather.market.lfc_recording_io import retained


def packet(rows=(), *, cursor=None, more=False):
    return json.dumps({'data': list(rows), 'pagination': {'has_more': more, 'next_cursor': cursor}}).encode()


def rpc_packet(value):
    return retained(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': value}).encode())


def native_packet(packet):
    return {**packet, 'native_asset_proof': {'asset': ASSET, 'chain': rpc_packet('0x89'),
                                           'decimals': rpc_packet('0x6')}, 'native_receipts': {}}


def setup_read(tmp_path, *, token='yes'):
    ledger = ledger_at(tmp_path)
    now = ledger.clock()
    baseline = take_baseline(label='t40', now=now, maker_address=MAKER, positions=[], open_orders=[], available_collateral='100')
    write_baseline(ledger.path.parent, baseline, ledger)
    filled(ledger, 'legacy', token=token)
    read = {'complete': True, 'maker_address': MAKER, 'open_orders': [],
            'positions': [{'asset': token, 'size': '20'}],
            'balances': {'available_collateral': '290', 'assets': {ASSET: '290'},
                         'collateral_evidence': {'balance': '290000000'}},
            'ended_at_utc': now.isoformat(), 'capital_activity': native_packet(read_activity(MAKER, int(now.timestamp()),
                          int(now.timestamp()), get=lambda *a: packet(), sleep=lambda _: None))}
    return ledger, baseline, read


def test_legacy_bridge_reconciles_in_same_ledger_and_does_not_reset_L(tmp_path):
    ledger, baseline, read = setup_read(tmp_path)
    figures = synchronize(ledger, baseline, read)
    assert figures['complete'] and figures['legacy_L_native'] == 10_000_000
    assert figures['headroom_native'] == 290_000_000 and ledger.L() == 10
    before = ledger.path.read_bytes()
    assert synchronize(ledger, baseline, read) == figures
    assert ledger.path.read_bytes() == before


def test_mismatched_inventory_refuses_activation_until_read_agrees(tmp_path):
    ledger, baseline, read = setup_read(tmp_path)
    wrong = deepcopy(read)
    wrong['positions'] = []
    with pytest.raises(CapitalRefused, match='capital_inventory_unreconciled'):
        synchronize(ledger, baseline, wrong)
    assert CapitalBook(ledger).bridge is None
    assert synchronize(ledger, baseline, read)['complete']


def test_wrong_asset_or_unexplained_cash_never_funds_the_sleeve(tmp_path):
    ledger, baseline, read = setup_read(tmp_path)
    wrong = deepcopy(read)
    wrong['balances']['assets'] = {'usdc': '290'}
    with pytest.raises(CapitalRefused, match='capital_collateral_identity'):
        synchronize(ledger, baseline, wrong)
    synchronize(ledger, baseline, read)
    read['balances'].update(available_collateral='300', assets={ASSET: '300'}, collateral_evidence={'balance': '300000000'})
    observed = synchronize(ledger, baseline, read)
    assert observed['quarantined_unattributed_incoming_native'] == 10_000_000
    assert observed['cash_bridge_complete'] is False
    assert CapitalBook(ledger).expected_cash() == 290_000_000
    read['balances'].update(available_collateral='289', assets={ASSET: '289'}, collateral_evidence={'balance': '289000000'})
    with pytest.raises(CapitalRefused, match='capital_cash_unreconciled'):
        synchronize(ledger, baseline, read)


def test_all_filters_are_repeated_on_cursor_pages_and_walk_is_bounded():
    calls = []
    def get(endpoint, params):
        calls.append((endpoint, params))
        return packet(cursor='next', more=True) if len(calls) == 1 else packet()
    result = read_activity(MAKER, 1, 2, get=get, sleep=lambda _: None)
    assert result['complete'] and len(result['pages']) == 2
    assert calls[1][1] == {**calls[0][1], 'cursor': 'next'}
    assert calls[0][1]['exclude_deposits_withdrawals'] == 'false'
    with pytest.raises(CapitalRefused, match='capital_activity_cursor'):
        read_activity(MAKER, 1, 2, get=lambda *a: packet(cursor='loop', more=True), sleep=lambda _: None)


@pytest.mark.parametrize('page', [{}, {'data': []}, {'data': [], 'pagination': {'has_more': False}},
                                 {'data': [], 'pagination': {'has_more': False, 'next_cursor': 'next'}}])
def test_incomplete_success_never_means_no_cash_movements(page):
    with pytest.raises(CapitalRefused):
        read_activity(MAKER, 1, 2, get=lambda *a: json.dumps(page).encode(), sleep=lambda _: None)
