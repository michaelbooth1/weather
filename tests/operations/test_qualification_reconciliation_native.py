"""Execute native split recovery readers and actual evidence retention paths."""

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from test_qualification_arming_native import values


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.name != "nt", reason="native PowerShell recovery contracts")


def invoke(tmp_path, body):
    literal = lambda value: "'" + str(value).replace("'", "''") + "'"
    path = tmp_path / "invoke.ps1"
    path.write_text("$ErrorActionPreference='Stop'\n$root=" + literal(ROOT) + "\n$fixture=" + literal(tmp_path) + "\n"
        ". (Join-Path $root 'scripts/ops/integration_attempt_contract.ps1')\n"
        ". (Join-Path $root 'scripts/ops/qualification_reconcile_contract.ps1')\n"
        "$v=Get-Content -LiteralPath (Join-Path $fixture 'fixture.json') -Raw | ConvertFrom-Json\n"
        "$contract=$v.contract\n" + body, encoding="utf-8")
    exe = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(exe), "-NoProfile", "-NonInteractive", "-File", str(path)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def fixture(tmp_path, *, kind="QuietReport"):
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    production = tmp_path / "production"
    (production / "data/alerts").mkdir(parents=True)
    path = production / "data/alerts/quiet_window_merge_in_progress.json" if kind == "ActiveMarker" else attempt / "quiet-merge-report.json"
    contract = {"ManifestPath": str(attempt / "manifest.json"), "ManifestSha256": "a" * 64,
        "AttemptRoot": str(attempt), "Manifest": {"schema": "weather_integration_attempt_manifest_v2", "qualification_mode": "split_v2",
        "attempt_id": "fixture", "repo_root": str(production), "branch_ref": "codex/fixture", "expected_tip": "b" * 40,
        "baseline": {"master": "c" * 40}, "schedule": {"host_task_name": "WeatherIntegrationHost_fixture", "host_at_local": "2026-09-15T00:35:00"},
        "evidence": {"quiet_merge_report": str(attempt / "quiet-merge-report.json"), "merge_receipt": str(attempt / "merge-receipt.json")}}}
    report = {"schema": "quiet_window_merge_in_progress_v0.1" if kind == "ActiveMarker" else "quiet_window_merge_report_v0.2",
        "operation_mode": "split_qualification_v2", "repo_root": str(production), "branch": "codex/fixture",
        "expected_tip": "b" * 40, "resolved_branch_tip": "b" * 40, "expected_baseline": "c" * 40,
        "baseline_commit": "c" * 40, "pre_merge_commit": "d" * 40, "execution_tape_recovery_required": False,
        "qualification" if kind == "ActiveMarker" else "split_qualification": {
            "manifest_path": contract["ManifestPath"], "manifest_sha256": "a" * 64, "commit_invocation_started": True}}
    return contract, report, path


@pytest.mark.parametrize("kind", ["QuietReport", "ActiveMarker", "MergeReceipt"])
def test_exact_ambiguous_evidence_requires_no_fictional_completed_commit(tmp_path, kind):
    contract, report, path = fixture(tmp_path, kind=kind)
    path.write_text(json.dumps(report), encoding="utf-8")
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    if kind == "MergeReceipt":
        path = Path(contract["Manifest"]["evidence"]["merge_receipt"])
        path.write_text(json.dumps({"schema": "weather_integration_attempt_merge_receipt_v2", "status": "COMMIT_UNVERIFIED",
            "manifest_sha256": "a" * 64, "attempt_id": "fixture", "source_tip": "b" * 40, "branch_ref": "codex/fixture",
            "quiet_merge_report": {"path": contract["Manifest"]["evidence"]["quiet_merge_report"], "sha256": expected}}), encoding="utf-8")
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / "fixture.json").write_text(json.dumps({"contract": contract, "kind": kind, "sha256": expected}), encoding="utf-8")
    invoke(tmp_path, r'''
$result=Read-WeatherQualificationCommitEvidence -AttemptContract $contract -Kind $v.kind -ExpectedSha256 $v.sha256
if($result.PreparedBaseline -cne ('d'*40)){throw 'wrong prepared baseline'}
$refused=$false
try{Assert-WeatherQualificationNoCommitClaim -AttemptContract $contract}catch{$refused=$true}
if(-not $refused){throw 'ambiguous commit permitted ordinary retry'}
''')


@pytest.mark.parametrize("fault", ["source", "baseline", "manifest", "boolean", "schema", "hash", "not-started"])
def test_commit_evidence_rejects_unbound_or_untyped_history(tmp_path, fault):
    contract, report, path = fixture(tmp_path)
    if fault == "source": report["expected_tip"] = "e" * 40
    if fault == "baseline": report["baseline_commit"] = "e" * 40
    if fault == "manifest": report["split_qualification"]["manifest_sha256"] = "e" * 64
    if fault == "boolean": report["split_qualification"]["commit_invocation_started"] = "true"
    if fault == "schema": report["operation_mode"] = "production_baseline_reconciliation_v0.1"
    if fault == "not-started": report["split_qualification"]["commit_invocation_started"] = False
    path.write_text(json.dumps(report), encoding="utf-8")
    expected = "e" * 64 if fault == "hash" else hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / "fixture.json").write_text(json.dumps({"contract": contract, "sha256": expected}), encoding="utf-8")
    invoke(tmp_path, r'''
$refused=$false
try{Read-WeatherQualificationCommitEvidence -AttemptContract $contract -Kind QuietReport -ExpectedSha256 $v.sha256 | Out-Null}catch{$refused=$true}
if(-not $refused){throw 'invalid commit evidence accepted'}
''')


