"""Native arming/publication failures cannot create reusable authority."""

import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows arming and durable rename")


def invoke(tmp_path, body, *, check=True):
    literal = lambda value: "'" + str(value).replace("'", "''") + "'"
    path = tmp_path / "invoke.ps1"
    path.write_text("$ErrorActionPreference='Stop'\n$root=" + literal(ROOT) + "\n$fixture=" + literal(tmp_path) + "\n"
        ". (Join-Path $root 'scripts/ops/integration_attempt_contract.ps1')\n"
        ". (Join-Path $root 'scripts/ops/qualification_attempt_contract.ps1')\n"
        ". (Join-Path $root 'scripts/ops/qualification_arming_contract.ps1')\n" + body, encoding="utf-8")
    exe = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    args = [str(exe), "-NoProfile", "-NonInteractive", "-File", str(path)]
    if not check:
        return args
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def values():
    ref = lambda digit: {"sha256": digit * 64}
    state = {"Contract": {"ManifestSha256": "1" * 64, "Manifest": {
        "host": ref("2"), "qualification": {"certificate": ref("3"), "import": ref("4")}}},
        "Plan": {"configuration": ref("5"), "environment": ref("6")},
        "Measurements": {"phases": {"metadata": {"maximum": {"seconds": 120, "commit_bytes": 1000, "working_set_bytes": 900}}}},
        "Policy": {"host": {"minimum_disk_bytes": 10000}}}
    proof = {"schema": "qualification_arming_proof_v2", "manifest_sha256": "1" * 64,
        "host_plan_sha256": "2" * 64, "configuration_sha256": "5" * 64, "environment_sha256": "6" * 64,
        "certificate_sha256": "3" * 64, "import_sha256": "4" * 64,
        "validated_at": "2026-09-14T12:00:00Z", "latest_merge": "2026-09-15T08:00:00Z",
        "signature": {"certificate_sha256": "3" * 64, "verified_output_sha256": "7" * 64,
                      "native_parent_completion_required": True, "integration_eligible": False},
        "native_parent_completion_required": True, "integration_eligible": False}
    native = {"completed": True, "teardown_proved": True, "exit_code": 0, "failure": None,
        "elapsed_ms": 1000, "peak_private_bytes": 500, "native_peak_commit_bytes": 600,
        "peak_working_set_bytes": 500, "maximum_sample_gap_ms": 100, "resource_samples": 10,
        "system_commit_basis_points": 6000, "minimum_disk_bytes": 20000}
    return {"state": state, "proof": proof, "native": native}


@pytest.mark.parametrize("case", ["valid", "manifest", "certificate", "configuration", "import", "forged-signature",
    "incomplete", "children", "memory", "rss", "system", "disk", "time", "missing-samples", "gap", "exit", "string-bool"])
def test_actual_arming_proof_rejects_substitution_and_failed_native_bounds(tmp_path, case):
    value = values()
    if case in {"manifest", "certificate", "configuration", "import"}:
        value["proof"][case + "_sha256"] = "a" * 64
    elif case == "forged-signature":
        value["proof"]["signature"]["certificate_sha256"] = "a" * 64
    elif case != "valid":
        key, bad = {"incomplete": ("completed", False), "children": ("teardown_proved", False),
            "memory": ("native_peak_commit_bytes", 1001), "rss": ("peak_working_set_bytes", 901),
            "system": ("system_commit_basis_points", 6601), "disk": ("minimum_disk_bytes", 9999),
            "time": ("elapsed_ms", 120001), "missing-samples": ("resource_samples", 0),
            "gap": ("maximum_sample_gap_ms", 1001), "exit": ("exit_code", 1), "string-bool": ("completed", "true")}[case]
        value["native"][key] = bad
    (tmp_path / "fixture.json").write_text(json.dumps(value), encoding="utf-8")
    invoke(tmp_path, r'''
$value=Get-Content -LiteralPath (Join-Path $fixture 'fixture.json') -Raw | ConvertFrom-Json
$rejected=$false
try { Assert-WeatherQualificationArmingProof -State $value.state -Proof $value.proof -Native $value.native }
catch { $rejected=$true }
''' + ("if($rejected){throw 'valid proof refused'}" if case == "valid" else "if(-not $rejected){throw 'invalid arming proof accepted'}"))


def test_durable_publication_has_one_winner_and_retains_spent_claim(tmp_path):
    args = invoke(tmp_path, r'''
. (Join-Path $root 'scripts/ops/qualification_durable_json.ps1')
Write-WeatherQualificationImmutableJson -Path (Join-Path $fixture 'receipt.json') -Payload @{schema='fixture_v2';status='ARMED'}
''', check=False)
    children = [subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    try:
        results = [child.communicate(timeout=30) for child in children]
        assert sorted(child.returncode for child in children)[0] == 0, results
        assert sum(child.returncode == 0 for child in children) == 1, results
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
    assert json.loads((tmp_path / "receipt.json").read_text()) == {"schema": "fixture_v2", "status": "ARMED"}
    assert (tmp_path / "receipt.json.publish-claim").read_bytes() == b"\1"
    retry = subprocess.run(args, capture_output=True, timeout=30)
    assert retry.returncode != 0


def test_interrupted_publication_preserves_partial_and_never_retries(tmp_path):
    (tmp_path / "receipt.json.publish-claim").write_bytes(b"\1")
    (tmp_path / "receipt.json.partial").write_bytes(b'{"status":')
    invoke(tmp_path, r'''
. (Join-Path $root 'scripts/ops/qualification_durable_json.ps1')
$refused=$false
try { Write-WeatherQualificationImmutableJson -Path (Join-Path $fixture 'receipt.json') -Payload @{status='ARMED'} }
catch { $refused=$true }
if(-not $refused -or (Test-Path -LiteralPath (Join-Path $fixture 'receipt.json'))){throw 'interrupted publication regained authority'}
''')
    assert (tmp_path / "receipt.json.partial").read_bytes() == b'{"status":'


def test_task_entrypoints_refuse_before_execution_without_arming_receipt(tmp_path):
    invoke(tmp_path, r'''
$contract=[pscustomobject]@{}
function Assert-WeatherQualificationArming { throw 'NO_ARMING' }
foreach($name in @('integration_attempt_host.ps1','integration_attempt_merge.ps1')) {
    $tokens=$null; $errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root ('scripts/ops/'+$name)),[ref]$tokens,[ref]$errors)
    if($errors.Count){throw ($errors | Out-String)}
    $calls=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.CommandAst] -and $node.GetCommandName() -ceq 'Assert-WeatherQualificationArming'},$true))
    if($calls.Count -ne 1){throw 'entrypoint lacks exact arming gate'}
    $refused=$false
    try { Invoke-Expression $calls[0].Extent.Text } catch { if($_.Exception.Message -cne 'NO_ARMING'){throw}; $refused=$true }
    if(-not $refused){throw 'unarmed task entered execution'}
}
foreach($name in @('arm_integration_attempt.ps1','qualification_durable_json.ps1','qualification_arming_contract.ps1')) {
    $tokens=$null; $errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile((Join-Path $root ('scripts/ops/'+$name)),[ref]$tokens,[ref]$errors)
    if($errors.Count){throw ($errors | Out-String)}
}
''')
