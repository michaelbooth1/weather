Set-StrictMode -Version Latest

# Every preparer-owned child receives a fresh, short bound. The
# Job object's open handle is the stronger crash boundary; this timeout keeps a
# live preparer from holding the host-global preparation mutex indefinitely.
$script:WeatherIntegrationPreparationMutationTimeoutSeconds = 300
$script:WeatherIntegrationPreparationChildMaximumLifetimeSeconds = 5700
$script:WeatherIntegrationPreparationChildOutputMaximumBytes = 1048576
$script:WeatherIntegrationCreatorPreflightPlanSchema =
    "weather_integration_attempt_creator_preflight_plan_v1"

function Get-WeatherIntegrationPreparationMutationHardStop {
    param([datetime]$Now = (Get-WeatherIntegrationScheduleLocalNow))

    return $Now.AddSeconds(
        [int]$script:WeatherIntegrationPreparationMutationTimeoutSeconds
    )
}

function ConvertTo-WeatherIntegrationTrackedPytestInventory {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$Rows
    )

    return @(
        $Rows |
            ForEach-Object { ([string]$_).Replace("\", "/") } |
            Where-Object {
                $_ -match '^tests/(?:.*/)?(?:test_[^/]*|[^/]+_test)\.py$'
            } |
            Sort-Object -Unique
    )
}

function Assert-WeatherIntegrationCandidateTestInventory {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$BaselinePaths,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$CandidatePaths
    )

    $baseline = @(ConvertTo-WeatherIntegrationTrackedPytestInventory -Rows $BaselinePaths)
    $candidate = @(ConvertTo-WeatherIntegrationTrackedPytestInventory -Rows $CandidatePaths)
    $deleted = @($baseline | Where-Object { $candidate -cnotcontains $_ })
    if ($deleted.Count -ne 0) {
        throw "Candidate deletes baseline test inventory: $($deleted -join ', ')"
    }
    return @($candidate)
}

