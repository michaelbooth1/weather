import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


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
CLOSER = OPS / "close_integration_attempt.ps1"


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
    qualification_preflight = script.index('-Label "pre-arming integration preflight"')
    qualification_full_suite = script.index('-Label "pre-arming full bounded suite"')
    creator = script.index('-Label "integration attempt creator"')
    registrar = script.index('-Label "integration attempt registrar"')
    readiness = script.index('-Label "integration attempt readiness assertion"')
    activator = script.index('-Label "integration attempt activator"')

    assert (
        schedule_gate
        < creator_preflight
        < push
        < qualification_preflight
        < qualification_full_suite
        < creator
        < registrar
        < readiness
        < activator
    )
    assert 'MinimumLeadMinutes 10' in script
    assert script.count("Assert-WeatherIntegrationPreparationSchedule") == 4
    assert script.count("Assert-WeatherIntegrationPrearmingQualificationWindow") == 3
    assert script.index("$publicationSchedule = Assert-WeatherIntegrationPreparationSchedule") < push
    assert script.index("$registrationSchedule = Assert-WeatherIntegrationPreparationSchedule") < registrar
    assert (
        script.index("$qualificationSchedule = Assert-WeatherIntegrationPreparationSchedule")
        < creator
    )
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
    assert "$script:WeatherIntegrationAttemptPrearmingQualificationSchema" in script
    assert 'status = "FAIL"' in script
    assert script.rindex('$status = "PASS"') > activator
    assert "close_integration_attempt.ps1" in script
    assert "Canonical closure failed; exact task terminality is unproved" in script
    assert "Assert-WeatherIntegrationCurrentFailClosure" in script
    assert script.rindex("Assert-WeatherIntegrationCurrentFailClosure") > script.index(
        '-Label "integration attempt closer"'
    )
    assert "receipt_sha256 = $closureReceiptSha256" in script
    assert '-Label "integration attempt closer"' in script
    assert '"-PreflightOnly"' in script
    assert "Assert-WeatherIntegrationNoActiveAttemptCollision" in script
    assert script.index("Assert-WeatherIntegrationNoActiveAttemptCollision") < push


def test_task_activation_requires_separate_exact_owner_confirmation() -> None:
    preparer = PREPARER.read_text(encoding="utf-8-sig")
    activator = ACTIVATOR.read_text(encoding="utf-8-sig")

    literal = "AUTHORIZE_EXACT_INTEGRATION_TASK_ACTIVATION"
    assert (
        '[ValidateSet("AUTHORIZE_DISABLED_INTEGRATION_TASK_REGISTRATION")]'
        in preparer
    )
    assert f'[ValidateSet("{literal}")]' in preparer
    assert f'[ValidateSet("{literal}")]' in activator
    assert "activation_confirmation = $ActivationConfirmation" in preparer
    assert '"scheduler_confirmation", "activation_confirmation"' in (
        ATTEMPT_CONTRACT.read_text(encoding="utf-8-sig")
    )
    activation = preparer.index('$stage = "activate_exact_tasks"')
    assert preparer.index("$ActivationConfirmation -cne", activation) < preparer.index(
        '"-ActivationConfirmation", $ActivationConfirmation', activation
    )
    mutation = activator.index('$stage = "activation_boundary"')
    assert activator.index("$ActivationConfirmation -cne", mutation) < activator.index(
        "Enable-ScheduledTask", mutation
    )


def test_creator_preflight_covers_every_locally_knowable_creation_rejection() -> None:
    script = CREATOR.read_text(encoding="utf-8-sig")
    contract = ATTEMPT_CONTRACT.read_text(encoding="utf-8-sig")
    preflight_return = script.index('status = "PREFLIGHT_READY"')
    branch_guard = script.index(
        "BranchRef must be an exact origin/<topic> remote-tracking ref."
    )

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
        "Assert-WeatherIntegrationRepairTipPolicy",
        "Production master and origin/master must be reconciled",
        "must contain the exact production baseline",
        "Get-WeatherIntegrationFileSha256 -Path $path",
        "Assert-WeatherIntegrationPrearmingQualificationEvidence",
    )
    for fragment in required_before_publication:
        assert script.index(fragment) < preflight_return

    for fragment in (
        "A repair tip must descend",
        "retry_unchanged requires the exact same commit id",
        "Repair attempt does not contain a change",
        "Bounded repair classes permit only added or modified files",
        "does not authorize changed path",
    ):
        assert fragment in contract

    assert '[switch]$PreflightOnly' in script
    assert '[string]$PreflightResultPath = ""' in script
    assert '[string]$CreatorPreflightPlanPath = ""' in script
    assert '[string]$ExpectedCreatorPreflightPlanSha256 = ""' in script
    assert 'status = "PREFLIGHT_READY"' in script
    assert "$script:WeatherIntegrationCreatorPreflightPlanSchema" in script
    assert "Write-WeatherIntegrationImmutableJson" in script
    assert "Assert-WeatherIntegrationCreatorPreflightPlan" in script
    assert "stdout is deliberately not an evidence transport" in script
    assert "prearming_qualification_required = $true" in script
    assert "prearming_qualification_present" in script
    first_mutation = script.index("New-Item -ItemType Directory -Path $AttemptRoot")
    assert branch_guard < preflight_return < first_mutation


def test_exit_bearing_attempt_children_are_process_isolated() -> None:
    script = PREPARER.read_text(encoding="utf-8-sig")
    contract = PREPARATION_CONTRACT.read_text(encoding="utf-8-sig")

    assert "Invoke-WeatherIntegrationPowerShellChild" not in script
    assert "function Invoke-WeatherIntegrationPowerShellChild" not in contract
    assert 'Join-Path $PSHOME "powershell.exe"' in contract
    assert "-NoProfile" in contract
    assert "-NonInteractive" in contract
    assert '"-ExecutionPolicy", "Bypass"' in contract
    assert "ExitCode = [int]$process.ExitCode" in contract
    assert "Get-WeatherIntegrationChildDiagnosticExcerpt" in contract
    assert "MaximumCharacters = 2048" in contract
    assert "ExpectedSha256" in contract
    assert "[IO.FileShare]::Read" in contract
    assert "$scriptSha.ComputeHash($scriptStream)" in contract
    assert "$childRuntimeStopwatch = [Diagnostics.Stopwatch]::StartNew()" in contract
    assert "$childRuntimeStopwatch.Elapsed.TotalSeconds" in contract
    assert "Get-WeatherIntegrationLocalElapsedSeconds" in contract
    assert "param([datetime]$Now = (Get-WeatherIntegrationScheduleLocalNow))" in contract
    assert "$childStartLocal = Get-WeatherIntegrationScheduleLocalNow" in contract
    assert "if ((Get-WeatherIntegrationScheduleLocalNow) -ge $HardStop -or" in contract
    assert "WeatherIntegrationPreparationChildMaximumLifetimeSeconds = 5700" in contract
    assert script.count("Invoke-WeatherIntegrationContainedPowerShellChild") == 8
    assert script.count("-ExpectedSha256") >= 8
    assert "& $registrarPath" not in script
    assert "& $readinessPath" not in script
    assert "& $closerPath" not in script
    assert script.count("Get-WeatherIntegrationChildDiagnosticExcerpt") == 8
    assert "Enter-WeatherIntegrationPreparationMutex" in contract
    assert "New-WeatherKillOnCloseJob" in contract
    assert "Start-WeatherProcessInJobWithRedirectedOutput" in contract
    assert 'Containment = "WINDOWS_JOB_KILL_ON_CLOSE_RETAINED_OUTPUT"' in contract
    assert "ReadStandardOutputBytes" in contract
    assert "ReadStandardErrorBytes" in contract
    assert "New-Object Text.UTF8Encoding($false, $true)" in contract
    assert "StdoutSha256 = $stdoutSha256" in contract
    assert "StderrSha256 = $stderrSha256" in contract
    assert script.count("-OutputDirectory $preparationRoot") == 8
    assert "$job.TerminateAndWaitForEmpty(5000)" in contract
    assert "observing an empty active-process count" in contract
    assert "$script:WeatherIntegrationPreparationMutationTimeoutSeconds = 300" in contract
    assert "function Get-WeatherIntegrationPreparationMutationHardStop" in contract
    preflight_boundary = script.index('$stage = "creator_preflight_before_publication"')
    publication_boundary = script.index('$stage = "publish_exact_topic"')
    preflight_region = script[preflight_boundary:publication_boundary]
    assert preflight_region.count(
        "Invoke-WeatherIntegrationContainedPowerShellChild"
    ) == 1
    assert "-HardStop (Get-WeatherIntegrationPreparationMutationHardStop)" in (
        preflight_region
    )
    assert "-WorkingDirectory $RepoRoot" in preflight_region
    assert '"-PreflightResultPath", $creatorPreflightPlanPath' in preflight_region
    assert "Read-WeatherIntegrationEvidenceSnapshot" in preflight_region
    mutation_boundary = script.index('$stage = "create_immutable_attempt"')
    mutation_region = script[mutation_boundary:]
    assert "Invoke-WeatherIntegrationPowerShellChild" not in mutation_region
    assert mutation_region.count("Invoke-WeatherIntegrationContainedPowerShellChild") == 5
    assert mutation_region.count(
        "-HardStop (Get-WeatherIntegrationPreparationMutationHardStop)"
    ) == 5
    assert mutation_region.count("-WorkingDirectory $RepoRoot") == 5
    assert "[IO.FileShare]::None" in contract
    assert "Assert-WeatherIntegrationNoActiveAttemptCollision" in contract
    assert "[switch]$AllowOwnExactTasks" in contract
    assert "-AllowOwnExactTasks" not in script
    assert "-AllowOwnExactTasks" in READINESS.read_text(encoding="utf-8-sig")
    assert "-AllowOwnExactTasks" in ACTIVATOR.read_text(encoding="utf-8-sig")


def test_final_readiness_requires_every_live_and_immutable_binding() -> None:
    script = READINESS.read_text(encoding="utf-8-sig")

    required_fragments = (
        "Assert-WeatherIntegrationAttemptManifest",
        "Assert-WeatherIntegrationRepairClaim -AttemptContract $contract",
        "successor_expected_tip",
        "successor_manifest_sha256",
        "Read-WeatherIntegrationEvidenceSnapshot -Path $claimPath",
        "Get-WeatherIntegrationCanonicalRemoteTip",
        'RemoteRef "refs/heads/master"',
        "Live origin master changed after the attempt baseline was frozen",
        "Assert-WeatherIntegrationOriginIdentity",
        'rev-parse", [string]$manifest.branch_ref',
        "Assert-WeatherIntegrationGitBaseline",
        '-Arguments @("worktree", "list", "--porcelain")',
        '-Arguments @("status", "--porcelain")',
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
        "Enter-WeatherIntegrationControlMutex",
        "Assert-WeatherIntegrationAttemptNotTerminal",
    )
    for fragment in required_fragments:
        assert fragment in script

    assert "Register-ScheduledTask" not in script
    assert "Start-ScheduledTask" not in script
    assert "git push" not in script.lower()
    receipt_write = script.index(
        "Write-WeatherIntegrationImmutableJson -Path $resolvedResultPath"
    )
    terminal_mutex = script.index("Enter-WeatherIntegrationControlMutex")
    terminal_check = script.index("Assert-WeatherIntegrationAttemptNotTerminal")
    assert terminal_mutex < terminal_check < receipt_write
    final_pass = script.index('$status = "PASS"', receipt_write)
    assert receipt_write < final_pass


def test_ignored_import_namespace_is_rechecked_at_every_prearm_boundary(
    tmp_path: Path,
) -> None:
    contract = ATTEMPT_CONTRACT.read_text(encoding="utf-8-sig")
    creator = CREATOR.read_text(encoding="utf-8-sig")
    readiness = READINESS.read_text(encoding="utf-8-sig")
    activation = ACTIVATOR.read_text(encoding="utf-8-sig")

    assert "function Assert-WeatherIntegrationNoIgnoredImportArtifacts" in contract
    for blocked in (
        '".pyc"',
        '".pyd"',
        '".so"',
        '"conftest.py"',
        '"pytest.ini"',
        '"pyproject.toml"',
        '"sitecustomize.py"',
    ):
        assert blocked in contract
    assert '"--others", "--ignored", "--exclude-standard", "--"' in contract
    for import_root in (
        '"app", "src", "tests", "weather", "tools", "scripts", "__pycache__"',
        '":(glob)$_/**"',
    ):
        assert import_root in contract
    assert '":(glob)*$_"' in contract
    assert "$trackedNamespaceQuery" in contract
    ignored_guard = contract[
        contract.index("function Assert-WeatherIntegrationNoIgnoredImportArtifacts") :
        contract.index("function Read-WeatherIntegrationSharedText")
    ]
    assert '":(glob)data/**"' not in ignored_guard
    assert "$importRoots -icontains $topLevel" in ignored_guard
    assert "$blockedExtensions -icontains $extension" in ignored_guard
    assert "Assert-WeatherIntegrationNoIgnoredImportArtifacts" in creator
    assert "function Assert-WeatherIntegrationCurrentAuthorityTuple" in contract
    authority_helper = contract[
        contract.index("function Assert-WeatherIntegrationCurrentAuthorityTuple") :
        contract.index("function Assert-WeatherIntegrationOriginIdentity")
    ]
    assert "Assert-WeatherIntegrationNoIgnoredImportArtifacts" in authority_helper
    assert "foreach ($pass in 1..2)" in authority_helper
    assert "Assert-WeatherIntegrationLiveOriginBaseline" in authority_helper
    assert 'Arguments @("rev-parse", [string]$manifest.branch_ref)' in authority_helper
    assert 'Arguments @("worktree", "list", "--porcelain")' in authority_helper
    assert "expected_test_inventory_sha256" in authority_helper
    assert "expected_python_inventory_sha256" in authority_helper
    assert "expected_powershell_inventory_sha256" in authority_helper
    assert "authority tuple changed between complete observations" in authority_helper
    assert readiness.count("Assert-WeatherIntegrationCurrentAuthorityTuple") == 2
    assert activation.count("Assert-WeatherIntegrationCurrentAuthorityTuple") == 2
    assert activation.index(
        '-Phase "activation mutation boundary"'
    ) < activation.index("Enable-ScheduledTask")
    assert activation.index(
        '-Phase "final activation receipt boundary"'
    ) > activation.rindex("Enable-ScheduledTask")

    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
