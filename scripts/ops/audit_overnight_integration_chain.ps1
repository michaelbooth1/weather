# Produce one fail-closed, read-only receipt after the bounded suite/merge/adoption
# chain. The only mutations are writing the requested report and disabling the
# spent one-shot audit task itself.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$Stage01Tip,
    [Parameter(Mandatory = $true)][string]$ExecutionTapeTip,
    [Parameter(Mandatory = $true)][string]$AuditScriptTip,
    [Parameter(Mandatory = $true)][string]$AuditScriptSha256,
    [Parameter(Mandatory = $true)][string]$ReportPath,
    [string]$AuditTaskName = "",
    [string]$AuditScriptBranch = "codex/agent-context-resilience-20260814",
    [string]$Stage01Branch = "codex/international-live-probe-refresh-20260814",
    [string]$ExecutionTapeBranch = "codex/execution-tape-launcher-adoption-20260814",
    [string]$Stage01SuiteTask = "WeatherInternationalLiveProbeRefreshSuite0815",
    [string]$Stage01MergeTask = "WeatherQuietWindowInternationalLiveProbeRefresh0815",
    [string]$ExecutionTapeSuiteTask = "WeatherExecutionTapeLauncherSuite0815",
    [string]$ExecutionTapeMergeTask = "WeatherQuietWindowExecutionTapeLauncher0815",
    [string]$AdoptionTask = "WeatherExecutionTapeAdoption0815",
    [string]$TrainingReenableTask = "WeatherTrainingWindowReenable0815",
    [string]$Stage01SuiteLog = "C:\Users\micha\ops\international-live-probe-refresh-full-suite-20260815.log",
    [string]$ExecutionTapeSuiteLog = "C:\Users\micha\ops\execution-tape-launcher-full-suite-20260815.log",
    [string]$AdoptionLog = "C:\Users\micha\ops\execution-tape-adoption-20260815.log"
)

$ErrorActionPreference = "Stop"
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
$ReportPath = [IO.Path]::GetFullPath($ReportPath)
$Stage01Tip = $Stage01Tip.Trim().ToLowerInvariant()
$ExecutionTapeTip = $ExecutionTapeTip.Trim().ToLowerInvariant()
$AuditScriptTip = $AuditScriptTip.Trim().ToLowerInvariant()
$AuditScriptSha256 = $AuditScriptSha256.Trim().ToLowerInvariant()
$expectedDate = [datetime]"2026-08-15"
$python = Join-Path $RepoRoot "venv\Scripts\python.exe"
$checks = New-Object System.Collections.Generic.List[object]
$failures = New-Object System.Collections.Generic.List[string]

function Add-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][bool]$Ok,
        [Parameter(Mandatory = $true)][string]$Detail
    )
    $script:checks.Add([ordered]@{ name = $Name; ok = $Ok; detail = $Detail })
    if (-not $Ok) { $script:failures.Add("${Name}: $Detail") }
}

function Check-TaskSuccess {
    param([Parameter(Mandatory = $true)][string]$Name)
    try {
        $task = Get-ScheduledTask -TaskName $Name -ErrorAction Stop
        $info = Get-ScheduledTaskInfo -TaskName $Name -ErrorAction Stop
        $ok = (
            [string]$task.State -ne "Running" -and
            [datetime]$info.LastRunTime -ge $script:expectedDate -and
            [int]$info.LastTaskResult -eq 0
        )
        Add-Check $Name $ok ("state={0}; last={1:o}; result={2}" -f
            $task.State, $info.LastRunTime, $info.LastTaskResult)
    }
    catch {
        Add-Check $Name $false ("inspection failed: {0}" -f $_.Exception.GetType().Name)
    }
}

function Check-SuiteReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Branch,
        [Parameter(Mandatory = $true)][string]$Tip
    )
    try {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            Add-Check $Name $false "receipt missing"
            return
        }
        $lines = @(Get-Content -LiteralPath $Path)
        $identity = "branch=$Branch expected_tip=$Tip"
        $identityOk = @($lines | Where-Object { [string]$_ -like "*$identity*" }).Count -gt 0
        $last = if ($lines.Count -gt 0) { [string]$lines[-1] } else { "" }
        $verdictOk = $last -match (
            "VERDICT: ALL CHUNKS PASSED \(\d+/\d+\); " +
            "exact tip eligible for separate reviewed merge$"
        )
        Add-Check $Name ($identityOk -and $verdictOk) (
            "identity={0}; terminal_verdict={1}" -f $identityOk, $verdictOk
        )
    }
    catch {
        Add-Check $Name $false ("receipt inspection failed: {0}" -f
            $_.Exception.GetType().Name)
    }
}

foreach ($tip in @($Stage01Tip, $ExecutionTapeTip, $AuditScriptTip)) {
    if ($tip -notmatch "^[0-9a-f]{40}$") {
        throw "Expected tips must be full 40-character hexadecimal SHAs"
    }
}
if ($AuditScriptSha256 -notmatch "^[0-9a-f]{64}$") {
    throw "AuditScriptSha256 must be a full 64-character hexadecimal digest"
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "repository Python interpreter is missing"
}

