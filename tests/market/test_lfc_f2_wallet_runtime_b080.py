"""Guards: B080 normal pre-go, owner history and read-only status wiring.

All account, readiness, workload and driver capabilities are inert fixtures.
"""
from contextlib import nullcontext
from copy import deepcopy
from datetime import timedelta
import json
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, bind_launch, state_at
from tests.market.test_lfc_f2_inventory_b080 import fixture, observation
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_campaign import CampaignCoordinator, TransientPrecheck
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import load_policy
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_campaign_state import StateRefused
from weather.market.lfc_f2_pinb import example_policy
from weather.market.lfc_recording_io import write_new


@pytest.mark.parametrize('foreign_open', [False, True])
def test_first_tick_reanchors_personal_wallet_before_session_stub(tmp_path, monkeypatch, foreign_open):
    from weather.market import lfc_campaign_runtime, lfc_campaign_visibility, lfc_cli, re1_owner_checks
    from weather.market.lfc_campaign_recovery import failure_result
    from tests.market.test_lfc_f2_capital import NOW
    clock = Clock()
    clock.value = NOW
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path / 'account', clock)
        policy_path = tmp_path / 'campaign.json'
        row = example_policy()
        row['enabled'] = True
        write_new(policy_path, row)
        runtime = Runtime(state=state, pilot_root=state.ledger.path.parent, policy_path=policy_path,
            release={}, clock=clock, control_root=tmp_path / 'control', task_enabled=lambda: True)
        runtime.lease = SimpleNamespace(check=lambda: None)
        values = {'positions': {'nfl': '15'}, 'cash': '300'}
        monkeypatch.setattr(runtime, 'read_account', lambda: observation(state.ledger, clock, **values))
        assert runtime.core_proof(state.ledger, runtime.read_account())['money_accounting_complete']
        original = deepcopy(CapitalBook(state.ledger).inventory_anchor)
        clock.value += timedelta(seconds=1)
        values.update(positions={'evening-nfl': '25'}, cash='240')
        if foreign_open:
            def foreign_read():
                read = observation(state.ledger, clock, **values)
                read['open_orders'] = [{'id': 'personal-resting-order'}]
                return read
            monkeypatch.setattr(runtime, 'read_account', foreign_read)
        monkeypatch.setattr(runtime, 'admission', lambda: nullcontext())
        monkeypatch.setattr(runtime, 'followup', lambda *a, **k: None)
        monkeypatch.setattr(runtime, 'notify_control', lambda *a: None)
        monkeypatch.setattr(lfc_campaign_runtime, 'workstation_headroom', lambda: {})
        monkeypatch.setattr(lfc_campaign_visibility, 'disk_headroom', lambda _: {})
        monkeypatch.setattr(lfc_cli, 'session0_passed', lambda *a, **k: True)
        monkeypatch.setattr(re1_owner_checks, 'code_identity', lambda: 'f' * 40)
        monkeypatch.setattr(runtime, 'readiness', lambda *a: {
            'timeouts_seconds': {'open_orders': 2}, 'selection_sha256': 'a' * 64,
            'readiness_directory': 'readiness/inert', 'latency_seconds': {}})
        calls = []
        def session_stub(claim, entry, policy, prepared):
            calls.append(claim['attempt_id'])
            assert CapitalBook(state.ledger).inventory_anchor['positions'] == {'evening-nfl': '25'}
            return failure_result(state.ledger, claim, 'synthetic_no_orders')
        monkeypatch.setattr(runtime, 'run_session', session_stub)
        coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
        policy = bind_launch(coordinator, load_policy(policy_path))
        runtime.wrapper_launch = coordinator.wrapper_launch
        result = coordinator.tick(lambda: policy)
        if foreign_open:
            from weather.market.lfc_campaign_control import latest_control
            assert result == 'MISSED' and not calls and not state.incidents()
            assert not state.ledger.autostart_claims
            assert not any(row['event'] == 'f2_session_anchor' for row in state.ledger.rows)
            assert latest_control(tmp_path / 'control')['reason'] == 'foreign_open_order'
            return
        assert result == 'STARTED'
        assert len(calls) == 1 and not state.incidents()
        assert original['positions'] == {'nfl': '15'}
        events = [r['event'] for r in state.ledger.rows]
        assert events.index('capital_bridge') < events.index('f2_session_anchor') < events.index('autostart_claim')
        assert CapitalBook(state.ledger).figures()['funding_native'] == 300_000_000
        assert CapitalBook(state.ledger).expected_cash() == 240_000_000