function Enter-WeatherIntegrationPreparationMutex {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot
    )

    $resolvedRoot = Resolve-WeatherIntegrationPath -Path $RepositoryRoot
    $lockDirectory = Join-Path $resolvedRoot "data\locks"
    if (-not (Test-Path -LiteralPath $lockDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $lockDirectory -Force -ErrorAction Stop |
            Out-Null
    }
    $lockPath = Join-Path $lockDirectory "integration-attempt-preparation.lock"
    try {
        # The open handle, not stale file contents, owns this host-global lock.
        return [IO.File]::Open(
            $lockPath,
            [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None
        )
    }
    catch {
        throw "Another integration attempt preparation is active; global preparation lock is unavailable."
    }
}

function Get-WeatherIntegrationTaskManifestBinding {
    param([Parameter(Mandatory = $true)][object]$Task)

    $actions = @($Task.Actions)
    if ($actions.Count -ne 1) {
        throw "Retired integration task must retain one exact executable action."
    }
    $argumentsProperty = $actions[0].PSObject.Properties["Arguments"]
    if ($null -eq $argumentsProperty) {
        throw "Retired integration task action has no immutable arguments."
    }
    $arguments = [string]$argumentsProperty.Value
    $pathMatches = [regex]::Matches(
        $arguments,
        '(?i)(?:^|\s)-ManifestPath\s+(?:"(?<quoted>[^"]+)"|(?<bare>[^\s"]+))(?=\s|$)'
    )
    $hashMatches = [regex]::Matches(
        $arguments,
        '(?i)(?:^|\s)-ExpectedManifestSha256\s+(?<hash>[0-9a-f]{64})(?=\s|$)'
    )
    if ($pathMatches.Count -ne 1 -or $hashMatches.Count -ne 1) {
        throw "Retired integration task action lost its exact manifest binding."
    }
    $pathMatch = $pathMatches[0]
    $manifestPath = if ($pathMatch.Groups["quoted"].Success) {
        [string]$pathMatch.Groups["quoted"].Value
    }
    else { [string]$pathMatch.Groups["bare"].Value }
    return [pscustomobject]@{
        ManifestPath = Resolve-WeatherIntegrationPath -Path $manifestPath
        ManifestSha256 = ([string]$hashMatches[0].Groups["hash"].Value).ToLowerInvariant()
    }
}

function Assert-WeatherIntegrationDisabledTaskRetirementEvidence {
    param(
        [Parameter(Mandatory = $true)][object]$Task,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot
    )

    $taskName = [string]$Task.TaskName
    if ($taskName -match '^WeatherIntegration(?<role>Suite|Merge)_(?<attempt>[A-Za-z0-9][A-Za-z0-9._-]{0,47})$') {
        $role = if ([string]$Matches.role -ceq "Suite") { "suite" } else { "merge" }
        $attemptId = [string]$Matches.attempt
        $binding = Get-WeatherIntegrationTaskManifestBinding -Task $Task
        $contract = Assert-WeatherIntegrationAttemptManifest `
            -ManifestPath $binding.ManifestPath `
            -ExpectedSha256 $binding.ManifestSha256
        if ([string]$contract.Manifest.attempt_id -cne $attemptId) {
            throw "Retired task name and manifest attempt id disagree."
        }
        $retirementFailure = $null
        try {
            Assert-WeatherIntegrationTaskRetirementReceipt `
                -AttemptContract $contract -Task $Task -Role $role | Out-Null
            return
        }
        catch { $retirementFailure = $_.Exception.Message }
        try {
            Assert-WeatherIntegrationFailClosureReceipt `
                -AttemptContract $contract -Task $Task -Role $role | Out-Null
            return
        }
        catch {
            throw (
                "Disabled attempt task has neither exact PASS retirement nor " +
                "exact FAIL closure evidence. retirement=$retirementFailure; " +
                "closure=$($_.Exception.Message)"
            )
        }
    }
    if ($taskName -cmatch
        '^WeatherIntegrationRecoveryBootstrap(?:Suite|Merge)Fixed0822$') {
        Assert-WeatherLegacyBootstrapRetirementReceipt `
            -RepositoryRoot $RepositoryRoot -Task $Task | Out-Null
        return
    }
    throw "Disabled task is not an exact supported retirement identity."
}

function Assert-WeatherIntegrationNoActiveAttemptCollision {
    param(
        [Parameter(Mandatory = $true)][datetime]$SuiteAtLocal,
        [Parameter(Mandatory = $true)][datetime]$MergeAtLocal,
        [AllowEmptyString()][string]$AttemptId = "",
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [switch]$AllowOwnExactTasks
    )

    $resolvedRepositoryRoot = Resolve-WeatherIntegrationPath -Path $RepositoryRoot
    $suiteInstant = ConvertTo-WeatherIntegrationLocalInstant `
        -Value $SuiteAtLocal -Label "collision SuiteAtLocal"
    $mergeInstant = ConvertTo-WeatherIntegrationLocalInstant `
        -Value $MergeAtLocal -Label "collision MergeAtLocal"
    $ownTaskNames = if ([string]::IsNullOrWhiteSpace($AttemptId)) { @() } else {
        @("WeatherIntegrationSuite_$AttemptId", "WeatherIntegrationMerge_$AttemptId")
    }
    $schedulerSnapshot = @(Get-ScheduledTask -ErrorAction Stop)
    $tasks = @($schedulerSnapshot | Where-Object {
        $isOwnExactTask = ($AllowOwnExactTasks -and
            [string]$_.TaskPath -ieq "\" -and
            $ownTaskNames -icontains [string]$_.TaskName)
        $settingsEnabled = ($null -eq $_.Settings.PSObject.Properties['Enabled'] -or
            [bool]$_.Settings.Enabled)
        $isOwnExactStagedTask = ($isOwnExactTask -and
            [string]$_.State -eq "Disabled" -and -not $settingsEnabled)
        ([string]$_.TaskName -match '^WeatherIntegration(?:Suite|Merge)_' -or
            [string]$_.TaskName -match
                '^WeatherIntegrationRecoveryBootstrap(?:Suite|Merge)Fixed[0-9]+$') -and
        -not $isOwnExactStagedTask
    })
    $active = New-Object System.Collections.Generic.List[string]
    $now = Get-WeatherIntegrationScheduleLocalNow
    $nowInstant = ConvertTo-WeatherIntegrationLocalInstant `
        -Value $now -Label "collision current time"
    foreach ($task in $tasks) {
        $isOwnExactTask = ([string]$task.TaskPath -ieq "\" -and
            $ownTaskNames -icontains [string]$task.TaskName)
        if ($isOwnExactTask -and -not $AllowOwnExactTasks) {
            $active.Add(
                "$([string]$task.TaskPath)$([string]$task.TaskName)@task-name-already-exists"
            )
            continue
        }
        $taskState = [string]$task.State
        $settingsEnabled = ($null -eq $task.Settings.PSObject.Properties['Enabled'] -or
            [bool]$task.Settings.Enabled)
        if ($taskState -in @("Running", "Queued") -or
            $taskState -notin @("Ready", "Disabled")) {
            $active.Add("$([string]$task.TaskPath)$([string]$task.TaskName)@$taskState")
            continue
        }
        $allowDemandStartProperty = $task.Settings.PSObject.Properties[
            "AllowDemandStart"
        ]
        if ($taskState -eq "Disabled" -or -not $settingsEnabled) {
            try {
                Assert-WeatherIntegrationDisabledTaskRetirementEvidence `
                    -Task $task -RepositoryRoot $resolvedRepositoryRoot
            }
            catch {
                $retirementFailure = [string]$_.Exception.Message
                $active.Add(
                    "$([string]$task.TaskPath)$([string]$task.TaskName)" +
                    "@disabled-without-valid-retirement-receipt" +
                    "[$retirementFailure]"
                )
            }
            continue
        }
        if ($null -eq $allowDemandStartProperty -or
            [bool]$allowDemandStartProperty.Value) {
            $active.Add(
                "$([string]$task.TaskPath)$([string]$task.TaskName)@demand-start-enabled"
            )
            continue
        }
        # An enabled Ready one-shot remains a collision even when Scheduler
        # reports a due, past, or null NextRunTime. Only exact Disabled own
        # staging and exact retired/closed Disabled tasks are admissible.
        $active.Add(
            "$([string]$task.TaskPath)$([string]$task.TaskName)@ready-enabled"
        )
    }
    $activeNames = @($active | Sort-Object -Unique)

    $quietConflicts = New-Object System.Collections.Generic.List[string]
    $quietStableObservations = New-Object System.Collections.Generic.List[object]
    foreach ($task in $schedulerSnapshot) {
        $taskSettingsEnabled = (
            $null -eq $task.Settings.PSObject.Properties['Enabled'] -or
            [bool]$task.Settings.Enabled
        )
        $isOwnExactStagedTask = ($AllowOwnExactTasks -and
            [string]$task.TaskPath -ieq "\" -and
            $ownTaskNames -icontains [string]$task.TaskName -and
            [string]$task.State -eq "Disabled" -and -not $taskSettingsEnabled)
        if ($isOwnExactStagedTask) { continue }
        $arguments = @($task.Actions | ForEach-Object {
            if ($null -eq $_) { return "" }
            $argumentsProperty = $_.PSObject.Properties["Arguments"]
            if ($null -eq $argumentsProperty) { return "" }
            [string]$argumentsProperty.Value
        }) -join " "
        $isSensitiveDriver = ([string]$task.TaskName -ieq "WeatherMergeSensitiveDriver")
        $isQuietMerge = ($arguments -match
            '(?i)(quiet_window_merge|suite_gated_quiet_merge|integration_attempt_merge)\.ps1')
        if (-not $isSensitiveDriver -and -not $isQuietMerge) { continue }
        $taskState = [string]$task.State
        $settingsEnabled = ($null -eq $task.Settings.PSObject.Properties['Enabled'] -or
            [bool]$task.Settings.Enabled)
        if ($taskState -in @("Running", "Queued") -or
            $taskState -notin @("Ready", "Disabled")) {
            $quietConflicts.Add(
                "$([string]$task.TaskPath)$([string]$task.TaskName)@$taskState"
            )
            continue
        }
        if ($taskState -eq "Disabled" -or -not $settingsEnabled) { continue }
        $info = Get-ScheduledTaskInfo `
            -TaskName ([string]$task.TaskName) `
            -TaskPath ([string]$task.TaskPath) `
            -ErrorAction Stop
        # Task Scheduler can advance a recurring task's NextRunTime as it
        # transitions Ready -> Running. Re-fetch the exact object after the
        # separate info query; never interpret the next recurrence as proof
        # that the current protected driver is idle.
        $postInfoSnapshot = @(Get-ScheduledTask -ErrorAction Stop)
        $postInfoMatches = @($postInfoSnapshot | Where-Object {
            [string]$_.TaskName -ieq [string]$task.TaskName -and
            [string]$_.TaskPath -ieq [string]$task.TaskPath
        })
        if ($postInfoMatches.Count -ne 1) {
            $quietConflicts.Add(
                "$([string]$task.TaskPath)$([string]$task.TaskName)@state-changed-during-collision-check"
            )
            continue
        }
        $postInfoTask = $postInfoMatches[0]
        $postInfoEnabled = (
            $null -eq $postInfoTask.Settings.PSObject.Properties['Enabled'] -or
            [bool]$postInfoTask.Settings.Enabled
        )
        $postInfoArguments = @($postInfoTask.Actions | ForEach-Object {
            if ($null -eq $_) { return "" }
            $argumentsProperty = $_.PSObject.Properties["Arguments"]
            if ($null -eq $argumentsProperty) { return "" }
            [string]$argumentsProperty.Value
        }) -join " "
        if ([string]$postInfoTask.State -cne $taskState -or
            $postInfoEnabled -ne $settingsEnabled -or
            $postInfoArguments -cne $arguments) {
            $quietConflicts.Add(
                "$([string]$task.TaskPath)$([string]$task.TaskName)@state-changed-during-collision-check"
            )
            continue
        }
        if ($null -eq $info.NextRunTime) {
            $quietConflicts.Add(
                "$([string]$task.TaskPath)$([string]$task.TaskName)@ready-due-or-past"
            )
            continue
        }
        $conflictStart = [datetime]$info.NextRunTime
        $conflictStartInstant = ConvertTo-WeatherIntegrationLocalInstant `
            -Value $conflictStart -Label "protected merge NextRunTime"
        if ($conflictStartInstant -le $nowInstant) {
            $quietConflicts.Add(
                "$([string]$task.TaskPath)$([string]$task.TaskName)@ready-due-or-past"
            )
            continue
        }
        # The sensitive driver can spend the full quiet-merge recovery budget
        # after its trigger; treating it as a point event allowed a proposed
        # suite to start while its publish/recovery work was still active.
        $conflictEndInstant = if ($isSensitiveDriver) {
            $conflictStartInstant.AddHours(4)
        }
        else { $conflictStartInstant }
        if ($isQuietMerge) {
            $settleSeconds = 300
            $rollbackSeconds = 1200
            if ($arguments -match '(?i)-SettleSeconds\s+(\d+)') {
                $settleSeconds = [int]$Matches[1]
            }
            if ($arguments -match '(?i)-RollbackRecoverySeconds\s+(\d+)') {
                $rollbackSeconds = [int]$Matches[1]
            }
            $conflictEndInstant = $conflictStartInstant.AddSeconds(
                [math]::Max(
                    $settleSeconds + 240,
                    $settleSeconds + $rollbackSeconds + 60
                )
            )
        }
        if ($conflictStartInstant -le $mergeInstant -and
            $suiteInstant -le $conflictEndInstant) {
            $quietConflicts.Add(
                "$([string]$task.TaskPath)$([string]$task.TaskName)@$($conflictStart.ToString('o'))"
            )
        }
        else {
            $quietStableObservations.Add([pscustomobject]@{
                TaskName = [string]$task.TaskName
                TaskPath = [string]$task.TaskPath
                State = $taskState
                Enabled = $settingsEnabled
                Arguments = $arguments
                NextRunTime = $conflictStart
            })
        }
    }
    if ($quietStableObservations.Count -ne 0) {
        # One final shared Scheduler snapshot closes the longer gap between the
        # per-task info reads and admission. A state/definition/run-time change
        # is itself a collision; a later call may retry from a coherent view.
        $finalQuietSnapshot = @(Get-ScheduledTask -ErrorAction Stop)
        $finalNowInstant = ConvertTo-WeatherIntegrationLocalInstant `
            -Value (Get-WeatherIntegrationScheduleLocalNow) `
            -Label "final collision current time"
        foreach ($observation in $quietStableObservations) {
            $finalMatches = @($finalQuietSnapshot | Where-Object {
                [string]$_.TaskName -ieq [string]$observation.TaskName -and
                [string]$_.TaskPath -ieq [string]$observation.TaskPath
            })
            if ($finalMatches.Count -ne 1) {
                $quietConflicts.Add(
                    "$([string]$observation.TaskPath)$([string]$observation.TaskName)@state-changed-during-collision-check"
                )
                continue
            }
            $finalTask = $finalMatches[0]
            $finalEnabled = (
                $null -eq $finalTask.Settings.PSObject.Properties['Enabled'] -or
                [bool]$finalTask.Settings.Enabled
            )
            $finalArguments = @($finalTask.Actions | ForEach-Object {
                if ($null -eq $_) { return "" }
                $argumentsProperty = $_.PSObject.Properties["Arguments"]
                if ($null -eq $argumentsProperty) { return "" }
                [string]$argumentsProperty.Value
            }) -join " "
            if ([string]$finalTask.State -cne [string]$observation.State -or
                $finalEnabled -ne [bool]$observation.Enabled -or
                $finalArguments -cne [string]$observation.Arguments) {
                $quietConflicts.Add(
                    "$([string]$observation.TaskPath)$([string]$observation.TaskName)@state-changed-during-collision-check"
                )
                continue
            }
            $finalInfo = Get-ScheduledTaskInfo `
                -TaskName ([string]$observation.TaskName) `
                -TaskPath ([string]$observation.TaskPath) `
                -ErrorAction Stop
            $terminalSnapshot = @(Get-ScheduledTask -ErrorAction Stop)
            $terminalMatches = @($terminalSnapshot | Where-Object {
                [string]$_.TaskName -ieq [string]$observation.TaskName -and
                [string]$_.TaskPath -ieq [string]$observation.TaskPath
            })
            if ($terminalMatches.Count -ne 1) {
                $quietConflicts.Add(
                    "$([string]$observation.TaskPath)$([string]$observation.TaskName)@state-changed-during-collision-check"
                )
                continue
            }
            $terminalTask = $terminalMatches[0]
            $terminalEnabled = (
                $null -eq $terminalTask.Settings.PSObject.Properties['Enabled'] -or
                [bool]$terminalTask.Settings.Enabled
            )
            $terminalArguments = @($terminalTask.Actions | ForEach-Object {
                if ($null -eq $_) { return "" }
                $argumentsProperty = $_.PSObject.Properties["Arguments"]
                if ($null -eq $argumentsProperty) { return "" }
                [string]$argumentsProperty.Value
            }) -join " "
            if ([string]$terminalTask.State -cne [string]$observation.State -or
                $terminalEnabled -ne [bool]$observation.Enabled -or
                $terminalArguments -cne [string]$observation.Arguments) {
                $quietConflicts.Add(
                    "$([string]$observation.TaskPath)$([string]$observation.TaskName)@state-changed-during-collision-check"
                )
                continue
            }
            if ($null -eq $finalInfo.NextRunTime -or
                [datetime]$finalInfo.NextRunTime -ne [datetime]$observation.NextRunTime) {
                $quietConflicts.Add(
                    "$([string]$observation.TaskPath)$([string]$observation.TaskName)@next-run-changed-during-collision-check"
                )
                continue
            }
            $finalStartInstant = ConvertTo-WeatherIntegrationLocalInstant `
                -Value ([datetime]$finalInfo.NextRunTime) `
                -Label "final protected merge NextRunTime"
            if ($finalStartInstant -le $finalNowInstant) {
                $quietConflicts.Add(
                    "$([string]$observation.TaskPath)$([string]$observation.TaskName)@ready-due-or-past"
                )
            }
        }
    }
    $allConflicts = @(
        @($activeNames) + @($quietConflicts) |
            Sort-Object -Unique
    )
    if ($allConflicts.Count -gt 0) {
        throw (
            "Integration preparation is blocked by enabled attempt or protected merge work: " +
            "$($allConflicts -join ', '). Close a failed attempt, retire a successful " +
            "historical task pair with retire_integration_attempt_tasks.ps1, or obtain " +
            "reviewed cleanup for a legacy non-attempt task before preparing another schedule."
        )
    }
}

function Invoke-WeatherIntegrationContainedPowerShellChild {
    param(
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{64}$")]
        [string]$ExpectedSha256,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$OutputDirectory,
        [Parameter(Mandatory = $true)][datetime]$HardStop
    )

    $resolvedScriptPath = Resolve-WeatherIntegrationPath -Path $ScriptPath
    if (-not (Test-Path -LiteralPath $resolvedScriptPath -PathType Leaf)) {
        throw "$Label script is missing: $resolvedScriptPath"
    }
    $powershellExe = Join-Path $PSHOME "powershell.exe"
    if (-not (Test-Path -LiteralPath $powershellExe -PathType Leaf)) {
        throw "Windows PowerShell executable is missing: $powershellExe"
    }
    $childStartLocal = Get-WeatherIntegrationScheduleLocalNow
    if ($HardStop -le $childStartLocal) {
        throw "$Label hard teardown boundary is not in the future."
    }
    $childRuntimeMaximumSeconds = [double](
        Get-WeatherIntegrationLocalElapsedSeconds `
            -StartLocal $childStartLocal `
            -EndLocal $HardStop `
            -StartLabel "$Label child start" `
            -EndLabel "$Label hard teardown boundary" `
            -TimeZone (Get-WeatherIntegrationScheduleTimeZone)
    )
    if ($childRuntimeMaximumSeconds -le 0) {
        throw "$Label hard teardown boundary has no positive elapsed-time budget."
    }
    if ($childRuntimeMaximumSeconds -gt
            [double]$script:WeatherIntegrationPreparationChildMaximumLifetimeSeconds) {
        throw "$Label hard teardown boundary exceeds the 5,700-second child-tree ceiling."
    }
    # Wall time remains an independent fail-early boundary, but it cannot be
    # the only lifetime clock: an operator/NTP clock rollback must not let a
    # child tree outlive the budget frozen immediately before launch.
    $childRuntimeStopwatch = [Diagnostics.Stopwatch]::StartNew()
    $resolvedOutputDirectory = Resolve-WeatherIntegrationPath -Path $OutputDirectory
    if (-not (Test-Path -LiteralPath $resolvedOutputDirectory -PathType Container)) {
        throw "$Label output directory is missing: $resolvedOutputDirectory"
    }
    $outputDirectoryItem = Get-Item -LiteralPath $resolvedOutputDirectory -Force
    if (($outputDirectoryItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "$Label output directory may not be a reparse point: $resolvedOutputDirectory"
    }
    $outputId = [guid]::NewGuid().ToString("N")
    $stdoutPath = Join-Path $resolvedOutputDirectory ".contained-child-${outputId}.stdout"
    $stderrPath = Join-Path $resolvedOutputDirectory ".contained-child-${outputId}.stderr"
    if ((Test-Path -LiteralPath $stdoutPath) -or
        (Test-Path -LiteralPath $stderrPath)) {
        throw "$Label unique redirected-output paths unexpectedly already exist."
    }
    $tokens = @(
        "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", $resolvedScriptPath
    ) + @($Arguments)
    $argumentString = ConvertTo-ScheduledTaskArgumentString -Tokens $tokens
    $job = $null
    $process = $null
    $scriptStream = $null
    $primaryFailure = $null
    $observedChildExitCode = $null
    try {
        # Hash and execute under one retained read-only handle. FileShare.Read
        # lets powershell.exe open the script but denies write/delete/rename,
        # so the path cannot be swapped after verification and before -File.
        $scriptStream = [IO.File]::Open(
            $resolvedScriptPath,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::Read
        )
        $openedScriptItem = Get-Item -LiteralPath $resolvedScriptPath -Force
        if ($openedScriptItem.PSIsContainer -or
            ($openedScriptItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            -not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$openedScriptItem.FullName) `
                -Right $resolvedScriptPath)) {
            throw "$Label script is not one stable regular file: $resolvedScriptPath"
        }
        $scriptSha = [Security.Cryptography.SHA256]::Create()
        try {
            $actualSha256 = (
                [BitConverter]::ToString($scriptSha.ComputeHash($scriptStream)) -replace '-', ''
            ).ToLowerInvariant()
        }
        finally { $scriptSha.Dispose() }
        if ($actualSha256 -ne $ExpectedSha256.ToLowerInvariant()) {
            throw "$Label changed after its immutable script binding was frozen."
        }

        $job = New-WeatherKillOnCloseJob
        $process = Start-WeatherProcessInJobWithRedirectedOutput `
            -Job $job `
            -FilePath $powershellExe `
            -ArgumentString $argumentString `
            -WorkingDirectory (Resolve-WeatherIntegrationPath -Path $WorkingDirectory) `
            -StandardOutputPath $stdoutPath `
            -StandardErrorPath $stderrPath
        while (-not $process.HasExited) {
            $stdoutLength = [int64]$process.GetStandardOutputLength()
            $stderrLength = [int64]$process.GetStandardErrorLength()
            if ($stdoutLength -gt
                    $script:WeatherIntegrationPreparationChildOutputMaximumBytes -or
                $stderrLength -gt
                    $script:WeatherIntegrationPreparationChildOutputMaximumBytes) {
                $job.TerminateAndWaitForEmpty(5000)
                $job = $null
                throw (
                    "$Label exceeded its bounded diagnostic-output limit; terminating " +
                    "its kill-on-close Job and observing an empty active-process count " +
                    "proved its child tree was terminated."
                )
            }
            if ((Get-WeatherIntegrationScheduleLocalNow) -ge $HardStop -or
                $childRuntimeStopwatch.Elapsed.TotalSeconds -ge
                    $childRuntimeMaximumSeconds) {
                $job.TerminateAndWaitForEmpty(5000)
                $job = $null
                throw (
                    "$Label reached its wall or monotonic hard teardown boundary; terminating its " +
                    "kill-on-close Job and observing an empty active-process count " +
                    "proved its child tree was terminated."
                )
            }
            Start-Sleep -Milliseconds 200
            $process.Refresh()
        }
        $process.WaitForExit()
        $observedChildExitCode = [int]$process.ExitCode
        # A successful top-level exit does not prove that it left no helper
        # process behind. Terminate the Job, wait until its authoritative
        # active-process count is zero, and close it before retaining the exact
        # diagnostic bytes so descendants can no longer mutate the held files.
        $job.TerminateAndWaitForEmpty(5000)
        $job = $null
        [byte[]]$stdoutBytes = $process.ReadStandardOutputBytes(
            $script:WeatherIntegrationPreparationChildOutputMaximumBytes
        )
        [byte[]]$stderrBytes = $process.ReadStandardErrorBytes(
            $script:WeatherIntegrationPreparationChildOutputMaximumBytes
        )
        $decoder = New-Object Text.UTF8Encoding($false, $true)
        try {
            $stdout = $decoder.GetString($stdoutBytes)
            $stderr = $decoder.GetString($stderrBytes)
        }
        catch {
            throw "$Label diagnostic output is not strict UTF-8: $($_.Exception.Message)"
        }
        foreach ($name in @("stdout", "stderr")) {
            $value = Get-Variable -Name $name -ValueOnly
            if ($value.Length -gt 0 -and $value[0] -eq [char]0xFEFF) {
                Set-Variable -Name $name -Value $value.Substring(1)
            }
        }
        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            $stdoutSha256 = (
                [BitConverter]::ToString($sha.ComputeHash($stdoutBytes)) -replace '-', ''
            ).ToLowerInvariant()
            $sha.Initialize()
            $stderrSha256 = (
                [BitConverter]::ToString($sha.ComputeHash($stderrBytes)) -replace '-', ''
            ).ToLowerInvariant()
        }
        finally { $sha.Dispose() }
        $stdoutLines = @($stdout -split "`r?`n" | Where-Object { $_ -ne "" })
        $stderrLines = @($stderr -split "`r?`n" | Where-Object { $_ -ne "" })
        return [pscustomobject]@{
            ScriptPath = $resolvedScriptPath
            ScriptSha256 = $actualSha256
            ExitCode = [int]$observedChildExitCode
            Output = @($stdoutLines + $stderrLines)
            Stdout = $stdout
            Stderr = $stderr
            StdoutSha256 = $stdoutSha256
            StderrSha256 = $stderrSha256
            StdoutLength = [int]$stdoutBytes.Length
            StderrLength = [int]$stderrBytes.Length
            ProcessId = [int]$process.Id
            Containment = "WINDOWS_JOB_KILL_ON_CLOSE_RETAINED_OUTPUT"
        }
    }
    catch {
        $failure = $_
        if ($null -ne $observedChildExitCode -and
            [int]$observedChildExitCode -ne 0) {
            $postExitFailure = $failure
            $combinedException = [InvalidOperationException]::new(
                (
                    "$Label child exited with code $observedChildExitCode; " +
                    "post-exit containment or evidence validation also failed: " +
                    $postExitFailure.Exception.Message
                ),
                $postExitFailure.Exception
            )
            $combinedException.Data["weather_observed_child_exit_code"] =
                [int]$observedChildExitCode
            $combinedException.Data["weather_post_exit_failure"] =
                $postExitFailure.Exception.Message
            $failure = [Management.Automation.ErrorRecord]::new(
                $combinedException,
                "WeatherIntegrationContainedChildPostExitFailure",
                [Management.Automation.ErrorCategory]::OperationStopped,
                $resolvedScriptPath
            )
        }
        if ($job) {
            try {
                $job.TerminateAndWaitForEmpty(5000)
                $job = $null
            }
            catch {
                $drainMessage = (
                    "$Label Job drain after primary failure also failed: " +
                    $_.Exception.Message
                )
                $failure.Exception.Data["weather_drain_failure"] = $drainMessage
                Write-Warning $drainMessage -WarningAction Continue
            }
        }
        $primaryFailure = $failure
        throw $failure
    }
    finally {
        $cleanupFailures = New-Object System.Collections.Generic.List[string]
        if ($job) {
            try { $job.Dispose() }
            catch { $cleanupFailures.Add("Job handle: $($_.Exception.Message)") }
        }
        if ($process) {
            try { $process.Dispose() }
            catch {
                $cleanupFailures.Add(
                    "retained process/output handles: $($_.Exception.Message)"
                )
            }
        }
        if ($scriptStream) {
            try { $scriptStream.Dispose() }
            catch { $cleanupFailures.Add("verified script handle: $($_.Exception.Message)") }
        }
        foreach ($path in @($stdoutPath, $stderrPath)) {
            try {
                if (Test-Path -LiteralPath $path) {
                    $item = Get-Item -LiteralPath $path -Force
                    if (-not $item.PSIsContainer -and
                        ($item.Attributes -band
                            [IO.FileAttributes]::ReparsePoint) -eq 0) {
                        Remove-Item -LiteralPath $path -Force -ErrorAction Stop
                    }
                    else {
                        throw "$Label owned redirected-output path changed type before cleanup: $path"
                    }
                }
            }
            catch { $cleanupFailures.Add("redirected-output file ${path}: $($_.Exception.Message)") }
        }
        if ($cleanupFailures.Count -ne 0) {
            $cleanupMessage = "$Label cleanup failed: $($cleanupFailures -join ' | ')"
            if ($null -ne $primaryFailure) {
                $primaryFailure.Exception.Data["weather_cleanup_failure"] = $cleanupMessage
                Write-Warning $cleanupMessage -WarningAction Continue
            }
            elseif ($null -ne $observedChildExitCode -and
                [int]$observedChildExitCode -ne 0) {
                # The caller owns the nonzero child result and its diagnostics;
                # cleanup damage must not replace that primary failure signal.
                Write-Warning $cleanupMessage -WarningAction Continue
            }
            else { throw $cleanupMessage }
        }
    }
}

