"""Guards: incident-specific external facts, native fees and segregated owner cash."""
from copy import deepcopy
from contextlib import nullcontext
from datetime import timedelta
from decimal import Decimal
import json
import os
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_f2_capital import MAKER, filled
from tests.market.test_lfc_f2_cash_mirror_b082 import cash_activity
from tests.market.test_lfc_f2_capital_reads import rpc_packet
from tests.market.test_lfc_f2_inventory_b080 import fixture, observation
from tests.market.test_lfc_f2_personal_cash_b081 import account_guard, owner_trade
from tests.market.test_lfc_redemption_native import paired
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_campaign_state import AccountState, StateRefused
from weather.market.lfc_capital import ASSET, CapitalBook, CapitalRefused, record_activity
from weather.market.lfc_capital_native import TRANSFER
from weather.market.lfc_capital_reads import read_activity, synchronize
from weather.market.lfc_ledger import Ledger, LedgerUnavailable
from weather.market.lfc_owner_external_close import (
    EXCHANGES, MAX_TRADES, ORDER_FILLED, PROOF_SCHEMA, PROTOCOL_MOVEMENTS, build_facts, live_proof,
)
from weather.market.lfc_recording_io import file_sha, retained
from weather.market.lfc_redemption_native import CTF, SINGLE
from weather.market.mm_stage2_hold import canonical_bytes, digest, utc


ATTEMPT = 'a' * 32
INCIDENT = 'f' * 32
INCIDENT_HASH = 'f' * 64
MARKET = '0x' + 'c' * 64
FOREIGN = '0x' + 'e' * 64
ORDER = '0x' + 'd' * 64
TX = '0x' + '1' * 64
LATER_TX = '0x' + 'a1' * 32
GROSS, FEE, SIZE = 10_400_000, 800_000, 20_000_000


def trade_receipt(cash_in, cash_out, *, side='SELL', gross=GROSS, tx=TX, order=ORDER):
    wallet, other = f'0x{int(MAKER, 16):064x}', f'0x{9:064x}'
    fields = {'transactionHash': tx, 'blockNumber': '0x100', 'blockHash': '0x' + 'b' * 64}

    def move(index, send, receive, amount):
        return {**fields, 'address': ASSET, 'logIndex': hex(index), 'topics': [TRANSFER, send, receive],
                'data': f'0x{amount:064x}'}

    logs = [move(0, other, wallet, cash_in)] if cash_in else []
    if cash_out:
        logs.append(move(1, wallet, other, cash_out))
    direction, making, taking = (0, gross, SIZE) if side == 'BUY' else (1, SIZE, gross)
    sender, receiver = (other, wallet) if side == 'BUY' else (wallet, other)
    logs.extend([
        {**fields, 'address': CTF, 'logIndex': '0x2', 'topics': [SINGLE, other, sender, receiver],
         'data': f'0x{90:064x}{SIZE:064x}'},
        {**fields, 'address': min(EXCHANGES), 'logIndex': '0x3', 'topics': [ORDER_FILLED, order, wallet, other],
         'data': '0x' + ''.join(f'{n:064x}' for n in (direction, 90, making, taking, FEE, 0, 0))},
    ])
    return retained(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {**fields, 'status': '0x1', 'logs': logs}}).encode())


def activity_page(rows):
    return json.dumps({'data': rows, 'pagination': {'next_cursor': None, 'has_more': False}}).encode()


@pytest.fixture(autouse=True)
def empty_protocol_feed(monkeypatch):
    def empty(wallet, anchor, cut):
        return read_activity(wallet, anchor.timestamp(), cut.timestamp(),
                             get=lambda *_: activity_page([]), types=PROTOCOL_MOVEMENTS)
    monkeypatch.setattr('weather.market.lfc_owner_external_close.read_protocol_movements', empty)


def fixture_trade(tmp_path, *, separate_fee=False, side='SELL', deposit=0, withdraw=0, quarantine=0,
                  example=False, owner_position='30', personal_holdings=None):
    ledger, baseline, clock, _ = fixture(tmp_path, personal=False, bridge=False)
    holdings = {'denver': '20', '90': owner_position, **(personal_holdings or {})}
    if not example:
        source, proof, tokens = paired(auto=True)
        for idx, token in enumerate(tokens):
            filled(ledger, f'pair-{idx}', token=token, condition=source['condition_id'], price='.48')
        holdings.update({token: '20' for token in tokens})
    before = observation(ledger, clock, positions=holdings, cash='100' if example else '270.8')
    synchronize(ledger, baseline, before, anchor_mode='enrollment', funding='110' if example else '300')
    if withdraw:
        clock.value += timedelta(minutes=1)
        debit, native_debit = cash_activity(clock, 'WITHDRAWAL', withdraw)
        record_activity(ledger, debit, native_evidence=native_debit)
    if not example:
        clock.value += timedelta(minutes=1)
        source['timestamp'] = int(clock.now().timestamp())
        proof.update(rows=[source], rows_sha256=digest([source]))
        record_activity(ledger, source, native_evidence=proof)
    if deposit:
        clock.value += timedelta(minutes=1)
        credit, native_credit = cash_activity(clock, 'DEPOSIT', deposit)
        record_activity(ledger, credit, native_evidence=native_credit)
    if quarantine:
        clock.value += timedelta(minutes=1)
        book = CapitalBook(ledger)
        extra_cash = str(Decimal(book.expected_cash()) / 1_000_000 + quarantine)
        read = observation(ledger, clock, positions={'denver': '20', '90': '30'}, cash=extra_cash)
        synchronize(ledger, book.anchor, read, anchor_mode='session')
    clock.value += timedelta(minutes=1)
    from weather.market.lfc_campaign_closures import PROTOCOL
    ledger.record('autostart_enroll', state_id='state', identity_sha256='identity', state_root='state',
                  closure_anchor_protocol=PROTOCOL)
    ledger.record('autostart_claim', attempt_id=ATTEMPT, file_sha256='claim')
    ledger.record('session_start', session_id='end-band', protocol='lfc_autostart_v2',
                  condition_id=MARKET, autostart_attempt_id=ATTEMPT)
    clock.value += timedelta(seconds=6)
    ledger.record('session_end', session_id='end-band')
    book = CapitalBook(ledger)
    assert example or book.figures()['retained_gains_available_native'] > 0
    gross = 5_200_000 if example else GROSS
    cash_in, cash_out = ((0, gross + FEE) if side == 'BUY' else
                         (gross, FEE) if separate_fee else (gross - FEE, 0))
    cash = str(Decimal(book.expected_cash() + cash_in - cash_out) / 1_000_000)
    after = Decimal(owner_position) + (20 if side == 'BUY' else -20)
    read = observation(ledger, clock, positions={'denver': '20', **(personal_holdings or {}),
                                                **({'90': str(after)} if after > 0 else {})}, cash=cash)
    trade = owner_trade(clock, side, seconds=3)
    trade.update(market=FOREIGN, condition_id=FOREIGN, taker_order_id=ORDER)
    if example:
        trade['price'] = '.26'
    read['trades'].append(trade)
    receipt = trade_receipt(cash_in, cash_out, side=side, gross=gross)
    facts = build_facts(ledger, INCIDENT, INCIDENT_HASH, ATTEMPT, read, {TX: receipt})
    runtime = object.__new__(Runtime)
    runtime.state = SimpleNamespace(maker=MAKER)
    runtime.clock, runtime.task_enabled = clock, lambda: False
    return runtime, ledger, read, facts, receipt


