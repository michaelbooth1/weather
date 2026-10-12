<#
.SYNOPSIS
Runs the clean-room oracle author's quick unit tests from the H1 cut folder under the shared lease.

.DESCRIPTION
Owner ruling I-6 (2026-10-12): the oracle author account runs only quick unit tests, inside the cut
folder, during 00:30-09:00, through a wrapper that the operator (master) runs and that holds the
shared workload lease. The author account cannot take the lease itself. Heavier tests run after
hand-back. This is that wrapper. It is attended and is not a scheduled task.

One call is one pytest run:

  gate         refuses the 12:00-18:00 graded and 18:00-00:30 near-close protected windows and any
               time outside 00:30-09:00 (Toronto); the child must end by 08:55, so the hard timeout
               is min(-TimeoutMinutes, time left to 08:55) and under 60 s left is a refusal.
  admission    >= 50 GiB free on the volume of -LogDir (it holds --basetemp), and the memory guard's
               commit_percent < 70 from a status no older than 5 minutes.
  containment  every -TestPath resolves inside <CutDir>\<RepoSubdir>; '..', drive or UNC paths,
               and absolute paths elsewhere are refused. The cut may hold no reparse point (a
               junction would let a lexically contained path reach another tree).
  interpreter  -PythonPath is a dedicated venv (or base install) outside the cut, outside this
               checkout and outside every -ForbiddenRoot. It runs as `python -I -S -B -X utf8 -c
               <bootstrap>`: -I ignores every PYTHON* variable, the user site and the script
               directory; -S skips site, so no .pth file runs (the production venv carries an
               editable .pth that adds the production src to sys.path, which is why it is refused).
               The bootstrap appends exactly two kinds of entries to the stdlib path: the venv's
               site-packages and the cut repository (plus its src when present). A probe child
               proves the flags, the prefix, every sys.path entry and where pytest and the
               repository's top-level packages resolve before pytest starts; it imports no cut code.
  pytest       -p no:cacheprovider, --rootdir/--confcutdir at the cut repository, an explicit fresh
               --basetemp outside the cut, PYTEST_DISABLE_PLUGIN_AUTOLOAD=1, PYTEST_ADDOPTS and
               PYTEST_PLUGINS removed. Options are typed parameters, never free-form pytest flags.
  environment  the child sees an allowlisted environment only: system variables, a minimal PATH, and
               TEMP/TMP/HOME/USERPROFILE inside the run's scratch folder. Operator variables (tokens,
               GIT_*, WEATHER_*, PYTHON*) are not inherited. The parent's environment is restored as
               soon as the child is created.
  containment  every Python child runs in a kill-on-close Job; the tree is proved gone before the
               lease is released, otherwise the lease is poisoned (retained until this process exits).
  integrity    the cut is fingerprinted (path, length, SHA-256 of every file) before and after the
               run. Any change, including a new reparse point, makes the run CUT_MODIFIED (exit 65)
               and the operator must inspect the cut before the author resumes.
  receipt      <LogDir>\<stamp>-<pid>.receipt.json: start/end, lease workload id, exit codes, cut
               manifest binding SHA-256 (H1-manifest.json when present), test arguments, durations,
               fingerprints, interpreter probe, free bytes and log hashes. The scratch folder is
               deleted afterwards, pass or fail, and the receipt records whether that succeeded.

TRADE-OFF (for the owner and master): pytest runs as the OPERATOR account. The author's test code
therefore executes with operator file rights and network access: it could read the production clone
and leak it through stdout, through a file it writes inside the cut (detected here as CUT_MODIFIED),
through a location the author account can read (not detected), or over the network. Relay output to
the author only after review, and treat this design as safe only for non-adversarial test code. The
stronger alternative runs the child as the author account (whose ACL denies every production tree):
it needs the author's credential at run time or a stored-credential task, both of which the
isolation runbook's I-2 and section 2.6 currently forbid, so it is documented, not implemented.

Exit codes: pytest's own code (0 passed, 1 failed, 2 interrupted, 3 internal, 4 usage, 5 no tests)
when the run completed and the cut is unchanged; 64 refused before pytest started; 65 cut modified;
75 the shared lease is busy; 124 hard timeout (child tree killed); 70 any other wrapper failure.

