import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
SCRIPTS = {
    name: OPS / name
    for name in (
        "integration_attempt_contract.ps1",
        "new_integration_attempt.ps1",
        "integration_attempt_suite.ps1",
        "integration_attempt_merge.ps1",
        "register_integration_attempt.ps1",
        "close_integration_attempt.ps1",
        "dispatch_integration_attempt_recovery.ps1",
        "assert_integration_attempt_success.ps1",
    )
}
PARSE_SCRIPTS = tuple(SCRIPTS.values()) + tuple(
    OPS / name
    for name in (
        "bounded_worktree_test_suite.ps1",
        "adopt_execution_tape_after_merge.ps1",
        "quiet_window_merge.ps1",
        "status.ps1",
    )
)


def _text(name: str) -> str:
    return SCRIPTS[name].read_text(encoding="utf-8-sig")


def test_attempt_manifest_freezes_evidence_not_the_entire_night() -> None:
    contract = _text("integration_attempt_contract.ps1")
    creator = _text("new_integration_attempt.ps1")

    assert "weather_integration_attempt_manifest_v1" in contract
    assert "Immutable evidence already exists and will not be replaced" in contract
    assert "AttemptRoot already exists" in creator
    assert "A repair attempt must bind the immutable failed receipt" in creator
    assert 'priorReceipt.status -ne "FAIL"' in creator
    assert "prior_attempt_id" in creator
    assert "review_reference" in creator
    assert "repair_class" in creator
    assert "RepairClass $RepairClass does not authorize changed path" in creator
    assert "schema_registry_data" in contract
    assert "module-ownership-map" in contract
    assert "manual_reviewed_change" in creator
    assert "retry_unchanged" in creator
    assert "An unchanged retry may not follow another unchanged retry" in creator
    assert "ExpectedTip -ne $priorTip" in creator
    assert "merge-base --is-ancestor $masterTip $ExpectedTip" in creator
    assert "production working tree must have exact master checked out" in creator
    assert "already has a successor claim" in creator
    assert "successor-claim.json" in creator
    assert "recovery_dispatch" in creator
    assert "suite_at_local" in creator
    assert "merge_at_local" in creator
    assert "expected_test_file_count" in creator
    assert "max_files_per_chunk" in creator
    assert "expected_chunk_count" in creator
    assert '@("ls-files", "--", "tests")' in creator
    assert "quiet_merge_report" in creator
    assert "git reset" not in creator.lower()
    assert "git push" not in creator.lower()

    closer = _text("close_integration_attempt.ps1")
    assert "Attempt task is still running" in closer
    assert "Disable-ScheduledTask" in closer
    assert "An attempt that reached production cannot be abandoned or retried" in closer
    assert "immutable registration receipt" in closer
    assert "registeredAction.arguments" in closer
    assert 'Principal.LogonType -ne "S4U"' in closer
    assert "training_window_contract.ps1" not in closer
    assert "weather_integration_attempt_closure_receipt_v1" in contract


def test_attempt_suite_runs_ratchets_before_full_suite_and_freezes_receipt() -> None:
    bounded = (OPS / "bounded_worktree_test_suite.ps1").read_text(
        encoding="utf-8-sig"
    )
    suite = _text("integration_attempt_suite.ps1")

    assert "IntegrationPreflight" in bounded
    assert "tests/operations/test_schema_registry.py" in bounded
    assert "tests/operations/test_module_size_audit.py" in bounded
    assert "tests/operations/test_import_architecture.py" in bounded
    assert "VERDICT: INTEGRATION PREFLIGHT PASSED" in bounded
    assert suite.index("-IntegrationPreflight") < suite.index('Phase "full suite"')
    assert "full suite was not started" in suite
    assert "Start-WeatherProcessInJob" in suite
    assert "New-WeatherKillOnCloseJob" in suite
    assert suite.count("Assert-WeatherIntegrationGitBaseline") == 3
    assert "weather_integration_attempt_suite_receipt_v1" in (
        _text("integration_attempt_contract.ps1")
    )
    assert "Write-WeatherIntegrationImmutableJson -Path $suiteReceiptPath" in suite
    assert "Get-WeatherIntegrationLogVerdict" in suite
    assert "Assert-WeatherIntegrationFullSuiteVerdict" in suite
    assert "Assert-WeatherIntegrationFullSuiteLogPlan" in suite
    assert "Get-WeatherAttemptLogVerdict" not in suite
    assert "git merge" not in suite.lower()
    assert "git push" not in suite.lower()

    for frozen_helper in (
        "training_window_contract.ps1",
        "windows_kill_on_close_job.ps1",
        "workload_admission.ps1",
        "roll_verdict.ps1",
    ):
        assert frozen_helper in _text("new_integration_attempt.ps1")
        assert frozen_helper in _text("integration_attempt_contract.ps1")


