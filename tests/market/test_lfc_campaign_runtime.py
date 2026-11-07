"""Money-vs-research and optional public recorder contracts, fixture-only.

Guards: T026 M02/M03/M04/M06/S01. Runtime tests never load owner credentials.
"""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, NOW, policy_row, state_at
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_runtime import Runtime, ScheduledAuthority
from weather.market.lfc_campaign_sidecar import cadences, health_receipt, public_environment
from weather.market.lfc_campaign_state import StateRefused
from weather.market.lfc_recording_io import file_sha, write_new
from weather.market.lfc_campaign_proof import local_money_proof
from weather.market.lfc_campaign_workload import WorkloadMarker, owner_clear_after_reboot
from weather.market.lfc_campaign_guard import AdmissionUncertain, OwnedHold


def runtime_at(tmp_path):
    clock = Clock()
    state = state_at(tmp_path, clock)
    path = tmp_path / 'campaign.json'
    path.write_text(json.dumps(policy_row()))
    runtime = Runtime(state=state, pilot_root=state.ledger.path.parent, policy_path=path, release={}, clock=clock,
                      control_root=tmp_path / 'control', task_enabled=lambda: True, hold_path=tmp_path / 'HOLD')
    return runtime


def test_release_parameter_support_covers_policy_and_rejects_stale_or_expanded_contract():
    from weather.market.lfc_campaign_policy import parameter_support
    from weather.market.lfc_campaign_release import validate_parameter_support
    table = parameter_support()
    row = policy_row()
    assert all('terms.' + key in table for key in row['terms'])
    assert set(row) - {'schema_version', 'enabled', 'campaign_id', 'revision', 'timezone', 'terms'} <= set(table)
    assert table['terms.budget_pusd']['max'] == '100'
    assert table['terms.shares_per_leg']['values'] == ['20']
    assert table['terms.k_max']['values'] == [1]
    validate_parameter_support({'parameter_support': table})
    for changed in ({}, {'parameter_support': {}}, {'parameter_support': {
            **table, 'terms.budget_pusd': {'exclusive_min': '0', 'max': '300'}}}):
        with pytest.raises(RuntimeError, match='campaign_parameter_support_changed'):
            validate_parameter_support(changed)


def account_read(runtime, *, positions=(), trades=()):
    return {'schema_version': 'lfc_campaign_account_read_v0.1', 'maker_address': MAKER, 'complete': True,
            'errors': [], 'scope': 'account_wide_sdk_trades_and_f0_v2_positions',
            'since': str(int(NOW.timestamp())), 'started_at_utc': NOW.isoformat(), 'ended_at_utc': NOW.isoformat(),
            'open_orders': [], 'positions': list(positions), 'trades': list(trades), 'balances': {'available_collateral': '100'}}


def fill(runtime, *, size='20', matched='20'):
    ledger = runtime.state.ledger
    ledger.record('session_start', session_id='s', owner_local_date='2026-11-11')
    ledger.intent(session_id='s', intent_key='i', token_id='t', condition_id='c', size=size, price='.5', fee_rate_bps='0')
    ledger.ack('i', 'o')
    ledger.terminal('o', {'id': 'o', 'status': 'CANCELED', 'size_matched': matched}, source='fixture')
    ledger.record('session_end', session_id='s')


def test_money_complete_can_preserve_incomplete_research_without_resetting_raw_flags(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, NOW)
        monkeypatch.setattr(runtime, 'read_account', lambda: account_read(runtime))
        runtime.lease = SimpleNamespace(check=lambda: None)
        result = {'evidence_complete': False, 'inventory_proven': True, 'unknown_submit': False,
                  'public_coverage': {'gap': 'sidecar_failed'}, 'local_money_proof': {'complete': True}}
        proof = runtime.postcheck(claim, result)
        assert proof['money_accounting_complete'] and proof['cleanup_proven']
        assert not proof['research_evidence_complete'] and not proof['raw_evidence_flags']['evidence_complete']
        assert proof['raw_evidence_flags']['unknown_submit'] is False