def book_trade(runtime, ledger, read, facts):
    proof = live_proof(runtime, ledger, INCIDENT, INCIDENT_HASH, ATTEMPT, read, facts)
    ledger.record('autostart_owner_close', attempt_id=INCIDENT, incident_id=INCIDENT, source_attempt_id=ATTEMPT,
                  proof=proof, proof_sha256=digest(proof))
    return CapitalBook(Ledger.open(ledger.path, clock=runtime.clock.now)), proof['owner_external_close']


def finish_claim(ledger):
    from weather.market.lfc_campaign_closures import anchor

    state = AccountState(ledger.path.parent / 'test-postchecks', ledger)
    state.root.mkdir(parents=True)
    proof = {'authority': 'owner_operational_close', 'money_accounting_complete': True, 'cleanup_proven': True,
             'unknown_submit': False, 'ledger_head_sha256': ledger.previous}
    state.save('closed/' + ATTEMPT + '.json', {'attempt_id': ATTEMPT, 'proof': proof,
        'proof_sha256': digest(proof), 'closed_at_utc': ledger.clock().isoformat()})
    anchor(state, ATTEMPT)


@pytest.mark.parametrize('kind, funded', [('DEPOSIT', False), ('WITHDRAWAL', True), ('WITHDRAWAL', False),
                                         ('REDEEM', False), ('MERGE', False), ('REWARD', False)])
def test_between_session_activity_replays_and_reaches_next_cash_snapshot(tmp_path, monkeypatch, account_guard,
                                                                   kind, funded):
    from tests.market.test_lfc_redemption_native import event, log, BLOCK, TX as PROTOCOL_TX, word
    from weather.market.lfc_capital_native import result
    from weather.market.lfc_capital_reads import TYPES
    from weather.market.lfc_f2_cash_snapshot import context
    from weather.market.lfc_owner_close_activity import MERGE
    from weather.market.lfc_owner_external_close import GAP_SCHEMA, coverage, validate_retained_read
    from weather.market.lfc_redemption_native import BATCH, ZERO

    redemption, group, tokens = paired(auto=True)
    runtime, ledger, initial, facts, trade = fixture_trade(tmp_path, example=True, deposit=25 if funded else 0,
                                                           personal_holdings=dict.fromkeys(tokens, '30'))
    clock = runtime.clock
    clock.value += timedelta(minutes=1)
    when = int(clock.now().timestamp()) - 20
    positions = {row['asset']: row['size'] for row in initial['positions']}
    movements, main = [], []
    if kind in {'REDEEM', 'MERGE'}:
        positions.update(dict.fromkeys(tokens, '10'))
        cash = 20
        if kind == 'REDEEM':
            source = {**redemption, 'timestamp': when}
            main = [source]
        else:
            source = {**redemption, 'timestamp': when, 'type': 'MERGE', 'size': '20'}
            movements = [source]
            rows = [event(CTF, BATCH, [MAKER, MAKER, ZERO], ['uint256[]', 'uint256[]'],
                          [list(map(int, tokens)), [20_000_000] * 2], 0),
                    event(CTF, MERGE, [MAKER, ZERO, source['condition_id']], ['address', 'uint256[]', 'uint256'],
                          [ASSET, [1, 2], 20_000_000], 1), log(20_000_000, index=2)]
            group = {'transaction_hash': PROTOCOL_TX, 'receipt': rpc_packet({'transactionHash': PROTOCOL_TX,
                'blockHash': BLOCK, 'blockNumber': word(0x123), 'status': '0x1', 'logs': rows}), 'failure_type': None}
        group.update(rows=[source], rows_sha256=digest([source]))
    else:
        cash = -20 if kind == 'WITHDRAWAL' else 20
        source, group = cash_activity(clock, 'WITHDRAWAL' if cash < 0 else 'DEPOSIT', abs(cash), timestamp=when)
        source.update(type=kind, condition_id='', transaction_hash='0x' + '3' * 64)
        receipt = result(group['receipt'])
        receipt['transactionHash'] = source['transaction_hash']
        for row in receipt['logs']:
            row['transactionHash'] = source['transaction_hash']
        group.update(transaction_hash=source['transaction_hash'], rows=[source], rows_sha256=digest([source]),
                     receipt=rpc_packet(receipt))
        main = [source]
    tx = source['transaction_hash'].lower()
    final_cash = str(Decimal(initial['balances']['available_collateral']) + cash)
    read = observation(ledger, clock, positions=positions, cash=final_cash)
    read['trades'] = initial['trades']
    asset = read['capital_activity']['native_asset_proof']
    scope = read['capital_activity']['scope']
    read['capital_activity'] = {**read_activity(MAKER, scope['start'], scope['end'], types=TYPES,
        get=lambda *_: activity_page(main)), 'native_asset_proof': asset,
        'native_receipts': {tx: group} if main else {}}
    monkeypatch.setattr('weather.market.lfc_owner_external_close.read_protocol_movements', lambda wallet, anchor, cut:
        read_activity(wallet, anchor.timestamp(), cut.timestamp(), types=PROTOCOL_MOVEMENTS,
                      get=lambda *_: activity_page(movements)))
    monkeypatch.setattr('weather.market.lfc_owner_external_close.rpc_read', lambda _, args:
        trade if args == [TX] else group['receipt'])
    original = ledger.path.read_bytes(), ledger.previous
    if kind == 'DEPOSIT':
        overlap = deepcopy(read)
        conflicted = {**source, 'condition_id': MARKET}
        overlap['capital_activity'].update(read_activity(MAKER, scope['start'], scope['end'], types=TYPES,
                                                         get=lambda *_: activity_page([conflicted])))
        overlap['capital_activity']['native_receipts'][tx].update(rows=[conflicted], rows_sha256=digest([conflicted]))
        with pytest.raises(StateRefused, match='^owner_external_campaign_overlap$'):
            live_proof(runtime, ledger, INCIDENT, INCIDENT_HASH, ATTEMPT, overlap, facts)
        assert (ledger.path.read_bytes(), ledger.previous) == original
    proof = live_proof(runtime, ledger, INCIDENT, INCIDENT_HASH, ATTEMPT, read, facts)
    packet = proof['owner_external_close']
    assert packet['schema_version'] == GAP_SCHEMA
    validate_retained_read(ledger, packet, read, coverage(read))
    assert (ledger.path.read_bytes(), ledger.previous) == original
    count = len(ledger.rows)
    ledger.record('autostart_owner_close', attempt_id=INCIDENT, incident_id=INCIDENT, source_attempt_id=ATTEMPT,
                  proof=proof, proof_sha256=digest(proof))
    reopened = Ledger.open(ledger.path, clock=clock.now)
    book = CapitalBook(reopened)
    assert len(reopened.rows) == count + 1 and book.expected_cash() == int(Decimal(final_cash) * 1_000_000)
    assert len(book.personal_trades) == 1 and tx in book.activity_transactions.values()
    if kind == 'WITHDRAWAL':
        allocation, = (item for key, item in packet['owner_cash_allocation'].items() if key.startswith('activity-'))
        assert bool(allocation['owner_overdraw_created_native']) is not funded
        assert allocation['verified_owner_cash_used_native'] + allocation['owner_overdraw_created_native'] == 20_000_000
        assert book.owner_overdraw_outstanding == allocation['owner_overdraw_created_native']
        assert book.costs == 0
    elif kind == 'REWARD':
        assert book.incentives == 20_000_000
    else:
        assert book.verified_owner_cash == 24_400_000
    if kind in {'REDEEM', 'MERGE'}:
        assert [(item['token_id'], item['delta']) for item in book.owner_inventory_adjustments if
                item['token_id'] in tokens] == [(token, '-20') for token in sorted(tokens)]
    before = book.figures(), book.expected_cash(), book.personal_trades
    finish_claim(reopened)
    synchronize(reopened, book.inventory_anchor, read, anchor_mode='session', owner_fault_review=True)
    assert len(reopened.rows) == count + 4  # Decision, finalization intent/anchor, then session anchor.
    book = CapitalBook(Ledger.open(reopened.path, clock=clock.now))
    assert (book.figures(), book.expected_cash(), book.personal_trades) == before
    sample, evidence = cash_activity(clock, 'DEPOSIT', 1, timestamp=int(coverage(read).timestamp()))
    # Give this independent overlap probe a distinct identity from the close movement.
    receipt = result(evidence['receipt'])
    sample['transaction_hash'] = receipt['transactionHash'] = '0x' + '4' * 64
    for row in receipt['logs']:
        row['transactionHash'] = sample['transaction_hash']
    evidence.update(transaction_hash=sample['transaction_hash'], rows=[sample], rows_sha256=digest([sample]),
                    receipt=rpc_packet(receipt))
    sha = digest(evidence)
    book.native_groups[sha] = evidence
    assert context(book, read, [(sample, sha)])['personal_trade_sources'] == []