function Get-WeatherIntegrationChildDiagnosticExcerpt {
    param(
        [Parameter(Mandatory = $true)][object]$ChildResult,
        [ValidateRange(128, 4096)][int]$MaximumCharacters = 2048
    )

    $text = (@(
        $ChildResult.Output |
            ForEach-Object { ([string]$_).Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Select-Object -Last 12
    ) -join " | ").Trim()
    if ([string]::IsNullOrWhiteSpace($text)) { return "no child diagnostic output" }
    if ($text.Length -gt $MaximumCharacters) {
        return $text.Substring($text.Length - $MaximumCharacters, $MaximumCharacters)
    }
    return $text
}

function Assert-WeatherIntegrationCreatorPreflightPlan {
    param(
        [Parameter(Mandatory = $true)][object]$EvidenceSnapshot,
        [Parameter(Mandatory = $true)][string]$AttemptRoot,
        [Parameter(Mandatory = $true)][string]$AttemptId,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$WorktreeRoot,
        [Parameter(Mandatory = $true)][string]$BranchRef,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{40}$")]
        [string]$ExpectedTip,
        [Parameter(Mandatory = $true)][datetime]$SuiteAtLocal,
        [Parameter(Mandatory = $true)][datetime]$MergeAtLocal,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{40}$")]
        [string]$ProductionBaseline,
        [Parameter(Mandatory = $true)][string]$OriginUrl,
        [Parameter(Mandatory = $true)][string]$RepairClass,
        [Parameter(Mandatory = $true)][bool]$RequireLiveSdkContract,
        [Parameter(Mandatory = $true)][string]$PreparationIntentPath,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{64}$")]
        [string]$ExpectedPreparationIntentSha256,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{64}$")]
        [string]$ExpectedPreparationAuthorizationSha256,
        [Parameter(Mandatory = $true)][string]$CreatorPath,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{64}$")]
        [string]$ExpectedCreatorSha256,
        [Parameter(Mandatory = $true)][string]$PreparationContractPath,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{64}$")]
        [string]$ExpectedPreparationContractSha256,
        [ValidateRange(0, 1000000)][int]$ExpectedTestFileCount = 0,
        [ValidateRange(0, 100000)][int]$ExpectedChunkCount = 0,
        [ValidatePattern("^$|^[0-9a-fA-F]{64}$")]
        [string]$ExpectedTestInventorySha256 = "",
        [ValidateRange(0, 1000000)][int]$ExpectedPythonFileCount = 0,
        [ValidatePattern("^$|^[0-9a-fA-F]{64}$")]
        [string]$ExpectedPythonInventorySha256 = "",
        [ValidateRange(0, 1000000)][int]$ExpectedPowerShellFileCount = 0,
        [ValidatePattern("^$|^[0-9a-fA-F]{64}$")]
        [string]$ExpectedPowerShellInventorySha256 = "",
        [Parameter(Mandatory = $true)]
        [string]$ExpectedTrackedWorktreeSchema,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{64}$")]
        [string]$ExpectedTrackedWorktreeSha256,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 20000)][int]$ExpectedTrackedWorktreeFileCount,
        [Parameter(Mandatory = $true)]
        [ValidateRange(0, 2147483648)]
        [long]$ExpectedTrackedWorktreeTotalBytes,
        [Parameter(Mandatory = $true)]
        [ValidateRange(0, 20000)][int]$ExpectedTrackedWorktreeLfsFileCount
    )

    $canonicalAttemptRoot = Resolve-WeatherIntegrationPath -Path $AttemptRoot
    $canonicalPreparationRoot = Resolve-WeatherIntegrationPath -Path (
        $canonicalAttemptRoot + ".preparation"
    )
    $canonicalPlanPath = Resolve-WeatherIntegrationPath -Path (
        Join-Path $canonicalPreparationRoot "creator-preflight-plan.json"
    )
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$EvidenceSnapshot.Path) -Right $canonicalPlanPath)) {
        throw "Creator preflight evidence is not the canonical immutable plan path."
    }
    if ([string]$EvidenceSnapshot.Sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Creator preflight evidence has no exact retained SHA-256."
    }

    $plan = $EvidenceSnapshot.Payload
    Assert-WeatherIntegrationRequiredProperties `
        -Object $plan `
        -Names @(
            "schema", "status", "created_at_local", "attempt_id",
            "attempt_root", "preparation_root", "preflight_plan_path",
            "repo_root", "worktree_root", "branch_ref", "expected_tip",
            "suite_at_local", "suite_at_utc", "merge_at_local",
            "merge_at_utc", "schedule_time_zone", "production_baseline",
            "origin_url", "expected_test_file_count", "expected_chunk_count",
            "expected_test_inventory_sha256", "expected_python_file_count",
            "expected_python_inventory_sha256",
            "expected_powershell_file_count",
            "expected_powershell_inventory_sha256",
            "expected_tracked_worktree_schema",
            "expected_tracked_worktree_sha256",
            "expected_tracked_worktree_file_count",
            "expected_tracked_worktree_total_bytes",
            "expected_tracked_worktree_lfs_file_count",
            "repair_class", "require_live_sdk_contract", "creator",
            "preparation_contract",
            "preparation", "prearming_qualification_required",
            "prearming_qualification_present", "safety"
        ) `
        -Label "Integration creator preflight plan"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $plan.creator -Names @("path", "sha256") `
        -Label "Integration creator preflight plan creator binding"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $plan.preparation_contract -Names @("path", "sha256") `
        -Label "Integration creator preflight plan contract binding"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $plan.preparation `
        -Names @(
            "intent_path", "intent_sha256", "execution_authorization_sha256"
        ) `
        -Label "Integration creator preflight plan preparation binding"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $plan.safety `
        -Names @(
            "authority", "credential_value_access_authorized",
            "live_exchange_mutation_authorized"
        ) `
        -Label "Integration creator preflight plan safety boundary"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $plan `
        -Names @(
            "require_live_sdk_contract", "prearming_qualification_required",
            "prearming_qualification_present"
        ) `
        -Label "Integration creator preflight plan"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $plan.safety `
        -Names @(
            "credential_value_access_authorized",
            "live_exchange_mutation_authorized"
        ) `
        -Label "Integration creator preflight plan safety boundary"

    $planSchedule = [pscustomobject]@{
        time_zone = $plan.schedule_time_zone
        suite_at_local = [string]$plan.suite_at_local
        suite_at_utc = [string]$plan.suite_at_utc
        merge_at_local = [string]$plan.merge_at_local
        merge_at_utc = [string]$plan.merge_at_utc
    }
    $validatedPlanSchedule = Assert-WeatherIntegrationScheduleEvidence `
        -Schedule $planSchedule -Label "Integration creator preflight schedule"
    if ([datetime]$validatedPlanSchedule.SuiteAtLocal -ne
            [datetime](Assert-WeatherIntegrationLocalScheduleTime `
                -Value $SuiteAtLocal -Label "expected creator suite time") -or
        [datetime]$validatedPlanSchedule.MergeAtLocal -ne
            [datetime](Assert-WeatherIntegrationLocalScheduleTime `
                -Value $MergeAtLocal -Label "expected creator merge time")) {
        throw "Integration creator preflight schedule differs from its invocation."
    }

    $testFileCount = [int]$plan.expected_test_file_count
    $chunkCount = [int]$plan.expected_chunk_count
    $pythonFileCount = [int]$plan.expected_python_file_count
    $powerShellFileCount = [int]$plan.expected_powershell_file_count
    $trackedFileCount = [int]$plan.expected_tracked_worktree_file_count
    $trackedTotalBytes = [long]$plan.expected_tracked_worktree_total_bytes
    $trackedLfsFileCount = [int]$plan.expected_tracked_worktree_lfs_file_count
    if ([string]$plan.schema -cne
            $script:WeatherIntegrationCreatorPreflightPlanSchema -or
        [string]$plan.status -cne "PREFLIGHT_READY" -or
        [string]::IsNullOrWhiteSpace([string]$plan.created_at_local) -or
        [string]$plan.attempt_id -cne $AttemptId -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$plan.attempt_root) -Right $canonicalAttemptRoot) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$plan.preparation_root) `
            -Right $canonicalPreparationRoot) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$plan.preflight_plan_path) `
            -Right $canonicalPlanPath) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$plan.repo_root) -Right $RepositoryRoot) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$plan.worktree_root) -Right $WorktreeRoot) -or
        [string]$plan.branch_ref -cne $BranchRef -or
        [string]$plan.expected_tip -cne $ExpectedTip.ToLowerInvariant() -or
        [string]$plan.suite_at_local -cne $SuiteAtLocal.ToString("o") -or
        [string]$plan.merge_at_local -cne $MergeAtLocal.ToString("o") -or
        [string]$plan.production_baseline -cne
            $ProductionBaseline.ToLowerInvariant() -or
        [string]$plan.origin_url -cne $OriginUrl -or
        [string]$plan.repair_class -cne $RepairClass -or
        [bool]$plan.require_live_sdk_contract -ne $RequireLiveSdkContract -or
        $testFileCount -le 0 -or $chunkCount -ne
            [int][math]::Ceiling($testFileCount / 20.0) -or
        [string]$plan.expected_test_inventory_sha256 -cnotmatch
            '^[0-9a-f]{64}$' -or
        $pythonFileCount -le 0 -or
        [string]$plan.expected_python_inventory_sha256 -cnotmatch
            '^[0-9a-f]{64}$' -or
        $powerShellFileCount -le 0 -or
        [string]$plan.expected_powershell_inventory_sha256 -cnotmatch
            '^[0-9a-f]{64}$' -or
        [string]$plan.expected_tracked_worktree_schema -cne
            "tracked_worktree_content_fingerprint_v1" -or
        [string]$plan.expected_tracked_worktree_sha256 -cnotmatch
            '^[0-9a-f]{64}$' -or
        $trackedFileCount -le 0 -or $trackedFileCount -gt 20000 -or
        $trackedTotalBytes -lt 0 -or $trackedTotalBytes -gt 2147483648 -or
        $trackedLfsFileCount -lt 0 -or
        $trackedLfsFileCount -gt $trackedFileCount -or
        ($ExpectedTestFileCount -gt 0 -and
            $testFileCount -ne $ExpectedTestFileCount) -or
        ($ExpectedChunkCount -gt 0 -and $chunkCount -ne $ExpectedChunkCount) -or
        (-not [string]::IsNullOrWhiteSpace($ExpectedTestInventorySha256) -and
            [string]$plan.expected_test_inventory_sha256 -cne
                $ExpectedTestInventorySha256.ToLowerInvariant()) -or
        ($ExpectedPythonFileCount -gt 0 -and
            $pythonFileCount -ne $ExpectedPythonFileCount) -or
        (-not [string]::IsNullOrWhiteSpace($ExpectedPythonInventorySha256) -and
            [string]$plan.expected_python_inventory_sha256 -cne
                $ExpectedPythonInventorySha256.ToLowerInvariant()) -or
        ($ExpectedPowerShellFileCount -gt 0 -and
            $powerShellFileCount -ne $ExpectedPowerShellFileCount) -or
        (-not [string]::IsNullOrWhiteSpace(
                $ExpectedPowerShellInventorySha256) -and
            [string]$plan.expected_powershell_inventory_sha256 -cne
                $ExpectedPowerShellInventorySha256.ToLowerInvariant()) -or
        [string]$plan.expected_tracked_worktree_schema -cne
            $ExpectedTrackedWorktreeSchema -or
        [string]$plan.expected_tracked_worktree_sha256 -cne
            $ExpectedTrackedWorktreeSha256.ToLowerInvariant() -or
        $trackedFileCount -ne $ExpectedTrackedWorktreeFileCount -or
        $trackedTotalBytes -ne $ExpectedTrackedWorktreeTotalBytes -or
        $trackedLfsFileCount -ne $ExpectedTrackedWorktreeLfsFileCount -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$plan.creator.path) -Right $CreatorPath) -or
        [string]$plan.creator.sha256 -cne
            $ExpectedCreatorSha256.ToLowerInvariant() -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$plan.preparation_contract.path) `
            -Right $PreparationContractPath) -or
        [string]$plan.preparation_contract.sha256 -cne
            $ExpectedPreparationContractSha256.ToLowerInvariant() -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$plan.preparation.intent_path) `
            -Right $PreparationIntentPath) -or
        [string]$plan.preparation.intent_sha256 -cne
            $ExpectedPreparationIntentSha256.ToLowerInvariant() -or
        [string]$plan.preparation.execution_authorization_sha256 -cne
            $ExpectedPreparationAuthorizationSha256.ToLowerInvariant() -or
        -not [bool]$plan.prearming_qualification_required -or
        [bool]$plan.prearming_qualification_present -or
        [string]$plan.safety.authority -cne
            "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$plan.safety.credential_value_access_authorized -or
        [bool]$plan.safety.live_exchange_mutation_authorized) {
        throw "Creator preflight plan did not bind the exact prepared attempt."
    }

    try {
        [DateTimeOffset]::Parse(
            [string]$plan.created_at_local,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        ) | Out-Null
    }
    catch {
        throw "Creator preflight plan has an invalid creation timestamp."
    }
    return [pscustomobject]@{
        Path = $canonicalPlanPath
        Sha256 = [string]$EvidenceSnapshot.Sha256
        Plan = $plan
    }
}

