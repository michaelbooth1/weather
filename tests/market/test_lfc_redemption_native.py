"""Synthetic mined redemption shapes; no service, wallet or credential reads.

Guards: B040 paired redemptions, per-position payouts, quarantine and propagation.
"""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path

from eth_abi import encode
from eth_utils import keccak
import pytest

from tests.market.test_lfc_campaign import Clock, Mutexes, state_at
from tests.market.test_lfc_f2_capital import MAKER, activity, filled, install, ledger_at
from tests.market.test_lfc_f2_capital_reads import rpc_packet
from tests.market.test_lfc_f2_native import BLOCK, TX, log, proof
from weather.market.lfc_campaign import TransientPrecheck
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_state import AccountState, MoneyContradiction
from weather.market.lfc_capital import CapitalBook, normalize_activity, record_activity
from weather.market.lfc_capital_consistency import observe
from weather.market.lfc_capital_native import cash_native, rpc_read
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_redemption_native import (AUTO, AUTO_POSITION, BATCH, CTF, MODULES, PM,
    POSITION, REDEEM, SINGLE, ZERO, ctf_calls, permitted_call, positions)
from weather.market.mm_stage2_hold import digest


@pytest.fixture(autouse=True)
def guarded_account():
    with account_lease(MAKER, backend=Mutexes()):
        yield


def word(value):
    return '0x' + (value[2:] if isinstance(value, str) else hex(value)[2:]).rjust(64, '0')


def event(contract, signature, indexed, types, values, index):
    return {'address': contract, 'topics': [signature, *map(word, indexed)],
            'data': '0x' + encode(types, values).hex(), 'transactionHash': TX,
            'blockHash': BLOCK, 'blockNumber': '0x123', 'logIndex': hex(index), 'removed': False}


def paired(*, auto=False, ctf=False):
    source = json.loads((Path(__file__).parents[1] / 'fixtures/lfc/paired_redeem_v2.json').read_text())
    logs, views = [], {}
    if ctf:
        cid, collateral = source['condition_id'], '0x' + 'd' * 40
        collections = ['0x' + '2' * 64, '0x' + '3' * 64]
        tokens = [int.from_bytes(keccak(bytes.fromhex(collateral[2:] + c[2:])), 'big') for c in collections]
        recipient = AUTO if auto else ZERO
        logs.append(event(CTF, BATCH, [AUTO if auto else MAKER, MAKER, recipient],
                          ['uint256[]', 'uint256[]'], [tokens, [20_000_000] * 2], 0))
        if auto:
            logs.append(event(CTF, BATCH, [AUTO, AUTO, ZERO], ['uint256[]', 'uint256[]'], [tokens, [20_000_000] * 2], 1))
        logs.append(event(CTF, REDEEM, [AUTO if auto else MAKER, collateral, ZERO],
                    ['bytes32', 'uint256[]', 'uint256'], [bytes.fromhex(cid[2:]), [1, 2], 20_000_000], len(logs)))
        views = dict(zip(ctf_calls(cid), map(rpc_packet, [word(1), word(1), word(0), *collections])))
    else:
        tokens, module = [101, 102], sorted(MODULES)[0]
        for token, payout in zip(tokens, [20_000_000, 0]):
            logs.append(event(PM, SINGLE, [AUTO if auto else MAKER, MAKER, module],
                              ['uint256', 'uint256'], [token, 20_000_000], len(logs)))
            logs.append(event(PM, SINGLE, [module, module, ZERO], ['uint256', 'uint256'], [token, 20_000_000], len(logs)))
            logs.append(event(module, POSITION, [AUTO if auto else MAKER, token, AUTO if auto else MAKER],
                              ['uint256', 'uint256'], [20_000_000, payout], len(logs)))
            if auto:
                logs.append(event(AUTO, AUTO_POSITION, [MAKER, token], ['uint256'], [payout], len(logs)))
    logs.append(log(20_000_000, index=len(logs)))
    native = proof([source])
    native.update(receipt=rpc_packet({'transactionHash': TX, 'blockHash': BLOCK, 'blockNumber': '0x123',
                                      'status': '0x1', 'logs': logs}), ctf_views=views)
    return source, native, list(map(str, tokens))


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('ctf', [False, True])
def test_single_api_row_redeems_both_sides_from_position_payouts(tmp_path, auto, ctf):
    row, native, tokens = paired(auto=auto, ctf=ctf)
    ledger = ledger_at(tmp_path)
    filled(ledger, 'winner', token=tokens[0], condition=row['condition_id'], price='.35')
    filled(ledger, 'loser', token=tokens[1], condition=row['condition_id'], price='.45')
    install(ledger, cash='284')
    record_activity(ledger, row, native_evidence=native)
    book = CapitalBook(ledger)
    assert book.returned_principal == 7_000_000
    assert book.losses == 9_000_000 and book.profit == 13_000_000
    assert book.expected_cash() == 304_000_000 and book.figures()['headroom_native'] == 291_000_000
    assert all(lot['remaining_quantity'] == 0 for lot in book.lots.values())
    assert CapitalBook(Ledger.open(ledger.path, clock=ledger.clock)).figures() == book.figures()


