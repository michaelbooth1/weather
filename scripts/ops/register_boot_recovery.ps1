# Register WeatherBootRecovery: runs boot_recovery.ps1 at every startup.
#
#   .\scripts\ops\register_boot_recovery.ps1 [-Unregister]
#
# S4U so it runs after an unattended reboot with nobody logged on -- which is the only
# case it exists for. Start immediately to minimize the interval in which an interrupted
# guarded merge remains visible. Task Scheduler does not promise ordering among startup
# and logon tasks, so boot_recovery.ps1 still owns fail-closed evidence and the bounded
# post-rollback retry while supervisor evidence catches up.
[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$ExpectedScriptSha256 = "",
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$taskName = "WeatherBootRecovery"
$repo = $RepoRoot
$script = Join-Path $repo "scripts\ops\boot_recovery.ps1"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "unregistered $taskName"
    exit 0
}
if (-not (Test-Path $script)) { throw "missing $script" }
$ExpectedScriptSha256 = $ExpectedScriptSha256.Trim().ToLowerInvariant()
if ($ExpectedScriptSha256) {
    if ($ExpectedScriptSha256 -notmatch '^[0-9a-f]{64}$') {
        throw "ExpectedScriptSha256 must be a full SHA256."
    }
    $actualScriptSha256 = (Get-FileHash -LiteralPath $script -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualScriptSha256 -ne $ExpectedScriptSha256) {
        throw "boot_recovery.ps1 does not match ExpectedScriptSha256."
    }
}

$actionArguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`""
if ($ExpectedScriptSha256) {
    $actionArguments += " -ExpectedSelfSha256 $ExpectedScriptSha256"
}
$action = New-ScheduledTaskAction -Execute "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -Argument $actionArguments `
    -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -MultipleInstances IgnoreNew
# Match the rest of the fleet exactly: bare current username, not
# "$env:USERDOMAIN\$env:USERNAME" --
# USERDOMAIN is WORKGROUP on this host and does not resolve to a SID. RunLevel Limited like
# the other supervisors; nothing here needs elevation.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

$taskMatches = @(Get-ScheduledTask -TaskName $taskName -ErrorAction Stop)
if ($taskMatches.Count -ne 1) {
    throw "WeatherBootRecovery did not resolve to exactly one registered task."
}
$t = $taskMatches[0]
$registeredActions = @($t.Actions | Where-Object { $null -ne $_ })
$registeredTriggers = @($t.Triggers | Where-Object { $null -ne $_ })
$expectedExecutable = "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
$expectedWorkingDirectory = [IO.Path]::GetFullPath($repo).TrimEnd('\')
$actualWorkingDirectory = try {
    [IO.Path]::GetFullPath([string]$registeredActions[0].WorkingDirectory).TrimEnd('\')
}
catch { "" }
$bindingOk = (
    [string]$t.TaskPath -ceq "\" -and
    [string]$t.State -ceq "Ready" -and
    $t.Settings.Enabled -eq $true -and
    [string]$t.Principal.UserId -ieq [string]$env:USERNAME -and
    [string]$t.Principal.LogonType -ceq "S4U" -and
    [string]$t.Principal.RunLevel -ceq "Limited" -and
    $registeredActions.Count -eq 1 -and
    [string]$registeredActions[0].Execute -ieq $expectedExecutable -and
    [string]$registeredActions[0].Arguments -ceq $actionArguments -and
    $actualWorkingDirectory -ieq $expectedWorkingDirectory -and
    $registeredTriggers.Count -eq 1 -and
    [string]$registeredTriggers[0].CimClass.CimClassName -ceq "MSFT_TaskBootTrigger" -and
    [string]$registeredTriggers[0].Delay -eq "" -and
    [bool]$registeredTriggers[0].Enabled -and
    [bool]$t.Settings.StartWhenAvailable -and
    [string]$t.Settings.ExecutionTimeLimit -ceq "PT15M" -and
    [string]$t.Settings.MultipleInstances -ceq "IgnoreNew" -and
    -not [bool]$t.Settings.DisallowStartIfOnBatteries -and
    -not [bool]$t.Settings.StopIfGoingOnBatteries -and
    -not [bool]$t.Settings.RunOnlyIfIdle -and
    -not [bool]$t.Settings.RunOnlyIfNetworkAvailable
)
if (-not $bindingOk) {
    Disable-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Out-Null
    throw "WeatherBootRecovery registration did not preserve its exact reviewed action, principal, trigger, and settings contract; the task was disabled."
}
Write-Output ("registered {0}: state={1} logon={2} runlevel={3}" -f $taskName, $t.State, $t.Principal.LogonType, $t.Principal.RunLevel)
