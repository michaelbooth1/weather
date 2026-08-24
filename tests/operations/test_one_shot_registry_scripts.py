from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
OPS = REPO_ROOT / "scripts" / "ops"
WRITER = OPS / "write_one_shot_active_manifest.ps1"
RESOLVER = OPS / "resolve_one_shot_active_manifest.ps1"
RECOVERY = OPS / "recover_one_shot_registry_activation.ps1"
COMPACTOR = OPS / "compact_one_shot_registry.ps1"
DEBRIS_RECONCILER = OPS / "reconcile_one_shot_registry_debris.ps1"
VALIDATOR = OPS / "one_shot_readiness.ps1"
WORKLOAD_ADMISSION = OPS / "workload_admission.ps1"
GUARDED_LAUNCHER = OPS / "one_shot_guarded_launcher.ps1"
JOB_CONTAINMENT = OPS / "windows_kill_on_close_job.ps1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _powershell() -> str:
    return shutil.which("powershell") or str(
        Path(
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        )
    )


def _copy_registry_repo(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = tmp_path / "repo"
    ops = repo / "scripts" / "ops"
    ops.mkdir(parents=True)
    for source in (
        WRITER,
        RESOLVER,
        RECOVERY,
        COMPACTOR,
        DEBRIS_RECONCILER,
        VALIDATOR,
        WORKLOAD_ADMISSION,
        GUARDED_LAUNCHER,
        JOB_CONTAINMENT,
    ):
        shutil.copy2(source, ops / source.name)

    action = tmp_path / "action.ps1"
    action.write_text("Write-Output 'bounded one-shot'\n", encoding="utf-8")
    powershell = str(Path(_powershell()).resolve())
    now = datetime.now().astimezone()
    # Manifest reading validates the host-local offset but not futurity. A
    # near-current instant avoids fixed-offset DST flakiness in this file-only
    # registry test; pre-trigger timing is covered by the validator tests.
    trigger = now.replace(microsecond=0)
    earliest = trigger - timedelta(hours=1)
    deadline = trigger + timedelta(hours=2)
    boot = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    validator = (ops / VALIDATOR.name).resolve()
    admission = (ops / WORKLOAD_ADMISSION.name).resolve()
    launcher = (ops / GUARDED_LAUNCHER.name).resolve()
    job_containment = (ops / JOB_CONTAINMENT.name).resolve()
    manifest = {
        "schema_version": "weather_one_shot_readiness_manifest_v0.4",
        "task": {
            "task_name": "WeatherSyntheticRegistryOneShot",
            "task_path": "\\",
            "executable": powershell,
            "arguments_template": (
                f'-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{launcher}" '
                '-ReadinessManifestPath "{READINESS_MANIFEST_PATH}" '
                "-ExpectedReadinessManifestSha256 "
                "{EXPECTED_READINESS_MANIFEST_SHA256}"
            ),
            "working_directory": str(repo.resolve()),
            "action_file": str(launcher),
            "payload_file": str(action.resolve()),
            "payload_arguments": [],
            "trigger_at_local": trigger.isoformat(),
        },
        "principal": {
            "user_id": "weather-operator",
            "logon_type": "S4U",
            "run_level": "Limited",
        },
        "settings": {
            "multiple_instances": "IgnoreNew",
            "execution_time_limit": "PT1H",
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
            "teardown_deadline_at_local": deadline.isoformat(),
        },
        "boot_identity": {"last_boot_up_time_utc": boot},
        "dependencies": [
            {"path": str(launcher), "sha256": _sha256(launcher)},
            {"path": str(job_containment), "sha256": _sha256(job_containment)},
            {"path": str(action.resolve()), "sha256": _sha256(action)},
            {"path": str(validator), "sha256": _sha256(validator)},
        ],
    }
    source = tmp_path / "reviewed-manifest.json"
    source.write_text(json.dumps(manifest), encoding="utf-8")
    return repo, source, _sha256(source)


def _run_writer(repo: Path, source: Path, digest: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            _powershell(),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo / "scripts" / "ops" / WRITER.name),
            "-RepoRoot",
            str(repo),
            "-SourceManifestPath",
            str(source),
            "-ExpectedSourceSha256",
            digest,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _run_resolver(
    repo: Path,
    manifest: Path,
    digest: str,
    *,
    task_state: str,
    scheduler_error: bool = False,
    status: str = "TERMINAL",
    successor_source: Path | None = None,
    successor_sha256: str = "",
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "WEATHER_TEST_REPO": str(repo),
            "WEATHER_TEST_MANIFEST": str(manifest),
            "WEATHER_TEST_SHA": digest,
            "WEATHER_TEST_TASK_STATE": task_state,
            "WEATHER_TEST_SCHEDULER_ERROR": str(scheduler_error),
            "WEATHER_TEST_STATUS": status,
            "WEATHER_TEST_SUCCESSOR_SOURCE": (
                "" if successor_source is None else str(successor_source)
            ),
            "WEATHER_TEST_SUCCESSOR_SHA": successor_sha256,
        }
    )
    command = r"""
$ErrorActionPreference = 'Stop'
function Get-ScheduledTask {
    [CmdletBinding()]
    param()
    if ([bool]::Parse($env:WEATHER_TEST_SCHEDULER_ERROR)) {
        throw 'synthetic Scheduler access failure'
    }
    if ($env:WEATHER_TEST_TASK_STATE -eq 'ABSENT') { return @() }
    return [pscustomobject]@{
        TaskName = 'WeatherSyntheticRegistryOneShot'
        TaskPath = '\'
        State = $env:WEATHER_TEST_TASK_STATE
    }
}
function Get-ScheduledTaskInfo {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)]$InputObject)
    return [pscustomobject]@{
        NextRunTime = $null
        LastRunTime = [datetime]'2026-08-24T01:15:00'
        LastTaskResult = 0
    }
}
try {
    $arguments = @{
        RepoRoot = $env:WEATHER_TEST_REPO
        ManifestPath = $env:WEATHER_TEST_MANIFEST
        ExpectedManifestSha256 = $env:WEATHER_TEST_SHA
        Status = $env:WEATHER_TEST_STATUS
        Reason = 'synthetic terminal proof'
        ReviewReference = 'tests/operations/test_one_shot_registry_scripts.py'
    }
    if ($env:WEATHER_TEST_SUCCESSOR_SOURCE) {
        $arguments.SuccessorSourceManifestPath = $env:WEATHER_TEST_SUCCESSOR_SOURCE
    }
    if ($env:WEATHER_TEST_SUCCESSOR_SHA) {
        $arguments.ExpectedSuccessorManifestSha256 = $env:WEATHER_TEST_SUCCESSOR_SHA
    }
    & (Join-Path $env:WEATHER_TEST_REPO `
        'scripts\ops\resolve_one_shot_active_manifest.ps1') @arguments
}
catch {
    [Console]::Error.WriteLine([string]$_.ScriptStackTrace)
    throw
}
"""
    return subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _run_activation_recovery(
    repo: Path,
    *,
    orphan_state: str = "",
    binding_style: str = "space",
    scheduler_error: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "WEATHER_TEST_REPO": str(repo),
            "WEATHER_TEST_ORPHAN_STATE": orphan_state,
            "WEATHER_TEST_BINDING_STYLE": binding_style,
            "WEATHER_TEST_SCHEDULER_ERROR": str(scheduler_error),
        }
    )
    command = r"""
$ErrorActionPreference = 'Stop'
function Get-ScheduledTask {
    [CmdletBinding()]
    param()
    if ([bool]::Parse($env:WEATHER_TEST_SCHEDULER_ERROR)) {
        throw 'synthetic Scheduler inventory failure'
    }
    if (-not $env:WEATHER_TEST_ORPHAN_STATE) { return @() }
    return [pscustomobject]@{
        TaskName = 'WeatherSyntheticRegistryOneShot'
        TaskPath = '\'
        State = $env:WEATHER_TEST_ORPHAN_STATE
        Actions = @([pscustomobject]@{
            Execute = if ($env:WEATHER_TEST_BINDING_STYLE -in @('launcher', 'alias')) {
                Join-Path $env:WEATHER_TEST_REPO 'scripts\ops\one_shot_guarded_launcher.ps1'
            } else { $env:SystemRoot + '\System32\WindowsPowerShell\v1.0\powershell.exe' }
            Arguments = if ($env:WEATHER_TEST_BINDING_STYLE -eq 'colon') {
                '-ReadinessManifestPath:"missing.json" -ExpectedReadinessManifestSha256:' + ('a' * 64)
            } elseif ($env:WEATHER_TEST_BINDING_STYLE -in @('alias', 'generic_alias')) {
                '-ManifestPath "missing.json" -ExpectedManifestSha256 ' + ('a' * 64)
            } elseif ($env:WEATHER_TEST_BINDING_STYLE -eq 'launcher') {
                '-File "one_shot_guarded_launcher.ps1"'
            } else {
                '-ReadinessManifestPath "missing.json" -ExpectedReadinessManifestSha256 ' + ('a' * 64)
            }
        })
    }
}
& (Join-Path $env:WEATHER_TEST_REPO `
    'scripts\ops\recover_one_shot_registry_activation.ps1') `
    -RepoRoot $env:WEATHER_TEST_REPO `
    -Reason 'reviewed synthetic interrupted first activation' `
    -ReviewReference 'tests/operations/test_one_shot_registry_scripts.py' `
    -Confirmation 'REVIEWED_RECONCILE_EMPTY_ONE_SHOT_REGISTRY_ACTIVATION'
"""
    return subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _run_compactor(
    repo: Path,
    manifest: Path,
    manifest_sha256: str,
    resolution_sha256: str,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "WEATHER_TEST_REPO": str(repo),
            "WEATHER_TEST_MANIFEST": str(manifest),
            "WEATHER_TEST_MANIFEST_SHA": manifest_sha256,
            "WEATHER_TEST_RESOLUTION_SHA": resolution_sha256,
        }
    )
    command = r"""
$ErrorActionPreference = 'Stop'
function Get-ScheduledTask { [CmdletBinding()] param(); return @() }
try {
    & (Join-Path $env:WEATHER_TEST_REPO `
        'scripts\ops\compact_one_shot_registry.ps1') `
        -RepoRoot $env:WEATHER_TEST_REPO `
        -ManifestPath $env:WEATHER_TEST_MANIFEST `
        -ExpectedManifestSha256 $env:WEATHER_TEST_MANIFEST_SHA `
        -ExpectedResolutionSha256 $env:WEATHER_TEST_RESOLUTION_SHA `
        -Reason 'reviewed bounded history compaction' `
        -ReviewReference 'tests/operations/test_one_shot_registry_scripts.py' `
        -Confirmation 'REVIEWED_COMPACT_RESOLVED_ONE_SHOT_HISTORY'
}
catch {
    [Console]::Error.WriteLine([string]$_.ScriptStackTrace)
    throw
}
"""
    return subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _run_debris_reconciler(
    repo: Path,
    debris: Path,
    debris_sha256: str,
    *,
    scheduler_state: str = "ABSENT",
    scheduler_error: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "WEATHER_TEST_REPO": str(repo),
            "WEATHER_TEST_DEBRIS": str(debris),
            "WEATHER_TEST_DEBRIS_SHA": debris_sha256,
            "WEATHER_TEST_SCHEDULER_STATE": scheduler_state,
            "WEATHER_TEST_SCHEDULER_ERROR": str(scheduler_error),
        }
    )
    command = r"""
$ErrorActionPreference = 'Stop'
function Get-ScheduledTask {
    [CmdletBinding()]
    param()
    if ([bool]::Parse($env:WEATHER_TEST_SCHEDULER_ERROR)) {
        throw 'synthetic Scheduler inventory failure'
    }
    if ($env:WEATHER_TEST_SCHEDULER_STATE -cne 'ABSENT') {
        return [pscustomobject]@{
            TaskName = 'WeatherSyntheticRegistryOneShot'
            TaskPath = '\'
            State = $env:WEATHER_TEST_SCHEDULER_STATE
        }
    }
    return @()
}
& (Join-Path $env:WEATHER_TEST_REPO `
    'scripts\ops\reconcile_one_shot_registry_debris.ps1') `
    -RepoRoot $env:WEATHER_TEST_REPO `
    -DebrisPath $env:WEATHER_TEST_DEBRIS `
    -ExpectedDebrisSha256 $env:WEATHER_TEST_DEBRIS_SHA `
    -Reason 'reviewed invalid pending test debris' `
    -ReviewReference 'tests/operations/test_one_shot_registry_scripts.py' `
    -Confirmation 'REVIEWED_REMOVE_INVALID_ONE_SHOT_SUCCESSOR_PENDING'
"""
    return subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_registry_publication_is_atomic_create_only_and_independently_marked() -> None:
    writer = WRITER.read_text(encoding="utf-8-sig")
    resolver = RESOLVER.read_text(encoding="utf-8-sig")

    assert "Flush($true)" in writer
    assert "[IO.File]::Move($temporary, $Destination)" in writer
    assert "Flush($true)" in resolver
    assert "[IO.File]::Move($temporary, $Destination)" in resolver
    assert 'Join-Path $RepoRoot "one_shot_registry_activation.json"' in writer
    assert 'data\\one_shot_readiness\\registry_activation.json' not in writer
    assert "Get-ScheduledTask -ErrorAction Stop" in resolver
    assert '$state -ceq "Disabled"' in resolver
    assert "REVIEWED_RECONCILE_EMPTY_ONE_SHOT_REGISTRY_ACTIVATION" in (
        RECOVERY.read_text(encoding="utf-8-sig")
    )


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_writer_freezes_exact_anchor_and_never_overwrites(tmp_path: Path) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)

    first = _run_writer(repo, source, digest)
    assert first.returncode == 0, first.stderr
    payload = json.loads(first.stdout)
    anchor = Path(payload["manifest_path"])
    marker = repo / "one_shot_registry_activation.json"
    assert anchor.read_bytes() == source.read_bytes()
    assert anchor.name == f"WeatherSyntheticRegistryOneShot.{digest}.manifest.json"
    assert marker.is_file()
    assert marker.parent == repo
    assert not list(anchor.parent.glob("*.tmp"))

    original = anchor.read_bytes()
    second = _run_writer(repo, source, digest)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["status"] == "ALREADY_FROZEN"
    assert anchor.read_bytes() == original


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
@pytest.mark.parametrize("crash_bytes", [b"", b"partial"])
def test_writer_reconciles_strict_partial_atomic_crash_debris(
    tmp_path: Path, crash_bytes: bytes
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    first = _run_writer(repo, source, digest)
    assert first.returncode == 0, first.stderr
    anchor = Path(json.loads(first.stdout)["manifest_path"])
    anchor.unlink()
    debris = anchor.with_name(f".{anchor.name}.{'a' * 32}.tmp")
    debris.write_bytes(crash_bytes)

    recovered = _run_writer(repo, source, digest)
    assert recovered.returncode == 0, recovered.stderr
    assert anchor.read_bytes() == source.read_bytes()
    assert not debris.exists()


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
@pytest.mark.parametrize("task_state", ["Running", "Queued", "Ready"])
def test_resolver_refuses_every_still_executable_state(
    tmp_path: Path, task_state: str
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    written = _run_writer(repo, source, digest)
    assert written.returncode == 0, written.stderr
    anchor = Path(json.loads(written.stdout)["manifest_path"])

    result = _run_resolver(repo, anchor, digest, task_state=task_state)
    resolution = anchor.with_name(anchor.name.replace(".manifest.json", ".resolution.json"))
    assert result.returncode != 0
    assert not resolution.exists()


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_resolver_requires_successful_inventory_to_prove_absence(
    tmp_path: Path,
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    written = _run_writer(repo, source, digest)
    assert written.returncode == 0, written.stderr
    anchor = Path(json.loads(written.stdout)["manifest_path"])

    failed = _run_resolver(
        repo, anchor, digest, task_state="ABSENT", scheduler_error=True
    )
    resolution = anchor.with_name(anchor.name.replace(".manifest.json", ".resolution.json"))
    assert failed.returncode != 0
    assert not resolution.exists()

    passed = _run_resolver(repo, anchor, digest, task_state="ABSENT")
    assert passed.returncode == 0, passed.stderr
    payload = json.loads(passed.stdout)
    assert payload["task_terminal_proof"]["state"] == "ABSENT"
    assert payload["task_terminal_proof"]["cannot_execute"] is True
    assert resolution.is_file()
    assert not list(resolution.parent.glob("*.tmp"))

    rearmed = _run_resolver(repo, anchor, digest, task_state="Ready")
    assert rearmed.returncode != 0


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_resolver_repairs_only_valid_missing_resolution_index_event(
    tmp_path: Path,
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    written = _run_writer(repo, source, digest)
    anchor = Path(json.loads(written.stdout)["manifest_path"])
    resolved = _run_resolver(repo, anchor, digest, task_state="ABSENT")
    assert resolved.returncode == 0, resolved.stderr
    resolution = anchor.with_name(anchor.name.replace(".manifest.json", ".resolution.json"))
    event = (
        repo
        / "one_shot_registry_index"
        / f"resolution.WeatherSyntheticRegistryOneShot.{digest}.json"
    )
    event.unlink()

    repaired = _run_resolver(repo, anchor, digest, task_state="ABSENT")
    assert repaired.returncode == 0, repaired.stderr
    assert event.is_file()

    resolution.unlink()
    refused = _run_resolver(repo, anchor, digest, task_state="ABSENT")
    assert refused.returncode != 0
    assert event.is_file()


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_idempotent_resolution_rejects_incoherent_stored_terminal_proof(
    tmp_path: Path,
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    written = _run_writer(repo, source, digest)
    assert written.returncode == 0, written.stderr
    anchor = Path(json.loads(written.stdout)["manifest_path"])
    resolved = _run_resolver(repo, anchor, digest, task_state="ABSENT")
    assert resolved.returncode == 0, resolved.stderr
    resolution = anchor.with_name(anchor.name.replace(".manifest.json", ".resolution.json"))
    payload = json.loads(resolution.read_text(encoding="utf-8"))
    payload["task_terminal_proof"]["exists"] = True
    payload["task_terminal_proof"]["state"] = "ABSENT"
    resolution.write_text(json.dumps(payload), encoding="utf-8")

    retried = _run_resolver(repo, anchor, digest, task_state="ABSENT")
    assert retried.returncode != 0


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
@pytest.mark.parametrize("malformation", ["state", "proof_gap"])
def test_writer_refuses_malformed_prior_resolution_history(
    tmp_path: Path, malformation: str
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    written = _run_writer(repo, source, digest)
    assert written.returncode == 0, written.stderr
    anchor = Path(json.loads(written.stdout)["manifest_path"])
    resolved = _run_resolver(repo, anchor, digest, task_state="ABSENT")
    assert resolved.returncode == 0, resolved.stderr
    resolution = anchor.with_name(anchor.name.replace(".manifest.json", ".resolution.json"))
    payload = json.loads(resolution.read_text(encoding="utf-8"))
    if malformation == "state":
        payload["task_terminal_proof"]["exists"] = True
        payload["task_terminal_proof"]["state"] = "ABSENT"
    else:
        resolved_at = datetime.fromisoformat(payload["resolved_at_local"])
        payload["task_terminal_proof"]["observed_at_local"] = (
            resolved_at - timedelta(minutes=6)
        ).isoformat()
    resolution.write_text(json.dumps(payload), encoding="utf-8")

    next_payload = json.loads(source.read_text(encoding="utf-8"))
    next_payload["principal"]["user_id"] = "weather-operator-next"
    successor = tmp_path / "next-generation.json"
    successor.write_text(json.dumps(next_payload), encoding="utf-8")
    refused = _run_writer(repo, successor, _sha256(successor))
    assert refused.returncode != 0


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_activation_marker_survives_whole_active_parent_deletion(
    tmp_path: Path,
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    written = _run_writer(repo, source, digest)
    assert written.returncode == 0, written.stderr
    marker = repo / "one_shot_registry_activation.json"
    data_root = repo / "data"

    shutil.rmtree(data_root)

    assert marker.is_file()
    assert not data_root.exists()

    retry = _run_writer(repo, source, digest)
    assert retry.returncode != 0
    assert not data_root.exists()


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_deleted_durable_registry_lock_is_never_silently_recreated(
    tmp_path: Path,
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    written = _run_writer(repo, source, digest)
    assert written.returncode == 0, written.stderr
    anchor = Path(json.loads(written.stdout)["manifest_path"])
    lock = repo / "one_shot_registry.lock"
    lock.unlink()

    writer_retry = _run_writer(repo, source, digest)
    assert writer_retry.returncode != 0
    assert not lock.exists()

    resolution = anchor.with_name(anchor.name.replace(".manifest.json", ".resolution.json"))
    resolver = _run_resolver(repo, anchor, digest, task_state="ABSENT")
    assert resolver.returncode != 0
    assert not resolution.exists()
    assert not lock.exists()


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_reviewed_recovery_closes_interrupted_empty_first_activation(
    tmp_path: Path,
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    active = repo / "data" / "one_shot_readiness" / "active"
    active.mkdir(parents=True)
    (repo / "one_shot_registry.lock").write_bytes(b"")

    recovered = _run_activation_recovery(repo)
    assert recovered.returncode == 0, recovered.stderr
    payload = json.loads(recovered.stdout)
    marker = repo / "one_shot_registry_activation.json"
    intent = repo / "one_shot_registry_activation_intent.json"
    receipt = repo / "one_shot_registry_activation_recovery.json"
    assert payload["status"] == "PASS"
    assert marker.is_file()
    assert intent.is_file()
    assert receipt.is_file()

    repeated = _run_activation_recovery(repo)
    assert repeated.returncode == 0, repeated.stderr
    assert marker.is_file()

    published = _run_writer(repo, source, digest)
    assert published.returncode == 0, published.stderr
    anchor = Path(json.loads(published.stdout)["manifest_path"])
    resolved = _run_resolver(repo, anchor, digest, task_state="ABSENT")
    assert resolved.returncode == 0, resolved.stderr


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
@pytest.mark.parametrize("orphan_state", ["Ready", "Disabled"])
@pytest.mark.parametrize("binding_style", ["space", "colon", "alias", "launcher"])
def test_activation_recovery_refuses_any_readiness_bound_scheduler_orphan(
    tmp_path: Path, orphan_state: str, binding_style: str
) -> None:
    repo, _, _ = _copy_registry_repo(tmp_path)
    active = repo / "data" / "one_shot_readiness" / "active"
    active.mkdir(parents=True)
    (repo / "one_shot_registry.lock").write_bytes(b"")

    refused = _run_activation_recovery(
        repo, orphan_state=orphan_state, binding_style=binding_style
    )
    assert refused.returncode != 0
    assert not (repo / "one_shot_registry_activation.json").exists()
    assert not (repo / "one_shot_registry_activation_recovery.json").exists()


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_activation_recovery_does_not_misclassify_generic_manifest_aliases(
    tmp_path: Path,
) -> None:
    repo, _, _ = _copy_registry_repo(tmp_path)
    active = repo / "data" / "one_shot_readiness" / "active"
    active.mkdir(parents=True)
    (repo / "one_shot_registry.lock").write_bytes(b"")

    recovered = _run_activation_recovery(
        repo, orphan_state="Disabled", binding_style="generic_alias"
    )
    assert recovered.returncode == 0, recovered.stderr


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_recovered_registry_cannot_forget_later_marker_and_data_loss(
    tmp_path: Path,
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    active = repo / "data" / "one_shot_readiness" / "active"
    active.mkdir(parents=True)
    (repo / "one_shot_registry.lock").write_bytes(b"")
    recovered = _run_activation_recovery(repo)
    assert recovered.returncode == 0, recovered.stderr

    shutil.rmtree(repo / "data")
    (repo / "one_shot_registry_activation.json").unlink()
    assert (repo / "one_shot_registry_activation_intent.json").is_file()
    assert (repo / "one_shot_registry_activation_recovery.json").is_file()

    refused = _run_writer(repo, source, digest)
    assert refused.returncode != 0
    assert not (repo / "data").exists()


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_same_task_supersession_publishes_resolution_before_successor(
    tmp_path: Path,
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    written = _run_writer(repo, source, digest)
    assert written.returncode == 0, written.stderr
    anchor = Path(json.loads(written.stdout)["manifest_path"])

    successor_payload = json.loads(source.read_text(encoding="utf-8"))
    successor_payload["principal"]["user_id"] = "weather-operator-reviewed-v2"
    successor = tmp_path / "reviewed-successor.json"
    successor.write_text(json.dumps(successor_payload), encoding="utf-8")
    successor_sha256 = _sha256(successor)

    resolved = _run_resolver(
        repo,
        anchor,
        digest,
        task_state="ABSENT",
        status="SUPERSEDED",
        successor_source=successor,
        successor_sha256=successor_sha256,
    )
    assert resolved.returncode == 0, resolved.stderr
    payload = json.loads(resolved.stdout)
    successor_anchor = Path(payload["successor_manifest_path"])
    assert payload["status"] == "SUPERSEDED"
    assert successor_anchor.read_bytes() == successor.read_bytes()
    assert successor_anchor.name.endswith(f".{successor_sha256}.manifest.json")

    # Simulate a host stop after durable pending publication + predecessor
    # resolution but before the final successor rename. Recovery does not
    # depend on the external reviewed source still existing.
    pending = successor_anchor.with_name(
        f"WeatherSyntheticRegistryOneShot.{successor_sha256}.successor.pending.json"
    )
    successor_anchor.replace(pending)
    successor.unlink()
    retried = _run_resolver(
        repo,
        anchor,
        digest,
        task_state="ABSENT",
        status="SUPERSEDED",
        successor_sha256=successor_sha256,
    )
    assert retried.returncode == 0, retried.stderr
    assert json.loads(retried.stdout)["successor_manifest_sha256"] == (
        successor_sha256
    )
    assert successor_anchor.is_file()
    assert not pending.exists()

    # Completing the superseded generation must not wedge a later reviewed
    # generation of the same Scheduler task identity.
    completed_successor = _run_resolver(
        repo, successor_anchor, successor_sha256, task_state="ABSENT"
    )
    assert completed_successor.returncode == 0, completed_successor.stderr
    third_payload = successor_payload
    third_payload["principal"]["user_id"] = "weather-operator-reviewed-v3"
    third = tmp_path / "reviewed-third.json"
    third.write_text(json.dumps(third_payload), encoding="utf-8")
    third_hash = _sha256(third)
    third_written = _run_writer(repo, third, third_hash)
    assert third_written.returncode == 0, third_written.stderr
    assert json.loads(third_written.stdout)["manifest_sha256"] == third_hash


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_wrong_identity_successor_is_rejected_before_pending_write(
    tmp_path: Path,
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    written = _run_writer(repo, source, digest)
    anchor = Path(json.loads(written.stdout)["manifest_path"])
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["task"]["task_name"] = "WeatherDifferentOneShot"
    wrong = tmp_path / "wrong-successor.json"
    wrong.write_text(json.dumps(payload), encoding="utf-8")
    wrong_sha = _sha256(wrong)

    refused = _run_resolver(
        repo,
        anchor,
        digest,
        task_state="ABSENT",
        status="SUPERSEDED",
        successor_source=wrong,
        successor_sha256=wrong_sha,
    )
    assert refused.returncode != 0
    assert not list(anchor.parent.glob("*.successor.pending.json"))


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_reviewed_debris_reconciler_removes_invalid_but_not_valid_pending(
    tmp_path: Path,
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    written = _run_writer(repo, source, digest)
    anchor = Path(json.loads(written.stdout)["manifest_path"])

    malformed = anchor.parent / (
        "WeatherSyntheticRegistryOneShot."
        + hashlib.sha256(b'{"principal":{}}').hexdigest()
        + ".successor.pending.json"
    )
    malformed.write_bytes(b'{"principal":{}}')
    malformed_sha = _sha256(malformed)
    reconciled = _run_debris_reconciler(repo, malformed, malformed_sha)
    assert reconciled.returncode == 0, reconciled.stderr
    assert not malformed.exists()
    receipt = (
        repo
        / "one_shot_registry_index"
        / (
            "debris.successor_pending.WeatherSyntheticRegistryOneShot."
            + malformed_sha
            + ".json"
        )
    )
    assert receipt.is_file()

    valid_payload = json.loads(source.read_text(encoding="utf-8"))
    valid_payload["principal"]["user_id"] = "weather-operator-valid-next"
    valid_bytes = json.dumps(valid_payload).encode()
    valid_sha = hashlib.sha256(valid_bytes).hexdigest()
    valid_pending = anchor.parent / (
        f"WeatherSyntheticRegistryOneShot.{valid_sha}.successor.pending.json"
    )
    valid_pending.write_bytes(valid_bytes)
    refused = _run_debris_reconciler(repo, valid_pending, valid_sha)
    assert refused.returncode != 0
    assert valid_pending.exists()


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_debris_reconciler_removes_valid_pending_with_invalid_predecessor(
    tmp_path: Path,
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    written = _run_writer(repo, source, digest)
    assert written.returncode == 0, written.stderr
    anchor = Path(json.loads(written.stdout)["manifest_path"])

    invalid_predecessor_payload = json.loads(source.read_text(encoding="utf-8"))
    invalid_predecessor_payload["settings"]["wake_to_run"] = "true"
    invalid_predecessor_bytes = json.dumps(invalid_predecessor_payload).encode()
    invalid_predecessor_sha = hashlib.sha256(invalid_predecessor_bytes).hexdigest()
    invalid_predecessor = anchor.parent / (
        "WeatherSyntheticRegistryOneShot."
        + invalid_predecessor_sha
        + ".manifest.json"
    )
    anchor.unlink()
    invalid_predecessor.write_bytes(invalid_predecessor_bytes)

    pending_payload = json.loads(source.read_text(encoding="utf-8"))
    pending_payload["principal"]["user_id"] = "weather-operator-valid-next"
    pending_bytes = json.dumps(pending_payload).encode()
    pending_sha = hashlib.sha256(pending_bytes).hexdigest()
    pending = anchor.parent / (
        f"WeatherSyntheticRegistryOneShot.{pending_sha}.successor.pending.json"
    )
    pending.write_bytes(pending_bytes)

    reconciled = _run_debris_reconciler(repo, pending, pending_sha)

    assert reconciled.returncode == 0, reconciled.stderr
    assert not pending.exists()
    assert invalid_predecessor.is_file()
    receipt = (
        repo
        / "one_shot_registry_index"
        / (
            "debris.successor_pending.WeatherSyntheticRegistryOneShot."
            + pending_sha
            + ".json"
        )
    )
    assert receipt.is_file()


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_debris_reconciler_receipt_first_retry_removes_unchanged_remainder(
    tmp_path: Path,
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    written = _run_writer(repo, source, digest)
    assert written.returncode == 0, written.stderr
    anchor = Path(json.loads(written.stdout)["manifest_path"])
    debris_bytes = b'{"principal":{}}'
    debris_sha = hashlib.sha256(debris_bytes).hexdigest()
    debris = anchor.parent / (
        f"WeatherSyntheticRegistryOneShot.{debris_sha}.successor.pending.json"
    )
    debris.write_bytes(debris_bytes)

    initial = _run_debris_reconciler(repo, debris, debris_sha)
    assert initial.returncode == 0, initial.stderr
    assert not debris.exists()
    receipt = (
        repo
        / "one_shot_registry_index"
        / (
            "debris.successor_pending.WeatherSyntheticRegistryOneShot."
            + debris_sha
            + ".json"
        )
    )
    assert receipt.is_file()

    # Recreate the exact remainder left by an interruption after the durable
    # receipt was published but before the pending file was deleted.
    debris.write_bytes(debris_bytes)
    resumed = _run_debris_reconciler(repo, debris, debris_sha)
    assert resumed.returncode == 0, resumed.stderr
    assert not debris.exists()

    repeated = _run_debris_reconciler(repo, debris, debris_sha)
    assert repeated.returncode == 0, repeated.stderr
    assert not debris.exists()


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_debris_reconciler_refuses_changed_receipt_first_remainder(
    tmp_path: Path,
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    written = _run_writer(repo, source, digest)
    assert written.returncode == 0, written.stderr
    anchor = Path(json.loads(written.stdout)["manifest_path"])
    reviewed_bytes = b'{"principal":{}}'
    reviewed_sha = hashlib.sha256(reviewed_bytes).hexdigest()
    debris = anchor.parent / (
        f"WeatherSyntheticRegistryOneShot.{reviewed_sha}.successor.pending.json"
    )
    debris.write_bytes(reviewed_bytes)

    initial = _run_debris_reconciler(repo, debris, reviewed_sha)
    assert initial.returncode == 0, initial.stderr
    assert not debris.exists()

    changed_bytes = b'{"principal":{"changed":true}}'
    debris.write_bytes(changed_bytes)
    refused = _run_debris_reconciler(repo, debris, reviewed_sha)

    assert refused.returncode != 0
    assert "does not match its reviewed hash" in refused.stderr
    assert debris.read_bytes() == changed_bytes


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_debris_reconciler_refuses_scheduler_inventory_failure(
    tmp_path: Path,
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    written = _run_writer(repo, source, digest)
    assert written.returncode == 0, written.stderr
    anchor = Path(json.loads(written.stdout)["manifest_path"])
    debris_bytes = b'{"principal":{}}'
    debris_sha = hashlib.sha256(debris_bytes).hexdigest()
    debris = anchor.parent / (
        f"WeatherSyntheticRegistryOneShot.{debris_sha}.successor.pending.json"
    )
    debris.write_bytes(debris_bytes)

    refused = _run_debris_reconciler(
        repo, debris, debris_sha, scheduler_error=True
    )

    assert refused.returncode != 0
    assert "Task Scheduler inventory failed" in refused.stderr
    assert debris.read_bytes() == debris_bytes
    assert not (
        repo
        / "one_shot_registry_index"
        / (
            "debris.successor_pending.WeatherSyntheticRegistryOneShot."
            + debris_sha
            + ".json"
        )
    ).exists()


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_debris_reconciler_refuses_same_name_non_disabled_task(
    tmp_path: Path,
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    written = _run_writer(repo, source, digest)
    assert written.returncode == 0, written.stderr
    anchor = Path(json.loads(written.stdout)["manifest_path"])
    debris_bytes = b'{"principal":{}}'
    debris_sha = hashlib.sha256(debris_bytes).hexdigest()
    debris = anchor.parent / (
        f"WeatherSyntheticRegistryOneShot.{debris_sha}.successor.pending.json"
    )
    debris.write_bytes(debris_bytes)

    refused = _run_debris_reconciler(
        repo, debris, debris_sha, scheduler_state="Ready"
    )

    assert refused.returncode != 0
    assert "requires every same-name task to be absent or Disabled" in refused.stderr
    assert debris.read_bytes() == debris_bytes
    assert not (
        repo
        / "one_shot_registry_index"
        / (
            "debris.successor_pending.WeatherSyntheticRegistryOneShot."
            + debris_sha
            + ".json"
        )
    ).exists()


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_compaction_is_receipt_first_idempotent_and_refuses_changed_remainder(
    tmp_path: Path,
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    written = _run_writer(repo, source, digest)
    assert written.returncode == 0, written.stderr
    anchor = Path(json.loads(written.stdout)["manifest_path"])
    resolved = _run_resolver(repo, anchor, digest, task_state="ABSENT")
    assert resolved.returncode == 0, resolved.stderr
    resolution = anchor.with_name(anchor.name.replace(".manifest.json", ".resolution.json"))
    resolution_sha256 = _sha256(resolution)
    anchor_bytes = anchor.read_bytes()

    compacted = _run_compactor(repo, anchor, digest, resolution_sha256)
    assert compacted.returncode == 0, compacted.stderr
    receipt = Path(json.loads(compacted.stdout)["compaction_receipt_path"])
    assert receipt.is_file()
    assert not anchor.exists()
    assert not resolution.exists()

    repeated = _run_compactor(repo, anchor, digest, resolution_sha256)
    assert repeated.returncode == 0, repeated.stderr

    # Simulate a receipt-first crash followed by replacement/corruption of the
    # surviving source. Retry must preserve and report it, never launder it.
    anchor.write_bytes(anchor_bytes + b"corrupt")
    refused = _run_compactor(repo, anchor, digest, resolution_sha256)
    assert refused.returncode != 0
    assert anchor.exists()


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_compaction_retry_rejects_malformed_terminal_receipt(tmp_path: Path) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    written = _run_writer(repo, source, digest)
    anchor = Path(json.loads(written.stdout)["manifest_path"])
    resolved = _run_resolver(repo, anchor, digest, task_state="ABSENT")
    assert resolved.returncode == 0, resolved.stderr
    resolution = anchor.with_name(anchor.name.replace(".manifest.json", ".resolution.json"))
    resolution_sha256 = _sha256(resolution)
    compacted = _run_compactor(repo, anchor, digest, resolution_sha256)
    assert compacted.returncode == 0, compacted.stderr
    receipt = Path(json.loads(compacted.stdout)["compaction_receipt_path"])
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["task_terminal_proof"]["cannot_execute"] = "false"
    receipt.write_text(json.dumps(payload), encoding="utf-8")

    refused = _run_compactor(repo, anchor, digest, resolution_sha256)
    assert refused.returncode != 0


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_predecessor_can_compact_after_exact_successor_is_compacted(
    tmp_path: Path,
) -> None:
    repo, source, digest = _copy_registry_repo(tmp_path)
    first = _run_writer(repo, source, digest)
    predecessor = Path(json.loads(first.stdout)["manifest_path"])
    successor_payload = json.loads(source.read_text(encoding="utf-8"))
    successor_payload["principal"]["user_id"] = "weather-operator-v2"
    successor_source = tmp_path / "successor.json"
    successor_source.write_text(json.dumps(successor_payload), encoding="utf-8")
    successor_sha = _sha256(successor_source)
    superseded = _run_resolver(
        repo,
        predecessor,
        digest,
        task_state="ABSENT",
        status="SUPERSEDED",
        successor_source=successor_source,
        successor_sha256=successor_sha,
    )
    assert superseded.returncode == 0, superseded.stderr
    successor = Path(json.loads(superseded.stdout)["successor_manifest_path"])
    successor_resolved = _run_resolver(
        repo, successor, successor_sha, task_state="ABSENT"
    )
    assert successor_resolved.returncode == 0, successor_resolved.stderr
    successor_resolution = successor.with_name(
        successor.name.replace(".manifest.json", ".resolution.json")
    )
    compact_successor = _run_compactor(
        repo, successor, successor_sha, _sha256(successor_resolution)
    )
    assert compact_successor.returncode == 0, compact_successor.stderr

    predecessor_resolution = predecessor.with_name(
        predecessor.name.replace(".manifest.json", ".resolution.json")
    )
    compact_predecessor = _run_compactor(
        repo, predecessor, digest, _sha256(predecessor_resolution)
    )
    assert compact_predecessor.returncode == 0, compact_predecessor.stderr


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell contract",
)
def test_cross_session_registry_lock_allows_only_one_different_hash(
    tmp_path: Path,
) -> None:
    repo, bootstrap, _ = _copy_registry_repo(tmp_path)
    bootstrap_payload = json.loads(bootstrap.read_text(encoding="utf-8"))
    bootstrap_payload["task"]["task_name"] = "WeatherRegistryBootstrap"
    bootstrap.write_text(json.dumps(bootstrap_payload), encoding="utf-8")
    bootstrap_hash = _sha256(bootstrap)
    activated = _run_writer(repo, bootstrap, bootstrap_hash)
    assert activated.returncode == 0, activated.stderr

    first_payload = json.loads(bootstrap.read_text(encoding="utf-8"))
    first_payload["task"]["task_name"] = "WeatherConcurrentOneShot"
    first = tmp_path / "concurrent-a.json"
    first.write_text(json.dumps(first_payload), encoding="utf-8")
    second_payload = json.loads(first.read_text(encoding="utf-8"))
    second_payload["principal"]["user_id"] = "weather-operator-concurrent-b"
    second = tmp_path / "concurrent-b.json"
    second.write_text(json.dumps(second_payload), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_run_writer, repo, candidate, _sha256(candidate))
            for candidate in (first, second)
        ]
        results = [future.result() for future in futures]

    assert sum(result.returncode == 0 for result in results) == 1
    anchors = list(
        (repo / "data" / "one_shot_readiness" / "active").glob(
            "WeatherConcurrentOneShot.*.manifest.json"
        )
    )
    assert len(anchors) == 1
