<#
FC-11 host backlog run (DLv2 S0b), written for master-agent 2026-10-16 (revision 2, after the Fable review).
Copy to the host as text; run with Windows PowerShell 5.1:

  powershell -NoProfile -ExecutionPolicy Bypass -File fc11_host_run.ps1 -RepoRoot <production repo> -DryRun
  powershell -NoProfile -ExecutionPolicy Bypass -File fc11_host_run.ps1 -RepoRoot <production repo> -MaxDays 1

Contract
- Needs weather.collection.forecast_payload_pit on the checkout (branch claude/dlv2-s0b-fc11-20261016 b509a90aa, the streaming
  revision or later).
- Slot (host load policy 4f): start only 03:50-04:00 local; the extractor gets --deadline 04:30 (no new day starts
  after it); the wrapper hard-kills the child tree at 04:45. WeatherClobTiering 05:00, WeatherClobRawTapeTiering 06:00
  and ColdSnapshotNightly 06:50 hold the same lease, so the run must be gone well before them.
- Takes the shared heavy-work lease (workload 'fc11_backlog_extract'); exits 4 at once if it is busy (an N11/N12
  merge can hold it to ~03:50). One child, in a kill-on-close job. The lease is released only after teardown is
  proved (else poisoned, per the admission contract).
- Chunked across nights: the extractor output lives in a stable <OutRoot>\backlog. A day with a receipt there is
  skipped; -MaxDays N counts only days extracted this run (default 1). An interrupted day has no receipt and is
  extracted again; its leftover table is renamed *.orphan-<stamp>, never overwritten or deleted.
- Each run's own files (child logs, wrapper_receipt.json) go to a fresh <OutRoot>\runs\fc11-<utc stamp>-<8 hex>.
- Reads only event folders whose slug date is < 2026-09-30. The date is parsed from the folder NAME before anything
  inside is listed or opened (here for -DryRun; in the extractor for the run, which re-checks each manifest row before
  opening its blob). --max-date 2026-09-29 is fixed; the extractor itself refuses any range reaching 09-30..10-15.
- The extractor opens inputs read-only with FILE_SHARE_READ|WRITE|DELETE (capture writers can still write, rename
  and delete) and streams each day to disk per fetch. -DryRun opens no file: it lists directories, reads
  FileInfo.Length, and checks which days already have a receipt.
- Memory: every 5 s the child tree (child + descendants by ParentProcessId) is sampled; a tree working-set sum above
  -TreeCapBytes (default 1 GiB) kills the tree (exit 7). A failed sample is counted, never fatal.

Exit codes
  0  run finished, every day extracted this run matched its manifest (or -DryRun finished)
  1  run finished, at least one day did not match (see the extractor run receipt)
  2  the extractor refused the request (embargo, out-dir inside the input tree, format)
  3  hard stop: the child tree was killed at 04:45 (days written before then keep their receipts)
  4  not admitted: outside 03:50-04:00, or the lease is busy / admission threw
  5  preflight failed: no venv python, module missing, git HEAD unreadable, output under data, bad snapshots root
  6  teardown not proved (the lease was poisoned: needs the admission recovery procedure), or any wrapper fault
  7  memory stop: the child tree exceeded -TreeCapBytes and was killed
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [string[]]$SnapshotsRoot = @(),
    [string]$OutRoot = "C:\fc11-out",
    [string]$MinDate = "",
    [ValidateRange(1, 400)][int]$MaxDays = 1,
    [int64]$TreeCapBytes = 1GB,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$MaxDate = '2026-09-29'
$EmbargoFirst = [datetime]'2026-09-30'
$StartEarliest = (Get-Date).Date.AddHours(3).AddMinutes(50)
$StartLatest = (Get-Date).Date.AddHours(4).AddMinutes(1)      # exclusive: through 04:00:59
$ChildDeadline = (Get-Date).Date.AddHours(4).AddMinutes(30)
$HardKill = (Get-Date).Date.AddHours(4).AddMinutes(45)
$Workload = 'fc11_backlog_extract'

$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
if ($SnapshotsRoot.Count -eq 0) { $SnapshotsRoot = @(Join-Path $RepoRoot 'data\snapshots') }
$Backlog = Join-Path $OutRoot 'backlog'
$Months = @{ january=1; february=2; march=3; april=4; may=5; june=6; july=7; august=8; september=9; october=10; november=11; december=12 }
$SlugRe = '^(?:highest|lowest)-temperature-in-(?<market>[a-z0-9-]+?)-on-(?<month>[a-z]+)-(?<day>\d{1,2})-(?<year>\d{4})$'