Example (operator account, 00:30-09:00 Toronto; under -File join several paths with ';'):
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\oracle_author_test_run.ps1 `
    -CutDir <CUT_DIR> -PythonPath <ORACLE_VENV>\Scripts\python.exe -LogDir <LOG_DIR> `
    -TestPath "tests/test_a.py;tests/test_b.py::test_one" -ExpectedManifestSha256 <MANIFEST_SHA256> `
    -ForbiddenRoot "<WORKTREES>;<LDATA>;<SOURCES>"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$CutDir,
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$LogDir,
    [Parameter(Mandatory = $true)][string[]]$TestPath,
    [ValidatePattern('\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\z')][string]$RepoSubdir = 'oracle-repo',
    [ValidateRange(1, 30)][int]$TimeoutMinutes = 15,
    [ValidatePattern('\A(|[0-9a-f]{64})\z')][string]$ExpectedManifestSha256 = '',
    [string[]]$ForbiddenRoot = @(),
    [string]$Keyword = '',
    [string]$Marker = '',
    [switch]$FailFast,
    [ValidateSet('quiet', 'normal', 'verbose')][string]$Verbosity = 'quiet',
    [ValidateSet('short', 'long', 'line', 'native', 'no')][string]$Traceback = 'short',
    [ValidateRange(0, 50)][int]$Durations = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# The production checkout that owns this wrapper; never a parameter (lease file and memory guard
# status live under it, and it is always a forbidden import root).
$RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))

$WindowStartMinute = 30                  # 00:30
$WindowEndMinute = 540                   # 09:00
$GradedStartMinute = 720                 # 12:00
$NearCloseStartMinute = 1080             # 18:00; protected through 00:30
$ChildEnd = [TimeSpan]'08:55:00'         # teardown before the 09:00 window end
$MinimumBudgetSeconds = 60
$TimeoutUnitSeconds = 60
$MinFreeBytes = 53687091200              # 50 GiB, HOST_LOAD_POLICY rule 2
$MaxCommitPercent = 70
$MaxMemoryStatusAgeMinutes = 5
$MaxTestPaths = 25
$MaxCutEntries = 200000
$MaxCutBytes = 4294967296                # 4 GiB bounded fingerprint
$MaxChangeRows = 50
$ProbeSeconds = 60
$OutputCapBytes = 8388608
$ManifestName = 'H1-manifest.json'
$GuardedPackages = @('weather', 'maker_core', 'app', 'sitecustomize', 'usercustomize')
$Zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$Utf8 = [Text.UTF8Encoding]::new($false)
$ExitRefused = 64; $ExitCutModified = 65; $ExitWrapperError = 70; $ExitLeaseBusy = 75; $ExitTimeout = 124

# Read only by the probe and the bootstrap, never by pytest; single quotes only (one argv token).
$SysPathVariable = 'ORACLE_AUTHOR_TEST_SYSPATH'
$Bootstrap = "import os,sys;sys.path.extend(p for p in os.environ['$SysPathVariable'].split(';') if p);" +
    'import pytest;raise SystemExit(pytest.main(sys.argv[1:]))'
$Probe = "import os,sys,json,importlib.util as u;sys.path.extend(p for p in os.environ['$SysPathVariable'].split(';') if p);" +
    "o=lambda n:(lambda s:None if s is None else (s.origin or ';'.join(s.submodule_search_locations or [])))(u.find_spec(n));" +
    "print(json.dumps(dict(version=sys.version.split()[0],prefix=sys.prefix,base_prefix=sys.base_prefix,path=sys.path," +
    "isolated=sys.flags.isolated,no_site=sys.flags.no_site,safe_path=bool(getattr(sys.flags,'safe_path',0))," +
    "dont_write_bytecode=bool(sys.dont_write_bytecode),pytest=o('pytest')," +
    "guarded={n:o(n) for n in sys.argv[1:]})))"
$ChildEnvironmentKeep = @('SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'COMSPEC', 'PATHEXT', 'OS',
    'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'PROCESSOR_IDENTIFIER', 'PROCESSOR_LEVEL',
    'PROCESSOR_REVISION')

$script:Receipt = [ordered]@{
    schema_version = 'oracle_author_test_receipt_v1'
    status = 'STARTED'
    reason = $null
    run_as = 'operator'
    principal = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    host = [Environment]::MachineName
    wrapper_pid = $PID
    repo_root = $RepoRoot
    started_utc = $null
    started_toronto = $null
    ended_utc = $null
    window = $null
    timeout_seconds = $null
    cut_dir = $null
    repo_dir = $null
    cut_manifest = $null
    test_paths = @()
    pytest_arguments = @()
    interpreter = $null
    lease = $null
    free_bytes_before = $null
    free_bytes_after = $null
    cut_fingerprint_before = $null
    cut_fingerprint_after = $null
    cut_changes = $null
    probe = $null
    pytest = $null
    exit_code = $null
    scratch = $null
    scratch_deleted = $null
    durations_seconds = [ordered]@{}
}
$script:ReceiptPath = $null
$script:TeardownFailed = $false

function Stop-Refused([string]$Message) { throw "REFUSED: $Message" }

function Get-OracleTestUtcNow { return [DateTime]::UtcNow }

function Get-TorontoNow { return [TimeZoneInfo]::ConvertTimeFromUtc((Get-OracleTestUtcNow), $Zone) }

function Get-FullPath([string]$Path) { return [IO.Path]::GetFullPath($Path).TrimEnd('\') }

function Test-PathInside([string]$Child, [string]$Parent) {
    $c = (Get-FullPath $Child) + '\'; $p = (Get-FullPath $Parent) + '\'
    return $c.StartsWith($p, [StringComparison]::OrdinalIgnoreCase)
}

function Test-PathOverlap([string]$A, [string]$B) { return (Test-PathInside $A $B) -or (Test-PathInside $B $A) }

function Get-Sha256Hex([byte[]]$Bytes) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($Bytes)) -replace '-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Get-FileSha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Split-ListParameter([string[]]$Values) {
    # Under `powershell -File` an array parameter arrives as one string; ';' separates items.
    return @($Values | ForEach-Object { ([string]$_) -split ';' } | ForEach-Object { $_.Trim() } |
        Where-Object { $_ })
}

function Get-StepSeconds([Diagnostics.Stopwatch]$Clock) { return [Math]::Round($Clock.Elapsed.TotalSeconds, 3) }

# ---- Gate ----------------------------------------------------------------------------------------

function Get-OracleTestWindow([datetime]$Toronto) {
    $minute = [int][Math]::Floor($Toronto.TimeOfDay.TotalMinutes)
    if ($minute -ge $GradedStartMinute -and $minute -lt $NearCloseStartMinute) { return 'protected_graded_1200_1800' }
    if ($minute -ge $NearCloseStartMinute -or $minute -lt $WindowStartMinute) { return 'protected_near_close_1800_0030' }
    if ($minute -ge $WindowStartMinute -and $minute -lt $WindowEndMinute) { return 'admitted_0030_0900' }
    return 'outside_0030_0900'
}

function Get-RunBudgetSeconds {
    $now = Get-TorontoNow
    $window = Get-OracleTestWindow $now
    $script:Receipt.window = $window
    if ($window -cne 'admitted_0030_0900') {
        Stop-Refused "Toronto time $($now.ToString('HH:mm')) is in $window; author tests run only 00:30-09:00"
    }
    $left = [int][Math]::Floor(($ChildEnd - $now.TimeOfDay).TotalSeconds)
    if ($left -lt $MinimumBudgetSeconds) { Stop-Refused "only $left s remain before the 08:55 teardown" }
    return [Math]::Min($TimeoutMinutes * $TimeoutUnitSeconds, $left)
}

# ---- Paths and inputs ----------------------------------------------------------------------------

function Resolve-ExistingDirectory([string]$Path, [string]$What) {
    if (-not $Path -or -not [IO.Path]::IsPathRooted($Path) -or $Path.StartsWith('\\')) {
        Stop-Refused "$What must be an absolute local path"
    }
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if ($null -eq $item -or -not $item.PSIsContainer) { Stop-Refused "$What is not a directory: $Path" }
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { Stop-Refused "$What is a reparse point: $Path" }
    $full = Get-FullPath $item.FullName
    if ($full.Length -le 3) { Stop-Refused "$What may not be a volume root: $full" }
    return $full
}

function Resolve-TestPathItem([string]$Item, [string]$RepoDir) {
    if ($Item.Length -gt 600 -or $Item -match '[\x00-\x1f"*?<>|]') { Stop-Refused "test path has forbidden characters: $Item" }
    $pathPart = $Item; $node = ''
    $split = $Item.IndexOf('::')
    if ($split -ge 0) { $pathPart = $Item.Substring(0, $split); $node = $Item.Substring($split) }
    if ($node -and $node -cnotmatch '\A(::[A-Za-z_][A-Za-z0-9_]*)+(\[[^\x00-\x1f\]]{0,200}\])?\z') {
        Stop-Refused "test node id is not a plain pytest node id: $Item"
    }
    if ($pathPart.StartsWith('\\') -or $pathPart.StartsWith('//')) { Stop-Refused "UNC test path refused: $Item" }
    if (@($pathPart -split '[\\/]') -contains '..') { Stop-Refused "test path may not contain '..': $Item" }
    if ([IO.Path]::IsPathRooted($pathPart) -or $pathPart -match '\A[A-Za-z]:') {
        $full = Get-FullPath $pathPart
        if (-not (Test-PathInside $full $RepoDir) -or $full.Length -le $RepoDir.Length) {
            Stop-Refused "absolute test path is outside the cut repository: $Item"
        }
        $pathPart = $full.Substring($RepoDir.Length + 1)
    }
    $segments = @($pathPart -split '[\\/]' | Where-Object { $_ -ne '' })
    if (-not $segments.Count) { Stop-Refused "empty test path: $Item" }
    foreach ($segment in $segments) {
        if ($segment -cnotmatch '\A[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\z') { Stop-Refused "test path segment '$segment' is not allowed: $Item" }
    }
    $relative = $segments -join '\'
    $full = Get-FullPath (Join-Path $RepoDir $relative)
    if (-not (Test-PathInside $full $RepoDir) -or $full.Length -le $RepoDir.Length) {
        Stop-Refused "test path resolves outside the cut repository: $Item"
    }
    if (-not (Test-Path -LiteralPath $full)) { Stop-Refused "test path does not exist in the cut: $Item" }
    return (($segments -join '/') + $node)
}

function Assert-Expression([string]$Value, [string]$What) {
    if ($Value -and $Value -cnotmatch '\A[A-Za-z0-9_ ().,:=\[\]-]{1,256}\z') { Stop-Refused "$What expression has forbidden characters" }
}

function Resolve-Interpreter([string]$Path, [string]$CutDirFull, [string[]]$Forbidden) {
    if (-not $Path -or -not [IO.Path]::IsPathRooted($Path) -or $Path.StartsWith('\\')) { Stop-Refused '-PythonPath must be an absolute local path' }
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if ($null -eq $item -or $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        $item.Name -cnotmatch '\Apython(?:3(?:\.\d+)?)?\.exe\z') {
        Stop-Refused "-PythonPath is not a regular python.exe: $Path"
    }
    $full = Get-FullPath $item.FullName
    if (Test-PathInside $full $CutDirFull) { Stop-Refused 'the interpreter may not live inside the cut' }
    foreach ($root in $Forbidden) {
        if (Test-PathInside $full $root) { Stop-Refused "the interpreter is inside a forbidden root ($root); use a dedicated venv" }
    }
    $directory = Split-Path -Parent $full
    $parent = Split-Path -Parent $directory
    $prefix = if (Test-Path -LiteralPath (Join-Path $parent 'pyvenv.cfg') -PathType Leaf) { $parent } else { $directory }
    $site = Join-Path $prefix 'Lib\site-packages'
    if (-not (Test-Path -LiteralPath $site -PathType Container)) { Stop-Refused "interpreter has no site-packages: $site" }
    foreach ($root in $Forbidden) {
        if (Test-PathOverlap $prefix $root) { Stop-Refused "the interpreter prefix overlaps a forbidden root ($root)" }
    }
    return [pscustomobject]@{ Path = $full; Directory = $directory; Prefix = (Get-FullPath $prefix); SitePackages = (Get-FullPath $site) }
}

# ---- Cut fingerprint -----------------------------------------------------------------------------

function Get-CutFingerprint([string]$Root) {
    $entries = [Collections.Generic.SortedDictionary[string, string]]::new([StringComparer]::OrdinalIgnoreCase)
    $reparse = [Collections.Generic.List[string]]::new()
    $stack = [Collections.Generic.Stack[string]]::new()
    $stack.Push($Root)
    $bytes = [long]0; $files = 0
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        while ($stack.Count -gt 0) {
            $directory = $stack.Pop()
            foreach ($path in [IO.Directory]::EnumerateFileSystemEntries($directory)) {
                $relative = $path.Substring($Root.Length).TrimStart('\')
                if ($entries.Count + $reparse.Count -ge $MaxCutEntries) { Stop-Refused "the cut holds more than $MaxCutEntries entries" }
                $attributes = [IO.File]::GetAttributes($path)
                if ($attributes -band [IO.FileAttributes]::ReparsePoint) { $reparse.Add($relative); continue }
                if ($attributes -band [IO.FileAttributes]::Directory) { $entries[$relative + '\'] = 'dir'; $stack.Push($path); continue }
                $share = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
                $stream = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, $share)
                try { $hash = $sha.ComputeHash($stream); $length = $stream.Length }
                finally { $stream.Dispose() }
                $bytes += $length; $files++
                if ($bytes -gt $MaxCutBytes) { Stop-Refused "the cut exceeds $MaxCutBytes bytes" }
                $entries[$relative] = '{0}:{1}' -f $length, (([BitConverter]::ToString($hash) -replace '-', '').ToLowerInvariant())
            }
        }
    }
    finally { $sha.Dispose() }
    $lines = foreach ($pair in $entries.GetEnumerator()) { '{0}{1}{2}' -f $pair.Key, "`t", $pair.Value }
    return [pscustomobject]@{
        Entries = $entries
        Reparse = @($reparse)
        Files = $files
        Bytes = $bytes
        Sha256 = Get-Sha256Hex ($Utf8.GetBytes((@($lines) -join "`n")))
    }
}

