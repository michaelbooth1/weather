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
REMOTE_GIT = OPS / "integration_attempt_remote_git.ps1"
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
    push = script.index('-Label "exact reviewed topic publication"')
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
    assert "Get-WeatherIntegrationCanonicalRemoteTip" in script
    assert '-RemoteRef "refs/heads/master"' in script
    assert '"refs/heads/master:refs/remotes/origin/master"' in script
    assert "origin_url = $originUrl" in script
    assert "Assert-WeatherIntegrationCanonicalOriginUrl" in script
    assert "$masterTip -ne $liveMasterTip" in script
    assert '@("fetch", "--no-tags", $originUrl, $fetchRefspec)' in script
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
        "Get-WeatherIntegrationCanonicalRemoteTip",
        'RemoteRef "refs/heads/master"',
        "Live origin master changed after the attempt baseline was frozen",
        "Assert-WeatherIntegrationOriginIdentity",
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
    assert "Assert-WeatherIntegrationRegistrationPreparationState" in registrar
    assert "Assert-WeatherIntegrationPreparationExecutionAuthorization" not in registrar
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


def test_disabled_registration_requires_planned_but_absent_execution_authority(
    tmp_path: Path,
) -> None:
    attempt_root = tmp_path / "attempt-a1"
    preparation_root = Path(str(attempt_root) + ".preparation")
    preparation_root.mkdir()
    manifest_path = attempt_root / "manifest.json"
    intent_path = preparation_root / "preparation-intent.json"
    intent_path.write_text('{"status":"PREPARED"}\n', encoding="utf-8")
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$intentSha = Get-WeatherIntegrationFileSha256 -Path $env:WEATHER_INTENT_PATH
$plan = Get-WeatherIntegrationPreparationAuthorizationPlan `
    -AttemptRoot $env:WEATHER_ATTEMPT_ROOT `
    -AttemptId 'attempt-a1' `
    -ManifestPath $env:WEATHER_MANIFEST_PATH `
    -ExpectedTip ('1' * 40) `
    -PreparationIntentPath $env:WEATHER_INTENT_PATH `
    -PreparationIntentSha256 $intentSha `
    -SuiteTaskName 'WeatherIntegrationSuite_attempt-a1' `
    -MergeTaskName 'WeatherIntegrationMerge_attempt-a1'
