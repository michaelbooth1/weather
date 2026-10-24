# Second workstation lease slot for focused pytest runs (owner decision 2026-10-13).
#
# Dot-sourced by workstation_heavy.ps1 only when -FocusedSlot is passed, after
# workload_admission.ps1 and windows_kill_on_close_job.ps1. Without -FocusedSlot
# nothing here is loaded, so the primary lease, the FIFO queue and their state are
# untouched.
#
# The slot is a separate named mutex. It never takes, waits for or queues on the
# primary host-global mutex, and it writes no primary ACTIVE/TEARDOWN_PENDING marker.
# Contract (HOST_LOAD_POLICY "Second lease slot"):
#   * the assigned non-capture workstation only (Assert-WeatherWorkstationOfflineHost);
#   * pytest only, in the focused-run shape: 1..25 named test files, an explicit
#     --basetemp, no xdist, only allowlisted options (the Codex hook's classifier);
#   * a hard wall-clock limit below 300 s; on overrun the whole child tree is killed;
#   * refused, and pre-empted mid-run, while any live-session signal is present.
#   * a test file marked `real_global_mutex` (it opens a real Global\WeatherProject*
#     mutex, so beside the primary lease it would fail as busy or disturb that lease)
#     is refused before anything starts.
# Exit codes: the child's code; 76 slot busy (nothing started); 77 pre-empted by a
# live-session signal; 78 refused because a named file takes the real global mutex
# (nothing started); 124 time limit overrun. Other refusals throw (exit 1).

$script:WeatherFocusedSlotBusyExitCode = 76
$script:WeatherFocusedSlotPreemptedExitCode = 77
$script:WeatherFocusedSlotGlobalMutexExitCode = 78
$script:WeatherFocusedSlotOverrunExitCode = 124
$script:WeatherFocusedSlotMaxSeconds = 299

function Get-WeatherWorkstationFocusedSlotMutexName {
    return "Global\WeatherProjectWorkstationFocusedSlotV1"
}

function Get-WeatherWorkstationFocusedSlotStateRoot {
    # Beside the host-global state marker, so every checkout shares one slot state.
    return (Split-Path -Parent (Get-WeatherHeavyWorkloadPoisonPath))
}

function Get-WeatherWorkstationLiveSessionReason {
    # Returns $null when no live-session signal is present, else the reason. Every
    # signal fails closed: an unreadable marker or a failed process scan is a reason.
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [int]$ExcludeTreeRootProcessId = 0
    )

    # 1. Explicit operator/runbook marker for the whole live session.
    $sessionMarker = Join-Path $StateRoot "live_session_v1.active"
    try {
        if (Test-Path -LiteralPath $sessionMarker -ErrorAction Stop) {
            return "the live-session marker live_session_v1.active is present"
        }
    }
    catch { return "the live-session marker cannot be checked" }

    # 2. A portable live stage holding (or failing to release) the host-global mutex.
    try {
        $state = Get-WeatherHeavyWorkloadPoisonState -Path (Get-WeatherHeavyWorkloadPoisonPath)
    }
    catch { return "the host-global workload state cannot be read" }
    if ($null -ne $state) {
        if ([string]$state.state -ceq "TEARDOWN_PENDING") {
            return "a host-global workload teardown is pending"
        }
        if ([string]$state.execution_host_profile -cne "workstation_offline_v1") {
            return "a portable live stage holds the host-global mutex"
        }
    }

    # 3. A live session runner, sealed stage wrapper or live pilot process, outside
    #    this slot's own process tree.
    try { $snapshot = @(Get-WeatherProcessSnapshot) }
    catch { return "the live-process scan failed" }
    $own = [Collections.Generic.HashSet[long]]::new()
    if ($ExcludeTreeRootProcessId -gt 0) {
        [void]$own.Add([long]$ExcludeTreeRootProcessId)
        $grew = $true
        while ($grew) {
            $grew = $false
            foreach ($process in $snapshot) {
                if ($own.Contains([long]$process.ParentProcessId) -and
                    $own.Add([long]$process.ProcessId)) { $grew = $true }
            }
        }
    }
    $livePattern = '(?i)weather\.operations\.international_live_session_runner|' +
        'weather\.market\.mm_live_pilot_cli|' +
        '[\\/]wrappers[\\/]stage(?:0|1-cancel-all|1-dead-man)\.(?:ps1|py)\b'
    foreach ($process in $snapshot) {
        if ($own.Contains([long]$process.ProcessId)) { continue }
        if ([string]$process.Name -cnotmatch '(?i)\A(?:pythonw?(?:3(?:\.\d+)?)?|powershell|pwsh)\.exe\z') {
            continue
        }
        if ([string]$process.CommandLine -match $livePattern) {
            return ("a live-session process is running (pid {0})" -f $process.ProcessId)
        }
    }
    return $null
}

