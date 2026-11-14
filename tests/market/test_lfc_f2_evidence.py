"""Full retained two-band packets and recurrent faults after legitimate recovery.

Guards: B036 preserves R1-R4/N1 across nested journals, ACKs and reboot.
"""
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import Mutexes
from tests.market.test_lfc_campaign_runtime import account_read
from tests.market.test_lfc_campaign_recurrence import recover
from tests.market.test_lfc_f2_capital import MAKER
from tests.market.test_lfc_f2_capital_reads import packet, native_packet
from tests.market.test_lfc_f2_controller import setup
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_campaign_state import AccountState, StateRefused
from weather.market.lfc_capital import ASSET
from weather.market.lfc_capital_reads import read_activity
from weather.market.lfc_campaign_proof import local_money_proof
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_recording_io import file_sha
from weather.market.mm_stage2_hold import digest


def runtime_at_controller(controller, account, status, ledger, clock, monkeypatch):
    state = account.state
    runtime = Runtime(state=state, pilot_root=ledger.path.parent, policy_path=ledger.path.parent / 'unused.json',
                      release={}, clock=clock, control_root=ledger.path.parent / 'control', task_enabled=lambda: True)
    runtime.lease = SimpleNamespace(check=lambda: None)
    @contextmanager
    def admission():
        yield
    monkeypatch.setattr(runtime, 'admission', admission)
    def fresh_read():
        row = account_read(runtime)
        now = clock.now()
        row['started_at_utc'] = row['ended_at_utc'] = now.isoformat()
        for component in row['component_times'].values():
            component['started_at_utc'] = component['ended_at_utc'] = now.isoformat()
        row['since'] = str(int(datetime.fromisoformat(ledger.rows[0]['recorded_at_utc']).timestamp()))
        row['balances'] = {'available_collateral': '300', 'assets': {ASSET: '300'},
                           'collateral_evidence': {'balance': '300000000'}}
        row['capital_activity'] = native_packet(read_activity(MAKER, int(row['since']), int(now.timestamp()),
                                                get=lambda *a: packet(), sleep=lambda _: None))
        return row
    monkeypatch.setattr(runtime, 'read_account', fresh_read)
    from weather.market import lfc_campaign_cli as cli
    monkeypatch.setattr(cli.sys.stdin, 'isatty', lambda: True)
    return runtime


@pytest.mark.parametrize('second_file', ['band-1/journal.jsonl', 'band-2/submit-1.ack.json'])
@pytest.mark.parametrize('reboot', [False, True])
def test_f2_recurrent_nested_evidence_loss_requires_new_owner_recovery(tmp_path, monkeypatch, second_file, reboot):
    with account_lease(MAKER, backend=Mutexes()):
        controller, account, status, ledger, clock = setup(tmp_path, enrolled=True)
        result = controller.run()
        assert result['cleanup_ok']
        outcome = status.finish(success=True)
        local = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                                    attempt_id=controller.attempt_id, outcome=outcome)
        assert local['complete'], local
        runtime = runtime_at_controller(controller, account, status, ledger, clock, monkeypatch)
        claim = account.claim
        runtime.save_result(claim, {'session_id': controller.session_id, 'outcome': outcome,
                    'private_evidence_directory': controller.directory.relative_to(tmp_path).as_posix(),
                    'local_money_proof': local, 'unknown_submit': False, 'evidence_complete': True,
                    'inventory_proven': True, 'public_coverage': {'configured': False, 'gap': 'not_configured'}})
        proof = runtime.postcheck(claim, runtime.saved_result(claim))
        assert proof['money_accounting_complete'] and proof['cleanup_proven'], proof
        runtime.state.close(claim, proof, clock.now())
        initial_dates = runtime.state.consumed_dates()
        assert claim['local_date'] not in initial_dates  # B090: clean claims no longer consume a date.
        first_path = controller.directory / 'band-1/journal.jsonl'
        raw = first_path.read_bytes()
        first_path.unlink()
        with pytest.raises(StateRefused, match='retained_private_evidence_fault'):
            runtime.state.require_retained_evidence()
        first_path.write_bytes(raw)
        first = runtime.state.incidents()[0]
        recover(runtime, first['attempt_id'], monkeypatch)
        consumed_after_incident = initial_dates | {claim['local_date']}
        assert runtime.state.consumed_dates() == consumed_after_incident
        closure = runtime.state.root / 'owner-closures' / (first['attempt_id'] + '.json')
        original_receipt = file_sha(closure)
        if reboot:
            reopened = Ledger.open(ledger.path, clock=clock.now)
            runtime.state = AccountState(runtime.state.root.parent, reopened)
            runtime.state.verify()
        second_path = controller.directory / second_file
        raw = second_path.read_bytes()
        second_path.unlink()
        with pytest.raises(StateRefused, match='retained_private_evidence_fault'):
            runtime.state.require_retained_evidence()
        second_path.write_bytes(raw)
        second = runtime.state.incidents()[0]
        assert second['attempt_id'] != first['attempt_id']
        assert second['artifact'] == 'private/' + second_file
        assert second['detection_sequence'] > first['detection_sequence']
        assert runtime.state.consumed_dates() == consumed_after_incident
        assert file_sha(closure) == original_receipt
        following = next(e for e in account.policy.entries if e.local_date == '2026-11-12')
        clock.sleep((following.start - clock.now()).total_seconds())
        with pytest.raises(StateRefused, match='account_incident_latched'):
            runtime.state.claim(following, account.policy, clock.now())
        recover(runtime, second['attempt_id'], monkeypatch)
        assert runtime.state.incidents() == []
        assert file_sha(closure) == original_receipt
