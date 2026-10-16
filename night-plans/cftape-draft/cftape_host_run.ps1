<#
Counterfactual fill-tape host export (item 330 build 2 input). Written for master-agent on 2026-10-16; revision 2
(after the Fable review: one backlog per fill rule). Cloned from the FC-11 wrapper r3
(night-plans/2026-10-19/fc11_host_run.ps1).
Copy it to the host as text and run it with Windows PowerShell 5.1:

  powershell -NoProfile -ExecutionPolicy Bypass -File cftape_host_run.ps1 -RepoRoot <production repo> -DryRun
  powershell -NoProfile -ExecutionPolicy Bypass -File cftape_host_run.ps1 -RepoRoot <production repo> -MaxDays 1
  powershell -NoProfile -ExecutionPolicy Bypass -File cftape_host_run.ps1 -RepoRoot <production repo> -MaxDays 1 -FillRule at_price

Fill rule
- One rule per run, into <OutRoot>\backlog-<FillRule>. The default is strictly_through (build 2's default fit);
  at_price is build 2's declared sensitivity and runs as its own backlog. The exporter refuses (exit 2) a backlog
  that already holds receipts of the other rule.
- Needs claude/cf-tape-export-20261016 at the post-review tip or later (the rule check and strict
  point-in-time context).

Contract

Prerequisites
- Needs weather.market.maker_counterfactual_tape on the checkout: branch claude/cf-tape-export-20261016 or later,
  merged roll-free.

Slot and lease
- Host load policy 4f, the same slot as FC-11. Do not run both on one night.
- Start only between 03:50 and 04:00 local. The exporter gets --deadline 04:30, so no new day starts after it.
- The wrapper hard-kills the child tree at 04:45.
- Takes the shared heavy-work lease (workload 'cftape_export'). If the lease is busy it retries every 15 s, and
  exits 4 if it has not got the lease by 04:00:59.
- One child, in a kill-on-close job. The lease is released only after teardown is proved; otherwise it is
  poisoned, per the admission contract.

Output and resume
- The work is chunked across nights. The exporter output lives in a stable <OutRoot>\backlog-<FillRule>, outside data\ and
  outside the 88a root.
- A day with a receipt is skipped. -MaxDays N counts only days exported this run (default 1).
- An interrupted day has no receipt and is exported again. Its leftover tables are renamed *.orphan-<stamp>, never
  overwritten or deleted.
- Only a matching day is sealed (receipts\<day>.json). A mismatch writes receipts\<day>.mismatch-<stamp>.json and
  is redone after every never-attempted day.
- Each run's own files (child logs, wrapper_receipt.json) go to a fresh <OutRoot>\runs\cftape-<utc stamp>-<8 hex>.

Which data is read
- Reads only 88a UTC day folders dated on or before 2026-09-29. The date is parsed from the folder NAME before
  anything inside is listed or opened. This wrapper does that for -DryRun; the exporter does it for the run.
- Folders dated 2026-09-30..2026-10-15 or later are never listed, stat'ed or opened.
- --max-date 2026-09-29 is fixed, and the exporter itself refuses anything later.
- Inside an allowed day, a band whose event date is after 09-29 is dropped before its book journals are opened.
- The exporter opens inputs read-only with FILE_SHARE_READ|WRITE|DELETE, so the 88a writer and archive can still
  write, rename and delete. It never opens .writer.lock or status.json.
- -DryRun opens no file. It lists directories, reads FileInfo.Length, and checks which days already have a receipt.

Memory
- Every 5 s the child tree (the child plus its descendants by ParentProcessId) is sampled.
- A tree working-set sum above -TreeCapBytes (default 1 GiB) kills the tree (exit 7).
- A failed sample is counted, never fatal.

Rollback
- Delete <OutRoot>. Nothing else is written; the 88a root is only read.

Exit codes
  0  run finished, and every day exported this run matched its manifests (or -DryRun finished)
  1  run finished, and at least one day did not match (see the exporter run receipt); also an unexpected child crash
  2  the exporter refused the request (max date, out-dir inside an input tree, a backlog sealed under the other rule)
  3  hard stop: the child tree was killed at 04:45 (days written before then keep their receipts)
  4  not admitted: outside 03:50-04:00, the lease stayed busy until 04:00:59, or admission threw
  5  preflight failed: no venv python, module missing, git HEAD unreadable, output under data or the 88a root, no 88a root
  6  teardown not proved (the lease was poisoned and needs the admission recovery procedure), or any wrapper fault
  7  memory stop: the child tree exceeded -TreeCapBytes and was killed
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [string]$EvidenceRoot = "",
    [string]$OutRoot = "C:\cftape-out",
    [string]$MinDate = "",
    [ValidateRange(1, 400)][int]$MaxDays = 1,
    [ValidateSet('at_price', 'strictly_through')][string]$FillRule = 'strictly_through',
    [int64]$TreeCapBytes = 1GB,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$MaxDate = [datetime]'2026-09-29'
$ReservedFirst = [datetime]'2026-09-30'
$ReservedLast = [datetime]'2026-10-15'
$StartEarliest = (Get-Date).Date.AddHours(3).AddMinutes(50)
$StartLatest = (Get-Date).Date.AddHours(4).AddMinutes(1)      # exclusive: through 04:00:59
$ChildDeadline = (Get-Date).Date.AddHours(4).AddMinutes(30)
$HardKill = (Get-Date).Date.AddHours(4).AddMinutes(45)
$Workload = 'cftape_export'
$Module = 'weather.market.maker_counterfactual_tape'

$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not $EvidenceRoot) { $EvidenceRoot = Join-Path $RepoRoot 'data\maker_evidence' }
$Backlog = Join-Path $OutRoot "backlog-$FillRule"   # one fill rule per backlog; the exporter refuses a mixed one (exit 2)

