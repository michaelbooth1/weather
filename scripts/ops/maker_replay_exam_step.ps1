<#
.SYNOPSIS
Runs ONE step of the maker replay exam from a locked, pinned worktree (W2 runbook).

.DESCRIPTION
Codifies the production runbook in docs/roadmap/agent-report-2026-10-111e-followup.md
("Production runbook", revised 2026-10-03 W2). One attended call runs one step:

  module_hash      print the exporter module-closure hash under the pin (light, unleased)
  calibration      calibration export of 09-27..29 into a fresh attempt root
  night            night export, -Kind rehearsal-panel (09-27..29) or panel (09-30..10-14)
  quote_markets    rule-derived quote-market set from the calibration bundles
  calibrate_hazard sealed hazard; refuses a global_fallback or a binding_status
  rehearse         one fresh process per calibration date
  derive_ceilings  light; exit 3 is the signed "not executable on this host" verdict
  universe         manifest universe from the fifteen sealed panel bundles
  manifest_build   on or after the Toronto scoring date
  manifest_verify  requires VERIFIED_PREFLIGHT_ONLY; records the (pin, manifest) pair
  prelook          the pre-look checks only
  look             pre-look checks, then the single look (needs a verify from this pin)

Every Python child runs with -P -B, PYTHONPATH=<worktree>\src set for the child only, after a
__file__ probe proving the exam modules resolve inside the worktree. Heavy steps hold the shared
lease from workload_admission.ps1 and run in a kill-on-close Job; the child tree is proved gone
before the lease is released, otherwise the lease is poisoned. Every --max-seconds is capped so the
step ends by 08:50 America/Toronto, and the wrapper hard-stops the tree at 08:55.

Export roots are fresh per attempt. A root may be continued only with new days, and only while every
day already in it is SEALED under the same module hash; a refused day is never retried in place.

This script reads and writes nothing under the 88a data root except through the exporter, never
edits a repository file, and imports no Python module itself. Lease and Job helpers are dot-sourced
from -RepoRoot (production master); only Python code comes from the pinned worktree.

Exit codes: 0 step passed its asserts; 3 derive_ceilings measured "not executable on this host"
(the exam ends on this host as signed); any other non-zero is a refusal or failure.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('module_hash', 'calibration', 'night', 'quote_markets', 'calibrate_hazard', 'rehearse',
        'derive_ceilings', 'universe', 'manifest_build', 'manifest_verify', 'prelook', 'look')]
    [string]$Step,
    [Parameter(Mandatory = $true)][string]$Worktree,
    [Parameter(Mandatory = $true)][ValidatePattern('\A[0-9a-f]{40}\z')][string]$Pin,
    [string]$ExamRoot = '',
    [string]$RepoRoot = "",
    [string]$DataRoot = '',
    [string]$ReleaseRoot = '',
    [ValidateSet('', 'rehearsal-panel', 'panel')][string]$Kind = '',
    [string[]]$Day = @(),
    [string]$AttemptRoot = '',
    [string]$CalibrationRoot = '',
    [string]$RehearsalRoot = '',
    [string]$PanelRoot = '',
    [ValidatePattern('\A(|[0-9a-f]{64})\z')][string]$ModuleSha256 = ''
)
# Windows PowerShell 5.1 leaves $PSScriptRoot and $PSCommandPath empty inside an
# advanced script's param() defaults under `powershell -File`; derive the default
# here. An explicit -RepoRoot always wins.
if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
}

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$CalibrationDays = @('2026-09-27', '2026-09-28', '2026-09-29')
$PanelDays = @(0..14 | ForEach-Object { ([datetime]'2026-09-30').AddDays($_).ToString('yyyy-MM-dd') })
$ScoringDate = [datetime]'2026-10-15'
$StepEnd = [TimeSpan]'08:50:00'          # every child must finish by here
$HardStopGrace = 300                     # wrapper teardown at 08:55, before the 09:00 window end
$MinimumSeconds = 60
$ExportSeconds = 11000; $ExportInputBytes = '17179869184'; $ExportOutputBytes = '2147483648'
$PackSeconds = 2700; $PackOutputBytes = '8388608'
$ExamModules = @('weather.market.maker_replay_night', 'maker_core.replay.ceilings',
    'maker_core.replay.approved_registrations', 'weather.paths')
$Zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$Utf8 = [Text.UTF8Encoding]::new($false)

function Stop-Exam([string]$Message) { throw "REFUSED: $Message" }