function Get-SlugDate([string]$Name) {
    $m = [regex]::Match($Name.ToLowerInvariant(), $SlugRe)
    if (-not $m.Success -or -not $Months.ContainsKey($m.Groups['month'].Value)) { return $null }
    try { return [datetime]::new([int]$m.Groups['year'].Value, $Months[$m.Groups['month'].Value], [int]$m.Groups['day'].Value) } catch { return $null }
}
function Get-AllowedEventDirs {
    # Name-only filter: nothing inside an excluded folder is listed or opened.
    $out = New-Object System.Collections.Generic.List[object]
    foreach ($root in $SnapshotsRoot) {
        if (-not [IO.Directory]::Exists($root)) { throw "snapshots root missing: $root" }
        foreach ($dir in [IO.Directory]::EnumerateDirectories($root)) {
            $d = Get-SlugDate ([IO.Path]::GetFileName($dir))
            if ($null -eq $d -or $d -ge $EmbargoFirst -or $d -gt [datetime]$MaxDate) { continue }
            if ($MinDate -and $d -lt [datetime]$MinDate) { continue }
            $out.Add([pscustomobject]@{ Dir = $dir; Date = $d })
        }
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

# ---- dry run: stat only
if ($DryRun) {
    $byDay = @{}
    foreach ($e in Get-AllowedEventDirs) {
        $bytes = 0L; $files = 0
        foreach ($name in @('forecast_payloads.jsonl', 'forecast_payloads_long.csv')) {
            $p = Join-Path $e.Dir $name
            if ([IO.File]::Exists($p)) { $bytes += (New-Object IO.FileInfo $p).Length; $files++ }
        }
        $blobDir = Join-Path $e.Dir 'forecast_payloads'
        if ([IO.Directory]::Exists($blobDir)) {
            foreach ($f in [IO.Directory]::EnumerateFiles($blobDir, '*', [IO.SearchOption]::AllDirectories)) {
                $bytes += (New-Object IO.FileInfo $f).Length; $files++
            }
        }
        $k = $e.Date.ToString('yyyy-MM-dd')
        if (-not $byDay.ContainsKey($k)) { $byDay[$k] = [ordered]@{ date = $k; done = (Test-DayDone $k); events = 0; files = 0; bytes = 0L } }
        $byDay[$k].events++; $byDay[$k].files += $files; $byDay[$k].bytes += $bytes
    }
    $days = @($byDay.Keys | Sort-Object -Descending | ForEach-Object { [pscustomobject]$byDay[$_] })
    $todo = @($days | Where-Object { -not $_.done })
    $total = Get-Sum $days 'bytes'; $todoBytes = Get-Sum $todo 'bytes'
    $days | Format-Table -AutoSize | Out-String | Write-Output
    Write-Output ("DRYRUN days={0} done={1} remaining={2} events={3} files={4} input_bytes={5} ({6:N1} MiB) remaining_bytes={7} ({8:N1} MiB); next run order is newest first; max_date={9}; no file was opened" -f `
        $days.Count, ($days.Count - $todo.Count), $todo.Count, (Get-Sum $days 'events'), (Get-Sum $days 'files'), $total, ($total / 1MB),
        $todoBytes, ($todoBytes / 1MB), $MaxDate)
    exit 0
}

# ---- preflight
$now = Get-Date
if ($now -lt $StartEarliest -or $now -ge $StartLatest) { Write-Output "NOT ADMITTED: start only 03:50-04:00 local (slot 04:00-04:45)"; exit 4 }
$py = Join-Path $RepoRoot 'venv\Scripts\python.exe'
$module = Join-Path $RepoRoot 'src\weather\collection\forecast_payload_pit.py'
if (-not (Test-Path -LiteralPath $py -PathType Leaf)) { Write-Output "PREFLIGHT: no venv python at $py"; exit 5 }
if (-not (Test-Path -LiteralPath $module -PathType Leaf)) { Write-Output "PREFLIGHT: FC-11 module missing ($module)"; exit 5 }
foreach ($root in $SnapshotsRoot) { if (-not [IO.Directory]::Exists($root)) { Write-Output "PREFLIGHT: snapshots root missing: $root"; exit 5 } }
$head = $null
try { $head = [string](& git -C $RepoRoot rev-parse HEAD) } catch { $head = $null }
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($head)) { Write-Output "PREFLIGHT: git rev-parse HEAD failed in $RepoRoot"; exit 5 }
$head = $head.Trim()
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$RunDir = Join-Path $OutRoot ("runs\fc11-{0}-{1}" -f $stamp, [guid]::NewGuid().ToString('N').Substring(0, 8))
$dataRoot = (Join-Path $RepoRoot 'data').TrimEnd('\') + '\'
if (([IO.Path]::GetFullPath($OutRoot).TrimEnd('\') + '\').StartsWith($dataRoot, [StringComparison]::OrdinalIgnoreCase)) { Write-Output "PREFLIGHT: output under data\"; exit 5 }
if (Test-Path -LiteralPath $RunDir) { Write-Output "PREFLIGHT: run dir exists: $RunDir"; exit 5 }
$moduleSha = Get-FileSha $module

. (Join-Path $RepoRoot 'scripts\ops\windows_kill_on_close_job.ps1')
. (Join-Path $RepoRoot 'scripts\ops\workload_admission.ps1')
# The dot-sourced helpers set StrictMode 2.0 in this scope; the receipt code below relies on lenient property access.
Set-StrictMode -Off

$lease = $null
try { $lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $RepoRoot -Workload $Workload } catch { Write-Output "NOT ADMITTED: $($_.Exception.Message)"; exit 4 }
if ($null -eq $lease) { Write-Output "NOT ADMITTED: heavy-work lease busy"; exit 4 }

$job = $null; $child = $null; $output = $null; $proved = $false; $hardStop = $false; $memStop = $false; $code = $null; $fault = $null
$peakTree = 0L; $peakAt = $null; $perProc = @{}; $samples = 0; $sampleErrors = 0; $lastSampleError = $null
$started = Get-Date
try {
    New-Item -ItemType Directory -Path $RunDir | Out-Null
    New-Item -ItemType Directory -Path $Backlog -Force | Out-Null
    $tokens = @('-P', '-B', '-m', 'weather.collection.forecast_payload_pit', '--out-dir', $Backlog, '--max-date', $MaxDate,
                '--format', 'jsonl_gz', '--deadline', $ChildDeadline.ToString('yyyy-MM-ddTHH:mm:sszzz'), '--max-days', [string]$MaxDays)
    foreach ($root in $SnapshotsRoot) { $tokens += @('--snapshots-root', $root) }
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
$daysComplete = @(Get-ChildItem -LiteralPath (Join-Path $Backlog 'receipts') -Filter '*.json' -File -ErrorAction SilentlyContinue).Count
$outputs = @($dayReceiptsThisRun | ForEach-Object {
    $r = $null; try { $r = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json } catch {}
    [ordered]@{ receipt = $_.Name; receipt_sha256 = Get-FileSha $_.FullName
                table = if ($r) { $r.output.path } else { $null }; table_bytes = if ($r) { $r.output.bytes } else { $null }
                table_sha256 = if ($r) { $r.output.sha256 } else { $null }; match = if ($r) { [bool]$r.match } else { $null } } })
$receipt = [ordered]@{
    receipt = 'fc11_host_wrapper_receipt'; receipt_revision = 2
    repo_head = $head; module_sha256 = $moduleSha; workload = $Workload; leased = $true; teardown_proved = $proved; fault = $fault
    started_local = $started.ToString('o'); finished_local = (Get-Date).ToString('o')
    child_deadline_local = $ChildDeadline.ToString('o'); hard_kill_local = $HardKill.ToString('o')
    child_exit_code = $code; hard_stop = $hardStop; memory_stop = $memStop; wrapper_exit_code = $exit
    snapshots_roots = $SnapshotsRoot; max_date = $MaxDate; min_date = $MinDate; max_days = $MaxDays
    backlog_dir = $Backlog; run_dir = $RunDir
    peak_rss = [ordered]@{ tree_working_set_bytes_max = $peakTree; at = $peakAt; cap_bytes = $TreeCapBytes; samples = $samples
                           sample_errors = $sampleErrors; last_sample_error = $lastSampleError; interval_seconds = 5
                           per_process_peak_working_set_bytes = $perProc }
    run_receipt = if ($runReceipt) { [ordered]@{ path = $runReceipt.FullName; sha256 = Get-FileSha $runReceipt.FullName } } else { $null }
    days_available = if ($run) { $run.days_available } else { $null }
    days_extracted = if ($run) { $days.Count } else { $dayReceiptsThisRun.Count }
    days_complete_in_backlog = $daysComplete
    days_remaining = if ($run) { $run.days_remaining } else { $null }
    all_match = if ($run) { [bool]$run.all_match } else { $false }
    stopped_reason = if ($run) { $run.stopped_reason } elseif ($memStop) { 'memory_cap' } elseif ($hardStop) { 'hard_kill' } else { $null }
    manifest_rows = Get-Sum $days 'manifest_rows'
    manifest_rows_extracted = Get-Sum $days 'manifest_rows_extracted'
    pit_rows = Get-Sum $days 'pit_rows'
    mismatched_days = @($days | Where-Object { -not $_.match } | ForEach-Object { $_.target_date })
    outputs = $outputs
    stdout_sha256 = if (Test-Path -LiteralPath "$RunDir\child.stdout.log") { Get-FileSha "$RunDir\child.stdout.log" } else { $null }
    stderr_sha256 = if (Test-Path -LiteralPath "$RunDir\child.stderr.log") { Get-FileSha "$RunDir\child.stderr.log" } else { $null }
}
if (-not (Test-Path -LiteralPath $RunDir)) { New-Item -ItemType Directory -Path $RunDir -Force | Out-Null }
Write-Json $receipt (Join-Path $RunDir 'wrapper_receipt.json')
Write-Output ("FC11 exit={0} days={1} complete={2} remaining={3} all_match={4} pit_rows={5} peak_tree_ws={6:N1} MiB sample_errors={7} hard_stop={8} memory_stop={9} run={10}" -f `
    $exit, $receipt.days_extracted, $daysComplete, $receipt.days_remaining, $receipt.all_match, $receipt.pit_rows, ($peakTree / 1MB),
    $sampleErrors, $hardStop, $memStop, $RunDir)
exit $exit
