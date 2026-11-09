"""Guards: B074 bounded maximum-breadth result publication and postcheck closure."""
from copy import deepcopy
from types import MethodType, SimpleNamespace
import pytest

from tests.market.lfc_pinb_fixtures import pinb_row
from tests.market.test_lfc_f2_breadth import cities
from tests.market.test_lfc_f2_controller import setup, MAKER
from tests.market.test_lfc_campaign import Mutexes
from tests.market.test_lfc_f2_capital_reads import native_packet, packet
from weather.market.lfc_campaign import CampaignCoordinator
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_proof import local_money_proof
from weather.market.lfc_campaign_reads import ACCOUNT_READ_COMPONENTS
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_campaign_state import StateRefused
from weather.market.lfc_capital import ASSET
from weather.market.lfc_capital_reads import read_activity
from weather.market.lfc_completion import evidence_flags
from weather.market.lfc_f2_evidence import result_file_limit
from weather.market.lfc_recording_io import file_sha, write_new


def test_twelve_bands_at_forty_submits_publish_1027_files_close_and_idle(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        row = pinb_row(); row.update(learning_leg_arms=['paired'], enabled=True)
        controller, account, status, ledger, clock = setup(tmp_path, k=12, policy_row=row,
            universe_rows=cities(), enrolled=True)
        def maximum(self, **kwargs):
            for cycle in range(20):
                self.requotes = min(cycle, 16)
                for leg in self.TRADE_LEGS:
                    yield from self.submit_steps(leg, self.prices[leg])
                for oid in list(self.active): self.cancel_leg(oid)
                yield 1
        for band in controller.bands: band.quote_steps = MethodType(maximum, band)
        result = controller.run()
        assert result['cleanup_ok'] and result['unknown_submit'] is False
        assert all(b.posts == 40 and b.requotes == 16 for b in controller.bands)
        outcome = status.finish(success=True)
        # Exercise the writer's optional seventh root file without asserting
        # that this inert setup used a production go proof.
        go = controller.directory/'go_account.json'
        write_new(go, {'fixture_only': True, 'purpose': 'optional-root-file-inventory'})
        outcome['evidence_sha256']['go_account.json'] = file_sha(go)
        local = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
            attempt_id=controller.attempt_id, outcome=outcome)
        assert local['complete'] and local['unknown_submit'] is False
        runtime = object.__new__(Runtime)
        runtime.pilot_root, runtime.state, runtime.clock = tmp_path, account.state, clock
        runtime.lease = SimpleNamespace(check=lambda: None)
        runtime.control_root = tmp_path/'control'
        runtime.notify_control = lambda row: None
        saved = {'session_id': controller.session_id, 'outcome': outcome, 'exit_code': 0,
            'private_evidence_directory': controller.directory.relative_to(tmp_path).as_posix(),
            **evidence_flags(outcome), 'unknown_submit': False, 'local_money_proof': local,
            'public_coverage': {'configured': False, 'gap': 'not_configured'}}
        assert result_file_limit(ledger, controller.attempt_id) == 1027
        # One extra declared file is refused before any result is published.
        from weather.market import lfc_f2_evidence as evidence
        excessive = deepcopy(evidence.manifest_at(controller.directory))
        excessive['bands'][0]['evidence_sha256']['excess.json'] = 'a'*64
        with monkeypatch.context() as patch:
            patch.setattr(evidence, 'manifest_at', lambda path: excessive)
            with pytest.raises(StateRefused, match='private_file_count'):
                runtime.save_result(account.claim, saved)
        assert not ledger.autostart_results and not ledger.autostart_incidents
        runtime.save_result(account.claim, saved)
        retained = runtime.saved_result(account.claim)
        assert len(retained['private_file_hashes']) == 1027
        runtime.state.retained_result(account.claim)
        def read():
            now = clock.now().isoformat()
            from datetime import datetime
            start = int(datetime.fromisoformat(ledger.rows[0]['recorded_at_utc']).timestamp())
            return {'schema_version': 'lfc_campaign_account_read_v0.1', 'complete': True, 'errors': [],
                'maker_address': MAKER, 'since': str(start), 'scope': 'account_wide_sdk_trades_and_f0_v2_positions',
                'started_at_utc': now, 'ended_at_utc': now,
                'component_times': {k: {'started_at_utc': now, 'ended_at_utc': now} for k in ACCOUNT_READ_COMPONENTS},
                'open_orders': [], 'trades': [], 'positions': [], 'geography': {'blocked': False},
                'balances': {'available_collateral': '300', 'assets': {ASSET: '300'},
                    'collateral_evidence': {'balance': '300000000'}},
                'capital_activity': native_packet(read_activity(MAKER, start, int(clock.now().timestamp()),
                    get=lambda *a: packet(), sleep=lambda _: None))}
        runtime.read_account = read
        proof = runtime.postcheck(account.claim, retained)
        assert proof['money_accounting_complete'] and proof['cleanup_proven'] and proof['unknown_submit'] is False
        runtime.state.close(account.claim, proof, clock.now())
        coordinator = CampaignCoordinator(state=runtime.state, runtime=runtime, clock=clock, control_root=runtime.control_root)
        clock.sleep(3600)  # Today's claim is consumed; the next window is tomorrow.
        runtime.task_enabled = lambda: True
        assert coordinator.tick(lambda: controller.policy) == 'IDLE'
        assert not runtime.state.pending() and not runtime.state.incidents()


def test_legacy_band_metadata_keeps_ten_submit_file_bound():
    starts = {str(i): {'start': {'autostart_attempt_id': 'claim', 'max_submits_per_band': 40}}
              for i in range(12)}
    assert result_file_limit(SimpleNamespace(sessions=starts), 'claim') == 307
