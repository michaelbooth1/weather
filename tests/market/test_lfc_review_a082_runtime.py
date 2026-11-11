"""Guards: personal receipt/position endpoint ordering cannot latch a false incident."""
from datetime import timedelta
import pytest
from tests.market.test_lfc_campaign import Clock, Mutexes, state_at
from tests.market.test_lfc_f2_capital import MAKER, NOW, filled
from tests.market.test_lfc_f2_inventory_b080 import observation
from tests.market.test_lfc_f2_capital_reads import native_packet, packet
from tests.market.test_lfc_redemption_native import paired
from weather.market.lfc_campaign import TransientPrecheck
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_campaign_state import AccountState, MoneyContradiction
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_f2_pinb import example_policy
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_recording_io import write_new
from weather.market.mm_stage2_hold import digest


@pytest.mark.parametrize('reopen', [False, True])
def test_personal_activity_then_positions_catchup_does_not_latch(tmp_path, monkeypatch, reopen):
    from weather.market import re1_transport, lfc_campaign_runtime, lfc_capital_reads, lfc_f2_wallet_reads
    clock = Clock(); clock.value = NOW
    source, proof, tokens = paired(auto=True)
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path/'account', clock)
        ledger = state.ledger
        path = tmp_path/'campaign.json'; write_new(path, example_policy())
        runtime = Runtime(state=state, pilot_root=ledger.path.parent, policy_path=path,
            release={}, clock=clock, control_root=tmp_path/'control', task_enabled=lambda: True)
        runtime.core_proof(ledger, observation(ledger, clock, positions={token: '20' for token in tokens}, cash='300'))
        filled(ledger, 'campaign-lot', token='denver', condition='denver-condition')
        clock.value += timedelta(days=1)
        source['timestamp'] = int(clock.now().timestamp())-20
        proof.update(rows=[source], rows_sha256=digest([source]))
        world = {'activity': False, 'positions': False}
        class Venue:
            def __init__(self, *args, **kwargs): pass
            def open_orders(self): return []
            def trades(self): return observation(runtime.state.ledger, clock, positions={}, cash='310')['trades']
            def balances(self): return observation(runtime.state.ledger, clock, positions={}, cash='310')['balances']
            def geography(self): return {'blocked': False}
            def close(self): pass
        monkeypatch.setattr(re1_transport, 'load_owner_credentials', lambda _: ({'FUNDER_ADDRESS': MAKER}, None))
        monkeypatch.setattr(re1_transport, 'build_client', lambda *args, **kwargs: object())
        monkeypatch.setattr(re1_transport, 'OwnerVenue', Venue)
        monkeypatch.setattr(lfc_campaign_runtime, 'fetch_account_positions', lambda _:
            observation(runtime.state.ledger, clock, positions={'denver': '20',
                **({} if world['positions'] else {token: '20' for token in tokens})}, cash='310')['positions'])
        ordinary = lfc_capital_reads.read_activity
        def activity_read(maker, start, end):
            return ordinary(maker, start, end, get=lambda _, params:
                packet([source] if world['activity'] and params['start'] <= source['timestamp'] <= params['end'] else []),
                sleep=lambda _: None)
        monkeypatch.setattr(lfc_capital_reads, 'read_activity', activity_read)
        def collect(observed, *, ledger):
            result = native_packet(observed)
            result['native_receipts'] = {source['transaction_hash']: proof} if observed['rows'] else {}
            return result
        monkeypatch.setattr(lfc_f2_wallet_reads, 'collect_window', collect)
        runtime.preparing_f2 = True
        runtime.core_proof(ledger, runtime.account_read_once())
        runtime.preparing_f2 = False
        # Retain the same claim and policy artifacts as AccountState.claim;
        # a synthetic bare claim cannot exercise the real latch's verify().
        from weather.market.lfc_campaign_policy import parse_policy
        policy = parse_policy(example_policy())
        entry = next(entry for entry in policy.entries if entry.permits(clock.now()))
        attempt = 'a'*32
        snapshot_sha = state.save(f'policies/{attempt}.json', {'policy': policy.raw, 'sha256': policy.sha256})
        claim = {'attempt_id': attempt, 'local_date': entry.local_date, 'entry_id': entry.id,
                 'prepared_file': None, 'prepared_sha256': None,
                 'campaign_id': policy.raw['campaign_id'], 'policy_sha256': policy.sha256,
                 'policy_snapshot_sha256': snapshot_sha, 'claimed_at_utc': clock.now().isoformat(),
                 'ledger_sha256': ledger.previous, 'sleeve_loss_basis': policy.raw['sleeve_loss_basis']}
        sha = state.save(f'claims/{entry.local_date}.json', claim)
        ledger.record('autostart_claim', attempt_id=attempt, local_date=entry.local_date,
                      file_sha256=sha, sleeve_loss_basis=policy.raw['sleeve_loss_basis'])
        state.verify()
        world['activity'] = True
        clock.value += timedelta(seconds=2)
        runtime.core_proof(ledger, runtime.account_read_once())
        if reopen:
            ledger = Ledger.open(ledger.path, clock=clock.now)
            runtime.state = AccountState(state.root.parent, ledger)
            state = runtime.state
        world['positions'] = True
        outcomes = []
        for seconds in (2, 901):
            clock.value += timedelta(seconds=seconds)
            try:
                runtime.core_proof(ledger, runtime.account_read_once())
                outcomes.append('clean')
            except (TransientPrecheck, MoneyContradiction) as exc:
                outcomes.append(str(exc))
        assert not state.incidents(), outcomes
        assert outcomes == ['clean', 'clean'], outcomes
        assert CapitalBook(ledger).profit == 0
