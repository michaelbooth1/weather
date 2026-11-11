"""Guards: no redemption may fall between two complete anchored read windows."""
from datetime import timedelta
from types import SimpleNamespace
import pytest

from tests.market.test_lfc_f2_inventory_b080 import fixture, observation
from tests.market.test_lfc_f2_capital import activity, MAKER
from tests.market.test_lfc_f2_capital_reads import native_packet, packet
from weather.market.lfc_capital import CapitalBook, CapitalRefused
from weather.market.lfc_capital_reads import read_activity, synchronize
from weather.market.lfc_f2_inventory import activity_start
from weather.market.lfc_f2_wallet_reads import pending_rows
from weather.market.lfc_ledger import Ledger


def test_real_account_read_can_finish_after_its_last_activity_cutoff(tmp_path, monkeypatch):
    from weather.market import re1_transport, lfc_campaign_runtime, lfc_capital_reads, lfc_f2_wallet_reads
    from weather.market.lfc_campaign_runtime import Runtime
    from weather.market.lfc_f2_pinb import example_policy
    from weather.market.lfc_recording_io import write_new
    ledger, _, clock, original = fixture(tmp_path, personal=False)
    clock.value += timedelta(days=1)
    path = tmp_path/'campaign.json'; write_new(path, example_policy())
    runtime = object.__new__(Runtime)
    runtime.state = SimpleNamespace(ledger=ledger, maker=MAKER, policy_binding={})
    runtime.clock, runtime.policy_path = clock, path
    world = {'redeemed': False, 'rows': []}
    class Venue:
        def __init__(self, *a, **k): pass
        def open_orders(self): return []
        def trades(self): return original['trades']
        def balances(self): return observation(ledger, clock, positions={}, cash='310' if world['redeemed'] else '290')['balances']
        def geography(self): return {'blocked': False}
        def close(self): pass
    monkeypatch.setattr(re1_transport, 'load_owner_credentials', lambda _: ({'FUNDER_ADDRESS': MAKER}, None))
    monkeypatch.setattr(re1_transport, 'build_client', lambda *a, **k: object())
    monkeypatch.setattr(re1_transport, 'OwnerVenue', Venue)
    monkeypatch.setattr(lfc_campaign_runtime, 'fetch_account_positions', lambda _: [] if world['redeemed'] else original['positions'])
    ordinary = lfc_capital_reads.read_activity
    monkeypatch.setattr(lfc_capital_reads, 'read_activity', lambda maker, start, end:
        ordinary(maker, start, end, get=lambda endpoint, params: packet([
            r for r in world['rows'] if params['start'] <= r['timestamp'] <= params['end']]), sleep=lambda _: None))
    def native_collection(packet, *, ledger):
        if not world['redeemed']:
            source = activity(cash='20', token='denver', tx='during-native-read')
            source['timestamp'] = int(clock.now().timestamp())+1
            clock.value += timedelta(seconds=2)
            world.update(redeemed=True, rows=[source])
        return native_packet(packet)
    monkeypatch.setattr(lfc_f2_wallet_reads, 'collect_window', native_collection)
    first = runtime.account_read_once()
    assert first['complete'] and first['capital_activity']['rows'] == []
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, first, anchor_mode='session')
    second = runtime.account_read_once()
    assert second['positions'] == [] and second['balances']['available_collateral'] == '310'
    if second['capital_activity']['rows'] == []:
        with pytest.raises(CapitalRefused, match='capital_inventory_unreconciled'):
            synchronize(ledger, CapitalBook(ledger).inventory_anchor, second)
    assert second['capital_activity']['rows'] == world['rows'], 'A normal redemption was skipped permanently between query and anchor end'