function Get-FolderDate([string]$Name) {
    if ($Name -notmatch '^\d{4}-\d{2}-\d{2}$') { return $null }
    $parsed = [datetime]::MinValue
    if (-not [datetime]::TryParseExact($Name, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::None, [ref]$parsed)) { return $null }
    $parsed
}
function Get-AllowedDays {
    # Name-only filter: nothing inside an excluded folder is listed or opened.
    $out = New-Object System.Collections.Generic.List[object]
    if (-not [IO.Directory]::Exists($EvidenceRoot)) { throw "88a root missing: $EvidenceRoot" }
    foreach ($dir in [IO.Directory]::EnumerateDirectories($EvidenceRoot)) {
        $d = Get-FolderDate ([IO.Path]::GetFileName($dir))
        if ($null -eq $d -or ($d -ge $ReservedFirst -and $d -le $ReservedLast) -or $d -gt $MaxDate) { continue }
        if ($MinDate -and $d -lt [datetime]$MinDate) { continue }
        $out.Add([pscustomobject]@{ Dir = $dir; Date = $d })
    }
    $out
}
function Get-Sum($Items, [string]$Property) {
    # Measure-Object's .Sum is absent on empty input under StrictMode; this is total 0 instead.
    $total = 0L
    foreach ($item in @($Items)) { if ($null -ne $item -and $null -ne $item.$Property) { $total += [int64]$item.$Property } }
    $total
}
function Write-Json($Object, [string]$Path) {
    [IO.File]::WriteAllText($Path, ($Object | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false)))
}
function Get-FileSha([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash }
function Test-DayDone([string]$Day) { [IO.File]::Exists((Join-Path $Backlog "receipts\$Day.json")) }
function Get-MismatchCount([string]$Day) {
    $dir = Join-Path $Backlog 'receipts'
    if (-not [IO.Directory]::Exists($dir)) { return 0 }
    @([IO.Directory]::EnumerateFiles($dir, "$Day.mismatch-*.json")).Count
}
$SealedReceipt = '^\d{4}-\d{2}-\d{2}\.json$'

# ---- dry run: stat only
if ($DryRun) {
    $rows = @()
    foreach ($e in Get-AllowedDays) {
        $segments = 0; $sealed = 0; $files = 0; $bytes = 0L
        foreach ($seg in [IO.Directory]::EnumerateDirectories($e.Dir)) {
            if ([IO.Path]::GetFileName($seg) -notmatch '^\d{2}-[0-9a-f]{12}$') { continue }
            $segments++
            $isSealed = $false
            foreach ($f in [IO.Directory]::EnumerateFiles($seg)) {
                $files++; $bytes += (New-Object IO.FileInfo $f).Length
                $leaf = [IO.Path]::GetFileName($f)
                if ($leaf -eq 'manifest.json' -or $leaf -eq 'manifest.json.gz') { $isSealed = $true }
            }
            if ($isSealed) { $sealed++ }
        }
        $k = $e.Date.ToString('yyyy-MM-dd')
        $rows += [pscustomobject][ordered]@{ date = $k; done = (Test-DayDone $k); mismatches = (Get-MismatchCount $k)
                                             segments = $segments; unsealed = ($segments - $sealed); files = $files; bytes = $bytes }
    }
    $days = @($rows | Sort-Object date -Descending)
    $todo = @($days | Where-Object { -not $_.done })
    $total = Get-Sum $days 'bytes'; $todoBytes = Get-Sum $todo 'bytes'
    $days | Format-Table -AutoSize | Out-String | Write-Output
    Write-Output ("DRYRUN days={0} done={1} remaining={2} segments={3} files={4} input_bytes={5} ({6:N1} MiB) remaining_bytes={7} ({8:N1} MiB); next run order is newest first; max_date={9}; reserved {10}..{11} not listed; no file was opened" -f `
        $days.Count, ($days.Count - $todo.Count), $todo.Count, (Get-Sum $days 'segments'), (Get-Sum $days 'files'), $total, ($total / 1MB),
        $todoBytes, ($todoBytes / 1MB), $MaxDate.ToString('yyyy-MM-dd'), $ReservedFirst.ToString('yyyy-MM-dd'), $ReservedLast.ToString('yyyy-MM-dd'))
    exit 0
}

# ---- preflight
$now = Get-Date
if ($now -lt $StartEarliest -or $now -ge $StartLatest) { Write-Output "NOT ADMITTED: start only 03:50-04:00 local (slot 03:50-04:45)"; exit 4 }
$py = Join-Path $RepoRoot 'venv\Scripts\python.exe'
$modulePath = Join-Path $RepoRoot 'src\weather\market\maker_counterfactual_tape.py'
if (-not (Test-Path -LiteralPath $py -PathType Leaf)) { Write-Output "PREFLIGHT: no venv python at $py"; exit 5 }
if (-not (Test-Path -LiteralPath $modulePath -PathType Leaf)) { Write-Output "PREFLIGHT: exporter module missing ($modulePath)"; exit 5 }
if (-not [IO.Directory]::Exists($EvidenceRoot)) { Write-Output "PREFLIGHT: 88a root missing: $EvidenceRoot"; exit 5 }
$head = $null
try { $head = [string](& git -C $RepoRoot rev-parse HEAD) } catch { $head = $null }
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($head)) { Write-Output "PREFLIGHT: git rev-parse HEAD failed in $RepoRoot"; exit 5 }
$head = $head.Trim()
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$RunDir = Join-Path $OutRoot ("runs\cftape-{0}-{1}" -f $stamp, [guid]::NewGuid().ToString('N').Substring(0, 8))
$outFull = [IO.Path]::GetFullPath($OutRoot).TrimEnd('\') + '\'
foreach ($guard in @((Join-Path $RepoRoot 'data'), $EvidenceRoot)) {
    $g = [IO.Path]::GetFullPath($guard).TrimEnd('\') + '\'
    if ($outFull.StartsWith($g, [StringComparison]::OrdinalIgnoreCase)) { Write-Output "PREFLIGHT: output under $guard"; exit 5 }
}
if (Test-Path -LiteralPath $RunDir) { Write-Output "PREFLIGHT: run dir exists: $RunDir"; exit 5 }
$moduleSha = Get-FileSha $modulePath

. (Join-Path $RepoRoot 'scripts\ops\windows_kill_on_close_job.ps1')
. (Join-Path $RepoRoot 'scripts\ops\workload_admission.ps1')
# The dot-sourced helpers set StrictMode 2.0 in this scope; the receipt code below relies on lenient property access.
Set-StrictMode -Off

$lease = $null; $leaseAttempts = 0
while ($true) {
    $leaseAttempts++
    try { $lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $RepoRoot -Workload $Workload } catch { Write-Output "NOT ADMITTED: $($_.Exception.Message)"; exit 4 }
    if ($null -ne $lease) { break }
    # Busy (a quiet-window merge can hold it to ~03:50): retry every 15 s, never starting after $StartLatest.
    if ((Get-Date).AddSeconds(15) -ge $StartLatest) { Write-Output "NOT ADMITTED: heavy-work lease busy until 04:01 ($leaseAttempts attempts)"; exit 4 }
    Start-Sleep -Seconds 15
}

$job = $null; $child = $null; $output = $null; $proved = $false; $hardStop = $false; $memStop = $false; $code = $null; $fault = $null
$peakTree = 0L; $peakAt = $null; $perProc = @{}; $samples = 0; $sampleErrors = 0; $lastSampleError = $null
$started = Get-Date
try {
    New-Item -ItemType Directory -Path $RunDir | Out-Null
    New-Item -ItemType Directory -Path $Backlog -Force | Out-Null
    $tokens = @('-P', '-B', '-m', $Module, 'export', '--root', $EvidenceRoot, '--out-dir', $Backlog,
                '--max-date', $MaxDate.ToString('yyyy-MM-dd'), '--fill-rule', $FillRule, '--code-commit', $head,
                '--deadline', $ChildDeadline.ToString('yyyy-MM-ddTHH:mm:sszzz'), '--max-days', [string]$MaxDays)
    if ($MinDate) { $tokens += @('--min-date', $MinDate) }
    $env:PYTHONPATH = Join-Path $RepoRoot 'src'
    $job = New-WeatherKillOnCloseJob
    $output = [Weather.Operations.KillOnCloseJob+CapturedOutput]::new("$RunDir\child.stdout.log", "$RunDir\child.stderr.log", 8388608)
    $child = Start-WeatherProcessInJob -Job $job -FilePath $py -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $tokens) `
        -WorkingDirectory $RepoRoot -OutputCapture $output
    $null = $child.Handle
    $nextSample = Get-Date
    while (-not $child.HasExited) {
        if ((Get-Date) -ge $HardKill) { $hardStop = $true; break }
        if ((Get-Date) -ge $nextSample) {
            $nextSample = (Get-Date).AddSeconds(5)
            try {
                $all = @(Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId, WorkingSetSize -ErrorAction Stop)
                $tree = @($child.Id); $added = $true
                while ($added) {
                    $added = $false
                    foreach ($p in $all) { if ($tree -contains [int]$p.ParentProcessId -and $tree -notcontains [int]$p.ProcessId) { $tree += [int]$p.ProcessId; $added = $true } }
                }
                $sum = 0L
                foreach ($p in $all) {
                    if ($tree -notcontains [int]$p.ProcessId) { continue }
                    $sum += [int64]$p.WorkingSetSize
                    try { $gp = Get-Process -Id $p.ProcessId -ErrorAction Stop; $perProc["$($p.ProcessId)"] = [math]::Max([int64]$perProc["$($p.ProcessId)"], [int64]$gp.PeakWorkingSet64) } catch {}
                }
                if ($sum -gt $peakTree) { $peakTree = $sum; $peakAt = (Get-Date).ToString('o') }
                $samples++
                if ($sum -gt $TreeCapBytes) { $memStop = $true; break }
            }
            catch { $sampleErrors++; $lastSampleError = $_.Exception.Message }
        }
        $output.Drain(); Start-Sleep -Milliseconds 200; $child.Refresh()
    }
    if (-not $hardStop -and -not $memStop) { $child.WaitForExit(); $code = [int]$child.ExitCode }
}
catch { $fault = $_.Exception.Message }
finally {
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    try {
        if ($job) { $job.TerminateAndWait(10000) }
        $proved = $true
        if ($output) { try { $output.Complete(2000) } catch { if (-not $fault) { $fault = "output capture: $($_.Exception.Message)" } } }
    }
    catch { if (-not $fault) { $fault = "teardown: $($_.Exception.Message)" } }
    finally {
        try { if ($output) { $output.Dispose() } } catch {}
        try { if ($child) { $child.Dispose() } } catch {}
        try { if ($job) { $job.Dispose() } } catch {}
        if ($proved) { Exit-WeatherHeavyWorkloadLease -Lease $lease } else { Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease }
    }
}

# ---- receipt (written on every path that reached the lease)
$exit = if (-not $proved -or $fault) { 6 } elseif ($memStop) { 7 } elseif ($hardStop) { 3 } elseif ($code -eq 2) { 2 } elseif ($code -eq 0) { 0 } else { 1 }
$runReceipt = $null; $run = $null; $days = @()
try {
    $runReceipt = Get-ChildItem -LiteralPath $Backlog -Filter 'run_receipt_*.json' -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -ge $started } | Sort-Object Name | Select-Object -Last 1
    if ($runReceipt) { $run = Get-Content -LiteralPath $runReceipt.FullName -Raw | ConvertFrom-Json }
    if ($run) { $days = @($run.days | Where-Object { $_.status -eq 'extracted' }) }
}
catch { if (-not $fault) { $fault = "run receipt read: $($_.Exception.Message)" }; $exit = 6 }
# Killed runs (3, 7) write no run receipt: count the day receipts this run wrote instead.
$dayReceiptsThisRun = @(Get-ChildItem -LiteralPath (Join-Path $Backlog 'receipts') -Filter '*.json' -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -ge $started })
$daysComplete = @(Get-ChildItem -LiteralPath (Join-Path $Backlog 'receipts') -Filter '*.json' -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match $SealedReceipt }).Count
$outputs = @($dayReceiptsThisRun | ForEach-Object {
    $r = $null; try { $r = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json } catch {}
    [ordered]@{ receipt = $_.Name; receipt_sha256 = Get-FileSha $_.FullName; match = if ($r) { [bool]$r.match } else { $null }
                minutes = if ($r) { $r.outputs.cf_minutes } else { $null }; fills = if ($r) { $r.outputs.cf_fills } else { $null } } })
