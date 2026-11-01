# Commit-charge watchdog for the dedicated weather-capture host.
#
# 2026-07-12 incident: an ad-hoc `python -` analysis job grew to 36 GB of
# private commit on a 15.7 GB RAM / 48 GB pagefile host. Commit charge hit
# 99.4% (63.3/63.7 GB), the pagefile thrashed the data disk at 100%, and the
# snapshot + CLOB capture loops stalled for ~75 minutes before the process was
# killed manually. Scheduled `-m weather.*` pipelines are already governed by
# working-set caps and the capture-resource admission gate; ad-hoc interpreter
# jobs are the ungoverned class this guard covers.
#
# Policy:
#   physical RAM available < 1.5 GiB -> log a WARNING with the top
#                     working-set processes. This is observability only;
#                     termination decisions remain commit-based.
#   commit >= 85%  -> log a WARNING with the top private-memory processes.
#   commit >= 92%  -> kill the single largest ungoverned offender above
#                     8 GB private bytes. This includes ad-hoc Python and an
#                     agent-owned process tree (codex.exe, chatgpt.exe or
#                     claude.exe root). Production `-m weather.*` workers are
#                     excluded by ancestry and command identity.
#   every run      -> outside 00:30-09:00, terminate agent-owned (codex.exe,
#                     chatgpt.exe or claude.exe root) pytest, compileall,
#                     inline/stdin/script Python (option flags such as -I or
#                     -X before the script included), the explicit heavy
#                     `-m` module list owned by workload_admission.ps1, and
#                     recursive scans of a repository data directory by an
#                     rg/grep/find/robocopy process image. Every child is
#                     judged by its OWN command line: a PowerShell tool shell
#                     can hide its script text, so the shell line is not
#                     trusted. Bash/sh tool shells are recognized like
#                     PowerShell/cmd. Inside that window, retain at most one
#                     such tool tree. Work admitted under a live heavy-workload
#                     lease (the lease owner recorded by workload_admission.ps1,
#                     matched by PID and creation time, is the row, an
#                     ancestor, or inside the row's subtree) is never a window
#                     or concurrency target, and a tool tree containing a live
#                     lease owner is never terminated as a whole: only heavy
#                     member subtrees that do not contain the owner are.
#   every run      -> orphan sweep: kill `python -` / `python -c` processes
#                     whose parent is gone and which are older than 30 min.
#                     A stdin/-c job's script and output have no owner once
#                     the parent dies; the 2026-07-12 incident's second
#                     process idled at only 1.3 GB (below every memory
#                     threshold) while reading 113 GB from the data disk.
#                     Orphaned bare-script python is logged but not killed
#                     (detached-by-design launchers exist in this repo).
#
# Registered by register_memory_commit_guard.ps1 (every minute).

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$ExpectedExecutionHostId = "",
    [double]$WarnPercent = 85.0,
    [double]$ActPercent = 92.0,
    [long]$MinKillPrivateBytes = 8GB,
    [double]$OrphanGraceMinutes = 30.0,
    [long]$WarnFreePhysicalBytes = 1536MB,
    [ValidateRange(0.0, 3600.0)]
    [double]$AgentWorkloadGraceSeconds = 15.0,
    [ValidateRange(0, 64)]
    [int]$MaxConcurrentAgentHeavyWorkloads = 1,
    # Host-global heavy-workload state written by workload_admission.ps1 for the
    # portable and workstation-offline profiles. Read only; never created here.
    [string]$HeavyWorkloadStateRoot = (Join-Path `
        ([Environment]::GetFolderPath([Environment+SpecialFolder]::CommonApplicationData)) `
        "WeatherProject")
)

function Get-MemoryGuardExecutionHostId {
    $machineGuid = [string](Get-ItemPropertyValue `
        -LiteralPath "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography" `
        -Name "MachineGuid" `
        -ErrorAction Stop)
    $machineGuid = $machineGuid.Trim().ToLowerInvariant()
    if (-not $machineGuid) {
        throw "memory guard execution-host identity is unavailable"
    }
    $material = "international_live_execution_host_v2`0$machineGuid"
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        return -join ($hasher.ComputeHash(
            [Text.Encoding]::UTF8.GetBytes($material)
        ) | ForEach-Object { $_.ToString("x2") })
    }
    finally { $hasher.Dispose() }
}

# Existing production registrations predate the immutable host binding and
# retain their protection until the separately authorized registrar is rerun.
# Every new registration supplies the exact validated capture-host ID.
if ($ExpectedExecutionHostId) {
    if ($ExpectedExecutionHostId -cnotmatch '\A[0-9a-f]{64}\z') {
        throw "memory guard expected execution-host identity is invalid"
    }
    $guardExecutionHostId = Get-MemoryGuardExecutionHostId
    if ($guardExecutionHostId -cne $ExpectedExecutionHostId) {
        Write-Output (
            "SKIPPED: memory commit guard is restricted to its registered " +
            "dedicated capture host"
        )
        exit 0
    }
}

$logDir = Join-Path $RepoRoot "data\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
$logPath = Join-Path $logDir "memory_commit_guard.log"
$statusPath = Join-Path $logDir "memory_commit_guard_status.json"
$historyPath = Join-Path $logDir "memory_commit_guard_history.jsonl"

function Write-GuardLog([string]$Level, [string]$Message) {
    $line = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $Level, $Message
    Add-Content -Path $logPath -Value $line -Encoding utf8
}

$agentRootNames = @("codex.exe", "chatgpt.exe", "claude.exe")
# Claude Code's Bash tool runs claude.exe -> bash.exe (Git Bash, nested) -> child;
# its PowerShell tool runs claude.exe -> cmd.exe -> powershell.exe whose script
# text arrives through an environment variable, not the command line.
$agentShellNames = @("powershell.exe", "pwsh.exe", "cmd.exe", "bash.exe", "sh.exe")
$terminationPerformed = $false
$guardActions = New-Object System.Collections.Generic.List[string]

function Get-AgentHeavyModuleNames([string]$AdmissionScriptPath) {
    # The exact heavy-module list is owned by Get-WeatherWorkstationOfflineModule in
    # workload_admission.ps1. Read it by parsing (never executing) that file so the
    # guard cannot drift from the wrapper's list. On any failure the guard keeps only
    # the pytest/compileall set. The guard is a fresh process every minute, so there
    # is no cross-run cache; one AST parse of that file costs milliseconds.
    $names = New-Object System.Collections.Generic.List[string]
    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        $AdmissionScriptPath, [ref]$tokens, [ref]$parseErrors)
    if (@($parseErrors).Count -ne 0) { throw "workload admission script does not parse" }
    $function = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq 'Get-WeatherWorkstationOfflineModule'
    }, $true))
    if ($function.Count -ne 1) { throw "offline module list function not found exactly once" }
    foreach ($constant in @($function[0].Body.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.StringConstantExpressionAst]
    }, $true))) {
        $value = [string]$constant.Value
        if ($value -cmatch '\A[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+\z') {
            $names.Add($value.ToLowerInvariant())
        }
    }
    if ($names.Count -eq 0) { throw "offline module list is empty" }
    return $names.ToArray()
}