def test_attempt_merge_consumes_exact_receipts_and_preserves_quiet_merge() -> None:
    merge = _text("integration_attempt_merge.ps1")
    downstream = _text("assert_integration_attempt_success.ps1")

    suite_gate = merge.index("Assert-WeatherIntegrationSuiteReceipt")
    task_gate = merge.index("Assert-WeatherIntegrationSuiteTask")
    quiet_merge = merge.index("$quietMergeExitCode = Invoke-WeatherQuietMergeChild")
    assert suite_gate < quiet_merge
    assert task_gate < quiet_merge
    assert "Suite task arguments are not exactly bound" in merge
    assert "quiet_window_merge.ps1" in merge
    assert 'stage -ne "pushed"' in merge
    assert "documentation transaction recorded" not in merge.lower()
    assert "quietReport.documentation_transaction_recorded" in merge
    assert "merge-base --is-ancestor" in merge
    assert "capture_recovery_check" in merge
    assert "Wait-WeatherIntegrationSuiteTerminal" in merge
    assert "Get-WeatherIntegrationSuiteWaitDecision" in merge
    assert '"-ExpectedBaseline", $ExpectedBaseline' in merge
    assert "expected_baseline -ne [string]$manifest.baseline.master" in merge
    assert merge.count("Assert-WeatherIntegrationGitBaseline") == 2
    assert merge.count("Assert-WeatherIntegrationOrchestrationFiles") == 2
    assert "suiteDeadlineStopEvidence" in merge
    assert "Stop-ScheduledTask -TaskName $taskName" in merge
    assert 'status = "MERGED_UNVERIFIED"' in merge
    assert "Write-WeatherIntegrationImmutableJson -Path $attemptQuietReportPath" in merge
    assert "Write-WeatherIntegrationImmutableJson -Path $mergeReceiptPath" in merge
    assert "git push" not in merge.lower()

    assert "ExpectedMergeReceiptSha256" in downstream
    assert "Assert-WeatherIntegrationMergeReceipt" in downstream
    assert "Current master and origin/master are not exact" in downstream
    assert "published integration tip is not in current master history" in downstream
    assert "capture_recovery_check" in downstream


def test_attempt_registrar_is_unique_unattended_and_does_not_start_work() -> None:
    registrar = _text("register_integration_attempt.ps1")

    assert "Attempt task already exists and will not be replaced" in registrar
    assert "Register the fail-closed consumer first" in registrar
    assert "-LogonType S4U" in registrar
    assert "-RunLevel Limited" in registrar
    assert "-Principal $principal" in registrar
    assert "-Once -At $suiteAt" in registrar
    assert "-Once -At $mergeAt" in registrar
    assert "StartWhenAvailable" not in registrar
    assert "downstream_tasks_created = $false" in registrar
    assert "Start-ScheduledTask" not in registrar
    assert "Unregister-ScheduledTask" not in registrar
    assert r"C:\Users\micha" not in registrar
    assert "New-TimeSpan -Hours 4" in registrar


def test_attempt_receipts_label_static_safety_as_authority_not_observed_outcome() -> None:
    attempt_text = "\n".join(path.read_text(encoding="utf-8-sig") for path in SCRIPTS.values())

    assert "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" in attempt_text
    assert "credential_value_access_authorized" in attempt_text
    assert "live_exchange_mutation_authorized" in attempt_text
    assert "credential_value_read" not in attempt_text
    assert "live_exchange_mutation_attempted" not in attempt_text


def test_recovery_dispatch_is_reviewed_non_mutating_and_single_use() -> None:
    dispatch = _text("dispatch_integration_attempt_recovery.ps1")

    assert "ExpectedClosureReceiptSha256" in dispatch
    assert "READY_FOR_SUCCESSOR_REVIEW" in dispatch
    assert "automatic_source_edit_authorized = $false" in dispatch
    assert "scheduler_change_authorized = $false" in dispatch
    assert "orchestration_drift" in dispatch
    assert "orchestration_wrapper or an explicitly manual_reviewed_change" in dispatch
    assert 'FailureClass -notin @("orchestration_wrapper", "manual_reviewed_change")' in dispatch
    assert "Assert-WeatherIntegrationOrchestrationFiles" not in dispatch
    assert "Write-WeatherIntegrationImmutableJson -Path $dispatchPath" in dispatch
    assert "Register-ScheduledTask" not in dispatch
    assert "Start-ScheduledTask" not in dispatch
    assert "git commit" not in dispatch.lower()


def test_orchestration_repair_scope_excludes_governing_policy_documents() -> None:
    env = os.environ.copy()
    env["WEATHER_ATTEMPT_CONTRACT"] = str(
        SCRIPTS["integration_attempt_contract.ps1"]
    )
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$patterns = @(Get-WeatherIntegrationRepairAllowedPatterns -RepairClass orchestration_wrapper)
$paths = @(
    'docs/operations/INTEGRATION_ATTEMPT_RUNBOOK.md',
    'docs/operations/OPERATIONS_DESIGN.md',
    'docs/ops/streak-soak.md',
    'docs/operations/reserved-confirmation-window.md',
    'docs/operations/HOST_LOAD_POLICY.md',
    'docs/operations/DELEGATION_CONTRACT.md',
    'docs/operations/STATE_OF_PLAY.md'
)
@($paths | ForEach-Object {
    $path = $_
    [pscustomobject]@{
        path = $path
        allowed = @($patterns | Where-Object { $path -match $_ }).Count -gt 0
    }
}) | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    allowed = {row["path"]: row["allowed"] for row in json.loads(result.stdout)}
    assert allowed == {
        "docs/operations/INTEGRATION_ATTEMPT_RUNBOOK.md": True,
        "docs/operations/OPERATIONS_DESIGN.md": True,
        "docs/ops/streak-soak.md": True,
        "docs/operations/reserved-confirmation-window.md": False,
        "docs/operations/HOST_LOAD_POLICY.md": False,
        "docs/operations/DELEGATION_CONTRACT.md": False,
        "docs/operations/STATE_OF_PLAY.md": False,
    }


