<#
EXPLORATORY_NOT_COUNTED step runner for the <= 2026-09-26 maker replay v2 shadow (EXPLORATORY-SHADOW-HOST-SPEC
section 1.1 and 2). Runs ONE step from a locked, pinned, clean worktree on the capture host:

  snapshot  -Phase pre|post  names, sizes and mtimes of data\maker_evidence\2026-09-23..26 (no content read);
                             post must equal pre (exit 7 otherwise). Light, unleased, no Python.
  verify    guard B over $Root\bundles (leased Python child).
  seal      SHA-256 manifest of every staged bundle file, then a deny-write ACE on $Root\bundles. Light.
  run       -HazardPerMinute 1.0|0.1|0.01: the guarded driver (leased Python child) into $Root\runs\h<H>.
  aggregate output manifest of $Root\runs, then the identifier-refusing aggregate (light Python child).
  unseal    removes the deny ACE.
  cleanup   unseal, then deletes $Root\bundles, $Root\runs and $Root\work only.

Every Python child: <Prod>\venv\Scripts\python.exe -P -B -m tools.research.maker_replay_v2.exploratory_le0926
with PYTHONPATH=<Wt>\src;<Wt> for the child only, cwd <Root>\work, the four BLAS pins at 1, inside a
New-ReplayExportLimitedJob (commit cap, BelowNormal). A __file__ probe first proves the modules resolve inside
<Wt>. Child budget = min(step cap, 04:45 Toronto - now); hard stop of the whole Job tree at 04:50. An unproved
teardown poisons the lease. Each step writes <Root>\receipts\<stamp>-<step>.step.json.
Nothing here is counted toward any gate. It never writes under <Prod>.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('snapshot', 'verify', 'seal', 'run', 'aggregate', 'unseal', 'cleanup')]
    [string]$Step,
    [Parameter(Mandatory = $true)][string]$Worktree,
    [Parameter(Mandatory = $true)][ValidatePattern('\A[0-9a-f]{40}\z')][string]$Pin,
    [Parameter(Mandatory = $true)][string]$ProductionRoot,
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][ValidatePattern('\A[A-Za-z0-9.-]{1,32}\z')][string]$RunId,
    [ValidateSet('1.0', '0.1', '0.01')][string]$HazardPerMinute,
    [ValidateRange(512, 65536)][int]$MinAvailableMiB,
    [ValidateSet('pre', 'post')][string]$Phase
)
$ErrorActionPreference = 'Stop'


$Days = @('2026-09-23', '2026-09-24', '2026-09-25', '2026-09-26')
$Module = 'tools.research.maker_replay_v2.exploratory_le0926'
$ProbeModules = @($Module, 'maker_core.replay.v2.pipeline', 'maker_core.replay.bundle_v02',
    'maker_core.replay.export_gate', 'weather.market.maker_replay_universe')
# step -> lease, Job commit cap (bytes), runtime cap (s), default admission MiB, disk need (bytes)
$Caps = @{
    verify    = @{ Lease = $true; Job = 1GB; Seconds = 1800; Admission = 3072; Disk = 1GB }
    run       = @{ Lease = $true; Job = 4GB; Seconds = 3600; Admission = 6144; Disk = 4GB }
    aggregate = @{ Lease = $false; Job = 512MB; Seconds = 600; Admission = 0; Disk = 0 }
}
$ExitBlocked = 10       # a precondition refused before anything ran
$Exit88aChanged = 7

