import json
import os
import subprocess
from pathlib import Path

from weather.operations.daily_refresh import build_parser
from weather.operations.producer_provenance import (
    _windows_argv,
    decode_scheduler_action_arguments,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "scripts" / "ops" / "daily_refresh.ps1"
REGISTER = REPO_ROOT / "scripts" / "ops" / "register_daily_refresh.ps1"
CONTRACT = REPO_ROOT / "scripts" / "ops" / "daily_refresh_contract.ps1"
JOB_HELPER = REPO_ROOT / "scripts" / "ops" / "windows_kill_on_close_job.ps1"
SHARED_CONTRACT = REPO_ROOT / "scripts" / "ops" / "training_window_contract.ps1"


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _expected_action_tokens(
    stage,
    task_name,
    *,
    provenance_only,
    evidence_b64,
):
    tokens = [
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        r"C:\Repo Root\scripts\ops\daily_refresh.ps1",
        "-RepoRoot",
        r"C:\Repo Root",
        "-Stage",
        stage,
        "-SchedulerTaskName",
        task_name,
        "-EvidenceTaskName",
        "WeatherEveningEvidenceRefresh",
        "-SchedulerTaskExecutable",
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        "-ContinueOnError",
    ]
    if provenance_only:
        return [*tokens, "-ProvenanceOnly"]
    return [*tokens, "-ProductionEvidenceArgumentsB64", evidence_b64]


def _expected_child_tokens(
    stage,
    task_name,
    action_contract,
    *,
    provenance_only,
    evidence_tokens,
):
    tokens = [
        "-m",
        "weather.operations.daily_refresh",
        "run",
        "--fail-on-variant-evidence-alert",
        "--continue-on-error",
        "--stage",
        stage,
    ]
    if stage == "settlement":
        tokens += ["--evidence-task-name", "WeatherEveningEvidenceRefresh"]
        producer_sla = "14400"
    else:
        tokens += [
            "--status-out",
            r"data\backtest\daily_refresh_evidence_status.json",
            "--report-out",
            r"data\backtest\daily_refresh_evidence_report.md",
        ]
        producer_sla = "28800"
    tokens += [
        "--scheduler-invocation-topology",
        "delegated_child",
        "--scheduler-task-name",
        task_name,
        "--scheduler-task-executable",
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        "--scheduler-task-working-directory",
        r"C:\Repo Root",
        "--scheduler-task-action-arguments-b64",
        action_contract,
        "--scheduler-process-executable",
        r"C:\Repo Root\venv\Scripts\pythonw.exe",
        "--scheduler-correlation-seconds",
        "300",
        "--producer-sla-seconds",
        producer_sla,
        "--active-release-pointer",
        r"C:\Repo Root\artifacts\releases\current_release.json",
        "--releases-root",
        r"C:\Repo Root\artifacts\releases",
        "--repo-root",
        r"C:\Repo Root",
    ]
    return tokens if provenance_only else [*tokens, *evidence_tokens]


def test_daily_refresh_scripts_share_exact_delegated_child_contract():
    wrapper = WRAPPER.read_text(encoding="utf-8-sig")
    registration = REGISTER.read_text(encoding="utf-8-sig")
    contract = CONTRACT.read_text(encoding="utf-8-sig")

    assert "Get-DailyRefreshTaskActionTokens" in contract
    assert "training_window_contract.ps1" in contract
    assert "Get-DailyRefreshChildTokens" in contract
    assert "ConvertTo-ScheduledTaskArgumentString" in registration
    assert "ConvertTo-ScheduledTaskArgumentString" in wrapper
    assert "ConvertTo-SchedulerArgumentContract" in registration
    assert "ConvertTo-SchedulerArgumentContract" in wrapper
    assert "Get-DailyRefreshChildTokens" in wrapper
    assert "Get-DailyRefreshTaskActionTokens" in registration
    assert "Get-DailyRefreshTaskActionTokens" in wrapper
    assert "New-WeatherKillOnCloseJob" in wrapper
    assert "Start-WeatherProcessInJob" in wrapper
    assert "-Execute $PowerShellExecutable" in registration
    assert "-Argument $stageAArguments" in registration
    assert "-Argument $stageBArguments" in registration
    assert '"--scheduler-invocation-topology", "delegated_child"' in contract
    assert '"--scheduler-task-action-arguments-b64"' in contract
    assert '"--scheduler-process-executable", $SchedulerProcessExecutable' in contract
    assert '"--scheduler-correlation-seconds", "300"' in contract
    assert '"--active-release-pointer", $releasePointer' in contract
    assert '"--releases-root", $releasesRoot' in contract
    assert '"--repo-root", $RepoRoot' in contract
    assert "ConvertFrom-DailyRefreshProductionEvidenceArguments" in contract
    assert 'childParameters["ProductionEvidenceArguments"]' in wrapper
    assert "exit $childExitCode" in wrapper
    assert 'DefaultParameterSetName = "Full"' in registration
    assert 'ParameterSetName = "Full"' in registration
    assert 'ParameterSetName = "ProvenanceOnly"' in registration


def test_daily_refresh_child_tree_is_owned_by_a_kill_on_close_job():
    helper = JOB_HELPER.read_text(encoding="utf-8-sig")
    wrapper = WRAPPER.read_text(encoding="utf-8-sig")

    assert "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE" in helper
    assert "AssignProcessToJobObject" in helper
    assert "CREATE_SUSPENDED" in helper
    assert "ResumeThread" in helper
    assert "StartAssigned" in helper
    assert "Start-Process" not in helper
    assert "Add-WeatherProcessToJob" not in helper
    assert "public void Assign(Process process)" not in helper
    assert "IntPtr managedHandle = managedProcess.Handle" in helper
    assert "CreateJobObject" in helper
    assert "CloseHandle" in helper
    assert "windows_kill_on_close_job.ps1" in wrapper
    assert wrapper.index("New-WeatherKillOnCloseJob") < wrapper.index("Start-WeatherProcessInJob")
    assert wrapper.index("Start-WeatherProcessInJob") < wrapper.index("$child.WaitForExit()")


def test_daily_refresh_is_serialized_and_cannot_cross_the_graded_window():
    wrapper = WRAPPER.read_text(encoding="utf-8-sig")

    assert "workload_admission.ps1" in wrapper
    assert 'Enter-WeatherHeavyWorkloadLease -RepoRoot $RepoRoot -Workload "daily_refresh_$Stage"' in wrapper
    assert "$localMinute -ge 715 -or $localMinute -lt 30" in wrapper
    assert "$minute -ge 715 -or $minute -lt 30" in wrapper
    assert "Closing the kill-on-close Job" in wrapper
    assert "$childExitCode = 75" in wrapper
    assert "Exit-WeatherHeavyWorkloadLease" in wrapper


def test_daily_refresh_parser_accepts_delegated_child_contract():
    args = build_parser().parse_args([
        "run",
        "--stage",
        "settlement",
        "--scheduler-invocation-topology",
        "delegated_child",
        "--scheduler-task-name",
        "WeatherDailySettlementPromotionRefresh",
        "--scheduler-task-executable",
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        "--scheduler-task-working-directory",
        r"C:\Repo Root",
        "--scheduler-task-action-arguments-b64",
        "WyItTm9Qcm9maWxlIl0=",
        "--scheduler-process-executable",
        r"C:\Repo Root\venv\Scripts\pythonw.exe",
        "--scheduler-correlation-seconds",
        "300",
    ])

    assert args.scheduler_invocation_topology == "delegated_child"
    assert args.scheduler_task_name == "WeatherDailySettlementPromotionRefresh"
    assert args.scheduler_task_action_arguments_b64 == "WyItTm9Qcm9maWxlIl0="
    assert args.scheduler_process_executable.endswith(r"venv\Scripts\pythonw.exe")
    assert args.scheduler_correlation_seconds == 300.0


def test_daily_refresh_powershell_scripts_parse_without_execution():
    if os.name != "nt":
        return
    env = os.environ.copy()
    env["WEATHER_DAILY_WRAPPER"] = str(WRAPPER)
    env["WEATHER_DAILY_REGISTER"] = str(REGISTER)
    env["WEATHER_DAILY_CONTRACT"] = str(CONTRACT)
    env["WEATHER_DAILY_JOB_HELPER"] = str(JOB_HELPER)
    script = r"""
$ErrorActionPreference = 'Stop'
$paths = @(
    $env:WEATHER_DAILY_WRAPPER,
    $env:WEATHER_DAILY_REGISTER,
    $env:WEATHER_DAILY_CONTRACT,
    $env:WEATHER_DAILY_JOB_HELPER
)
$results = foreach ($path in $paths) {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        $path,
        [ref]$tokens,
        [ref]$errors
    )
    [pscustomobject]@{
        path = $path
        errors = @($errors | ForEach-Object { $_.Message })
    }
}
$results | ConvertTo-Json -Depth 4 -Compress
"""
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    assert len(rows) == 4
    assert all(row["errors"] == [] for row in rows)


def test_daily_refresh_action_tokens_and_full_payload_round_trip():
    if os.name != "nt":
        return
    env = os.environ.copy()
    env["WEATHER_DAILY_CONTRACT"] = str(CONTRACT)
    env["WEATHER_DAILY_REGISTER"] = str(REGISTER)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_DAILY_CONTRACT
$repo = 'C:\Repo Root'
$wrapper = 'C:\Repo Root\scripts\ops\daily_refresh.ps1'
$powerShell = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$evidenceTokens = @(
    '--fail-on-production-readiness-block',
    '--captured-input-parity-served', 'C:\Evidence Root\served.json',
    '--captured-input-parity-replay', 'C:\Evidence Root\replay.json',
    '--production-readiness-served-artifact', 'model=C:\Artifacts Root\model.pkl',
    '--production-readiness-served-route', 'C:\Artifacts Root\route.json'
)
$evidenceB64 = ConvertTo-SchedulerArgumentContract -Tokens $evidenceTokens
function New-DailyContractCase {
    param(
        [string]$Name,
        [string]$Stage,
        [string]$TaskName,
        [switch]$ProvenanceOnly
    )
    $actionParameters = @{
        RepoRoot = $repo
        ScriptPath = $wrapper
        Stage = $Stage
        SchedulerTaskName = $TaskName
        EvidenceTaskName = 'WeatherEveningEvidenceRefresh'
        SchedulerTaskExecutable = $powerShell
        ContinueOnError = $true
    }
    if ($ProvenanceOnly) {
        $actionParameters['ProvenanceOnly'] = $true
    } else {
        $actionParameters['ProductionEvidenceArgumentsB64'] = $evidenceB64
    }
    $action = @(Get-DailyRefreshTaskActionTokens @actionParameters)
    $actionContract = ConvertTo-SchedulerArgumentContract -Tokens $action
    $childParameters = @{
        RepoRoot = $repo
        Stage = $Stage
        SchedulerTaskName = $TaskName
        EvidenceTaskName = 'WeatherEveningEvidenceRefresh'
        SchedulerTaskExecutable = $powerShell
        SchedulerTaskActionArgumentsB64 = $actionContract
        SchedulerProcessExecutable = 'C:\Repo Root\venv\Scripts\pythonw.exe'
        ContinueOnError = $true
    }
    if ($ProvenanceOnly) {
        $childParameters['ProvenanceOnly'] = $true
    } else {
        $childParameters['ProductionEvidenceArguments'] = $evidenceTokens
    }
    [pscustomobject]@{
        name = $Name
        tokens = $action
        arguments = ConvertTo-ScheduledTaskArgumentString -Tokens $action
        contract = $actionContract
        child_tokens = @(Get-DailyRefreshChildTokens @childParameters)
    }
}
$cases = @(
    New-DailyContractCase `
        -Name 'settlement_provenance_only' `
        -Stage settlement `
        -TaskName WeatherDailySettlementPromotionRefresh `
        -ProvenanceOnly
    New-DailyContractCase `
        -Name 'settlement_full' `
        -Stage settlement `
        -TaskName WeatherDailySettlementPromotionRefresh
    New-DailyContractCase `
        -Name 'evidence_provenance_only' `
        -Stage evidence `
        -TaskName WeatherEveningEvidenceRefresh `
        -ProvenanceOnly
    New-DailyContractCase `
        -Name 'evidence_full' `
        -Stage evidence `
        -TaskName WeatherEveningEvidenceRefresh
)
$command = Get-Command -Name $env:WEATHER_DAILY_REGISTER
$parameterSets = @($command.ParameterSets | ForEach-Object {
    [pscustomobject]@{
        name = $_.Name
        mandatory = @($_.Parameters | Where-Object {
            $_.IsMandatory
        } | ForEach-Object {
            $_.Name
        })
    }
})
[pscustomobject]@{
    cases = $cases
    evidence_b64 = $evidenceB64
    evidence_tokens = $evidenceTokens
    decoded_evidence_tokens = @(
        ConvertFrom-DailyRefreshProductionEvidenceArguments -ArgumentsB64 $evidenceB64
    )
    parameter_sets = $parameterSets
} | ConvertTo-Json -Depth 8 -Compress
"""
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    cases = {row["name"]: row for row in payload["cases"]}
    expected_cases = {
        "settlement_provenance_only": (
            "settlement",
            "WeatherDailySettlementPromotionRefresh",
            True,
        ),
        "settlement_full": (
            "settlement",
            "WeatherDailySettlementPromotionRefresh",
            False,
        ),
        "evidence_provenance_only": (
            "evidence",
            "WeatherEveningEvidenceRefresh",
            True,
        ),
        "evidence_full": (
            "evidence",
            "WeatherEveningEvidenceRefresh",
            False,
        ),
    }
    assert set(cases) == set(expected_cases)
    for name, (stage, task_name, provenance_only) in expected_cases.items():
        row = cases[name]
        assert row["tokens"] == _expected_action_tokens(
            stage,
            task_name,
            provenance_only=provenance_only,
            evidence_b64=payload["evidence_b64"],
        )
        assert _windows_argv(row["arguments"]) == row["tokens"]
        assert decode_scheduler_action_arguments(row["contract"]) == row["tokens"]
        assert row["child_tokens"] == _expected_child_tokens(
            stage,
            task_name,
            row["contract"],
            provenance_only=provenance_only,
            evidence_tokens=payload["evidence_tokens"],
        )
    assert payload["decoded_evidence_tokens"] == payload["evidence_tokens"]

    parameter_sets = {
        row["name"]: set(_as_list(row.get("mandatory")))
        for row in payload["parameter_sets"]
    }
    assert parameter_sets["Full"] == {
        "CapturedInputParityServed",
        "CapturedInputParityReplay",
        "ProductionReadinessServedArtifact",
        "ProductionReadinessServedRoute",
    }
    assert parameter_sets["ProvenanceOnly"] == {"ProvenanceOnly"}
