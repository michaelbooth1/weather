"""F2 versions and research lanes survive config changes and reboot.

Guards: B036 next-unclaimed revision, fixed calendar and no confirmation laundering.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from tests.market.test_lfc_campaign import Mutexes
from tests.market.test_lfc_f2_capital import MAKER
from tests.market.test_lfc_pilot import Clock
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_state import AccountState, StateRefused
from weather.market.lfc_f2_freeze import capture
from weather.market.lfc_f2_policy import example_policy
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_recording_io import file_sha


def setup(tmp_path, now):
    clock = Clock(now)
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=clock.now, maker_address=MAKER)
    state = AccountState(tmp_path / 'state', ledger)
    state.enroll(clock.now())
    return state, clock, parse_policy(example_policy())


def close_empty(state, claim, clock):
    state.close(claim, {'unknown_submit': False, 'cleanup_proven': True,
                        'money_accounting_complete': True}, clock.now())


def test_economic_change_needs_new_revision_and_applies_next_unclaimed_session(tmp_path):
    now = datetime(2026, 11, 11, 14, tzinfo=timezone.utc)
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, policy = setup(tmp_path, now)
        entry = next(e for e in policy.entries if e.local_date == '2026-11-11')
        claim = state.claim(entry, policy, clock.now())
        original = (state.root / 'policies' / (claim['attempt_id'] + '.json')).read_bytes()
        close_empty(state, claim, clock)
        changed = deepcopy(policy.raw)
        changed.update(quote_offset_pusd='.025', requote_distance_cents=['2', '4'])
        clock.seconds = 86400
        next_entry = next(e for e in policy.entries if e.local_date == '2026-11-12')
        with pytest.raises(StateRefused, match='economic_policy_change_requires_revision'):
            state.claim(next_entry, parse_policy(changed), clock.now())
        assert '2026-11-12' not in state.consumed_dates()
        changed['policy_revision'] = 2
        next_claim = state.claim(next_entry, parse_policy(changed), clock.now())
        assert next_claim['policy_revision'] == 2 and next_claim['policy_sha256'] != claim['policy_sha256']
        assert (state.root / 'policies' / (claim['attempt_id'] + '.json')).read_bytes() == original


def test_automatic_freeze_and_successor_learning_persist_across_reboot(tmp_path):
    now = datetime(2026, 11, 16, 22, 55, tzinfo=timezone.utc)
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, policy = setup(tmp_path, now)
        capture(state, policy, clock.now())
        frozen = (state.root / 'policies' / 'freeze.json').read_bytes()
        assert state.policy_labels(policy, '2026-11-17')['evidence_lane'] == 'confirmation'
        changed = deepcopy(policy.raw)
        changed.update(policy_revision=2, tokens=['YES'])
        changed = parse_policy(changed)
        clock.seconds = (datetime(2026, 11, 17, 14, tzinfo=timezone.utc) - now).total_seconds()
        entry = next(e for e in changed.entries if e.local_date == '2026-11-17')
        claim = state.claim(entry, changed, clock.now())
        assert claim['evidence_lane'] == 'successor_learning'
        close_empty(state, claim, clock)
        ledger = Ledger.open(state.ledger.path, clock=clock.now)
        state = AccountState(state.root.parent, ledger)
        state.verify()
        back = deepcopy(policy.raw)
        back['policy_revision'] = 3
        assert state.policy_labels(parse_policy(back), '2026-11-18')['evidence_lane'] == 'successor_learning'
        assert (state.root / 'policies' / 'freeze.json').read_bytes() == frozen


@pytest.mark.parametrize('late', [False, True])
def test_missing_or_late_freeze_never_claims_confirmation_and_never_blocks_learning(tmp_path, late):
    now = datetime(2026, 11, 17, 14, tzinfo=timezone.utc)
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, policy = setup(tmp_path, now)
        if late:
            capture(state, policy, now)
        entry = next(e for e in policy.entries if e.local_date == '2026-11-17')
        claim = state.claim(entry, policy, now)
        assert claim['evidence_lane'] == 'successor_learning'
        assert state.pending() == [claim]


def test_freeze_original_loss_latches_N1_and_restoration_does_not_clear_it(tmp_path):
    now = datetime(2026, 11, 16, 22, 55, tzinfo=timezone.utc)
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, policy = setup(tmp_path, now)
        capture(state, policy, now)
        path = state.root / 'policies' / 'freeze.json'
        original = path.read_bytes()
        path.unlink()
        with pytest.raises(StateRefused, match='freeze_evidence_fault'):
            state.verify()
        path.write_bytes(original)
        assert state.verify() and state.incidents()
        assert state.incidents()[0]['artifact'] == 'policies/freeze.json'


def test_partial_unanchored_freeze_is_not_adopted_or_a_trading_arm(tmp_path):
    now = datetime(2026, 11, 16, 22, 55, tzinfo=timezone.utc)
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, policy = setup(tmp_path, now)
        state.save('policies/freeze.json', {'partial_write': True})
        capture(state, policy, now)
        assert not any(row['event'] == 'autostart_freeze' for row in state.ledger.rows)
        assert state.policy_labels(policy, '2026-11-17')['evidence_lane'] == 'successor_learning'
        assert not state.incidents()
