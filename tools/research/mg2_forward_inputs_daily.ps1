# Lane L2: MG-2 / Rule B-1 forward input channel, workstation side (binding plan section 9.7; the action of the
# standing pull+receive task; also safe to run by hand). DRAFT: not registered (owner's yes needed via the coordinator).
#
# For every local target date D from -FirstDate (D0 2026-10-29) up to yesterday, in date order:
#   * D already terminal in the receipt ledger (verified, late, missing, or two failed attempts): skipped, never
#     re-pulled. A verified date only gets the optional build stage below.
#   * before the receiver's deadline (00:00 workstation local on D+2):
#       python -m weather.calibration.mg2_inputs pull --share-root <share> --inbox <inbox> --date D --ledger <ledger>
#       python -m weather.calibration.mg2_inputs receive --inbox <inbox> --date D --ledger <ledger>
#   * at or after the deadline: receive only, which appends the date's single late/missing line (no backfill).
# Stops the whole run (logged, exit 0; the next trigger is the only retry) on: pull not_ready,
# unchanged_since_refusal or refused; receive not_ready, quarantined or refused:<check>; an unparseable result.
# Refuses the whole run (logged, exit 0, nothing started) on: the STOP file, another run holding the mutex, or
# any of mg2_inputs.py / mg2_input_allowlist.py / mg2_composite.py in -Worktree not at the B binding git blob.
# -Build (off by default; a separable stage): for each verified date with no layout yet, mg2_inputs build into
# <LayoutRoot>\D through scripts\ops\workstation_heavy.ps1 -Queue -MinAvailableMemoryGB 3, with the pinned v2 parser
# worktree (HEAD must be 2e17ce0eb). emit/check are not run here (binding plan section 11: a forward multi-date
# layout is an open item, and their bound inputs are master's).
# Never handles credentials: the share is read with the logged-on user's stored credential (Interactive task), and
# mg2_inputs pull only reads under it. Reads no label, price, settlement or MG-2 output. Writes only the inbox and
# the ledger (through mg2_inputs), the layout root (with -Build) and its own logs under -LogRoot.
# -WhatIf prints the per-date plan and runs nothing.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Worktree = '',
    [string]$ShareRoot = '\\192.168.1.247\mg2-inputs',
    [string]$Inbox = 'C:\Users\Michael\Documents\github\weather\data\inbox\mg2-inputs',
    [string]$Ledger = 'C:\t\mg2\forward\input_receipts.jsonl',
    [string]$LogRoot = 'C:\t\mg2\forward\task',
    [string]$Python = 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe',
    [string]$FirstDate = '2026-10-29',
    [string]$Date = '',
    [switch]$Build,
    [string]$LayoutRoot = 'C:\t\mg2\forward\layout',
    [string]$ParserWorktree = 'C:\wt\mg2parser',
    [ValidateRange(60, 86400)][int]$QueueTimeoutSeconds = 7200
)
$ErrorActionPreference = 'Stop'
if (-not $Worktree) { $Worktree = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath)) }  # tools\research\ -> root
# B binding blobs (claude/b-binding-package-20261028 and origin/master 1a78e1ba0 agree).
$PinnedBlobs = [ordered]@{
    'src\weather\calibration\mg2_inputs.py'          = '045956fea83dd6a3c87f03fe0ab70005679f2003'
    'src\weather\calibration\mg2_input_allowlist.py' = '0ce9002c84eaed702518ab7e516c73b5a32b0b99'
    'src\weather\calibration\mg2_composite.py'       = '8cff85ae5cfed477b3fbc77505bcb0e4d1f613ce'
}
$ParserCommit = '2e17ce0eba891b028a968ac45895d3c203ea7dda'
$TerminalStatuses = @('verified', 'late', 'missing')
$StopStatuses = @{ pull = @('not_ready', 'unchanged_since_refusal', 'refused'); receive = @('not_ready', 'quarantined') }
$culture = [Globalization.CultureInfo]::InvariantCulture
$runStamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ', $culture)
$dry = -not $PSCmdlet.ShouldProcess($LogRoot, 'MG-2 forward pull+receive')
$logDir = Join-Path $LogRoot 'logs'
$logFile = Join-Path $logDir ("pull_{0}.log" -f (Get-Date).ToString('yyyyMMdd', $culture))
$runsFile = Join-Path $logDir 'runs.jsonl'

