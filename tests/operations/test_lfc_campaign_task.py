"""Pure task XML/identity tests; never access the real Windows Scheduler.

Guards: T026 M01/S01 owner-only Interactive/Limited finite disabled task and readback.
"""
import json
import os
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.powershell_host import run_command
from weather.market import lfc_campaign_release as release
from weather.paths import REPO_ROOT


CONTRACT = REPO_ROOT / 'scripts/ops/lfc_campaign_task_contract.ps1'


def powershell(body):
    script = str(CONTRACT).replace("'", "''")
    return run_command(f". '{script}'; " + body)


@pytest.mark.spawns
def test_all_campaign_scripts_parse_without_execution():
    paths = [str(REPO_ROOT / 'scripts/ops' / name).replace("'", "''") for name in
             ('lfc_campaign_task.ps1', 'lfc_campaign_task_contract.ps1', 'register_lfc_campaign_task.ps1')]
    result = run_command("$errorsFound=@(); foreach($path in @(" + ','.join("'" + p + "'" for p in paths) +
                         ")) {$tokens=$null; $errors=$null; [void][Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors); $errorsFound+=@($errors)}; @($errorsFound | ForEach-Object {$_.Message}) | ConvertTo-Json -Compress")
    assert result.returncode == 0 and result.stdout.strip() in ('', '[]', 'null')


@pytest.mark.spawns
def test_dot_sourced_contract_preserves_registrar_and_wrapper_arguments():
    script = str(CONTRACT).replace("'", "''")
    result = run_command("$Action='Register'; $ReleasePath='C:\\fixture\\release.json'; $ReleaseSha256='a'*64; " +
                         f". '{script}'; " +
                         "@{action=$Action;path=$ReleasePath;sha=$ReleaseSha256} | ConvertTo-Json -Compress")
    assert result.returncode == 0, result.stderr
    row = json.loads(result.stdout)
    assert row == {'action': 'Register', 'path': r'C:\fixture\release.json', 'sha': 'a' * 64}


BASE = r"""
$r=[pscustomobject]@{root='C:\fixture pin';task_name='WeatherLFCCampaign'}
$xml=New-LfcCampaignTaskXml -Release $r -ReleasePath 'C:\fixture\release.json' -ReleaseSha256 ('a'*64) -OwnerSid 'S-1-5-21-1-2-3-1001'
"""


@pytest.mark.spawns
def test_task_registered_disabled_then_actual_enabled_state_is_read():
    result = powershell(BASE + r"""
$disabled=Assert-LfcCampaignTaskXml -Actual $xml -Expected $xml
$enabledXml=$xml.Replace('<Enabled>false</Enabled>','<Enabled>true</Enabled>')
$enabled=Assert-LfcCampaignTaskXml -Actual $enabledXml -Expected $xml
@{disabled=$disabled;enabled=$enabled;xml=$xml} | ConvertTo-Json -Compress
""")
    assert result.returncode == 0, result.stderr
    row = json.loads(result.stdout)
    assert row['disabled'] is False and row['enabled'] is True
    import xml.etree.ElementTree as ET
    root = ET.fromstring(row['xml'])
    ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
    assert root.findtext('.//t:LogonType', namespaces=ns) == 'InteractiveToken'
    assert root.findtext('.//t:RunLevel', namespaces=ns) == 'LeastPrivilege'
    assert root.findtext('.//t:StartWhenAvailable', namespaces=ns) == 'false'
    assert root.findtext('.//t:WakeToRun', namespaces=ns) == 'false'
    assert root.findtext('.//t:AllowStartOnDemand', namespaces=ns) == 'false'
    assert root.findtext('.//t:MultipleInstancesPolicy', namespaces=ns) == 'IgnoreNew'
    assert root.findtext('.//t:StartBoundary', namespaces=ns) == '2026-11-10T00:00:00'
    assert root.findtext('.//t:EndBoundary', namespaces=ns) == '2027-01-01T00:00:00'
    assert root.findtext('.//t:Repetition/t:Duration', namespaces=ns) == 'P52D'
    assert root.find('.//t:TimeTrigger', ns) is not None and root.find('.//t:CalendarTrigger', ns) is None


