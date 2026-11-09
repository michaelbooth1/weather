"""Guards: B075 requote not_canceled needs a terminal read, never an assumed cancel."""
from types import SimpleNamespace
import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_f2_repost import fixture
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_proof import local_money_proof
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_recording_io import strict_json
from weather.market.lfc_f2_controller import F2Band
from weather.market.re1_attended import Session
from weather.market.mm_stage2_hold import HoldEnd


def test_legacy_requote_cancel_guard_remains_strict():
    with pytest.raises(RuntimeError, match='no complete acknowledgment list'):
        Session.check_requote_cancel_response(None, 'known', {'canceled': [], 'not_canceled': {'known': 'matched'}})


@pytest.mark.parametrize('reply', [None, {'canceled': [], 'not_canceled': {'foreign': 'matched'}},
                                 {'canceled': [], 'not_canceled': ['known']}])
def test_f2_does_not_accept_a_malformed_or_unrelated_cancel_reply(reply):
    band = object.__new__(F2Band)
    with pytest.raises((RuntimeError, HoldEnd)):
        band.check_requote_cancel_response('known', reply)


def racing_cancel(controller, account, *, filled):
    first = controller.bands[0]; raw = account.raws[0]
    account.fills_enabled = False
    ordinary_observe, ordinary_cancel = first.observe_snapshot, raw.cancel
    raced = []
    def observation(snapshot):
        observed = ordinary_observe(snapshot)
        observed['requote_legs'] = [0] if first.posts == 2 and not raced and account.clock.seconds >= 60 else []
        return observed
    def cancel(oid):
        if not raced:
            raced.append(oid)
            if filled:
                row = raw.memory.orders[oid]
                row.update(status='MATCHED', size_matched=row['original_size'], associate_trades=['fill-'+oid])
                account.fill_times.append(account.clock.seconds)
        if oid == raced[0]:
            raw.cancellations.append((account.clock.seconds, oid))
            return {'canceled': [], 'not_canceled': {oid: 'already matched' if filled else 'still open'}}
        return ordinary_cancel(oid)
    first.observe_snapshot, raw.cancel = observation, cancel
    return raced


def test_requote_cancel_loses_to_fill_reposts_and_closes_without_incident(tmp_path):
    with account_lease(MAKER, backend=Mutexes()):
        controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, enrolled=True, seconds=600)
        raced = racing_cancel(controller, account, filled=True)
        result = controller.run(); first, peer = controller.bands
        assert raced and first.posts == 4, controller.results
        assert controller.results[first.session_id]['reason'] == 'fixed_end'
        assert controller.results[first.session_id]['failure_type'] is None
        assert peer.posts == 2 and result['cleanup_ok'] and result['unknown_submit'] is False
        rows = [strict_json(line) for line in first.journal.path.read_bytes().splitlines()]
        assert any(r['event'] == 'cancel_response' and r['response'].get('not_canceled') for r in rows)
        assert any(r['event'] == 'repost_ready' for r in rows)
        outcome = status.finish(success=True)
        local = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
            attempt_id=controller.attempt_id, outcome=outcome)
        assert local['complete'] and local['money_read_gaps'] == [] and not local['unknown_submit']
        runtime.lease = SimpleNamespace(check=lambda: None); runtime.control_root = tmp_path/'control'
        runtime.read_account = read
        runtime.save_result(account.claim, {'session_id': controller.session_id,
            'private_evidence_directory': controller.directory.name, 'outcome': outcome,
            'local_money_proof': local, 'evidence_complete': True, 'inventory_proven': True,
            'unknown_submit': False})
        proof = runtime.postcheck(account.claim, runtime.saved_result(account.claim))
        assert proof['money_accounting_complete'] and proof['cleanup_proven']
        runtime.state.close(account.claim, proof, clock.now())
        runtime.state.require_retained_evidence()
        assert runtime.state.pending() == [] and runtime.state.incidents() == []


def test_requote_not_canceled_still_live_exhausts_bound_without_reposting(tmp_path):
    with account_lease(MAKER, backend=Mutexes()):
        controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, enrolled=True, seconds=600)
        raced = racing_cancel(controller, account, filled=False)
        result = controller.run(); first = controller.bands[0]
        assert raced and first.posts == 2
        assert controller.results[first.session_id]['reason'] == 'cancel_not_terminal', controller.results
        assert controller.results[first.session_id]['failure_type'] is None
        rows = [strict_json(line) for line in first.journal.path.read_bytes().splitlines()]
        assert not any(r['event'] == 'repost_ready' for r in rows)
        assert result['reason'] == 'f2_band_money_or_core_fault' and not result['cleanup_ok']
        assert result['unknown_submit'] is False and clock.seconds < 600
        assert account.open_orders() and ledger.unresolved_legs()
        assert CapitalBook(ledger).figures()['resting_reserve_native'] > 0
        outcome = status.finish(success=False)
        local = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
            attempt_id=controller.attempt_id, outcome=outcome)
        assert local['complete'] and not local['unknown_submit'] and local['money_read_gaps']
