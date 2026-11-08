"""Owner task visibility, independent work lock and recoverable freeze window.

Guards: B046 B2-B4; no Scheduler API, real toast or pilot-root access.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.market.test_lfc_campaign import Mutexes, MAKER, StubRuntime
from tests.market.test_lfc_f2_revision import setup
from weather.market.lfc_campaign import CampaignCoordinator
from weather.market.lfc_campaign_guard import account_lease, CAMPAIGN_WORK_LOCK, HOLD_PATH
from weather.market.lfc_f2_freeze import capture, verify


@pytest.mark.parametrize('stamp,timely', [('2026-11-16T22:55:00+00:00', True),
    ('2026-11-16T23:05:00+00:00', True), ('2026-11-17T13:54:59+00:00', True),
    ('2026-11-17T13:55:00+00:00', True), ('2026-11-17T13:55:01+00:00', False)])
def test_first_healthy_tick_has_the_entire_approved_freeze_window(tmp_path, stamp, timely):
    now = datetime.fromisoformat(stamp)
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, policy = setup(tmp_path, now)
        capture(state, policy, now)
        frozen = verify(state)
        assert frozen['on_time'] is timely
        assert frozen['captured_at_utc'] == now.isoformat()
        assert state.policy_labels(policy, '2026-11-17')['evidence_lane'] == ('confirmation' if timely else 'successor_learning')


def test_freeze_capture_precedes_existing_incident_early_return(tmp_path):
    now = datetime(2026, 11, 17, 13, 54, tzinfo=timezone.utc)
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, policy = setup(tmp_path, now)
        state.latch('a' * 32, 'clock_or_resume_uncertain', now)
        runtime = StubRuntime(state, clock)
        coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
        assert coordinator.tick(lambda: policy) == 'INCIDENT'
        assert verify(state)['on_time'] is True
        assert state.incidents() and runtime.go_count == 0


def test_freeze_capture_precedes_an_ambiguous_pending_claim(tmp_path):
    from datetime import timedelta
    now = datetime(2026, 11, 15, 14, tzinfo=timezone.utc)
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, policy = setup(tmp_path, now)
        entry = next(e for e in policy.entries if e.local_date == '2026-11-15')
        claim = state.claim(entry, policy, now)
        state.ledger.record('session_start', session_id='pending', counted=True,
                            autostart_attempt_id=claim['attempt_id'])
        state.ledger.intent(session_id='pending', intent_key='lost-ack', token_id='111',
                            condition_id='c', size='20', price='.4', fee_rate_bps='0')
        clock.seconds = (datetime(2026, 11, 16, 23, 5, tzinfo=timezone.utc) - now).total_seconds()
        runtime = StubRuntime(state, clock)
        coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
        assert coordinator.tick(lambda: policy) == 'POSTCHECKS'
        assert verify(state)['on_time'] is True
        assert state.pending() and state.incidents() and runtime.go_count == 0


def test_missing_timely_freeze_emits_an_evidence_gap_notice(tmp_path):
    now = datetime(2026, 11, 17, 14, tzinfo=timezone.utc)
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, policy = setup(tmp_path, now)
        runtime = StubRuntime(state, clock)
        notices = []
        runtime.notify_control = notices.append
        coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
        assert coordinator.tick(lambda: policy) == 'DISABLED'
        assert any(row['phase'] == 'EVIDENCE_GAP' and row['reason'] == 'freeze_missing' and row['research_gaps']
                   for row in notices)
        assert verify(state)['on_time'] is False


def test_manual_heavy_hold_is_observed_but_never_owned_or_removed(tmp_path):
    from tests.market.test_lfc_campaign_runtime import runtime_at
    from weather.market.lfc_campaign_guard import AdmissionBusy
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        runtime.heavy_hold_path.write_text('fixture master hold')
        with pytest.raises(AdmissionBusy, match='agent_heavy_hold'):
            with runtime.admission():
                pytest.fail('manual hold must refuse before all-slot or live ownership')
        assert runtime.heavy_hold_path.read_text() == 'fixture master hold'
        assert not runtime.hold_path.exists()


def test_campaign_owns_no_agent_hold_path():
    assert CAMPAIGN_WORK_LOCK != HOLD_PATH
    assert CAMPAIGN_WORK_LOCK.name == 'campaign-work.lock'
    assert HOLD_PATH == Path(r'C:\t\codex\HOLD_HEAVY')


def test_missing_freeze_toast_contains_only_the_safe_reason(tmp_path):
    from weather.market.lfc_pilot import notify_owner
    status = {'phase': 'EVIDENCE_GAP', 'attempt_id': 'a' * 32,
              'orders_open_unproven': False, 'reason': 'freeze_missing'}
    row = notify_owner(tmp_path, {}, windows=False, printer=lambda *a, **k: None, public_status=status)
    assert 'reason=freeze_missing' in row['result_line'] and not row['toast_delivered']
    with pytest.raises(ValueError, match='notification_public_status'):
        notify_owner(tmp_path, {}, windows=False, public_status={**status, 'reason': 'PRIVATE_VALUE'})


@pytest.mark.spawns
@pytest.mark.skipif(os.name != 'nt', reason='native headless Windows process contract')
def test_headless_console_has_no_visible_window_and_preserves_process_session(tmp_path):
    import ctypes
    from tests.operations.test_lfc_campaign_task import powershell, BASE
    result = powershell(BASE + '$xml')
    assert result.returncode == 0, result.stderr
    import xml.etree.ElementTree as ET
    tree = ET.fromstring(result.stdout)
    ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
    command = tree.findtext('.//t:Exec/t:Command', namespaces=ns)
    arguments = tree.findtext('.//t:Exec/t:Arguments', namespaces=ns)
    assert Path(command).name.lower() == 'powershell.exe'
    assert '"-WindowStyle" "Hidden"' in arguments
    assert tree.findtext('.//t:LogonType', namespaces=ns) == 'InteractiveToken'
    marker = tmp_path / 'headless-child.json'
    helper = tmp_path / 'headless-fixture.ps1'
    helper.write_text('''Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class FixtureConsole {
 [DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hwnd);
 [DllImport("kernel32.dll")] public static extern bool ProcessIdToSessionId(uint pid, out uint sid);
}
'@
$session=[uint32]0
if(-not [FixtureConsole]::ProcessIdToSessionId($PID,[ref]$session)){throw 'fixture session'}
Start-Sleep -Milliseconds 600
@{session=$session;visible=[FixtureConsole]::IsWindowVisible([FixtureConsole]::GetConsoleWindow())} | ConvertTo-Json -Compress | Set-Content -LiteralPath 'REPLACE_MARKER'
'''.replace('REPLACE_MARKER', str(marker).replace("'", "''")))
    import time
    started = time.monotonic()
    child = subprocess.run([command, '-NoProfile', '-NonInteractive',
                            '-WindowStyle', 'Hidden', '-File', str(helper)], timeout=20,
                           creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True)
    (tmp_path / 'headless-stdout.txt').write_bytes(child.stdout)
    (tmp_path / 'headless-stderr.txt').write_bytes(child.stderr)
    assert child.returncode == 0 and marker.exists()
    assert time.monotonic() - started >= .6
    observed = json.loads(marker.read_text())
    session = ctypes.c_ulong()
    assert ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session))
    assert not observed['visible'] and observed['session'] == session.value
