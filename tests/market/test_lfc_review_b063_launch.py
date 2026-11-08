"""Guards: B063 wrapper launch envelope across policy and window read races.

Only inert coordinator dependencies and a native pure PowerShell function.
"""
from datetime import timedelta
import hashlib
import json

import pytest

from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, state_at, StubRuntime
from tests.market.test_lfc_review_t044_recheck1 import wrapper_deadline
from weather.market.lfc_campaign import CampaignCoordinator
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import load_policy, parse_policy
from weather.market.lfc_f2_breadth import example_policy


@pytest.fixture
def guarded_runtime(tmp_path):
    from tests.market.test_lfc_campaign_runtime import runtime_at
    with account_lease(MAKER, backend=Mutexes()):
        yield runtime_at(tmp_path)


@pytest.mark.spawns
@pytest.mark.parametrize('race', ['policy_edit', 'early_tick'])
def test_wrapper_read_and_child_admission_share_a_bound_deadline(tmp_path, monkeypatch, race):
    row = example_policy(); row.update(enabled=True, max_session_seconds=300 if race=='policy_edit' else 21600)
    entry = next(e for e in parse_policy(row).entries if e.local_date=='2026-11-11')
    # B064 gives near-window ticks a full envelope. This earlier tick remains
    # outside that bounded lookback and must still refuse after slow work.
    began = entry.start if race=='policy_edit' else entry.start-timedelta(minutes=20)
    deadline = wrapper_deadline(tmp_path, row, began)
    path = tmp_path/'synthetic-policy.json'
    launch = {'deadline_utc': deadline.isoformat(), 'policy_bytes_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    if race=='policy_edit':
        row.update(max_session_seconds=21600, revision=row['revision']+1, policy_revision=row['policy_revision']+1)
        path.write_text(json.dumps(row))
    policy = load_policy(path)
    child_entry = next(e for e in policy.entries if e.local_date==entry.local_date)
    clock = Clock(); clock.value = began
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path/'account', clock)
        runtime = StubRuntime(state, clock)
        runtime.wrapper_launch = launch
        coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path/'control')
        coordinator.wrapper_launch = launch
        if race=='early_tick':
            original = state.verify
            first = [True]
            def slow(*args, **kwargs):
                if first[0]: first[0]=False; clock.sleep(1201)
                return original(*args, **kwargs)
            monkeypatch.setattr(state, 'verify', slow)
            outcome = coordinator.tick(lambda: load_policy(path))
        else:
            clock.sleep(1)
            outcome = coordinator.start(child_entry, policy, lambda: load_policy(path))
        assert outcome in {'DEFERRED','MISSED'}, outcome
        assert runtime.go_count==0 and not state.ledger.autostart_claims and not state.incidents()


