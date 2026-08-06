# Register the fleet-wide, execution-only maker evidence producer.
#
# Registration is an operator action. This script registers nothing until the
# deployed module advertises the three contracts that protect the CLOB writer
# and the single-host training window. It never explicitly starts the task.
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

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "missing $python" }
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) { throw "missing $pythonw" }

$enrichmentTask = Get-ScheduledTask -TaskName $enrichmentTaskName -ErrorAction SilentlyContinue
if ($enrichmentTask -and $enrichmentTask.State -ne "Disabled") {
    throw "$enrichmentTaskName is enabled; do not run both maker-tape producers"
}

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
foreach ($requiredArgument in @(
    "--retention-mode executions-only",
    "--lock-scope execution-tape",
    "--host-policy-mode pause-training-window"
)) {
    if ($task.Actions.Arguments -notmatch [regex]::Escape($requiredArgument)) {
        throw "$taskName registered without $requiredArgument"
    }
}
Write-Output ("registered {0}: state={1} priority={2} logon={3} next={4}" -f `
    $taskName, $task.State, $task.Settings.Priority, $task.Principal.LogonType, $info.NextRunTime)
Write-Output "not explicitly started; scheduler will use the configured trigger"
Write-Output "verify bound execution receipts and status before the first countable window"