@pytest.mark.spawns
@pytest.mark.parametrize('before,after', [
    ('<WakeToRun>false</WakeToRun>', '<WakeToRun>true</WakeToRun>'),
    ('<StartWhenAvailable>false</StartWhenAvailable>', '<StartWhenAvailable>true</StartWhenAvailable>'),
    ('<LogonType>InteractiveToken</LogonType>', '<LogonType>S4U</LogonType>'),
    ('<RunLevel>LeastPrivilege</RunLevel>', '<RunLevel>HighestAvailable</RunLevel>'),
    ('<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>', '<MultipleInstancesPolicy>Parallel</MultipleInstancesPolicy>'),
    ('<Interval>PT5M</Interval>', '<Interval>PT1M</Interval>'),
    ('</Settings>', '<RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure></Settings>'),
    ('</Actions>', '<Exec><Command>other.exe</Command></Exec></Actions>'),
    ('<AllowStartOnDemand>false</AllowStartOnDemand>', '<AllowStartOnDemand>true</AllowStartOnDemand>')])
def test_task_definition_mutation_refused(before, after):
    result = powershell(BASE + "$changed=$xml.Replace('" + before + "','" + after + "'); " +
                        "try { [void](Assert-LfcCampaignTaskXml -Actual $changed -Expected $xml); 'BAD' } catch { 'REFUSED' }")
    assert result.returncode == 0 and result.stdout.strip() == 'REFUSED'


@pytest.mark.parametrize('code,row,expected', [
    (0, {'schema_version': 'lfc_campaign_task_read_v0.1', 'definition_valid': True, 'enabled': True,
         'release_sha256': 'a' * 64}, True),
    (0, {'schema_version': 'lfc_campaign_task_read_v0.1', 'definition_valid': True, 'enabled': False,
         'release_sha256': 'a' * 64}, False),
    (1, {'enabled': True}, None), (0, {'enabled': True}, None),
    (0, {'schema_version': 'lfc_campaign_task_read_v0.1', 'definition_valid': True, 'enabled': 1,
         'release_sha256': 'a' * 64}, None)])
def test_fresh_task_state_is_strict_and_bound(monkeypatch, code, row, expected):
    monkeypatch.setattr(release.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=code, stdout=json.dumps(row)))
    if expected is None:
        with pytest.raises(RuntimeError, match='readback'):
            release.task_enabled({}, Path('fixture.json'), 'a' * 64)
    else:
        assert release.task_enabled({}, Path('fixture.json'), 'a' * 64) is expected


@pytest.mark.skipif(os.name != 'nt', reason='native Windows mutex contract')
@pytest.mark.parametrize('suffix', ['', '.Exclusive', '.Slot8'])
def test_native_mutex_domains_refuse_overlapping_compatibility_slots(tmp_path, suffix):
    from weather.market.lfc_campaign_guard import AdmissionBusy, ExclusiveWorkload, WindowsMutexes, account_lease
    from tests.market.test_lfc_campaign import MAKER, Mutexes
    prefix = 'Local\\CodexLFCFixture.' + uuid.uuid4().hex
    acquired, stop = threading.Event(), threading.Event()
    errors = []
    def hold():
        backend = WindowsMutexes()
        try:
            handle = backend.acquire(prefix + suffix)
            acquired.set()
            stop.wait(15)
            backend.release(handle)
        except BaseException as exc:
            errors.append(type(exc).__name__)
            acquired.set()
    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert acquired.wait(10) and not errors
        with account_lease(MAKER, backend=Mutexes()):
            with pytest.raises(AdmissionBusy):
                with ExclusiveWorkload(MAKER, backend=WindowsMutexes(), namespace=prefix, poison_root=tmp_path):
                    pytest.fail('overlapping native slot admitted')
    finally:
        stop.set()
        thread.join(10)
    assert not thread.is_alive() and not errors