def test_unresolved_history_cannot_install_enrollment_anchor(tmp_path, monkeypatch):
    from weather.market import lfc_campaign_history
    ledger, baseline, clock, read = fixture(tmp_path, bridge=False)
    policy_path = tmp_path / 'campaign.json'
    write_new(policy_path, example_policy())
    runtime = object.__new__(Runtime)
    runtime.clock, runtime.policy_path, runtime.pilot_root = clock, policy_path, tmp_path
    runtime.state = SimpleNamespace(ledger=ledger, maker=MAKER, root=tmp_path / 'state')
    monkeypatch.setattr(lfc_campaign_history, 'history_refusals', lambda *a: {'prior': 'a' * 64})
    before = ledger.path.read_bytes()
    with pytest.raises(StateRefused, match='f2_anchor_history_unresolved'):
        runtime.core_proof(ledger, read)
    assert ledger.path.read_bytes() == before


def test_owner_funding_check_cannot_reanchor_over_pending_postchecks(tmp_path, monkeypatch):
    from tests.market.test_lfc_f2_capital import NOW
    clock = Clock()
    clock.value = NOW
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path / 'account', clock)
        path = tmp_path / 'campaign.json'
        row = example_policy()
        row['enabled'] = True
        write_new(path, row)
        runtime = Runtime(state=state, pilot_root=state.ledger.path.parent, policy_path=path,
            release={}, clock=clock, control_root=tmp_path / 'control', task_enabled=lambda: False)
        monkeypatch.setattr(runtime, 'admission', lambda: nullcontext())
        monkeypatch.setattr(runtime, 'read_account', lambda: observation(state.ledger, clock, positions={}, cash='300'))
        assert runtime.core_proof(state.ledger, runtime.read_account())['money_accounting_complete']
        policy = load_policy(path)
        entry = next(entry for entry in policy.entries if entry.permits(clock.now()))
        state.claim(entry, policy, clock.now())
        before = state.ledger.path.read_bytes()
        from weather.market.lfc_capital import CapitalRefused
        with pytest.raises(CapitalRefused, match='f2_anchor_postchecks_pending'):
            runtime.confirm_funding()
        assert state.ledger.path.read_bytes() == before


def test_trade_quantity_mismatch_cannot_be_hidden_by_an_enrollment_anchor(tmp_path):
    ledger, baseline, clock, read = fixture(tmp_path, bridge=False)
    path = tmp_path / 'campaign.json'
    write_new(path, example_policy())
    runtime = object.__new__(Runtime)
    runtime.clock, runtime.policy_path, runtime.pilot_root = clock, path, tmp_path
    runtime.state = SimpleNamespace(ledger=ledger, maker=MAKER, root=tmp_path / 'state')
    read['trades'] = []
    before = ledger.path.read_bytes()
    proof = runtime.core_proof(ledger, read)
    assert not proof['money_accounting_complete'] and proof['money_contradiction']
    assert ledger.path.read_bytes() == before and CapitalBook(ledger).inventory_anchor is None


def test_owner_recovery_of_one_history_defers_bridge_until_remaining_history_is_resolved(tmp_path, monkeypatch):
    from weather.market import lfc_campaign_history
    ledger, baseline, clock, read = fixture(tmp_path, bridge=False)
    path = tmp_path / 'campaign.json'
    write_new(path, example_policy())
    runtime = object.__new__(Runtime)
    runtime.clock, runtime.policy_path, runtime.pilot_root = clock, path, tmp_path
    runtime.state = SimpleNamespace(ledger=ledger, maker=MAKER, root=tmp_path / 'state')
    runtime.history_recovery_session = 's0c'
    issues = {'s0c': 'a' * 64, 's1': 'b' * 64}
    monkeypatch.setattr(lfc_campaign_history, 'history_refusals', lambda *a: dict(issues))
    proof = runtime.core_proof(ledger, read)
    assert proof['money_accounting_complete'] and proof['capital']['bridge_pending_history_recovery']
    assert CapitalBook(ledger).bridge is None
    del issues['s0c']
    runtime.history_recovery_session = 's1'
    assert runtime.core_proof(ledger, read)['money_accounting_complete']
    assert CapitalBook(ledger).inventory_anchor['positions'] == {'denver': '20', 'nfl': '15'}