def test_recovery_dispatch_writes_one_hash_bound_successor_instruction(
    tmp_path: Path,
) -> None:
    attempt_root = tmp_path / "attempt"
    worktree_root = tmp_path / "worktree"
    attempt_root.mkdir()
    worktree_root.mkdir()
    manifest_path = attempt_root / "manifest.json"
    zeros = "0" * 40
    orchestration_files = {
        "contract": OPS / "integration_attempt_contract.ps1",
        "attempt_creator": OPS / "new_integration_attempt.ps1",
        "attempt_registrar": OPS / "register_integration_attempt.ps1",
        "attempt_closer": OPS / "close_integration_attempt.ps1",
        "bounded_suite": OPS / "bounded_worktree_test_suite.ps1",
        "attempt_suite": OPS / "integration_attempt_suite.ps1",
        "attempt_merge": OPS / "integration_attempt_merge.ps1",
        "attempt_success_gate": OPS / "assert_integration_attempt_success.ps1",
        "attempt_recovery_dispatch": OPS
        / "dispatch_integration_attempt_recovery.ps1",
        "quiet_merge": OPS / "quiet_window_merge.ps1",
        "token_contract": OPS / "training_window_contract.ps1",
        "job_containment": OPS / "windows_kill_on_close_job.ps1",
        "workload_admission": OPS / "workload_admission.ps1",
        "roll_verdict": OPS / "roll_verdict.ps1",
    }
    manifest = {
        "schema": "weather_integration_attempt_manifest_v1",
        "attempt_id": "dispatch-test",
        "attempt_root": str(attempt_root),
        "repo_root": str(ROOT),
        "worktree_root": str(worktree_root),
        "branch_ref": "codex/dispatch-test",
        "expected_tip": "1" * 40,
        "authorization": {
            "review_reference": "initial-review",
            "repair_class": "initial",
            "repair_of": None,
        },
        "schedule": {
            "suite_at_local": "2026-08-21T00:30:00",
            "merge_at_local": "2026-08-21T01:00:00",
            "suite_task_name": "WeatherIntegrationSuite_dispatch-test",
            "merge_task_name": "WeatherIntegrationMerge_dispatch-test",
        },
        "suite": {
            "additional_python_path": "",
            "require_live_sdk_contract": False,
            "expected_test_file_count": 40,
            "max_files_per_chunk": 20,
            "expected_chunk_count": 2,
        },
        "baseline": {"master": zeros, "origin_master": zeros},
        "orchestration": {
            name: {
                "path": str(path),
                "sha256": (
                    "0" * 64
                    if name == "token_contract"
                    else hashlib.sha256(path.read_bytes()).hexdigest()
                ),
            }
            for name, path in orchestration_files.items()
        },
        "evidence": {
            "preflight_log": str(attempt_root / "preflight.log"),
            "full_suite_log": str(attempt_root / "full-suite.log"),
            "suite_receipt": str(attempt_root / "suite-receipt.json"),
            "merge_receipt": str(attempt_root / "merge-receipt.json"),
            "quiet_merge_report": str(attempt_root / "quiet-merge-report.json"),
            "registration_receipt": str(attempt_root / "registration-receipt.json"),
            "closure_receipt": str(attempt_root / "closure-receipt.json"),
            "recovery_dispatch": str(attempt_root / "recovery-dispatch.json"),
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    closure_path = attempt_root / "closure-receipt.json"
    closure = {
        "schema": "weather_integration_attempt_closure_receipt_v1",
        "status": "FAIL",
        "attempt_id": "dispatch-test",
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_hash,
        "tasks": [],
    }
    closure_path.write_text(json.dumps(closure), encoding="utf-8")
    closure_hash = hashlib.sha256(closure_path.read_bytes()).hexdigest()
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPTS["dispatch_integration_attempt_recovery.ps1"]),
        "-ManifestPath",
        str(manifest_path),
        "-ExpectedManifestSha256",
        manifest_hash,
        "-ExpectedClosureReceiptSha256",
        closure_hash,
        "-FailureClass",
        "schema_registry",
        "-ReviewReference",
        "review-329",
    ]
    wrong_class = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert wrong_class.returncode != 0
    assert "orchestration_wrapper or an explicitly manual_reviewed_change" in wrong_class.stderr

    command[command.index("schema_registry")] = "manual_reviewed_change"
    created = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert created.returncode == 0, created.stderr
    payload = json.loads(created.stdout)
    assert payload["status"] == "READY_FOR_SUCCESSOR_REVIEW"
    assert payload["repair_class"] == "manual_reviewed_change"
    assert [row["name"] for row in payload["orchestration_drift"]] == [
        "token_contract"
    ]
    assert payload["closure_receipt_sha256"] == closure_hash
    assert payload["automatic_source_edit_authorized"] is False
    assert payload["scheduler_change_authorized"] is False

    refused = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert refused.returncode != 0
    assert "already exists" in refused.stderr.lower()