$actualScriptHash = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
Add-Check "audit_script_hash" ($actualScriptHash -eq $AuditScriptSha256) (
    "actual={0}; expected={1}" -f $actualScriptHash, $AuditScriptSha256
)
try {
    $auditLocal = (& git -C $RepoRoot rev-parse `
        "refs/heads/$AuditScriptBranch").Trim().ToLowerInvariant()
    $auditRemote = (& git -C $RepoRoot rev-parse `
        "refs/remotes/origin/$AuditScriptBranch").Trim().ToLowerInvariant()
    $auditRefOk = (
        $LASTEXITCODE -eq 0 -and
        $auditLocal -eq $AuditScriptTip -and
        $auditRemote -eq $AuditScriptTip
    )
    Add-Check "audit_script_ref" $auditRefOk (
        "local={0}; remote={1}; expected={2}" -f
        $auditLocal, $auditRemote, $AuditScriptTip
    )
}
catch {
    Add-Check "audit_script_ref" $false ("inspection failed: {0}" -f
        $_.Exception.GetType().Name)
}

foreach ($taskName in @(
        $Stage01SuiteTask,
        $Stage01MergeTask,
        $ExecutionTapeSuiteTask,
        $ExecutionTapeMergeTask,
        $AdoptionTask,
        $TrainingReenableTask
    )) {
    Check-TaskSuccess $taskName
}

Check-SuiteReceipt "stage01_suite_receipt" $Stage01SuiteLog $Stage01Branch $Stage01Tip
Check-SuiteReceipt "execution_tape_suite_receipt" $ExecutionTapeSuiteLog `
    $ExecutionTapeBranch $ExecutionTapeTip

try {
    $adoption = Get-Content -LiteralPath $AdoptionLog -Raw | ConvertFrom-Json
    $adoptionOk = (
        $adoption.adopted -eq $true -and
        [string]$adoption.expected_tip -eq $ExecutionTapeTip -and
        [string]$adoption.capture_state -eq "CONNECTED" -and
        [string]$adoption.evidence_integrity -eq "PASS" -and
        $adoption.runtime_identity_matches_current -eq $true
    )
    Add-Check "execution_tape_adoption_receipt" $adoptionOk (
        "adopted={0}; state={1}; integrity={2}; identity={3}" -f
        $adoption.adopted, $adoption.capture_state,
        $adoption.evidence_integrity, $adoption.runtime_identity_matches_current
    )
}
catch {
    Add-Check "execution_tape_adoption_receipt" $false (
        "receipt inspection failed: {0}" -f $_.Exception.GetType().Name
    )
}

try {
    $master = (& git -C $RepoRoot rev-parse master).Trim().ToLowerInvariant()
    $origin = (& git -C $RepoRoot rev-parse origin/master).Trim().ToLowerInvariant()
    $exact = ($LASTEXITCODE -eq 0 -and $master -eq $origin)
    Add-Check "master_origin_exact" $exact "master=$master; origin=$origin"
    foreach ($tip in @($Stage01Tip, $ExecutionTapeTip)) {
        & git -C $RepoRoot merge-base --is-ancestor $tip master
        $ancestor = ($LASTEXITCODE -eq 0)
        Add-Check ("master_contains_{0}" -f $tip.Substring(0, 12)) $ancestor (
            "expected_tip=$tip"
        )
    }
}
catch {
    Add-Check "git_integration" $false ("inspection failed: {0}" -f
        $_.Exception.GetType().Name)
}

try {
    $captureText = (& $python -m weather.operations.capture_recovery_check --json) -join "`n"
    $captureExit = $LASTEXITCODE
    $capture = $captureText | ConvertFrom-Json
    $captureOk = (
        $captureExit -eq 0 -and
        $capture.ok -eq $true -and
        @($capture.workers).Count -eq 3 -and
        @($capture.workers | Where-Object { $_.ok -ne $true }).Count -eq 0
    )
    Add-Check "core_capture_recovery" $captureOk (
        "exit={0}; ok={1}; workers={2}" -f
        $captureExit, $capture.ok, @($capture.workers).Count
    )
}
catch {
    Add-Check "core_capture_recovery" $false ("inspection failed: {0}" -f
        $_.Exception.GetType().Name)
}

