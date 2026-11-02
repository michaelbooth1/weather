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
#                     `-m` module list owned by workload_admission.ps1 plus a
#                     short guard-local list (refresh, replays, pooled
#                     training), and recursive scans of a repository data
#                     directory by an rg/grep/find/robocopy process image.
#                     Every child is judged by its OWN command line; a
#                     powershell/pwsh/cmd line that itself runs pytest,
#                     compileall, a heavy weather module, Get-ChildItem
#                     -Recurse or rg over data is heavy too (master's rule, a
#                     secondary signal). The start-up grace runs on the TOOL
#                     ROOT's age, so a loop of short heavy children is seen.
#                     Inside that window, retain at most one such tool tree.
#                     Work admitted under a live heavy-workload lease (the
#                     lease owner recorded by workload_admission.ps1, matched
#                     by PID and creation time, is the row, an ancestor, or,
#                     for a non-shell launcher, inside the row's subtree) is
#                     never a window or concurrency target while
#                     the lease is inside its own policy window (agent_heavy
#                     00:30-09:00, stage_a 09:30-11:55, workstation/portable
#                     profiles always, but only on the assigned non-capture
#                     host). Past it, the owner's heavy descendants are
#                     stopped and only the owner itself is spared
#                     (CRITICAL). A tool tree containing a live lease owner
#                     is never terminated as a whole, and no stop reaches a
#                     live lease owner or, while one lives, a console host,
#                     except at the hard ceiling (97% commit, or the owner
#                     itself at twice the private budget), where the owner
#                     is stopped too. A lease owner orphaned by a stop keeps
#                     its tree under these rules (memory_commit_guard_state).
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
    # Hard ceiling: at this commit, or when a lease owner itself holds twice the
    # private budget, the owner is stopped too (CRITICAL; its finally is lost).
    [double]$HardCeilingPercent = 97.0,
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
$guardStatePath = Join-Path $logDir "memory_commit_guard_state.json"

function Write-GuardLog([string]$Level, [string]$Message) {
    $line = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $Level, $Message
    Add-Content -Path $logPath -Value $line -Encoding utf8
}