@pytest.mark.parametrize('change', [
    {'complete': False}, {'maker_address': '0x' + 'b' * 40}, {'schema_version': 'unknown'},
    {'ended_at_utc': (NOW - timedelta(seconds=121)).isoformat()},
    {'ended_at_utc': (NOW + timedelta(seconds=1)).isoformat()}])
def test_core_read_binding_and_actual_observation_time(tmp_path, change):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        row = account_read(runtime)
        row.update(change)
        with pytest.raises(StateRefused, match='account_read_binding'):
            runtime.core_proof(runtime.state.ledger, row)


def test_missing_pilot_holding_is_money_contradiction_and_microfills_are_retained(tmp_path):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        fill(runtime, matched='.000001')
        trades = [{'status': 'CONFIRMED', 'maker_orders': [{'order_id': 'o', 'matched_amount': '.000001'}]}]
        missing = runtime.core_proof(runtime.state.ledger, account_read(runtime, trades=trades))
        assert missing['money_contradiction'] and missing['inventory']['missing_or_below_visibility'] == ['t']
        present = runtime.core_proof(runtime.state.ledger, account_read(runtime, trades=trades,
                                      positions=[{'asset': 't', 'size': '.000001'}]))
        assert present['money_accounting_complete'] and present['cleanup_proven']


def test_postcheck_never_adopts_lost_ack_or_closes_crashed_session(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        ledger = runtime.state.ledger
        ledger.record('session_start', session_id='crashed')
        ledger.intent(session_id='crashed', intent_key='lost', token_id='t', condition_id='c', size='20', price='.5', fee_rate_bps='0')
        runtime.lease = SimpleNamespace(check=lambda: None)
        monkeypatch.setattr(runtime, 'read_account', lambda: pytest.fail('must not manufacture a proof'))
        proof = runtime.postcheck({'attempt_id': 'fixture'}, {'unknown_submit': False})
        assert proof['unknown_submit'] and not proof['cleanup_proven']
        assert ledger.open_sessions() == ['crashed'] and ledger.L() == 10


@pytest.mark.parametrize('bands', [1, 11, 22, 44, 100, 500, 1000])
def test_sidecar_scope_cadences_leave_retry_room_under_two_rps(bands):
    row = cadences(bands)
    independent = (__import__('math').ceil(2 * bands / 100) / row['book_seconds'] +
                   (4 * bands + 1) / row['slow_seconds'] + 1 / 60)
    assert independent == row['nominal_rps'] <= 1.5 < row['hard_rps'] == 2


def test_sidecar_environment_is_public_allowlist(monkeypatch, tmp_path):
    monkeypatch.setenv('FAKE_SECRET', 'never pass')
    monkeypatch.setenv('POLYMM_PRIVATE_KEY', 'fixture never pass')
    monkeypatch.setenv('PYTHONPATH', 'untrusted')
    env = public_environment(tmp_path)
    assert 'FAKE_SECRET' not in env and 'POLYMM_PRIVATE_KEY' not in env and 'PYTHONPATH' not in env


def health(tmp_path, *, gap=False, final=False):
    from datetime import datetime, timezone
    row = {'schema_version': 'fixture', 'receipt_utc': datetime.now(timezone.utc).isoformat(),
           'final': final, 'sealed_chunks': 0, 'counts': {'rest_requests': 1}, 'storage_failed': False,
           'coverage': {'events': {'event': {}}, 'expected_tokens': 2, 'baselines_taken': 2,
                        'coverage_ready': not gap, 'open_intervals': {'gap': {}} if gap else {},
                        'last_transport': {'receipt_utc': datetime.now(timezone.utc).isoformat()},
                        'tokens': {'token': {'source_age_seconds': 900, 'last_rest': {'receipt_utc': NOW.isoformat()}}}}}
    row['health_receipt_sha256'] = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    (tmp_path / 'health.json').write_text(json.dumps(row))
    return row


def test_sidecar_preserves_source_gaps_without_calling_old_book_a_dead_receiver(tmp_path):
    health(tmp_path, gap=True)
    row = health_receipt(tmp_path, event_slug='event', health_schema='fixture')
    assert row['source_gaps'] and not row['research_evidence_complete']
    assert row['coverage']['last_transport'] and row['coverage']['tokens']['token']['source_age_seconds'] == 900


def test_sidecar_final_missing_or_corrupt_chunk_refuses_coverage(tmp_path):
    row = health(tmp_path, final=True)
    row['sealed_chunks'] = 1
    body = {k: v for k, v in row.items() if k != 'health_receipt_sha256'}
    row['health_receipt_sha256'] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    (tmp_path / 'health.json').write_text(json.dumps(row))
    with pytest.raises(ValueError, match='chunks_incomplete'):
        health_receipt(tmp_path, event_slug='event', health_schema='fixture', final=True)
    chunk = tmp_path / 'chunk-000000.jsonl.gz'
    chunk.write_bytes(b'synthetic not a real tape')
    write_new(tmp_path / 'chunk-000000.jsonl.gz.sha256.json', {'file': chunk.name, 'bytes': chunk.stat().st_size,
                                                           'sha256': file_sha(chunk)})
    assert health_receipt(tmp_path, event_slug='event', health_schema='fixture', final=True)['chunk_sha256']
    chunk.write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='chunk_corrupt'):
        health_receipt(tmp_path, event_slug='event', health_schema='fixture', final=True)


