# Registers WeatherHostHealthWatchdog: a time-aware health check that records what needed
# attention while nobody was looking, and at what severity FOR THAT HOUR.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\ops\register_health_watchdog.ps1
#
# Every 15 minutes, S4U so it survives a reboot with nobody logged on (the whole point --
# see docs/ops/streak-soak.md). Cheap: one status.ps1 pass, no capture imports.
[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [switch]$Unregister
)

$taskName = "WeatherHostHealthWatchdog"
$repo = $RepoRoot
$script = Join-Path $repo "scripts\ops\health_watchdog.ps1"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "unregistered $taskName"
    exit 0
}
if (-not (Test-Path $script)) { throw "watchdog script not found: $script" }

$action = New-ScheduledTaskAction -Execute "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`"" `
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
Write-Output ("registered {0}: logon={1} state={2} limit={3}" -f $taskName, $t.Principal.LogonType, $t.State, $t.Settings.ExecutionTimeLimit)
