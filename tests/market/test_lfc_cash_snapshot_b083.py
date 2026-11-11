"""Guards: B083 uncertain event seconds and personal-only quantity catch-up."""
from copy import deepcopy
from datetime import timedelta

import pytest

from tests.market.test_lfc_f2_overlap_b082 import wallet, feed
from tests.market.test_lfc_f2_cash_mirror_b082 import profitable_wallet, cash_activity, observed, single_redemption
from tests.market.test_lfc_f2_capital import filled, MAKER
from tests.market.test_lfc_f2_inventory_b080 import observation
from tests.market.test_lfc_f2_capital_reads import native_packet, packet
from weather.market.lfc_campaign import TransientPrecheck
from weather.market.lfc_capital import CapitalBook, CapitalRefused
from weather.market.lfc_capital_reads import read_activity, synchronize
from weather.market.lfc_ledger import Ledger
from weather.market.mm_stage2_hold import digest


@pytest.mark.parametrize('reopen', [False, True])
def test_same_second_captured_credit_relabels_only_existing_cash(tmp_path, reopen):
    ledger, _, clock, source, proof, tokens, _ = wallet(tmp_path)
    second = clock.now()
    clock.value += timedelta(microseconds=250000)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={token: '20' for token in tokens}, cash='310'), anchor_mode='session')
    source['timestamp'] = int(second.timestamp())
    proof.update(rows=[source], rows_sha256=digest([source]))
    if reopen:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    clock.value += timedelta(seconds=2)
    read = feed(ledger, clock, source, proof, {}, '310')
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read)['cash_bridge_complete']
    book = CapitalBook(ledger)
    assert book.expected_cash() == 310_000_000 and book.external == 0
    assert book.figures()['retained_gains_available_native'] == 10_000_000
    assert list(book.cash_capture_bindings.values())[-1]['captured'] is True
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == book.figures()


@pytest.mark.parametrize('reopen', [False, True])
def test_unexplained_same_second_cash_defers_then_accepts_later_complete_read(tmp_path, reopen):
    ledger, _, clock, source, proof, tokens, _ = wallet(tmp_path)
    second = clock.now()
    clock.value += timedelta(microseconds=250000)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={token: '20' for token in tokens}, cash='290'), anchor_mode='session')
    source['timestamp'] = int(second.timestamp())
    proof.update(rows=[source], rows_sha256=digest([source]))
    clock.value += timedelta(seconds=2)
    with pytest.raises(TransientPrecheck, match='capital_cash_snapshot_pending'):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, feed(ledger, clock, source, proof, {}, '300'))
    assert not CapitalBook(ledger).activities
    assert CapitalBook(ledger).figures()['retained_gains_available_native'] == 0
    if reopen:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    clock.value += timedelta(seconds=1)
    read = feed(ledger, clock, source, proof, {}, '310')
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read)['cash_bridge_complete']
    assert CapitalBook(ledger).expected_cash() == 310_000_000


@pytest.mark.parametrize('captured', [False, True])
def test_same_second_debit_never_consumes_gains_twice(tmp_path, captured):
    ledger, clock = profitable_wallet(tmp_path)
    second = clock.now()
    clock.value += timedelta(microseconds=250000)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={'103': '20'}, cash='323' if captured else '373'), anchor_mode='session')
    source, proof = cash_activity(clock, 'WITHDRAWAL', '50', timestamp=int(second.timestamp()))
    clock.value += timedelta(seconds=2)
    read = observed(ledger, clock, source, proof, '323')
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read)['cash_bridge_complete']
    book = CapitalBook(ledger)
    assert book.expected_cash() == 323_000_000
    assert book.figures()['retained_gains_available_native'] == 33_000_000
    assert book.external == 0 and list(book.cash_capture_bindings.values())[-1]['captured'] is captured
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == book.figures()