def test_marker_retirement_keeps_original_bytes_and_is_idempotent(tmp_path):
    contract, report, path = fixture(tmp_path, kind="ActiveMarker")
    raw = (json.dumps(report, indent=2) + "\n").encode()
    path.write_bytes(raw)
    destination = Path(contract["AttemptRoot"]) / "reconciliations" / ("f" * 64)
    destination.mkdir(parents=True)
    (tmp_path / "fixture.json").write_text(json.dumps({"contract": contract, "receipt": {
        "marker": {"sha256": hashlib.sha256(raw).hexdigest()}, "observation": "reconciliations/" + "f" * 64}}), encoding="utf-8")
    invoke(tmp_path, r'''
Move-WeatherQualificationReconciledMarker -AttemptContract $contract -Receipt $v.receipt
Move-WeatherQualificationReconciledMarker -AttemptContract $contract -Receipt $v.receipt
''')
    assert not path.exists()
    assert (destination / "retired-marker.json").read_bytes() == raw


@pytest.mark.parametrize("fault", ["valid", "children", "memory", "disk", "elapsed", "authority", "manifest", "string-bool"])
def test_terminal_native_bounds_cannot_upgrade_historical_authority(tmp_path, fault):
    contract, _, _ = fixture(tmp_path)
    value = values()
    current = {"schema": "qualification_terminal_current_v2", "manifest_sha256": "1" * 64,
        "disposition": "PUBLISHED_CURRENT", "native_parent_completion_required": True,
        "historical_proof_upgraded": False, "downstream_authorized": False}
    if fault == "children": value["native"]["teardown_proved"] = False
    if fault == "memory": value["native"]["native_peak_commit_bytes"] = 1001
    if fault == "disk": value["native"]["minimum_disk_bytes"] = 9999
    if fault == "elapsed": value["native"]["elapsed_ms"] = 120001
    if fault == "authority": current["downstream_authorized"] = True
    if fault == "manifest": current["manifest_sha256"] = "a" * 64
    if fault == "string-bool": current["historical_proof_upgraded"] = "false"
    value.update(contract=contract, current=current)
    (tmp_path / "fixture.json").write_text(json.dumps(value), encoding="utf-8")
    invoke(tmp_path, r'''
$refused=$false
try{Assert-WeatherQualificationTerminalNative -State $v.state -Current $v.current -Native $v.native}catch{$refused=$true}
''' + ("if($refused){throw 'valid current observation refused'}" if fault == "valid" else "if(-not $refused){throw 'invalid native proof accepted'}"))


def test_split_publication_resume_refuses_before_any_native_or_scheduler_work(tmp_path):
    contract, _, _ = fixture(tmp_path)
    (tmp_path / "fixture.json").write_text(json.dumps({"contract": contract}), encoding="utf-8")
    invoke(tmp_path, r'''
$refused=$false
try{Invoke-WeatherQualificationReconciliation -AttemptContract $contract -Kind QuietReport -ExpectedSha256 ('a'*64) -ReviewReference fixture -ResumePublication}
catch{if($_.Exception.Message -notlike '*no commit or publication authority*'){throw};$refused=$true}
if(-not $refused){throw 'reconciliation attempted publication'}
''')


@pytest.mark.parametrize("fault", ["valid", "python", "git", "powershell", "gh", "environment", "platform"])
def test_native_launch_pins_are_checked_before_running_the_selected_interpreter(tmp_path, fault):
    contract, _, _ = fixture(tmp_path)
    expected = {"schema": "qualification_environment_v2", "platform": "windows",
        "python": {"executable_sha256": "1" * 64}, "git": {"sha256": "2" * 64}, "powershell": {"sha256": "3" * 64}}
    if fault == "platform": expected["platform"] = "linux"
    path = tmp_path / "environment.json"
    path.write_text(json.dumps(expected), encoding="utf-8")
    ref = {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size}
    profile = {"schema": "qualification_host_environment_v2", "environment": dict(ref),
        "tools": {name: {"sha256": digit * 64} for name, digit in (("python", "1"), ("git", "2"), ("powershell", "3"), ("gh", "4"))}}
    if fault in profile["tools"]: profile["tools"][fault]["sha256"] = "e" * 64
    if fault == "environment": profile["environment"]["sha256"] = "e" * 64
    value = {"contract": contract, "profile": profile, "review": {"environments": {"windows": ref}}, "policy": {"verifier": {"gh_sha256": "4" * 64}}}
    (tmp_path / "fixture.json").write_text(json.dumps(value), encoding="utf-8")
    invoke(tmp_path, r'''
$refused=$false
try{Assert-WeatherQualificationNativeToolPins -Profile $v.profile -Policy $v.policy -Review $v.review -GraphRoot $fixture}catch{$refused=$true}
''' + ("if($refused){throw 'qualified tools rejected'}" if fault == "valid" else "if(-not $refused){throw 'unqualified executable may launch'}"))