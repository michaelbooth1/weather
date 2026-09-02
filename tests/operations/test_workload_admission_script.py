from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
LEASE_SCRIPT = REPO_ROOT / "scripts" / "ops" / "workload_admission.ps1"
WORKSTATION_WRAPPER = REPO_ROOT / "scripts" / "ops" / "workstation_heavy.ps1"
POWERSHELL = (
    "powershell",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
)
OUTER_WORKSTATION_LEASE = os.environ.get("WEATHER_WORKSTATION_WRAPPER_ACTIVE") == "1"
WRAPPERS = (
    "training_window.ps1",
    "quiet_window_merge.ps1",
    "bounded_worktree_test_suite.ps1",
    "bounded_execution_tape_probe.ps1",
    "clob_tiering_run.ps1",
    "clob_raw_tape_tiering_run.ps1",
    "daily_refresh.ps1",
)


def _argument_contract(arguments: list[str]) -> str:
    return base64.b64encode(json.dumps(arguments).encode("utf-8")).decode("ascii")


def _install_workstation_wrapper(repo_root: Path) -> Path:
    target_ops = repo_root / "scripts/ops"
    target_ops.mkdir(parents=True, exist_ok=True)
    for name in (
        "workstation_heavy.ps1",
        "workload_admission.ps1",
        "windows_kill_on_close_job.ps1",
    ):
        target = target_ops / name
        if not target.exists():
            shutil.copyfile(REPO_ROOT / "scripts/ops" / name, target)
    admission = target_ops / "workload_admission.ps1"
    source = admission.read_text(encoding="utf-8-sig")
    test_override = "# TEST-ONLY HOST-GLOBAL POISON PATH OVERRIDE"
    if test_override not in source:
        admission.write_text(
            source
            + "\n"
            + test_override
            + "\nfunction Get-WeatherHeavyWorkloadPoisonPath {\n"
            + "    param([switch]$CreateIfMissing)\n"
            + "    Join-Path (Split-Path -Parent (Split-Path -Parent "
            + "$PSScriptRoot)) '.test-heavy-workload.poison'\n"
            + "}\n"
            + "function Get-WeatherActiveWorkstationHeavyProcess { @() }\n",
            encoding="utf-8",
        )
    return target_ops / "workstation_heavy.ps1"


def _workstation_wrapper_argv(repo_root: Path, arguments: list[str]) -> list[str]:
    wrapper = _install_workstation_wrapper(repo_root)
    return [
        *POWERSHELL,
        "-File",
        str(wrapper),
        "-Kind",
        "pytest",
        "-PythonPath",
        sys.executable,
        "-ArgumentsBase64",
        _argument_contract(arguments),
        "-RepoRoot",
        str(repo_root),
    ]


