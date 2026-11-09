"""Guards: B072 same account/capital root and preserved old/new freeze receipts."""
from copy import deepcopy
from datetime import datetime, timezone
import pytest

from tests.market.lfc_pinb_fixtures import pinb_row
from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes
from tests.market.test_lfc_f2_capital import install
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_state import AccountState
from weather.market.lfc_campaign_recovery import close_empty
from weather.market.lfc_f2_breadth import example_policy
from weather.market.lfc_f2_freeze import capture, verify, labels
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_recording_io import file_sha


def stamp(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00'))


def existing_pina(tmp_path):
    clock = Clock(); clock.value = stamp('2026-11-11T14:00:00Z')
    ledger = Ledger.create(tmp_path/'pilot'/'ledger.jsonl', clock=clock.now, maker_address=MAKER)
    install(ledger, cash='300')
    state = AccountState(tmp_path/'state', ledger); state.enroll(clock.now())
    row = example_policy(); row['enabled'] = True
    policy = parse_policy(row)
    claim = state.claim(next(e for e in policy.entries if e.local_date == '2026-11-11'), policy, clock.now())
    close_empty(state, claim, clock.now())
    return state, clock, policy, claim


@pytest.mark.parametrize('old_seal', [False, True])
def test_pinb_takes_over_same_root_without_new_funding_or_date_reset(tmp_path, old_seal):
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, old, old_claim = existing_pina(tmp_path)
        if old_seal:
            clock.value = stamp('2026-11-16T22:55:00Z'); capture(state, old, clock.now())
        original_rows = list(state.ledger.rows)
        before = CapitalBook(state.ledger).figures()
        identity = state.verify()['state_id']
        closed = state.root/'closed'/(old_claim['attempt_id']+'.json'); original_close = closed.read_bytes()
        state = AccountState(state.root.parent, Ledger.open(state.ledger.path, clock=clock.now))
        new = parse_policy(pinb_row())
        clock.value = stamp('2026-11-17T14:00:00Z')
        claim = state.claim(next(e for e in new.entries if e.local_date == '2026-11-17'), new, clock.now())
        assert claim['evidence_lane'] == ('successor_learning' if old_seal else 'learning')
        assert state.verify()['state_id'] == identity
        assert CapitalBook(state.ledger).figures() == before and before['funding_native'] == 300_000_000
        assert state.ledger.rows[:len(original_rows)] == original_rows and closed.read_bytes() == original_close
        assert state.consumed_dates() == {'2026-11-11', '2026-11-17'}
        assert len(state.ledger.event_rows('capital_bridge')) == 1
        close_empty(state, claim, clock.now())
        capture(state, new, clock.now())  # Not yet in the new capture window.
        assert len(state.ledger.event_rows('autostart_freeze')) == int(old_seal)


def test_old_seal_survives_new_capture_and_confirmation_uses_new_family(tmp_path):
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, old, claim = existing_pina(tmp_path)
        clock.value = stamp('2026-11-16T22:55:00Z'); capture(state, old, clock.now())
        old_path = state.root/'policies'/'freeze.json'; original = old_path.read_bytes()
        old_event = state.ledger.event_rows('autostart_freeze')[0]
        new = parse_policy(pinb_row())
        assert labels(state, new, '2026-11-17')['evidence_lane'] == 'successor_learning'
        clock.value = stamp('2026-11-22T22:55:00Z'); capture(state, new, clock.now())
        assert len(state.ledger.event_rows('autostart_freeze')) == 2
        assert old_path.read_bytes() == original and state.ledger.event_rows('autostart_freeze')[0] == old_event
        assert verify(state, policy=old)['policy_sha256'] == old.sha256
        assert verify(state, policy=new)['policy_sha256'] == new.sha256
        assert labels(state, new, '2026-11-23')['evidence_lane'] == 'confirmation'
        changed = deepcopy(new.raw); changed.update(policy_revision=6, quote_offset_pusd='0.025')
        assert labels(state, parse_policy(changed), '2026-11-23')['evidence_lane'] == 'successor_learning'
        state = AccountState(state.root.parent, Ledger.open(state.ledger.path, clock=clock.now))
        state.verify()
        assert verify(state, policy=new)['on_time'] is True


def test_real_legacy_l_and_capital_replay_are_carried_not_reinterpreted(tmp_path):
    from tests.market.test_lfc_review_b060_refill import settled_pair
    with account_lease(MAKER, backend=Mutexes()):
        ledger, state, source, evidence = settled_pair(tmp_path, 'net_of_retained_gains')
        before, old_l = CapitalBook(ledger).figures(), ledger.L()
        assert str(old_l) == '19.20'
        raw = ledger.path.read_bytes()
        policy = parse_policy(pinb_row())
        reopened = Ledger.open(ledger.path, clock=ledger.clock)
        assert reopened.L() == old_l and CapitalBook(reopened).figures() == before
        assert len(reopened.event_rows('capital_bridge')) == 1
        assert reopened.path.read_bytes() == raw and policy.raw['owner_funding_ceiling_pusd'] == '300'


def test_pinb_migration_preserves_a_sticky_ambiguity_and_unknown_intent(tmp_path):
    from weather.market.lfc_campaign_state import StateRefused
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, old, claim = existing_pina(tmp_path)
        state.latch('a'*32, 'ambiguous_placement', clock.now())
        state.ledger.record('session_start', session_id='unknown-A', counted=True)
        state.ledger.intent(session_id='unknown-A', intent_key='unknown-A:1', token_id='t', condition_id='c',
                            price='.5', size='20', fee_rate_bps='0')
        original = list(state.ledger.rows)
        clock.value = stamp('2026-11-17T14:00:00Z')
        state = AccountState(state.root.parent, Ledger.open(state.ledger.path, clock=clock.now))
        policy = parse_policy(pinb_row())
        with pytest.raises(StateRefused):
            state.claim(next(e for e in policy.entries if e.local_date == '2026-11-17'), policy, clock.now())
        assert len(state.ledger.unacknowledged_intents()) == 1
        assert state.ledger.rows[:len(original)] == original
        assert len(state.ledger.autostart_claims) == 1 and state.ledger.autostart_incidents


def test_pinb_does_not_hide_loss_of_a_completed_pina_closure(tmp_path):
    from weather.market.lfc_campaign_state import StateRefused
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, old, claim = existing_pina(tmp_path)
        path = state.root/'closed'/(claim['attempt_id']+'.json'); path.unlink()
        state = AccountState(state.root.parent, Ledger.open(state.ledger.path, clock=clock.now))
        policy = parse_policy(pinb_row()); clock.value = stamp('2026-11-17T14:00:00Z')
        with pytest.raises(StateRefused, match='anchored_closure_evidence_fault'):
            state.claim(next(e for e in policy.entries if e.local_date == '2026-11-17'), policy, clock.now())
        assert not path.exists() and len(state.ledger.autostart_incidents) == 1
        assert len(state.ledger.autostart_claims) == 1