@pytest.mark.skipif(os.name != 'nt', reason='native Windows abandoned mutex contract')
def test_native_abandoned_mutex_is_refused_without_recovery():
    from ctypes import wintypes
    from weather.market.lfc_campaign_guard import AdmissionUncertain, WindowsMutexes
    backend = WindowsMutexes()
    name = 'Local\\CodexLFCFixture.' + uuid.uuid4().hex
    handles = []
    ready, leave = threading.Event(), threading.Event()
    def hold_until_native_handle_opened():
        try:
            handles.append(backend.acquire(name))
        finally:
            ready.set()
        leave.wait(10)
    thread = threading.Thread(target=hold_until_native_handle_opened)
    thread.start()
    native_thread = None
    try:
        assert ready.wait(10) and len(handles) == 1
        backend.api.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        backend.api.OpenThread.restype = wintypes.HANDLE
        native_thread = backend.api.OpenThread(0x00100000, False, thread.native_id)  # SYNCHRONIZE only
        assert native_thread
        leave.set()
        # Python join can finish before Windows signals native thread death;
        # only native termination proves that this mutex has been abandoned.
        assert backend.api.WaitForSingleObject(native_thread, 10000) == 0
        thread.join(10)
        assert not thread.is_alive()
        with pytest.raises(AdmissionUncertain, match='abandoned'):
            backend.acquire(name)
    finally:
        leave.set()
        thread.join(10)
        if native_thread:
            backend.api.CloseHandle(native_thread)
        for handle in handles:
            backend.api.CloseHandle(handle)


@pytest.mark.spawns
def test_legacy_poison_reader_refuses_new_campaign_schema_without_recovery(tmp_path):
    marker = tmp_path / 'heavy_workload_v1.poison'
    raw = json.dumps({'schema_version': 'lfc_campaign_workload_v0.1', 'state': 'ACTIVE', 'owner_pid': 123})
    marker.write_text(raw)
    script = str(REPO_ROOT / 'scripts/ops/workload_admission.ps1').replace("'", "''")
    path = str(marker).replace("'", "''")
    result = run_command(f". '{script}'; try {{ [void](Get-WeatherHeavyWorkloadPoisonState -Path '{path}'); 'BAD' }} catch {{ 'REFUSED' }}")
    assert result.returncode == 0 and result.stdout.strip() == 'REFUSED'
    assert marker.read_text() == raw


@pytest.mark.spawns
@pytest.mark.skipif(os.name != 'nt', reason='native owned child Job containment')
def test_strict_child_container_teardown_proves_entire_job_empty(tmp_path):
    import sys
    from weather.market.lfc_session_driver import ChildProcess
    from weather.market.lfc_campaign_sidecar import public_environment
    child = ChildProcess([sys.executable, '-c', 'import time; time.sleep(60)'], cwd=tmp_path,
                         env=public_environment(tmp_path), interactive=False, require_containment=True)
    try:
        assert child.job is not None and child.kill_method == 'job'
        assert child.job.terminate() and child.job.wait_empty(timeout=10)
        assert child.wait() != 0
    finally:
        child.close()


