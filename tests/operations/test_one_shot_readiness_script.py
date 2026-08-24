from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "one_shot_readiness.ps1"
WORKLOAD_ADMISSION = REPO_ROOT / "scripts" / "ops" / "workload_admission.ps1"
GUARDED_LAUNCHER = REPO_ROOT / "scripts" / "ops" / "one_shot_guarded_launcher.ps1"
JOB_CONTAINMENT = REPO_ROOT / "scripts" / "ops" / "windows_kill_on_close_job.ps1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest_index(path: Path, manifest_hash: str, task_name: str) -> None:
    index_root = path.parent.parent / "one_shot_registry_index"
    index_root.mkdir(exist_ok=True)
    event = {
        "schema_version": "weather_one_shot_registry_index_v1",
        "kind": "MANIFEST_ANCHOR",
        "recorded_at_local": "2026-08-24T20:00:00-04:00",
        "task_name": task_name,
        "manifest_path": str(path.resolve()),
        "manifest_sha256": manifest_hash,
        "authority": "CREATE_ONLY_ONE_SHOT_REGISTRY_INDEX",
    }
    (index_root / f"manifest.{task_name}.{manifest_hash}.json").write_text(
        json.dumps(event), encoding="utf-8"
    )


def _write_manifest(
    tmp_path: Path,
    *,
    dependency: Path,
    dependency_sha256: str,
    boot_identity: str = "2026-08-24T18:53:27.0000000Z",
    extra_dependencies: tuple[Path, ...] = (),
) -> tuple[Path, str]:
    powershell = Path(
        shutil.which("powershell")
        or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    ).resolve()
    arguments_template = (
        f'-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{GUARDED_LAUNCHER.resolve()}" '
        '-ReadinessManifestPath "{READINESS_MANIFEST_PATH}" '
        "-ExpectedReadinessManifestSha256 "
        "{EXPECTED_READINESS_MANIFEST_SHA256}"
    )
    manifest = {
        "schema_version": "weather_one_shot_readiness_manifest_v0.4",
        "task": {
            "task_name": "WeatherSyntheticOneShot",
            "task_path": "\\",
            "executable": str(powershell),
            "arguments_template": arguments_template,
            "working_directory": str(tmp_path.resolve()),
            "action_file": str(GUARDED_LAUNCHER.resolve()),
            "payload_file": str(dependency.resolve()),
            "payload_arguments": [],
            "trigger_at_local": "2026-08-25T01:15:00-04:00",
        },
        "principal": {
            "user_id": "weather-operator",
            "logon_type": "S4U",
            "run_level": "Limited",
        },
        "settings": {
            "multiple_instances": "IgnoreNew",
            "execution_time_limit": "PT2H",
            "start_when_available": False,
            "allow_demand_start": False,
            "wake_to_run": True,
            "restart_count": 0,
            "restart_interval": "",
            "allow_start_if_on_batteries": True,
            "stop_if_going_on_batteries": False,
            "run_only_if_idle": False,
            "run_only_if_network_available": False,
        },
        "admission": {
            "workload_class": "heavy",
            "earliest_at_local": "2026-08-25T00:30:00-04:00",
            "teardown_deadline_at_local": "2026-08-25T04:00:00-04:00",
        },
        "boot_identity": {"last_boot_up_time_utc": boot_identity},
        "dependencies": [
            {
                "path": str(GUARDED_LAUNCHER.resolve()),
                "sha256": _sha256(GUARDED_LAUNCHER),
            },
            {
                "path": str(JOB_CONTAINMENT.resolve()),
                "sha256": _sha256(JOB_CONTAINMENT),
            },
            {"path": str(dependency.resolve()), "sha256": dependency_sha256},
            {"path": str(SCRIPT.resolve()), "sha256": _sha256(SCRIPT)},
            {
                "path": str(WORKLOAD_ADMISSION.resolve()),
                "sha256": _sha256(WORKLOAD_ADMISSION),
            },
            *(
                {"path": str(path.resolve()), "sha256": _sha256(path)}
                for path in extra_dependencies
            ),
        ],
    }
    scratch = tmp_path / "readiness.json"
    scratch.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_hash = _sha256(scratch)
    registry = tmp_path / "active"
    registry.mkdir()
    path = registry / f"WeatherSyntheticOneShot.{manifest_hash}.manifest.json"
    scratch.replace(path)
    _write_manifest_index(path, manifest_hash, "WeatherSyntheticOneShot")
    return path, manifest_hash


def _rewrite_manifest(
    path: Path, payload: dict[str, object]
) -> tuple[Path, str]:
    scratch = path.parent / "rewrite.json"
    scratch.write_text(json.dumps(payload), encoding="utf-8")
    manifest_hash = _sha256(scratch)
    task_name = str(payload["task"]["task_name"])  # type: ignore[index]
    destination = path.parent / f"{task_name}.{manifest_hash}.manifest.json"
    path.unlink()
    scratch.replace(destination)
    _write_manifest_index(destination, manifest_hash, task_name)
    return destination, manifest_hash