def test_two_equal_same_second_receipts_require_a_unique_explanation(tmp_path):
    ledger, _, clock, first, first_proof, tokens, _ = wallet(tmp_path)
    filled(ledger, 'second-lot', token='203', condition='0x'+'6'*64)
    second, second_proof = single_redemption('203', '20', '20', '0x'+'e'*64, '0x'+'6'*64)
    stamp = clock.now()
    clock.value += timedelta(microseconds=250000)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={**{token: '20' for token in tokens}, '203': '20'}, cash='280'),
        anchor_mode='session')
    for row, proof in ((first, first_proof), (second, second_proof)):
        row['timestamp'] = int(stamp.timestamp())
        proof.update(rows=[row], rows_sha256=digest([row]))
    def read(cash):
        result = observation(ledger, clock, positions={}, cash=cash)
        raw = read_activity(MAKER, result['capital_activity']['scope']['start'], int(clock.now().timestamp()),
                            get=lambda *a: packet([first, second]), sleep=lambda _: None)
        result['capital_activity'] = {**native_packet(raw), 'native_receipts': {
            first['transaction_hash']: first_proof, second['transaction_hash']: second_proof}}
        return result
    clock.value += timedelta(seconds=2)
    with pytest.raises(TransientPrecheck, match='capital_cash_snapshot_pending'):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read('300'))
    assert not CapitalBook(ledger).activities
    clock.value += timedelta(seconds=1)
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read('320'))['cash_bridge_complete']
    book = CapitalBook(ledger)
    assert book.expected_cash() == 320_000_000
    assert book.figures()['funding_native'] == 300_000_000
    raw = ledger.path.read_bytes()
    synchronize(ledger, book.inventory_anchor, read('320'))
    assert ledger.path.read_bytes() == raw
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == book.figures()


def test_personal_catchup_cannot_hide_a_campaign_token_or_replay_cash(tmp_path):
    ledger, _, clock, source, proof, tokens, campaign = wallet(tmp_path, campaign=False)
    source['timestamp'] = int(clock.now().timestamp())-20
    proof.update(rows=[source], rows_sha256=digest([source]))
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={campaign: '20', **{token: '20' for token in tokens}}, cash='310'),
        anchor_mode='session')
    clock.value += timedelta(seconds=2)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        feed(ledger, clock, source, proof, {campaign: '20', **{token: '10' for token in tokens}}, '310'))
    before = CapitalBook(ledger)
    clock.value += timedelta(seconds=2)
    with pytest.raises(CapitalRefused, match='capital_inventory_unreconciled'):
        synchronize(ledger, before.inventory_anchor, feed(ledger, clock, source, proof, {}, '310'))
    book = CapitalBook(ledger)
    assert book.cash_in == before.cash_in and book.external == before.external and book.profit == 0
    rows = ledger.event_rows('capital_owner_inventory')
    assert rows and all(row['token_id'] != campaign for row in rows)
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == book.figures()


@pytest.mark.parametrize('captured', [False, True])
@pytest.mark.parametrize('reopen', [False, True])
def test_enrollment_snapshot_uses_component_time_not_receipt_completion(tmp_path, captured, reopen):
    ledger, baseline, clock, source, proof, tokens, _ = wallet(tmp_path, enroll=False)
    second = clock.now()
    clock.value += timedelta(microseconds=250000)
    first = observation(ledger, clock, positions={token: '20' for token in tokens},
                        cash='310' if captured else '290')
    clock.value += timedelta(seconds=2)
    first['ended_at_utc'] = clock.now().isoformat()
    synchronize(ledger, baseline, first, anchor_mode='enrollment')
    source['timestamp'] = int(second.timestamp())
    proof.update(rows=[source], rows_sha256=digest([source]))
    if reopen:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    clock.value += timedelta(seconds=1)
    read = feed(ledger, clock, source, proof, {}, '310')
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read)['cash_bridge_complete']
    book = CapitalBook(ledger)
    assert book.expected_cash() == 310_000_000
    assert book.figures()['funding_native'] == 300_000_000 and book.external == 0
    assert book.figures()['retained_gains_available_native'] == 10_000_000
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == book.figures()