function Compare-CutFingerprint($Before, $After) {
    $added = @(); $removed = @(); $changed = @()
    foreach ($key in $After.Entries.Keys) {
        if (-not $Before.Entries.ContainsKey($key)) { $added += $key }
        elseif ($Before.Entries[$key] -cne $After.Entries[$key]) { $changed += $key }
    }
    foreach ($key in $Before.Entries.Keys) { if (-not $After.Entries.ContainsKey($key)) { $removed += $key } }
    $total = $added.Count + $removed.Count + $changed.Count + $After.Reparse.Count
    return [ordered]@{
        changed_entries = $total
        added = @($added | Select-Object -First $MaxChangeRows)
        removed = @($removed | Select-Object -First $MaxChangeRows)
        modified = @($changed | Select-Object -First $MaxChangeRows)
        reparse_points = @($After.Reparse | Select-Object -First $MaxChangeRows)
    }
}

function Get-FingerprintSummary($Fingerprint) {
    return [ordered]@{ sha256 = $Fingerprint.Sha256; files = $Fingerprint.Files; bytes = $Fingerprint.Bytes; reparse_points = @($Fingerprint.Reparse) }
}

# ---- Admission -----------------------------------------------------------------------------------

function Get-VolumeFreeBytes([string]$Path) {
    return [long]([IO.DriveInfo]::new([IO.Path]::GetPathRoot($Path))).AvailableFreeSpace
}

