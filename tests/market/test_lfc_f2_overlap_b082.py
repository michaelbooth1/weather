"""Guards: B082 W1-W6 late redemption coverage and read-bound owner quantities."""
from datetime import timedelta

import pytest

from tests.market.test_lfc_campaign import Clock
from tests.market.test_lfc_f2_capital import MAKER, NOW, activity, filled
from tests.market.test_lfc_f2_capital_reads import native_packet, packet, rpc_packet
from tests.market.test_lfc_f2_inventory_b080 import observation
from tests.market.test_lfc_redemption_native import paired
from weather.market.lfc_capital import CapitalBook, CapitalRefused
from weather.market.lfc_capital_reads import read_activity, synchronize
from weather.market.lfc_f2_breadth import PROTOCOL
from weather.market.lfc_f2_inventory import ACTIVITY_OVERLAP_SECONDS, activity_start
from weather.market.lfc_f2_wallet_reads import collect_window
from weather.market.lfc_ledger import Ledger, take_baseline, write_baseline
from weather.market.mm_stage2_hold import digest


def wallet(tmp_path, *, campaign=True, personal=True, enroll=True):
    source, proof, tokens = paired(auto=True)
    clock = Clock()
    clock.value = NOW
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=clock.now, maker_address=MAKER)
    owner = {tokens[1]: '20'} if campaign else {token: '20' for token in tokens}
    if not personal:
        owner = {}
    baseline = take_baseline(label='t40', now=clock.now(), maker_address=MAKER,
        positions=[{'asset': token, 'size': value, 'conditionId': source['condition_id']} for token, value in owner.items()],
        open_orders=[], available_collateral='300')
    write_baseline(tmp_path, baseline, ledger)
    token = tokens[0] if campaign else 'denver'
    filled(ledger, 'f0', token=token, condition=source['condition_id'] if campaign else 'denver-condition')
    positions = {token: '20', **owner}
    if enroll:
        synchronize(ledger, baseline, observation(ledger, clock, positions=positions, cash='290'), anchor_mode='enrollment')
    clock.value += timedelta(days=1)
    return ledger, baseline, clock, source, proof, tokens, token


def feed(ledger, clock, source, proof, positions, cash):
    read = observation(ledger, clock, positions=positions, cash=cash)
    since = activity_start(ledger, read['started_at_utc'])
    raw = read_activity(MAKER, since, int(clock.now().timestamp()),
        get=lambda _, params: packet([source] if params['start'] <= source['timestamp'] <= params['end'] else []),
        sleep=lambda _: None)
    read['capital_activity'] = {**native_packet(raw), 'native_receipts':
        {source['transaction_hash']: proof} if raw['rows'] else {}}
    return read


@pytest.mark.parametrize('reopen', [False, True])
@pytest.mark.parametrize('lag', [1, 20, 600])
@pytest.mark.parametrize('enrollment', [False, True])
def test_w1_w6_campaign_redemption_indexed_after_anchor(tmp_path, reopen, lag, enrollment):
    ledger, baseline, clock, source, proof, tokens, token = wallet(tmp_path, enroll=not enrollment)
    source['timestamp'] = int(clock.now().timestamp()) - lag
    proof.update(rows=[source], rows_sha256=digest([source]))
    stale = observation(ledger, clock, positions={part: '20' for part in tokens}, cash='310')
    synchronize(ledger, CapitalBook(ledger).inventory_anchor or baseline, stale,
                anchor_mode='enrollment' if enrollment else 'session')
    if reopen:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    anchor = CapitalBook(ledger).inventory_anchor
    clock.value += timedelta(seconds=90)
    after = feed(ledger, clock, source, proof, {}, '310')
    assert after['capital_activity']['rows'] == [source]
    result = synchronize(ledger, anchor, after)
    book = CapitalBook(ledger)
    assert result['cash_bridge_complete'] and result['inventory']['changed'] == []
    assert book.expected_cash() == 310_000_000 and book.external == 0
    assert book.profit == 10_000_000 and book.returned_principal == 10_000_000
    assert book.figures()['funding_native'] == 300_000_000
    before = ledger.path.read_bytes()
    assert synchronize(ledger, anchor, after) == result
    assert ledger.path.read_bytes() == before
    clock.value += timedelta(seconds=1)
    fresh = feed(ledger, clock, source, proof, {}, '310')
    synchronize(ledger, anchor, fresh)
    assert ledger.path.read_bytes() == before
    replay = CapitalBook(Ledger.open(ledger.path, clock=clock.now))
    assert replay.figures() == book.figures()
    assert ACTIVITY_OVERLAP_SECONDS >= 900


