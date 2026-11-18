# Registers WeatherBPriceCoverage: the R19 daily B-1 coverage-count catch-up (owner yes 2026-11-05).
#
# The canonical task definition is scripts\ops\tasks\WeatherBPriceCoverage.xml. This registrar substitutes
# exactly three values into it (current user, this checkout's root, Windows PowerShell 5.1 path), registers the
# result with Register-ScheduledTask -Xml, reads it back and disables it on any mismatch.
#
# NOT REGISTERED by default. Only the production agent runs it without -WhatIf, on the dedicated capture host,
# from a clean checkout at -ExpectedSourceTip. It never replaces an existing task; to change the definition,
# review a new XML and unregister the old task first. -WhatIf prints the plan (one JSON line, after
# PowerShell's own "What if:" line) followed by the exact XML it would register, and touches nothing: no host
# check, no git call, no Scheduler call. Both modes refuse when b_price_coverage.ps1 does not hash to its pin.
#
# Trigger: daily at 04:35 local (an unzoned CalendarTrigger, so it follows the wall clock across DST), after the
# 04:15 WeatherMg2InputExport has published D and before the 04:45-06:45 tiering reserve. The action is
# b_price_coverage.ps1 in its catch-up default with -MaxRuntimeSeconds 540, so the wrapper's own deadline
# (04:44) and teardown come before the Scheduler's PT10M backstop (04:45). IgnoreNew, no StartWhenAvailable:
# a missed or lease-refused run is not retried that day; the next day's catch-up covers every date without a
# sidecar. Timetable and reasoning: docs/operations/OPERATIONS_DESIGN.md (B-1 coverage counts).
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSourceTip,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedScriptSha256
)
$ErrorActionPreference = 'Stop'

