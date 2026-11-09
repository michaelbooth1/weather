"""Guards: B072 separate immutable freeze epochs and unchanged crash recovery."""
from copy import deepcopy
import pytest

from tests.market.lfc_pinb_fixtures import pinb_row
from tests.market.test_lfc_pinb_migration import existing_pina, stamp
from tests.market.test_lfc_campaign import MAKER, Mutexes
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_state import AccountState, StateRefused
from weather.market.lfc_f2_freeze import capture, verify, labels
from weather.market.lfc_ledger import Ledger


@pytest.mark.parametrize('epoch', ['pina', 'pinb'])
def test_each_freeze_epoch_recovers_its_own_interrupted_anchor_without_rewriting(tmp_path, monkeypatch, epoch):
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, old, claim = existing_pina(tmp_path)
        policy = old if epoch == 'pina' else parse_policy(pinb_row())
        when = '2026-11-16T22:55:00Z' if epoch == 'pina' else '2026-11-22T22:55:00Z'
        clock.value = stamp(when)
        ordinary = state.ledger.record
        def interrupted(event, **fields):
            if event == 'autostart_freeze':
                raise OSError('synthetic interruption after receipt')
            return ordinary(event, **fields)
        with monkeypatch.context() as patch:
            patch.setattr(state.ledger, 'record', interrupted)
            with pytest.raises(OSError): capture(state, policy, clock.now())
        name = 'freeze.json' if epoch == 'pina' else 'freeze-pinb.json'
        path = state.root/'policies'/name; original = path.read_bytes()
        state = AccountState(state.root.parent, Ledger.open(state.ledger.path, clock=clock.now))
        clock.sleep(300)
        capture(state, policy, clock.now())
        assert path.read_bytes() == original
        assert verify(state, policy=policy)['on_time'] is True
        assert len(state.ledger.event_rows('autostart_freeze')) == 1


@pytest.mark.parametrize('case', ['missing', 'late', 'edited'])
def test_pinb_missing_late_or_edited_freeze_keeps_trading_in_successor_learning(tmp_path, case):
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, old, claim = existing_pina(tmp_path)
        clock.value = stamp('2026-11-16T22:55:00Z'); capture(state, old, clock.now())
        row = pinb_row(); policy = parse_policy(row)
        if case == 'late':
            clock.value = stamp('2026-11-23T14:00:00Z'); capture(state, policy, clock.now())
        elif case == 'edited':
            clock.value = stamp('2026-11-22T23:50:00Z'); capture(state, policy, clock.now())
            row = deepcopy(row); row.update(confirmation_leg_arm='cheap', policy_revision=row['policy_revision']+1)
            policy = parse_policy(row)
        clock.value = stamp('2026-11-23T14:00:00Z')
        claim = state.claim(next(e for e in policy.entries if e.local_date == '2026-11-23'), policy, clock.now())
        assert claim['evidence_lane'] == 'successor_learning' and not state.incidents()
        assert len(state.ledger.event_rows('capital_bridge')) == 1


@pytest.mark.parametrize('epoch', ['pina', 'pinb'])
def test_new_policy_still_detects_loss_of_either_freeze_original(tmp_path, epoch):
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, old, claim = existing_pina(tmp_path)
        clock.value = stamp('2026-11-16T22:55:00Z'); capture(state, old, clock.now())
        new = parse_policy(pinb_row())
        clock.value = stamp('2026-11-22T22:55:00Z'); capture(state, new, clock.now())
        name = 'freeze.json' if epoch == 'pina' else 'freeze-pinb.json'
        path = state.root/'policies'/name; original = path.read_bytes(); path.unlink()
        with pytest.raises(StateRefused, match='freeze_evidence_fault'):
            verify(state, policy=new)
        path.write_bytes(original)
        assert verify(state, policy=new) and state.incidents()[-1]['artifact'] == 'policies/'+name


def test_retained_pina_confirmation_fills_are_not_pooled_into_pinb_family(tmp_path):
    from tests.market.test_lfc_f2_capital import filled
    from weather.market.lfc_f2_final import snapshot
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, old, claim = existing_pina(tmp_path)
        clock.value = stamp('2026-11-16T22:55:00Z'); capture(state, old, clock.now())
        frozen_a = verify(state, policy=old)
        clock.value = stamp('2026-11-17T14:00:00Z')
        claim = state.claim(next(e for e in old.entries if e.local_date == '2026-11-17'), old, clock.now())
        assert claim['evidence_lane'] == 'confirmation'
        filled(state.ledger, 'retained-A-fill', token='111', condition='old-condition')
        new = parse_policy(pinb_row())
        clock.value = stamp('2026-11-22T23:50:00Z'); capture(state, new, clock.now())
        frozen_b = verify(state, policy=new)
        now = stamp('2026-12-28T23:00:00Z')
        old_report = snapshot(state.ledger, old, root=tmp_path, now=now, frozen=frozen_a)
        new_report = snapshot(state.ledger, new, root=tmp_path, now=now, frozen=frozen_b)
        assert old_report['purchase_cost_native']['confirmation'] == 10_000_000
        assert new_report['purchase_cost_native'] == {'confirmation': 0, 'learning_and_legacy': 10_000_000}
