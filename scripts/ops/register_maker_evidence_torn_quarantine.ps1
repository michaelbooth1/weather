# Registers WeatherMakerEvidenceTornQuarantine: torn-journal quarantine Stage 2 (owner yes 2026-11-02).
#
# The canonical task definition is scripts\ops\tasks\WeatherMakerEvidenceTornQuarantine.xml. This registrar
# substitutes exactly three values into it (current user, this checkout's root, Windows PowerShell 5.1 path),
# registers the result with Register-ScheduledTask -Xml, reads it back and disables it on any mismatch.
#
# NOT REGISTERED by default. Only the production agent runs it without -WhatIf, on the dedicated capture host,
# from a clean checkout at -ExpectedSourceTip, after Stage 1 has landed there. It never replaces an existing
# task; to change the definition, review a new XML and unregister the old task first (owner decision).
# -WhatIf prints the plan (one JSON line) followed by the exact XML it would register, and touches nothing: no
# host check, no git call, no Scheduler call. Both modes refuse when maker_evidence_torn_quarantine.ps1 does not
# hash to -ExpectedScriptSha256.
#
# Trigger: at startup, then every minute for 15 minutes (the design's bounded poll loop, done by the
# Scheduler rather than inside the Stage 1 script). IgnoreNew, no StartWhenAvailable, 5-minute run limit.
# Each run is one Stage 1 -Apply pass on the core root: it no-ops while the recorder holds .writer.lock.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSourceTip,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedScriptSha256
)
$ErrorActionPreference = 'Stop'

