"""Feasibility has declared caps and no circular prior-measurement dependency."""

from copy import deepcopy
from datetime import timedelta
import os
from pathlib import Path
import subprocess

import pytest

from weather.operations.qualification import host_acceptance, measurement, records
from test_qualification_evidence import NOW, bundle


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def measurement_request(bundle, tmp_path):
    root, production, candidate = [tmp_path / name for name in ("measurement", "production", "candidate")]
    for path in (root, production, candidate):
        path.mkdir()
    placeholder = records.publish(root, "placeholder.json", {"test_only": True})
    plan = {"source": bundle.values["review"]["source"], "scope": "control_plane", "host_id": "a" * 64,
        "principal_id": "b" * 64, "not_before": NOW.isoformat().replace("+00:00", "Z"),
        "deadline": (NOW + timedelta(seconds=1920)).isoformat().replace("+00:00", "Z"),
        "configuration": placeholder, "environment": placeholder, "audit": None,
        "maximums": {name: {"seconds": seconds, "commit_bytes": 512 * 1024**2,
            "working_set_bytes": 512 * 1024**2, "scratch_bytes": 1024**2, "read_bytes": 1024**2}
            for name, seconds in (("probes", 478), ("audit", 1200), ("metadata", 120), ("teardown", 120))}}
    value = {"schema": "qualification_measurement_request_v2", "measurement_id": "fixture", "repo_root": str(production),
        "candidate": str(candidate), "qualification": {"root": str(bundle.root), "policy": bundle.refs["policy"],
            "review": bundle.refs["review"], "certificate": bundle.refs["certificate"], "import": placeholder, "revocations": placeholder},
        "control": {"root": str(root / "control"), "closure": placeholder, "git_policy": placeholder},
        "plan": plan, "task": {"name": "WeatherQualificationMeasure_fixture", "user_sid": "S-1-5-21-1"}}
    return root, value


def test_measurement_context_accepts_declared_caps_without_manufactured_prior_samples(measurement_request):
    root, value = measurement_request
    result = measurement.context(value, root, now=NOW)
    assert "measurements" not in result["host_plan"]
    assert "integration_eligible" not in result
    assert result["host_plan"]["scope"] == "control_plane"
    assert set(result["host_plan"]["maximums"]) == set(host_acceptance.PHASES)


@pytest.mark.parametrize("fault", ["prior-sample", "source", "scope", "missing-audit", "wrong-task", "memory", "time", "reserve", "early", "late", "root"])
def test_measurement_preparation_cannot_select_an_unbounded_or_different_execution(measurement_request, fault):
    root, original = measurement_request
    value = deepcopy(original)
    now = NOW
    if fault == "prior-sample": value["plan"]["measurements"] = value["plan"]["configuration"]
    elif fault == "source": value["plan"]["source"]["commit"] = "f" * 40
    elif fault == "scope": value["plan"]["scope"] = "unrestricted"
    elif fault == "missing-audit": value["plan"]["scope"] = "reliability_current_inputs"
    elif fault == "wrong-task": value["task"]["name"] += "other"
    elif fault == "memory": value["plan"]["maximums"]["probes"]["commit_bytes"] += 1
    elif fault == "time": value["plan"]["maximums"]["probes"]["seconds"] = 481
    elif fault == "reserve": value["plan"]["maximums"]["probes"]["seconds"] = 480
    elif fault == "early": now -= timedelta(seconds=1)
    elif fault == "late": now += timedelta(seconds=1920)
    else: value["repo_root"] = str(root)
    with pytest.raises(ValueError):
        measurement.context(value, root, now=now)


@pytest.mark.skipif(os.name != "nt", reason="native Windows measurement invocation refusal")
def test_measurement_actual_native_logon_refuses_an_ordinary_test_process(tmp_path):
    script = tmp_path / "native.ps1"
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    script.write_text("$ErrorActionPreference='Stop'\n$root=" + quote(ROOT) + r'''
. (Join-Path $root 'scripts/ops/integration_attempt_contract.ps1')
. (Join-Path $root 'scripts/ops/workload_admission.ps1')
. (Join-Path $root 'scripts/ops/qualification_host_identity.ps1')
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'scripts/ops/measure_split_qualification.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors | Out-String)}
$function=$ast.Find({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Assert-WeatherMeasurementInvocation'},$true)
Invoke-Expression $function.Extent.Text
$identity=Get-WeatherQualificationCurrentLogon
if($identity.logon_type -eq 4 -and -not $identity.elevated){throw 'fixture must run outside a real S4U measurement task'}
$request=[pscustomobject]@{plan=[pscustomobject]@{host_id=(Get-WeatherExecutionHostId);principal_id=(Get-WeatherExecutionPrincipalId)}
    task=[pscustomobject]@{user_sid=$identity.sid}}
$refused=$false
try{Assert-WeatherMeasurementInvocation -Request $request -Path 'C:\fixture.json' -Sha256 ('a'*64) -Script 'C:\fixture.ps1'}
catch{if($_.Exception.Message -notlike '*exact unelevated primary batch token*'){throw};$refused=$true}
if(-not $refused){throw 'ordinary process became S4U measurement authority'}
''', encoding="utf-8")
    executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-File", str(script)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