$taskName = 'WeatherBPriceCoverage'
$taskPath = '\'
$triggerAt = '04:35'
$repoRoot = [IO.Path]::GetFullPath((Split-Path -Parent (Split-Path -Parent $PSScriptRoot))).TrimEnd('\')
$templatePath = Join-Path $PSScriptRoot 'tasks\WeatherBPriceCoverage.xml'
$coverageScript = Join-Path $PSScriptRoot 'b_price_coverage.ps1'
$powerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
. (Join-Path $PSScriptRoot 'scheduled_task_local_trigger.ps1')

function Get-BPriceCoverageSha256Text([string]$Text) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Get-BPriceCoverageSha256File([string]$Path) {
    # .NET hashing: Get-FileHash honours -WhatIf and returns nothing under it.
    $sha = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($Path)
    try { return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $sha.Dispose() }
}

function Assert-BPriceCoveragePin {
    if (-not (Test-Path -LiteralPath $coverageScript -PathType Leaf)) { throw "missing $coverageScript" }
    $actual = Get-BPriceCoverageSha256File $coverageScript
    if ($actual -cne $ExpectedScriptSha256) {
        throw "b_price_coverage.ps1 is $actual, not ExpectedScriptSha256 $ExpectedScriptSha256"
    }
}

function ConvertTo-BPriceCoverageTaskXml {
    param(
        [Parameter(Mandatory = $true)][string]$Template,
        [Parameter(Mandatory = $true)][string]$UserId,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$PowerShell
    )
    $expectedCounts = [ordered]@{ '__WEATHER_USER_ID__' = 1; '__WEATHER_REPO_ROOT__' = 2; '__WEATHER_POWERSHELL__' = 1 }
    foreach ($token in $expectedCounts.Keys) {
        $count = ([regex]::Matches($Template, [regex]::Escape($token))).Count
        if ($count -ne $expectedCounts[$token]) { throw "task template must contain $token exactly $($expectedCounts[$token]) time(s), found $count" }
    }
    if ($RepoRoot.Contains('"') -or -not [IO.Path]::IsPathRooted($RepoRoot)) {
        throw "repository root is not an absolute path usable in the action: $RepoRoot"
    }
    if (-not $UserId.Trim() -or $UserId.Contains('\')) { throw "user id must be the bare current user name: '$UserId'" }
    $xml = $Template.Replace('__WEATHER_USER_ID__', [Security.SecurityElement]::Escape($UserId))
    $xml = $xml.Replace('__WEATHER_REPO_ROOT__', [Security.SecurityElement]::Escape($RepoRoot))
    $xml = $xml.Replace('__WEATHER_POWERSHELL__', [Security.SecurityElement]::Escape($PowerShell))
    if ($xml.Contains('__WEATHER_')) { throw 'task template carries an unknown placeholder' }
    $null = [xml]$xml
    return $xml
}

function Test-BPriceCoverageTaskReadback {
    # Returns the list of contract violations of a registered task (empty = exact). Expected values come from
    # the rendered XML, so the readback is checked against the reviewed definition, not a second copy of it.
    # Callers collect it with @(...); an exact task yields an empty array.
    param(
        [Parameter(Mandatory = $true)][object[]]$Task,
        [Parameter(Mandatory = $true)][xml]$Definition,
        [Parameter(Mandatory = $true)][string]$At
    )
    $problems = New-Object System.Collections.Generic.List[string]
    if ($Task.Count -ne 1) { $problems.Add("expected exactly one task, found $($Task.Count)"); return $problems.ToArray() }
    $t = $Task[0]
    $exec = $Definition.Task.Actions.Exec
    $calendar = $Definition.Task.Triggers.CalendarTrigger
    $check = {
        param([string]$Name, [bool]$Ok)
        if (-not $Ok) { $problems.Add($Name) }
    }
    & $check 'task path' ([string]$t.TaskPath -ceq '\')
    & $check 'enabled' ($t.Settings.Enabled -eq $true)
    & $check 'principal user' ([string]$t.Principal.UserId -ieq [string]$Definition.Task.Principals.Principal.UserId)
    & $check 'principal logon type S4U' ([string]$t.Principal.LogonType -ceq 'S4U')
    & $check 'principal run level Limited' ([string]$t.Principal.RunLevel -ceq 'Limited')
    $actions = @($t.Actions | Where-Object { $null -ne $_ })
    & $check 'one action' ($actions.Count -eq 1)
    if ($actions.Count -eq 1) {
        & $check 'action executable' ([string]$actions[0].Execute -ieq [string]$exec.Command)
        & $check 'action arguments' ([string]$actions[0].Arguments -ceq [string]$exec.Arguments)
        & $check 'action working directory' ([string]$actions[0].WorkingDirectory -ieq [string]$exec.WorkingDirectory)
    }
    $triggers = @($t.Triggers | Where-Object { $null -ne $_ })
    & $check 'one trigger' ($triggers.Count -eq 1)
    if ($triggers.Count -eq 1) {
        $trigger = $triggers[0]
        $boundary = [string]$trigger.StartBoundary
        & $check 'daily trigger' ([string]$trigger.CimClass.CimClassName -ceq 'MSFT_TaskDailyTrigger')
        & $check 'trigger enabled' ([bool]$trigger.Enabled)
        & $check 'every day' ([int]$trigger.DaysInterval -eq 1)
        & $check "local unzoned start $At" (Test-WeatherLocalDailyStartBoundary -StartBoundary $boundary -At $At)
        & $check 'start boundary as defined' ($boundary -ceq [string]$calendar.StartBoundary)
        & $check 'no end boundary' ([string]::IsNullOrEmpty([string]$trigger.EndBoundary))
        & $check 'no random delay' ([string]::IsNullOrEmpty([string]$trigger.RandomDelay))
        & $check 'no repetition' ($null -eq $trigger.Repetition -or [string]::IsNullOrEmpty([string]$trigger.Repetition.Interval))
    }
    $s = $t.Settings
    & $check 'IgnoreNew' ([string]$s.MultipleInstances -ceq 'IgnoreNew')
    & $check 'no StartWhenAvailable' (-not [bool]$s.StartWhenAvailable)
    & $check 'execution time limit PT10M' ([string]$s.ExecutionTimeLimit -ceq 'PT10M')
    & $check 'starts on batteries' (-not [bool]$s.DisallowStartIfOnBatteries)
    & $check 'keeps running on batteries' (-not [bool]$s.StopIfGoingOnBatteries)
    & $check 'not idle gated' (-not [bool]$s.RunOnlyIfIdle)
    & $check 'not network gated' (-not [bool]$s.RunOnlyIfNetworkAvailable)
    & $check 'no wake' (-not [bool]$s.WakeToRun)
    & $check 'not hidden' (-not [bool]$s.Hidden)
    & $check 'hard terminate allowed' ([bool]$s.AllowHardTerminate)
    & $check 'priority 7' ([int]$s.Priority -eq 7)
    return $problems.ToArray()
}

Assert-BPriceCoveragePin
$template = [IO.File]::ReadAllText($templatePath, [Text.Encoding]::UTF8)
$taskXml = ConvertTo-BPriceCoverageTaskXml -Template $template -UserId $env:USERNAME -RepoRoot $repoRoot -PowerShell $powerShell
$plan = [ordered]@{
    task_name = $taskName; task_path = $taskPath; registered = $false
    planned_action = "Register-ScheduledTask -TaskName $taskName -TaskPath \ -Xml <the XML below>, then Get-ScheduledTask readback; Disable-ScheduledTask and fail on any mismatch"
    preconditions = @('dedicated capture host', "clean checkout at $ExpectedSourceTip", "no existing task named $taskName")
    trigger_local_daily = $triggerAt; execution_time_limit = 'PT10M'; max_runtime_seconds = 540
    repo_root = $repoRoot; user_id = $env:USERNAME
    template_path = $templatePath; template_sha256 = (Get-BPriceCoverageSha256File $templatePath)
    task_xml_sha256_utf8 = (Get-BPriceCoverageSha256Text $taskXml)
    coverage_script = $coverageScript; coverage_script_sha256 = $ExpectedScriptSha256
    expected_source_tip = $ExpectedSourceTip
}

if (-not $PSCmdlet.ShouldProcess($taskName, 'Register-ScheduledTask -Xml (owner approval required)')) {
    $plan | ConvertTo-Json -Compress
    $taskXml
    return
}

. (Join-Path $PSScriptRoot 'workload_admission.ps1')
$assignment = Get-WeatherExecutionHostAssignment -RepoRoot $repoRoot
if ((Get-WeatherExecutionHostId) -cne [string]$assignment.dedicated_capture_execution_host_id) {
    throw 'Registration is restricted to the dedicated capture host'
}
$head = ([string](git -C $repoRoot rev-parse HEAD)).Trim()
if ($LASTEXITCODE -ne 0 -or $head -cne $ExpectedSourceTip) { throw "Reviewed source tip mismatch: HEAD is $head" }
# Untracked files do not block: the production tree carries a permanent untracked venv-cp3110\ (master, 2026-10-27).
$tracked = @(git -C $repoRoot status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0 -or $tracked.Count -ne 0) { throw 'Source must be clean (tracked changes present)' }
Assert-BPriceCoveragePin
. (Join-Path $PSScriptRoot 'scheduled_task_test_guard.ps1')
Assert-WeatherScheduledTaskTestIsolation -Command @('Get-ScheduledTask', 'Register-ScheduledTask',
    'Export-ScheduledTask', 'Disable-ScheduledTask')
$existing = $null
try { $existing = @(Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction Stop) }
catch {
    # Only "no such task" means absent; access or service errors stop the registration.
    if ([string]$_.CategoryInfo.Category -cne 'ObjectNotFound') { throw }
    $existing = @()
}
if ($existing.Count -ne 0) { throw "$taskName already exists; this registrar never replaces it" }

# No -Force: Register-ScheduledTask itself refuses an existing task, a second guard for never-replace.
$null = Register-ScheduledTask -TaskName $taskName -TaskPath $taskPath -Xml $taskXml
try {
    $registered = @(Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction Stop)
    $problems = @(Test-BPriceCoverageTaskReadback -Task $registered -Definition ([xml]$taskXml) -At $triggerAt)
    if ($problems.Count -ne 0) { throw ('readback mismatch (' + ($problems -join '; ') + ')') }
    $exported = [string](Export-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction Stop)
}
catch {
    $why = $_.Exception.Message
    try {
        $null = Disable-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction Stop
        $after = Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction Stop
        if ($after.Settings.Enabled -ne $false) { throw 'Settings.Enabled is still true' }
    }
    catch {
        throw ("$taskName registration unverified ($why); disabling it or proving it disabled failed " +
            "($($_.Exception.Message)). Check whether the task exists now and, if it does, disable it by hand")
    }
    throw "$taskName registered but unverified ($why); the task was disabled (Settings.Enabled false)"
}
$plan.registered = $true
$plan.readback = 'exact'
$plan.exported_xml_sha256_utf8 = Get-BPriceCoverageSha256Text $exported
$plan.registered_at_utc = [DateTime]::UtcNow.ToString('o')
$plan | ConvertTo-Json -Compress
$exported
