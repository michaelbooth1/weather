"""The first-landing probe adapter cannot mint acceptance or broaden its scope."""

from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from weather.operations.qualification import bootstrap_probe, records
from test_qualification_evidence import NOW, bundle


ROOT = Path(__file__).resolve().parents[2]
PS = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


@pytest.fixture
def envelope(bundle, tmp_path):
    evidence, production, candidate, control = [tmp_path / name for name in ("probe-evidence", "production", "candidate", "adapter")]
    for path in (evidence, production, candidate, control):
        path.mkdir()
    placeholder = records.publish(evidence, "placeholder.json", {"fixture_only": True})
    paths = sorted({*bootstrap_probe.NATIVE_HELPERS,
        "scripts/ops/bootstrap_qualification_probe.ps1", "scripts/ops/qualification_bootstrap_probe_child.ps1",
        "scripts/ops/qualification_bootstrap_probe_control.py"})
    closure = records.publish(evidence, "closure.json", {"schema": "qualification_runtime_files_v2", "files": [
        {"path": path, "sha256": "d" * 64, "size": 1, "mode": "100644"} for path in paths]})
    value = {"schema": bootstrap_probe.SCHEMA, "bootstrap_id": "fixture", "operation": "fixed_control_plane_probes",
        "repo_root": str(production), "candidate": str(candidate), "evidence_root": str(evidence),
        "baseline": bundle.values["review"]["source"]["baseline"], "source": bundle.values["review"]["source"],
        "qualification": {"root": str(bundle.root), "policy": bundle.refs["policy"], "review": bundle.refs["review"]},
        "control": {"root": str(control), "closure": closure, "git_policy": placeholder},
        "environment": placeholder, "configuration": placeholder, "review_evidence": placeholder,
        "host": {"host_id": "a" * 64, "principal_id": "b" * 64, "user_sid": "S-1-5-21-1"},
        "task": {"name": "WeatherQualificationBootstrapProbe_fixture"},
        "not_before": records.utc_now(), "deadline": records.utc_now(),
        "limits": {"commit_bytes": 512 * 1024**2, "working_set_bytes": 512 * 1024**2,
            "scratch_bytes": 64 * 1024**2, "read_bytes": 2 * 1024**3, "teardown_seconds": 30},
        "adopted_helpers": {"schema": "qualification_runtime_files_v2", "files": [
            {"path": name, "sha256": "e" * 64, "size": 1, "mode": "100644"} for name in bootstrap_probe.ADOPTED_HELPERS]},
        "integration_eligible": False, "full_suite_replacement": False}
    value["not_before"] = NOW.isoformat().replace("+00:00", "Z")
    value["deadline"] = (NOW + timedelta(seconds=480)).isoformat().replace("+00:00", "Z")
    return evidence, value


def test_probe_envelope_consumes_direct_review_without_a_self_issued_certificate(envelope):
    root, value = envelope
    checked = bootstrap_probe.context(value, root, now=NOW)
    assert checked["envelope"]["integration_eligible"] is False
    assert checked["envelope"]["full_suite_replacement"] is False
    assert "certificate" not in checked["manifest"]["qualification"]
    assert checked["review"]["scope"] == "control_plane"


@pytest.mark.parametrize("fault", [
    "command", "operation", "merge", "legacy-pass", "authority-string", "certificate", "source", "baseline",
    "host", "sid", "task", "id", "long-window", "execution-reserve", "early", "expired",
    "memory", "working-set", "scratch", "reads", "boolean-limit", "helper", "helper-reorder", "closure",
    "evidence-location", "evidence-in-production", "adapter-in-candidate", "same-source"])
def test_probe_envelope_rejects_unsafe_or_changed_bindings(envelope, fault):
    root, original = envelope
    value = deepcopy(original)
    now = NOW
    if fault == "command": value["command"] = ["python", "-m", "anything"]
    elif fault == "operation": value["operation"] = "current_settlement_audit"
    elif fault == "merge": value["integration_eligible"] = True
    elif fault == "legacy-pass": value["full_suite_replacement"] = True
    elif fault == "authority-string": value["integration_eligible"] = "false"
    elif fault == "certificate": value["qualification"]["certificate"] = value["environment"]
    elif fault == "source": value["source"]["commit"] = "f" * 40
    elif fault == "baseline": value["baseline"] = "f" * 40
    elif fault == "host": value["host"]["host_id"] = "other"
    elif fault == "sid": value["host"]["user_sid"] = "current-user"
    elif fault == "task": value["task"]["name"] += "other"
    elif fault == "id": value["bootstrap_id"] = "../other"
    elif fault == "long-window": value["deadline"] = (NOW + timedelta(seconds=481)).isoformat().replace("+00:00", "Z")
    elif fault == "execution-reserve": value["deadline"] = (NOW + timedelta(seconds=35)).isoformat().replace("+00:00", "Z")
    elif fault == "early": now -= timedelta(seconds=1)
    elif fault == "expired": now += timedelta(seconds=480)
    elif fault == "memory": value["limits"]["commit_bytes"] += 1
    elif fault == "working-set": value["limits"]["working_set_bytes"] += 1
    elif fault == "scratch": value["limits"]["scratch_bytes"] += 1
    elif fault == "reads": value["limits"]["read_bytes"] += 1
    elif fault == "boolean-limit": value["limits"]["teardown_seconds"] = True
    elif fault == "helper": value["adopted_helpers"]["files"][0]["path"] = "scripts/ops/another.ps1"
    elif fault == "helper-reorder": value["adopted_helpers"]["files"].reverse()
    elif fault == "closure": value["control"]["closure"] = value["environment"]
    elif fault == "evidence-location": value["evidence_root"] = value["candidate"]
    elif fault == "evidence-in-production": value["repo_root"] = str(root)
    elif fault == "adapter-in-candidate": value["control"]["root"] = value["candidate"]
    else: value["candidate"] = value["repo_root"]
    with pytest.raises(ValueError):
        bootstrap_probe.context(value, root, now=now)


