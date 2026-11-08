"""Guards: B061 pre-POST exits through private proof, result and campaign latch.

All transport, admission and account reads are inert fixtures. No signing.
"""
from contextlib import contextmanager

import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_f2_repost import fixture
from weather.market.lfc_campaign import CampaignCoordinator
from weather.market.lfc_campaign_guard import account_lease
from weather.market.mm_stage2_hold import HoldEnd


@pytest.mark.parametrize('exit_kind', ['intent_write', 'signed_order_fresh_ask', 'signed_order_binding', 'checkpoint_fill', 'post_ack_lost'])
def test_submit_exit_has_only_proved_monetary_ambiguity_end_to_end(tmp_path, monkeypatch, exit_kind):
    with account_lease(MAKER, backend=Mutexes()):
        from tests.market import test_lfc_f2_repost as transport_fixture
        example = transport_fixture.example_policy
        monkeypatch.setattr(transport_fixture, 'example_policy', lambda: {**example(), 'enabled': True})
        controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, enrolled=True)
        account.fills_enabled = False
        claim, policy = account.claim, controller.policy
        first, peer = controller.bands
        if exit_kind == 'post_ack_lost':
            account.unknown_ack_band = 0
        elif exit_kind == 'intent_write':
            ordinary = ledger.intent
            def refuse(**fields):
                if fields['session_id'] == first.session_id: raise OSError('synthetic before durable intent')
                return ordinary(**fields)
            monkeypatch.setattr(ledger, 'intent', refuse)
        else:
            def refuse(*args, **kwargs):
                if exit_kind == 'checkpoint_fill': raise HoldEnd('fill')
                raise RuntimeError(exit_kind)
            monkeypatch.setattr(account.raws[0], 'submit', refuse)
        runtime.sidecar, runtime.control_root = None, tmp_path / 'control'
        runtime.task_enabled = lambda: True
        runtime.notify_control = lambda row: None
        runtime.pre_go = lambda *args: None
        runtime.lease = object()  # Only a fixture marker; no OS workload admission.
        runtime.read_account = read
        @contextmanager
        def admission(): yield
        runtime.admission = admission
        # The fixture already created the sole claim/session bindings. Reuse
        # that claim at the real coordinator's admission boundary, never another.
        monkeypatch.setattr(runtime.state, 'claim', lambda *args, **kwargs: claim)
        results = []
        def session(*args):
            controller.run()
            outcome = status.finish(success=True)
            result = runtime.session_result(claim, status, outcome, 0)
            results.append(result)
            return result
        runtime.run_session = session
        campaign = CampaignCoordinator(state=runtime.state, runtime=runtime, clock=clock, control_root=runtime.control_root)
        from tests.market.test_lfc_campaign import bind_launch
        policy = bind_launch(campaign, policy)
        assert campaign.start(controller.entry, policy, lambda: policy) == 'STARTED'
        if exit_kind == 'post_ack_lost':
            assert results[0]['unknown_submit'] is True
            assert runtime.state.ledger.unacknowledged_intents()
            assert any(row['reason'] == 'ambiguous_placement' for row in runtime.state.incidents())
            assert peer.posts == 0  # An actual unproved POST stops the account.
            return
        assert len(results) == 1 and results[0]['unknown_submit'] is False, results
        assert results[0]['local_money_proof']['complete'], results[0]['local_money_proof']
        assert not runtime.state.incidents() and not runtime.state.pending()
        assert not ledger.unacknowledged_intents()
        assert first.posts == 0 and not account.raws[0].memory.orders
        assert peer.posts == 2 and peer.session_id in controller.closed_bands
        assert account.cancel_all_calls == [300]  # Peer kept quoting to fixed end.
        assert controller.results[first.session_id]['failure_type'] is None


def test_missing_private_evidence_is_a_fault_but_never_invents_a_submission(tmp_path):
    with account_lease(MAKER, backend=Mutexes()):
        controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, enrolled=True)
        account.fills_enabled = False
        controller.run()
        outcome = status.finish(success=True)
        (controller.bands[0].directory / 'journal.jsonl').unlink()
        runtime.sidecar = None
        result = runtime.session_result(account.claim, status, outcome, 0)
        assert not result['unknown_submit'] and not result['local_money_proof']['complete']
        assert not result['local_money_proof']['unknown_submit']
