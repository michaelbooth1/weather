"""Immediate owner timing retains exact scope, lease and teardown boundaries."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import subprocess

import pytest
from weather.operations import production_cold_archive_stage_cli as stage
from weather.operations import replay_cache_compression_admission as admission

ROOT = Path(__file__).resolve().parents[2]
TOKEN = admission.ARCHIVE_IMMEDIATE_EXCEPTION
START = admission.ARCHIVE_IMMEDIATE_START
END = admission.ARCHIVE_IMMEDIATE_END
PLAN = "2faae41470c42508a8639e98ec17ace7ecebc0b8715c09eaa92d33c0845251d3"


@pytest.mark.parametrize("now,allowed", [
    (START - timedelta(seconds=1), False), (START, True),
    (END - timedelta(seconds=1), True), (END, False),
    (END + timedelta(days=1), False),
])
def test_exact_dated_window_and_independent_lease(now, allowed):
    assert admission.storage_daytime_authorized(now, TOKEN) is allowed
    if allowed:
        assert stage.verify_archive_exception(
            {"policy_window": TOKEN.lower()}, now, exception=TOKEN) == TOKEN
    else:
        with pytest.raises(ValueError):
            stage.verify_archive_exception(
                {"policy_window": TOKEN.lower()}, now, exception=TOKEN)


@pytest.mark.parametrize("policy,token", [
    ("agent_heavy", TOKEN), (TOKEN.lower(), ""),
    (TOKEN.lower(), admission.ARCHIVE_EVENING_EXCEPTION),
])
def test_exception_cannot_substitute_another_lease(policy, token):
    with pytest.raises(ValueError):
        stage.verify_archive_exception({"policy_window": policy}, START, exception=token)


def test_reserve_is_twenty_gib_only_for_primary_plan_and_valid_deadline(monkeypatch):
    plan = {"selection_sha256": stage.OVERNIGHT_SELECTION_SHA256}
    monkeypatch.setattr(stage, "_read_pinned_json", lambda *a: (plan, b""))
    args = {"now": START, "deadline": START + timedelta(seconds=300),
            "owner_approved_exception": TOKEN}
    assert stage.load_plan_with_reserve(Path("fixture"), PLAN, **args)[1] == 20 * 1024**3
    assert stage.load_plan_with_reserve(Path("fixture"), PLAN, now=START)[1] == 50 * 1024**3
    for bad in ("0" * 64, stage.OVERNIGHT_PACKED_PLAN_SHA256,
                "92878b66c9cb04f476de89ef6fac4d12203b5fe8b8a0b5f337a0c4a103caefbc"):
        with pytest.raises(ValueError):
            stage.load_plan_with_reserve(Path("fixture"), bad, **args)
    for overrides in ({"now": END}, {"deadline": None}, {"deadline": END},
                      {"deadline": START}, {"now": START - timedelta(seconds=1)}):
        with pytest.raises(ValueError):
            stage.load_plan_with_reserve(Path("fixture"), PLAN, **{**args, **overrides})
    plan["selection_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        stage.load_plan_with_reserve(Path("fixture"), PLAN, **args)


def test_native_deadline_retains_fifteen_seconds_for_teardown():
    now = END - timedelta(seconds=60)
    stage.verify_archive_deadline(END - timedelta(seconds=15), now, TOKEN)
    with pytest.raises(ValueError, match="teardown"):
        stage.verify_archive_deadline(END - timedelta(seconds=14), now, TOKEN)


@pytest.mark.skipif(os.name != "nt", reason="native PowerShell policy")
def test_powershell_window_matches_python_and_preserves_scheduled_start(tmp_path):
    script = tmp_path / "check.ps1"
    script.write_text(r"""
$ErrorActionPreference='Stop'
. (Join-Path $args[0] 'scripts/ops/workload_admission.ps1')
. (Join-Path $args[0] 'scripts/ops/archive_plain_campaign_contract.ps1')
$token='OWNER_APPROVED_ARCHIVE_RECOVERY_20260913_EVENING'
$valid=Get-WeatherHeavyWorkloadPolicyWindow -Now ([datetime]'2026-09-13T18:46:00') -OwnerApprovedException $token
if($valid -cne $token.ToLowerInvariant()){throw 'Policy differs'}
$refused=0
foreach($stamp in @('2026-09-13T18:45:59','2026-09-14T00:30:00','2026-09-15T18:46:00')){
 try{$null=Get-WeatherHeavyWorkloadPolicyWindow -Now ([datetime]$stamp) -OwnerApprovedException $token}catch{$refused++}
}
try{$null=Get-WeatherHeavyWorkloadPolicyWindow -Now ([datetime]'2026-09-13T18:46:00') -OwnerApprovedException $token -AllowStageAWindow}catch{$refused++}
if($refused -ne 4){throw 'Expired or widened policy accepted'}
$c=@{campaign_id='plain-20260913-test';start_utc='2026-09-13T22:46:00Z';end_utc='2026-09-14T04:30:00Z'}
if(-not(Test-WeatherPlainStartWindow $c -Now ([datetime]'2026-09-14T01:00:00Z'))){throw 'Immediate start rejected'}
if(Test-WeatherPlainStartWindow $c -Now ([datetime]'2026-09-14T04:30:00Z')){throw 'Expired start accepted'}
$c=@{campaign_id='plain-20260914-test';start_utc='2026-09-14T04:30:00Z';end_utc='2026-09-14T08:42:00Z'}
if(Test-WeatherPlainStartWindow $c -Now ([datetime]'2026-09-14T04:31:00Z')){throw 'Scheduled catch-up accepted'}
foreach($name in @('production_cold_archive_run.ps1','workload_admission.ps1','archive_plain_campaign_contract.ps1','archive_plain_campaign_run.ps1','archive_plain_campaign_worker.ps1')){
 $tokens=$null;$errors=$null
 $null=[Management.Automation.Language.Parser]::ParseFile((Join-Path $args[0] ('scripts/ops/'+$name)),[ref]$tokens,[ref]$errors)
 if(@($errors).Count){throw ($errors|Out-String)}
}
""", encoding="utf-8")
    ps = Path(os.environ["WINDIR"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(ps), "-NoProfile", "-NonInteractive", "-File", str(script), str(ROOT)],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