$taskName = 'WeatherMakerEvidenceTornQuarantine'
$taskPath = '\'
$repoRoot = [IO.Path]::GetFullPath((Split-Path -Parent (Split-Path -Parent $PSScriptRoot))).TrimEnd('\')
$templatePath = Join-Path $PSScriptRoot 'tasks\WeatherMakerEvidenceTornQuarantine.xml'
$quarantineScript = Join-Path $PSScriptRoot 'maker_evidence_torn_quarantine.ps1'
$powerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

function Get-TornQuarantineSha256Text([string]$Text) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Get-TornQuarantineSha256File([string]$Path) {
    # .NET hashing: Get-FileHash honours -WhatIf and returns nothing under it.
    $sha = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($Path)
    try { return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $sha.Dispose() }
}

function ConvertTo-TornQuarantineTaskXml {
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
    if ($RepoRoot.Contains('"') -or -not [IO.Path]::IsPathRooted($RepoRoot)) { throw "repository root is not an absolute path usable in the action: $RepoRoot" }
    if (-not $UserId.Trim() -or $UserId.Contains('\')) { throw "user id must be the bare current user name: '$UserId'" }
    $xml = $Template.Replace('__WEATHER_USER_ID__', [Security.SecurityElement]::Escape($UserId))
    $xml = $xml.Replace('__WEATHER_REPO_ROOT__', [Security.SecurityElement]::Escape($RepoRoot))
    $xml = $xml.Replace('__WEATHER_POWERSHELL__', [Security.SecurityElement]::Escape($PowerShell))
    if ($xml.Contains('__WEATHER_')) { throw 'task template carries an unknown placeholder' }
    $null = [xml]$xml
    return $xml
}

function Test-TornQuarantineTaskReadback {
    # Returns the list of contract violations of a registered task (empty = exact). Expected values come from
    # the rendered XML, so the readback is checked against the reviewed definition, not a second copy of it.
    param([Parameter(Mandatory = $true)][object[]]$Task, [Parameter(Mandatory = $true)][xml]$Definition)
    $problems = New-Object System.Collections.Generic.List[string]
    if ($Task.Count -ne 1) { $problems.Add("expected exactly one task, found $($Task.Count)"); return $problems.ToArray() }
    $t = $Task[0]
    $exec = $Definition.Task.Actions.Exec
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
        & $check 'boot trigger' ([string]$trigger.CimClass.CimClassName -ceq 'MSFT_TaskBootTrigger')
        & $check 'trigger enabled' ([bool]$trigger.Enabled)
        & $check 'no trigger delay' ([string]::IsNullOrEmpty([string]$trigger.Delay))
        & $check 'repetition interval PT1M' ([string]$trigger.Repetition.Interval -ceq 'PT1M')
        & $check 'repetition duration PT15M' ([string]$trigger.Repetition.Duration -ceq 'PT15M')
        & $check 'repetition does not stop at duration end' (-not [bool]$trigger.Repetition.StopAtDurationEnd)
    }
    $s = $t.Settings
    & $check 'IgnoreNew' ([string]$s.MultipleInstances -ceq 'IgnoreNew')
    & $check 'no StartWhenAvailable' (-not [bool]$s.StartWhenAvailable)
    & $check 'execution time limit PT5M' ([string]$s.ExecutionTimeLimit -ceq 'PT5M')
    & $check 'runs on batteries' (-not [bool]$s.DisallowStartIfOnBatteries -and -not [bool]$s.StopIfGoingOnBatteries)
    & $check 'not idle or network gated' (-not [bool]$s.RunOnlyIfIdle -and -not [bool]$s.RunOnlyIfNetworkAvailable)
    & $check 'no wake, not hidden' (-not [bool]$s.WakeToRun -and -not [bool]$s.Hidden)
    & $check 'hard terminate allowed' ([bool]$s.AllowHardTerminate)
    & $check 'priority 7' ([int]$s.Priority -eq 7)
    return $problems.ToArray()
}

if (-not (Test-Path -LiteralPath $quarantineScript -PathType Leaf)) { throw "missing $quarantineScript" }
$actualScriptSha256 = (Get-TornQuarantineSha256File $quarantineScript)
if ($actualScriptSha256 -cne $ExpectedScriptSha256) {
    throw "maker_evidence_torn_quarantine.ps1 is $actualScriptSha256, not ExpectedScriptSha256 $ExpectedScriptSha256"
}
$template = [IO.File]::ReadAllText($templatePath, [Text.Encoding]::UTF8)
$templateSha256 = (Get-TornQuarantineSha256File $templatePath)
$taskXml = ConvertTo-TornQuarantineTaskXml -Template $template -UserId $env:USERNAME -RepoRoot $repoRoot -PowerShell $powerShell
$plan = [ordered]@{
    task_name = $taskName; task_path = $taskPath; registered = $false
    planned_action = "Register-ScheduledTask -TaskName $taskName -TaskPath \ -Xml <the XML below>, then Get-ScheduledTask readback; Disable-ScheduledTask and fail on any mismatch"
    preconditions = @('dedicated capture host', "clean checkout at $ExpectedSourceTip", "no existing task named $taskName")
    repo_root = $repoRoot; user_id = $env:USERNAME
    template_path = $templatePath; template_sha256 = $templateSha256; task_xml_sha256_utf8 = (Get-TornQuarantineSha256Text $taskXml)
    quarantine_script = $quarantineScript; quarantine_script_sha256 = $actualScriptSha256
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
$tracked = @(git -C $repoRoot status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0 -or $tracked.Count -ne 0) { throw 'Source must be clean (tracked changes present)' }
if ((Get-TornQuarantineSha256File $quarantineScript) -cne $ExpectedScriptSha256) {
    throw 'maker_evidence_torn_quarantine.ps1 changed during registration'
}
if (@(Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction SilentlyContinue).Count -ne 0) {
    throw "$taskName already exists; this registrar never replaces it"
}

$null = Register-ScheduledTask -TaskName $taskName -TaskPath $taskPath -Xml $taskXml
$registered = @(Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction Stop)
$problems = @(Test-TornQuarantineTaskReadback -Task $registered -Definition ([xml]$taskXml))
if ($problems.Count -ne 0) {
    Disable-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction SilentlyContinue | Out-Null
    throw ("$taskName readback mismatch (" + ($problems -join '; ') + '); the task was disabled')
}
$exported = [string](Export-ScheduledTask -TaskName $taskName -TaskPath $taskPath)
$plan.registered = $true
$plan.readback = 'exact'
$plan.exported_xml_sha256_utf8 = Get-TornQuarantineSha256Text $exported
$plan.registered_at_utc = [DateTime]::UtcNow.ToString('o')
$plan | ConvertTo-Json -Compress
$exported