$receipt = [ordered]@{
    receipt = 'cftape_host_wrapper_receipt'; receipt_revision = 2
    repo_head = $head; module_sha256 = $moduleSha; workload = $Workload; leased = $true; lease_attempts = $leaseAttempts
    teardown_proved = $proved; fault = $fault
    started_local = $started.ToString('o'); finished_local = (Get-Date).ToString('o')
    child_deadline_local = $ChildDeadline.ToString('o'); hard_kill_local = $HardKill.ToString('o')
    child_exit_code = $code; hard_stop = $hardStop; memory_stop = $memStop; wrapper_exit_code = $exit
    evidence_root = $EvidenceRoot; max_date = $MaxDate.ToString('yyyy-MM-dd'); min_date = $MinDate; max_days = $MaxDays; fill_rule = $FillRule
    backlog_dir = $Backlog; run_dir = $RunDir
    peak_rss = [ordered]@{ tree_working_set_bytes_max = $peakTree; at = $peakAt; cap_bytes = $TreeCapBytes; samples = $samples
                           sample_errors = $sampleErrors; last_sample_error = $lastSampleError; interval_seconds = 5
                           per_process_peak_working_set_bytes = $perProc }
    run_receipt = if ($runReceipt) { [ordered]@{ path = $runReceipt.FullName; sha256 = Get-FileSha $runReceipt.FullName } } else { $null }
    days_available = if ($run) { $run.days_available } else { $null }
    input_days = if ($run) { $run.input_days } else { $null }
    days_extracted = if ($run) { $days.Count } else { $dayReceiptsThisRun.Count }
    days_complete_in_backlog = $daysComplete
    days_remaining = if ($run) { $run.days_remaining } else { $null }
    all_match = if ($run) { [bool]$run.all_match } else { $false }
    stopped_reason = if ($run) { $run.stopped_reason } elseif ($memStop) { 'memory_cap' } elseif ($hardStop) { 'hard_kill' } else { $null }
    minutes = Get-Sum $days 'minutes'
    fills = Get-Sum $days 'fills'
    journal_bytes_read = Get-Sum $days 'journal_bytes_read'
    output_bytes = Get-Sum $days 'output_bytes'
    mismatched_days = @($days | Where-Object { -not $_.match } | ForEach-Object { $_.utc_day })
    outputs = $outputs
    stdout_sha256 = if (Test-Path -LiteralPath "$RunDir\child.stdout.log") { Get-FileSha "$RunDir\child.stdout.log" } else { $null }
    stderr_sha256 = if (Test-Path -LiteralPath "$RunDir\child.stderr.log") { Get-FileSha "$RunDir\child.stderr.log" } else { $null }
}
if (-not (Test-Path -LiteralPath $RunDir)) { New-Item -ItemType Directory -Path $RunDir -Force | Out-Null }
Write-Json $receipt (Join-Path $RunDir 'wrapper_receipt.json')
Write-Output ("CFTAPE exit={0} days={1} complete={2} remaining={3} all_match={4} minutes={5} fills={6} read={7:N1} MiB out={8:N1} MiB peak_tree_ws={9:N1} MiB sample_errors={10} hard_stop={11} memory_stop={12} run={13}" -f `
    $exit, $receipt.days_extracted, $daysComplete, $receipt.days_remaining, $receipt.all_match, $receipt.minutes, $receipt.fills,
    ($receipt.journal_bytes_read / 1MB), ($receipt.output_bytes / 1MB), ($peakTree / 1MB), $sampleErrors, $hardStop, $memStop, $RunDir)
exit $exit