def test_cash_below_a_qualifying_band_need_defers_without_money_incident(tmp_path, monkeypatch):
    from weather.market import re1_transport, lfc_pilot, lfc_f2_selection
    ledger, baseline, clock, _ = fixture(tmp_path, personal=False)
    clock.value += timedelta(days=1)
    read = observation(ledger, clock, positions={'denver': '20'}, cash='1')
    from weather.market.lfc_capital_reads import synchronize
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    path = tmp_path / 'campaign.json'
    write_new(path, example_policy())
    runtime = object.__new__(Runtime)
    runtime.clock = clock
    runtime.state = SimpleNamespace(ledger=ledger, maker=MAKER)
    monkeypatch.setattr(re1_transport, 'load_owner_credentials', lambda _: ({'FUNDER_ADDRESS': MAKER}, None))
    monkeypatch.setattr(lfc_pilot, 'LfcPublicBooks', lambda: object())
    monkeypatch.setattr(lfc_f2_selection, 'discover', lambda *a, **k: {
        'selected_condition_id': None, 'rows': [{'eligible': True, 'quote': {'reserve_pusd': '19.4'}}]})
    with pytest.raises(TransientPrecheck, match='wallet_cash_below_sleeve'):
        runtime.readiness(None, load_policy(path), read)
    assert not ledger.halted and not ledger.autostart_incidents
    from weather.market.lfc_campaign_control import control_record
    row = control_record(tmp_path / 'control', 'a' * 32, phase='DEFERRED',
                         now=clock.now(), reason='wallet_cash_below_sleeve')
    assert row['reason'] == 'wallet_cash_below_sleeve' and row['incident'] is False


def test_status_prints_personal_wallet_rule_and_remains_read_only(tmp_path, monkeypatch, capsys):
    from tests.market.test_lfc_review_b068_status import setup_status, files
    from weather.market import lfc_campaign_cli as cli, lfc_campaign_guard as guard
    from weather.market.lfc_campaign_control import control_record
    from weather.market.lfc_f2_inventory import PERSONAL_TRADES_RULE
    from datetime import datetime, timezone
    setup_status(tmp_path, monkeypatch)
    monkeypatch.setattr(guard, 'account_lease_busy', lambda _: False)
    control_record(tmp_path / 'control', 'a' * 32, phase='IDLE', now=datetime.now(timezone.utc))
    before = files(tmp_path)
    assert cli.main(['status', '--release', 'fixture', '--release-sha256', 'a' * 64]) == 0
    output = capsys.readouterr()
    assert output.err.strip() == PERSONAL_TRADES_RULE
    assert json.loads(output.out)['personal_trades_rule'] == PERSONAL_TRADES_RULE
    assert files(tmp_path) == before


@pytest.mark.parametrize('personal_buy,k', [(False, 12), (True, 2)])
def test_pinb_driver_reposts_with_new_anchor_and_halts_on_personal_buy(tmp_path, monkeypatch, personal_buy, k):
    from tests.market import test_lfc_f2_repost as factories
    from tests.market.lfc_pinb_fixtures import pinb_row
    from weather.market.lfc_capital_reads import synchronize
    from weather.market.lfc_campaign_state import MoneyContradiction
    from tests.market import test_lfc_f2_controller as controller_fixtures
    original_install = controller_fixtures.install
    def install_with_anchor(ledger, *, cash):
        original_install(ledger, cash=cash)
        row = observation(ledger, SimpleNamespace(now=ledger.clock), positions={}, cash=cash)
        synchronize(ledger, CapitalBook(ledger).anchor, row, anchor_mode='session')
    with account_lease(MAKER, backend=Mutexes()):
        with monkeypatch.context() as patch:
            patch.setattr(factories, 'example_policy', pinb_row)
            patch.setattr(controller_fixtures, 'install', install_with_anchor)
            controller, account, status, ledger, clock, runtime, read = factories.fixture(
                tmp_path, k=k, enrolled=True, seconds=600)
        runtime.policy_path = tmp_path / 'campaign.json'
        write_new(runtime.policy_path, controller.policy.raw)
        original = read
        def current():
            row = original()
            if personal_buy and clock.seconds >= 12:
                row['positions'].append({'asset': 'personal-nfl', 'size': '1', 'conditionId': 'nfl'})
            return row
        monkeypatch.setattr(runtime, 'read_account', current)
        from weather.market.lfc_f2_reconcile import prove
        controller.repost_proof = lambda band: prove(runtime, band, current())
        controller.verify = lambda: runtime.core_proof(ledger, current())
        result = controller.run()
        if not personal_buy:
            assert result['cleanup_ok'], result
            assert controller.bands[0].submits > 2  # A proven fill passes the actual repost rail.
            assert status.finish(success=True)['state'] == 'COMPLETE'
            assert len(controller.bands) == 12
            assert CapitalBook(ledger).figures()['funding_native'] == 300_000_000
            from weather.market.lfc_ledger import Ledger
            reopened = Ledger.open(ledger.path, clock=clock.now)
            assert CapitalBook(reopened).inventory_anchor == CapitalBook(ledger).inventory_anchor
            assert CapitalBook(reopened).figures() == CapitalBook(ledger).figures()
        else:
            assert not result['cleanup_ok']
            assert controller.bands[0].submits == 2
            assert not ledger.unacknowledged_intents()
            clock.sleep(901)
            with pytest.raises(MoneyContradiction, match='confirmed_capital_read_mismatch'):
                runtime.core_proof(ledger, current())
            assert runtime.state.incidents()