def test_local_private_proof_keeps_explained_scoring_gap_and_refuses_unexplained_false(tmp_path):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        fill(runtime, matched='0')
        runtime.state.ledger.sessions['s']['start']['autostart_attempt_id'] = 'a' * 32
        directory = tmp_path / 'private-session'
        directory.mkdir()
        journal = directory / 'journal.jsonl'
        journal.write_text(json.dumps({'event': 'scoring_missed'}) + '\n')
        prediction = {'mode': 'live', 'scope': {'session_id': 's'}, 'unknown_submit': False,
                      'inventory_proven': True, 'evidence_complete': False, 'post_count': 1, 'order_ids': ['o'],
                      'journal_sha256': file_sha(journal), 'failure_type': None}
        write_new(directory / 'prediction.json', prediction)
        write_new(directory / 'session_end.json', {'session_id': 's'})
        outcome = {'evidence_sha256': {name: file_sha(directory / name) for name in
                                      ('journal.jsonl', 'prediction.json', 'session_end.json')}}
        proof = local_money_proof(directory, ledger=runtime.state.ledger, session_id='s', attempt_id='a' * 32, outcome=outcome)
        assert proof['complete'] and not proof['raw_flags']['evidence_complete']
        assert proof['explained_gaps'] == ['scoring_missed']
        journal.write_text(json.dumps({'event': 'ordinary'}) + '\n')
        prediction['journal_sha256'] = file_sha(journal)
        (directory / 'prediction.json').write_text(json.dumps(prediction))
        outcome['evidence_sha256'] = {name: file_sha(directory / name) for name in
                                    ('journal.jsonl', 'prediction.json', 'session_end.json')}
        refused = local_money_proof(directory, ledger=runtime.state.ledger, session_id='s', attempt_id='a' * 32, outcome=outcome)
        assert not refused['complete'] and refused['unknown_submit']
        assert refused['failure'] == 'unexplained_false_evidence_flag'