function Get-ExamUtcNow { return [DateTime]::UtcNow }

function Get-TorontoNow { return [TimeZoneInfo]::ConvertTimeFromUtc((Get-ExamUtcNow), $Zone) }

function Get-FullPath([string]$Path) { return [IO.Path]::GetFullPath($Path).TrimEnd('\') }

function Test-PathInside([string]$Child, [string]$Parent) {
    $c = (Get-FullPath $Child) + '\'; $p = (Get-FullPath $Parent) + '\'
    return $c.StartsWith($p, [StringComparison]::OrdinalIgnoreCase)
}

function Read-Json([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { Stop-Exam "missing $Path" }
    return ([IO.File]::ReadAllText($Path) | ConvertFrom-Json)
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-JsonProperty($Object, [string]$Name) {
    return $null -ne $Object -and @($Object.PSObject.Properties.Name) -contains $Name
}

function Write-ExamJson([string]$Path, $Value) {
    if (Test-Path -LiteralPath $Path) { Stop-Exam "refusing to overwrite $Path" }
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 8), $Utf8)
}

function Get-Stamp { return [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') }

function Require([string]$Name, [string]$Value) {
    if (-not $Value) { Stop-Exam "-$Name is required for step $Step" }
}

# ---- Session binding: repo, pinned worktree, exam root ------------------------------------------

$RepoRoot = Get-FullPath $RepoRoot
$Worktree = Get-FullPath $Worktree
$Src = Join-Path $Worktree 'src'
$Py = Join-Path $RepoRoot 'venv\Scripts\python.exe'
foreach ($helper in @('workload_admission.ps1', 'windows_kill_on_close_job.ps1')) {
    $path = Join-Path $RepoRoot "scripts\ops\$helper"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Stop-Exam "missing $path" }
    . $path
}
if (-not (Test-Path -LiteralPath $Py -PathType Leaf)) { Stop-Exam "missing interpreter $Py" }
if (-not (Test-Path -LiteralPath $Src -PathType Container)) { Stop-Exam "pinned worktree has no src: $Src" }
if (Test-PathInside $Worktree $RepoRoot) { Stop-Exam 'the pinned worktree must not be inside the production checkout' }

$head = ([string](& git -C $Worktree rev-parse HEAD)).Trim()
if ($LASTEXITCODE -ne 0 -or $head -cne $Pin) { Stop-Exam "worktree HEAD '$head' is not the pin $Pin" }
$dirty = @(& git -C $Worktree status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0 -or $dirty.Count) { Stop-Exam "pinned worktree is not clean: $($dirty -join '; ')" }
$listing = @(& git -C $RepoRoot worktree list --porcelain)
if ($LASTEXITCODE -ne 0) { Stop-Exam 'git worktree list failed' }
$locked = $false; $current = $null
foreach ($line in $listing) {
    if ($line.StartsWith('worktree ')) { $current = Get-FullPath ($line.Substring(9) -replace '/', '\') }
    elseif ($line -cmatch '\Alocked( |\z)' -and $current -and
        [string]::Equals($current, $Worktree, [StringComparison]::OrdinalIgnoreCase)) { $locked = $true }
}
if (-not $locked) { Stop-Exam "pinned worktree $Worktree is not a locked worktree of $RepoRoot" }

if ($Step -cne 'module_hash') {
    Require 'ExamRoot' $ExamRoot
    $ExamRoot = Get-FullPath $ExamRoot
    if ($DataRoot -and (Test-PathInside $ExamRoot $DataRoot)) { Stop-Exam 'the exam root must be outside the data root' }
    for ($dir = [IO.DirectoryInfo]::new($ExamRoot); $null -ne $dir; $dir = $dir.Parent) {
        if (Test-Path -LiteralPath (Join-Path $dir.FullName '.git')) { Stop-Exam "the exam root is inside a repository: $($dir.FullName)" }
    }
    if (-not (Test-Path -LiteralPath $ExamRoot -PathType Container)) { New-Item -ItemType Directory -Path $ExamRoot | Out-Null }
    $OperatorDir = Join-Path $ExamRoot 'operator'
    if (-not (Test-Path -LiteralPath $OperatorDir)) { New-Item -ItemType Directory -Path $OperatorDir | Out-Null }
}

# ---- Pinned imports and child execution ----------------------------------------------------------

function Invoke-PinnedPython([string[]]$Tokens) {
    $env:PYTHONPATH = $Src
    try { $out = @(& $Py -P -B @Tokens); $code = $LASTEXITCODE }
    finally { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    if ($code -ne 0) { Stop-Exam "pinned python exited $code" }
    return $out
}

function Assert-PinnedImports {
    $names = ($ExamModules | ForEach-Object { "'$_'" }) -join ','
    $code = "import importlib; [print(importlib.import_module(n).__file__) for n in ($names)]"
    $probe = @(Invoke-PinnedPython @('-c', $code))
    $outside = @($probe | Where-Object { -not (Test-PathInside $_ $Src) })
    if ($probe.Count -ne $ExamModules.Count -or $outside.Count) { Stop-Exam "module-path probe failed: $($probe -join '; ')" }
}

function Get-LiveModuleHash {
    Assert-PinnedImports
    $text = (Invoke-PinnedPython @('-m', 'weather.market.maker_plugin.replay_export', 'module-hash')) -join ''
    $value = [string]($text | ConvertFrom-Json).module_sha256
    if ($value -cnotmatch '\A[0-9a-f]{64}\z') { Stop-Exam "module-hash printed no hash: $text" }
    return $value
}

function Get-StepBudgetSeconds {
    $now = Get-TorontoNow
    if ($now.TimeOfDay -lt [TimeSpan]'00:30:00' -or $now.TimeOfDay -ge $StepEnd) {
        Stop-Exam "Toronto time $($now.ToString('HH:mm')) is outside 00:30-08:50"
    }
    $seconds = [int][Math]::Floor(($StepEnd - $now.TimeOfDay).TotalSeconds)
    if ($seconds -lt $MinimumSeconds) { Stop-Exam "only $seconds s remain before 08:50" }
    return $seconds
}

function Get-CappedSeconds([int]$Requested) {
    return [string][Math]::Min($Requested, (Get-StepBudgetSeconds))
}

function Invoke-ExamChild([string]$Name, [string[]]$Tokens, [switch]$NoLease) {
    $budget = Get-StepBudgetSeconds
    Assert-PinnedImports                                   # immediately before every step
    $stamp = Get-Stamp
    $log = Join-Path $OperatorDir "$stamp-$Name"
    $lease = $null
    if (-not $NoLease) {
        $lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $RepoRoot -Workload "maker_replay_exam_$Name" `
            -ExpectedExecutionHostId (Get-WeatherExecutionHostId)
        if ($null -eq $lease) { Stop-Exam 'shared heavy-work lease busy' }
    }
    $job = $null; $child = $null; $output = $null; $proved = $false; $hardStop = $false; $code = $null
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $env:PYTHONPATH = $Src
    try {
        $job = New-WeatherKillOnCloseJob
        $output = [Weather.Operations.KillOnCloseJob+CapturedOutput]::new("$log.stdout.log", "$log.stderr.log", 8388608)
        $arguments = ConvertTo-WeatherWindowsArgumentString -Tokens (@('-P', '-B') + $Tokens)
        $child = Start-WeatherProcessInJob -Job $job -FilePath $Py -ArgumentString $arguments `
            -WorkingDirectory $RepoRoot -OutputCapture $output
        $null = $child.Handle
        while (-not $child.HasExited) {
            if ($clock.Elapsed.TotalSeconds -ge ($budget + $HardStopGrace)) { $hardStop = $true; break }
            $output.Drain(); Start-Sleep -Milliseconds 100; $child.Refresh()
        }
        if (-not $hardStop) { $child.WaitForExit(); $code = [int]$child.ExitCode }
    }
    finally {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        try {
            if ($job) { $job.TerminateAndWait(5000) }
            $proved = $true
            if ($output) { $output.Complete(2000) }
        }
        finally {
            if ($output) { $output.Dispose() }
            if ($child) { $child.Dispose() }
            if ($job) { $job.Dispose() }
            if ($lease) {
                if ($proved) { Exit-WeatherHeavyWorkloadLease -Lease $lease } else { Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease }
            }
        }
    }
    $stdout = if (Test-Path -LiteralPath "$log.stdout.log") { [IO.File]::ReadAllText("$log.stdout.log") } else { '' }
    $stderr = if (Test-Path -LiteralPath "$log.stderr.log") { [IO.File]::ReadAllText("$log.stderr.log") } else { '' }
    if ($stdout) { Write-Host $stdout.TrimEnd() }
    if ($stderr) { Write-Host $stderr.TrimEnd() }
    $record = [ordered]@{
        step = $Step; name = $Name; pin = $Pin; worktree = $Worktree; tokens = $Tokens; leased = (-not $NoLease)
        exit_code = $code; hard_stop = $hardStop; teardown_proved = $proved; budget_seconds = $budget
        runtime_seconds = [Math]::Round($clock.Elapsed.TotalSeconds, 3)
        stdout_log = "$log.stdout.log"; stderr_log = "$log.stderr.log"; finished_utc = (Get-ExamUtcNow).ToString('o')
    }
    Write-ExamJson "$log.step.json" $record
    if ($hardStop) { Stop-Exam "$Name hard-stopped at the 08:55 teardown boundary" }
    return [pscustomobject]@{ Code = $code; Stdout = $stdout; Record = "$log.step.json" }
}

function Assert-ChildPassed($Result, [string]$Name) {
    if ($Result.Code -ne 0) { Stop-Exam "$Name exited $($Result.Code)" }
}

# ---- Export roots and receipts -------------------------------------------------------------------

function Assert-DaysAllowed([string[]]$Requested, [string[]]$Allowed, [string]$What) {
    if (-not $Requested.Count) { Stop-Exam "no $What days" }
    foreach ($d in $Requested) { if ($Allowed -cnotcontains $d) { Stop-Exam "$d is not a $What day" } }
    if (@($Requested | Sort-Object -Unique).Count -ne $Requested.Count) { Stop-Exam "duplicate $What day" }
}

function Assert-DayClosed([string]$Date) {
    if ((Get-ExamUtcNow) -lt ([datetime]::ParseExact($Date, 'yyyy-MM-dd', $null)).AddDays(1)) {
        Stop-Exam "UTC day $Date has not closed"
    }
}

function Assert-ReceiptSealed([string]$Root, [string]$Date, [string]$Module) {
    $x = Read-Json (Join-Path $Root "$Date\receipt.json")
    if ([string]$x.status -cne 'SEALED') { Stop-Exam "$Root $Date receipt status is $($x.status), not SEALED" }
    if ([string]$x.module_sha256 -notmatch '\A[0-9a-f]{64}\z') { Stop-Exam "$Root $Date receipt has no module_sha256" }
    if ($Module -and [string]$x.module_sha256 -cne $Module) { Stop-Exam "$Root $Date was exported under another module hash" }
    return $x
}

function Assert-SealedRoot([string]$Root, [string[]]$Days, [string]$Module) {
    if (-not $Root -or -not (Test-Path -LiteralPath $Root -PathType Container)) { Stop-Exam "export root missing: $Root" }
    if (-not (Test-PathInside $Root $ExamRoot)) { Stop-Exam "export root $Root is outside the exam root" }
    $hash = $Module; $receipts = @()
    foreach ($d in $Days) {
        $x = Assert-ReceiptSealed $Root $d $hash
        $hash = [string]$x.module_sha256; $receipts += $x
    }
    return [pscustomobject]@{ Module = $hash; Receipts = $receipts }
}

function Resolve-ExportRoot([string]$Prefix, [string[]]$Days, [string]$Module) {
    if (-not $AttemptRoot) {
        $root = Join-Path $ExamRoot ("$Prefix-" + (Get-Stamp))
        if (Test-Path -LiteralPath $root) { Stop-Exam "attempt root already exists: $root" }
        New-Item -ItemType Directory -Path $root | Out-Null
        return $root
    }
    $root = Get-FullPath $AttemptRoot
    if (-not (Test-PathInside $root $ExamRoot) -or -not (Split-Path -Leaf $root).StartsWith("$Prefix-")) {
        Stop-Exam "-AttemptRoot must be a $Prefix-* root inside the exam root"
    }
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { Stop-Exam "attempt root missing: $root" }
    foreach ($entry in @(Get-ChildItem -LiteralPath $root -Directory -Force)) {
        # Only sealed days under the same module hash may share a root; anything else needs a new root.
        if ($entry.Name -cnotmatch '\A\d{4}-\d{2}-\d{2}\z') { Stop-Exam "unexpected directory $($entry.FullName)" }
        $null = Assert-ReceiptSealed $root $entry.Name $Module
    }
    foreach ($d in $Days) {
        if (Test-Path -LiteralPath (Join-Path $root $d)) { Stop-Exam "$d was already attempted in $root; never retry in place" }
    }
    return $root
}

function Invoke-Export([string]$Command, [string]$Prefix, [string[]]$Days, [string[]]$Allowed) {
    Require 'DataRoot' $DataRoot; Require 'ModuleSha256' $ModuleSha256
    if ($Command -ceq 'night') { Require 'ReleaseRoot' $ReleaseRoot }
    Assert-DaysAllowed $Days $Allowed $Prefix
    foreach ($d in $Days) { Assert-DayClosed $d }
    $null = Get-StepBudgetSeconds                         # refuse before any child or root
    $live = Get-LiveModuleHash
    if ($live -cne $ModuleSha256) { Stop-Exam "pinned exporter hashes to $live, not -ModuleSha256 $ModuleSha256" }
    $root = Resolve-ExportRoot $Prefix $Days $ModuleSha256
    Write-Host "attempt root: $root"
    foreach ($d in $Days) {
        $tokens = @('-m', 'weather.market.maker_plugin.replay_export', $Command, '--day', $d, '--data-root', $DataRoot)
        if ($Command -ceq 'night') { $tokens += @('--release-root', $ReleaseRoot) }
        $tokens += @('--out', $root, '--expected-module-sha256', $ModuleSha256,
            '--max-input-bytes', $ExportInputBytes, '--max-seconds', (Get-CappedSeconds $ExportSeconds),
            '--max-output-bytes', $ExportOutputBytes)
        $result = Invoke-ExamChild "$($Prefix -replace '-', '_')_$d" $tokens
        $x = Assert-ReceiptSealed $root $d $ModuleSha256      # a REFUSED receipt stops the line here
        Assert-ChildPassed $result "$Prefix $d"
        if (Test-JsonProperty $x 'events_trimmed') { Write-Host "$d event lists trimmed: $($x.events_trimmed | ConvertTo-Json -Compress)" }
        $skew = if (Test-JsonProperty $x.bundle 'trade_clock_skew') { $x.bundle.trade_clock_skew } else { $null }
        Write-Host ("$d SEALED leading_capture=$(if ($skew) { $skew.leading_capture }) max_us=$(if ($skew) { $skew.max_us }) " +
            "peak=$($x.peak_memory_bytes) bytes=$($x.bundle.bytes)")
    }
    Write-Host "SEALED $($Days.Count) day(s) in $root under module $ModuleSha256"
}

# ---- Sealed inputs for the pack steps ------------------------------------------------------------

function Get-CalibrationBundleTokens {
    Require 'CalibrationRoot' $CalibrationRoot
    $sealed = Assert-SealedRoot $CalibrationRoot $CalibrationDays $ModuleSha256
    return [pscustomobject]@{
        Tokens = @($CalibrationDays | ForEach-Object { '--calibration-bundle', (Join-Path $CalibrationRoot "$_\bundle") })
        Bytes = [string](($sealed.Receipts | ForEach-Object { [long]$_.bundle.bytes } | Measure-Object -Sum).Sum)
        Records = [string](($sealed.Receipts | ForEach-Object { [long]$_.bundle.records } | Measure-Object -Sum).Sum)
    }
}

function Get-PackLimits($Calibration) {
    return @('--max-input-bytes', $Calibration.Bytes, '--max-records', $Calibration.Records,
        '--max-seconds', (Get-CappedSeconds $PackSeconds), '--max-output-bytes', $PackOutputBytes)
}

function Assert-Calibration {
    $c = Read-Json (Join-Path $ExamRoot 'calibration.json')
    if ((Test-JsonProperty $c 'global_fallback') -and $null -ne $c.global_fallback) { Stop-Exam "calibration global_fallback=$($c.global_fallback)" }
    if (Test-JsonProperty $c 'binding_status') { Stop-Exam "calibration binding_status=$($c.binding_status)" }
    return Get-Sha256 (Join-Path $ExamRoot 'calibration.json')
}

function Assert-CeilingBinding {
    $key = Assert-Calibration
    $m = Read-Json (Join-Path $ExamRoot 'ceiling-measurement.json')
    if ([string]$m.calibration_sha256 -cne $key) { Stop-Exam 'ceilings rehearsed on another calibration' }
    if (-not (Test-JsonProperty $m 'derived') -or $m.derived.executable -ne $true) {
        Stop-Exam 'ceiling measurement is not executable on this host'
    }
}

function Get-PanelBundleTokens {
    Require 'PanelRoot' $PanelRoot
    $null = Assert-SealedRoot $PanelRoot $PanelDays $ModuleSha256
    return @($PanelDays | ForEach-Object { '--bundle', (Join-Path $PanelRoot "$_\bundle") })
}

function Get-DocumentTokens {
    $tokens = @('--decision-log', (Join-Path $RepoRoot 'docs\operations\DECISION_LOG.md'))
    foreach ($pair in @(@('--frozen-protocol', 'maker-replay-hurdles-preregistration-2026-09-27.md'),
            @('--execution-addendum', 'maker-replay-execution-addendum-2026-09-27.md'),
            @('--clarification', 'maker-replay-clarification-1-2026-09-27.md'),
            @('--clarification-2', 'maker-replay-clarification-2-2026-09-29.md'),
            @('--clarification-3', 'maker-replay-clarification-3-2026-10-01.md'))) {
        $tokens += @($pair[0], (Join-Path $Worktree "docs\research\$($pair[1])"))
    }
    for ($i = 1; $i -lt $tokens.Count; $i += 2) {
        if (-not (Test-Path -LiteralPath $tokens[$i] -PathType Leaf)) { Stop-Exam "missing signed document $($tokens[$i])" }
    }
    return $tokens
}

function Get-BindingTokens {
    Assert-CeilingBinding
    $calibration = Get-CalibrationBundleTokens
    return @($calibration.Tokens + @('--calibration', (Join-Path $ExamRoot 'calibration.json'),
        '--universe', (Join-Path $ExamRoot 'universe.json'), '--quote-markets', (Join-Path $ExamRoot 'quote-markets.json'),
        '--ceiling-measurement', (Join-Path $ExamRoot 'ceiling-measurement.json')) + (Get-DocumentTokens))
}

function Assert-ScoringDate {
    if ((Get-TorontoNow).Date -lt $ScoringDate) { Stop-Exam 'manifest steps run on or after 2026-10-15 Toronto' }
}

function Assert-Absent([string]$Path) {
    if (Test-Path -LiteralPath $Path) { Stop-Exam "$Path already exists; a sealed output is never replaced" }
}

function Get-OwnerDecision {
    $path = Join-Path $ExamRoot 'owner-decision.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Stop-Exam "missing $path" }
    $bytes = [IO.File]::ReadAllBytes($path)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        Stop-Exam 'owner-decision.json must be UTF-8 without a BOM'
    }
    $decision = Read-Json $path
    if ([string]$decision.authorization_id -cnotmatch '\Amaker-replay-[0-9-]+-v[0-9]+\z') { Stop-Exam 'owner decision has no authorization_id' }
    return $decision
}

function Get-ManifestKey {
    $path = Join-Path $ExamRoot 'manifest\manifest.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Stop-Exam "missing $path" }
    return Get-Sha256 $path
}

function Invoke-PreLookChecks {
    $decision = Get-OwnerDecision
    $m = Read-Json (Join-Path $ExamRoot 'manifest\manifest.json')
    $cl = $m.ceilings
    foreach ($field in @('max_seconds', 'max_memory_bytes', 'max_output_bytes')) {
        if (-not (Test-JsonProperty $cl $field)) { Stop-Exam "manifest ceilings lack $field" }
    }
    $now = Get-TorontoNow
    $end = $now.AddSeconds([double]$cl.max_seconds)
    if ($now.TimeOfDay -lt [TimeSpan]'00:30:00' -or $end.Date -ne $now.Date -or $end.TimeOfDay -gt $StepEnd) {
        Stop-Exam "max_seconds=$($cl.max_seconds) does not fit before 08:50 (now $($now.ToString('HH:mm:ss')))"
    }
    $free = [long](Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory * 1024
    if ($free -lt [long]$cl.max_memory_bytes) { Stop-Exam "available RAM $free < memory ceiling $($cl.max_memory_bytes)" }
    $disk = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($ExamRoot)).AvailableFreeSpace
    if ($disk -lt 2 * [long]$cl.max_output_bytes) { Stop-Exam "disk free $disk < 2x report cap $($cl.max_output_bytes)" }
    $reservation = Join-Path $ExamRoot "manifest\attempts\$($decision.authorization_id).json"
    if (Test-Path -LiteralPath $reservation) { Stop-Exam "look already reserved: $reservation" }
    $margin = [int]($StepEnd - $end.TimeOfDay).TotalSeconds
    Write-Host ("PRELOOK_OK time cap $($cl.max_seconds) s (ends $($end.ToString('HH:mm:ss')), margin $margin s to 08:50); " +
        "report cap $($cl.max_output_bytes) bytes (disk $disk); memory cap $($cl.max_memory_bytes) bytes (available $free)")
    return $decision
}

function Assert-VerifiedFromThisPin([string]$Key) {
    $ok = @(Get-ChildItem -LiteralPath $OperatorDir -Filter '*-manifest_verify.verified.json' -File | Where-Object {
            $v = Read-Json $_.FullName
            $v.pin -ceq $Pin -and $v.manifest_sha256 -ceq $Key -and $v.verified -eq $true
        })
    if (-not $ok.Count) { Stop-Exam "no VERIFIED_PREFLIGHT_ONLY manifest_verify from pin $Pin for manifest $Key" }
}

# ---- Steps ---------------------------------------------------------------------------------------

switch ($Step) {
    'module_hash' {
        $value = Get-LiveModuleHash
        if ($ModuleSha256 -and $value -cne $ModuleSha256) { Stop-Exam "module hash $value != -ModuleSha256 $ModuleSha256" }
        Write-Output $value
    }
    'calibration' {
        Invoke-Export 'calibration' 'calibration' $(if ($Day.Count) { $Day } else { $CalibrationDays }) $CalibrationDays
    }
    'night' {
        Require 'Kind' $Kind
        $allowed = if ($Kind -ceq 'panel') { $PanelDays } else { $CalibrationDays }
        Invoke-Export 'night' $Kind $(if ($Day.Count) { $Day } else { $allowed }) $allowed
    }
    'quote_markets' {
        $out = Join-Path $ExamRoot 'quote-markets.json'; Assert-Absent $out
        $calibration = Get-CalibrationBundleTokens
        $result = Invoke-ExamChild 'quote_markets' (@('-m', 'maker_core.replay', 'quote_markets') + $calibration.Tokens +
            @('--out', $out) + (Get-PackLimits $calibration))
        Assert-ChildPassed $result 'quote_markets'
    }
    'calibrate_hazard' {
        $out = Join-Path $ExamRoot 'calibration.json'; Assert-Absent $out
        $markets = Join-Path $ExamRoot 'quote-markets.json'
        if (-not (Test-Path -LiteralPath $markets -PathType Leaf)) { Stop-Exam "missing $markets" }
        $calibration = Get-CalibrationBundleTokens
        $bundles = @($CalibrationDays | ForEach-Object { '--bundle', (Join-Path $CalibrationRoot "$_\bundle") })
        $result = Invoke-ExamChild 'calibrate' (@('-m', 'maker_core.replay', 'calibrate_hazard') + $bundles +
            @('--quote-markets', $markets, '--out', $out) + (Get-PackLimits $calibration))
        Assert-ChildPassed $result 'calibrate_hazard'
        $key = Assert-Calibration
        Write-Host "calibration sealed: sha256 $key, global_fallback null"
    }
    'rehearse' {
        Require 'RehearsalRoot' $RehearsalRoot
        $days = if ($Day.Count) { $Day } else { $CalibrationDays }
        Assert-DaysAllowed $days $CalibrationDays 'rehearsal'
        $null = Assert-SealedRoot $RehearsalRoot $days $ModuleSha256
        $calibrationPath = Join-Path $ExamRoot 'calibration.json'
        $null = Assert-Calibration
        foreach ($d in $days) { Assert-Absent (Join-Path $ExamRoot "rehearsal-$d.json") }
        foreach ($d in $days) {                                   # one fresh process per date
            $result = Invoke-ExamChild "rehearse_$d" @('-m', 'maker_core.replay', 'rehearse', '--bundle',
                (Join-Path $RehearsalRoot "$d\bundle"), '--calibration', $calibrationPath,
                '--out', (Join-Path $ExamRoot "rehearsal-$d.json"))
            Assert-ChildPassed $result "rehearse $d"
        }
    }
    'derive_ceilings' {
        $out = Join-Path $ExamRoot 'ceiling-measurement.json'; Assert-Absent $out
        $null = Assert-Calibration
        $tokens = @('-m', 'maker_core.replay', 'derive_ceilings')
        foreach ($d in $CalibrationDays) {
            $path = Join-Path $ExamRoot "rehearsal-$d.json"
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Stop-Exam "missing $path" }
            $tokens += @('--rehearsal', $path)
        }
        $result = Invoke-ExamChild 'derive_ceilings' ($tokens + @('--out', $out)) -NoLease
        if ($result.Code -eq 3) {
            Write-Host 'NOT_EXECUTABLE_ON_THIS_HOST: the exam ends on this host as signed; do not re-rehearse to make it fit.'
            exit 3
        }
        Assert-ChildPassed $result 'derive_ceilings'
        Assert-CeilingBinding
        Write-Host 'ceilings derived on the sealed calibration; executable on this host'
    }
    'universe' {
        $out = Join-Path $ExamRoot 'universe.json'; Assert-Absent $out
        $result = Invoke-ExamChild 'universe' (@('-m', 'weather.market.maker_plugin.replay_export', 'universe') +
            (Get-PanelBundleTokens) + @('--out', $out))
        Assert-ChildPassed $result 'universe'
    }
    'manifest_build' {
        Assert-ScoringDate
        $null = Get-OwnerDecision
        $dir = Join-Path $ExamRoot 'manifest'; $out = Join-Path $dir 'manifest.json'; Assert-Absent $out
        $tokens = @('-m', 'maker_core.replay', 'manifest', 'build') + (Get-PanelBundleTokens) + (Get-BindingTokens) +
            @('--owner-decision', (Join-Path $ExamRoot 'owner-decision.json'), '--out', $out)
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }   # canonical; never relocate
        $result = Invoke-ExamChild 'manifest_build' $tokens
        Assert-ChildPassed $result 'manifest_build'
        Write-Host "manifest sha256 $(Get-ManifestKey)"
    }
    'manifest_verify' {
        Assert-ScoringDate
        $key = Get-ManifestKey
        $tokens = @('-m', 'maker_core.replay', 'manifest', 'verify') + (Get-PanelBundleTokens) + (Get-BindingTokens) +
            @('--manifest', (Join-Path $ExamRoot 'manifest\manifest.json'), '--manifest-sha256', $key)
        $result = Invoke-ExamChild 'manifest_verify' $tokens
        Assert-ChildPassed $result 'manifest_verify'
        if ($result.Stdout -cnotmatch "manifest_sha256=$key; VERIFIED_PREFLIGHT_ONLY") { Stop-Exam 'manifest verify did not print VERIFIED_PREFLIGHT_ONLY' }
        if ((Get-ManifestKey) -cne $key) { Stop-Exam 'manifest changed during verify' }
        Write-ExamJson ($result.Record -replace '\.step\.json\z', '.verified.json') ([ordered]@{
                pin = $Pin; manifest_sha256 = $key; verified = $true; step_record = $result.Record })
        Write-Host "VERIFIED_PREFLIGHT_ONLY from pin $Pin"
    }
    'prelook' {
        $key = Get-ManifestKey
        Assert-VerifiedFromThisPin $key
        $null = Invoke-PreLookChecks
    }
    'look' {
        $key = Get-ManifestKey
        Assert-VerifiedFromThisPin $key
        $tokens = @('-m', 'maker_core.replay', 'run', '--compare', '--pre-registration', (Join-Path $ExamRoot 'manifest\manifest.json'),
            '--pre-registration-sha256', $key)
        $lookOut = Join-Path $ExamRoot ('look-' + (Get-Stamp)); Assert-Absent $lookOut
        $tokens += @('--out', $lookOut) + (Get-PanelBundleTokens) + (Get-BindingTokens)
        $decision = Invoke-PreLookChecks                        # the same session, immediately before the look
        $result = Invoke-ExamChild 'look' $tokens
        $attempts = Join-Path $ExamRoot 'manifest\attempts'
        $id = [string]$decision.authorization_id
        $reserved = Test-Path -LiteralPath (Join-Path $attempts "$id.json")
        $completed = Test-Path -LiteralPath (Join-Path $attempts "$id.completed.json")
        $refusals = @(if (Test-Path -LiteralPath $attempts) { Get-ChildItem -LiteralPath $attempts -Filter '*.refusal-*.json' -File })
        $outcome = if ($completed) { 'COMPLETED' } elseif ($reserved) { 'CONSUMED_STOPPED: do not retry' }
        elseif ($refusals.Count) { 'REFUSED_NOT_CONSUMED: fix the operational cause; a new look gets a new --out' } else { 'NO_RESERVATION' }
        Write-Host "look out $lookOut; exit $($result.Code); outcome $outcome; refusal records $($refusals.Count)"
        Assert-ChildPassed $result 'look'
    }
}
