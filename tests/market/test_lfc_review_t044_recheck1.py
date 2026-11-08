"""Guards: T044 RECHECK1 synthetic attacks on the fourteen fixes. No external IO.

Desired-behavior assertions are retained even when they expose a product defect.
"""
from datetime import datetime, timedelta, timezone
import json

import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_f2_repost import fixture
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_f2_breadth import example_policy
from weather.market.lfc_recording_io import strict_json


def wrapper_deadline(tmp_path, row, start):
    from tests.operations.test_lfc_campaign_task import powershell
    path = tmp_path / 'synthetic-policy.json'
    path.write_text(json.dumps(row))
    result = powershell("(Get-LfcCampaignDeadline -CampaignPath '" + str(path).replace("'", "''") +
        "' -NowUtc ([DateTimeOffset]'" + start.isoformat() + "')).ToString('o')")
    assert result.returncode == 0, result.stderr
    return datetime.fromisoformat(result.stdout.strip())


@pytest.mark.parametrize('delay_seconds,window_end', [(192, '09:15:00'), (2700, '11:00:00')])
@pytest.mark.spawns
def test_wrapper_preserves_child_end_and_cleanup_margin_after_delayed_go(tmp_path, delay_seconds, window_end):
    # Both schedules pass the real v0.3 parser. Delay can be setup or the
    # coordinator's permitted transient admission retries before its date claim.
    row = example_policy()
    row.update(enabled=True, start_window_toronto=['09:00:00', window_end], max_session_seconds=3600)
    policy = parse_policy(row)
    entry = next(e for e in policy.entries if e.local_date == '2026-11-11')
    wrapper_start = entry.start
    actual_start = wrapper_start + timedelta(seconds=delay_seconds)
    assert entry.permits(actual_start)
    child_end = entry.session_end(actual_start)
    deadline = wrapper_deadline(tmp_path, row, wrapper_start)
    assert deadline >= child_end + timedelta(minutes=30), {
        'wrapper_start': str(wrapper_start), 'actual_start': str(actual_start),
        'child_end': str(child_end), 'wrapper_kill': str(deadline),
        'cleanup_seconds': (deadline - child_end).total_seconds()}


@pytest.mark.spawns
def test_unparseable_deadline_policy_keeps_short_refused_window(tmp_path):
    now = datetime(2026, 11, 11, 14, tzinfo=timezone.utc)
    assert wrapper_deadline(tmp_path, {'schema_version': 'lfc_campaign_policy_v0.3'}, now) == now + timedelta(minutes=30)


def test_permanent_peer_private_gap_never_reposts_and_exits_at_session_end(tmp_path, monkeypatch):
    from weather.market import lfc_f2_repost
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, seconds=300)
    peer = controller.bands[1]
    ordinary = lfc_f2_repost.private_fill_proof
    waits = []
    def private(band, **kwargs):
        if band is peer:
            waits.append(clock.seconds)
            raise ValueError('synthetic_peer_private_proof_permanently_unavailable')
        return ordinary(band, **kwargs)
    monkeypatch.setattr(lfc_f2_repost, 'private_fill_proof', private)
    result = controller.run()
    assert waits and controller.bands[0].submits == 2
    assert clock.seconds <= 301 and account.cancel_all_calls == [300]
    assert not result['unknown_submit']
    assert not result['cleanup_ok']  # Missing research proof cannot become COMPLETE.


def test_permanent_peer_cash_gap_is_bounded_and_never_posts_waiting_band(tmp_path, monkeypatch):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, seconds=300)
    account.fills_enabled = False
    raw = account.raws[1]
    ordinary = raw.balances
    waiting = []
    authorize = controller.bands[1].authorize_post
    def start_wait(*args, **kwargs):
        waiting.append(clock.seconds)
        return authorize(*args, **kwargs)
    monkeypatch.setattr(controller.bands[1], 'authorize_post', start_wait)
    def discrepant():
        row = ordinary()
        if waiting:
            row['available_collateral'] = '299'
            row['collateral_evidence']['balance'] = '299000000'
        return row
    monkeypatch.setattr(raw, 'balances', discrepant)
    result = controller.run()
    assert controller.bands[1].posts == 0 and raw.memory.orders == {}
    assert clock.seconds <= 301 and account.cancel_all_calls == [300]
    assert not result['unknown_submit']
    rows = [strict_json(line) for line in controller.bands[1].journal.path.read_bytes().splitlines()]
    assert any(row['event'] == 'f2_peer_cash_wait' for row in rows)


