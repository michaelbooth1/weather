"""Native first-landing containment and irreversible-boundary refusal fixtures.

All roots are disposable. Scheduler, production identity and capture resources
are fixture observations; these tests never register or start an actual task.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess

import pytest

from weather.operations.qualification import records
from test_qualification_native_job import run, ps_literal, HELPER
from test_qualification_bootstrap_install import installation
from test_qualification_bootstrap import envelope
from test_qualification_evidence import bundle
from test_qualification_merge_tree import merge_fixture, stage

pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows bootstrap boundaries")
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("readoption", [False, True])
def test_guarded_monitor_keeps_native_containment_during_expected_capture_generation_change(tmp_path, readoption):
    (tmp_path / "child.py").write_text("import time\ntime.sleep(0.35)\nprint('guarded fixture finished')\n", encoding="utf-8")
    # Fixture-only host telemetry: the native Job/child/EOF/accounting remain
    # real. Hosted CI is not this repository's assigned capture installation.
    body = r'''
Add-Type -TypeDefinition @'
namespace Weather.Operations {
    public sealed class QualificationSystemResources {
        public ulong CommittedBytes=2147483648, CommitLimitBytes=17179869184, PhysicalAvailableBytes=8589934592;
        public static QualificationSystemResources Read() { return new QualificationSystemResources(); }
    }
}
'@
''' + ". " + ps_literal(HELPER.parent / "qualification_process.ps1") + "\n" + r'''
function Assert-WeatherQualificationDisk {param($VolumePaths,$MinimumFreeBytes,$ReservedScratchBytes) return [UInt64]107374182400}
$script:captureReads=0
function Assert-WeatherQualificationCapture {
    param($ProductionRoot,$Bindings)
    $script:captureReads++
    if($script:captureReads -gt 1) {throw 'fixture capture generation intentionally changed'}
}
$envelope=[Weather.Operations.KillOnCloseJob]::EncloseCurrentProcess(536870912,32)
try {
    $options=@{
        Envelope=$envelope;Executable=$python;Tokens=@('-u',(Join-Path $root 'child.py'));WorkingDirectory=$root
        Transcript=(Join-Path $root 'output.log');DeadlineUtc=[DateTimeOffset]::UtcNow.AddSeconds(15)
        MaximumSeconds=3;TeardownSeconds=5;CommitBytes=[UInt64]536870912;WorkingSetBytes=[UInt64]536870912
        MaximumOutputBytes=4096;VolumePaths=@($root);MinimumDiskBytes=[UInt64]53687091200;MaximumReadBytes=[UInt64]2147483648
        ResourceMode='capture_s4u';ProductionRoot=$root;CaptureBindings=@(1,2,3)
    }
''' + ("    $options.GuardedCaptureReadoption=$true\n" if readoption else "") + r'''
    $result=Invoke-WeatherQualificationProcess @options
    if(-not $result.teardown_proved -or $envelope.Snapshot().ProcessIds.Count -ne 1) {throw 'guarded monitor leaked descendants'}
    if($result.resource_samples -le 0 -or $result.native_peak_commit_bytes -le 0) {throw 'resource monitor did not run'}
    [IO.File]::WriteAllText((Join-Path $root 'result.json'),($result | ConvertTo-Json))
} finally {$envelope.Dispose()}
'''
    run(tmp_path, body)
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8-sig"))
    assert result["completed"] is readoption
    if not readoption:
        assert "generation intentionally changed" in result["failure"]


def test_guarded_monitor_rejects_offhost_readoption_and_unapproved_long_audit(tmp_path):
    (tmp_path / "child.py").write_text("raise RuntimeError('must not launch')\n", encoding="utf-8")
    body = ". " + ps_literal(HELPER.parent / "qualification_process.ps1") + "\n" + r'''
$envelope=[Weather.Operations.KillOnCloseJob]::EncloseCurrentProcess(536870912,32)
try {
    $options=@{
        Envelope=$envelope;Executable=$python;Tokens=@('-u',(Join-Path $root 'child.py'));WorkingDirectory=$root
        Transcript=(Join-Path $root 'output.log');DeadlineUtc=[DateTimeOffset]::UtcNow.AddSeconds(15)
        MaximumSeconds=3;TeardownSeconds=5;CommitBytes=[UInt64]536870912;WorkingSetBytes=[UInt64]536870912
        MaximumOutputBytes=4096;VolumePaths=@($root);MinimumDiskBytes=[UInt64]1
    }
    foreach($fault in @('readoption','long-audit')) {
        if($fault -eq 'readoption') {$options.GuardedCaptureReadoption=$true}
        else {$options.Remove('GuardedCaptureReadoption');$options.MaximumSeconds=1201}
        $refused=$false
        try {$null=Invoke-WeatherQualificationProcess @options} catch {$refused=$true}
        if(-not $refused -or $envelope.Snapshot().ProcessIds.Count -ne 1) {throw 'unapproved monitor mode ran a child'}
    }
} finally {$envelope.Dispose()}
'''
    run(tmp_path, body)
    assert not (tmp_path / "output.log").exists()


def test_actual_marker_uses_legacy_boot_safe_sentinel_only_while_commit_is_ambiguous(merge_fixture, tmp_path):
    fixture = merge_fixture
    _, repo, baseline, candidate, _, _, _, _, git = fixture
    prepared = stage(fixture)
    git("commit", "-qm", "native marker fixture")
    merged = git("rev-parse", "HEAD")
    script = tmp_path / "marker.ps1"
    script.write_text("$ErrorActionPreference='Stop'\nSet-StrictMode -Off\n$source=" +
        ps_literal(ROOT / "scripts/ops/quiet_window_merge.ps1") + "\n" + r'''
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$tokens,[ref]$errors)
$function=$ast.Find({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -ceq 'Write-QuietMergeMarker'},$true)
Invoke-Expression $function.Extent.Text
''' + "\n$repo=" + ps_literal(repo) + "\n$baselineCommit=" + ps_literal(baseline) +
        "\n$ExpectedBaseline=$baselineCommit\n$ExpectedTip=" + ps_literal(candidate) +
        "\n$resolvedBranchTip=$ExpectedTip\n$preMerge=" + ps_literal(prepared) +
        "\n$Branch='candidate'\n$activeMarkerPath=" + ps_literal(tmp_path / "marker.json") + r'''
$bootstrapInstallation=$true;$splitQualification=$true;$productionBaselineReconciliationMode=$false
$qualificationCommitAttempted=$true
$rollbackContentSha256=[ordered]@{}
$mergeCommit=$null
Write-QuietMergeMarker -Phase 'qualification_commit_invoked'
$marker=Get-Content -LiteralPath $activeMarkerPath -Raw | ConvertFrom-Json
if($marker.pre_merge_commit -cne $ExpectedTip -or $marker.bootstrap_installation.prepared_baseline -cne $preMerge) {
    throw 'ambiguous commit exposed a hard-reset preparation parent'
}
''' + "\n$mergeCommit=" + ps_literal(merged) + r'''
Write-QuietMergeMarker -Phase 'merge_committed_unpublished'
$marker=Get-Content -LiteralPath $activeMarkerPath -Raw | ConvertFrom-Json
if($marker.pre_merge_commit -cne $preMerge -or $marker.merge_commit -cne $mergeCommit) {
    throw 'proved commit did not restore normal recovery identity'
}
''', encoding="utf-8")
    ps = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(ps), "-NoProfile", "-NonInteractive", "-File", str(script)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    # B's actual Git predicate cannot trust K as a generated-config child.
    assert "module.py" in git("diff", "--name-only", baseline, candidate).splitlines()


@pytest.fixture
def completed_installation(installation):
    root, value = installation
    work = root / "install-work"
    work.mkdir()
    proofs = {}
    envelope_sha, merged = "f" * 64, "f" * 40
    for phase in ("prepare", "prepared", "before-stage", "staged", "before-commit", "committed", "before-push", "published"):
        directory = work / "merge-work" / phase
        directory.mkdir(parents=True)
        boundary = records.publish(directory, "boundary.json", {
            "schema": "qualification_bootstrap_install_boundary_v1", "phase": phase, "envelope_sha256": envelope_sha,
            "effective_tree": value["effective_tree"], "head": merged})
        native = records.publish(directory, "native.json",
            {"completed": True, "teardown_proved": True, "exit_code": 0, "failure": None})
        proofs[phase] = {key: {**ref, "path": f"merge-work/{phase}/{ref['path']}"} for key, ref in (("boundary", boundary), ("native", native))}
    native = {"schema": "qualification_bootstrap_install_native_result_v1", "envelope_sha256": envelope_sha,
        "native_read_bytes": 1, "native": {"completed": True, "teardown_proved": True, "exit_code": 0, "failure": None,
                                        "native_peak_commit_bytes": 1, "peak_working_set_bytes": 1}}
    quiet = {"schema": "qualification_bootstrap_install_quiet_native_v1", "envelope_sha256": envelope_sha,
             "children_zero": True, "native_read_bytes": 1, "native_peak_commit_bytes": 1}
    report = {"schema": "quiet_window_merge_report_v0.2", "operation_mode": "bootstrap_installation_v1",
        "ok": True, "stage": "pushed", "publication_acknowledged": True, "capture_recovery_proved": True,
        "documentation_transaction_recorded": True, "expected_baseline": value["baseline"], "baseline_commit": value["baseline"],
        "expected_tip": value["source"]["commit"], "resolved_branch_tip": value["source"]["commit"],
        "branch": value["branch_ref"], "merge_commit": merged,
        "bootstrap_installation": {"manifest_sha256": envelope_sha, "commit_invocation_started": True,
                                  "capture": {"ok": True, "workers": [{"ok": True} for _ in range(3)]}, "boundaries": proofs}}
    fixture = root / "completion-fixture.json"
    fixture.write_text(json.dumps({"envelope": value, "sha256": envelope_sha, "native": native, "quiet": quiet, "report": report}),
                       encoding="utf-8")
    return root, fixture


def test_native_completion_rejects_unacknowledged_wrong_tree_and_unproved_teardown(completed_installation):
    root, fixture = completed_installation
    ps = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = root / "completion.ps1"
    script.write_text("$ErrorActionPreference='Stop'\n. " +
        ps_literal(ROOT / "scripts/ops/workload_admission.ps1") + "\n. " +
        ps_literal(ROOT / "scripts/ops/qualification_bootstrap_install_contract.ps1") +
        "\n$fixture=" + ps_literal(fixture) + "\n" + r'''
function LoadFixture {return (Get-Content -LiteralPath $fixture -Raw | ConvertFrom-Json)}
$value=LoadFixture
Assert-WeatherBootstrapInstallCompletion $value.envelope $value.sha256 $value.native $value.quiet $value.report
foreach($fault in @('no-teardown','string-teardown','string-exit','no-publication','local-only','wrong-K','wrong-tree','missing-boundary','reads')) {
    $value=LoadFixture
    switch($fault) {
        'no-teardown' {$value.native.native.teardown_proved=$false}
        'string-teardown' {$value.native.native.teardown_proved='true'}
        'string-exit' {$value.native.native.exit_code='0'}
        'no-publication' {$value.report.publication_acknowledged=$false}
        'local-only' {$value.report.stage='merged_unpushed'}
        'wrong-K' {$value.report.expected_tip='e'*40}
        'wrong-tree' {$value.envelope.effective_tree='a'*40}
        'missing-boundary' {$value.report.bootstrap_installation.boundaries.PSObject.Properties.Remove('before-commit')}
        'reads' {$value.native.native_read_bytes=[long]$value.envelope.limits.read_bytes+1}
    }
    $refused=$false
    try {Assert-WeatherBootstrapInstallCompletion $value.envelope $value.sha256 $value.native $value.quiet $value.report} catch {$refused=$true}
    if(-not $refused) {throw ('invalid native installation accepted: '+$fault)}
}
''', encoding="utf-8")
    result = subprocess.run([str(ps), "-NoProfile", "-NonInteractive", "-File", str(script)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
