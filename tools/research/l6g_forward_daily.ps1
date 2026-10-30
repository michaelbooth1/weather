# Lane L2: daily L6_G forward emission on the workstation (the action of the L6_G daily task; safe to run by hand).
#
# Pre-registration: docs/research/gefs-members-l11-2026-10-26/l6g_forward_prereg_FROZEN_2026-10-30.md (D0 2026-10-31).
# For every finished local date D from -FirstDate up to yesterday that has no vectors yet, it runs the chain
#   1. mg2_inputs pull + receive (read-only copy of <share>\<D>\, verified into L6_G's own inbox and ledger);
#   2. mg2_inputs build (label-free layout) and mg2_composite captured-nowcast --prev-root, each through
#      workstation_heavy.ps1 -Queue, into a fresh per-attempt work directory;
#   3. l6g_forward_frame run (frame + l6g_forward_emit.emit_day: vectors\<D>.parquet + one receipt row).
# Idempotent: a date whose vectors exist is a no-op. It never writes a partial emission: a missing or unverified
# bundle, a missing GEFS recorder manifest or any failed step is a logged refusal for that date, and the frame and
# vectors are written only by the last step (exclusive create). A date whose frame exists without vectors is left
# for the operator (the builder never rewrites).
# Point-in-time: a bundle counts only if L6_G's receiver verified it by 23:59 local on D+1 (mg2_inputs.receive's own
# deadline; after it the receiver records late/missing and the date is never emitted). Every later step reads only
# hash-pinned, as-of-capture inputs (verified bundle, recorder manifest, frozen states), so a verified date missed by
# the task can still be emitted on a later run with identical content; the receipt's emitted_utc discloses lateness.
# Refuses the whole run (logged, exit 0) on: STOP file, another run holding the mutex, or any pinned module in the
# worktree not at its pinned git blob. Never touches B's ledger (C:\t\mg2\forward), the share (read-only) or
# anything outside -Root. -WhatIf prints the per-date plan and runs nothing.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Worktree = '',
    [string]$Root = 'C:\t\l6g\forward',
    [string]$ShareRoot = '\\192.168.1.247\mg2-inputs',
    [string]$ParserWorktree = 'C:\wt\l6g-parser-pinned',
    [string]$Python = 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe',
    [string]$ResearchRoot = 'C:\Users\Michael\Documents\github\weather\data\research',
    [string]$L6State = 'C:\t\l6g\forward\pins\l6_own_state_octdec.pkl',
    [string]$Coefficients = 'C:\t\l6g\forward\pins\mg2_coefficients.json',
    [string]$FirstDate = '2026-10-31',
    [string]$LastDate = '2026-12-31',
    [string]$Date = '',
    [ValidateRange(60, 86400)][int]$QueueTimeoutSeconds = 7200
)
$ErrorActionPreference = 'Stop'
if (-not $Worktree) { $Worktree = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath)) }  # tools\research\ -> root
$L6StateSha256 = '800072c79af65394cc33134cbaae34af65c4428feb3934e35f8cd6cd153ee2db'
$PinnedBlobs = [ordered]@{
    'src\weather\calibration\l6g_forward_emit.py'  = '3ecf3819342b051fa86d0adebca4d268ddeea398'
    'src\weather\calibration\l6g_forward_look.py'  = '17539ca496d32d935a80461859d555243a9a317e'
    'src\weather\calibration\l6g_forward_frame.py' = '75a587b02ca5a579fdbbd08c65387fad249d4db9'
    'src\weather\calibration\mg2_inputs.py'        = '045956fea83dd6a3c87f03fe0ab70005679f2003'
    'src\weather\calibration\mg2_composite.py'     = '8cff85ae5cfed477b3fbc77505bcb0e4d1f613ce'
}
$culture = [Globalization.CultureInfo]::InvariantCulture
$runStamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ', $culture)
$dry = -not $PSCmdlet.ShouldProcess($Root, 'L6_G daily emission')
$logDir = Join-Path $Root 'logs'
$logFile = Join-Path $logDir ("daily_{0}.log" -f (Get-Date).ToString('yyyyMMdd', $culture))
$runsFile = Join-Path $logDir 'runs.jsonl'

