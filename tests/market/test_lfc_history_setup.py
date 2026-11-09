"""Owner recovery and setup of a synthetic F0 with retained failed flags.

Guards: T073 explicit policy path before enrollment, no erased flags or credited income.
External account, installation, lease and terminal inputs are inert fixtures.
"""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tests.market.lfc_campaign_fixtures import private_result
from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes
from tests.market.test_lfc_campaign_runtime import account_read
from tests.market.test_lfc_f2_capital_reads import native_packet, packet
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_history import history_refusals
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_campaign_state import AccountState, StateRefused
from weather.market.lfc_capital import ASSET, CapitalBook
from weather.market.lfc_capital_reads import read_activity
from weather.market.lfc_f2_breadth import example_policy
from weather.market.lfc_ledger import Ledger, take_baseline, write_baseline
from weather.market.lfc_recording_io import write_new


def test_failed_f0_recovery_explicit_policy_then_enroll_then_seal(tmp_path, monkeypatch):
    from weather import execution_host
    from weather.market import lfc_campaign_cli as cli, lfc_campaign_guard as guard
    from weather.market import lfc_campaign_runtime as adapter, lfc_campaign_release as release
    from weather.market import lfc_campaign_state as states, lfc_campaign_workload as workload, lfc_pilot
    from weather.market.lfc_campaign_policy import load_policy
    clock = Clock()
    root = tmp_path / 'synthetic-pilot'
    ledger = Ledger.create(root / 'ledger.jsonl', clock=clock.now, maker_address=MAKER)
    write_baseline(root, take_baseline(label='t40', now=clock.now(), maker_address=MAKER,
        positions=[], open_orders=[], available_collateral='300'), ledger)
    state_root = tmp_path / 'account-state'
    state = AccountState(state_root, ledger)
    runtime = Runtime(state=state, pilot_root=root, policy_path=tmp_path / 'unused.json', release={}, clock=clock,
                      control_root=tmp_path / 'control', task_enabled=lambda: False)
    with account_lease(MAKER, backend=Mutexes()):
        directory, _ = private_result(runtime, None, legacy=True, terminal_read_gap=True,
                                      faults=('terminal_order_unavailable',))
        ledger.terminal('o', {'id': 'o', 'status': 'MATCHED', 'size_matched': '1'}, source='fixture-reconcile')
        original = deepcopy(ledger.sessions['s'])
        original_files = {p.name: p.read_bytes() for p in directory.iterdir()}
        with pytest.raises(StateRefused, match='historical_money_ambiguity_requires_owner_recovery'):
            state.enroll(clock.now())
    issue = history_refusals(ledger, root)['s']
    assert not original['end']['evidence_complete'] and not original['end']['inventory_proven']
    # Funding is final before the first F2 proof creates its immutable bridge.
    policy_path = tmp_path / 'chosen-final-policy.json'
    write_new(policy_path, example_policy())
    monkeypatch.setattr(cli.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda: 'recover legacy ' + issue[:12])
    monkeypatch.setattr(cli, 'pilot_root', lambda: root)
    monkeypatch.setattr(cli, 'DEFAULT_STATE_ROOT', state_root)
    monkeypatch.setattr(adapter, 'CampaignClock', lambda: clock)
    monkeypatch.setattr(release, 'git_identity', lambda _: 'f' * 40)
    monkeypatch.setattr(execution_host, 'require_current_portable_execution_assignment', lambda: {})
    monkeypatch.setattr(cli, 'account_lease', lambda maker: account_lease(maker, backend=Mutexes()))
    monkeypatch.setattr(guard, 'HOLD_PATH', tmp_path / 'HOLD')
    monkeypatch.setattr(guard, 'CAMPAIGN_WORK_LOCK', tmp_path / 'work-lock')
    poison = tmp_path / 'poison'
    poison.mkdir()
    @contextmanager
    def lease(_):
        yield SimpleNamespace(poison_root=poison)
    monkeypatch.setattr(guard, 'ExclusiveWorkload', lease)
    marker_type = workload.WorkloadMarker
    monkeypatch.setattr(workload, 'WorkloadMarker', lambda **kwargs: marker_type(**kwargs, boot_id=7))
    def read(runtime):
        assert runtime.policy_path == policy_path and load_policy(runtime.policy_path).f2
        row = account_read(runtime, positions=[{'asset': 't', 'size': '1'}], trades=[{
            'status': 'CONFIRMED', 'maker_orders': [{'order_id': 'o', 'matched_amount': '1'}]}])
        row['balances'] = {'available_collateral': '299.5', 'assets': {ASSET: '299.5'},
                           'collateral_evidence': {'balance': '299500000'}}
        row['capital_activity'] = native_packet(read_activity(MAKER, int(clock.now().timestamp()),
            int(clock.now().timestamp()), get=lambda *a: packet(), sleep=lambda _: None))
        return row
    monkeypatch.setattr(adapter.Runtime, 'account_read_once', read)
    assert not (root / 'campaign.json').exists()
    assert cli.main(['owner-recover-history', '--head', 'f' * 40, '--session', 's',
                     '--campaign', str(policy_path)]) == 0
    ledger = Ledger.open(ledger.path, clock=clock.now)
    assert history_refusals(ledger, root) == {} and ledger.sessions['s'] == original
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == original_files
    book = CapitalBook(ledger)
    figures = book.figures()
    assert figures['funding_native'] == 300_000_000
    assert figures['unrecovered_inventory_cost_native'] == 500_000
    assert figures['retained_gains_available_native'] == figures['segregated_profit_native'] == 0
    assert figures['segregated_incentives_native'] == figures['returned_principal_native'] == 0
    state = AccountState(state_root, ledger)
    with account_lease(MAKER, backend=Mutexes()):
        state.enroll(clock.now())
        state.require_history()
    code_root = tmp_path / 'code'
    (code_root / 'scripts/ops').mkdir(parents=True)
    (code_root / 'scripts/ops/lfc_campaign_windowless.py').write_text('fixture')
    (code_root / 'config').mkdir()
    (code_root / 'config/international_live_execution_host.json').write_text('{}')
    for name in ('python.exe', 'pythonw.exe', 'pregate.json'):
        (tmp_path / name).write_bytes(b'fixture')
    monkeypatch.setattr(release, 'REPO_ROOT', code_root)
    monkeypatch.setattr(release, 'require_current_portable_execution_assignment', lambda: {})
    monkeypatch.setattr(release, 'datetime', SimpleNamespace(now=lambda tz: clock.now()))
    monkeypatch.setattr(release, 'current_execution_host_id', lambda: 'fixture')
    monkeypatch.setattr(release, 'current_execution_principal_id', lambda: 'fixture')
    monkeypatch.setattr(release, 'resolve_production_python_runtime_binding', lambda *a, **kw: {})
    monkeypatch.setattr(release, 'package_binding', lambda name: {})
    monkeypatch.setattr(lfc_pilot, 'pilot_root', lambda: root)
    monkeypatch.setattr(states, 'DEFAULT_STATE_ROOT', state_root)
    monkeypatch.setattr(guard, 'account_lease', lambda maker: account_lease(maker, backend=Mutexes()))
    output = tmp_path / 'release.json'
    sealed = release.seal_release(campaign_path=policy_path, pregate_path=tmp_path / 'pregate.json',
        qualified_head='f' * 40, python_path=tmp_path / 'python.exe', output=output)
    assert output.is_file() and sealed['state_id'] == state.verify()['state_id']
    reopened = Ledger.open(ledger.path, clock=clock.now)
    assert reopened.sessions['s'] == original
    events = [r['event'] for r in reopened.rows]
    assert events.index('capital_bridge') < events.index('owner_history_recovery') < events.index('autostart_enroll')
    assert reopened.counted_sessions() == 1 and state.incidents() == []