function Invoke-WeatherIntegrationCheckedLocalGit {
    param([string]$Root, [string[]]$Arguments, [string]$Label)
    if (@($Arguments | Where-Object { [string]$_ -like '*data*' }).Count -ne 0) {
        throw 'ignored data tree was included in the authority query'
    }
    if ($Label -like '*tracked Python/native*') {
        return [pscustomobject]@{
            StdoutLines = @('src/weather/module.py', 'tools/audit.py')
        }
    }
    [pscustomobject]@{ StdoutLines = @($script:IgnoredRows) }
}
$script:IgnoredRows = @('data/ignored-evidence.pyc')
Assert-WeatherIntegrationNoIgnoredImportArtifacts `
    -WorktreeRoot $env:WEATHER_IGNORED_ROOT -Phase 'data-only test' | Out-Null
foreach ($adversarialPath in @(
    'json.py', 'root_native.pyd', 'tools/ignored-shadow.pyc'
)) {
    $script:IgnoredRows = @($adversarialPath)
    $blocked = $false
    try {
        Assert-WeatherIntegrationNoIgnoredImportArtifacts `
            -WorktreeRoot $env:WEATHER_IGNORED_ROOT `
            -Phase "adversarial $adversarialPath test"
    }
    catch { $blocked = $_.Exception.Message -like '*ignored Python/native*' }
    if (-not $blocked) {
        throw "ignored import shadow passed the shared guard: $adversarialPath"
    }
}
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
        WEATHER_IGNORED_ROOT=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_creator_and_baseline_samplers_use_complete_ref_tuple_sandwiches() -> None:
    creator = CREATOR.read_text(encoding="utf-8-sig")
    contract = ATTEMPT_CONTRACT.read_text(encoding="utf-8-sig")

    creator_state = creator[
        creator.index("function Get-WeatherIntegrationCreatorLocalState") :
        creator.index("function Assert-WeatherIntegrationCreatorLocalStateUnchanged")
    ]
    assert creator_state.count('(@("rev-parse") + $refNames)') == 2
    assert "$closingProductionRefRows" in creator_state
    assert "$closingWorktreeTip" in creator_state
    assert "$closingWorktreeStatus" in creator_state
    baseline = contract[
        contract.index("function Assert-WeatherIntegrationGitBaseline") :
        contract.index("function Assert-WeatherIntegrationLiveOriginBaseline")
    ]
    assert baseline.count('"refs/remotes/origin/master"') == 2
    assert "$closingRefsQuery" in baseline
    assert "production branch/ref tuple changed" in baseline


def test_registrar_rechecks_lead_at_the_external_mutation_boundary() -> None:
    script = REGISTRAR.read_text(encoding="utf-8-sig")

    boundary = script.index("$schedulerBoundaryCheckedAt = Get-Date")
    first_registration = script.index("Register-ScheduledTask")
    assert boundary < first_registration
    assert "[int]$MinimumSuiteLeadMinutes = 1" in script
    assert "$schedulerBoundaryLeadSeconds" in script
    assert "Get-WeatherIntegrationLocalElapsedSeconds" in script
    assert "$MinimumSuiteLeadMinutes * 60" in script
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
        schema = $script:WeatherIntegrationAttemptLegacyManifestSchema
        attempt_id = 'attempt-a1'
        expected_tip = ('1' * 40)
        schedule = [pscustomobject]@{
            suite_task_name = 'WeatherIntegrationSuite_attempt-a1'
            merge_task_name = 'WeatherIntegrationMerge_attempt-a1'
        }
        authorization = [pscustomobject]@{
            repair_class = 'manual_reviewed_change'
            repair_of = [pscustomobject]@{
                receipt_path = Join-Path $env:WEATHER_MISSING_PRIOR `
                    'closure-receipt.json'
                receipt_sha256 = ('4' * 64)
                receipt_schema = $script:WeatherIntegrationAttemptClosureReceiptSchema
                prior_attempt_id = 'prior-a1'
                claim_path = Join-Path $env:WEATHER_MISSING_PRIOR `
                    'successor-claim.json'
                dispatch_path = Join-Path $env:WEATHER_MISSING_PRIOR `
                    'recovery-dispatch.json'
                dispatch_sha256 = ('5' * 64)
            }
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
$contract.Manifest.schema = $script:WeatherIntegrationAttemptManifestSchema
$v2OmissionAccepted = $false
try {
    Assert-WeatherIntegrationRegistrationPreparationState `
        -AttemptContract $contract | Out-Null
    $v2OmissionAccepted = $true
}
catch { }
if ($v2OmissionAccepted) {
    throw 'qualified v2 manifest accepted omitted qualification evidence'
}
$contract.Manifest.schema = $script:WeatherIntegrationAttemptLegacyManifestSchema
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


def test_v2_cleanup_structure_survives_missing_qualification_evidence(
    tmp_path: Path,
) -> None:
    attempt_root = tmp_path / "attempt-v2"
    manifest_path = attempt_root / "manifest.json"
    intent_path = Path(str(attempt_root) + ".preparation") / "preparation-intent.json"
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$plan = Get-WeatherIntegrationPreparationAuthorizationPlan `
    -AttemptRoot $env:WEATHER_ATTEMPT_ROOT `
    -AttemptId 'attempt-v2' `
    -ManifestPath $env:WEATHER_MANIFEST_PATH `
    -ExpectedTip ('1' * 40) `
    -PreparationIntentPath $env:WEATHER_INTENT_PATH `
    -PreparationIntentSha256 ('2' * 64) `
    -SuiteTaskName 'WeatherIntegrationSuite_attempt-v2' `
    -MergeTaskName 'WeatherIntegrationMerge_attempt-v2'
$contract = [pscustomobject]@{
    AttemptRoot = $env:WEATHER_ATTEMPT_ROOT
    ManifestPath = $env:WEATHER_MANIFEST_PATH
    Manifest = [pscustomobject]@{
        schema = $script:WeatherIntegrationAttemptManifestSchema
        attempt_id = 'attempt-v2'
        expected_tip = ('1' * 40)
        schedule = [pscustomobject]@{
            suite_task_name = 'WeatherIntegrationSuite_attempt-v2'
            merge_task_name = 'WeatherIntegrationMerge_attempt-v2'
        }
        authorization = [pscustomobject]@{
            preparation = [pscustomobject]@{
                required = $true
                execution_authorization_path = $plan.Path
                execution_authorization_sha256 = $plan.Sha256
                preparation_intent_path = $env:WEATHER_INTENT_PATH
                preparation_intent_sha256 = ('2' * 64)
                prearming_qualification_path = Join-Path `
                    ($env:WEATHER_ATTEMPT_ROOT + '.preparation') `
                    'prearming-qualification-receipt.json'
                prearming_qualification_sha256 = ('3' * 64)
                creator_preflight_plan_path = Join-Path `
                    ($env:WEATHER_ATTEMPT_ROOT + '.preparation') `
                    'creator-preflight-plan.json'
                creator_preflight_plan_sha256 = ('4' * 64)
            }
        }
    }
}
$structure = Assert-WeatherIntegrationPreparationAuthorizationStructure `
    -AttemptContract $contract
if (-not [bool]$structure.Required) {
    throw 'cleanup-safe v2 structure was not accepted'
}
$repairStructure = Assert-WeatherIntegrationRepairClaimStructure `
    -AttemptContract $contract
if (-not [bool]$repairStructure.Required) {
    throw 'cleanup-safe repair structure was not accepted'
}
$strictAccepted = $false
try {
    Assert-WeatherIntegrationPreparationExecutionAuthorization `
        -AttemptContract $contract -AllowMissing | Out-Null
    $strictAccepted = $true
}
catch { }
if ($strictAccepted) {
    throw 'strict runtime reader accepted missing qualification evidence'
}
$strictRepairAccepted = $false
try {
    Assert-WeatherIntegrationRepairClaim -AttemptContract $contract | Out-Null
    $strictRepairAccepted = $true
}
catch { }
if ($strictRepairAccepted) {
    throw 'strict runtime reader accepted missing predecessor repair evidence'
}
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
        WEATHER_ATTEMPT_ROOT=str(attempt_root),
        WEATHER_MANIFEST_PATH=str(manifest_path),
        WEATHER_INTENT_PATH=str(intent_path),
        WEATHER_MISSING_PRIOR=str(tmp_path / "missing-prior"),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"
    contract = ATTEMPT_CONTRACT.read_text(encoding="utf-8-sig")
    closer = CLOSER.read_text(encoding="utf-8-sig")
    assert "Assert-WeatherIntegrationPreparationAuthorizationStructure" in contract
    assert "Assert-WeatherIntegrationPreparationExecutionAuthorization" not in contract[
        contract.index("function Assert-WeatherIntegrationAttemptManifest") :
        contract.index("function Disable-WeatherIntegrationAttemptTasks")
    ]
    assert "Assert-WeatherIntegrationRepairClaim `" not in contract[
        contract.index("function Assert-WeatherIntegrationAttemptManifest") :
        contract.index("function Disable-WeatherIntegrationAttemptTasks")
    ]
    assert closer.index("Assert-WeatherIntegrationAttemptManifest") < closer.index(
        "Disable-WeatherIntegrationAttemptTasks"
    )


def test_registrar_revalidates_qualification_inside_terminal_mutex() -> None:
    script = REGISTRAR.read_text(encoding="utf-8-sig")

    mutex = script.index("Enter-WeatherIntegrationControlMutex")
    inner_authorization = script.index(
        "Assert-WeatherIntegrationRegistrationPreparationState", mutex
    )
    git_controls = script.index("Assert-WeatherIntegrationGitControlSafety", mutex)
    intent_write = script.index("Write-WeatherIntegrationImmutableJson", mutex)
    scheduler_write = script.index("Register-ScheduledTask", mutex)
    assert script.count("Assert-WeatherIntegrationRegistrationPreparationState") == 2
    assert mutex < inner_authorization < git_controls < intent_write < scheduler_write


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
    worktree_inventory = activator.index(
        '-Arguments @("worktree", "list", "--porcelain")', revalidation
    )
    worktree_clean = activator.index(
        '-Arguments @("status", "--porcelain")', worktree_inventory
    )
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