$agentRootNames = @("codex.exe", "chatgpt.exe", "claude.exe")
# Claude Code's Bash tool runs claude.exe -> bash.exe (Git Bash, nested) -> child;
# its PowerShell tool runs claude.exe -> cmd.exe -> powershell.exe whose script
# text arrives through an environment variable, not the command line. Shells are
# therefore never classified by name; the direct child of the agent root is the
# tool tree whatever it is.
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
        # An unquoted interpreter path with spaces (C:\Program Files\Python312\python.exe)
        # splits into several words: the arguments start after the first word that ends
        # in the interpreter name. No such word: unparsed, and the caller falls back to
        # the legacy whole-line patterns.
        $start = -1
        for ($index = 0; $index -lt $words.Count; $index++) {
            if ([string]$words[$index] -match '(?i)(?:\A|[\\/])pythonw?[0-9.]*(?:\.exe)?\z') { $start = $index + 1; break }
        }
        if ($start -lt 1) { return $null }
        for ($index = $start; $index -lt $words.Count; $index++) {
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
        # The explicit list owned by Get-WeatherWorkstationOfflineModule in
        # workload_admission.ps1 (read at script scope), plus the heavy modules the
        # wrapper does not admit but which master's shell-line rule caught by name
        # (refresh, replays, pooled training). A status/help invocation of a listed
        # module is a reader, not a job.
        $guardHeavyModules = @(
            'weather.operations.daily_refresh',
            'weather.operations.daily_refresh_bounded',
            'weather.backtesting.r0_paired_replay',
            'weather.backtesting.metar_keying_replay',
            'weather.backtesting.lockin_anchor_replay',
            'weather.calibration.pooled_training',
            'weather.calibration.pooled_band_training',
            'weather.calibration.pooled_density_training')
        $listed = ($guardHeavyModules -ccontains $Module) -or
            ($null -ne $agentHeavyModuleNames -and ($agentHeavyModuleNames -ccontains $Module))
        if (-not $listed) { return $false }
        $first = if (@($Rest).Count -gt 0) { [string]@($Rest)[0] } else { '' }
        return -not ($first -cin @('status', '--help', '-h', '--version'))
    }

    function Test-AgentShellLineHeavy([string]$CommandLine) {
        # Master's shell-line rule, a secondary signal for powershell/pwsh/cmd: a tool
        # shell that runs pytest/compileall or a heavy weather module in its own -Command
        # line (including a `foreach { python -m pytest $f }` loop whose children each
        # finish inside the grace) is heavy itself. A lease admits it like any member.
        if ($CommandLine -match '(?i)(?:^|\s)-m\s+(?:pytest|compileall|coverage|tox|nox)(?:\s|$)') { return $true }
        $readers = @('status', '--help', '-h', '--version')
        foreach ($match in [regex]::Matches($CommandLine,
                '(?i)(?:^|[\s"''])-m\s+["'']?(?<module>[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)["'']?(?:\s+["'']?(?<next>[^\s"'';|&]+))?')) {
            $module = $match.Groups['module'].Value.ToLowerInvariant()
            $next = $match.Groups['next'].Value
            $rest = if ($next) { @($next) } else { @() }
            if (Test-AgentHeavyModule $module $rest) { return $true }
            if ($module -match '\Aweather\.\S*(?:retrain|training|replay|backtest|daily_refresh|score_all)' -and
                -not ($next -cin $readers)) { return $true }
        }
        if (($CommandLine -match '(?i)Get-ChildItem') -and ($CommandLine -match '(?i)-Recurse')) { return $true }
        $normalized = $CommandLine.Replace('/', '\')
        return (($CommandLine -match '(?i)(?:^|[\s;&|])rg(?:\.exe)?(?:\s|$)') -and
            ($normalized -match '(?i)(?:^|[\s"''])(?:\.\\)?data(?:\\|[\s"''])'))
    }

    function Test-AgentRepoDataPath([string]$PathText) {
        # True for a directory path inside a repository data directory: relative
        # paths whose first segment is data (agents run from a checkout root), or
        # absolute paths with a data segment whose parent holds .git. A path whose
        # leaf has an extension is a single file, not a recursive scan.
        $path = $PathText.Trim().Replace('/', '\')
        if (-not $path) { return $false }
        # A UNC path is never probed: Test-Path on \\server\share can block on the
        # network for the length of an SMB timeout inside a one-minute guard.
        if ($path.StartsWith('\\')) { return $false }
        if ($path -match '\A\\([A-Za-z])(?:\\|\z)') { $path = $Matches[1] + ':' + $path.Substring(2) }
        $path = $path -replace '\A(?:\.\\)+', ''
        $segments = @($path.Split('\') | Where-Object { $_ -ne '' })
        if ($segments.Count -eq 0) { return $false }
        if ([string]$segments[$segments.Count - 1] -match '\.[A-Za-z0-9]{1,10}\z') { return $false }
        if ($path -notmatch '\A(?:[A-Za-z]:\\|\\\\)') { return ([string]$segments[0] -ieq 'data') }
        for ($index = 1; $index -lt $segments.Count; $index++) {
            if ([string]$segments[$index] -ine 'data') { continue }
            $parent = ($segments[0..($index - 1)] -join '\')
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
        $longValueOptions = if ($name -eq 'rg.exe') {
            @('regexp', 'file', 'glob', 'iglob', 'type', 'type-not', 'type-add', 'type-clear', 'max-count',
                'threads', 'context', 'after-context', 'before-context', 'max-depth', 'maxdepth', 'max-filesize',
                'encoding', 'replace', 'sort', 'sortr', 'color', 'colors', 'path-separator', 'pre', 'pre-glob',
                'engine', 'ignore-file', 'max-columns', 'context-separator', 'field-match-separator',
                'field-context-separator', 'dfa-size-limit', 'regex-size-limit', 'hyperlink-format', 'generate')
        } else {
            @('regexp', 'file', 'context', 'after-context', 'before-context', 'max-count', 'include', 'exclude',
                'exclude-dir', 'exclude-from', 'directories', 'devices', 'binary-files', 'label', 'group-separator')
        }
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
                # `--context 2`, `--glob '*.py'`: the value is the next word, not a path.
                if (-not $word.Contains('=') -and ($longValueOptions -ccontains $word.Substring(2))) { $index++ }
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

    if ($name -eq 'powershell.exe' -or $name -eq 'pwsh.exe' -or $name -eq 'cmd.exe') {
        # Children (python, rg, find) are judged above by their own lines. The shell
        # line is a secondary signal (master's rule): it can quote a command it does
        # not run, but it is also the only evidence of a recursive listing run inside
        # the shell and of a loop of short-lived heavy children.
        return (Test-AgentShellLineHeavy $cmd)
    }

    return ($name -eq 'pytest.exe')
}

function Test-AgentLeaseReadRace($Exception) {
    # True only for the races a live acquisition or release can cause: a sharing
    # violation (0x80070020) or lock violation (0x80070021), or the file or its
    # directory vanishing between the existence check and the read.
    for ($current = $Exception; $null -ne $current; $current = $current.InnerException) {
        if ($current -is [System.IO.FileNotFoundException] -or $current -is [System.IO.DirectoryNotFoundException]) { return $true }
        if ($current -is [System.IO.IOException] -and (($current.HResult -band 0xFFFF) -in @(32, 33))) { return $true }
    }
    return $false
}

function Get-GuardLeaseHostScope([string]$AssignmentRepoRoot, [string]$ExpectedHostId) {
    # Whether this guard runs on the assigned non-capture execution host, the only
    # host on which a workstation_offline or portable_execution lease may waive the
    # agent_heavy window (workload_admission.ps1 refuses those profiles everywhere
    # else, but a record is only a file: a forged or copied one must not waive it).
    # The capture host is a guard registered with -ExpectedExecutionHostId, or one
    # whose identity is dedicated_capture_execution_host_id in the assignment file.
    # Any doubt (no identity, unreadable or invalid assignment, UNASSIGNED, another
    # active host) leaves Eligible false: every lease then gets the agent_heavy window.
    $scope = [pscustomobject]@{ HostId = ''; Eligible = $false; Why = '' }
    if ($ExpectedHostId) { $scope.Why = 'registered capture host'; return $scope }
    $errorMark = $Error.Count
    try {
        $scope.HostId = [string](Get-MemoryGuardExecutionHostId)
        $path = Join-Path $AssignmentRepoRoot "config\international_live_execution_host.json"
        $assignment = [IO.File]::ReadAllText($path, (New-Object System.Text.UTF8Encoding($false))).TrimStart([char]0xFEFF) | ConvertFrom-Json
        $dedicated = [string]$assignment.dedicated_capture_execution_host_id
        $active = [string]$assignment.active_portable_execution_host_id
        if ([string]$assignment.schema_version -cne 'international_live_execution_host_assignment_v0.1') { $scope.Why = 'assignment schema unknown' }
        elseif ($dedicated -cnotmatch '\A[0-9a-f]{64}\z') { $scope.Why = 'assignment has no valid capture host' }
        elseif ($scope.HostId -ceq $dedicated) { $scope.Why = 'assigned capture host' }
        elseif ([string]$assignment.assignment_status -cne 'ASSIGNED') { $scope.Why = 'no execution host is assigned' }
        elseif ($active -cnotmatch '\A[0-9a-f]{64}\z' -or $scope.HostId -cne $active) { $scope.Why = 'not the assigned execution host' }
        else { $scope.Eligible = $true; $scope.Why = 'assigned non-capture execution host' }
    }
    catch {
        while ($Error.Count -gt $errorMark) { $Error.RemoveAt(0) }
        $scope.Eligible = $false
        $scope.Why = "host assignment unavailable ({0})" -f $_.Exception.Message
    }
    return $scope
}

function Test-AgentLeaseOwnerInWindow($Owner, [double]$MinuteOfDay) {
    # Local minute of day against the owner's effective policy window (see
    # Get-AdmittedLeaseOwners), each with its teardown grace: agent_heavy 00:30 to
    # 09:00 exactly (the guard's own window, no grace); stage_a 09:30 to its 11:55
    # teardown deadline; the workstation and portable profiles, which
    # Get-AdmittedLeaseOwners keeps only on the assigned non-capture host, have no
    # time window. Anything else (the integration mutex, an older schema, an expired
    # owner-approved exception) gets the agent_heavy window.
    switch -CaseSensitive ([string]$Owner.Window) {
        'workstation_offline' { return $true }
        'portable_execution' { return $true }
        'stage_a' { return ($MinuteOfDay -ge 570.0) -and ($MinuteOfDay -lt 715.0) }
        default { return ($MinuteOfDay -ge 30.0) -and ($MinuteOfDay -lt 540.0) }
    }
}

function Get-AdmittedLeaseOwners([string]$LeaseRepoRoot, [string]$StateRoot, [datetime]$NowUtc, $HostScope = $null) {
    # Owners of heavy-workload leases taken through workload_admission.ps1
    # (workstation_heavy.ps1, the bounded suite, training_window, one-off lease
    # wrappers). Files are opened read-only with full sharing: the guard never
    # probes for write access, so it cannot race a lease acquisition.
    #
    # Scope: only the repository lock files of $LeaseRepoRoot (the guard's own
    # checkout) and the host-global state files are read. A lease taken against a
    # different checkout or worktree writes its lock there and is invisible here,
    # unless its profile also writes the host-global state file.
    #
    # Matching. A v3 lease record names its owner's creation instant, and only the
    # live process with that PID AND creation instant counts. Any other JSON record
    # with a pid (the integration control mutex shares heavy_workload.lock and writes
    # weather_integration_control_mutex_v1; an older schema) counts only for a live
    # process with that PID created no later than the file's last write, so a record
    # left behind after its writer exited, whose PID was reused later, admits nothing.
    # A host-global state record admits its owner in ACTIVE and TEARDOWN_PENDING.
    #
    # Torn records. Acquisition truncates the lock and then writes it, and a failed
    # identity proof can leave it empty. An empty or unparseable file written within
    # the last minute is reported in Unreadable (the caller then skips window and
    # concurrency kills for the tick); an older one is stale and ignored.
    #
    # Release. Exit-WeatherHeavyWorkloadLease overwrites the repo lock with a
    # weather_heavy_workload_lease_released_v1 marker (no pid) before it disposes the
    # handle, so a released lease admits nothing even while its former owner process
    # lives on. The host-global state file is deleted on release. A release that
    # could not write the marker (it only warns) leaves the old record; the owner's
    # policy window below still bounds what it can admit.
    #
    # Window. Each owner carries the record's policy window. The caller admits work
    # only through owners inside their window; owners outside it are still protected
    # from every stop, but their heavy descendants are not admitted. The windowless
    # workstation_offline and portable_execution profiles are kept only on the
    # assigned non-capture host ($HostScope.Eligible, Get-GuardLeaseHostScope), and
    # for a repo lock only when the record's execution_host_id is this host's own
    # identity; otherwise the owner gets the agent_heavy window (RecordWindow keeps
    # what the record said). A host-state record has no execution_host_id field (its
    # schema is exact); it lives in this machine's own ProgramData, so the host check
    # alone applies to it.
    #
    # Read failures. A file whose last write time is known is judged by it (recent
    # torn write: Unreadable; older: stale, ignored). Without a usable last write
    # time only a sharing violation or a file/directory-not-found race counts as
    # Unreadable; anything else is logged as an ERROR and the file is ignored.
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
        # A handled read failure is reported through Unreadable or ignored as stale;
        # drop its record from $Error so the run's error list keeps meaning "unhandled".
        $errorMark = $Error.Count
        $writtenUtc = $null
        try {
            if (-not (Test-Path -LiteralPath $candidate.Path -PathType Leaf)) { continue }
            $writtenUtc = [IO.File]::GetLastWriteTimeUtc($candidate.Path)
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
        }
        catch {
            $failure = $_.Exception
            while ($Error.Count -gt $errorMark) { $Error.RemoveAt(0) }
            # GetLastWriteTimeUtc reports 1601-01-01 for a file that has vanished.
            $writtenKnown = ($null -ne $writtenUtc) -and ($writtenUtc.Year -gt 1601)
            if ($writtenKnown) {
                if ([math]::Abs(($NowUtc - $writtenUtc).TotalSeconds) -le 60.0) { $unreadable.Add([string]$candidate.Path) }
            }
            elseif (Test-AgentLeaseReadRace $failure) {
                $unreadable.Add([string]$candidate.Path)
            }
            else {
                Write-GuardLog "ERROR" ("heavy-workload lease record {0} ignored: its last write time is unreadable ({1})" -f $candidate.Path, $failure.Message)
            }
            continue
        }
        $ownerPid = [uint32]0
        $window = ''
        try {
            # A released marker (no pid) names no owner.
            if ([string]$record.schema_version -ceq 'weather_heavy_workload_lease_released_v1') { continue }
            if ($null -ne $record.pid -and [string]$record.pid -match '\A\d+\z') { $ownerPid = [uint32][string]$record.pid }
            if ($ownerPid -eq 0) { continue }
            $born = $null
            if ($candidate.Kind -eq 'repo_lock' -and [string]$record.schema_version -ceq 'weather_heavy_workload_lease_v3') {
                $window = [string]$record.policy_window
                $tokenMatch = [regex]::Match([string]$record.owner_process_creation_time_token, '\Awin32-filetime:(\d+)\z')
                if ($tokenMatch.Success) { $born = [datetime]::FromFileTimeUtc([long]$tokenMatch.Groups[1].Value) }
            }
            elseif ($candidate.Kind -eq 'host_state' -and [string]$record.schema_version -ceq 'weather_heavy_workload_state_v1') {
                if ([string]$record.state -cnotin @('ACTIVE', 'TEARDOWN_PENDING')) { continue }
                $window = switch -CaseSensitive ([string]$record.execution_host_profile) {
                    'workstation_offline_v1' { 'workstation_offline' }
                    'portable_execution_v1' { 'portable_execution' }
                    default { '' }
                }
                $born = [datetime]::Parse(
                    [string]$record.owner_process_start_utc,
                    [Globalization.CultureInfo]::InvariantCulture,
                    [Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()
            }
            $recordWindow = $window
            if ($window -cin @('workstation_offline', 'portable_execution')) {
                $hostHonours = ($null -ne $HostScope) -and ($HostScope.Eligible -eq $true)
                if ($hostHonours -and $candidate.Kind -eq 'repo_lock') {
                    $hostHonours = ([string]$record.execution_host_id -ceq [string]$HostScope.HostId)
                }
                if (-not $hostHonours) { $window = 'agent_heavy' }
            }
            $owners.Add([pscustomobject]@{
                Pid = $ownerPid
                CreationUtc = $born
                NotAfterUtc = $writtenUtc
                Source = $candidate.Kind
                Window = $window
                RecordWindow = $recordWindow
            })
        }
        catch {
            # A parsed record with an unusable identity falls back to the PID rule; a
            # pid that did not even convert (overflow) names no process at all.
            while ($Error.Count -gt $errorMark) { $Error.RemoveAt(0) }
            if ($ownerPid -ne 0) {
                # Only the agent_heavy or stage_a window survives this path: the
                # windowless profiles need the identity checks above.
                if ($window -cin @('workstation_offline', 'portable_execution')) { $window = 'agent_heavy' }
                $owners.Add([pscustomobject]@{ Pid = $ownerPid; CreationUtc = $null; NotAfterUtc = $writtenUtc; Source = $candidate.Kind; Window = $window; RecordWindow = $window })
            }
        }
    }
    return [pscustomobject]@{ Owners = $owners.ToArray(); Unreadable = $unreadable.ToArray() }
}

function Test-AgentLeaseOwnerRow($ProcessRow, $LeaseOwners) {
    $rowId = [uint32]$ProcessRow.ProcessId
    $born = ([datetime]$ProcessRow.CreationDate).ToUniversalTime()
    foreach ($owner in @($LeaseOwners)) {
        if ([uint32]$owner.Pid -ne $rowId) { continue }
        if ($null -ne $owner.CreationUtc) {
            # CIM CreationDate carries microseconds and the lease token 100 ns ticks of
            # the same kernel instant; one second absorbs rounding, never PID reuse
            # (a live owner's PID cannot be reused).
            if ([math]::Abs(($born - [datetime]$owner.CreationUtc).TotalSeconds) -le 1.0) { return $true }
        }
        elseif ($null -ne $owner.NotAfterUtc) {
            # No creation identity: the writer must have existed when the file was written.
            if (($born - [datetime]$owner.NotAfterUtc).TotalSeconds -le 1.0) { return $true }
        }
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
    # Admitted when the row is a live lease owner or one of the owner's verified
    # descendants (an ancestor below the agent root owns the lease).
    #
    # Above the owner (review m4): a powershell/pwsh/cmd shell is heavy only by its
    # own command line (master's shell-line rule), which is evidence of heavy work
    # run by the shell itself, so a lease below it never admits it: it is judged
    # like any heavy member, and the kill loop stops such a spine process alone so
    # the owner keeps running (orphaned; its tree stays attributed through the guard
    # state file). Any other process whose subtree holds the owner is admitted
    # whatever its name: `python tools\x.py`, py.exe or a git hook script that only
    # launched the leased wrapper must not be judged as unleased between the
    # wrapper's children (between bounded-suite chunks).
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
    if (([string]$ProcessRow.Name).ToLowerInvariant() -in @('powershell.exe', 'pwsh.exe', 'cmd.exe')) { return $false }
    return (Test-AgentTreeHasLeaseOwner $ProcessRow $AllProcesses $LeaseOwners)
}

function Test-AgentConsoleHost($ProcessRow) {
    # Stopping a console host ends every process attached to its console, which
    # can include a lease owner elsewhere in the tree: never a stop target here.
    return ([string]$ProcessRow.Name).ToLowerInvariant() -in @('conhost.exe', 'openconsole.exe')
}

function Get-AgentLeaseSpine($RootRow, $Tree, $ProcessByPid, $LeaseOwners) {
    # The protected spine of a tree holding a live lease owner: the tree root plus
    # every owner and each owner's verified ancestors inside the tree.
    $inTree = @{}
    foreach ($row in $Tree) { $inTree[[uint32]$row.ProcessId] = $row }
    $spine = @{}
    $spine[[uint32]$RootRow.ProcessId] = $true
    foreach ($row in $Tree) {
        if (-not (Test-AgentLeaseOwnerRow $row $LeaseOwners)) { continue }
        $current = $row
        for ($depth = 0; $depth -lt 64 -and $null -ne $current; $depth++) {
            $currentId = [uint32]$current.ProcessId
            if (-not $inTree.ContainsKey($currentId)) { break }
            $spine[$currentId] = $true
            if ($currentId -eq [uint32]$RootRow.ProcessId) { break }
            $parentId = [uint32]$current.ParentProcessId
            if (-not $ProcessByPid.ContainsKey($parentId)) { break }
            $parent = $ProcessByPid[$parentId]
            if (([datetime]$parent.CreationDate).ToUniversalTime() -gt ([datetime]$current.CreationDate).ToUniversalTime()) { break }
            $current = $parent
        }
    }
    return $spine
}

function Get-AgentLeaseBranches($RootRow, $AllProcesses, $ProcessByPid, $RuntimeByPid, $LeaseOwners) {
    # Disjoint subtrees hanging off the protected spine (see Get-AgentLeaseSpine);
    # nothing on it is ever returned, so the owner, its parents and the tree root
    # survive whatever is stopped. Console hosts are never returned. Governed is
    # true when the subtree holds a governed `-m weather.*` process (capture
    # children restored by training_window, for example). Largest first by
    # aggregate private bytes, any process type.
    $tree = @(Get-ProcessTreeRows $RootRow $AllProcesses)
    $spine = Get-AgentLeaseSpine $RootRow $tree $ProcessByPid $LeaseOwners
    $branches = New-Object System.Collections.Generic.List[object]
    foreach ($row in $tree) {
        $rowId = [uint32]$row.ProcessId
        if ($spine.ContainsKey($rowId)) { continue }
        if (-not $spine.ContainsKey([uint32]$row.ParentProcessId)) { continue }
        if (Test-AgentConsoleHost $row) { continue }
        $branches.Add([pscustomobject]@{
            Row = $row
            Bytes = [long](Get-ProcessTreePrivateBytes $row $AllProcesses $RuntimeByPid)
            Governed = (@(Get-ProcessTreeRows $row $AllProcesses | Where-Object { Test-GovernedWeatherProcess $_ }).Count -gt 0)
        })
    }
    return @($branches.ToArray() | Sort-Object @{ Expression = { $_.Bytes }; Descending = $true }, @{ Expression = { [uint32]$_.Row.ProcessId } })
}

function Get-AgentLeaseSpineHog($RootRow, $AllProcesses, $ProcessByPid, $RuntimeByPid, $LeaseOwners) {
    # The single spine process holding the most private bytes (agent roots and
    # console hosts excluded), with whether it is itself a lease owner. A hog that
    # only launched the owner may be stopped alone; the owner is orphaned but runs
    # on, and its finally blocks still run. An owner that is the hog is spared.
    $tree = @(Get-ProcessTreeRows $RootRow $AllProcesses)
    $spine = Get-AgentLeaseSpine $RootRow $tree $ProcessByPid $LeaseOwners
    $best = $null
    foreach ($row in $tree) {
        if (-not $spine.ContainsKey([uint32]$row.ProcessId)) { continue }
        if ($agentRootNames -contains ([string]$row.Name).ToLowerInvariant()) { continue }
        if (Test-AgentConsoleHost $row) { continue }
        $runtime = $RuntimeByPid[[uint32]$row.ProcessId]
        $bytes = if ($runtime) { [long]$runtime.PrivateMemorySize64 } else { [long]0 }
        if ($null -eq $best -or $bytes -gt $best.Bytes) {
            $best = [pscustomobject]@{ Row = $row; Bytes = $bytes; IsOwner = (Test-AgentLeaseOwnerRow $row $LeaseOwners) }
        }
    }
    return $best
}

function Get-AgentLeaseReliefPlan($RootRow, [long]$TreeBytes, $AllProcesses, $ProcessByPid, $RuntimeByPid, $LeaseOwners, [long]$Budget) {
    # How to bring a tree holding a live lease owner back under $Budget without
    # stopping the owner, its spine or a console host. Shared by the budget rule and
    # the commit emergency.
    #   branches: the subtrees off the spine can do it; stop them largest first until
    #             the tree is under budget. A subtree holding a governed weather
    #             process (capture children training_window restores) is eligible
    #             only when it alone reaches the budget.
    #   ancestor: the memory sits on the spine and its largest non-owner process
    #             holds enough that stopping it alone brings the spine under budget
    #             (Bytes > spine bytes - budget): stop that process alone.
    #   small:    the largest non-owner spine process cannot do that.
    #   owner:    the largest spine process is a lease owner (spared, CRITICAL).
    #   none:     nothing on the spine is stoppable.
    $eligible = @(Get-AgentLeaseBranches $RootRow $AllProcesses $ProcessByPid $RuntimeByPid $LeaseOwners |
        Where-Object { (-not $_.Governed) -or ([long]$_.Bytes -ge $Budget) })
    $offSpineBytes = [long]0
    foreach ($branch in $eligible) { $offSpineBytes += [long]$branch.Bytes }
    $spineBytes = $TreeBytes - $offSpineBytes
    if ($spineBytes -lt $Budget) {
        $chosen = New-Object System.Collections.Generic.List[object]
        $remaining = $TreeBytes
        $freed = [long]0
        foreach ($branch in $eligible) {
            if ($remaining -lt $Budget) { break }
            $chosen.Add($branch)
            $remaining -= [long]$branch.Bytes
            $freed += [long]$branch.Bytes
        }
        return [pscustomobject]@{ Kind = 'branches'; Branches = $chosen.ToArray(); Bytes = $freed; Hog = $null; SpineBytes = $spineBytes }
    }
    $hog = Get-AgentLeaseSpineHog $RootRow $AllProcesses $ProcessByPid $RuntimeByPid $LeaseOwners
    $kind = if ($null -eq $hog) { 'none' }
        elseif ($hog.IsOwner) { 'owner' }
        elseif ([long]$hog.Bytes -gt ($spineBytes - $Budget)) { 'ancestor' }
        else { 'small' }
    $hogBytes = if ($null -eq $hog) { [long]0 } else { [long]$hog.Bytes }
    return [pscustomobject]@{ Kind = $kind; Branches = @(); Bytes = $hogBytes; Hog = $hog; SpineBytes = $spineBytes }
}

# One-shot job-handle probe for single-process stops (compiled only when a single
# stop is about to run while a lease owner lives). Stopping a process closes its
# handles; if it held the last handle to a kill-on-close job containing the lease
# owner, the owner would die with it. Job MEMBERSHIP is not the hazard: every
# process an agent spawns may share the agent's own job, whose handle the agent
# root (never stopped) holds. So the probe asks whether the target process HOLDS a
# job handle whose job contains an owner: it enumerates the system handle table
# (SystemExtendedHandleInformation), duplicates each of the target's job handles
# with query access, and calls IsProcessInJob for each owner. 0 = no, 1 = yes,
# 2 = could not tell (access denied, duplicate or query failed).
$agentJobProbeSource = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
namespace WeatherGuard {
public static class JobHandleProbe {
    [DllImport("ntdll.dll")] static extern int NtQuerySystemInformation(int infoClass, IntPtr info, int length, out int returnLength);
    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool DuplicateHandle(IntPtr sourceProcess, IntPtr source, IntPtr targetProcess, out IntPtr target, uint access, bool inherit, uint options);
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll")] static extern uint GetCurrentProcessId();
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool IsProcessInJob(IntPtr process, IntPtr job, out bool result);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)] static extern IntPtr CreateJobObjectW(IntPtr attributes, string name);

    const uint ProcessDupHandle = 0x0040;
    const uint ProcessQueryLimited = 0x1000;
    const uint JobObjectQuery = 0x0004;
    const int SystemExtendedHandleInformation = 64;
    const int StatusInfoLengthMismatch = unchecked((int)0xC0000004);
    const int ErrorInvalidParameter = 87;

    public static int HolderJobContains(uint holderPid, uint[] targetPids) {
        IntPtr holder = OpenProcess(ProcessDupHandle, false, holderPid);
        if (holder == IntPtr.Zero) { return Marshal.GetLastWin32Error() == ErrorInvalidParameter ? 0 : 2; }
        List<IntPtr> targets = new List<IntPtr>();
        IntPtr probeJob = IntPtr.Zero;
        IntPtr buffer = IntPtr.Zero;
        try {
            foreach (uint targetPid in targetPids) {
                IntPtr target = OpenProcess(ProcessQueryLimited, false, targetPid);
                if (target == IntPtr.Zero) {
                    if (Marshal.GetLastWin32Error() == ErrorInvalidParameter) { continue; }
                    return 2;
                }
                targets.Add(target);
            }
            if (targets.Count == 0) { return 0; }
            probeJob = CreateJobObjectW(IntPtr.Zero, null);
            if (probeJob == IntPtr.Zero) { return 2; }
            int length = 1 << 22;
            for (int attempt = 0; ; attempt++) {
                buffer = Marshal.AllocHGlobal(length);
                int needed;
                int status = NtQuerySystemInformation(SystemExtendedHandleInformation, buffer, length, out needed);
                if (status == StatusInfoLengthMismatch && attempt < 6) {
                    Marshal.FreeHGlobal(buffer);
                    buffer = IntPtr.Zero;
                    length = Math.Max(length * 2, needed + (1 << 20));
                    continue;
                }
                if (status != 0) { return 2; }
                break;
            }
            long count = Marshal.ReadIntPtr(buffer).ToInt64();
            int pointer = IntPtr.Size;
            int entrySize = 3 * pointer + 16;
            long first = buffer.ToInt64() + 2 * pointer;
            uint self = GetCurrentProcessId();
            int jobType = -1;
            for (long index = 0; index < count && jobType < 0; index++) {
                IntPtr entry = new IntPtr(first + index * entrySize);
                if ((ulong)Marshal.ReadIntPtr(entry, pointer).ToInt64() != self) { continue; }
                if (Marshal.ReadIntPtr(entry, 2 * pointer) != probeJob) { continue; }
                jobType = (ushort)Marshal.ReadInt16(entry, 3 * pointer + 6);
            }
            if (jobType < 0) { return 2; }
            bool unknown = false;
            for (long index = 0; index < count; index++) {
                IntPtr entry = new IntPtr(first + index * entrySize);
                if ((ulong)Marshal.ReadIntPtr(entry, pointer).ToInt64() != holderPid) { continue; }
                if ((ushort)Marshal.ReadInt16(entry, 3 * pointer + 6) != jobType) { continue; }
                IntPtr job;
                if (!DuplicateHandle(holder, Marshal.ReadIntPtr(entry, 2 * pointer), GetCurrentProcess(), out job, JobObjectQuery, false, 0)) {
                    unknown = true;
                    continue;
                }
                try {
                    foreach (IntPtr target in targets) {
                        bool inJob;
                        if (!IsProcessInJob(target, job, out inJob)) { unknown = true; continue; }
                        if (inJob) { return 1; }
                    }
                }
                finally { CloseHandle(job); }
            }
            return unknown ? 2 : 0;
        }
        finally {
            if (buffer != IntPtr.Zero) { Marshal.FreeHGlobal(buffer); }
            if (probeJob != IntPtr.Zero) { CloseHandle(probeJob); }
            foreach (IntPtr target in targets) { CloseHandle(target); }
            CloseHandle(holder);
        }
    }
}
}
'@

function Test-AgentHolderJobContainsOwner([uint32]$HolderPid, $OwnerRows) {
    # 0 = safe to stop alone, 1 = it holds a job handle containing an owner, 2 = unknown.
    $errorMark = $Error.Count
    try {
        $ownerIds = [uint32[]]@($OwnerRows | ForEach-Object { [uint32]$_.ProcessId })
        if ($ownerIds.Count -eq 0) { return 0 }
        # A process that no longer exists holds nothing (and is not stopped below).
        $exists = $true
        try { $null = [System.Diagnostics.Process]::GetProcessById([int]$HolderPid) } catch { $exists = $false }
        if (-not $exists) { return 0 }
        if (-not ('WeatherGuard.JobHandleProbe' -as [type])) {
            Add-Type -TypeDefinition $agentJobProbeSource -Language CSharp -ErrorAction Stop
        }
        return [int][WeatherGuard.JobHandleProbe]::HolderJobContains($HolderPid, $ownerIds)
    }
    catch {
        Write-GuardLog "WARNING" ("job-handle probe for pid {0} failed: {1}" -f $HolderPid, $_.Exception.Message)
        return 2
    }
    finally {
        while ($Error.Count -gt $errorMark) { $Error.RemoveAt(0) }
    }
}

function Get-AgentToolRoot($ProcessRow, $ProcessByPid) {
    # The direct child of the agent root above the row. A row with no agent root
    # gets the top of its verified ancestry when that process is an orphaned lease
    # tree root ($orphanLeaseRoots, null-safe for harnesses that extract this
    # function alone): stopping a hog that launched a lease owner orphans the
    # owner, and its tree must stay under the agent rules.
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
        $parent = if ($ProcessByPid.ContainsKey($parentId)) { $ProcessByPid[$parentId] } else { $null }
        if ($null -eq $parent -or ([datetime]$parent.CreationDate).ToUniversalTime() -gt ([datetime]$current.CreationDate).ToUniversalTime()) {
            if (($null -ne $orphanLeaseRoots) -and $orphanLeaseRoots.ContainsKey([uint32]$current.ProcessId)) {
                $orphanRoot = $orphanLeaseRoots[[uint32]$current.ProcessId]
                if (([datetime]$orphanRoot.CreationDate).ToUniversalTime() -eq ([datetime]$current.CreationDate).ToUniversalTime()) { return $current }
            }
            return $null
        }
        $current = $parent
    }
    return $null
}

function Get-VerifiedTopAncestor($ProcessRow, $ProcessByPid) {
    # The highest process reachable from the row through parents that exist and are
    # older than their child (PID reuse closes the chain).
    $current = $ProcessRow
    for ($depth = 0; $depth -lt 64; $depth++) {
        $parentId = [uint32]$current.ParentProcessId
        if (-not $ProcessByPid.ContainsKey($parentId)) { return $current }
        $parent = $ProcessByPid[$parentId]
        if (([datetime]$parent.CreationDate).ToUniversalTime() -gt ([datetime]$current.CreationDate).ToUniversalTime()) { return $current }
        if ($agentRootNames -contains ([string]$parent.Name).ToLowerInvariant()) { return $current }
        $current = $parent
    }
    return $current
}

function Read-GuardState([string]$Path, [datetime]$NowUtc) {
    # The guard's memory between one-minute runs: the consecutive runs on which a
    # lease record was unreadable, and the lease owners last seen inside an agent
    # tree (PID plus creation instant, so a reused PID never matches).
    #
    # Fail-safe (review delta (a)): losing the memory only ever spares. An empty
    # memory restarts the unreadable streak at 1 (spared again) and attributes no
    # orphaned tree (no agent rule reaches it), so no read outcome can make the
    # guard kill something it would otherwise have spared.
    #   absent     no file (first run): empty, not degraded.
    #   stale      older than five minutes (or dated in the future): empty.
    #   ok         the remembered owners are kept; the streak carries over only
    #              when the record is at most 90 seconds old, i.e. it was written by
    #              the run one minute ago. An older record means at least one run in
    #              between failed to write its own state, so its streak may be
    #              higher than the truth and restarts at 0 instead.
    #   unreadable the file exists but cannot be read (sharing violation, access
    #              denied): empty and degraded, and this run does not overwrite the
    #              file, so the last good record survives for the next run.
    #   invalid    the file reads but is not a v1 state record: empty and degraded;
    #              this run's write replaces it.
    $result = [pscustomobject]@{ UnreadableStreak = 0; LeaseOwnerTrees = @(); Status = 'absent'; Error = $null }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $result }
    $errorMark = $Error.Count
    try {
        $text = [IO.File]::ReadAllText($Path, (New-Object System.Text.UTF8Encoding($false)))
    }
    catch {
        while ($Error.Count -gt $errorMark) { $Error.RemoveAt(0) }
        $result.Status = 'unreadable'
        $result.Error = $_.Exception.Message
        return $result
    }
    try {
        $state = $text.TrimStart([char]0xFEFF) | ConvertFrom-Json
        if ([string]$state.schema_version -cne 'memory_commit_guard_state_v1') { throw ("schema_version '{0}'" -f [string]$state.schema_version) }
        $updated = [datetime]::Parse([string]$state.updated_at_utc, [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()
        $age = ($NowUtc - $updated).TotalSeconds
        $trees = @(@($state.lease_owner_trees) | Where-Object { $null -ne $_ } | ForEach-Object {
            [pscustomobject]@{ Pid = [uint32]$_.pid; CreationTicks = [long]$_.creation_utc_ticks }
        })
        $streak = [int]$state.lease_records_unreadable_streak
    }
    catch {
        while ($Error.Count -gt $errorMark) { $Error.RemoveAt(0) }
        $result.Status = 'invalid'
        $result.Error = $_.Exception.Message
        return $result
    }
    if ($age -lt -60.0 -or $age -gt 300.0) {
        $result.Status = 'stale'
        return $result
    }
    $result.Status = 'ok'
    $result.LeaseOwnerTrees = $trees
    if ($age -le 90.0) { $result.UnreadableStreak = [math]::Max(0, $streak) }
    return $result
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
    [bool]$AllowWeatherDescendants = $false,
    # The one lease owner (by PID, the tree root) a hard-ceiling stop may end; every
    # other owner in the tree stays protected. 0: none.
    [uint32]$CeilingOwnerPid = 0
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
    # Last line, whatever the caller decided: never a live lease owner, and while any
    # owner lives (or a lease record is unreadable, so an owner may be live) never a
    # console host, whose end takes every process attached to its console. Both are
    # null-safe so a harness that extracts this function alone still runs it.
    $protectOwners = ($null -ne $leaseOwners) -and (@($leaseOwners).Count -gt 0)
    $protectConsoles = (($null -ne $liveLeaseOwnerRows) -and (@($liveLeaseOwnerRows).Count -gt 0)) -or ($leaseRecordsUnreadable -eq $true)
    Write-GuardLog "ACTION" ("{0}; terminating verified process tree root pid {1} members {2}" -f $Reason, $RootRow.ProcessId, $tree.Count)
    foreach ($row in $ordered) {
        $memberId = [uint32]$row.ProcessId
        if ($memberId -eq [uint32]$PID) {
            Write-GuardLog "CRITICAL" ("refusing to terminate the guard's own process pid {0}" -f $memberId)
            $ok = $false
            continue
        }
        if ($protectOwners -and -not ($CeilingOwnerPid -ne 0 -and $memberId -eq $CeilingOwnerPid) -and (Test-AgentLeaseOwnerRow $row $leaseOwners)) {
            Write-GuardLog "CRITICAL" ("refusing to terminate heavy-workload lease owner pid {0} inside tree pid {1}" -f $memberId, $RootRow.ProcessId)
            $ok = $false
            continue
        }
        if ($protectConsoles -and (([string]$row.Name).ToLowerInvariant() -in @('conhost.exe', 'openconsole.exe'))) {
            Write-GuardLog "WARNING" ("left console host pid {0} running: a heavy-workload lease owner may be attached to it" -f $memberId)
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

function Test-LeaseOwnerHardCeiling([long]$OwnerBytes) {
    # Past this, sparing a lease owner risks the host (review M2): commit at the hard
    # ceiling, or the owner process itself holding twice the private budget.
    return ($commitPercent -ge $HardCeilingPercent) -or ($OwnerBytes -ge (2 * $MinKillPrivateBytes))
}

function Stop-VerifiedSingleProcess($ProcessRow, [string]$Reason) {
    # One process only, never its subtree: used for a memory hog that launched a
    # live lease owner, so the owner (orphaned, still running) keeps its finally.
    $targetId = [uint32]$ProcessRow.ProcessId
    if ($targetId -eq [uint32]$PID) {
        Write-GuardLog "CRITICAL" ("refusing to terminate the guard's own process pid {0}" -f $targetId)
        return $false
    }
    if ($agentRootNames -contains ([string]$ProcessRow.Name).ToLowerInvariant() -or (Test-AgentConsoleHost $ProcessRow)) {
        Write-GuardLog "CRITICAL" ("refusing single-process termination of pid {0} ({1})" -f $targetId, $ProcessRow.Name)
        return $false
    }
    if ((@($leaseOwners).Count -gt 0) -and (Test-AgentLeaseOwnerRow $ProcessRow $leaseOwners)) {
        Write-GuardLog "CRITICAL" ("refusing to terminate heavy-workload lease owner pid {0}" -f $targetId)
        return $false
    }
    $current = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $targetId) -ErrorAction SilentlyContinue
    if (-not $current) { return $true }
    if (([datetime]$current.CreationDate).ToUniversalTime() -ne ([datetime]$ProcessRow.CreationDate).ToUniversalTime()) {
        Write-GuardLog "ERROR" ("pid {0} creation identity changed before termination" -f $targetId)
        return $false
    }
    if (@($liveLeaseOwnerRows).Count -gt 0) {
        # Stopping this process closes its handles: refuse when it holds a job handle
        # whose job contains a live lease owner, or when that cannot be ruled out.
        $jobVerdict = Test-AgentHolderJobContainsOwner $targetId $liveLeaseOwnerRows
        if ($jobVerdict -ne 0) {
            $why = if ($jobVerdict -eq 1) { "it holds a handle to a job that contains a live heavy-workload lease owner" } else { "whether it holds a job handle containing a live heavy-workload lease owner could not be determined" }
            Write-GuardLog "CRITICAL" ("refusing single-process termination of pid {0}: {1}; manual attention required" -f $targetId, $why)
            return $false
        }
    }
    Write-GuardLog "ACTION" ("{0}; terminating verified single process pid {1} (its subtree is left running)" -f $Reason, $targetId)
    try {
        Stop-Process -Id $targetId -Force -Confirm:$false -ErrorAction Stop
    }
    catch {
        Write-GuardLog "ERROR" ("failed to terminate pid {0}: {1}" -f $targetId, $_.Exception.Message)
        return $false
    }
    return $true
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
    guard_state_read = 'not_read'
    guard_state_degraded = $false
    guard_state_written = $false
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
$heavyRowIds = @{}
$heavyCandidateRows = @($allProcesses | Where-Object { Test-AgentHeavyProcess $_ })
$orphanLeaseRoots = @{}
function Add-AgentHeavyRows {
    # Runs again once orphaned lease tree roots are known; the hashtables are shared.
    foreach ($row in $heavyCandidateRows) {
        if ($heavyRowIds.ContainsKey([uint32]$row.ProcessId)) { continue }
        $toolRoot = Get-AgentToolRoot $row $processByPid
        if (-not $toolRoot) { continue }
        # The grace runs on the tool root's age, not the heavy child's: a loop of short
        # children (foreach { python -m pytest $f }) under one old shell is still seen.
        $ageSeconds = ($utcNow - ([datetime]$toolRoot.CreationDate).ToUniversalTime()).TotalSeconds
        if ($ageSeconds -lt $AgentWorkloadGraceSeconds) { continue }
        $key = "{0}|{1}" -f $toolRoot.ProcessId, ([datetime]$toolRoot.CreationDate).ToUniversalTime().Ticks
        if (-not $heavyToolRoots.ContainsKey($key)) { $heavyToolRoots[$key] = $toolRoot }
        if (-not $heavyRowsByKey.ContainsKey($key)) { $heavyRowsByKey[$key] = New-Object System.Collections.Generic.List[object] }
        $heavyRowsByKey[$key].Add($row)
        $heavyRowIds[[uint32]$row.ProcessId] = $true
    }
}
Add-AgentHeavyRows

# Lease owners remembered from earlier runs (Read-GuardState) that are still alive
# under the same creation instant.
$guardState = Read-GuardState $guardStatePath $utcNow
$status.guard_state_read = $guardState.Status
if ($guardState.Status -in @('unreadable', 'invalid')) {
    $status.guard_state_degraded = $true
    Write-GuardLog "ERROR" ("guard state {0} is {1} ({2}); this run remembers nothing, which only spares: the unreadable-lease count restarts and no orphaned lease tree is attributed{3}" -f `
        $guardStatePath, $guardState.Status, $guardState.Error, $(if ($guardState.Status -eq 'unreadable') { '; the file is left in place for the next run' } else { '' }))
}
$rememberedOwnerRows = @(foreach ($remembered in @($guardState.LeaseOwnerTrees)) {
    if (-not $processByPid.ContainsKey([uint32]$remembered.Pid)) { continue }
    $row = $processByPid[[uint32]$remembered.Pid]
    if (([datetime]$row.CreationDate).ToUniversalTime().Ticks -ne [long]$remembered.CreationTicks) { continue }
    $row
})

# Lease admission. A heavy member is admitted when a live heavy-workload lease
# owner (workstation_heavy.ps1, the bounded suite, training_window, a one-off lease
# wrapper) is the member, an ancestor below the agent root, or inside the member's
# own subtree, except that a heavy powershell/pwsh/cmd line above the owner is never
# admitted by it (review m4; Test-AgentLeaseAdmitted). A tool tree whose
# every heavy member is admitted is never a window or concurrency target; that
# lease already enforces the window and serialization.
# A tool tree that CONTAINS a live lease owner is never terminated as a whole by
# any rule here, the private-byte budget included: the owner's finally blocks
# (training_window re-enabling capture supervisors, lease release) must run, so
# only heavy member subtrees that do not contain the owner are stopped.
#
# Every owner is protected; only owners inside their own policy window (plus its
# teardown grace) admit work. Past it, admitted work is no longer exempt: the
# owner's heavy descendants are stopped like any unadmitted member, an owner
# ancestor that is itself heavy is stopped alone, and only the owner is spared.
$unadmittedRowsByKey = @{}
$admittedRootKeys = @{}
$ownerRootKeys = @{}
$leaseOwners = @()
$admittingOwners = @()
$liveLeaseOwnerRows = @()
$leaseRecordsUnreadable = $false
$leasesRead = $false
$unreadableStreak = 0
# Read for the commit-emergency path too, which must spare lease owners as well,
# and whenever a remembered lease owner lives (its tree may have been orphaned).
if ($heavyToolRoots.Count -gt 0 -or $commitPercent -ge $ActPercent -or $rememberedOwnerRows.Count -gt 0) {
    $leasesRead = $true
    $hostScope = Get-GuardLeaseHostScope $RepoRoot $ExpectedExecutionHostId
    $leaseState = Get-AdmittedLeaseOwners $RepoRoot $HeavyWorkloadStateRoot $utcNow $hostScope
    $leaseOwners = @($leaseState.Owners)
    $admittingOwners = @($leaseOwners | Where-Object { Test-AgentLeaseOwnerInWindow $_ $minuteOfDay })
    if ($leaseOwners.Count -gt 0) {
        $liveLeaseOwnerRows = @($allProcesses | Where-Object { Test-AgentLeaseOwnerRow $_ $leaseOwners })
    }
    foreach ($downgraded in @($leaseOwners | Where-Object { [string]$_.RecordWindow -cne [string]$_.Window })) {
        if (@($liveLeaseOwnerRows | Where-Object { [uint32]$_.ProcessId -eq [uint32]$downgraded.Pid }).Count -eq 0) { continue }
        Write-GuardLog "WARNING" ("heavy-workload lease owner pid {0} names the {1} profile, which this host does not honour ({2}); the agent_heavy window applies" -f `
            $downgraded.Pid, $downgraded.RecordWindow, $hostScope.Why)
    }
    if (@($leaseState.Unreadable).Count -gt 0) {
        # Fail toward sparing: a lease that cannot be read may be admitting this work,
        # but only for two consecutive runs. A lock rewritten empty or with garbage
        # every minute must not disable the window, concurrency and budget rules.
        $unreadableStreak = 1 + [int]$guardState.UnreadableStreak
        if ($unreadableStreak -le 2) {
            $leaseRecordsUnreadable = $true
            Write-GuardLog "WARNING" ("heavy-workload lease record(s) unreadable ({0}; run {1} in a row); skipping agent window and concurrency kills this run, budget kills stop heavy members only" -f `
                (@($leaseState.Unreadable) -join ", "), $unreadableStreak)
        }
        else {
            Write-GuardLog "WARNING" ("heavy-workload lease record(s) unreadable ({0}) for {1} runs in a row; no longer sparing on their account, every rule applies" -f `
                (@($leaseState.Unreadable) -join ", "), $unreadableStreak)
        }
    }
}
# Orphaned lease trees (review M1): a remembered owner that is still a live lease
# owner but no longer sits below an agent root (a hog that launched it was stopped
# alone) makes the top of its verified ancestry a tool root of its own.
foreach ($ownerRow in $rememberedOwnerRows) {
    if (-not (Test-AgentLeaseOwnerRow $ownerRow $leaseOwners)) { continue }
    if ($null -ne (Get-AgentToolRoot $ownerRow $processByPid)) { continue }
    $orphanTop = Get-VerifiedTopAncestor $ownerRow $processByPid
    $orphanLeaseRoots[[uint32]$orphanTop.ProcessId] = $orphanTop
    Write-GuardLog "INFO" ("heavy-workload lease owner pid {0} lost its agent root; tree root pid {1} stays under the agent rules" -f $ownerRow.ProcessId, $orphanTop.ProcessId)
}
if ($orphanLeaseRoots.Count -gt 0) { Add-AgentHeavyRows }
$status.agent_heavy_lease_unreadable_streak = $unreadableStreak
$status.agent_heavy_orphaned_lease_tree_count = $orphanLeaseRoots.Count
foreach ($ownerRow in $liveLeaseOwnerRows) {
    if (Test-AgentLeaseOwnerRow $ownerRow $admittingOwners) { continue }
    $ownerToolRoot = Get-AgentToolRoot $ownerRow $processByPid
    if (-not $ownerToolRoot) { continue }
    $ownerKey = "{0}|{1}" -f $ownerToolRoot.ProcessId, ([datetime]$ownerToolRoot.CreationDate).ToUniversalTime().Ticks
    if (-not $heavyToolRoots.ContainsKey($ownerKey)) { continue }
    Write-GuardLog "CRITICAL" ("heavy-workload lease owner pid {0} is past its policy window; its heavy work is no longer admitted and is stopped, the owner alone is spared; manual attention required" -f $ownerRow.ProcessId)
}
foreach ($entry in $heavyToolRoots.GetEnumerator()) {
    $unadmitted = New-Object System.Collections.Generic.List[object]
    foreach ($member in $heavyRowsByKey[$entry.Key]) {
        if (-not (Test-AgentLeaseAdmitted $member $processByPid $allProcesses $admittingOwners)) { $unadmitted.Add($member) }
    }
    $unadmittedRowsByKey[$entry.Key] = $unadmitted
    if ($unadmitted.Count -eq 0) { $admittedRootKeys[$entry.Key] = $true }
    if (Test-AgentTreeHasLeaseOwner $entry.Value $allProcesses $leaseOwners) { $ownerRootKeys[$entry.Key] = $true }
}
$agentHeavyRows = @($heavyCandidateRows | Where-Object { $null -ne (Get-AgentToolRoot $_ $processByPid) })
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
    # Each tree holding a live lease takes exactly one slot first for its admitted
    # work. Its unadmitted heavy members, if any, then compete with the other trees
    # for the remaining slots, oldest first; a losing leased tree loses only those
    # members (the kill loop below never stops a leased tree as a whole).
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
        "agent tool tree exceeds the $([math]::Round($MinKillPrivateBytes / 1MB, 0)) MB private budget (observed ${treePrivateMB} MB)"
    } elseif ($agentHeavyWindowAllowed) {
        "agent heavy-workload concurrency exceeds $MaxConcurrentAgentHeavyWorkloads"
    } else {
        "agent heavy workload is outside the 00:30-09:00 host window"
    }
    if ($overBudget -and $ownerRootKeys.ContainsKey($entry.Key)) {
        # Never the whole tree, never an owner (Get-AgentLeaseReliefPlan): subtrees
        # off the owner's spine largest first while they can bring the tree under
        # budget (any process type, so the real hog dies, not an innocent heavy
        # chunk), else the spine's largest non-owner process alone when stopping it
        # brings the spine under budget, else a WARNING or, for an owner hog, CRITICAL.
        $plan = Get-AgentLeaseReliefPlan $target ([long]$agentTreeBytes[$entry.Key]) $allProcesses $processByPid $runtimeByPid $leaseOwners $MinKillPrivateBytes
        if ($plan.Kind -ceq 'branches') {
            foreach ($branch in @($plan.Branches)) {
                if (Stop-VerifiedProcessTree $branch.Row $allProcesses ("{0} (largest subtree off the lease owner's spine; the owner is spared)" -f $reason) $true) {
                    $guardActions.Add("killed_agent_member_pid_$($branch.Row.ProcessId)")
                    $terminationPerformed = $true
                } else {
                    $guardActions.Add("kill_failed_agent_member_pid_$($branch.Row.ProcessId)")
                }
            }
        }
        elseif ($plan.Kind -ceq 'owner' -and (Test-LeaseOwnerHardCeiling ([long]$plan.Hog.Bytes))) {
            # Review M2: an owner growing in-process is stopped past the hard ceiling.
            Write-GuardLog "CRITICAL" ("{0}; heavy-workload lease owner pid {1} itself holds {2} MB at commit {3}%, past the hard ceiling ({4}% or {5} MB); stopping the owner and its subtree, its finally blocks are lost; manual attention required" -f `
                $reason, $plan.Hog.Row.ProcessId, [math]::Round([long]$plan.Hog.Bytes / 1MB, 0), [math]::Round($commitPercent, 1), $HardCeilingPercent, [math]::Round(2 * $MinKillPrivateBytes / 1MB, 0))
            if (Stop-VerifiedProcessTree $plan.Hog.Row $allProcesses ("{0} (lease owner past the hard ceiling)" -f $reason) $true ([uint32]$plan.Hog.Row.ProcessId)) {
                $guardActions.Add("killed_lease_owner_pid_$($plan.Hog.Row.ProcessId)")
                $terminationPerformed = $true
            } else {
                $guardActions.Add("kill_failed_lease_owner_pid_$($plan.Hog.Row.ProcessId)")
            }
        }
        elseif ($plan.Kind -ceq 'owner') {
            Write-GuardLog "CRITICAL" ("{0}; heavy-workload lease owner pid {1} itself holds {2} MB and is spared below the hard ceiling; manual attention required" -f `
                $reason, $plan.Hog.Row.ProcessId, [math]::Round([long]$plan.Hog.Bytes / 1MB, 0))
        }
        elseif ($plan.Kind -ceq 'ancestor') {
            if (Stop-VerifiedSingleProcess $plan.Hog.Row ("{0} (largest process on the lease owner's ancestry; the owner is orphaned, not stopped)" -f $reason)) {
                $guardActions.Add("killed_agent_ancestor_pid_$($plan.Hog.Row.ProcessId)")
                $terminationPerformed = $true
            } else {
                $guardActions.Add("kill_failed_agent_ancestor_pid_$($plan.Hog.Row.ProcessId)")
            }
        }
        elseif ($plan.Kind -ceq 'small') {
            Write-GuardLog "WARNING" ("{0}; tool tree pid {1} holds a heavy-workload lease and its largest non-owner spine process pid {2} ({3} MB) cannot bring the {4} MB spine under budget alone; nothing stopped" -f `
                $reason, $target.ProcessId, $plan.Hog.Row.ProcessId, [math]::Round([long]$plan.Hog.Bytes / 1MB, 0), [math]::Round([long]$plan.SpineBytes / 1MB, 0))
        }
        else {
            Write-GuardLog "WARNING" ("{0}; tool tree pid {1} holds a heavy-workload lease and has no stoppable process" -f $reason, $target.ProcessId)
        }
        continue
    }
    if ($ownerRootKeys.ContainsKey($entry.Key) -or $leaseRecordsUnreadable) {
        # Never the whole tree: stop heavy member subtrees that hold no lease owner.
        # Over budget here means the lease records are unreadable, so owners are
        # unknown: every heavy member is a candidate; otherwise only unadmitted ones.
        # A member whose subtree holds an owner is a heavy shell line on the owner's
        # spine (never admitted by the owner below it), or the owner itself
        # past its policy window: the owner is spared (CRITICAL), a heavy owner
        # ancestor is stopped alone (the owner runs on, orphaned, and its tree stays
        # attributed through the guard state file), and the owner's heavy
        # descendants are members of their own.
        $memberReason = if ($overBudget) { "{0} (heavy member subtree; lease records unreadable)" -f $reason } else { "{0} (unadmitted member of a leased tool tree)" -f $reason }
        # .ToArray(): @() over a generic List throws in Windows PowerShell 5.1.
        $candidateMembers = if ($overBudget) { $heavyRowsByKey[$entry.Key].ToArray() } else { $unadmittedRowsByKey[$entry.Key].ToArray() }
        $coveredMemberIds = @{}
        foreach ($member in @($candidateMembers |
                Sort-Object @{ Expression = { ([datetime]$_.CreationDate).ToUniversalTime() } }, ProcessId)) {
            if ($coveredMemberIds.ContainsKey([uint32]$member.ProcessId)) { continue }
            $memberTree = @(Get-ProcessTreeRows $member $allProcesses)
            if (@($memberTree | Where-Object { Test-AgentLeaseOwnerRow $_ $leaseOwners }).Count -gt 0) {
                if (Test-AgentLeaseOwnerRow $member $leaseOwners) {
                    Write-GuardLog "CRITICAL" ("{0}; heavy-workload lease owner pid {1} is spared; manual attention required" -f $reason, $member.ProcessId)
                }
                elseif (Stop-VerifiedSingleProcess $member ("{0} (heavy ancestor of a heavy-workload lease owner; the owner is orphaned, not stopped)" -f $reason)) {
                    $guardActions.Add("killed_agent_ancestor_pid_$($member.ProcessId)")
                    $terminationPerformed = $true
                }
                else {
                    $guardActions.Add("kill_failed_agent_ancestor_pid_$($member.ProcessId)")
                }
                continue
            }
            foreach ($covered in $memberTree) { $coveredMemberIds[[uint32]$covered.ProcessId] = $true }
            if (Stop-VerifiedProcessTree $member $allProcesses $memberReason $true) {
                $guardActions.Add("killed_agent_member_pid_$($member.ProcessId)")
                $terminationPerformed = $true
            } else {
                $guardActions.Add("kill_failed_agent_member_pid_$($member.ProcessId)")
            }
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
        # A python whose subtree holds a live lease owner (it launched the lease
        # wrapper) is stopped alone, never with its subtree: the owner is orphaned
        # but keeps running its finally. A python that is itself an owner is spared.
        $single = $false
        $ceilingOwner = $false
        if (Test-AgentTreeHasLeaseOwner $_ $allProcesses $leaseOwners) {
            if (Test-AgentLeaseOwnerRow $_ $leaseOwners) {
                if (-not (Test-LeaseOwnerHardCeiling ([long]$proc.PrivateMemorySize64))) {
                    Write-GuardLog "CRITICAL" ("commit emergency: python pid {0} is a heavy-workload lease owner holding {1} MB; spared below the hard ceiling" -f $_.ProcessId, [math]::Round($proc.PrivateMemorySize64 / 1MB, 0))
                    return
                }
                $ceilingOwner = $true
            }
            else { $single = $true }
        }
        [pscustomobject]@{
            Kind = if ($ceilingOwner) { "lease_owner" } elseif ($single) { "python_ancestor" } else { "python" }
            Single = $single
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
    # Orphaned lease tree roots (review M1) are judged like agent trees.
    foreach ($root in @(@($allProcesses | Where-Object { $agentRootNames -contains ([string]$_.Name).ToLowerInvariant() }) + @($orphanLeaseRoots.Values))) {
        $tree = @(Get-ProcessTreeRows $root $allProcesses)
        $privateBytes = [long]0
        foreach ($member in $tree) {
            $runtime = $runtimeByPid[[uint32]$member.ProcessId]
            if ($runtime) { $privateBytes += [long]$runtime.PrivateMemorySize64 }
        }
        if ($privateBytes -lt $MinKillPrivateBytes) { continue }
        if (Test-AgentTreeHasLeaseOwner $root $allProcesses $leaseOwners) {
            # Never the agent root, a lease owner or a console host. Like the budget
            # rule (Get-AgentLeaseReliefPlan): the subtrees off the owner's spine,
            # largest first, until the tree is under budget; else the spine's largest
            # non-owner process alone when that brings the spine under budget or it
            # alone reaches the budget. The candidate ranks by the whole tree's bytes,
            # as an unleased agent tree would.
            $plan = Get-AgentLeaseReliefPlan $root $privateBytes $allProcesses $processByPid $runtimeByPid $leaseOwners $MinKillPrivateBytes
            if ($plan.Kind -ceq 'branches' -and @($plan.Branches).Count -gt 0) {
                $candidates += [pscustomobject]@{
                    Kind = "agent_branch"
                    Single = $false
                    Branches = @($plan.Branches)
                    Id = $root.ProcessId
                    CreationDate = $root.CreationDate
                    RootRow = $root
                    PrivateBytes = $privateBytes
                    PrivateMB = [math]::Round($privateBytes / 1MB, 0)
                    CommandLine = "subtrees off a lease owner's spine in agent tree pid $($root.ProcessId)"
                }
                continue
            }
            if ($plan.Kind -ceq 'owner' -and (Test-LeaseOwnerHardCeiling ([long]$plan.Hog.Bytes))) {
                $candidates += [pscustomobject]@{
                    Kind = "lease_owner"
                    Single = $false
                    Branches = @()
                    Id = $plan.Hog.Row.ProcessId
                    CreationDate = $plan.Hog.Row.CreationDate
                    RootRow = $plan.Hog.Row
                    PrivateBytes = $privateBytes
                    PrivateMB = [math]::Round($privateBytes / 1MB, 0)
                    CommandLine = "lease owner past the hard ceiling in tree pid $($root.ProcessId)"
                }
                continue
            }
            if ($plan.Kind -ceq 'owner') {
                Write-GuardLog "CRITICAL" ("commit emergency: heavy-workload lease owner pid {0} holds {1} MB; spared below the hard ceiling" -f $plan.Hog.Row.ProcessId, [math]::Round([long]$plan.Hog.Bytes / 1MB, 0))
                continue
            }
            if ($plan.Kind -ceq 'ancestor' -or ($plan.Kind -ceq 'small' -and [long]$plan.Hog.Bytes -ge $MinKillPrivateBytes)) {
                $candidates += [pscustomobject]@{
                    Kind = "agent_ancestor"
                    Single = $true
                    Branches = @()
                    Id = $plan.Hog.Row.ProcessId
                    CreationDate = $plan.Hog.Row.CreationDate
                    RootRow = $plan.Hog.Row
                    PrivateBytes = [long]$plan.Hog.Bytes
                    PrivateMB = [math]::Round([long]$plan.Hog.Bytes / 1MB, 0)
                    CommandLine = "process on a lease owner's ancestry in agent tree pid $($root.ProcessId)"
                }
                continue
            }
            Write-GuardLog "WARNING" ("commit emergency: agent tree pid {0} holds a heavy-workload lease and nothing off or on the owner's spine can be stopped to relieve it" -f $root.ProcessId)
            continue
        }
        $candidates += [pscustomobject]@{
            Kind = "agent_tree"
            Single = $false
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
        $allowWeather = $target.Kind -in @("agent_tree", "agent_branch", "lease_owner")
        if ($target.Kind -ceq "agent_branch") {
            # Each subtree off the owner's spine, largest first, as planned.
            foreach ($branch in @($target.Branches)) {
                $branchReason = "{0} (subtree pid {1} off a lease owner's spine, {2} MB; the owner is spared)" -f `
                    $reason, $branch.Row.ProcessId, [math]::Round([long]$branch.Bytes / 1MB, 0)
                if (Stop-VerifiedProcessTree $branch.Row $allProcesses $branchReason $true) {
                    $guardActions.Add("killed_agent_branch_pid_$($branch.Row.ProcessId)")
                    $terminationPerformed = $true
                }
                else {
                    $guardActions.Add("kill_failed_agent_branch_pid_$($branch.Row.ProcessId)")
                }
            }
        }
        else {
            $stopped = if ($target.Kind -ceq "lease_owner") {
                Write-GuardLog "CRITICAL" ("{0}: heavy-workload lease owner pid {1} is past the hard ceiling ({2}% commit or {3} MB owner); stopping the owner and its subtree, its finally blocks are lost; manual attention required" -f `
                    $reason, $target.Id, $HardCeilingPercent, [math]::Round(2 * $MinKillPrivateBytes / 1MB, 0))
                Stop-VerifiedProcessTree $target.RootRow $allProcesses ("{0} (lease owner past the hard ceiling)" -f $reason) $true ([uint32]$target.Id)
            } elseif ($target.Single) {
                Stop-VerifiedSingleProcess $target.RootRow ("{0} (single process; the lease owner it launched is left running)" -f $reason)
            } else {
                Stop-VerifiedProcessTree $target.RootRow $allProcesses $reason $allowWeather
            }
            if ($stopped) {
                $guardActions.Add("killed_$($target.Kind)_pid_$($target.Id)")
                $terminationPerformed = $true
            }
            else {
                $guardActions.Add("kill_failed_$($target.Kind)_pid_$($target.Id)")
            }
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

# Remember the lease owners seen inside an agent tree this run (and keep the ones
# already remembered while the records could not be read or were not read), so a
# tree orphaned by a single-process stop stays attributed on later runs.
$rememberRows = New-Object System.Collections.Generic.List[object]
foreach ($ownerRow in $liveLeaseOwnerRows) {
    if ($null -ne (Get-AgentToolRoot $ownerRow $processByPid)) { $rememberRows.Add($ownerRow) }
}
if (-not $leasesRead -or $unreadableStreak -gt 0) {
    foreach ($ownerRow in $rememberedOwnerRows) { $rememberRows.Add($ownerRow) }
}
$rememberedIds = @{}
$rememberedTrees = New-Object System.Collections.Generic.List[object]
foreach ($ownerRow in $rememberRows) {
    if ($rememberedIds.ContainsKey([uint32]$ownerRow.ProcessId) -or $rememberedTrees.Count -ge 64) { continue }
    $rememberedIds[[uint32]$ownerRow.ProcessId] = $true
    $rememberedTrees.Add([ordered]@{ pid = [uint32]$ownerRow.ProcessId; creation_utc_ticks = ([datetime]$ownerRow.CreationDate).ToUniversalTime().Ticks })
}
$guardStateRecord = [ordered]@{
    schema_version = 'memory_commit_guard_state_v1'
    updated_at_utc = $utcNow.ToString('o')
    lease_records_unreadable_streak = $unreadableStreak
    lease_owner_trees = $rememberedTrees.ToArray()
}
# A failed write leaves the previous record in place (Read-GuardState: its owners
# stay usable for five minutes, its streak is not carried past 90 seconds) and marks
# this run degraded. An unreadable record is not overwritten, so it survives.
if ($guardState.Status -eq 'unreadable') {
    $status.guard_state_written = $false
}
else {
    $guardStateTempPath = "{0}.{1}.tmp" -f $guardStatePath, [guid]::NewGuid().ToString("N")
    $errorMark = $Error.Count
    try {
        ConvertTo-Json -InputObject $guardStateRecord -Depth 4 | Out-File -LiteralPath $guardStateTempPath -Encoding utf8 -ErrorAction Stop
        Move-Item -LiteralPath $guardStateTempPath -Destination $guardStatePath -Force -ErrorAction Stop
        $status.guard_state_written = $true
    }
    catch {
        while ($Error.Count -gt $errorMark) { $Error.RemoveAt(0) }
        $status.guard_state_written = $false
        $status.guard_state_degraded = $true
        Write-GuardLog "ERROR" ("guard state {0} could not be written ({1}); the previous record stays in place and the next run carries no unreadable-lease count from it" -f `
            $guardStatePath, $_.Exception.Message)
    }
    finally {
        if (Test-Path -LiteralPath $guardStateTempPath) { Remove-Item -LiteralPath $guardStateTempPath -Force -ErrorAction SilentlyContinue }
    }
}

$statusTempPath = "{0}.{1}.tmp" -f $statusPath, [guid]::NewGuid().ToString("N")
try {
    $status | ConvertTo-Json | Out-File -LiteralPath $statusTempPath -Encoding utf8
    Move-Item -LiteralPath $statusTempPath -Destination $statusPath -Force
}
finally {
    if (Test-Path -LiteralPath $statusTempPath) { Remove-Item -LiteralPath $statusTempPath -Force }
}
