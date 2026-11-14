"""Guards: B090-K check validation truth and narrowly bounded pending-postcheck Enable."""
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
import json

import pytest

from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, state_at
from tests.market.test_lfc_f2_capital import NOW
from tests.market.test_lfc_f2_inventory_b080 import observation
from weather.market.lfc_campaign import TransientPrecheck
from weather.market.lfc_campaign_enable_check import NOTICE, pending_postchecks_only
from weather.market.lfc_campaign_guard import AdmissionBusy, account_lease
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_campaign_state import StateRefused
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_campaign_policy import load_policy
from weather.market.lfc_f2_pinb import example_policy
from weather.market.lfc_recording_io import write_new


@pytest.fixture
def pending_runtime(tmp_path, monkeypatch):
    clock = Clock(); clock.value = NOW
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path / 'account', clock)
        path = tmp_path / 'campaign.json'
        policy = example_policy(); policy['enabled'] = True
        write_new(path, policy)
        runtime = Runtime(state=state, pilot_root=state.ledger.path.parent, policy_path=path,
            release={}, clock=clock, control_root=tmp_path / 'control', task_enabled=lambda: False)
        monkeypatch.setattr(runtime, 'admission', lambda: nullcontext())
        monkeypatch.setattr(runtime, 'read_account', lambda: observation(state.ledger, clock, positions={}, cash='300'))
        assert runtime.core_proof(state.ledger, runtime.read_account())['money_accounting_complete']
        loaded = load_policy(path)
        entry = next(entry for entry in loaded.entries if entry.permits(clock.now()))
        state.claim(entry, loaded, clock.now())
        yield runtime


def test_only_pending_postchecks_pass_funding_without_reanchor_close_or_live_action(pending_runtime):
    runtime = pending_runtime
    before = runtime.state.ledger.path.read_bytes()
    claims = runtime.state.pending()
    anchor = CapitalBook(runtime.state.ledger).inventory_anchor
    funding = runtime.confirm_funding()
    assert funding['notice'] == NOTICE and funding['capital_bridge_complete']
    assert runtime.state.ledger.path.read_bytes() == before and runtime.state.pending() == claims
    assert CapitalBook(runtime.state.ledger).inventory_anchor == anchor


@pytest.mark.parametrize('blocker', ['open_session', 'unresolved_leg', 'intent', 'incident', 'halt', 'mismatch'])
def test_pending_exception_refuses_every_unsafe_local_state(blocker):
    flags = {blocker}
    ledger = SimpleNamespace(rows=[{'event': 'autostart_claim', 'attempt_id': 'pending'}],
        open_sessions=lambda: ['open'] if 'open_session' in flags else [],
        unresolved_legs=lambda: ['leg'] if 'unresolved_leg' in flags else [],
        unacknowledged_intents=lambda: ['intent'] if 'intent' in flags else [],
        halted='halt' in flags, mismatches=['mismatch'] if 'mismatch' in flags else [])
    state = SimpleNamespace(incidents=lambda: ['incident'] if 'incident' in flags else [],
        pending=lambda: [{'attempt_id': 'pending'}])
    with pytest.raises(StateRefused, match='enrollment_funding_unreconciled'):
        pending_postchecks_only(state, ledger)


@pytest.mark.parametrize('blocker', ['money', 'cleanup', 'unknown_submit', 'cash_bridge'])
def test_pending_exception_never_hides_other_funding_blockers(pending_runtime, monkeypatch, blocker):
    runtime = pending_runtime
    ordinary = runtime.core_proof
    def incomplete(*args):
        proof = ordinary(*args)
        if blocker == 'cash_bridge':
            proof['capital']['cash_bridge_complete'] = False
        else:
            proof[{'money': 'money_accounting_complete', 'cleanup': 'cleanup_proven',
                   'unknown_submit': 'unknown_submit'}[blocker]] = blocker == 'unknown_submit'
        return proof
    monkeypatch.setattr(runtime, 'core_proof', incomplete)
    with pytest.raises(StateRefused, match='enrollment_funding_unreconciled'):
        runtime.confirm_funding()


def wire_cli(cli, runtime, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, 'load_release', lambda *args: {'campaign_path': str(runtime.policy_path), 'maker_address': MAKER})
    monkeypatch.setattr(cli, 'validate_release', lambda *args: None)
    monkeypatch.setattr(cli, 'bound_state', lambda *args, **kwargs: (runtime.pilot_root, runtime.state))
    monkeypatch.setattr(cli, 'account_lease', lambda *args: nullcontext())
    monkeypatch.setattr(cli, 'CONTROL_ROOT', tmp_path / 'cli-control')
    import weather.market.lfc_campaign_runtime as module
    monkeypatch.setattr(module, 'Runtime', lambda **kwargs: runtime)


def test_check_prints_notice_and_explicit_validated_receipt(pending_runtime, monkeypatch, tmp_path, capsys):
    from weather.market import lfc_campaign_cli as cli
    wire_cli(cli, pending_runtime, monkeypatch, tmp_path)
    assert cli.main(['check', '--release', 'fixture', '--release-sha256', 'a' * 64, '--require-enabled']) == 0
    output = capsys.readouterr().out
    assert NOTICE in output.splitlines()
    assert json.loads(output.splitlines()[-1]) == {'state': 'VALIDATED', 'validated': True, 'require_enabled': True}


@pytest.mark.parametrize('exception', ['busy', 'deferred'])
def test_check_busy_or_deferred_is_nonzero_and_never_validated(tmp_path, monkeypatch, capsys, exception):
    from weather.market import lfc_campaign_cli as cli
    from weather.market.lfc_campaign_launch import LaunchDeferred
    monkeypatch.setattr(cli, 'CONTROL_ROOT', tmp_path / 'control')
    monkeypatch.setattr(cli, 'validate_release', lambda *args: None)
    if exception == 'deferred':
        def load(*args):
            raise LaunchDeferred('wrapper_launch_missing_or_invalid')
        monkeypatch.setattr(cli, 'load_release', load)
    else:
        monkeypatch.setattr(cli, 'load_release', lambda *args: {'maker_address': MAKER})
        @contextmanager
        def busy(*args):
            raise AdmissionBusy('busy')
            yield
        monkeypatch.setattr(cli, 'account_lease', busy)
    assert cli.main(['check', '--release', 'fixture', '--release-sha256', 'a' * 64]) != 0
    assert 'VALIDATED' not in capsys.readouterr().out