@pytest.mark.parametrize('role', ['MAKER', 'TAKER'])
def test_receipt_bound_trade_rejects_campaign_counterparty_on_later_read(
        tmp_path, monkeypatch, account_guard, role):
    from weather.market.lfc_f2_cash_snapshot import context, personal_net
    from weather.market.lfc_f2_inventory import make_anchor
    from weather.market.lfc_f2_personal_cash import receipt_bound_trade

    runtime, ledger, read, facts, receipt = fixture_trade(tmp_path)
    if role == 'MAKER':
        trade = owner_trade(runtime.clock, 'SELL', role=role, seconds=3)
        trade.update(market=FOREIGN, condition_id=FOREIGN, taker_order_id='0x'+'5'*64)
        trade['maker_orders'][0]['order_id'] = ORDER
        read['trades'][-1] = trade
        facts = build_facts(ledger, INCIDENT, INCIDENT_HASH, ATTEMPT, read, {TX: receipt})
    monkeypatch.setattr('weather.market.lfc_owner_external_close.rpc_read', lambda *_: receipt)
    book, _ = book_trade(runtime, ledger, read, facts)
    finish_claim(book.ledger)
    clean = make_anchor(book, read, kind='f2_session_anchor')
    cut = clean['snapshot_at_utc']
    assert clean['personal_trade_sources'] == []
    campaign_row = read['trades'][0]
    assert personal_net(book, [campaign_row], cut) == personal_net(book, read['trades'], cut) == 0

    second = int(utc(book.cash_reference['snapshot_at_utc']).timestamp())
    source, proof = cash_activity(runtime.clock, 'DEPOSIT', 1, timestamp=second)
    sha = digest(proof)
    book.native_groups[sha] = proof
    assert context(book, read, [(source, sha)])['personal_trade_sources'] == []

    mixed = deepcopy(read)
    row = mixed['trades'][-1]
    campaign_ids = book.ledger.our_order_ids()
    campaign_order = min(campaign_ids)
    if role == 'MAKER':
        row['taker_order_id'] = campaign_order
        part, size_key = row['maker_orders'][0], 'matched_amount'
    else:
        row['maker_orders'].append({'order_id': campaign_order, 'maker_address': '0x'+'9'*40})
        part, size_key = row, 'size'
    item, = book.personal_trades.values()
    before = ledger.path.read_bytes(), book.ledger.previous, book.figures(), book.expected_cash(), deepcopy(book.personal_trades)
    for readback in (
            lambda: make_anchor(book, mixed, kind='f2_session_anchor'),
            lambda: personal_net(book, mixed['trades'], cut),
            lambda: context(book, mixed, [(source, sha)]),
            lambda: receipt_bound_trade(item, row, part, ORDER, size_key, utc(row['matched_at']), MAKER,
                                        campaign_order_ids={order.lower() for order in campaign_ids})):
        with pytest.raises(CapitalRefused, match='^f2_personal_trade_changed$'):
            readback()
        assert (ledger.path.read_bytes(), book.ledger.previous, book.figures(), book.expected_cash(), book.personal_trades) == before


@pytest.mark.parametrize('separate_fee', [False, True])
@pytest.mark.parametrize('withdraw', [0, 4, 12])
def test_external_sale_protects_existing_campaign_gains_even_when_fee_has_its_own_transfer(
        tmp_path, monkeypatch, account_guard, separate_fee, withdraw):
    runtime, ledger, read, facts, receipt = fixture_trade(tmp_path, separate_fee=separate_fee, withdraw=withdraw)
    monkeypatch.setattr('weather.market.lfc_owner_external_close.rpc_read', lambda method, params: receipt)
    book = CapitalBook(ledger)
    before = book.figures()
    replay, packet = book_trade(runtime, ledger, read, facts)
    allocation, = packet['owner_cash_allocation'].values()
    repaid = min(withdraw * 1_000_000, GROSS - FEE)
    assert replay.owner_external_close_cash == GROSS - FEE
    assert replay.expected_cash() == book.expected_cash() + GROSS - FEE
    assert replay.owner_overdraw_outstanding == withdraw * 1_000_000 - repaid
    assert replay.owner_overdraw_repaid == allocation['owner_overdraw_repaid_native'] == repaid
    assert allocation['owner_cash_credited_native'] == GROSS - FEE - repaid
    for key in ('retained_gains_available_native', 'returned_principal_native', 'funding_native',
                'paid_or_reserved_campaign_costs_native', 'segregated_profit_native', 'segregated_incentives_native'):
        assert replay.figures()[key] == before[key]
    assert replay.external == before['segregated_external_cash_native'] + GROSS - FEE - repaid


