"""Guards: incident-specific external facts, native fees and segregated owner cash."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_f2_capital import MAKER, filled
from tests.market.test_lfc_f2_inventory_b080 import fixture, observation
from tests.market.test_lfc_f2_personal_cash_b081 import account_guard, owner_trade
from tests.market.test_lfc_redemption_native import paired
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_campaign_state import StateRefused
from weather.market.lfc_capital import ASSET, CapitalBook, record_activity
from weather.market.lfc_capital_native import TRANSFER
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_owner_external_close import EXCHANGES, ORDER_FILLED, build_facts, live_proof
from weather.market.lfc_recording_io import retained
from weather.market.lfc_redemption_native import CTF, SINGLE
from weather.market.mm_stage2_hold import digest


ATTEMPT = 'a' * 32
INCIDENT = 'f' * 32
INCIDENT_HASH = 'f' * 64
MARKET = '0x' + 'c' * 64
FOREIGN = '0x' + 'e' * 64
ORDER = '0x' + 'd' * 64
TX = '0x' + '1' * 64
GROSS, FEE, SIZE = 10_400_000, 800_000, 20_000_000


def sale_receipt(cash_in, cash_out):
    wallet, other = f'0x{int(MAKER, 16):064x}', f'0x{9:064x}'
    fields = {'transactionHash': TX, 'blockNumber': '0x100', 'blockHash': '0x' + 'b' * 64}

    def move(index, send, receive, amount):
        return {**fields, 'address': ASSET, 'logIndex': hex(index), 'topics': [TRANSFER, send, receive],
                'data': f'0x{amount:064x}'}

    logs = [move(0, other, wallet, cash_in)]
    if cash_out:
        logs.append(move(1, wallet, other, cash_out))
    logs.extend([
        {**fields, 'address': CTF, 'logIndex': '0x2', 'topics': [SINGLE, other, wallet, other],
         'data': f'0x{90:064x}{SIZE:064x}'},
        {**fields, 'address': min(EXCHANGES), 'logIndex': '0x3', 'topics': [ORDER_FILLED, ORDER, wallet, other],
         'data': '0x' + ''.join(f'{n:064x}' for n in (1, 90, SIZE, GROSS, FEE, 0, 0))},
    ])
    return retained(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {**fields, 'status': '0x1', 'logs': logs}}).encode())


def fixture_sale(tmp_path, *, separate_fee=False):
    ledger, baseline, clock, _ = fixture(tmp_path, personal=False, bridge=False)
    source, proof, tokens = paired(auto=True)
    for idx, token in enumerate(tokens):
        filled(ledger, f'pair-{idx}', token=token, condition=source['condition_id'], price='.48')
    holdings = {'denver': '20', '90': '30', **{token: '20' for token in tokens}}
    before = observation(ledger, clock, positions=holdings, cash='270.8')
    synchronize(ledger, baseline, before, anchor_mode='enrollment')
    clock.value += timedelta(minutes=1)
    source['timestamp'] = int(clock.now().timestamp())
    proof.update(rows=[source], rows_sha256=digest([source]))
    record_activity(ledger, source, native_evidence=proof)
    clock.value += timedelta(minutes=1)
    ledger.record('autostart_enroll', state_id='state', identity_sha256='identity', state_root='state')
    ledger.record('autostart_claim', attempt_id=ATTEMPT, file_sha256='claim')
    ledger.record('session_start', session_id='end-band', protocol='lfc_autostart_v2',
                  condition_id=MARKET, autostart_attempt_id=ATTEMPT)
    clock.value += timedelta(seconds=6)
    ledger.record('session_end', session_id='end-band')
    book = CapitalBook(ledger)
    assert book.figures()['retained_gains_available_native'] > 0
    cash = str(Decimal(book.expected_cash() + GROSS - FEE) / 1_000_000)
    read = observation(ledger, clock, positions={'denver': '20', '90': '10'}, cash=cash)
    read['trades'].append(dict(owner_trade(clock, 'SELL', seconds=3), market=FOREIGN, condition_id=FOREIGN,
                               taker_order_id=ORDER))
    receipt = sale_receipt(GROSS, FEE) if separate_fee else sale_receipt(GROSS - FEE, 0)
    facts = build_facts(ledger, INCIDENT, INCIDENT_HASH, ATTEMPT, read, {TX: receipt})
    runtime = object.__new__(Runtime)
    runtime.state = SimpleNamespace(maker=MAKER)
    runtime.clock, runtime.task_enabled = clock, lambda: False
    return runtime, ledger, read, facts, receipt


@pytest.mark.parametrize('separate_fee', [False, True])
def test_external_sale_protects_existing_campaign_gains_even_when_fee_has_its_own_transfer(
        tmp_path, monkeypatch, account_guard, separate_fee):
    runtime, ledger, read, facts, receipt = fixture_sale(tmp_path, separate_fee=separate_fee)
    monkeypatch.setattr('weather.market.lfc_owner_external_close.rpc_read', lambda method, params: receipt)
    book = CapitalBook(ledger)
    before = book.figures()
    proof = live_proof(runtime, ledger, INCIDENT, INCIDENT_HASH, ATTEMPT, read, facts)
    ledger.record('autostart_owner_close', attempt_id=INCIDENT, incident_id=INCIDENT, source_attempt_id=ATTEMPT,
                  proof=proof, proof_sha256=digest(proof))
    replay = CapitalBook(Ledger.open(ledger.path, clock=runtime.clock.now))
    assert replay.owner_external_close_cash == GROSS - FEE
    assert replay.expected_cash() == book.expected_cash() + GROSS - FEE
    for key in ('retained_gains_available_native', 'returned_principal_native', 'funding_native',
                'owner_overdraw_outstanding_native', 'paid_or_reserved_campaign_costs_native',
                'segregated_profit_native', 'segregated_incentives_native'):
        assert replay.figures()[key] == before[key]
    assert replay.figures()['segregated_external_cash_native'] == before['segregated_external_cash_native'] + GROSS - FEE


@pytest.mark.parametrize(('case', 'reason'), [
    ('unexplained_movement', 'owner_external_inventory_changed'),
    ('extra_execution', 'owner_external_trade_set_changed'),
    ('late_execution', 'owner_external_trade_outside_cut'),
    ('campaign_condition', 'owner_external_campaign_overlap'),
    ('receipt_omits_fee', 'owner_external_cash_legs_changed'),
    ('changed_receipt_identity', 'owner_external_receipt_changed'),
    ('enabled_task', 'owner_external_requires_disabled_terminal_account'),
])
def test_external_close_refusal_preserves_ledger_bytes(tmp_path, monkeypatch, account_guard, case, reason):
    runtime, ledger, read, facts, receipt = fixture_sale(tmp_path)
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
        receipt = sale_receipt(GROSS, 0)
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