function Assert-WeatherIntegrationPreparationSchedule {
    param(
        [Parameter(Mandatory = $true)][datetime]$SuiteAtLocal,
        [Parameter(Mandatory = $true)][datetime]$MergeAtLocal,
        [datetime]$Now = (Get-WeatherIntegrationScheduleLocalNow),
        [ValidateRange(1, 120)][int]$MinimumLeadMinutes = 10,
        [TimeZoneInfo]$TimeZone = (Get-WeatherIntegrationScheduleTimeZone)
    )

    $suiteAt = Assert-WeatherIntegrationLocalScheduleTime `
        -Value $SuiteAtLocal -Label "SuiteAtLocal" -TimeZone $TimeZone
    $mergeAt = Assert-WeatherIntegrationLocalScheduleTime `
        -Value $MergeAtLocal -Label "MergeAtLocal" -TimeZone $TimeZone
    $localNow = Assert-WeatherIntegrationLocalScheduleTime `
        -Value $Now -Label "Now" -TimeZone $TimeZone
    $suiteMinute = ($suiteAt.Hour * 60) + $suiteAt.Minute
    $mergeMinute = ($mergeAt.Hour * 60) + $mergeAt.Minute
    $leadSeconds = Get-WeatherIntegrationLocalElapsedSeconds `
        -StartLocal $localNow -EndLocal $suiteAt `
        -StartLabel "Now" -EndLabel "SuiteAtLocal" -TimeZone $TimeZone

    if ($leadSeconds -lt ($MinimumLeadMinutes * 60)) {
        throw "SuiteAtLocal must retain at least $MinimumLeadMinutes minutes of preparation lead time."
    }
    if ($suiteAt.Date -ne $mergeAt.Date) {
        throw "SuiteAtLocal and MergeAtLocal must be on the same local calendar day."
    }
    if ($suiteMinute -lt 30 -or $suiteMinute -ge (9 * 60)) {
        throw "SuiteAtLocal must be in the admitted 00:30-09:00 local host window."
    }
    if ($mergeMinute -lt 60 -or $mergeMinute -ge 220) {
        throw "MergeAtLocal must be in the guarded 01:00-03:40 quiet window."
    }
    $suiteToMergeSeconds = Get-WeatherIntegrationLocalElapsedSeconds `
        -StartLocal $suiteAt -EndLocal $mergeAt `
        -StartLabel "SuiteAtLocal" -EndLabel "MergeAtLocal" -TimeZone $TimeZone
    if ($suiteToMergeSeconds -lt 1800) {
        throw "MergeAtLocal must remain at least 30 minutes after SuiteAtLocal."
    }

    $scheduleEvidence = if ([string]$TimeZone.Id -ceq
        $script:WeatherIntegrationScheduleTimeZoneId) {
        Get-WeatherIntegrationScheduleEvidence `
            -SuiteAtLocal $suiteAt -MergeAtLocal $mergeAt
    }
    else { $null }
    return [pscustomobject][ordered]@{
        suite_at_local = $suiteAt
        suite_at_utc = if ($null -eq $scheduleEvidence) { $null } else {
            [string]$scheduleEvidence.suite_at_utc
        }
        merge_at_local = $mergeAt
        merge_at_utc = if ($null -eq $scheduleEvidence) { $null } else {
            [string]$scheduleEvidence.merge_at_utc
        }
        time_zone = if ($null -eq $scheduleEvidence) { $null } else {
            $scheduleEvidence.time_zone
        }
        checked_at_local = $localNow
        minimum_lead_minutes = $MinimumLeadMinutes
    }
}