$contract = [pscustomobject]@{
    AttemptRoot = $env:WEATHER_ATTEMPT_ROOT
    ManifestPath = $env:WEATHER_MANIFEST_PATH
    Manifest = [pscustomobject]@{
        attempt_id = 'attempt-a1'
        expected_tip = ('1' * 40)
        schedule = [pscustomobject]@{
            suite_task_name = 'WeatherIntegrationSuite_attempt-a1'
            merge_task_name = 'WeatherIntegrationMerge_attempt-a1'
        }
        authorization = [pscustomobject]@{
            preparation = [pscustomobject]@{
                required = $true
                execution_authorization_path = $plan.Path
                execution_authorization_sha256 = $plan.Sha256
                preparation_intent_path = $env:WEATHER_INTENT_PATH
                preparation_intent_sha256 = $intentSha
            }
        }
    }
}
$staged = Assert-WeatherIntegrationRegistrationPreparationState `
    -AttemptContract $contract
if (-not [bool]$staged.Required -or [bool]$staged.Present) {
    throw 'disabled staging did not accept the planned absent token'
}
Write-WeatherIntegrationImmutableJson -Path $plan.Path -Payload $plan.Payload
$prematureAccepted = $false
try {
    Assert-WeatherIntegrationRegistrationPreparationState `
        -AttemptContract $contract | Out-Null
    $prematureAccepted = $true
}
catch { }
if ($prematureAccepted) {
    throw 'disabled staging accepted a pre-existing execution token'
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
    topic = activator.index("activation live canonical origin topic query", revalidation)
    master = activator.index(
        "activation live canonical origin/master query", revalidation
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
$protectedAccepted = $false
try {
    Get-WeatherIntegrationTopicBranchName -BranchRef 'origin/master' | Out-Null
    $protectedAccepted = $true
}
catch { }
if ($valid.minimum_lead_minutes -ne 10 -or $lateAccepted -or
    $remote -ne ('1' * 40) -or $null -ne $missing -or
    $protectedAccepted -or
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


def test_production_branch_is_rejected_before_the_publication_boundary() -> None:
    preparer = PREPARER.read_text(encoding="utf-8-sig")
    creator = CREATOR.read_text(encoding="utf-8-sig")
    topic_validation = preparer.index(
        "$topicBranch = Get-WeatherIntegrationTopicBranchName"
    )
    push = preparer.index('-Label "exact reviewed topic publication"')
    assert topic_validation < push
    assert 'never a production branch' in creator
    assert creator.index('never a production branch') < creator.index(
        'if ($ExpectedTip -notmatch'
    )


def test_schedule_clock_stays_local_but_receipt_evidence_uses_offsets() -> None:
    readiness = READINESS.read_text(encoding="utf-8-sig")
    activation = ACTIVATOR.read_text(encoding="utf-8-sig")
    assert (
        "$scheduleCheckedAt = ConvertFrom-WeatherIntegrationLocalTimestamp"
        in readiness
    )
    assert (
        "$schedulerBoundaryCheckedAt = "
        "ConvertFrom-WeatherIntegrationEvidenceTimestamp"
        in readiness
    )
    assert (
        "$readinessCheckedAt = ConvertFrom-WeatherIntegrationEvidenceTimestamp"
        in activation
    )

    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$first = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
    -Value '2026-08-24T16:27:55.1170635-04:00' -Label 'first'
$second = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
    -Value '2026-08-24T20:27:56.1170635Z' -Label 'second'
if ($first.UtcDateTime -ge $second.UtcDateTime -or
    ($second - $first) -ne [TimeSpan]::FromSeconds(1)) {
    throw 'Offset-bearing evidence timestamps did not compare by instant.'
}
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
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
    disabled_branch = contract.index(
        'if ($taskState -eq "Disabled" -or -not $settingsEnabled)'
    )
    receipt_gate = contract.index(
        "Assert-WeatherIntegrationDisabledTaskRetirementEvidence", disabled_branch
    )
    disabled_continue = contract.index("continue", disabled_branch)
    assert disabled_branch < receipt_gate < disabled_continue
    assert '"AllowDemandStart"' in contract
    assert "@demand-start-enabled" in contract
    assert "@disabled-without-valid-retirement-receipt" in contract
    assert "Assert-WeatherIntegrationTaskRetirementReceipt" in contract
    assert "Assert-WeatherIntegrationFailClosureReceipt" in contract
    assert "-Task $task -RepositoryRoot $resolvedRepositoryRoot" in contract
    assert "$repositoryRoot = Split-Path -Parent" not in contract
    assert "[$retirementFailure]" in contract
    assert "$conflictStart.AddHours(4)" in contract
    assert "$conflictStart -le $MergeAtLocal" in contract
    assert "$SuiteAtLocal -le $conflictEnd" in contract
    assert "retire_integration_attempt_tasks.ps1" in contract
    assert "-RepositoryRoot $RepoRoot" in PREPARER.read_text(encoding="utf-8-sig")
    assert "-RepositoryRoot $repoRoot" in READINESS.read_text(encoding="utf-8-sig")
    assert "-RepositoryRoot $repoRoot" in ACTIVATOR.read_text(encoding="utf-8-sig")


def test_collision_gate_reads_legacy_receipt_from_explicit_production_root(
    tmp_path: Path,
) -> None:
    code_ops = tmp_path / "isolated-code" / "scripts" / "ops"
    code_ops.mkdir(parents=True)
    isolated_contract = code_ops / PREPARATION_CONTRACT.name
    isolated_contract.write_text(
        PREPARATION_CONTRACT.read_text(encoding="utf-8-sig"), encoding="utf-8"
    )
    production_root = tmp_path / "production-evidence"

    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
. $env:WEATHER_PREPARATION_CONTRACT
$productionRoot = [IO.Path]::GetFullPath($env:WEATHER_PRODUCTION_ROOT)
$taskName = 'WeatherIntegrationRecoveryBootstrapSuiteFixed0822'
$triggerAt = '2026-08-22T00:35:00-04:00'
$global:legacyXml = "<Task>`r`n<Settings>`r`n<Enabled>false</Enabled>`r`n</Settings>`r`n</Task>"
$global:legacyTask = [pscustomobject]@{
    TaskName = $taskName
    TaskPath = '\'
    State = 'Disabled'
    Settings = [pscustomobject]@{
        Enabled = $false
        AllowDemandStart = $true
    }
    Actions = @([pscustomobject]@{ Arguments = '' })
    Triggers = @([pscustomobject]@{ StartBoundary = $triggerAt })
}
function Get-ScheduledTask {
    param($ErrorAction)
    return @($global:legacyTask)
}
function Get-ScheduledTaskInfo {
    param([string]$TaskName, [string]$TaskPath, $ErrorAction)
    return [pscustomobject]@{
        LastRunTime = [datetime]'2026-08-22T00:35:00'
        LastTaskResult = 0
        NextRunTime = $null
    }
}
function Export-ScheduledTask {
    param([string]$TaskName, [string]$TaskPath, $ErrorAction)
    return $global:legacyXml
}
$receiptRoot = Join-Path $productionRoot 'data\integration_attempts\legacy-task-retirements'
New-Item -ItemType Directory -Path $receiptRoot -Force | Out-Null
$receiptPath = Join-Path $receiptRoot "$taskName.json"
$receipt = [ordered]@{
    schema = 'weather_legacy_integration_bootstrap_task_retirement_v1'
    status = 'PASS'
    classification = 'EXPIRED_LEGACY_BOOTSTRAP_TASK_RETIRED'
    task_name = $taskName
    task_xml_sha256 = Get-WeatherLegacyBootstrapTaskXmlSha256 -Xml $global:legacyXml
    trigger_at = $triggerAt
    last_run_time = $triggerAt
    last_task_result = 0
    retired_at_local = '2026-08-24T20:00:00-04:00'
    review_reference = 'cross-worktree-root-regression'
    confirmation = 'RETIRE_EXACT_EXPIRED_LEGACY_INTEGRATION_TASK'
    state = 'Disabled'
    enabled = $false
    safety = [ordered]@{
        authority = 'NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY'
        credential_value_access_authorized = $false
        live_exchange_mutation_authorized = $false
    }
}
$encoding = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText(
    $receiptPath,
    ($receipt | ConvertTo-Json -Depth 10) + [Environment]::NewLine,
    $encoding
)
Assert-WeatherIntegrationNoActiveAttemptCollision `
    -SuiteAtLocal ([datetime]'2026-08-25T00:40:00') `
    -MergeAtLocal ([datetime]'2026-08-25T01:20:00') `
    -RepositoryRoot $productionRoot
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
        WEATHER_PREPARATION_CONTRACT=str(isolated_contract),
        WEATHER_PRODUCTION_ROOT=str(production_root),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


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
$global:retirementReceiptValid = $false
$global:expectedRepositoryRoot = 'C:\synthetic-production-root'
function Assert-WeatherIntegrationDisabledTaskRetirementEvidence {
    param([object]$Task, [string]$RepositoryRoot)
    if ($RepositoryRoot -cne $global:expectedRepositoryRoot) {
        throw 'collision gate did not forward the explicit production root'
    }
    if (-not $global:retirementReceiptValid) {
        throw 'synthetic missing or invalid retirement receipt'
    }
}
function New-TestTask(
    [string]$Name,
    [string]$State,
    [bool]$Enabled,
    [string]$Arguments,
    [bool]$AllowDemandStart = $false
) {
    return [pscustomobject]@{
        TaskName = $Name
        TaskPath = '\'
        State = $State
        Settings = [pscustomobject]@{
            Enabled = $Enabled
            AllowDemandStart = $AllowDemandStart
        }
        Actions = @([pscustomobject]@{ Arguments = $Arguments })
    }
}
$suite = [datetime]'2026-08-25T00:40:00'
$merge = [datetime]'2026-08-25T01:20:00'
foreach ($case in @(
    [pscustomobject]@{ Task = (New-TestTask 'WeatherIntegrationSuite_old' 'Running' $false ''); Label = 'running disabled' },
    [pscustomobject]@{ Task = (New-TestTask 'WeatherMergeSensitiveDriver' 'Queued' $false ''); Label = 'queued disabled' },
    [pscustomobject]@{ Task = (New-TestTask 'weathermERgesensitivedriver' 'Running' $false ''); Label = 'case-variant sensitive driver' },
    [pscustomobject]@{ Task = (New-TestTask 'WeatherMergeSensitiveDriver' 'Unknown' $true ''); Label = 'unknown' },
    [pscustomobject]@{ Task = (New-TestTask 'WeatherIntegrationSuite_manual' 'Ready' $true '' $true); Label = 'manual resurrection' },
    [pscustomobject]@{ Task = (New-TestTask 'WeatherIntegrationRecoveryBootstrapMergeFixed0822' 'Ready' $true 'quiet_window_merge.ps1' $true); Label = 'legacy quiet manual resurrection' }
)) {
    $global:tasks = @($case.Task)
    $blocked = $false
    try {
        Assert-WeatherIntegrationNoActiveAttemptCollision `
            -SuiteAtLocal $suite -MergeAtLocal $merge `
            -RepositoryRoot $global:expectedRepositoryRoot
    }
    catch { $blocked = $true }
    if (-not $blocked) { throw "$($case.Label) task bypassed collision gate" }
}
$global:tasks = @(
    (New-TestTask 'WeatherIntegrationSuite_old' 'Ready' $true '' $true),
    (New-TestTask 'WeatherIntegrationRecoveryBootstrapMergeFixed0822' 'Ready' $true 'quiet_window_merge.ps1' $true)
)
$aggregateFailure = ''
try {
    Assert-WeatherIntegrationNoActiveAttemptCollision `
        -SuiteAtLocal $suite -MergeAtLocal $merge `
        -RepositoryRoot $global:expectedRepositoryRoot
}
catch { $aggregateFailure = $_.Exception.Message }
if ($aggregateFailure -notlike '*WeatherIntegrationSuite_old@demand-start-enabled*' -or
    $aggregateFailure -notlike '*WeatherIntegrationRecoveryBootstrapMergeFixed0822@demand-start-enabled*' -or
    $aggregateFailure -notlike '*reviewed cleanup for a legacy non-attempt task*') {
    throw 'Collision gate hid one of multiple exact legacy blockers.'
}
$global:tasks = @(
    New-TestTask 'WeatherIntegrationSuite_retired' 'Disabled' $false '' $true
)
$disabledFailure = ''
try {
    Assert-WeatherIntegrationNoActiveAttemptCollision `
        -SuiteAtLocal $suite -MergeAtLocal $merge `
        -RepositoryRoot $global:expectedRepositoryRoot
}
catch { $disabledFailure = $_.Exception.Message }
if ($disabledFailure -notlike
        '*WeatherIntegrationSuite_retired@disabled-without-valid-retirement-receipt*' -or
    $disabledFailure -notlike '*synthetic missing or invalid retirement receipt*') {
    throw 'Disabled demand-start task escaped without a valid retirement receipt.'
}
$global:retirementReceiptValid = $true
Assert-WeatherIntegrationNoActiveAttemptCollision `
    -SuiteAtLocal $suite -MergeAtLocal $merge `
    -RepositoryRoot $global:expectedRepositoryRoot
$global:retirementReceiptValid = $false
$global:tasks = @(New-TestTask 'WeatherIntegrationSuite_spent' 'Ready' $true '')
$global:nextRun = $null
Assert-WeatherIntegrationNoActiveAttemptCollision `
    -SuiteAtLocal $suite -MergeAtLocal $merge `
    -RepositoryRoot $global:expectedRepositoryRoot
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
        WEATHER_PREPARATION_CONTRACT=str(PREPARATION_CONTRACT),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_collision_gate_handles_non_exec_actions_without_arguments() -> None:
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
. $env:WEATHER_PREPARATION_CONTRACT
$global:tasks = @()
$global:nextRun = $null
$global:taskInfoCalls = 0
function Get-ScheduledTask { param($ErrorAction) return @($global:tasks) }
function Get-ScheduledTaskInfo {
    param([string]$TaskName, [string]$TaskPath, $ErrorAction)
    $global:taskInfoCalls++
    return [pscustomobject]@{ NextRunTime = $global:nextRun }
}
function New-NonExecTask([string]$Name) {
    return [pscustomobject]@{
        TaskName = $Name
        TaskPath = '\'
        State = 'Ready'
        Settings = [pscustomobject]@{ Enabled = $true }
        Actions = @([pscustomobject]@{ ClassId = '{00000000-0000-0000-0000-000000000000}' })
    }
}
$suite = [datetime]'2026-08-25T00:40:00'
$merge = [datetime]'2026-08-25T01:20:00'
$global:tasks = @(New-NonExecTask 'BenignComHandlerTask')
Assert-WeatherIntegrationNoActiveAttemptCollision `
    -SuiteAtLocal $suite -MergeAtLocal $merge `
    -RepositoryRoot 'C:\synthetic-production-root'
if ($global:taskInfoCalls -ne 0) {
    throw 'benign non-Exec action was treated as protected merge work'
}
$global:tasks = @(New-NonExecTask 'WeatherMergeSensitiveDriver')
$global:nextRun = $suite.AddMinutes(5)
$blocked = $false
try {
    Assert-WeatherIntegrationNoActiveAttemptCollision `
        -SuiteAtLocal $suite -MergeAtLocal $merge `
        -RepositoryRoot 'C:\synthetic-production-root'
}
catch { $blocked = $true }
if (-not $blocked -or $global:taskInfoCalls -ne 1) {
    throw 'non-Exec sensitive driver bypassed collision protection'
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


def test_attempt_closure_requires_exact_provably_terminal_states() -> None:
    contract = ATTEMPT_CONTRACT.read_text(encoding="utf-8-sig")

    assert '[string]$task.State -notin @("Ready", "Disabled")' in contract
    assert "not provably terminal and may not be disabled" in contract


def test_attempt_wrappers_bind_frozen_date_and_disallow_demand_start() -> None:
    contract = ATTEMPT_CONTRACT.read_text(encoding="utf-8-sig")
    registrar = REGISTRAR.read_text(encoding="utf-8-sig")
    suite = SUITE.read_text(encoding="utf-8-sig")
    merge = MERGE.read_text(encoding="utf-8-sig")

    assert "$script:WeatherIntegrationAttemptLegacyTaskBindingContract" in contract
    assert "DisallowDemandStart = $true" in registrar
    assert "Integration-attempt suite may run only on its immutable scheduled local date" in suite
    assert "Integration-attempt merge may run only on its immutable scheduled local date" in merge


def test_remote_git_is_noninteractive_bounded_and_kills_on_timeout(
    tmp_path: Path,
) -> None:
    helper = REMOTE_GIT.read_text(encoding="utf-8-sig")
    assert 'GIT_TERMINAL_PROMPT = "0"' in helper
    assert 'GCM_INTERACTIVE = "Never"' in helper
    assert "ReadToEndAsync()" in helper
    assert "WaitForExit($TimeoutSeconds * 1000)" in helper
    assert 'Arguments = "/PID $processId /T /F"' in helper
    assert "[int]$killer.ExitCode -ne 0" in helper
    assert "timed-out parent did not prove exit" in helper
    assert "termination could not be proved" in helper
    assert '@("ls-remote", "fetch", "push")' in helper

    descendant = tmp_path / "bounded-descendant.ps1"
    descendant.write_text(
        "Start-Sleep -Seconds 4\n"
        "[IO.File]::WriteAllText($env:WEATHER_DESCENDANT_MARKER, 'escaped')\n",
        encoding="utf-8",
    )
    parent = tmp_path / "bounded-parent.ps1"
    parent.write_text(
        "param([string]$DescendantScript)\n"
        "$powershell = Join-Path $PSHOME 'powershell.exe'\n"
        "Start-Process -FilePath $powershell -WindowStyle Hidden "
        "-ArgumentList @('-NoProfile', '-NonInteractive', '-File', $DescendantScript)\n"
        "Start-Sleep -Seconds 20\n",
        encoding="utf-8",
    )
    marker = tmp_path / "escaped-descendant.txt"

    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_REMOTE_GIT
$powershell = Join-Path $PSHOME 'powershell.exe'
$failureClosed = $false
try {
    Invoke-WeatherIntegrationBoundedProcess `
        -Executable $powershell `
        -Arguments @('-NoProfile', '-NonInteractive', '-Command', 'exit 23') `
        -WorkingDirectory $env:WEATHER_ROOT `
        -TimeoutSeconds 5 `
        -Label 'synthetic failure' | Out-Null
}
catch {
    $failureClosed = $_.Exception.Message -like '*exit code 23*'
}
$started = Get-Date
$timeoutClosed = $false
try {
    Invoke-WeatherIntegrationBoundedProcess `
        -Executable $powershell `
        -Arguments @(
            '-NoProfile', '-NonInteractive', '-File', $env:WEATHER_PARENT_SCRIPT,
            '-DescendantScript', $env:WEATHER_DESCENDANT_SCRIPT
        ) `
        -WorkingDirectory $env:WEATHER_ROOT `
        -TimeoutSeconds 1 `
        -Label 'synthetic timeout' | Out-Null
}
catch {
    $timeoutClosed = (
        $_.Exception.Message -like '*timed out after 1 seconds*' -and
        $_.Exception.Message -like '*proved its child process tree was terminated*'
    )
}
$elapsed = ((Get-Date) - $started).TotalSeconds
Start-Sleep -Seconds 5
$descendantEscaped = Test-Path -LiteralPath $env:WEATHER_DESCENDANT_MARKER
if (-not $failureClosed -or -not $timeoutClosed -or $elapsed -gt 8 -or
    $descendantEscaped) {
    throw "Bounded process contract failed: failure=$failureClosed timeout=$timeoutClosed elapsed=$elapsed"
}
'OK'
"""
    result = _powershell(
        command,
        WEATHER_REMOTE_GIT=str(REMOTE_GIT),
        WEATHER_ROOT=str(ROOT),
        WEATHER_PARENT_SCRIPT=str(parent),
        WEATHER_DESCENDANT_SCRIPT=str(descendant),
        WEATHER_DESCENDANT_MARKER=str(marker),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_frozen_origin_url_rejects_fork_substitution(tmp_path: Path) -> None:
    repo = tmp_path / "origin-binding"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q", str(repo)], check=True, capture_output=True, text=True
    )
    expected = "https://github.com/michaelbooth1/weather.git"
    subprocess.run(
        ["git", "-C", str(repo), "config", "remote.origin.url", expected],
        check=True,
        capture_output=True,
        text=True,
    )
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_REMOTE_GIT
Assert-WeatherIntegrationCanonicalOriginUrl `
    -Root $env:WEATHER_TEST_REPO `
    -ExpectedUrl 'https://github.com/michaelbooth1/weather.git' `
    -Phase 'test initial binding' | Out-Null
& git -C $env:WEATHER_TEST_REPO config remote.origin.url `
    'https://github.com/substituted-fork/weather.git'
if ($LASTEXITCODE -ne 0) { throw 'Could not apply synthetic fork substitution.' }
$substitutionAccepted = $false
try {
    Assert-WeatherIntegrationCanonicalOriginUrl `
        -Root $env:WEATHER_TEST_REPO `
        -ExpectedUrl 'https://github.com/michaelbooth1/weather.git' `
        -Phase 'test substituted binding' | Out-Null
    $substitutionAccepted = $true
}
catch { }
if ($substitutionAccepted) { throw 'A substituted origin fork was accepted.' }
'OK'
"""
    result = _powershell(
        command,
        WEATHER_REMOTE_GIT=str(REMOTE_GIT),
        WEATHER_TEST_REPO=str(repo),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_frozen_origin_rejects_pushurl_and_url_rewrites_in_effective_config(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "origin-routing"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q", str(repo)], check=True, capture_output=True, text=True
    )
    expected = "https://github.com/michaelbooth1/weather.git"
    subprocess.run(
        ["git", "-C", str(repo), "config", "remote.origin.url", expected],
        check=True,
        capture_output=True,
        text=True,
    )
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_REMOTE_GIT
function Assert-Rejected([string]$ExpectedFragment) {
    $accepted = $false
    try {
        Assert-WeatherIntegrationCanonicalOriginUrl `
            -Root $env:WEATHER_TEST_REPO `
            -ExpectedUrl 'https://github.com/michaelbooth1/weather.git' `
            -Phase 'synthetic routing substitution' | Out-Null
        $accepted = $true
    }
    catch {
        if ($_.Exception.Message -notlike "*$ExpectedFragment*") { throw }
    }
    if ($accepted) { throw "Unsafe Git routing config was accepted: $ExpectedFragment" }
}
& git -C $env:WEATHER_TEST_REPO config remote.origin.pushurl `
    'https://github.com/substituted-fork/weather.git'
if ($LASTEXITCODE -ne 0) { throw 'Could not configure synthetic pushurl.' }
Assert-Rejected 'pushurl'
& git -C $env:WEATHER_TEST_REPO config --unset-all remote.origin.pushurl
if ($LASTEXITCODE -ne 0) { throw 'Could not remove synthetic pushurl.' }
& git -C $env:WEATHER_TEST_REPO config `
    'url.https://github.com/substituted-fork/.pushInsteadOf' `
    'https://github.com/'
if ($LASTEXITCODE -ne 0) { throw 'Could not configure synthetic pushInsteadOf.' }
Assert-Rejected 'insteadOf/pushInsteadOf'
& git -C $env:WEATHER_TEST_REPO config --unset-all `
    'url.https://github.com/substituted-fork/.pushInsteadOf'
if ($LASTEXITCODE -ne 0) { throw 'Could not remove synthetic pushInsteadOf.' }
'OK'
"""
    result = _powershell(
        command,
        WEATHER_REMOTE_GIT=str(REMOTE_GIT),
        WEATHER_TEST_REPO=str(repo),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"

    isolated_global = tmp_path / "synthetic-global.gitconfig"
    subprocess.run(
        [
            "git",
            "config",
            "--file",
            str(isolated_global),
            "url.https://github.com/substituted-global/.insteadOf",
            "https://github.com/",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    global_result = _powershell(
        r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_REMOTE_GIT
Assert-WeatherIntegrationCanonicalOriginUrl `
    -Root $env:WEATHER_TEST_REPO `
    -ExpectedUrl 'https://github.com/michaelbooth1/weather.git' `
    -Phase 'synthetic global rewrite' | Out-Null
""",
        WEATHER_REMOTE_GIT=str(REMOTE_GIT),
        WEATHER_TEST_REPO=str(repo),
        GIT_CONFIG_GLOBAL=str(isolated_global),
    )
    assert global_result.returncode != 0
    assert "insteadOf/pushInsteadOf" in global_result.stderr


def test_origin_identity_is_frozen_and_rechecked_at_every_live_boundary() -> None:
    preparer = PREPARER.read_text(encoding="utf-8-sig")
    creator = CREATOR.read_text(encoding="utf-8-sig")
    readiness = READINESS.read_text(encoding="utf-8-sig")
    activation = ACTIVATOR.read_text(encoding="utf-8-sig")
    contract = ATTEMPT_CONTRACT.read_text(encoding="utf-8-sig")
    merge = MERGE.read_text(encoding="utf-8-sig")
    closer = (OPS / "close_integration_attempt.ps1").read_text(encoding="utf-8-sig")
    quiet_merge = (OPS / "quiet_window_merge.ps1").read_text(encoding="utf-8-sig")

    assert "origin_url = $originUrl" in preparer
    assert "origin_url = $originUrl" in creator
    assert '"remote", "origin_url", "remote_ref"' in readiness
    assert "Assert-WeatherIntegrationOriginIdentity" in readiness
    assert "Assert-WeatherIntegrationOriginIdentity" in activation
    assert "Assert-WeatherIntegrationOriginIdentity" in contract
    assert "Assert-WeatherIntegrationOriginIdentity" in closer
    assert '"-ExpectedOriginUrl", $ExpectedOriginUrl' in merge
    assert "-ExpectedOriginUrl ([string]$manifest.baseline.origin_url)" in merge
    assert "RequireLiveOrigin requires the frozen canonical origin URL" in quiet_merge
    assert "remote.origin.pushurl" in REMOTE_GIT.read_text(encoding="utf-8-sig")
    assert "url.*.insteadOf/pushInsteadOf" in REMOTE_GIT.read_text(encoding="utf-8-sig")
    assert "Get-WeatherIntegrationCanonicalRemoteTip" in quiet_merge
    start_push = quiet_merge.index("Start-ScheduledTask -TaskName WeatherOneShotPush")
    immediate_identity = quiet_merge.index(
        "quiet-window immediate pre-push origin identity"
    )
    canonical_ack = quiet_merge.index(
        "quiet-window post-push canonical origin/master verification"
    )
    pushed_receipt = quiet_merge.index('$publicationAcknowledged = $true')
    assert immediate_identity < start_push < canonical_ack < pushed_receipt


def test_real_credential_reconcile_a1_v1_registration_evidence_flows_real_readers(
    tmp_path: Path,
) -> None:
    fixture = (
        ROOT
        / "tests"
        / "fixtures"
        / "operations"
        / "credential_reconcile_0824_a1_registration_v1.json"
    )
    evidence = json.loads(fixture.read_text(encoding="utf-8"))
    assert evidence["source"].startswith("production credential-reconcile-0824-a1")
    assert evidence["intent"]["schema"] == (
        "weather_integration_attempt_registration_intent_v1"
    )
    assert evidence["receipt"]["schema"] == (
        "weather_integration_attempt_registration_receipt_v1"
    )
    assert evidence["intent"]["suite"]["settings"]["allow_demand_start"] is True
    assert evidence["intent"]["merge"]["settings"]["allow_demand_start"] is True
    assert evidence["receipt"]["suite"]["registered"] is True
    assert evidence["receipt"]["merge"]["registered"] is True
    assert evidence["closure"]["schema"] == (
        "weather_integration_attempt_closure_receipt_v1"
    )
    assert evidence["closure"]["status"] == "FAIL"

    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$fixture = Get-Content -LiteralPath $env:WEATHER_V1_FIXTURE -Raw | ConvertFrom-Json
$attemptRoot = [IO.Path]::GetFullPath($env:WEATHER_V1_ATTEMPT_ROOT)
[IO.Directory]::CreateDirectory($attemptRoot) | Out-Null
$suiteScript = Join-Path $env:WEATHER_ROOT 'scripts\ops\integration_attempt_suite.ps1'
$mergeScript = Join-Path $env:WEATHER_ROOT 'scripts\ops\integration_attempt_merge.ps1'
$manifestPath = Join-Path $attemptRoot 'manifest.json'
$intentPath = Join-Path $attemptRoot 'registration-intent.json'
$receiptPath = Join-Path $attemptRoot 'registration-receipt.json'
$closurePath = Join-Path $attemptRoot 'closure-receipt.json'
$manifestSha = ('c' * 64)
$manifest = [pscustomobject]@{
    attempt_id = [string]$fixture.intent.attempt_id
    attempt_root = $attemptRoot
    repo_root = $env:WEATHER_ROOT
    expected_tip = [string]$fixture.closure.expected_tip
    baseline = [pscustomobject]@{
        master = [string]$fixture.closure.post_disable_proof.master
        origin_master = [string]$fixture.closure.post_disable_proof.origin_master
    }
    schedule = [pscustomobject]@{
        suite_task_name = [string]$fixture.intent.suite.task_name
        merge_task_name = [string]$fixture.intent.merge.task_name
        suite_at_local = [string]$fixture.intent.suite.trigger.at_local
        merge_at_local = [string]$fixture.intent.merge.trigger.at_local
    }
    orchestration = [pscustomobject]@{
        attempt_suite = [pscustomobject]@{
            path = $suiteScript
            sha256 = [string]$fixture.intent.suite.script_sha256
        }
        attempt_merge = [pscustomobject]@{
            path = $mergeScript
            sha256 = [string]$fixture.intent.merge.script_sha256
        }
    }
    evidence = [pscustomobject]@{
        registration_intent = $intentPath
        registration_receipt = $receiptPath
        closure_receipt = $closurePath
    }
}
$attempt = [pscustomobject]@{
    Manifest = $manifest
    ManifestPath = $manifestPath
    ManifestSha256 = $manifestSha
    AttemptRoot = $attemptRoot
}
$intent = $fixture.intent
$receipt = $fixture.receipt
$intent.intent_path = $intentPath
$intent.manifest_path = $manifestPath
$intent.manifest_sha256 = $manifestSha
$receipt.manifest_path = $manifestPath
$receipt.manifest_sha256 = $manifestSha
$receipt.registration_intent_path = $intentPath
foreach ($role in @('suite', 'merge')) {
    $expected = Get-WeatherIntegrationExpectedTaskBinding `
        -AttemptContract $attempt -Role $role `
        -UserId ([string]$intent.principal.user_id) `
        -BindingContract ([string]$intent.binding_contract)
    $intent.$role.arguments = [string]$expected.arguments
    $intent.$role.working_directory = [string]$expected.working_directory
    $receipt.$role.arguments = [string]$expected.arguments
    $receipt.$role.working_directory = [string]$expected.working_directory
}
$encoding = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText(
    $intentPath,
    ($intent | ConvertTo-Json -Depth 20) + [Environment]::NewLine,
    $encoding
)
$receipt.registration_intent_sha256 = Get-WeatherIntegrationFileSha256 -Path $intentPath
[IO.File]::WriteAllText(
    $receiptPath,
    ($receipt | ConvertTo-Json -Depth 20) + [Environment]::NewLine,
    $encoding
)
$intentResult = Assert-WeatherIntegrationRegistrationIntent `
    -AttemptContract $attempt
$receiptResult = Assert-WeatherIntegrationRegistrationReceipt `
    -AttemptContract $attempt -RequirePass
if ([string]$intentResult.Intent.schema -ne
        $script:WeatherIntegrationAttemptLegacyRegistrationIntentSchema -or
    [string]$receiptResult.Receipt.schema -ne
        $script:WeatherIntegrationAttemptLegacyRegistrationReceiptSchema -or
    -not [bool]$receiptResult.Intent.suite.settings.allow_demand_start -or
    -not [bool]$receiptResult.Intent.merge.settings.allow_demand_start) {
    throw 'The real historical v1 evidence did not survive the production readers.'
}
$intent.suite.settings.allow_demand_start = $false
[IO.File]::WriteAllText(
    $intentPath,
    ($intent | ConvertTo-Json -Depth 20) + [Environment]::NewLine,
    $encoding
)
$tamperAccepted = $false
try {
    Assert-WeatherIntegrationRegistrationReceipt `
        -AttemptContract $attempt -RequirePass | Out-Null
    $tamperAccepted = $true
}
catch { }
if ($tamperAccepted) { throw 'Tampered historical v1 intent was accepted.' }
$intent.suite.settings.allow_demand_start = $true
[IO.File]::WriteAllText(
    $intentPath,
    ($intent | ConvertTo-Json -Depth 20) + [Environment]::NewLine,
    $encoding
)
$receipt.registration_intent_sha256 = Get-WeatherIntegrationFileSha256 -Path $intentPath
[IO.File]::WriteAllText(
    $receiptPath,
    ($receipt | ConvertTo-Json -Depth 20) + [Environment]::NewLine,
    $encoding
)
$closure = $fixture.closure
$closure.manifest_path = $manifestPath
$closure.manifest_sha256 = $manifestSha
$closure.registration_evidence.registration_intent_path = $intentPath
$closure.registration_evidence.registration_intent_sha256 = `
    Get-WeatherIntegrationFileSha256 -Path $intentPath
$closure.registration_evidence.registration_receipt_path = $receiptPath
$closure.registration_evidence.registration_receipt_sha256 = `
    Get-WeatherIntegrationFileSha256 -Path $receiptPath
foreach ($row in @($closure.preserved_evidence)) {
    $leaf = Split-Path -Leaf ([string]$row.path)
    $portablePath = Join-Path $attemptRoot $leaf
    if ($leaf -eq 'registration-intent.json') {
        $portablePath = $intentPath
    }
    elseif ($leaf -eq 'registration-receipt.json') {
        $portablePath = $receiptPath
    }
    else {
        [IO.File]::WriteAllText(
            $portablePath, "portable historical evidence: $leaf", $encoding
        )
    }
    $row.path = $portablePath
    $row.sha256 = Get-WeatherIntegrationFileSha256 -Path $portablePath
}
[IO.File]::WriteAllText(
    $closurePath,
    ($closure | ConvertTo-Json -Depth 20) + [Environment]::NewLine,
    $encoding
)
# The reader below is the production closure reader. Only the CIM-rich
# Scheduler-object comparator is isolated because this test has no Scheduler.
function Assert-WeatherIntegrationScheduledTaskObject {
    param([object]$Task, [object]$BindingEvidence, [string]$Role)
    return $Task
}
foreach ($role in @('suite', 'merge')) {
    $taskName = if ($role -eq 'suite') {
        [string]$manifest.schedule.suite_task_name
    }
    else { [string]$manifest.schedule.merge_task_name }
    $task = [pscustomobject]@{
        TaskName = $taskName
        TaskPath = '\'
        State = 'Disabled'
        Settings = [pscustomobject]@{ Enabled = $false }
    }
    Assert-WeatherIntegrationFailClosureReceipt `
        -AttemptContract $attempt -Task $task -Role $role | Out-Null
}
$fullPreservedEvidence = @($closure.preserved_evidence)
$manifest.evidence.registration_receipt = Join-Path $attemptRoot 'missing-registration-receipt.json'
$closure.registration_evidence.registration_receipt_path = `
    [string]$manifest.evidence.registration_receipt
$closure.registration_evidence.registration_receipt_sha256 = $null
$closure.preserved_evidence = @($fullPreservedEvidence | Where-Object {
    (Split-Path -Leaf ([string]$_.path)) -ne 'registration-receipt.json'
})
[IO.File]::WriteAllText(
    $closurePath,
    ($closure | ConvertTo-Json -Depth 20) + [Environment]::NewLine,
    $encoding
)
Assert-WeatherIntegrationFailClosureReceipt `
    -AttemptContract $attempt `
    -Task ([pscustomobject]@{
        TaskName = [string]$manifest.schedule.suite_task_name
        TaskPath = '\'
        State = 'Disabled'
        Settings = [pscustomobject]@{ Enabled = $false }
    }) `
    -Role suite | Out-Null
$manifest.evidence.registration_receipt = $receiptPath
$closure.registration_evidence.registration_receipt_path = $receiptPath
$closure.registration_evidence.registration_receipt_sha256 = `
    Get-WeatherIntegrationFileSha256 -Path $receiptPath
$closure.preserved_evidence = $fullPreservedEvidence
$closure.tasks = @($closure.tasks[0])
[IO.File]::WriteAllText(
    $closurePath,
    ($closure | ConvertTo-Json -Depth 20) + [Environment]::NewLine,
    $encoding
)
$corruptClosureAccepted = $false
try {
    Assert-WeatherIntegrationFailClosureReceipt `
        -AttemptContract $attempt `
        -Task ([pscustomobject]@{
            TaskName = [string]$manifest.schedule.suite_task_name
            TaskPath = '\'
            State = 'Disabled'
            Settings = [pscustomobject]@{ Enabled = $false }
        }) `
        -Role suite | Out-Null
    $corruptClosureAccepted = $true
}
catch { }
if ($corruptClosureAccepted) { throw 'Corrupt historical FAIL closure was accepted.' }
$mergeReceiptPath = Join-Path $attemptRoot 'merge-receipt.json'
$manifest.evidence | Add-Member `
    -NotePropertyName merge_receipt -NotePropertyValue $mergeReceiptPath
[IO.File]::WriteAllText(
    $mergeReceiptPath,
    ([ordered]@{
        schema = $script:WeatherIntegrationAttemptMergeReceiptSchema
        status = 'PASS'
        manifest_sha256 = $manifestSha
    } | ConvertTo-Json -Depth 5) + [Environment]::NewLine,
    $encoding
)
$retirementPath = Join-Path $attemptRoot 'task-retirement-receipt.json'
$preDisable = @()
$postDisable = @()
foreach ($role in @('suite', 'merge')) {
    $taskName = if ($role -eq 'suite') {
        [string]$manifest.schedule.suite_task_name
    }
    else { [string]$manifest.schedule.merge_task_name }
    $preDisable += [ordered]@{
        role = $role
        task_name = $taskName
        state = 'Ready'
        enabled = $true
        allow_demand_start = $true
        last_run_time = '2026-08-24T00:30:00-04:00'
        last_task_result = 0
    }
    $postDisable += [ordered]@{
        task_name = $taskName
        exists = $true
        disabled = $true
        last_task_result = 0
    }
}
$retirement = [ordered]@{
    schema = $script:WeatherIntegrationTaskRetirementReceiptSchema
    status = 'PASS'
    classification = 'SUCCESSFUL_ATTEMPT_TASKS_RETIRED'
    attempt_id = [string]$manifest.attempt_id
    manifest_path = $manifestPath
    manifest_sha256 = $manifestSha
    merge_receipt_path = $mergeReceiptPath
    merge_receipt_sha256 = Get-WeatherIntegrationFileSha256 -Path $mergeReceiptPath
    retired_at_local = '2026-08-24T04:00:00-04:00'
    review_reference = 'portable real-v1 reader regression'
    confirmation = $script:WeatherIntegrationTaskRetirementConfirmation
    pre_disable = $preDisable
    post_disable = $postDisable
    safety = [ordered]@{
        authority = 'NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY'
        credential_value_access_authorized = $false
        live_exchange_mutation_authorized = $false
    }
}
[IO.File]::WriteAllText(
    $retirementPath,
    ($retirement | ConvertTo-Json -Depth 20) + [Environment]::NewLine,
    $encoding
)
foreach ($role in @('suite', 'merge')) {
    $taskName = if ($role -eq 'suite') {
        [string]$manifest.schedule.suite_task_name
    }
    else { [string]$manifest.schedule.merge_task_name }
    Assert-WeatherIntegrationTaskRetirementReceipt `
        -AttemptContract $attempt `
        -Task ([pscustomobject]@{
            TaskName = $taskName
            TaskPath = '\'
            State = 'Disabled'
            Settings = [pscustomobject]@{ Enabled = $false }
        }) `
        -Role $role | Out-Null
}
$retirement.post_disable = @($retirement.post_disable[0])
[IO.File]::WriteAllText(
    $retirementPath,
    ($retirement | ConvertTo-Json -Depth 20) + [Environment]::NewLine,
    $encoding
)
$partialRetirementAccepted = $false
try {
    Assert-WeatherIntegrationTaskRetirementReceipt `
        -AttemptContract $attempt `
        -Task ([pscustomobject]@{
            TaskName = [string]$manifest.schedule.suite_task_name
            TaskPath = '\'
            State = 'Disabled'
            Settings = [pscustomobject]@{ Enabled = $false }
        }) `
        -Role suite | Out-Null
    $partialRetirementAccepted = $true
}
catch { }
if ($partialRetirementAccepted) { throw 'Partial task retirement was accepted.' }
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
        WEATHER_V1_FIXTURE=str(fixture),
        WEATHER_ROOT=str(ROOT),
        WEATHER_V1_ATTEMPT_ROOT=str(tmp_path / "historical-a1"),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


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
    paths = (PREPARER, READINESS, ACTIVATOR, PREPARATION_CONTRACT, REMOTE_GIT)
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
