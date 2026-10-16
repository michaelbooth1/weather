<#
FC-11 host backlog run (DLv2 S0b), written for master-agent 2026-10-16. Copy to the host as text; run with Windows PowerShell 5.1:

  powershell -NoProfile -ExecutionPolicy Bypass -File fc11_host_run.ps1 -RepoRoot <production repo> -DryRun
  powershell -NoProfile -ExecutionPolicy Bypass -File fc11_host_run.ps1 -RepoRoot <production repo>

Contract
- Needs weather.collection.forecast_payload_pit on the checkout (branch claude/dlv2-s0b-fc11-20261016 a2ed92347 or later).
- Real run: 00:30-08:30 start only; takes the shared heavy-work lease (workload 'fc11_backlog_extract'); one child,
  in a kill-on-close job; the extractor gets --deadline 08:15 (no new day starts after it); the wrapper hard-kills the
  child tree at 08:45 local; lease released only after teardown is proved (else poisoned, per the admission contract).
- Reads only event folders whose slug date is < 2026-09-30. The date is parsed from the folder NAME before anything
  inside is listed or opened (here for -DryRun; in the extractor for the run, which re-checks each manifest row before
  opening its blob). --max-date 2026-09-29 is fixed; the extractor itself refuses any range reaching 09-30..10-15.
- Files are opened only by CPython open() (msvcrt share mode deny-none: other readers and the capture writers are not
  blocked). -DryRun opens no file at all: it lists directories and reads FileInfo.Length only.
- Output: a fresh directory <OutRoot>\fc11-<utc stamp>-<8 hex>, refused if it exists or lies under <RepoRoot>\data.
- Peak RSS: every 5 s the child tree (child + descendants by ParentProcessId) is sampled; the receipt keeps the largest
  tree working-set sum and each process's own peak (PeakWorkingSet64 at its last sample).

Exit codes
  0  run finished, every extracted day matched its manifest (or -DryRun finished)
  1  run finished, at least one day did not match (see the extractor run receipt)
  2  the extractor refused the request (embargo, out-dir inside the input tree, format)
  3  hard stop: the child tree was killed at 08:45 (days written before then keep their receipts)
  4  not admitted: outside 00:30-08:30, or the lease is busy / admission threw
  5  preflight failed: no venv python, module missing, output dir exists or is under data, bad snapshots root
  6  teardown not proved: the lease was poisoned (needs the admission recovery procedure); also any wrapper fault
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [string[]]$SnapshotsRoot = @(),
    [string]$OutRoot = "C:\fc11-out",
    [string]$MinDate = "",
    [int]$MaxDays = 0,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$MaxDate = '2026-09-29'
$EmbargoFirst = [datetime]'2026-09-30'
$HardKill = (Get-Date).Date.AddHours(8).AddMinutes(45)
$ChildDeadline = (Get-Date).Date.AddHours(8).AddMinutes(15)
$Workload = 'fc11_backlog_extract'