def _write_non_capture_assignment(repo_root: Path) -> None:
    config_root = repo_root / "config"
    config_root.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "WEATHER_LEASE_SCRIPT": str(LEASE_SCRIPT),
        "WEATHER_ASSIGNMENT_PATH": str(
            config_root / "international_live_execution_host.json"
        ),
    }
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
$record = [ordered]@{
    active_portable_execution_host_id = Get-WeatherExecutionHostId
    active_portable_execution_principal_id = Get-WeatherExecutionPrincipalId
    assignment_status = 'ASSIGNED'
    dedicated_capture_execution_host_id = ('f' * 64)
    reassignment_requires_new_production_tip = $true
    schema_version = 'international_live_execution_host_assignment_v0.1'
}
[IO.File]::WriteAllText(
    $env:WEATHER_ASSIGNMENT_PATH,
    ($record | ConvertTo-Json -Compress),
    [Text.UTF8Encoding]::new($false)
)
"""
    result = subprocess.run(
        [*POWERSHELL, "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)


def _inside_heavy_window() -> bool:
    now = datetime.now()
    minute = now.hour * 60 + now.minute
    return 30 <= minute < 9 * 60


def test_every_heavy_wrapper_uses_the_shared_lease() -> None:
    for name in WRAPPERS:
        text = (REPO_ROOT / "scripts" / "ops" / name).read_text(encoding="utf-8-sig")
        assert "workload_admission.ps1" in text, name
        assert "Enter-WeatherHeavyWorkloadLease" in text, name
        assert "Exit-WeatherHeavyWorkloadLease" in text, name


@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="Windows lease")
@pytest.mark.skipif(not _inside_heavy_window(), reason="lease acquisition is policy-blocked now")
@pytest.mark.skipif(OUTER_WORKSTATION_LEASE, reason="outer workstation lease owns mutex")
def test_lease_is_exclusive_and_recovers_when_owner_exits(tmp_path: Path) -> None:
    holder = tmp_path / "holder.ps1"
    holder.write_text(
        f". '{LEASE_SCRIPT}'\n"
        f"$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot '{tmp_path}' -Workload holder\n"
        "if ($null -eq $lease) { Write-Output 'BLOCKED'; exit 3 }\n"
        "Write-Output 'ACQUIRED'\n"
        "Start-Sleep -Seconds 2\n"
        "Exit-WeatherHeavyWorkloadLease -Lease $lease\n",
        encoding="utf-8",
    )
    contender = tmp_path / "contender.ps1"
    contender.write_text(
        f". '{LEASE_SCRIPT}'\n"
        f"$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot '{tmp_path}' -Workload contender\n"
        "if ($null -eq $lease) { Write-Output 'BLOCKED'; exit 3 }\n"
        "Write-Output 'ACQUIRED'\n"
        "Exit-WeatherHeavyWorkloadLease -Lease $lease\n",
        encoding="utf-8",
    )

    owner = subprocess.Popen(
        [*POWERSHELL, "-File", str(holder)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert owner.stdout is not None
    assert owner.stdout.readline().strip() == "ACQUIRED"
    blocked = subprocess.run(
        [*POWERSHELL, "-File", str(contender)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert blocked.returncode == 3
    assert blocked.stdout.strip() == "BLOCKED"
    assert owner.wait(timeout=10) == 0

    recovered = subprocess.run(
        [*POWERSHELL, "-File", str(contender)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert recovered.returncode == 0
    assert recovered.stdout.strip() == "ACQUIRED"


def test_forced_tiering_cannot_bypass_protected_host_window() -> None:
    for name in ("clob_tiering_run.ps1", "clob_raw_tape_tiering_run.ps1"):
        text = (REPO_ROOT / "scripts" / "ops" / name).read_text(encoding="utf-8-sig")
        assert "$localMinute -ge (9 * 60) -or $localMinute -lt 30" in text
        assert "-Forced cannot bypass host policy" in text


def test_shared_lease_owns_the_heavy_window_and_exact_dated_exceptions() -> None:
    text = LEASE_SCRIPT.read_text(encoding="utf-8-sig")

    assert "$localMinute -ge 30 -and $localMinute -lt (9 * 60)" in text
    assert "$localMinute -ge (9 * 60 + 30)" in text
    assert "$localMinute -lt (11 * 60 + 55)" in text
    assert "AllowStageAWindow" in text
    assert "only the explicit Stage-A lane" in text
    assert "OWNER_APPROVED_PROTECTED_WINDOW_MERGE_20260823" in text
    assert "owner_approved_merge_20260823" in text
    assert 'Workload -cne "quiet_window_merge"' in text
    assert 'ToString("yyyy-MM-dd") -cne "2026-08-23"' in text


def test_portable_profile_is_exactly_host_bound_and_live_workload_scoped() -> None:
    text = LEASE_SCRIPT.read_text(encoding="utf-8-sig")

    assert '"capture_colocated_v1"' in text
    assert '"portable_execution_v1"' in text
    assert '"workstation_offline_v1"' in text
    assert '"portable_execution"' in text
    assert "Get-WeatherExecutionHostId" in text
    assert "Get-WeatherExecutionHostAssignment" in text
    assert "active_portable_execution_principal_id" in text
    assert "pre_tool_use_host_load.py" not in text
    assert "portable execution-host admission is forbidden" in text
    assert "capture-colocated International live admission is restricted" in text
    assert '"international_live_execution_host_v2`0$machineGuid"' in text
    assert "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Cryptography" in text
    assert '-Name "MachineGuid"' in text
    assert "$env:COMPUTERNAME" not in text
    assert "$env:USERNAME" not in text
    assert "InternationalLive-(?:stage0|stage1_cancel_all|stage1_dead_man)-" in text
    assert "portable execution-host identity does not match the sealed host binding" in text
    assert "portable execution-host admission cannot combine with Stage-A" in text
    assert '"Global\\WeatherProjectHeavyWorkloadV1"' in text
    assert 'schema_version = "weather_heavy_workload_lease_v3"' in text
    assert "owner_process_creation_time_token" in text
    assert "[Threading.Mutex]::new" in text
    assert "AbandonedMutexException" in text
    assert "[Environment]::MachineName" in text
    assert "Get-WeatherActiveWorkstationHeavyProcess" in text
    assert "ACTIVE workload recovery could not prove heavy-process" in text
    assert "owner_process_start_utc" in text
    assert "ACTIVE workload recovery found {0} residual heavy" in text


def test_host_global_state_uses_a_protected_program_data_acl() -> None:
    text = LEASE_SCRIPT.read_text(encoding="utf-8-sig")

    assert "[Environment+SpecialFolder]::CommonApplicationData" in text
    assert "[Environment+SpecialFolder]::CommonDocuments" not in text
    assert "[Security.AccessControl.DirectorySecurity]::new()" in text
    assert "$directorySecurity.SetAccessRuleProtection($true, $false)" in text
    assert '"S-1-5-18"' in text
    assert '"S-1-5-32-544"' in text
    assert ".GetOwner(" in text
    for right in (
        "WriteData",
        "AppendData",
        "WriteExtendedAttributes",
        "WriteAttributes",
        "Delete",
        "DeleteSubdirectoriesAndFiles",
        "ChangePermissions",
        "TakeOwnership",
    ):
        assert f"[Security.AccessControl.FileSystemRights]::{right}" in text


def test_workstation_wrapper_canonicalizes_modules_before_admission() -> None:
    text = WORKSTATION_WRAPPER.read_text(encoding="utf-8-sig")

    module_path = text.index('"PSModulePath"')
    dot_source_admission = text.index(". $admissionScript")
    enter_admission = text.index("Enter-WeatherHeavyWorkloadLease")
    assert text.count('"PSModulePath"') == 1
    assert module_path < dot_source_admission < enter_admission
    assert "Get-WeatherWorkstationOfflineModule" in text
    assert "train_serve_feature_parity" not in text


def test_calendar_residual_replication_is_an_exact_offline_module() -> None:
    text = LEASE_SCRIPT.read_text(encoding="utf-8-sig")

    assert text.count('"weather.calibration.calendar_residual_replication"') == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows filesystem ACLs")
@pytest.mark.parametrize("shell", ("powershell", "pwsh"))
def test_host_global_state_helpers_round_trip_on_both_powershell_editions(
    tmp_path: Path,
    shell: str,
) -> None:
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} is unavailable")
    env = {
        **os.environ,
        "WEATHER_LEASE_SCRIPT": str(LEASE_SCRIPT),
        "WEATHER_TEST_STATE_ROOT": str(tmp_path / f"state-{shell}"),
    }
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
$security = [Security.AccessControl.DirectorySecurity]::new()
$security.SetAccessRuleProtection($true, $false)
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
$rule = [Security.AccessControl.FileSystemAccessRule]::new(
    $identity,
    [Security.AccessControl.FileSystemRights]::FullControl,
    [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [Security.AccessControl.InheritanceFlags]::ObjectInherit,
    [Security.AccessControl.PropagationFlags]::None,
    [Security.AccessControl.AccessControlType]::Allow
)
[void]$security.AddAccessRule($rule)
$stateRoot = New-WeatherProtectedStateDirectory `
    -Path $env:WEATHER_TEST_STATE_ROOT `
    -Security $security
$observedSecurity = Get-WeatherStateDirectorySecurity -Directory $stateRoot
$markerPath = Join-Path $stateRoot.FullName 'marker.json'
$workload = 'WorkstationOffline-pytest-cross-edition'
$profile = 'workstation_offline_v1'
New-WeatherHeavyWorkloadPoisonMarker `
    -Path $markerPath `
    -Workload $workload `
    -ExecutionHostProfile $profile `
    -State ACTIVE
$active = Get-WeatherHeavyWorkloadPoisonState -Path $markerPath
$pending = Set-WeatherHeavyWorkloadMarkerTeardownPending `
    -Path $markerPath `
    -ExpectedWorkload $workload `
    -ExpectedExecutionHostProfile $profile `
    -ExpectedPid $PID `
    -ExpectedOwnerProcessStartUtc ([string]$active.owner_process_start_utc)
[pscustomobject]@{
    edition = [string]$PSVersionTable.PSEdition
    acl_protected = [bool]$observedSecurity.AreAccessRulesProtected
    active_pid = [int]$active.pid
    active_pid_type = $active.pid.GetType().FullName
    active_boot_type = $active.boot_session_id.GetType().FullName
    active_owner_time_type = $active.owner_process_start_utc.GetType().FullName
    active_changed_time_type = $active.state_changed_at_utc.GetType().FullName
    pending_state = [string]$pending.state
    pending_owner_time_type = $pending.owner_process_start_utc.GetType().FullName
    pending_changed_time_type = $pending.state_changed_at_utc.GetType().FullName
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        [
            shell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["edition"] == ("Desktop" if shell == "powershell" else "Core")
    assert observed["acl_protected"] is True
    assert observed["active_pid"] > 0
    assert observed["active_pid_type"] in ("System.Int32", "System.Int64")
    assert observed["active_boot_type"] in ("System.Int32", "System.Int64")
    assert observed["active_owner_time_type"] == "System.String"
    assert observed["active_changed_time_type"] == "System.String"
    assert observed["pending_state"] == "TEARDOWN_PENDING"
    assert observed["pending_owner_time_type"] == "System.String"
    assert observed["pending_changed_time_type"] == "System.String"


@pytest.mark.skipif(os.name != "nt", reason="Windows JSON runtime types")
@pytest.mark.parametrize("shell", ("powershell", "pwsh"))
def test_marker_reader_rejects_non_integral_and_out_of_range_numbers_on_both_editions(
    tmp_path: Path,
    shell: str,
) -> None:
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} is unavailable")
    valid = {
        "schema_version": "weather_heavy_workload_state_v1",
        "state": "ACTIVE",
        "workload": "WorkstationOffline-pytest-numeric-types",
        "execution_host_profile": "workstation_offline_v1",
        "pid": 123,
        "owner_process_start_utc": "2026-08-28T12:34:56.1234567Z",
        "boot_session_id": 456,
        "state_changed_at_utc": "2026-08-28T12:34:57.1234567Z",
    }
    fixtures = {"valid.json": valid}
    malformed_values = (
        ("pid", "123"),
        ("pid", True),
        ("pid", 123.5),
        ("pid", 2_147_483_648),
        ("boot_session_id", "456"),
        ("boot_session_id", True),
        ("boot_session_id", 456.5),
        ("boot_session_id", -1),
        ("boot_session_id", 2_147_483_648),
    )
    for index, (field, value) in enumerate(malformed_values):
        fixture = dict(valid)
        fixture[field] = value
        fixtures[f"invalid-{index:02d}.json"] = fixture
    marker_root = tmp_path / f"markers-{shell}"
    marker_root.mkdir()
    for name, fixture in fixtures.items():
        (marker_root / name).write_text(
            json.dumps(fixture, separators=(",", ":")), encoding="utf-8"
        )
    env = {
        **os.environ,
        "WEATHER_LEASE_SCRIPT": str(LEASE_SCRIPT),
        "WEATHER_TEST_MARKER_ROOT": str(marker_root),
    }
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
$accepted = @()
foreach ($item in Get-ChildItem -LiteralPath $env:WEATHER_TEST_MARKER_ROOT) {
    try {
        Get-WeatherHeavyWorkloadPoisonState -Path $item.FullName | Out-Null
        $accepted += $item.Name
    }
    catch { }
}
ConvertTo-Json -InputObject @($accepted | Sort-Object) -Compress
"""
    result = subprocess.run(
        [
            shell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["valid.json"]


@pytest.mark.skipif(os.name != "nt", reason="Windows workload state")
@pytest.mark.parametrize("shell", ("powershell", "pwsh"))
def test_poison_recovery_does_not_create_an_absent_state_directory(
    tmp_path: Path,
    shell: str,
) -> None:
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} is unavailable")
    env = {
        **os.environ,
        "WEATHER_LEASE_SCRIPT": str(LEASE_SCRIPT),
        "WEATHER_TEST_COMMON_DATA": str(tmp_path),
    }
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
function Get-WeatherHeavyWorkloadPoisonPath {
    param([switch]$CreateIfMissing)
    Resolve-WeatherHeavyWorkloadPoisonPath `
        -CommonDataRoot $env:WEATHER_TEST_COMMON_DATA `
        -CreateIfMissing:$CreateIfMissing
}
$blocked = $false
try {
    Clear-WeatherHeavyWorkloadPoison `
        -Confirmation 'I_HAVE_VERIFIED_NO_RESIDUAL_WEATHER_WORKLOAD_PROCESSES'
}
catch {
    $blocked = $_.Exception.Message -match 'state directory is absent'
}
[pscustomobject]@{
    blocked = $blocked
    directory_absent = -not (Test-Path -LiteralPath (
        Join-Path $env:WEATHER_TEST_COMMON_DATA 'WeatherProject'
    ))
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        [
            shell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"blocked": True, "directory_absent": True}


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows identity binding",
)
def test_wrong_principal_is_rejected_before_host_global_state_path_access(
    tmp_path: Path,
) -> None:
    env = {
        **os.environ,
        "WEATHER_LEASE_SCRIPT": str(LEASE_SCRIPT),
        "WEATHER_LEASE_ROOT": str(tmp_path),
    }
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
$hostId = Get-WeatherExecutionHostId
$configRoot = Join-Path $env:WEATHER_LEASE_ROOT 'config'
New-Item -ItemType Directory -Path $configRoot | Out-Null
$assignment = [ordered]@{
    active_portable_execution_host_id = $hostId
    active_portable_execution_principal_id = ('0' * 64)
    assignment_status = 'ASSIGNED'
    dedicated_capture_execution_host_id = ('f' * 64)
    reassignment_requires_new_production_tip = $true
    schema_version = 'international_live_execution_host_assignment_v0.1'
}
[IO.File]::WriteAllText(
    (Join-Path $configRoot 'international_live_execution_host.json'),
    ($assignment | ConvertTo-Json -Compress),
    [Text.UTF8Encoding]::new($false)
)
$script:statePathCalls = 0
function Get-WeatherHeavyWorkloadPoisonPath {
    param([switch]$CreateIfMissing)
    $script:statePathCalls++
    throw 'state path must not be touched by an unassigned principal'
}
$portableRejected = $false
try {
    Enter-WeatherHeavyWorkloadLease `
        -RepoRoot $env:WEATHER_LEASE_ROOT `
        -Workload 'InternationalLive-stage0-test-0123456789ab' `
        -ExecutionHostProfile 'portable_execution_v1' `
        -ExpectedExecutionHostId $hostId | Out-Null
}
catch { $portableRejected = $_.Exception.Message -match 'not the active portable' }
$workstationRejected = $false
try {
    Enter-WeatherHeavyWorkloadLease `
        -RepoRoot $env:WEATHER_LEASE_ROOT `
        -Workload 'WorkstationOffline-pytest-wrong-principal' `
        -ExecutionHostProfile 'workstation_offline_v1' | Out-Null
}
catch {
    $workstationRejected = $_.Exception.Message -match
        'not the assigned non-capture workstation'
}
[pscustomobject]@{
    portable_rejected = $portableRejected
    workstation_rejected = $workstationRejected
    state_path_calls = $script:statePathCalls
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        [*POWERSHELL, "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        '{"portable_rejected":true,"workstation_rejected":true,'
        '"state_path_calls":0}'
    )


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows assignment reader",
)
@pytest.mark.parametrize(
    "duplicate_key",
    (
        "schema_version",
        r"schema\u005fversion",
    ),
)
def test_workload_assignment_reader_rejects_duplicate_json_keys(
    tmp_path: Path,
    duplicate_key: str,
) -> None:
    config_root = tmp_path / "config"
    config_root.mkdir()
    assignment = config_root / "international_live_execution_host.json"
    assignment.write_text(
        (
            '{"schema_version":"international_live_execution_host_assignment_v0.1",'
            f'"{duplicate_key}":"international_live_execution_host_assignment_v0.1",'
            '"assignment_status":"UNASSIGNED",'
            f'"dedicated_capture_execution_host_id":"{"f" * 64}",'
            '"active_portable_execution_host_id":null,'
            '"active_portable_execution_principal_id":null,'
            '"reassignment_requires_new_production_tip":true}'
        ),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "WEATHER_LEASE_SCRIPT": str(LEASE_SCRIPT),
        "WEATHER_LEASE_ROOT": str(tmp_path),
    }
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
try {
    Get-WeatherExecutionHostAssignment -RepoRoot $env:WEATHER_LEASE_ROOT |
        Out-Null
    Write-Output 'ACCEPTED'
    exit 3
}
catch {
    Write-Output 'BLOCKED_DUPLICATE'
}
"""
    result = subprocess.run(
        [*POWERSHELL, "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "BLOCKED_DUPLICATE"


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows assignment reader",
)
@pytest.mark.parametrize(
    ("field", "malformed_value"),
    (
        (
            "schema_version",
            ["international_live_execution_host_assignment_v0.1"],
        ),
        ("assignment_status", ["ASSIGNED"]),
        ("dedicated_capture_execution_host_id", ["f" * 64]),
        ("reassignment_requires_new_production_tip", "true"),
        ("reassignment_requires_new_production_tip", 1),
        ("active_portable_execution_host_id", ["e" * 64]),
        ("active_portable_execution_principal_id", ["d" * 64]),
    ),
)
def test_workload_assignment_reader_rejects_malformed_field_types(
    tmp_path: Path,
    field: str,
    malformed_value: object,
) -> None:
    config_root = tmp_path / "config"
    config_root.mkdir()
    assignment = config_root / "international_live_execution_host.json"
    payload: dict[str, object] = {
        "active_portable_execution_host_id": "e" * 64,
        "active_portable_execution_principal_id": "d" * 64,
        "assignment_status": "ASSIGNED",
        "dedicated_capture_execution_host_id": "f" * 64,
        "reassignment_requires_new_production_tip": True,
        "schema_version": "international_live_execution_host_assignment_v0.1",
    }
    payload[field] = malformed_value
    assignment.write_text(json.dumps(payload), encoding="utf-8")
    env = {
        **os.environ,
        "WEATHER_LEASE_SCRIPT": str(LEASE_SCRIPT),
        "WEATHER_LEASE_ROOT": str(tmp_path),
    }
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
try {
    Get-WeatherExecutionHostAssignment -RepoRoot $env:WEATHER_LEASE_ROOT |
        Out-Null
    Write-Output 'ACCEPTED'
    exit 3
}
catch {
    Write-Output 'BLOCKED_TYPE'
}
"""
    result = subprocess.run(
        [*POWERSHELL, "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "BLOCKED_TYPE"


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows assignment reader",
)
def test_workload_assignment_reader_rejects_non_object_root(tmp_path: Path) -> None:
    config_root = tmp_path / "config"
    config_root.mkdir()
    assignment = config_root / "international_live_execution_host.json"
    assignment.write_text(
        json.dumps(
            [
                {
                    "active_portable_execution_host_id": None,
                    "active_portable_execution_principal_id": None,
                    "assignment_status": "UNASSIGNED",
                    "dedicated_capture_execution_host_id": "f" * 64,
                    "reassignment_requires_new_production_tip": True,
                    "schema_version": (
                        "international_live_execution_host_assignment_v0.1"
                    ),
                }
            ]
        ),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "WEATHER_LEASE_SCRIPT": str(LEASE_SCRIPT),
        "WEATHER_LEASE_ROOT": str(tmp_path),
    }
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
try {
    Get-WeatherExecutionHostAssignment -RepoRoot $env:WEATHER_LEASE_ROOT |
        Out-Null
    Write-Output 'ACCEPTED'
    exit 3
}
catch {
    Write-Output 'BLOCKED_ROOT'
}
"""
    result = subprocess.run(
        [*POWERSHELL, "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "BLOCKED_ROOT"


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows assignment reader",
)
def test_workload_assignment_reader_rejects_path_swap_during_read(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "config"
    config_root.mkdir()
    assignment = config_root / "international_live_execution_host.json"
    replacement = config_root / "replacement.json"
    prior = config_root / "prior.json"
    for path, dedicated_id in ((assignment, "e" * 64), (replacement, "f" * 64)):
        path.write_text(
            json.dumps(
                {
                    "active_portable_execution_host_id": None,
                    "active_portable_execution_principal_id": None,
                    "assignment_status": "UNASSIGNED",
                    "dedicated_capture_execution_host_id": dedicated_id,
                    "reassignment_requires_new_production_tip": True,
                    "schema_version": (
                        "international_live_execution_host_assignment_v0.1"
                    ),
                }
            ),
            encoding="utf-8",
        )
    env = {
        **os.environ,
        "WEATHER_LEASE_SCRIPT": str(LEASE_SCRIPT),
        "WEATHER_ASSIGNMENT_PATH": str(assignment),
        "WEATHER_ASSIGNMENT_REPLACEMENT": str(replacement),
        "WEATHER_ASSIGNMENT_PRIOR": str(prior),
    }
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
$afterRead = [Action]{
    Move-Item -LiteralPath $env:WEATHER_ASSIGNMENT_PATH `
        -Destination $env:WEATHER_ASSIGNMENT_PRIOR -ErrorAction Stop
    Move-Item -LiteralPath $env:WEATHER_ASSIGNMENT_REPLACEMENT `
        -Destination $env:WEATHER_ASSIGNMENT_PATH -ErrorAction Stop
}
try {
    Read-WeatherStableExecutionHostAssignmentText `
        -Path $env:WEATHER_ASSIGNMENT_PATH `
        -AfterReadTestHook $afterRead | Out-Null
    Write-Output 'ACCEPTED'
    exit 3
}
catch {
    if ($_.Exception.Message -notmatch 'changed while it was read') {
        throw
    }
    Write-Output 'BLOCKED_SWAP'
}
"""
    result = subprocess.run(
        [*POWERSHELL, "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "BLOCKED_SWAP"
    assert prior.is_file()
    assert assignment.is_file()
    assert not replacement.exists()


def test_workstation_wrapper_holds_shared_lease_and_owns_its_child_tree() -> None:
    text = WORKSTATION_WRAPPER.read_text(encoding="utf-8-sig")
    job_helper = (
        REPO_ROOT / "scripts/ops/windows_kill_on_close_job.ps1"
    ).read_text(encoding="utf-8-sig")

    assert '"workstation_offline_v1"' in text
    assert "windows_kill_on_close_job.ps1" in text
    assert "New-WeatherKillOnCloseJob" in text
    assert "Start-WeatherInteractiveProcessInJob" in text
    assert "ConvertTo-WeatherWindowsArgumentString" in text
    assert "ArgumentsBase64" in text
    assert text.index("Enter-WeatherHeavyWorkloadLease") < text.index(
        "Start-WeatherInteractiveProcessInJob"
    )
    assert text.index("$child.WaitForExit()") < text.index("$job.TerminateAndWait(5000)")
    assert text.index(
        "Set-WeatherHeavyWorkloadLeaseTeardownPending -Lease $lease"
    ) < text.index("$job.TerminateAndWait(5000)")
    assert text.index("$job.TerminateAndWait(5000)") < text.index("$job.Dispose()")
    assert text.index("$job.Dispose()") < text.index(
        "Exit-WeatherHeavyWorkloadLease"
    )
    assert "-ExecutionHostProfile \"workstation_offline_v1\"" in text
    assert "--?(?:live|execute|place|cancel|promote)" in text
    assert "& $resolvedPython" not in text
    assert "Console attachment does not require inheriting every ambient" in job_helper
    assert "interactive,\n                CREATE_SUSPENDED" not in job_helper


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows lease",
)
@pytest.mark.skipif(OUTER_WORKSTATION_LEASE, reason="outer workstation lease owns mutex")
def test_portable_profile_admits_exact_bound_live_workload_at_any_time(
    tmp_path: Path,
) -> None:
    env = os.environ.copy()
    env["WEATHER_LEASE_SCRIPT"] = str(LEASE_SCRIPT)
    env["WEATHER_LEASE_ROOT"] = str(tmp_path)
    env["WEATHER_TEST_POISON_PATH"] = str(tmp_path / "host-global.poison")
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
function Get-WeatherHeavyWorkloadPoisonPath {
    param([switch]$CreateIfMissing)
    $env:WEATHER_TEST_POISON_PATH
}
function Get-WeatherActiveWorkstationHeavyProcess { @() }
$hostId = Get-WeatherExecutionHostId
$principalId = Get-WeatherExecutionPrincipalId
$configRoot = Join-Path $env:WEATHER_LEASE_ROOT 'config'
New-Item -ItemType Directory -Path $configRoot | Out-Null
$assignmentJson = @{
    schema_version = 'international_live_execution_host_assignment_v0.1'
    assignment_status = 'ASSIGNED'
    dedicated_capture_execution_host_id = ('f' * 64)
    active_portable_execution_host_id = $hostId
    active_portable_execution_principal_id = $principalId
    reassignment_requires_new_production_tip = $true
} | ConvertTo-Json
[IO.File]::WriteAllText(
    (Join-Path $configRoot 'international_live_execution_host.json'),
    $assignmentJson,
    [Text.UTF8Encoding]::new($false)
)
$lease = Enter-WeatherHeavyWorkloadLease `
    -RepoRoot $env:WEATHER_LEASE_ROOT `
    -Workload 'InternationalLive-stage0-portable-test-0123456789ab' `
    -ExecutionHostProfile 'portable_execution_v1' `
    -ExpectedExecutionHostId $hostId
if ($null -eq $lease) { throw 'portable lease was unexpectedly busy' }
try {
    $owner = Get-Content -LiteralPath $lease.Path -Raw | ConvertFrom-Json
    $self = [Diagnostics.Process]::GetCurrentProcess()
    try {
        $expectedCreationToken = "win32-filetime:{0}" -f (
            $self.StartTime.ToUniversalTime().ToFileTimeUtc()
        )
    }
    finally { $self.Dispose() }
    $wrongHostRejected = $false
    try {
        Enter-WeatherHeavyWorkloadLease `
            -RepoRoot $env:WEATHER_LEASE_ROOT `
            -Workload 'InternationalLive-stage0-portable-test-0123456789ab' `
            -ExecutionHostProfile 'portable_execution_v1' `
            -ExpectedExecutionHostId ('0' * 64)
    }
    catch { $wrongHostRejected = $true }
    $wrongWorkloadRejected = $false
    try {
        Enter-WeatherHeavyWorkloadLease `
            -RepoRoot $env:WEATHER_LEASE_ROOT `
            -Workload 'portable-test' `
            -ExecutionHostProfile 'portable_execution_v1' `
            -ExpectedExecutionHostId $hostId
    }
    catch { $wrongWorkloadRejected = $true }
    $stageARejected = $false
    try {
        Enter-WeatherHeavyWorkloadLease `
            -RepoRoot $env:WEATHER_LEASE_ROOT `
            -Workload 'InternationalLive-stage0-portable-test-0123456789ab' `
            -AllowStageAWindow `
            -ExecutionHostProfile 'portable_execution_v1' `
            -ExpectedExecutionHostId $hostId
    }
    catch { $stageARejected = $true }
    $ownerExceptionRejected = $false
    try {
        Enter-WeatherHeavyWorkloadLease `
            -RepoRoot $env:WEATHER_LEASE_ROOT `
            -Workload 'InternationalLive-stage0-portable-test-0123456789ab' `
            -OwnerApprovedException 'OWNER_APPROVED_PROTECTED_WINDOW_MERGE_20260823' `
            -ExecutionHostProfile 'portable_execution_v1' `
            -ExpectedExecutionHostId $hostId
    }
    catch { $ownerExceptionRejected = $true }
    [pscustomobject]@{
        acquired = $true
        schema = [string]$owner.schema_version
        creation_token_matches = (
            [string]$owner.owner_process_creation_time_token -ceq
            $expectedCreationToken
        )
        policy_window = [string]$owner.policy_window
        profile = [string]$owner.execution_host_profile
        identity_matches = [string]$owner.execution_host_id -ceq $hostId
        wrong_host_rejected = $wrongHostRejected
        wrong_workload_rejected = $wrongWorkloadRejected
        stage_a_rejected = $stageARejected
        owner_exception_rejected = $ownerExceptionRejected
    } | ConvertTo-Json -Compress
}
finally {
    Set-WeatherHeavyWorkloadLeaseTeardownPending -Lease $lease | Out-Null
    Exit-WeatherHeavyWorkloadLease -Lease $lease
}
"""
    result = subprocess.run(
        [*POWERSHELL, "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        '{"acquired":true,"schema":"weather_heavy_workload_lease_v3",'
        '"creation_token_matches":true,"policy_window":"portable_execution",'
        '"profile":"portable_execution_v1","identity_matches":true,'
        '"wrong_host_rejected":true,"wrong_workload_rejected":true,'
        '"stage_a_rejected":true,"owner_exception_rejected":true}'
    )


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows lease",
)
@pytest.mark.skipif(OUTER_WORKSTATION_LEASE, reason="outer workstation lease owns mutex")
def test_workstation_profile_is_any_time_but_strictly_non_capture_and_offline(
    tmp_path: Path,
) -> None:
    env = os.environ.copy()
    env["WEATHER_LEASE_SCRIPT"] = str(LEASE_SCRIPT)
    env["WEATHER_LEASE_ROOT"] = str(tmp_path)
    env["WEATHER_TEST_POISON_PATH"] = str(tmp_path / "host-global.poison")
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
function Get-WeatherHeavyWorkloadPoisonPath {
    param([switch]$CreateIfMissing)
    $env:WEATHER_TEST_POISON_PATH
}
$hostId = Get-WeatherExecutionHostId
$principalId = Get-WeatherExecutionPrincipalId
$configRoot = Join-Path $env:WEATHER_LEASE_ROOT 'config'
New-Item -ItemType Directory -Path $configRoot | Out-Null
$assignmentPath = Join-Path $configRoot 'international_live_execution_host.json'
function Write-TestAssignment([string]$DedicatedId, [bool]$Assigned) {
    $assignmentJson = @{
        schema_version = 'international_live_execution_host_assignment_v0.1'
        assignment_status = $(if ($Assigned) { 'ASSIGNED' } else { 'UNASSIGNED' })
        dedicated_capture_execution_host_id = $DedicatedId
        active_portable_execution_host_id = $(if ($Assigned) { $hostId } else { $null })
        active_portable_execution_principal_id = $(if ($Assigned) { $principalId } else { $null })
        reassignment_requires_new_production_tip = $true
    } | ConvertTo-Json
    [IO.File]::WriteAllText(
        $assignmentPath,
        $assignmentJson,
        [Text.UTF8Encoding]::new($false)
    )
}
Write-TestAssignment $hostId $false
$captureRejected = $false
try {
    Enter-WeatherHeavyWorkloadLease `
        -RepoRoot $env:WEATHER_LEASE_ROOT `
        -Workload 'WorkstationOffline-pytest-test' `
        -ExecutionHostProfile 'workstation_offline_v1'
}
catch { $captureRejected = $_.Exception.Message -match 'dedicated capture host' }
Write-TestAssignment ('f' * 64) $true
$liveNameRejected = $false
try {
    Enter-WeatherHeavyWorkloadLease `
        -RepoRoot $env:WEATHER_LEASE_ROOT `
        -Workload 'InternationalLive-stage0-test-0123456789ab' `
        -ExecutionHostProfile 'workstation_offline_v1'
}
catch { $liveNameRejected = $_.Exception.Message -match 'canonical offline workload' }
$exceptionRejected = $false
try {
    Enter-WeatherHeavyWorkloadLease `
        -RepoRoot $env:WEATHER_LEASE_ROOT `
        -Workload 'WorkstationOffline-pytest-test' `
        -AllowStageAWindow `
        -ExecutionHostProfile 'workstation_offline_v1'
}
catch { $exceptionRejected = $_.Exception.Message -match 'cannot combine' }
$bindingRejected = $false
try {
    Enter-WeatherHeavyWorkloadLease `
        -RepoRoot $env:WEATHER_LEASE_ROOT `
        -Workload 'WorkstationOffline-pytest-test' `
        -ExecutionHostProfile 'workstation_offline_v1' `
        -ExpectedExecutionHostId $hostId
}
catch { $bindingRejected = $_.Exception.Message -match 'does not accept a live host binding' }
$lease = Enter-WeatherHeavyWorkloadLease `
    -RepoRoot $env:WEATHER_LEASE_ROOT `
    -Workload 'WorkstationOffline-pytest-test' `
    -ExecutionHostProfile 'workstation_offline_v1'
$owner = Get-Content -LiteralPath $lease.Path -Raw | ConvertFrom-Json
Set-WeatherHeavyWorkloadLeaseTeardownPending -Lease $lease | Out-Null
Exit-WeatherHeavyWorkloadLease -Lease $lease
[pscustomobject]@{
    capture_rejected = $captureRejected
    live_name_rejected = $liveNameRejected
    exception_rejected = $exceptionRejected
    binding_rejected = $bindingRejected
    admitted = [string]$owner.policy_window -ceq 'workstation_offline'
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        [*POWERSHELL, "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        '{"capture_rejected":true,"live_name_rejected":true,'
        '"exception_rejected":true,"binding_rejected":true,"admitted":true}'
    )


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows lease",
)
@pytest.mark.skipif(OUTER_WORKSTATION_LEASE, reason="outer workstation lease owns mutex")
def test_portable_live_and_workstation_heavy_profiles_are_mutually_exclusive(
    tmp_path: Path,
) -> None:
    roots = (tmp_path / "repo-a", tmp_path / "repo-b")
    env = os.environ.copy()
    env["WEATHER_LEASE_SCRIPT"] = str(LEASE_SCRIPT)
    env["WEATHER_TEST_POISON_PATH"] = str(tmp_path / "host-global.poison")
    prepare = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
$configRoot = Join-Path $env:WEATHER_LEASE_ROOT 'config'
New-Item -ItemType Directory -Path $configRoot -Force | Out-Null
$assignmentJson = @{
    schema_version = 'international_live_execution_host_assignment_v0.1'
    assignment_status = 'ASSIGNED'
    dedicated_capture_execution_host_id = ('f' * 64)
    active_portable_execution_host_id = (Get-WeatherExecutionHostId)
    active_portable_execution_principal_id = (Get-WeatherExecutionPrincipalId)
    reassignment_requires_new_production_tip = $true
} | ConvertTo-Json
[IO.File]::WriteAllText(
    (Join-Path $configRoot 'international_live_execution_host.json'),
    $assignmentJson,
    [Text.UTF8Encoding]::new($false)
)
"""
    for root in roots:
        root.mkdir()
        prepare_env = env.copy()
        prepare_env["WEATHER_LEASE_ROOT"] = str(root)
        prepared = subprocess.run(
            [*POWERSHELL, "-Command", prepare],
            capture_output=True,
            text=True,
            check=False,
            env=prepare_env,
        )
        assert prepared.returncode == 0, prepared.stderr

    holder_template = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
function Get-WeatherHeavyWorkloadPoisonPath {{
    param([switch]$CreateIfMissing)
    $env:WEATHER_TEST_POISON_PATH
}}
function Get-WeatherActiveWorkstationHeavyProcess {{ @() }}
$hostId = Get-WeatherExecutionHostId
$lease = Enter-WeatherHeavyWorkloadLease `
    -RepoRoot $env:WEATHER_LEASE_ROOT `
    -Workload '{workload}' `
    -ExecutionHostProfile '{profile}' {host_binding}
if ($null -eq $lease) {{ Write-Output 'BLOCKED'; exit 3 }}
Write-Output 'ACQUIRED'
Start-Sleep -Seconds 2
Set-WeatherHeavyWorkloadLeaseTeardownPending -Lease $lease | Out-Null
Exit-WeatherHeavyWorkloadLease -Lease $lease
"""
    contender_template = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
function Get-WeatherHeavyWorkloadPoisonPath {{
    param([switch]$CreateIfMissing)
    $env:WEATHER_TEST_POISON_PATH
}}
$hostId = Get-WeatherExecutionHostId
$lease = Enter-WeatherHeavyWorkloadLease `
    -RepoRoot $env:WEATHER_LEASE_ROOT `
    -Workload '{workload}' `
    -ExecutionHostProfile '{profile}' {host_binding}
if ($null -eq $lease) {{ Write-Output 'BLOCKED'; exit 3 }}
Write-Output 'ACQUIRED'
Set-WeatherHeavyWorkloadLeaseTeardownPending -Lease $lease | Out-Null
Exit-WeatherHeavyWorkloadLease -Lease $lease
"""
    profiles = (
        (
            "workstation_offline_v1",
            "WorkstationOffline-pytest-holder",
            "",
            "portable_execution_v1",
            "InternationalLive-stage0-test-0123456789ab",
            "-ExpectedExecutionHostId $hostId",
            roots[0],
            roots[1],
        ),
        (
            "portable_execution_v1",
            "InternationalLive-stage0-test-0123456789ab",
            "-ExpectedExecutionHostId $hostId",
            "workstation_offline_v1",
            "WorkstationOffline-pytest-contender",
            "",
            roots[1],
            roots[0],
        ),
    )
    for (
        holder_profile,
        holder_workload,
        holder_binding,
        contender_profile,
        contender_workload,
        contender_binding,
        holder_root,
        contender_root,
    ) in profiles:
        holder_script = holder_template.format(
            profile=holder_profile,
            workload=holder_workload,
            host_binding=holder_binding,
        )
        contender_script = contender_template.format(
            profile=contender_profile,
            workload=contender_workload,
            host_binding=contender_binding,
        )
        holder_env = env.copy()
        holder_env["WEATHER_LEASE_ROOT"] = str(holder_root)
        contender_env = env.copy()
        contender_env["WEATHER_LEASE_ROOT"] = str(contender_root)
        owner = subprocess.Popen(
            [*POWERSHELL, "-Command", holder_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=holder_env,
        )
        assert owner.stdout is not None
        assert owner.stdout.readline().strip() == "ACQUIRED"
        blocked = subprocess.run(
            [*POWERSHELL, "-Command", contender_script],
            capture_output=True,
            text=True,
            check=False,
            env=contender_env,
        )
        assert blocked.returncode == 3, blocked.stderr
        assert blocked.stdout.strip() == "BLOCKED"
        assert owner.wait(timeout=10) == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows process classifier")
@pytest.mark.parametrize("shell", ("powershell", "pwsh"))
def test_workstation_process_classifier_covers_every_offline_module(
    shell: str,
) -> None:
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} is unavailable")
    shell_argv = (
        POWERSHELL
        if shell == "powershell"
        else ("pwsh", "-NoProfile", "-NonInteractive")
    )
    env = {**os.environ, "WEATHER_LEASE_SCRIPT": str(LEASE_SCRIPT)}
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
$rows = @(
    [pscustomobject]@{
        ProcessId = $PID
        ParentProcessId = 101
        Name = 'powershell.exe'
        CommandLine = 'powershell harmless'
    },
    [pscustomobject]@{
        ProcessId = 101
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python -m pytest tests\test_x.py'
    },
    [pscustomobject]@{
        ProcessId = 102
        ParentProcessId = 10
        Name = 'git.exe'
        CommandLine = 'git commit -m pytest'
    },
    [pscustomobject]@{
        ProcessId = 103
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = $null
    },
    [pscustomobject]@{
        ProcessId = 104
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python service.py'
    },
    [pscustomobject]@{
        ProcessId = 105
        ParentProcessId = 10
        Name = 'pytest.exe'
        CommandLine = $null
    },
    [pscustomobject]@{
        ProcessId = 106
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python -I -S -B -c "import runpy,sys;sys.dont_write_bytecode=True;runpy.run_path(x)"'
    },
    [pscustomobject]@{
        ProcessId = 107
        ParentProcessId = 10
        Name = 'python3.12.exe'
        CommandLine = 'python3.12.exe -m pytest tests\test_x.py'
    },
    [pscustomobject]@{
        ProcessId = 108
        ParentProcessId = 10
        Name = 'pythonw3.10.exe'
        CommandLine = $null
    },
    [pscustomobject]@{
        ProcessId = 109
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python -m weather.operations.experimental_training --dry-run'
    },
    [pscustomobject]@{
        ProcessId = 110
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe "-m" weather.operations.experimental_training'
    },
    [pscustomobject]@{
        ProcessId = 111
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -m "weather.operations.experimental_training"'
    },
    [pscustomobject]@{
        ProcessId = 112
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe "-m" "weather.reporting.scorecards.train_serve_feature_parity"'
    },
    [pscustomobject]@{
        ProcessId = 113
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -Bmpytest -q'
    },
    [pscustomobject]@{
        ProcessId = 114
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe "-m"pytest -q'
    },
    [pscustomobject]@{
        ProcessId = 115
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -BImweather.operations.nightly_retrain --dry-run'
    },
    [pscustomobject]@{
        ProcessId = 116
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -Bm pytest -q'
    },
    [pscustomobject]@{
        ProcessId = 117
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe "-Bm"pytest -q'
    },
    [pscustomobject]@{
        ProcessId = 118
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -BIm weather.operations.nightly_retrain --dry-run'
    },
    [pscustomobject]@{
        ProcessId = 119
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -Bm pip --version'
    },
    [pscustomobject]@{
        ProcessId = 120
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -W -mpip -mpytest -q'
    },
    [pscustomobject]@{
        ProcessId = 121
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -X -mpip -BIm weather.operations.nightly_retrain --dry-run'
    },
    [pscustomobject]@{
        ProcessId = 122
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -W -mpytest -mpip --version'
    },
    [pscustomobject]@{
        ProcessId = 123
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe service.py -mpytest -q'
    },
    [pscustomobject]@{
        ProcessId = 124
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -BIm pytest.__main__ -q'
    },
    [pscustomobject]@{
        ProcessId = 125
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -m coverage run -m pytest'
    },
    [pscustomobject]@{
        ProcessId = 126
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -m tox -e py311'
    },
    [pscustomobject]@{
        ProcessId = 127
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -m nox -s tests'
    },
    [pscustomobject]@{
        ProcessId = 128
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -c "print(1)" -mpytest -q'
    },
    [pscustomobject]@{
        ProcessId = 129
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -- service.py -mpytest -q'
    },
    [pscustomobject]@{
        ProcessId = 130
        ParentProcessId = 10
        Name = 'py.exe'
        CommandLine = 'py.exe -V:PythonCore/3.12 -m pytest -q'
    },
    [pscustomobject]@{
        ProcessId = 131
        ParentProcessId = 10
        Name = 'py.exe'
        CommandLine = 'py.exe -V:3.12 -m weather.operations.nightly_retrain --dry-run'
    },
    [pscustomobject]@{
        ProcessId = 132
        ParentProcessId = 10
        Name = 'py.exe'
        CommandLine = 'py.exe -3.13t -m pytest -q'
    },
    [pscustomobject]@{
        ProcessId = 133
        ParentProcessId = 10
        Name = 'pyw.exe'
        CommandLine = 'pyw.exe -V:3.12 -m pytest -q'
    },
    [pscustomobject]@{
        ProcessId = 134
        ParentProcessId = 10
        Name = 'pymanager.exe'
        CommandLine = 'pymanager.exe exec -m pytest -q'
    },
    [pscustomobject]@{
        ProcessId = 135
        ParentProcessId = 10
        Name = 'pywmanager.exe'
        CommandLine = 'pywmanager.exe exec -m weather.operations.nightly_retrain --dry-run'
    },
    [pscustomobject]@{
        ProcessId = 136
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -m coverage.__main__ run -m pytest'
    },
    [pscustomobject]@{
        ProcessId = 137
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -m tox.__main__ -e py311'
    },
    [pscustomobject]@{
        ProcessId = 138
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -m nox.__main__ -s tests'
    },
    [pscustomobject]@{
        ProcessId = 139
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -m cProfile -m pytest -q'
    },
    [pscustomobject]@{
        ProcessId = 140
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -V -mpytest -q'
    },
    [pscustomobject]@{
        ProcessId = 141
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = 'python.exe -x -mpip -mpytest -q'
    },
    [pscustomobject]@{
        ProcessId = 142
        ParentProcessId = 10
        Name = 'python3.13t.exe'
        CommandLine = 'python3.13t.exe -m pytest -q'
    },
    [pscustomobject]@{
        ProcessId = 143
        ParentProcessId = 10
        Name = 'python_d.exe'
        CommandLine = 'python_d.exe -m pytest -q'
    },
    [pscustomobject]@{
        ProcessId = 144
        ParentProcessId = 10
        Name = 'py.exe'
        CommandLine = 'py.exe exec --quiet -m pytest -q'
    },
    [pscustomobject]@{
        ProcessId = 145
        ParentProcessId = 10
        Name = 'pymanager.exe'
        CommandLine = 'pymanager.exe exec --config C:\tmp\pymanager.json -m weather.operations.nightly_retrain --dry-run'
    },
    [pscustomobject]@{
        ProcessId = 146
        ParentProcessId = 10
        Name = 'py-manager.exe'
        CommandLine = 'py-manager.exe exec -m pytest -q'
    },
    [pscustomobject]@{
        ProcessId = 147
        ParentProcessId = 10
        Name = 'pyw-manager.exe'
        CommandLine = 'pyw-manager.exe exec -m weather.operations.nightly_retrain --dry-run'
    },
    [pscustomobject]@{
        ProcessId = 148
        ParentProcessId = 10
        Name = 'py-manager.exe'
        CommandLine = 'py-manager.exe exec -m pip --version'
    },
    [pscustomobject]@{
        ProcessId = 149
        ParentProcessId = 10
        Name = 'python3.13-64.exe'
        CommandLine = 'python3.13-64.exe -m pytest -q'
    },
    [pscustomobject]@{
        ProcessId = 150
        ParentProcessId = 10
        Name = 'pythonw3t-arm64.exe'
        CommandLine = 'pythonw3t-arm64.exe -m pip --version'
    },
    [pscustomobject]@{
        ProcessId = 151
        ParentProcessId = 10
        Name = 'py.exe'
        CommandLine = 'py.exe /V:3.14 -m pytest -q'
    },
    [pscustomobject]@{
        ProcessId = 152
        ParentProcessId = 10
        Name = 'py.exe'
        CommandLine = 'py.exe /3.14 -m weather.operations.nightly_retrain --dry-run'
    },
    [pscustomobject]@{
        ProcessId = 153
        ParentProcessId = 10
        Name = 'py.exe'
        CommandLine = 'py.exe -V: -m pip --version'
    },
    [pscustomobject]@{
        ProcessId = 154
        ParentProcessId = 10
        Name = 'coverage3.exe'
        CommandLine = 'coverage3.exe run -m pytest -q'
    },
    [pscustomobject]@{
        ProcessId = 155
        ParentProcessId = 10
        Name = 'coverage-3.11.exe'
        CommandLine = 'coverage-3.11.exe run -m pytest -q'
    }
)
$expectedProcessIds = @(
    101, 103, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115,
    116, 117, 118, 120, 121, 124, 125, 126, 127, 130, 131, 132, 133,
    134, 135, 136, 137, 138, 139, 142, 143, 144, 145, 146, 147, 149,
    151, 152, 154, 155
)
$nextProcessId = 200
foreach ($offlineModule in @(Get-WeatherWorkstationOfflineModule)) {
    $rows += [pscustomobject]@{
        ProcessId = $nextProcessId
        ParentProcessId = 10
        Name = 'python.exe'
        CommandLine = "python -m $offlineModule --dry-run"
    }
    $expectedProcessIds += $nextProcessId
    $nextProcessId += 1
}
$detected = @(Get-WeatherActiveWorkstationHeavyProcess -ProcessSnapshot $rows)
if (
    (@($detected.ProcessId) -join ',') -cne
        ($expectedProcessIds -join ',')
) {
    throw 'process classifier did not fail closed exactly'
}
"""
    result = subprocess.run(
        [*shell_argv, "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows lease",
)
@pytest.mark.skipif(OUTER_WORKSTATION_LEASE, reason="outer workstation lease owns mutex")
def test_process_quiescence_is_fail_closed_without_heavy_ancestor_exemptions(
    tmp_path: Path,
) -> None:
    env = os.environ.copy()
    env["WEATHER_LEASE_SCRIPT"] = str(LEASE_SCRIPT)
    env["WEATHER_LEASE_ROOT"] = str(tmp_path)
    env["WEATHER_TEST_POISON_PATH"] = str(tmp_path / "host-global.poison")
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
function Get-WeatherHeavyWorkloadPoisonPath {
    param([switch]$CreateIfMissing)
    $env:WEATHER_TEST_POISON_PATH
}
$hostId = Get-WeatherExecutionHostId
$principalId = Get-WeatherExecutionPrincipalId
$configRoot = Join-Path $env:WEATHER_LEASE_ROOT 'config'
New-Item -ItemType Directory -Path $configRoot | Out-Null
$assignmentJson = @{
    schema_version = 'international_live_execution_host_assignment_v0.1'
    assignment_status = 'ASSIGNED'
    dedicated_capture_execution_host_id = ('f' * 64)
    active_portable_execution_host_id = $hostId
    active_portable_execution_principal_id = $principalId
    reassignment_requires_new_production_tip = $true
} | ConvertTo-Json
[IO.File]::WriteAllText(
    (Join-Path $env:WEATHER_LEASE_ROOT 'config\international_live_execution_host.json'),
    $assignmentJson,
    [Text.UTF8Encoding]::new($false)
)
function Get-WeatherActiveWorkstationHeavyProcess {
    [pscustomobject]@{ ProcessId = 101; Name = 'python.exe' }
}
$staleMarker = [ordered]@{
    schema_version = 'weather_heavy_workload_state_v1'
    state = 'ACTIVE'
    workload = 'WorkstationOffline-pytest-stale-owner'
    execution_host_profile = 'workstation_offline_v1'
    pid = 2147483647
    owner_process_start_utc = '2000-01-01T00:00:00.0000000Z'
    boot_session_id = Get-WeatherBootSessionId
    state_changed_at_utc = '2000-01-01T00:00:00.0000000Z'
} | ConvertTo-Json -Compress
[IO.File]::WriteAllText(
    $env:WEATHER_TEST_POISON_PATH,
    $staleMarker,
    [Text.UTF8Encoding]::new($false)
)
$blocked = $false
try {
    Enter-WeatherHeavyWorkloadLease `
        -RepoRoot $env:WEATHER_LEASE_ROOT `
        -Workload 'InternationalLive-stage0-test-0123456789ab' `
        -ExecutionHostProfile 'portable_execution_v1' `
        -ExpectedExecutionHostId $hostId
}
catch {
    $blocked = $_.Exception.Message -match 'residual heavy'
}
$probe = [Threading.Mutex]::new($false, 'Global\WeatherProjectHeavyWorkloadV1')
$probeOwned = $false
try { $probeOwned = $probe.WaitOne(0, $false) }
catch [Threading.AbandonedMutexException] { $probeOwned = $true }
if ($probeOwned) { $probe.ReleaseMutex() }
$probe.Dispose()
[pscustomobject]@{
    classifier = $true
    live_blocked = $blocked
    mutex_released = $probeOwned
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        [*POWERSHELL, "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        '{"classifier":true,"live_blocked":true,"mutex_released":true}'
    )


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows lease",
)
@pytest.mark.skipif(OUTER_WORKSTATION_LEASE, reason="outer workstation lease owns mutex")
def test_active_state_cannot_be_recovered_while_exact_owner_process_exists(
    tmp_path: Path,
) -> None:
    _write_non_capture_assignment(tmp_path)
    env = {
        **os.environ,
        "WEATHER_LEASE_SCRIPT": str(LEASE_SCRIPT),
        "WEATHER_LEASE_ROOT": str(tmp_path),
        "WEATHER_TEST_POISON_PATH": str(tmp_path / "host-global.poison"),
    }
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
function Get-WeatherHeavyWorkloadPoisonPath {
    param([switch]$CreateIfMissing)
    $env:WEATHER_TEST_POISON_PATH
}
function Get-WeatherActiveWorkstationHeavyProcess {
    throw 'owner-alive admission must not begin residual recovery'
}
New-WeatherHeavyWorkloadPoisonMarker `
    -Path $env:WEATHER_TEST_POISON_PATH `
    -Workload 'WorkstationOffline-pytest-owner-alive' `
    -ExecutionHostProfile 'workstation_offline_v1' `
    -State 'ACTIVE'
$blocked = $false
try {
    Enter-WeatherHeavyWorkloadLease `
        -RepoRoot $env:WEATHER_LEASE_ROOT `
        -Workload 'WorkstationOffline-pytest-owner-probe' `
        -ExecutionHostProfile 'workstation_offline_v1' | Out-Null
}
catch { $blocked = $_.Exception.Message -match 'owner process still exists' }
$preserved = Test-Path -LiteralPath $env:WEATHER_TEST_POISON_PATH
[IO.File]::Delete($env:WEATHER_TEST_POISON_PATH)
[pscustomobject]@{
    blocked = $blocked
    preserved = $preserved
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        [*POWERSHELL, "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '{"blocked":true,"preserved":true}'


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows wrapper",
)
@pytest.mark.skipif(OUTER_WORKSTATION_LEASE, reason="outer workstation lease owns mutex")
def test_workstation_wrapper_executes_approved_pytest_and_rejects_live_mode(
    tmp_path: Path,
) -> None:
    _write_non_capture_assignment(tmp_path)
    focused = tmp_path / "test_wrapper_child.py"
    focused.write_text("def test_ok():\n    assert 2 + 2 == 4\n", encoding="utf-8")
    approved_arguments = base64.b64encode(
        json.dumps(["-m", "pytest", str(focused), "-q"]).encode("utf-8")
    ).decode("ascii")
    approved = subprocess.run(
        [
            *POWERSHELL,
            "-File",
            str(_install_workstation_wrapper(tmp_path)),
            "-Kind",
            "pytest",
            "-PythonPath",
            sys.executable,
            "-ArgumentsBase64",
            approved_arguments,
            "-RepoRoot",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert approved.returncode == 0, approved.stderr
    assert "1 passed" in approved.stdout
    owner = json.loads((tmp_path / "data" / "logs" / "heavy_workload.lock").read_text())
    assert owner["execution_host_profile"] == "workstation_offline_v1"
    assert owner["policy_window"] == "workstation_offline"

    rejected = subprocess.run(
        [
            *POWERSHELL,
            "-File",
            str(_install_workstation_wrapper(tmp_path)),
            "-Kind",
            "weather_heavy",
            "-PythonPath",
            sys.executable,
            "-ArgumentsBase64",
            base64.b64encode(
                json.dumps(
                    ["-m", "weather.operations.density_live_replay_parity", "--live"]
                ).encode("utf-8")
            ).decode("ascii"),
            "-RepoRoot",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "offline training/replay" in rejected.stderr


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows wrapper",
)
@pytest.mark.skipif(OUTER_WORKSTATION_LEASE, reason="outer workstation lease owns mutex")
def test_workstation_wrapper_blocks_before_child_and_cleans_descendants(
    tmp_path: Path,
) -> None:
    _write_non_capture_assignment(tmp_path)
    busy_sentinel = tmp_path / "busy-child-started.txt"
    busy_test = tmp_path / "test_busy_child.py"
    busy_test.write_text(
        "from pathlib import Path\n\n"
        "def test_must_not_start():\n"
        f"    Path({str(busy_sentinel)!r}).write_text('started')\n",
        encoding="utf-8",
    )
    holder_script = r"""
$ErrorActionPreference = 'Stop'
$mutex = [Threading.Mutex]::new($false, 'Global\WeatherProjectHeavyWorkloadV1')
$owned = $false
try {
    try { $owned = $mutex.WaitOne(0, $false) }
    catch [Threading.AbandonedMutexException] { $owned = $true }
    if (-not $owned) { throw 'test mutex unexpectedly busy' }
    Write-Output 'ACQUIRED'
    Start-Sleep -Seconds 2
}
finally {
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
"""
    holder = subprocess.Popen(
        [*POWERSHELL, "-Command", holder_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None
    assert holder.stdout.readline().strip() == "ACQUIRED"
    blocked = subprocess.run(
        _workstation_wrapper_argv(
            tmp_path,
            ["-m", "pytest", str(busy_test), "-q"],
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert blocked.returncode != 0
    assert "blocked by another heavy or portable live lease" in blocked.stderr
    assert not busy_sentinel.exists()
    assert holder.wait(timeout=10) == 0

    quoted_root = tmp_path / "unicodé's child"
    quoted_root.mkdir()
    grandchild_done = tmp_path / "grandchild-survived.txt"
    spawn_test = quoted_root / "test_job_tree.py"
    child_code = (
        "import time; from pathlib import Path; time.sleep(1); "
        f"Path({str(grandchild_done)!r}).write_text('survived')"
    )
    spawn_test.write_text(
        "import subprocess\n"
        "import sys\n\n"
        "def test_spawn_detached_candidate():\n"
        f"    subprocess.Popen([sys.executable, '-c', {child_code!r}])\n",
        encoding="utf-8",
    )
    contained = subprocess.run(
        _workstation_wrapper_argv(
            tmp_path,
            ["-m", "pytest", str(spawn_test), "-q"],
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert contained.returncode == 0, contained.stderr
    assert "1 passed" in contained.stdout
    time.sleep(1.25)
    assert not grandchild_done.exists()

    stderr_test = quoted_root / "test_stderr_exit.py"
    stderr_test.write_text(
        "import sys\n\n"
        "def test_exact_failure():\n"
        "    print('WORKSTATION_WRAPPER_STDERR', file=sys.stderr, flush=True)\n"
        "    assert False\n",
        encoding="utf-8",
    )
    failed = subprocess.run(
        _workstation_wrapper_argv(
            tmp_path,
            ["-m", "pytest", str(stderr_test), "-q", "-s"],
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert failed.returncode == 1
    assert "WORKSTATION_WRAPPER_STDERR" in failed.stderr


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows wrapper",
)
@pytest.mark.skipif(OUTER_WORKSTATION_LEASE, reason="outer workstation lease owns mutex")
def test_failed_job_teardown_durably_poison_blocks_other_repo_roots(
    tmp_path: Path,
) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    _write_non_capture_assignment(repo_a)
    _write_non_capture_assignment(repo_b)
    ops = repo_a / "scripts/ops"
    ops.mkdir(parents=True)
    fake_job = ops / "windows_kill_on_close_job.ps1"
    fake_job.write_text(
        "function New-WeatherKillOnCloseJob {\n"
        "  $job=[pscustomobject]@{}\n"
        "  $job | Add-Member ScriptMethod TerminateAndWait { "
        "param($Milliseconds) throw 'FAKE_JOB_TEARDOWN_FAILURE' }\n"
        "  $job | Add-Member ScriptMethod Dispose { }\n"
        "  $job\n"
        "}\n"
        "function ConvertTo-WeatherWindowsArgumentString { param($Tokens) 'unused' }\n"
        "function Start-WeatherInteractiveProcessInJob {\n"
        "  param($Job,$FilePath,$ArgumentString,$WorkingDirectory)\n"
        "  $child=[pscustomobject]@{ExitCode=0}\n"
        "  $child | Add-Member ScriptMethod WaitForExit { }\n"
        "  $child | Add-Member ScriptMethod Dispose { }\n"
        "  $child\n"
        "}\n",
        encoding="utf-8",
    )
    wrapper = _install_workstation_wrapper(repo_a)
    shared_poison = tmp_path / "host-global-heavy-workload.poison"
    admission = ops / "workload_admission.ps1"
    admission.write_text(
        admission.read_text(encoding="utf-8-sig")
        + "\nfunction Get-WeatherHeavyWorkloadPoisonPath { "
        + "param([switch]$CreateIfMissing) "
        + "$env:WEATHER_TEST_POISON_PATH }\n",
        encoding="utf-8",
    )
    arguments = base64.b64encode(
        json.dumps(["-m", "pytest", "tests/test_never_started.py", "-q"]).encode(
            "utf-8"
        )
    ).decode("ascii")
    env = {
        **os.environ,
        "WEATHER_TEST_POISON_PATH": str(shared_poison),
    }

    failed = subprocess.run(
        [
            *POWERSHELL,
            "-File",
            str(wrapper),
            "-Kind",
            "pytest",
            "-PythonPath",
            sys.executable,
            "-ArgumentsBase64",
            arguments,
            "-RepoRoot",
            str(repo_a),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert failed.returncode != 0
    assert "FAKE_JOB_TEARDOWN_FAILURE" in failed.stderr
    assert shared_poison.is_file()
    assert (
        json.loads(shared_poison.read_text(encoding="utf-8"))["state"]
        == "TEARDOWN_PENDING"
    )

    probe = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
function Get-WeatherHeavyWorkloadPoisonPath {
    param([switch]$CreateIfMissing)
    $env:WEATHER_TEST_POISON_PATH
}
try {
    Enter-WeatherHeavyWorkloadLease `
        -RepoRoot $env:WEATHER_LEASE_ROOT `
        -Workload 'WorkstationOffline-pytest-cross-root-probe' `
        -ExecutionHostProfile 'workstation_offline_v1' | Out-Null
    Write-Output 'ACCEPTED'
    exit 3
}
catch {
    if ($_.Exception.Message -notmatch
        'teardown is pending|poison state blocks admission') { throw }
    Write-Output 'BLOCKED_POISON'
}
"""
    probe_env = {
        **env,
        "WEATHER_LEASE_SCRIPT": str(LEASE_SCRIPT),
        "WEATHER_LEASE_ROOT": str(repo_b),
    }
    for _attempt in range(2):
        blocked = subprocess.run(
            [*POWERSHELL, "-Command", probe],
            capture_output=True,
            text=True,
            check=False,
            env=probe_env,
        )
        assert blocked.returncode == 0, blocked.stderr
        assert blocked.stdout.strip() == "BLOCKED_POISON"

    shared_poison.write_text("malformed", encoding="utf-8")
    malformed = subprocess.run(
        [*POWERSHELL, "-Command", probe],
        capture_output=True,
        text=True,
        check=False,
        env=probe_env,
    )
    assert malformed.returncode == 0, malformed.stderr
    assert malformed.stdout.strip() == "BLOCKED_POISON"
    shared_poison.unlink()
    cleanup = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
function Get-WeatherHeavyWorkloadPoisonPath {
    param([switch]$CreateIfMissing)
    $env:WEATHER_TEST_POISON_PATH
}
function Get-WeatherActiveWorkstationHeavyProcess { @() }
$lease = $null
try {
    $lease = Enter-WeatherHeavyWorkloadLease `
        -RepoRoot $env:WEATHER_LEASE_ROOT `
        -Workload 'WorkstationOffline-pytest-poison-cleanup' `
        -ExecutionHostProfile 'workstation_offline_v1'
}
catch {
    if ($_.Exception.Message -notmatch 'retry the exact attended operation') { throw }
    $lease = Enter-WeatherHeavyWorkloadLease `
        -RepoRoot $env:WEATHER_LEASE_ROOT `
        -Workload 'WorkstationOffline-pytest-poison-cleanup' `
        -ExecutionHostProfile 'workstation_offline_v1'
}
if ($null -eq $lease) { throw 'test cleanup could not acquire the mutex' }
Set-WeatherHeavyWorkloadLeaseTeardownPending -Lease $lease | Out-Null
Exit-WeatherHeavyWorkloadLease -Lease $lease
"""
    cleaned = subprocess.run(
        [*POWERSHELL, "-Command", cleanup],
        capture_output=True,
        text=True,
        check=False,
        env=probe_env,
    )
    assert cleaned.returncode == 0, cleaned.stderr


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows lease",
)
def test_capture_teardown_failure_retains_lease_without_workstation_marker() -> None:
    env = {**os.environ, "WEATHER_LEASE_SCRIPT": str(LEASE_SCRIPT)}
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
function Get-WeatherHeavyWorkloadPoisonPath {
    param([switch]$CreateIfMissing)
    throw 'capture path must not request workstation state'
}
$mutex = [Threading.Mutex]::new(
    $false,
    ('Global\WeatherProjectCapturePoisonTest-' + [guid]::NewGuid().ToString('N'))
)
$owned = $mutex.WaitOne(0, $false)
$lease = [pscustomobject]@{
    Workload = 'capture-test'
    ExecutionHostProfile = 'capture_colocated_v1'
    Mutex = $mutex
    MutexOwned = $owned
    Stream = $null
}
Set-WeatherHeavyWorkloadLeaseTeardownPending -Lease $lease | Out-Null
Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease
$exitRejected = $false
try { Exit-WeatherHeavyWorkloadLease -Lease $lease }
catch { $exitRejected = $_.Exception.Message -match 'teardown-poisoned' }
$retained = $lease.TeardownPoisoned -and
    [object]::ReferenceEquals($script:WeatherHeavyWorkloadPoisonedLease, $lease)
$script:WeatherHeavyWorkloadPoisonedLease = $null
if ($owned) { $mutex.ReleaseMutex() }
$mutex.Dispose()
[pscustomobject]@{
    retained = $retained
    exit_rejected = $exitRejected
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        [*POWERSHELL, "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '{"retained":true,"exit_rejected":true}'


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows lease",
)
@pytest.mark.skipif(OUTER_WORKSTATION_LEASE, reason="outer workstation lease owns mutex")
def test_teardown_pending_recovery_requires_reboot_zero_scan_and_exact_reread(
    tmp_path: Path,
) -> None:
    env = {
        **os.environ,
        "WEATHER_LEASE_SCRIPT": str(LEASE_SCRIPT),
        "WEATHER_TEST_POISON_PATH": str(tmp_path / "host-global.poison"),
    }
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
function Get-WeatherHeavyWorkloadPoisonPath {
    param([switch]$CreateIfMissing)
    $env:WEATHER_TEST_POISON_PATH
}
$script:testBootId = 100
function Get-WeatherBootSessionId { [int]$script:testBootId }
function Start-Sleep { param($Milliseconds) }
$script:scanMode = 'zero'
$script:scanMutated = $false
function Get-WeatherActiveWorkstationHeavyProcess {
    if ($script:scanMode -ceq 'residual') {
        return [pscustomobject]@{ ProcessId = 77; Name = 'python.exe' }
    }
    if ($script:scanMode -ceq 'swap' -and -not $script:scanMutated) {
        $script:scanMutated = $true
        $marker = Get-WeatherHeavyWorkloadPoisonState `
            -Path $env:WEATHER_TEST_POISON_PATH
        $replacement = [ordered]@{
            schema_version = [string]$marker.schema_version
            state = [string]$marker.state
            workload = 'WorkstationOffline-pytest-swapped'
            execution_host_profile = [string]$marker.execution_host_profile
            pid = [int]$marker.pid
            owner_process_start_utc = [string]$marker.owner_process_start_utc
            boot_session_id = [int]$marker.boot_session_id
            state_changed_at_utc = (Get-Date).ToUniversalTime().ToString('o')
        }
        [IO.File]::WriteAllText(
            $env:WEATHER_TEST_POISON_PATH,
            ($replacement | ConvertTo-Json -Compress),
            [Text.UTF8Encoding]::new($false)
        )
    }
    return @()
}
function New-TestMarker([string]$State, [int]$BootId) {
    $script:testBootId = $BootId
    New-WeatherHeavyWorkloadPoisonMarker `
        -Path $env:WEATHER_TEST_POISON_PATH `
        -Workload 'WorkstationOffline-pytest-recovery' `
        -ExecutionHostProfile 'workstation_offline_v1' `
        -State $State
}
$confirmation = 'I_HAVE_VERIFIED_NO_RESIDUAL_WEATHER_WORKLOAD_PROCESSES'

New-TestMarker 'ACTIVE' 100
$script:testBootId = 101
$activeBlocked = $false
try { Clear-WeatherHeavyWorkloadPoison -Confirmation $confirmation }
catch { $activeBlocked = $_.Exception.Message -match 'only a TEARDOWN_PENDING' }
$activePreserved = Test-Path -LiteralPath $env:WEATHER_TEST_POISON_PATH
[IO.File]::Delete($env:WEATHER_TEST_POISON_PATH)

[IO.File]::WriteAllText(
    $env:WEATHER_TEST_POISON_PATH,
    'malformed',
    [Text.UTF8Encoding]::new($false)
)
$malformedBlocked = $false
try { Clear-WeatherHeavyWorkloadPoison -Confirmation $confirmation }
catch { $malformedBlocked = $_.Exception.Message -match 'cannot be recovered' }
[IO.File]::Delete($env:WEATHER_TEST_POISON_PATH)

New-TestMarker 'TEARDOWN_PENDING' 200
$sameBootBlocked = $false
try { Clear-WeatherHeavyWorkloadPoison -Confirmation $confirmation }
catch { $sameBootBlocked = $_.Exception.Message -match 'different Windows boot session' }
[IO.File]::Delete($env:WEATHER_TEST_POISON_PATH)

New-TestMarker 'TEARDOWN_PENDING' 300
$script:testBootId = 301
$script:scanMode = 'residual'
$residualBlocked = $false
try { Clear-WeatherHeavyWorkloadPoison -Confirmation $confirmation }
catch { $residualBlocked = $_.Exception.Message -match 'residual heavy processes remain' }
$residualPreserved = Test-Path -LiteralPath $env:WEATHER_TEST_POISON_PATH
[IO.File]::Delete($env:WEATHER_TEST_POISON_PATH)

New-TestMarker 'TEARDOWN_PENDING' 400
$script:testBootId = 401
$script:scanMode = 'swap'
$script:scanMutated = $false
$swapBlocked = $false
try { Clear-WeatherHeavyWorkloadPoison -Confirmation $confirmation }
catch { $swapBlocked = $_.Exception.Message -match 'changed during residual scan' }
$swapPreserved = Test-Path -LiteralPath $env:WEATHER_TEST_POISON_PATH
[IO.File]::Delete($env:WEATHER_TEST_POISON_PATH)

New-TestMarker 'TEARDOWN_PENDING' 500
$script:testBootId = 501
$script:scanMode = 'zero'
Clear-WeatherHeavyWorkloadPoison -Confirmation $confirmation
$cleared = -not (Test-Path -LiteralPath $env:WEATHER_TEST_POISON_PATH)
[pscustomobject]@{
    active_blocked = $activeBlocked
    active_preserved = $activePreserved
    malformed_blocked = $malformedBlocked
    same_boot_blocked = $sameBootBlocked
    residual_blocked = $residualBlocked
    residual_preserved = $residualPreserved
    swap_blocked = $swapBlocked
    swap_preserved = $swapPreserved
    different_boot_cleared = $cleared
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        [*POWERSHELL, "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        '{"active_blocked":true,"active_preserved":true,'
        '"malformed_blocked":true,"same_boot_blocked":true,'
        '"residual_blocked":true,"residual_preserved":true,'
        '"swap_blocked":true,"swap_preserved":true,'
        '"different_boot_cleared":true}'
    )


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows wrapper",
)
@pytest.mark.skipif(OUTER_WORKSTATION_LEASE, reason="outer workstation lease owns mutex")
def test_forced_wrapper_exit_kills_child_tree_before_mutex_reuse(
    tmp_path: Path,
) -> None:
    _write_non_capture_assignment(tmp_path)
    survived = tmp_path / "forced-child-survived.txt"
    hold_test = tmp_path / "test_forced_wrapper.py"
    hold_test.write_text(
        "import time\n"
        "from pathlib import Path\n\n"
        "def test_hold():\n"
        "    print('FORCED_WRAPPER_CHILD_READY', flush=True)\n"
        "    time.sleep(30)\n"
        f"    Path({str(survived)!r}).write_text('survived')\n",
        encoding="utf-8",
    )
    wrapper = subprocess.Popen(
        _workstation_wrapper_argv(
            tmp_path,
            ["-m", "pytest", str(hold_test), "-q", "-s"],
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert wrapper.stdout is not None
    while True:
        line = wrapper.stdout.readline()
        assert line, "contained pytest exited before its readiness marker"
        if "FORCED_WRAPPER_CHILD_READY" in line:
            break
    wrapper.terminate()
    wrapper.wait(timeout=10)

    env = os.environ.copy()
    env["WEATHER_LEASE_SCRIPT"] = str(LEASE_SCRIPT)
    env["WEATHER_LEASE_ROOT"] = str(tmp_path)
    env["WEATHER_TEST_POISON_PATH"] = str(tmp_path / ".test-heavy-workload.poison")
    recovery_probe = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
function Get-WeatherHeavyWorkloadPoisonPath {
    param([switch]$CreateIfMissing)
    $env:WEATHER_TEST_POISON_PATH
}
function Get-WeatherActiveWorkstationHeavyProcess { @() }
$recoveredActive = $false
try {
    Enter-WeatherHeavyWorkloadLease `
        -RepoRoot $env:WEATHER_LEASE_ROOT `
        -Workload 'WorkstationOffline-pytest-recovery-probe' `
        -ExecutionHostProfile 'workstation_offline_v1' | Out-Null
}
catch {
    if ($_.Exception.Message -notmatch
        'stale ACTIVE workload marker was recovered') { throw }
    $recoveredActive = $true
}
if (-not $recoveredActive) {
    throw 'stale ACTIVE marker did not force one attended retry'
}
$lease = Enter-WeatherHeavyWorkloadLease `
    -RepoRoot $env:WEATHER_LEASE_ROOT `
    -Workload 'WorkstationOffline-pytest-recovery-probe' `
    -ExecutionHostProfile 'workstation_offline_v1'
if ($null -eq $lease) { throw 'mutex did not recover after Job teardown' }
Set-WeatherHeavyWorkloadLeaseTeardownPending -Lease $lease | Out-Null
Exit-WeatherHeavyWorkloadLease -Lease $lease
Write-Output 'RECOVERED'
"""
    recovered = subprocess.run(
        [*POWERSHELL, "-Command", recovery_probe],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert recovered.returncode == 0, recovered.stderr
    assert recovered.stdout.strip() == "RECOVERED"
    time.sleep(2.25)
    assert not survived.exists()


@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="Windows lease")
def test_policy_rejects_daytime_work_but_admits_explicit_stage_a() -> None:
    env = os.environ.copy()
    env["WEATHER_LEASE_SCRIPT"] = str(LEASE_SCRIPT)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
$denied = Get-WeatherHeavyWorkloadPolicyWindow -Now '2026-08-14T10:00:00'
$stageA = Get-WeatherHeavyWorkloadPolicyWindow -Now '2026-08-14T10:00:00' `
    -AllowStageAWindow
[pscustomobject]@{ denied = $null -eq $denied; stage_a = $stageA } |
    ConvertTo-Json -Compress
"""
    result = subprocess.run(
        [*POWERSHELL, "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '{"denied":true,"stage_a":"stage_a"}'


@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="Windows lease")
def test_policy_accepts_only_the_exact_dated_owner_merge_exception() -> None:
    env = os.environ.copy()
    env["WEATHER_LEASE_SCRIPT"] = str(LEASE_SCRIPT)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
$accepted = Get-WeatherHeavyWorkloadPolicyWindow `
    -Now '2026-08-23T19:00:00' `
    -OwnerApprovedException 'OWNER_APPROVED_PROTECTED_WINDOW_MERGE_20260823'
$expired = $false
try {
    Get-WeatherHeavyWorkloadPolicyWindow `
        -Now '2026-08-24T00:31:00' `
        -OwnerApprovedException 'OWNER_APPROVED_PROTECTED_WINDOW_MERGE_20260823'
}
catch { $expired = $true }
[pscustomobject]@{ accepted = $accepted; expired = $expired } |
    ConvertTo-Json -Compress
"""
    result = subprocess.run(
        [*POWERSHELL, "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        '{"accepted":"owner_approved_merge_20260823","expired":true}'
    )