function Write-DailyLog([string]$Message) {
    $line = '{0} [{1}] {2}' -f (Get-Date).ToUniversalTime().ToString('s', $culture), $runStamp, $Message
    if ($dry) { Write-Output "WhatIf: $line"; return }
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
    Write-Output $line
}
function Write-DateOutcome([string]$Day, [string]$Outcome, [string]$Detail) {
    Write-DailyLog ("{0} {1}: {2}" -f $Day, $Outcome, $Detail)
    if ($dry) { return }
    $row = [ordered]@{ run = $runStamp; date = $Day; outcome = $Outcome; detail = $Detail;
        logged_utc = (Get-Date).ToUniversalTime().ToString('o', $culture) }
    Add-Content -LiteralPath $runsFile -Value ($row | ConvertTo-Json -Compress) -Encoding UTF8
}
function Get-GitBlobLf([string]$Path) {
    $raw = [IO.File]::ReadAllBytes($Path)
    $text = [Text.Encoding]::GetEncoding(28591).GetString($raw).Replace("`r`n", "`n")
    $data = [Text.Encoding]::GetEncoding(28591).GetBytes($text)
    $head = [Text.Encoding]::ASCII.GetBytes("blob $($data.Length)`0")
    $sha1 = [Security.Cryptography.SHA1]::Create()
    return (($sha1.ComputeHash([byte[]]($head + $data)) | ForEach-Object { $_.ToString('x2') }) -join '')
}
function Get-FileSha256([string]$Path) {
    $sha = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($Path)
    try { return (($sha.ComputeHash($stream) | ForEach-Object { $_.ToString('x2') }) -join '') } finally { $stream.Dispose() }
}
function ConvertTo-ArgString([string[]]$Tokens) {
    return (($Tokens | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join ' ')
}
function Invoke-Logged([string]$Exe, [string[]]$Tokens, [string]$Tag) {
    # Child output goes to per-step files under logs\; the exit code and the stdout text come back.
    $out = Join-Path $logDir ("{0}_{1}.stdout.log" -f $runStamp, $Tag)
    $err = Join-Path $logDir ("{0}_{1}.stderr.log" -f $runStamp, $Tag)
    $p = Start-Process -FilePath $Exe -ArgumentList (ConvertTo-ArgString $Tokens) -WorkingDirectory $Worktree `
        -NoNewWindow -Wait -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    $text = if (Test-Path -LiteralPath $out) { [IO.File]::ReadAllText($out) } else { '' }
    return @{ code = $p.ExitCode; stdout = $text; log = $out }
}
function Invoke-Py([string[]]$ModuleArgs, [string]$Tag) {
    return Invoke-Logged $Python (@('-B', '-m') + $ModuleArgs) $Tag
}
function Invoke-Heavy([string[]]$ModuleArgs, [string]$Tag) {
    $json = '[' + ((@('-m') + $ModuleArgs | ForEach-Object { $_ | ConvertTo-Json -Compress }) -join ',') + ']'
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
    $ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    return Invoke-Logged $ps @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
        (Join-Path $Worktree 'scripts\ops\workstation_heavy.ps1'), '-Kind', 'weather_heavy', '-PythonPath', $Python,
        '-ArgumentsBase64', $b64, '-RepoRoot', $Worktree, '-Queue', '-QueueTimeoutSeconds', "$QueueTimeoutSeconds",
        '-MinAvailableMemoryGB', '3') $Tag
}
function Get-JsonStatus([string]$Text) {
    $last = @($Text -split "`r?`n" | Where-Object { $_.Trim().StartsWith('{') }) | Select-Object -Last 1
    if (-not $last) { return '' }
    try { return [string]($last | ConvertFrom-Json).status } catch { return '' }
}

# Children import the worktree's src first (the venv's .pth points at the main checkout's src).
$env:PYTHONPATH = Join-Path $Worktree 'src'
if (-not $dry) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
if (Test-Path -LiteralPath (Join-Path $Root 'STOP')) { Write-DailyLog 'refused: STOP file present; nothing run'; exit 0 }
$mutex = New-Object Threading.Mutex($false, 'Local\WeatherL6gForwardDaily')
$owned = $false
try { $owned = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owned = $true }
if (-not $owned) { Write-DailyLog 'refused: another L6_G daily run holds the mutex; nothing run'; exit 0 }
try {
    foreach ($rel in $PinnedBlobs.Keys) {
        $path = Join-Path $Worktree $rel
        $got = if (Test-Path -LiteralPath $path -PathType Leaf) { Get-GitBlobLf $path } else { 'missing' }
        if ($got -cne $PinnedBlobs[$rel]) {
            Write-DailyLog "refused: $rel blob $got != pinned $($PinnedBlobs[$rel]) in $Worktree; nothing run"
            exit 0
        }
    }
    Write-DailyLog ("start: worktree {0}, pins ok (emit 3ecf3819, look 17539ca4, frame 75a587b0), share {1}" -f $Worktree, $ShareRoot)
    $yesterday = (Get-Date).Date.AddDays(-1)
    $first = [datetime]::ParseExact($FirstDate, 'yyyy-MM-dd', $culture)
    $last = [datetime]::ParseExact($LastDate, 'yyyy-MM-dd', $culture)
    if ($last -gt $yesterday) { $last = $yesterday }
    $days = @()
    if ($Date) {
        $d = [datetime]::ParseExact($Date, 'yyyy-MM-dd', $culture)
        if ($d -lt $first) { Write-DateOutcome $Date 'refused' "before the first emitted date $FirstDate (D0)"; exit 0 }
        if ($d -gt $yesterday) { Write-DateOutcome $Date 'refused' 'not a finished local date'; exit 0 }
        $days = @($d)
    } else {
        for ($d = $first; $d -le $last; $d = $d.AddDays(1)) { $days += $d }
    }
    $inbox = Join-Path $Root 'inbox'
    $ledger = Join-Path $Root 'bundle_receipts.jsonl'
    foreach ($dayDate in $days) {
        $day = $dayDate.ToString('yyyy-MM-dd', $culture)
        if (Test-Path -LiteralPath (Join-Path $Root "vectors\$day.parquet")) { Write-DateOutcome $day 'noop' 'already emitted'; continue }
        if (Test-Path -LiteralPath (Join-Path $Root "frames\$day")) {
            Write-DateOutcome $day 'refused' "frames\$day exists without vectors: operator review (never rewritten)"; continue
        }
        if (-not (Test-Path -LiteralPath (Join-Path $Root "gefs\$day\manifest.json") -PathType Leaf)) {
            Write-DateOutcome $day 'refused' 'GEFS recorder manifest missing'; continue
        }
        $missingInputs = @(foreach ($f in @((Join-Path $Root 'state\l6g_state.json'), $L6State, $Coefficients)) {
                if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { $f } })
        if ($missingInputs.Count) { Write-DateOutcome $day 'refused' ('pinned input missing: ' + ($missingInputs -join ', ')); continue }
        $verified = Join-Path $inbox "$day\verified"
        $pastDeadline = (Get-Date) -ge $dayDate.AddDays(2)
        if (-not (Test-Path -LiteralPath $verified -PathType Container)) {
            $onShare = Test-Path -LiteralPath (Join-Path $ShareRoot "$day\manifest.json.sha256") -PathType Leaf
            $pulled = Test-Path -LiteralPath (Join-Path $inbox "$day\incoming") -PathType Container
            if (-not $onShare -and -not $pulled -and -not $pastDeadline) {
                Write-DateOutcome $day 'refused' "bundle missing: no $ShareRoot\$day\manifest.json.sha256 yet (retried by the next trigger)"; continue
            }
            if ($dry) { Write-DateOutcome $day 'plan' 'pull + receive, build, captured-nowcast, frame run'; continue }
            $r = Invoke-Py @('weather.calibration.mg2_inputs', 'pull', '--share-root', $ShareRoot, '--inbox', $inbox,
                '--date', $day, '--ledger', $ledger) "$day-pull"
            Write-DailyLog ("{0} pull exit {1} status {2}" -f $day, $r.code, (Get-JsonStatus $r.stdout))
            $r = Invoke-Py @('weather.calibration.mg2_inputs', 'receive', '--inbox', $inbox, '--date', $day,
                '--ledger', $ledger) "$day-receive"
            $status = Get-JsonStatus $r.stdout
            if (-not (Test-Path -LiteralPath $verified -PathType Container)) {
                Write-DateOutcome $day 'refused' ("bundle not verified (receive exit {0}, status '{1}'); nothing emitted" -f $r.code, $status); continue
            }
        }
        if ($dry) { Write-DateOutcome $day 'plan' 'build, captured-nowcast, frame run (bundle verified)'; continue }
        $work = Join-Path $Root "work\$day\$runStamp"
        $layout = Join-Path $work 'layout'
        $nowcasts = Join-Path $work 'nowcasts'
        New-Item -ItemType Directory -Force -Path $work | Out-Null
        $r = Invoke-Heavy @('weather.calibration.mg2_inputs', 'build', '--bundle', $verified, '--date', $day, '--out', $layout,
            '--parser-worktree', $ParserWorktree, '--parser-python', $Python) "$day-build"
        if ($r.code -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $layout 'manifest.json'))) {
            Write-DateOutcome $day 'refused' "layout build failed (exit $($r.code), log $($r.log)); nothing emitted"; continue
        }
        $r = Invoke-Heavy @('weather.calibration.mg2_composite', 'captured-nowcast', '--layout', $layout,
            '--replay-root', $verified, '--research-root', $ResearchRoot, '--first', $day, '--last', $day,
            '--out', $nowcasts, '--prev-root', (Join-Path $verified 'prev_day'), '--l6-state', $L6State,
            '--l6-state-sha256', $L6StateSha256) "$day-nowcast"
        if ($r.code -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $nowcasts 'nowcasts.parquet'))) {
            Write-DateOutcome $day 'refused' "captured-nowcast failed (exit $($r.code), log $($r.log)); nothing emitted"; continue
        }
        $r = Invoke-Py @('weather.calibration.l6g_forward_frame', 'run', '--date', $day, '--layout-root', $layout,
            '--nowcasts', (Join-Path $nowcasts 'nowcasts.parquet'), '--coefficients', $Coefficients,
            '--frame-root', (Join-Path $Root 'frames'), '--state', (Join-Path $Root 'state\l6g_state.json'),
            '--recorder-root', (Join-Path $Root 'gefs'), '--out-root', $Root) "$day-emit"
        if ($r.code -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $Root "vectors\$day.parquet"))) {
            Write-DateOutcome $day 'refused' "frame/emit refused (exit $($r.code), log $($r.log))"; continue
        }
        $sha = Get-FileSha256 (Join-Path $Root "vectors\$day.parquet")
        Write-DateOutcome $day 'emitted' ("vectors sha256 {0}; {1}" -f $sha, $r.stdout.Trim())
    }
    Write-DailyLog 'done'
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