function Assert-MemoryHeadroom {
    $path = Join-Path $RepoRoot 'data\logs\memory_commit_guard_status.json'
    try { $read = Read-WeatherMemoryGuardStatus -Path $path }
    catch { Stop-Refused "memory guard status is unreadable: $path" }
    $row = $read.row
    $percent = if ($row.PSObject.Properties.Name -contains 'commit_percent') { $row.commit_percent } else { $null }
    if (((Get-Date) - $read.last_write_time).TotalMinutes -gt $MaxMemoryStatusAgeMinutes -or
        $null -eq $percent -or [double]$percent -ge $MaxCommitPercent) {
        Stop-Refused "memory evidence blocks admission (commit_percent=$percent, max $MaxCommitPercent, status age limit $MaxMemoryStatusAgeMinutes min)"
    }
    return [double]$percent
}

# ---- Child environment and execution -------------------------------------------------------------

function Get-ProcessEnvironmentSnapshot {
    $saved = @{}
    foreach ($entry in [Environment]::GetEnvironmentVariables('Process').GetEnumerator()) { $saved[[string]$entry.Key] = [string]$entry.Value }
    return $saved
}

# CreateProcess receives a null environment block, so the child inherits this process's variables:
# narrow them to the allowlist for the instant of creation; the caller restores them in finally.
function Enter-ChildEnvironment([hashtable]$Saved, [hashtable]$Values) {
    foreach ($name in @($Saved.Keys)) {
        if ($ChildEnvironmentKeep -notcontains $name.ToUpperInvariant()) { [Environment]::SetEnvironmentVariable($name, $null, 'Process') }
    }
    foreach ($name in $Values.Keys) { [Environment]::SetEnvironmentVariable($name, [string]$Values[$name], 'Process') }
}