$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
if ($SnapshotsRoot.Count -eq 0) { $SnapshotsRoot = @(Join-Path $RepoRoot 'data\snapshots') }
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
function Write-Json($Object, [string]$Path) {
    [IO.File]::WriteAllText($Path, ($Object | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false)))
}
function Get-FileSha([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash }

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
        if (-not $byDay.ContainsKey($k)) { $byDay[$k] = [ordered]@{ date = $k; events = 0; files = 0; bytes = 0L } }
        $byDay[$k].events++; $byDay[$k].files += $files; $byDay[$k].bytes += $bytes
    }
    $days = @($byDay.Keys | Sort-Object | ForEach-Object { [pscustomobject]$byDay[$_] })
    $total = ($days | Measure-Object -Property bytes -Sum).Sum
    $days | Format-Table -AutoSize | Out-String | Write-Output
    Write-Output ("DRYRUN days={0} events={1} files={2} input_bytes={3} ({4:N1} MiB); max_date={5}; no file was opened" -f `
        $days.Count, ($days | Measure-Object events -Sum).Sum, ($days | Measure-Object files -Sum).Sum, $total, ($total / 1MB), $MaxDate)
    exit 0
}

# ---- preflight
$now = Get-Date
$minute = $now.Hour * 60 + $now.Minute
if ($minute -lt 30 -or $minute -ge 8 * 60 + 30) { Write-Output "NOT ADMITTED: start only 00:30-08:30 local"; exit 4 }
$py = Join-Path $RepoRoot 'venv\Scripts\python.exe'
$module = Join-Path $RepoRoot 'src\weather\collection\forecast_payload_pit.py'
if (-not (Test-Path -LiteralPath $py -PathType Leaf)) { Write-Output "PREFLIGHT: no venv python at $py"; exit 5 }
if (-not (Test-Path -LiteralPath $module -PathType Leaf)) { Write-Output "PREFLIGHT: FC-11 module missing ($module)"; exit 5 }
foreach ($root in $SnapshotsRoot) { if (-not [IO.Directory]::Exists($root)) { Write-Output "PREFLIGHT: snapshots root missing: $root"; exit 5 } }
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$Out = Join-Path $OutRoot ("fc11-{0}-{1}" -f $stamp, [guid]::NewGuid().ToString('N').Substring(0, 8))
$dataRoot = (Join-Path $RepoRoot 'data').TrimEnd('\') + '\'
if (([IO.Path]::GetFullPath($Out) + '\').StartsWith($dataRoot, [StringComparison]::OrdinalIgnoreCase)) { Write-Output "PREFLIGHT: output under data\"; exit 5 }
if (Test-Path -LiteralPath $Out) { Write-Output "PREFLIGHT: output exists: $Out"; exit 5 }
New-Item -ItemType Directory -Path $Out | Out-Null
$moduleSha = Get-FileSha $module
$head = (& git -C $RepoRoot rev-parse HEAD).Trim()

. (Join-Path $RepoRoot 'scripts\ops\windows_kill_on_close_job.ps1')
. (Join-Path $RepoRoot 'scripts\ops\workload_admission.ps1')

$lease = $null
try { $lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $RepoRoot -Workload $Workload } catch { Write-Output "NOT ADMITTED: $($_.Exception.Message)"; exit 4 }
if ($null -eq $lease) { Write-Output "NOT ADMITTED: heavy-work lease busy"; exit 4 }

$tokens = @('-P', '-B', '-m', 'weather.collection.forecast_payload_pit', '--out-dir', $Out, '--max-date', $MaxDate,
            '--format', 'jsonl_gz', '--deadline', $ChildDeadline.ToString('yyyy-MM-ddTHH:mm:sszzz'))
foreach ($root in $SnapshotsRoot) { $tokens += @('--snapshots-root', $root) }
if ($MinDate) { $tokens += @('--min-date', $MinDate) }
if ($MaxDays -gt 0) { $tokens += @('--max-days', [string]$MaxDays) }

$job = $null; $child = $null; $output = $null; $proved = $false; $hardStop = $false; $code = $null; $fault = $null
$peakTree = 0L; $peakAt = $null; $perProc = @{}; $samples = 0
$started = Get-Date
$env:PYTHONPATH = Join-Path $RepoRoot 'src'
try {
    $job = New-WeatherKillOnCloseJob
    $output = [Weather.Operations.KillOnCloseJob+CapturedOutput]::new("$Out\child.stdout.log", "$Out\child.stderr.log", 8388608)
    $child = Start-WeatherProcessInJob -Job $job -FilePath $py -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $tokens) `
        -WorkingDirectory $RepoRoot -OutputCapture $output
    $null = $child.Handle
    $nextSample = Get-Date
    while (-not $child.HasExited) {
        if ((Get-Date) -ge $HardKill) { $hardStop = $true; break }
        if ((Get-Date) -ge $nextSample) {
            $all = @(Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId, WorkingSetSize)
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
            $samples++; $nextSample = (Get-Date).AddSeconds(5)
        }
        $output.Drain(); Start-Sleep -Milliseconds 200; $child.Refresh()
    }
    if (-not $hardStop) { $child.WaitForExit(); $code = [int]$child.ExitCode }
}
catch { $fault = $_.Exception.Message }
finally {
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    try {
        if ($job) { $job.TerminateAndWait(10000) }
        $proved = $true
        if ($output) { $output.Complete(2000) }
    }
    finally {
        if ($output) { $output.Dispose() }
        if ($child) { $child.Dispose() }
        if ($job) { $job.Dispose() }
        if ($proved) { Exit-WeatherHeavyWorkloadLease -Lease $lease } else { Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease }
    }
}