@pytest.mark.spawns
@pytest.mark.parametrize('refuse_check', [False, True])
def test_real_registrar_binding_with_mocked_scheduler_and_python(tmp_path, refuse_check):
    from datetime import datetime, timedelta, timezone
    from weather.market.lfc_recording_io import file_sha
    import hashlib
    import shutil
    import subprocess
    from weather.paths import REPO_ROOT
    root = tmp_path / 'fixture pin'
    ops = root / 'scripts' / 'ops'
    ops.mkdir(parents=True)
    for name in ('register_lfc_campaign_task.ps1','lfc_campaign_task_contract.ps1','workstation_pregate_receipt.ps1'):
        shutil.copyfile(REPO_ROOT / 'scripts' / 'ops' / name, ops / name)
    # Mock only the OS interactivity predicate in this isolated test copy.
    # The first unmodified attempt refused in this noninteractive agent session;
    # no Scheduler function was reached. No production code is changed.
    registrar = ops / 'register_lfc_campaign_task.ps1'
    text = registrar.read_text()
    assert text.count('[Environment]::UserInteractive') == 1
    registrar.write_text(text.replace('[Environment]::UserInteractive', '$true'))
    examples = root / 'docs' / 'examples'
    examples.mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / 'docs/examples/lfc-campaign.example.json', examples / 'lfc-campaign.example.json')
    xml = tmp_path / 'suite.xml'
    xml.write_text('<testsuite tests="1" errors="0" failures="0"/>')
    log = tmp_path / 'suite.log'
    log.write_text(''.join('0'*21 + m + '\n' for m in (
        'planned chunks=1 files=1 max_files=25', f'chunk 1/1 starting files=1 junit={xml}',
        'chunk 1/1 exit=0','VERDICT: ALL CHUNKS PASSED (1/1)')))
    now = datetime.now(timezone.utc)
    receipt = {'schema':'weather.workstation_pregate_receipt.v1','head':'a'*40,'verdict':'PASS',
        'failure_reasons':[],'driver_exit_code':0,'worktree_removed':True,'basetemp_removed':True,
        'started_at':(now-timedelta(minutes=1)).isoformat(),'finished_at':(now-timedelta(seconds=1)).isoformat(),
        'chunk_plan':[['tests/test_fixture.py']], 'chunks':[{'ordinal':1,'files':1,'logged_files':1,'exit_code':0}],
        'inventory_files':1,'max_files_per_chunk':25,'skipped_host_checks':['fixture']*5,'log_path':str(log),
        'log_sha256':file_sha(log),'junit_paths':[str(xml)],'junit_files':[{'path':str(xml),'sha256':file_sha(xml)}]}
    receipt_path = tmp_path / 'receipt.json'
    receipt_path.write_text(json.dumps(receipt))
    campaign, release = tmp_path / 'campaign.json', tmp_path / 'release.json'
    def q(value): return "'" + str(value).replace("'", "''") + "'"
    harness = r'''
$ErrorActionPreference='Stop'
$global:calls=New-Object System.Collections.ArrayList
$global:xml=$null; $global:registered=0; $global:enabled=0
function Get-ScheduledTask { param($TaskName,$TaskPath) return $null }
function Register-ScheduledTask { param($TaskName,$TaskPath,$Xml) $global:xml=$Xml; $global:registered++ }
function Export-ScheduledTask { param($TaskName,$TaskPath) return $global:xml }
function Enable-ScheduledTask { param($TaskName,$TaskPath) $global:enabled++; $global:xml=$global:xml.Replace('<Enabled>false</Enabled>','<Enabled>true</Enabled>') }
function FixturePython {
    [void]$global:calls.Add(@{argv=@($args);cwd=(Get-Location).Path})
    $global:LASTEXITCODE=0
    if($args -contains 'seal') {
        @{schema_version='lfc_campaign_release_v0.1';task_name='WeatherLFCCampaign';root=$global:pin;python='FixturePython';campaign_path=$global:campaign} |
            ConvertTo-Json | Set-Content -Encoding ASCII -LiteralPath $global:release
    } elseif($args -contains '--require-enabled' -and $global:refuse) { $global:LASTEXITCODE=3 }
}
'''
    harness += f"\n$global:pin={q(root)}; $global:campaign={q(campaign)}; $global:release={q(release)}; $global:refuse=${str(refuse_check).lower()}\n"
    script = q(ops / 'register_lfc_campaign_task.ps1')
    harness += f"& {script} -Action Register -RepoRoot $global:pin -CampaignPath $global:campaign -ReleasePath $global:release -PythonPath FixturePython -PregateReceipt {q(receipt_path)} -QualifiedHead ('a'*40) | Out-Null\n"
    harness += f"& {script} -Action Verify -CampaignPath $global:campaign -ReleasePath $global:release | Out-Null\n"
    harness += "$p=Get-Content -Raw -LiteralPath $global:campaign | ConvertFrom-Json; $p.enabled=$true; $p | ConvertTo-Json -Depth 10 | Set-Content -Encoding ASCII -LiteralPath $global:campaign\n"
    harness += f"$failed=$false; try {{ & {script} -Action Enable -CampaignPath $global:campaign -ReleasePath $global:release | Out-Null }} catch {{ $failed=$true }}\n"
    harness += "@{calls=@($global:calls);registered=$global:registered;enabled=$global:enabled;failed=$failed} | ConvertTo-Json -Depth 8 -Compress"
    path = tmp_path / 'harness.ps1'
    path.write_text(harness)
    result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(path)],
                            capture_output=True,text=True,timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    observed = json.loads(result.stdout)
    assert observed['registered'] == 1
    assert observed['enabled'] == (0 if refuse_check else 1)
    assert observed['failed'] == refuse_check
    calls = observed['calls']
    assert len(calls) == 3
    assert all(c['cwd'] == str(root) for c in calls)
    assert calls[0]['argv'] == ['-m','weather.market.lfc_campaign_cli','seal','--campaign',str(campaign),
        '--release',str(release),'--pregate',str(receipt_path),'--head','a'*40,'--python','FixturePython']
    assert calls[1]['argv'][:4] == ['-m','weather.market.lfc_campaign_cli','check','--release']
    assert '--require-enabled' not in calls[1]['argv'] and calls[2]['argv'][-1] == '--require-enabled'
