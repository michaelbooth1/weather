"""Desired-behavior regressions for the independent T037 witnesses.

Guards: B032 R1-R4, legacy ambiguity and retained private/public evidence.
All account, clock, process and Scheduler inputs are synthetic.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, NOW, policy_row
from tests.market.test_lfc_campaign_runtime import account_read, runtime_at, health
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_state import AccountState, StateRefused
from weather.market.lfc_recording_io import file_sha, write_new


def reconciled_legacy(tmp_path):
    from tests.market.test_lfc_cli import lost_ack, FakeVenue, venue_order
    from weather.market.lfc_cli import reconcile_ledger
    ledger = lost_ack(tmp_path)
    venue = FakeVenue([], {'o1': {'id': 'o1', 'status': 'CANCELED', 'size_matched': '0'},
                           'o2': venue_order('o2')})
    report, _ = reconcile_ledger(ledger, venue, root=tmp_path, sleep=lambda _: None)
    assert report['adopted_order_ids'] == ['o2'] and report['closed_sessions'] == ['S0c-1']
    assert ledger.sessions['S0c-1']['end']['unknown_submit'] is True
    ledger.clock = Clock().now
    return ledger


def test_witness_enrollment_forgets_legacy_unknown_submission(tmp_path):
    """Real lost-ACK reconcile cannot silently become the owner recovery ceremony."""
    ledger = reconciled_legacy(tmp_path)
    original = deepcopy(ledger.sessions['S0c-1']['end'])
    with account_lease(MAKER, backend=Mutexes()):
        state = AccountState(tmp_path / 'state', ledger)
        with pytest.raises(StateRefused, match='historical_money_ambiguity_requires_owner_recovery'):
            state.enroll(NOW)
        assert not state.root.exists() and ledger.enrollment is None
        assert ledger.sessions['S0c-1']['end'] == original


def test_explicit_owner_history_recovery_preserves_flags_and_consumed_date(tmp_path):
    from weather.market.lfc_campaign_history import history_refusals, record_owner_recovery
    from weather.market.lfc_campaign_runtime import Runtime
    ledger = reconciled_legacy(tmp_path)
    original = deepcopy(ledger.sessions['S0c-1']['end'])
    with account_lease(MAKER, backend=Mutexes()):
        state = AccountState(tmp_path / 'state', ledger)
        runtime = Runtime(state=state, pilot_root=tmp_path, policy_path=tmp_path / 'unused.json', release={}, clock=Clock(),
                          control_root=tmp_path / 'control', task_enabled=lambda: False)
        read = account_read(runtime)
        read['since'] = str(int(datetime.fromisoformat(ledger.rows[0]['recorded_at_utc']).timestamp()))
        proof = runtime.core_proof(ledger, read)
        assert proof['money_accounting_complete'] and proof['cleanup_proven']
        with pytest.raises(ValueError, match='owner_history_repair_required'):
            record_owner_recovery(ledger, tmp_path, 'S0c-1', account_read=read, proof=proof,
                                  now=NOW, containment_proven=False)
        record_owner_recovery(ledger, tmp_path, 'S0c-1', account_read=read, proof=proof,
                              now=NOW, containment_proven=True)
        assert history_refusals(ledger, tmp_path) == {}
        state.enroll(NOW)
        policy = parse_policy(policy_row())
        state.claim(policy.entries[0], policy, NOW)
        assert ledger.sessions['S0c-1']['end'] == original
        recovery = tmp_path / ledger.history_recoveries[0]['file']
        recovery.rename(recovery.with_suffix('.lost'))
        with pytest.raises(StateRefused, match='historical_recovery_evidence_fault'):
            state.require_history()


def test_qualified_intentional_s0_exercises_are_not_blanket_rejected(tmp_path):
    from tests.market.test_lfc_cli import ledger_with_baselines, pass_all_session0
    ledger = ledger_with_baselines(tmp_path)
    pass_all_session0(ledger, tmp_path)
    ledger.clock = Clock().now
    with account_lease(MAKER, backend=Mutexes()):
        state = AccountState(tmp_path / 'state', ledger)
        state.enroll(NOW)
        state.require_history()


def test_proved_f0_history_can_enroll_but_later_legacy_ambiguity_blocks_claim(tmp_path):
    from tests.market.test_lfc_campaign import state_at
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path, Clock())
        state.ledger.record('session_start', session_id='manual', counted=True, owner_local_date='2026-11-10')
        state.ledger.record('session_end', session_id='manual', unknown_submit=True, cleanup_ok=False)
        policy = parse_policy(policy_row())
        with pytest.raises(StateRefused, match='historical_money_ambiguity_requires_owner_recovery'):
            state.claim(policy.entries[0], policy, NOW)
        assert not list((state.root / 'claims').glob('*.json'))


def test_proved_normal_f0_history_remains_enrollable(tmp_path):
    from tests.market.test_lfc_cli import ledger_with_baselines
    ledger = ledger_with_baselines(tmp_path)
    ledger.record('session_start', session_id='proved-F0', counted=True, owner_local_date='2026-11-09')
    ledger.record('session_end', session_id='proved-F0', unknown_submit=False, cleanup_ok=True,
                  inventory_proven=True, evidence_complete=True, reason='fixed_end')
    ledger.clock = Clock().now
    with account_lease(MAKER, backend=Mutexes()):
        AccountState(tmp_path / 'state', ledger).enroll(NOW)