# ---- receipt
$runReceipt = Get-ChildItem -LiteralPath $Out -Filter 'run_receipt_*.json' -File -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1
$run = $null; if ($runReceipt) { $run = Get-Content -LiteralPath $runReceipt.FullName -Raw | ConvertFrom-Json }
$days = @(); if ($run) { $days = @($run.days | Where-Object { $_.status -eq 'extracted' }) }
$outputs = @(Get-ChildItem -LiteralPath $Out -Recurse -File | Where-Object { $_.Name -notlike 'child.*.log' -and $_.Name -ne 'wrapper_receipt.json' } |
    ForEach-Object { [ordered]@{ path = $_.FullName.Substring($Out.Length + 1); bytes = $_.Length; sha256 = Get-FileSha $_.FullName } })
$exit = if (-not $proved -or $fault) { 6 } elseif ($hardStop) { 3 } elseif ($code -eq 2) { 2 } elseif ($code -eq 0) { 0 } else { 1 }
$receipt = [ordered]@{
    receipt = 'fc11_host_wrapper_receipt'; receipt_revision = 1
    repo_head = $head; module_sha256 = $moduleSha; workload = $Workload; leased = $true; teardown_proved = $proved; fault = $fault
    started_local = $started.ToString('o'); finished_local = (Get-Date).ToString('o'); hard_kill_local = $HardKill.ToString('o')
    child_deadline_local = $ChildDeadline.ToString('o'); child_exit_code = $code; hard_stop = $hardStop; wrapper_exit_code = $exit
    snapshots_roots = $SnapshotsRoot; max_date = $MaxDate; min_date = $MinDate; out_dir = $Out
    peak_rss = [ordered]@{ tree_working_set_bytes_max = $peakTree; at = $peakAt; samples = $samples; interval_seconds = 5; per_process_peak_working_set_bytes = $perProc }
    run_receipt = if ($runReceipt) { [ordered]@{ path = $runReceipt.Name; sha256 = Get-FileSha $runReceipt.FullName } } else { $null }
    days_available = if ($run) { $run.days_available } else { $null }
    days_extracted = $days.Count
    all_match = if ($run) { [bool]$run.all_match } else { $false }
    stopped_reason = if ($run) { $run.stopped_reason } else { $null }
    manifest_rows = ($days | Measure-Object manifest_rows -Sum).Sum
    manifest_rows_extracted = ($days | Measure-Object manifest_rows_extracted -Sum).Sum
    pit_rows = ($days | Measure-Object pit_rows -Sum).Sum
    mismatched_days = @($days | Where-Object { -not $_.match } | ForEach-Object { $_.target_date })
    outputs = $outputs
    stdout_sha256 = if (Test-Path "$Out\child.stdout.log") { Get-FileSha "$Out\child.stdout.log" } else { $null }
    stderr_sha256 = if (Test-Path "$Out\child.stderr.log") { Get-FileSha "$Out\child.stderr.log" } else { $null }
}
Write-Json $receipt (Join-Path $Out 'wrapper_receipt.json')
Write-Output ("FC11 exit={0} days={1}/{2} all_match={3} pit_rows={4} peak_tree_ws={5:N1} MiB hard_stop={6} out={7}" -f `
    $exit, $receipt.days_extracted, $receipt.days_available, $receipt.all_match, $receipt.pit_rows, ($peakTree / 1MB), $hardStop, $Out)
exit $exit
