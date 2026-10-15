# Registers WeatherHostHealthWatchdog: a time-aware health check that records what needed
# attention while nobody was looking, and at what severity FOR THAT HOUR.
#
# Supply both reviewed hashes; see OPERATIONS_DESIGN.md for the pinned deployment.
#
# Every 15 minutes, S4U so it survives a reboot with nobody logged on (the whole point --
# see docs/ops/streak-soak.md). Cheap: one status.ps1 pass, no capture imports.
[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$WatchdogScriptPath = "",
    [string]$ExpectedSelfSha256 = "",
    [string]$StatusScriptPath = "",
    [string]$ExpectedStatusScriptSha256 = "",
    [switch]$Unregister
)
# Windows PowerShell 5.1 leaves $PSScriptRoot and $PSCommandPath empty inside an
# advanced script's param() defaults under `powershell -File`; derive the default
# here. An explicit -RepoRoot always wins.
if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
}

$ErrorActionPreference = "Stop"
$taskName = "WeatherHostHealthWatchdog"
$repo = [IO.Path]::GetFullPath($RepoRoot)
$script = if ($WatchdogScriptPath) { $WatchdogScriptPath } else { Join-Path $repo "scripts\ops\health_watchdog.ps1" }
if (-not $StatusScriptPath) { $StatusScriptPath = Join-Path $repo "scripts\ops\status.ps1" }

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "unregistered $taskName"
    exit 0
}
foreach ($binding in @(
    @{ Path = $script; Hash = $ExpectedSelfSha256; Parameters = @('RepoRoot', 'ExpectedSelfSha256', 'StatusScriptPath', 'ExpectedStatusScriptSha256') },
    @{ Path = $StatusScriptPath; Hash = $ExpectedStatusScriptSha256; Parameters = @('RepoRoot', 'Json', 'ExpectedSelfSha256') }
)) {
    if (-not [IO.Path]::IsPathRooted($binding.Path) -or
        $binding.Hash -notmatch '^[0-9A-Fa-f]{64}$' -or
        -not (Test-Path -LiteralPath $binding.Path -PathType Leaf) -or
        (Get-FileHash -LiteralPath $binding.Path -Algorithm SHA256).Hash -ine $binding.Hash) {
        throw 'watchdog registration requires both absolute reviewed script paths and matching SHA256 pins'
    }
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($binding.Path, [ref]$tokens, [ref]$errors)
    $parameters = @($ast.ParamBlock.Parameters | ForEach-Object { $_.Name.VariablePath.UserPath })
    if (@($errors).Count -or @($binding.Parameters | Where-Object { $_ -notin $parameters }).Count) {
        throw 'watchdog registration refuses scripts without the pinned-source contract'
    }
}
foreach ($path in @($repo, $script, $StatusScriptPath)) {
    if ($path -match '["\r\n]') { throw 'unsafe quoted task path' }
}
$script = (Get-Item -LiteralPath $script).FullName
$StatusScriptPath = (Get-Item -LiteralPath $StatusScriptPath).FullName
$executable = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`" -RepoRoot `"$repo`" -ExpectedSelfSha256 $ExpectedSelfSha256 -StatusScriptPath `"$StatusScriptPath`" -ExpectedStatusScriptSha256 $ExpectedStatusScriptSha256"

$action = New-ScheduledTaskAction -Execute $executable `
    -Argument $arguments `
    -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(5) `
    -RepetitionInterval (New-TimeSpan -Minutes 15)
# S4U: runs whether or not anyone is logged on, without storing a password.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force `
    -Description "Time-aware host health watchdog; writes data/alerts/host_health_alerts.jsonl and MORNING_BRIEFING.md" | Out-Null

$t = Get-ScheduledTask $taskName
if (@($t.Actions).Count -ne 1 -or $t.Actions[0].Execute -ine $executable -or
    $t.Actions[0].Arguments -cne $arguments -or $t.Actions[0].WorkingDirectory -ine $repo -or
    [string]$t.Principal.LogonType -ne 'S4U' -or [string]$t.Principal.RunLevel -ne 'Limited') {
    throw 'registered watchdog does not match the reviewed pinned action and S4U/Limited principal'
}
Write-Output ("registered {0}: logon={1} state={2} limit={3}" -f $taskName, $t.Principal.LogonType, $t.State, $t.Settings.ExecutionTimeLimit)