function Stop-Step([string]$Message, [int]$Code = $ExitBlocked) {
    [Console]::Error.WriteLine("EXPLORATORY ABORT ($Step): $Message")
    exit $Code
}
function Get-FullPath([string]$Path) { return [IO.Path]::GetFullPath($Path).TrimEnd('\') }
function Test-PathInside([string]$Path, [string]$Base) {
    $p = Get-FullPath $Path; $b = Get-FullPath $Base
    return ($p -ieq $b -or $p.StartsWith($b + '\', [StringComparison]::OrdinalIgnoreCase))
}
function Get-Stamp { return [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ', [Globalization.CultureInfo]::InvariantCulture) }
$Zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
function Get-TorontoNow { return [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $Zone) }
function Write-StepJson([string]$Path, $Value) {
    if (Test-Path -LiteralPath $Path) { Stop-Step "refusing to overwrite $Path" }
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
}

# ---- pin, paths and placement (every step) -----------------------------------------------------------------
foreach ($p in @($Worktree, $ProductionRoot, $Root)) {
    if (-not [IO.Path]::IsPathRooted($p) -or $p -match '["\r\n]' -or (Get-FullPath $p) -cne $p.TrimEnd('\')) {
        Stop-Step "absolute normalized path required: $p"
    }
    if (-not (Test-Path -LiteralPath $p -PathType Container)) { Stop-Step "missing directory $p" }
}
if (-not (Test-PathInside $PSCommandPath $Worktree)) { Stop-Step 'this runner must be the pinned worktree copy' }
if ((Test-PathInside $Worktree $ProductionRoot) -or (Test-PathInside $ProductionRoot $Worktree)) {
    Stop-Step 'the pinned worktree and the production checkout must be disjoint'
}
foreach ($tree in @($ProductionRoot, $Worktree)) {
    if ((Test-PathInside $Root $tree) -or (Test-PathInside $tree $Root)) { Stop-Step "staging root overlaps $tree" }
}
foreach ($part in (Get-FullPath $Root).Split('\')) {
    if ($part -ieq 'data' -or $part -match '2026-(09-(2[7-9]|30)|1[0-2]-\d\d)') { Stop-Step "forbidden staging root component $part" }
}
$Receipts = Join-Path $Root 'receipts'
$Work = Join-Path $Root 'work'
$Bundles = Join-Path $Root 'bundles'
$Runs = Join-Path $Root 'runs'
foreach ($d in @($Receipts, $Work, $Runs)) {
    if (-not (Test-Path -LiteralPath $d -PathType Container)) { Stop-Step "missing staging directory $d (H0.4)" }
}
$head = ([string](& git -C $Worktree rev-parse HEAD)).Trim()
if ($LASTEXITCODE -ne 0 -or $head -cne $Pin) { Stop-Step "worktree HEAD '$head' is not the pin $Pin" }
$dirty = @(& git -C $Worktree status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0 -or $dirty.Count) { Stop-Step 'pinned worktree is not clean' }
$listing = @(& git -C $ProductionRoot worktree list --porcelain)
if ($LASTEXITCODE -ne 0) { Stop-Step 'git worktree list failed' }
$locked = $false; $current = $null
foreach ($line in $listing) {
    if ($line.StartsWith('worktree ')) { $current = Get-FullPath ($line.Substring(9) -replace '/', '\') }
    elseif ($line -cmatch '\Alocked( |\z)' -and $current -and ($current -ieq (Get-FullPath $Worktree))) { $locked = $true }
}
if (-not $locked) { Stop-Step "pinned worktree $Worktree is not a locked worktree of $ProductionRoot" }
$Py = Join-Path $ProductionRoot 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Py -PathType Leaf)) { Stop-Step "missing interpreter $Py" }

. (Join-Path $ProductionRoot 'scripts\ops\workload_admission.ps1')
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
. (Join-Path $PSScriptRoot 'replay_export_limited_job.ps1')

# ---- Python children ----------------------------------------------------------------------------------------
function Get-ChildDeadline([int]$CapSeconds) {
    # The child must END by 04:45 Toronto and starts no earlier than 00:35; the Job tree is hard-stopped at 04:50.
    $now = Get-TorontoNow
    $t = $now.TimeOfDay
    if ($t -lt [TimeSpan]'00:35:00' -or $t -ge [TimeSpan]'04:45:00') {
        Stop-Step "Toronto $($now.ToString('HH:mm')) is outside 00:35-04:45"
    }
    $end = [TimeZoneInfo]::ConvertTimeToUtc($now.Date.Add([TimeSpan]'04:45:00'), $Zone)
    $hard = [TimeZoneInfo]::ConvertTimeToUtc($now.Date.Add([TimeSpan]'04:50:00'), $Zone)
    $budget = [Math]::Min($CapSeconds, [Math]::Floor(($end - [DateTime]::UtcNow).TotalSeconds))
    if ($budget -lt $CapSeconds) { Stop-Step "a $CapSeconds s step no longer fits before 04:45 ($budget s left)" }
    return [pscustomobject]@{ Budget = $budget; HardStopUtc = $hard }
}

function Set-ChildEnvironment {
    foreach ($name in @('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')) {
        [Environment]::SetEnvironmentVariable($name, '1', 'Process')
    }
    $env:PYTHONPATH = "$(Join-Path $Worktree 'src');$Worktree"
}

function Invoke-ImportProbe([UInt64]$JobBytes) {
    $names = ($ProbeModules | ForEach-Object { "'$_'" }) -join ','
    $code = ('import importlib,os,sys;root=os.path.normcase(os.path.realpath(sys.argv[1]))+os.sep;' +
        "bad=[n for n in ($names,) if not os.path.normcase(os.path.realpath(importlib.import_module(n).__file__))" +
        '.startswith(root)];sys.exit(3 if bad else 0)')
    $probeJob = New-ReplayExportLimitedJob -JobMemoryLimitBytes $JobBytes -ProcessMemoryLimitBytes $JobBytes
    $probe = $null
    try {
        $probe = $probeJob.StartAssigned($Py, (ConvertTo-WeatherWindowsArgumentString -Tokens @('-P', '-B', '-c', $code, $Worktree)), $Work)
        if (-not $probe.WaitForExit(120000)) { throw '__file__ probe timed out' }
        $probe.WaitForExit()
        if ($probe.ExitCode -ne 0) { throw "__file__ probe failed (exit $($probe.ExitCode)): a module resolves outside $Worktree" }
    }
    finally {
        try { $probeJob.TerminateAndWait(5000) }
        finally { if ($probe) { $probe.Dispose() }; $probeJob.Dispose() }
    }
}

function Assert-LeasedAdmission([hashtable]$Cap) {
    $memoryPath = Join-Path $ProductionRoot 'data\logs\memory_commit_guard_status.json'
    $info = Get-Item -LiteralPath $memoryPath
    if ($info.Length -gt 1MB -or $info.LastWriteTimeUtc -lt [DateTime]::UtcNow.AddMinutes(-5)) {
        Stop-Step 'fresh bounded memory guard status required'
    }
    $memory = Get-Content -LiteralPath $memoryPath -Raw | ConvertFrom-Json
    if ($null -eq $memory.commit_percent -or [double]$memory.commit_percent -ge 70 -or [double]$memory.commit_percent -lt 0) {
        Stop-Step 'commit charge must be measured below 70 percent'
    }
    $free = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($Root)).AvailableFreeSpace
    if ($free -lt (50GB + $Cap.Disk)) { Stop-Step "free $free bytes < 50 GiB + $($Cap.Disk)" }
}

function Invoke-ExploratoryChild([string]$Name, [string[]]$Tokens, [string]$ResultPath) {
    $cap = $Caps[$Name]
    $deadline = Get-ChildDeadline $cap.Seconds
    $stamp = Get-Stamp
    $lease = $null
    $admission = if ($MinAvailableMiB) { $MinAvailableMiB } else { $cap.Admission }
    if ($cap.Lease) {
        if ((Get-WeatherHeavyWorkloadLeaseState -RepoRoot $ProductionRoot).Active) { Stop-Step 'lease busy; no wait, no retry' }
        $hostId = Get-WeatherExecutionHostId
        $assignment = Get-WeatherExecutionHostAssignment -RepoRoot $ProductionRoot
        if ($hostId -cne [string]$assignment.dedicated_capture_execution_host_id) { Stop-Step 'not the assigned capture host' }
        Assert-LeasedAdmission $cap
        $lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $ProductionRoot -Workload "exploratory_le0926_$Name" `
            -ExpectedExecutionHostId $hostId
        if ($null -eq $lease) { Stop-Step 'shared heavy-work lease busy' }
    }
    $job = $null; $child = $null; $code = $null; $hardStop = $false; $proved = $false; $wsStop = $false
    $available = $null; $peakWs = [UInt64]0; $peakJob = $null; $limitHit = $null; $failure = $null
    $clock = [Diagnostics.Stopwatch]::StartNew()
    try {
        try {
            Set-ChildEnvironment
            Invoke-ImportProbe $cap.Job
            $available = [Weather.Operations.ReplayExportLimitedJob]::AvailablePhysicalMiB()
            if ($admission -and $available -lt [UInt64]$admission) {
                throw "available physical memory $available MiB < $admission MiB; not waiting"
            }
            $job = New-ReplayExportLimitedJob -JobMemoryLimitBytes $cap.Job -ProcessMemoryLimitBytes $cap.Job
            $child = $job.StartAssigned($Py, (ConvertTo-WeatherWindowsArgumentString -Tokens (@('-P', '-B', '-m', $Module) + $Tokens)), $Work)
            $null = $child.Handle
            while (-not $child.HasExited) {
                if ($job.MemoryLimitHit) { break }
                $ws = [UInt64]0
                foreach ($id in $job.ProcessIds()) {
                    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
                    if ($p) { $ws += [UInt64]$p.WorkingSet64; $p.Dispose() }
                }
                if ($ws -gt $peakWs) { $peakWs = $ws }
                if ($ws -ge [UInt64]$cap.Job) { $wsStop = $true; break }
                if ($clock.Elapsed.TotalSeconds -ge $deadline.Budget -or [DateTime]::UtcNow -ge $deadline.HardStopUtc) {
                    $hardStop = $true; break
                }
                Start-Sleep -Milliseconds 250
                $child.Refresh()
            }
            if (-not ($hardStop -or $wsStop -or $job.MemoryLimitHit)) { $child.WaitForExit(); $code = [int]$child.ExitCode }
            $peakJob = $job.PeakJobMemoryUsed
            $limitHit = $job.MemoryLimitHit
        }
        catch { $failure = $_.Exception.Message }
    }
    finally {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        try {
            if ($job) { $job.TerminateAndWait(5000) }
            $proved = $true
        }
        finally {
            if ($child) { $child.Dispose() }
            if ($job) { $job.Dispose() }
            if ($lease) {
                if ($proved) { Exit-WeatherHeavyWorkloadLease -Lease $lease } else { Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease }
            }
        }
    }
    $result = $null
    if ($ResultPath -and (Test-Path -LiteralPath $ResultPath -PathType Leaf)) {
        $result = Get-Content -LiteralPath $ResultPath -Raw | ConvertFrom-Json
    }
    $record = [ordered]@{
        label = 'EXPLORATORY_NOT_COUNTED'; step = $Name; run_id = $RunId; pin = $Pin; leased = [bool]$cap.Lease
        hazard_per_minute = $HazardPerMinute; exit_code = $code; runtime_seconds = [Math]::Round($clock.Elapsed.TotalSeconds, 3)
        budget_seconds = $deadline.Budget; job_commit_cap_bytes = [UInt64]$cap.Job; available_mib_at_launch = $available
        admission_mib = $admission; peak_job_memory_bytes = $peakJob; peak_working_set_bytes = $peakWs
        memory_limit_hit = $limitHit; working_set_stop = $wsStop; hard_stop = $hardStop; teardown_proved = $proved
        failure = $failure; result_status = $(if ($result -and ($result.PSObject.Properties.Name -contains 'status')) { $result.status } else { $null })
        result_reason = $(if ($result -and ($result.PSObject.Properties.Name -contains 'reason')) { $result.reason } else { $null })
        finished_utc = [DateTime]::UtcNow.ToString('o')
    }
    Write-StepJson (Join-Path $Receipts "$stamp-$Name.step.json") $record
    if (-not $proved) { Stop-Step 'teardown unproved; lease poisoned; do not clear without the owner' 9 }
    if ($failure) { Stop-Step $failure }
    if ($hardStop -or $wsStop -or $limitHit) { Stop-Step "$Name stopped (hard stop $hardStop, working set $wsStop, commit $limitHit)" 8 }
    return $code
}

function Get-Inventory([string]$Path) {
    # name, bytes and mtime of every entry; never opens a file.
    $rows = @()
    if (Test-Path -LiteralPath $Path -PathType Container) {
        $rows = @(Get-ChildItem -LiteralPath $Path -Recurse -Force | Sort-Object FullName | ForEach-Object {
            $len = if ($_.PSIsContainer) { -1 } else { $_.Length }
            '{0}|{1}|{2}' -f $_.FullName.Substring($Path.Length), $len, $_.LastWriteTimeUtc.Ticks
        })
    }
    $text = ($rows -join "`n")
    $sha = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($text))).Replace('-', '').ToLowerInvariant()
    return [pscustomobject]@{ Exists = (Test-Path -LiteralPath $Path -PathType Container); Entries = $rows.Count; Sha256 = $sha; Rows = $rows }
}

function Get-FileManifest([string]$Dir) {
    return @(Get-ChildItem -LiteralPath $Dir -Recurse -File -Force | Sort-Object FullName | ForEach-Object {
        [ordered]@{ path = $_.FullName.Substring($Root.Length + 1); bytes = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    })
}

$me = "$env:USERDOMAIN\$env:USERNAME"
switch ($Step) {
    'snapshot' {
        if (-not $Phase) { Stop-Step '-Phase pre|post required' }
        $evidence = Join-Path $ProductionRoot 'data\maker_evidence'
        $snapshot = [ordered]@{ label = 'EXPLORATORY_NOT_COUNTED'; phase = $Phase; pin = $Pin; days = [ordered]@{} }
        $listing = [ordered]@{}
        foreach ($d in $Days) {
            $inv = Get-Inventory (Join-Path $evidence $d)
            $snapshot.days[$d] = [ordered]@{ exists = $inv.Exists; entries = $inv.Entries; sha256 = $inv.Sha256 }
            $listing[$d] = $inv.Rows
        }
        Write-StepJson (Join-Path $Receipts "EXPLORATORY-88a-meta-$Phase.json") $snapshot
        Write-StepJson (Join-Path $Receipts "EXPLORATORY-88a-listing-$Phase.json") $listing  # stays on the host
        if ($Phase -eq 'post') {
            $pre = Get-Content -LiteralPath (Join-Path $Receipts 'EXPLORATORY-88a-meta-pre.json') -Raw | ConvertFrom-Json
            foreach ($d in $Days) {
                if ([string]$pre.days.$d.sha256 -cne [string]$snapshot.days[$d].sha256) {
                    Stop-Step "88a metadata for $d changed between pre and post: STOP and escalate to the owner" $Exit88aChanged
                }
            }
        }
        Write-Output (ConvertTo-Json -Compress @{ step = 'snapshot'; phase = $Phase; status = 'OK' })
        exit 0
    }
    'verify' {
        if (-not (Test-Path -LiteralPath $Bundles -PathType Container)) { Stop-Step 'no staged bundles' }
        $result = Join-Path $Receipts 'EXPLORATORY-verify.result.json'
        $code = Invoke-ExploratoryChild 'verify' (@('verify', '--bundle-root', $Bundles, '--day') + $Days + @(
            '--out', (Join-Path $Receipts 'EXPLORATORY-verify.json'), '--result', $result,
            '--forbid-root', $ProductionRoot, '--pin', $Pin)) $result
        exit $code
    }
    'seal' {
        $manifest = Join-Path $Receipts 'EXPLORATORY-input-manifest.json'
        if (-not (Test-Path -LiteralPath $Bundles -PathType Container)) { Stop-Step 'no staged bundles' }
        Write-StepJson $manifest (Get-FileManifest $Bundles)
        & icacls $Bundles /deny "${me}:(OI)(CI)(W,D,DC)" | Out-Null
        if ($LASTEXITCODE -ne 0) { Stop-Step 'icacls deny failed' }
        Write-Output (ConvertTo-Json -Compress @{ step = 'seal'; status = 'SEALED'; manifest = $manifest })
        exit 0
    }
    'run' {
        if (-not $HazardPerMinute) { Stop-Step '-HazardPerMinute 1.0|0.1|0.01 required' }
        if (-not (Test-Path -LiteralPath (Join-Path $Receipts 'EXPLORATORY-input-manifest.json') -PathType Leaf)) {
            Stop-Step 'seal first: no input manifest'
        }
        $verify = Get-Content -LiteralPath (Join-Path $Receipts 'EXPLORATORY-verify.json') -Raw | ConvertFrom-Json
        if ([string]$verify.status -cne 'PASS') { Stop-Step 'verify did not pass' }
        $used = @($verify.days_used | ForEach-Object { [string]$_ })
        foreach ($d in $used) { if ($Days -cnotcontains $d) { Stop-Step "verify names a day outside the window: $d" } }
        $result = Join-Path $Receipts "EXPLORATORY-run-h$HazardPerMinute.result.json"
        $code = Invoke-ExploratoryChild 'run' (@('run', '--bundle-root', $Bundles, '--day') + $used + @(
            '--hazard-per-minute', $HazardPerMinute, '--verify', (Join-Path $Receipts 'EXPLORATORY-verify.json'),
            '--out', (Join-Path $Runs "h$HazardPerMinute"), '--result', $result, '--forbid-root', $ProductionRoot,
            '--pin', $Pin)) $result
        exit $code
    }
    'aggregate' {
        $outputs = Join-Path $Receipts 'EXPLORATORY-output-manifest.json'
        Write-StepJson $outputs (Get-FileManifest $Runs)
        $result = Join-Path $Receipts 'EXPLORATORY-aggregate.result.json'
        $code = Invoke-ExploratoryChild 'aggregate' @('aggregate', '--run-root', $Runs,
            '--verify', (Join-Path $Receipts 'EXPLORATORY-verify.json'),
            '--input-manifest', (Join-Path $Receipts 'EXPLORATORY-input-manifest.json'),
            '--out', (Join-Path $Receipts 'EXPLORATORY-aggregate.json'), '--result', $result,
            '--forbid-root', $ProductionRoot, '--pin', $Pin) $result
        exit $code
    }
    { $_ -in @('unseal', 'cleanup') } {
        if (Test-Path -LiteralPath $Bundles -PathType Container) {
            & icacls $Bundles /remove:d $me | Out-Null
            if ($LASTEXITCODE -ne 0) { Stop-Step 'icacls /remove:d failed' }
        }
        if ($Step -eq 'cleanup') {
            $t = (Get-TorontoNow).TimeOfDay
            if ($t -lt [TimeSpan]'00:30:00' -or $t -ge [TimeSpan]'09:00:00') { Stop-Step 'bulk deletion runs only 00:30-09:00' }
            $before = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($Root)).AvailableFreeSpace
            foreach ($d in @($Bundles, $Runs, $Work)) {
                if (-not (Test-PathInside $d $Root)) { Stop-Step "refusing to delete outside $Root" }
                if (Test-Path -LiteralPath $d) { Remove-Item -LiteralPath $d -Recurse -Force }
            }
            $freed = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($Root)).AvailableFreeSpace - $before
            Write-Output (ConvertTo-Json -Compress @{ step = 'cleanup'; status = 'DELETED'; freed_bytes = $freed })
        }
        else { Write-Output (ConvertTo-Json -Compress @{ step = 'unseal'; status = 'UNSEALED' }) }
        exit 0
    }
}