@pytest.mark.parametrize('reopen', [False, True])
@pytest.mark.parametrize('previously_held,fresh', [(True, False), (False, False), (True, True)])
def test_w2_w3_w4_personal_late_rows_reconcile_in_live_proof(tmp_path, reopen, previously_held, fresh):
    ledger, baseline, clock, source, proof, tokens, token = wallet(tmp_path, campaign=False, personal=previously_held)
    source['timestamp'] = int(clock.now().timestamp()) - 20
    proof.update(rows=[source], rows_sha256=digest([source]))
    positions = {token: '20', **({} if fresh else {part: '20' for part in tokens})}
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
                observation(ledger, clock, positions=positions, cash='310'), anchor_mode='session')
    if reopen:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    anchor = CapitalBook(ledger).inventory_anchor
    attempt = 'a' * 32
    ledger.record('session_start', session_id='active', protocol=PROTOCOL, autostart_attempt_id=attempt)
    clock.value += timedelta(seconds=90)
    after = feed(ledger, clock, source, proof, {token: '20'}, '310')
    after['terminal_orders'] = {}
    result = synchronize(ledger, anchor, after, live_proof={'attempt_id': attempt})
    assert result['inventory']['changed'] == [] and result['cash_bridge_complete']
    book = CapitalBook(ledger)
    assert book.profit == 0 and book.external == 20_000_000
    from weather.market.lfc_capital_income import unknown_cash
    assert unknown_cash(book)['blockers'] == []
    assert book.figures()['funding_native'] == 300_000_000
    ledger.record('session_end', session_id='active')
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == book.figures()
    clock.value += timedelta(seconds=1)
    next_read = feed(ledger, clock, source, proof, {token: '20'}, '310')
    assert synchronize(ledger, anchor, next_read, anchor_mode='session')['inventory']['changed'] == []


def test_w5_fresh_campaign_shortfall_cannot_advance_anchor(tmp_path):
    ledger, baseline, clock, source, proof, tokens, token = wallet(tmp_path)
    source['timestamp'] = int(clock.now().timestamp()) - 20
    proof.update(rows=[source], rows_sha256=digest([source]))
    before = ledger.path.read_bytes()
    with pytest.raises(CapitalRefused, match='capital_inventory_unreconciled'):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor,
                    observation(ledger, clock, positions={}, cash='310'), anchor_mode='session')
    assert ledger.path.read_bytes() == before
    clock.value += timedelta(seconds=90)
    after = feed(ledger, clock, source, proof, {}, '310')
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, after, anchor_mode='session')['cash_bridge_complete']


def test_pre_enrollment_owner_history_uses_no_receipt_budget(tmp_path, monkeypatch):
    from weather.market import lfc_capital_native
    ledger, baseline, clock, source, proof, tokens, token = wallet(tmp_path, enroll=False)
    rows = []
    for number in range(250):
        row = activity(cash='1', token='personal-' + str(number), tx='old-' + str(number))
        row.update(condition_id='unrelated', timestamp=int(clock.now().timestamp()) - 20)
        rows.append(row)
    read = observation(ledger, clock, positions={part: '20' for part in tokens}, cash='302')
    raw = read_activity(MAKER, read['capital_activity']['scope']['start'], int(clock.now().timestamp()),
                        get=lambda *a: packet(rows), sleep=lambda _: None)
    requests = []
    real = lfc_capital_native.collect
    def rpc(method, params):
        requests.append(method)
        assert method != 'eth_getTransactionReceipt'
        return rpc_packet('0x89' if method == 'eth_chainId' else '0x6')
    monkeypatch.setattr(lfc_capital_native, 'collect', lambda value, ledger: real(value, ledger=ledger, rpc=rpc, sleep=lambda _: None))
    read['capital_activity'] = collect_window(raw, ledger=ledger)
    result = synchronize(ledger, baseline, read, anchor_mode='enrollment')
    assert result['funding_native'] == 300_000_000 and result['cash_bridge_complete']
    assert not CapitalBook(ledger).activities
    assert 'eth_getTransactionReceipt' not in requests