@pytest.mark.parametrize('after_append', [False, True])
def test_personal_catchup_crash_replays_quantity_without_cash(tmp_path, monkeypatch, after_append):
    ledger, _, clock, source, proof, tokens, campaign = wallet(tmp_path, campaign=False)
    source['timestamp'] = int(clock.now().timestamp())-20
    proof.update(rows=[source], rows_sha256=digest([source]))
    stale = {campaign: '20', **{token: '20' for token in tokens}}
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions=stale, cash='310'), anchor_mode='session')
    clock.value += timedelta(seconds=2)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, feed(ledger, clock, source, proof, stale, '310'))
    before = CapitalBook(ledger).figures()
    clock.value += timedelta(seconds=2)
    read = feed(ledger, clock, source, proof, {campaign: '20'}, '310')
    original = ledger.record
    def crash(event, **fields):
        if event == 'capital_owner_inventory':
            if after_append:
                original(event, **fields)
            raise OSError('synthetic quantity catchup interruption')
        return original(event, **fields)
    monkeypatch.setattr(ledger, 'record', crash)
    with pytest.raises(OSError, match='synthetic quantity catchup interruption'):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read)
    ledger = Ledger.open(ledger.path, clock=clock.now)
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read)['cash_bridge_complete']
    assert CapitalBook(ledger).figures() == before
    rows = ledger.event_rows('capital_owner_inventory')
    assert len(rows) == len(tokens)
    assert sum(int(row['before'])-int(row['after']) for row in rows) == 20*len(tokens)


def test_unapplied_native_outflow_blocks_peer_reserves_until_accounted(tmp_path):
    ledger, clock = profitable_wallet(tmp_path)
    source, proof = cash_activity(clock, 'WITHDRAWAL', '50')
    ledger.record('capital_native_group', proof=proof, proof_sha256=digest(proof))
    with pytest.raises(CapitalRefused, match='capital_cash_snapshot_pending'):
        CapitalBook(ledger).gate(reserve='19.6', available_cash='373', loss_basis='net_of_retained_gains')
    assert not ledger.unacknowledged_intents()
    read = observed(ledger, clock, source, proof, '323')
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read)['cash_bridge_complete']
    book = CapitalBook(ledger)
    assert not book.pending_native_outgoing
    book.gate(reserve='19.6', available_cash='323', loss_basis='net_of_retained_gains')
    assert book.figures()['retained_gains_available_native'] == 33_000_000


def test_cached_pre_enrollment_outflow_retries_outside_current_window(tmp_path, monkeypatch):
    from weather.market import lfc_capital_native
    from weather.market.lfc_f2_wallet_reads import collect_window, pending_rows
    from tests.market.test_lfc_f2_capital_reads import rpc_packet
    ledger, baseline, clock, _, _, tokens, _ = wallet(tmp_path, enroll=False)
    source, proof = cash_activity(clock, 'WITHDRAWAL', '50', timestamp=int(clock.now().timestamp()))
    ledger.record('capital_native_group', proof=proof, proof_sha256=digest(proof))
    assert pending_rows(ledger) == [source]
    clock.value += timedelta(hours=1)
    read = observation(ledger, clock, positions={token: '20' for token in tokens}, cash='290')
    assert source['timestamp'] < read['capital_activity']['scope']['start']
    original = lfc_capital_native.collect
    def rpc(method, params):
        assert method != 'eth_getTransactionReceipt'
        return rpc_packet('0x89' if method == 'eth_chainId' else '0x6')
    monkeypatch.setattr(lfc_capital_native, 'collect', lambda packet, ledger:
        original(packet, ledger=ledger, rpc=rpc, sleep=lambda _: None))
    read['capital_activity'] = collect_window(read['capital_activity'], ledger=ledger)
    result = synchronize(ledger, baseline, read, anchor_mode='enrollment')
    assert result['cash_bridge_complete'] and result['funding_native'] == 300_000_000
    assert not CapitalBook(ledger).pending_native_outgoing and pending_rows(ledger) == []


def test_cash_snapshot_deferral_is_visible_and_not_clean(tmp_path):
    from weather.market.lfc_campaign_control import control_record, watch_status
    from tests.market.test_lfc_campaign import NOW
    row = control_record(tmp_path, 'a'*32, phase='DEFERRED', now=NOW, reason='capital_cash_snapshot_pending')
    assert row['reason'] == 'capital_cash_snapshot_pending'
    assert watch_status(row, now=NOW)[1] == 1
