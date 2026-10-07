"""Trading readiness must not suppress settlement-valid learning artifacts."""
from pathlib import Path

import pytest

from tests.operations.test_daily_refresh import _args, _settled_barrier_dependency_steps
from weather.operations import daily_refresh as refresh
from weather.operations import daily_refresh_reporting_steps as reports
from weather.operations import daily_refresh_settled_day as barrier
from weather.operations.daily_refresh_lanes import settlement_barrier_blocker, chain_target_settlement_coverage
from weather.operations.daily_refresh_registry import SETTLEMENT_GATED_LEARNING_STEPS

TARGET = '2026-09-23'


@pytest.fixture
def ready_freshness(monkeypatch):
    monkeypatch.setattr(barrier.settled_day_freshness, 'build_freshness_payload',
                        lambda **kw: {'status': 'PASS', 'summary': {}, 'markets': []})
    monkeypatch.setattr(barrier.settled_day_freshness, 'write_outputs',
                        lambda payload, json_path, report_path: (json_path, report_path))


@pytest.mark.parametrize('fault', [None, 'market_day_labels_finalize', 'settlement_source_audit',
                                  'public_wu_settlement_restore', 'replay_status_backfill'])
def test_real_chain_writes_learning_despite_economics_block_but_not_settlement_fault(tmp_path, ready_freshness, fault):
    args = _args(str(tmp_path), settled_analysis_target_date=TARGET)
    steps = _settled_barrier_dependency_steps(TARGET)
    for step in steps:
        if step['name'] in {'exchange_economics_rule_drift', fault}:
            step['result'] = {**step['result'], 'status': 'BLOCK'}
    runners = [(step['name'], lambda args, value=step['result']: value) for step in steps]
    runners.append(('settled_day_analysis_barrier', barrier.run_settled_day_analysis_barrier_step))
    def forbidden_promotion(args):
        pytest.fail('economics block must still prevent promotion')
    runners.append(('promotion_refresh', forbidden_promotion))
    runners.extend((name, getattr(reports, 'run_' + name + '_step'))
                   for name in ('data_retention_inventory', 'daily_learning', 'market_beating_objective_scoreboard'))
    payload, _, _ = refresh.run_daily_refresh(args, runners=runners)
    by_name = {row['name']: row for row in payload['steps']}
    verdict = by_name['settled_day_analysis_barrier']['result']
    assert verdict['status'] == 'BLOCK'
    assert verdict['learning_status'] == ('BLOCK' if fault else 'PASS')
    assert by_name['promotion_refresh']['status'] == 'blocked'
    for name in SETTLEMENT_GATED_LEARNING_STEPS:
        result = by_name[name]['result']
        if fault:
            assert result['reason'] == 'settlement_truth_not_ready'
            assert 'json_out' not in result
        else:
            assert Path(result['json_out']).is_file()
    coverage = chain_target_settlement_coverage(args, payload['steps'])
    assert coverage['target_included'] is (not bool(fault))


@pytest.mark.parametrize('steps', [[], [{'name': 'settled_day_analysis_barrier', 'status': 'ok',
    'result': {'status': 'PASS', 'target_date': '2026-09-22'}}],
    [{'name': 'settled_day_analysis_barrier', 'status': 'error',
      'result': {'status': 'BLOCK', 'learning_status': 'PASS', 'target_date': TARGET}}]])
def test_missing_stale_or_failed_receipts_cannot_admit_learning(tmp_path, steps):
    args = _args(str(tmp_path), settled_analysis_target_date=TARGET)
    args._daily_refresh_steps_so_far = steps
    for name in SETTLEMENT_GATED_LEARNING_STEPS:
        assert getattr(reports, 'run_' + name + '_step')(args)['reason'] == 'settlement_truth_not_ready'


def test_retired_taker_and_maker_steps_are_gone_from_barrier_and_cli(tmp_path, ready_freshness):
    # Retired and deleted 2026-09-29: no barrier dependency, no step, no flag.
    retired = {'taker_finalization_watchdog', 'taker_edge_permission_map',
               'taker_tail_casebook', 'maker_paper_score'}
    args = _args(str(tmp_path), settled_analysis_target_date=TARGET)
    payload = barrier.build_settled_day_analysis_barrier(
        args, steps_so_far=_settled_barrier_dependency_steps(TARGET))
    assert payload['learning_status'] == 'PASS'
    assert not retired & {row['step'] for row in payload['dependencies']}
    assert not retired & {row['step'] for row in barrier.SETTLED_DAY_ANALYSIS_DEPENDENCIES}
    assert '--paper-maker-paused' not in payload['resume_command']
    assert 'trading_evidence' in {row['step'] for row in payload['dependencies']}
    parser = refresh.build_parser()
    for flag in ('--paper-maker-paused', '--skip-taker-finalization-watchdog',
                 '--skip-taker-edge-permission-map', '--skip-taker-tail-casebook'):
        with pytest.raises(SystemExit):
            parser.parse_args(['run', '--dry-run', flag])


def test_old_blocked_receipt_remains_closed_until_barrier_reruns():
    steps = [{'name': 'settled_day_analysis_barrier', 'status': 'error',
              'root_cause_class': 'settled_day_analysis_barrier',
              'result': {'status': 'BLOCK', 'target_date': TARGET}}]
    assert settlement_barrier_blocker(steps, target_date=TARGET, learning_only=True)


@pytest.mark.parametrize('status', ['FAIL', 'UNKNOWN', None])
def test_bad_freshness_never_clears_learning(tmp_path, ready_freshness, monkeypatch, status):
    monkeypatch.setattr(barrier.settled_day_freshness, 'build_freshness_payload', lambda **kw: {'status': status})
    args = _args(str(tmp_path), settled_analysis_target_date=TARGET)
    payload = barrier.build_settled_day_analysis_barrier(args, steps_so_far=_settled_barrier_dependency_steps(TARGET))
    assert payload['learning_status'] == 'BLOCK'


@pytest.mark.parametrize('fault', ['deferred', 'STALE', 'wrong_date', 'floor_hard_stop'])
def test_settlement_receipt_failures_remain_learning_blockers(tmp_path, ready_freshness, fault):
    args = _args(str(tmp_path), settled_analysis_target_date=TARGET)
    steps = _settled_barrier_dependency_steps(TARGET)
    step = next(row for row in steps if row['name'] == 'public_wu_settlement_restore')
    if fault == 'deferred':
        step['status'] = 'deferred'
    elif fault == 'wrong_date':
        step['result']['target_date'] = '2026-09-22'
    elif fault == 'floor_hard_stop':
        step = next(row for row in steps if row['name'] == 'observed_floor_safety_monitor')
        step['result'].update(status='ALERT', hard_stop_pipeline=True)
    else:
        step['result']['status'] = fault
    payload = barrier.build_settled_day_analysis_barrier(args, steps_so_far=steps)
    assert payload['learning_status'] == 'BLOCK'
