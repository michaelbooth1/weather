"""Guards: B084 bounded snapshot retries and truthful non-incident funding check."""
from contextlib import contextmanager
from datetime import timedelta
import json

import pytest

from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, state_at
from tests.market.test_lfc_campaign_runtime import runtime_at
from weather.market.lfc_campaign import TransientPrecheck
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_state import StateRefused
from weather.market.lfc_capital import CapitalRefused


@pytest.fixture
def guarded_account():
    with account_lease(MAKER, backend=Mutexes()):
        yield


@pytest.mark.parametrize('code', ['f2_anchor_snapshot_pending', 'capital_cash_snapshot_pending'])
@pytest.mark.parametrize('exception', [CapitalRefused, TransientPrecheck])
@pytest.mark.parametrize('failures', [1, 2, 3])
def test_confirm_funding_retries_only_bounded_snapshot_races(tmp_path, monkeypatch, code, exception, failures, guarded_account):
    runtime = runtime_at(tmp_path)
    @contextmanager
    def admission():
        yield
    monkeypatch.setattr(runtime, 'admission', admission)
    monkeypatch.setattr(runtime, 'reload_ledger', lambda: runtime.state.ledger)
    reads = []
    monkeypatch.setattr(runtime, 'read_account', lambda: reads.append(runtime.clock.now()) or {})
    def proof(*args):
        if len(reads) <= failures:
            raise exception(code)
        return {'money_accounting_complete': True, 'cleanup_proven': True, 'unknown_submit': False,
                'capital': {'cash_bridge_complete': True, 'funding_native': 300_000_000}}
    monkeypatch.setattr(runtime, 'core_proof', proof)
    if failures < 3:
        assert runtime.confirm_funding()['funding_native'] == 300_000_000
        assert len(list((runtime.state.root/'funding').glob('*.json'))) == 1
    else:
        with pytest.raises(TransientPrecheck, match=code):
            runtime.confirm_funding()
        assert not list((runtime.state.root/'funding').glob('*.json'))
    assert len(reads) == min(failures + 1, 3)
    assert all(b - a == timedelta(seconds=10) for a, b in zip(reads, reads[1:]))
    assert not getattr(runtime, 'preparing_f2', False)
    assert not runtime.state.ledger.autostart_claims and not runtime.state.incidents()


def test_confirm_funding_does_not_retry_campaign_loss_or_contradiction(tmp_path, monkeypatch, guarded_account):
    runtime = runtime_at(tmp_path)
    @contextmanager
    def admission():
        yield
    monkeypatch.setattr(runtime, 'admission', admission)
    monkeypatch.setattr(runtime, 'reload_ledger', lambda: runtime.state.ledger)
    calls = []
    monkeypatch.setattr(runtime, 'read_account', lambda: calls.append(True) or {})
    def proof(*args):
        raise CapitalRefused('capital_inventory_unreconciled')
    monkeypatch.setattr(runtime, 'core_proof', proof)
    with pytest.raises(CapitalRefused, match='capital_inventory_unreconciled'):
        runtime.confirm_funding()
    assert len(calls) == 1 and not runtime.state.incidents()


@pytest.mark.parametrize('code', ['f2_anchor_snapshot_pending', 'capital_cash_snapshot_pending'])
def test_exhausted_check_is_deferred_without_display_incident(tmp_path, monkeypatch, capsys, code):
    from weather.market import lfc_campaign_cli as cli
    from weather.market.lfc_campaign_runtime import Runtime
    from weather.market.lfc_f2_policy import example_policy
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path, Clock())
    path = tmp_path/'campaign.json'
    policy = example_policy(); policy['enabled'] = True
    path.write_text(json.dumps(policy))
    monkeypatch.setattr(cli, 'load_release', lambda *args: {'campaign_path': str(path), 'maker_address': MAKER})
    monkeypatch.setattr(cli, 'validate_release', lambda *args: None)
    monkeypatch.setattr(cli, 'bound_state', lambda *args, **kwargs: (state.ledger.path.parent, state))
    monkeypatch.setattr(cli, 'account_lease', lambda maker: account_lease(maker, backend=Mutexes()))
    monkeypatch.setattr(cli, 'CONTROL_ROOT', tmp_path/'control')
    def funding(*args):
        raise TransientPrecheck(code)
    monkeypatch.setattr(Runtime, 'confirm_funding', funding)
    monkeypatch.setattr(cli, 'notify_control', lambda *args: None, raising=False)
    assert cli.main(['check', '--release', 'fixture', '--release-sha256', 'a'*64, '--require-enabled']) == 1
    rows = [json.loads(p.read_text()) for p in (tmp_path/'control').glob('*.json')]
    assert rows and rows[-1]['phase'] == 'DEFERRED' and rows[-1]['incident'] is not True
    assert rows[-1]['reason'] == code
    assert not state.incidents()
    assert code in capsys.readouterr().out
