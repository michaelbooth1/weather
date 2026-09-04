from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "ops" / "production_baseline_scheduler_rpc.ps1"
QUIET_MERGE = REPO_ROOT / "scripts" / "ops" / "quiet_window_merge.ps1"
POWERSHELL = shutil.which("powershell.exe")
WINDOWS_POWERSHELL = pytest.mark.skipif(
    os.name != "nt" or POWERSHELL is None,
    reason="the fixed-scope helper requires Windows PowerShell",
)
TEST_TASK_XML = "<Task>fixed-scope-scheduler-rpc-test</Task>"
TEST_TASK_XML_SHA256 = hashlib.sha256(TEST_TASK_XML.encode()).hexdigest()
INPUT_OBJECT_TASK_XML = "<Task>same-task-input-object-serialization</Task>"
REQUEST_SCHEMA = "production_baseline_scheduler_rpc_request_v0.1"
RESULT_SCHEMA = "production_baseline_scheduler_rpc_result_v0.1"
MUTATION_CLAIM_SCHEMA = "production_baseline_scheduler_rpc_mutation_claim_v0.1"


def _canonical_deadline(*, minutes: int = 5) -> str:
    value = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond:06d}0Z"


def _encode_json(value: dict[str, object]) -> str:
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
    return base64.b64encode(raw).decode("ascii")


def _base_request(operation: str, repo_root: Path, request_id: str) -> dict[str, object]:
    request: dict[str, object] = {
        "schema": REQUEST_SCHEMA,
        "request_id": request_id,
        "operation": operation,
        "deadline_utc": _canonical_deadline(),
        "repo_root": str(repo_root.resolve()),
    }
    if operation != "ReadExecutionTapeTask":
        request["task_xml_sha256"] = TEST_TASK_XML_SHA256
    return request


def _write_marker(
    root: Path,
    request: dict[str, object],
    *,
    stop_ordinal: int | None = None,
) -> tuple[Path, str]:
    marker: dict[str, object] = {
        "schema": "quiet_window_merge_in_progress_v0.1",
        "operation_mode": "production_baseline_reconciliation_v0.1",
        "phase": "documented_unpublished",
        "repo_root": str(root.resolve()),
        "merge_commit": "a" * 40,
        "push_invocation_attempted": True,
        "publication_acknowledged": False,
    }
    if request["operation"] == "StartPush":
        marker["push_start_rpc_request_id"] = request["request_id"]
        marker["push_start_rpc_deadline_utc"] = request["deadline_utc"]
    else:
        assert stop_ordinal is not None
        marker.update(
            {
                "push_stop_attempted": True,
                "push_stop_count": stop_ordinal,
                "push_stop_rpc_request_id": request["request_id"],
                "push_stop_rpc_deadline_utc": request["deadline_utc"],
            }
        )
    path = root / "data" / "alerts" / "quiet_window_merge_in_progress.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(marker, separators=(",", ":")).encode()
    path.write_bytes(encoded)
    return path, hashlib.sha256(encoded).hexdigest()


def _complete_mutation_request(
    request: dict[str, object], repo_root: Path, *, stop_ordinal: int | None = None
) -> None:
    marker_path, marker_sha = _write_marker(
        repo_root, request, stop_ordinal=stop_ordinal
    )
    request["marker_path"] = str(marker_path.resolve())
    request["marker_sha256"] = marker_sha
    if stop_ordinal is not None:
        request["stop_ordinal"] = stop_ordinal


def _claim_path(
    repo_root: Path, operation: str, *, stop_ordinal: int | None = None
) -> Path:
    if operation == "StartPush":
        leaf = "production_baseline_scheduler_rpc_start_authority.claim.json"
    else:
        assert operation == "StopPush"
        assert stop_ordinal in {1, 2}
        leaf = (
            "production_baseline_scheduler_rpc_"
            f"stop_{stop_ordinal}_authority.claim.json"
        )
    return repo_root / "data" / "alerts" / leaf


