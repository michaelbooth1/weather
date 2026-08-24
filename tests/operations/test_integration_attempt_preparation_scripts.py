import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
PREPARER = OPS / "prepare_integration_attempt.ps1"
READINESS = OPS / "assert_integration_attempt_ready.ps1"
PREPARATION_CONTRACT = OPS / "integration_attempt_preparation_contract.ps1"
ATTEMPT_CONTRACT = OPS / "integration_attempt_contract.ps1"
CREATOR = OPS / "new_integration_attempt.ps1"
REGISTRAR = OPS / "register_integration_attempt.ps1"
ACTIVATOR = OPS / "activate_integration_attempt.ps1"
SUITE = OPS / "integration_attempt_suite.ps1"
MERGE = OPS / "integration_attempt_merge.ps1"


def _powershell(command: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(extra_env)
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_preparer_checks_credible_schedule_before_exact_non_force_push() -> None:
    script = PREPARER.read_text(encoding="utf-8-sig")

    schedule_gate = script.index("Assert-WeatherIntegrationPreparationSchedule")
    creator_preflight = script.index('-Label "integration attempt creator preflight"')
    push = script.index("& git -C $WorktreeRoot push origin $exactRefspec")
    creator = script.index('-Label "integration attempt creator"')
    registrar = script.index('-Label "integration attempt registrar"')
    readiness = script.index('-Label "integration attempt readiness assertion"')
    activator = script.index('-Label "integration attempt activator"')

    assert schedule_gate < creator_preflight < push < creator < registrar < readiness < activator
    assert 'MinimumLeadMinutes 10' in script
    assert script.count("Assert-WeatherIntegrationPreparationSchedule") == 3
    assert script.index("$publicationSchedule = Assert-WeatherIntegrationPreparationSchedule") < push
    assert script.index("$registrationSchedule = Assert-WeatherIntegrationPreparationSchedule") < registrar
    assert '$exactRefspec = "${ExpectedTip}:$remoteRef"' in script
    assert "push --force" not in script.lower()
    assert "push -f" not in script.lower()
    assert "ls-remote --heads origin $RemoteRef" in script
    assert '-RemoteRef "refs/heads/master"' in script
    assert '"refs/heads/master:refs/remotes/origin/master"' in script
    assert "$masterTip -ne $liveMasterTip" in script
    assert 'fetch --no-tags origin $fetchRefspec' in script
    assert 'schema = "weather_integration_attempt_preparation_intent_v1"' in script
    assert 'schema = "weather_integration_attempt_preparation_receipt_v1"' in script
    assert 'status = "FAIL"' in script
    assert script.rindex('$status = "PASS"') > activator
    assert "close_integration_attempt.ps1" in script
    assert "Canonical closure failed; exact task terminality is unproved" in script
    assert "receipt_sha256 = $closureReceiptSha256" in script
    assert '-Label "integration attempt closer"' in script
    assert '"-PreflightOnly"' in script
    assert "Assert-WeatherIntegrationNoActiveAttemptCollision" in script
    assert script.index("Assert-WeatherIntegrationNoActiveAttemptCollision") < push


def test_creator_preflight_covers_every_locally_knowable_creation_rejection() -> None:
    script = CREATOR.read_text(encoding="utf-8-sig")
    preflight_return = script.index('status = "PREFLIGHT_READY"')

    required_before_publication = (
        "AttemptRoot already exists",
        "AdditionalPythonPath is unsupported",
        "SuiteAtLocal must be in the admitted",
        "A repair attempt must bind the immutable failed receipt",
        "does not authorize this repair class and closure receipt",
        "already has a successor claim",
        "Suite worktree is not registered",
        "Suite worktree must be clean",
        "contains no pytest files to freeze",
        "A repair tip must descend",
        "retry_unchanged requires the exact same commit id",
        "Repair attempt does not contain a change",
        "Bounded repair classes permit only added or modified files",
        "does not authorize changed path",
        "Production master and origin/master must be reconciled",
        "must contain the exact production baseline",
        "Get-WeatherIntegrationFileSha256 -Path $path",
    )
    for fragment in required_before_publication:
        assert script.index(fragment) < preflight_return

    assert '[switch]$PreflightOnly' in script
    assert 'status = "PREFLIGHT_READY"' in script
    assert script.index("New-Item -ItemType Directory -Path $AttemptRoot") > preflight_return


def test_exit_bearing_attempt_children_are_process_isolated() -> None:
    script = PREPARER.read_text(encoding="utf-8-sig")
    contract = PREPARATION_CONTRACT.read_text(encoding="utf-8-sig")

    assert "Invoke-WeatherIntegrationPowerShellChild" in script
    assert 'Join-Path $PSHOME "powershell.exe"' in contract
    assert "-NoProfile" in contract
    assert "-NonInteractive" in contract
    assert "-ExecutionPolicy Bypass" in contract
    assert "ExitCode = [int]$exitCode" in contract
    assert "Get-WeatherIntegrationChildDiagnosticExcerpt" in contract
    assert "MaximumCharacters = 2048" in contract
    assert "ExpectedSha256" in contract
    assert "Get-WeatherIntegrationFileSha256 -Path $resolvedScriptPath" in contract
    assert script.count("Invoke-WeatherIntegrationPowerShellChild") == 6
    assert script.count("-ExpectedSha256") >= 6
    assert "& $registrarPath" not in script
    assert "& $readinessPath" not in script
    assert "& $closerPath" not in script
    assert script.count("Get-WeatherIntegrationChildDiagnosticExcerpt") == 6
    assert "Enter-WeatherIntegrationPreparationMutex" in contract
    assert "[IO.FileShare]::None" in contract
    assert "Assert-WeatherIntegrationNoActiveAttemptCollision" in contract


def test_final_readiness_requires_every_live_and_immutable_binding() -> None:
    script = READINESS.read_text(encoding="utf-8-sig")

    required_fragments = (
        "Assert-WeatherIntegrationAttemptManifest",
        "Assert-WeatherIntegrationRepairClaim -AttemptContract $contract",
        "successor_expected_tip",
        "successor_manifest_sha256",
        "Get-WeatherIntegrationFileSha256 -Path $claimPath",
        "ls-remote --heads origin $remoteRef",
        'ls-remote --heads origin "refs/heads/master"',
        "Live origin master changed after the attempt baseline was frozen",
        'rev-parse", [string]$manifest.branch_ref',
        "Assert-WeatherIntegrationGitBaseline",
        "worktree list --porcelain",
        "status --porcelain",
        "Assert-WeatherIntegrationRegistrationReceipt",
        "scheduler_boundary_checked_at_local",
        "minimum_suite_lead_minutes",
        "preparer's ten-minute Scheduler boundary",
        "Assert-WeatherIntegrationScheduledTaskBinding",
        'binding.Task.State -ne "Disabled"',
        "binding.Task.Settings.Enabled",
        "Both exact integration task triggers must still be in the future",
        "disabled task exposes a NextRunTime that differs",
        'stage = "validate_final_schedule_reserve"',
        "MinimumLeadMinutes 5",
        "publication_checked_at_local",
        "registration_checked_at_local",
        "Runtime or terminal evidence already exists",
        'status = "PASS"',
        'stage = "READY"',
        "Assert-WeatherIntegrationPreparationExecutionAuthorization",
        "created_after_readiness",
    )
    for fragment in required_fragments:
        assert fragment in script

    assert "Register-ScheduledTask" not in script
    assert "Start-ScheduledTask" not in script
    assert "git push" not in script.lower()
    receipt_write = script.index(
        "Write-WeatherIntegrationImmutableJson -Path $resolvedResultPath"
    )
    final_pass = script.index('$status = "PASS"', receipt_write)
    assert receipt_write < final_pass


def test_registrar_rechecks_lead_at_the_external_mutation_boundary() -> None:
    script = REGISTRAR.read_text(encoding="utf-8-sig")

    boundary = script.index("$schedulerBoundaryCheckedAt = Get-Date")
    first_registration = script.index("Register-ScheduledTask")
    assert boundary < first_registration
    assert "[int]$MinimumSuiteLeadMinutes = 1" in script
    assert "$schedulerBoundaryCheckedAt.AddMinutes($MinimumSuiteLeadMinutes)" in script
    assert "scheduler_boundary_checked_at_local" in script
    assert "minimum_suite_lead_minutes" in script
    preparer = PREPARER.read_text(encoding="utf-8-sig")
    assert '"-MinimumSuiteLeadMinutes", "10"' in preparer


def test_composite_registration_is_disabled_before_any_scheduler_mutation() -> None:
    registrar = REGISTRAR.read_text(encoding="utf-8-sig")
    preparer = PREPARER.read_text(encoding="utf-8-sig")
    activator = ACTIVATOR.read_text(encoding="utf-8-sig")
    suite = SUITE.read_text(encoding="utf-8-sig")
    merge = MERGE.read_text(encoding="utf-8-sig")

    first_register = registrar.index("Register-ScheduledTask")
    assert registrar.index("$suiteSettingsParameters.Disable = $true") < first_register
    assert registrar.index("$mergeSettingsParameters.Disable = $true") < first_register
    assert "[switch]$StageDisabled" in registrar
    assert "staged_disabled = [bool]$StageDisabled" in registrar
    assert '"-StageDisabled"' in preparer
    assert '"-StagedDisabled"' in preparer
    assert preparer.index('-Label "integration attempt readiness assertion"') < preparer.index(
        '-Label "integration attempt activator"'
    )
    assert activator.index("Assert-WeatherIntegrationPreparationExecutionAuthorization") < activator.index(
        "Enable-ScheduledTask"
    )
    assert activator.rindex("Enable-ScheduledTask") < activator.index(
        '$stage = "write_activation_receipt"'
    )
    assert activator.index("Write-WeatherIntegrationImmutableJson") > activator.rindex(
        "Enable-ScheduledTask"
    )
    assert activator.index("Disable-WeatherIntegrationAttemptTasks") > activator.index(
        "Write-WeatherIntegrationImmutableJson"
    )
    for wrapper in (suite, merge):
        manifest = wrapper.index("Assert-WeatherIntegrationAttemptManifest")
        authorization = wrapper.index(
            "Assert-WeatherIntegrationPreparationExecutionAuthorization"
        )
        activation = wrapper.index("Assert-WeatherIntegrationActivationReceipt")
        terminal = wrapper.index("Assert-WeatherIntegrationAttemptNotTerminal")
        assert manifest < authorization < activation < terminal


def test_activation_terminal_checks_are_inside_mutex_and_receipt_failure_rolls_back() -> None:
    activator = ACTIVATOR.read_text(encoding="utf-8-sig")

    lock = activator.index("Enter-WeatherIntegrationControlMutex")
    terminal = activator.index("Assert-WeatherIntegrationAttemptNotTerminal")
    runtime = activator.index("Runtime or terminal evidence exists before activation")
    first_enable = activator.index("Enable-ScheduledTask")
    receipt_write = activator.index(
        "Write-WeatherIntegrationImmutableJson",
        activator.index('$stage = "write_activation_receipt"'),
    )
    rollback = activator.index("Disable-WeatherIntegrationAttemptTasks")
    assert lock < terminal < runtime < first_enable < receipt_write < rollback
    assert 'schema = "weather_integration_attempt_preparation_receipt_v1"' in activator
    assert "Assert-WeatherIntegrationActivationReceipt" in SUITE.read_text(
        encoding="utf-8-sig"
    )
    assert "Assert-WeatherIntegrationActivationReceipt" in MERGE.read_text(
        encoding="utf-8-sig"
    )


def test_activation_revalidates_mutable_premises_before_enable() -> None:
    activator = ACTIVATOR.read_text(encoding="utf-8-sig")

    revalidation = activator.index('$stage = "revalidate_mutable_readiness"')
    freshness = activator.index("[TimeSpan]::FromMinutes(2)", revalidation)
    topic = activator.index("ls-remote --heads origin $topicRemoteRef", revalidation)
    master = activator.index(
        'ls-remote --heads origin "refs/heads/master"', revalidation
    )
    baseline = activator.index("Assert-WeatherIntegrationGitBaseline", revalidation)
    worktree_inventory = activator.index("worktree list --porcelain", revalidation)
    worktree_clean = activator.index("status --porcelain", worktree_inventory)
    quiet_preflight = activator.index(
        "Assert-WeatherIntegrationQuietMergePreconditions", revalidation
    )
    first_enable = activator.index("Enable-ScheduledTask")

    assert (
        revalidation
        < freshness
        < topic
        < master
        < baseline
        < worktree_inventory
        < worktree_clean
        < quiet_preflight
        < first_enable
    )
    assert "Live origin topic changed after final readiness." in activator
    assert "Live origin master changed after final readiness." in activator
    assert "Quiet-merge prerequisites changed after final readiness." in activator


def test_preparation_authorization_is_deterministic_and_manifest_hash_bound(
    tmp_path: Path,
) -> None:
    attempt_root = tmp_path / "attempt-a1"
    intent_path = Path(str(attempt_root) + ".preparation") / "preparation-intent.json"
    manifest_path = attempt_root / "manifest.json"
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$args = @{
    AttemptRoot = $env:WEATHER_ATTEMPT_ROOT
    AttemptId = 'attempt-a1'
    ManifestPath = $env:WEATHER_MANIFEST_PATH
    ExpectedTip = ('1' * 40)
    PreparationIntentPath = $env:WEATHER_INTENT_PATH
    PreparationIntentSha256 = ('2' * 64)
    SuiteTaskName = 'WeatherIntegrationSuite_attempt-a1'
    MergeTaskName = 'WeatherIntegrationMerge_attempt-a1'
}
$first = Get-WeatherIntegrationPreparationAuthorizationPlan @args
$second = Get-WeatherIntegrationPreparationAuthorizationPlan @args
if ($first.Sha256 -ne $second.Sha256 -or
    $first.Sha256 -notmatch '^[0-9a-f]{64}$' -or
    [string]$first.Payload.status -ne 'PASS' -or
    [bool]$first.Payload.credential_value_access_authorized -or
    [bool]$first.Payload.live_exchange_mutation_authorized) {
    throw 'deterministic preparation authorization plan failed'
}
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
        WEATHER_ATTEMPT_ROOT=str(attempt_root),
        WEATHER_MANIFEST_PATH=str(manifest_path),
        WEATHER_INTENT_PATH=str(intent_path),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_preparation_contract_schedule_and_remote_parser_execute() -> None:
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
. $env:WEATHER_PREPARATION_CONTRACT
$now = [datetime]::SpecifyKind([datetime]'2026-08-25T00:30:00', [DateTimeKind]::Unspecified)
$valid = Assert-WeatherIntegrationPreparationSchedule `
    -SuiteAtLocal ([datetime]'2026-08-25T00:40:00') `
    -MergeAtLocal ([datetime]'2026-08-25T01:20:00') `
    -Now $now
$lateAccepted = $false
try {
    Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal ([datetime]'2026-08-25T00:39:59') `
        -MergeAtLocal ([datetime]'2026-08-25T01:20:00') `
        -Now $now | Out-Null
    $lateAccepted = $true
}
catch { }
$remote = Resolve-WeatherIntegrationRemoteTipRows `
    -Rows @('1111111111111111111111111111111111111111' + "`t" + 'refs/heads/codex/test') `
    -ExpectedRemoteRef 'refs/heads/codex/test'
$missing = Resolve-WeatherIntegrationRemoteTipRows `
    -Rows @() -ExpectedRemoteRef 'refs/heads/codex/missing' -AllowMissing
if ($valid.minimum_lead_minutes -ne 10 -or $lateAccepted -or
    $remote -ne ('1' * 40) -or $null -ne $missing -or
    (Get-WeatherIntegrationTopicBranchName -BranchRef 'origin/codex/test') -cne 'codex/test') {
    throw 'Preparation helper contract did not enforce its exact boundary.'
}
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
        WEATHER_PREPARATION_CONTRACT=str(PREPARATION_CONTRACT),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_collision_gate_uses_exact_task_paths_and_conservative_running_windows() -> None:
    contract = PREPARATION_CONTRACT.read_text(encoding="utf-8-sig")

    assert '[string]$_.TaskPath -ieq "\\"' in contract
    assert "$ownTaskNames -icontains [string]$_.TaskName" in contract
    assert "-TaskPath ([string]$task.TaskPath)" in contract
    assert '$taskState -in @("Running", "Queued")' in contract
    assert '$taskState -notin @("Ready", "Disabled")' in contract
    assert '$taskState -eq "Disabled" -or -not $settingsEnabled' in contract
    assert "$conflictStart.AddHours(4)" in contract
    assert "$conflictStart -le $MergeAtLocal" in contract
    assert "$SuiteAtLocal -le $conflictEnd" in contract


def test_collision_gate_fails_closed_for_running_queued_and_unknown_states() -> None:
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
. $env:WEATHER_PREPARATION_CONTRACT
$global:tasks = @()
$global:nextRun = $null
function Get-ScheduledTask { param($ErrorAction) return @($global:tasks) }
function Get-ScheduledTaskInfo {
    param([string]$TaskName, [string]$TaskPath, $ErrorAction)
    return [pscustomobject]@{ NextRunTime = $global:nextRun }
}
function New-TestTask([string]$Name, [string]$State, [bool]$Enabled, [string]$Arguments) {
    return [pscustomobject]@{
        TaskName = $Name
        TaskPath = '\'
        State = $State
        Settings = [pscustomobject]@{ Enabled = $Enabled }
        Actions = @([pscustomobject]@{ Arguments = $Arguments })
    }
}
$suite = [datetime]'2026-08-25T00:40:00'
$merge = [datetime]'2026-08-25T01:20:00'
foreach ($case in @(
    [pscustomobject]@{ Task = (New-TestTask 'WeatherIntegrationSuite_old' 'Running' $false ''); Label = 'running disabled' },
    [pscustomobject]@{ Task = (New-TestTask 'WeatherMergeSensitiveDriver' 'Queued' $false ''); Label = 'queued disabled' },
    [pscustomobject]@{ Task = (New-TestTask 'weathermERgesensitivedriver' 'Running' $false ''); Label = 'case-variant sensitive driver' },
    [pscustomobject]@{ Task = (New-TestTask 'WeatherMergeSensitiveDriver' 'Unknown' $true ''); Label = 'unknown' }
)) {
    $global:tasks = @($case.Task)
    $blocked = $false
    try {
        Assert-WeatherIntegrationNoActiveAttemptCollision `
            -SuiteAtLocal $suite -MergeAtLocal $merge
    }
    catch { $blocked = $true }
    if (-not $blocked) { throw "$($case.Label) task bypassed collision gate" }
}
$global:tasks = @(New-TestTask 'WeatherIntegrationSuite_spent' 'Ready' $true '')
$global:nextRun = $null
Assert-WeatherIntegrationNoActiveAttemptCollision `
    -SuiteAtLocal $suite -MergeAtLocal $merge
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
        WEATHER_PREPARATION_CONTRACT=str(PREPARATION_CONTRACT),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_preparation_child_process_preserves_exit_code_and_output(tmp_path: Path) -> None:
    child = tmp_path / "exit-child.ps1"
    child.write_text(
        "param([string]$Value, [switch]$Flag)\n"
        "\"$Value|$([bool]$Flag)\"\n"
        "exit 7\n",
        encoding="utf-8",
    )
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
. $env:WEATHER_PREPARATION_CONTRACT
$result = Invoke-WeatherIntegrationPowerShellChild `
    -ScriptPath $env:WEATHER_EXIT_CHILD `
    -ExpectedSha256 (Get-WeatherIntegrationFileSha256 -Path $env:WEATHER_EXIT_CHILD) `
    -Arguments @('-Value', 'value with spaces', '-Flag') `
    -Label 'test child'
if ($result.ExitCode -ne 7 -or
    @($result.Output).Count -ne 1 -or
    [string]$result.Output[0] -ne 'value with spaces|True') {
    throw 'Child process isolation did not preserve output and exit code.'
}
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
        WEATHER_PREPARATION_CONTRACT=str(PREPARATION_CONTRACT),
        WEATHER_EXIT_CHILD=str(child),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_scheduler_snapshot_failure_can_never_be_interpreted_as_task_absence() -> None:
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
function Get-ScheduledTask {
    param([string]$ErrorAction)
    throw 'synthetic Scheduler access failure'
}
$failedClosed = $false
try { Get-WeatherIntegrationScheduledTaskSnapshot | Out-Null }
catch { $failedClosed = ($_.Exception.Message -like '*synthetic Scheduler*') }
if (-not $failedClosed) {
    throw 'Scheduler access failure was interpreted as an empty task snapshot'
}
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_attempt_closure_refuses_queued_instances_as_nonterminal() -> None:
    contract = ATTEMPT_CONTRACT.read_text(encoding="utf-8-sig")

    assert '[string]$task.State -in @("Running", "Queued")' in contract
    assert "still running or queued and may not be disabled" in contract


def test_preparation_schedule_reserve_has_deterministic_boundaries() -> None:
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
. $env:WEATHER_PREPARATION_CONTRACT
$suite = [datetime]'2026-08-25T00:40:00'
$merge = [datetime]'2026-08-25T01:20:00'
Assert-WeatherIntegrationPreparationSchedule `
    -SuiteAtLocal $suite -MergeAtLocal $merge `
    -Now ([datetime]'2026-08-25T00:30:00') -MinimumLeadMinutes 10 | Out-Null
Assert-WeatherIntegrationPreparationSchedule `
    -SuiteAtLocal $suite -MergeAtLocal $merge `
    -Now ([datetime]'2026-08-25T00:35:00') -MinimumLeadMinutes 5 | Out-Null
$initialLateAccepted = $false
$finalLateAccepted = $false
try {
    Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal $suite -MergeAtLocal $merge `
        -Now ([datetime]'2026-08-25T00:30:00.001') `
        -MinimumLeadMinutes 10 | Out-Null
    $initialLateAccepted = $true
}
catch { }
try {
    Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal $suite -MergeAtLocal $merge `
        -Now ([datetime]'2026-08-25T00:35:00.001') `
        -MinimumLeadMinutes 5 | Out-Null
    $finalLateAccepted = $true
}
catch { }
if ($initialLateAccepted -or $finalLateAccepted) {
    throw 'Preparation reserve accepted a clock value past its exact boundary.'
}
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
        WEATHER_PREPARATION_CONTRACT=str(PREPARATION_CONTRACT),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_expired_preparation_fails_before_git_or_scheduler_and_is_durable(
    tmp_path: Path,
) -> None:
    attempt_parent = tmp_path / "attempts"
    attempt_parent.mkdir()
    attempt_root = attempt_parent / "expired-a1"
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(PREPARER),
        "-RepoRoot",
        str(ROOT),
        "-AttemptRoot",
        str(attempt_root),
        "-AttemptId",
        "expired-a1",
        "-BranchRef",
        "origin/codex/expired-a1",
        "-WorktreeRoot",
        str(ROOT),
        "-ExpectedTip",
        "0" * 40,
        "-SuiteAtLocal",
        "2020-01-01T00:40:00",
        "-MergeAtLocal",
        "2020-01-01T01:20:00",
        "-ReviewReference",
        "test-expired-window",
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "failed at stage 'validate_schedule'" in result.stdout
    assert '"status":"PASS"' not in result.stdout
    assert not attempt_root.exists()
    receipt_path = Path(str(attempt_root) + ".preparation") / "preparation-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "FAIL"
    assert receipt["stage"] == "validate_schedule"
    assert receipt["publication"]["remote_lookup_completed"] is False
    assert receipt["publication"]["push_attempted"] is False
    assert receipt["publication"]["push_performed"] is False
    assert receipt["manifest_sha256"] is None


def test_new_preparation_powershell_sources_parse_without_execution() -> None:
    paths = (PREPARER, READINESS, ACTIVATOR, PREPARATION_CONTRACT)
    command = r"""
$errors = New-Object System.Collections.Generic.List[string]
foreach ($path in @($env:WEATHER_PREPARATION_PARSE_PATHS -split [IO.Path]::PathSeparator)) {
    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        $path,
        [ref]$tokens,
        [ref]$parseErrors
    ) | Out-Null
    foreach ($error in @($parseErrors)) {
        $errors.Add("$path :: $($error.Message)")
    }
}
if ($errors.Count -ne 0) {
    throw ($errors -join [Environment]::NewLine)
}
'OK'
"""
    result = _powershell(
        command,
        WEATHER_PREPARATION_PARSE_PATHS=os.pathsep.join(str(path) for path in paths),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"
