# Workstation pre-gate: run the full test suite for one exact head on a
# non-capture workstation, in the capture host's bounded-suite launch mode,
# before that head may take a host landing slot. A FAIL receipt keeps the head
# off the host.
#
# How it matches the host (docs/development.md, "Workstation pre-gate"):
#   - host:      S4U task -> integration_attempt_suite.ps1 -> powershell.exe
#                bounded_worktree_test_suite.ps1 (Start-WeatherProcessInJob with
#                captured output) -> each pytest chunk (Start-WeatherProcessInJob)
#   - pre-gate:  this script -> powershell.exe workstation_pregate_driver.ps1
#                (the same Start-WeatherProcessInJob with captured output) ->
#                the host suite's own statements, replayed from its AST, launch
#                each chunk.
# Both hops use CREATE_SUSPENDED|CREATE_NO_WINDOW inside a kill-on-close Job, so
# each pytest chunk owns a fresh, windowless console whatever the session of the
# top-level caller. No Scheduled Task is registered.
#
# Holds the workstation FIFO heavy-work queue lease (workstation_offline_v1),
# creates a detached worktree at -Head under a short path, removes it and the
# per-chunk basetemps afterwards, and writes one JSON receipt.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{40}$")]
    [string]$Head,
    [ValidatePattern("^(?:[0-9a-fA-F]{40})?$")]
    [string]$Base = "",
    [string]$RepoRoot = "",
    [string]$OutputDirectory = "",
    [string]$ReceiptPath = "",
    [string]$WorktreeParent = "C:\lpf-s",
    [string]$GitExecutablePath = "",
    [ValidateRange(1, 86400)]
    [int]$QueueTimeoutSeconds = 14400
)

$ErrorActionPreference = "Stop"
$receiptSchema = "weather.workstation_pregate_receipt.v1"
$mutexName = "Global\WeatherProjectHeavyWorkloadV1"
$queueTimeoutExitCode = 75

$Head = $Head.ToLowerInvariant()
$Base = $Base.ToLowerInvariant()
$sha12 = $Head.Substring(0, 12)
if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Join-Path $PSScriptRoot "..\.."
}
$RepoRoot = (Get-Item -LiteralPath $RepoRoot -Force -ErrorAction Stop).FullName
$opsRoot = $PSScriptRoot
$hostSuitePath = Join-Path $opsRoot "bounded_worktree_test_suite.ps1"
$driverPath = Join-Path $opsRoot "workstation_pregate_driver.ps1"
foreach ($required in @(
    $hostSuitePath, $driverPath,
    (Join-Path $opsRoot "windows_kill_on_close_job.ps1"),
    (Join-Path $opsRoot "workload_admission.ps1"),
    (Join-Path $opsRoot "git_executable_identity.ps1"),
    (Join-Path $opsRoot "training_window_contract.ps1"),
    (Join-Path $RepoRoot "scripts\ops\bounded_worktree_test_suite.ps1"),
    (Join-Path $RepoRoot "venv\Scripts\python.exe")
)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "workstation pre-gate prerequisite is missing: $required"
    }
}
. (Join-Path $opsRoot "workload_admission.ps1")
. (Join-Path $opsRoot "windows_kill_on_close_job.ps1")
. (Join-Path $opsRoot "git_executable_identity.ps1")
. (Join-Path $opsRoot "training_window_contract.ps1")

function Get-WorkstationPregateHostFunctions {
    # Define the host suite's own chunk-planning functions in the caller's scope.
    param([Parameter(Mandatory = $true)][string]$HostSuitePath)

    $tokens = $null
    $errors = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile(
        $HostSuitePath, [ref]$tokens, [ref]$errors
    )
    if ($errors.Count -ne 0) { throw "cannot parse the host bounded suite: $HostSuitePath" }
    $definitions = @()
    foreach ($name in @("Read-SuiteFileTimingTable", "Get-SuiteTimePackedChunks")) {
        $found = @($ast.FindAll({
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -ceq $name
        }, $true))
        if ($found.Count -ne 1) { throw "host bounded suite has no unique function: $name" }
        $definitions += $found[0].Extent.Text
    }
    $cap = @($ast.ParamBlock.Parameters | Where-Object {
        $_.Name.VariablePath.UserPath -ceq "MaxFilesPerChunk"
    })
    if ($cap.Count -ne 1 -or $null -eq $cap[0].DefaultValue) {
        throw "host bounded suite has no MaxFilesPerChunk default"
    }
    return [pscustomobject]@{
        Definitions = $definitions
        MaxFilesPerChunk = [int](Invoke-Expression $cap[0].DefaultValue.Extent.Text)
    }
}

