"""Guards: B068 status observes without an account lease or any writes."""
import json
import os
from datetime import datetime, timezone
import pytest
from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, state_at
from tests.market.test_lfc_f2_policy import example_policy
from weather.market.lfc_campaign_guard import account_lease
from weather.market import lfc_campaign_cli as cli


def setup_status(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()): state = state_at(tmp_path/'account', Clock())
    path = tmp_path/'campaign.json'; path.write_text(json.dumps(example_policy()))
    release = {'maker_address': MAKER, 'state_id': state.ledger.enrollment['state_id'],
        'ledger_genesis_sha256': state.ledger.row_sha256(0), 'campaign_path': str(path)}
    monkeypatch.setattr(cli, 'load_release', lambda *a: release)
    monkeypatch.setattr(cli, 'validate_release', lambda *a: None)
    monkeypatch.setattr(cli, 'pilot_root', lambda: state.ledger.path.parent)
    monkeypatch.setattr(cli, 'DEFAULT_STATE_ROOT', state.root.parent)
    monkeypatch.setattr(cli, 'CONTROL_ROOT', tmp_path/'control')
    monkeypatch.setattr(cli, 'account_lease', lambda *a: pytest.fail('status took account lease'))
    return state


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_status_held_lease_is_read_only_and_does_not_block_next_entry(tmp_path, monkeypatch, capsys):
    state = setup_status(tmp_path, monkeypatch)
    before = files(tmp_path)
    with account_lease(MAKER, backend=Mutexes()):
        assert cli.main(['status', '--release', 'fixture', '--release-sha256', 'a'*64]) == 1
        assert 'deferred: lease busy' in capsys.readouterr().out
    assert files(tmp_path) == before
    # The observer leaves neither a date claim nor a retained admission holder.
    with account_lease(MAKER, backend=Mutexes()):
        assert not state.claims() and not state.incidents()
        from tests.market.test_lfc_campaign import StubRuntime, policy_row, bind_launch
        from weather.market.lfc_campaign import CampaignCoordinator
        from weather.market.lfc_campaign_policy import parse_policy
        clock = Clock(); runtime = StubRuntime(state, clock)
        coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path/'control')
        policy = bind_launch(coordinator, parse_policy(policy_row()))
        assert coordinator.tick(lambda: policy) == 'STARTED' and runtime.go_count == 1
        assert len(state.claims()) == 1 and not state.incidents()


def test_status_idle_reads_snapshot_without_writing(tmp_path, monkeypatch, capsys):
    from weather.market.lfc_campaign_control import control_record
    from weather.market import lfc_campaign_guard as guard
    state = setup_status(tmp_path, monkeypatch)
    monkeypatch.setattr(guard, 'account_lease_busy', lambda maker: False, raising=False)
    control_record(tmp_path/'control', 'a'*32, phase='IDLE', now=datetime.now(timezone.utc))
    before = files(tmp_path)
    assert cli.main(['status', '--release', 'fixture', '--release-sha256', 'a'*64]) == 0
    row = json.loads(capsys.readouterr().out)
    assert row['state'] == 'STATUS' and row['clean'] is True
    assert row['sleeve_loss_basis'] == 'net_of_retained_gains'
    assert row['ledger_head_sha256'] == state.ledger.row_sha256(len(state.ledger.rows)-1)
    assert files(tmp_path) == before


def test_status_detects_deleted_anchored_closure_without_latching_or_repairing(tmp_path, monkeypatch, capsys):
    from tests.market.test_lfc_review_b067_integrity import prepared
    from tests.market.test_lfc_campaign import NOW
    from weather.market import lfc_campaign_guard as guard
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        runtime.state.close(claim, proof, NOW)
        (runtime.state.root/'closed'/(claim['attempt_id']+'.json')).unlink()
    release = {'maker_address': MAKER, 'state_id': runtime.state.ledger.enrollment['state_id'],
        'ledger_genesis_sha256': runtime.state.ledger.row_sha256(0), 'campaign_path': 'not-read'}
    monkeypatch.setattr(cli, 'load_release', lambda *a: release)
    monkeypatch.setattr(cli, 'validate_release', lambda *a: None)
    monkeypatch.setattr(cli, 'pilot_root', lambda: runtime.pilot_root)
    monkeypatch.setattr(cli, 'DEFAULT_STATE_ROOT', runtime.state.root.parent)
    monkeypatch.setattr(cli, 'CONTROL_ROOT', runtime.control_root)
    monkeypatch.setattr(guard, 'account_lease_busy', lambda maker: False)
    before = files(tmp_path)
    assert cli.main(['status', '--release', 'fixture', '--release-sha256', 'a'*64]) == 1
    assert json.loads(capsys.readouterr().out)['reason'] == 'status_evidence_fault'
    assert files(tmp_path) == before


@pytest.mark.skipif(os.name != 'nt', reason='Windows mutex observation')
def test_os_mutex_observation_never_acquires_the_account_guard():
    from weather.market.lfc_campaign_guard import WindowsMutexes, account_key, account_lease_busy
    maker = '0x'+'b'*40
    backend = WindowsMutexes()
    handle = backend.acquire(r'Global\WeatherLFCCampaignAccount.'+account_key(maker))
    try:
        assert account_lease_busy(maker) is True
    finally:
        backend.release(handle)
    assert account_lease_busy(maker) is False