def test_candidate_may_be_an_existing_registered_worktree_below_production(envelope):
    root, value = envelope
    candidate = Path(value["repo_root"]) / "scratch" / "worktree"
    candidate.mkdir(parents=True)
    value["candidate"] = str(candidate)
    assert bootstrap_probe.context(value, root, now=NOW)["manifest"]["worktree_root"] == str(candidate)


def test_request_bytes_fail_before_probe_execution(envelope, monkeypatch):
    root, value = envelope
    ref = records.publish(root, "envelope.json", value)
    calls = []
    monkeypatch.setattr(bootstrap_probe, "verify_inputs", lambda *_: calls.append("verify"))
    with pytest.raises(ValueError, match="envelope changed"):
        bootstrap_probe.run(root / ref["path"], "f" * 64)
    assert calls == []


@pytest.mark.skipif(os.name != "nt", reason="actual Windows parser and file-sharing semantics")
def test_native_adapter_files_parse_without_executing_an_entrypoint(tmp_path):
    files = ["bootstrap_qualification_probe.ps1", "qualification_bootstrap_probe_contract.ps1", "qualification_bootstrap_probe_child.ps1"]
    paths = ",".join("'" + str(ROOT / "scripts/ops" / name).replace("'", "''") + "'" for name in files)
    script = tmp_path / "parse.ps1"
    script.write_text("$ErrorActionPreference='Stop'\nforeach($path in @(" + paths + ")) {\n"
        "$tokens=$null;$errors=$null\n"
        "[void][Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors)\n"
        "if($errors.Count){throw ($errors | Out-String)}\n}\n", encoding="utf-8")
    result = subprocess.run([str(PS), "-NoProfile", "-NonInteractive", "-File", str(script)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.name != "nt", reason="actual Windows adapter startup refusal")
@pytest.mark.parametrize("wrong", ["adapter", "envelope"])
def test_native_entrypoint_refuses_changed_bytes_without_creating_attempt_state(tmp_path, wrong):
    request = tmp_path / "envelope.json"
    request.write_text('{"schema":"fixture-only"}', encoding="utf-8")
    adapter = ROOT / "scripts/ops/bootstrap_qualification_probe.ps1"
    adapter_sha = hashlib.sha256(adapter.read_bytes()).hexdigest()
    envelope_sha = hashlib.sha256(request.read_bytes()).hexdigest()
    if wrong == "adapter": adapter_sha = "f" * 64
    else: envelope_sha = "f" * 64
    result = subprocess.run([str(PS), "-NoProfile", "-NonInteractive", "-File", str(adapter),
        "-EnvelopePath", str(request), "-ExpectedEnvelopeSha256", envelope_sha,
        "-ExpectedAdapterSha256", adapter_sha], capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "pinned bytes differ" in result.stdout + result.stderr
    assert sorted(path.name for path in tmp_path.iterdir()) == ["envelope.json"]


@pytest.mark.skipif(os.name != "nt", reason="native sharing lock prevents replacement during an attempt")
def test_native_pinned_file_is_locked_and_detects_drift(tmp_path):
    target = tmp_path / "pinned.bin"
    target.write_bytes(b"reviewed bytes")
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    driver = tmp_path / "pin.ps1"
    driver.write_text("$ErrorActionPreference='Stop'\n" +
        "$tokens=$null;$errors=$null\n$ast=[Management.Automation.Language.Parser]::ParseFile(" +
        quote(ROOT / "scripts/ops/bootstrap_qualification_probe.ps1") + ",[ref]$tokens,[ref]$errors)\n" +
        "$function=$ast.Find({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and "
        "$node.Name -ceq 'Open-WeatherBootstrapPinnedFile'},$true)\nInvoke-Expression $function.Extent.Text\n" +
        "$path=" + quote(target) + "\n$sha=" + quote(hashlib.sha256(target.read_bytes()).hexdigest()) + "\n" +
        "$handle=Open-WeatherBootstrapPinnedFile $path $sha 14\n"
        "try {$refused=$false;try {[IO.File]::WriteAllText($path,'changed')}catch{$refused=$true}\n"
        "if(-not $refused){throw 'pinned bytes were writable'}}finally{$handle.Dispose()}\n"
        "[IO.File]::WriteAllText($path,'modified bytes')\n$refused=$false\n"
        "try {$unexpected=Open-WeatherBootstrapPinnedFile $path $sha 14;$unexpected.Dispose()}catch{$refused=$true}\n"
        "if(-not $refused){throw 'changed bytes were accepted'}\n", encoding="utf-8")
    result = subprocess.run([str(PS), "-NoProfile", "-NonInteractive", "-File", str(driver)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_spent_observation_namespace_never_runs_probes(envelope, monkeypatch):
    root, value = envelope
    output = root / "probe-work" / "observations"
    output.mkdir(parents=True)
    (output / "retained.json").write_text("{}", encoding="utf-8")
    ref = records.publish(root, "envelope.json", value)
    checked = bootstrap_probe.context(value, root, now=NOW)
    monkeypatch.setattr(bootstrap_probe, "context", lambda *_: checked)
    monkeypatch.setattr(bootstrap_probe, "verify_inputs", lambda *_: ({}, {}))
    def forbidden(*_):
        pytest.fail("spent namespace ran a probe")
    monkeypatch.setattr(bootstrap_probe, "_probes", forbidden)
    with pytest.raises(ValueError, match="namespace is spent"):
        bootstrap_probe.run(root / ref["path"], ref["sha256"])
    assert (output / "retained.json").read_text() == "{}"


@pytest.mark.skipif(os.name != "nt", reason="native closed inventory, readback and durable claim boundaries")
def test_native_closed_tree_scratch_result_and_single_use_boundaries(tmp_path):
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    driver = tmp_path / "boundaries.ps1"
    driver.write_text(
        "$ErrorActionPreference='Stop'\n. " +
        quote(ROOT / "scripts/ops/qualification_bootstrap_probe_contract.ps1") + "\n$root=" + quote(tmp_path) + "\n" +
        r'''
function MustRefuse([scriptblock]$Action) {
    $refused=$false;try {& $Action}catch{$refused=$true}
    if(-not $refused){throw 'unsafe boundary was accepted'}
}
$tree=Join-Path $root 'tree';[void][IO.Directory]::CreateDirectory($tree)
[IO.File]::WriteAllText((Join-Path $tree 'module.py'),'reviewed')
$inventory=[pscustomobject]@{schema='qualification_runtime_files_v2';files=@([pscustomobject]@{path='module.py'})}
Assert-WeatherBootstrapProbeTree $tree $inventory -SourceOnly $true
[IO.File]::WriteAllText((Join-Path $tree 'module.pyc'),'injected')
MustRefuse {Assert-WeatherBootstrapProbeTree $tree $inventory -SourceOnly $true}
$inventory.files+=([pscustomobject]@{path='module.pyc'})
MustRefuse {Assert-WeatherBootstrapProbeTree $tree $inventory -SourceOnly $true}
MustRefuse {Assert-WeatherBootstrapProbeTree $tree $inventory -Exclusions @('Lib')}
MustRefuse {Get-WeatherBootstrapProbeScratchBytes $tree 1}
$claim=Join-Path $root 'use.json'
Write-WeatherBootstrapProbeRecord $claim @{sentinel='retained'}
MustRefuse {Write-WeatherBootstrapProbeRecord $claim @{sentinel='replaced'}}
if((Get-Content -Raw -LiteralPath $claim | ConvertFrom-Json).sentinel -cne 'retained'){throw 'claim replaced'}
$sha='a'*64
$value=[pscustomobject]@{
    schema='qualification_bootstrap_probe_native_result_v1';envelope_sha256=$sha;integration_eligible=$false;native_read_bytes=1
    native=[pscustomobject]@{completed=$true;teardown_proved=$true;failure=$null;exit_code=0}
}
Assert-WeatherBootstrapProbeNativeResult $value $sha 10
foreach($name in @('completed','teardown_proved')){
    $value.native.$name='true'
    MustRefuse {Assert-WeatherBootstrapProbeNativeResult $value $sha 10}
    $value.native.$name=$true
}
$value.native_read_bytes=$true
MustRefuse {Assert-WeatherBootstrapProbeNativeResult $value $sha 10}
$value.native_read_bytes=11
MustRefuse {Assert-WeatherBootstrapProbeNativeResult $value $sha 10}
$value.native_read_bytes=1;$value.native.failure='retained refusal'
MustRefuse {Assert-WeatherBootstrapProbeNativeResult $value $sha 10}
''', encoding="utf-8")
    result = subprocess.run([str(PS), "-NoProfile", "-NonInteractive", "-File", str(driver)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