def test_workload_marker_survives_uncertainty_and_requires_owner_proved_reboot(tmp_path):
    hold_path = tmp_path / 'HOLD'
    hold = OwnedHold(hold_path)
    hold.acquire()
    marker = WorkloadMarker(poison_root=tmp_path, state_id='fixture-state', maker=MAKER, boot_id=7)
    marker.acquire(hold_sha256=hold.sha256, hold_owner=hold.identity)
    original = marker.path.read_bytes()
    with pytest.raises(AdmissionUncertain, match='retained'):
        marker.release(contained=False)
    assert marker.path.read_bytes() == original
    arguments = dict(path=marker.path, expected_sha=marker.sha256, state_id='fixture-state', maker=MAKER,
                     backend=Mutexes(), namespace='fixture', hold_path=hold_path)
    with pytest.raises(AdmissionUncertain, match='terminal'):
        owner_clear_after_reboot(**arguments, boot_id=8, owner_terminal=False)
    with pytest.raises(AdmissionUncertain, match='reboot'):
        owner_clear_after_reboot(**arguments, boot_id=7, owner_terminal=True)
    owner_clear_after_reboot(**arguments, boot_id=8, owner_terminal=True,
                             confirmation='clear workload ' + marker.sha256[:12])
    assert not marker.path.exists() and not hold_path.exists()


def test_claimed_setup_error_still_publishes_policy_bound_outcome(tmp_path, monkeypatch):
    from weather.market import lfc_cli
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        policy = parse_policy(policy_row())
        entry = policy.entries[0]
        claim = runtime.state.claim(entry, policy, NOW)
        runtime.lease = SimpleNamespace(check=lambda: None)
        def failed(*args, **kwargs):
            raise RuntimeError('synthetic setup failure')
        monkeypatch.setattr(lfc_cli, '_run_live', failed)
        with pytest.raises(RuntimeError, match='synthetic setup'):
            runtime.run_session(claim, entry, policy, {'baseline': {}})
        paths = list((runtime.state.root / 'owner-status').glob('*.json'))
        assert len(paths) == 1
        row = json.loads(paths[0].read_text())
        assert row['state'] == 'ATTENTION' and row['unknown_submit'] is True
        assert row['policy_name'] == policy.raw['policy_name'] and row['policy_revision'] == 1
        assert row['halt_reason'] == 'exception_RuntimeError'


def test_regressed_clock_cannot_corrupt_ledger_history(tmp_path):
    from weather.market.lfc_ledger import LedgerUnavailable
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        ledger = runtime.state.ledger
        before = ledger.path.read_bytes()
        runtime.clock.value -= timedelta(seconds=1)
        with pytest.raises(LedgerUnavailable, match='clock_regressed'):
            ledger.record('halt', reason='fixture')
        assert ledger.path.read_bytes() == before


def test_pre_go_receipt_and_selection_are_bound_to_entry_and_claim(tmp_path):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        runtime.lease = SimpleNamespace(check=lambda: None)
        policy = parse_policy(policy_row())
        entry = policy.entries[0]
        directory = runtime.state.root / 'readiness' / 'fixture'
        directory.mkdir(parents=True)
        selection = directory / 'selection.json'
        write_new(selection, {'fixture': 'selection'})
        prepared = {'baseline': {}, 'entry_id': entry.id, 'local_date': entry.local_date,
                    'policy_sha256': policy.sha256, 'account_read': account_read(runtime),
                    'expires_utc': (NOW + timedelta(seconds=120)).isoformat(),
                    'preflight': {'commit': 'f' * 40, 'maker_address': MAKER, 'readiness_directory': 'readiness/fixture',
                                  'selection_sha256': file_sha(selection)}}
        relative = 'prepared/fixture.json'
        sha = runtime.state.save(relative, prepared)
        prepared.update(file=relative, sha256=sha)
        claim = runtime.state.claim(entry, policy, NOW, prepared=prepared)
        authority = ScheduledAuthority(runtime, claim, entry, policy, prepared)
        assert authority.preflight(now=NOW, commit='f' * 40)['commit'] == 'f' * 40
        assert authority.selection() == {'fixture': 'selection'}
        selection.write_text('{"fixture":"changed"}')
        with pytest.raises(StateRefused, match='selection_hash'):
            authority.selection()
        authority.claim = {**claim, 'prepared_sha256': '0' * 64}
        with pytest.raises(StateRefused, match='prepared_hash'):
            authority.preflight(now=NOW, commit='f' * 40)
