"""Independent T044 desired-behavior witnesses.

Guards: retained campaign evidence.

All inputs are synthetic. No account, venue, credential, reader or Scheduler call.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_f2_capital import ledger_at, install, filled
from tests.market.test_lfc_f2_revision import setup
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_capital import CapitalBook, record_activity
from weather.market.lfc_f2_economics import measured
from weather.market.lfc_f2_final import snapshot
from weather.market.lfc_f2_freeze import capture, verify
from weather.market.lfc_recording_io import file_sha


@pytest.fixture(autouse=True)
def account_guard():
    with account_lease(MAKER, backend=Mutexes()):
        yield


def test_confirmation_revision_only_edit_keeps_all_frozen_economic_fills(tmp_path):
    now = datetime(2026, 11, 16, 22, 55, tzinfo=timezone.utc)
    state, clock, policy = setup(tmp_path, now)
    install(state.ledger, cash='300')
    capture(state, policy, now)
    frozen = verify(state)
    edited = parse_policy({**policy.raw, 'policy_revision': policy.raw['policy_revision'] + 1})
    assert state.policy_labels(edited, '2026-11-17')['evidence_lane'] == 'confirmation'
    clock.seconds = (datetime(2026, 11, 17, 14, tzinfo=timezone.utc) - now).total_seconds()
    entry = next(e for e in edited.entries if e.local_date == '2026-11-17')
    claim = state.claim(entry, edited, clock.now())
    assert claim['evidence_lane'] == 'confirmation'
    # claim() binds the real policy metadata to every new session/ledger row.
    filled(state.ledger, 'confirmation-fill', token='111', condition='condition')
    assert state.ledger.sessions['confirmation-fill']['start']['evidence_lane'] == 'confirmation'
    report = snapshot(state.ledger, policy, root=tmp_path,
                      now=datetime(2026, 12, 28, 23, tzinfo=timezone.utc), frozen=frozen)
    assert report['purchase_cost_native']['confirmation'] == 10_000_000, report['purchase_cost_native']


@pytest.mark.parametrize('change', ['economics', 'reverted_after_successor', 'missing_claim', 'foreign_attempt'])
def test_final_confirmation_requires_retained_frozen_economic_claim(tmp_path, change):
    now = datetime(2026, 11, 16, 22, 55, tzinfo=timezone.utc)
    state, clock, policy = setup(tmp_path, now)
    install(state.ledger, cash='300')
    capture(state, policy, now)
    frozen = verify(state)
    clock.seconds = (datetime(2026, 11, 17, 14, tzinfo=timezone.utc) - now).total_seconds()
    raw = {**policy.raw, 'policy_revision': policy.raw['policy_revision'] + 1}
    if change in ('economics', 'reverted_after_successor'): raw['tokens'] = ['YES']
    edited = parse_policy(raw)
    claim = state.claim(next(e for e in edited.entries if e.local_date == '2026-11-17'), edited, clock.now())
    if change == 'reverted_after_successor':
        from tests.market.test_lfc_f2_revision import close_empty
        close_empty(state, claim, clock)
        clock.seconds += 86400
        edited = parse_policy({**policy.raw, 'policy_revision': policy.raw['policy_revision'] + 2})
        claim = state.claim(next(e for e in edited.entries if e.local_date == '2026-11-18'), edited, clock.now())
        assert claim['evidence_lane'] == 'successor_learning'
    if change == 'foreign_attempt': state.ledger.policy_metadata['autostart_attempt_id'] = 'f' * 32
    filled(state.ledger, 'scoped-fill', token='111', condition='condition')
    if change == 'missing_claim':
        (state.root / 'claims' / (claim['local_date'] + '.json')).unlink()
        from weather.operations.live_path_security import LivePathSecurityError
        with pytest.raises(LivePathSecurityError): snapshot(state.ledger, policy, root=tmp_path,
            now=datetime(2026, 12, 28, 23, tzinfo=timezone.utc), frozen=frozen)
    else:
        report = snapshot(state.ledger, policy, root=tmp_path,
            now=datetime(2026, 12, 28, 23, tzinfo=timezone.utc), frozen=frozen)
        assert report['purchase_cost_native'] == {'confirmation': 0, 'learning_and_legacy': 10_000_000}
