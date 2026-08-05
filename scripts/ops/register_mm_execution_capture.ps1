# Register a separate continuous WebSocket producer for strict-through maker evidence.
# Editing this file does not authorize registration or provider access.
[CmdletBinding()]
param(
    [string]$StartAt = "00:55",
    [double]$SessionSeconds = 86400.0,
    [double]$ReconnectSeconds = 1.0,
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$taskName = "WeatherMakerExecutionCapture"
$repo = "C:\Users\micha\Desktop\github\weather"
$python = Join-Path $repo "venv\Scripts\pythonw.exe"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "unregistered $taskName"
    exit 0
}
if (-not (Test-Path $python)) { throw "missing $python" }

$arguments = "-m weather.market.mm_execution_capture --market all " +
    "--session-seconds $SessionSeconds --reconnect-seconds $ReconnectSeconds"
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Once -At $StartAt -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "micha" -LogonType S4U -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

$task = Get-ScheduledTask -TaskName $taskName
$info = $task | Get-ScheduledTaskInfo
Write-Output ("registered {0}: state={1} logon={2} next={3}" -f $taskName, $task.State, $task.Principal.LogonType, $info.NextRunTime)
Write-Output "verify retained status: data\snapshots\market_execution_capture_status.json"
