"""Execute actual lifecycle functions with inert native/Scheduler boundaries."""

import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.name != "nt", reason="native PowerShell lifecycle")


def run(tmp_path, body):
    literal = lambda value: "'" + str(value).replace("'", "''") + "'"
    script = tmp_path / "lifecycle.ps1"
    script.write_text("$ErrorActionPreference='Stop'\n$root=" + literal(ROOT) + "\n"
                      ". (Join-Path $root 'scripts/ops/integration_attempt_contract.ps1')\n" + body, encoding="utf-8")
    executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-File", str(script)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_split_child_receives_exact_manifest_and_proves_void_native_teardown(tmp_path):
    run(tmp_path, r'''
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'scripts/ops/integration_attempt_merge.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count) { throw ($errors | Out-String) }
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Invoke-WeatherQuietMergeChild'},$true)
Invoke-Expression $function.Extent.Text
$SettleSeconds=300
$script:disposed=0; $script:terminated=0; $script:launched=''
function ConvertTo-ScheduledTaskArgumentString($Tokens) { ConvertTo-WeatherIntegrationScheduledTaskArgumentString -Tokens $Tokens }
function New-WeatherKillOnCloseJob {
    $job=[pscustomobject]@{}
    $job | Add-Member ScriptMethod TerminateAndWait { param($Milliseconds) if($Milliseconds -ne 3000){throw 'wrong teardown budget'}; $script:terminated++ }
    $job | Add-Member ScriptMethod Snapshot { [pscustomobject]@{ProcessIds=@()} }
    $job | Add-Member ScriptMethod Dispose { $script:disposed++ }
    return $job
}
function Start-WeatherProcessInJob($Job,$FilePath,$ArgumentString,$WorkingDirectory) {
    $script:launched=$ArgumentString
    $process=[pscustomobject]@{HasExited=$true;ExitCode=0}
    $process | Add-Member ScriptMethod WaitForExit { }
    $process | Add-Member ScriptMethod Dispose { $script:disposed++ }
    return $process
}
$contract=[pscustomobject]@{ManifestPath='C:\fixture with spaces\manifest.json';ManifestSha256=('b'*64)}
$parameters=@{QuietMergeScript='C:\baseline\quiet_window_merge.ps1';PowerShellExecutable='C:\Windows\powershell.exe'
    RepoRoot='C:\production';Branch='origin/codex/fixture';ExpectedTip=('a'*40);ExpectedBaseline=('c'*40)
    AttemptReportPath='C:\attempt\quiet-merge-report.json';ExpectedQuietMergeSha256=('d'*64);SplitContract=$contract}
if((Invoke-WeatherQuietMergeChild @parameters) -ne 0){throw 'successful void teardown was treated as failure'}
if($script:terminated -ne 1 -or $script:disposed -ne 2){throw 'native ownership not closed exactly once'}
if($script:launched -notlike '*-QualificationManifestPath "C:\fixture with spaces\manifest.json"*' -or
   $script:launched -notlike ('*-QualificationManifestSha256 '+('b'*64)+'*')){throw 'split manifest missing from actual launch tokens'}
$parameters.SplitContract=$null
Invoke-WeatherQuietMergeChild @parameters | Out-Null
if($script:terminated -ne 1 -or $script:launched -like '*-QualificationManifest*'){throw 'legacy invocation gained split arguments'}
''')


def test_boot_commit_claim_preserves_unknown_outcome_without_git_mutation(tmp_path):
    run(tmp_path, r'''
$source=[IO.File]::ReadAllText((Join-Path $root 'scripts/ops/boot_recovery.ps1'))
$start=$source.IndexOf('$splitCommitPending =')
$end=$source.IndexOf('elseif ($markerReadable) {',$start)
if($start -lt 0 -or $end -le $start){throw 'split boot branch is missing'}
$actual=$source.Substring($start,$end-$start)+'else { $legacyEntered=$true }'
function git { throw 'boot tried to mutate an ambiguous split commit' }
foreach($phase in @('qualification_commit_invoked','merge_committed_unpublished','documented_unpublished','published')){
    foreach($mergeHeadExists in @($true,$false)){
        $markerReadable=$true; $mergeReconciliationRequired=$false; $legacyEntered=$false
        $untrustedMergeHeadRecoveryRequired=$mergeHeadExists
        $notes=New-Object System.Collections.Generic.List[string]
        $marker=[pscustomobject]@{operation_mode='split_qualification_v2';phase=$phase
            qualification=[pscustomobject]@{commit_invocation_started=$true}}
        Invoke-Expression $actual
        if(-not $mergeReconciliationRequired -or $legacyEntered -or $untrustedMergeHeadRecoveryRequired -or $notes.Count -ne 1){
            throw 'ambiguous split commit fell through to ordinary abort/reset'
        }
    }
}
$marker.qualification.commit_invocation_started=$false
$legacyEntered=$false
Invoke-Expression $actual
if(-not $legacyEntered){throw 'pre-commit split lost ordinary rollback routing'}
''')


def test_prerequisite_receipt_field_selection_remains_local_to_manifest(tmp_path):
    run(tmp_path, r'''
foreach($version in @('v2','v1','v2')){
    $role=if($version -eq 'v2'){'host'}else{'suite'}
    $schedule=[ordered]@{}
    $schedule[$role+'_task_name']='fixture'; $schedule[$role+'_at_local']='2026-09-15T00:35:00'
    $manifest=[ordered]@{schema="weather_integration_attempt_manifest_$version";attempt_id='fixture';schedule=[pscustomobject]$schedule}
    if($version -eq 'v2'){$manifest['qualification_mode']='split_v2'}
    $contract=[pscustomobject]@{Manifest=[pscustomobject]$manifest}
    $phase=Get-WeatherIntegrationPrerequisite -AttemptContract $contract
    $receipt=[ordered]@{schema=(Get-WeatherIntegrationRecordSchema -AttemptContract $contract -Kind merge_receipt)
        ($phase.ReceiptPathField)='C:\fixture'; ($phase.ReceiptShaField)=('a'*64)}
    if($receipt.schema -cne "weather_integration_attempt_merge_receipt_$version" -or
       -not $receipt.Contains($role+'_receipt_path') -or -not $receipt.Contains($role+'_receipt_sha256')){throw 'receipt phase mislabeled'}
    $opposite=if($role -eq 'host'){'suite'}else{'host'}
    if($receipt.Contains($opposite+'_receipt_path')){throw 'receipt borrows the other phase'}
}
''')