@pytest.mark.parametrize('reopen', [False, True])
def test_redemption_after_query_cutoff_before_anchor_end_stays_discoverable(tmp_path, reopen):
    ledger, _, clock, _ = fixture(tmp_path, personal=False)
    clock.value += timedelta(days=1)
    # Components and activity cover t=0. Native receipt collection then takes
    # two seconds; a normal auto-redemption executes at t=1 in that interval.
    read = observation(ledger, clock, positions={'denver': '20'}, cash='290')
    source = activity(cash='20', token='denver', tx='gap-redemption')
    source['timestamp'] = int(clock.now().timestamp()) + 1
    clock.value += timedelta(seconds=2)
    read['ended_at_utc'] = clock.now().isoformat()
    old = CapitalBook(ledger).inventory_anchor
    synchronize(ledger, old, read, anchor_mode='session')
    if reopen:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    anchor = CapitalBook(ledger).inventory_anchor
    assert not pending_rows(ledger)
    clock.value += timedelta(seconds=1)
    next_read = observation(ledger, clock, positions={}, cash='310')
    start, end = activity_start(ledger, next_read['started_at_utc']), int(clock.now().timestamp())
    seen = read_activity(MAKER, start, end, get=lambda endpoint, params:
        packet([source] if params['start'] <= source['timestamp'] <= params['end'] else []), sleep=lambda _: None)
    next_read['capital_activity'] = native_packet(seen)
    # Establish the actual consequence before the desired discovery assertion:
    # no old pending row exists, and the full money check now refuses the burn.
    if not seen['rows']:
        with pytest.raises(CapitalRefused, match='capital_inventory_unreconciled'):
            synchronize(ledger, anchor, next_read)
    assert seen['rows'] == [source], {
        'query_end': read['capital_activity']['scope']['end'],
        'redemption_at': source['timestamp'], 'anchor_at': anchor['at_utc'],
        'next_query_start': start, 'remaining_campaign_lot': CapitalBook(ledger).lots}


def test_skipped_campaign_auto_redemption_latches_a_false_incident(tmp_path):
    from tests.market.test_lfc_campaign import Clock, Mutexes, state_at
    from tests.market.test_lfc_f2_capital import NOW, filled
    from weather.market.lfc_campaign_guard import account_lease
    from weather.market.lfc_campaign_runtime import Runtime
    from weather.market.lfc_campaign import TransientPrecheck
    from weather.market.lfc_campaign_state import MoneyContradiction
    from weather.market.lfc_f2_pinb import example_policy
    from weather.market.lfc_recording_io import write_new
    from tests.market.test_lfc_redemption_native import paired
    from tests.market.test_lfc_f2_capital_reads import rpc_packet
    from weather.market.mm_stage2_hold import digest
    source, proof, tokens = paired(auto=True)
    clock = Clock(); clock.value = NOW
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path/'account', clock)
        ledger = state.ledger
        path = tmp_path/'campaign.json'; write_new(path, example_policy())
        runtime = Runtime(state=state, pilot_root=ledger.path.parent, policy_path=path,
            release={}, clock=clock, control_root=tmp_path/'control', task_enabled=lambda: True)
        initial = observation(ledger, clock, positions={tokens[1]: '20'}, cash='300')
        assert runtime.core_proof(ledger, initial)['money_accounting_complete']
        filled(ledger, 'campaign-lot', token=tokens[0], condition=source['condition_id'])
        clock.value += timedelta(days=1)
        read = observation(ledger, clock, positions={token: '20' for token in tokens}, cash='290')
        source['timestamp'] = int(clock.now().timestamp())+1
        proof.update(rows=[source], rows_sha256=digest([source]))
        clock.value += timedelta(seconds=2)
        read['ended_at_utc'] = clock.now().isoformat()
        runtime.preparing_f2 = True
        assert runtime.core_proof(ledger, read)['money_accounting_complete']
        runtime.preparing_f2 = False
        outcomes = []
        for elapsed in (0, 901):
            clock.value += timedelta(seconds=elapsed)
            after = observation(ledger, clock,
                positions={token: '20' for token in tokens} if elapsed == 0 else {}, cash='310')
            start, end = activity_start(ledger, after['started_at_utc']), int(clock.now().timestamp())
            after['capital_activity'] = native_packet(read_activity(MAKER, start, end,
                get=lambda _, params: packet([source] if params['start'] <= source['timestamp'] <= params['end'] else []),
                sleep=lambda _: None))
            if after['capital_activity']['rows']:
                after['capital_activity']['native_receipts'] = {source['transaction_hash']:
                    proof if elapsed else {**proof, 'receipt': rpc_packet(None)}}
            try:
                runtime.core_proof(ledger, after)
                outcomes.append('clean')
            except (TransientPrecheck, MoneyContradiction) as exc:
                outcomes.append(str(exc))
        assert outcomes[0] == 'capital_propagation_pending'
        assert not state.incidents(), {'outcomes': outcomes, 'incidents': state.incidents()}