def test_duplicate_api_rows_for_one_native_bundle_credit_once(tmp_path):
    row, native, tokens = paired()
    second = {**row, 'token_id': tokens[1]}
    native.update(rows=[row, second], rows_sha256=digest([row, second]))
    ledger = ledger_at(tmp_path)
    for key, token in zip(('one', 'two'), tokens):
        filled(ledger, key, token=token, condition=row['condition_id'])
    install(ledger, cash='280')
    for source in (row, second):
        record_activity(ledger, source, native_evidence=native)
    book = CapitalBook(ledger)
    assert book.cash_in == 20_000_000 and book.returned_principal == 10_000_000
    assert len(book.removal_events) == 2 and book.losses == 10_000_000


@pytest.mark.parametrize('defect', ['missing_burn', 'missing_view', 'wrong_cash', 'missing_auto', 'duplicate'])
def test_unproved_native_allocation_returns_no_principal(defect):
    row, native, _ = paired(auto=True, ctf=defect == 'missing_view')
    raw = json.loads(native['receipt']['raw_response'])
    logs = raw['result']['logs']
    if defect == 'missing_burn': del logs[1]
    if defect == 'missing_auto': logs[:] = [l for l in logs if l['address'] != AUTO]
    if defect == 'missing_view': native['ctf_views'] = {}
    if defect == 'wrong_cash': logs[-1]['data'] = word(21_000_000)
    if defect == 'duplicate': logs.append(deepcopy(logs[0]))
    native['receipt'] = rpc_packet(raw['result'])
    assert cash_native(row, native) is None
    assert positions(row, native) is None


@pytest.mark.parametrize('case', ['outside', 'pre_snapshot', 'outcome_999'])
def test_unmatched_redemption_is_quarantined_and_never_blocks_ledger_write(tmp_path, case):
    ledger = ledger_at(tmp_path)
    filled(ledger, 'lot')
    install(ledger)
    row = activity(cash='20', token='outside')
    if case == 'pre_snapshot': row['timestamp'] -= 60
    if case == 'outcome_999': row['outcome_index'] = 999
    record_activity(ledger, row)
    book = CapitalBook(ledger)
    assert book.returned_principal == 0 and book.external == 20_000_000
    assert book.redemptions[next(iter(book.redemptions))]['unallocated']
    assert book.figures()['headroom_native'] == (270_000_000 if case == 'pre_snapshot' else 290_000_000)