function Assert-WeatherIntegrationPrearmingQualificationWindow {
    param(
        [Parameter(Mandatory = $true)][datetime]$SuiteAtLocal,
        [datetime]$Now = (Get-WeatherIntegrationScheduleLocalNow),
        [TimeZoneInfo]$TimeZone = (Get-WeatherIntegrationScheduleTimeZone)
    )

    $suiteAt = Assert-WeatherIntegrationLocalScheduleTime `
        -Value $SuiteAtLocal -Label "SuiteAtLocal" -TimeZone $TimeZone
    $localNow = Assert-WeatherIntegrationLocalScheduleTime `
        -Value $Now -Label "Now" -TimeZone $TimeZone
    $localMinute = ($localNow.Hour * 60) + $localNow.Minute
    if ($localMinute -lt 30 -or $localMinute -ge (9 * 60)) {
        throw "Pre-arming qualification must start inside the 00:30-09:00 heavy-work window."
    }
    if ($suiteAt.Date -le $localNow.Date) {
        throw "Pre-arming qualification must precede the attempt's local calendar day."
    }
    $hardStop = Assert-WeatherIntegrationLocalScheduleTime `
        -Value $localNow.Date.AddHours(9) -Label "qualification hard stop" `
        -TimeZone $TimeZone
    $requiredCurrentWindowSeconds =
        [int]$script:WeatherIntegrationPrearmingPlanningCeilingSeconds +
        [int]$script:WeatherIntegrationPrearmingSafetyMarginSeconds
    $remainingCurrentWindowSeconds = Get-WeatherIntegrationLocalElapsedSeconds `
        -StartLocal $localNow -EndLocal $hardStop `
        -StartLabel "Now" -EndLabel "qualification hard stop" `
        -TimeZone $TimeZone
    if ($remainingCurrentWindowSeconds -lt $requiredCurrentWindowSeconds) {
        throw (
            "Pre-arming qualification requires at least " +
            "$requiredCurrentWindowSeconds seconds before the 09:00 hard stop."
        )
    }
    return [pscustomobject][ordered]@{
        checked_at_local = $localNow
        hard_stop_local = $hardStop
        suite_at_local = $suiteAt
        minimum_calendar_margin = "NEXT_LOCAL_DAY"
        required_current_window_seconds = $requiredCurrentWindowSeconds
        remaining_current_window_seconds = [math]::Floor(
            $remainingCurrentWindowSeconds
        )
    }
}

function Assert-WeatherIntegrationPrearmingScheduleFeasibility {
    param(
        [Parameter(Mandatory = $true)][datetime]$SuiteAtLocal,
        [Parameter(Mandatory = $true)][datetime]$MergeAtLocal,
        [ValidateRange(0, 86400)][double]$MeasuredDurationSeconds = 0,
        [TimeZoneInfo]$TimeZone = (Get-WeatherIntegrationScheduleTimeZone)
    )

    $suiteAt = Assert-WeatherIntegrationLocalScheduleTime `
        -Value $SuiteAtLocal -Label "SuiteAtLocal" -TimeZone $TimeZone
    $mergeAt = Assert-WeatherIntegrationLocalScheduleTime `
        -Value $MergeAtLocal -Label "MergeAtLocal" -TimeZone $TimeZone
    $observedCeilingSeconds = [math]::Ceiling($MeasuredDurationSeconds)
    $runtimeCeilingSeconds = [math]::Max(
        [int]$script:WeatherIntegrationPrearmingPlanningCeilingSeconds,
        [int]$observedCeilingSeconds
    )
    $requiredRuntimeSeconds = [int]$runtimeCeilingSeconds +
        [int]$script:WeatherIntegrationPrearmingSafetyMarginSeconds
    $launchGraceSeconds = [int]$script:WeatherIntegrationSchedulerLaunchGraceSeconds
    $requiredScheduleSeconds = $requiredRuntimeSeconds + $launchGraceSeconds
    $hardStop = Assert-WeatherIntegrationLocalScheduleTime `
        -Value $suiteAt.Date.AddHours(9) -Label "suite hard stop" `
        -TimeZone $TimeZone
    $suiteToMergeSeconds = [int][math]::Floor(
        (Get-WeatherIntegrationLocalElapsedSeconds `
            -StartLocal $suiteAt -EndLocal $mergeAt `
            -StartLabel "SuiteAtLocal" -EndLabel "MergeAtLocal" `
            -TimeZone $TimeZone)
    )
    $suiteToHardStopSeconds = [int][math]::Floor(
        (Get-WeatherIntegrationLocalElapsedSeconds `
            -StartLocal $suiteAt -EndLocal $hardStop `
            -StartLabel "SuiteAtLocal" -EndLabel "suite hard stop" `
            -TimeZone $TimeZone)
    )
    if ($suiteToMergeSeconds -lt $requiredScheduleSeconds -or
        $suiteToHardStopSeconds -lt $requiredScheduleSeconds -or
        $MeasuredDurationSeconds -gt
            [double]$script:WeatherIntegrationBoundedSuiteMaximumRuntimeSeconds) {
        throw (
            "Attempt schedule cannot contain the repeated preflight/full suite: " +
            "execution_required=${requiredRuntimeSeconds}s " +
            "launch_grace=${launchGraceSeconds}s " +
            "schedule_required=${requiredScheduleSeconds}s " +
            "suite_to_merge=${suiteToMergeSeconds}s " +
            "suite_to_09:00=${suiteToHardStopSeconds}s."
        )
    }
    return [pscustomobject][ordered]@{
        measured_duration_seconds = [math]::Round($MeasuredDurationSeconds, 3)
        planning_ceiling_seconds = [int]$script:WeatherIntegrationPrearmingPlanningCeilingSeconds
        safety_margin_seconds = [int]$script:WeatherIntegrationPrearmingSafetyMarginSeconds
        required_runtime_seconds = $requiredRuntimeSeconds
        launch_grace_seconds = $launchGraceSeconds
        required_schedule_seconds = $requiredScheduleSeconds
        bounded_suite_max_runtime_seconds =
            [int]$script:WeatherIntegrationBoundedSuiteMaximumRuntimeSeconds
        suite_wrapper_teardown_allowance_seconds =
            [int]$script:WeatherIntegrationSuiteWrapperTeardownAllowanceSeconds
        suite_task_execution_time_limit_seconds =
            [int]$script:WeatherIntegrationSuiteTaskExecutionLimitSeconds
        suite_to_merge_seconds = $suiteToMergeSeconds
        suite_to_hard_stop_seconds = $suiteToHardStopSeconds
        eligible = $true
    }
}

function Assert-WeatherIntegrationGitControlSafety {
    param(
        [Parameter(Mandatory = $true)][string[]]$RepositoryRoots
    )

    $blockedExact = @(
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_REPLACE_REF_BASE", "GIT_NAMESPACE", "GIT_SHALLOW_FILE",
        "GIT_CONFIG", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS",
        "GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM"
    )
    $ambient = @(Get-ChildItem Env: | Where-Object {
        $_.Name -cin $blockedExact -or
        $_.Name -match '^GIT_CONFIG_(?:KEY|VALUE)_[0-9]+$'
    })
    if ($ambient.Count -ne 0) {
        throw "Ambient Git control variables are forbidden: $(@($ambient.Name | Sort-Object) -join ', ')"
    }
    foreach ($rootValue in $RepositoryRoots) {
        $root = Resolve-WeatherIntegrationPath -Path $rootValue
        $shallowQuery = Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $root -Arguments @("rev-parse", "--is-shallow-repository") `
            -Label "integration preparation shallow-repository query"
        $shallowRows = @($shallowQuery.StdoutLines)
        if ($shallowRows.Count -ne 1 -or
            [string]$shallowRows[0] -cne "false") {
            throw "Integration preparation requires a non-shallow repository: $root"
        }
        $replaceQuery = Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $root `
            -Arguments @("for-each-ref", "--format=%(refname)", "refs/replace") `
            -Label "integration preparation replace-ref query"
        $replaceRefs = @($replaceQuery.StdoutLines)
        if ($replaceRefs.Count -ne 0) {
            throw "Git replace refs are forbidden during integration preparation: $root"
        }
        foreach ($gitPathName in @("info/grafts", "objects/info/alternates")) {
            $gitPathQuery = Invoke-WeatherIntegrationCheckedLocalGit `
                -Root $root `
                -Arguments @("rev-parse", "--git-path", $gitPathName) `
                -Label "integration preparation Git-control-path query"
            $gitPathRows = @($gitPathQuery.StdoutLines)
            if ($gitPathRows.Count -ne 1) {
                throw "Could not resolve Git control path $gitPathName for $root"
            }
            $gitControlPathValue = [string]$gitPathRows[0]
            if (-not [IO.Path]::IsPathRooted($gitControlPathValue)) {
                $gitControlPathValue = Join-Path $root $gitControlPathValue
            }
            $gitControlPath = Resolve-WeatherIntegrationPath -Path $gitControlPathValue
            if (Test-Path -LiteralPath $gitControlPath) {
                throw "Git $gitPathName override is forbidden during integration preparation: $root"
            }
        }
    }
}

function Get-WeatherIntegrationTopicBranchName {
    param(
        [Parameter(Mandatory = $true)][string]$BranchRef
    )

    if ($BranchRef -cmatch '^origin/(?<branch>[A-Za-z0-9][A-Za-z0-9._/-]{0,192})$') {
        $branchName = [string]$Matches.branch
    }
    else {
        throw "BranchRef must be an exact origin/<topic-branch> reference."
    }
    if ($branchName.Contains("..") -or $branchName.Contains("@{") -or
        $branchName.EndsWith(".") -or $branchName.EndsWith("/") -or
        $branchName.Contains("//") -or $branchName.EndsWith(".lock")) {
        throw "BranchRef contains a Git-unsafe topic branch name."
    }
    if ($branchName -cin @("master", "main")) {
        throw "BranchRef must name a topic branch, never a production branch."
    }
    return $branchName
}

function Resolve-WeatherIntegrationRemoteTipRows {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$Rows,
        [Parameter(Mandatory = $true)][string]$ExpectedRemoteRef,
        [switch]$AllowMissing
    )

    $matches = New-Object System.Collections.Generic.List[string]
    foreach ($row in @($Rows)) {
        $columns = @(([string]$row).Trim() -split '\s+')
        if ($columns.Count -eq 2 -and [string]$columns[1] -ceq $ExpectedRemoteRef) {
            $matches.Add(([string]$columns[0]).ToLowerInvariant())
        }
    }
    if ($matches.Count -eq 0 -and $AllowMissing) {
        return $null
    }
    if ($matches.Count -ne 1 -or [string]$matches[0] -notmatch '^[0-9a-f]{40}$') {
        throw "Remote topic lookup must resolve exactly one full commit for $ExpectedRemoteRef."
    }
    return ([string]$matches[0])
}
