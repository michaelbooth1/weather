"""Native pUSD cash proof from synthetic EVM receipts, never USD conversion.

Guards: B036 native units, unknown/full-loss, exact batched allocation and read-only RPC semantics.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_f2_capital import MAKER, activity, filled, install, ledger_at
from tests.market.test_lfc_f2_capital_reads import rpc_packet
from weather.market.lfc_capital import ASSET, CapitalBook, normalize_activity, record_activity
from weather.market.lfc_capital_native import (TRANSFER, cash_native, collect, rpc_read, validate_packet)
from weather.market.mm_stage2_hold import digest


TX = '0x' + 'a' * 64
BLOCK = '0x' + 'b' * 64
SENDER = '0x' + 'c' * 40


def log(amount, *, sender=SENDER, receiver=MAKER, index=0, asset=ASSET):
    return {'address': asset, 'topics': [TRANSFER, '0x' + sender[2:].rjust(64, '0'),
             '0x' + receiver[2:].rjust(64, '0')], 'data': '0x' + hex(amount)[2:].rjust(64, '0'),
             'removed': False, 'transactionHash': TX, 'blockHash': BLOCK, 'logIndex': hex(index)}


def proof(rows, *, incoming=20_000_000, outgoing=0):
    logs = [log(incoming)] if incoming else []
    if outgoing:
        logs.append(log(outgoing, sender=MAKER, receiver=SENDER, index=len(logs)))
    receipt = {'transactionHash': TX, 'blockHash': BLOCK, 'blockNumber': '0x123', 'status': '0x1', 'logs': logs}
    return {'transaction_hash': TX, 'rows': rows, 'rows_sha256': digest(rows),
            'receipt': rpc_packet(receipt), 'failure_type': None}


def source(cash='999', **kwargs):
    return activity(cash=cash, tx=TX, **kwargs)


def test_usd_label_is_never_converted_or_credited_when_native_cash_differs(tmp_path):
    ledger = ledger_at(tmp_path)
    filled(ledger, 'lot')
    install(ledger)
    row = source(cash='999')
    native = proof([row], incoming=20_000_000)
    assert normalize_activity(row, native)['cash_native'] is None
    record_activity(ledger, row, native_evidence=native)
    book = CapitalBook(ledger)
    assert book.figures()['returned_principal_native'] == 0
    assert book.figures()['segregated_profit_native'] == 0
    assert book.figures()['headroom_native'] == 290_000_000


def test_unknown_receipt_returns_no_principal_and_zero_native_transfer_is_actual_zero(tmp_path):
    row = source(cash='20')
    unknown = {**proof([row]), 'receipt': rpc_packet(None)}
    assert cash_native(row, unknown) is None
    assert cash_native(row, proof([row], incoming=0)) == 0
    ledger = ledger_at(tmp_path)
    filled(ledger, 'lot')
    install(ledger)
    record_activity(ledger, row, native_evidence=unknown)
    assert CapitalBook(ledger).figures()['headroom_native'] == 290_000_000


def test_batch_needs_exact_allocation_and_cannot_reuse_whole_transfer_per_lot():
    first, second = source(cash='10', size='10'), source(cash='10', size='10', token='no')
    native = proof([first, second])
    # Exact total does not bind either condition to its own payout.
    assert cash_native(first, native) is cash_native(second, native) is None
    unknown = deepcopy(native)
    unknown['rows'][1]['usdc_size'] = None
    unknown['rows_sha256'] = digest(unknown['rows'])
    assert cash_native(first, unknown) is None
    mismatch = proof([first, second], incoming=19_000_000)
    assert cash_native(first, mismatch) is cash_native(second, mismatch) is None


def test_non_native_reward_never_funds_trading_and_outgoing_is_native_cost():
    row = source(cash='500', size='0', kind='REWARD')
    assert cash_native(row, proof([row], incoming=0)) == 0
    withdrawal = source(cash='1', size='0', kind='WITHDRAWAL')
    assert cash_native(withdrawal, proof([withdrawal], incoming=0, outgoing=700_000)) == 700_000


def test_native_redemption_bridges_legacy_lots_and_cached_receipt_is_not_refetched(tmp_path):
    from tests.market.test_lfc_f2_capital_reads import setup_read, packet
    from weather.market.lfc_capital_reads import read_activity, synchronize
    from tests.market.test_lfc_redemption_native import paired
    ledger, baseline, read = setup_read(tmp_path, token='101')
    row, position_proof, _ = paired()
    raw = read_activity(MAKER, int(row['timestamp']), int(row['timestamp']),
                        get=lambda *a: packet([row]), sleep=lambda _: None)
    calls = []
    def rpc(method, params):
        calls.append(method)
        return rpc_packet('0x89') if method == 'eth_chainId' else rpc_packet('0x6') if method == 'eth_call' else position_proof['receipt']
    read['capital_activity'] = collect(raw, ledger=ledger, rpc=rpc, sleep=lambda _: None)
    read['positions'] = []
    read['balances'] = {'available_collateral': '310', 'assets': {ASSET: '310'},
                        'collateral_evidence': {'balance': '310000000'}}
    result = synchronize(ledger, baseline, read)
    assert result['returned_principal_native'] == result['segregated_profit_native'] == 10_000_000
    assert result['funding_native'] == 300_000_000 and result['cash_bridge_complete']
    assert ledger.L() == 10 and len(CapitalBook(ledger).native_groups) == 1
    before = ledger.previous
    calls.clear()
    read['capital_activity'] = collect(raw, ledger=ledger, rpc=rpc, sleep=lambda _: None)
    assert calls == ['eth_chainId', 'eth_call']
    assert synchronize(ledger, baseline, read)['complete'] and ledger.previous == before


def test_failed_native_read_retains_bounded_raw_evidence_without_returning_principal(tmp_path):
    from weather.market.lfc_recording_io import PublicReadFailure
    from weather.market.lfc_capital_native import resolve
    ledger = ledger_at(tmp_path)
    row = source(cash='20')
    def rpc(method, params):
        if method == 'eth_chainId': return rpc_packet('0x89')
        if method == 'eth_call': return rpc_packet('0x6')
        raise PublicReadFailure('capital_rpc_response_refused', status=503, raw=b'{"error":"fixture"}')
    packet = collect({'rows': [row]}, ledger=ledger, rpc=rpc, sleep=lambda _: None)
    proof = resolve(packet['native_receipts'][TX], ledger)
    assert proof['failed_response']['raw_response'] == '{"error":"fixture"}'
    assert proof['failed_response']['status'] == 503 and cash_native(row, proof) is None


@pytest.mark.parametrize('mutation', ['removed', 'wrong_tx', 'wrong_block', 'duplicate_log', 'bad_padding', 'reverted'])
def test_incomplete_or_conflicting_receipt_never_releases_money(mutation):
    row = source()
    raw = {'transactionHash': TX, 'blockHash': BLOCK, 'blockNumber': '0x123', 'status': '0x1', 'logs': [log(20_000_000)]}
    if mutation == 'removed':
        raw['logs'][0]['removed'] = True
    elif mutation == 'wrong_tx':
        raw['transactionHash'] = '0x' + 'd' * 64
    elif mutation == 'wrong_block':
        raw['logs'][0]['blockHash'] = '0x' + 'd' * 64
    elif mutation == 'duplicate_log':
        raw['logs'].append(deepcopy(raw['logs'][0]))
    elif mutation == 'bad_padding':
        raw['logs'][0]['topics'][1] = '0x' + '1' * 24 + SENDER[2:]
    else:
        raw['status'] = '0x0'
    native = {**proof([row]), 'receipt': rpc_packet(raw)}
    with pytest.raises(ValueError):
        cash_native(row, native)


def test_rpc_method_allowlist_refuses_transactions_before_transport():
    for method, params in [('eth_sendRawTransaction', ['synthetic']), ('eth_sendTransaction', [{}]),
                           ('eth_call', [{'to': ASSET, 'data': '0xdeadbeef'}, 'latest']),
                           ('eth_getTransactionReceipt', ['not-a-tx'])]:
        with pytest.raises(ValueError, match='capital_rpc_method_refused'):
            rpc_read(method, params, opener=lambda *a, **k: pytest.fail('no request allowed'))


def test_native_metadata_and_receipts_are_retained_and_replayed_without_network(tmp_path):
    ledger = ledger_at(tmp_path)
    row = source()
    calls = []
    def rpc(method, params):
        calls.append((method, params))
        if method == 'eth_chainId':
            return rpc_packet('0x89')
        if method == 'eth_call':
            return rpc_packet('0x6')
        return proof([row])['receipt']
    packet = collect({'rows': [row]}, ledger=ledger, rpc=rpc, sleep=lambda _: None)
    validate_packet(packet, ledger=ledger)
    assert [method for method, _ in calls] == ['eth_chainId', 'eth_call', 'eth_getTransactionReceipt']
    bad = deepcopy(packet)
    bad['native_asset_proof']['decimals'] = rpc_packet('0x12')
    with pytest.raises(ValueError, match='capital_native_asset_identity'):
        validate_packet(bad, ledger=ledger)
    bad = deepcopy(packet)
    bad['native_receipts'][TX]['native_group_sha256'] = 'f' * 64
    with pytest.raises(ValueError):
        validate_packet(bad, ledger=ledger)


def test_receipt_accepts_documented_optional_log_metadata_without_guessing_cash():
    row = source(cash='20')
    native = proof([row])
    from weather.market.lfc_capital_native import result
    receipt = result(native['receipt'])
    for name in ('removed', 'blockHash', 'logIndex'):
        receipt['logs'][0].pop(name)
    native['receipt'] = rpc_packet(receipt)
    assert cash_native(row, native) == 20_000_000