def test_post_reached_then_response_lost_cannot_be_pre_post_abort(tmp_path, monkeypatch):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path)
    account.fills_enabled = False
    raw = account.raws[0]
    ordinary = raw.submit
    posted = []
    def lost(*args, **kwargs):
        response = ordinary(*args, **kwargs)
        posted.append(response)
        raise ConnectionError('synthetic_response_lost_after_post')
    monkeypatch.setattr(raw, 'submit', lost)
    result = controller.run()
    assert len(posted) == 1 and len(ledger.legs) == 1
    assert result['unknown_submit'] and ledger.unacknowledged_intents()
    assert account.raws[1].memory.orders == {}
    for band in controller.bands:
        rows = [strict_json(line) for line in band.journal.path.read_bytes().splitlines()]
        assert not any(row['event'] in {'pre_post_abort', 'submit_deferred'} for row in rows)


def test_refresh_go_rejects_fresh_envelope_with_stale_balance_component(tmp_path, monkeypatch):
    from tests.market.test_lfc_f2_breadth_runtime import owner_runtime_fixture
    from weather.market.lfc_campaign_runtime import ScheduledAuthority
    from weather.market.lfc_campaign_state import StateRefused
    from weather.market.lfc_ledger import Ledger
    ordinary = ScheduledAuthority.refresh_go
    reads = []
    def refresh(self, **kwargs):
        read_account = self.runtime.read_account
        def stale():
            row = read_account()
            stamp = (self.runtime.clock.now() - timedelta(seconds=121)).isoformat()
            row['started_at_utc'] = stamp
            row['component_times']['balances'] = {'started_at_utc': stamp, 'ended_at_utc': stamp}
            reads.append(row)
            return row
        self.runtime.read_account = stale
        return ordinary(self, **kwargs)
    monkeypatch.setattr(ScheduledAuthority, 'refresh_go', refresh)
    with pytest.raises(StateRefused, match='start_window_expired'):
        owner_runtime_fixture(tmp_path, monkeypatch, setup_latency=12)
    ledger = Ledger.open(tmp_path / 'ledger.jsonl', clock=lambda: datetime(2026, 11, 11, 14, 15, tzinfo=timezone.utc))
    assert reads and ledger.legs == {} and len(ledger.autostart_claims) == 1
    assert not ledger.open_sessions()


def test_partial_owner_close_rejects_stale_current_read_without_rewriting_receipt(tmp_path, monkeypatch):
    from tests.market.test_lfc_campaign_recovery import owner_runtime
    from weather.market.lfc_campaign_owner_close import owner_close
    from weather.market.lfc_campaign_state import StateRefused
    from weather.market.lfc_ledger import Ledger
    with account_lease(MAKER, backend=Mutexes()):
        runtime, claim, incident, directory = owner_runtime(tmp_path, monkeypatch)
        ordinary = Ledger.record
        def crash(self, event, **fields):
            if event == 'autostart_owner_close':
                raise OSError('synthetic_power_loss_before_anchor')
            return ordinary(self, event, **fields)
        with monkeypatch.context() as patch:
            patch.setattr(Ledger, 'record', crash)
            with pytest.raises(OSError):
                owner_close(runtime, incident)
        path = runtime.state.root / 'owner-closures' / (incident + '.json')
        original = path.read_bytes()
        runtime.clock.sleep(121)
        with pytest.raises(StateRefused, match='account_read_binding'):
            owner_close(runtime, incident)
        assert path.read_bytes() == original
        assert not any(row['event'] == 'autostart_owner_close' for row in runtime.state.ledger.rows)


def test_repost_money_recovery_cannot_erase_unclassified_evidence_fault(tmp_path):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path)
    controller.bands[0].evidence_failed = True
    result = controller.run()
    assert controller.bands[0].evidence_failed
    assert 'unclassified_core_fault' in controller.bands[0]._evidence_faults
    assert not result['cleanup_ok']


def test_original_twelve_band_witness_with_new_read_allowances(tmp_path, monkeypatch):
    from tests.market.test_lfc_review_t044_setup import test_b058_4_twelve_serial_stream_starts_fit_go_budget
    from tests.market.test_lfc_f2_repost import FundedRaw
    from weather.market.lfc_session_driver import SPENDERS
    ordinary = FundedRaw.balances
    def balances(self):
        row = ordinary(self)
        row['collateral_evidence']['allowances'] = {address.lower(): '300000000' for address in SPENDERS.values()}
        return row
    monkeypatch.setattr(FundedRaw, 'balances', balances)
    test_b058_4_twelve_serial_stream_starts_fit_go_budget(tmp_path, monkeypatch)


@pytest.mark.spawns
def test_original_gui_xml_witness_with_required_release_binding():
    from tests.operations.test_lfc_campaign_task import powershell, BASE
    result = powershell(BASE + '$xml')
    assert result.returncode == 0, result.stderr
    assert 'powershell.exe' not in result.stdout.lower()
    assert 'pythonw.exe' in result.stdout.lower() and 'InteractiveToken' in result.stdout
