# Registers WeatherManualOrderJournal: manual_order_journal.ps1 every 5 minutes, S4U/Limited.
#
#   .\scripts\ops\register_manual_order_journal.ps1 -ExpectedRunnerSha256 <sha> -ExpectedModulesSha256 <sha> -WhatIf
#   .\scripts\ops\register_manual_order_journal.ps1 -ExpectedRunnerSha256 <sha> -ExpectedModulesSha256 <sha>
#   .\scripts\ops\register_manual_order_journal.ps1 -Unregister [-WhatIf]
#
# -RepoRoot is the code checkout whose runner and modules are pinned; -StateRoot (default RepoRoot) is
# the checkout whose venv, config\local reader client file and data\ the runner uses.
#
# Light, read-only and lease-free (see docs/operations/manual-order-journal.md). Both pins must
# match the files in -RepoRoot before any Scheduler call; the action carries them so the runner
# refuses a later unreviewed edit. -WhatIf prints the exact action and the current hashes only.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$StateRoot = "",
    [string]$ExpectedRunnerSha256 = "",
    [string]$ExpectedModulesSha256 = "",
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$taskName = "WeatherManualOrderJournal"
$repo = [IO.Path]::GetFullPath($RepoRoot).TrimEnd('\')
$state = if ([string]::IsNullOrWhiteSpace($StateRoot)) { $repo } else { [IO.Path]::GetFullPath($StateRoot).TrimEnd('\') }
$runner = Join-Path $repo "scripts\ops\manual_order_journal.ps1"
$ModuleFiles = @(
    'src/weather/market/order_journal.py',
    'src/weather/market/order_journal_io.py',
    'src/weather/market/order_journal_sources.py',
    'src/weather/market/order_journal_report.py',
    'src/weather/market/wallet_reader_client.py'
)

function Get-ModulesSha256([string]$Root) {
    $lines = foreach ($name in $ModuleFiles) {
        $path = Join-Path $Root ($name -replace '/', '\')
        '{0}:{1}' -f $name, (Get-FileHash -LiteralPath $path -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
    $sha = [Security.Cryptography.SHA256]::Create()
    try { -join ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') }) } finally { $sha.Dispose() }
}

if ($Unregister) {
    if ($PSCmdlet.ShouldProcess($taskName, 'Unregister-ScheduledTask')) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Output "unregistered $taskName"
    }
    exit 0
}
if ($repo -match '["\r\n]' -or $state -match '["\r\n]') { throw 'unsafe quoted task path' }
$actualRunner = (Get-FileHash -LiteralPath $runner -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
$actualModules = Get-ModulesSha256 $repo
if ($ExpectedRunnerSha256 -notmatch '^[0-9A-Fa-f]{64}$' -or $ExpectedModulesSha256 -notmatch '^[0-9A-Fa-f]{64}$' -or
        $actualRunner -ine $ExpectedRunnerSha256 -or $actualModules -ine $ExpectedModulesSha256) {
    throw ("manual order journal registration requires matching reviewed pins (current runner {0}, modules {1})" -f $actualRunner, $actualModules)
}
$ExpectedRunnerSha256 = $ExpectedRunnerSha256.ToLowerInvariant()
$ExpectedModulesSha256 = $ExpectedModulesSha256.ToLowerInvariant()
$executable = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`" -RepoRoot `"$repo`" -StateRoot `"$state`" -ExpectedSelfSha256 $ExpectedRunnerSha256 -ExpectedModulesSha256 $ExpectedModulesSha256"
if (-not $PSCmdlet.ShouldProcess($taskName, "Register every 5 minutes: $executable $arguments")) {
    exit 0
}

$action = New-ScheduledTaskAction -Execute $executable -Argument $arguments -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Force `
    -Description "Read-only owner-discretionary manual order journal; data\manual_order_journal" | Out-Null

$t = Get-ScheduledTask -TaskName $taskName
$registeredActions = @($t.Actions | Where-Object { $null -ne $_ })
$registeredTriggers = @($t.Triggers | Where-Object { $null -ne $_ })
if ($registeredActions.Count -ne 1 -or [string]$registeredActions[0].Execute -ine $executable -or
        [string]$registeredActions[0].Arguments -cne $arguments -or
        ([string]$registeredActions[0].WorkingDirectory).TrimEnd('\') -ine $repo -or
        $registeredTriggers.Count -ne 1 -or [string]$registeredTriggers[0].Repetition.Interval -cne 'PT5M' -or
        [string]$t.Principal.LogonType -cne 'S4U' -or [string]$t.Principal.RunLevel -cne 'Limited' -or
        [string]$t.Settings.ExecutionTimeLimit -cne 'PT4M' -or [string]$t.Settings.MultipleInstances -cne 'IgnoreNew') {
    Disable-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Out-Null
    throw 'registered manual order journal does not match the reviewed action, trigger, principal and settings; the task was disabled'
}
Write-Output ("registered {0}: logon={1} state={2} interval=PT5M" -f $taskName, $t.Principal.LogonType, $t.State)