def test_prearming_qualification_binds_both_exact_logs_and_worktree_import(
    tmp_path: Path,
) -> None:
    attempt_root = tmp_path / "attempt-qualified"
    preparation_root = Path(str(attempt_root) + ".preparation")
    preparation_root.mkdir()
    intent_path = preparation_root / "preparation-intent.json"
    receipt_path = preparation_root / "prearming-qualification-receipt.json"
    preflight_log = preparation_root / "prearming-integration-preflight.log"
    full_log = preparation_root / "prearming-full-suite.log"
    bounded_suite = OPS / "bounded_worktree_test_suite.ps1"
    weather_import = ROOT / "weather" / "__init__.py"

    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    bounded_sha = sha256(bounded_suite)
    import_sha = sha256(weather_import)
    preflight_verdict = (
        "VERDICT: INTEGRATION PREFLIGHT PASSED; full suite not run and merge "
        "is not authorized"
    )
    full_verdict = (
        "VERDICT: ALL CHUNKS PASSED (2/2); exact tip eligible for separate "
        "reviewed merge"
    )
    def write_run_evidence(
        log_path: Path, *, planned_files: int, chunks: int, verdict: str
    ) -> dict[str, object]:
        python_list = Path(str(log_path) + ".python-syntax-inventory.txt")
        powershell_list = Path(str(log_path) + ".powershell-syntax-inventory.txt")
        test_list = Path(str(log_path) + ".test-inventory.txt")
        python_list.write_text("alpha.py\nbeta.py\n", encoding="utf-8")
        powershell_list.write_text("alpha.ps1\n", encoding="utf-8")
        test_list.write_text(
            "".join(f"tests/test_fixture_{index}.py\n" for index in range(planned_files)),
            encoding="utf-8",
        )
        runtime_root = ROOT / "venv"
        executable = runtime_root / "Scripts" / "python.exe"
        launcher = runtime_root / "Scripts" / "pythonw.exe"
        python_dll = runtime_root / "python311.dll"
        pth_root = runtime_root / "Lib" / "site-packages"
        record_path = (
            runtime_root / "Lib" / "site-packages" / "fixture-1.dist-info" / "RECORD"
        )
        runtime_rows = sorted(
            [
                {"kind": "executable", "path": str(executable), "length": 2, "sha256": "d" * 64},
                {"kind": "launcher", "path": str(launcher), "length": 2, "sha256": "1" * 64},
                {"kind": "runtime_dll", "path": str(python_dll), "length": 3, "sha256": "e" * 64},
            ],
            key=lambda row: str(row["path"]).casefold(),
        )
        controls = {
            "allowed_write_root": "",
            "candidate_root": str(ROOT),
            "git_allow_protocol": "file",
            "git_terminal_prompt": "0",
            "git_config_nosystem": "1",
            "git_config_system": "NUL",
            "git_config_global": "NUL",
            "git_config_count": "0",
            "git_attr_nosystem": "1",
            "git_protocol_from_user": "0",
            "git_optional_locks": "0",
            "git_topology_environment_clear": True,
            "git_topology_environment_count": 0,
            "offline": "1",
            "production_root": str(ROOT),
            "evidence_root": str(ROOT),
            "pythonhashseed": "0",
            "pythonioencoding": "utf-8",
            "pythonutf8": "1",
            "secret_environment_clear": True,
            "secret_environment_count": 0,
            "secret_policy": "conservative_v1",
            "temp_policy": "system_temp_unique_v1",
            "python_executable": str(executable),
            "git_executable": str(ROOT / "git.exe"),
            "powershell_executable": str(ROOT / "powershell.exe"),
            "setuptools_use_distutils": "stdlib",
            "read_only_production_probe": False,
        }
        python_payload = {
            "schema_version": "python_environment_fingerprint_v2",
            "executable": str(executable),
            "executable_sha256": "d" * 64,
            "python_version": "3.11.0",
            "implementation": "cpython",
            "cache_tag": "cpython-311",
            "platform": "win32",
            "prefix": str(runtime_root),
            "base_prefix": str(runtime_root),
            "sys_path": [str(ROOT), str(ROOT / "src")],
            "controls": controls,
            "distributions": [
                {
                    "name": "fixture",
                    "version": "1",
                    "location": str(runtime_root / "Lib" / "site-packages"),
                    "record_path": str(record_path),
                    "record_sha256": "f" * 64,
                    "installer_sha256": None,
                    "files": [
                        {
                            "path": str(record_path),
                            "length": 1,
                            "sha256": "f" * 64,
                            "record_algorithm": None,
                            "record_digest": None,
                            "record_size": None,
                        }
                    ],
                }
            ],
            "runtime_files": runtime_rows,
            "pth_files": [
                {
                    "path": str(pth_root / "__editable__.weather_market-0.1.0.pth"),
                    "length": 1,
                    "sha256": "4" * 64,
                },
                {
                    "path": str(pth_root / "distutils-precedence.pth"),
                    "length": 1,
                    "sha256": "5" * 64,
                },
            ],
            "file_count": 4,
            "total_bytes": 8,
        }
        toolchain_payload = {
            "schema_version": "integration_toolchain_fingerprint_v1",
            "git": {"executable": str(ROOT / "git.exe"), "executable_sha256": "a" * 64, "version": "git version fixture"},
            "git_lfs": {"executable": str(ROOT / "git-lfs.exe"), "executable_sha256": "c" * 64, "version": "git-lfs fixture"},
            "powershell": {"executable": str(ROOT / "powershell.exe"), "executable_sha256": "b" * 64, "version": "5.1", "edition": "Desktop", "clr_version": "4", "architecture": "x64"},
            "controls": controls,
        }
        tracked_entry = {
            "path": "fixture.txt",
            "mode": "100644",
            "blob_oid": "2" * 40,
            "worktree_length": 1,
            "worktree_sha256": "3" * 64,
            "lfs_oid": None,
            "lfs_size": None,
        }
        tracked_digest = hashlib.sha256(
            (f"fixture.txt\t100644\t{'2' * 40}\t1\t{'3' * 64}\t-\t-\n").encode()
        ).hexdigest()
        tracked_payload = {
            "schema_version": "tracked_worktree_content_fingerprint_v1",
            "content_sha256": tracked_digest,
            "head": "1" * 40,
            "root": str(ROOT),
            "file_count": 1,
            "total_bytes": 1,
            "lfs_file_count": 0,
            "entries": [tracked_entry],
        }
        python_text = json.dumps(python_payload, separators=(",", ":"))
        toolchain_text = json.dumps(toolchain_payload, separators=(",", ":"))
        python_paths = {
            phase: Path(str(log_path) + f".python-environment.{phase}.json")
            for phase in ("pre", "post")
        }
        toolchain_paths = {
            phase: Path(str(log_path) + f".integration-toolchain.{phase}.json")
            for phase in ("pre", "post")
        }
        tracked_paths = {
            phase: Path(str(log_path) + f".tracked-worktree.{phase}.json")
            for phase in ("pre", "post")
        }
        for path in python_paths.values():
            path.write_text(python_text, encoding="utf-8")
        for path in toolchain_paths.values():
            path.write_text(toolchain_text, encoding="utf-8")
        for path in tracked_paths.values():
            path.write_text(json.dumps(tracked_payload, separators=(",", ":")), encoding="utf-8")
        python_sha = sha256(python_paths["pre"])
        toolchain_sha = sha256(toolchain_paths["pre"])
        junit_rows: list[dict[str, object]] = []
        lines = [
            "2026-08-25 00:31:00  tracked_worktree phase=pre "
            "schema=tracked_worktree_content_fingerprint_v1 "
            f"sha256={tracked_digest} files=1 bytes=1 lfs_files=0 path={tracked_paths['pre']}",
            "2026-08-25 00:31:00  integration_toolchain phase=pre "
            "schema=integration_toolchain_fingerprint_v1 "
            f"sha256={toolchain_sha} git_sha256={'a' * 64} "
            f"git_lfs_sha256={'c' * 64} "
            f"powershell_sha256={'b' * 64} path={toolchain_paths['pre']}",
            "2026-08-25 00:31:00  python_environment phase=pre "
            "schema=python_environment_fingerprint_v2 "
            f"sha256={python_sha} distributions=1 files=4 bytes=8 path={python_paths['pre']}",
            f"2026-08-25 00:31:01  weather_import={weather_import} "
            f"weather_import_sha256={import_sha}",
            "2026-08-25 00:31:02  syntax "
            f"python_files=2 python_inventory_sha256={sha256(python_list)} "
            f"python_list={python_list} powershell_files=1 "
            f"powershell_inventory_sha256={sha256(powershell_list)} "
            f"powershell_list={powershell_list} python_exit=0 powershell_errors=0",
            f"2026-08-25 00:31:03  planned chunks={chunks} "
            f"files={planned_files} max_files=20",
        ]
        for ordinal in range(1, chunks + 1):
            junit = Path(str(log_path) + f".chunk-{ordinal:03d}.xml")
            junit.write_text(
                '<testsuites><testsuite tests="2" failures="0" errors="0" '
                'skipped="0" /></testsuites>\n',
                encoding="utf-8",
            )
            junit_row = {
                "ordinal": ordinal,
                "path": str(junit),
                "sha256": sha256(junit),
                "tests": 2,
                "failures": 0,
                "errors": 0,
                "skipped": 0,
                "deselected": 0,
            }
            junit_rows.append(junit_row)
            lines.append(
                f"2026-08-25 00:31:04  chunk {ordinal}/{chunks} junit_summary "
                f"path={junit} sha256={junit_row['sha256']} tests=2 failures=0 "
                "errors=0 skipped=0 deselected=0"
            )
        lines.extend(
            [
                f"2026-08-25 00:31:05  aggregate tests={2 * chunks} failures=0 "
                f"errors=0 skipped=0 deselected=0 planned_files={planned_files} "
                f"inventory_sha256={sha256(test_list)} inventory_path={test_list}",
                "2026-08-25 00:32:01  integration_toolchain phase=post "
                "schema=integration_toolchain_fingerprint_v1 "
                f"sha256={toolchain_sha} git_sha256={'a' * 64} "
                f"git_lfs_sha256={'c' * 64} "
                f"powershell_sha256={'b' * 64} path={toolchain_paths['post']}",
                "2026-08-25 00:32:01  python_environment phase=post "
                "schema=python_environment_fingerprint_v2 "
                f"sha256={python_sha} distributions=1 files=4 bytes=8 path={python_paths['post']}",
                "2026-08-25 00:32:01  python_environment stable=true "
                f"pre_sha256={python_sha} post_sha256={python_sha} distributions=1 files=4 bytes=8",
                "2026-08-25 00:32:01  integration_toolchain stable=true "
                f"pre_sha256={toolchain_sha} post_sha256={toolchain_sha}",
                "2026-08-25 00:32:01  tracked_worktree phase=post "
                "schema=tracked_worktree_content_fingerprint_v1 "
                f"sha256={tracked_digest} files=1 bytes=1 lfs_files=0 path={tracked_paths['post']}",
                "2026-08-25 00:32:01  tracked_worktree stable=true "
                f"pre_sha256={tracked_digest} post_sha256={tracked_digest} files=1 bytes=1 lfs_files=0",
                f"2026-08-25 00:32:02  {verdict}",
            ]
        )
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = {
            "planned_files": planned_files,
            "inventory_path": str(test_list),
            "inventory_sha256": sha256(test_list),
            "tests": 2 * chunks,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "deselected": 0,
            "python_files": 2,
            "python_inventory_path": str(python_list),
            "python_inventory_sha256": sha256(python_list),
            "powershell_files": 1,
            "powershell_inventory_path": str(powershell_list),
            "powershell_inventory_sha256": sha256(powershell_list),
            "junit": junit_rows,
        }
        result.update(
            {
                "python_environment_schema": "python_environment_fingerprint_v2",
                "python_environment_sha256": python_sha,
                "python_environment_distributions": 1,
                "python_environment_files": 4,
                "python_environment_bytes": 8,
                "python_executable_sha256": "d" * 64,
                "python_environment_pre_path": str(python_paths["pre"]),
                "python_environment_post_path": str(python_paths["post"]),
                "python_environment_candidate_root": str(ROOT),
                "python_environment_production_root": str(ROOT),
                "toolchain_schema": "integration_toolchain_fingerprint_v1",
                "toolchain_sha256": toolchain_sha,
                "toolchain_git_sha256": "a" * 64,
                "toolchain_git_lfs_sha256": "c" * 64,
                "toolchain_powershell_sha256": "b" * 64,
                "toolchain_pre_path": str(toolchain_paths["pre"]),
                "toolchain_post_path": str(toolchain_paths["post"]),
                "tracked_worktree_schema": "tracked_worktree_content_fingerprint_v1",
                "tracked_worktree_sha256": tracked_digest,
                "tracked_worktree_file_count": 1,
                "tracked_worktree_total_bytes": 1,
                "tracked_worktree_lfs_file_count": 0,
                "tracked_worktree_root": str(ROOT),
                "tracked_worktree_head": "1" * 40,
                "tracked_worktree_pre_path": str(tracked_paths["pre"]),
                "tracked_worktree_post_path": str(tracked_paths["post"]),
            }
        )
        return result

    # Deliberately use a historical/non-current count: acceptance must derive
    # this mode's plan from its retained log, never a copied source literal.
    preflight_results = write_run_evidence(
        preflight_log, planned_files=19, chunks=1, verdict=preflight_verdict
    )
    full_results = write_run_evidence(
        full_log, planned_files=40, chunks=2, verdict=full_verdict
    )
    intent = {
        "schema": "weather_integration_attempt_preparation_intent_v1",
        "status": "PREPARED",
        "schedule": {
            "suite_at_local": "2026-08-26T00:30:00",
            "merge_at_local": "2026-08-26T03:10:00",
        },
        "publication": {
            "confirmation": "AUTHORIZE_EXACT_NON_FORCE_TOPIC_PUBLICATION"
        },
        "authorization": {
            "scheduler_confirmation": (
                "AUTHORIZE_DISABLED_INTEGRATION_TASK_REGISTRATION"
            ),
            "activation_confirmation": (
                "AUTHORIZE_EXACT_INTEGRATION_TASK_ACTIVATION"
            ),
        },
        "qualification": {
            "required": True,
            "receipt_path": str(receipt_path),
            "integration_preflight_log_path": str(preflight_log),
            "full_suite_log_path": str(full_log),
            "bounded_suite_path": str(bounded_suite),
            "bounded_suite_sha256": bounded_sha,
            "require_live_sdk_contract": False,
            "rerun_at_suite_trigger": True,
            "planning_ceiling_seconds": 5400,
            "safety_margin_seconds": 600,
            "launch_grace_seconds": 300,
        },
    }
    intent_path.write_text(json.dumps(intent) + "\n", encoding="utf-8")
    receipt = {
        "schema": "weather_integration_attempt_prearming_qualification_receipt_v1",
        "status": "PASS",
        "attempt_id": "attempt-qualified",
        "repo_root": str(ROOT),
        "worktree_root": str(ROOT),
        "branch_ref": "origin/codex/qualified",
        "expected_tip": "1" * 40,
        "started_at_local": "2026-08-25T00:31:00-04:00",
        "completed_at_local": "2026-08-25T00:32:03-04:00",
        "duration_seconds": 63.0,
        "bounded_suite": {"path": str(bounded_suite), "sha256": bounded_sha},
        "require_live_sdk_contract": False,
        "expected_test_file_count": 40,
        "max_files_per_chunk": 20,
        "expected_chunk_count": 2,
        "expected_test_inventory_sha256": full_results["inventory_sha256"],
        "expected_python_file_count": 2,
        "expected_python_inventory_sha256": full_results[
            "python_inventory_sha256"
        ],
        "expected_powershell_file_count": 1,
        "expected_powershell_inventory_sha256": full_results[
            "powershell_inventory_sha256"
        ],
        "expected_tracked_worktree_schema": "tracked_worktree_content_fingerprint_v1",
        "expected_tracked_worktree_sha256": full_results["tracked_worktree_sha256"],
        "expected_tracked_worktree_file_count": 1,
        "expected_tracked_worktree_total_bytes": 1,
        "expected_tracked_worktree_lfs_file_count": 0,
        "expected_python_environment_schema": (
            "python_environment_fingerprint_v2"
        ),
        "expected_python_environment_sha256": full_results[
            "python_environment_sha256"
        ],
        "expected_python_environment_distributions": 1,
        "expected_python_environment_files": 3,
        "expected_python_environment_bytes": 6,
        "expected_toolchain_schema": "integration_toolchain_fingerprint_v1",
        "expected_toolchain_sha256": full_results["toolchain_sha256"],
        "runs": {
            "integration_preflight": {
                "mode": "integration_preflight",
                "log_path": str(preflight_log),
                "log_sha256": sha256(preflight_log),
                "exit_code": 0,
                "verdict": preflight_verdict,
                "weather_import_path": str(weather_import),
                "weather_import_sha256": import_sha,
                "test_results": preflight_results,
                "evidence_validation_error": None,
                "started_at_local": "2026-08-25T00:31:00-04:00",
                "completed_at_local": "2026-08-25T00:31:03-04:00",
                "duration_seconds": 3.0,
            },
            "full_suite": {
                "mode": "full_suite",
                "log_path": str(full_log),
                "log_sha256": sha256(full_log),
                "exit_code": 0,
                "verdict": full_verdict,
                "weather_import_path": str(weather_import),
                "weather_import_sha256": import_sha,
                "test_results": full_results,
                "evidence_validation_error": None,
                "started_at_local": "2026-08-25T00:31:04-04:00",
                "completed_at_local": "2026-08-25T00:32:02-04:00",
                "duration_seconds": 58.0,
            },
        },
        "feasibility": {
            "measured_duration_seconds": 63.0,
            "planning_ceiling_seconds": 5400,
            "safety_margin_seconds": 600,
            "required_runtime_seconds": 6000,
            "launch_grace_seconds": 300,
            "required_schedule_seconds": 6300,
            "bounded_suite_max_runtime_seconds": 5400,
            "suite_wrapper_teardown_allowance_seconds": 300,
            "suite_task_execution_time_limit_seconds": 5700,
            "suite_to_merge_seconds": 9600,
            "suite_to_hard_stop_seconds": 30600,
            "eligible": True,
        },
        "safety": {
            "authority": "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY",
            "credential_value_access_authorized": False,
            "live_exchange_mutation_authorized": False,
        },
    }
    receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$intent = Get-Content -LiteralPath $env:WEATHER_INTENT_PATH -Raw | ConvertFrom-Json
$schedule = Get-WeatherIntegrationScheduleEvidence `
    -SuiteAtLocal ([datetime]'2026-08-26T00:30:00') `
    -MergeAtLocal ([datetime]'2026-08-26T03:10:00')
$intent.schedule = $schedule
[IO.File]::WriteAllText(
    $env:WEATHER_INTENT_PATH,
    ($intent | ConvertTo-Json -Depth 30) + [Environment]::NewLine,
    (New-Object Text.UTF8Encoding($false))
)
$args = @{
    PreparationIntentPath = $env:WEATHER_INTENT_PATH
    ExpectedPreparationIntentSha256 = Get-WeatherIntegrationFileSha256 -Path $env:WEATHER_INTENT_PATH
    AttemptRoot = $env:WEATHER_ATTEMPT_ROOT
    AttemptId = 'attempt-qualified'
    RepoRoot = $env:WEATHER_REPO_ROOT
    WorktreeRoot = $env:WEATHER_REPO_ROOT
    BranchRef = 'origin/codex/qualified'
    ExpectedTip = ('1' * 40)
    BoundedSuitePath = $env:WEATHER_BOUNDED_SUITE
    ExpectedBoundedSuiteSha256 = Get-WeatherIntegrationFileSha256 -Path $env:WEATHER_BOUNDED_SUITE
    ExpectedTestFileCount = 40
    ExpectedChunkCount = 2
    ExpectedTestInventorySha256 = $env:WEATHER_TEST_INVENTORY_SHA256
    ExpectedPythonFileCount = 2
    ExpectedPythonInventorySha256 = $env:WEATHER_PYTHON_INVENTORY_SHA256
    ExpectedPowerShellFileCount = 1
    ExpectedPowerShellInventorySha256 = $env:WEATHER_POWERSHELL_INVENTORY_SHA256
    ExpectedTrackedWorktreeSchema = 'tracked_worktree_content_fingerprint_v1'
    ExpectedTrackedWorktreeSha256 = $env:WEATHER_TRACKED_WORKTREE_SHA256
    ExpectedTrackedWorktreeFileCount = 1
    ExpectedTrackedWorktreeTotalBytes = 1
    ExpectedTrackedWorktreeLfsFileCount = 0
    RequireLiveSdkContract = $false
}
$proof = Assert-WeatherIntegrationPrearmingQualificationEvidence @args
if (-not [bool]$proof.Present -or $proof.Sha256 -notmatch '^[0-9a-f]{64}$') {
    throw 'exact qualification evidence was not accepted'
}
$correctInventorySha = [string]$args.ExpectedTestInventorySha256
$args.ExpectedTestInventorySha256 = ('f' * 64)
$sameCountWrongInventoryAccepted = $false
try {
    Assert-WeatherIntegrationPrearmingQualificationEvidence @args | Out-Null
    $sameCountWrongInventoryAccepted = $true
}
catch { }
if ($sameCountWrongInventoryAccepted) {
    throw 'same-count substituted creator test inventory was accepted'
}
$args.ExpectedTestInventorySha256 = $correctInventorySha
$receiptText = [IO.File]::ReadAllText($proof.Path)
$receiptPayload = $receiptText | ConvertFrom-Json
$receiptPayload.expected_toolchain_sha256 = ('c' * 64)
$encoding = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText(
    $proof.Path,
    ($receiptPayload | ConvertTo-Json -Depth 30) + [Environment]::NewLine,
    $encoding
)
$toolchainForgeryAccepted = $false
try {
    Assert-WeatherIntegrationPrearmingQualificationEvidence @args | Out-Null
    $toolchainForgeryAccepted = $true
}
catch { }
if ($toolchainForgeryAccepted) {
    throw 'receipt-authored toolchain fingerprint was accepted over log evidence'
}
[IO.File]::WriteAllText($proof.Path, $receiptText, $encoding)
$receiptPayload = $receiptText | ConvertFrom-Json
$receiptPayload.feasibility.launch_grace_seconds = 301
[IO.File]::WriteAllText(
    $proof.Path,
    ($receiptPayload | ConvertTo-Json -Depth 30) + [Environment]::NewLine,
    $encoding
)
$graceTamperAccepted = $false
try {
    Assert-WeatherIntegrationPrearmingQualificationEvidence @args | Out-Null
    $graceTamperAccepted = $true
}
catch { }
if ($graceTamperAccepted) { throw 'tampered Scheduler launch grace was accepted' }
[IO.File]::WriteAllText($proof.Path, $receiptText, $encoding)
Add-Content -LiteralPath $env:WEATHER_FULL_LOG -Value 'tamper'
$tamperAccepted = $false
try {
    Assert-WeatherIntegrationPrearmingQualificationEvidence @args | Out-Null
    $tamperAccepted = $true
}
catch { }
if ($tamperAccepted) { throw 'tampered qualification log was accepted' }
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
        WEATHER_INTENT_PATH=str(intent_path),
        WEATHER_ATTEMPT_ROOT=str(attempt_root),
        WEATHER_REPO_ROOT=str(ROOT),
        WEATHER_BOUNDED_SUITE=str(bounded_suite),
        WEATHER_FULL_LOG=str(full_log),
        WEATHER_TEST_INVENTORY_SHA256=str(full_results["inventory_sha256"]),
        WEATHER_PYTHON_INVENTORY_SHA256=str(
            full_results["python_inventory_sha256"]
        ),
        WEATHER_POWERSHELL_INVENTORY_SHA256=str(
            full_results["powershell_inventory_sha256"]
        ),
        WEATHER_TRACKED_WORKTREE_SHA256=str(
            full_results["tracked_worktree_sha256"]
        ),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_scheduled_suite_repeats_preflight_and_full_suite_after_qualification() -> None:
    script = SUITE.read_text(encoding="utf-8-sig")

    preflight = script.index('-Phase "integration preflight"', script.index("try {"))
    full_suite = script.index('-Phase "full suite"', preflight)
    assert preflight < full_suite
    assert '-IntegrationPreflight' in script[preflight:full_suite]
    assert "full suite was not started" in script
    assert "Assert-WeatherIntegrationScheduledSuiteLaunchReserve" in script
    assert "prearming_launch_grace_seconds" in script
    assert "prearming_required_schedule_seconds" in script
    suite_phase = script[
        script.index("function Invoke-WeatherAttemptSuitePhase") :
        script.index("function Assert-WeatherAttemptSuiteWorktreeState")
    ]
    assert "Invoke-WeatherIntegrationContainedPowerShellChild" in suite_phase
    assert "-ExpectedSha256" in suite_phase
    assert "-OutputDirectory ([string]$manifest.attempt_root)" in suite_phase
    assert '"-MaxRuntimeSeconds", [string]$phaseRuntimeSeconds' in suite_phase
    assert "-HardStop $suiteSharedHardStopLocal" in suite_phase
    assert "$suiteRuntimeStopwatch.Elapsed.TotalSeconds" in suite_phase
    assert "Start-WeatherProcessInJob" not in suite_phase

    assert "bounded_suite_max_runtime_seconds" in script
    assert "suite_wrapper_teardown_allowance_seconds" in script
    assert "suite_task_execution_time_limit_seconds" in script
    assert "suiteSharedDeadlineUtc" in script