def test_late_receipt_replaces_unknown_scope_without_losing_lot_basis(tmp_path):
    row, native, tokens = paired()
    ledger = ledger_at(tmp_path)
    for key, token in zip(('one', 'two'), tokens): filled(ledger, key, token=token, condition=row['condition_id'])
    install(ledger, cash='280')
    record_activity(ledger, row, native_evidence={**native, 'receipt': rpc_packet(None)})
    book = CapitalBook(ledger)
    assert book.returned_principal == 0
    ledger.record('capital_resolution', source=row, source_sha256=digest(row),
                  previous_source_sha256=book.sources[normalize_activity(row)['id']], native_evidence=native)
    book = CapitalBook(ledger)
    assert not book.unknown and book.cash_in == 20_000_000
    assert book.losses == book.returned_principal == 10_000_000


def test_ctf_view_allowlist_is_historical_and_read_only():
    data = ctf_calls('0x' + '1' * 64)[0]
    assert permitted_call([{'to': CTF, 'data': data}, '0x123'])
    for params in ([{'to': CTF, 'data': data}, 'latest'], [{'to': MAKER, 'data': data}, '0x123'],
                   [{'to': CTF, 'data': '0xdeadbeef'}, '0x123']):
        assert not permitted_call(params)
        with pytest.raises(ValueError, match='capital_rpc_method_refused'): rpc_read('eth_call', params)


@pytest.mark.parametrize('reboot', [False, True])
def test_redemption_race_defers_until_two_mismatches_fifteen_minutes_apart(tmp_path, reboot):
    clock = Clock()
    state = state_at(tmp_path, clock)
    with pytest.raises(TransientPrecheck): observe(state, clock.now(), reason='capital_inventory_unreconciled')
    assert not state.incidents()
    clock.sleep(899)
    if reboot: state = AccountState(tmp_path / 'state', Ledger.open(state.ledger.path, clock=clock.now))
    with pytest.raises(TransientPrecheck): observe(state, clock.now(), reason='capital_cash_unreconciled')
    assert not state.incidents()
    clock.sleep(1)
    with pytest.raises(MoneyContradiction): observe(state, clock.now(), reason='capital_inventory_unreconciled')
    assert state.incidents()


def test_consistent_read_resets_only_propagation_candidate(tmp_path):
    clock = Clock()
    state = state_at(tmp_path, clock)
    with pytest.raises(TransientPrecheck): observe(state, clock.now(), reason='capital_cash_unreconciled')
    clock.sleep(900)
    observe(state, clock.now())
    with pytest.raises(TransientPrecheck): observe(state, clock.now(), reason='capital_cash_unreconciled')
    assert not state.incidents()


@pytest.mark.parametrize('late', [False, True])
def test_native_half_payout_preserves_each_mixed_basis_lots_loss(tmp_path, late):
    row, native, tokens = paired(ctf=True)
    raw = json.loads(native['receipt']['raw_response'])['result']
    raw['logs'][0]['data'] = '0x' + encode(['uint256[]', 'uint256[]'], [list(map(int, tokens)), [40_000_000, 0]]).hex()
    keys = ctf_calls(row['condition_id'])
    native['ctf_views'].update({keys[0]: rpc_packet(word(2)), keys[2]: rpc_packet(word(1))})
    native['receipt'] = rpc_packet(raw)
    row.update(token_id=tokens[0], size=40.0)
    native.update(rows=[row], rows_sha256=digest([row]))
    ledger = ledger_at(tmp_path)
    for key, price in [('high', '.70'), ('low', '.30')]:
        filled(ledger, key, price=price, token=tokens[0], condition=row['condition_id'])
    install(ledger, cash='280')
    if late:
        record_activity(ledger, row, native_evidence={**native, 'receipt': rpc_packet(None)})
        book = CapitalBook(ledger)
        ledger.record('capital_resolution', source=row, source_sha256=digest(row),
            previous_source_sha256=book.sources[normalize_activity(row)['id']], native_evidence=native)
    else:
        record_activity(ledger, row, native_evidence=native)
    book = CapitalBook(ledger)
    assert book.returned_principal == 16_000_000 and book.losses == book.profit == 4_000_000
    from weather.market.lfc_capital import CapitalRefused
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        book.gate(reserve='296.000001', available_cash='300')
