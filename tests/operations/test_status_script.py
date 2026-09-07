import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "status.ps1"
REPO_ROOT = SCRIPT.parents[2]
GIT = shutil.which("git.exe") or shutil.which("git")
WINDOWS_POWERSHELL_REQUIRED = pytest.mark.skipif(
    os.name != "nt" or GIT is None,
    reason="requires Windows PowerShell and Git",
)
CONFIG_PATHS = (
    "config/locations.json",
    "config/location_market_events.json",
)
LOCAL_BASELINE = "3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac"
PUBLISHED_TARGET = "c932b54f8747df5cdefc4cc42f8454b6797f09ae"
REVIEWED_PARENT = "a24cf0f41bf0b321c5c813820594c56198a58d1a"
SAFETY_DEPENDENCY_PATHS = (
    "scripts/ops/quiet_window_merge.ps1",
    "scripts/ops/production_baseline_scheduler_rpc.ps1",
    "scripts/ops/windows_kill_on_close_job.ps1",
    "scripts/ops/status.ps1",
    "scripts/ops/health_watchdog.ps1",
)
LOCAL_BASELINE_DEPENDENCY_SHA256 = {
    "scripts/ops/boot_recovery.ps1": (
        "253ab48e38a24af8cf8c8a5fde33f223b6e298b7acf91bbc56ad4c4a0ea8dc4a"
    ),
    "scripts/ops/roll_verdict.ps1": (
        "3fb522a82c5325558a9da9d458c643edf5c0da8d5893e14189979859ed0a4881"
    ),
    "scripts/ops/workload_admission.ps1": (
        "cdeaab38b2b9483cff5936e52411d725b0cffe4373ccebba688797c6e1d3c105"
    ),
    "src/weather/operations/capture_recovery_check.py": (
        "814ec274838e5cb905a0074298f5c4e27aee2d32b0b9cc6fac2ca4def27cc895"
    ),
    "src/weather/operations/documentation_transaction.py": (
        "057def07c4ad8529457a11bba6b1f5afdb19b6f6011ff3dd77905af29bd354d9"
    ),
    "src/weather/operations/execution_tape_supervisor.py": (
        "1f5d8e1130fa2dd4c14d8f8f9dd6c44d9a7c4850f85a5942919d5c6bbfc5763f"
    ),
}
PUBLISHED_TARGET_DEPENDENCY_SHA256 = {
    **LOCAL_BASELINE_DEPENDENCY_SHA256,
    "scripts/ops/workload_admission.ps1": (
        "4117eb901d292952473c57425434593bed414fa2ed2fecee301fe56e8f893306"
    ),
}


def test_status_paths_are_derived_from_the_invoked_checkout_and_user_profile() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert (
        "$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)"
        in text
    )
    assert "$repo = [IO.Path]::GetFullPath($RepoRoot)" in text
    assert 'Join-Path $env:USERPROFILE "ops\\mirror_status.json"' in text
    assert "C:\\Users\\micha" not in text


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.parametrize("explicit_root", [False, True])
def test_status_native_file_startup_resolves_the_selected_checkout(
    tmp_path: Path, explicit_root: bool
) -> None:
    checkout = tmp_path / "checkout with spaces"
    script = checkout / "scripts" / "ops" / "status.ps1"
    script.parent.mkdir(parents=True)
    startup = SCRIPT.read_text(encoding="utf-8-sig").split(
        "function Get-WeatherIntegrationValidatedEvidence", 1
    )[0]
    script.write_text(
        startup + "[pscustomobject]@{repo = $repo} | ConvertTo-Json -Compress\n",
        encoding="utf-8",
    )
    selected_root = tmp_path / "explicit checkout" if explicit_root else checkout
    selected_root.mkdir(exist_ok=True)
    command = [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(script), "-Json"
    ]
    if explicit_root:
        command.extend(["-RepoRoot", str(selected_root)])
    result = subprocess.run(
        command, cwd=tmp_path, capture_output=True, text=True, check=False, timeout=30
    )
    assert result.returncode == 0, result.stderr
    assert Path(json.loads(result.stdout)["repo"]) == selected_root


def test_unpushed_guidance_has_one_affirmative_push_path() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "function Get-WeatherReconciliationPublicationState" in text
    assert "function Get-WeatherUnpushedPublicationGuidance" in text
    assert text.count("unpushed (run WeatherOneShotPush)") == 1
    assert "RECONCILIATION_PUBLICATION_GUARDED_PRE_DISPATCH" in text
    assert "RECONCILIATION_PUBLICATION_ATTEMPTED_UNACKNOWLEDGED" in text
    assert "RECONCILIATION_PUBLICATION_EVIDENCE_INVALID" in text
    assert "manual WeatherOneShotPush invocation is forbidden" in text
    assert "WeatherOneShotPush retry is forbidden" in text
    assert "RECONCILIATION_PUBLICATION_RELATED_TASK_STATE" in text
    assert "No task/integration compatibility branch may turn" in text
    assert '-CanonicalOrigin "https://github.com/michaelbooth1/weather.git"' in text
    assert "origin fetch/push identity is not the exact canonical no-rewrite contract" in text
    assert "readable roll-verdict payload is not the writer-validated L-to-S result" in text
    assert "documentation transaction snapshot does not exactly bind M/S" in text
    assert "reconciliation dependency maps do not have the exact writer key sets" in text
    assert "StatusStrictJsonObjectKeyValidator" in text
    assert "StringComparer.OrdinalIgnoreCase" in text
    assert text.count("ConvertFrom-StrictReconciliationJson") == 5
    assert "$Label JSON is invalid or contains duplicate/case-colliding object keys" in text
    for strict_label in (
        "active quiet-window marker",
        "reconciliation snapshot manifest",
        "reconciliation roll-verdict snapshot",
        "reconciliation documentation transaction snapshot",
    ):
        assert f'-Label "{strict_label}"' in text
    assert "ordinary operation mode cannot downgrade populated reconciliation incident evidence" in text
    assert "old report cannot poison an unrelated later commit" in text
    assert '"${unpushedBase}..master"' in text
    assert "live_origin_master = [string]$reconciliationPublication.live_origin_master" in text
    assert (
        '$ordinaryReport = [string]$qw.operation_mode -cne\n'
        '            "production_baseline_reconciliation_v0.1"'
    ) in text
    assert (
        '[string]$reconciliationPublication.classification -ceq "ordinary"'
        in text
    )
    assert "-PublicationClassification ([string]$reconciliationPublication.classification)" in text
    assert (
        "obtain review, run WeatherOneShotPush, then reconcile the immutable attempt "
        "evidence"
    ) in text


def test_live_origin_timeout_never_uses_an_unbounded_post_kill_wait() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")
    start = text.index("function Get-StatusLiveOriginMaster")
    end = text.index("function Test-ExactConfigPathSet", start)
    live_origin = text[start:end]

    assert "$process.WaitForExit()" not in live_origin
    assert live_origin.count("$process.WaitForExit(5000)") == 2
    assert "$process.WaitForExit(1000)" in live_origin
    assert "root termination was not observed" in live_origin


def _git(repo: Path, *args: str) -> str:
    assert GIT is not None
    result = subprocess.run(
        [GIT, *args],
        cwd=repo,
        env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"},
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed with {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout.strip().lower()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "--all")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "head")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _replace_json_text_once(path: Path, needle: str, replacement: str) -> bytes:
    raw = path.read_text(encoding="utf-8")
    assert raw.count(needle) == 1, needle
    mutated = raw.replace(needle, replacement, 1).encode("utf-8")
    path.write_bytes(mutated)
    return mutated


