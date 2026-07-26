# Runs at every boot. Records WHY we rebooted, heals anything a hard power loss can leave
# broken, and verifies the fleet actually came back.
#
# Why this exists: this host loses power. Event-log forensics on 2026-07-25 found five
# unexpected shutdowns in 90 days -- four of them with bugcheck=0, powerButton=0 and no
# BSOD, which is the signature of abrupt power loss rather than a crash. That is roughly
# one every three weeks against a 14-day contiguous streak requirement, and nothing in the
# monitoring noticed any of them: the digest reported a healthy host either side of a
# 29-minute outage on 2026-07-21 (day 1 of the current streak).
#
# Two things a power loss can leave behind that nothing else repairs:
#   1. A half-finished merge. quiet_window_merge.ps1 merges locally and waits ~5 minutes
#      before deciding; a power cut inside that window leaves MERGE_HEAD and a merged
#      working tree, so the supervisors readopt UNREVIEWED half-merged code on the way back
#      up, with no rollback in flight. Undo it: an interrupted merge was never approved.
#   2. Nobody knowing it happened. The boot record below is the only place an unattended
#      outage is written down in project terms rather than the Windows event log.
[CmdletBinding()]
param([switch]$NoWait)

$ErrorActionPreference = "Continue"
$repo = "C:\Users\micha\Desktop\github\weather"
$alertDir = Join-Path $repo "data\alerts"
$logPath = Join-Path $alertDir "boot_events.jsonl"
$notes = New-Object System.Collections.Generic.List[string]

$os = Get-CimInstance Win32_OperatingSystem
$boot = $os.LastBootUpTime

# ---- was the previous shutdown clean? ----
# Kernel-Power 41 is written on the way back UP, describing the shutdown that just ended.
# bugcheck=0 with no power-button timestamp means the machine simply stopped -- power loss
# or a hard hang -- as opposed to a BSOD (non-zero bugcheck) or a held power button.
$unclean = $false
$cause = "clean"
try {
    $e41 = Get-WinEvent -FilterHashtable @{LogName = 'System'; Id = 41; StartTime = $boot.AddMinutes(-10) } -MaxEvents 1 -EA SilentlyContinue
    if ($e41) {
        $unclean = $true
        $d = @{}
        ([xml]$e41.ToXml()).Event.EventData.Data | ForEach-Object { $d[$_.Name] = $_.'#text' }
        $cause = if ([int]$d['BugcheckCode'] -ne 0) { "bugcheck 0x{0:X}" -f [int]$d['BugcheckCode'] }
        elseif ($d['LongPowerButtonPressDetected'] -eq 'true') { "power button held" }
        else { "power loss or hard hang" }
    }
}
catch {}
$notes.Add("boot $boot; previous shutdown: $cause")

# ---- heal an interrupted merge ----
$mergeHealed = $false
Set-Location $repo
if (Test-Path (Join-Path $repo ".git\MERGE_HEAD")) {
    $notes.Add("FOUND AN INTERRUPTED MERGE (.git/MERGE_HEAD present) - aborting it")
    & git merge --abort | Out-Null
    if ($LASTEXITCODE -ne 0) {
        # merge --abort can refuse if the index is also damaged; fall back to the last commit.
        & git reset --hard HEAD | Out-Null
        $notes.Add("merge --abort failed; reset --hard HEAD instead")
    }
    $mergeHealed = $true
    $notes.Add("interrupted merge undone; it was never verified, so it must not survive a reboot")
}
$head = (& git rev-parse --short HEAD 2>$null)
if ($head) { $notes.Add("HEAD $head") }

# ---- did the fleet come back? ----
# The supervisors are S4U on 1-2 minute repeating triggers, so they should self-start with
# nobody logged on. Verify rather than assume: this is the one failure mode that silences
# every other check, and a boot is exactly when it would show up.
function Count-Loops {
    @(Get-CimInstance Win32_Process | Where-Object {
            ($_.CommandLine -like '*weather.collection.snapshot_tracker*' -or
            $_.CommandLine -like '*weather.market.market_microstructure*' -or
            $_.CommandLine -like '*weather.operations.observation_trigger*') -and
            $_.CommandLine -notlike '*hot_capture*' -and
            $_.CommandLine -notlike '*--expected-runtime-fingerprint*'
        }).Count
}
# Always take a reading; -NoWait only skips the retry loop (it exists so the script can be
# tested on an already-running host without a 5-minute pause).
$loops = Count-Loops
if (-not $NoWait) {
    for ($i = 0; $i -lt 20 -and $loops -lt 3; $i++) {
        Start-Sleep -Seconds 15
        $loops = Count-Loops
    }
}
$recovered = ($loops -ge 3)
$notes.Add("capture loops after boot: $loops ($(if ($recovered) { 'recovered unattended' } else { 'NOT RECOVERED' }))")

# ---- record ----
$rec = [ordered]@{
    ts = (Get-Date).ToString("o")
    boot_time = $boot.ToString("o")
    previous_shutdown_unclean = $unclean
    previous_shutdown_cause = $cause
    interrupted_merge_healed = $mergeHealed
    head = "$head"
    capture_loops = $loops
    capture_recovered = $recovered
    notes = @($notes)
}
try {
    if (-not (Test-Path $alertDir)) { New-Item -ItemType Directory -Path $alertDir -Force | Out-Null }
    Add-Content -Path $logPath -Value ($rec | ConvertTo-Json -Depth 4 -Compress) -Encoding utf8
}
catch {}
$notes | ForEach-Object { Write-Output $_ }
if (-not $recovered) { exit 2 }
exit 0
