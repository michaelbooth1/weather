"""Guards: expanded Pin B submit counts survive the real campaign result writer."""
import pytest
from tests.market.lfc_pinb_fixtures import pinb_row
from tests.market.test_lfc_f2_controller import setup, MAKER
from tests.market.test_lfc_f2_breadth import cities
from tests.market.test_lfc_campaign import Mutexes
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_proof import local_money_proof
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_completion import evidence_flags


@pytest.mark.parametrize('posts_per_band', [10, 12])
def test_twelve_clean_bands_publish_result_after_permitted_requotes(tmp_path, posts_per_band):
    with account_lease(MAKER, backend=Mutexes()):
        row = pinb_row(); row['learning_leg_arms'] = ['paired']
        controller, account, status, ledger, clock = setup(tmp_path, k=12, policy_row=row,
            universe_rows=cities(), enrolled=True, schedule={'max_session_seconds': 420})
        for band in controller.bands:
            ordinary = band.observe_snapshot
            def observation(snapshot, ordinary=ordinary, band=band):
                observed = ordinary(snapshot)
                # Five permitted two-leg re-quotes, following ordinary cancel,
                # submit, intent/ACK, journal, terminal and cleanup code.
                observed['requote_legs'] = [0, 1] if band.requotes < posts_per_band//2-1 else []
                return observed
            band.observe_snapshot = observation
        result = controller.run()
        assert result['cleanup_ok'] and not result['unknown_submit'], result
        assert all(b.posts == posts_per_band and b.requotes <= 16 for b in controller.bands)
        assert not ledger.unresolved_legs() and not ledger.open_sessions()
        outcome = status.finish(success=True)
        local = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
            attempt_id=controller.attempt_id, outcome=outcome)
        assert local['complete'] and not local['unknown_submit'], local
        runtime = object.__new__(Runtime)
        runtime.pilot_root, runtime.state = tmp_path, account.state
        packet = {'session_id': controller.session_id, 'outcome': outcome, 'exit_code': 0,
            'private_evidence_directory': controller.directory.relative_to(tmp_path).as_posix(),
            **evidence_flags(outcome), 'unknown_submit': False, 'local_money_proof': local,
            'public_coverage': {'configured': False, 'gap': 'not_configured'}}
        from weather.market.lfc_campaign_state import StateRefused
        try:
            runtime.save_result(account.claim, packet)
        except StateRefused as exc:
            from weather.market.lfc_campaign import CampaignCoordinator
            from weather.market.lfc_campaign_control import latest_control
            runtime.notify_control = lambda row: None
            coordinator = CampaignCoordinator(state=account.state, runtime=runtime, clock=clock,
                control_root=tmp_path/'control-next')
            next_tick = coordinator.tick(lambda: controller.policy)
            control = latest_control(tmp_path/'control-next')
            assert len(ledger.autostart_incidents) == 1 and not ledger.autostart_results
            assert control['phase'] == 'INCIDENT' and control['incident'] is True
            assert not ledger.unresolved_legs() and not ledger.open_sessions()
            pytest.fail(f'Clean Pin B result was refused: {exc}; next tick {next_tick} emits INCIDENT')
        assert runtime.saved_result(account.claim)['session_id'] == controller.session_id
        assert len(ledger.autostart_results) == 1