function Write-RunLog([string]$Message) {
    $line = '{0} [{1}] {2}' -f (Get-Date).ToUniversalTime().ToString('s', $culture), $runStamp, $Message
    if ($dry) { Write-Output "WhatIf: $line"; return }
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
    Write-Output $line
}
function Write-DateOutcome([string]$Day, [string]$Step, [string]$Outcome, [string]$Detail) {
    Write-RunLog ("{0} {1} {2}: {3}" -f $Day, $Step, $Outcome, $Detail)
    if ($dry) { return }
    $row = [ordered]@{ run = $runStamp; date = $Day; step = $Step; outcome = $Outcome; detail = $Detail;
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
function Invoke-Inputs([string[]]$ModuleArgs, [string]$Tag) {
    return Invoke-Logged $Python (@('-B', '-m', 'weather.calibration.mg2_inputs') + $ModuleArgs) $Tag
}
function Invoke-Heavy([string[]]$ModuleArgs, [string]$Tag) {
    $json = '[' + ((@('-m', 'weather.calibration.mg2_inputs') + $ModuleArgs | ForEach-Object { $_ | ConvertTo-Json -Compress }) -join ',') + ']'
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
function Get-LedgerState([string]$Day) {
    # 'verified' / 'late' / 'missing' / 'closed' (two failed attempts) / '' (still open), as mg2_inputs._terminal.
    if (-not (Test-Path -LiteralPath $Ledger -PathType Leaf)) { return '' }
    $attempts = 0
    foreach ($line in [IO.File]::ReadAllLines($Ledger)) {
        if (-not $line.Trim()) { continue }
        $row = $line | ConvertFrom-Json
        if ([string]$row.target_date -cne $Day) { continue }
        if ($TerminalStatuses -ccontains [string]$row.status) { return [string]$row.status }
        if ($row.attempt) { $attempts += 1 }
    }
    if ($attempts -ge 2) { return 'closed' }
    return ''
}
function Invoke-BuildStage([string]$Day) {
    # Returns $true to continue the run, $false to stop it.
    $layout = Join-Path $LayoutRoot $Day
    if (Test-Path -LiteralPath (Join-Path $layout 'manifest.json') -PathType Leaf) { return $true }
    if (Test-Path -LiteralPath $layout) {
        Write-DateOutcome $Day 'build' 'stop' "$layout exists without manifest.json: operator review (never rewritten)"; return $false
    }
    $verified = Join-Path $Inbox "$Day\verified"
    if (-not (Test-Path -LiteralPath $verified -PathType Container)) {
        Write-DateOutcome $Day 'build' 'stop' "ledger says verified but $verified is absent"; return $false
    }
    if ($dry) { Write-DateOutcome $Day 'build' 'plan' "mg2_inputs build -> $layout (workstation_heavy -Queue)"; return $true }
    $r = Invoke-Heavy @('build', '--bundle', $verified, '--date', $Day, '--out', $layout,
        '--parser-worktree', $ParserWorktree, '--parser-python', $Python) "$Day-build"
    if ($r.code -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $layout 'manifest.json') -PathType Leaf)) {
        Write-DateOutcome $Day 'build' 'stop' "build failed (exit $($r.code), log $($r.log))"; return $false
    }
    Write-DateOutcome $Day 'build' 'built' $layout
    return $true
}

# Children import the worktree's src first (the venv's .pth points at the main checkout's src).
$env:PYTHONPATH = Join-Path $Worktree 'src'
if (-not $dry) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
if (Test-Path -LiteralPath (Join-Path $LogRoot 'STOP')) { Write-RunLog 'refused: STOP file present; nothing run'; exit 0 }
$mutex = New-Object Threading.Mutex($false, 'Local\WeatherMg2ForwardInputs')
$owned = $false
try { $owned = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owned = $true }
if (-not $owned) { Write-RunLog 'refused: another MG-2 forward input run holds the mutex; nothing run'; exit 0 }
try {
    foreach ($rel in $PinnedBlobs.Keys) {
        $path = Join-Path $Worktree $rel
        $got = if (Test-Path -LiteralPath $path -PathType Leaf) { Get-GitBlobLf $path } else { 'missing' }
        if ($got -cne $PinnedBlobs[$rel]) {
            Write-RunLog "refused: $rel blob $got != pinned $($PinnedBlobs[$rel]) in $Worktree; nothing run"
            exit 0
        }
    }
    if ($Build) {
        $parserHead = try { $ErrorActionPreference = 'Continue'; [string](& git -C $ParserWorktree rev-parse HEAD 2>$null) } catch { '' } finally { $ErrorActionPreference = 'Stop' }
        if ($parserHead.Trim() -cne $ParserCommit) {
            Write-RunLog "refused: -Build parser worktree $ParserWorktree HEAD '$($parserHead.Trim())' != $ParserCommit; nothing run"
            exit 0
        }
    }
    Write-RunLog ("start: worktree {0}, pins ok (mg2_inputs 045956fe, allowlist 0ce9002c, composite 8cff85ae), share {1}, build {2}" -f $Worktree, $ShareRoot, [bool]$Build)
    $now = Get-Date
    $yesterday = $now.Date.AddDays(-1)
    $first = [datetime]::ParseExact($FirstDate, 'yyyy-MM-dd', $culture)
    $days = @()
    if ($Date) {
        $d = [datetime]::ParseExact($Date, 'yyyy-MM-dd', $culture)
        if ($d -lt $first) { Write-DateOutcome $Date 'plan' 'stop' "before the first date $FirstDate (D0)"; exit 0 }
        if ($d -gt $yesterday) { Write-DateOutcome $Date 'plan' 'stop' 'not a finished local date'; exit 0 }
        $days = @($d)
    } else {
        for ($d = $first; $d -le $yesterday; $d = $d.AddDays(1)) { $days += $d }
    }
    foreach ($dayDate in $days) {
        $day = $dayDate.ToString('yyyy-MM-dd', $culture)
        $state = Get-LedgerState $day
        if ($state -ceq 'verified') {
            if ($Build -and -not (Invoke-BuildStage $day)) { break }
            continue
        }
        if ($state) { continue }  # late, missing or closed: final, never re-pulled
        $pastDeadline = $now -ge $dayDate.AddDays(2)
        if ($dry) {
            $plan = if ($pastDeadline) { 'receive only (records late/missing)' } else { 'pull + receive' }
            Write-DateOutcome $day 'plan' 'plan' $plan; continue
        }
        if (-not $pastDeadline) {
            $r = Invoke-Inputs @('pull', '--share-root', $ShareRoot, '--inbox', $Inbox, '--date', $day, '--ledger', $Ledger) "$day-pull"
            $status = Get-JsonStatus $r.stdout
            if (-not $status -or $StopStatuses.pull -ccontains $status) {
                Write-DateOutcome $day 'pull' 'stop' ("status '{0}' (exit {1}, log {2})" -f $status, $r.code, $r.log); break
            }
            Write-DateOutcome $day 'pull' $status ("exit {0}" -f $r.code)
            if ($status -ceq 'already_recorded') { continue }
        }
        $r = Invoke-Inputs @('receive', '--inbox', $Inbox, '--date', $day, '--ledger', $Ledger) "$day-receive"
        $status = Get-JsonStatus $r.stdout
        if (-not $status -or $status.StartsWith('refused') -or $StopStatuses.receive -ccontains $status) {
            Write-DateOutcome $day 'receive' 'stop' ("status '{0}' (exit {1}, log {2})" -f $status, $r.code, $r.log); break
        }
        Write-DateOutcome $day 'receive' $status ("exit {0}" -f $r.code)
        if ($status -ceq 'verified' -and $Build -and -not (Invoke-BuildStage $day)) { break }
    }
    Write-RunLog 'done'
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