@pytest.mark.parametrize('deposit', [0, 4, 20])
def test_external_buy_consumes_existing_verified_cash_then_records_overdraw(
        tmp_path, monkeypatch, account_guard, deposit):
    runtime, ledger, read, facts, receipt = fixture_trade(tmp_path, side='BUY', deposit=deposit, quarantine=25)
    monkeypatch.setattr('weather.market.lfc_owner_external_close.rpc_read', lambda method, params: receipt)
    before = CapitalBook(ledger)
    assert before.verified_owner_cash == deposit * 1_000_000
    assert before.external - before.verified_owner_cash == 25_000_000
    after, packet = book_trade(runtime, ledger, read, facts)
    debit = GROSS + FEE
    used = min(debit, before.verified_owner_cash)
    created = debit - used
    allocation, = packet['owner_cash_allocation'].values()
    assert allocation['verified_owner_cash_used_native'] == used
    assert allocation['owner_overdraw_created_native'] == after.owner_overdraw_outstanding == created
    assert after.external - after.verified_owner_cash == 25_000_000
    assert after.expected_cash() == before.expected_cash() - debit
    assert after.verified_owner_cash == before.verified_owner_cash - used
    for key in ('funding_native', 'headroom_native', 'retained_gains_available_native',
                'segregated_profit_native', 'paid_or_reserved_campaign_costs_native'):
        assert after.figures()[key] == before.figures()[key]
    assert after.figures() == CapitalBook(ledger).figures()


def test_audit_example_keeps_100_campaign_spendable(tmp_path, monkeypatch, account_guard):
    runtime, ledger, read, facts, receipt = fixture_trade(tmp_path, side='BUY', deposit=20, example=True)
    monkeypatch.setattr('weather.market.lfc_owner_external_close.rpc_read', lambda method, params: receipt)
    assert CapitalBook(ledger).expected_cash() == 120_000_000
    after, _ = book_trade(runtime, ledger, read, facts)
    assert after.expected_cash() == 114_000_000
    assert after.external == after.verified_owner_cash == 14_000_000
    after.gate(reserve='100', available_cash='114')
    with pytest.raises(CapitalRefused, match='capital_total_ceiling|capital_spendable_cash'):
        after.gate(reserve='100.000001', available_cash='114')


def test_later_native_owner_deposit_repays_buy_overdraw_then_stays_segregated(
        tmp_path, monkeypatch, account_guard):
    runtime, ledger, read, facts, receipt = fixture_trade(tmp_path, side='BUY')
    monkeypatch.setattr('weather.market.lfc_owner_external_close.rpc_read', lambda method, params: receipt)
    after, packet = book_trade(runtime, ledger, read, facts)
    debit = GROSS + FEE
    assert after.owner_overdraw_outstanding == debit
    runtime.clock.value += timedelta(minutes=1)
    credit, proof = cash_activity(runtime.clock, 'DEPOSIT', 20)
    record_activity(ledger, credit, native_evidence=proof)
    replay = CapitalBook(Ledger.open(ledger.path, clock=runtime.clock.now))
    assert replay.owner_overdraw_outstanding == 0
    assert replay.owner_overdraw_repaid == debit
    assert replay.external == replay.verified_owner_cash == 20_000_000 - debit
    assert replay.owner_close_allocations == packet['owner_cash_allocation']
    assert replay.figures()['retained_gains_available_native'] == after.figures()['retained_gains_available_native']


def include_trade(runtime, ledger, read, side, *, before_session=False):
    source = read['trades'][-1]
    runtime.clock.value += timedelta(seconds=8)
    trade = owner_trade(runtime.clock, side, seconds=2)
    tx, order = LATER_TX, '0x'+'b2'*32
    trade.update(id='other-'+side, market=FOREIGN, condition_id=FOREIGN, taker_order_id=order, transaction_hash=tx)
    if before_session:
        trade['matched_at'] = (utc(ledger.sessions['end-band']['start']['recorded_at_utc']) - timedelta(seconds=2)).isoformat()
    # The exact native fill improves the SDK price. Collateral and fee still match the chain byte for byte.
    trade['price'] = '.53' if side == 'BUY' else '.51'
    cash_in, cash_out = (0, GROSS + FEE) if side == 'BUY' else (GROSS - FEE, 0)
    cash = Decimal(read['balances']['available_collateral']) + Decimal(cash_in - cash_out) / 1_000_000
    read = observation(ledger, runtime.clock, positions={'denver': '20', '90': '70' if side == 'BUY' else '30'},
                       cash=str(cash))
    read['trades'].extend([source, trade])
    return read, trade_receipt(cash_in, cash_out, side=side, tx=tx, order=order)


@pytest.mark.parametrize(('side', 'deposit', 'before_session'), [
    ('BUY', 40, False), ('BUY', 0, False), ('SELL', 0, False), ('BUY', 40, True),
])
def test_external_trade_window_and_owner_allocation(tmp_path, monkeypatch, account_guard, side, deposit, before_session):
    runtime, ledger, read, facts, pinned = fixture_trade(tmp_path, side='BUY', deposit=deposit)
    read, later = include_trade(runtime, ledger, read, side, before_session=before_session)
    receipts = {TX: pinned, LATER_TX: later}
    monkeypatch.setattr('weather.market.lfc_owner_external_close.rpc_read', lambda method, params: receipts[params[0]])
    before = CapitalBook(ledger)
    after, packet = book_trade(runtime, ledger, read, facts)
    added, = packet['additional_trades']
    assert added['receipt']['gross_native'] == GROSS
    assert packet['facts_sha256'] == digest(facts)
    allocation = packet['owner_cash_allocation'][added['source']['trade_id']+'/'+added['source']['order_id']]
    if side == 'SELL':
        assert allocation['owner_overdraw_repaid_native'] == GROSS - FEE
        assert after.owner_overdraw_outstanding == 2*FEE
    elif deposit:
        assert allocation['verified_owner_cash_used_native'] == GROSS + FEE
        assert after.verified_owner_cash == before.verified_owner_cash - 2*(GROSS+FEE)
    else:
        assert allocation['owner_overdraw_created_native'] == GROSS + FEE
        assert after.owner_overdraw_outstanding == 2*(GROSS+FEE)
    assert after.figures()['retained_gains_available_native'] == before.figures()['retained_gains_available_native']


