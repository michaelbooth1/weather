# Register WeatherBootRecovery: runs boot_recovery.ps1 at every startup.
#
#   .\scripts\ops\register_boot_recovery.ps1 [-Unregister]
#
# S4U so it runs after an unattended reboot with nobody logged on -- which is the only
# case it exists for. A 2-minute delay lets the supervisors' own repeating triggers get
# a chance to start the loops first, so the check measures recovery rather than racing it.
[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
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

$action = New-ScheduledTaskAction -Execute "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = "PT2M"
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

$t = Get-ScheduledTask -TaskName $taskName
Write-Output ("registered {0}: state={1} logon={2} runlevel={3}" -f $taskName, $t.State, $t.Principal.LogonType, $t.Principal.RunLevel)