function Test-GovernedWeatherProcess($ProcessRow) {
    $name = ([string]$ProcessRow.Name).ToLowerInvariant()
    $cmd = [string]$ProcessRow.CommandLine
    return ($name -match '^pythonw?\.exe$') -and ($cmd -match '(?i)(?:^|\s)-m\s+weather\.')
}

function Test-AgentHeavyProcess($ProcessRow) {
    # Nested helpers live inside this function so that a caller extracting only
    # this definition (the DST audit harness) still gets them.
    function Get-AgentCommandWords([string]$CommandLine) {
        return @([regex]::Matches($CommandLine, '(?:"[^"]*"|''[^'']*''|[^\s"'']+)+') |
            ForEach-Object { ($_.Value -replace '"', '') -replace "'", '' })
    }

    function Get-AgentPythonInvocation([string]$CommandLine) {
        # Interpreter options may precede -m/-c/the script (python -I x.py,
        # python -X utf8 x.py, python -Bu -m pytest). Returns Kind module (with
        # the module's own arguments in Rest), inline, stdin, or script; $null for
        # a bare interpreter (an interactive REPL or a long-lived server reading
        # stdin is not a batch job), --version, -h and anything unparsed.
        $words = @(Get-AgentCommandWords $CommandLine)
        $flags = '[bBdEiIOPqRsSuvx]*'
        for ($index = 1; $index -lt $words.Count; $index++) {
            $word = [string]$words[$index]
            if ($word -ceq '-') { return @{ Kind = 'stdin'; Target = ''; Rest = @() } }
            if ($word -ceq '--') {
                if ($index + 1 -lt $words.Count) { return @{ Kind = 'script'; Target = [string]$words[$index + 1]; Rest = @() } }
                return @{ Kind = 'stdin'; Target = ''; Rest = @() }
            }
            $moduleMatch = [regex]::Match($word, ('\A-' + $flags + 'm(?<module>.*)\z'))
            if ($moduleMatch.Success) {
                $module = $moduleMatch.Groups['module'].Value
                if (-not $module) {
                    $index++
                    if ($index -ge $words.Count) { return $null }
                    $module = [string]$words[$index]
                }
                $rest = @()
                if ($index + 1 -lt $words.Count) { $rest = @($words[($index + 1)..($words.Count - 1)]) }
                return @{ Kind = 'module'; Target = $module.ToLowerInvariant(); Rest = $rest }
            }
            if ($word -cmatch ('\A-' + $flags + 'c')) { return @{ Kind = 'inline'; Target = ''; Rest = @() } }
            $valueMatch = [regex]::Match($word, ('\A-' + $flags + '[WX](?<value>.*)\z'))
            if ($valueMatch.Success) {
                if (-not $valueMatch.Groups['value'].Value) { $index++ }
                continue
            }
            if ($word -ceq '--check-hash-based-pycs') { $index++; continue }
            if ($word -cmatch '\A--check-hash-based-pycs=') { continue }
            if ($word -cmatch ('\A-' + $flags + '\z')) { continue }
            if ($word.StartsWith('-')) { return $null }
            return @{ Kind = 'script'; Target = $word; Rest = @() }
        }
        return $null
    }

    function Test-AgentHeavyModule([string]$Module, $Rest) {
        if ($Module -cin @('pytest', 'compileall', 'coverage', 'tox', 'nox')) { return $true }
        # Only the explicit list owned by Get-WeatherWorkstationOfflineModule in
        # workload_admission.ps1 (read at script scope); no name pattern, which
        # caught operator readers (daily_refresh status, *_status, *_report) and
        # retention deletes mid-run. A status/help invocation of a listed module
        # is a reader, not a job.
        if ($null -eq $agentHeavyModuleNames -or -not ($agentHeavyModuleNames -ccontains $Module)) { return $false }
        $first = if (@($Rest).Count -gt 0) { [string]@($Rest)[0] } else { '' }
        return -not ($first -cin @('status', '--help', '-h', '--version'))
    }

    function Test-AgentRepoDataPath([string]$PathText) {
        # True for a directory path inside a repository data directory: relative
        # paths whose first segment is data (agents run from a checkout root), or
        # absolute paths with a data segment whose parent holds .git. A path whose
        # leaf has an extension is a single file, not a recursive scan.
        $path = $PathText.Trim().Replace('/', '\')
        if (-not $path) { return $false }
        if ($path -match '\A\\([A-Za-z])(?:\\|\z)') { $path = $Matches[1] + ':' + $path.Substring(2) }
        $path = $path -replace '\A(?:\.\\)+', ''
        $segments = @($path.Split('\') | Where-Object { $_ -ne '' })
        if ($segments.Count -eq 0) { return $false }
        if ([string]$segments[$segments.Count - 1] -match '\.[A-Za-z0-9]{1,10}\z') { return $false }
        if ($path -notmatch '\A(?:[A-Za-z]:\\|\\\\)') { return ([string]$segments[0] -ieq 'data') }
        for ($index = 1; $index -lt $segments.Count; $index++) {
            if ([string]$segments[$index] -ine 'data') { continue }
            $parent = ($segments[0..($index - 1)] -join '\')
            if ($path.StartsWith('\\')) { $parent = '\\' + $parent }
            if ($parent -match '\A[A-Za-z]:\z') { $parent += '\' }
            try { if (Test-Path -LiteralPath (Join-Path $parent '.git')) { return $true } } catch { }
        }
        return $false
    }

    $name = ([string]$ProcessRow.Name).ToLowerInvariant()
    $cmd = [string]$ProcessRow.CommandLine
    if ([string]::IsNullOrWhiteSpace($cmd)) { return $false }

    if ($name -match '^pythonw?\.exe$') {
        # Classify by the interpreter's own arguments. Agent-rooted `-m weather.*`
        # is no longer exempt as a class: modules on the explicit heavy list count;
        # other weather CLIs (recovery checks, supervisors, status readers) do not.
        $invocation = Get-AgentPythonInvocation $cmd
        if ($null -ne $invocation) {
            if ($invocation.Kind -ceq 'module') {
                return (Test-AgentHeavyModule ([string]$invocation.Target) $invocation.Rest)
            }
            if ($invocation.Kind -cin @('inline', 'stdin')) { return $true }
            if ($invocation.Kind -ceq 'script') { return ([string]$invocation.Target -match '(?i)\.pyw?\z') }
        }
        if (Test-GovernedWeatherProcess $ProcessRow) { return $false }
        return ($cmd -match '(?i)(?:^|\s)-m\s+(?:pytest|compileall|coverage|tox|nox)(?:\s|$)') -or
            ($cmd -match '(?i)pythonw?(?:\.exe)?"?\s+-\s*$') -or
            ($cmd -match '(?i)pythonw?(?:\.exe)?"?\s+-c\s') -or
            ($cmd -match '(?i)pythonw?(?:\.exe)?"?\s+[^-]\S*\.py(?:\s|$)')
    }

    # Recursive scanners, only as the process image and only by their own path
    # arguments: the pattern, option values (--exclude-dir=data) and a commit
    # message mentioning a scanner never count.
    if ($name -eq 'rg.exe' -or $name -eq 'grep.exe') {
        $words = @(Get-AgentCommandWords $cmd)
        $positional = New-Object System.Collections.Generic.List[string]
        $patternGiven = $false
        $recursive = ($name -eq 'rg.exe')
        $valueOptions = if ($name -eq 'rg.exe') { @('-e', '-f', '-g', '-t', '-T', '-A', '-B', '-C', '-m', '-j', '-M', '-r', '-E', '-d') } else { @('-e', '-f', '-A', '-B', '-C', '-m', '-d', '-D') }
        for ($index = 1; $index -lt $words.Count; $index++) {
            $word = [string]$words[$index]
            if ($word -ceq '--') {
                for ($rest = $index + 1; $rest -lt $words.Count; $rest++) { $positional.Add([string]$words[$rest]) }
                break
            }
            if ($word.StartsWith('--')) {
                if ($word -cmatch '\A--(?:regexp|file)(?:=|\z)' -or $word -ceq '--files') { $patternGiven = $true }
                if ($word -cmatch '\A--(?:dereference-)?recursive\z') { $recursive = $true }
                continue
            }
            if ($word.StartsWith('-') -and $word.Length -gt 1) {
                if ($word -cmatch '\A-[A-Za-z]*[ef]') { $patternGiven = $true }
                if ($name -eq 'grep.exe' -and $word -cmatch '\A-[A-Za-z]*[rR]') { $recursive = $true }
                if ($valueOptions -ccontains $word) { $index++ }
                continue
            }
            $positional.Add($word)
        }
        if (-not $recursive) { return $false }
        $paths = @($positional | Select-Object -Skip ([int](-not $patternGiven)))
        return @($paths | Where-Object { Test-AgentRepoDataPath $_ }).Count -gt 0
    }
    if ($name -eq 'find.exe') {
        # Windows find.exe (System32) searches named files for a string; it never
        # recurses. Only GNU find (Git usr\bin) walks a tree.
        $words = @(Get-AgentCommandWords $cmd)
        $image = if ($ProcessRow.PSObject.Properties.Name -contains 'ExecutablePath') { [string]$ProcessRow.ExecutablePath } else { '' }
        if ($image -match '(?i)\\windows\\' -or ($words.Count -gt 0 -and [string]$words[0] -match '(?i)\\windows\\')) { return $false }
        if (@($words | Where-Object { $_ -match '(?i)\A/(?:v|c|n|i|off(?:line)?)\z' }).Count -gt 0) { return $false }
        $paths = New-Object System.Collections.Generic.List[string]
        $index = 1
        for (; $index -lt $words.Count; $index++) {
            $word = [string]$words[$index]
            if ($word.StartsWith('-') -or $word -in @('(', '!', ',', '\(', '\!')) { break }
            $paths.Add($word)
        }
        for (; $index -lt $words.Count - 1; $index++) {
            if ([string]$words[$index] -ceq '-maxdepth' -and [string]$words[$index + 1] -in @('0', '1')) { return $false }
        }
        return @($paths | Where-Object { Test-AgentRepoDataPath $_ }).Count -gt 0
    }
    if ($name -eq 'robocopy.exe') { return ($cmd -match '(?i)(?:^|\s)/(?:s|e|mir)(?:\s|$)') }

    if ($name -eq 'powershell.exe' -or $name -eq 'pwsh.exe') {
        # A recursive listing runs inside the shell itself, so its own line is the
        # only evidence. Child processes (python, rg, find) are judged above, never
        # through a shell line, which may only quote them (git commit -m '...').
        return (($cmd -match '(?i)Get-ChildItem') -and ($cmd -match '(?i)-Recurse'))
    }

    return ($name -eq 'pytest.exe')
}

function Get-AdmittedLeaseOwners([string]$LeaseRepoRoot, [string]$StateRoot) {
    # Owners of heavy-workload leases taken through workload_admission.ps1
    # (workstation_heavy.ps1, the bounded suite, training_window, one-off lease
    # wrappers). Each owner is a PID plus its creation instant; only a live
    # process whose PID AND creation instant both match counts, so a stale record
    # (owner exited, PID reused) admits nothing. Files are opened read-only with
    # full sharing: the guard never probes for write access, so it cannot race a
    # lease acquisition.
    #
    # A lease file that exists but cannot be read or parsed (mid-write, unknown
    # schema, damaged) is reported in Unreadable; the caller then skips window and
    # concurrency kills for the tick rather than misjudge a leased job.
    #
    # Known limitation: release disposes the repo lock handle but leaves its record
    # on disk (there is no released/status field), so until the former owner
    # process exits its subtree still reads as admitted. Telling a held lock from a
    # released one would need an exclusive open that can block a real acquisition,
    # so the guard does not probe. The host-global state file is deleted on
    # release and does not have this gap.
    $owners = New-Object System.Collections.Generic.List[object]
    $unreadable = New-Object System.Collections.Generic.List[string]
    $candidates = New-Object System.Collections.Generic.List[object]
    foreach ($slot in 1..8) {
        $lockName = if ($slot -eq 1) { "heavy_workload.lock" } else { "heavy_workload.slot{0}.lock" -f $slot }
        $candidates.Add(@{ Kind = 'repo_lock'; Path = (Join-Path $LeaseRepoRoot ("data\logs\" + $lockName)) })
        if ($StateRoot) {
            $stateName = if ($slot -eq 1) { "heavy_workload_v1.poison" } else { "heavy_workload_v1.slot{0}.poison" -f $slot }
            $candidates.Add(@{ Kind = 'host_state'; Path = (Join-Path $StateRoot $stateName) })
        }
    }
    foreach ($candidate in $candidates) {
        try {
            if (-not (Test-Path -LiteralPath $candidate.Path -PathType Leaf)) { continue }
        }
        catch { $unreadable.Add([string]$candidate.Path); continue }
        try {
            $stream = [System.IO.File]::Open(
                $candidate.Path,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                ([System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete))
            try {
                $reader = New-Object System.IO.StreamReader($stream, (New-Object System.Text.UTF8Encoding($false)))
                $text = $reader.ReadToEnd()
            }
            finally { $stream.Dispose() }
            $text = $text.TrimStart([char]0xFEFF)
            if (-not $text.TrimStart().StartsWith('{')) { throw "not a JSON object" }
            $record = $text | ConvertFrom-Json
            $ownerPid = [uint32]$record.pid
            if ($ownerPid -eq 0) { throw "no owner pid" }
            if ($candidate.Kind -eq 'repo_lock') {
                if ([string]$record.schema_version -cne 'weather_heavy_workload_lease_v3') { throw "unknown lease schema" }
                $tokenMatch = [regex]::Match([string]$record.owner_process_creation_time_token, '\Awin32-filetime:(\d+)\z')
                if (-not $tokenMatch.Success) { throw "no owner creation token" }
                $born = [datetime]::FromFileTimeUtc([long]$tokenMatch.Groups[1].Value)
            }
            else {
                if ([string]$record.schema_version -cne 'weather_heavy_workload_state_v1') { throw "unknown state schema" }
                $born = [datetime]::Parse(
                    [string]$record.owner_process_start_utc,
                    [Globalization.CultureInfo]::InvariantCulture,
                    [Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()
                # TEARDOWN_PENDING (or any non-ACTIVE state) is a readable record that admits nothing.
                if ([string]$record.state -cne 'ACTIVE') { continue }
            }
            $owners.Add([pscustomobject]@{ Pid = $ownerPid; CreationUtc = $born; Source = $candidate.Kind })
        }
        catch { $unreadable.Add([string]$candidate.Path) }
    }
    return [pscustomobject]@{ Owners = $owners.ToArray(); Unreadable = $unreadable.ToArray() }
}

function Test-AgentLeaseOwnerRow($ProcessRow, $LeaseOwners) {
    $rowId = [uint32]$ProcessRow.ProcessId
    $born = ([datetime]$ProcessRow.CreationDate).ToUniversalTime()
    foreach ($owner in @($LeaseOwners)) {
        if ([uint32]$owner.Pid -ne $rowId) { continue }
        # CIM CreationDate carries microseconds and the lease token 100 ns ticks of
        # the same kernel instant; one second absorbs rounding, never PID reuse
        # (a live owner's PID cannot be reused).
        if ([math]::Abs(($born - [datetime]$owner.CreationUtc).TotalSeconds) -le 1.0) { return $true }
    }
    return $false
}

function Test-AgentTreeHasLeaseOwner($RootRow, $AllProcesses, $LeaseOwners) {
    if (@($LeaseOwners).Count -eq 0) { return $false }
    foreach ($member in @(Get-ProcessTreeRows $RootRow $AllProcesses)) {
        if (Test-AgentLeaseOwnerRow $member $LeaseOwners) { return $true }
    }
    return $false
}

function Test-AgentLeaseAdmitted($ProcessRow, $ProcessByPid, $AllProcesses, $LeaseOwners) {
    # Admitted when the row or one of its verified ancestors (below the agent root)
    # owns a live lease, or when the row's own subtree contains a lease owner,
    # whatever the row's name: a shell, `python tools\x.py`, py.exe or a git hook
    # that launched the leased wrapper must not be judged as unleased between the
    # wrapper's children (between bounded-suite chunks). Unleased heavy siblings
    # elsewhere in the tree are still judged one by one.
    if (@($LeaseOwners).Count -eq 0) { return $false }
    $current = $ProcessRow
    for ($depth = 0; $depth -lt 32 -and $null -ne $current; $depth++) {
        if ($agentRootNames -contains ([string]$current.Name).ToLowerInvariant()) { break }
        if (Test-AgentLeaseOwnerRow $current $LeaseOwners) { return $true }
        $parentId = [uint32]$current.ParentProcessId
        if (-not $ProcessByPid.ContainsKey($parentId)) { break }
        $parent = $ProcessByPid[$parentId]
        if (([datetime]$parent.CreationDate).ToUniversalTime() -gt ([datetime]$current.CreationDate).ToUniversalTime()) { break }
        $current = $parent
    }
    return (Test-AgentTreeHasLeaseOwner $ProcessRow $AllProcesses $LeaseOwners)
}

function Get-AgentToolRoot($ProcessRow, $ProcessByPid) {
    $path = New-Object System.Collections.Generic.List[object]
    $current = $ProcessRow
    for ($depth = 0; $depth -lt 32 -and $null -ne $current; $depth++) {
        $path.Add($current)
        $name = ([string]$current.Name).ToLowerInvariant()
        if ($agentRootNames -contains $name) {
            if ($path.Count -lt 2) { return $null }
            return $path[$path.Count - 2]
        }
        $parentId = [uint32]$current.ParentProcessId
        if (-not $ProcessByPid.ContainsKey($parentId)) { return $null }
        $parent = $ProcessByPid[$parentId]
        if (([datetime]$parent.CreationDate).ToUniversalTime() -gt ([datetime]$current.CreationDate).ToUniversalTime()) { return $null }
        $current = $parent
    }
    return $null
}

function Get-ProcessTreeRows($RootRow, $AllProcesses) {
    $selected = @{}
    $queue = New-Object System.Collections.Generic.Queue[object]
    $queue.Enqueue($RootRow)
    while ($queue.Count -gt 0) {
        $current = $queue.Dequeue()
        $key = [uint32]$current.ProcessId
        if ($selected.ContainsKey($key)) { continue }
        $selected[$key] = $current
        foreach ($child in $AllProcesses) {
            if ([uint32]$child.ParentProcessId -ne $key) { continue }
            if (([datetime]$child.CreationDate).ToUniversalTime() -lt ([datetime]$current.CreationDate).ToUniversalTime()) { continue }
            $queue.Enqueue($child)
        }
    }
    return @($selected.Values)
}

function Stop-VerifiedProcessTree(
    $RootRow,
    $AllProcesses,
    [string]$Reason,
    [bool]$AllowWeatherDescendants = $false
) {
    $tree = @(Get-ProcessTreeRows $RootRow $AllProcesses)
    $governed = @($tree | Where-Object { Test-GovernedWeatherProcess $_ })
    if (-not $AllowWeatherDescendants -and $governed.Count -gt 0) {
        Write-GuardLog "CRITICAL" ("refusing agent-tree termination for pid {0}: tree contains {1} governed weather process(es)" -f $RootRow.ProcessId, $governed.Count)
        return $false
    }

    $depthByPid = @{}
    $depthByPid[[uint32]$RootRow.ProcessId] = 0
    $pending = @($tree | Where-Object { [uint32]$_.ProcessId -ne [uint32]$RootRow.ProcessId })
    while ($pending.Count -gt 0) {
        $progress = $false
        $next = @()
        foreach ($row in $pending) {
            $parentId = [uint32]$row.ParentProcessId
            if (-not $depthByPid.ContainsKey($parentId)) { $next += $row; continue }
            $depthByPid[[uint32]$row.ProcessId] = 1 + [int]$depthByPid[$parentId]
            $progress = $true
        }
        if (-not $progress) { break }
        $pending = @($next)
    }

    # NEVER name this variable $pid. PowerShell names are case-insensitive and $PID is a
    # Constant, AllScope automatic variable holding THIS process's id, so `$pid = ...` raises a
    # statement-terminating error that the default Continue preference swallows. From
    # 2026-08-23 to 2026-09-19 that left every lookup below pointed at the guard itself: the
    # CreationDate comparison always mismatched, "creation identity changed" was logged once
    # per tree member with the guard's own pid, and Stop-Process was never reached. Every tree
    # kill this guard owns was inert for 27 days (memory_commit_guard.log 2026-09-10T21:29).
    $ok = $true
    $ordered = @($tree | Sort-Object @{ Expression = {
        $memberId = [uint32]$_.ProcessId
        if ($depthByPid.ContainsKey($memberId)) { -[int]$depthByPid[$memberId] } else { 0 }
    } })
    Write-GuardLog "ACTION" ("{0}; terminating verified process tree root pid {1} members {2}" -f $Reason, $RootRow.ProcessId, $tree.Count)
    foreach ($row in $ordered) {
        $memberId = [uint32]$row.ProcessId
        if ($memberId -eq [uint32]$PID) {
            Write-GuardLog "CRITICAL" ("refusing to terminate the guard's own process pid {0}" -f $memberId)
            $ok = $false
            continue
        }
        $current = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $memberId) -ErrorAction SilentlyContinue
        if (-not $current) { continue }
        if (([datetime]$current.CreationDate).ToUniversalTime() -ne ([datetime]$row.CreationDate).ToUniversalTime()) {
            Write-GuardLog "ERROR" ("pid {0} creation identity changed before termination" -f $memberId)
            $ok = $false
            continue
        }
        try {
            Stop-Process -Id $memberId -Force -Confirm:$false -ErrorAction Stop
        }
        catch {
            Write-GuardLog "ERROR" ("failed to terminate pid {0}: {1}" -f $memberId, $_.Exception.Message)
            $ok = $false
        }
    }
    return $ok
}

function Get-ProcessTreePrivateBytes($RootRow, $AllProcesses, $RuntimeByPid) {
    $privateBytes = [long]0
    foreach ($member in @(Get-ProcessTreeRows $RootRow $AllProcesses)) {
        $runtime = $RuntimeByPid[[uint32]$member.ProcessId]
        if ($runtime) { $privateBytes += [long]$runtime.PrivateMemorySize64 }
    }
    return $privateBytes
}

$os = Get-CimInstance Win32_OperatingSystem
$commitTotalMB = [double]$os.TotalVirtualMemorySize / 1024.0
$commitUsedMB = ([double]$os.TotalVirtualMemorySize - [double]$os.FreeVirtualMemory) / 1024.0
$commitPercent = if ($commitTotalMB -gt 0) { 100.0 * $commitUsedMB / $commitTotalMB } else { 0.0 }
$freeRamMB = [double]$os.FreePhysicalMemory / 1024.0
$warnFreePhysicalMB = [double]$WarnFreePhysicalBytes / 1MB
$allProcesses = @(Get-CimInstance Win32_Process)
$processByPid = @{}
$runtimeByPid = @{}
foreach ($row in $allProcesses) {
    $processByPid[[uint32]$row.ProcessId] = $row
    $runtimeByPid[[uint32]$row.ProcessId] = Get-Process -Id $row.ProcessId -ErrorAction SilentlyContinue
}

$status = @{
    checked_at = (Get-Date -Format "o")
    commit_used_mb = [math]::Round($commitUsedMB, 0)
    commit_total_mb = [math]::Round($commitTotalMB, 0)
    commit_percent = [math]::Round($commitPercent, 1)
    free_ram_mb = [math]::Round($freeRamMB, 0)
    physical_warn_below_mb = [math]::Round($warnFreePhysicalMB, 0)
    physical_warning = $false
    memory_warning = $false
    warn_percent = $WarnPercent
    act_percent = $ActPercent
    action = "none"
    actions = @()
    agent_heavy_process_count = 0
    agent_heavy_workload_count = 0
    agent_heavy_admitted_workload_count = 0
    agent_heavy_lease_owner_workload_count = 0
    agent_heavy_lease_records_unreadable = $false
    agent_heavy_max_private_mb = 0
    agent_heavy_window_allowed = $false
}

# A previous Codex session launched 42 pytest/compile invocations across
# concurrent agents inside the protected window. Enforce the existing host
# policy from OS process ancestry, not from model compliance. Each distinct
# direct tool subtree is one workload; a PID is accepted only while its parent
# creation identity is older, which closes the Windows PID-reuse hole.
# CreationDate is an offset-bearing instant (a Kind=Local DateTime that keeps the
# ambiguous-DST bit); compare it only via .ToUniversalTime(), never by its local
# components. Every age and creation order in this guard compares UTC instants:
# on the wall clock a 01:55 EDT parent reads as younger than its 01:05 EST child
# across the fall-back hour (DST audit 2026-10-07 DST-M4).
# The 00:30-09:00 and 12:00-18:00 windows are deliberately local.
$localNow = Get-Date
$utcNow = $localNow.ToUniversalTime()
$minuteOfDay = (60 * $localNow.Hour) + $localNow.Minute + ($localNow.Second / 60.0)
$agentHeavyWindowAllowed = ($minuteOfDay -ge 30.0) -and ($minuteOfDay -lt 540.0)
$status.agent_heavy_window_allowed = $agentHeavyWindowAllowed
$agentHeavyModuleNames = $null
try {
    $agentHeavyModuleNames = @(Get-AgentHeavyModuleNames (Join-Path $PSScriptRoot "workload_admission.ps1"))
}
catch {
    Write-GuardLog "WARNING" ("heavy-module list unavailable; only pytest/compileall/coverage/tox/nox modules count this run: {0}" -f $_.Exception.Message)
}
$heavyToolRoots = @{}
$heavyRowsByKey = @{}
foreach ($row in $allProcesses) {
    if (-not (Test-AgentHeavyProcess $row)) { continue }
    $ageSeconds = ($utcNow - ([datetime]$row.CreationDate).ToUniversalTime()).TotalSeconds
    if ($ageSeconds -lt $AgentWorkloadGraceSeconds) { continue }
    $toolRoot = Get-AgentToolRoot $row $processByPid
    if (-not $toolRoot) { continue }
    $key = "{0}|{1}" -f $toolRoot.ProcessId, ([datetime]$toolRoot.CreationDate).ToUniversalTime().Ticks
    if (-not $heavyToolRoots.ContainsKey($key)) { $heavyToolRoots[$key] = $toolRoot }
    if (-not $heavyRowsByKey.ContainsKey($key)) { $heavyRowsByKey[$key] = New-Object System.Collections.Generic.List[object] }
    $heavyRowsByKey[$key].Add($row)
}

# Lease admission. A heavy member is admitted when a live heavy-workload lease
# owner (workstation_heavy.ps1, the bounded suite, training_window, a one-off lease
# wrapper) is the member, an ancestor below the agent root, or inside the member's
# own subtree. A tool tree whose every heavy member is admitted is never a window
# or concurrency target; that lease already enforces the window and serialization.
# A tool tree that CONTAINS a live lease owner is never terminated as a whole by
# any rule here, the private-byte budget included: the owner's finally blocks
# (training_window re-enabling capture supervisors, lease release) must run, so
# only heavy member subtrees that do not contain the owner are stopped.
$unadmittedRowsByKey = @{}
$admittedRootKeys = @{}
$ownerRootKeys = @{}
$leaseOwners = @()
$leaseRecordsUnreadable = $false
if ($heavyToolRoots.Count -gt 0) {
    $leaseState = Get-AdmittedLeaseOwners $RepoRoot $HeavyWorkloadStateRoot
    $leaseOwners = @($leaseState.Owners)
    if (@($leaseState.Unreadable).Count -gt 0) {
        # Fail toward sparing: a lease that cannot be read may be admitting this work.
        $leaseRecordsUnreadable = $true
        Write-GuardLog "WARNING" ("heavy-workload lease record(s) unreadable ({0}); skipping agent window and concurrency kills this run, budget kills stop heavy members only" -f (@($leaseState.Unreadable) -join ", "))
    }
}
foreach ($entry in $heavyToolRoots.GetEnumerator()) {
    $unadmitted = New-Object System.Collections.Generic.List[object]
    foreach ($member in $heavyRowsByKey[$entry.Key]) {
        if (-not (Test-AgentLeaseAdmitted $member $processByPid $allProcesses $leaseOwners)) { $unadmitted.Add($member) }
    }
    $unadmittedRowsByKey[$entry.Key] = $unadmitted
    if ($unadmitted.Count -eq 0) { $admittedRootKeys[$entry.Key] = $true }
    if (Test-AgentTreeHasLeaseOwner $entry.Value $allProcesses $leaseOwners) { $ownerRootKeys[$entry.Key] = $true }
}
$agentHeavyRows = @($allProcesses | Where-Object {
    if (-not (Test-AgentHeavyProcess $_)) { return $false }
    return $null -ne (Get-AgentToolRoot $_ $processByPid)
})
$status.agent_heavy_process_count = $agentHeavyRows.Count
$status.agent_heavy_workload_count = $heavyToolRoots.Count
$status.agent_heavy_admitted_workload_count = $admittedRootKeys.Count
$status.agent_heavy_lease_owner_workload_count = $ownerRootKeys.Count
$status.agent_heavy_lease_records_unreadable = $leaseRecordsUnreadable

$agentTreeBytes = @{}
foreach ($entry in $heavyToolRoots.GetEnumerator()) {
    $agentTreeBytes[$entry.Key] = Get-ProcessTreePrivateBytes $entry.Value $allProcesses $runtimeByPid
}
if ($agentTreeBytes.Count -gt 0) {
    $status.agent_heavy_max_private_mb = [math]::Round(
        (($agentTreeBytes.Values | Measure-Object -Maximum).Maximum / 1MB),
        0
    )
}

$agentTargetMap = @{}
if ($leaseRecordsUnreadable) {
    # No window or concurrency targets this run (see the WARNING above).
}
elseif (-not $agentHeavyWindowAllowed) {
    foreach ($entry in $heavyToolRoots.GetEnumerator()) {
        if ($admittedRootKeys.ContainsKey($entry.Key)) { continue }
        $agentTargetMap[$entry.Key] = $entry.Value
    }
}
elseif ($heavyToolRoots.Count -gt $MaxConcurrentAgentHeavyWorkloads) {
    $orderedRoots = @($heavyToolRoots.Values |
        Sort-Object @{ Expression = { ([datetime]$_.CreationDate).ToUniversalTime() } }, ProcessId)
    # Each tree holding a live lease takes a slot first; fully admitted trees are
    # never targets; the oldest trees with unadmitted heavy work fill what remains.
    $freeSlots = $MaxConcurrentAgentHeavyWorkloads - $ownerRootKeys.Count
    foreach ($root in $orderedRoots) {
        $key = "{0}|{1}" -f $root.ProcessId, ([datetime]$root.CreationDate).ToUniversalTime().Ticks
        if ($admittedRootKeys.ContainsKey($key)) { continue }
        if ($freeSlots -gt 0) { $freeSlots--; continue }
        $agentTargetMap[$key] = $root
    }
}
foreach ($entry in $heavyToolRoots.GetEnumerator()) {
    if ([long]$agentTreeBytes[$entry.Key] -ge $MinKillPrivateBytes) {
        $agentTargetMap[$entry.Key] = $entry.Value
    }
}
foreach ($entry in $agentTargetMap.GetEnumerator()) {
    $target = $entry.Value
    $treePrivateMB = [math]::Round(([long]$agentTreeBytes[$entry.Key] / 1MB), 0)
    $overBudget = [long]$agentTreeBytes[$entry.Key] -ge $MinKillPrivateBytes
    $reason = if ($overBudget) {
        "Codex tool tree exceeds the $([math]::Round($MinKillPrivateBytes / 1MB, 0)) MB private budget (observed ${treePrivateMB} MB)"
    } elseif ($agentHeavyWindowAllowed) {
        "Codex heavy-workload concurrency exceeds $MaxConcurrentAgentHeavyWorkloads"
    } else {
        "Codex heavy workload is outside the 00:30-09:00 host window"
    }
    if ($ownerRootKeys.ContainsKey($entry.Key) -or $leaseRecordsUnreadable) {
        # Never the whole tree: stop heavy member subtrees that hold no lease owner.
        # Over budget that includes admitted members BELOW the owner (the job, not
        # its wrapper); otherwise only unadmitted members.
        $memberReason = if ($overBudget) { "{0} (heavy member subtree; the lease owner is spared)" -f $reason } else { "{0} (unadmitted member of a leased tool tree)" -f $reason }
        $candidateMembers = if ($overBudget) { @($heavyRowsByKey[$entry.Key]) } else { @($unadmittedRowsByKey[$entry.Key]) }
        $coveredMemberIds = @{}
        $memberKilled = $false
        foreach ($member in @($candidateMembers |
                Sort-Object @{ Expression = { ([datetime]$_.CreationDate).ToUniversalTime() } }, ProcessId)) {
            if ($coveredMemberIds.ContainsKey([uint32]$member.ProcessId)) { continue }
            $memberTree = @(Get-ProcessTreeRows $member $allProcesses)
            if (@($memberTree | Where-Object { Test-AgentLeaseOwnerRow $_ $leaseOwners }).Count -gt 0) {
                Write-GuardLog "WARNING" ("left heavy pid {0} running: its subtree owns a heavy-workload lease" -f $member.ProcessId)
                continue
            }
            foreach ($covered in $memberTree) { $coveredMemberIds[[uint32]$covered.ProcessId] = $true }
            if (Stop-VerifiedProcessTree $member $allProcesses $memberReason $true) {
                $guardActions.Add("killed_agent_member_pid_$($member.ProcessId)")
                $terminationPerformed = $true
                $memberKilled = $true
            } else {
                $guardActions.Add("kill_failed_agent_member_pid_$($member.ProcessId)")
            }
        }
        if (-not $memberKilled -and $overBudget) {
            Write-GuardLog "WARNING" ("{0}; tool tree pid {1} holds a heavy-workload lease and has no heavy member outside the owner's ancestry; not terminated" -f $reason, $target.ProcessId)
        }
        continue
    }
    if (Stop-VerifiedProcessTree $target $allProcesses $reason $true) {
        $action = "killed_agent_tree_pid_$($target.ProcessId)"
        $guardActions.Add($action)
        $terminationPerformed = $true
    } else {
        $guardActions.Add("kill_failed_agent_tree_pid_$($target.ProcessId)")
    }
}

# A scheduled PowerShell wrapper can be terminated while its delegated Python
# child survives in the S4U session. That happened to the evidence refresh on
# 2026-08-13: Task Scheduler no longer owned the run, but the orphaned
# weather.operations.daily_refresh child exhausted host commit and starved
# every snapshot market inside the graded window. The ordinary commit rule
# deliberately exempts governed weather modules, so handle this narrower case
# from scheduler truth: during the protected window, an evidence-refresh child
# older than two minutes cannot be legitimate when its owning task is not
# Running. Stop children before shims by sorting on private bytes.
$evidenceTaskName = "WeatherEveningEvidenceRefresh"
if ($localNow.Hour -ge 12 -and $localNow.Hour -lt 18) {
    $evidenceTask = Get-ScheduledTask -TaskName $evidenceTaskName -ErrorAction SilentlyContinue
    if ($evidenceTask -and [string]$evidenceTask.State -ne "Running") {
        $escapedTaskName = [regex]::Escape($evidenceTaskName)
        $orphanedEvidence = @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
            ForEach-Object {
                $cmd = [string]$_.CommandLine
                $ageMinutes = ($utcNow - ([datetime]$_.CreationDate).ToUniversalTime()).TotalMinutes
                if ($ageMinutes -lt 2) { return }
                if ($cmd -notmatch '(?i)-m\s+weather\.operations\.daily_refresh') { return }
                if ($cmd -notmatch "(?i)--scheduler-task-name\s+$escapedTaskName(?:\s|$)") { return }
                $proc = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
                if (-not $proc) { return }
                [pscustomobject]@{
                    Id = $_.ProcessId
                    PrivateBytes = $proc.PrivateMemorySize64
                    PrivateMB = [math]::Round($proc.PrivateMemorySize64 / 1MB, 0)
                    AgeMinutes = [math]::Round($ageMinutes, 0)
                }
            } | Where-Object { $null -ne $_ } | Sort-Object PrivateBytes -Descending)
        foreach ($target in $orphanedEvidence) {
            Write-GuardLog "ACTION" ("owning task {0} is {1} inside protected window; killing orphaned daily-refresh pid {2} age {3}m private {4}MB" -f `
                $evidenceTaskName, $evidenceTask.State, $target.Id, $target.AgeMinutes, $target.PrivateMB)
            try {
                Stop-Process -Id $target.Id -Force -Confirm:$false -ErrorAction Stop
                $guardActions.Add("killed_orphaned_evidence_pid_$($target.Id)")
                $terminationPerformed = $true
                Write-GuardLog "ACTION" ("pid {0} terminated" -f $target.Id)
            }
            catch {
                $guardActions.Add("kill_failed_orphaned_evidence_pid_$($target.Id)")
                Write-GuardLog "ERROR" ("failed to kill orphaned daily-refresh pid {0}: {1}" -f $target.Id, $_.Exception.Message)
            }
        }
    }
}

if ($freeRamMB -lt $warnFreePhysicalMB) {
    $topWorkingSet = Get-Process -ErrorAction SilentlyContinue |
        Sort-Object WorkingSet64 -Descending | Select-Object -First 5 |
        ForEach-Object { "{0}(pid {1})={2}MB" -f $_.Name, $_.Id, [math]::Round($_.WorkingSet64 / 1MB, 0) }
    Write-GuardLog "WARNING" ("physical RAM available at {0} MB, below {1} MB; top working set: {2}" -f `
        [math]::Round($freeRamMB, 0), [math]::Round($warnFreePhysicalMB, 0), ($topWorkingSet -join ", "))
    $status.physical_warning = $true
}

if ($commitPercent -ge $WarnPercent) {
    $top = Get-Process | Sort-Object PrivateMemorySize64 -Descending | Select-Object -First 5 |
        ForEach-Object { "{0}(pid {1})={2}MB" -f $_.Name, $_.Id, [math]::Round($_.PrivateMemorySize64 / 1MB, 0) }
    Write-GuardLog "WARNING" ("commit at {0}% ({1}/{2} MB); top: {3}" -f `
        [math]::Round($commitPercent, 1), [math]::Round($commitUsedMB, 0), [math]::Round($commitTotalMB, 0), ($top -join ", "))
    $status.memory_warning = $true
}

if ($commitPercent -ge $ActPercent -and -not $terminationPerformed) {
    $candidates = @($allProcesses | Where-Object { ([string]$_.Name) -like 'python*' } | ForEach-Object {
        $proc = $runtimeByPid[[uint32]$_.ProcessId]
        if ($null -eq $proc) { return }
        $cmd = [string]$_.CommandLine
        # Governed weather modules are never eligible.
        if (Test-GovernedWeatherProcess $_) { return }
        # Ad-hoc profiles: pytest/compile, stdin script, inline -c, or bare script path.
        $adhoc = ($cmd -match '(?i)python[w]?(\.exe)?"?\s+-\s*$') -or
                 ($cmd -match '(?i)python[w]?(\.exe)?"?\s+-c\s') -or
                 ($cmd -match '(?i)python[w]?(\.exe)?"?\s+[^-]\S*\.py') -or
                 ($cmd -match '(?i)(?:^|\s)-m\s+(?:pytest|compileall|coverage|tox|nox)(?:\s|$)')
        if (-not $adhoc) { return }
        if ($proc.PrivateMemorySize64 -lt $MinKillPrivateBytes) { return }
        [pscustomobject]@{
            Kind = "python"
            Id = $_.ProcessId
            CreationDate = $_.CreationDate
            RootRow = $_
            PrivateBytes = $proc.PrivateMemorySize64
            PrivateMB = [math]::Round($proc.PrivateMemorySize64 / 1MB, 0)
            CommandLine = $cmd.Substring(0, [Math]::Min(200, $cmd.Length))
        }
    } | Where-Object { $null -ne $_ })

    # An agent can spread one runaway over several PowerShell/Python children,
    # each below 8 GiB. Attribute aggregate private bytes to the verified
    # agent root (codex.exe, chatgpt.exe or claude.exe) and treat the tree as
    # one offender.
    foreach ($root in @($allProcesses | Where-Object { $agentRootNames -contains ([string]$_.Name).ToLowerInvariant() })) {
        $tree = @(Get-ProcessTreeRows $root $allProcesses)
        $privateBytes = [long]0
        foreach ($member in $tree) {
            $runtime = $runtimeByPid[[uint32]$member.ProcessId]
            if ($runtime) { $privateBytes += [long]$runtime.PrivateMemorySize64 }
        }
        if ($privateBytes -lt $MinKillPrivateBytes) { continue }
        $candidates += [pscustomobject]@{
            Kind = "agent_tree"
            Id = $root.ProcessId
            CreationDate = $root.CreationDate
            RootRow = $root
            PrivateBytes = $privateBytes
            PrivateMB = [math]::Round($privateBytes / 1MB, 0)
            CommandLine = "agent process tree"
        }
    }

    $target = $candidates | Sort-Object PrivateBytes -Descending | Select-Object -First 1
    if ($null -ne $target) {
        $reason = "commit at {0}%: {1} pid {2} private {3} MB" -f `
            [math]::Round($commitPercent, 1), $target.Kind, $target.Id, $target.PrivateMB
        $allowWeather = $target.Kind -eq "agent_tree"
        if (Stop-VerifiedProcessTree $target.RootRow $allProcesses $reason $allowWeather) {
            $guardActions.Add("killed_$($target.Kind)_pid_$($target.Id)")
            $terminationPerformed = $true
        }
        else {
            $guardActions.Add("kill_failed_$($target.Kind)_pid_$($target.Id)")
        }
    } else {
        Write-GuardLog "CRITICAL" ("commit at {0}% but no eligible ungoverned offender above {1} MB; manual attention required" -f `
            [math]::Round($commitPercent, 1), [math]::Round($MinKillPrivateBytes / 1MB, 0))
        $guardActions.Add("no_eligible_target")
    }
}

# ---- Orphan sweep: runs every invocation, independent of commit level ----
$orphanActions = @()
$allProcs = @($allProcesses | Where-Object { ([string]$_.Name) -like 'python*' })
$pidTable = @{}
$allProcesses | ForEach-Object { $pidTable[[uint32]$_.ProcessId] = ([datetime]$_.CreationDate).ToUniversalTime() }
foreach ($row in $allProcs) {
    $cmd = [string]$row.CommandLine
    if ($cmd -match "-m\s+weather\.") { continue }
    $isStdin = $cmd -match '(?i)python[w]?(\.exe)?"?\s+-\s*$'
    $isInline = $cmd -match '(?i)python[w]?(\.exe)?"?\s+-c\s'
    $isBareScript = $cmd -match '(?i)python[w]?(\.exe)?"?\s+[^-]\S*\.py'
    if (-not ($isStdin -or $isInline -or $isBareScript)) { continue }
    $ageMinutes = ((Get-Date).ToUniversalTime() - ([datetime]$row.CreationDate).ToUniversalTime()).TotalMinutes
    if ($ageMinutes -lt $OrphanGraceMinutes) { continue }
    $ppid = [uint32]$row.ParentProcessId
    $parentBirth = $pidTable[$ppid]
    # Parent gone, or its PID was reused by a younger process.
    $orphaned = ($null -eq $parentBirth) -or ($parentBirth -gt ([datetime]$row.CreationDate).ToUniversalTime())
    if (-not $orphaned) { continue }
    $proc = Get-Process -Id $row.ProcessId -ErrorAction SilentlyContinue
    $privateMB = 0
    if ($proc) { $privateMB = [math]::Round($proc.PrivateMemorySize64 / 1MB, 0) }
    $readGB = [math]::Round([double]$row.ReadTransferCount / 1GB, 1)
    $summary = "pid {0} age {1}m private {2}MB read {3}GB: {4}" -f `
        $row.ProcessId, [math]::Round($ageMinutes, 0), $privateMB, $readGB, `
        $cmd.Substring(0, [Math]::Min(160, $cmd.Length))
    if ($isStdin -or $isInline) {
        Write-GuardLog "ACTION" ("orphaned ad-hoc python (parent {0} gone): killing {1}" -f $ppid, $summary)
        try {
            Stop-Process -Id $row.ProcessId -Force -Confirm:$false -ErrorAction Stop
            $orphanActions += "killed_pid_$($row.ProcessId)"
            $guardActions.Add("killed_orphan_pid_$($row.ProcessId)")
            $terminationPerformed = $true
            Write-GuardLog "ACTION" ("pid {0} terminated" -f $row.ProcessId)
        } catch {
            $orphanActions += "kill_failed_pid_$($row.ProcessId)"
            $guardActions.Add("kill_failed_orphan_pid_$($row.ProcessId)")
            Write-GuardLog "ERROR" ("failed to kill orphan pid {0}: {1}" -f $row.ProcessId, $_.Exception.Message)
        }
    } else {
        Write-GuardLog "WARNING" ("orphaned bare-script python left running (detached launchers are legitimate): {0}" -f $summary)
        $orphanActions += "warned_pid_$($row.ProcessId)"
    }
}
$status.orphan_sweep = if ($orphanActions.Count -gt 0) { $orphanActions -join "," } else { "clean" }
$status.actions = @($guardActions)
$status.action = if ($guardActions.Count -gt 0) { $guardActions -join "," } else { "none" }

# Preserve incident-bearing samples without raw command lines. The mutable
# latest status is still atomic and cheap for monitors; history is event-only.
if ($status.physical_warning -or $status.memory_warning -or $guardActions.Count -gt 0 -or $status.agent_heavy_workload_count -gt 0) {
    $history = [ordered]@{
        checked_at = $status.checked_at
        commit_percent = $status.commit_percent
        free_ram_mb = $status.free_ram_mb
        agent_heavy_window_allowed = $status.agent_heavy_window_allowed
        agent_heavy_process_count = $status.agent_heavy_process_count
        agent_heavy_workload_count = $status.agent_heavy_workload_count
        agent_heavy_admitted_workload_count = $status.agent_heavy_admitted_workload_count
        agent_heavy_lease_owner_workload_count = $status.agent_heavy_lease_owner_workload_count
        agent_heavy_lease_records_unreadable = $status.agent_heavy_lease_records_unreadable
        agent_heavy_max_private_mb = $status.agent_heavy_max_private_mb
        actions = @($guardActions)
    }
    Add-Content -LiteralPath $historyPath -Value ($history | ConvertTo-Json -Compress) -Encoding utf8
}

$statusTempPath = "{0}.{1}.tmp" -f $statusPath, [guid]::NewGuid().ToString("N")
try {
    $status | ConvertTo-Json | Out-File -LiteralPath $statusTempPath -Encoding utf8
    Move-Item -LiteralPath $statusTempPath -Destination $statusPath -Force
}
finally {
    if (Test-Path -LiteralPath $statusTempPath) { Remove-Item -LiteralPath $statusTempPath -Force }
}
