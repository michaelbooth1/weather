Set-StrictMode -Version Latest

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

function Assert-WeatherIntegrationNoActiveAttemptCollision {
    param(
        [Parameter(Mandatory = $true)][datetime]$SuiteAtLocal,
        [Parameter(Mandatory = $true)][datetime]$MergeAtLocal,
        [AllowEmptyString()][string]$AttemptId = ""
    )

    $ownTaskNames = if ([string]::IsNullOrWhiteSpace($AttemptId)) { @() } else {
        @("WeatherIntegrationSuite_$AttemptId", "WeatherIntegrationMerge_$AttemptId")
    }
    $tasks = @(Get-ScheduledTask -ErrorAction Stop | Where-Object {
        $isOwnExactTask = ([string]$_.TaskPath -ieq "\" -and
            $ownTaskNames -icontains [string]$_.TaskName)
        [string]$_.TaskName -match '^WeatherIntegration(?:Suite|Merge)_' -and
        -not $isOwnExactTask
    })
    $active = New-Object System.Collections.Generic.List[string]
    $now = Get-Date
    foreach ($task in $tasks) {
        $taskState = [string]$task.State
        $settingsEnabled = ($null -eq $task.Settings.PSObject.Properties['Enabled'] -or
            [bool]$task.Settings.Enabled)
        if ($taskState -in @("Running", "Queued") -or
            $taskState -notin @("Ready", "Disabled")) {
            $active.Add("$([string]$task.TaskPath)$([string]$task.TaskName)@$taskState")
            continue
        }
        if ($taskState -eq "Disabled" -or -not $settingsEnabled) { continue }
        $info = Get-ScheduledTaskInfo `
            -TaskName ([string]$task.TaskName) `
            -TaskPath ([string]$task.TaskPath) `
            -ErrorAction Stop
        if ($null -ne $info.NextRunTime -and [datetime]$info.NextRunTime -gt $now) {
            $active.Add("$([string]$task.TaskPath)$([string]$task.TaskName)")
        }
    }
    if ($active.Count -gt 0) {
        $names = @($active | Sort-Object -Unique)
        throw "An enabled integration attempt already exists: $($names -join ', '). Close it before preparing another schedule."
    }

    $quietConflicts = New-Object System.Collections.Generic.List[string]
    foreach ($task in @(Get-ScheduledTask -ErrorAction Stop)) {
        if ([string]$task.TaskPath -ieq "\" -and
            $ownTaskNames -icontains [string]$task.TaskName) { continue }
        $arguments = @($task.Actions | ForEach-Object { [string]$_.Arguments }) -join " "
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
        if ($null -eq $info.NextRunTime) { continue }
        $conflictStart = [datetime]$info.NextRunTime
        # The sensitive driver can spend the full quiet-merge recovery budget
        # after its trigger; treating it as a point event allowed a proposed
        # suite to start while its publish/recovery work was still active.
        $conflictEnd = if ($isSensitiveDriver) {
            $conflictStart.AddHours(4)
        }
        else { $conflictStart }
        if ($isQuietMerge) {
            $settleSeconds = 300
            $rollbackSeconds = 1200
            if ($arguments -match '(?i)-SettleSeconds\s+(\d+)') {
                $settleSeconds = [int]$Matches[1]
            }
            if ($arguments -match '(?i)-RollbackRecoverySeconds\s+(\d+)') {
                $rollbackSeconds = [int]$Matches[1]
            }
            $conflictEnd = $conflictStart.AddSeconds(
                [math]::Max(
                    $settleSeconds + 240,
                    $settleSeconds + $rollbackSeconds + 60
                )
            )
        }
        if ($conflictStart -le $MergeAtLocal -and
            $SuiteAtLocal -le $conflictEnd) {
            $quietConflicts.Add(
                "$([string]$task.TaskPath)$([string]$task.TaskName)@$($conflictStart.ToString('o'))"
            )
        }
    }
    if ($quietConflicts.Count -gt 0) {
        throw "Prepared integration schedule overlaps protected merge work: $($quietConflicts -join ', ')."
    }
}

function Invoke-WeatherIntegrationPowerShellChild {
    param(
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{64}$")]
        [string]$ExpectedSha256,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $resolvedScriptPath = Resolve-WeatherIntegrationPath -Path $ScriptPath
    if (-not (Test-Path -LiteralPath $resolvedScriptPath -PathType Leaf)) {
        throw "$Label script is missing: $resolvedScriptPath"
    }
    $actualSha256 = Get-WeatherIntegrationFileSha256 -Path $resolvedScriptPath
    if ($actualSha256 -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "$Label changed after its immutable script binding was frozen."
    }
    $powershellExe = Join-Path $PSHOME "powershell.exe"
    if (-not (Test-Path -LiteralPath $powershellExe -PathType Leaf)) {
        throw "Windows PowerShell executable is missing: $powershellExe"
    }

    # Several canonical integration scripts intentionally call `exit`. Keep
    # that exit inside a child process so it becomes evidence for this caller
    # instead of terminating the preparation host before cleanup/closure.
    $priorErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& $powershellExe `
            -NoProfile `
            -NonInteractive `
            -ExecutionPolicy Bypass `
            -File $resolvedScriptPath `
            @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $priorErrorActionPreference
    }
    return [pscustomobject]@{
        ScriptPath = $resolvedScriptPath
        ScriptSha256 = $actualSha256
        ExitCode = [int]$exitCode
        Output = @($output | ForEach-Object { [string]$_ })
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

function Assert-WeatherIntegrationPreparationSchedule {
    param(
        [Parameter(Mandatory = $true)][datetime]$SuiteAtLocal,
        [Parameter(Mandatory = $true)][datetime]$MergeAtLocal,
        [datetime]$Now = (Get-Date),
        [ValidateRange(1, 120)][int]$MinimumLeadMinutes = 10
    )

    $suiteAt = Assert-WeatherIntegrationLocalScheduleTime `
        -Value $SuiteAtLocal -Label "SuiteAtLocal"
    $mergeAt = Assert-WeatherIntegrationLocalScheduleTime `
        -Value $MergeAtLocal -Label "MergeAtLocal"
    $localNow = [datetime]::SpecifyKind($Now, [DateTimeKind]::Unspecified)
    $suiteMinute = ($suiteAt.Hour * 60) + $suiteAt.Minute
    $mergeMinute = ($mergeAt.Hour * 60) + $mergeAt.Minute

    if ($suiteAt -lt $localNow.AddMinutes($MinimumLeadMinutes)) {
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
    if (($mergeAt - $suiteAt) -lt [TimeSpan]::FromMinutes(30)) {
        throw "MergeAtLocal must remain at least 30 minutes after SuiteAtLocal."
    }

    return [pscustomobject][ordered]@{
        suite_at_local = $suiteAt
        merge_at_local = $mergeAt
        checked_at_local = $localNow
        minimum_lead_minutes = $MinimumLeadMinutes
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