def _build_reconciliation_status_fixture(
    tmp_path: Path, *, safety_base: str = REVIEWED_PARENT
) -> dict[str, object]:
    repo = tmp_path / "repo"
    assert GIT is not None
    clone = subprocess.run(
        [
            GIT,
            "clone",
            "--quiet",
            "--no-checkout",
            "--shared",
            str(REPO_ROOT),
            str(repo),
        ],
        cwd=tmp_path,
        env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"},
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert clone.returncode == 0, clone.stderr
    _git(repo, "config", "user.name", "Status Test")
    _git(repo, "config", "user.email", "status-test@invalid.local")
    local_baseline = _git(repo, "rev-parse", f"{LOCAL_BASELINE}^{{commit}}")
    published_target = _git(repo, "rev-parse", f"{PUBLISHED_TARGET}^{{commit}}")
    reviewed_parent = _git(repo, "rev-parse", f"{REVIEWED_PARENT}^{{commit}}")
    assert local_baseline == LOCAL_BASELINE
    assert published_target == PUBLISHED_TARGET
    assert reviewed_parent == REVIEWED_PARENT

    bare_origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", str(bare_origin))
    _git(repo, "remote", "set-url", "origin", str(bare_origin))
    _git(repo, "push", "origin", f"{published_target}:refs/heads/master")
    _git(repo, "update-ref", "refs/remotes/origin/master", published_target)

    _git(repo, "checkout", "--detach", safety_base)
    for relative in SAFETY_DEPENDENCY_PATHS:
        source = REPO_ROOT / relative
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    safety_tip = _commit(repo, "S")
    source_tree = _git(repo, "rev-parse", f"{safety_tip}^{{tree}}")

    _git(repo, "checkout", "-b", "config-child", local_baseline)
    for relative in CONFIG_PATHS:
        (repo / relative).write_text(
            f"production generated {relative}\n", encoding="utf-8"
        )
    config_commit = _commit(repo, "C")
    _git(repo, "merge", "--no-ff", "--no-edit", safety_tip)
    merge_commit = _git(repo, "rev-parse", "head")
    _git(repo, "checkout", "-B", "master", merge_commit)
    _git(repo, "update-ref", "refs/remotes/origin/master", published_target)

    snapshot_root = (
        repo
        / "data"
        / "alerts"
        / "production_baseline_reconciliation"
        / ("20260901T012500000-" + "a" * 32)
    )
    snapshot_entries: dict[str, dict[str, object]] = {}
    config_hashes: dict[str, str] = {}
    for relative in CONFIG_PATHS:
        live = repo / relative
        snapshot = snapshot_root / "raw" / relative
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes(live.read_bytes())
        digest = hashlib.sha256(live.read_bytes()).hexdigest()
        config_hashes[relative] = digest
        snapshot_entries[relative] = {
            "snapshot_path": snapshot.relative_to(repo).as_posix(),
            "sha256": digest,
            "length": live.stat().st_size,
        }
    roll_transcript_path = snapshot_root / "roll-verdict-output.txt"
    roll_transcript_path.write_text("bounded roll verdict fixture\n", encoding="utf-8")
    roll_transcript_sha = hashlib.sha256(roll_transcript_path.read_bytes()).hexdigest()
    roll_json_path = snapshot_root / "roll-verdict.json"
    _write_json(
        roll_json_path,
        {
            "generated_at": "2026-09-01T01:24:30-04:00",
            "branch": safety_tip,
            "verdict": "ROLL-FREE",
            "base_ref": local_baseline,
            "base_sha": _git(repo, "rev-parse", "--short", local_baseline),
            "base_note": None,
            "closures_used": ["snapshot"],
            "problems": [],
            "files": [],
        },
    )
    roll_json_sha = hashlib.sha256(roll_json_path.read_bytes()).hexdigest()
    safety_dependency_hashes = {
        f"{relative}@safety_tip": hashlib.sha256(
            (repo / relative).read_bytes()
        ).hexdigest()
        for relative in SAFETY_DEPENDENCY_PATHS
    }
    manifest_dependency_hashes = {
        **{
            f"{relative}@local_baseline": digest
            for relative, digest in LOCAL_BASELINE_DEPENDENCY_SHA256.items()
        },
        **safety_dependency_hashes,
    }
    marker_dependency_hashes = {
        **manifest_dependency_hashes,
        **{
            f"{relative}@published_target": digest
            for relative, digest in PUBLISHED_TARGET_DEPENDENCY_SHA256.items()
        },
        **{
            f"{relative}@published_target": safety_dependency_hashes[
                f"{relative}@safety_tip"
            ]
            for relative in SAFETY_DEPENDENCY_PATHS
        },
    }
    entry_sha = safety_dependency_hashes[
        "scripts/ops/quiet_window_merge.ps1@safety_tip"
    ]
    manifest = {
        "schema": "production_baseline_reconciliation_snapshot_v0.1",
        "created_at": "2026-09-01T01:25:00-04:00",
        "local_baseline": local_baseline,
        "published_target": published_target,
        "source_tip": safety_tip,
        "source_tree": source_tree,
        "safety_tip": safety_tip,
        "safety_tree": source_tree,
        "entry_sha256": entry_sha,
        "config": snapshot_entries,
        "reconciliation_config_content_sha256": config_hashes,
        "roll_verdict": {
            "explicit_base": local_baseline,
            "explicit_branch": safety_tip,
            "exit_code": 0,
            "readable": True,
            "json_path": roll_json_path.relative_to(repo).as_posix(),
            "json_sha256": roll_json_sha,
            "transcript_path": roll_transcript_path.relative_to(repo).as_posix(),
            "transcript_sha256": roll_transcript_sha,
        },
        "dependency_sha256": manifest_dependency_hashes,
    }
    manifest_path = snapshot_root / "manifest.json"
    _write_json(manifest_path, manifest)
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    pending_bytes = json.dumps(
        {
            "schema_version": "documentation_transaction_pending_v0.1",
            "status": "PENDING",
            "created_at_local": "2026-09-01T01:29:15-04:00",
            "due_at_local": "2026-09-01T09:00:00-04:00",
            "integrations": [
                {
                    "integration_tip": merge_commit,
                    "branch": safety_tip,
                    "expected_tip": safety_tip,
                    # A coarse clock can record documentation and the marker
                    # at the same instant after staged recovery.
                    "recorded_at_local": "2026-09-01T01:30:00-04:00",
                }
            ],
            "latest_integration_tip": merge_commit,
        },
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    pending_sha = hashlib.sha256(pending_bytes).hexdigest()
    pending_path = (
        repo
        / "data"
        / "alerts"
        / "documentation_transactions"
        / f"pending-{pending_sha}.json"
    )
    pending_path.parent.mkdir(parents=True, exist_ok=True)
    pending_path.write_bytes(pending_bytes)
    marker: dict[str, object] = {
        "schema": "quiet_window_merge_in_progress_v0.1",
        "updated_at": "2026-09-01T01:30:00-04:00",
        "repo_root": str(repo.resolve()),
        "phase": "documented_unpublished",
        "operation_mode": "production_baseline_reconciliation_v0.1",
        "branch": safety_tip,
        "expected_tip": safety_tip,
        "expected_baseline": local_baseline,
        "resolved_branch_tip": safety_tip,
        "baseline_commit": local_baseline,
        "pre_merge_commit": config_commit,
        "reconciliation_actual_pre_merge_commit": config_commit,
        "reconciliation_boot_guard_commit": published_target,
        "reconciliation_local_baseline": local_baseline,
        "reconciliation_published_target": published_target,
        "reconciliation_source_tip": safety_tip,
        "reconciliation_safety_tip": safety_tip,
        "reconciliation_source_tree": source_tree,
        "reconciliation_safety_tree": source_tree,
        "reconciliation_entry_sha256": entry_sha,
        "reconciliation_snapshot_manifest_path": manifest_path.relative_to(
            repo
        ).as_posix(),
        "reconciliation_snapshot_manifest_sha256": manifest_sha,
        "reconciliation_snapshot_paths": snapshot_entries,
        "reconciliation_dependency_sha256": marker_dependency_hashes,
        "roll_verdict_exit_code": 0,
        "roll_verdict_explicit_base": local_baseline,
        "roll_verdict_explicit_branch": safety_tip,
        "roll_verdict_json_sha256": roll_json_sha,
        "roll_verdict_transcript_sha256": roll_transcript_sha,
        "merge_commit": merge_commit,
        "capture_recovery_proved": True,
        "reconciliation_staged_safety_capture_recovery_proved": True,
        "reconciliation_staged_safety_capture_recovery_at": (
            "2026-09-01T01:29:00-04:00"
        ),
        "reconciliation_pre_push_capture_recovery_proved": False,
        "reconciliation_pre_push_capture_recovery_at": None,
        "execution_tape_recovery_required": False,
        "execution_tape_readoption_expected": False,
        "execution_tape_rolled_but_inactive_skipped": False,
        "execution_tape_recovery_proved": False,
        "execution_tape_source_before": None,
        "documentation_transaction_recorded": True,
        "documentation_transaction_pending_sha256": pending_sha,
        "documentation_transaction_snapshot_path": (
            f"data/alerts/documentation_transactions/pending-{pending_sha}.json"
        ),
        "push_invocation_attempted": False,
        "push_pre_last_run_time": None,
        "push_observed_last_run_time": None,
        "push_last_task_result": None,
        "push_runtime_state": None,
        "push_terminal_proved": False,
        "push_run_observed": False,
        "push_stop_attempted": False,
        "push_stop_count": 0,
        "push_stop_exhausted": False,
        "push_start_issued_at": None,
        "push_containment_deadline": None,
        "push_terminal_proved_at": None,
        "push_containment_breached": False,
        "push_start_rpc_request_id": None,
        "push_start_rpc_request_sha256": None,
        "push_start_rpc_deadline_utc": None,
        "push_start_rpc_timed_out": False,
        "push_stop_rpc_request_id": None,
        "push_stop_rpc_request_sha256": None,
        "push_stop_rpc_deadline_utc": None,
        "push_stop_rpc_timed_out": False,
        "publication_acknowledged": False,
        "auto_refreshed_paths": list(CONFIG_PATHS),
        "auto_refreshed_sha256": config_hashes,
        "reconciliation_config_content_sha256": config_hashes,
    }
    marker_path = repo / "data" / "alerts" / "quiet_window_merge_in_progress.json"
    _write_json(marker_path, marker)
    return {
        "repo": repo,
        "marker": marker,
        "marker_path": marker_path,
        "bare_origin": bare_origin,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "roll_json_path": roll_json_path,
        "pending_path": pending_path,
        "local_baseline": local_baseline,
        "published_target": published_target,
        "safety_tip": safety_tip,
        "config_commit": config_commit,
        "merge_commit": merge_commit,
    }


def _publication_state(
    fixture: dict[str, object], *, unpushed_count: int | None = 1,
    marker_lookup_fault: bool = False,
) -> dict[str, object]:
    env = {
        **os.environ,
        "WEATHER_STATUS_SCRIPT": str(SCRIPT),
        "WEATHER_REPO": str(fixture["repo"]),
        "WEATHER_MARKER": str(fixture["marker_path"]),
        "WEATHER_CANONICAL_ORIGIN": str(fixture["bare_origin"]),
        "WEATHER_UNPUSHED_COUNT": (
            "__auto__" if unpushed_count is None else str(unpushed_count)
        ),
        "WEATHER_MARKER_LOOKUP_FAULT": "1" if marker_lookup_fault else "0",
    }
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_STATUS_SCRIPT,
    [ref]$tokens,
    [ref]$errors
)
if (@($errors).Count -ne 0) { throw 'status script did not parse' }
foreach ($name in @(
    'Get-WeatherReconciliationPublicationState',
    'Get-WeatherUnpushedPublicationGuidance',
    'Get-WeatherUnpushedPublicationSummary'
)) {
    $functionAst = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)) | Select-Object -First 1
    if ($null -eq $functionAst) { throw "missing function $name" }
    Invoke-Expression $functionAst.Extent.Text
}
if ($env:WEATHER_MARKER_LOOKUP_FAULT -ceq '1') {
    function global:Get-Item {
        param([string]$LiteralPath, [switch]$Force, $ErrorAction)
        if ($LiteralPath -ceq $env:WEATHER_MARKER) {
            throw [System.UnauthorizedAccessException]::new(
                'injected active-marker lookup denial'
            )
        }
        Microsoft.PowerShell.Management\Get-Item `
            -LiteralPath $LiteralPath -Force:$Force -ErrorAction $ErrorAction
    }
}
$state = Get-WeatherReconciliationPublicationState `
    -RepositoryRoot $env:WEATHER_REPO `
    -ActiveMarkerPath $env:WEATHER_MARKER `
    -CanonicalOrigin $env:WEATHER_CANONICAL_ORIGIN `
    -Now ([datetimeoffset]'2026-09-01T01:45:00-04:00')
$summary = if ($env:WEATHER_UNPUSHED_COUNT -ceq '__auto__') {
    Get-WeatherUnpushedPublicationSummary `
        -RepositoryRoot $env:WEATHER_REPO -PublicationState $state
}
else {
    [pscustomobject]@{
        count = [int]$env:WEATHER_UNPUSHED_COUNT
        display = [string]$env:WEATHER_UNPUSHED_COUNT
        readable = $true
        base = 'injected'
    }
}
$guidance = Get-WeatherUnpushedPublicationGuidance `
    -UnpushedCount ([int]$summary.count) `
    -PublicationState $state
[pscustomobject]@{
    classification = [string]$state.classification
    detail = [string]$state.detail
    merge_commit = [string]$state.merge_commit
    attempted = [bool]$state.push_invocation_attempted
    acknowledged = [bool]$state.publication_acknowledged
    manual_push_allowed = [bool]$state.manual_push_allowed
    live_origin_master = [string]$state.live_origin_master
    unpushed_base = [string]$summary.base
    unpushed_display = [string]$summary.display
    warning = [string]$guidance.warning
    flag = [string]$guidance.flag
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _make_published_marker(marker: dict[str, object]) -> None:
    marker.update(
        {
            "updated_at": "2026-09-01T01:41:00-04:00",
            "phase": "published",
            "push_invocation_attempted": True,
            "publication_acknowledged": True,
            "reconciliation_pre_push_capture_recovery_proved": True,
            "reconciliation_pre_push_capture_recovery_at": (
                "2026-09-01T01:30:30-04:00"
            ),
            "push_pre_last_run_time": "2026-09-01T01:00:00-04:00",
            "push_observed_last_run_time": "2026-09-01T01:36:00-04:00",
            "push_last_task_result": 0,
            "push_runtime_state": "Ready",
            "push_terminal_proved": True,
            "push_run_observed": True,
            "push_start_issued_at": "2026-09-01T01:31:00-04:00",
            "push_containment_deadline": "2026-09-01T01:46:00-04:00",
            "push_terminal_proved_at": "2026-09-01T01:40:00-04:00",
            "push_start_rpc_request_id": "a" * 32,
            "push_start_rpc_request_sha256": "b" * 64,
            "push_start_rpc_deadline_utc": "2026-09-01T05:31:20Z",
            "push_start_rpc_timed_out": False,
        }
    )


@WINDOWS_POWERSHELL_REQUIRED
def test_valid_reconciliation_marker_has_three_distinct_publication_states(
    tmp_path: Path,
) -> None:
    fixture = _build_reconciliation_status_fixture(tmp_path)
    marker_path = fixture["marker_path"]
    assert isinstance(marker_path, Path)
    marker = copy.deepcopy(fixture["marker"])

    pre_dispatch = _publication_state(fixture)
    assert pre_dispatch["classification"] == "guarded_pre_dispatch"
    assert pre_dispatch["warning"] == "1 commit(s) unpushed"
    assert "owns publication" in pre_dispatch["flag"]
    assert "manual WeatherOneShotPush invocation is forbidden" in pre_dispatch["flag"]
    assert pre_dispatch["manual_push_allowed"] is False

    marker["reconciliation_staged_safety_capture_recovery_at"] = marker["updated_at"]
    _write_json(marker_path, marker)
    equal_timestamp = _publication_state(fixture)
    assert equal_timestamp["classification"] == "guarded_pre_dispatch", equal_timestamp

    marker = copy.deepcopy(fixture["marker"])
    marker.update(
        {
            "phase": "merge_committed_unpublished",
            "documentation_transaction_recorded": False,
            "documentation_transaction_pending_sha256": None,
            "documentation_transaction_snapshot_path": None,
        }
    )
    _write_json(marker_path, marker)
    merge_committed = _publication_state(fixture)
    assert merge_committed["classification"] == "guarded_pre_dispatch"

    marker = copy.deepcopy(fixture["marker"])

    marker["push_invocation_attempted"] = True
    marker["push_pre_last_run_time"] = "2026-09-01T01:00:00-04:00"
    _write_json(marker_path, marker)
    attempted = _publication_state(fixture)
    assert attempted["classification"] == "attempted_unacknowledged"
    assert attempted["warning"] == "1 commit(s) unpushed"
    assert "pending or uncertain" in attempted["flag"]
    assert "retry is forbidden" in attempted["flag"]

    marker.update(
        {
            "updated_at": "2026-09-01T01:31:10-04:00",
            "reconciliation_pre_push_capture_recovery_proved": True,
            "reconciliation_pre_push_capture_recovery_at": (
                "2026-09-01T01:30:30-04:00"
            ),
            "push_start_issued_at": "2026-09-01T01:31:00-04:00",
            "push_containment_deadline": "2026-09-01T01:46:00-04:00",
            "push_start_rpc_request_id": "a" * 32,
            "push_start_rpc_deadline_utc": "2026-09-01T05:31:20Z",
        }
    )
    _write_json(marker_path, marker)
    start_pre_call = _publication_state(fixture)
    assert start_pre_call["classification"] == "attempted_unacknowledged"
    assert "retry is forbidden" in start_pre_call["flag"]

    marker.update(
        {
            "updated_at": "2026-09-01T01:32:00-04:00",
            "push_start_rpc_request_sha256": "b" * 64,
            "push_start_rpc_timed_out": True,
        }
    )
    _write_json(marker_path, marker)
    timed_out = _publication_state(fixture)
    assert timed_out["classification"] == "attempted_unacknowledged"
    assert "pending or uncertain" in timed_out["flag"]
    assert "retry is forbidden" in timed_out["flag"]

    repo = fixture["repo"]
    assert isinstance(repo, Path)
    merge_commit = str(fixture["merge_commit"])
    _git(repo, "push", "origin", f"{merge_commit}:refs/heads/master")
    _git(repo, "update-ref", "refs/remotes/origin/master", merge_commit)
    remote_m_before_ack = _publication_state(fixture, unpushed_count=0)
    assert remote_m_before_ack["classification"] == "attempted_unacknowledged"
    assert "retry is forbidden" in remote_m_before_ack["flag"]
    _make_published_marker(marker)
    _write_json(marker_path, marker)
    acknowledged = _publication_state(fixture, unpushed_count=0)
    assert acknowledged["classification"] == "acknowledged"
    assert acknowledged["warning"] == ""
    assert acknowledged["flag"] == ""
    assert acknowledged["acknowledged"] is True
    assert acknowledged["manual_push_allowed"] is False


@WINDOWS_POWERSHELL_REQUIRED
def test_operation_mode_only_cannot_downgrade_reconciliation_authority(
    tmp_path: Path,
) -> None:
    fixture = _build_reconciliation_status_fixture(tmp_path)
    marker_path = fixture["marker_path"]
    assert isinstance(marker_path, Path)
    marker = copy.deepcopy(fixture["marker"])

    # This is the exact reviewed marker with one changed field. Status must not
    # let an attacker regain ordinary manual-push guidance by relabeling it.
    marker["operation_mode"] = "ordinary_synchronized_merge_v0.1"
    _write_json(marker_path, marker)

    state = _publication_state(fixture)
    assert state["classification"] == "incident_evidence_invalid"
    assert "cannot downgrade populated reconciliation incident evidence" in state[
        "detail"
    ]
    assert "reconciliation_actual_pre_merge_commit" in state["detail"]
    assert state["warning"] == "1 commit(s) unpushed"
    assert "EVIDENCE_INVALID" in state["flag"]
    assert state["manual_push_allowed"] is False


@WINDOWS_POWERSHELL_REQUIRED
def test_active_marker_lookup_error_is_invalid_not_ordinary(
    tmp_path: Path,
) -> None:
    fixture = _build_reconciliation_status_fixture(tmp_path)

    state = _publication_state(fixture, marker_lookup_fault=True)

    assert state["classification"] == "incident_evidence_invalid"
    assert "injected active-marker lookup denial" in state["detail"]
    assert state["warning"] == "1 commit(s) unpushed"
    assert "EVIDENCE_INVALID" in state["flag"]
    assert "WeatherOneShotPush invocation is forbidden" in state["flag"]
    assert "(run WeatherOneShotPush)" not in state["warning"]
    assert state["manual_push_allowed"] is False


@WINDOWS_POWERSHELL_REQUIRED
def test_genuine_ordinary_writer_shape_remains_ordinary(tmp_path: Path) -> None:
    fixture = _build_reconciliation_status_fixture(tmp_path)
    marker_path = fixture["marker_path"]
    assert isinstance(marker_path, Path)
    marker = copy.deepcopy(fixture["marker"])
    marker["operation_mode"] = "ordinary_synchronized_merge_v0.1"

    # The additive writer emits reconciliation_* compatibility slots for both
    # modes. Genuine ordinary slots are null/false/empty; the config hash alias
    # is intentionally populated and therefore cannot itself identify the
    # one-time incident.
    for name, value in list(marker.items()):
        if name.startswith("reconciliation_") and name != (
            "reconciliation_config_content_sha256"
        ):
            if isinstance(value, dict):
                marker[name] = {}
            elif isinstance(value, bool):
                marker[name] = False
            else:
                marker[name] = None
    for name in (
        "roll_verdict_exit_code",
        "roll_verdict_explicit_base",
        "roll_verdict_explicit_branch",
        "roll_verdict_json_sha256",
        "roll_verdict_transcript_sha256",
        "push_start_rpc_request_id",
        "push_start_rpc_request_sha256",
        "push_start_rpc_deadline_utc",
        "push_stop_rpc_request_id",
        "push_stop_rpc_request_sha256",
        "push_stop_rpc_deadline_utc",
        "push_containment_deadline",
        "push_terminal_proved_at",
    ):
        marker[name] = None
    for name in (
        "push_start_rpc_timed_out",
        "push_stop_rpc_timed_out",
        "push_containment_breached",
        "push_terminal_proved",
        "push_run_observed",
        "push_stop_attempted",
        "push_stop_exhausted",
    ):
        marker[name] = False
    _write_json(marker_path, marker)

    state = _publication_state(fixture)
    assert state["classification"] == "ordinary"
    assert state["warning"] == "1 commit(s) unpushed (run WeatherOneShotPush)"
    assert state["flag"] == ""
    assert state["manual_push_allowed"] is True


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.parametrize(
    "case",
    [
        "active_marker_case_collision",
        "manifest_duplicate_nested_key",
        "roll_case_collision_nested_key",
        "documentation_duplicate_nested_key",
    ],
)
def test_reconciliation_json_rejects_duplicate_and_case_colliding_keys(
    tmp_path: Path,
    case: str,
) -> None:
    fixture = _build_reconciliation_status_fixture(tmp_path)
    marker_path = fixture["marker_path"]
    manifest_path = fixture["manifest_path"]
    roll_json_path = fixture["roll_json_path"]
    pending_path = fixture["pending_path"]
    assert isinstance(marker_path, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(roll_json_path, Path)
    assert isinstance(pending_path, Path)
    marker = copy.deepcopy(fixture["marker"])

    if case == "active_marker_case_collision":
        needle = (
            '  "operation_mode": '
            '"production_baseline_reconciliation_v0.1",'
        )
        _replace_json_text_once(
            marker_path,
            needle,
            needle
            + '\n  "Operation_Mode": "ordinary_synchronized_merge_v0.1",',
        )
    elif case == "manifest_duplicate_nested_key":
        needle = f'    "explicit_base": "{fixture["local_baseline"]}",'
        manifest_bytes = _replace_json_text_once(
            manifest_path, needle, needle + "\n" + needle
        )
        marker["reconciliation_snapshot_manifest_sha256"] = hashlib.sha256(
            manifest_bytes
        ).hexdigest()
        _write_json(marker_path, marker)
    elif case == "roll_case_collision_nested_key":
        roll_bytes = _replace_json_text_once(
            roll_json_path,
            '  "files": [],',
            '  "files": [],\n  "adversarial": {"Key": 1, "key": 2},',
        )
        roll_sha = hashlib.sha256(roll_bytes).hexdigest()
        manifest = copy.deepcopy(fixture["manifest"])
        manifest["roll_verdict"]["json_sha256"] = roll_sha
        _write_json(manifest_path, manifest)
        marker["roll_verdict_json_sha256"] = roll_sha
        marker["reconciliation_snapshot_manifest_sha256"] = hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest()
        _write_json(marker_path, marker)
    elif case == "documentation_duplicate_nested_key":
        needle = f'      "branch": "{fixture["safety_tip"]}",'
        pending_bytes = _replace_json_text_once(
            pending_path, needle, needle + "\n" + needle
        )
        pending_sha = hashlib.sha256(pending_bytes).hexdigest()
        new_pending_path = pending_path.with_name(f"pending-{pending_sha}.json")
        new_pending_path.write_bytes(pending_bytes)
        marker["documentation_transaction_pending_sha256"] = pending_sha
        marker["documentation_transaction_snapshot_path"] = (
            f"data/alerts/documentation_transactions/pending-{pending_sha}.json"
        )
        _write_json(marker_path, marker)
    else:  # pragma: no cover - parametrization is exhaustive
        raise AssertionError(case)

    state = _publication_state(fixture)
    assert state["classification"] == "incident_evidence_invalid"
    assert "duplicate/case-colliding object keys" in state["detail"]
    assert state["warning"] == "1 commit(s) unpushed"
    assert "EVIDENCE_INVALID" in state["flag"]
    assert state["manual_push_allowed"] is False


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.parametrize(
    "case",
    [
        "malformed",
        "wrong_merge_sha",
        "wrong_safety_sha",
        "wrong_config_hash",
        "wrong_config_hash_alias",
        "wrong_safety_tree",
        "missing_staged_recovery",
        "future_staged_recovery",
        "reversed_pre_push_recovery",
        "future_push_baseline",
        "wrong_phase",
        "stale",
        "incomplete",
        "wrong_branch",
        "unreviewed_safety_tip",
        "snapshot_aliases_live_config",
        "wrong_dependency_hash",
        "missing_dependency_stage",
        "wrong_roll_payload",
        "wrong_documentation_payload",
        "dirty_worktree",
        "noncanonical_origin_url",
        "origin_pushurl_override",
        "origin_url_rewrite",
        "wrong_origin",
        "published_without_rpc_hash",
        "published_stop_count_over_limit",
        "published_pre_last_after_start",
        "published_with_stale_origin_cache",
    ],
)
def test_invalid_reconciliation_evidence_retains_neutral_unpushed_warning(
    tmp_path: Path,
    case: str,
) -> None:
    fixture = _build_reconciliation_status_fixture(
        tmp_path,
        safety_base=(
            PUBLISHED_TARGET if case == "unreviewed_safety_tip" else REVIEWED_PARENT
        ),
    )
    marker_path = fixture["marker_path"]
    repo = fixture["repo"]
    assert isinstance(marker_path, Path)
    assert isinstance(repo, Path)
    marker = copy.deepcopy(fixture["marker"])
    if case == "malformed":
        marker_path.write_text("{", encoding="utf-8")
    elif case == "wrong_merge_sha":
        marker["merge_commit"] = "f" * 40
        _write_json(marker_path, marker)
    elif case == "wrong_safety_sha":
        marker["reconciliation_safety_tip"] = str(fixture["published_target"])
        _write_json(marker_path, marker)
    elif case == "wrong_config_hash":
        hashes = dict(marker["auto_refreshed_sha256"])
        hashes[CONFIG_PATHS[0]] = "0" * 64
        marker["auto_refreshed_sha256"] = hashes
        _write_json(marker_path, marker)
    elif case == "wrong_config_hash_alias":
        hashes = dict(marker["reconciliation_config_content_sha256"])
        hashes[CONFIG_PATHS[0]] = "0" * 64
        marker["reconciliation_config_content_sha256"] = hashes
        _write_json(marker_path, marker)
    elif case == "wrong_safety_tree":
        marker["reconciliation_safety_tree"] = "0" * 40
        _write_json(marker_path, marker)
    elif case == "missing_staged_recovery":
        marker["reconciliation_staged_safety_capture_recovery_proved"] = False
        marker["reconciliation_staged_safety_capture_recovery_at"] = None
        _write_json(marker_path, marker)
    elif case == "future_staged_recovery":
        marker["reconciliation_staged_safety_capture_recovery_at"] = (
            "2026-09-01T01:31:00-04:00"
        )
        _write_json(marker_path, marker)
    elif case == "reversed_pre_push_recovery":
        marker.update(
            {
                "push_invocation_attempted": True,
                "push_pre_last_run_time": "2026-09-01T01:00:00-04:00",
                "reconciliation_pre_push_capture_recovery_proved": True,
                "reconciliation_pre_push_capture_recovery_at": (
                    "2026-09-01T01:28:00-04:00"
                ),
                "push_start_issued_at": "2026-09-01T01:29:30-04:00",
                "push_containment_deadline": "2026-09-01T01:44:30-04:00",
            }
        )
        _write_json(marker_path, marker)
    elif case == "future_push_baseline":
        marker["push_invocation_attempted"] = True
        marker["push_pre_last_run_time"] = "2026-09-01T01:31:00-04:00"
        _write_json(marker_path, marker)
    elif case == "wrong_phase":
        marker["phase"] = "reconciliation_prepared"
        _write_json(marker_path, marker)
    elif case == "stale":
        marker["updated_at"] = "2026-08-29T01:30:00-04:00"
        _write_json(marker_path, marker)
    elif case == "incomplete":
        marker.pop("reconciliation_safety_tip")
        _write_json(marker_path, marker)
    elif case == "wrong_branch":
        marker["branch"] = str(fixture["published_target"])
        _write_json(marker_path, marker)
    elif case == "unreviewed_safety_tip":
        pass
    elif case == "snapshot_aliases_live_config":
        manifest = copy.deepcopy(fixture["manifest"])
        snapshots = copy.deepcopy(marker["reconciliation_snapshot_paths"])
        for relative in CONFIG_PATHS:
            snapshots[relative]["snapshot_path"] = relative
            manifest["config"][relative]["snapshot_path"] = relative
        marker["reconciliation_snapshot_paths"] = snapshots
        manifest_path = fixture["manifest_path"]
        assert isinstance(manifest_path, Path)
        _write_json(manifest_path, manifest)
        marker["reconciliation_snapshot_manifest_sha256"] = hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest()
        _write_json(marker_path, marker)
    elif case == "wrong_dependency_hash":
        dependencies = dict(marker["reconciliation_dependency_sha256"])
        dependencies[
            "scripts/ops/status.ps1@safety_tip"
        ] = "0" * 64
        marker["reconciliation_dependency_sha256"] = dependencies
        _write_json(marker_path, marker)
    elif case == "missing_dependency_stage":
        dependencies = dict(marker["reconciliation_dependency_sha256"])
        dependencies.pop("scripts/ops/boot_recovery.ps1@published_target")
        marker["reconciliation_dependency_sha256"] = dependencies
        _write_json(marker_path, marker)
    elif case == "wrong_roll_payload":
        roll_json_path = fixture["roll_json_path"]
        manifest_path = fixture["manifest_path"]
        assert isinstance(roll_json_path, Path)
        assert isinstance(manifest_path, Path)
        roll_payload = json.loads(roll_json_path.read_text(encoding="utf-8"))
        roll_payload["branch"] = str(fixture["published_target"])
        _write_json(roll_json_path, roll_payload)
        roll_sha = hashlib.sha256(roll_json_path.read_bytes()).hexdigest()
        manifest = copy.deepcopy(fixture["manifest"])
        manifest["roll_verdict"]["json_sha256"] = roll_sha
        _write_json(manifest_path, manifest)
        marker["roll_verdict_json_sha256"] = roll_sha
        marker["reconciliation_snapshot_manifest_sha256"] = hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest()
        _write_json(marker_path, marker)
    elif case == "wrong_documentation_payload":
        invalid_pending_bytes = json.dumps(
            {
                "schema_version": "documentation_transaction_pending_v0.1",
                "status": "PENDING",
                "created_at_local": "2026-09-01T01:29:15-04:00",
                "due_at_local": "2026-09-01T09:00:00-04:00",
                "integrations": [],
                "latest_integration_tip": str(fixture["merge_commit"]),
            },
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        invalid_pending_sha = hashlib.sha256(invalid_pending_bytes).hexdigest()
        invalid_pending_path = (
            repo
            / "data"
            / "alerts"
            / "documentation_transactions"
            / f"pending-{invalid_pending_sha}.json"
        )
        invalid_pending_path.write_bytes(invalid_pending_bytes)
        marker["documentation_transaction_pending_sha256"] = invalid_pending_sha
        marker["documentation_transaction_snapshot_path"] = (
            f"data/alerts/documentation_transactions/pending-{invalid_pending_sha}.json"
        )
        _write_json(marker_path, marker)
    elif case == "dirty_worktree":
        (repo / "unexpected-untracked.txt").write_text("dirty\n", encoding="utf-8")
    elif case == "noncanonical_origin_url":
        _git(repo, "remote", "set-url", "origin", str(tmp_path / "other.git"))
    elif case == "origin_pushurl_override":
        _git(repo, "config", "remote.origin.pushurl", str(fixture["bare_origin"]))
    elif case == "origin_url_rewrite":
        _git(
            repo,
            "config",
            "url.https://mirror.invalid/.insteadOf",
            "https://unused.invalid/",
        )
    elif case == "wrong_origin":
        bare_origin = fixture["bare_origin"]
        assert isinstance(bare_origin, Path)
        _git(
            bare_origin,
            "update-ref",
            "refs/heads/master",
            str(fixture["local_baseline"]),
        )
        _git(
            repo,
            "update-ref",
            "refs/remotes/origin/master",
            str(fixture["local_baseline"]),
        )
    elif case == "published_without_rpc_hash":
        merge_commit = str(fixture["merge_commit"])
        _git(repo, "push", "origin", f"{merge_commit}:refs/heads/master")
        _git(repo, "update-ref", "refs/remotes/origin/master", merge_commit)
        _make_published_marker(marker)
        marker["push_start_rpc_request_sha256"] = None
        _write_json(marker_path, marker)
    elif case == "published_stop_count_over_limit":
        merge_commit = str(fixture["merge_commit"])
        _git(repo, "push", "origin", f"{merge_commit}:refs/heads/master")
        _git(repo, "update-ref", "refs/remotes/origin/master", merge_commit)
        _make_published_marker(marker)
        marker.update(
            {
                "push_stop_attempted": True,
                "push_stop_count": 3,
                "push_stop_rpc_request_id": "c" * 32,
                "push_stop_rpc_request_sha256": "d" * 64,
                "push_stop_rpc_deadline_utc": "2026-09-01T05:31:30Z",
            }
        )
        _write_json(marker_path, marker)
    elif case == "published_pre_last_after_start":
        merge_commit = str(fixture["merge_commit"])
        _git(repo, "push", "origin", f"{merge_commit}:refs/heads/master")
        _git(repo, "update-ref", "refs/remotes/origin/master", merge_commit)
        _make_published_marker(marker)
        marker["push_pre_last_run_time"] = "2026-09-01T01:31:30-04:00"
        _write_json(marker_path, marker)
    elif case == "published_with_stale_origin_cache":
        merge_commit = str(fixture["merge_commit"])
        _git(repo, "update-ref", "refs/remotes/origin/master", merge_commit)
        _make_published_marker(marker)
        _write_json(marker_path, marker)
    else:  # pragma: no cover - parametrization is exhaustive
        raise AssertionError(case)

    state = _publication_state(fixture)
    assert state["classification"] == "incident_evidence_invalid"
    assert state["warning"] == "1 commit(s) unpushed"
    assert "EVIDENCE_INVALID" in state["flag"]
    assert "WeatherOneShotPush invocation is forbidden" in state["flag"]
    assert "(run WeatherOneShotPush)" not in state["warning"]
    assert state["manual_push_allowed"] is False
    if case == "published_with_stale_origin_cache":
        assert state["live_origin_master"] == str(fixture["published_target"])


@WINDOWS_POWERSHELL_REQUIRED
def test_invalid_marker_uses_cached_origin_when_live_origin_is_unfetched(
    tmp_path: Path,
) -> None:
    fixture = _build_reconciliation_status_fixture(tmp_path)
    marker_path = fixture["marker_path"]
    bare_origin = fixture["bare_origin"]
    assert isinstance(marker_path, Path)
    assert isinstance(bare_origin, Path)
    marker_path.write_text("{", encoding="utf-8")

    writer = tmp_path / "remote-writer"
    _git(tmp_path, "clone", str(bare_origin), str(writer))
    _git(writer, "config", "user.name", "Status Remote Writer")
    _git(writer, "config", "user.email", "status-remote@invalid.local")
    (writer / "remote-only.txt").write_text("unfetched\n", encoding="utf-8")
    remote_only = _commit(writer, "remote-only")
    _git(writer, "push", "origin", "master")

    state = _publication_state(fixture, unpushed_count=None)
    assert state["classification"] == "incident_evidence_invalid"
    assert state["live_origin_master"] == remote_only
    assert state["unpushed_base"] == "origin/master"
    cached_count = int(state["unpushed_display"])
    assert cached_count > 0
    assert state["warning"] == f"{cached_count} commit(s) unpushed"
    assert "EVIDENCE_INVALID" in state["flag"]
    assert "WeatherOneShotPush invocation is forbidden" in state["flag"]
    assert "(run WeatherOneShotPush)" not in state["warning"]


@WINDOWS_POWERSHELL_REQUIRED
def test_unreadable_unpushed_state_is_never_silently_coerced_to_zero(
    tmp_path: Path,
) -> None:
    fixture = _build_reconciliation_status_fixture(tmp_path)
    marker_path = fixture["marker_path"]
    repo = fixture["repo"]
    assert isinstance(marker_path, Path)
    assert isinstance(repo, Path)
    marker_path.write_text("{", encoding="utf-8")
    _git(repo, "update-ref", "-d", "refs/remotes/origin/master")

    state = _publication_state(fixture, unpushed_count=None)
    assert state["classification"] == "incident_evidence_invalid"
    assert state["unpushed_display"] == "?"
    assert state["warning"] == "unpushed commit state unreadable"
    assert "EVIDENCE_INVALID" in state["flag"]
    assert "WeatherOneShotPush invocation is forbidden" in state["flag"]
    assert "(run WeatherOneShotPush)" not in state["warning"]


@WINDOWS_POWERSHELL_REQUIRED
def test_absent_marker_and_old_special_report_do_not_poison_unrelated_commit(
    tmp_path: Path,
) -> None:
    fixture = _build_reconciliation_status_fixture(tmp_path)
    marker_path = fixture["marker_path"]
    repo = fixture["repo"]
    assert isinstance(marker_path, Path)
    assert isinstance(repo, Path)
    marker_path.unlink()
    _write_json(
        repo / "data" / "alerts" / "quiet_window_merge_last.json",
        {
            "schema": "quiet_window_merge_report_v0.2",
            "operation_mode": "production_baseline_reconciliation_v0.1",
            "stage": "pushed",
            "merge_commit": fixture["merge_commit"],
        },
    )
    (repo / "unrelated.txt").write_text("later unrelated change\n", encoding="utf-8")
    unrelated = _commit(repo, "unrelated")
    _git(repo, "checkout", "-B", "master", unrelated)
    _git(repo, "update-ref", "refs/remotes/origin/master", str(fixture["merge_commit"]))

    state = _publication_state(fixture)
    assert state["classification"] == "ordinary"
    assert state["warning"] == "1 commit(s) unpushed (run WeatherOneShotPush)"
    assert state["flag"] == ""
    assert state["manual_push_allowed"] is True


def test_rearmed_one_shot_does_not_reuse_prior_failure_as_current_flag():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '$Trigger.PSObject.Properties["CimClass"]' in text
    assert '$cimClassProperty.Value.PSObject.Properties["CimClassName"]' in text
    assert "$Trigger.CimClass.CimClassName" not in text
    assert '$Trigger.PSObject.Properties["Repetition"]' in text
    assert '$repetitionProperty.Value.PSObject.Properties["Interval"]' in text
    assert "-not $_.Repetition.Interval" not in text
    assert text.count("Test-WeatherOneShotTrigger -Trigger $_") == 2
    assert "$oneShot -and $ti.NextRunTime" in text
    assert '([datetime]$ti.NextRunTime) -gt (Get-Date)' in text
    assert "is re-armed for" in text
    assert "$ok = $true" in text


def test_running_task_does_not_report_its_stale_last_result_as_current_failure():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '$st -eq "Running"' in text
    assert "LastTaskResult is a completed-run field" in text
    assert 'if (-not $ok -and $st -eq "Running") { $ok = $true }' in text


def test_stage_a_protected_window_teardown_is_an_expected_task_result():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '"WeatherDailySettlementPromotionRefresh" = @("0x2", "0x4B")' in text
    assert "kill-on-close Job tore down the delegated child tree" in text
    assert "workload lease is the ownership signal" in text
    assert '$chainTaskResult -eq "0x4B"' in text
    assert "protected-window deadline; durable terminal status verified" in text


def test_capture_alert_flags_only_the_current_local_capture_day():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$historicalCaptureDay = $alertTime.Date -lt (Get-Date).Date" in text
    assert "-not $historicalCaptureDay -and $ageH -lt 24" in text
    assert "capture alert raised today" in text


def test_disabled_on_demand_success_is_not_an_unexpected_disable():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$noTriggers = ($null -eq $_.Triggers)" in text
    assert "$onDemandCompleted = ($noTriggers -and $res -eq \"0x0\"" in text
    assert "completed an on-demand run" in text


def test_exact_tip_merge_is_spent_only_when_tip_is_integrated() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$integratedExactTipMerge = $false" in text
    assert '$actionArguments -like "*quiet_window_merge.ps1*"' in text
    assert '$actionArguments -like "*suite_gated_quiet_merge.ps1*"' in text
    assert '$actionArguments -like "*integration_attempt_merge.ps1*"' in text
    assert "weather_integration_attempt_manifest_v1" in text
    assert "$isQuietMergeAction -and" in text
    assert "-ExpectedTip\\s+([0-9a-f]{40})" in text
    assert "merge-base --is-ancestor $integratedExactTip HEAD" in text
    assert "$integratedExactTipMerge = ($LASTEXITCODE -eq 0)" in text
    assert "retained as spent exact-tip merge evidence" in text
    assert (
        "-not $ok -and $integratedExactTipMerge -and $oneShot -and "
        "-not $ti.NextRunTime"
    ) in text
    assert "but exact tip $integratedExactTip is already in production history" in text


def test_integration_attempt_recovery_states_are_operator_visible() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$integrationAttemptState" in text
    assert '"FAILED_NEEDS_CLOSE"' in text
    assert '"CLOSED_NEEDS_DISPATCH"' in text
    assert '"RECOVERY_READY"' in text
    assert '"SUCCESSOR_CLAIMED"' in text
    assert '"MERGED_UNVERIFIED"' in text
    assert "recovery is ready for an active agent" in text
    assert "$attemptEvidenceAgeHours" in text
    assert "$attemptEvidenceIsFresh" in text
    assert 'evidence_age_hours = $_.evidence_age_hours' in text
    assert 'task_state = $_.task_state' in text
    assert 'suite_task_state = $_.suite_task_state' in text
    assert "$suiteObservation = Get-WeatherIntegrationSuiteObservation" in text
    assert "$suiteReceiptStatus = [string]$suiteObservation.ReceiptStatus" in text
    assert "$suiteObservation.ReceiptUnreadable" in text
    assert "$mergeObservation = Get-WeatherIntegrationMergeObservation" in text
    assert "$attemptMissedSuite = [bool]$suiteObservation.TriggerMissed" in text
    assert "Test-WeatherIntegrationSuiteTriggerMissed" in text
    assert "suite_ran_without_receipt" in text
    assert "merge_receipt_missing_after_trigger" in text
    assert "-SuiteRanWithoutReceipt ([bool]$suiteObservation.RanWithoutReceipt)" in text
    assert "-MergeReceiptMissingAfterTrigger ([bool]$mergeObservation.ReceiptMissingAfterTrigger)" in text
    assert "unreadable or does not match its task-bound hash" in text
    assert "missed its suite trigger and has no receipt" in text
    assert "integration_attempts =" in text
    assert 'Write-Output "  ATTEMPTS  :"' in text


@WINDOWS_POWERSHELL_REQUIRED
def test_integration_attempt_alert_lifecycle_executes_without_running_status() -> None:
    env = os.environ.copy()
    env["WEATHER_STATUS_SCRIPT"] = str(SCRIPT)
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_STATUS_SCRIPT,
    [ref]$tokens,
    [ref]$errors
)
if (@($errors).Count -ne 0) { throw 'status script did not parse' }
foreach ($name in @(
    'Get-WeatherIntegrationAttemptState',
    'Get-WeatherIntegrationAttemptAlertDisposition'
)) {
    $functionAst = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)) | Select-Object -First 1
    if ($null -eq $functionAst) { throw "missing function $name" }
    Invoke-Expression $functionAst.Extent.Text
}
$failed = Get-WeatherIntegrationAttemptState -SuiteReceiptStatus FAIL
$recovery = Get-WeatherIntegrationAttemptState -DispatchStatus READY_FOR_SUCCESSOR_REVIEW
$merged = Get-WeatherIntegrationAttemptState -MergeReceiptStatus MERGED_UNVERIFIED
$mergedUnpushed = Get-WeatherIntegrationAttemptState -MergeReceiptStatus RECOVERED_UNPUSHED
$reconciled = Get-WeatherIntegrationAttemptState -MergeReceiptStatus MERGED_UNVERIFIED -ReconciliationStatus MERGED_RECONCILED
$cases = @(
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $failed -TaskState Ready -EvidenceIsFresh $true -SuiteTriggerMissed $false
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $failed -TaskState Disabled -EvidenceIsFresh $false -SuiteTriggerMissed $false
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $recovery -TaskState Disabled -EvidenceIsFresh $true -SuiteTriggerMissed $false -RecoveryDispatch dispatch.json
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State ACTIVE_OR_ARMED -TaskState Ready -EvidenceIsFresh $true -SuiteTriggerMissed $true
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State ACTIVE_OR_ARMED -TaskState Disabled -EvidenceIsFresh $true -SuiteTriggerMissed $true
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State SUCCESSOR_CLAIMED -TaskState Disabled -EvidenceIsFresh $false -SuiteTriggerMissed $false -SuccessorAttemptId b
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $merged -TaskState Ready -EvidenceIsFresh $true -SuiteTriggerMissed $false
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $reconciled -TaskState Disabled -EvidenceIsFresh $true -SuiteTriggerMissed $false
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $reconciled -TaskState Disabled -EvidenceIsFresh $false -SuiteTriggerMissed $false
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State ACTIVE_OR_ARMED -TaskState Ready -EvidenceIsFresh $true -SuiteTriggerMissed $false -SuiteRanWithoutReceipt $true
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State ACTIVE_OR_ARMED -TaskState Ready -EvidenceIsFresh $true -SuiteTriggerMissed $false -MergeReceiptMissingAfterTrigger $true
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State ACTIVE_OR_ARMED -TaskState Ready -EvidenceIsFresh $false -SuiteTriggerMissed $false -SuiteRanWithoutReceipt $true -MergeReceiptMissingAfterTrigger $true
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $mergedUnpushed -TaskState Ready -EvidenceIsFresh $true -SuiteTriggerMissed $false
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $mergedUnpushed -TaskState Ready -EvidenceIsFresh $true -SuiteTriggerMissed $false -PublicationClassification guarded_pre_dispatch
)
[pscustomobject]@{
    states = @($failed, $recovery, $merged, $mergedUnpushed, $reconciled)
    severities = @($cases | ForEach-Object { [string]$_.Severity })
    ordinary_unpushed_detail = [string]$cases[-2].Detail
    guarded_unpushed_detail = [string]$cases[-1].Detail
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "states": [
            "FAILED_NEEDS_CLOSE",
            "RECOVERY_READY",
            "MERGED_UNVERIFIED",
            "MERGED_UNPUSHED",
            "MERGED_RECONCILED",
        ],
        "severities": [
            "FLAG",
            "WARN",
            "FLAG",
            "FLAG",
            "FLAG",
            "NONE",
            "FLAG",
            "WARN",
            "NONE",
            "FLAG",
            "FLAG",
            "WARN",
            "FLAG",
            "FLAG",
        ],
        "ordinary_unpushed_detail": (
            "integration attempt a has a recovery-proved local merge not "
            "acknowledged by origin; obtain review, resume publication, and do not "
            "retry it"
        ),
        "guarded_unpushed_detail": (
            "RECONCILIATION_PUBLICATION_RELATED_ATTEMPT: integration attempt a "
            "has a recovery-proved local merge not "
            "acknowledged by origin; the active reconciliation marker owns "
            "publication, so preserve exact evidence and do not manually invoke or "
            "retry WeatherOneShotPush"
        ),
    }


@WINDOWS_POWERSHELL_REQUIRED
def test_attempt_observation_distinguishes_running_interrupted_and_missed(
    tmp_path: Path,
) -> None:
    preflight = tmp_path / "preflight.log"
    preflight.write_text("started\n", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "WEATHER_STATUS_SCRIPT": str(SCRIPT),
            "WEATHER_PREFLIGHT": str(preflight),
            "WEATHER_MISSING_PREFLIGHT": str(tmp_path / "missing.log"),
            "WEATHER_SUITE_RECEIPT": str(tmp_path / "suite-receipt.json"),
        }
    )
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_STATUS_SCRIPT,
    [ref]$tokens,
    [ref]$errors
)
if (@($errors).Count -ne 0) { throw 'status script did not parse' }
foreach ($name in @(
    'Get-WeatherIntegrationSuiteRuntimeState',
    'Test-WeatherIntegrationSuiteTriggerMissed',
    'Get-WeatherIntegrationSuiteObservation',
    'Get-WeatherIntegrationMergeObservation'
)) {
    $functionAst = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)) | Select-Object -First 1
    if ($null -eq $functionAst) { throw "missing function $name" }
    Invoke-Expression $functionAst.Extent.Text
}
$global:suiteState = 'Running'
$global:lastRun = [datetime]'2026-08-21T00:35:00'
function Get-ScheduledTask {
    param([string]$TaskName, $ErrorAction)
    return [pscustomobject]@{ TaskName = $TaskName; State = $global:suiteState }
}
function Get-ScheduledTaskInfo {
    param([string]$TaskName, $ErrorAction)
    return [pscustomobject]@{ LastRunTime = $global:lastRun; LastTaskResult = 267009 }
}
$suiteAt = [datetime]'2026-08-21T00:35:00'
$now = [datetime]'2026-08-21T00:45:00'
$manifest = [pscustomobject]@{
    schedule = [pscustomobject]@{
        suite_at_local = $suiteAt.ToString('o')
        merge_at_local = $suiteAt.AddMinutes(30).ToString('o')
        suite_task_name = 'WeatherIntegrationSuite_a'
    }
    evidence = [pscustomobject]@{
        preflight_log = $env:WEATHER_MISSING_PREFLIGHT
        suite_receipt = $env:WEATHER_SUITE_RECEIPT
    }
}
$running = Get-WeatherIntegrationSuiteObservation -AttemptManifest $manifest -Now $now
$global:suiteState = 'Ready'
$global:lastRun = [datetime]'1999-11-30T00:00:00'
$manifest.evidence.preflight_log = $env:WEATHER_PREFLIGHT
$preflight = Get-WeatherIntegrationSuiteObservation -AttemptManifest $manifest -Now $now
Set-Content -LiteralPath $env:WEATHER_SUITE_RECEIPT -Value '{"status":"PASS"}'
$receiptAppeared = Get-WeatherIntegrationSuiteObservation `
    -AttemptManifest $manifest -Now $now
Set-Content -LiteralPath $env:WEATHER_SUITE_RECEIPT -Value '{'
$unreadableReceipt = Get-WeatherIntegrationSuiteObservation `
    -AttemptManifest $manifest -Now $now
