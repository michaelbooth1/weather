"""Guards: B072 finite per-band limits, legacy defaults and full money evidence."""
from types import MethodType
import pytest

from tests.market.lfc_pinb_fixtures import pinb_row
from tests.market.test_lfc_f2_controller import setup, MAKER
from tests.market.test_lfc_campaign import Mutexes
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_proof import local_money_proof
from weather.market.re1_attended import Session, MAX_SUBMITS, MAX_REQUOTES


def test_pinb_long_session_posts_gtd_against_the_real_1845_end(tmp_path):
    from weather.market.mm_stage2_hold import HoldEnd
    with account_lease(MAKER, backend=Mutexes()):
        row = pinb_row(); row['learning_leg_arms'] = ['paired']
        controller, account, status, ledger, clock = setup(tmp_path, policy_row=row,
            schedule={'max_session_seconds': 35100, 'trading_end_toronto': '18:45:00'})
        def opening_only(self, **kwargs):
            for leg in self.TRADE_LEGS:
                yield from self.submit_steps(leg, self.prices[leg])
            raise HoldEnd('fixture_stop_after_opening')
        for band in controller.bands:
            band.quote_steps = MethodType(opening_only, band)
        result = controller.run()
        assert result['cleanup_ok'] and result['unknown_submit'] is False
        for band, raw in zip(controller.bands, account.raws):
            assert band.planned_seconds == 35100 and band.end.strftime('%H:%M') == '23:45'
            assert len(raw.calls) == 2
            assert all(request['expiration'] == int(band.end.timestamp())+60 for request in raw.calls)


def test_pinb_fortieth_post_is_proved_and_only_exhausted_band_ends(tmp_path):
    with account_lease(MAKER, backend=Mutexes()):
        row = pinb_row(); row['learning_leg_arms'] = ['paired']
        controller, account, status, ledger, clock = setup(tmp_path, policy_row=row)
        first, second = controller.bands
        def many(self, *, rehearsal_seconds=None):
            for _ in range(41):
                yield from self.submit_steps(0, self.prices[0])
                oid = next(oid for oid, (leg, price) in self.active.items() if leg == 0)
                self.cancel_leg(oid)
                yield 1
        first.quote_steps = MethodType(many, first)
        result = controller.run()
        assert first.posts == first.submits == 40
        assert controller.results[first.session_id]['reason'] == 'submit_budget'
        assert controller.results[second.session_id]['reason'] == 'fixed_end' and second.posts == 2
        assert result['cleanup_ok'] and result['unknown_submit'] is False
        outcome = status.finish(success=True)
        proof = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                                 attempt_id='a'*32, outcome=outcome)
        assert proof['complete'] and proof['unknown_submit'] is False
        from weather.market.lfc_campaign_state import AccountState
        from weather.market.lfc_campaign_owner_close import manifest
        originals = manifest(AccountState(tmp_path/'state', ledger), 'a'*32)
        key = 'pilot/'+(first.directory.relative_to(tmp_path)/'submit-40.intent.json').as_posix()
        assert originals[key] and not any(name.endswith('submit-41.intent.json') for name in originals)


def test_pinb_limits_do_not_change_reference_constants(tmp_path):
    assert (MAX_SUBMITS, MAX_REQUOTES) == (10, 4)
    with account_lease(MAKER, backend=Mutexes()):
        row = pinb_row(); row['learning_leg_arms'] = ['paired']
        controller, *_ = setup(tmp_path, policy_row=row)
        assert [(b.MAX_SUBMITS, b.MAX_REQUOTES) for b in controller.bands] == [(40, 16), (40, 16)]
        assert (Session.MAX_SUBMITS, Session.MAX_REQUOTES) == (10, 4)
        for b in controller.bands: b.journal.close()
        controller.journal.close()


def test_pinb_sixteenth_requote_is_proved_and_seventeenth_retires_own_band(tmp_path):
    with account_lease(MAKER, backend=Mutexes()):
        row = pinb_row(); row['learning_leg_arms'] = ['paired']
        controller, account, status, ledger, clock = setup(tmp_path, policy_row=row,
            schedule={'max_session_seconds': 1800, 'trading_end_toronto': '09:30:00'})
        first, second = controller.bands
        original = first.observe_snapshot
        def requote(snapshot):
            result = original(snapshot)
            result['requote_legs'] = [0, 1]
            return result
        first.observe_snapshot = requote
        result = controller.run()
        assert first.requotes == 16 and first.posts == 34
        assert controller.results[first.session_id]['reason'] == 'band_requote_limit'
        assert controller.results[second.session_id]['reason'] == 'fixed_end' and second.requotes == 0
        assert result['cleanup_ok'] and result['unknown_submit'] is False
        outcome = status.finish(success=True)
        proof = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                                 attempt_id='a'*32, outcome=outcome)
        assert proof['complete'] and proof['unknown_submit'] is False