@pytest.mark.spawns
def test_unchanged_wrapper_snapshot_admits_and_a_new_tick_accepts_a_revision(tmp_path):
    from tests.operations.test_lfc_campaign_task import powershell
    row = example_policy(); row.update(enabled=True, max_session_seconds=300)
    entry = next(e for e in parse_policy(row).entries if e.local_date=='2026-11-11')
    for revision in (row['revision'], row['revision']+1):
        row.update(revision=revision, policy_revision=revision)
        path = tmp_path/'synthetic-policy.json'; path.write_text(json.dumps(row))
        result = powershell("Get-LfcCampaignLaunch -CampaignPath '"+str(path).replace("'","''")+
            "' -NowUtc ([DateTimeOffset]'"+entry.start.isoformat()+"') | ConvertTo-Json -Compress")
        assert result.returncode==0, result.stderr
        launch = json.loads(result.stdout)
        assert launch['policy_bytes_sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
        policy = load_policy(path)
        clock=Clock();clock.value=entry.start
        with account_lease(MAKER,backend=Mutexes()):
            state=state_at(tmp_path/str(revision),clock)
            runtime=StubRuntime(state,clock)
            coordinator=CampaignCoordinator(state=state,runtime=runtime,clock=clock,control_root=tmp_path/('control'+str(revision)),wrapper_launch=launch)
            assert coordinator.start(entry,policy,lambda:load_policy(path))=='STARTED'
            assert runtime.go_count==1 and len(state.ledger.autostart_claims)==1


@pytest.mark.parametrize('invalid', [None, {}, {'deadline_utc':'bad','policy_bytes_sha256':'a'*64}])
def test_live_runtime_refuses_missing_or_invalid_budget_before_any_account_capability(tmp_path, invalid, guarded_runtime):
    from tests.market.test_lfc_campaign_runtime import runtime_at
    from weather.market.lfc_campaign_launch import LaunchDeferred
    runtime=guarded_runtime;runtime.wrapper_launch=invalid
    policy=load_policy(runtime.policy_path)
    with pytest.raises(LaunchDeferred,match='wrapper_launch_missing_or_invalid'):
        runtime.run_session({},policy.entries[0],policy,{})


def test_post_boundary_rechecks_the_same_policy_snapshot_and_cleanup_budget(tmp_path, guarded_runtime):
    from tests.market.test_lfc_campaign_runtime import runtime_at
    from weather.market.lfc_campaign_runtime import ScheduledAuthority
    from weather.market.mm_stage2_hold import HoldEnd
    runtime=guarded_runtime
    policy=load_policy(runtime.policy_path);entry=policy.entries[0]
    runtime.wrapper_launch={'deadline_utc':entry.start.isoformat(),'policy_bytes_sha256':policy.source_sha256}
    authority=ScheduledAuthority(runtime,{'attempt_id':'a'*32},entry,policy,{'baseline':{}})
    with pytest.raises(HoldEnd,match='wrapper_cleanup_budget_insufficient'):
        authority.check()


@pytest.mark.spawns
def test_wrapper_passes_its_snapshot_and_deadline_to_its_inert_child(tmp_path):
    import os, re, subprocess
    from weather.paths import REPO_ROOT
    ops=tmp_path/'pin with spaces'/'scripts'/'ops';ops.mkdir(parents=True)
    for name in ('lfc_campaign_task.ps1','lfc_campaign_task_contract.ps1'):
        (ops/name).write_bytes((REPO_ROOT/'scripts'/'ops'/name).read_bytes())
    captured=tmp_path/'captured-arguments.txt'
    capture=str(captured).replace("'","''")
    (ops/'windows_kill_on_close_job.ps1').write_text("""
function New-WeatherKillOnCloseJob {
 $j=[pscustomobject]@{}
 $j | Add-Member ScriptMethod TerminateAndWait {param($ms)}
 $j | Add-Member ScriptMethod Dispose {}
 return $j
}
function ConvertTo-WeatherWindowsArgumentString {param([string[]]$Tokens); return ($Tokens | ConvertTo-Json -Compress)}
function Start-WeatherProcessInJob {
 param($Job,$FilePath,$ArgumentString,$WorkingDirectory)
 [IO.File]::WriteAllText('"""+capture+"""',$ArgumentString)
 $p=[pscustomobject]@{ExitCode=0}
 $p | Add-Member ScriptMethod WaitForExit {param($ms);return $true}
 $p | Add-Member ScriptMethod Dispose {}
 return $p
}
""")
    policy=tmp_path/'campaign.json';policy.write_text(json.dumps(example_policy()))
    release=tmp_path/'release.json';release.write_text(json.dumps({'schema_version':'lfc_campaign_release_v0.1',
        'task_name':'WeatherLFCCampaign','root':str(ops.parent.parent),'python':'inert-never-launched',
        'campaign_path':str(policy)}))
    env={key:value for key,value in os.environ.items() if key not in ('PYTHONPATH','PYTHONHOME','WEATHER_MARKET_REGISTRY')}
    result=subprocess.run(['powershell.exe','-NoProfile','-File',str(ops/'lfc_campaign_task.ps1'),
        '-ReleasePath',str(release),'-ReleaseSha256',hashlib.sha256(release.read_bytes()).hexdigest()],
        capture_output=True,text=True,timeout=20,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert result.returncode==0,result.stdout+result.stderr
    tokens=json.loads(captured.read_text())
    assert tokens[:3]==['-m','weather.market.lfc_campaign_cli','tick']
    assert tokens[tokens.index('--wrapper-policy-sha256')+1]==hashlib.sha256(policy.read_bytes()).hexdigest()
    from weather.market.lfc_campaign_launch import launch_packet
    launch_packet(tokens[tokens.index('--wrapper-deadline-utc')+1],tokens[tokens.index('--wrapper-policy-sha256')+1])