def test_attempt_merge_hard_stop_proves_quiet_merge_child_termination() -> None:
    script = MERGE.read_text(encoding="utf-8-sig")
    quiet_child = script[
        script.index("function Invoke-WeatherQuietMergeChild") :
        script.index("function Get-WeatherIntegrationRecoverableActiveMarker")
    ]

    assert "$job.TerminateAndWaitForEmpty(5000)" in quiet_child
    assert "$job = $null" in quiet_child
    assert "observing an empty" in quiet_child
    assert "active-process count proved its child tree" in quiet_child


def test_candidate_inventory_accepts_both_pytest_names_and_rejects_deletion() -> None:
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
. $env:WEATHER_PREPARATION_CONTRACT
$baseline = @(
    'tests/operations/test_keep.py',
    'tests/operations/legacy_contract_test.py',
    'tests/operations/not_a_test.txt'
)
$accepted = @(Assert-WeatherIntegrationCandidateTestInventory `
    -BaselinePaths $baseline `
    -CandidatePaths @(
        'tests/operations/test_keep.py',
        'tests/operations/legacy_contract_test.py',
        'tests/operations/test_added.py'
    ))
$deletionAccepted = $false
try {
    Assert-WeatherIntegrationCandidateTestInventory `
        -BaselinePaths $baseline `
        -CandidatePaths @('tests/operations/test_keep.py') | Out-Null
    $deletionAccepted = $true
}
catch { }
if ($accepted.Count -ne 3 -or
    $accepted -cnotcontains 'tests/operations/test_keep.py' -or
    $accepted -cnotcontains 'tests/operations/legacy_contract_test.py' -or
    $deletionAccepted) {
    throw 'candidate pytest inventory guard failed'
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


def test_suite_evidence_rejects_all_skipped_and_forged_junit_counts(
    tmp_path: Path,
) -> None:
    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    python_list = tmp_path / "python.txt"
    powershell_list = tmp_path / "powershell.txt"
    test_list = tmp_path / "tests.txt"
    for path, text in (
        (python_list, "module.py\n"),
        (powershell_list, "script.ps1\n"),
        (test_list, "tests/test_one.py\n"),
    ):
        path.write_text(text, encoding="utf-8")

    def write_log(name: str, *, xml_tests: int, xml_skipped: int) -> Path:
        log = tmp_path / f"{name}.log"
        junit = tmp_path / f"{name}.xml"
        junit.write_text(
            f'<testsuites><testsuite tests="{xml_tests}" failures="0" '
            f'errors="0" skipped="{xml_skipped}" /></testsuites>\n',
            encoding="utf-8",
        )
        # The forged case deliberately claims one executed test even though
        # its hash-bound XML reports two. The skipped case exactly reports an
        # all-skipped XML. Neither may become PASS evidence.
        logged_skipped = xml_skipped if name == "skipped" else 0
        log.write_text(
            "2026-08-25 00:31:00  syntax "
            f"python_files=1 python_inventory_sha256={sha256(python_list)} "
            f"python_list={python_list} powershell_files=1 "
            f"powershell_inventory_sha256={sha256(powershell_list)} "
            f"powershell_list={powershell_list} python_exit=0 powershell_errors=0\n"
            "2026-08-25 00:31:01  chunk 1/1 junit_summary "
            f"path={junit} sha256={sha256(junit)} tests=1 failures=0 "
            f"errors=0 skipped={logged_skipped} deselected=0\n"
            f"2026-08-25 00:31:02  aggregate tests=1 failures=0 errors=0 "
            f"skipped={logged_skipped} deselected=0 planned_files=1 "
            f"inventory_sha256={sha256(test_list)} inventory_path={test_list}\n",
            encoding="utf-8",
        )
        return log

    skipped_log = write_log("skipped", xml_tests=1, xml_skipped=1)
    forged_log = write_log("forged", xml_tests=2, xml_skipped=0)
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
foreach ($path in @($env:WEATHER_SKIPPED_LOG, $env:WEATHER_FORGED_LOG)) {
    $accepted = $false
    try {
        Get-WeatherIntegrationSuiteEvidenceSummary `
            -Path $path -ExpectedChunkCount 1 -ExpectedPlannedFiles 1 | Out-Null
        $accepted = $true
    }
    catch { }
    if ($accepted) { throw "false-PASS suite evidence was accepted: $path" }
}
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
        WEATHER_SKIPPED_LOG=str(skipped_log),
        WEATHER_FORGED_LOG=str(forged_log),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_canonical_suite_receipt_derives_each_verdict_and_summary_for_v1_v2(
    tmp_path: Path,
) -> None:
    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    python_list = tmp_path / "python.txt"
    powershell_list = tmp_path / "powershell.txt"
    test_list = tmp_path / "tests.txt"
    python_list.write_text("module.py\n", encoding="utf-8")
    powershell_list.write_text("script.ps1\n", encoding="utf-8")
    test_list.write_text("tests/test_one.py\n", encoding="utf-8")

    def write_pass_log(name: str, verdict: str) -> tuple[Path, dict[str, object]]:
        log = tmp_path / f"{name}.log"
        junit = tmp_path / f"{name}.xml"
        python_paths = {
            phase: Path(str(log) + f".python-environment.{phase}.json")
            for phase in ("pre", "post")
        }
        toolchain_paths = {
            phase: Path(str(log) + f".integration-toolchain.{phase}.json")
            for phase in ("pre", "post")
        }
        runtime_root = ROOT / "venv"
        executable = runtime_root / "Scripts" / "python.exe"
        launcher = runtime_root / "Scripts" / "pythonw.exe"
        python_dll = runtime_root / "python311.dll"
        pth_root = runtime_root / "Lib" / "site-packages"
        record_path = runtime_root / "Lib" / "site-packages" / "fixture-1.dist-info" / "RECORD"
        controls = {
            "allowed_write_root": "",
            "candidate_root": str(tmp_path),
            "git_allow_protocol": "file",
            "git_terminal_prompt": "0",
            "git_config_nosystem": "1",
            "git_config_system": "NUL",
            "git_config_global": "NUL",
            "git_config_count": "0",
            "git_attr_nosystem": "1",
            "git_protocol_from_user": "0",
            "git_optional_locks": "0",
            "git_topology_environment_clear": True,
            "git_topology_environment_count": 0,
            "offline": "1",
            "production_root": str(ROOT),
            "evidence_root": str(tmp_path),
            "pythonhashseed": "0",
            "pythonioencoding": "utf-8",
            "pythonutf8": "1",
            "secret_environment_clear": True,
            "secret_environment_count": 0,
            "secret_policy": "conservative_v1",
            "temp_policy": "system_temp_unique_v1",
            "python_executable": str(executable),
            "git_executable": str(ROOT / "git.exe"),
            "powershell_executable": str(ROOT / "powershell.exe"),
            "setuptools_use_distutils": "stdlib",
            "read_only_production_probe": False,
        }
        runtime_rows = sorted(
            [
                {"kind": "executable", "path": str(executable), "length": 2, "sha256": "d" * 64},
                {"kind": "launcher", "path": str(launcher), "length": 2, "sha256": "1" * 64},
                {"kind": "runtime_dll", "path": str(python_dll), "length": 3, "sha256": "e" * 64},
            ],
            key=lambda row: str(row["path"]).casefold(),
        )
        python_text = json.dumps(
            {
                "schema_version": "python_environment_fingerprint_v2",
                "executable": str(executable),
                "executable_sha256": "d" * 64,
                "python_version": "3.11.0",
                "implementation": "cpython",
                "cache_tag": "cpython-311",
                "platform": "win32",
                "prefix": str(runtime_root),
                "base_prefix": str(runtime_root),
                "sys_path": [str(tmp_path), str(ROOT / "src")],
                "controls": controls,
                "distributions": [{
                    "name": "fixture",
                    "version": "1",
                    "location": str(runtime_root / "Lib" / "site-packages"),
                    "record_path": str(record_path),
                    "record_sha256": "f" * 64,
                    "installer_sha256": None,
                    "files": [{
                        "path": str(record_path),
                        "length": 1,
                        "sha256": "f" * 64,
                        "record_algorithm": None,
                        "record_digest": None,
                        "record_size": None,
                    }],
                }],
                "runtime_files": runtime_rows,
                "pth_files": [
                    {
                        "path": str(pth_root / "__editable__.weather_market-0.1.0.pth"),
                        "length": 1,
                        "sha256": "4" * 64,
                    },
                    {
                        "path": str(pth_root / "distutils-precedence.pth"),
                        "length": 1,
                        "sha256": "5" * 64,
                    },
                ],
                "file_count": 4,
                "total_bytes": 8,
            },
            separators=(",", ":"),
        )
        toolchain_text = json.dumps(
            {
                "schema_version": "integration_toolchain_fingerprint_v1",
                "git": {"executable": str(ROOT / "git.exe"), "executable_sha256": "a" * 64, "version": "git fixture"},
                "git_lfs": {"executable": str(ROOT / "git-lfs.exe"), "executable_sha256": "c" * 64, "version": "git-lfs fixture"},
                "powershell": {"executable": str(ROOT / "powershell.exe"), "executable_sha256": "b" * 64, "version": "5.1", "edition": "Desktop", "clr_version": "4", "architecture": "x64"},
                "controls": controls,
            },
            separators=(",", ":"),
        )
        for path in python_paths.values():
            path.write_text(python_text, encoding="utf-8")
        for path in toolchain_paths.values():
            path.write_text(toolchain_text, encoding="utf-8")
        tracked_paths = {
            phase: Path(str(log) + f".tracked-worktree.{phase}.json")
            for phase in ("pre", "post")
        }
        tracked_digest = hashlib.sha256(
            (f"fixture.txt\t100644\t{'2' * 40}\t1\t{'3' * 64}\t-\t-\n").encode()
        ).hexdigest()
        tracked_payload = {
            "schema_version": "tracked_worktree_content_fingerprint_v1",
            "content_sha256": tracked_digest,
            "head": "1" * 40,
            "root": str(tmp_path),
            "file_count": 1,
            "total_bytes": 1,
            "lfs_file_count": 0,
            "entries": [{
                "path": "fixture.txt", "mode": "100644", "blob_oid": "2" * 40,
                "worktree_length": 1, "worktree_sha256": "3" * 64,
                "lfs_oid": None, "lfs_size": None,
            }],
        }
        for path in tracked_paths.values():
            path.write_text(json.dumps(tracked_payload, separators=(",", ":")), encoding="utf-8")
        python_sha = sha256(python_paths["pre"])
        toolchain_sha = sha256(toolchain_paths["pre"])
        junit.write_text(
            '<testsuites><testsuite tests="1" failures="0" errors="0" '
            'skipped="0" /></testsuites>\n',
            encoding="utf-8",
        )
        junit_sha = sha256(junit)
        log.write_text(
            "2026-08-25 00:30:59  tracked_worktree phase=pre "
            "schema=tracked_worktree_content_fingerprint_v1 "
            f"sha256={tracked_digest} files=1 bytes=1 lfs_files=0 path={tracked_paths['pre']}\n"
            "2026-08-25 00:30:59  integration_toolchain phase=pre "
            "schema=integration_toolchain_fingerprint_v1 "
            f"sha256={toolchain_sha} git_sha256={'a' * 64} "
            f"git_lfs_sha256={'c' * 64} "
            f"powershell_sha256={'b' * 64} path={toolchain_paths['pre']}\n"
            "2026-08-25 00:30:59  python_environment phase=pre "
            "schema=python_environment_fingerprint_v2 "
            f"sha256={python_sha} distributions=1 files=4 bytes=8 path={python_paths['pre']}\n"
            "2026-08-25 00:31:00  syntax "
            f"python_files=1 python_inventory_sha256={sha256(python_list)} "
            f"python_list={python_list} powershell_files=1 "
            f"powershell_inventory_sha256={sha256(powershell_list)} "
            f"powershell_list={powershell_list} python_exit=0 powershell_errors=0\n"
            "2026-08-25 00:31:01  planned chunks=1 files=1 max_files=20\n"
            "2026-08-25 00:31:02  chunk 1/1 junit_summary "
            f"path={junit} sha256={junit_sha} tests=1 failures=0 errors=0 "
            "skipped=0 deselected=0\n"
            "2026-08-25 00:31:03  aggregate tests=1 failures=0 errors=0 "
            f"skipped=0 deselected=0 planned_files=1 inventory_sha256={sha256(test_list)} "
            f"inventory_path={test_list}\n"
            "2026-08-25 00:31:04  integration_toolchain phase=post "
            "schema=integration_toolchain_fingerprint_v1 "
            f"sha256={toolchain_sha} git_sha256={'a' * 64} "
            f"git_lfs_sha256={'c' * 64} "
            f"powershell_sha256={'b' * 64} path={toolchain_paths['post']}\n"
            "2026-08-25 00:31:04  python_environment phase=post "
            "schema=python_environment_fingerprint_v2 "
            f"sha256={python_sha} distributions=1 files=4 bytes=8 path={python_paths['post']}\n"
            "2026-08-25 00:31:04  python_environment stable=true "
            f"pre_sha256={python_sha} post_sha256={python_sha} distributions=1 files=4 bytes=8\n"
            "2026-08-25 00:31:04  integration_toolchain stable=true "
            f"pre_sha256={toolchain_sha} post_sha256={toolchain_sha}\n"
            "2026-08-25 00:31:04  tracked_worktree phase=post "
            "schema=tracked_worktree_content_fingerprint_v1 "
            f"sha256={tracked_digest} files=1 bytes=1 lfs_files=0 path={tracked_paths['post']}\n"
            "2026-08-25 00:31:04  tracked_worktree stable=true "
            f"pre_sha256={tracked_digest} post_sha256={tracked_digest} files=1 bytes=1 lfs_files=0\n"
            f"{verdict}\n",
            encoding="utf-8",
        )
        results = {
            "planned_files": 1,
            "inventory_path": str(test_list),
            "inventory_sha256": sha256(test_list),
            "tests": 1,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "deselected": 0,
            "python_files": 1,
            "python_inventory_path": str(python_list),
            "python_inventory_sha256": sha256(python_list),
            "powershell_files": 1,
            "powershell_inventory_path": str(powershell_list),
            "powershell_inventory_sha256": sha256(powershell_list),
            "junit": [
                {
                    "ordinal": 1,
                    "path": str(junit),
                    "sha256": junit_sha,
                    "tests": 1,
                    "failures": 0,
                    "errors": 0,
                    "skipped": 0,
                    "deselected": 0,
                }
            ],
        }
        results.update(
            {
                "python_environment_schema": "python_environment_fingerprint_v2",
                "python_environment_sha256": python_sha,
                "python_environment_distributions": 1,
                "python_environment_files": 4,
                "python_environment_bytes": 8,
                "python_executable_sha256": "d" * 64,
                "python_environment_pre_path": str(python_paths["pre"]),
                "python_environment_post_path": str(python_paths["post"]),
                "python_environment_candidate_root": str(tmp_path),
                "python_environment_production_root": str(ROOT),
                "toolchain_schema": "integration_toolchain_fingerprint_v1",
                "toolchain_sha256": toolchain_sha,
                "toolchain_git_sha256": "a" * 64,
                "toolchain_git_lfs_sha256": "c" * 64,
                "toolchain_powershell_sha256": "b" * 64,
                "toolchain_pre_path": str(toolchain_paths["pre"]),
                "toolchain_post_path": str(toolchain_paths["post"]),
                "tracked_worktree_schema": "tracked_worktree_content_fingerprint_v1",
                "tracked_worktree_sha256": tracked_digest,
                "tracked_worktree_file_count": 1,
                "tracked_worktree_total_bytes": 1,
                "tracked_worktree_lfs_file_count": 0,
                "tracked_worktree_root": str(tmp_path),
                "tracked_worktree_head": "1" * 40,
                "tracked_worktree_pre_path": str(tracked_paths["pre"]),
                "tracked_worktree_post_path": str(tracked_paths["post"]),
            }
        )
        return log, results

    preflight_verdict = (
        "2026-08-25 00:31:04  VERDICT: INTEGRATION PREFLIGHT PASSED; "
        "full suite not run and merge is not authorized"
    )
    full_verdict = (
        "2026-08-25 00:32:04  VERDICT: ALL CHUNKS PASSED (1/1); "
        "exact tip eligible for separate reviewed merge"
    )
    preflight_log, preflight_results = write_pass_log(
        "preflight", preflight_verdict
    )
    full_log, full_results = write_pass_log("full", full_verdict)
    suite_receipt_path = tmp_path / "suite-receipt.json"
    bounded_suite = OPS / "bounded_worktree_test_suite.ps1"
    suite_script = OPS / "integration_attempt_suite.ps1"
    receipt = {
        "schema": "weather_integration_attempt_suite_receipt_v1",
        "status": "PASS",
        "manifest_sha256": "a" * 64,
        "registration_receipt_sha256": "b" * 64,
        "registration_intent_sha256": "c" * 64,
        "expected_tip": "1" * 40,
        "branch_ref": "origin/codex/suite-proof",
        "origin_url": "https://example.invalid/weather.git",
        "worktree_root": str(tmp_path),
        "full_suite_started": True,
        "started_at_local": "2026-08-25T00:31:00-04:00",
        "completed_at_local": "2026-08-25T00:32:05-04:00",
        "runtime": {
            "bounded_suite_max_runtime_seconds": 5400,
            "suite_wrapper_teardown_allowance_seconds": 300,
            "suite_task_execution_time_limit_seconds": 5700,
            "minimum_phase_runtime_seconds": 60,
            "shared_deadline_utc": "2026-08-25T06:00:00.0000000Z",
            "elapsed_seconds": 65.0,
        },
        "safety": {
            "authority": "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY",
            "credential_value_access_authorized": False,
            "live_exchange_mutation_authorized": False,
        },
        "logs": {
            "preflight": {
                "path": str(preflight_log),
                "sha256": sha256(preflight_log),
                "exit_code": 0,
                "verdict": preflight_verdict,
                "test_results": preflight_results,
                "evidence_validation_error": None,
            },
            "full_suite": {
                "path": str(full_log),
                "sha256": sha256(full_log),
                "exit_code": 0,
                "verdict": full_verdict,
                "test_results": full_results,
                "evidence_validation_error": None,
            },
        },
        "scripts": {
            "bounded_suite": {"path": str(bounded_suite), "sha256": "d" * 64},
            "integration_suite": {"path": str(suite_script), "sha256": "e" * 64},
        },
    }
    suite_receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
function Assert-WeatherIntegrationRegistrationReceipt {
    param([object]$AttemptContract, [switch]$RequirePass)
    return [pscustomobject]@{
        ReceiptSha256 = ('b' * 64)
        IntentSha256 = ('c' * 64)
    }
}
function New-TestAttemptContract {
    param([string]$Schema)
    $manifest = [pscustomobject]@{
        schema = $Schema
        expected_tip = ('1' * 40)
        branch_ref = 'origin/codex/suite-proof'
        worktree_root = $env:WEATHER_TEST_ROOT
        baseline = [pscustomobject]@{
            origin_url = 'https://example.invalid/weather.git'
        }
        suite = [pscustomobject]@{
            expected_test_file_count = 1
            max_files_per_chunk = 20
            expected_chunk_count = 1
            expected_test_inventory_sha256 = $env:WEATHER_TEST_INVENTORY_SHA256
            expected_python_file_count = 1
            expected_python_inventory_sha256 = $env:WEATHER_PYTHON_INVENTORY_SHA256
            expected_powershell_file_count = 1
            expected_powershell_inventory_sha256 = $env:WEATHER_POWERSHELL_INVENTORY_SHA256
            expected_tracked_worktree_schema = 'tracked_worktree_content_fingerprint_v1'
            expected_tracked_worktree_sha256 = $env:WEATHER_TRACKED_WORKTREE_SHA256
            expected_tracked_worktree_file_count = 1
            expected_tracked_worktree_total_bytes = 1
            expected_tracked_worktree_lfs_file_count = 0
            expected_python_environment_schema = 'python_environment_fingerprint_v2'
            expected_python_environment_sha256 = $env:WEATHER_PYTHON_ENVIRONMENT_SHA256
            expected_python_environment_distributions = 1
            expected_python_environment_files = 3
            expected_python_environment_bytes = 6
            expected_toolchain_schema = 'integration_toolchain_fingerprint_v1'
            expected_toolchain_sha256 = $env:WEATHER_TOOLCHAIN_SHA256
            bounded_suite_max_runtime_seconds = 5400
            suite_wrapper_teardown_allowance_seconds = 300
            suite_task_execution_time_limit_seconds = 5700
        }
        evidence = [pscustomobject]@{
            suite_receipt = $env:WEATHER_SUITE_RECEIPT
            preflight_log = $env:WEATHER_PREFLIGHT_LOG
            full_suite_log = $env:WEATHER_FULL_LOG
        }
        orchestration = [pscustomobject]@{
            bounded_suite = [pscustomobject]@{
                path = $env:WEATHER_BOUNDED_SUITE
                sha256 = ('d' * 64)
            }
            attempt_suite = [pscustomobject]@{
                path = $env:WEATHER_SUITE_SCRIPT
                sha256 = ('e' * 64)
            }
        }
    }
    return [pscustomobject]@{ Manifest = $manifest; ManifestSha256 = ('a' * 64) }
}
$encoding = New-Object Text.UTF8Encoding($false)
$originalText = [IO.File]::ReadAllText($env:WEATHER_SUITE_RECEIPT)
foreach ($schema in @(
    'weather_integration_attempt_manifest_v1',
    'weather_integration_attempt_manifest_v2'
)) {
    $contract = New-TestAttemptContract -Schema $schema
    [IO.File]::WriteAllText($env:WEATHER_SUITE_RECEIPT, $originalText, $encoding)
    Assert-WeatherIntegrationSuiteReceipt -AttemptContract $contract | Out-Null
    if ($schema -eq 'weather_integration_attempt_manifest_v1') {
        $legacyReceipt = $originalText | ConvertFrom-Json
        $legacyReceipt.logs.preflight.PSObject.Properties.Remove('test_results')
        $legacyReceipt.logs.full_suite.PSObject.Properties.Remove('test_results')
        [IO.File]::WriteAllText(
            $env:WEATHER_SUITE_RECEIPT,
            ($legacyReceipt | ConvertTo-Json -Depth 30) + [Environment]::NewLine,
            $encoding
        )
        Assert-WeatherIntegrationSuiteReceipt -AttemptContract $contract | Out-Null
    }

    $forgedVerdict = $originalText | ConvertFrom-Json
    $forgedVerdict.logs.full_suite.verdict =
        '2026-08-25 00:32:05  VERDICT: ALL CHUNKS PASSED (1/1); exact tip eligible for separate reviewed merge'
    [IO.File]::WriteAllText(
        $env:WEATHER_SUITE_RECEIPT,
        ($forgedVerdict | ConvertTo-Json -Depth 30) + [Environment]::NewLine,
        $encoding
    )
    $verdictAccepted = $false
    try {
        Assert-WeatherIntegrationSuiteReceipt -AttemptContract $contract | Out-Null
        $verdictAccepted = $true
    }
    catch { }
    if ($verdictAccepted) { throw "forged $schema receipt verdict was accepted" }

    $forgedSummary = $originalText | ConvertFrom-Json
    $forgedSummary.logs.preflight.test_results.tests = 2
    [IO.File]::WriteAllText(
        $env:WEATHER_SUITE_RECEIPT,
        ($forgedSummary | ConvertTo-Json -Depth 30) + [Environment]::NewLine,
        $encoding
    )
    $summaryAccepted = $false
    try {
        Assert-WeatherIntegrationSuiteReceipt -AttemptContract $contract | Out-Null
        $summaryAccepted = $true
    }
    catch { }
    if ($summaryAccepted) { throw "forged $schema receipt summary was accepted" }
    [IO.File]::WriteAllText($env:WEATHER_SUITE_RECEIPT, $originalText, $encoding)
}
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
        WEATHER_TEST_ROOT=str(tmp_path),
        WEATHER_SUITE_RECEIPT=str(suite_receipt_path),
        WEATHER_PREFLIGHT_LOG=str(preflight_log),
        WEATHER_FULL_LOG=str(full_log),
        WEATHER_BOUNDED_SUITE=str(bounded_suite),
        WEATHER_SUITE_SCRIPT=str(suite_script),
        WEATHER_TEST_INVENTORY_SHA256=str(full_results["inventory_sha256"]),
        WEATHER_PYTHON_INVENTORY_SHA256=str(
            full_results["python_inventory_sha256"]
        ),
        WEATHER_POWERSHELL_INVENTORY_SHA256=str(
            full_results["powershell_inventory_sha256"]
        ),
        WEATHER_PYTHON_ENVIRONMENT_SHA256=str(
            full_results["python_environment_sha256"]
        ),
        WEATHER_TOOLCHAIN_SHA256=str(full_results["toolchain_sha256"]),
        WEATHER_TRACKED_WORKTREE_SHA256=str(
            full_results["tracked_worktree_sha256"]
        ),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_bounded_runner_fail_closes_ambient_controls_and_syntax_evidence() -> None:
    runner = (OPS / "bounded_worktree_test_suite.ps1").read_text(
        encoding="utf-8-sig"
    )
    contract = ATTEMPT_CONTRACT.read_text(encoding="utf-8-sig")
    creator = CREATOR.read_text(encoding="utf-8-sig")

    for control in (
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONUSERBASE",
        "PYTHONOPTIMIZE",
        "PYTHONWARNINGS",
    ):
        assert f'"{control}"' in runner
    assert '$env:PYTHONNOUSERSITE = "1"' in runner
    assert '$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"' in runner
    assert "read_bytes(),p,'exec'" in runner
    assert "Management.Automation.Language.Parser]::ParseFile" in runner
    assert '"--junitxml", $junitPath' in runner
    assert "Get-SuiteJUnitSummary -Path $junitPath" in runner
    assert "DtdProcessing]::Prohibit" in runner
    assert "Get-WeatherIntegrationJUnitFileSummary -Path $junitPath" in contract
    assert "Candidate deletes baseline test inventory" in (
        PREPARATION_CONTRACT.read_text(encoding="utf-8-sig")
    )
    assert "Assert-WeatherIntegrationCandidateTestInventory" in creator
    for source in (runner, creator, SUITE.read_text(encoding="utf-8-sig")):
        assert "(?:test_[^/]*|[^/]+_test)" in source


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
    assert "$schedulerSnapshot = @(Get-ScheduledTask -ErrorAction Stop)" in contract
    assert contract.count("Get-ScheduledTask -ErrorAction Stop") == 1
    assert "@task-name-already-exists" in contract
    assert "$isOwnExactStagedTask" in contract
    assert '[string]$_.State -eq "Disabled" -and -not $settingsEnabled' in contract
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
    assert "@ready-enabled" in contract
    assert "@ready-due-or-past" in contract
    assert "@disabled-without-valid-retirement-receipt" in contract
    assert "Assert-WeatherIntegrationTaskRetirementReceipt" in contract
    assert "Assert-WeatherIntegrationFailClosureReceipt" in contract
    assert "-Task $task -RepositoryRoot $resolvedRepositoryRoot" in contract
    assert "$repositoryRoot = Split-Path -Parent" not in contract
    assert "[$retirementFailure]" in contract
    assert "$conflictStartInstant.AddHours(4)" in contract
    assert "$conflictStartInstant -le $mergeInstant" in contract
    assert "$suiteInstant -le $conflictEndInstant" in contract
    assert "$postInfoSnapshot = @(Get-ScheduledTask -ErrorAction Stop)" in contract
    assert "$finalQuietSnapshot = @(Get-ScheduledTask -ErrorAction Stop)" in contract
    assert "$terminalSnapshot = @(Get-ScheduledTask -ErrorAction Stop)" in contract
    assert "@state-changed-during-collision-check" in contract
    assert "@next-run-changed-during-collision-check" in contract
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
    New-TestTask 'WeatherIntegrationSuite_candidate-a1' 'Ready' $true ''
)
$global:nextRun = $null
$ownNameAcceptedDuringPreparation = $false
try {
    Assert-WeatherIntegrationNoActiveAttemptCollision `
        -SuiteAtLocal $suite -MergeAtLocal $merge `
        -AttemptId 'candidate-a1' `
        -RepositoryRoot $global:expectedRepositoryRoot
    $ownNameAcceptedDuringPreparation = $true
}
catch { }
if ($ownNameAcceptedDuringPreparation) {
    throw 'Preparation accepted an already-existing exact task name.'
}
$global:tasks = @(
    (New-TestTask 'WeatherIntegrationSuite_candidate-a1' 'Disabled' $false ''),
    (New-TestTask 'WeatherIntegrationMerge_candidate-a1' 'Disabled' $false 'integration_attempt_merge.ps1')
)
Assert-WeatherIntegrationNoActiveAttemptCollision `
    -SuiteAtLocal $suite -MergeAtLocal $merge `
    -AttemptId 'candidate-a1' `
    -RepositoryRoot $global:expectedRepositoryRoot `
    -AllowOwnExactTasks
$global:tasks = @(
    New-TestTask 'WeatherIntegrationSuite_candidate-a1' 'Ready' $true ''
)
$ownReadyAccepted = $false
try {
    Assert-WeatherIntegrationNoActiveAttemptCollision `
        -SuiteAtLocal $suite -MergeAtLocal $merge `
        -AttemptId 'candidate-a1' `
        -RepositoryRoot $global:expectedRepositoryRoot `
        -AllowOwnExactTasks
    $ownReadyAccepted = $true
}
catch { }
if ($ownReadyAccepted) {
    throw 'AllowOwnExactTasks accepted an enabled Ready own task.'
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
foreach ($allowDemandStart in @($true, $false)) {
    $global:tasks = @(
        New-TestTask 'WeatherIntegrationSuite_retired' 'Disabled' $false '' $allowDemandStart
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
        throw 'Disabled task escaped without a valid retirement receipt.'
    }
}
$global:retirementReceiptValid = $true
Assert-WeatherIntegrationNoActiveAttemptCollision `
    -SuiteAtLocal $suite -MergeAtLocal $merge `
    -RepositoryRoot $global:expectedRepositoryRoot
$global:retirementReceiptValid = $false
$global:tasks = @(New-TestTask 'WeatherIntegrationSuite_spent' 'Ready' $true '')
foreach ($nextRunCase in @(
    [pscustomobject]@{ Label = 'null'; Value = $null },
    [pscustomobject]@{ Label = 'past'; Value = $suite.AddMinutes(-1) },
    [pscustomobject]@{ Label = 'due'; Value = $suite }
)) {
    $global:nextRun = $nextRunCase.Value
    $spentAccepted = $false
    try {
        Assert-WeatherIntegrationNoActiveAttemptCollision `
            -SuiteAtLocal $suite -MergeAtLocal $merge `
            -RepositoryRoot $global:expectedRepositoryRoot
        $spentAccepted = $true
    }
    catch { }
    if ($spentAccepted) {
        throw "Enabled Ready spent task with $($nextRunCase.Label) NextRunTime bypassed collision gate."
    }
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


def test_collision_gate_handles_non_exec_actions_without_arguments() -> None:
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
. $env:WEATHER_PREPARATION_CONTRACT
$global:tasks = @()
$global:nextRun = $null
$global:taskInfoCalls = 0
$global:taskSnapshotCalls = 0
$global:transitionAtTaskSnapshot = 0
$global:transitionTasks = @()
function Get-ScheduledTask {
    param($ErrorAction)
    $global:taskSnapshotCalls++
    if ($global:transitionAtTaskSnapshot -gt 0 -and
        $global:taskSnapshotCalls -ge $global:transitionAtTaskSnapshot) {
        return @($global:transitionTasks)
    }
    return @($global:tasks)
}
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
$suite = (Get-Date).Date.AddDays(1).AddMinutes(40)
$merge = (Get-Date).Date.AddDays(1).AddMinutes(80)
$global:tasks = @(New-NonExecTask 'BenignComHandlerTask')
Assert-WeatherIntegrationNoActiveAttemptCollision `
    -SuiteAtLocal $suite -MergeAtLocal $merge `
    -RepositoryRoot 'C:\synthetic-production-root'
if ($global:taskInfoCalls -ne 0) {
    throw 'benign non-Exec action was treated as protected merge work'
}
$global:tasks = @(New-NonExecTask 'WeatherMergeSensitiveDriver')
foreach ($nextRunCase in @(
    [pscustomobject]@{ Label = 'null'; Value = $null },
    [pscustomobject]@{ Label = 'past'; Value = (Get-Date).AddMinutes(-1) },
    [pscustomobject]@{ Label = 'due'; Value = (Get-Date) }
)) {
    $global:taskInfoCalls = 0
    $global:nextRun = $nextRunCase.Value
    $dueBlocked = $false
    try {
        Assert-WeatherIntegrationNoActiveAttemptCollision `
            -SuiteAtLocal $suite -MergeAtLocal $merge `
            -RepositoryRoot 'C:\synthetic-production-root'
    }
    catch {
        $dueBlocked = $_.Exception.Message -like '*@ready-due-or-past*'
    }
    if (-not $dueBlocked -or $global:taskInfoCalls -ne 1) {
        throw "Sensitive Ready task with $($nextRunCase.Label) NextRunTime escaped the due-transition collision."
    }
}
$global:taskInfoCalls = 0
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
$global:nextRun = $merge.AddMinutes(30)
foreach ($transitionAt in @(2, 3, 4)) {
    $global:taskSnapshotCalls = 0
    $global:taskInfoCalls = 0
    $global:tasks = @(New-NonExecTask 'WeatherMergeSensitiveDriver')
    $global:transitionTasks = @(
        [pscustomobject]@{
            TaskName = 'WeatherMergeSensitiveDriver'
            TaskPath = '\'
            State = 'Running'
            Settings = [pscustomobject]@{ Enabled = $true }
            Actions = @([pscustomobject]@{
                ClassId = '{00000000-0000-0000-0000-000000000000}'
            })
        }
    )
    $global:transitionAtTaskSnapshot = $transitionAt
    $transitionFailure = ''
    try {
        Assert-WeatherIntegrationNoActiveAttemptCollision `
            -SuiteAtLocal $suite -MergeAtLocal $merge `
            -RepositoryRoot 'C:\synthetic-production-root'
    }
    catch { $transitionFailure = $_.Exception.Message }
    if ($transitionFailure -notlike '*@state-changed-during-collision-check*') {
        throw "Ready-to-Running transition at Scheduler snapshot $transitionAt escaped collision protection"
    }
}
$global:transitionAtTaskSnapshot = 0
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
        WEATHER_PREPARATION_CONTRACT=str(PREPARATION_CONTRACT),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_creator_preflight_uses_immutable_file_handoff_and_zero_plain_children() -> None:
    preparer = PREPARER.read_text(encoding="utf-8-sig")
    creator = CREATOR.read_text(encoding="utf-8-sig")
    contract = PREPARATION_CONTRACT.read_text(encoding="utf-8-sig")

    assert "Invoke-WeatherIntegrationPowerShellChild" not in preparer
    assert "function Invoke-WeatherIntegrationPowerShellChild" not in contract
    assert 'Join-Path $preparationRoot "creator-preflight-plan.json"' in preparer
    assert 'Join-Path $preparationRoot "creator-preflight-plan.json"' in creator
    assert "creator_preflight_plan_path = $creatorPreflightPlanPath" in preparer
    assert "Write-WeatherIntegrationImmutableJson" in creator
    assert "Read-WeatherIntegrationEvidenceSnapshot" in preparer
    assert "Read-WeatherIntegrationEvidenceSnapshot" in creator
    assert "Assert-WeatherIntegrationCreatorPreflightPlan" in preparer
    assert "Assert-WeatherIntegrationCreatorPreflightPlan" in creator
    assert "preparation_contract = [ordered]@{" in creator
    assert "-PreparationContractPath (" in preparer
    assert "-ExpectedPreparationContractSha256 (" in preparer
    assert (
        "-PreparationContractPath ([string]$orchestration.preparation_contract.path)"
        in creator
    )
    assert "-ExpectedPreparationContractSha256 (" in creator
    assert '"-CreatorPreflightPlanPath", $creatorPreflightPlanPath' in preparer
    assert (
        '"-ExpectedCreatorPreflightPlanSha256", $creatorPreflightPlanSha256'
        in preparer
    )
    assert "Creator preflight plan changed after the preparer retained" in creator
    assert 'preparationAuthorizationRecord["creator_preflight_plan_path"]' in creator
    assert 'preparationAuthorizationRecord["creator_preflight_plan_sha256"]' in creator
    assert "creator_preflight = [ordered]@{" in preparer
    assert "plan_sha256 = $creatorPreflightPlanSha256" in preparer
    assert '"creator_preflight_plan_path", "creator_preflight_plan_sha256"' in (
        ATTEMPT_CONTRACT.read_text(encoding="utf-8-sig")
    )
    assert "Creator preflight plan changed after the attempt manifest was frozen." in (
        ATTEMPT_CONTRACT.read_text(encoding="utf-8-sig")
    )


def test_preparer_derives_integration_preflight_inventory_from_exact_log() -> None:
    preparer = PREPARER.read_text(encoding="utf-8-sig")
    contract = ATTEMPT_CONTRACT.read_text(encoding="utf-8-sig")
    suite = SUITE.read_text(encoding="utf-8-sig")

    observation = preparer[preparer.index("Get-WeatherPrearmingRunObservation") :]
    preflight_observation = observation[
        observation.index('-Mode "integration_preflight"') :
        observation.index("$expectedPreflightVerdict")
    ]
    assert "-ExpectedTestFileCount 0" in preflight_observation
    assert "-ExpectedChunkCount 0" in preflight_observation
    assert "Get-WeatherIntegrationSuiteLogDeclaredPlan" in preparer
    assert "Get-WeatherIntegrationSuiteLogDeclaredPlan" in contract
    assert "Get-WeatherIntegrationSuiteLogDeclaredPlan" in suite
    assert "Integration-preflight log changed its bounded chunk size." in contract
    assert (
        "$null -eq $qualificationRuns.integration_preflight.test_results" in preparer
    )
    assert "$null -eq $qualificationRuns.full_suite.test_results" in preparer
    assert "ExpectedTestFileCount 19" not in preparer
    assert "ExpectedPlannedFiles 19" not in contract
    assert "ExpectedPlannedFiles 19" not in suite


def test_creator_preflight_plan_validator_rejects_identity_substitution(
    tmp_path: Path,
) -> None:
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
. $env:WEATHER_PREPARATION_CONTRACT
$attemptRoot = Join-Path $env:WEATHER_PLAN_ROOT 'attempt-a1'
$preparationRoot = $attemptRoot + '.preparation'
New-Item -ItemType Directory -Path $preparationRoot | Out-Null
$planPath = Join-Path $preparationRoot 'creator-preflight-plan.json'
$repoRoot = Join-Path $env:WEATHER_PLAN_ROOT 'repo'
$worktreeRoot = Join-Path $env:WEATHER_PLAN_ROOT 'worktree'
$creatorPath = Join-Path $repoRoot 'scripts\ops\new_integration_attempt.ps1'
$preparationContractPath = $env:WEATHER_PREPARATION_CONTRACT
$intentPath = Join-Path $preparationRoot 'preparation-intent.json'
$suite = [datetime]'2026-08-27T01:00:00'
$merge = [datetime]'2026-08-27T03:00:00'
$payload = [ordered]@{
    schema = $script:WeatherIntegrationCreatorPreflightPlanSchema
    status = 'PREFLIGHT_READY'
    created_at_local = [DateTimeOffset]::Now.ToString('o')
    attempt_id = 'attempt-a1'
    attempt_root = $attemptRoot
    preparation_root = $preparationRoot
    preflight_plan_path = $planPath
    repo_root = $repoRoot
    worktree_root = $worktreeRoot
    branch_ref = 'origin/codex/attempt-a1'
    expected_tip = ('1' * 40)
    suite_at_local = $suite.ToString('o')
    merge_at_local = $merge.ToString('o')
    production_baseline = ('2' * 40)
    origin_url = 'https://github.com/example/weather.git'
    expected_test_file_count = 21
    expected_chunk_count = 2
    expected_test_inventory_sha256 = ('7' * 64)
    expected_python_file_count = 100
    expected_python_inventory_sha256 = ('8' * 64)
    expected_powershell_file_count = 20
    expected_powershell_inventory_sha256 = ('9' * 64)
    repair_class = 'initial'
    require_live_sdk_contract = $false
    creator = [ordered]@{ path = $creatorPath; sha256 = ('3' * 64) }
    preparation_contract = [ordered]@{
        path = $preparationContractPath
        sha256 = ('6' * 64)
    }
    preparation = [ordered]@{
        intent_path = $intentPath
        intent_sha256 = ('4' * 64)
        execution_authorization_sha256 = ('5' * 64)
    }
    prearming_qualification_required = $true
    prearming_qualification_present = $false
    safety = [ordered]@{
        authority = 'NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY'
        credential_value_access_authorized = $false
        live_exchange_mutation_authorized = $false
    }
}
Write-WeatherIntegrationImmutableJson -Path $planPath -Payload $payload
$snapshot = Read-WeatherIntegrationEvidenceSnapshot `
    -Path $planPath -MaximumBytes 65536 -ContentType Json
$arguments = @{
    EvidenceSnapshot = $snapshot
    AttemptRoot = $attemptRoot
    AttemptId = 'attempt-a1'
    RepositoryRoot = $repoRoot
    WorktreeRoot = $worktreeRoot
    BranchRef = 'origin/codex/attempt-a1'
    ExpectedTip = ('1' * 40)
    SuiteAtLocal = $suite
    MergeAtLocal = $merge
    ProductionBaseline = ('2' * 40)
    OriginUrl = 'https://github.com/example/weather.git'
    RepairClass = 'initial'
    RequireLiveSdkContract = $false
    PreparationIntentPath = $intentPath
    ExpectedPreparationIntentSha256 = ('4' * 64)
    ExpectedPreparationAuthorizationSha256 = ('5' * 64)
    CreatorPath = $creatorPath
    ExpectedCreatorSha256 = ('3' * 64)
    PreparationContractPath = $preparationContractPath
    ExpectedPreparationContractSha256 = ('6' * 64)
    ExpectedTestFileCount = 21
    ExpectedChunkCount = 2
    ExpectedTestInventorySha256 = ('7' * 64)
    ExpectedPythonFileCount = 100
    ExpectedPythonInventorySha256 = ('8' * 64)
    ExpectedPowerShellFileCount = 20
    ExpectedPowerShellInventorySha256 = ('9' * 64)
}
$validated = Assert-WeatherIntegrationCreatorPreflightPlan @arguments
if ([string]$validated.Sha256 -ne [string]$snapshot.Sha256) {
    throw 'creator preflight validator did not retain the exact snapshot hash'
}
$payload.expected_tip = ('9' * 40)
[IO.File]::WriteAllText(
    $planPath,
    ($payload | ConvertTo-Json -Depth 20) + [Environment]::NewLine,
    (New-Object Text.UTF8Encoding($false))
)
$substituted = Read-WeatherIntegrationEvidenceSnapshot `
    -Path $planPath -MaximumBytes 65536 -ContentType Json
$arguments.EvidenceSnapshot = $substituted
$accepted = $false
try {
    Assert-WeatherIntegrationCreatorPreflightPlan @arguments | Out-Null
    $accepted = $true
}
catch { }
if ($accepted) {
    throw 'creator preflight validator accepted an identity substitution'
}
$payload.expected_tip = ('1' * 40)
$payload.preparation_contract["sha256"] = ('7' * 64)
[IO.File]::WriteAllText(
    $planPath,
    ($payload | ConvertTo-Json -Depth 20) + [Environment]::NewLine,
    (New-Object Text.UTF8Encoding($false))
)
$dependencySubstitution = Read-WeatherIntegrationEvidenceSnapshot `
    -Path $planPath -MaximumBytes 65536 -ContentType Json
$arguments.EvidenceSnapshot = $dependencySubstitution
$dependencyAccepted = $false
try {
    Assert-WeatherIntegrationCreatorPreflightPlan @arguments | Out-Null
    $dependencyAccepted = $true
}
catch { }
if ($dependencyAccepted) {
    throw 'creator preflight validator accepted a preparation-contract substitution'
}
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
        WEATHER_PREPARATION_CONTRACT=str(PREPARATION_CONTRACT),
        WEATHER_PLAN_ROOT=str(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_contained_preparation_child_rejects_expired_bound_and_disposes_on_timeout(
    tmp_path: Path,
) -> None:
    child = tmp_path / "contained-child.ps1"
    child.write_text("exit 0\n", encoding="utf-8")
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
. $env:WEATHER_PREPARATION_CONTRACT
$global:newJobCalls = 0
$global:jobTerminatedAndDrained = $false
$global:jobDisposed = $false
$global:processDisposed = $false
function ConvertTo-ScheduledTaskArgumentString {
    param([string[]]$Tokens)
    return ($Tokens -join ' ')
}
function New-WeatherKillOnCloseJob {
    $global:newJobCalls += 1
    $job = [pscustomobject]@{}
    $job | Add-Member -MemberType ScriptMethod -Name TerminateAndWaitForEmpty -Value {
        param([int]$Milliseconds)
        $global:jobTerminatedAndDrained = $true
        $this.Dispose()
    }
    $job | Add-Member -MemberType ScriptMethod -Name Dispose -Value {
        $global:jobDisposed = $true
    }
    return $job
}
function Start-WeatherProcessInJobWithRedirectedOutput {
    param(
        $Job, [string]$FilePath, [string]$ArgumentString,
        [string]$WorkingDirectory, [string]$StandardOutputPath,
        [string]$StandardErrorPath
    )
    $process = [pscustomobject]@{ HasExited = $false }
    $process | Add-Member -MemberType ScriptMethod -Name Refresh -Value {}
    $process | Add-Member -MemberType ScriptMethod -Name GetStandardOutputLength -Value { return 0 }
    $process | Add-Member -MemberType ScriptMethod -Name GetStandardErrorLength -Value { return 0 }
    $process | Add-Member -MemberType ScriptMethod -Name ReadStandardOutputBytes -Value {
        param([int]$MaximumBytes)
        return [byte[]]@()
    }
    $process | Add-Member -MemberType ScriptMethod -Name ReadStandardErrorBytes -Value {
        param([int]$MaximumBytes)
        return [byte[]]@()
    }
    $process | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {
        param([int]$Milliseconds = -1)
        $this.HasExited = $true
        return $true
    }
    $process | Add-Member -MemberType ScriptMethod -Name Dispose -Value {
        $global:processDisposed = $true
    }
    return $process
}
$expiredRejected = $false
try {
    Invoke-WeatherIntegrationContainedPowerShellChild `
        -ScriptPath $env:WEATHER_CONTAINED_CHILD `
        -ExpectedSha256 (Get-WeatherIntegrationFileSha256 -Path $env:WEATHER_CONTAINED_CHILD) `
        -Arguments @() -Label 'expired child' -WorkingDirectory $env:WEATHER_TEMP_ROOT `
        -OutputDirectory $env:WEATHER_TEMP_ROOT `
        -HardStop (Get-WeatherIntegrationScheduleLocalNow).AddSeconds(-1) | Out-Null
}
catch { $expiredRejected = ($_.Exception.Message -like '*not in the future*') }
if (-not $expiredRejected -or $global:newJobCalls -ne 0) {
    throw 'Expired hard stop launched a contained child.'
}
$timedOut = $false
try {
    Invoke-WeatherIntegrationContainedPowerShellChild `
        -ScriptPath $env:WEATHER_CONTAINED_CHILD `
        -ExpectedSha256 (Get-WeatherIntegrationFileSha256 -Path $env:WEATHER_CONTAINED_CHILD) `
        -Arguments @() -Label 'timed child' -WorkingDirectory $env:WEATHER_TEMP_ROOT `
        -OutputDirectory $env:WEATHER_TEMP_ROOT `
        -HardStop (Get-WeatherIntegrationScheduleLocalNow).AddMilliseconds(50) | Out-Null
}
catch { $timedOut = ($_.Exception.Message -like '*hard teardown boundary*') }
if (-not $timedOut -or $global:newJobCalls -ne 1 -or
    -not $global:jobTerminatedAndDrained -or -not $global:jobDisposed -or
    -not $global:processDisposed) {
    throw 'Contained child timeout did not drain the Job and dispose both wrappers.'
}
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
        WEATHER_PREPARATION_CONTRACT=str(PREPARATION_CONTRACT),
        WEATHER_CONTAINED_CHILD=str(child),
        WEATHER_TEMP_ROOT=str(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_contained_preparation_child_retains_verified_script_handle(
    tmp_path: Path,
) -> None:
    child = tmp_path / "retained-child.ps1"
    ready = tmp_path / "child-ready.txt"
    release = tmp_path / "child-release.txt"
    replacement = tmp_path / "replacement.ps1"
    child.write_text(
        "param([string]$ReadyPath, [string]$ReleasePath)\n"
        "[IO.File]::WriteAllText($ReadyPath, 'ready')\n"
        "$deadline = (Get-Date).AddSeconds(15)\n"
        "while (-not (Test-Path -LiteralPath $ReleasePath)) {\n"
        "    if ((Get-Date) -ge $deadline) { exit 9 }\n"
        "    Start-Sleep -Milliseconds 50\n"
        "}\n"
        "Write-Output 'stable-script'\n"
        "exit 0\n",
        encoding="utf-8",
    )
    replacement.write_text("Write-Output 'replacement'\nexit 0\n", encoding="utf-8")
    expected_sha256 = hashlib.sha256(child.read_bytes()).hexdigest()
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
. $env:WEATHER_PREPARATION_CONTRACT
. $env:WEATHER_JOB_HELPER
$result = Invoke-WeatherIntegrationContainedPowerShellChild `
    -ScriptPath $env:WEATHER_CONTAINED_CHILD `
    -ExpectedSha256 $env:WEATHER_CONTAINED_CHILD_SHA256 `
    -Arguments @($env:WEATHER_READY_PATH, $env:WEATHER_RELEASE_PATH) `
    -Label 'retained script child' `
    -WorkingDirectory $env:WEATHER_TEMP_ROOT `
    -OutputDirectory $env:WEATHER_TEMP_ROOT `
    -HardStop (Get-WeatherIntegrationScheduleLocalNow).AddSeconds(20)
[pscustomobject]@{
    exit_code = [int]$result.ExitCode
    stdout = [string]$result.Stdout
    stdout_sha256 = [string]$result.StdoutSha256
    containment = [string]$result.Containment
} | ConvertTo-Json -Compress
"""
    env = os.environ.copy()
    env.update(
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
        WEATHER_PREPARATION_CONTRACT=str(PREPARATION_CONTRACT),
        WEATHER_JOB_HELPER=str(OPS / "windows_kill_on_close_job.ps1"),
        WEATHER_CONTAINED_CHILD=str(child),
        WEATHER_CONTAINED_CHILD_SHA256=expected_sha256,
        WEATHER_READY_PATH=str(ready),
        WEATHER_RELEASE_PATH=str(release),
        WEATHER_TEMP_ROOT=str(tmp_path),
    )
    wrapper = subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 10
    while not ready.exists() and wrapper.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    replacement_blocked = False
    try:
        os.replace(replacement, child)
    except OSError:
        replacement_blocked = True
    finally:
        release.write_text("release\n", encoding="utf-8")
    stdout, stderr = wrapper.communicate(timeout=20)

    assert ready.exists(), stderr
    assert replacement_blocked, "verified child script was replaceable while executing"
    assert wrapper.returncode == 0, stderr
    payload = json.loads(stdout.strip().splitlines()[-1])
    assert payload["exit_code"] == 0
    assert payload["stdout"].strip() == "stable-script"
    assert payload["containment"] == "WINDOWS_JOB_KILL_ON_CLOSE_RETAINED_OUTPUT"
    assert not list(tmp_path.glob(".contained-child-*.stdout"))
    assert not list(tmp_path.glob(".contained-child-*.stderr"))
    os.replace(replacement, child)
    assert "replacement" in child.read_text(encoding="utf-8")


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
    current_closure = contract[
        contract.index("function Assert-WeatherIntegrationCurrentFailClosure") :
        contract.index("function Assert-WeatherLegacyBootstrapRetirementReceipt")
    ]
    assert current_closure.count("Get-WeatherIntegrationScheduledTaskSnapshot") == 1
    assert "Get-ScheduledTask `" not in current_closure
    assert "appeared after the FAIL closure proved exact absence" in contract
    assert "Current task does not match the exact Disabled FAIL closure evidence" in contract


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
    assert 'Join-Path $PSScriptRoot "windows_kill_on_close_job.ps1"' in helper
    assert ". $weatherIntegrationJobHelper" in helper
    assert "New-WeatherKillOnCloseJob" in helper
    assert "Start-WeatherProcessInJobWithRedirectedOutput" in helper
    assert "while (-not $process.WaitForExit(200))" in helper
    assert "MaxOutputBytes = 1048576" in helper
    assert "$job.Dispose()" in helper
    assert "closing its kill-on-close Job proved its" in helper
    assert "child process tree was terminated" in helper
    assert "ReadToEndAsync" not in helper
    assert "taskkill" not in helper.lower()
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
    assert "$ExpectedOriginUrl = Get-WeatherIntegrationCanonicalOriginUrl" in quiet_merge
    assert "no mutation may continue from a stale tracking ref" in quiet_merge
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
$script:WeatherTestPredecessorTaskState = 'Disabled'
$script:WeatherTestPredecessorTasksPresent = $true
function Get-ScheduledTask {
    param([string]$TaskName, [string]$TaskPath, [object]$ErrorAction)
    if (-not $script:WeatherTestPredecessorTasksPresent) { return @() }
    $taskNames = if ([string]::IsNullOrWhiteSpace($TaskName)) {
        @(
            [string]$manifest.schedule.suite_task_name,
            [string]$manifest.schedule.merge_task_name
        )
    }
    else { @($TaskName) }
    return @($taskNames | ForEach-Object {
        [pscustomobject]@{
            TaskName = $_
            TaskPath = '\'
            State = $script:WeatherTestPredecessorTaskState
            Settings = [pscustomobject]@{
                Enabled = ($script:WeatherTestPredecessorTaskState -ne 'Disabled')
            }
        }
    })
}
$currentClosure = Assert-WeatherIntegrationCurrentFailClosure `
    -AttemptContract $attempt
if ($currentClosure.Suite.ReceiptSha256 -ne $currentClosure.Merge.ReceiptSha256) {
    throw 'current closure did not return one exact receipt'
}
$script:WeatherTestPredecessorTaskState = 'Ready'
$reenabledAccepted = $false
try {
    Assert-WeatherIntegrationCurrentFailClosure -AttemptContract $attempt | Out-Null
    $reenabledAccepted = $true
}
catch { }
if ($reenabledAccepted) { throw 're-enabled predecessor tasks authorized a successor' }
$script:WeatherTestPredecessorTaskState = 'Disabled'
$script:WeatherTestPredecessorTasksPresent = $false
foreach ($row in @($closure.tasks)) {
    $row.exists = $false
    $row.disabled = $false
}
[IO.File]::WriteAllText(
    $closurePath,
    ($closure | ConvertTo-Json -Depth 20) + [Environment]::NewLine,
    $encoding
)
Assert-WeatherIntegrationCurrentFailClosure -AttemptContract $attempt | Out-Null
$registrationPreservedEvidence = @($closure.preserved_evidence)
$intentBackupPath = "$intentPath.test-backup"
$receiptBackupPath = "$receiptPath.test-backup"
Move-Item -LiteralPath $intentPath -Destination $intentBackupPath
Move-Item -LiteralPath $receiptPath -Destination $receiptBackupPath
$closure.registration_evidence.registration_intent_sha256 = $null
$closure.registration_evidence.registration_receipt_sha256 = $null
$closure.preserved_evidence = @()
[IO.File]::WriteAllText(
    $closurePath,
    ($closure | ConvertTo-Json -Depth 20) + [Environment]::NewLine,
    $encoding
)
Assert-WeatherIntegrationCurrentFailClosure -AttemptContract $attempt | Out-Null
Move-Item -LiteralPath $intentBackupPath -Destination $intentPath
Move-Item -LiteralPath $receiptBackupPath -Destination $receiptPath
$closure.registration_evidence.registration_intent_sha256 = `
    Get-WeatherIntegrationFileSha256 -Path $intentPath
$closure.registration_evidence.registration_receipt_sha256 = `
    Get-WeatherIntegrationFileSha256 -Path $receiptPath
$closure.preserved_evidence = $registrationPreservedEvidence
[IO.File]::WriteAllText(
    $closurePath,
    ($closure | ConvertTo-Json -Depth 20) + [Environment]::NewLine,
    $encoding
)
$script:WeatherTestPredecessorTasksPresent = $true
$appearedTaskAccepted = $false
try {
    Assert-WeatherIntegrationCurrentFailClosure -AttemptContract $attempt | Out-Null
    $appearedTaskAccepted = $true
}
catch { }
if ($appearedTaskAccepted) {
    throw 'task appearance after exact-absence closure authorized a successor'
}
foreach ($row in @($closure.tasks)) {
    $row.exists = $true
    $row.disabled = $true
}
[IO.File]::WriteAllText(
    $closurePath,
    ($closure | ConvertTo-Json -Depth 20) + [Environment]::NewLine,
    $encoding
)
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
    attempt_contract = ATTEMPT_CONTRACT.read_text(encoding="utf-8-sig")
    preparation_contract = PREPARATION_CONTRACT.read_text(encoding="utf-8-sig")
    manifest_reader = attempt_contract[
        attempt_contract.index("function Assert-WeatherIntegrationAttemptManifest") :
        attempt_contract.index("function Disable-WeatherIntegrationAttemptTasks")
    ]

    assert "function ConvertTo-WeatherIntegrationLocalInstant" in attempt_contract
    assert "function Get-WeatherIntegrationLocalElapsedSeconds" in attempt_contract
    assert "$TimeZone.GetUtcOffset($wallClock)" in attempt_contract
    assert "Get-WeatherIntegrationLocalElapsedSeconds" in manifest_reader
    assert "Historical v1 manifests retain" in manifest_reader
    assert "Get-WeatherIntegrationLocalElapsedSeconds" in preparation_contract
    assert "Get-WeatherIntegrationLocalElapsedSeconds" in CREATOR.read_text(
        encoding="utf-8-sig"
    )
    assert "Get-WeatherIntegrationLocalElapsedSeconds" in REGISTRAR.read_text(
        encoding="utf-8-sig"
    )
    preparer = PREPARER.read_text(encoding="utf-8-sig")
    assert "[DateTimeOffset]::Now" in preparer
    assert preparer.count("Get-WeatherIntegrationLocalElapsedSeconds") >= 2
    assert "$qualificationHardStop - (Get-WeatherIntegrationScheduleLocalNow)" not in (
        preparer
    )

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
$qualificationBoundary = Assert-WeatherIntegrationPrearmingQualificationWindow `
    -SuiteAtLocal ([datetime]'2026-08-26T00:40:00') `
    -Now ([datetime]'2026-08-25T07:20:00')
if ([int]$qualificationBoundary.required_current_window_seconds -ne 6000 -or
    [int]$qualificationBoundary.remaining_current_window_seconds -ne 6000 -or
    [datetime]$qualificationBoundary.hard_stop_local -ne
        [datetime]'2026-08-25T09:00:00') {
    throw 'Pre-arming qualification boundary did not freeze its exact reserve.'
}
$feasibilityBoundary = Assert-WeatherIntegrationPrearmingScheduleFeasibility `
    -SuiteAtLocal ([datetime]'2026-08-26T01:55:00') `
    -MergeAtLocal ([datetime]'2026-08-26T03:40:00')
if ([int]$feasibilityBoundary.required_runtime_seconds -ne 6000 -or
    [int]$feasibilityBoundary.launch_grace_seconds -ne 300 -or
    [int]$feasibilityBoundary.required_schedule_seconds -ne 6300 -or
    [int]$feasibilityBoundary.suite_to_merge_seconds -ne 6300) {
    throw 'Preparation feasibility did not freeze execution plus launch grace.'
}
$launchBoundary = Assert-WeatherIntegrationScheduledSuiteLaunchReserve `
    -SuiteAtLocal ([datetime]'2026-08-26T01:55:00') `
    -MergeAtLocal ([datetime]'2026-08-26T03:40:00') `
    -Now ([datetime]'2026-08-26T02:00:00') `
    -RequiredExecutionSeconds 6000 `
    -LaunchGraceSeconds 300 `
    -RequiredScheduleSeconds 6300
if ([double]$launchBoundary.launch_delay_seconds -ne 300 -or
    [int]$launchBoundary.remaining_to_merge_seconds -ne 6000) {
    throw 'Scheduled launch did not consume exactly the frozen grace.'
}
$zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$springElapsed = Get-WeatherIntegrationLocalElapsedSeconds `
    -StartLocal ([datetime]'2027-03-14T01:55:00') `
    -EndLocal ([datetime]'2027-03-14T03:00:00') `
    -TimeZone $zone
if ([int]$springElapsed -ne 300) {
    throw 'Spring-forward wall times did not convert to actual elapsed instants.'
}
$springLeadAccepted = $false
try {
    Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal ([datetime]'2027-03-14T03:00:00') `
        -MergeAtLocal ([datetime]'2027-03-14T03:35:00') `
        -Now ([datetime]'2027-03-14T01:55:00') `
        -MinimumLeadMinutes 10 -TimeZone $zone | Out-Null
    $springLeadAccepted = $true
}
catch { }
$springSpacingAccepted = $false
try {
    Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal ([datetime]'2027-03-14T01:55:00') `
        -MergeAtLocal ([datetime]'2027-03-14T03:10:00') `
        -Now ([datetime]'2027-03-14T00:30:00') `
        -MinimumLeadMinutes 10 -TimeZone $zone | Out-Null
    $springSpacingAccepted = $true
}
catch { }
$springFeasibilityAccepted = $false
try {
    Assert-WeatherIntegrationPrearmingScheduleFeasibility `
        -SuiteAtLocal ([datetime]'2027-03-14T01:55:00') `
        -MergeAtLocal ([datetime]'2027-03-14T03:40:00') `
        -TimeZone $zone | Out-Null
    $springFeasibilityAccepted = $true
}
catch { }
$springLaunch = Assert-WeatherIntegrationScheduledSuiteLaunchReserve `
    -SuiteAtLocal ([datetime]'2027-03-14T01:55:00') `
    -MergeAtLocal ([datetime]'2027-03-14T03:40:00') `
    -Now ([datetime]'2027-03-14T03:00:00') `
    -RequiredExecutionSeconds 2400 `
    -LaunchGraceSeconds 300 `
    -RequiredScheduleSeconds 2700 `
    -TimeZone $zone
$springQualification = Assert-WeatherIntegrationPrearmingQualificationWindow `
    -SuiteAtLocal ([datetime]'2027-03-15T00:40:00') `
    -Now ([datetime]'2027-03-14T01:55:00') `
    -TimeZone $zone
if ($springLeadAccepted -or $springSpacingAccepted -or
    $springFeasibilityAccepted -or
    [int]$springLaunch.launch_delay_seconds -ne 300 -or
    [int]$springLaunch.remaining_to_merge_seconds -ne 2400 -or
    [int]$springQualification.remaining_current_window_seconds -ne 21900) {
    throw 'Spring-forward reserve arithmetic used naive wall-clock subtraction.'
}
$initialLateAccepted = $false
$finalLateAccepted = $false
$sameDayQualificationAccepted = $false
$daytimeQualificationAccepted = $false
$lateWindowQualificationAccepted = $false
$shortRuntimeReserveAccepted = $false
$lateScheduledLaunchAccepted = $false
$earlyScheduledLaunchAccepted = $false
$extraSlackLateLaunchAccepted = $false
try {
    Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal $suite -MergeAtLocal $merge `
        -Now ([datetime]'2026-08-25T00:30:00.001') `
        -MinimumLeadMinutes 10 | Out-Null
    $initialLateAccepted = $true
}
catch { }
try {
    Assert-WeatherIntegrationPrearmingQualificationWindow `
        -SuiteAtLocal ([datetime]'2026-08-26T00:40:00') `
        -Now ([datetime]'2026-08-25T07:20:00.001') | Out-Null
    $lateWindowQualificationAccepted = $true
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
try {
    Assert-WeatherIntegrationPrearmingQualificationWindow `
        -SuiteAtLocal $suite `
        -Now ([datetime]'2026-08-25T00:30:00') | Out-Null
    $sameDayQualificationAccepted = $true
}
catch { }
try {
    Assert-WeatherIntegrationPrearmingQualificationWindow `
        -SuiteAtLocal ([datetime]'2026-08-26T00:40:00') `
        -Now ([datetime]'2026-08-25T12:00:00') | Out-Null
    $daytimeQualificationAccepted = $true
}
catch { }
try {
    Assert-WeatherIntegrationPrearmingScheduleFeasibility `
        -SuiteAtLocal ([datetime]'2026-08-26T01:55:00.001') `
        -MergeAtLocal ([datetime]'2026-08-26T03:40:00') | Out-Null
    $shortRuntimeReserveAccepted = $true
}
catch { }
try {
    Assert-WeatherIntegrationScheduledSuiteLaunchReserve `
        -SuiteAtLocal ([datetime]'2026-08-26T01:55:00') `
        -MergeAtLocal ([datetime]'2026-08-26T03:40:00') `
        -Now ([datetime]'2026-08-26T02:00:00.001') `
        -RequiredExecutionSeconds 6000 `
        -LaunchGraceSeconds 300 `
        -RequiredScheduleSeconds 6300 | Out-Null
    $lateScheduledLaunchAccepted = $true
}
catch { }
try {
    Assert-WeatherIntegrationScheduledSuiteLaunchReserve `
        -SuiteAtLocal ([datetime]'2026-08-26T01:55:00') `
        -MergeAtLocal ([datetime]'2026-08-26T03:40:00') `
        -Now ([datetime]'2026-08-26T01:54:59.999') `
        -RequiredExecutionSeconds 6000 `
        -LaunchGraceSeconds 300 `
        -RequiredScheduleSeconds 6300 | Out-Null
    $earlyScheduledLaunchAccepted = $true
}
catch { }
try {
    Assert-WeatherIntegrationScheduledSuiteLaunchReserve `
        -SuiteAtLocal ([datetime]'2026-08-26T01:00:00') `
        -MergeAtLocal ([datetime]'2026-08-26T03:40:00') `
        -Now ([datetime]'2026-08-26T01:05:00.001') `
        -RequiredExecutionSeconds 6000 `
        -LaunchGraceSeconds 300 `
        -RequiredScheduleSeconds 6300 | Out-Null
    $extraSlackLateLaunchAccepted = $true
}
catch { }
if ($initialLateAccepted -or $finalLateAccepted -or
    $sameDayQualificationAccepted -or $daytimeQualificationAccepted -or
    $lateWindowQualificationAccepted -or
    $shortRuntimeReserveAccepted -or $lateScheduledLaunchAccepted -or
    $earlyScheduledLaunchAccepted -or $extraSlackLateLaunchAccepted) {
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


def test_atomic_evidence_and_runtime_namespace_guards_are_load_bearing() -> None:
    contract = ATTEMPT_CONTRACT.read_text(encoding="utf-8-sig")
    preparation_contract = PREPARATION_CONTRACT.read_text(encoding="utf-8-sig")
    snapshot_helper = contract[
        contract.index("function Read-WeatherIntegrationEvidenceSnapshot") :
        contract.index("function Get-WeatherIntegrationFileSha256")
    ]
    manifest_reader = contract[
        contract.index("function Assert-WeatherIntegrationAttemptManifest") :
        contract.index("function Disable-WeatherIntegrationAttemptTasks")
    ]
    closure_reader = contract[
        contract.index("function Assert-WeatherIntegrationCurrentFailClosure") :
        contract.index("function Assert-WeatherLegacyBootstrapRetirementReceipt")
    ]

    assert "[IO.FileShare]::Read" in snapshot_helper
    assert "Get-WeatherIntegrationFileHandleIdentity" in snapshot_helper
    assert "$pathIdentity -cne $openedIdentity" in snapshot_helper
    assert "$closingIdentity -cne $openedIdentity" in snapshot_helper
    assert "Assert-WeatherIntegrationRegularPathAncestry" in snapshot_helper
    assert "$stream.Length -le 0" in snapshot_helper
    assert "$stream.Length -gt $MaximumBytes" in snapshot_helper
    assert "New-Object Text.UTF8Encoding($false, $true)" in snapshot_helper
    assert "$sha.ComputeHash($bytes)" in snapshot_helper
    assert "$text | ConvertFrom-Json -ErrorAction Stop" in snapshot_helper
    assert "Read-WeatherIntegrationEvidenceSnapshot" in manifest_reader
    assert "Read-WeatherIntegrationSharedJson" not in manifest_reader
    assert "Get-WeatherIntegrationFileSha256" not in manifest_reader
    assert "Read-WeatherIntegrationEvidenceSnapshot" in closure_reader
    assert "Assert-WeatherIntegrationRuntimeEvidenceNamespace" not in closure_reader
    assert "function Assert-WeatherIntegrationCanonicalAttemptRoot" in contract
    assert "function Assert-WeatherIntegrationCanonicalAttemptRoot" not in preparation_contract

    for path in (REGISTRAR, READINESS, ACTIVATOR, SUITE, MERGE):
        assert "Assert-WeatherIntegrationRuntimeEvidenceNamespace" in path.read_text(
            encoding="utf-8-sig"
        )
    assert "-RequireAttemptRoot -RequirePreparationRoot" in CREATOR.read_text(
        encoding="utf-8-sig"
    )


def test_evidence_snapshot_is_bounded_strict_utf8_and_reuses_one_buffer(
    tmp_path: Path,
) -> None:
    payload_bytes = b'{"value":7}'
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$validPath = Join-Path $env:WEATHER_EVIDENCE_ROOT 'valid.json'
$emptyPath = Join-Path $env:WEATHER_EVIDENCE_ROOT 'empty.json'
$invalidPath = Join-Path $env:WEATHER_EVIDENCE_ROOT 'invalid.json'
[IO.File]::WriteAllBytes($validPath, [Text.Encoding]::UTF8.GetBytes('{"value":7}'))
[IO.File]::WriteAllBytes($emptyPath, [byte[]]@())
[IO.File]::WriteAllBytes($invalidPath, [byte[]]@(0xff))
$snapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $validPath -MaximumBytes 64 -ContentType Json
if ([string]$snapshot.Sha256 -ne $env:WEATHER_EVIDENCE_SHA256 -or
    [string]$snapshot.Text -cne '{"value":7}' -or
    [int]$snapshot.Payload.value -ne 7 -or
    [int]$snapshot.Length -ne $snapshot.Bytes.Length) {
    throw 'single evidence snapshot did not retain matching bytes, text, payload, and SHA'
}
foreach ($rejection in @(
    [pscustomobject]@{ Path = $emptyPath; MaximumBytes = 64; ContentType = 'Json' },
    [pscustomobject]@{ Path = $invalidPath; MaximumBytes = 64; ContentType = 'Text' },
    [pscustomobject]@{ Path = $validPath; MaximumBytes = 3; ContentType = 'Bytes' }
)) {
    $accepted = $false
    try {
        Read-WeatherIntegrationEvidenceSnapshot -Path $rejection.Path -MaximumBytes $rejection.MaximumBytes -ContentType $rejection.ContentType | Out-Null
        $accepted = $true
    }
    catch { }
    if ($accepted) {
        throw 'empty, invalid UTF-8, or oversized evidence was accepted'
    }
}
$script:IdentityCall = 0
function Get-WeatherIntegrationFileHandleIdentity {
    param([IO.FileStream]$Stream, [string]$Label)
    $script:IdentityCall++
    if ($script:IdentityCall -eq 1) { return 'volume:old-file' }
    return 'volume:replacement-file'
}
$replacementAccepted = $false
try {
    Read-WeatherIntegrationEvidenceSnapshot `
        -Path $validPath -MaximumBytes 64 -ContentType Json | Out-Null
    $replacementAccepted = $true
}
catch { }
if ($replacementAccepted) {
    throw 'path replacement with a different file identity was accepted'
}
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
        WEATHER_EVIDENCE_ROOT=str(tmp_path),
        WEATHER_EVIDENCE_SHA256=hashlib.sha256(payload_bytes).hexdigest(),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_preparation_rejects_noncanonical_attempt_root_and_ambient_git_control(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    canonical_parent = repo_root / "data" / "integration_attempts" / "2026-08-26"
    canonical_parent.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-b", "master", str(repo_root)],
        check=True,
        capture_output=True,
        text=True,
    )
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
. $env:WEATHER_PREPARATION_CONTRACT
$canonical = Join-Path $env:WEATHER_REPO_ROOT `
    'data\integration_attempts\2026-08-26\attempt-a1'
Assert-WeatherIntegrationCanonicalAttemptRoot `
    -RepositoryRoot $env:WEATHER_REPO_ROOT `
    -AttemptRoot $canonical `
    -AttemptId 'attempt-a1' `
    -SuiteAtLocal ([datetime]'2026-08-26T00:40:00') | Out-Null
$wrongAccepted = $false
try {
    Assert-WeatherIntegrationCanonicalAttemptRoot `
        -RepositoryRoot $env:WEATHER_REPO_ROOT `
        -AttemptRoot (Join-Path $env:WEATHER_REPO_ROOT 'data\elsewhere\attempt-a1') `
        -AttemptId 'attempt-a1' `
        -SuiteAtLocal ([datetime]'2026-08-26T00:40:00') | Out-Null
    $wrongAccepted = $true
}
catch { }
$preparationRoot = $canonical + '.preparation'
New-Item -ItemType Directory -Path $canonical | Out-Null
New-Item -ItemType Directory -Path $preparationRoot | Out-Null
$runtimeContract = [pscustomobject]@{
    AttemptRoot = $canonical
    Manifest = [pscustomobject]@{
        schema = $script:WeatherIntegrationAttemptManifestSchema
        attempt_id = 'attempt-a1'
        repo_root = $env:WEATHER_REPO_ROOT
        schedule = [pscustomobject]@{
            suite_at_local = '2026-08-26T00:40:00'
        }
    }
}
$runtimeNamespace = Assert-WeatherIntegrationRuntimeEvidenceNamespace -AttemptContract $runtimeContract
if (-not [bool]$runtimeNamespace.Required) {
    throw 'v2 runtime namespace was not enforced'
}
$preparationBacking = $canonical + '.preparation-backing'
Move-Item -LiteralPath $preparationRoot -Destination $preparationBacking
New-Item -ItemType Junction -Path $preparationRoot -Target $preparationBacking | Out-Null
$preparationJunctionAccepted = $false
try {
    Assert-WeatherIntegrationRuntimeEvidenceNamespace -AttemptContract $runtimeContract | Out-Null
    $preparationJunctionAccepted = $true
}
catch { }
Remove-Item -LiteralPath $preparationRoot
Move-Item -LiteralPath $preparationBacking -Destination $preparationRoot
$dateRoot = Split-Path -Parent $canonical
$backingRoot = Join-Path $env:WEATHER_REPO_ROOT 'data\integration_attempts-backing'
Move-Item -LiteralPath $dateRoot -Destination $backingRoot
New-Item -ItemType Junction -Path $dateRoot -Target $backingRoot | Out-Null
$junctionAccepted = $false
try {
    Assert-WeatherIntegrationRuntimeEvidenceNamespace -AttemptContract $runtimeContract | Out-Null
    $junctionAccepted = $true
}
catch { }
$legacyContract = [pscustomobject]@{
    AttemptRoot = (Join-Path $env:WEATHER_REPO_ROOT 'legacy\missing')
    Manifest = [pscustomobject]@{
        schema = $script:WeatherIntegrationAttemptLegacyManifestSchema
    }
}
$legacyNamespace = Assert-WeatherIntegrationRuntimeEvidenceNamespace -AttemptContract $legacyContract
if ($preparationJunctionAccepted -or $junctionAccepted -or
    -not [bool]$legacyNamespace.Legacy) {
    throw 'runtime namespace accepted a junction ancestor or rejected v1 compatibility'
}
$priorGitDir = $env:GIT_DIR
$env:GIT_DIR = 'ambient-override'
$ambientAccepted = $false
try {
    Assert-WeatherIntegrationGitControlSafety `
        -RepositoryRoots @($env:WEATHER_REPO_ROOT) | Out-Null
    $ambientAccepted = $true
}
catch { }
finally { $env:GIT_DIR = $priorGitDir }
if ($wrongAccepted -or $ambientAccepted) {
    throw 'canonical attempt-root or ambient Git control guard failed'
}
'OK'
"""
    result = _powershell(
        command,
        WEATHER_ATTEMPT_CONTRACT=str(ATTEMPT_CONTRACT),
        WEATHER_PREPARATION_CONTRACT=str(PREPARATION_CONTRACT),
        WEATHER_REPO_ROOT=str(repo_root),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_expired_preparation_fails_before_git_or_scheduler_and_is_durable(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    attempt_parent = repo_root / "data" / "integration_attempts" / "2020-01-01"
    attempt_parent.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-b", "master", str(repo_root)],
        check=True,
        capture_output=True,
        text=True,
    )
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
        str(repo_root),
        "-AttemptRoot",
        str(attempt_root),
        "-AttemptId",
        "expired-a1",
        "-BranchRef",
        "origin/codex/expired-a1",
        "-WorktreeRoot",
        str(repo_root),
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
    paths = (
        PREPARER,
        READINESS,
        ACTIVATOR,
        REGISTRAR,
        SUITE,
        PREPARATION_CONTRACT,
        REMOTE_GIT,
        CREATOR,
        ATTEMPT_CONTRACT,
        OPS / "bounded_worktree_test_suite.ps1",
    )
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
