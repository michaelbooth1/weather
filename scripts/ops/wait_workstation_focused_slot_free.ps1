# Live-session runbook step: wait until the workstation focused slot is free.
#
# Run it right after the runbook writes live_session_v1.active and before the first
# preflight. With the marker present no new slot run can start, and a running one is
# pre-empted within about a second (exit 77), so the slot normally frees at once.
# The helper briefly takes and releases the slot mutex to prove nobody holds it.
#
# Output (last line) and exit code:
#   SLOT_FREE                     0  the slot mutex was free (or abandoned) and no
#                                    unproved slot teardown is recorded
#   STOP: <reason>                1  still held after -MaxWaitSeconds, the session
#                                    marker is missing, or a slot teardown was not
#                                    proved (workstation_focused_slot_v1.poison)
# On STOP the session does not proceed to its first preflight.
[CmdletBinding()]
param(
    [ValidateRange(1, 300)][int]$MaxWaitSeconds = 300,
    # Overrides exist for tests only; operators use the defaults.
    [string]$MutexName = "",
    [string]$StateRoot = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "workload_admission.ps1")
. (Join-Path $PSScriptRoot "workstation_focused_slot.ps1")

function Stop-WithReason([string]$Reason) {
    [Console]::Out.WriteLine("STOP: $Reason")
    exit 1
}

try {
    if (-not $MutexName) { $MutexName = Get-WeatherWorkstationFocusedSlotMutexName }
    if (-not $StateRoot) { $StateRoot = Get-WeatherWorkstationFocusedSlotStateRoot }
}
catch { Stop-WithReason "the focused-slot state cannot be located: $($_.Exception.Message)" }

$marker = Join-Path $StateRoot "live_session_v1.active"
if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
    Stop-WithReason "live_session_v1.active is not present; write it before probing the slot"
}

$mutex = $null
$owned = $false
try {
    $mutex = [Threading.Mutex]::new($false, $MutexName)
    try { $owned = $mutex.WaitOne([TimeSpan]::FromSeconds($MaxWaitSeconds), $false) }
    catch [Threading.AbandonedMutexException] { $owned = $true }
    if ($owned) { $mutex.ReleaseMutex() }
}
catch { Stop-WithReason "the focused-slot mutex cannot be probed: $($_.Exception.Message)" }
finally {
    if ($null -ne $mutex) { $mutex.Dispose() }
}
if (-not $owned) {
    Stop-WithReason "the workstation focused slot is still held after $MaxWaitSeconds s"
}
if (Test-Path -LiteralPath (Join-Path $StateRoot "workstation_focused_slot_v1.poison")) {
    Stop-WithReason "an earlier focused-slot teardown was not proved (workstation_focused_slot_v1.poison)"
}
[Console]::Out.WriteLine("SLOT_FREE")
exit 0