function Test-WeatherWorkstationFocusedSlotArguments {
    # The focused-run shape from the Codex hook's classifier (`focused_pytest_arguments`).
    # Unlike the exemption, `serial` files are admitted: the slot owns them in a Job
    # under a hard time limit instead of letting them run unwrapped. Files marked
    # `real_global_mutex` are reported in GlobalMutexFiles so the caller can refuse them.
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$PythonPath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $refuse = { param([string]$Reason) [PSCustomObject]@{ Allowed = $false; Reason = $Reason; GlobalMutexFiles = @() } }
    if ($Arguments.Count -lt 3 -or $Arguments[0] -cne "-m" -or $Arguments[1] -cne "pytest") {
        return & $refuse "the focused slot admits only '-m pytest' runs"
    }
    $hook = Join-Path $RepoRoot ".codex\hooks\pre_tool_use_host_load.py"
    if (-not (Test-Path -LiteralPath $hook -PathType Leaf)) {
        return & $refuse "the focused-run classifier is missing"
    }
    $request = [ordered]@{
        arguments = @($Arguments | Select-Object -Skip 2)
        cwd = $RepoRoot
    } | ConvertTo-Json -Compress
    $encoded = [Convert]::ToBase64String([Text.UTF8Encoding]::new($false).GetBytes($request))
    $probe = @'
import base64, importlib.util, json, pathlib, re, sys
spec = importlib.util.spec_from_file_location('weather_focused_slot_hook', sys.argv[1])
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)
request = json.loads(base64.b64decode(sys.argv[2], validate=True).decode('utf-8'))
files, why = hook.focused_pytest_arguments(request['arguments'], pathlib.Path(request['cwd']))
paths = [] if files is None else list(files.values() if isinstance(files, dict) else files)
marker = re.compile(r'^\s*(?:pytestmark\s*=\s*\[?\s*|@)?pytest\.mark\.real_global_mutex\b', re.M)
held = []
for path in paths:
    try:
        text = pathlib.Path(path).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        held.append(str(path))
        continue
    if marker.search(text):
        held.append(str(path))
json.dump({'allowed': files is not None, 'reason': why, 'global_mutex': held}, sys.stdout, separators=(',', ':'))
'@
    # No double quotes in the probe: Windows PowerShell 5.1 strips them from native arguments.
    try {
        $output = & $PythonPath -I -B -c $probe $hook $encoded
        if ($LASTEXITCODE -ne 0) { throw "classifier exited $LASTEXITCODE" }
        $verdict = (@($output) -join "") | ConvertFrom-Json -ErrorAction Stop
    }
    catch { return & $refuse "the focused-run classifier failed: $($_.Exception.Message)" }
    if ($verdict.allowed -isnot [bool] -or $verdict.reason -isnot [string] -or
        $null -eq $verdict.PSObject.Properties['global_mutex']) {
        return & $refuse "the focused-run classifier returned a malformed verdict"
    }
    return [PSCustomObject]@{
        Allowed = [bool]$verdict.allowed
        Reason = [string]$verdict.reason
        GlobalMutexFiles = @($verdict.global_mutex | ForEach-Object { [string]$_ })
    }
}