def test_known_overlap_receipt_is_cached_and_writes_nothing(tmp_path, monkeypatch):
    from weather.market import lfc_capital_native
    ledger, baseline, clock, source, proof, tokens, token = wallet(tmp_path)
    source['timestamp'] = int(clock.now().timestamp()) - 20
    proof.update(rows=[source], rows_sha256=digest([source]))
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={part: '20' for part in tokens}, cash='310'), anchor_mode='session')
    clock.value += timedelta(seconds=90)
    after = feed(ledger, clock, source, proof, {}, '310')
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, after)
    raw_bytes = ledger.path.read_bytes()
    calls = []
    real = lfc_capital_native.collect
    def rpc(method, params):
        calls.append(method)
        assert method != 'eth_getTransactionReceipt'
        return rpc_packet('0x89' if method == 'eth_chainId' else '0x6')
    monkeypatch.setattr(lfc_capital_native, 'collect', lambda value, ledger: real(value, ledger=ledger, rpc=rpc, sleep=lambda _: None))
    after['capital_activity'] = collect_window(after['capital_activity'], ledger=ledger)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, after)
    assert ledger.path.read_bytes() == raw_bytes
    assert 'eth_getTransactionReceipt' not in calls


def test_two_same_transaction_rows_straddling_anchor_apply_payout_once(tmp_path):
    from copy import deepcopy
    ledger, baseline, clock, source, proof, tokens, token = wallet(tmp_path)
    source['timestamp'] = int(clock.now().timestamp()) - 20
    first, second = deepcopy(source), deepcopy(source)
    first.update(token_id=tokens[0], size='20', outcome_index=0)
    second.update(token_id=tokens[1], size='20', outcome_index=1, usdc_size='0')
    proof.update(rows=[first], rows_sha256=digest([first]))
    initial = feed(ledger, clock, first, proof, {}, '310')
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, initial, anchor_mode='session')
    before = CapitalBook(ledger).figures()
    clock.value += timedelta(seconds=90)
    later = observation(ledger, clock, positions={}, cash='310')
    raw = read_activity(MAKER, later['capital_activity']['scope']['start'], int(clock.now().timestamp()),
                        get=lambda *a: packet([first, second]), sleep=lambda _: None)
    full_proof = {**proof, 'rows': [first, second], 'rows_sha256': digest([first, second])}
    later['capital_activity'] = {**native_packet(raw), 'native_receipts': {source['transaction_hash']: full_proof}}
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, later)
    after = CapitalBook(ledger).figures()
    assert {key: value for key, value in after.items() if key != 'redemptions'} == {
        key: value for key, value in before.items() if key != 'redemptions'}
    from weather.market.lfc_capital import normalize_activity
    assert after['redemptions'] == before['redemptions'] + [{
        'activity_id': normalize_activity(second, full_proof)['id'], 'cash_native': 0,
        'cost_basis_released_native': 0, 'returned_principal_native': 0,
        'duplicate_of': before['redemptions'][0]['activity_id'], 'outside_campaign': True}]
    assert len(CapitalBook(ledger).allocations) == 1
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == after


def test_credit_between_position_and_cash_components_is_captured_once(tmp_path):
    ledger, baseline, clock, source, proof, tokens, token = wallet(tmp_path)
    first = clock.now()
    source['timestamp'] = int(first.timestamp()) + 1
    proof.update(rows=[source], rows_sha256=digest([source]))
    stale = observation(ledger, clock, positions={part: '20' for part in tokens}, cash='310')
    clock.value += timedelta(seconds=2)
    stale['component_times']['balances'] = {'started_at_utc': clock.now().isoformat(), 'ended_at_utc': clock.now().isoformat()}
    stale['ended_at_utc'] = clock.now().isoformat()
    stale['capital_activity'] = native_packet(read_activity(MAKER, stale['capital_activity']['scope']['start'],
        int(clock.now().timestamp()), get=lambda *a: packet(), sleep=lambda _: None))
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, stale, anchor_mode='session')
    clock.value += timedelta(seconds=90)
    after = feed(ledger, clock, source, proof, {}, '310')
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, after)
    assert result['cash_bridge_complete'] and result['inventory']['changed'] == []
    assert CapitalBook(ledger).expected_cash() == 310_000_000