def _invoke_snapshot(
    manifest_path: Path,
    manifest_sha256: str,
    *,
    current_boot: str,
    state: str = "Ready",
    repetition_interval: str = "",
    next_run_time: str = "2026-08-25T01:15:00-04:00",
    last_run_time: str = "1999-11-30T00:00:00-05:00",
    observed_at_local: str = "2026-08-24T20:00:00-04:00",
    observation_mode: str = "PreTrigger",
    action_executable: str | None = None,
    action_arguments: str | None = None,
    working_directory: str | None = None,
    dependency_count_limit: int | None = None,
    aggregate_byte_limit: int | None = None,
    principal_logon_type: str = "S4U",
    principal_run_level: str = "Limited",
    start_when_available: bool = False,
    allow_demand_start: bool = False,
    wake_to_run: bool = True,
    restart_count: int = 0,
) -> dict[str, object]:
    env = os.environ.copy()
    env.update(
        {
            "WEATHER_READINESS_SCRIPT": str(SCRIPT),
            "WEATHER_READINESS_MANIFEST": str(manifest_path),
            "WEATHER_READINESS_MANIFEST_SHA": manifest_sha256,
            "WEATHER_READINESS_BOOT": current_boot,
            "WEATHER_READINESS_TASK_STATE": state,
            "WEATHER_READINESS_REPETITION": repetition_interval,
            "WEATHER_READINESS_NEXT_RUN": next_run_time,
            "WEATHER_READINESS_LAST_RUN": last_run_time,
            "WEATHER_READINESS_OBSERVED_AT": observed_at_local,
            "WEATHER_READINESS_OBSERVATION_MODE": observation_mode,
            "WEATHER_READINESS_ACTION_EXECUTABLE": action_executable or "",
            "WEATHER_READINESS_ACTION_ARGUMENTS": action_arguments or "",
            "WEATHER_READINESS_WORKING_DIRECTORY": working_directory or "",
            "WEATHER_READINESS_DEPENDENCY_COUNT_LIMIT": (
                "" if dependency_count_limit is None else str(dependency_count_limit)
            ),
            "WEATHER_READINESS_AGGREGATE_BYTE_LIMIT": (
                "" if aggregate_byte_limit is None else str(aggregate_byte_limit)
            ),
            "WEATHER_READINESS_PRINCIPAL_LOGON_TYPE": principal_logon_type,
            "WEATHER_READINESS_PRINCIPAL_RUN_LEVEL": principal_run_level,
            "WEATHER_READINESS_START_WHEN_AVAILABLE": str(start_when_available),
            "WEATHER_READINESS_ALLOW_DEMAND_START": str(allow_demand_start),
            "WEATHER_READINESS_WAKE_TO_RUN": str(wake_to_run),
            "WEATHER_READINESS_RESTART_COUNT": str(restart_count),
        }
    )
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_READINESS_SCRIPT -LibraryOnly
$script:OneShotReadinessSchedulerTimeZone =
    [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$script:OneShotReadinessRegistryRoot = Split-Path -Parent `
    $env:WEATHER_READINESS_MANIFEST
$script:OneShotReadinessRepositoryRoot = Split-Path -Parent `
    $script:OneShotReadinessRegistryRoot
$script:OneShotRegistryIndexRoot = Join-Path `
    $script:OneShotReadinessRepositoryRoot 'one_shot_registry_index'
$script:OneShotReadinessRequireActivationMarker = $false
if ($env:WEATHER_READINESS_DEPENDENCY_COUNT_LIMIT) {
    $script:OneShotReadinessMaximumDependencyCount =
        [int]$env:WEATHER_READINESS_DEPENDENCY_COUNT_LIMIT
}
if ($env:WEATHER_READINESS_AGGREGATE_BYTE_LIMIT) {
    $script:OneShotReadinessMaximumAggregateDependencyBytes =
        [long]$env:WEATHER_READINESS_AGGREGATE_BYTE_LIMIT
}
$contract = Read-WeatherOneShotReadinessManifest `
    -Path $env:WEATHER_READINESS_MANIFEST `
    -ExpectedSha256 $env:WEATHER_READINESS_MANIFEST_SHA
$task = [pscustomobject]@{
    task_name = [string]$contract.Manifest.task.task_name
    task_path = [string]$contract.Manifest.task.task_path
    enabled = $true
    state = $env:WEATHER_READINESS_TASK_STATE
    principal_user_id = [string]$contract.Manifest.principal.user_id
    principal_logon_type = $env:WEATHER_READINESS_PRINCIPAL_LOGON_TYPE
    principal_run_level = $env:WEATHER_READINESS_PRINCIPAL_RUN_LEVEL
    principal_id = 'Author'
    principal_display_name = ''
    principal_group_id = ''
    principal_process_token_sid_type = 'Default'
    principal_required_privilege_count = 0
    settings_multiple_instances = [string]$contract.Manifest.settings.multiple_instances
    settings_execution_time_limit = [string]$contract.Manifest.settings.execution_time_limit
    settings_start_when_available = [bool]::Parse(
        $env:WEATHER_READINESS_START_WHEN_AVAILABLE
    )
    settings_allow_demand_start = [bool]::Parse(
        $env:WEATHER_READINESS_ALLOW_DEMAND_START
    )
    settings_wake_to_run = [bool]::Parse($env:WEATHER_READINESS_WAKE_TO_RUN)
    settings_restart_count = [int]$env:WEATHER_READINESS_RESTART_COUNT
    settings_restart_interval = ''
    settings_allow_start_if_on_batteries = $true
    settings_stop_if_going_on_batteries = $false
    settings_run_only_if_idle = $false
    settings_run_only_if_network_available = $false
    action_executable = if ($env:WEATHER_READINESS_ACTION_EXECUTABLE) {
        $env:WEATHER_READINESS_ACTION_EXECUTABLE
    } else { [string]$contract.Manifest.task.executable }
    action_arguments = if ($env:WEATHER_READINESS_ACTION_ARGUMENTS) {
        $env:WEATHER_READINESS_ACTION_ARGUMENTS
    } else {
        [string]$contract.Manifest.task.arguments_template.Replace(
            '{READINESS_MANIFEST_PATH}', [string]$contract.ManifestPath
        ).Replace(
            '{EXPECTED_READINESS_MANIFEST_SHA256}', [string]$contract.ManifestSha256
        )
    }
    working_directory = if ($env:WEATHER_READINESS_WORKING_DIRECTORY) {
        $env:WEATHER_READINESS_WORKING_DIRECTORY
    } else { [string]$contract.Manifest.task.working_directory }
    action_file = [string]$contract.Manifest.task.action_file
    trigger_at_local = [string]$contract.Manifest.task.trigger_at_local
    repetition_interval = $env:WEATHER_READINESS_REPETITION
    next_run_time = $env:WEATHER_READINESS_NEXT_RUN
    last_run_time = $env:WEATHER_READINESS_LAST_RUN
    readiness_manifest_path = [string]$contract.ManifestPath
    expected_readiness_manifest_sha256 = [string]$contract.ManifestSha256
}
Test-WeatherOneShotReadinessSnapshot `
    -ManifestContract $contract `
    -ObservedTaskSnapshot $task `
    -CurrentBootIdentity $env:WEATHER_READINESS_BOOT `
    -ObservedAtLocal ([DateTimeOffset]::Parse($env:WEATHER_READINESS_OBSERVED_AT)) `
    -ObservationMode $env:WEATHER_READINESS_OBSERVATION_MODE |
    ConvertTo-Json -Depth 6 -Compress
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _read_manifest_blocker(manifest_path: Path, manifest_sha256: str) -> str:
    env = os.environ.copy()
    env.update(
        {
            "WEATHER_READINESS_SCRIPT": str(SCRIPT),
            "WEATHER_READINESS_MANIFEST": str(manifest_path),
            "WEATHER_READINESS_MANIFEST_SHA": manifest_sha256,
        }
    )
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_READINESS_SCRIPT -LibraryOnly
$script:OneShotReadinessSchedulerTimeZone =
    [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$script:OneShotReadinessRegistryRoot = Split-Path -Parent `
    $env:WEATHER_READINESS_MANIFEST
$script:OneShotReadinessRepositoryRoot = Split-Path -Parent `
    $script:OneShotReadinessRegistryRoot
$script:OneShotRegistryIndexRoot = Join-Path `
    $script:OneShotReadinessRepositoryRoot 'one_shot_registry_index'
$script:OneShotReadinessRequireActivationMarker = $false
try {
    Read-WeatherOneShotReadinessManifest `
        -Path $env:WEATHER_READINESS_MANIFEST `
        -ExpectedSha256 $env:WEATHER_READINESS_MANIFEST_SHA | Out-Null
    'PASS'
}
catch {
    [string]$_.Exception.Data['weather_one_shot_readiness_blocker_code']
}
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_contract_is_read_only_and_exposes_assert_and_inspect_modes() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert (
        '[ValidateSet("Assert", "Inspect", "InspectActive", "InspectAuto")]'
        in text
    )
    assert '$Mode -ceq "InspectAuto"' in text
    assert '[Alias("ReadinessManifestPath")]' in text
    assert '[Alias("ExpectedReadinessManifestSha256")]' in text
    assert 'status = if ($ready) { "PASS" } else { "BLOCKED" }' in text
    assert 'authority = "READ_ONLY_NO_SCHEDULER_MUTATION"' in text
    assert 'if ($Mode -eq "Assert" -and -not [bool]$result.ready)' in text
    assert "exit 2" in text
    for mutation in (
        "Register-ScheduledTask",
        "Set-ScheduledTask",
        "Enable-ScheduledTask",
        "Disable-ScheduledTask",
        "Start-ScheduledTask",
        "Stop-ScheduledTask",
        "Unregister-ScheduledTask",
    ):
        assert mutation not in text


def test_manifest_requires_action_file_in_hashed_dependencies() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "weather_one_shot_readiness_manifest_v0.4" in text
    assert (
        '"task_name", "task_path", "executable", "arguments_template",'
        in text
    )
    assert '"working_directory", "action_file", "payload_file",' in text
    assert "$actionFile -ine $script:OneShotGuardedLauncherPath" in text
    assert "$payloadDependencyCount -ne 1" in text
    assert "$jobContainmentDependencyCount -ne 1" in text
    assert 'ExpectedNames @("last_boot_up_time_utc")' in text
    assert 'ExpectedNames @("user_id", "logon_type", "run_level")' in text
    assert '"workload_class", "earliest_at_local", "teardown_deadline_at_local"' in text
    assert 'ExpectedNames @("path", "sha256")' in text
    assert "$actionDependencyCount -ne 1" in text
    assert "$validatorDependencyCount -ne 1" in text
    assert "$workloadAdmissionDependencyCount -ne 1" in text
    assert "Get-ScheduledTaskInfo" in text
    assert 'state = [string]$task.State' in text
    assert "repetition_interval = $repetitionInterval" in text
    assert "next_run_time = $nextRunTime" in text
    assert "last_run_time = $lastRunTime" in text
    assert "principal_logon_type = [string]$task.Principal.LogonType" in text
    assert "settings_start_when_available = [bool]$task.Settings.StartWhenAvailable" in text
    assert "settings_restart_count = [int]$task.Settings.RestartCount" in text
    assert "OneShotReadinessMaximumDependencyCount = 32" in text
    assert "OneShotReadinessMaximumManifestBytes = 64KB" in text
    assert "OneShotReadinessMaximumDependencyBytes = 4MB" in text
    assert "OneShotReadinessMaximumAggregateDependencyBytes = 8MB" in text
    assert "Get-WeatherOneShotBytesSha256 -Bytes $bytes" in text
    assert "$utf8.GetString([byte[]]$fileSnapshot.bytes)" in text
    assert "[IO.File]::ReadAllText" not in text


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_manifest_size_boundary_is_exactly_64_kib(tmp_path: Path) -> None:
    at_limit = tmp_path / "at-limit.json"
    at_limit.write_bytes(b" " * (64 * 1024))
    over_limit = tmp_path / "over-limit.json"
    over_limit.write_bytes(b" " * (64 * 1024 + 1))

    # At the byte ceiling the parser, rather than the size gate, owns the
    # rejection. One byte more must fail at the bounded snapshot gate.
    assert _read_manifest_blocker(at_limit, _sha256(at_limit)) == "INVALID_MANIFEST"
    assert _read_manifest_blocker(over_limit, _sha256(over_limit)) == (
        "MANIFEST_UNSAFE_PATH"
    )


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_validator_and_heavy_workload_gate_are_required_dependencies(
    tmp_path: Path,
) -> None:
    action = tmp_path / "task.ps1"
    action.write_text("Write-Output 'safe'\n", encoding="utf-8")
    manifest, _ = _write_manifest(
        tmp_path,
        dependency=action,
        dependency_sha256=_sha256(action),
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    payload["dependencies"] = [
        item
        for item in payload["dependencies"]
        if Path(item["path"]) != SCRIPT.resolve()
    ]
    manifest, manifest_hash = _rewrite_manifest(manifest, payload)
    assert _read_manifest_blocker(manifest, manifest_hash) == "INVALID_MANIFEST"

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["dependencies"].append(
        {"path": str(SCRIPT.resolve()), "sha256": _sha256(SCRIPT)}
    )
    payload["dependencies"] = [
        item
        for item in payload["dependencies"]
        if Path(item["path"]) != WORKLOAD_ADMISSION.resolve()
    ]
    manifest, manifest_hash = _rewrite_manifest(manifest, payload)
    assert _read_manifest_blocker(manifest, manifest_hash) == "INVALID_MANIFEST"


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_manifest_must_use_filename_hash_bound_active_registry_copy(
    tmp_path: Path,
) -> None:
    action = tmp_path / "task.ps1"
    action.write_text("Write-Output 'safe'\n", encoding="utf-8")
    manifest, manifest_hash = _write_manifest(
        tmp_path,
        dependency=action,
        dependency_sha256=_sha256(action),
    )
    external = tmp_path / "external-readiness.json"
    manifest.replace(external)

    assert _read_manifest_blocker(external, manifest_hash) == (
        "MANIFEST_NOT_REGISTRY_ANCHORED"
    )

@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_missing_executable_or_working_directory_fails_manifest_read(
    tmp_path: Path,
) -> None:
    action = tmp_path / "task.ps1"
    action.write_text("Write-Output 'safe'\n", encoding="utf-8")
    manifest, _ = _write_manifest(
        tmp_path,
        dependency=action,
        dependency_sha256=_sha256(action),
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    payload["task"]["executable"] = str((tmp_path / "missing.exe").resolve())
    manifest, manifest_hash = _rewrite_manifest(manifest, payload)
    assert _read_manifest_blocker(manifest, manifest_hash) == (
        "TASK_EXECUTABLE_UNAVAILABLE"
    )

    payload["task"]["executable"] = str(
        Path(
            shutil.which("powershell")
            or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        ).resolve()
    )
    payload["task"]["working_directory"] = str(
        (tmp_path / "missing-directory").resolve()
    )
    manifest, manifest_hash = _rewrite_manifest(manifest, payload)
    assert _read_manifest_blocker(manifest, manifest_hash) == (
        "TASK_WORKING_DIRECTORY_UNAVAILABLE"
    )


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_manifest_rejects_alternate_host_and_unencodable_payload_args(
    tmp_path: Path,
) -> None:
    action = tmp_path / "task.ps1"
    action.write_text("Write-Output 'safe'\n", encoding="utf-8")
    manifest, _ = _write_manifest(
        tmp_path, dependency=action, dependency_sha256=_sha256(action)
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    payload["task"]["executable"] = str(
        Path(os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")).resolve()
    )
    manifest, manifest_hash = _rewrite_manifest(manifest, payload)
    assert _read_manifest_blocker(manifest, manifest_hash) == "INVALID_MANIFEST"

    payload["task"]["executable"] = str(
        Path(shutil.which("powershell") or "powershell.exe").resolve()
    )
    payload["task"]["payload_arguments"] = ['contains"quote']
    manifest, manifest_hash = _rewrite_manifest(manifest, payload)
    assert _read_manifest_blocker(manifest, manifest_hash) == "INVALID_MANIFEST"

    payload["task"]["payload_arguments"] = ["C:\\path with space\\"]
    manifest, manifest_hash = _rewrite_manifest(manifest, payload)
    assert _read_manifest_blocker(manifest, manifest_hash) == "INVALID_MANIFEST"

    payload["task"]["payload_arguments"] = ["x" * 4000] * 8
    manifest, manifest_hash = _rewrite_manifest(manifest, payload)
    assert _read_manifest_blocker(manifest, manifest_hash) == "INVALID_MANIFEST"


def test_guarded_launcher_owns_validation_locks_and_payload_tree() -> None:
    launcher = GUARDED_LAUNCHER.read_text(encoding="utf-8-sig")
    readiness = SCRIPT.read_text(encoding="utf-8-sig")

    assert "[IO.FileShare]::Read" in launcher
    assert launcher.index("$registryLock = [IO.FileStream]::new") < launcher.index(
        "Read-WeatherOneShotReadinessManifest"
    )
    dependency_enter = launcher.index(
        "$dependencyLeaseSet = Enter-WeatherOneShotDependencyLeaseSet"
    )
    dependency_exit = launcher.index("Exit-WeatherOneShotDependencyLeaseSet")
    assert launcher.index("if (-not [bool]$readiness.ready)") < dependency_enter
    assert dependency_enter < launcher.index(". $workloadAdmissionPath")
    assert dependency_enter < launcher.index(". $jobContainmentPath")
    assert dependency_enter < launcher.index("Start-WeatherProcessInJob")
    assert "New-WeatherKillOnCloseJob" in launcher
    assert "Start-WeatherProcessInJob" in launcher
    assert "windows_kill_on_close_job.ps1" in launcher
    assert 'admission.workload_class -ceq "heavy"' in launcher
    assert "Enter-WeatherHeavyWorkloadLease" in launcher
    assert "Exit-WeatherHeavyWorkloadLease" in launcher
    assert launcher.index("Start-WeatherProcessInJob") < launcher.index(
        "$payloadProcess.WaitForExit()"
    )
    assert launcher.index("$payloadJob.Dispose()") < launcher.rindex(
        "$registryLock.Dispose()"
    )
    assert launcher.index("Exit-WeatherHeavyWorkloadLease") < launcher.rindex(
        "$registryLock.Dispose()"
    )
    assert launcher.rindex("$payloadJob.Dispose()") < dependency_exit
    assert launcher.index("$payloadProcess.Dispose()") < dependency_exit
    assert launcher.index("Exit-WeatherHeavyWorkloadLease") < dependency_exit
    assert dependency_exit < launcher.rindex("$registryLock.Dispose()")

    lease_function = readiness[
        readiness.index("function Enter-WeatherOneShotDependencyLeaseSet") :
        readiness.index("function Exit-WeatherOneShotDependencyLeaseSet")
    ]
    assert "[IO.FileShare]::Read" in lease_function
    assert "$algorithm.ComputeHash($currentStream)" in lease_function
    assert lease_function.index("$algorithm.ComputeHash($currentStream)") < (
        lease_function.index("$leases.Add($currentStream)")
    )


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_light_launcher_keeps_reviewed_payload_immutable_until_exit(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "copied-repo"
    ops = repo / "scripts" / "ops"
    ops.mkdir(parents=True)
    copied_readiness = ops / SCRIPT.name
    copied_launcher = ops / GUARDED_LAUNCHER.name
    copied_job_helper = ops / JOB_CONTAINMENT.name
    shutil.copy2(SCRIPT, copied_readiness)
    shutil.copy2(GUARDED_LAUNCHER, copied_launcher)

    copied_job_helper.write_text(
        r"""
function New-WeatherKillOnCloseJob {
    [IO.File]::WriteAllText($env:WEATHER_TEST_SENTINEL_READY, 'READY')
    while (-not [IO.File]::Exists($env:WEATHER_TEST_SENTINEL_RELEASE)) {
        Start-Sleep -Milliseconds 25
    }
    $job = [pscustomobject]@{}
    $job | Add-Member -MemberType ScriptMethod -Name Dispose -Value { }
    return $job
}

function Start-WeatherProcessInJob {
    param(
        [Parameter(Mandatory = $true)][object]$Job,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string]$ArgumentString,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = $ArgumentString
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    return [Diagnostics.Process]::Start($startInfo)
}
""".lstrip(),
        encoding="utf-8",
    )
    reviewed_payload = (
        "[IO.File]::WriteAllText($env:WEATHER_TEST_PAYLOAD_RESULT, 'REVIEWED')\n"
    )
    replacement_payload = (
        "[IO.File]::WriteAllText($env:WEATHER_TEST_PAYLOAD_RESULT, 'REPLACED')\n"
    )
    payload = repo / "reviewed-payload.ps1"
    replacement = repo / "replacement-payload.ps1"
    payload.write_text(reviewed_payload, encoding="utf-8")
    replacement.write_text(replacement_payload, encoding="utf-8")
    reviewed_payload_hash = _sha256(payload)

    powershell = Path(shutil.which("powershell") or "powershell.exe").resolve()
    now = datetime.now().astimezone().replace(microsecond=0)
    trigger = now - timedelta(seconds=2)
    earliest = trigger - timedelta(minutes=1)
    teardown = trigger + timedelta(minutes=3)
    trigger_at_local = trigger.isoformat()
    boot_identity = "2026-01-01T00:00:00.0000000Z"
    task_name = "WeatherDependencyLeaseRace"
    arguments_template = (
        "-NoProfile -NonInteractive -ExecutionPolicy Bypass "
        f'-File "{copied_launcher.resolve()}" '
        '-ReadinessManifestPath "{READINESS_MANIFEST_PATH}" '
        "-ExpectedReadinessManifestSha256 "
        "{EXPECTED_READINESS_MANIFEST_SHA256}"
    )
    manifest_payload = {
        "schema_version": "weather_one_shot_readiness_manifest_v0.4",
        "task": {
            "task_name": task_name,
            "task_path": "\\",
            "executable": str(powershell),
            "arguments_template": arguments_template,
            "working_directory": str(repo.resolve()),
            "action_file": str(copied_launcher.resolve()),
            "payload_file": str(payload.resolve()),
            "payload_arguments": [],
            "trigger_at_local": trigger_at_local,
        },
        "principal": {
            "user_id": "weather-test-operator",
            "logon_type": "S4U",
            "run_level": "Limited",
        },
        "settings": {
            "multiple_instances": "IgnoreNew",
            "execution_time_limit": "PT1M",
            "start_when_available": False,
            "allow_demand_start": False,
            "wake_to_run": True,
            "restart_count": 0,
            "restart_interval": "",
            "allow_start_if_on_batteries": True,
            "stop_if_going_on_batteries": False,
            "run_only_if_idle": False,
            "run_only_if_network_available": False,
        },
        "admission": {
            "workload_class": "light",
            "earliest_at_local": earliest.isoformat(),
            "teardown_deadline_at_local": teardown.isoformat(),
        },
        "boot_identity": {"last_boot_up_time_utc": boot_identity},
        "dependencies": [
            {
                "path": str(copied_launcher.resolve()),
                "sha256": _sha256(copied_launcher),
            },
            {
                "path": str(copied_readiness.resolve()),
                "sha256": _sha256(copied_readiness),
            },
            {
                "path": str(copied_job_helper.resolve()),
                "sha256": _sha256(copied_job_helper),
            },
            {"path": str(payload.resolve()), "sha256": reviewed_payload_hash},
        ],
    }
    scratch_manifest = repo / "manifest.scratch.json"
    scratch_manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    manifest_hash = _sha256(scratch_manifest)
    active = repo / "data" / "one_shot_readiness" / "active"
    active.mkdir(parents=True)
    manifest = active / f"{task_name}.{manifest_hash}.manifest.json"
    scratch_manifest.replace(manifest)

    timestamp = now.isoformat()
    (repo / "one_shot_registry.lock").write_text(
        "one-shot registry lock\n", encoding="utf-8"
    )
    (repo / "one_shot_registry_activation_intent.json").write_text(
        json.dumps(
            {
                "schema_version": "weather_one_shot_registry_activation_intent_v1",
                "status": "ACTIVATION_INTENDED",
                "registry_root": str(active.resolve()),
                "created_at_local": timestamp,
                "authority": "DURABLE_ONE_SHOT_REGISTRY_ACTIVATION_INTENT",
            }
        ),
        encoding="utf-8",
    )
    (repo / "one_shot_registry_activation.json").write_text(
        json.dumps(
            {
                "schema_version": "weather_one_shot_registry_activation_v1",
                "status": "ACTIVE",
                "registry_root": str(active.resolve()),
                "activated_at_local": timestamp,
                "authority": "CREATE_ONLY_ONE_SHOT_ACTIVE_REGISTRY",
            }
        ),
        encoding="utf-8",
    )
    index_root = repo / "one_shot_registry_index"
    index_root.mkdir()
    (index_root / f"manifest.{task_name}.{manifest_hash}.json").write_text(
        json.dumps(
            {
                "schema_version": "weather_one_shot_registry_index_v1",
                "kind": "MANIFEST_ANCHOR",
                "recorded_at_local": timestamp,
                "task_name": task_name,
                "manifest_path": str(manifest.resolve()),
                "manifest_sha256": manifest_hash,
                "authority": "CREATE_ONLY_ONE_SHOT_REGISTRY_INDEX",
            }
        ),
        encoding="utf-8",
    )

    expanded_arguments = arguments_template.replace(
        "{READINESS_MANIFEST_PATH}", str(manifest.resolve())
    ).replace("{EXPECTED_READINESS_MANIFEST_SHA256}", manifest_hash)
    ready = tmp_path / "dependency-leases-ready.txt"
    release = tmp_path / "dependency-leases-release.txt"
    payload_result = tmp_path / "payload-result.txt"
    env = os.environ.copy()
    env.update(
        {
            "WEATHER_TEST_LAUNCHER": str(copied_launcher.resolve()),
            "WEATHER_TEST_MANIFEST": str(manifest.resolve()),
            "WEATHER_TEST_MANIFEST_SHA": manifest_hash,
            "WEATHER_TEST_ACTION_ARGUMENTS": expanded_arguments,
            "WEATHER_TEST_TASK_NAME": task_name,
            "WEATHER_TEST_TASK_PATH": "\\",
            "WEATHER_TEST_TRIGGER_AT_LOCAL": trigger_at_local,
            "WEATHER_TEST_LAST_RUN_LOCAL": trigger.strftime("%Y-%m-%dT%H:%M:%S"),
            "WEATHER_TEST_EXECUTABLE": str(powershell),
            "WEATHER_TEST_WORKING_DIRECTORY": str(repo.resolve()),
            "WEATHER_TEST_USER_ID": "weather-test-operator",
            "WEATHER_TEST_BOOT_IDENTITY": boot_identity,
            "WEATHER_TEST_SENTINEL_READY": str(ready),
            "WEATHER_TEST_SENTINEL_RELEASE": str(release),
            "WEATHER_TEST_PAYLOAD_RESULT": str(payload_result),
        }
    )
    command = r"""
$ErrorActionPreference = 'Stop'
$lastRun = [datetime]::ParseExact(
    $env:WEATHER_TEST_LAST_RUN_LOCAL,
    'yyyy-MM-ddTHH:mm:ss',
    [Globalization.CultureInfo]::InvariantCulture
)
$lastRun = [datetime]::SpecifyKind($lastRun, [DateTimeKind]::Local)
$global:WeatherTestSyntheticTask = [pscustomobject]@{
    TaskName = $env:WEATHER_TEST_TASK_NAME
    TaskPath = $env:WEATHER_TEST_TASK_PATH
    State = 'Running'
    Actions = @([pscustomobject]@{
        Id = ''
        Execute = $env:WEATHER_TEST_EXECUTABLE
        Arguments = $env:WEATHER_TEST_ACTION_ARGUMENTS
        WorkingDirectory = $env:WEATHER_TEST_WORKING_DIRECTORY
    })
    Triggers = @([pscustomobject]@{
        CimClass = [pscustomobject]@{ CimClassName = 'MSFT_TaskTimeTrigger' }
        Enabled = $true
        Id = ''
        EndBoundary = ''
        RandomDelay = ''
        ExecutionTimeLimit = ''
        StartBoundary = $env:WEATHER_TEST_TRIGGER_AT_LOCAL
    })
    Principal = [pscustomobject]@{
        UserId = $env:WEATHER_TEST_USER_ID
        LogonType = 'S4U'
        RunLevel = 'Limited'
        Id = 'Author'
        DisplayName = ''
        GroupId = ''
        ProcessTokenSidType = 'Default'
        RequiredPrivilege = @()
    }
    Settings = [pscustomobject]@{
        Enabled = $true
        MultipleInstances = 'IgnoreNew'
        ExecutionTimeLimit = 'PT1M'
        StartWhenAvailable = $false
        AllowDemandStart = $false
        WakeToRun = $true
        RestartCount = 0
        RestartInterval = ''
        DisallowStartIfOnBatteries = $false
        StopIfGoingOnBatteries = $false
        RunOnlyIfIdle = $false
        RunOnlyIfNetworkAvailable = $false
    }
}
$global:WeatherTestSyntheticInfo = [pscustomobject]@{
    NextRunTime = [datetime]::MinValue
    LastRunTime = $lastRun
}
function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName, [string]$TaskPath)
    return $global:WeatherTestSyntheticTask
}
function Get-ScheduledTaskInfo {
    [CmdletBinding()]
    param([Parameter(ValueFromPipeline = $true)]$InputObject)
    process { return $global:WeatherTestSyntheticInfo }
}
function Get-CimInstance {
    [CmdletBinding()]
    param([Parameter(Position = 0)][string]$ClassName)
    if ($ClassName -cne 'Win32_OperatingSystem') {
        throw "Unexpected synthetic CIM class: $ClassName"
    }
    return [pscustomobject]@{
        LastBootUpTime = [DateTimeOffset]::Parse(
            $env:WEATHER_TEST_BOOT_IDENTITY,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        )
    }
}
& $env:WEATHER_TEST_LAUNCHER `
    -ReadinessManifestPath $env:WEATHER_TEST_MANIFEST `
    -ExpectedReadinessManifestSha256 $env:WEATHER_TEST_MANIFEST_SHA
"""
    process = subprocess.Popen(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_deadline = time.monotonic() + 15
        while not ready.exists() and time.monotonic() < wait_deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                pytest.fail(
                    "guarded launcher exited before dependency leases were held: "
                    f"stdout={stdout!r}, stderr={stderr!r}"
                )
            time.sleep(0.025)
        assert ready.exists(), "guarded launcher did not expose its lease sentinel"

        with pytest.raises(OSError):
            payload.write_text(replacement_payload, encoding="utf-8")
        assert _sha256(payload) == reviewed_payload_hash
        with pytest.raises(OSError):
            os.replace(replacement, payload)
        assert replacement.exists()
        assert _sha256(payload) == reviewed_payload_hash
        with pytest.raises(OSError):
            payload.unlink()
        assert _sha256(payload) == reviewed_payload_hash

        release.write_text("release\n", encoding="utf-8")
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 0, f"stdout={stdout!r}, stderr={stderr!r}"
    finally:
        if process.poll() is None:
            release.write_text("release\n", encoding="utf-8")
            process.kill()
            process.communicate()

    assert payload_result.read_text(encoding="utf-8") == "REVIEWED"
    os.replace(replacement, payload)
    assert payload.read_text(encoding="utf-8") == replacement_payload


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_heavy_task_must_finish_inside_admitted_window(tmp_path: Path) -> None:
    action = tmp_path / "task.ps1"
    action.write_text("Write-Output 'safe'\n", encoding="utf-8")
    manifest, _ = _write_manifest(
        tmp_path,
        dependency=action,
        dependency_sha256=_sha256(action),
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["task"]["trigger_at_local"] = "2026-08-25T08:59:00-04:00"
    payload["settings"]["execution_time_limit"] = "PT2H"
    payload["admission"]["teardown_deadline_at_local"] = (
        "2026-08-25T09:00:00-04:00"
    )
    manifest, manifest_hash = _rewrite_manifest(manifest, payload)

    assert _read_manifest_blocker(manifest, manifest_hash) == (
        "TASK_OUTSIDE_ADMISSION_WINDOW"
    )


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_foreign_offset_cannot_disguise_protected_window_trigger(
    tmp_path: Path,
) -> None:
    action = tmp_path / "task.ps1"
    action.write_text("Write-Output 'safe'\n", encoding="utf-8")
    manifest, _ = _write_manifest(
        tmp_path,
        dependency=action,
        dependency_sha256=_sha256(action),
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["task"]["trigger_at_local"] = "2026-08-25T08:00:00-12:00"
    payload["admission"]["earliest_at_local"] = "2026-08-25T00:30:00-12:00"
    payload["admission"]["teardown_deadline_at_local"] = (
        "2026-08-25T09:00:00-12:00"
    )
    manifest, manifest_hash = _rewrite_manifest(manifest, payload)

    assert _read_manifest_blocker(manifest, manifest_hash) == (
        "TASK_LOCAL_OFFSET_MISMATCH"
    )


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_ambiguous_fall_back_wall_clock_is_rejected(tmp_path: Path) -> None:
    action = tmp_path / "task.ps1"
    action.write_text("Write-Output 'safe'\n", encoding="utf-8")
    manifest, _ = _write_manifest(
        tmp_path,
        dependency=action,
        dependency_sha256=_sha256(action),
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["task"]["trigger_at_local"] = "2026-11-01T01:30:00-04:00"
    payload["admission"]["earliest_at_local"] = "2026-11-01T00:30:00-04:00"
    payload["admission"]["teardown_deadline_at_local"] = (
        "2026-11-01T04:00:00-05:00"
    )
    manifest, manifest_hash = _rewrite_manifest(manifest, payload)

    assert _read_manifest_blocker(manifest, manifest_hash) == (
        "TASK_LOCAL_TIME_INVALID"
    )


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_matching_snapshot_passes(tmp_path: Path) -> None:
    action = tmp_path / "task.ps1"
    action.write_text("Write-Output 'safe'\n", encoding="utf-8")
    manifest, manifest_hash = _write_manifest(
        tmp_path,
        dependency=action,
        dependency_sha256=_sha256(action),
    )

    result = _invoke_snapshot(
        manifest,
        manifest_hash,
        current_boot="2026-08-24T18:53:27.0000000Z",
    )

    assert result["status"] == "PASS"
    assert result["ready"] is True
    assert result["blocker_codes"] == []


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_execution_entry_accepts_current_running_task_without_future_next_run(
    tmp_path: Path,
) -> None:
    action = tmp_path / "task.ps1"
    action.write_text("Write-Output 'safe'\n", encoding="utf-8")
    manifest, manifest_hash = _write_manifest(
        tmp_path,
        dependency=action,
        dependency_sha256=_sha256(action),
    )

    result = _invoke_snapshot(
        manifest,
        manifest_hash,
        current_boot="2026-08-24T18:53:27.0000000Z",
        observation_mode="Execution",
        state="Running",
        next_run_time="",
        last_run_time="2026-08-25T01:15:00-04:00",
        observed_at_local="2026-08-25T01:16:00-04:00",
    )

    assert result["status"] == "PASS"
    assert result["ready"] is True
    assert result["observation_mode"] == "Execution"
    assert result["blocker_codes"] == []


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_active_inspection_accepts_a_bound_run_after_entry_window(
    tmp_path: Path,
) -> None:
    action = tmp_path / "task.ps1"
    action.write_text("Write-Output 'safe'\n", encoding="utf-8")
    manifest, manifest_hash = _write_manifest(
        tmp_path,
        dependency=action,
        dependency_sha256=_sha256(action),
    )

    result = _invoke_snapshot(
        manifest,
        manifest_hash,
        current_boot="2026-08-24T18:53:27.0000000Z",
        observation_mode="Active",
        state="Running",
        next_run_time="",
        last_run_time="2026-08-25T01:15:30-04:00",
        observed_at_local="2026-08-25T02:00:00-04:00",
    )

    assert result["status"] == "PASS"
    assert result["ready"] is True
    assert result["observation_mode"] == "Active"
    assert result["blocker_codes"] == []


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_execution_entry_rejects_late_or_uncorrelated_run(tmp_path: Path) -> None:
    action = tmp_path / "task.ps1"
    action.write_text("Write-Output 'safe'\n", encoding="utf-8")
    manifest, manifest_hash = _write_manifest(
        tmp_path,
        dependency=action,
        dependency_sha256=_sha256(action),
    )

    result = _invoke_snapshot(
        manifest,
        manifest_hash,
        current_boot="2026-08-24T18:53:27.0000000Z",
        observation_mode="Execution",
        state="Ready",
        next_run_time="",
        last_run_time="2026-08-25T01:30:00-04:00",
        observed_at_local="2026-08-25T01:30:00-04:00",
    )

    assert result["status"] == "BLOCKED"
    assert result["blocker_codes"] == [
        "TASK_NOT_RUNNING",
        "TASK_TRIGGER_OUTSIDE_EXECUTION_WINDOW",
        "TASK_CURRENT_RUN_MISMATCH",
    ]


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_principal_and_late_start_settings_drift_are_blocked(tmp_path: Path) -> None:
    action = tmp_path / "task.ps1"
    action.write_text("Write-Output 'safe'\n", encoding="utf-8")
    manifest, manifest_hash = _write_manifest(
        tmp_path,
        dependency=action,
        dependency_sha256=_sha256(action),
    )

    result = _invoke_snapshot(
        manifest,
        manifest_hash,
        current_boot="2026-08-24T18:53:27.0000000Z",
        principal_logon_type="Interactive",
        principal_run_level="Highest",
        start_when_available=True,
        restart_count=2,
    )

    assert result["status"] == "BLOCKED"
    assert result["blocker_codes"] == [
        "TASK_PRINCIPAL_MISMATCH",
        "TASK_SETTINGS_MISMATCH",
    ]


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_stale_boot_and_dependency_are_reported_together(tmp_path: Path) -> None:
    action = tmp_path / "task.ps1"
    action.write_text("Write-Output 'reviewed'\n", encoding="utf-8")
    reviewed_hash = _sha256(action)
    manifest, manifest_hash = _write_manifest(
        tmp_path,
        dependency=action,
        dependency_sha256=reviewed_hash,
    )
    action.write_text("Write-Output 'changed'\n", encoding="utf-8")

    result = _invoke_snapshot(
        manifest,
        manifest_hash,
        current_boot="2026-08-24T19:01:02.0000000Z",
    )

    assert result["status"] == "BLOCKED"
    assert result["ready"] is False
    assert result["blocker_codes"] == [
        "STALE_BOOT_IDENTITY",
        "STALE_DEPENDENCY_HASH",
    ]


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_exact_action_and_unspent_task_are_required(tmp_path: Path) -> None:
    action = tmp_path / "task.ps1"
    action.write_text("Write-Output 'reviewed'\n", encoding="utf-8")
    manifest, manifest_hash = _write_manifest(
        tmp_path,
        dependency=action,
        dependency_sha256=_sha256(action),
    )

    changed_action = _invoke_snapshot(
        manifest,
        manifest_hash,
        current_boot="2026-08-24T18:53:27.0000000Z",
        action_executable=r"C:\Windows\System32\cmd.exe",
    )
    changed_arguments = _invoke_snapshot(
        manifest,
        manifest_hash,
        current_boot="2026-08-24T18:53:27.0000000Z",
        action_arguments="-NoProfile -File changed.ps1",
    )
    changed_working_directory = _invoke_snapshot(
        manifest,
        manifest_hash,
        current_boot="2026-08-24T18:53:27.0000000Z",
        working_directory=r"C:\Windows",
    )
    already_ran = _invoke_snapshot(
        manifest,
        manifest_hash,
        current_boot="2026-08-24T18:53:27.0000000Z",
        last_run_time="2026-08-24T19:00:00-04:00",
    )

    assert changed_action["blocker_codes"] == ["TASK_ACTION_MISMATCH"]
    assert changed_arguments["blocker_codes"] == ["TASK_ACTION_MISMATCH"]
    assert changed_working_directory["blocker_codes"] == ["TASK_ACTION_MISMATCH"]
    assert already_ran["blocker_codes"] == ["TASK_ALREADY_RAN"]


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_missing_task_preserves_stable_blocker_without_null_dereference(
    tmp_path: Path,
) -> None:
    action = tmp_path / "task.ps1"
    action.write_text("Write-Output 'reviewed'\n", encoding="utf-8")
    manifest, manifest_hash = _write_manifest(
        tmp_path,
        dependency=action,
        dependency_sha256=_sha256(action),
    )
    env = os.environ.copy()
    env.update(
        {
            "WEATHER_READINESS_SCRIPT": str(SCRIPT),
            "WEATHER_READINESS_MANIFEST": str(manifest),
            "WEATHER_READINESS_MANIFEST_SHA": manifest_hash,
        }
    )
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_READINESS_SCRIPT -LibraryOnly
$script:OneShotReadinessSchedulerTimeZone =
    [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$script:OneShotReadinessRegistryRoot = Split-Path -Parent `
    $env:WEATHER_READINESS_MANIFEST
$script:OneShotReadinessRepositoryRoot = Split-Path -Parent `
    $script:OneShotReadinessRegistryRoot
$script:OneShotRegistryIndexRoot = Join-Path `
    $script:OneShotReadinessRepositoryRoot 'one_shot_registry_index'
$script:OneShotReadinessRequireActivationMarker = $false
$contract = Read-WeatherOneShotReadinessManifest `
    -Path $env:WEATHER_READINESS_MANIFEST `
    -ExpectedSha256 $env:WEATHER_READINESS_MANIFEST_SHA
$initial = New-WeatherOneShotReadinessBlocker `
    -Code 'TASK_NOT_FOUND' -Detail 'synthetic missing task'
Test-WeatherOneShotReadinessSnapshot `
    -ManifestContract $contract `
    -ObservedTaskSnapshot $null `
    -CurrentBootIdentity '2026-08-24T18:53:27.0000000Z' `
    -InitialBlockers @($initial) | ConvertTo-Json -Depth 6 -Compress
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["blocker_codes"] == ["TASK_NOT_FOUND"]


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_task_observation_accepts_absent_one_shot_repetition_object(
    tmp_path: Path,
) -> None:
    action = tmp_path / "task.ps1"
    action.write_text("Write-Output 'reviewed'\n", encoding="utf-8")
    manifest, manifest_hash = _write_manifest(
        tmp_path,
        dependency=action,
        dependency_sha256=_sha256(action),
    )
    env = os.environ.copy()
    env.update(
        {
            "WEATHER_READINESS_SCRIPT": str(SCRIPT),
            "WEATHER_READINESS_MANIFEST": str(manifest),
            "WEATHER_READINESS_MANIFEST_SHA": manifest_hash,
        }
    )
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_READINESS_SCRIPT -LibraryOnly
$script:OneShotReadinessSchedulerTimeZone =
    [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$script:OneShotReadinessRegistryRoot = Split-Path -Parent `
    $env:WEATHER_READINESS_MANIFEST
$script:OneShotReadinessRepositoryRoot = Split-Path -Parent `
    $script:OneShotReadinessRegistryRoot
$script:OneShotRegistryIndexRoot = Join-Path `
    $script:OneShotReadinessRepositoryRoot 'one_shot_registry_index'
$script:OneShotReadinessRequireActivationMarker = $false
$contract = Read-WeatherOneShotReadinessManifest `
    -Path $env:WEATHER_READINESS_MANIFEST `
    -ExpectedSha256 $env:WEATHER_READINESS_MANIFEST_SHA
$arguments = Expand-WeatherOneShotArgumentsTemplate `
    -Template ([string]$contract.Manifest.task.arguments_template) `
    -ManifestPath ([string]$contract.ManifestPath) `
    -ManifestSha256 ([string]$contract.ManifestSha256)
$script:syntheticTask = [pscustomobject]@{
    TaskName = [string]$contract.Manifest.task.task_name
    TaskPath = [string]$contract.Manifest.task.task_path
    State = 'Ready'
    Actions = @([pscustomobject]@{
        Id = ''
        Execute = [string]$contract.Manifest.task.executable
        Arguments = $arguments
        WorkingDirectory = [string]$contract.Manifest.task.working_directory
    })
    Triggers = @([pscustomobject]@{
        CimClass = [pscustomobject]@{ CimClassName = 'MSFT_TaskTimeTrigger' }
        Enabled = $true
        Id = ''
        EndBoundary = ''
        RandomDelay = ''
        ExecutionTimeLimit = ''
        StartBoundary = [string]$contract.Manifest.task.trigger_at_local
    })
    Principal = [pscustomobject]@{
        UserId = [string]$contract.Manifest.principal.user_id
        LogonType = 'S4U'
        RunLevel = 'Limited'
        Id = 'Author'
        DisplayName = ''
        GroupId = ''
        ProcessTokenSidType = 'Default'
        RequiredPrivilege = @()
    }
    Settings = [pscustomobject]@{
        Enabled = $true
        MultipleInstances = 'IgnoreNew'
        ExecutionTimeLimit = 'PT2H'
        StartWhenAvailable = $false
        AllowDemandStart = $false
        WakeToRun = $true
        RestartCount = 0
        RestartInterval = ''
        DisallowStartIfOnBatteries = $false
        StopIfGoingOnBatteries = $false
        RunOnlyIfIdle = $false
        RunOnlyIfNetworkAvailable = $false
    }
}
$script:syntheticInfo = [pscustomobject]@{
    NextRunTime = [datetime]'2026-08-25T01:15:00'
    LastRunTime = [datetime]'1999-11-30T00:00:00'
}
function Get-ScheduledTask { return $script:syntheticTask }
function Get-ScheduledTaskInfo {
    param([Parameter(ValueFromPipeline = $true)]$InputObject)
    process { return $script:syntheticInfo }
}
Get-WeatherOneShotTaskObservation -ManifestContract $contract |
    ConvertTo-Json -Depth 6 -Compress
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["Blockers"] == []
    assert payload["Snapshot"]["repetition_interval"] == ""


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_dependency_count_and_aggregate_hash_work_are_bounded(tmp_path: Path) -> None:
    action = tmp_path / "task.ps1"
    action.write_text("12", encoding="utf-8")
    extra = tmp_path / "bound.txt"
    extra.write_text("34", encoding="utf-8")
    must_not_read = tmp_path / "must-not-read.txt"
    must_not_read.write_text("56", encoding="utf-8")
    manifest, manifest_hash = _write_manifest(
        tmp_path,
        dependency=action,
        dependency_sha256=_sha256(action),
        extra_dependencies=(extra, must_not_read),
    )
    must_not_read.unlink()

    env = os.environ.copy()
    env.update(
        {
            "WEATHER_READINESS_SCRIPT": str(SCRIPT),
            "WEATHER_READINESS_MANIFEST": str(manifest),
            "WEATHER_READINESS_MANIFEST_SHA": manifest_hash,
        }
    )
    count_result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            ". $env:WEATHER_READINESS_SCRIPT -LibraryOnly; "
            "$script:OneShotReadinessSchedulerTimeZone = "
            "[TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time'); "
            "$script:OneShotReadinessRegistryRoot = "
            "Split-Path -Parent $env:WEATHER_READINESS_MANIFEST; "
            "$script:OneShotReadinessMaximumDependencyCount = 1; "
            "try { Read-WeatherOneShotReadinessManifest -Path $env:WEATHER_READINESS_MANIFEST "
            "-ExpectedSha256 $env:WEATHER_READINESS_MANIFEST_SHA | Out-Null; 'ACCEPTED' } "
            "catch { 'BLOCKED' }",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    aggregate = _invoke_snapshot(
        manifest,
        manifest_hash,
        current_boot="2026-08-24T18:53:27.0000000Z",
        aggregate_byte_limit=3,
    )

    assert count_result.returncode == 0, count_result.stderr
    assert count_result.stdout.strip() == "BLOCKED"
    assert aggregate["blocker_codes"] == ["DEPENDENCY_AGGREGATE_TOO_LARGE"]


def test_stale_blocker_codes_are_stable_machine_readable_contract() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '-Code "STALE_BOOT_IDENTITY"' in text
    assert '-Code "STALE_DEPENDENCY_HASH"' in text
    assert "blocker_codes" in text


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_nonready_repeating_or_expired_task_reports_stable_blockers(
    tmp_path: Path,
) -> None:
    action = tmp_path / "task.ps1"
    action.write_text("Write-Output 'reviewed'\n", encoding="utf-8")
    manifest, manifest_hash = _write_manifest(
        tmp_path,
        dependency=action,
        dependency_sha256=_sha256(action),
    )

    result = _invoke_snapshot(
        manifest,
        manifest_hash,
        current_boot="2026-08-24T18:53:27.0000000Z",
        state="Running",
        repetition_interval="PT5M",
        next_run_time="2026-08-25T01:20:00-04:00",
        observed_at_local="2026-08-25T01:30:00-04:00",
    )

    assert result["status"] == "BLOCKED"
    assert result["blocker_codes"] == [
        "TASK_NOT_READY",
        "TASK_REPETITION_CONFIGURED",
        "TASK_NEXT_RUN_MISMATCH",
        "TASK_NEXT_RUN_NOT_FUTURE",
    ]


def test_scheduler_readiness_blocker_codes_are_stable() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    for blocker in (
        "TASK_NOT_READY",
        "TASK_NOT_RUNNING",
        "TASK_REPETITION_CONFIGURED",
        "TASK_NEXT_RUN_UNAVAILABLE",
        "TASK_NEXT_RUN_MISMATCH",
        "TASK_NEXT_RUN_NOT_FUTURE",
        "TASK_READINESS_BINDING_MISMATCH",
        "TASK_ALREADY_RAN",
        "TASK_LAST_RUN_UNAVAILABLE",
        "TASK_TRIGGER_OUTSIDE_EXECUTION_WINDOW",
        "TASK_CURRENT_RUN_MISMATCH",
        "TASK_PRINCIPAL_MISMATCH",
        "TASK_SETTINGS_MISMATCH",
        "TASK_OUTSIDE_ADMISSION_WINDOW",
        "TASK_LOCAL_OFFSET_MISMATCH",
        "TASK_LOCAL_TIME_INVALID",
        "MANIFEST_NOT_REGISTRY_ANCHORED",
    ):
        assert f'-Code "{blocker}"' in text