try {
    $supervisorTask = Get-ScheduledTask -TaskName "WeatherExecutionTapeSupervisor" -ErrorAction Stop
    $taskEnabled = $supervisorTask.Settings.Enabled -eq $true
    Add-Check "execution_tape_supervisor_enabled" $taskEnabled (
        "state={0}; enabled={1}" -f $supervisorTask.State, $supervisorTask.Settings.Enabled
    )
    $healthText = (& $python -m weather.operations.execution_tape_supervisor status `
        --stale-after-seconds 180) -join "`n"
    $healthExit = $LASTEXITCODE
    $payload = $healthText | ConvertFrom-Json
    $health = $payload.health
    $status = $payload.status
    $writerLockPath = Join-Path $RepoRoot `
        "data\snapshots\.execution_tape_status.json.writer.lock"
    $writerLock = if (Test-Path -LiteralPath $writerLockPath -PathType Leaf) {
        Get-Content -LiteralPath $writerLockPath -Raw | ConvertFrom-Json
    }
    else {
        $null
    }
    $healthOk = (
        $healthExit -eq 0 -and
        @("RUNNING", "DEGRADED") -contains ([string]$health.state) -and
        $health.pid_alive -eq $true -and
        $health.runtime_identity_matches_current -eq $true -and
        [string]$health.evidence_integrity -eq "PASS" -and
        $health.price_path_evidence_usable -eq $true -and
        [string]$status.state -eq "CONNECTED" -and
        [string]$status.market -eq "all" -and
        [string]$status.runner -eq "managed_execution_tape" -and
        $status.managed_process.verified_at_capture -eq $true -and
        $null -ne $writerLock -and
        [int]$status.pid -eq [int]$status.managed_process.pid -and
        [int]$status.pid -eq [int]$writerLock.pid -and
        [int]$status.pid -eq [int]$writerLock.managed_process.pid -and
        [string]$status.managed_process.creation_time_token -ceq
            [string]$writerLock.managed_process.creation_time_token
    )
    Add-Check "execution_tape_runtime" $healthOk (
        "exit={0}; health={1}; capture={2}; integrity={3}; identity={4}; lock={5}" -f
        $healthExit, $health.state, $status.state, $health.evidence_integrity,
        $health.runtime_identity_matches_current, ($null -ne $writerLock)
    )
}
catch {
    Add-Check "execution_tape_runtime" $false ("inspection failed: {0}" -f
        $_.Exception.GetType().Name)
}

foreach ($expectedState in @(
        @{ Name = "WeatherTrainingWindow"; Enabled = $true },
        @{ Name = "WeatherTrainingWindowReenable0815"; Enabled = $false },
        @{ Name = "WeatherEveningEvidenceRefresh"; Enabled = $false }
    )) {
    try {
        $task = Get-ScheduledTask -TaskName $expectedState.Name -ErrorAction Stop
        $ok = $task.Settings.Enabled -eq $expectedState.Enabled
        Add-Check ("task_state_{0}" -f $expectedState.Name) $ok (
            "state={0}; enabled={1}; expected_enabled={2}" -f
            $task.State, $task.Settings.Enabled, $expectedState.Enabled
        )
    }
    catch {
        Add-Check ("task_state_{0}" -f $expectedState.Name) $false (
            "inspection failed: {0}" -f $_.Exception.GetType().Name
        )
    }
}

try {
    $push = Get-ScheduledTask -TaskName "WeatherOneShotPush" -ErrorAction Stop
    $actions = @($push.Actions)
    $expectedArgs = "/c git -C c:\Users\micha\Desktop\github\weather push origin master > C:\Users\micha\ops\logs\push-oneshot.log 2>&1"
    $pushOk = (
        $push.Settings.Enabled -eq $true -and
        $actions.Count -eq 1 -and
        [string]$actions[0].Execute -ieq "cmd.exe" -and
        [string]$actions[0].Arguments -ceq $expectedArgs
    )
    Add-Check "canonical_push_task" $pushOk (
        "state={0}; enabled={1}; action_exact={2}" -f
        $push.State, $push.Settings.Enabled, $pushOk
    )
}
catch {
    Add-Check "canonical_push_task" $false ("inspection failed: {0}" -f
        $_.Exception.GetType().Name)
}

if ($AuditTaskName) {
    try {
        Disable-ScheduledTask -TaskName $AuditTaskName | Out-Null
        Add-Check "audit_task_self_disabled" $true "task=$AuditTaskName"
    }
    catch {
        Add-Check "audit_task_self_disabled" $false ("failed: {0}" -f
            $_.Exception.GetType().Name)
    }
}

$result = [ordered]@{
    schema_version = "overnight_integration_chain_audit_v1"
    checked_at = (Get-Date).ToString("o")
    ok = $failures.Count -eq 0
    stage01_tip = $Stage01Tip
    execution_tape_tip = $ExecutionTapeTip
    audit_script_tip = $AuditScriptTip
    audit_script_sha256 = $AuditScriptSha256
    checks = @($checks)
    failures = @($failures)
}
$json = $result | ConvertTo-Json -Depth 10
$parent = Split-Path -Parent $ReportPath
if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
$temporary = "$ReportPath.tmp"
[IO.File]::WriteAllText($temporary, $json, (New-Object Text.UTF8Encoding($false)))
Move-Item -LiteralPath $temporary -Destination $ReportPath -Force
Write-Output $json
if ($result.ok) { exit 0 }
exit 1
