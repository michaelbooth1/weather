# Register the fleet-wide, execution-only maker tape producer.
#
# This script is deliberately fail-closed. It registers nothing until the
# refreshed producer advertises the two contracts that make a fourth capture
# loop safe on the workstation:
#
#   * execution objects only (no book or price-change payload retention); and
#   * a dedicated execution-tape lock (no contention with the raw CLOB writer).
#   * an explicit pause during the host policy's nightly training window.
#
# Registration is an operator action. This script does not invoke the task;
# Task Scheduler starts it when the configured trigger becomes due.
[CmdletBinding()]
param(
    [string]$StartAt = "00:55",
    [double]$SessionSeconds = 86400.0,
    [double]$ReconnectSeconds = 1.0,
    [string]$Repo = "C:\Users\micha\Desktop\github\weather",
    [string]$UserId = "micha",
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$taskName = "WeatherMakerExecutionCapture"
$enrichmentTaskName = "WeatherClobEnrichmentLoop"
$python = Join-Path $Repo "venv\Scripts\python.exe"
$pythonw = Join-Path $Repo "venv\Scripts\pythonw.exe"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "unregistered $taskName"
    exit 0
}

if (-not (Test-Path $python)) { throw "missing $python" }
if (-not (Test-Path $pythonw)) { throw "missing $pythonw" }

$enrichmentTask = Get-ScheduledTask -TaskName $enrichmentTaskName -ErrorAction SilentlyContinue
if ($enrichmentTask -and $enrichmentTask.State -ne "Disabled") {
    throw "$enrichmentTaskName is enabled; do not run both maker-tape producers"
}

# Importing --help is read-only and proves the deployed module has adopted the
# narrow writer contract. An older full-payload producer must not be scheduled.
$helpText = (& $python -m weather.market.mm_execution_capture --help 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) {
    throw "maker tape producer help failed with exit code $LASTEXITCODE"
}
foreach ($required in @(
    "--retention-mode",
    "executions-only",
    "--lock-scope",
    "execution-tape",
    "--host-policy-mode",
    "pause-training-window"
)) {
    if ($helpText -notmatch [regex]::Escape($required)) {
        throw "unsafe maker tape producer: help does not advertise $required"
    }
}

$arguments = "-m weather.market.mm_execution_capture --market all " +
    "--session-seconds $SessionSeconds --reconnect-seconds $ReconnectSeconds " +
    "--retention-mode executions-only --lock-scope execution-tape " +
    "--host-policy-mode pause-training-window"
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $Repo
$trigger = New-ScheduledTaskTrigger -Once -At $StartAt -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -Priority 6
$principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType S4U -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

$task = Get-ScheduledTask -TaskName $taskName
$info = $task | Get-ScheduledTaskInfo
if ($task.Settings.Priority -ne 6) {
    throw "$taskName registered with priority $($task.Settings.Priority), expected 6 (BelowNormal)"
}
if ($task.Actions.Arguments -notmatch "--retention-mode executions-only") {
    throw "$taskName registered without execution-only retention"
}
Write-Output ("registered {0}: state={1} priority={2} logon={3} next={4}" -f `
    $taskName, $task.State, $task.Settings.Priority, $task.Principal.LogonType, $info.NextRunTime)
Write-Output "not explicitly started; scheduler will use the configured trigger"
Write-Output "verify receipts and status before the first countable window"