@pytest.mark.parametrize(('mutation', 'code'), [
    ('condition', 'owner_external_campaign_overlap'), ('token', 'owner_external_campaign_overlap'),
    ('unconfirmed', 'owner_external_trade_unconfirmed'), ('cap', 'owner_external_trade_cap'),
    ('worse_price', 'owner_external_proof_invalid'),
])
def test_extended_trade_refusals(tmp_path, monkeypatch, account_guard, mutation, code):
    runtime, ledger, read, facts, pinned = fixture_trade(tmp_path, side='BUY')
    read, later = include_trade(runtime, ledger, read, 'BUY')
    trade = read['trades'][-1]
    if mutation == 'condition':
        trade.update(market=MARKET, condition_id=MARKET)
    elif mutation == 'token':
        trade.update(token_id=next(iter(ledger.tokens())))
    elif mutation == 'unconfirmed':
        trade['status'] = 'MATCHED'
    elif mutation == 'cap':
        read['trades'].extend({**trade, 'id': f'leg-{i}', 'transaction_hash': f'0x{i+100:064x}'}
                              for i in range(MAX_TRADES-1))
    else:
        trade['price'] = '.51'
    receipts = {TX: pinned, LATER_TX: later}
    monkeypatch.setattr('weather.market.lfc_owner_external_close.rpc_read', lambda method, params: receipts[params[0]])
    before = ledger.path.read_bytes()
    with pytest.raises(StateRefused, match=code):
        live_proof(runtime, ledger, INCIDENT, INCIDENT_HASH, ATTEMPT, read, facts)
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize(('kind', 'code'), [('REDEEM', 'redemption'), ('DEPOSIT', 'transfer'), ('MERGE', 'merge')])
def test_owner_close_types_unsupported_movements(tmp_path, monkeypatch, account_guard, kind, code):
    runtime, ledger, read, facts, _ = fixture_trade(tmp_path, side='BUY')
    packet = read['capital_activity']
    end = packet['scope']['end']
    source = dict(proxy_wallet=MAKER, timestamp=end-2, condition_id=FOREIGN, type=kind,
                  size='1', usdc_size='1', token_id='90', transaction_hash='0x'+'fe'*32)
    get = lambda *_: activity_page([source])
    if kind == 'MERGE':
        monkeypatch.setattr('weather.market.lfc_owner_external_close.read_protocol_movements',
            lambda wallet, anchor, cut: read_activity(wallet, anchor.timestamp(), cut.timestamp(),
                                                      get=get, types=PROTOCOL_MOVEMENTS))
    else:
        observed = read_activity(MAKER, packet['scope']['start'], end, get=get)
        packet.update(observed)
    monkeypatch.setattr('weather.market.lfc_owner_external_close.rpc_read', lambda *_: pytest.fail('unexpected RPC'))
    before = ledger.path.read_bytes()
    with pytest.raises(StateRefused, match=f'owner_external_{code}_unhandled'):
        live_proof(runtime, ledger, INCIDENT, INCIDENT_HASH, ATTEMPT, read, facts)
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize('failure', ['geoblock', 'busy', 'launch_deferred'])
def test_owner_close_cli_failure_keeps_exit_nonzero(monkeypatch, capsys, failure):
    from weather.market import lfc_campaign_cli as cli

    error = {'geoblock': StateRefused('geoblock'), 'busy': cli.AdmissionBusy('busy'),
             'launch_deferred': cli.LaunchDeferred('launch_deferred')}[failure]

    def refuse(*args):
        raise error

    monkeypatch.setattr(cli, 'load_release', refuse)
    monkeypatch.setattr(cli, 'control_record', lambda *args, **kwargs: None)
    status = cli.main(['owner-close', '--release', 'fixture.json', '--release-sha256', 'x', '--incident', INCIDENT])
    assert status == 1
    expected = 'Location check failed. Retry once the connection is normal.'
    assert capsys.readouterr().out.splitlines().count(expected) == (1 if failure == 'geoblock' else 0)


@pytest.mark.parametrize('owner_position', ['20', '19.99995'])
def test_touched_omitted_zero_or_slightly_negative_projection_uses_native_balance(
        tmp_path, monkeypatch, account_guard, owner_position):
    runtime, ledger, read, facts, receipt = fixture_trade(tmp_path, owner_position=owner_position)
    monkeypatch.setattr('weather.market.lfc_owner_external_close.rpc_read', lambda *_: receipt)
    calls = []

    def block(number, timestamp):
        return rpc_packet({'number': hex(number), 'timestamp': hex(timestamp),
                           'hash': f'0x{number:064x}', 'parentHash': f'0x{number-1:064x}'})

    def checkpoints(wallet, anchor, cut, omitted, first_trade_block):
        assert wallet == MAKER and first_trade_block == 256
        assert omitted == {'90': (Decimal(owner_position), Decimal('-20'), CTF)}
        a, b = int(anchor.timestamp()), int(cut.timestamp())
        calls.append(1)
        return {'brackets': [[block(250, a), block(251, a+1)], [block(260, b), block(261, b+1)]],
                'balances': {'90': [rpc_packet(f'0x{20_000_008:064x}'), rpc_packet(f'0x{8:064x}')]}}

    monkeypatch.setattr('weather.market.lfc_owner_external_inventory.collect_checkpoints', checkpoints)
    after, packet = book_trade(runtime, ledger, read, facts)
    from weather.market.lfc_f2_inventory import expected_inventory
    inventory = expected_inventory(after.ledger, after.inventory_anchor, after)
    assert set(packet['native_inventory']['balances']) == {'90'} and calls == [1]
    assert Decimal(inventory['90']) == Decimal('0.000008')


