import base64
import inspect
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from weather.operations import producer_provenance as producer_provenance_module
from weather.operations.daily_refresh_locks import acquire_lock, release_lock
from weather.operations.long_job_guard import acquire_long_job_lock, release_long_job_lock
from weather.operations.producer_provenance import (
    STATUS_BOUND,
    _windows_argv,
    attest_scheduled_invocation,
    build_invocation_proof,
    build_lock_proof,
    build_stage_sla,
    verified_active_release_proof,
)
from weather.release_contract import (
    PRODUCTION_CANDIDATE_MODE,
    PRODUCTION_RELEASE_KIND,
)


NOW = datetime(2026, 7, 12, 6, 30, tzinfo=timezone.utc)


def test_query_windows_task_enumerates_hidden_instances():
    """The daily-refresh tasks are registered Hidden=True; GetInstances(0)
    excludes hidden instances, so the running-instance enumeration must pass the
    TASK_ENUM_HIDDEN flag. Guards against silently reverting to GetInstances(0),
    which returns zero instances at live-fire and fails scheduler attestation."""

    source = inspect.getsource(producer_provenance_module.query_windows_task)
    assert "$registeredTask.GetInstances(1)" in source
    assert "$registeredTask.GetInstances(0)" not in source


def encoded_arguments(arguments):
    payload = json.dumps(arguments, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(payload).decode("ascii")


def daily_delegated_contract_tokens(
    *,
    workdir,
    stage,
    task_name,
    scheduler_executable,
    process_executable,
):
    env = os.environ.copy()
    env.update({
        "WEATHER_DAILY_CONTRACT": str(
            Path(workdir) / "scripts" / "ops" / "daily_refresh_contract.ps1"
        ),
        "WEATHER_DAILY_REPO_ROOT": str(workdir),
        "WEATHER_DAILY_WRAPPER": str(
            Path(workdir) / "scripts" / "ops" / "daily_refresh.ps1"
        ),
        "WEATHER_DAILY_STAGE": str(stage),
        "WEATHER_DAILY_TASK_NAME": str(task_name),
        "WEATHER_DAILY_SCHEDULER_EXE": str(scheduler_executable),
        "WEATHER_DAILY_PROCESS_EXE": str(process_executable),
    })
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_DAILY_CONTRACT
$action = @(Get-DailyRefreshTaskActionTokens `
    -RepoRoot $env:WEATHER_DAILY_REPO_ROOT `
    -ScriptPath $env:WEATHER_DAILY_WRAPPER `
    -Stage $env:WEATHER_DAILY_STAGE `
    -SchedulerTaskName $env:WEATHER_DAILY_TASK_NAME `
    -EvidenceTaskName WeatherEveningEvidenceRefresh `
    -SchedulerTaskExecutable $env:WEATHER_DAILY_SCHEDULER_EXE `
    -ContinueOnError `
    -ProvenanceOnly)
$actionB64 = ConvertTo-SchedulerArgumentContract -Tokens $action
$child = @(Get-DailyRefreshChildTokens `
    -RepoRoot $env:WEATHER_DAILY_REPO_ROOT `
    -Stage $env:WEATHER_DAILY_STAGE `
    -SchedulerTaskName $env:WEATHER_DAILY_TASK_NAME `
    -EvidenceTaskName WeatherEveningEvidenceRefresh `
    -SchedulerTaskExecutable $env:WEATHER_DAILY_SCHEDULER_EXE `
    -SchedulerTaskActionArgumentsB64 $actionB64 `
    -SchedulerProcessExecutable $env:WEATHER_DAILY_PROCESS_EXE `
    -ContinueOnError `
    -ProvenanceOnly)
[pscustomobject]@{
    action_tokens = $action
    action_contract = $actionB64
    child_tokens = $child
} | ConvertTo-Json -Depth 5 -Compress
"""
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_windows_task_arguments_use_native_command_line_parsing():
    if os.name != "nt":
        return
    assert _windows_argv(
        r'-m weather.operations.daily_refresh run --repo-root "C:\Program Files\weather"'
    ) == [
        "-m",
        "weather.operations.daily_refresh",
        "run",
        "--repo-root",
        r"C:\Program Files\weather",
    ]


def task_payload(executable, arguments, working_directory, **overrides):
    payload = {
        "task_name": "WeatherProducer",
        "task_path": "\\",
        "state": "Running",
        "enabled": True,
        "actions": [{
            "execute": str(executable),
            "arguments": "registered arguments",
            "working_directory": str(working_directory),
        }],
        "last_run_time_utc": (NOW - timedelta(seconds=4)).isoformat(),
        "last_task_result": 0x00041301,
        "running_instances": [{
            "engine_process_id": 2121,
            "instance_guid": "{11111111-2222-3333-4444-555555555555}",
            "state": 4,
            "current_action": "producer",
        }],
        "definition_xml": "<Task><Actions /></Task>",
    }
    payload.update(overrides)
    return payload


def lineage_payload(
    process_executable,
    process_arguments,
    parent_executable,
    parent_arguments,
    *,
    process_id=4242,
    parent_process_id=2121,
    parent_started_at_utc=None,
):
    command_vectors = {
        "observed child command": [str(process_executable), *process_arguments],
        "observed parent command": [str(parent_executable), *parent_arguments],
    }
    payload = {
        "process": {
            "process_id": process_id,
            "parent_process_id": parent_process_id,
            "executable": str(process_executable),
            "command_line": "observed child command",
            "created_at_utc": NOW.isoformat(),
        },
        "ancestors": [{
            "process_id": parent_process_id,
            "parent_process_id": 1000,
            "executable": str(parent_executable),
            "command_line": "observed parent command",
            "created_at_utc": (
                parent_started_at_utc
                or (NOW - timedelta(seconds=4)).isoformat()
            ),
        }],
    }
    return payload, lambda command: list(command_vectors[command])


def test_windows_scheduler_attestation_requires_exact_running_contract(tmp_path):
    executable = tmp_path / "venv" / "Scripts" / "pythonw.exe"
    process_image = tmp_path / "Python311" / "pythonw.exe"
    workdir = tmp_path / "repo"
    expected_arguments = ["-m", "weather.operations.nightly_retrain", "run"]
    payload = task_payload(executable, expected_arguments, workdir)
    lineage, command_parser = lineage_payload(
        process_image,
        expected_arguments,
        executable,
        expected_arguments,
    )

    proof = attest_scheduled_invocation(
        task_name="WeatherProducer",
        expected_executable=executable,
        expected_arguments=expected_arguments,
        expected_working_directory=workdir,
        invocation_started_at_utc=NOW,
        process_executable=executable,
        process_working_directory=workdir,
        os_name="nt",
        task_query=lambda _name: payload,
        argument_parser=lambda _arguments: expected_arguments,
        process_query=lambda _process_id: lineage,
        process_argument_parser=command_parser,
        process_id=4242,
        process_image_executable=process_image,
    )

    assert proof["status"] == "PASS"
    assert proof["scheduler_attested"] is True
    assert proof["task_enabled"] is True
    assert proof["task_state"] == "Running"
    assert proof["contract"]["status"] == "PASS"
    assert len(proof["task_definition_sha256"]) == 64
    assert len(proof["contract"]["contract_sha256"]) == 64
    assert proof["task_run_correlation"]["status"] == "PASS"
    assert proof["task_run_correlation"]["process_start_delta_seconds"] == 4.0
    assert proof["invocation_topology"] == "direct"
    assert proof["contract"]["scheduler_action"]["arguments"] == expected_arguments
    assert proof["contract"]["producer_process"]["arguments"] == expected_arguments
    assert proof["process_lineage"]["status"] == "PASS"
    assert proof["process_lineage"]["venv_redirector_observed"] is True
    assert proof["process_lineage"]["scheduler_process_id"] == 2121


def test_direct_scheduler_attestation_blocks_manual_lookalike_pid(tmp_path):
    executable = tmp_path / "venv" / "Scripts" / "pythonw.exe"
    process_image = tmp_path / "Python311" / "pythonw.exe"
    workdir = tmp_path / "repo"
    arguments = ["-m", "weather.operations.nightly_retrain", "run"]
    payload = task_payload(
        executable,
        arguments,
        workdir,
        running_instances=[{
            "engine_process_id": 9999,
            "instance_guid": "{real-task-running-elsewhere}",
            "state": 4,
            "current_action": "producer",
        }],
    )
    lineage, command_parser = lineage_payload(
        process_image,
        arguments,
        executable,
        arguments,
    )

    proof = attest_scheduled_invocation(
        task_name="WeatherProducer",
        expected_executable=executable,
        expected_arguments=arguments,
        expected_working_directory=workdir,
        invocation_started_at_utc=NOW,
        process_executable=executable,
        process_working_directory=workdir,
        os_name="nt",
        task_query=lambda _name: payload,
        argument_parser=lambda _arguments: arguments,
        process_query=lambda _process_id: lineage,
        process_argument_parser=command_parser,
        process_id=4242,
        process_image_executable=process_image,
    )

    assert proof["status"] == "BLOCK"
    assert proof["process_lineage"]["status"] == "BLOCK"
    assert "scheduler_parent_engine_pid_mismatch" in {
        row["code"] for row in proof["blockers"]
    }


def test_delegated_scheduler_attestation_binds_wrapper_action_and_child(tmp_path):
    scheduler_executable = tmp_path / "WindowsPowerShell" / "powershell.exe"
    child_executable = tmp_path / "venv" / "Scripts" / "python.exe"
    workdir = tmp_path / "repo"
    scheduler_arguments = [
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(workdir / "scripts" / "ops" / "training_window.ps1"),
        "-RepoRoot",
        str(workdir),
        "-WindowTaskName",
        "WeatherTrainingWindow",
        "-SchedulerTaskExecutable",
        str(scheduler_executable),
    ]
    child_arguments = [
        "-m",
        "weather.operations.nightly_retrain",
        "run",
        "--scheduler-invocation-topology",
        "delegated_child",
    ]
    payload = task_payload(scheduler_executable, scheduler_arguments, workdir)
    lineage, command_parser = lineage_payload(
        child_executable,
        child_arguments,
        scheduler_executable,
        scheduler_arguments,
    )

    proof = attest_scheduled_invocation(
        task_name="WeatherProducer",
        expected_executable=scheduler_executable,
        expected_arguments=scheduler_arguments,
        expected_working_directory=workdir,
        invocation_started_at_utc=NOW,
        invocation_topology="delegated_child",
        expected_process_executable=child_executable,
        expected_process_arguments=child_arguments,
        process_executable=child_executable,
        process_working_directory=workdir,
        os_name="nt",
        task_query=lambda _name: payload,
        argument_parser=lambda _arguments: scheduler_arguments,
        process_query=lambda _process_id: lineage,
        process_argument_parser=command_parser,
        process_id=4242,
        process_image_executable=child_executable,
    )

    assert proof["status"] == "PASS"
    assert proof["scheduler_attested"] is True
    assert proof["invocation_topology"] == "delegated_child"
    assert proof["contract"]["scheduler_action"] == {
        "executable": os.path.normcase(str(scheduler_executable.resolve())),
        "arguments": scheduler_arguments,
        "working_directory": os.path.normcase(str(workdir.resolve())),
    }
    assert proof["contract"]["producer_process"]["executable"] == os.path.normcase(
        str(child_executable.resolve())
    )
    assert proof["contract"]["producer_process"]["arguments"] == child_arguments
    assert proof["process_lineage"]["status"] == "PASS"
    assert proof["process_lineage"]["scheduler_process_id"] == 2121
    assert proof["process_lineage"]["scheduler_arguments"] == scheduler_arguments


def test_delegated_scheduler_attestation_accepts_exact_venv_redirector_chain(tmp_path):
    scheduler_executable = tmp_path / "WindowsPowerShell" / "powershell.exe"
    logical_child_executable = tmp_path / "venv" / "Scripts" / "python.exe"
    process_image_executable = tmp_path / "Python311" / "python.exe"
    workdir = tmp_path / "repo"
    scheduler_arguments = ["-NoProfile", "-File", "training_window.ps1"]
    child_arguments = ["-m", "weather.operations.nightly_retrain", "run"]
    payload = task_payload(scheduler_executable, scheduler_arguments, workdir)
    lineage = {
        "process": {
            "process_id": 4242,
            "parent_process_id": 3131,
            "executable": str(process_image_executable),
            "command_line": "observed base interpreter command",
            "created_at_utc": NOW.isoformat(),
        },
        "ancestors": [
            {
                "process_id": 3131,
                "parent_process_id": 2121,
                "executable": str(logical_child_executable),
                "command_line": "observed venv redirector command",
                "created_at_utc": NOW.isoformat(),
            },
            {
                "process_id": 2121,
                "parent_process_id": 1000,
                "executable": str(scheduler_executable),
                "command_line": "observed scheduler command",
                "created_at_utc": (NOW - timedelta(seconds=4)).isoformat(),
            },
        ],
    }
    command_vectors = {
        "observed base interpreter command": [
            str(process_image_executable),
            *child_arguments,
        ],
        "observed venv redirector command": [
            str(logical_child_executable),
            *child_arguments,
        ],
        "observed scheduler command": [
            str(scheduler_executable),
            *scheduler_arguments,
        ],
    }

    proof = attest_scheduled_invocation(
        task_name="WeatherProducer",
        expected_executable=scheduler_executable,
        expected_arguments=scheduler_arguments,
        expected_working_directory=workdir,
        invocation_started_at_utc=NOW,
        invocation_topology="delegated_child",
        expected_process_executable=logical_child_executable,
        expected_process_arguments=child_arguments,
        process_executable=logical_child_executable,
        process_working_directory=workdir,
        os_name="nt",
        task_query=lambda _name: payload,
        argument_parser=lambda _arguments: scheduler_arguments,
        process_query=lambda _process_id: lineage,
        process_argument_parser=lambda command: list(command_vectors[command]),
        process_id=4242,
        process_image_executable=process_image_executable,
    )

    assert proof["status"] == "PASS"
    assert proof["process_lineage"]["status"] == "PASS"
    assert proof["process_lineage"]["venv_redirector_observed"] is True
    assert proof["process_lineage"]["scheduler_ancestor_depth"] == 2
    assert proof["process_lineage"]["scheduler_process_id"] == 2121


def test_delegated_scheduler_attestation_blocks_spoofed_venv_redirector(tmp_path):
    scheduler_executable = tmp_path / "WindowsPowerShell" / "powershell.exe"
    logical_child_executable = tmp_path / "venv" / "Scripts" / "python.exe"
    process_image_executable = tmp_path / "Python311" / "python.exe"
    workdir = tmp_path / "repo"
    scheduler_arguments = ["-NoProfile", "-File", "training_window.ps1"]
    child_arguments = ["-m", "weather.operations.nightly_retrain", "run"]
    payload = task_payload(scheduler_executable, scheduler_arguments, workdir)
    lineage = {
        "process": {
            "process_id": 4242,
            "parent_process_id": 3131,
            "executable": str(process_image_executable),
            "command_line": "observed base interpreter command",
            "created_at_utc": NOW.isoformat(),
        },
        "ancestors": [
            {
                "process_id": 3131,
                "parent_process_id": 2121,
                "executable": str(logical_child_executable),
                "command_line": "spoofed redirector command",
                "created_at_utc": NOW.isoformat(),
            },
            {
                "process_id": 2121,
                "parent_process_id": 1000,
                "executable": str(scheduler_executable),
                "command_line": "observed scheduler command",
                "created_at_utc": (NOW - timedelta(seconds=4)).isoformat(),
            },
        ],
    }
    command_vectors = {
        "observed base interpreter command": [
            str(process_image_executable),
            *child_arguments,
        ],
        "spoofed redirector command": [
            str(logical_child_executable),
            *child_arguments,
            "--manual-copy",
        ],
        "observed scheduler command": [
            str(scheduler_executable),
            *scheduler_arguments,
        ],
    }

    proof = attest_scheduled_invocation(
        task_name="WeatherProducer",
        expected_executable=scheduler_executable,
        expected_arguments=scheduler_arguments,
        expected_working_directory=workdir,
        invocation_started_at_utc=NOW,
        invocation_topology="delegated_child",
        expected_process_executable=logical_child_executable,
        expected_process_arguments=child_arguments,
        process_executable=logical_child_executable,
        process_working_directory=workdir,
        os_name="nt",
        task_query=lambda _name: payload,
        argument_parser=lambda _arguments: scheduler_arguments,
        process_query=lambda _process_id: lineage,
        process_argument_parser=lambda command: list(command_vectors[command]),
        process_id=4242,
        process_image_executable=process_image_executable,
    )

    assert proof["status"] == "BLOCK"
    assert proof["process_lineage"]["status"] == "BLOCK"
    assert "scheduler_process_launcher_mismatch" in {
        row["code"] for row in proof["blockers"]
    }


def test_delegated_scheduler_attestation_blocks_unrelated_manual_child(tmp_path):
    scheduler_executable = tmp_path / "WindowsPowerShell" / "powershell.exe"
    child_executable = tmp_path / "venv" / "Scripts" / "python.exe"
    unrelated_parent = tmp_path / "cmd.exe"
    workdir = tmp_path / "repo"
    scheduler_arguments = ["-NoProfile", "-File", "training_window.ps1"]
    child_arguments = ["-m", "weather.operations.nightly_retrain", "run"]
    payload = task_payload(scheduler_executable, scheduler_arguments, workdir)
    lineage, command_parser = lineage_payload(
        child_executable,
        child_arguments,
        unrelated_parent,
        ["/c", "manual-launch.cmd"],
    )

    proof = attest_scheduled_invocation(
        task_name="WeatherProducer",
        expected_executable=scheduler_executable,
        expected_arguments=scheduler_arguments,
        expected_working_directory=workdir,
        invocation_started_at_utc=NOW,
        invocation_topology="delegated_child",
        expected_process_executable=child_executable,
        expected_process_arguments=child_arguments,
        process_executable=child_executable,
        process_working_directory=workdir,
        os_name="nt",
        task_query=lambda _name: payload,
        argument_parser=lambda _arguments: scheduler_arguments,
        process_query=lambda _process_id: lineage,
        process_argument_parser=command_parser,
        process_id=4242,
        process_image_executable=child_executable,
    )

    assert proof["status"] == "BLOCK"
    assert proof["scheduler_attested"] is False
    assert proof["process_lineage"]["status"] == "BLOCK"
    assert {
        "scheduler_parent_executable_mismatch",
        "scheduler_parent_arguments_mismatch",
    }.issubset({row["code"] for row in proof["blockers"]})


def test_delegated_scheduler_attestation_blocks_cloned_wrapper_pid(tmp_path):
    scheduler_executable = tmp_path / "powershell.exe"
    child_executable = tmp_path / "python.exe"
    workdir = tmp_path / "repo"
    scheduler_arguments = ["-File", "training_window.ps1"]
    child_arguments = ["-m", "weather.operations.nightly_retrain", "run"]
    payload = task_payload(scheduler_executable, scheduler_arguments, workdir)
    lineage, command_parser = lineage_payload(
        child_executable,
        child_arguments,
        scheduler_executable,
        scheduler_arguments,
        parent_process_id=3131,
    )

    proof = attest_scheduled_invocation(
        task_name="WeatherProducer",
        expected_executable=scheduler_executable,
        expected_arguments=scheduler_arguments,
        expected_working_directory=workdir,
        invocation_started_at_utc=NOW,
        invocation_topology="delegated_child",
        expected_process_executable=child_executable,
        expected_process_arguments=child_arguments,
        process_executable=child_executable,
        process_working_directory=workdir,
        os_name="nt",
        task_query=lambda _name: payload,
        argument_parser=lambda _arguments: scheduler_arguments,
        process_query=lambda _process_id: lineage,
        process_argument_parser=command_parser,
        process_id=4242,
        process_image_executable=child_executable,
    )

    assert proof["status"] == "BLOCK"
    assert proof["process_lineage"]["status"] == "BLOCK"
    assert "scheduler_parent_engine_pid_mismatch" in {
        row["code"] for row in proof["blockers"]
    }


def test_delegated_scheduler_attestation_blocks_stale_parent_process(tmp_path):
    scheduler_executable = tmp_path / "powershell.exe"
    child_executable = tmp_path / "python.exe"
    workdir = tmp_path / "repo"
    scheduler_arguments = ["-File", "training_window.ps1"]
    child_arguments = ["-m", "weather.operations.nightly_retrain", "run"]
    payload = task_payload(scheduler_executable, scheduler_arguments, workdir)
    lineage, command_parser = lineage_payload(
        child_executable,
        child_arguments,
        scheduler_executable,
        scheduler_arguments,
        parent_started_at_utc=(NOW - timedelta(minutes=3)).isoformat(),
    )

    proof = attest_scheduled_invocation(
        task_name="WeatherProducer",
        expected_executable=scheduler_executable,
        expected_arguments=scheduler_arguments,
        expected_working_directory=workdir,
        invocation_started_at_utc=NOW,
        invocation_topology="delegated_child",
        expected_process_executable=child_executable,
        expected_process_arguments=child_arguments,
        process_executable=child_executable,
        process_working_directory=workdir,
        os_name="nt",
        task_query=lambda _name: payload,
        argument_parser=lambda _arguments: scheduler_arguments,
        process_query=lambda _process_id: lineage,
        process_argument_parser=command_parser,
        process_id=4242,
        process_image_executable=child_executable,
    )

    assert proof["status"] == "BLOCK"
    assert proof["process_lineage"]["status"] == "BLOCK"
    assert "scheduler_parent_run_correlation_stale" in {
        row["code"] for row in proof["blockers"]
    }


@pytest.mark.parametrize(
    ("spoof_case", "expected_code"),
    [
        ("child_argv", "scheduler_process_arguments_mismatch"),
        ("stale_child", "scheduler_process_start_correlation_stale"),
        ("missing_child_start", "scheduler_process_start_correlation_missing"),
        ("parent_started_after_child", "scheduler_child_parent_start_correlation_stale"),
        ("broken_pid_chain", "scheduler_process_lineage_pid_mismatch"),
        ("overdeep_chain", "scheduler_process_lineage_too_deep"),
        ("wrong_child_cwd", "running_working_directory_mismatch"),
    ],
)
def test_delegated_scheduler_attestation_blocks_os_lineage_spoofs(
    tmp_path,
    spoof_case,
    expected_code,
):
    scheduler_executable = tmp_path / "powershell.exe"
    child_executable = tmp_path / "python.exe"
    workdir = tmp_path / "repo"
    scheduler_arguments = ["-File", "training_window.ps1"]
    child_arguments = ["-m", "weather.operations.nightly_retrain", "run"]
    payload = task_payload(scheduler_executable, scheduler_arguments, workdir)
    lineage, _unused_parser = lineage_payload(
        child_executable,
        child_arguments,
        scheduler_executable,
        scheduler_arguments,
    )
    command_vectors = {
        "observed child command": [str(child_executable), *child_arguments],
        "observed parent command": [
            str(scheduler_executable),
            *scheduler_arguments,
        ],
    }
    process_workdir = workdir
    if spoof_case == "child_argv":
        command_vectors["observed child command"].append("--copied-claim")
    elif spoof_case == "stale_child":
        lineage["process"]["created_at_utc"] = (
            NOW - timedelta(minutes=5)
        ).isoformat()
    elif spoof_case == "missing_child_start":
        lineage["process"]["created_at_utc"] = None
    elif spoof_case == "parent_started_after_child":
        lineage["ancestors"][0]["created_at_utc"] = (
            NOW + timedelta(seconds=10)
        ).isoformat()
    elif spoof_case == "broken_pid_chain":
        lineage["process"]["parent_process_id"] = 9999
    elif spoof_case == "overdeep_chain":
        lineage["ancestors"].extend([
            {
                "process_id": 1000,
                "parent_process_id": 900,
                "executable": str(tmp_path / "taskeng.exe"),
                "command_line": "unused third ancestor command",
                "created_at_utc": (NOW - timedelta(seconds=5)).isoformat(),
            },
            {
                "process_id": 900,
                "parent_process_id": 800,
                "executable": str(tmp_path / "services.exe"),
                "command_line": "unused fourth ancestor command",
                "created_at_utc": (NOW - timedelta(seconds=6)).isoformat(),
            },
        ])
    elif spoof_case == "wrong_child_cwd":
        process_workdir = tmp_path / "unrelated-repo"

    proof = attest_scheduled_invocation(
        task_name="WeatherProducer",
        expected_executable=scheduler_executable,
        expected_arguments=scheduler_arguments,
        expected_working_directory=workdir,
        invocation_started_at_utc=NOW,
        invocation_topology="delegated_child",
        expected_process_executable=child_executable,
        expected_process_arguments=child_arguments,
        process_executable=child_executable,
        process_working_directory=process_workdir,
        os_name="nt",
        task_query=lambda _name: payload,
        argument_parser=lambda _arguments: scheduler_arguments,
        process_query=lambda _process_id: lineage,
        process_argument_parser=lambda command: list(command_vectors[command]),
        process_id=4242,
        process_image_executable=child_executable,
    )

    assert proof["status"] == "BLOCK"
    assert proof["scheduler_attested"] is False
    assert proof["process_lineage"]["status"] == "BLOCK"
    assert expected_code in {row["code"] for row in proof["blockers"]}


def test_build_invocation_proof_decodes_exact_delegated_action(tmp_path):
    scheduler_executable = tmp_path / "powershell.exe"
    workdir = Path.cwd()
    scheduler_arguments = [
        "-NoProfile",
        "-File",
        str(workdir / "scripts" / "ops" / "training_window.ps1"),
    ]
    running_arguments = [
        "run",
        "--scheduler-invocation-topology",
        "delegated_child",
    ]
    args = SimpleNamespace(
        scheduler_task_name="WeatherProducer",
        scheduler_task_executable=str(scheduler_executable),
        scheduler_task_working_directory=str(workdir),
        scheduler_invocation_topology="delegated_child",
        scheduler_task_action_arguments_b64=encoded_arguments(scheduler_arguments),
        scheduler_process_executable=sys.executable,
        scheduler_correlation_seconds=900,
        dry_run=False,
        resume_from_step="",
        force_lock=False,
        force_long_job_lock=False,
        disable_long_job_guard=False,
    )
    payload = task_payload(scheduler_executable, scheduler_arguments, workdir)
    expected_child_arguments = [
        "-m",
        "weather.operations.nightly_retrain",
        *running_arguments,
    ]
    lineage, command_parser = lineage_payload(
        sys.executable,
        expected_child_arguments,
        scheduler_executable,
        scheduler_arguments,
    )

    proof = build_invocation_proof(
        args,
        module_name="weather.operations.nightly_retrain",
        invocation_started_at_utc=NOW,
        argv=running_arguments,
        os_name="nt",
        task_query=lambda _name: payload,
        argument_parser=lambda _arguments: scheduler_arguments,
        process_query=lambda _process_id: lineage,
        process_argument_parser=command_parser,
        process_id=4242,
        process_image_executable=sys.executable,
    )

    assert proof["status"] == "PASS"
    assert proof["mode"] == "scheduled"
    assert proof["manual_intervention"] is False
    assert proof["contract"]["scheduler_action"]["arguments"] == scheduler_arguments
    assert proof["contract"]["producer_process"]["arguments"] == expected_child_arguments
    assert proof["process_lineage"]["status"] == "PASS"


@pytest.mark.parametrize(
    ("task_name", "stage"),
    [
        ("WeatherDailySettlementPromotionRefresh", "settlement"),
        ("WeatherEveningEvidenceRefresh", "evidence"),
    ],
)
def test_build_invocation_proof_accepts_daily_delegated_child(
    tmp_path,
    task_name,
    stage,
):
    if os.name != "nt":
        pytest.skip("daily delegated-child contract is a Windows PowerShell surface")
    scheduler_executable = tmp_path / "WindowsPowerShell" / "powershell.exe"
    workdir = Path.cwd()
    generated = daily_delegated_contract_tokens(
        workdir=workdir,
        stage=stage,
        task_name=task_name,
        scheduler_executable=scheduler_executable,
        process_executable=sys.executable,
    )
    scheduler_arguments = generated["action_tokens"]
    scheduler_action_contract = generated["action_contract"]
    expected_child_arguments = generated["child_tokens"]
    assert expected_child_arguments[:2] == [
        "-m",
        "weather.operations.daily_refresh",
    ]
    running_arguments = expected_child_arguments[2:]
    args = SimpleNamespace(
        scheduler_task_name=task_name,
        scheduler_task_executable=str(scheduler_executable),
        scheduler_task_working_directory=str(workdir),
        scheduler_invocation_topology="delegated_child",
        scheduler_task_action_arguments_b64=scheduler_action_contract,
        scheduler_process_executable=sys.executable,
        scheduler_correlation_seconds=300,
        dry_run=False,
        resume_from_step="",
        force_lock=False,
        force_long_job_lock=False,
        disable_long_job_guard=False,
    )
    payload = task_payload(
        scheduler_executable,
        scheduler_arguments,
        workdir,
        task_name=task_name,
    )
    lineage, command_parser = lineage_payload(
        sys.executable,
        expected_child_arguments,
        scheduler_executable,
        scheduler_arguments,
    )
    queried_task_names = []

    def query_task(queried_task_name):
        queried_task_names.append(queried_task_name)
        return payload

    proof = build_invocation_proof(
        args,
        module_name="weather.operations.daily_refresh",
        invocation_started_at_utc=NOW,
        argv=running_arguments,
        os_name="nt",
        task_query=query_task,
        argument_parser=lambda _arguments: scheduler_arguments,
        process_query=lambda _process_id: lineage,
        process_argument_parser=command_parser,
        process_id=4242,
        process_image_executable=sys.executable,
    )

    assert queried_task_names == [task_name]
    assert proof["status"] == "PASS"
    assert proof["scheduler_attested"] is True
    assert proof["mode"] == "scheduled"
    assert proof["invocation_topology"] == "delegated_child"
    assert proof["task_name"] == task_name
    assert proof["contract"]["scheduler_action"]["arguments"] == scheduler_arguments
    assert proof["contract"]["producer_process"]["arguments"] == expected_child_arguments
    assert proof["process_lineage"]["status"] == "PASS"
    assert proof["process_lineage"]["scheduler_process_id"] == 2121
    assert proof["process_lineage"]["scheduler_engine_process_id"] == 2121
    assert proof["process_lineage"]["scheduler_instance_guid"]


def test_invalid_delegated_action_contract_fails_before_task_query():
    queried = []
    args = SimpleNamespace(
        scheduler_task_name="WeatherProducer",
        scheduler_task_executable="powershell.exe",
        scheduler_task_working_directory=str(Path.cwd()),
        scheduler_invocation_topology="delegated_child",
        scheduler_task_action_arguments_b64="not-base64",
        scheduler_process_executable=sys.executable,
        scheduler_correlation_seconds=900,
        dry_run=False,
        resume_from_step="",
        force_lock=False,
        force_long_job_lock=False,
        disable_long_job_guard=False,
    )

    proof = build_invocation_proof(
        args,
        module_name="weather.operations.nightly_retrain",
        invocation_started_at_utc=NOW,
        argv=["run"],
        os_name="nt",
        task_query=lambda name: queried.append(name),
    )

    assert proof["status"] == "BLOCK"
    assert proof["mode"] == "manual_or_unverified"
    assert queried == []
    assert {row["code"] for row in proof["blockers"]} == {
        "scheduler_task_action_contract_invalid"
    }


def test_nonfinite_scheduler_correlation_fails_before_os_queries():
    queried = []
    args = SimpleNamespace(
        scheduler_task_name="WeatherProducer",
        scheduler_task_executable=sys.executable,
        scheduler_task_working_directory=str(Path.cwd()),
        scheduler_invocation_topology="direct",
        scheduler_task_action_arguments_b64="",
        scheduler_process_executable="",
        scheduler_correlation_seconds=float("nan"),
        dry_run=False,
        resume_from_step="",
        force_lock=False,
        force_long_job_lock=False,
        disable_long_job_guard=False,
    )

    proof = build_invocation_proof(
        args,
        module_name="weather.operations.nightly_retrain",
        invocation_started_at_utc=NOW,
        argv=["run"],
        os_name="nt",
        task_query=lambda name: queried.append(("task", name)),
        process_query=lambda process_id: queried.append(("process", process_id)),
    )

    assert proof["status"] == "BLOCK"
    assert proof["mode"] == "manual_or_unverified"
    assert queried == []
    assert {row["code"] for row in proof["blockers"]} == {
        "scheduler_correlation_contract_invalid"
    }


def test_nightly_parser_accepts_delegated_scheduler_contract():
    from weather.operations.nightly_retrain import build_parser

    contract = encoded_arguments(["-NoProfile", "-File", "training_window.ps1"])
    args = build_parser().parse_args([
        "run",
        "--scheduler-invocation-topology",
        "delegated_child",
        "--scheduler-task-name",
        "WeatherTrainingWindow",
        "--scheduler-task-executable",
        "powershell.exe",
        "--scheduler-task-working-directory",
        "repo",
        "--scheduler-task-action-arguments-b64",
        contract,
        "--scheduler-process-executable",
        "python.exe",
    ])

    assert args.scheduler_invocation_topology == "delegated_child"
    assert args.scheduler_task_action_arguments_b64 == contract
    assert args.scheduler_process_executable == "python.exe"


def test_scheduler_attestation_blocks_disabled_stale_or_action_mismatch(tmp_path):
    expected_executable = tmp_path / "pythonw.exe"
    registered_executable = tmp_path / "wrong.exe"
    expected_workdir = tmp_path / "repo"
    payload = task_payload(
        registered_executable,
        [],
        tmp_path / "wrong-repo",
        state="Disabled",
        enabled=False,
        last_run_time_utc=(NOW - timedelta(hours=2)).isoformat(),
    )

    proof = attest_scheduled_invocation(
        task_name="WeatherProducer",
        expected_executable=expected_executable,
        expected_arguments=["-m", "weather.operations.daily_refresh", "run"],
        expected_working_directory=expected_workdir,
        invocation_started_at_utc=NOW,
        process_executable=expected_executable,
        process_working_directory=expected_workdir,
        os_name="nt",
        task_query=lambda _name: payload,
        argument_parser=lambda _arguments: ["-m", "wrong.module", "run"],
    )

    codes = {row["code"] for row in proof["blockers"]}
    assert proof["status"] == "BLOCK"
    assert proof["scheduler_attested"] is False
    assert {
        "scheduler_task_disabled",
        "scheduler_task_not_running",
        "scheduler_executable_mismatch",
        "scheduler_working_directory_mismatch",
        "scheduler_arguments_mismatch",
        "scheduler_run_correlation_stale",
    }.issubset(codes)


def test_manual_or_non_windows_label_cannot_spoof_scheduled_invocation():
    args = SimpleNamespace(
        scheduler_task_name="WeatherProducer",
        scheduler_task_executable="pythonw.exe",
        scheduler_task_working_directory="repo",
        scheduler_correlation_seconds=120,
        dry_run=False,
        resume_from_step="",
        force_lock=False,
        force_long_job_lock=False,
        disable_long_job_guard=False,
    )

    proof = build_invocation_proof(
        args,
        module_name="weather.operations.daily_refresh",
        invocation_started_at_utc=NOW,
        argv=["run"],
        os_name="posix",
    )

    assert proof["status"] == "BLOCK"
    assert proof["mode"] == "manual_or_unverified"
    assert proof["scheduler_attested"] is False
    assert proof["manual_intervention"] is True


def test_instrumented_daily_and_long_job_locks_report_stale_and_force_exactly(tmp_path):
    daily_path = tmp_path / "daily.lock"
    daily_path.write_text(json.dumps({"pid": -999}), encoding="utf-8")
    daily_audit = {}
    daily_lock = acquire_lock(daily_path, audit=daily_audit)
    release_lock(daily_lock)

    long_path = tmp_path / "long.lock"
    long_path.write_text(json.dumps({"pid": 123}), encoding="utf-8")
    forced_audit = {}
    long_lock = acquire_long_job_lock(long_path, "test", force=True, audit=forced_audit)
    release_long_job_lock(long_lock)

    proof = build_lock_proof(daily_audit, forced_audit)
    assert daily_audit["stale_lock_detected_count"] == 1
    assert daily_audit["stale_lock_repair_count"] == 1
    assert forced_audit["forced_lock_acquisition_count"] == 1
    assert forced_audit["forced_lock_repair_count"] == 1
    assert proof["status"] == "BLOCK"
    assert proof["stale_lock_count"] == 1
    assert proof["forced_lock_acquisition_count"] == 1


def test_predeclared_stage_sla_is_exact_and_breaches_fail_closed():
    passed = build_stage_sla(duration_seconds=59, limit_seconds=60)
    breached = build_stage_sla(duration_seconds=61, limit_seconds=60)
    missing = build_stage_sla(duration_seconds=1, limit_seconds=0)

    assert passed["status"] == "PASS"
    assert breached["status"] == "BLOCK"
    assert breached["breach_seconds"] == 1.0
    assert missing["status"] == "BLOCK"
    assert missing["predeclared"] is False


def test_release_identity_only_emits_after_verified_serving_binding(tmp_path):
    bound = SimpleNamespace(
        status=STATUS_BOUND,
        reason="verified",
        release_id="release-1",
        manifest_sha256="a" * 64,
        pointer_sha256="b" * 64,
        sequence=3,
        release_kind=PRODUCTION_RELEASE_KIND,
        candidate_mode=PRODUCTION_CANDIDATE_MODE,
        production_capable=True,
        artifact_paths={"pooled_band_model": str(tmp_path / "model.pkl")},
    )
    unbound = SimpleNamespace(
        status="RESEARCH_UNBOUND",
        reason="missing pointer",
        release_id="legacy-should-not-leak",
        manifest_sha256="c" * 64,
        pointer_sha256="",
        sequence=None,
        release_kind="",
        candidate_mode="",
        production_capable=False,
        artifact_paths={},
    )

    passed = verified_active_release_proof(
        pointer_path=tmp_path / "pointer.json",
        releases_root=tmp_path,
        bundle_provider=lambda **_kwargs: bound,
    )
    blocked = verified_active_release_proof(
        pointer_path=tmp_path / "missing.json",
        releases_root=tmp_path,
        bundle_provider=lambda **_kwargs: unbound,
    )

    assert passed["status"] == "PASS"
    assert passed["served_bindings_verified"] is True
    assert passed["release_id"] == "release-1"
    assert blocked["status"] == "BLOCK"
    assert blocked["release_id"] == ""
    assert blocked["release_manifest_sha256"] == ""


def test_scheduler_registration_scripts_declare_producer_contracts():
    repo_root = Path(__file__).resolve().parents[2]
    daily_registration = (
        repo_root / "scripts" / "ops" / "register_daily_refresh.ps1"
    ).read_text(encoding="utf-8")
    daily_wrapper = (
        repo_root / "scripts" / "ops" / "daily_refresh.ps1"
    ).read_text(encoding="utf-8")
    daily_contract = (
        repo_root / "scripts" / "ops" / "daily_refresh_contract.ps1"
    ).read_text(encoding="utf-8")
    nightly_registration = (
        repo_root / "scripts" / "ops" / "register_nightly_retrain.ps1"
    ).read_text(encoding="utf-8")
    scripts = {
        "daily": daily_registration,
        "nightly": nightly_registration,
    }
    production_evidence_flags = (
        "--captured-input-parity-served",
        "--captured-input-parity-replay",
        "--production-readiness-served-artifact",
        "--production-readiness-served-route",
        "--fail-on-production-readiness-block",
    )
    for script in scripts.values():
        for flag in production_evidence_flags:
            assert flag in script
        assert "Mandatory = $true" in script
        assert "Resolve-RequiredFile" in script

    daily_scheduler_flags = (
        "--scheduler-task-name",
        "--scheduler-task-executable",
        "--scheduler-task-working-directory",
        "--producer-sla-seconds",
        "--releases-root",
        "--repo-root",
    )
    for flag in daily_scheduler_flags:
        assert flag in daily_contract
    assert '"--scheduler-invocation-topology", "delegated_child"' in daily_contract
    assert "--active-release-pointer" in daily_contract
    assert "Get-DailyRefreshTaskActionTokens" in daily_registration
    assert "Get-DailyRefreshTaskActionTokens" in daily_wrapper
    assert "Get-DailyRefreshChildTokens" in daily_wrapper
    assert 'DefaultParameterSetName = "Full"' in daily_registration
    assert 'ParameterSetName = "Full"' in daily_registration
    assert 'ParameterSetName = "ProvenanceOnly"' in daily_registration
    assert "--scheduler-invocation-topology direct" in nightly_registration
    assert "--release-pointer" in nightly_registration

    training_register = (
        repo_root / "scripts" / "ops" / "register_training_window.ps1"
    ).read_text(encoding="utf-8")
    training_window = (
        repo_root / "scripts" / "ops" / "training_window.ps1"
    ).read_text(encoding="utf-8")
    assert "Get-TrainingWindowTaskActionTokens" in training_register
    assert "Get-TrainingWindowTaskActionTokens" in training_window
    assert "ConvertTo-SchedulerArgumentContract" in training_window
    assert '"--scheduler-invocation-topology", "delegated_child"' in training_window
    assert '"--scheduler-task-action-arguments-b64"' in training_window
    assert '"--scheduler-process-executable"' in training_window