function Get-WorkstationPregateChunkPlan {
    # The host's inventory rule (tracked tests/**/test_*.py, ordinal sort) and
    # the host's own packer and timing-table reader, extracted from its AST.
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$TrackedPaths,
        [Parameter(Mandatory = $true)][string]$TimingTablePath,
        [Parameter(Mandatory = $true)][string]$HostSuitePath
    )

    $hostFunctions = Get-WorkstationPregateHostFunctions -HostSuitePath $HostSuitePath
    foreach ($definition in $hostFunctions.Definitions) { Invoke-Expression $definition }
    $files = @(
        $TrackedPaths |
            ForEach-Object { ([string]$_).Replace("\", "/") } |
            Where-Object { $_ -match '^tests/(?:.*/)?test_[^/]*\.py$' } |
            Sort-Object
    )
    $table = Read-SuiteFileTimingTable -Path $TimingTablePath
    $chunks = Get-SuiteTimePackedChunks -TestFiles $files `
        -MaxFilesPerChunk $hostFunctions.MaxFilesPerChunk -TimingTable $table
    return [pscustomobject]@{
        Files = $files
        Chunks = @($chunks | ForEach-Object { ,@($_) })
        MaxFilesPerChunk = $hostFunctions.MaxFilesPerChunk
        TimingTablePresent = [bool]$table.Present
        TimingTableSha256 = [string]$table.Sha256
    }
}

function Read-WorkstationPregateSuiteLog {
    param([Parameter(Mandatory = $true)][string]$Path)

    $result = [ordered]@{
        planned_chunks = $null
        planned_files = $null
        planned_max_files = $null
        starts = @{}
        exits = @{}
        run_tag = $null
        all_passed_line = $false
        skip_notes = @()
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $result }
    foreach ($line in [IO.File]::ReadAllLines($Path)) {
        $message = if ($line.Length -gt 21) { $line.Substring(21) } else { $line }
        if ($message -cmatch '^planned chunks=(\d+) files=(\d+) max_files=(\d+)$') {
            $result.planned_chunks = [int]$Matches[1]
            $result.planned_files = [int]$Matches[2]
            $result.planned_max_files = [int]$Matches[3]
        }
        elseif ($message -cmatch '^chunk (\d+)/(\d+) starting files=(\d+) junit=(.+)$') {
            $result.starts[[int]$Matches[1]] = [pscustomobject]@{
                files = [int]$Matches[3]; junit = [string]$Matches[4]
            }
            if ($Matches[4] -cmatch '\.(\d{8}T\d{6})\.chunk-\d{3}\.xml$') {
                $result.run_tag = $Matches[1]
            }
        }
        elseif ($message -cmatch '^chunk (\d+)/(\d+) exit=(-?\d+)?$') {
            $code = if ($Matches.ContainsKey(3)) { [int]$Matches[3] } else { $null }
            $result.exits[[int]$Matches[1]] = $code
        }
        elseif ($message -cmatch '^VERDICT: ALL CHUNKS PASSED \((\d+)/(\d+)\)') {
            $result.all_passed_line = ([int]$Matches[1] -eq [int]$Matches[2])
        }
        elseif ($message.StartsWith("WORKSTATION PRE-GATE: ")) {
            $result.skip_notes += $message
        }
    }
    return $result
}

function Get-WorkstationPregateJUnitFailures {
    param([string[]]$Paths, [int]$Limit = 50)

    $failed = New-Object System.Collections.Generic.List[string]
    foreach ($path in @($Paths)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        try {
            [xml]$document = [IO.File]::ReadAllText($path)
            foreach ($case in @($document.SelectNodes("//testcase"))) {
                if ($null -ne $case.SelectSingleNode("failure|error")) {
                    if ($failed.Count -lt $Limit) {
                        $failed.Add(("{0}::{1}" -f $case.classname, $case.name))
                    }
                }
            }
        }
        catch { $failed.Add("unreadable junit: $path") }
    }
    return @($failed)
}

function Invoke-WorkstationPregateGit {
    param(
        [Parameter(Mandatory = $true)][string]$GitExe,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [int[]]$AllowedExitCodes = @(0)
    )
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $rows = @(& $GitExe -c core.fsmonitor=false -c core.hooksPath=NUL @Arguments 2>&1 |
            ForEach-Object { [string]$_ })
        $code = [int]$LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previousPreference }
    if ($code -notin $AllowedExitCodes) {
        throw ("git {0} failed with exit {1}: {2}" -f ($Arguments -join " "), $code, ($rows -join " | "))
    }
    return [pscustomobject]@{ ExitCode = $code; Rows = $rows }
}

function Remove-WorkstationPregateTree {
    # rmdir /s does not follow junctions inside the tree.
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $true }
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (-not $item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "refusing unsafe pre-gate cleanup: $Path"
    }
    & cmd.exe /d /c "rmdir /s /q `"$Path`"" | Out-Null
    return -not (Test-Path -LiteralPath $Path)
}

function Write-WorkstationPregateReceipt {
    param([Parameter(Mandatory = $true)][object]$Receipt, [Parameter(Mandatory = $true)][string]$Path)
    $json = ($Receipt | ConvertTo-Json -Depth 8) + "`n"
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try {
        $bytes = (New-Object Text.UTF8Encoding($false, $true)).GetBytes($json)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally { $stream.Dispose() }
}

# ---------------------------------------------------------------- setup
$stamp = (Get-Date).ToString("yyyyMMddTHHmmss", [Globalization.CultureInfo]::InvariantCulture)
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $RepoRoot "data\pregate"
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$runDirectory = Join-Path $OutputDirectory ("pg-{0}-{1}-{2}" -f $sha12, $stamp, $PID)
New-Item -ItemType Directory -Path $runDirectory -Force -ErrorAction Stop | Out-Null
if ([string]::IsNullOrWhiteSpace($ReceiptPath)) {
    $ReceiptPath = Join-Path $runDirectory "receipt.json"
}
$ReceiptPath = [IO.Path]::GetFullPath($ReceiptPath)
if (Test-Path -LiteralPath $ReceiptPath) {
    throw "workstation pre-gate refuses to replace an existing receipt: $ReceiptPath"
}
$logPath = Join-Path $runDirectory "suite.log"
$WorktreeParent = [IO.Path]::GetFullPath($WorktreeParent)
$worktreeRoot = Join-Path $WorktreeParent ("pg-{0}" -f $sha12)

$receipt = [ordered]@{
    schema = $receiptSchema
    head = $Head
    base = if ($Base) { $Base } else { $null }
    base_is_ancestor = $null
    verdict = "FAIL"
    failure_reasons = @()
    repo_root = $RepoRoot
    worktree = $worktreeRoot
    host_suite_script = $hostSuitePath
    host_suite_sha256 = (Get-FileHash -LiteralPath $hostSuitePath -Algorithm SHA256).Hash.ToLowerInvariant()
    driver_script = $driverPath
    driver_sha256 = (Get-FileHash -LiteralPath $driverPath -Algorithm SHA256).Hash.ToLowerInvariant()
    git_executable = $null
    lease_mode = $null
    launch_mode = [ordered]@{
        driver = "Start-WeatherProcessInJob -OutputCapture (CREATE_SUSPENDED|CREATE_NO_WINDOW, stdio pipes, kill-on-close Job), as integration_attempt_suite.ps1 launches the host suite"
        chunks = "host bounded suite statements replayed from its AST: Start-WeatherProcessInJob (CREATE_SUSPENDED|CREATE_NO_WINDOW, no inherited handles, kill-on-close Job)"
        scheduled_task_registered = $false
    }
    skipped_host_checks = @()
    scrubbed_environment_names = @()
    inventory_files = $null
    max_files_per_chunk = $null
    timing_table_present = $null
    timing_table_sha256 = $null
    chunk_plan = @()
    chunks = @()
    failed_tests = @()
    driver_exit_code = $null
    log_path = $logPath
    log_sha256 = $null
    stdout_path = $logPath + ".stdout.log"
    stderr_path = $logPath + ".stderr.log"
    junit_paths = @()
    started_at = (Get-Date).ToString("o")
    finished_at = $null
    worktree_removed = $null
    basetemp_removed = $null
}
$failures = New-Object System.Collections.Generic.List[string]
$exitCode = 1
$lease = $null
$worktreeCreated = $false
$plan = $null
$gitExe = $null

try {
    # ------------------------------------------------------------ lease
    if ($env:WEATHER_WORKSTATION_WRAPPER_ACTIVE -ceq "1") {
        # Nested inside workstation_heavy.ps1, which already holds the
        # host-global workstation lease. Prove somebody really holds it.
        $probe = [Threading.Mutex]::new($false, $mutexName)
        $acquired = $false
        try {
            try { $acquired = $probe.WaitOne(0, $false) }
            catch [Threading.AbandonedMutexException] { $acquired = $true }
            if ($acquired) { $probe.ReleaseMutex() }
        }
        finally { $probe.Dispose() }
        if ($acquired) {
            throw "WEATHER_WORKSTATION_WRAPPER_ACTIVE is set but nobody holds the workstation heavy-work lease"
        }
        $receipt.lease_mode = "inherited_from_workstation_heavy"
    }
    else {
        $lease = Enter-WeatherHeavyWorkloadLeaseQueued `
            -RepoRoot $RepoRoot `
            -Workload ("WorkstationOffline-pytest-pregate-{0}-{1}" -f $sha12, $PID) `
            -ExecutionHostProfile "workstation_offline_v1" `
            -TimeoutSeconds $QueueTimeoutSeconds
        if ($null -eq $lease) {
            $exitCode = $queueTimeoutExitCode
            throw "workstation heavy-work queue wait timed out after $QueueTimeoutSeconds s; nothing was started"
        }
        $receipt.lease_mode = "workstation_queue"
    }

    # ------------------------------------------------------------ git identity
    if ([string]::IsNullOrWhiteSpace($GitExecutablePath)) {
        $candidates = @(Get-Command git.exe -CommandType Application -All -ErrorAction Stop |
            ForEach-Object { [string]$_.Source })
        $preferred = @($candidates | Where-Object { $_ -match '\\cmd\\git\.exe$' })
        $GitExecutablePath = if ($preferred.Count -gt 0) { $preferred[0] } else { $candidates[0] }
    }
    $identity = Get-WeatherGitExecutableIdentity -Path $GitExecutablePath
    $gitExe = [string]$identity.path
    $receipt.git_executable = $identity

    # ------------------------------------------------------------ head / base
    Invoke-WorkstationPregateGit -GitExe $gitExe -Arguments @(
        "-C", $RepoRoot, "cat-file", "-e", "$Head^{commit}"
    ) | Out-Null
    if ($Base) {
        Invoke-WorkstationPregateGit -GitExe $gitExe -Arguments @(
            "-C", $RepoRoot, "cat-file", "-e", "$Base^{commit}"
        ) | Out-Null
        $ancestry = Invoke-WorkstationPregateGit -GitExe $gitExe -AllowedExitCodes @(0, 1) -Arguments @(
            "-C", $RepoRoot, "merge-base", "--is-ancestor", $Base, $Head
        )
        $receipt.base_is_ancestor = ($ancestry.ExitCode -eq 0)
        if (-not $receipt.base_is_ancestor) {
            throw "Base $Base is not an ancestor of Head $Head"
        }
    }

    # ------------------------------------------------------------ worktree
    if (Test-Path -LiteralPath $worktreeRoot) {
        throw "pre-gate worktree path already exists; remove the stale worktree first: $worktreeRoot"
    }
    New-Item -ItemType Directory -Path $WorktreeParent -Force -ErrorAction Stop | Out-Null
    $worktreeCreated = $true
    Invoke-WorkstationPregateGit -GitExe $gitExe -Arguments @(
        "-C", $RepoRoot, "worktree", "add", "--detach", $worktreeRoot, $Head
    ) | Out-Null
    $worktreeRoot = (Get-Item -LiteralPath $worktreeRoot -Force).FullName

    # ------------------------------------------------------------ plan
    $tracked = (Invoke-WorkstationPregateGit -GitExe $gitExe -Arguments @(
        "-C", $worktreeRoot, "ls-files", "--", "tests"
    )).Rows
    $plan = Get-WorkstationPregateChunkPlan -TrackedPaths @($tracked) `
        -TimingTablePath (Join-Path $worktreeRoot "tests\bounded_suite_file_timings.json") `
        -HostSuitePath $hostSuitePath
    $receipt.inventory_files = $plan.Files.Count
    $receipt.max_files_per_chunk = $plan.MaxFilesPerChunk
    $receipt.timing_table_present = $plan.TimingTablePresent
    $receipt.timing_table_sha256 = $plan.TimingTableSha256
    $receipt.chunk_plan = @($plan.Chunks | ForEach-Object { ,@($_) })

    # ------------------------------------------------------------ environment
    # The host task runs in a clean S4U environment. Remove ambient agent and
    # Python overrides the host would not carry; the host suite then applies its
    # own scrubbing and PYTHONPATH exactly as on the host.
    $scrubbed = @()
    foreach ($name in @([Environment]::GetEnvironmentVariables("Process").Keys | ForEach-Object { [string]$_ })) {
        $upper = $name.ToUpperInvariant()
        if ($upper -cin @(
                "WEATHER_ALLOW_CONSOLE_CHILDREN", "WEATHER_WORKSTATION_WRAPPER_ACTIVE",
                "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONSTARTUP", "PYTHONHOME",
                "PYTHONINSPECT", "PYTHONWARNINGS", "PYTHONPATH", "VIRTUAL_ENV", "CLAUDECODE"
            ) -or $upper.StartsWith("CLAUDE_CODE_") -or $upper.StartsWith("CODEX_")) {
            [Environment]::SetEnvironmentVariable($name, $null, "Process")
            $scrubbed += $name
        }
    }
    $receipt.scrubbed_environment_names = @($scrubbed | Sort-Object)

    # ------------------------------------------------------------ driver
    $powerShellExecutable = Join-Path $PSHOME "powershell.exe"
    $tokens = @(
        "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", $driverPath,
        "-RepoRoot", $RepoRoot,
        "-WorktreeRoot", $worktreeRoot,
        "-ExpectedTip", $Head,
        "-LogPath", $logPath,
        "-GitExecutablePath", [string]$identity.path,
        "-ExpectedGitExecutableSha256", [string]$identity.sha256,
        "-ExpectedGitExecutableFileVersion", [string]$identity.file_version
    )
    $argumentString = ConvertTo-ScheduledTaskArgumentString -Tokens $tokens
    $job = $null
    $driver = $null
    $output = $null
    try {
        $job = New-WeatherKillOnCloseJob
        $output = [Weather.Operations.KillOnCloseJob+CapturedOutput]::new(
            $receipt.stdout_path, $receipt.stderr_path, 1048576
        )
        $driver = Start-WeatherProcessInJob -Job $job -FilePath $powerShellExecutable `
            -ArgumentString $argumentString -WorkingDirectory $RepoRoot -OutputCapture $output
        # Host suite MaxRuntimeSeconds is at most 5400 s; allow setup headroom.
        $driverClock = [Diagnostics.Stopwatch]::StartNew()
        while (-not $driver.HasExited) {
            if ($driverClock.Elapsed.TotalSeconds -ge 6300) {
                $failures.Add("driver exceeded the pre-gate wall-clock bound; child tree terminated")
                break
            }
            $output.Drain()
            Start-Sleep -Milliseconds 200
            $driver.Refresh()
        }
        if ($driver.HasExited) {
            $driver.WaitForExit()
            $receipt.driver_exit_code = [int]$driver.ExitCode
        }
    }
    finally {
        if ($job) { $job.TerminateAndWait(5000) }
        if ($output) { $output.Complete(2000); $output.Dispose() }
        if ($driver) { $driver.Dispose() }
        if ($job) { $job.Dispose() }
    }
}
catch {
    $failures.Add("pre-gate error: $($_.Exception.Message)")
}
finally {
    # ------------------------------------------------------------ evidence
    $parsed = Read-WorkstationPregateSuiteLog -Path $logPath
    if (Test-Path -LiteralPath $logPath -PathType Leaf) {
        $receipt.log_sha256 = (Get-FileHash -LiteralPath $logPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $receipt.skipped_host_checks = @($parsed.skip_notes)
    $junitPaths = @($parsed.starts.Keys | Sort-Object | ForEach-Object { [string]$parsed.starts[$_].junit } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
    $receipt.junit_paths = $junitPaths
    $receipt.failed_tests = @(Get-WorkstationPregateJUnitFailures -Paths $junitPaths)
    $chunkRecords = @()
    if ($null -ne $plan) {
        for ($index = 0; $index -lt $plan.Chunks.Count; $index++) {
            $ordinal = $index + 1
            $chunkRecords += [ordered]@{
                ordinal = $ordinal
                files = @($plan.Chunks[$index]).Count
                logged_files = if ($parsed.starts.ContainsKey($ordinal)) { $parsed.starts[$ordinal].files } else { $null }
                exit_code = if ($parsed.exits.ContainsKey($ordinal)) { $parsed.exits[$ordinal] } else { $null }
            }
        }
    }
    $receipt.chunks = $chunkRecords

    # ------------------------------------------------------------ verdict
    if ($null -ne $plan -and $null -ne $receipt.driver_exit_code) {
        if ($parsed.planned_chunks -ne $plan.Chunks.Count -or
            $parsed.planned_files -ne $plan.Files.Count -or
            $parsed.planned_max_files -ne $plan.MaxFilesPerChunk) {
            $failures.Add("host suite log plan differs from the pre-gate plan")
        }
        foreach ($record in $chunkRecords) {
            if ($null -ne $record.logged_files -and $record.logged_files -ne $record.files) {
                $failures.Add("chunk $($record.ordinal) ran $($record.logged_files) files; plan has $($record.files)")
            }
            if ($null -eq $record.exit_code) {
                $failures.Add("chunk $($record.ordinal) has no recorded exit code")
            }
            elseif ($record.exit_code -ne 0) {
                $failures.Add("chunk $($record.ordinal) exited $($record.exit_code)")
            }
        }
        if ($receipt.driver_exit_code -ne 0) {
            $failures.Add("host suite driver exited $($receipt.driver_exit_code)")
        }
        if (-not $parsed.all_passed_line) {
            $failures.Add("host suite log has no ALL CHUNKS PASSED verdict")
        }
        if ($receipt.skipped_host_checks.Count -ne 5) {
            $failures.Add("host suite log does not record the five pre-gate replacements")
        }
    }
    elseif ($failures.Count -eq 0) {
        $failures.Add("host suite driver did not complete")
    }

    # ------------------------------------------------------------ cleanup
    if ($parsed.run_tag) {
        $baseTempParent = Join-Path $env:SystemDrive "pt"
        $baseTempRemoved = $true
        foreach ($leftover in @(Get-ChildItem -LiteralPath $baseTempParent -Directory -Force -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -like ("bs-{0}-*" -f $parsed.run_tag) })) {
            try { if (-not (Remove-WorkstationPregateTree -Path $leftover.FullName)) { $baseTempRemoved = $false } }
            catch { $baseTempRemoved = $false }
        }
        $receipt.basetemp_removed = $baseTempRemoved
    }
    if ($worktreeCreated) {
        try {
            if ($null -ne $gitExe -and (Test-Path -LiteralPath $worktreeRoot)) {
                Invoke-WorkstationPregateGit -GitExe $gitExe -AllowedExitCodes @(0, 128) -Arguments @(
                    "-C", $RepoRoot, "worktree", "remove", "--force", $worktreeRoot
                ) | Out-Null
            }
            if (Test-Path -LiteralPath $worktreeRoot) {
                Remove-WorkstationPregateTree -Path $worktreeRoot | Out-Null
            }
            if ($null -ne $gitExe) {
                Invoke-WorkstationPregateGit -GitExe $gitExe -Arguments @(
                    "-C", $RepoRoot, "worktree", "prune"
                ) | Out-Null
            }
        }
        catch { $failures.Add("worktree cleanup error: $($_.Exception.Message)") }
        $receipt.worktree_removed = -not (Test-Path -LiteralPath $worktreeRoot)
        if (-not $receipt.worktree_removed) { $failures.Add("pre-gate worktree was not removed") }
    }

    if ($null -ne $lease) {
        try {
            Set-WeatherHeavyWorkloadLeaseTeardownPending -Lease $lease | Out-Null
            Exit-WeatherHeavyWorkloadLease -Lease $lease
        }
        catch { $failures.Add("workstation lease release error: $($_.Exception.Message)") }
    }

    $receipt.failure_reasons = @($failures)
    if ($failures.Count -eq 0) {
        $receipt.verdict = "PASS"
        $exitCode = 0
    }
    elseif ($exitCode -ne $queueTimeoutExitCode) {
        $exitCode = 1
    }
    $receipt.finished_at = (Get-Date).ToString("o")
    Write-WorkstationPregateReceipt -Receipt $receipt -Path $ReceiptPath
    Write-Output ("workstation pre-gate {0} head={1} receipt={2}" -f $receipt.verdict, $Head, $ReceiptPath)
}
exit $exitCode