@pytest.fixture
def mocked_helper(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = HELPER.read_text(encoding="utf-8-sig")
    assert source.count(
        "8dc106989f176abfd1a21be0951cdfa325ffb5d5400e20e39c6978a10785dd05"
    ) == 1
    source = source.replace(
        "8dc106989f176abfd1a21be0951cdfa325ffb5d5400e20e39c6978a10785dd05",
        TEST_TASK_XML_SHA256,
    )
    expected_sid = (
        '$script:ExpectedPushSid = '
        '"S-1-5-21-1525964525-1566663060-3901869365-1001"'
    )
    assert expected_sid in source
    source = source.replace(
        expected_sid,
        "$script:ExpectedPushSid = "
        "[Security.Principal.WindowsIdentity]::GetCurrent().User.Value",
    )
    expected_user = '$script:ExpectedPushUserId = "micha"'
    assert expected_user in source
    source = source.replace(
        expected_user,
        "$script:ExpectedPushUserId = [string]$env:RPC_TEST_EXPECTED_USER",
    )
    claim_flush = (
        "        $stream.Flush($true)\n"
        "    }\n"
        "    catch {\n"
        "        # A collision means"
    )
    assert source.count(claim_flush) == 1
    source = source.replace(
        claim_flush,
        "        $stream.Flush($true)\n"
        "        if ($env:RPC_TEST_EXPIRE_AFTER_CLAIM -eq '1') {\n"
        "            $ValidatedRequest.deadline = "
        "[datetimeoffset]::UtcNow.AddSeconds(-1)\n"
        "        }\n"
        "    }\n"
        "    catch {\n"
        "        # A collision means",
    )
    adapted = tmp_path / "production_baseline_scheduler_rpc.test.ps1"
    adapted.write_text(source, encoding="utf-8", newline="")

    mutation_log = tmp_path / "mutation.log"
    wrapper = tmp_path / "invoke_mocked_scheduler_rpc.ps1"
    wrapper.write_text(
        r'''[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Helper,
    [Parameter(Mandatory = $true)][string]$Operation,
    [Parameter(Mandatory = $true)][string]$RequestBase64,
    [Parameter(Mandatory = $true)][string]$ResultPath
)
$ErrorActionPreference = "Stop"
$global:RpcTestPushTaskReadCount = 0
$global:RpcTestPushTaskExportCount = 0

function Assert-NoInjectedThrow {
    param([string]$Name)
    if ([string]$env:RPC_TEST_THROW -ceq $Name) {
        throw "injected $Name failure"
    }
}

function New-FakePushTask {
    param([int]$ReadOrdinal)

    $repo = [IO.Path]::GetFullPath($env:RPC_TEST_REPO_ROOT).TrimEnd('\')
    $action = [PSCustomObject]@{
        Execute = "cmd.exe"
        Arguments = "/c git -C $repo push origin master > C:\Users\micha\ops\logs\push-oneshot.log 2>&1"
        WorkingDirectory = $repo
    }
    $task = [PSCustomObject]@{
        TaskName = "WeatherOneShotPush"
        TaskPath = "\"
        State = [string]$env:RPC_TEST_PUSH_STATE
        Settings = [PSCustomObject]@{
            Enabled = $true
            MultipleInstances = "IgnoreNew"
            ExecutionTimeLimit = "PT15M"
            StartWhenAvailable = $false
        }
        Principal = [PSCustomObject]@{
            UserId = [string]$env:RPC_TEST_EXPECTED_USER
            LogonType = "Interactive"
            RunLevel = "Limited"
        }
        Actions = @($action)
        Triggers = if ($env:RPC_TEST_NULL_TRIGGERS -eq "1") { $null } else { @() }
        FixtureReadOrdinal = $ReadOrdinal
    }
    switch ([string]$env:RPC_TEST_TASK_VARIATION) {
        "action" { $task.Actions[0].Execute = "powershell.exe" }
        "principal" { $task.Principal.LogonType = "S4U" }
        "state" { $task.State = "Disabled" }
        "timing" { $task.Settings.ExecutionTimeLimit = "PT30M" }
        "working_directory" { $task.Actions[0].WorkingDirectory = "$repo\other" }
        "task_path" { $task.TaskPath = "\Other\" }
        "trigger" { $task.Triggers = @([PSCustomObject]@{ Kind = "Time" }) }
    }
    return $task
}

function Get-ScheduledTask {
    param([string]$TaskName, [string]$TaskPath, $ErrorAction)
    Assert-NoInjectedThrow -Name "Get"
    if ($TaskPath -cne "\") { throw "unexpected task path" }
    if ($TaskName -ceq "WeatherExecutionTapeSupervisor") {
        return [PSCustomObject]@{
            TaskName = $TaskName
            TaskPath = "\"
            State = "Disabled"
        }
    }
    if ($TaskName -cne "WeatherOneShotPush") { throw "unexpected task name" }
    $global:RpcTestPushTaskReadCount++
    $task = New-FakePushTask -ReadOrdinal $global:RpcTestPushTaskReadCount
    if ($env:RPC_TEST_TASK_VARIATION -eq "singleton") { return @($task, $task) }
    return $task
}

function Export-ScheduledTask {
    param($InputObject, [string]$TaskName, [string]$TaskPath, $ErrorAction)
    Assert-NoInjectedThrow -Name "Export"
    $global:RpcTestPushTaskExportCount++
    if ($null -ne $InputObject) {
        if ([string]$InputObject.TaskName -cne "WeatherOneShotPush") {
            throw "Export did not receive the exact task object"
        }
        if ($env:RPC_TEST_CHANGE_ON_FINAL -eq "1" -and
            [int]$InputObject.FixtureReadOrdinal -ge 2) {
            return "<Task>changed-between-scheduler-reads</Task>"
        }
        return [string]$env:RPC_TEST_INPUT_OBJECT_TASK_XML
    }
    if ($TaskName -cne "WeatherOneShotPush" -or $TaskPath -cne "\") {
        throw "Export did not receive the canonical task name/path"
    }
    if ($env:RPC_TEST_CHANGE_ON_FINAL -eq "1" -and
        $global:RpcTestPushTaskExportCount -ge 3) {
        return "<Task>changed-between-scheduler-reads</Task>"
    }
    return [string]$env:RPC_TEST_NAME_PATH_TASK_XML
}

function Get-ScheduledTaskInfo {
    param($InputObject, $ErrorAction)
    Assert-NoInjectedThrow -Name "Info"
    if ([string]$InputObject.TaskName -cne "WeatherOneShotPush") {
        throw "Info did not receive the exact task object"
    }
    return [PSCustomObject]@{
        LastRunTime = [datetime]"2026-09-01T01:00:00"
        LastTaskResult = [long]0
    }
}

function Start-ScheduledTask {
    param($InputObject, $ErrorAction)
    Assert-NoInjectedThrow -Name "Start"
    [IO.File]::AppendAllText(
        $env:RPC_TEST_MUTATION_LOG,
        ("Start|{0}|{1}" -f $InputObject.TaskName, $InputObject.TaskPath) +
            [Environment]::NewLine
    )
    Assert-NoInjectedThrow -Name "StartAfterDispatch"
}

function Stop-ScheduledTask {
    param($InputObject, $ErrorAction)
    Assert-NoInjectedThrow -Name "Stop"
    [IO.File]::AppendAllText(
        $env:RPC_TEST_MUTATION_LOG,
        ("Stop|{0}|{1}" -f $InputObject.TaskName, $InputObject.TaskPath) +
            [Environment]::NewLine
    )
    Assert-NoInjectedThrow -Name "StopAfterDispatch"
}

& $Helper -Operation $Operation -RequestBase64 $RequestBase64 -ResultPath $ResultPath
exit $LASTEXITCODE
''',
        encoding="utf-8",
    )
    return adapted, wrapper, mutation_log


def _invoke(
    mocked_helper: tuple[Path, Path, Path],
    repo_root: Path,
    operation: str,
    encoded_request: str,
    result_path: Path,
    *,
    throw: str = "",
    change_on_final: bool = False,
    expire_after_claim: bool = False,
    null_triggers: bool = False,
    task_variation: str = "",
    name_path_task_xml: str = TEST_TASK_XML,
    input_object_task_xml: str = TEST_TASK_XML,
) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL is not None
    adapted, wrapper, mutation_log = mocked_helper
    env = os.environ.copy()
    env.update(
        {
            "RPC_TEST_EXPECTED_USER": env.get("USERNAME", "test-user"),
            "RPC_TEST_REPO_ROOT": str(repo_root.resolve()),
            "RPC_TEST_PUSH_STATE": "Ready",
            "RPC_TEST_NAME_PATH_TASK_XML": name_path_task_xml,
            "RPC_TEST_INPUT_OBJECT_TASK_XML": input_object_task_xml,
            "RPC_TEST_MUTATION_LOG": str(mutation_log.resolve()),
            "RPC_TEST_THROW": throw,
            "RPC_TEST_CHANGE_ON_FINAL": "1" if change_on_final else "0",
            "RPC_TEST_EXPIRE_AFTER_CLAIM": "1" if expire_after_claim else "0",
            "RPC_TEST_NULL_TRIGGERS": "1" if null_triggers else "0",
            "RPC_TEST_TASK_VARIATION": task_variation,
        }
    )
    return subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(wrapper),
            "-Helper",
            str(adapted),
            "-Operation",
            operation,
            "-RequestBase64",
            encoded_request,
            "-ResultPath",
            str(result_path.resolve()),
        ],
        cwd=repo_root,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=20,
    )


