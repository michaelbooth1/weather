# Register only after production adoption/review. WhatIf validates pins without Scheduler IO.
# Pins: the runner's SHA-256 and the exporter module-closure hash printed by
# `python -B -m weather.market.maker_replay_night_v02 module-hash` in this checkout (the runner launches the
# v0.2 exporter). The runner refuses panel days 2026-09-30..2026-10-15 with exit code 3 (PANEL_GATED).
# -RepoRoot is the exact-tip DEPLOY tree (it owns the runner and becomes the runner's -DeployRoot); -ProductionRoot
# is the production checkout (venv, memory guard, lease helpers, host assignment). The two must be disjoint.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [Parameter(Mandatory = $true)][string]$ReleaseRoot,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedModuleSha256,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedRunnerSha256,
    [Parameter(Mandatory = $true)][string]$ProductionRoot,
    [Parameter(Mandatory = $true)][ValidateRange(512, 65536)][int]$MinAvailableMiB,
    [ValidateSet('00:35')][string]$At = '00:35'
)
$ErrorActionPreference = 'Stop'
$taskName = 'WeatherReplayBundleExportNightly'
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$ProductionRoot = (Resolve-Path -LiteralPath $ProductionRoot).Path
foreach ($pair in @(@($RepoRoot, $ProductionRoot), @($ProductionRoot, $RepoRoot))) {
    $inner = $pair[0].TrimEnd('\'); $outer = $pair[1].TrimEnd('\')
    if ($inner -ieq $outer -or $inner.StartsWith($outer + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'deploy RepoRoot and ProductionRoot must be disjoint trees'
    }
}
foreach ($path in @($DataRoot, $ReleaseRoot, $OutputRoot)) {
    if (-not [IO.Path]::IsPathRooted($path) -or $path -match '["\r\n]' -or
        [IO.Path]::GetFullPath($path).TrimEnd('\') -cne $path.TrimEnd('\')) {
        throw 'absolute normalized data/output paths required'
    }
    $part = $path
    while ($part) {
        if (Test-Path -LiteralPath $part) {
            $item = Get-Item -LiteralPath $part -Force
            if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw 'ordinary non-reparse directories required'
            }
        }
        $part = Split-Path -Parent $part
    }
}
foreach ($sourceRoot in @($DataRoot, $ReleaseRoot)) {
    if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) { throw 'input roots must exist' }
    if ($OutputRoot -ieq $sourceRoot -or
        $OutputRoot.StartsWith($sourceRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or
        $sourceRoot.StartsWith($OutputRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'output must be disjoint from all inputs'
    }
}
if (-not (Test-Path -LiteralPath (Split-Path -Parent $OutputRoot) -PathType Container)) { throw 'output parent must exist' }
$runner = Join-Path $RepoRoot 'scripts\ops\replay_bundle_export_nightly.ps1'
if ((Get-FileHash -LiteralPath $runner -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ExpectedRunnerSha256) {
    throw 'nightly runner hash mismatch'
}
if (-not $PSCmdlet.ShouldProcess($taskName, "Register daily $At export; pin modules $ExpectedModuleSha256")) { return }
if ((Get-TimeZone).Id -ne 'Eastern Standard Time') { throw 'Scheduler must use America/Toronto local time' }
. (Join-Path $ProductionRoot 'scripts\ops\workload_admission.ps1')
$assignment = Get-WeatherExecutionHostAssignment -RepoRoot $ProductionRoot
if ((Get-WeatherExecutionHostId) -cne [string]$assignment.dedicated_capture_execution_host_id) {
    throw 'registration requires assigned capture host'
}
. (Join-Path $RepoRoot 'scripts\ops\training_window_contract.ps1')
$powerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$tokens = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $runner,
    '-DeployRoot', $RepoRoot, '-ProductionRoot', $ProductionRoot, '-DataRoot', $DataRoot, '-ReleaseRoot', $ReleaseRoot,
    '-OutputRoot', $OutputRoot, '-ExpectedModuleSha256', $ExpectedModuleSha256, '-ExpectedSelfSha256', $ExpectedRunnerSha256,
    '-MinAvailableMiB', [string]$MinAvailableMiB)
$arguments = ConvertTo-ScheduledTaskArgumentString -Tokens $tokens
$action = New-ScheduledTaskAction -Execute $powerShell -Argument $arguments -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -Hidden -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 50) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description 'Pinned sealed replay export; no catch-up, no capture mutation.' -Force | Out-Null
$matches = @(Get-ScheduledTask -TaskName $taskName -ErrorAction Stop)
if ($matches.Count -ne 1) { throw 'expected exactly one registered export task' }
$task = $matches[0]
$actions = @($task.Actions)
$triggers = @($task.Triggers)
if ($task.TaskPath -ne '\' -or $task.State -eq 'Disabled' -or
    $actions.Count -ne 1 -or $actions[0].Execute -ine $powerShell -or
    $actions[0].Arguments -cne $arguments -or $actions[0].WorkingDirectory -ine $RepoRoot -or
    $triggers.Count -ne 1 -or $triggers[0].CimClass.CimClassName -ne 'MSFT_TaskDailyTrigger' -or
    $triggers[0].DaysInterval -ne 1 -or -not $triggers[0].Enabled -or
    ([datetime]$triggers[0].StartBoundary).ToString('HH:mm') -ne $At -or
    -not [string]::IsNullOrWhiteSpace([string]$triggers[0].Repetition.Interval) -or
    $task.Settings.StartWhenAvailable -or $task.Settings.ExecutionTimeLimit -ne 'PT50M' -or
    $task.Settings.MultipleInstances -ne 'IgnoreNew' -or -not $task.Settings.Hidden -or
    -not $task.Settings.WakeToRun -or $task.Settings.DisallowStartIfOnBatteries -or
    $task.Settings.StopIfGoingOnBatteries -or $task.Principal.UserId -ine $env:USERNAME -or
    $task.Principal.LogonType -ne 'S4U' -or $task.Principal.RunLevel -ne 'Limited') {
    throw 'registration readback differs from pinned nightly contract'
}
Write-Output "Registered $taskName at $At; rerun registrar after any exporter module change."