def test_closer_uses_registration_receipt_when_orchestration_helpers_drift(
    tmp_path: Path,
) -> None:
    attempt_root = tmp_path / "attempt"
    worktree_root = tmp_path / "worktree"
    attempt_root.mkdir()
    worktree_root.mkdir()
    manifest_path = attempt_root / "manifest.json"
    zeros = "0" * 40
    manifest = {
        "schema": "weather_integration_attempt_manifest_v1",
        "attempt_id": "close-test",
        "attempt_root": str(attempt_root),
        "repo_root": str(ROOT),
        "worktree_root": str(worktree_root),
        "branch_ref": "codex/close-test",
        "expected_tip": "1" * 40,
        "authorization": {
            "review_reference": "initial-review",
            "repair_class": "initial",
            "repair_of": None,
        },
        "schedule": {
            "suite_at_local": "2026-08-21T00:30:00",
            "merge_at_local": "2026-08-21T01:00:00",
            "suite_task_name": "WeatherIntegrationSuite_close-test",
            "merge_task_name": "WeatherIntegrationMerge_close-test",
        },
        "suite": {
            "additional_python_path": "",
            "require_live_sdk_contract": False,
            "expected_test_file_count": 40,
            "max_files_per_chunk": 20,
            "expected_chunk_count": 2,
        },
        "baseline": {"master": zeros, "origin_master": zeros},
        "evidence": {
            "preflight_log": str(attempt_root / "preflight.log"),
            "full_suite_log": str(attempt_root / "full-suite.log"),
            "suite_receipt": str(attempt_root / "suite-receipt.json"),
            "merge_receipt": str(attempt_root / "merge-receipt.json"),
            "quiet_merge_report": str(attempt_root / "quiet-merge-report.json"),
            "registration_receipt": str(attempt_root / "registration-receipt.json"),
            "closure_receipt": str(attempt_root / "closure-receipt.json"),
            "recovery_dispatch": str(attempt_root / "recovery-dispatch.json"),
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    executable = str(Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")
    registration_path = attempt_root / "registration-receipt.json"
    registration = {
        "schema": "weather_integration_attempt_registration_receipt_v1",
        "status": "PASS",
        "attempt_id": "close-test",
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_hash,
        "principal": {
            "user_id": "integration-test",
            "logon_type": "S4U",
            "run_level": "Limited",
        },
        "suite": {
            "task_name": "WeatherIntegrationSuite_close-test",
            "registered": False,
            "executable": executable,
            "arguments": "frozen-suite-arguments",
            "working_directory": str(ROOT),
        },
        "merge": {
            "task_name": "WeatherIntegrationMerge_close-test",
            "registered": True,
            "executable": executable,
            "arguments": "frozen-merge-arguments",
            "working_directory": str(ROOT),
        },
    }
    registration_path.write_text(json.dumps(registration), encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "WEATHER_ATTEMPT_CLOSE": str(SCRIPTS["close_integration_attempt.ps1"]),
            "WEATHER_ATTEMPT_MANIFEST": str(manifest_path),
            "WEATHER_ATTEMPT_MANIFEST_HASH": manifest_hash,
            "WEATHER_ATTEMPT_EXE": executable,
            "WEATHER_ATTEMPT_ROOT": str(ROOT),
        }
    )
    script = r"""
$ErrorActionPreference = 'Stop'
$global:mockTasks = @{
    'WeatherIntegrationSuite_close-test' = [pscustomobject]@{
        State = 'Ready'
        Actions = @([pscustomobject]@{ Execute = $env:WEATHER_ATTEMPT_EXE; Arguments = 'frozen-suite-arguments'; WorkingDirectory = $env:WEATHER_ATTEMPT_ROOT })
        Principal = [pscustomobject]@{ UserId = 'integration-test'; LogonType = 'S4U'; RunLevel = 'Limited' }
    }
    'WeatherIntegrationMerge_close-test' = [pscustomobject]@{
        State = 'Ready'
        Actions = @([pscustomobject]@{ Execute = $env:WEATHER_ATTEMPT_EXE; Arguments = 'frozen-merge-arguments'; WorkingDirectory = $env:WEATHER_ATTEMPT_ROOT })
        Principal = [pscustomobject]@{ UserId = 'integration-test'; LogonType = 'S4U'; RunLevel = 'Limited' }
    }
}
function Get-ScheduledTask { param([string]$TaskName, $ErrorAction); return $global:mockTasks[$TaskName] }
function Disable-ScheduledTask { param([string]$TaskName, $ErrorAction); $global:mockTasks[$TaskName].State = 'Disabled'; return $global:mockTasks[$TaskName] }
function Get-ScheduledTaskInfo { param([string]$TaskName, $ErrorAction); return [pscustomobject]@{ LastRunTime = [datetime]'2026-08-21T00:30:00'; LastTaskResult = 1 } }
& $env:WEATHER_ATTEMPT_CLOSE `
    -ManifestPath $env:WEATHER_ATTEMPT_MANIFEST `
    -ExpectedManifestSha256 $env:WEATHER_ATTEMPT_MANIFEST_HASH `
    -Reason 'reviewed failure' `
    -ReviewReference 'review-close'
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    closure = json.loads((attempt_root / "closure-receipt.json").read_text(encoding="utf-8-sig"))
    assert closure["status"] == "FAIL"
    assert [task["disabled"] for task in closure["tasks"]] == [True, True]
    assert closure["tasks"][0]["registration_receipt_disagreed"] is True
    assert closure["tasks"][1]["registration_receipt_disagreed"] is False


def test_execution_tape_adoption_accepts_only_hash_bound_attempt_receipts() -> None:
    adoption = (OPS / "adopt_execution_tape_after_merge.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert "integration_attempt_merge.ps1" in adoption
    assert "AttemptManifestPath" in adoption
    assert "ExpectedManifestSha256" in adoption
    assert "ExpectedMergeReceiptSha256" in adoption
    assert "assert_integration_attempt_success.ps1" in adoption
    assert "ExpectedTip does not equal the hash-bound integration-attempt source tip" in adoption
    assert "MergeTaskName does not equal the hash-bound integration-attempt task" in adoption
    assert "suite_gated_quiet_merge.ps1" in adoption  # legacy path remains supported


def test_manifest_contract_accepts_canonical_paths_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    attempt_root = tmp_path / "attempt-001"
    repo_root = tmp_path / "repo"
    worktree_root = tmp_path / "worktree"
    attempt_root.mkdir()
    repo_root.mkdir()
    worktree_root.mkdir()
    manifest_path = attempt_root / "manifest.json"
    zeros = "0" * 40
    manifest = {
        "schema": "weather_integration_attempt_manifest_v1",
        "attempt_id": "attempt-001",
        "attempt_root": str(attempt_root),
        "repo_root": str(repo_root),
        "worktree_root": str(worktree_root),
        "branch_ref": "codex/example",
        "expected_tip": "1" * 40,
        "authorization": {"review_reference": "test-review", "repair_class": "initial"},
        "schedule": {
            "suite_at_local": "2026-08-21T00:30:00",
            "merge_at_local": "2026-08-21T01:00:00",
            "suite_task_name": "WeatherIntegrationSuite_attempt-001",
            "merge_task_name": "WeatherIntegrationMerge_attempt-001",
        },
        "suite": {
            "additional_python_path": "",
            "require_live_sdk_contract": False,
            "expected_test_file_count": 40,
            "max_files_per_chunk": 20,
            "expected_chunk_count": 2,
        },
        "baseline": {"master": zeros, "origin_master": zeros},
        "evidence": {
            "preflight_log": str(attempt_root / "preflight.log"),
            "full_suite_log": str(attempt_root / "full-suite.log"),
            "suite_receipt": str(attempt_root / "suite-receipt.json"),
            "merge_receipt": str(attempt_root / "merge-receipt.json"),
            "quiet_merge_report": str(attempt_root / "quiet-merge-report.json"),
            "registration_receipt": str(attempt_root / "registration-receipt.json"),
            "closure_receipt": str(attempt_root / "closure-receipt.json"),
            "recovery_dispatch": str(attempt_root / "recovery-dispatch.json"),
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    env = os.environ.copy()
    env["WEATHER_ATTEMPT_CONTRACT"] = str(SCRIPTS["integration_attempt_contract.ps1"])
    env["WEATHER_ATTEMPT_MANIFEST"] = str(manifest_path)
    env["WEATHER_ATTEMPT_MANIFEST_HASH"] = manifest_hash
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$contract = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $env:WEATHER_ATTEMPT_MANIFEST `
    -ExpectedSha256 $env:WEATHER_ATTEMPT_MANIFEST_HASH
$overwriteRefused = $false
try {
    Write-WeatherIntegrationImmutableJson `
        -Path $env:WEATHER_ATTEMPT_MANIFEST `
        -Payload ([ordered]@{ replaced = $true })
}
catch {
    $overwriteRefused = $_.Exception.Message -like '*will not be replaced*'
}
[pscustomobject]@{
    attempt_id = [string]$contract.Manifest.attempt_id
    overwrite_refused = $overwriteRefused
} | ConvertTo-Json -Compress
"""
    accepted = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert accepted.returncode == 0, accepted.stderr
    assert json.loads(accepted.stdout) == {
        "attempt_id": "attempt-001",
        "overwrite_refused": True,
    }

    manifest["branch_ref"] = "codex/tampered"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    rejected = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "manifest hash mismatch" in rejected.stderr.lower()


def test_immutable_writer_allows_exactly_one_concurrent_claim(tmp_path: Path) -> None:
    target = tmp_path / "claim.json"
    base_env = os.environ.copy()
    base_env["WEATHER_ATTEMPT_CONTRACT"] = str(
        SCRIPTS["integration_attempt_contract.ps1"]
    )
    base_env["WEATHER_ATTEMPT_TARGET"] = str(target)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
Write-WeatherIntegrationImmutableJson `
    -Path $env:WEATHER_ATTEMPT_TARGET `
    -Payload ([ordered]@{ writer = $env:WEATHER_ATTEMPT_WRITER })
"""
    processes = []
    for writer in ("one", "two"):
        env = base_env.copy()
        env["WEATHER_ATTEMPT_WRITER"] = writer
        processes.append(
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
    results = [process.communicate(timeout=30) for process in processes]
    returncodes = [process.returncode for process in processes]
    assert returncodes.count(0) == 1, results
    assert sum(code != 0 for code in returncodes) == 1, results
    assert json.loads(target.read_text(encoding="utf-8"))["writer"] in {"one", "two"}


def test_suite_wait_decision_waits_for_running_task_and_fails_only_at_deadline() -> None:
    env = os.environ.copy()
    env["WEATHER_ATTEMPT_CONTRACT"] = str(SCRIPTS["integration_attempt_contract.ps1"])
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$today = [datetime]'2026-08-21T00:00:00'
$deadline = [datetime]'2026-08-21T03:40:00'
$cases = @(
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Running -LastRunTime $today.AddMinutes(30) -LastTaskResult 267009 -ReceiptExists $false -Now $today.AddHours(1) -Deadline $deadline
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Running -LastRunTime $today.AddMinutes(30) -LastTaskResult 267009 -ReceiptExists $false -Now $deadline -Deadline $deadline
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Ready -LastRunTime $today.AddMinutes(30) -LastTaskResult 0 -ReceiptExists $true -ReceiptStatus PASS -Now $today.AddHours(1) -Deadline $deadline
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Ready -LastRunTime $today.AddMinutes(30) -LastTaskResult 1 -ReceiptExists $true -ReceiptStatus FAIL -Now $today.AddHours(1) -Deadline $deadline
)
@($cases | ForEach-Object { [string]$_.Action }) | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["WAIT", "STOP", "READY", "FAIL"]


def test_log_verdict_helper_executes_and_rejects_false_chunk_ratios(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "suite.log"
    log_path.write_text(
        "2026-08-21 00:30:00  planned chunks=2 files=40 max_files=20\n"
        "2026-08-21 00:45:00  VERDICT: ALL CHUNKS PASSED (2/2); "
        "exact tip eligible for separate reviewed merge\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["WEATHER_ATTEMPT_CONTRACT"] = str(
        SCRIPTS["integration_attempt_contract.ps1"]
    )
    env["WEATHER_ATTEMPT_LOG"] = str(log_path)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$verdict = Get-WeatherIntegrationLogVerdict -Path $env:WEATHER_ATTEMPT_LOG
$chunks = Assert-WeatherIntegrationFullSuiteVerdict -Verdict $verdict -ExpectedChunkCount 2
$plan = Assert-WeatherIntegrationFullSuiteLogPlan `
    -Path $env:WEATHER_ATTEMPT_LOG `
    -ExpectedTestFileCount 40 `
    -ExpectedMaxFilesPerChunk 20 `
    -ExpectedChunkCount 2
$mismatchRejected = $false
try {
    Assert-WeatherIntegrationFullSuiteVerdict `
        -Verdict 'VERDICT: ALL CHUNKS PASSED (1/2); exact tip eligible for separate reviewed merge' | Out-Null
}
catch { $mismatchRejected = $_.Exception.Message -like '*invalid chunk ratio*' }
$zeroRejected = $false
try {
    Assert-WeatherIntegrationFullSuiteVerdict `
        -Verdict 'VERDICT: ALL CHUNKS PASSED (0/0); exact tip eligible for separate reviewed merge' | Out-Null
}
catch { $zeroRejected = $_.Exception.Message -like '*invalid chunk ratio*' }
[pscustomobject]@{
    verdict = $verdict
    chunks = $chunks
    planned_files = $plan.Files
    mismatch_rejected = $mismatchRejected
    zero_rejected = $zeroRejected
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["chunks"] == 2
    assert payload["planned_files"] == 40
    assert payload["verdict"].endswith(
        "VERDICT: ALL CHUNKS PASSED (2/2); "
        "exact tip eligible for separate reviewed merge"
    )
    assert payload["mismatch_rejected"] is True
    assert payload["zero_rejected"] is True


def test_schedule_helper_rejects_invalid_and_ambiguous_eastern_times() -> None:
    env = os.environ.copy()
    env["WEATHER_ATTEMPT_CONTRACT"] = str(
        SCRIPTS["integration_attempt_contract.ps1"]
    )
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$valid = Assert-WeatherIntegrationLocalScheduleTime `
    -Value ([datetime]'2026-08-21T01:30:00') -Label valid -TimeZone $zone
$invalidRejected = $false
try {
    Assert-WeatherIntegrationLocalScheduleTime `
        -Value ([datetime]'2027-03-14T02:30:00') -Label invalid -TimeZone $zone | Out-Null
}
catch { $invalidRejected = $_.Exception.Message -like '*daylight-saving gap*' }
$ambiguousRejected = $false
try {
    Assert-WeatherIntegrationLocalScheduleTime `
        -Value ([datetime]'2026-11-01T01:30:00') -Label ambiguous -TimeZone $zone | Out-Null
}
catch { $ambiguousRejected = $_.Exception.Message -like '*ambiguous daylight-saving hour*' }
[pscustomobject]@{
    valid = $valid.ToString('o')
    invalid_rejected = $invalidRejected
    ambiguous_rejected = $ambiguousRejected
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "valid": "2026-08-21T01:30:00.0000000",
        "invalid_rejected": True,
        "ambiguous_rejected": True,
    }


def test_git_baseline_gate_detects_production_advance(tmp_path: Path) -> None:
    repo_root = tmp_path / "baseline-repo"
    subprocess.run(
        ["git", "init", "--initial-branch=master", str(repo_root)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.name", "Integration Test"],
        check=True,
    )
    marker = repo_root / "marker.txt"
    marker.write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "marker.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", "baseline"],
        check=True,
        capture_output=True,
        text=True,
    )
    baseline = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "master"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "update-ref",
            "refs/remotes/origin/master",
            baseline,
        ],
        check=True,
    )
    env = os.environ.copy()
    env["WEATHER_ATTEMPT_CONTRACT"] = str(SCRIPTS["integration_attempt_contract.ps1"])
    env["WEATHER_ATTEMPT_REPO"] = str(repo_root)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$master = (& git -C $env:WEATHER_ATTEMPT_REPO rev-parse master).Trim().ToLowerInvariant()
$origin = (& git -C $env:WEATHER_ATTEMPT_REPO rev-parse origin/master).Trim().ToLowerInvariant()
$contract = [pscustomobject]@{
    Manifest = [pscustomobject]@{
        repo_root = $env:WEATHER_ATTEMPT_REPO
        baseline = [pscustomobject]@{ master = $master; origin_master = $origin }
    }
}
$pass = Assert-WeatherIntegrationGitBaseline -AttemptContract $contract -Phase test
$contract.Manifest.baseline.master = ('0' * 40)
$failed = $false
try { Assert-WeatherIntegrationGitBaseline -AttemptContract $contract -Phase test | Out-Null }
catch { $failed = $_.Exception.Message -like '*baseline changed after attempt freeze*' }
[pscustomobject]@{ pass = ($pass.Master -eq $master); rejected_advance = $failed } | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"pass": True, "rejected_advance": True}


def test_repair_manifest_requires_exact_single_successor_claim(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    prior_root = tmp_path / "prior"
    current_root = tmp_path / "current"
    prior_worktree = tmp_path / "prior-worktree"
    current_worktree = tmp_path / "current-worktree"
    for path in (repo_root, prior_root, current_root, prior_worktree, current_worktree):
        path.mkdir()

    zeros = "0" * 40
    prior_tip = "1" * 40

    def evidence(root: Path) -> dict[str, str]:
        return {
            "preflight_log": str(root / "preflight.log"),
            "full_suite_log": str(root / "full-suite.log"),
            "suite_receipt": str(root / "suite-receipt.json"),
            "merge_receipt": str(root / "merge-receipt.json"),
            "quiet_merge_report": str(root / "quiet-merge-report.json"),
            "registration_receipt": str(root / "registration-receipt.json"),
            "closure_receipt": str(root / "closure-receipt.json"),
            "recovery_dispatch": str(root / "recovery-dispatch.json"),
        }

    prior_manifest_path = prior_root / "manifest.json"
    prior_manifest = {
        "schema": "weather_integration_attempt_manifest_v1",
        "attempt_id": "prior",
        "attempt_root": str(prior_root),
        "repo_root": str(repo_root),
        "worktree_root": str(prior_worktree),
        "branch_ref": "codex/prior",
        "expected_tip": prior_tip,
        "authorization": {
            "review_reference": "review-prior",
            "repair_class": "initial",
            "repair_of": None,
        },
        "schedule": {
            "suite_at_local": "2026-08-21T00:30:00",
            "merge_at_local": "2026-08-21T01:00:00",
            "suite_task_name": "WeatherIntegrationSuite_prior",
            "merge_task_name": "WeatherIntegrationMerge_prior",
        },
        "suite": {
            "additional_python_path": "",
            "require_live_sdk_contract": False,
            "expected_test_file_count": 40,
            "max_files_per_chunk": 20,
            "expected_chunk_count": 2,
        },
        "baseline": {"master": zeros, "origin_master": zeros},
        "evidence": evidence(prior_root),
    }
    prior_manifest_path.write_text(json.dumps(prior_manifest), encoding="utf-8")
    prior_manifest_hash = hashlib.sha256(prior_manifest_path.read_bytes()).hexdigest()

    closure_path = prior_root / "closure-receipt.json"
    closure = {
        "schema": "weather_integration_attempt_closure_receipt_v1",
        "status": "FAIL",
        "attempt_id": "prior",
        "manifest_path": str(prior_manifest_path),
        "manifest_sha256": prior_manifest_hash,
    }
    closure_path.write_text(json.dumps(closure), encoding="utf-8")
    closure_hash = hashlib.sha256(closure_path.read_bytes()).hexdigest()

    dispatch_path = prior_root / "recovery-dispatch.json"
    dispatch = {
        "schema": "weather_integration_attempt_recovery_dispatch_v1",
        "status": "READY_FOR_SUCCESSOR_REVIEW",
        "repair_class": "retry_unchanged",
        "closure_receipt_path": str(closure_path),
        "closure_receipt_sha256": closure_hash,
    }
    dispatch_path.write_text(json.dumps(dispatch), encoding="utf-8")
    dispatch_hash = hashlib.sha256(dispatch_path.read_bytes()).hexdigest()

    claim_path = prior_root / "successor-claim.json"
    current_manifest_path = current_root / "manifest.json"
    current_manifest = {
        "schema": "weather_integration_attempt_manifest_v1",
        "attempt_id": "current",
        "attempt_root": str(current_root),
        "repo_root": str(repo_root),
        "worktree_root": str(current_worktree),
        "branch_ref": "codex/prior",
        "expected_tip": prior_tip,
        "authorization": {
            "review_reference": "review-current",
            "repair_class": "retry_unchanged",
            "repair_of": {
                "receipt_path": str(closure_path),
                "receipt_sha256": closure_hash,
                "receipt_schema": "weather_integration_attempt_closure_receipt_v1",
                "prior_attempt_id": "prior",
                "claim_path": str(claim_path),
                "dispatch_path": str(dispatch_path),
                "dispatch_sha256": dispatch_hash,
            },
        },
        "schedule": {
            "suite_at_local": "2026-08-21T00:30:00",
            "merge_at_local": "2026-08-21T01:00:00",
            "suite_task_name": "WeatherIntegrationSuite_current",
            "merge_task_name": "WeatherIntegrationMerge_current",
        },
        "suite": {
            "additional_python_path": "",
            "require_live_sdk_contract": False,
            "expected_test_file_count": 40,
            "max_files_per_chunk": 20,
            "expected_chunk_count": 2,
        },
        "baseline": {"master": zeros, "origin_master": zeros},
        "evidence": evidence(current_root),
    }
    current_manifest_path.write_text(json.dumps(current_manifest), encoding="utf-8")
    current_manifest_hash = hashlib.sha256(current_manifest_path.read_bytes()).hexdigest()
    claim = {
        "schema": "weather_integration_attempt_successor_claim_v1",
        "status": "CLAIMED",
        "predecessor_receipt_path": str(closure_path),
        "predecessor_receipt_sha256": closure_hash,
        "recovery_dispatch_path": str(dispatch_path),
        "recovery_dispatch_sha256": dispatch_hash,
        "successor_manifest_path": str(current_manifest_path),
        "successor_manifest_sha256": current_manifest_hash,
        "successor_attempt_id": "current",
        "successor_expected_tip": prior_tip,
        "repair_class": "retry_unchanged",
    }
    claim_path.write_text(json.dumps(claim), encoding="utf-8")

    env = os.environ.copy()
    env["WEATHER_ATTEMPT_CONTRACT"] = str(SCRIPTS["integration_attempt_contract.ps1"])
    env["WEATHER_ATTEMPT_MANIFEST"] = str(current_manifest_path)
    env["WEATHER_ATTEMPT_MANIFEST_HASH"] = current_manifest_hash
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$result = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $env:WEATHER_ATTEMPT_MANIFEST `
    -ExpectedSha256 $env:WEATHER_ATTEMPT_MANIFEST_HASH
[string]$result.Manifest.attempt_id
"""
    accepted = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert accepted.returncode == 0, accepted.stderr
    assert accepted.stdout.strip() == "current"

    claim["successor_expected_tip"] = "2" * 40
    claim_path.write_text(json.dumps(claim), encoding="utf-8")
    rejected = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "successor claim does not bind" in rejected.stderr.lower()


def test_creator_rejects_equal_tree_commit_and_claims_one_exact_retry(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    worktree_root = tmp_path / "candidate-worktree"
    attempt_parent = tmp_path / "attempts"
    repo_root.mkdir()
    attempt_parent.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=master", str(repo_root)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.name", "Integration Test"],
        check=True,
    )
    temp_ops = repo_root / "scripts" / "ops"
    temp_ops.mkdir(parents=True)
    required = (
        "integration_attempt_contract.ps1",
        "new_integration_attempt.ps1",
        "register_integration_attempt.ps1",
        "close_integration_attempt.ps1",
        "bounded_worktree_test_suite.ps1",
        "integration_attempt_suite.ps1",
        "integration_attempt_merge.ps1",
        "assert_integration_attempt_success.ps1",
        "dispatch_integration_attempt_recovery.ps1",
        "quiet_window_merge.ps1",
        "training_window_contract.ps1",
        "windows_kill_on_close_job.ps1",
        "workload_admission.ps1",
        "roll_verdict.ps1",
    )
    for name in required:
        shutil.copy2(OPS / name, temp_ops / name)
    temp_tests = repo_root / "tests"
    temp_tests.mkdir()
    (temp_tests / "test_example.py").write_text(
        "def test_example():\n    assert True\n", encoding="utf-8"
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "add", "scripts", "tests"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", "baseline"],
        check=True,
        capture_output=True,
        text=True,
    )
    baseline = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "update-ref",
            "refs/remotes/origin/master",
            baseline,
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "branch", "candidate", baseline],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", str(worktree_root), "candidate"],
        check=True,
        capture_output=True,
        text=True,
    )

    def creator_command(attempt_id: str, tip: str, repair: bool = False) -> list[str]:
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPTS["new_integration_attempt.ps1"]),
            "-RepoRoot",
            str(repo_root),
            "-AttemptRoot",
            str(attempt_parent / attempt_id),
            "-AttemptId",
            attempt_id,
            "-BranchRef",
            "candidate",
            "-WorktreeRoot",
            str(worktree_root),
            "-ExpectedTip",
            tip,
            "-SuiteAtLocal",
            "2026-08-21T00:30:00",
            "-MergeAtLocal",
            "2026-08-21T01:00:00",
            "-ReviewReference",
            f"review-{attempt_id}",
        ]
        if repair:
            command.extend(
                [
                    "-RepairClass",
                    "retry_unchanged",
                    "-RepairOfReceiptPath",
                    str(attempt_parent / "prior" / "closure-receipt.json"),
                ]
            )
        return command

    prior = subprocess.run(
        creator_command("prior", baseline),
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert prior.returncode == 0, prior.stderr
    prior_manifest_path = attempt_parent / "prior" / "manifest.json"
    prior_manifest_hash = hashlib.sha256(prior_manifest_path.read_bytes()).hexdigest()
    closure_path = attempt_parent / "prior" / "closure-receipt.json"
    closure = {
        "schema": "weather_integration_attempt_closure_receipt_v1",
        "status": "FAIL",
        "attempt_id": "prior",
        "manifest_path": str(prior_manifest_path),
        "manifest_sha256": prior_manifest_hash,
    }
    closure_path.write_text(json.dumps(closure), encoding="utf-8")
    closure_hash = hashlib.sha256(closure_path.read_bytes()).hexdigest()
    dispatch_path = attempt_parent / "prior" / "recovery-dispatch.json"
    dispatch = {
        "schema": "weather_integration_attempt_recovery_dispatch_v1",
        "status": "READY_FOR_SUCCESSOR_REVIEW",
        "repair_class": "retry_unchanged",
        "closure_receipt_path": str(closure_path),
        "closure_receipt_sha256": closure_hash,
    }
    dispatch_path.write_text(json.dumps(dispatch), encoding="utf-8")

    subprocess.run(
        ["git", "-C", str(worktree_root), "commit", "--allow-empty", "-m", "empty"],
        check=True,
        capture_output=True,
        text=True,
    )
    empty_tip = subprocess.run(
        ["git", "-C", str(worktree_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    equal_tree = subprocess.run(
        creator_command("equal-tree", empty_tip, repair=True),
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert equal_tree.returncode != 0
    assert "exact same commit id" in equal_tree.stderr.lower()

    subprocess.run(
        ["git", "-C", str(worktree_root), "reset", "--hard", baseline],
        check=True,
        capture_output=True,
        text=True,
    )
    accepted = subprocess.run(
        creator_command("retry", baseline, repair=True),
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert accepted.returncode == 0, accepted.stderr
    assert (attempt_parent / "prior" / "successor-claim.json").is_file()

    sibling = subprocess.run(
        creator_command("retry-sibling", baseline, repair=True),
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert sibling.returncode != 0
    assert "already has a successor claim" in sibling.stderr.lower()


def test_integration_attempt_powershell_sources_parse_without_execution() -> None:
    env = os.environ.copy()
    env["WEATHER_INTEGRATION_ATTEMPT_SCRIPTS"] = os.pathsep.join(
        str(path) for path in PARSE_SCRIPTS
    )
    script = r"""
$ErrorActionPreference = 'Stop'
$paths = @($env:WEATHER_INTEGRATION_ATTEMPT_SCRIPTS.Split([IO.Path]::PathSeparator))
$allErrors = @()
$operatorParameters = @()
$operatorNames = @(
    'split', 'replace', 'match', 'notmatch', 'like', 'notlike', 'eq', 'ne',
    'gt', 'ge', 'lt', 'le', 'join', 'contains', 'notcontains', 'in', 'notin',
    'is', 'isnot', 'as', 'f', 'shl', 'shr', 'band', 'bor', 'bxor'
)
foreach ($path in $paths) {
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        $path,
        [ref]$tokens,
        [ref]$errors
    )
    foreach ($item in @($errors)) {
        $allErrors += [pscustomobject]@{ path = $path; message = $item.Message }
    }
    $badParameters = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.CommandParameterAst] -and
            $operatorNames -contains $node.ParameterName.ToLowerInvariant()
    }, $true))
    foreach ($item in $badParameters) {
        $operatorParameters += [pscustomobject]@{
            path = $path
            line = $item.Extent.StartLineNumber
            parameter = $item.ParameterName
        }
    }
}
[pscustomobject]@{
    errors = $allErrors
    operator_parameters = $operatorParameters
} | ConvertTo-Json -Depth 5 -Compress
"""
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["errors"] == []
    assert payload["operator_parameters"] == []