function Write-WeatherWorkstationFocusedSlotEvent {
    param([string]$RepoRoot, [string]$Event, [hashtable]$Extra = @{})
    $record = [ordered]@{
        schema_version = "weather_workstation_focused_slot_event_v1"
        event = $Event
        at_utc = [DateTime]::UtcNow.ToString("o")
        pid = $PID
    }
    foreach ($key in ($Extra.Keys | Sort-Object)) { $record[$key] = $Extra[$key] }
    $line = $record | ConvertTo-Json -Compress
    # Console, not the pipeline: callers return an exit code from the same scope.
    [Console]::Out.WriteLine(("workstation focused slot: {0}" -f $line))
    try {
        $logs = Join-Path $RepoRoot "data\logs"
        [void][IO.Directory]::CreateDirectory($logs)
        [IO.File]::AppendAllText((Join-Path $logs "heavy_workload_focused_slot.jsonl"),
            $line + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    }
    catch { [Console]::Error.WriteLine("focused-slot event log write failed: $($_.Exception.Message)") }
}

function Invoke-WeatherWorkstationFocusedSlot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$PythonPath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Kind,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [switch]$Queue,
        [switch]$ArchiveUnattended,
        [ValidateRange(100, 5000)][int]$MonitorMilliseconds = 1000
    )

    if ($Queue) {
        throw "-FocusedSlot cannot combine with -Queue; the queue serves only the primary lease"
    }
    if ($Kind -cne "pytest" -or $ArchiveUnattended) {
        throw "the focused slot admits only pytest runs"
    }
    if ($TimeoutSeconds -lt 1 -or $TimeoutSeconds -gt $script:WeatherFocusedSlotMaxSeconds) {
        throw "the focused slot time limit must be 1-$($script:WeatherFocusedSlotMaxSeconds) s"
    }
    # Capture-host refusal and assigned-workstation proof: the same check the queue
    # runs before it writes any state.
    Assert-WeatherWorkstationOfflineHost -RepoRoot $RepoRoot
    $shape = Test-WeatherWorkstationFocusedSlotArguments -RepoRoot $RepoRoot `
        -PythonPath $PythonPath -Arguments $Arguments
    if (-not $shape.Allowed) { throw "focused slot refused: $($shape.Reason)" }
    if (@($shape.GlobalMutexFiles).Count -gt 0) {
        $names = @($shape.GlobalMutexFiles | ForEach-Object { Split-Path -Leaf $_ }) -join ", "
        Write-WeatherWorkstationFocusedSlotEvent -RepoRoot $RepoRoot -Event "refused_global_mutex" `
            -Extra @{ files = $names }
        [Console]::Error.WriteLine(("focused slot refused: {0} takes the real global workload mutex " +
            "(marked real_global_mutex); run it through -Queue instead; nothing was started") -f $names)
        return $script:WeatherFocusedSlotGlobalMutexExitCode
    }
    $stateRoot = Get-WeatherWorkstationFocusedSlotStateRoot
    $slotPoison = Join-Path $stateRoot "workstation_focused_slot_v1.poison"
    if (Test-Path -LiteralPath $slotPoison) {
        throw ("focused slot refused: an earlier slot teardown was not proved; verify that no " +
            "residual slot processes remain, then delete $slotPoison")
    }
    $live = Get-WeatherWorkstationLiveSessionReason -StateRoot $stateRoot `
        -ExcludeTreeRootProcessId $PID
    if ($live) { throw "focused slot refused: $live" }

    $mutex = [Threading.Mutex]::new($false, (Get-WeatherWorkstationFocusedSlotMutexName))
    $owned = $false
    try { $owned = $mutex.WaitOne(0, $false) }
    catch [Threading.AbandonedMutexException] { $owned = $true }
    if (-not $owned) {
        $mutex.Dispose()
        Write-WeatherWorkstationFocusedSlotEvent -RepoRoot $RepoRoot -Event "busy"
        [Console]::Error.WriteLine(
            "workstation focused slot is busy; nothing was started (the primary lease is -Queue)")
        return $script:WeatherFocusedSlotBusyExitCode
    }

    $job = $null
    $child = $null
    $exitCode = 1
    $outcome = "refused"
    $reason = ""
    $started = [DateTime]::UtcNow
    $teardownError = $null
    try {
        # Re-check after taking the slot, closing the check-then-acquire gap.
        $live = Get-WeatherWorkstationLiveSessionReason -StateRoot $stateRoot `
            -ExcludeTreeRootProcessId $PID
        if ($live) { throw "focused slot refused: $live" }
        $job = New-WeatherKillOnCloseJob
        $argumentString = ConvertTo-WeatherWindowsArgumentString -Tokens $Arguments
        # The slot is not the primary lease: nested tools that may reuse the
        # primary wrapper's lease (workstation_pregate.ps1) must not see its marker.
        [Environment]::SetEnvironmentVariable("WEATHER_WORKSTATION_WRAPPER_ACTIVE", $null, "Process")
        [Environment]::SetEnvironmentVariable("WEATHER_WORKSTATION_FOCUSED_SLOT_ACTIVE", "1", "Process")
        [Environment]::SetEnvironmentVariable("PSExecutionPolicyPreference", "Bypass", "Process")
        Write-WeatherWorkstationFocusedSlotEvent -RepoRoot $RepoRoot -Event "start" `
            -Extra @{ timeout_seconds = $TimeoutSeconds }
        $started = [DateTime]::UtcNow
        $deadline = $started.AddSeconds($TimeoutSeconds)
        $child = Start-WeatherInteractiveProcessInJob -Job $job -FilePath $PythonPath `
            -ArgumentString $argumentString -WorkingDirectory $RepoRoot
        $outcome = "finish"
        while (-not $child.WaitForExit($MonitorMilliseconds)) {
            if ([DateTime]::UtcNow -ge $deadline) {
                $outcome = "overrun"
                break
            }
            $live = Get-WeatherWorkstationLiveSessionReason -StateRoot $stateRoot `
                -ExcludeTreeRootProcessId $PID
            if ($live) {
                $outcome = "preempted"
                $reason = $live
                break
            }
        }
        if ($outcome -ceq "finish") {
            $child.WaitForExit()
            $exitCode = $child.ExitCode
        }
        elseif ($outcome -ceq "overrun") {
            $exitCode = $script:WeatherFocusedSlotOverrunExitCode
            [Console]::Error.WriteLine((
                "workstation focused slot: time limit of {0} s overrun; the child tree was killed" -f
                $TimeoutSeconds))
        }
        else {
            $exitCode = $script:WeatherFocusedSlotPreemptedExitCode
            [Console]::Error.WriteLine("workstation focused slot pre-empted: $reason; the child tree was killed")
        }
    }
    catch {
        $reason = $_.Exception.Message
        throw
    }
    finally {
        if ($job) {
            try { $job.TerminateAndWait(5000) }
            catch { $teardownError = $_ }
        }
        if ($teardownError) {
            $outcome = "teardown_unproved"
            try {
                [IO.File]::WriteAllText($slotPoison, ([ordered]@{
                    pid = $PID; at_utc = [DateTime]::UtcNow.ToString("o")
                    error = $teardownError.Exception.Message
                } | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
            }
            catch { }
        }
        if ($child) { $child.Dispose() }
        if ($job) { $job.Dispose() }
        try { $mutex.ReleaseMutex() } catch { }
        $mutex.Dispose()
        Write-WeatherWorkstationFocusedSlotEvent -RepoRoot $RepoRoot -Event "finish" -Extra @{
            outcome = $outcome
            exit_code = $exitCode
            reason = $reason
            elapsed_seconds = [Math]::Round(([DateTime]::UtcNow - $started).TotalSeconds, 1)
        }
    }
    if ($teardownError) { throw $teardownError }
    return $exitCode
}
