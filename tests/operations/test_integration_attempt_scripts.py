import json
import hashlib
import os
from pathlib import Path
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
        "assert_integration_attempt_success.ps1",
    )
}


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
    assert "schema_registry_data" in creator
    assert "module-ownership-map" in creator
    assert "manual_reviewed_change" in creator
    assert "retry_unchanged" in creator
    assert "An unchanged retry may not follow another unchanged retry" in creator
    assert "suite_at_local" in creator
    assert "merge_at_local" in creator
    assert "quiet_merge_report" in creator
    assert "git reset" not in creator.lower()
    assert "git push" not in creator.lower()

    closer = _text("close_integration_attempt.ps1")
    assert "Attempt task is still running" in closer
    assert "Disable-ScheduledTask" in closer
    assert "A successfully merged attempt cannot be abandoned" in closer
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
    assert "weather_integration_attempt_suite_receipt_v1" in (
        _text("integration_attempt_contract.ps1")
    )
    assert "Write-WeatherIntegrationImmutableJson -Path $suiteReceiptPath" in suite
    assert "git merge" not in suite.lower()
    assert "git push" not in suite.lower()


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
    assert "documentation transaction recorded" in merge
    assert "merge-base --is-ancestor" in merge
    assert "capture_recovery_check" in merge
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


def test_execution_tape_adoption_accepts_only_hash_bound_attempt_receipts() -> None:
    adoption = (OPS / "adopt_execution_tape_after_merge.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert "integration_attempt_merge.ps1" in adoption
    assert "AttemptManifestPath" in adoption
    assert "ExpectedManifestSha256" in adoption
    assert "ExpectedMergeReceiptSha256" in adoption
    assert "assert_integration_attempt_success.ps1" in adoption
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
        "baseline": {"master": zeros, "origin_master": zeros},
        "evidence": {
            "preflight_log": str(attempt_root / "preflight.log"),
            "full_suite_log": str(attempt_root / "full-suite.log"),
            "suite_receipt": str(attempt_root / "suite-receipt.json"),
            "merge_receipt": str(attempt_root / "merge-receipt.json"),
            "quiet_merge_report": str(attempt_root / "quiet-merge-report.json"),
            "registration_receipt": str(attempt_root / "registration-receipt.json"),
            "closure_receipt": str(attempt_root / "closure-receipt.json"),
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


def test_integration_attempt_powershell_sources_parse_without_execution() -> None:
    env = os.environ.copy()
    env["WEATHER_INTEGRATION_ATTEMPT_SCRIPTS"] = os.pathsep.join(
        str(path) for path in SCRIPTS.values()
    )
    env["WEATHER_INTEGRATION_BOUNDED_SCRIPT"] = str(
        OPS / "bounded_worktree_test_suite.ps1"
    )
    env["WEATHER_INTEGRATION_ADOPTION_SCRIPT"] = str(
        OPS / "adopt_execution_tape_after_merge.ps1"
    )
    script = r"""
$ErrorActionPreference = 'Stop'
$paths = @($env:WEATHER_INTEGRATION_ATTEMPT_SCRIPTS.Split([IO.Path]::PathSeparator))
$paths += $env:WEATHER_INTEGRATION_BOUNDED_SCRIPT
$paths += $env:WEATHER_INTEGRATION_ADOPTION_SCRIPT
$allErrors = @()
foreach ($path in $paths) {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        $path,
        [ref]$tokens,
        [ref]$errors
    )
    foreach ($item in @($errors)) {
        $allErrors += [pscustomobject]@{ path = $path; message = $item.Message }
    }
}
[pscustomobject]@{ errors = $allErrors } | ConvertTo-Json -Depth 5 -Compress
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
    assert json.loads(result.stdout)["errors"] == []