function Restore-ParentEnvironment([hashtable]$Saved) {
    foreach ($name in @([Environment]::GetEnvironmentVariables('Process').Keys)) {
        if (-not $Saved.ContainsKey([string]$name)) { [Environment]::SetEnvironmentVariable([string]$name, $null, 'Process') }
    }
    foreach ($name in $Saved.Keys) { [Environment]::SetEnvironmentVariable($name, $Saved[$name], 'Process') }
}

function Invoke-ContainedPython([string]$Name, [string[]]$Tokens, [int]$BudgetSeconds, [string]$WorkingDirectory, [hashtable]$Environment) {
    $stdout = "$($script:RunBase).$Name.stdout.log"; $stderr = "$($script:RunBase).$Name.stderr.log"
    $job = $null; $child = $null; $capture = $null; $hardStop = $false; $code = $null
    $clock = [Diagnostics.Stopwatch]::StartNew()
    try {
        $job = New-WeatherKillOnCloseJob
        $capture = [Weather.Operations.KillOnCloseJob+CapturedOutput]::new($stdout, $stderr, $OutputCapBytes)
        $arguments = ConvertTo-WeatherWindowsArgumentString -Tokens $Tokens
        $saved = Get-ProcessEnvironmentSnapshot
        try {
            Enter-ChildEnvironment $saved $Environment
            $child = Start-WeatherProcessInJob -Job $job -FilePath $script:Interpreter.Path -ArgumentString $arguments `
                -WorkingDirectory $WorkingDirectory -OutputCapture $capture
        }
        finally { Restore-ParentEnvironment $saved }
        $null = $child.Handle
        while (-not $child.HasExited) {
            if ($clock.Elapsed.TotalSeconds -ge $BudgetSeconds) { $hardStop = $true; break }
            $capture.Drain(); Start-Sleep -Milliseconds 100; $child.Refresh()
        }
        if (-not $hardStop) { $child.WaitForExit(); $code = [int]$child.ExitCode }
    }
    finally {
        try {
            if ($job) {
                try { $job.TerminateAndWait(5000) }
                catch { $script:TeardownFailed = $true; throw }
            }
            if ($capture) { $capture.Complete(2000) }
        }
        finally {
            if ($capture) { $capture.Dispose() }
            if ($child) { $child.Dispose() }
            if ($job) { $job.Dispose() }
        }
    }
    return [pscustomobject]@{
        ExitCode = $code; HardStop = $hardStop; Seconds = (Get-StepSeconds $clock); BudgetSeconds = $BudgetSeconds
        Stdout = $stdout; Stderr = $stderr
    }
}

function Get-LogRecord($Result) {
    return [ordered]@{
        exit_code = $Result.ExitCode; hard_stop = $Result.HardStop; seconds = $Result.Seconds; budget_seconds = $Result.BudgetSeconds
        stdout_log = $Result.Stdout; stdout_sha256 = $(if (Test-Path -LiteralPath $Result.Stdout) { Get-FileSha256 $Result.Stdout } else { $null })
        stderr_log = $Result.Stderr; stderr_sha256 = $(if (Test-Path -LiteralPath $Result.Stderr) { Get-FileSha256 $Result.Stderr } else { $null })
    }
}

function Assert-ProbeResult($Result, [string]$RepoDir, [string[]]$Forbidden) {
    if ($Result.HardStop -or $Result.ExitCode -ne 0) { Stop-Refused "interpreter probe failed (exit $($Result.ExitCode), hard stop $($Result.HardStop))" }
    try { $probe = [IO.File]::ReadAllText($Result.Stdout).Trim() | ConvertFrom-Json }
    catch { Stop-Refused 'interpreter probe printed no JSON' }
    $script:Receipt.probe = $probe
    # -I also implies -P (safe_path) on 3.11+; on older versions -I alone keeps the cwd off sys.path,
    # and every relative sys.path entry is refused below either way.
    if ([int]$probe.isolated -ne 1 -or [int]$probe.no_site -ne 1 -or -not $probe.dont_write_bytecode) {
        Stop-Refused 'interpreter probe did not run isolated (-I), without site (-S) and without bytecode (-B)'
    }
    # Without site (-S) a venv's sys.prefix stays at the base install; it must be that or the venv.
    $prefix = Get-FullPath ([string]$probe.prefix)
    $basePrefix = Get-FullPath ([string]$probe.base_prefix)
    if (-not ([string]::Equals($prefix, $basePrefix, [StringComparison]::OrdinalIgnoreCase) -or
            [string]::Equals($prefix, $script:Interpreter.Prefix, [StringComparison]::OrdinalIgnoreCase))) {
        Stop-Refused "interpreter prefix $prefix is neither its base install nor $($script:Interpreter.Prefix)"
    }
    foreach ($root in $Forbidden) {
        if (Test-PathOverlap $basePrefix $root) { Stop-Refused "interpreter base prefix overlaps a forbidden root ($root)" }
    }
    foreach ($entry in @($probe.path)) {
        $text = [string]$entry
        if (-not $text -or -not [IO.Path]::IsPathRooted($text)) { Stop-Refused "relative sys.path entry '$text'" }
        $inside = (Test-PathInside $text $RepoDir) -or (Test-PathInside $text $script:Interpreter.Prefix) -or (Test-PathInside $text $basePrefix)
        if (-not $inside) { Stop-Refused "sys.path entry outside the cut and the interpreter: $text" }
        foreach ($root in $Forbidden) { if (Test-PathInside $text $root) { Stop-Refused "sys.path entry inside a forbidden root: $text" } }
    }
    if (-not $probe.pytest -or -not (Test-PathInside ([string]$probe.pytest) $script:Interpreter.SitePackages)) {
        Stop-Refused "pytest does not resolve from the interpreter's site-packages ($($probe.pytest))"
    }
    foreach ($name in $GuardedPackages) {
        $origin = [string]$probe.guarded.$name
        if (-not $origin) { continue }
        foreach ($location in ($origin -split ';')) {
            if ($location -and -not (Test-PathInside $location $RepoDir)) { Stop-Refused "'$name' resolves outside the cut: $location" }
        }
    }
}

# ---- Receipt -------------------------------------------------------------------------------------

function Write-Receipt {
    if (-not $script:ReceiptPath) { return }
    $script:Receipt.ended_utc = (Get-OracleTestUtcNow).ToString('o')
    $temporary = "$($script:ReceiptPath).partial"
    [IO.File]::WriteAllText($temporary, ($script:Receipt | ConvertTo-Json -Depth 8), $Utf8)
    [IO.File]::Move($temporary, $script:ReceiptPath)
    Write-Host "receipt: $($script:ReceiptPath)"
}

# ---- Main ----------------------------------------------------------------------------------------

$exitCode = $ExitWrapperError
$lease = $null
$total = [Diagnostics.Stopwatch]::StartNew()
try {
    $script:Receipt.started_utc = (Get-OracleTestUtcNow).ToString('o')
    $script:Receipt.started_toronto = (Get-TorontoNow).ToString('yyyy-MM-ddTHH:mm:ss')
    foreach ($helper in @('workload_admission.ps1', 'windows_kill_on_close_job.ps1', 'memory_guard_status_reader.ps1')) {
        $path = Join-Path $PSScriptRoot $helper
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "missing helper $path" }
        . $path
    }

    # Log directory first, so every later refusal leaves a receipt.
    if (-not $LogDir -or -not [IO.Path]::IsPathRooted($LogDir) -or $LogDir.StartsWith('\\')) { Stop-Refused '-LogDir must be an absolute local path' }
    $logFull = Get-FullPath $LogDir
    if (Test-PathOverlap $logFull $RepoRoot) { Stop-Refused '-LogDir may not overlap the production checkout' }
    if ($CutDir -and [IO.Path]::IsPathRooted($CutDir) -and (Test-PathOverlap $logFull (Get-FullPath $CutDir))) {
        Stop-Refused '-LogDir may not overlap the cut'
    }
    if (-not (Test-Path -LiteralPath $logFull -PathType Container)) { New-Item -ItemType Directory -Path $logFull | Out-Null }
    $logFull = Resolve-ExistingDirectory $logFull '-LogDir'
    $stamp = (Get-OracleTestUtcNow).ToString('yyyyMMddTHHmmssfffZ')
    $script:RunBase = Join-Path $logFull "$stamp-$PID"
    $script:ReceiptPath = "$($script:RunBase).receipt.json"
    if (Test-Path -LiteralPath $script:ReceiptPath) { throw "receipt already exists: $($script:ReceiptPath)" }

    $budget = Get-RunBudgetSeconds

    $cutFull = Resolve-ExistingDirectory $CutDir '-CutDir'
    $forbidden = @(@($RepoRoot) + @(Split-ListParameter $ForbiddenRoot) | ForEach-Object {
        if (-not [IO.Path]::IsPathRooted($_)) { Stop-Refused "-ForbiddenRoot must be absolute: $_" }
        Get-FullPath $_
    })
    foreach ($root in $forbidden) {
        if (Test-PathOverlap $cutFull $root) { Stop-Refused "the cut overlaps a forbidden root ($root)" }
    }
    $repoDir = Resolve-ExistingDirectory (Join-Path $cutFull $RepoSubdir) 'cut repository'
    $script:Receipt.cut_dir = $cutFull
    $script:Receipt.repo_dir = $repoDir

    $manifestPath = Join-Path $cutFull $ManifestName
    $manifestSha = if (Test-Path -LiteralPath $manifestPath -PathType Leaf) { Get-FileSha256 $manifestPath } else { $null }
    $script:Receipt.cut_manifest = [ordered]@{ path = $manifestPath; present = ($null -ne $manifestSha); sha256 = $manifestSha }
    if ($ExpectedManifestSha256 -and $manifestSha -cne $ExpectedManifestSha256) {
        Stop-Refused "cut manifest SHA-256 '$manifestSha' is not the expected binding $ExpectedManifestSha256"
    }

    $items = @(Split-ListParameter $TestPath)
    if ($items.Count -lt 1 -or $items.Count -gt $MaxTestPaths) { Stop-Refused "between 1 and $MaxTestPaths test paths are required" }
    $tests = @($items | ForEach-Object { Resolve-TestPathItem $_ $repoDir })
    $script:Receipt.test_paths = $tests
    Assert-Expression $Keyword '-Keyword'
    Assert-Expression $Marker '-Marker'

    $script:Interpreter = Resolve-Interpreter $PythonPath $cutFull $forbidden
    $script:Receipt.interpreter = [ordered]@{ path = $script:Interpreter.Path; prefix = $script:Interpreter.Prefix; site_packages = $script:Interpreter.SitePackages }

    $script:Receipt.free_bytes_before = Get-VolumeFreeBytes $logFull
    if ($script:Receipt.free_bytes_before -lt $MinFreeBytes) {
        Stop-Refused "only $($script:Receipt.free_bytes_before) bytes free on the -LogDir volume; $MinFreeBytes required"
    }
    $commitPercent = Assert-MemoryHeadroom

    $clock = [Diagnostics.Stopwatch]::StartNew()
    $before = Get-CutFingerprint $cutFull
    $script:Receipt.durations_seconds.fingerprint_before = Get-StepSeconds $clock
    $script:Receipt.cut_fingerprint_before = Get-FingerprintSummary $before
    if ($before.Reparse.Count) { Stop-Refused "the cut holds reparse points: $(@($before.Reparse | Select-Object -First 5) -join ', ')" }

    $workload = "oracle_author_tests_$stamp"
    $lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $RepoRoot -Workload $workload
    if ($null -eq $lease) {
        $script:Receipt.status = 'LEASE_BUSY'; $script:Receipt.reason = 'the shared heavy-workload lease is held by another workload'
        $exitCode = $ExitLeaseBusy
    }
    else {
        $script:Receipt.lease = [ordered]@{ workload = $workload; acquired_utc = (Get-OracleTestUtcNow).ToString('o'); lock_path = $lease.Path; commit_percent = $commitPercent }
        $scratch = "$($script:RunBase).scratch"
        $script:Receipt.scratch = $scratch
        try {
            if (Test-Path -LiteralPath $scratch) { throw "scratch already exists: $scratch" }
            $baseTemp = Join-Path $scratch 'basetemp'
            foreach ($directory in @('tmp', 'home')) { New-Item -ItemType Directory -Path (Join-Path $scratch $directory) | Out-Null }
            $sysPath = @($script:Interpreter.SitePackages, $repoDir)
            if (Test-Path -LiteralPath (Join-Path $repoDir 'src') -PathType Container) { $sysPath += (Join-Path $repoDir 'src') }
            $childEnvironment = @{
                PATH = "$($script:Interpreter.Directory);$env:SystemRoot\System32;$env:SystemRoot"
                TEMP = (Join-Path $scratch 'tmp'); TMP = (Join-Path $scratch 'tmp')
                HOME = (Join-Path $scratch 'home'); USERPROFILE = (Join-Path $scratch 'home')
                PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
            }
            $childEnvironment[$SysPathVariable] = $sysPath -join ';'

            $probeTokens = @('-I', '-S', '-B', '-X', 'utf8', '-c', $Probe) + $GuardedPackages
            $probeResult = Invoke-ContainedPython 'probe' $probeTokens $ProbeSeconds $scratch $childEnvironment
            $script:Receipt.durations_seconds.probe = $probeResult.Seconds
            Assert-ProbeResult $probeResult $repoDir $forbidden

            $budget = Get-RunBudgetSeconds          # re-gate immediately before pytest
            $script:Receipt.timeout_seconds = $budget
            $pytestArguments = @('-p', 'no:cacheprovider', "--rootdir=$repoDir", "--confcutdir=$repoDir", "--basetemp=$baseTemp",
                "--tb=$Traceback")
            switch ($Verbosity) { 'quiet' { $pytestArguments += '-q' } 'verbose' { $pytestArguments += '-v' } }
            if ($FailFast) { $pytestArguments += '-x' }
            if ($Keyword) { $pytestArguments += @('-k', $Keyword) }
            if ($Marker) { $pytestArguments += @('-m', $Marker) }
            if ($Durations) { $pytestArguments += "--durations=$Durations" }
            $pytestArguments += $tests
            $script:Receipt.pytest_arguments = $pytestArguments
            $run = Invoke-ContainedPython 'pytest' (@('-I', '-S', '-B', '-X', 'utf8', '-c', $Bootstrap) + $pytestArguments) `
                $budget $repoDir $childEnvironment
            $script:Receipt.pytest = Get-LogRecord $run
            $script:Receipt.durations_seconds.pytest = $run.Seconds

            $clock = [Diagnostics.Stopwatch]::StartNew()
            $after = Get-CutFingerprint $cutFull
            $script:Receipt.durations_seconds.fingerprint_after = Get-StepSeconds $clock
            $script:Receipt.cut_fingerprint_after = Get-FingerprintSummary $after
            $changes = Compare-CutFingerprint $before $after
            $script:Receipt.cut_changes = $changes

            if ($run.HardStop) {
                $script:Receipt.status = 'TIMED_OUT'; $script:Receipt.reason = "pytest exceeded $budget s; the Job tree was killed"
                $exitCode = $ExitTimeout
            }
            elseif ($changes.changed_entries -gt 0) {
                $script:Receipt.status = 'CUT_MODIFIED'
                $script:Receipt.reason = "the run changed $($changes.changed_entries) cut entries; inspect the cut before the author resumes"
                $exitCode = $ExitCutModified
            }
            else {
                $script:Receipt.status = if ($run.ExitCode -eq 0) { 'PASSED' } else { 'FAILED' }
                $exitCode = [int]$run.ExitCode
            }
            if ($run.HardStop -and $changes.changed_entries -gt 0) {
                $script:Receipt.reason += "; the cut also changed ($($changes.changed_entries) entries)"
            }
        }
        finally {
            if ($script:TeardownFailed) {
                Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease
                $script:Receipt.lease.released = $false
            }
            else {
                Exit-WeatherHeavyWorkloadLease -Lease $lease
                $script:Receipt.lease.released = $true
                $script:Receipt.lease.released_utc = (Get-OracleTestUtcNow).ToString('o')
            }
            if (Test-Path -LiteralPath $scratch) {
                try { Remove-Item -LiteralPath $scratch -Recurse -Force } catch { Write-Warning "scratch cleanup failed: $($_.Exception.Message)" }
            }
            $script:Receipt.scratch_deleted = -not (Test-Path -LiteralPath $scratch)
            $script:Receipt.free_bytes_after = Get-VolumeFreeBytes $logFull
        }
    }
}
catch {
    $message = $_.Exception.Message
    if ($message.StartsWith('REFUSED: ')) {
        if ($script:Receipt.status -ceq 'STARTED') { $script:Receipt.status = 'REFUSED' }
        $script:Receipt.reason = $message.Substring(9)
        $exitCode = $ExitRefused
    }
    else {
        $script:Receipt.status = 'ERROR'
        $script:Receipt.reason = $message
        $exitCode = $ExitWrapperError
    }
    [Console]::Error.WriteLine($message)
}
finally {
    $script:Receipt.exit_code = $exitCode
    $script:Receipt.durations_seconds.total = Get-StepSeconds $total
    try { Write-Receipt } catch { [Console]::Error.WriteLine("receipt write failed: $($_.Exception.Message)"); $exitCode = $ExitWrapperError }
}
Write-Host "status: $($script:Receipt.status) exit: $exitCode"
exit $exitCode