@pytest.mark.parametrize('mode', ['pm_manual', 'pm_auto', 'ctf', 'pm_zero_payout'])
def test_omitted_redemption_checks_the_receipt_contract_at_both_cuts(tmp_path, monkeypatch, account_guard, mode):
    from io import BytesIO
    from weather.market.lfc_capital_native import result
    from weather.market.lfc_f2_inventory import expected_inventory
    from weather.market.lfc_owner_external_close import coverage, reconcile
    from weather.market.lfc_owner_external_inventory import BALANCE_SELECTOR
    from weather.market.lfc_redemption_native import PM
    from weather.market.re1_transport import RPC

    ctf = mode == 'ctf'
    source, group, tokens = paired(auto=mode == 'pm_auto', ctf=ctf)
    payout = 20
    if mode == 'pm_zero_payout':
        tokens, payout = tokens[-1:], 0
        receipt = result(group['receipt'])
        receipt['logs'] = receipt['logs'][3:6]
        group['receipt'] = rpc_packet(receipt)
        source.update(token_id=tokens[0], usdc_size='0')
    runtime, ledger, initial, facts, trade = fixture_trade(tmp_path, example=True,
                                                           personal_holdings=dict.fromkeys(tokens, '20'))
    clock = runtime.clock
    clock.value += timedelta(minutes=1)
    source['timestamp'] = int(clock.now().timestamp()) - 20
    group.update(rows=[source], rows_sha256=digest([source]))
    read = observation(ledger, clock, positions={row['asset']: row['size'] for row in initial['positions']
                                                if row['asset'] not in tokens},
                       cash=str(Decimal(initial['balances']['available_collateral']) + payout))
    read['trades'] = initial['trades']
    packet = read['capital_activity']
    scope = packet['scope']
    packet.update(read_activity(MAKER, scope['start'], scope['end'], get=lambda *_: activity_page([source])),
                  native_receipts={source['transaction_hash']: group})
    anchor_at = int(utc(CapitalBook(ledger).inventory_anchor['snapshot_at_utc']).timestamp())
    cut_at = int(coverage(read).timestamp())
    contract, other = (CTF, PM) if ctf else (PM, CTF)
    balances = {(target, int(token), height): 20_000_000 if target == contract and height == 250 else 0
                for token in tokens for target in (CTF, PM) for height in (250, 320)}
    calls = []

    def open_rpc(request, *, timeout):
        assert request.full_url == RPC
        body = json.loads(request.data)
        data, tag = body['params']
        if body['method'] == 'eth_getBlockByNumber':
            number = 350 if data == 'latest' else int(data, 16)
            stamp = (anchor_at + number - 250 if number <= 250 else
                     cut_at + number - 320 if number >= 320 else
                     anchor_at + (number - 250) * (cut_at - anchor_at) // 70)
            value = {'number': hex(number), 'timestamp': hex(stamp),
                     'hash': f'0x{number:064x}', 'parentHash': f'0x{max(0, number-1):064x}'}
        else:
            assert body['method'] == 'eth_call' and data['data'].startswith(BALANCE_SELECTOR)
            assert data['data'][10:74] == MAKER[2:].rjust(64, '0')
            key = data['to'], int(data['data'][74:], 16), int(tag, 16)
            calls.append(key)
            value = f'0x{balances[key]:064x}'
        response = BytesIO(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': value}).encode())
        response.status, response.geturl = 200, lambda: RPC
        return response

    monkeypatch.setattr('weather.market.lfc_capital_native.direct_opener', lambda: SimpleNamespace(open=open_rpc))
    monkeypatch.setattr('weather.market.lfc_owner_external_close.rpc_read', lambda *_: trade)
    before = ledger.path.read_bytes(), ledger.previous
    proof = live_proof(runtime, ledger, INCIDENT, INCIDENT_HASH, ATTEMPT, read, facts)
    assert (ledger.path.read_bytes(), ledger.previous) == before
    assert calls == [(contract, int(token), height) for token in sorted(tokens) for height in (250, 320)]
    external = proof['owner_external_close']
    with_wrong_contract = deepcopy(external)
    calls_for_token = with_wrong_contract['native_inventory']['balances'][tokens[0]]
    calls_for_token[0]['params'][0]['to'] = other
    with pytest.raises(StateRefused, match='^owner_external_native_inventory_binding$'):
        reconcile(CapitalBook(ledger), with_wrong_contract)
    legacy = deepcopy(external)
    legacy['native_inventory']['balances'] = {
        token: [entry['response'] for entry in pair] for token, pair in external['native_inventory']['balances'].items()}
    if ctf:
        reconcile(CapitalBook(ledger), legacy)  # Existing CTF witnesses retain their original meaning.
    else:
        with pytest.raises(StateRefused, match='^owner_external_native_inventory_binding$'):
            reconcile(CapitalBook(ledger), legacy)
    ledger.record('autostart_owner_close', attempt_id=INCIDENT, incident_id=INCIDENT, source_attempt_id=ATTEMPT,
                  proof=proof, proof_sha256=digest(proof))
    replay = CapitalBook(Ledger.open(ledger.path, clock=clock.now))
    positions = expected_inventory(replay.ledger, replay.inventory_anchor, replay)
    assert all(Decimal(positions[token]) == 0 for token in tokens)
    redeemed, = replay.redemptions.values()
    assert redeemed['cash_native'] == payout * 1_000_000


@pytest.mark.parametrize(('case', 'reason'), [
    ('unexplained_movement', 'owner_external_inventory_changed'),
    ('extra_execution', 'owner_external_proof_invalid'),
    ('late_execution', 'owner_external_trade_cut_retry'),
    ('campaign_condition', 'owner_external_campaign_overlap'),
    ('receipt_omits_fee', 'owner_external_cash_legs_changed'),
    ('changed_receipt_identity', 'owner_external_receipt_changed'),
    ('enabled_task', 'owner_external_requires_disabled_terminal_account'),
])
def test_external_close_refusal_preserves_ledger_bytes(tmp_path, monkeypatch, account_guard, case, reason):
    runtime, ledger, read, facts, receipt = fixture_trade(tmp_path)
    if case == 'unexplained_movement':
        read['positions'].append({'asset': '91', 'size': '0.000001'})
    elif case in ('extra_execution', 'late_execution'):
        extra = deepcopy(read['trades'][-1])
        extra.update(id='extra', transaction_hash='0x'+'2'*64, taker_order_id='0x'+'3'*64)
        if case == 'late_execution':
            extra['matched_at'] = runtime.clock.now().isoformat()
        read['trades'].append(extra)
    elif case == 'campaign_condition':
        row = read['trades'][-1]
        row.update(market=MARKET, condition_id=MARKET)
    elif case == 'receipt_omits_fee':
        receipt = trade_receipt(GROSS, 0)
    elif case == 'changed_receipt_identity':
        original = json.loads(receipt['raw_response'])
        original['result']['blockNumber'] = '0x101'
        for log in original['result']['logs']:
            log['blockNumber'] = '0x101'
        receipt = retained(json.dumps(original).encode())
    elif case == 'enabled_task':
        runtime.task_enabled = lambda: True
    monkeypatch.setattr('weather.market.lfc_owner_external_close.rpc_read', lambda method, params: receipt)
    before = ledger.path.read_bytes()
    with pytest.raises(StateRefused, match=reason):
        live_proof(runtime, ledger, INCIDENT, INCIDENT_HASH, ATTEMPT, read, facts)
    assert ledger.path.read_bytes() == before


def test_booked_owner_allocation_cannot_disagree_with_replay(tmp_path, monkeypatch, account_guard):
    runtime, ledger, read, facts, receipt = fixture_trade(tmp_path, side='BUY', deposit=20)
    monkeypatch.setattr('weather.market.lfc_owner_external_close.rpc_read', lambda method, params: receipt)
    proof = live_proof(runtime, ledger, INCIDENT, INCIDENT_HASH, ATTEMPT, read, facts)
    allocation, = proof['owner_external_close']['owner_cash_allocation'].values()
    allocation['verified_owner_cash_used_native'] -= 1
    before, head = ledger.path.read_bytes(), ledger.previous
    with pytest.raises(LedgerUnavailable, match='owner_external_cash_allocation_changed'):
        ledger.record('autostart_owner_close', attempt_id=INCIDENT, incident_id=INCIDENT, source_attempt_id=ATTEMPT,
                      proof=proof, proof_sha256=digest(proof))
    assert ledger.path.read_bytes() == before and ledger.previous == head


def test_only_unversioned_owner_close_rows_can_omit_allocation(tmp_path, monkeypatch, account_guard):
    runtime, ledger, read, facts, receipt = fixture_trade(tmp_path, side='BUY', deposit=20)
    monkeypatch.setattr('weather.market.lfc_owner_external_close.rpc_read', lambda method, params: receipt)
    proof = live_proof(runtime, ledger, INCIDENT, INCIDENT_HASH, ATTEMPT, read, facts)
    packet = proof['owner_external_close']
    assert packet['schema_version'] == PROOF_SCHEMA
    allocation, = packet.pop('owner_cash_allocation').values()
    before, head = ledger.path.read_bytes(), ledger.previous
    fields = dict(attempt_id=INCIDENT, incident_id=INCIDENT, source_attempt_id=ATTEMPT, proof=proof)
    with pytest.raises(LedgerUnavailable, match='owner_external_cash_allocation_missing'):
        ledger.record('autostart_owner_close', **fields, proof_sha256=digest(proof))
    assert ledger.path.read_bytes() == before and ledger.previous == head

    cash = CapitalBook(ledger).expected_cash()
    del packet['schema_version']
    ledger.record('autostart_owner_close', **fields, proof_sha256=digest(proof))
    replay = CapitalBook(Ledger.open(ledger.path, clock=runtime.clock.now))
    assert replay.expected_cash() == cash - GROSS - FEE
    assert replay.verified_owner_cash == 20_000_000 - GROSS - FEE
    assert next(iter(replay.owner_close_allocations.values())) == allocation


def owner_runtime(tmp_path, monkeypatch):
    runtime, ledger, read, facts, receipt = fixture_trade(tmp_path, side='BUY', deposit=20)
    state = AccountState(tmp_path / 'state', ledger)
    state.root.mkdir(parents=True)
    ledger.record('halt', reason='synthetic_incident')
    sha = state.save('incidents/' + INCIDENT + '.json', {'attempt_id': INCIDENT, 'source_attempt_id': ATTEMPT,
                      'artifact': 'private-proof', 'detection_sequence': 1})
    runtime.state, runtime.admission = state, nullcontext
    runtime.reload_ledger = lambda: ledger
    runtime.workload_path, runtime.hold_path = tmp_path / 'unused-marker', tmp_path / 'unused-hold'
    calls = []

    def read_account(*, persist):
        assert persist is False
        calls.append('account')
        return read

    def read_chain(method, params):
        assert (method, params) == ('eth_getTransactionReceipt', [TX])
        calls.append('chain')
        return receipt

    runtime.read_account = read_account
    monkeypatch.setattr('weather.market.lfc_owner_external_close.rpc_read', read_chain)
    monkeypatch.setattr('sys.stdin.isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda: 'close ' + sha[:12])
    return runtime, {**facts, 'incident_sha256': sha}, calls


def interrupted_partial(runtime, facts, monkeypatch):
    from weather.market.lfc_campaign_owner_close import owner_close
    ledger, root = runtime.state.ledger, runtime.state.root
    record = ledger.record

    def interrupted(event, **fields):
        if event == 'autostart_owner_close':
            raise OSError('interrupted after partial receipt')
        return record(event, **fields)

    with monkeypatch.context() as injection:
        injection.setattr(ledger, 'record', interrupted)
        with pytest.raises(OSError, match='interrupted after partial receipt'):
            owner_close(runtime, INCIDENT, external_facts=facts)
    return root / 'owner-closures' / (INCIDENT + '.json')


@pytest.mark.parametrize(('kind', 'direction'), [('WITHDRAWAL', 'OUT'), ('DEPOSIT', 'IN'), ('REWARD', 'IN'),
                                               ('TIP', 'IN'), ('TIP', 'OUT')])
def test_positive_cash_row_without_wallet_transfer_refuses_without_writes(tmp_path, monkeypatch, account_guard,
                                                                         kind, direction):
    from weather.market.lfc_campaign_owner_close import owner_close
    from weather.market.lfc_capital_native import result

    runtime, facts, _ = owner_runtime(tmp_path, monkeypatch)
    ledger, root = runtime.state.ledger, runtime.state.root
    partial = interrupted_partial(runtime, facts, monkeypatch)
    incident, seal = root / 'incidents' / (INCIDENT + '.json'), tmp_path / 'owner-closed-release.json'
    initial = runtime.read_account(persist=False)
    clock = runtime.clock
    clock.value += timedelta(minutes=1)
    later = observation(ledger, clock, positions={row['asset']: row['size'] for row in initial['positions']},
                        cash=initial['balances']['available_collateral'])
    later['trades'] = initial['trades']
    source, group = cash_activity(clock, 'WITHDRAWAL' if direction == 'OUT' else 'DEPOSIT', 1)
    tx = '0x' + '6' * 64
    source.update(type=kind, condition_id='', transaction_hash=tx, **({'side': direction} if kind == 'TIP' else {}))
    receipt = result(group['receipt'])
    receipt['transactionHash'] = tx
    for log in receipt['logs']:
        log['transactionHash'] = tx
        leg = 1 if direction == 'OUT' else 2
        log['topics'][leg] = f'0x{177:064x}'
    group.update(transaction_hash=tx, receipt=rpc_packet(receipt), rows=[source], rows_sha256=digest([source]))
    packet = later['capital_activity']
    scope = packet['scope']
    packet.update(read_activity(MAKER, scope['start'], scope['end'], get=lambda *_: activity_page([source])),
                  native_receipts={source['transaction_hash']: group})
    monkeypatch.setattr(runtime, 'read_account', lambda *, persist: later if not persist else pytest.fail('published'))

    def snapshot():
        opened = Ledger.open(ledger.path, clock=clock.now)
        book = CapitalBook(opened)
        return (opened.path.read_bytes(), opened.previous, book.pending_native_outgoing, book.figures(),
                book.expected_cash(), incident.read_bytes(), partial.read_bytes(), frozenset(root.rglob('*.json')))

    before = snapshot()
    for _ in range(2):
        with pytest.raises(StateRefused, match='^owner_external_activity_cash_unproved$'):
            if owner_close(runtime, INCIDENT, external_facts=facts) == 0:
                seal.write_text('unexpected close')
        assert snapshot() == before and not seal.exists()


@pytest.mark.parametrize('corruption', [None, 'nested_facts', 'occurrence', 'positions', 'allocation'])
def test_unanchored_partial_is_validated_before_any_append(tmp_path, monkeypatch, account_guard, corruption):
    from weather.market.lfc_campaign_owner_close import owner_close
    runtime, facts, calls = owner_runtime(tmp_path, monkeypatch)
    ledger, root = runtime.state.ledger, runtime.state.root
    partial = interrupted_partial(runtime, facts, monkeypatch)
    assert calls == ['account', 'chain']
    if corruption is not None:
        row = json.loads(partial.read_bytes())
        packet = row['proof']['owner_external_close']
        if corruption == 'nested_facts':
            packet['facts']['trades'][0]['source']['price'] = '0.01'
        elif corruption == 'occurrence':
            row['detection_sequence'] += 1
        elif corruption == 'positions':
            packet['positions']['90'] = '51'
        else:
            allocation, = packet['owner_cash_allocation'].values()
            allocation['owner_overdraw_created_native'] += 1
        partial.write_bytes(canonical_bytes(row))
    retained = partial.read_bytes()
    before, file_hash, head = ledger.path.read_bytes(), file_sha(ledger.path), ledger.previous
    assert ledger.halted and not ledger.event_rows('autostart_owner_close')
    figures = CapitalBook(ledger).figures()
    if corruption is None:
        if os.name == 'nt':
            record = ledger.record

            def check_sharing(event, **fields):
                if event == 'autostart_owner_close':
                    with pytest.raises(PermissionError):
                        partial.open('r+b').close()
                    with pytest.raises(PermissionError):
                        partial.rename(partial.with_suffix('.moved'))
                return record(event, **fields)

            monkeypatch.setattr(ledger, 'record', check_sharing)
        assert owner_close(runtime, INCIDENT, external_facts=facts) == 0
        assert calls == ['account', 'chain'] * 2
        decision, = ledger.event_rows('autostart_owner_close')
        assert decision['recovered_partial'] and not ledger.halted
        assert (root / 'closed' / (ATTEMPT + '.json')).is_file()
    else:
        with pytest.raises(StateRefused, match='owner_close_partial_binding|owner_external_facts_binding'):
            owner_close(runtime, INCIDENT, external_facts=facts)
        assert calls == ['account', 'chain']
        assert ledger.path.read_bytes() == before and file_sha(ledger.path) == file_hash
        assert ledger.previous == head and ledger.halted and not ledger.event_rows('autostart_owner_close')
        assert CapitalBook(ledger).figures() == figures
        assert not (root / 'closed' / (ATTEMPT + '.json')).exists()
    assert partial.read_bytes() == retained


@pytest.mark.parametrize('mutation', ['gone', 'different_file', 'identical_replacement', 'rewrite'])
def test_partial_change_during_fresh_proof_refuses_without_any_append(
        tmp_path, monkeypatch, account_guard, mutation):
    from weather.market.lfc_campaign_owner_close import owner_close
    runtime, facts, calls = owner_runtime(tmp_path, monkeypatch)
    ledger, root = runtime.state.ledger, runtime.state.root
    partial = interrupted_partial(runtime, facts, monkeypatch)
    original = partial.read_bytes()
    before, file_hash, head = ledger.path.read_bytes(), file_sha(ledger.path), ledger.previous
    figures = CapitalBook(ledger).figures()
    halts = ledger.event_rows('halt')
    account_read = runtime.read_account
    changed = original + b'\n'

    def read_after_mutation(*, persist):
        if mutation == 'gone':
            partial.unlink()
        elif mutation == 'rewrite':
            partial.write_bytes(changed)
        else:
            replacement = partial.with_suffix('.replacement')
            replacement.write_bytes(original if mutation == 'identical_replacement' else changed)
            replacement.replace(partial)
        return account_read(persist=persist)

    monkeypatch.setattr(runtime, 'read_account', read_after_mutation)
    with pytest.raises(StateRefused, match='owner_close_partial_binding'):
        owner_close(runtime, INCIDENT, external_facts=facts)
    assert calls == ['account', 'chain'] * 2
    assert ledger.path.read_bytes() == before and file_sha(ledger.path) == file_hash
    assert ledger.previous == head and CapitalBook(ledger).figures() == figures
    assert ledger.halted and ledger.event_rows('halt') == halts
    for event in ('autostart_owner_close', 'autostart_close', 'autostart_close_intent'):
        assert ledger.event_rows(event) == ()
    assert not (root / 'closed' / (ATTEMPT + '.json')).exists()
    if mutation == 'gone':
        assert not partial.exists()
    else:
        assert partial.read_bytes() == (original if mutation == 'identical_replacement' else changed)


def test_coordinator_finalization_reuses_commit_but_explicit_retry_rereads(tmp_path, monkeypatch, account_guard):
    from weather.market import lfc_campaign_owner_close as close
    runtime, facts, calls = owner_runtime(tmp_path, monkeypatch)
    ledger, root = runtime.state.ledger, runtime.state.root

    def interrupted(*args, **kwargs):
        raise OSError('interrupted after close commit')

    with monkeypatch.context() as injection:
        injection.setattr(close, 'complete_committed', interrupted)
        with pytest.raises(OSError, match='interrupted after close commit'):
            close.owner_close(runtime, INCIDENT, external_facts=facts)
    assert calls == ['account', 'chain']
    decision, = ledger.event_rows('autostart_owner_close')
    assert not (root / 'closed' / (ATTEMPT + '.json')).exists()
    # The coordinator's receipt-only helper accepts a state, with no runtime or
    # venue adapter. Removing live read capability must not block finalization.
    with monkeypatch.context() as no_reads:
        no_reads.setattr(runtime, 'read_account', lambda **_: pytest.fail('account read during finalization'))
        no_reads.setattr('weather.market.lfc_owner_external_close.rpc_read',
                         lambda *args: pytest.fail('chain read during finalization'))
        assert close.complete_committed(runtime.state, ATTEMPT, runtime.clock.now())
    assert ledger.event_rows('autostart_owner_close') == (decision,)
    with pytest.raises(StateRefused, match='owner_external_facts_required'):
        close.owner_close(runtime, INCIDENT)
    assert close.owner_close(runtime, INCIDENT, external_facts=facts) == 0
    assert calls == ['account', 'chain'] * 2
    assert ledger.event_rows('autostart_owner_close') == (decision,)