Remove-Item -LiteralPath $env:WEATHER_SUITE_RECEIPT
$global:suiteState = 'Disabled'
$manifest.evidence.preflight_log = $env:WEATHER_MISSING_PREFLIGHT
$missing = Get-WeatherIntegrationSuiteObservation -AttemptManifest $manifest -Now $now
$withinGrace = Get-WeatherIntegrationSuiteObservation `
    -AttemptManifest $manifest -Now $suiteAt.AddMinutes(4)
$global:suiteState = 'Ready'
$global:lastRun = $null
$nullLastRun = Get-WeatherIntegrationSuiteObservation `
    -AttemptManifest $manifest -Now $now
$mergeAt = $suiteAt.AddMinutes(30)
$mergeRunning = Get-WeatherIntegrationMergeObservation `
    -AttemptManifest $manifest -TaskState Running -Now $mergeAt.AddMinutes(10)
$mergeWithinGrace = Get-WeatherIntegrationMergeObservation `
    -AttemptManifest $manifest -TaskState Ready -Now $mergeAt.AddMinutes(4)
$mergeMissed = Get-WeatherIntegrationMergeObservation `
    -AttemptManifest $manifest -TaskState Ready -Now $mergeAt.AddMinutes(5)
$mergeReceipt = Get-WeatherIntegrationMergeObservation `
    -AttemptManifest $manifest -TaskState Ready -Now $mergeAt.AddMinutes(10) `
    -MergeReceiptStatus FAIL
$mergeClosed = Get-WeatherIntegrationMergeObservation `
    -AttemptManifest $manifest -TaskState Disabled -Now $mergeAt.AddMinutes(10) `
    -ClosureStatus FAIL
[pscustomobject]@{
    running_now = [bool]$running.Running
    running_started = [bool]$running.Started
    running_missed = [bool]$running.TriggerMissed
    running_without_receipt = [bool]$running.RanWithoutReceipt
    preflight_started = [bool]$preflight.Started
    preflight_missed = [bool]$preflight.TriggerMissed
    preflight_ran_without_receipt = [bool]$preflight.RanWithoutReceipt
    fresh_receipt_ran_without_receipt = [bool]$receiptAppeared.RanWithoutReceipt
    fresh_receipt_status = [string]$receiptAppeared.ReceiptStatus
    unreadable_receipt_flagged = [bool]$unreadableReceipt.ReceiptUnreadable
    unreadable_receipt_ran_without_receipt = [bool]$unreadableReceipt.RanWithoutReceipt
    disabled_started = [bool]$missing.Started
    disabled_missed = [bool]$missing.TriggerMissed
    grace_missed = [bool]$withinGrace.TriggerMissed
    null_last_run = $nullLastRun.LastRunTime
    null_last_run_missed = [bool]$nullLastRun.TriggerMissed
    merge_running_missing = [bool]$mergeRunning.ReceiptMissingAfterTrigger
    merge_grace_missing = [bool]$mergeWithinGrace.ReceiptMissingAfterTrigger
    merge_missed = [bool]$mergeMissed.ReceiptMissingAfterTrigger
    merge_receipt_missing = [bool]$mergeReceipt.ReceiptMissingAfterTrigger
    merge_closed_missing = [bool]$mergeClosed.ReceiptMissingAfterTrigger
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "running_now": True,
        "running_started": True,
        "running_missed": False,
        "running_without_receipt": False,
        "preflight_started": True,
        "preflight_missed": False,
        "preflight_ran_without_receipt": True,
        "fresh_receipt_ran_without_receipt": False,
        "fresh_receipt_status": "PASS",
        "unreadable_receipt_flagged": True,
        "unreadable_receipt_ran_without_receipt": True,
        "disabled_started": False,
        "disabled_missed": True,
        "grace_missed": False,
        "null_last_run": None,
        "null_last_run_missed": True,
        "merge_running_missing": False,
        "merge_grace_missing": False,
        "merge_missed": True,
        "merge_receipt_missing": False,
        "merge_closed_missing": False,
    }


def test_only_active_scheduled_interactive_tasks_count_as_reboot_exposure():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$scheduledWorkRemains = (-not $noTriggers" in text
    assert '$st -ne "Disabled"' in text
    assert "$scheduledWorkRemains)" in text


def test_status_flags_notify_only_windows_update_policy():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$windowsUpdateAuOptions -eq 2" in text
    assert "policy-forced to notify-only" in text
    assert "unattended_updates_blocked = ($windowsUpdateAuOptions -eq 2)" in text


def test_operator_held_evidence_refresh_keeps_one_honest_warning():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '"WeatherEveningEvidenceRefresh"' in text
    assert "$evidenceRefreshHeld = $true" in text
    assert "is operator-held DISABLED" in text


def test_quiet_merge_recovery_interval_cannot_overlap_sensitive_driver():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$oneShot -and $ti.NextRunTime -and $isQuietMergeAction" in text
    assert "-SettleSeconds\\s+(\\d+)" in text
    assert "-RollbackRecoverySeconds\\s+(\\d+)" in text
    assert "$settleSeconds + 240" in text
    assert "$settleSeconds + $rollbackRecoverySeconds + 60" in text
    assert "[math]::Max($successProtectionSeconds, $rollbackProtectionSeconds)" in text
    assert '$actionArguments -like "*integration_attempt_merge.ps1*"' in text
    assert "Date.AddHours(5)" in text
    assert "$sensitiveDriverNextRun -ge $mergeTask.at" in text
    assert "the driver can publish unverified local master" in text


def test_status_flags_unproven_rollback_recovery_separately() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '$qw.stage -eq "rollback_recovery_failed"' in text
    assert "rollback recovery is UNPROVEN" in text
    assert '$qw.stage -eq "rolled_back"' in text


def test_documentation_transaction_warns_before_deadline_and_flags_after_it() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "weather.operations.documentation_transaction" in text
    assert 'state -eq "INVALID"' in text
    assert 'state -eq "PENDING"' in text
    assert "DOCUMENTATION TRANSACTION DUE" in text
    assert "if ([bool]$documentationTransaction.overdue)" in text
    assert "$flags.Add($detail)" in text
    assert "$warns.Add($detail)" in text
    assert "documentation = $documentationTransaction" in text


def test_settlement_scan_seeks_from_end_instead_of_rescanning_each_ledger():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "weather.operations.settlement_hole_check" in text
    assert "--window-days $windowDays --tail-lines 400 --json" in text
    assert "Get-Content -LiteralPath $ledger -Tail 400" not in text


def test_legacy_unbound_merge_drivers_are_intentionally_held() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '"WeatherMergeQueueDriver", "WeatherMergeSensitiveDriver", "WeatherSuite0969a"' in text
    assert '$st -ne "Disabled"' in text


def test_training_hold_is_default_and_reenable_warning_requires_exact_bounded_action() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'Get-ScheduledTask -TaskName "WeatherTrainingWindowReenable*"' in text
    assert "$trainingReenableDeadline = $trainingReenableNow.AddHours(30)" in text
    assert '[string]$candidate.TaskPath -ne "\\"' in text
    assert "$candidateActions.Count -ne 1" in text
    assert "$candidateTriggers.Count -ne 1" in text
    assert 'Join-Path $PSHOME "powershell.exe"' in text
    assert "Enable-ScheduledTask -TaskName 'WeatherTrainingWindow'" in text
    assert "Disable-ScheduledTask -TaskName '$([string]$candidate.TaskName)'" in text
    assert '[string]$candidateAction.Arguments -cne $expectedArguments' in text
    assert '"WeatherTrainingWindow"' in text
    assert "held DISABLED by the opt-in maintenance policy" in text
    assert "automatic re-enable is armed" in text


def test_optional_chain_readiness_is_safe_for_strict_mode_callers() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '$chain.PSObject.Properties["production_readiness"]' in text
    assert '$chain.PSObject.Properties["summary"]' in text
    assert '$value.PSObject.Properties["status"]' in text
    assert '$f.PSObject.Properties["result"]' in text
    assert '$fResult.PSObject.Properties["reason"]' in text
    assert '$f.PSObject.Properties["error"]' in text
    assert "$f.result.reason" not in text
    assert "if ($chain -and $chain.production_readiness)" not in text


def test_status_reports_only_an_os_held_heavy_workload_lease() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "Get-WeatherHeavyWorkloadLeaseState" in text
    assert "heavy workload lease active" in text


def test_status_uses_durable_tiering_status_not_scheduler_zero() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "clob_tiering_task_status.json" in text
    assert "clob_raw_tape_tiering_task_status.json" in text
    assert "SKIPPED_WORKLOAD_LEASE_BUSY" in text
    assert "Task Scheduler 0x0 does not prove reclaim" in text
    assert "tiering  = $tieringState" in text


def test_status_snapshot_fallback_matches_the_twelve_minute_capture_contract() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '"snapshot_tracker"      = @{ Status = "loop_status.json"; Lock = ".loop_status.json.writer.lock"; MaxAge = 720.0 }' in text
    assert '"market_microstructure" = @{ Status = "clob_loop_status.json"; Lock = ".clob_loop_status.json.writer.lock"; MaxAge = 180.0 }' in text
    assert '"observation_trigger"   = @{ Status = "observation_trigger_status.json"; Lock = ".observation_trigger_status.json.writer.lock"; MaxAge = 180.0 }' in text


def test_status_surfaces_optional_capture_error_state_without_assuming_one_schema() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '$runtimeStatus.PSObject.Properties["consecutive_errors"]' in text
    assert '$runtimeStatus.PSObject.Properties["last_error"]' in text
    assert '$runtimeStatus.PSObject.Properties["last_clean_iteration"]' in text
    assert '$runtimeStatus.PSObject.Properties["last_clean_iteration_at"]' in text
    assert "capture loop ERRORING" in text
    assert "process/heartbeat liveness alone is not a clean iteration" in text
    assert "capture_runtime = $captureRuntimeState" in text
    assert "current_runtime_identity" not in text


def test_status_fails_closed_on_unsynchronized_windows_clock() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'ProviderName = "Microsoft-Windows-Time-Service"' in text
    assert "Id = 35, 37" in text
    assert 'Get-Service -Name W32Time' in text
    assert "$clockQueryExit = $LASTEXITCODE" in text
    assert "Last Successful Sync Time:" in text
    assert "[datetime]::TryParse" in text
    assert "$clockLastSync = $liveSync" in text
    assert 'if ($clockQueryExit -ne 0 -or -not $sourceMatch.Success)' in text
    assert 'Leap Indicator:\\s*3' in text
    assert 'Source:\\s*Local CMOS Clock' in text
    assert "system clock is not synchronized" in text
    assert 'Write-Output ("  CLOCK     : {0}"' in text


def test_clock_event_fallback_cannot_skip_live_w32tm_sampling() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    event_query = text.index("$syncEvent = Get-WinEvent")
    event_catch = text.index("catch { }", event_query)
    live_query = text.index(
        'if ($clockService -and $clockService.Status -eq "Running")',
        event_catch,
    )
    assert event_query < event_catch < live_query
    assert "absence of an event must not\n# skip w32tm" in text


def test_only_exact_superseded_nonfixed_bootstrap_pair_is_expected_disabled() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '"WeatherIntegrationRecoveryBootstrapSuite0822"' in text
    assert '"WeatherIntegrationRecoveryBootstrapMerge0822"' in text
    assert '"WeatherIntegrationRecoveryBootstrapSuiteFixed0822"' not in text
    assert '"WeatherIntegrationRecoveryBootstrapMergeFixed0822"' not in text
    assert '$isExpectedDisabled = ($st -eq "Disabled" -and $expDisabled -contains $name)' in text
    assert "-and -not $isExpectedDisabled" in text
    assert '$st -eq "Disabled" -and $expDisabled -notcontains $name' in text
    assert "$mustRemainDisabled" in text
    assert '$mustRemainDisabled.Add("WeatherIntegrationRecoveryBootstrapSuite0822")' in text
    assert '$mustRemainDisabled.Add("WeatherIntegrationRecoveryBootstrapMerge0822")' in text
    assert '$mustRemainDisabled.Contains([string]$name) -and $st -ne "Disabled"' in text
    assert "is superseded and must never be re-enabled" in text
    assert "Get-WeatherFixedBootstrapScheduleState" not in text


def test_failed_disabled_one_shot_reports_the_run_not_the_terminal_state() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$name spent one-shot FAILED $res" in text
    assert "verify its artifact" in text
    assert "(Get-Date).AddHours(-24)" in text


def test_complete_overnight_audit_receipt_replaces_stale_verify_artifact_flag() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '"*audit_overnight_integration_chain.ps1*"' in text
    assert "-ReportPath\\s+" in text
    assert '"overnight_integration_chain_audit_v1"' in text
    assert "$candidateAuditReceipt.complete -eq $true" in text
    assert "$knownRetainedGapOnly" in text
    assert "complete audit remains BLOCK only for retained execution-tape gaps" in text
    assert "complete audit verdict is BLOCK" in text


def test_codex_wake_receipt_is_authoritative_over_scheduler_result() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "function Get-WeatherCodexWakeReceiptState" in text
    assert '"live_overnight_codex_wake_receipt_v0.2"' in text
    assert '"live_night_salvage_wake_receipt_v0.1"' in text
    assert "overnight-audits|night-salvage" in text
    assert "Get-FileHash -LiteralPath $state.runner_path -Algorithm SHA256" in text
    assert "$propagatesChildExit" in text
    assert "LASTEXITCODE" in text
    assert "receiptStarted.LocalDateTime" in text
    assert 'secret_values_read' in text
    assert 'live_mutation_attempted_by_wrapper' in text
    assert 'authenticated_spawn_smoke' in text
    assert 'integration_already_complete' in text
    assert 'integration_recovered_by_bounded_codex' in text
    assert 'preintegration_ready_no_agent' in text
    assert 'preintegration_recovered_by_codex' in text
    assert 'morning_closeout_completed' in text
    assert 'live_wake_receipt_correction_v0.1' in text
    assert 'bounded_codex_completed_without_integration' in text
    assert 'original_receipt_sha256' in text
    assert 'last_message_sha256' in text
    assert '$correctionCreated -ge $receiptFinished' in text
    assert 'correction_applied' in text
    assert '[double]$receipt.commit_percent_after -lt 60' in text
    assert "completed without its authoritative wake receipt" in text
    assert "authoritative wake receipt is invalid" in text
    assert "authoritative wake receipt is FAIL" in text
    assert "authoritative wake receipt is PASS" in text
    assert "overnight_wakes =" in text


def test_disk_alarm_distinguishes_a_short_burst_from_multi_day_burn() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$cut48 = (Get-Date).AddHours(-48)" in text
    assert "$diskDelta48" in text
    assert "$diskDaysLeft48" in text
    assert "disk 24h burst is" in text
    assert "keep tiering armed and treat the short window as a burst" in text
    assert "delta_48h_gb_per_day" in text


def test_status_monitors_execution_tape_only_after_it_is_armed() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'Get-ScheduledTask -TaskName "WeatherExecutionTapeSupervisor"' in text
    assert '$executionTapeState.armed = [string]$executionTapeTask.State -ne "Disabled"' in text
    assert '"execution_tape_status.json"' in text
    assert '".execution_tape_status.json.writer.lock"' in text
    assert '"execution_tape_supervisor_status.json"' in text
    assert '$executionAge -le 180' in text
    assert 'public execution-tape evidence integrity is BLOCKED_EVIDENCE_LOSS' in text
    assert 'execution_tape = $executionTapeState' in text
