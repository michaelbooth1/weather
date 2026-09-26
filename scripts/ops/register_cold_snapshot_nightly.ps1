# Run only by the production agent after guarded integration and review.
[CmdletBinding()]
param(
    [string]$ProductionRepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory=$true)][string]$RequestPath,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$RequestSha256,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSourceTip,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'workload_admission.ps1')
. (Join-Path $PSScriptRoot 'training_window_contract.ps1')
$sourceRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$assignment = Get-WeatherExecutionHostAssignment -RepoRoot $sourceRoot
if ((Get-WeatherExecutionHostId) -cne [string]$assignment.dedicated_capture_execution_host_id) {
    throw 'Registration is restricted to the dedicated capture host'
}
if (([string](git -C $sourceRoot rev-parse HEAD)).Trim() -cne $ExpectedSourceTip -or $LASTEXITCODE -ne 0) {
    throw 'Reviewed source tip mismatch'
}
if (@(git -C $sourceRoot status --porcelain).Count -ne 0 -or $LASTEXITCODE -ne 0) { throw 'Source must be clean' }
if ((Get-FileHash -LiteralPath $RequestPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $RequestSha256) {
    throw 'Policy hash mismatch'
}
$tokens = @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'cold_snapshot_nightly_run.ps1'),
    '-ProductionRepoRoot',$ProductionRepoRoot,'-RequestPath',$RequestPath,
    '-RequestSha256',$RequestSha256,'-ExpectedSourceTip',$ExpectedSourceTip)
if ($Apply) { $tokens += '-Apply' }
$argsText = ConvertTo-ScheduledTaskArgumentString -Tokens $tokens
$exe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$action = New-ScheduledTaskAction -Execute $exe -Argument $argsText -WorkingDirectory $sourceRoot
$trigger = New-ScheduledTaskTrigger -Daily -At '00:30'
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 255) -MultipleInstances IgnoreNew
$taskName = 'WeatherColdSnapshotNightly'
$null = Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force
$actual = Get-ScheduledTask -TaskName $taskName
if ($actual.Actions.Count -ne 1 -or $actual.Actions[0].Execute -cne $exe -or
    $actual.Actions[0].Arguments -cne $argsText -or $actual.Actions[0].WorkingDirectory -cne $sourceRoot -or
    $actual.Principal.LogonType -ne 'S4U' -or $actual.Principal.RunLevel -ne 'Limited' -or
    $actual.Settings.StartWhenAvailable -or $actual.Settings.MultipleInstances -ne 'IgnoreNew' -or
    $actual.Settings.ExecutionTimeLimit -ne 'PT4H15M' -or $actual.Triggers.Count -ne 1 -or
    ([DateTime]$actual.Triggers[0].StartBoundary).ToString('HH:mm') -ne '00:30' -or
    $actual.Triggers[0].DaysInterval -ne 1) { throw 'Scheduled-task readback mismatch; inspect registration' }
$actual