def _read_result(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def test_divergent_serializations_reproduce_old_input_object_hash_rejection() -> None:
    reviewed_name_path_hash = hashlib.sha256(TEST_TASK_XML.encode()).hexdigest()
    old_child_input_object_hash = hashlib.sha256(
        INPUT_OBJECT_TASK_XML.encode()
    ).hexdigest()

    assert reviewed_name_path_hash == TEST_TASK_XML_SHA256
    assert old_child_input_object_hash != reviewed_name_path_hash


@WINDOWS_POWERSHELL
def test_name_path_export_is_the_canonical_reviewed_xml_when_serializations_differ(
    tmp_path: Path,
    mocked_helper: tuple[Path, Path, Path],
) -> None:
    request = _base_request("ReadPushSnapshot", tmp_path, "c" * 32)
    result_path = tmp_path / "divergent-export-shapes.json"

    completed = _invoke(
        mocked_helper,
        tmp_path,
        "ReadPushSnapshot",
        _encode_json(request),
        result_path,
        name_path_task_xml=TEST_TASK_XML,
        input_object_task_xml=INPUT_OBJECT_TASK_XML,
    )

    result = _read_result(result_path)
    assert completed.returncode == 0, json.dumps(result, sort_keys=True)
    assert base64.b64decode(result["task_xml_base64"]).decode() == TEST_TASK_XML
    assert result["task_xml_sha256"] == TEST_TASK_XML_SHA256


@WINDOWS_POWERSHELL
def test_null_triggers_property_is_counted_as_zero(
    tmp_path: Path,
    mocked_helper: tuple[Path, Path, Path],
) -> None:
    request = _base_request("ReadPushSnapshot", tmp_path, "d" * 32)
    result_path = tmp_path / "null-triggers.json"

    completed = _invoke(
        mocked_helper,
        tmp_path,
        "ReadPushSnapshot",
        _encode_json(request),
        result_path,
        null_triggers=True,
    )

    result = _read_result(result_path)
    assert completed.returncode == 0, json.dumps(result, sort_keys=True)
    assert result["trigger_count"] == 0


@WINDOWS_POWERSHELL
def test_windows_powershell_null_array_semantics_reproduce_old_trigger_defect() -> None:
    assert POWERSHELL is not None
    completed = subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$Task = [PSCustomObject]@{ Triggers = $null }; "
            '"$(@($Task.Triggers).Count)|'
            '$( @($Task.Triggers | Where-Object { $null -ne $_ }).Count)"',
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "1|0"


@WINDOWS_POWERSHELL
@pytest.mark.parametrize(
    "variation",
    (
        "action",
        "principal",
        "state",
        "timing",
        "working_directory",
        "task_path",
        "singleton",
    ),
)
def test_structured_task_identity_mismatches_still_fail_closed(
    tmp_path: Path,
    mocked_helper: tuple[Path, Path, Path],
    variation: str,
) -> None:
    request = _base_request("ReadPushSnapshot", tmp_path, "e" * 32)
    result_path = tmp_path / f"structured-mismatch-{variation}.json"

    completed = _invoke(
        mocked_helper,
        tmp_path,
        "ReadPushSnapshot",
        _encode_json(request),
        result_path,
        task_variation=variation,
    )

    assert completed.returncode == 2
    result = _read_result(result_path)
    assert result["ok"] is False
    assert result["mutation_authority_claimed"] is False
    assert result["mutation_dispatched"] is False
    assert not mocked_helper[2].exists()


@WINDOWS_POWERSHELL
def test_changed_name_path_xml_bytes_fail_closed_with_valid_structured_fields(
    tmp_path: Path,
    mocked_helper: tuple[Path, Path, Path],
) -> None:
    request = _base_request("ReadPushSnapshot", tmp_path, "f" * 32)
    result_path = tmp_path / "changed-canonical-xml.json"
    changed_xml = "<Task>changed-canonical-name-path-bytes</Task>"

    completed = _invoke(
        mocked_helper,
        tmp_path,
        "ReadPushSnapshot",
        _encode_json(request),
        result_path,
        name_path_task_xml=changed_xml,
        input_object_task_xml=changed_xml,
    )

    assert completed.returncode == 2
    result = _read_result(result_path)
    assert result["ok"] is False
    assert "task XML changed" in str(result["error_message"])
    assert result["mutation_authority_claimed"] is False
    assert result["mutation_dispatched"] is False


@WINDOWS_POWERSHELL
def test_one_actual_trigger_remains_a_hard_failure(
    tmp_path: Path,
    mocked_helper: tuple[Path, Path, Path],
) -> None:
    request = _base_request("ReadPushSnapshot", tmp_path, "0" * 32)
    result_path = tmp_path / "one-trigger.json"

    completed = _invoke(
        mocked_helper,
        tmp_path,
        "ReadPushSnapshot",
        _encode_json(request),
        result_path,
        task_variation="trigger",
    )

    assert completed.returncode == 2
    result = _read_result(result_path)
    assert result["ok"] is False
    assert result["mutation_authority_claimed"] is False
    assert result["mutation_dispatched"] is False


def test_helper_surface_is_fixed_and_contains_no_task_management_verbs() -> None:
    text = HELPER.read_text(encoding="utf-8-sig")
    for operation in (
        "ReadExecutionTapeTask",
        "ReadPushSnapshot",
        "StartPush",
        "StopPush",
    ):
        assert f'"{operation}"' in text
    for name in ("WeatherExecutionTapeSupervisor", "WeatherOneShotPush"):
        assert f'"{name}"' in text
    for forbidden in (
        "Register-ScheduledTask",
        "Set-ScheduledTask",
        "Enable-ScheduledTask",
        "Disable-ScheduledTask",
        "Unregister-ScheduledTask",
        "New-ScheduledTask",
        "Remove-ScheduledTask",
        "Invoke-Expression",
    ):
        assert forbidden not in text
    assert text.count("Start-ScheduledTask -InputObject $task") == 1
    assert text.count("Stop-ScheduledTask -InputObject $task") == 1
    assert "Start-ScheduledTask -TaskName" not in text
    assert "Stop-ScheduledTask -TaskName" not in text
    assert "[IO.FileMode]::CreateNew" in text
    assert "duplicate JSON property" in text


def test_repair_preserves_rpc_containment_evidence_and_one_push_budget() -> None:
    helper = HELPER.read_text(encoding="utf-8-sig")
    parent = QUIET_MERGE.read_text(encoding="utf-8-sig")

    assert '$script:RequestSchema = "production_baseline_scheduler_rpc_request_v0.1"' in helper
    assert '$script:ResultSchema = "production_baseline_scheduler_rpc_result_v0.1"' in helper
    assert "$stream.Flush($true)" in helper
    assert helper.count("[IO.FileMode]::CreateNew") == 2
    assert "request_sha256 = $ValidatedRequest.request_sha256" in helper
    assert "mutation_authority_claimed = $true" in helper
    assert "mutation_dispatched = $true" in helper

    assert "$reconciliationChildTerminationMilliseconds = 5000" in parent
    assert "$reconciliationChildBoundaryReserveSeconds = 8" in parent
    assert "$process.WaitForExit($waitMilliseconds)" in parent
    assert "$job.TerminateAndWait($cleanupWaitMilliseconds)" in parent
    assert "Scheduler RPC $Operation result is outside the fixed byte bound" in parent
    assert "$result | Add-Member -NotePropertyName request_sha256" in parent
    assert "$script:oneShotPushStartCount++" in parent
    assert "$oneShotPushStartCount -ne 0" in parent
    assert "$reconciliationPushStopAttemptLimit = 2" in parent
    assert 'Stage "publication_state_uncertain"' in parent


def test_mutation_claim_is_the_last_operation_before_scheduler_dispatch() -> None:
    text = HELPER.read_text(encoding="utf-8-sig")
    claim_function = text[
        text.index("function Write-MutationAuthorityClaim") : text.index(
            "function Get-ExactTask"
        )
    ]
    flush = claim_function.index("$stream.Flush($true)")
    dispose = claim_function.index("$stream.Dispose()", flush)
    deadline_recheck = claim_function.index(
        "Assert-DeadlineOpen -Deadline $ValidatedRequest.deadline", dispose
    )
    assert flush < dispose < deadline_recheck
    switch = text[text.index("$result = switch ($Operation)") :]
    start = switch[
        switch.index('"StartPush" {') : switch.index('"StopPush" {')
    ]
    stop = switch[
        switch.index('"StopPush" {') : switch.index(
            "\n    Assert-DeadlineOpen -Deadline $validated.deadline"
        )
    ]
    for block, operation, cmdlet in (
        (start, "StartPush", "Start-ScheduledTask -InputObject $task"),
        (stop, "StopPush", "Stop-ScheduledTask -InputObject $task"),
    ):
        claim = block.index("Write-MutationAuthorityClaim")
        dispatch = block.index(cmdlet, claim)
        between = block[claim:dispatch]
        assert f'-Mutation "{operation}"' in between
        for forbidden in (
            "Assert-MutationMarker",
            "Assert-DeadlineOpen",
            "Get-ScheduledTask",
            "Get-FullyValidatedPushTask",
            "Export-ScheduledTask",
            "Get-ScheduledTaskInfo",
        ):
            assert forbidden not in between


@WINDOWS_POWERSHELL
@pytest.mark.parametrize(
    ("operation", "stop_ordinal"),
    (("StartPush", None), ("StopPush", 1)),
)
def test_deadline_crossed_by_durable_claim_is_spent_without_dispatch(
    tmp_path: Path,
    mocked_helper: tuple[Path, Path, Path],
    operation: str,
    stop_ordinal: int | None,
) -> None:
    request = _base_request(operation, tmp_path, "b" * 32)
    _complete_mutation_request(request, tmp_path, stop_ordinal=stop_ordinal)
    encoded = _encode_json(request)

    first_path = tmp_path / f"expired-after-claim-{operation}.json"
    first = _invoke(
        mocked_helper,
        tmp_path,
        operation,
        encoded,
        first_path,
        expire_after_claim=True,
    )

    assert first.returncode == 2
    first_result = _read_result(first_path)
    assert first_result["ok"] is False
    assert first_result["mutation_authority_claimed"] is True
    assert first_result["mutation_dispatched"] is None
    assert "deadline" in str(first_result["error_message"]).lower()
    assert _claim_path(
        tmp_path, operation, stop_ordinal=stop_ordinal
    ).is_file()
    assert not mocked_helper[2].exists()

    replay_path = tmp_path / f"expired-after-claim-replay-{operation}.json"
    replay = _invoke(
        mocked_helper,
        tmp_path,
        operation,
        encoded,
        replay_path,
    )
    assert replay.returncode == 2
    replay_result = _read_result(replay_path)
    assert replay_result["mutation_authority_claimed"] is True
    assert replay_result["mutation_dispatched"] is None
    assert not mocked_helper[2].exists()


@WINDOWS_POWERSHELL
@pytest.mark.parametrize(
    "operation", ("ReadExecutionTapeTask", "ReadPushSnapshot")
)
def test_read_operations_return_bounded_structured_evidence(
    tmp_path: Path,
    mocked_helper: tuple[Path, Path, Path],
    operation: str,
) -> None:
    request = _base_request(operation, tmp_path, "1" * 32)
    result_path = tmp_path / f"{operation}.json"

    completed = _invoke(
        mocked_helper, tmp_path, operation, _encode_json(request), result_path
    )

    assert completed.returncode == 0, completed.stderr
    result = _read_result(result_path)
    assert result["schema"] == RESULT_SCHEMA
    assert result["request_id"] == request["request_id"]
    assert result["operation"] == operation
    assert result["ok"] is True
    assert result["match_count"] == 1
    assert result["task_path"] == "\\"
    if operation == "ReadPushSnapshot":
        assert base64.b64decode(result["task_xml_base64"]).decode() == TEST_TASK_XML
        assert result["task_xml_sha256"] == TEST_TASK_XML_SHA256
        assert result["last_task_result"] == 0
    assert not mocked_helper[2].exists()


@WINDOWS_POWERSHELL
@pytest.mark.parametrize(
    ("operation", "expected_log", "stop_ordinal"),
    (("StartPush", "Start|WeatherOneShotPush|\\", None),
     ("StopPush", "Stop|WeatherOneShotPush|\\", 1)),
)
def test_mutations_use_the_exact_validated_input_object_once(
    tmp_path: Path,
    mocked_helper: tuple[Path, Path, Path],
    operation: str,
    expected_log: str,
    stop_ordinal: int | None,
) -> None:
    request = _base_request(operation, tmp_path, "2" * 32)
    _complete_mutation_request(request, tmp_path, stop_ordinal=stop_ordinal)
    result_path = tmp_path / f"{operation}.json"
    encoded_request = _encode_json(request)

    completed = _invoke(
        mocked_helper, tmp_path, operation, encoded_request, result_path
    )

    assert completed.returncode == 0, completed.stderr
    result = _read_result(result_path)
    assert result["ok"] is True
    assert result["mutation_authority_claimed"] is True
    assert result["mutation_dispatched"] is True
    if stop_ordinal is not None:
        assert result["stop_ordinal"] == stop_ordinal
    assert mocked_helper[2].read_text(encoding="utf-8-sig").splitlines() == [
        expected_log
    ]
    claim = json.loads(
        _claim_path(
            tmp_path, operation, stop_ordinal=stop_ordinal
        ).read_text(encoding="utf-8-sig")
    )
    assert claim == {
        "schema": MUTATION_CLAIM_SCHEMA,
        "request_schema": REQUEST_SCHEMA,
        "request_id": request["request_id"],
        "request_sha256": hashlib.sha256(
            base64.b64decode(encoded_request)
        ).hexdigest(),
        "operation": operation,
        "marker_sha256": request["marker_sha256"],
        **({"stop_ordinal": stop_ordinal} if stop_ordinal is not None else {}),
    }


@WINDOWS_POWERSHELL
@pytest.mark.parametrize(
    ("operation", "fault", "stop_ordinal"),
    (
        ("ReadExecutionTapeTask", "Get", None),
        ("ReadPushSnapshot", "Export", None),
        ("ReadPushSnapshot", "Info", None),
        ("StartPush", "Start", None),
        ("StopPush", "Stop", 1),
    ),
)
def test_cmdlet_throws_return_structured_failure_without_retry(
    tmp_path: Path,
    mocked_helper: tuple[Path, Path, Path],
    operation: str,
    fault: str,
    stop_ordinal: int | None,
) -> None:
    request = _base_request(operation, tmp_path, "3" * 32)
    if operation in {"StartPush", "StopPush"}:
        _complete_mutation_request(request, tmp_path, stop_ordinal=stop_ordinal)
    result_path = tmp_path / f"throw-{operation}-{fault}.json"

    completed = _invoke(
        mocked_helper,
        tmp_path,
        operation,
        _encode_json(request),
        result_path,
        throw=fault,
    )

    assert completed.returncode == 2
    result = _read_result(result_path)
    assert result["schema"] == RESULT_SCHEMA
    assert result["ok"] is False
    claimed = operation in {"StartPush", "StopPush"}
    assert result["mutation_authority_claimed"] is claimed
    assert result["mutation_dispatched"] is (None if claimed else False)
    assert "injected" in result["error_message"]
    assert not mocked_helper[2].exists()
    if operation in {"StartPush", "StopPush"}:
        assert _claim_path(
            tmp_path, operation, stop_ordinal=stop_ordinal
        ).is_file()


@WINDOWS_POWERSHELL
def test_malformed_oversized_duplicate_unknown_and_mismatched_requests_fail_closed(
    tmp_path: Path,
    mocked_helper: tuple[Path, Path, Path],
) -> None:
    valid = _base_request("ReadExecutionTapeTask", tmp_path, "4" * 32)
    duplicate = (
        '{"schema":"production_baseline_scheduler_rpc_request_v0.1",'
        '"request_id":"44444444444444444444444444444444",'
        '"operation":"ReadExecutionTapeTask",'
        '"operation":"ReadPushSnapshot",'
        f'"deadline_utc":"{valid["deadline_utc"]}",'
        f'"repo_root":{json.dumps(valid["repo_root"])}' + "}"
    )
    unknown = dict(valid)
    unknown["arbitrary_task_name"] = "DoNotAllow"
    mismatch = dict(valid)
    mismatch["operation"] = "ReadPushSnapshot"
    cases = (
        "not-base64",
        base64.b64encode(("{" + '"x":"' + "a" * 20000 + '"}').encode()).decode(),
        base64.b64encode(duplicate.encode()).decode(),
        _encode_json(unknown),
        _encode_json(mismatch),
    )

    for index, encoded in enumerate(cases):
        result_path = tmp_path / f"invalid-{index}.json"
        completed = _invoke(
            mocked_helper,
            tmp_path,
            "ReadExecutionTapeTask",
            encoded,
            result_path,
        )
        assert completed.returncode == 2
        assert _read_result(result_path)["ok"] is False
    assert not mocked_helper[2].exists()


@WINDOWS_POWERSHELL
@pytest.mark.parametrize("variation", ("xml", "marker", "ordinal", "deadline"))
def test_mutation_request_bindings_fail_before_scheduler_mutation(
    tmp_path: Path,
    mocked_helper: tuple[Path, Path, Path],
    variation: str,
) -> None:
    operation = "StopPush" if variation == "ordinal" else "StartPush"
    request = _base_request(operation, tmp_path, "5" * 32)
    stop_ordinal = 1 if operation == "StopPush" else None
    _complete_mutation_request(request, tmp_path, stop_ordinal=stop_ordinal)
    if variation == "xml":
        request["task_xml_sha256"] = "0" * 64
    elif variation == "marker":
        request["marker_sha256"] = "0" * 64
    elif variation == "ordinal":
        request["stop_ordinal"] = 3
    else:
        request["deadline_utc"] = "2000-01-01T00:00:00.0000000Z"
    result_path = tmp_path / f"binding-{variation}.json"

    completed = _invoke(
        mocked_helper, tmp_path, operation, _encode_json(request), result_path
    )

    assert completed.returncode == 2
    assert _read_result(result_path)["ok"] is False
    assert not mocked_helper[2].exists()


@WINDOWS_POWERSHELL
@pytest.mark.parametrize(
    ("operation", "expected_log", "stop_ordinal"),
    (
        ("StartPush", "Start|WeatherOneShotPush|\\", None),
        ("StopPush", "Stop|WeatherOneShotPush|\\", 1),
        ("StopPush", "Stop|WeatherOneShotPush|\\", 2),
    ),
)
def test_fixed_mutation_claim_prevents_same_request_replay(
    tmp_path: Path,
    mocked_helper: tuple[Path, Path, Path],
    operation: str,
    expected_log: str,
    stop_ordinal: int | None,
) -> None:
    request = _base_request(operation, tmp_path, "7" * 32)
    _complete_mutation_request(request, tmp_path, stop_ordinal=stop_ordinal)
    encoded = _encode_json(request)

    first_path = tmp_path / f"first-{operation}.json"
    first = _invoke(mocked_helper, tmp_path, operation, encoded, first_path)
    assert first.returncode == 0, first.stderr
    assert _read_result(first_path)["mutation_dispatched"] is True

    replay_path = tmp_path / f"replay-{operation}.json"
    replay = _invoke(mocked_helper, tmp_path, operation, encoded, replay_path)
    assert replay.returncode == 2
    replay_result = _read_result(replay_path)
    assert replay_result["ok"] is False
    assert replay_result["mutation_authority_claimed"] is True
    assert replay_result["mutation_dispatched"] is None
    assert mocked_helper[2].read_text(encoding="utf-8-sig").splitlines() == [
        expected_log
    ]
    assert _claim_path(
        tmp_path, operation, stop_ordinal=stop_ordinal
    ).is_file()


@WINDOWS_POWERSHELL
@pytest.mark.parametrize(
    ("operation", "fault", "expected_log", "stop_ordinal"),
    (
        ("StartPush", "StartAfterDispatch", "Start|WeatherOneShotPush|\\", None),
        ("StopPush", "StopAfterDispatch", "Stop|WeatherOneShotPush|\\", 1),
    ),
)
def test_accepted_then_thrown_mutation_is_claimed_unknown_and_not_replayable(
    tmp_path: Path,
    mocked_helper: tuple[Path, Path, Path],
    operation: str,
    fault: str,
    expected_log: str,
    stop_ordinal: int | None,
) -> None:
    request = _base_request(operation, tmp_path, "a" * 32)
    _complete_mutation_request(request, tmp_path, stop_ordinal=stop_ordinal)
    encoded = _encode_json(request)

    first_path = tmp_path / f"accepted-then-thrown-{operation}.json"
    first = _invoke(
        mocked_helper,
        tmp_path,
        operation,
        encoded,
        first_path,
        throw=fault,
    )
    assert first.returncode == 2
    first_result = _read_result(first_path)
    assert first_result["ok"] is False
    assert first_result["mutation_authority_claimed"] is True
    assert first_result["mutation_dispatched"] is None
    assert mocked_helper[2].read_text(encoding="utf-8-sig").splitlines() == [
        expected_log
    ]

    replay_path = tmp_path / f"accepted-then-thrown-replay-{operation}.json"
    replay = _invoke(mocked_helper, tmp_path, operation, encoded, replay_path)
    assert replay.returncode == 2
    replay_result = _read_result(replay_path)
    assert replay_result["mutation_authority_claimed"] is True
    assert replay_result["mutation_dispatched"] is None
    assert mocked_helper[2].read_text(encoding="utf-8-sig").splitlines() == [
        expected_log
    ]


@WINDOWS_POWERSHELL
@pytest.mark.parametrize(
    ("operation", "stop_ordinal"),
    (("StartPush", None), ("StopPush", 1)),
)
def test_wrong_in_repo_marker_path_is_rejected_before_claim_or_mutation(
    tmp_path: Path,
    mocked_helper: tuple[Path, Path, Path],
    operation: str,
    stop_ordinal: int | None,
) -> None:
    request = _base_request(operation, tmp_path, "8" * 32)
    _complete_mutation_request(request, tmp_path, stop_ordinal=stop_ordinal)
    canonical_marker = Path(str(request["marker_path"]))
    alternate_marker = canonical_marker.with_name("alternate-marker.json")
    alternate_marker.write_bytes(canonical_marker.read_bytes())
    request["marker_path"] = str(alternate_marker.resolve())
    request["marker_sha256"] = hashlib.sha256(
        alternate_marker.read_bytes()
    ).hexdigest()
    result_path = tmp_path / f"wrong-marker-path-{operation}.json"

    completed = _invoke(
        mocked_helper, tmp_path, operation, _encode_json(request), result_path
    )

    assert completed.returncode == 2
    assert _read_result(result_path)["ok"] is False
    assert not mocked_helper[2].exists()
    assert not _claim_path(
        tmp_path, operation, stop_ordinal=stop_ordinal
    ).exists()


@WINDOWS_POWERSHELL
@pytest.mark.parametrize(
    ("operation", "stop_ordinal"),
    (("StartPush", None), ("StopPush", 1)),
)
def test_task_change_between_initial_and_final_read_fails_without_mutation(
    tmp_path: Path,
    mocked_helper: tuple[Path, Path, Path],
    operation: str,
    stop_ordinal: int | None,
) -> None:
    request = _base_request(operation, tmp_path, "9" * 32)
    _complete_mutation_request(request, tmp_path, stop_ordinal=stop_ordinal)
    result_path = tmp_path / f"changed-task-{operation}.json"

    completed = _invoke(
        mocked_helper,
        tmp_path,
        operation,
        _encode_json(request),
        result_path,
        change_on_final=True,
    )

    assert completed.returncode == 2
    result = _read_result(result_path)
    assert result["ok"] is False
    assert "task XML changed" in str(result["error_message"])
    assert not mocked_helper[2].exists()
    assert not _claim_path(
        tmp_path, operation, stop_ordinal=stop_ordinal
    ).exists()


@WINDOWS_POWERSHELL
def test_result_path_is_exclusive_and_prohibited_operation_is_not_callable(
    tmp_path: Path,
    mocked_helper: tuple[Path, Path, Path],
) -> None:
    request = _base_request("ReadExecutionTapeTask", tmp_path, "6" * 32)
    existing = tmp_path / "existing.json"
    existing.write_text("preserve", encoding="utf-8")

    collision = _invoke(
        mocked_helper,
        tmp_path,
        "ReadExecutionTapeTask",
        _encode_json(request),
        existing,
    )
    assert collision.returncode == 2
    assert existing.read_text(encoding="utf-8") == "preserve"

    prohibited_result = tmp_path / "prohibited.json"
    prohibited = _invoke(
        mocked_helper,
        tmp_path,
        "RegisterTask",
        _encode_json(request),
        prohibited_result,
    )
    assert prohibited.returncode != 0
    assert not prohibited_result.exists()
    assert not mocked_helper[2].exists()
