"""Connected public v2 readers, using synthetic records and no host authority.

This fixture deliberately does not run a signature verifier, prepare a real
attempt or touch Scheduler. It catches disagreements between the public
manifest reader and preparation/arming consumers using their actual readers.
Native process behavior and authenticated signatures have separate fixtures.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from weather.operations.qualification import attempt, planning, records
from test_qualification_arming_native import values


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.name != "nt", reason="connected native PowerShell readers")


def connected(tmp_path):
    root = tmp_path / "attempt"
    root.mkdir()
    production, candidate = tmp_path / "production", tmp_path / "candidate"
    production.mkdir()
    candidate.mkdir()
    control = root / "control"
    scripts = control / "scripts/ops"
    scripts.mkdir(parents=True)
    files = []
    for path in sorted((ROOT / "scripts/ops").glob("*.ps1")):
        target = scripts / path.name
        shutil.copyfile(path, target)
        files.append({"path": "scripts/ops/" + path.name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    put = lambda name, value: records.publish(root, name, value)
    placeholder = put("synthetic.json", {"test_only": True, "integration_eligible": False})
    native_env = put("environment.json", {"schema": "qualification_environment_v2", "platform": "windows",
        "python": {"executable_sha256": "1" * 64}, "git": {"sha256": "2" * 64}, "powershell": {"sha256": "3" * 64}})
    profile = put("profile.json", {"schema": "qualification_host_environment_v2", "environment": native_env,
        "tools": {name: {"sha256": digit * 64} for name, digit in (("python", "1"), ("git", "2"), ("powershell", "3"), ("gh", "4"))}})
    policy = put("policy.json", {"schema": "qualification_policy_v2", "verifier": {"gh_sha256": "4" * 64},
        "host": {"minimum_disk_bytes": 10000}})
    review = put("review.json", {"environments": {"windows": native_env}})
    measurement = put("measurement.json", {"schema": "qualification_host_measurement_v2",
        "phases": {"metadata": {"maximum": {"seconds": 120, "commit_bytes": 1000, "working_set_bytes": 900}}}})
    closure = {"schema": "qualification_control_closure_v2", "baseline": "b" * 40, "files": files}
    closure_ref = put("control.json", closure)
    plan = {"schema": "qualification_host_plan_v2", "environment": profile, "measurements": measurement,
        "configuration": placeholder, "audit": None, "local_day": "2026-09-15",
        "host_id": "5" * 64, "principal_id": "6" * 64}
    host = put("host-plan.json", plan)
    manifest = {"schema": "weather_integration_attempt_manifest_v2", "qualification_mode": "split_v2",
        "attempt_id": "connected", "created_at_local": "2026-09-14T10:00:00", "attempt_root": str(root),
        "repo_root": str(production), "worktree_root": str(candidate), "branch_ref": "codex/connected", "expected_tip": "c" * 40,
        "baseline": {"master": "b" * 40, "origin_master": "b" * 40},
        "authorization": {"review_reference": "synthetic reader fixture only", "repair_class": "initial", "repair_of": None},
        "schedule": {"host_at_local": "2026-09-15T00:30:00", "merge_at_local": "2026-09-15T01:05:00",
            "host_task_name": "WeatherIntegrationHost_connected", "merge_task_name": "WeatherIntegrationMerge_connected"},
        "orchestration": planning.orchestration(control, closure),
        "evidence": {key: str(root / name) for key, name in attempt.EVIDENCE.items()},
        "qualification": {"root": str(root), "policy": policy, "review": review, "certificate": placeholder,
            "import": placeholder, "revocations": placeholder},
        "control": {"root": str(control), "closure": closure_ref, "git_policy": placeholder}, "host": host}
    manifest_ref = put("manifest.json", manifest)
    proof = values()["proof"]
    proof.update(manifest_sha256=manifest_ref["sha256"], host_plan_sha256=host["sha256"],
        configuration_sha256=placeholder["sha256"], environment_sha256=profile["sha256"],
        certificate_sha256=placeholder["sha256"], import_sha256=placeholder["sha256"],
        validated_at="2020-01-01T00:00:00Z", latest_merge="2020-01-01T04:00:00Z")
    proof["signature"]["certificate_sha256"] = placeholder["sha256"]
    for directory in ("prepare-work", "arm-work"):
        (root / directory).mkdir()
    prep_proof = put("prepare-work/proof.json", {**proof, "schema": "qualification_preparation_proof_v2"})
    prep_native = put("prepare-work/native.json", values()["native"])
    preparation = {"schema": "weather_integration_attempt_preparation_receipt_v2", "status": "PREPARED",
        "manifest_sha256": manifest_ref["sha256"], "attempt_id": "connected", "proof": prep_proof,
        "native": prep_native, "integration_eligible": False}
    arming = {"schema": "weather_integration_attempt_arming_receipt_v2", "status": "ARMED",
        "manifest_sha256": manifest_ref["sha256"], "attempt_id": "connected",
        "registration_receipt_sha256": put("registration-receipt.json", {"test_only": True})["sha256"],
        "registration_intent_sha256": put("registration-intent.json", {"test_only": True})["sha256"],
        "proof": put("arm-work/proof.json", proof), "native": put("arm-work/native.json", values()["native"]),
        "completed_at": "2020-01-01T00:00:01Z", "host_id": plan["host_id"], "principal_id": plan["principal_id"],
        "integration_eligible": False}
    return root, manifest_ref, preparation, arming


def invoke(tmp_path, root, ref, body):
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    path = tmp_path / "connected.ps1"
    path.write_text("$ErrorActionPreference='Stop'\n$root=" + quote(ROOT) + "\n$evidence=" + quote(root) + "\n"
        ". (Join-Path $root 'scripts/ops/integration_attempt_contract.ps1')\n"
        ". (Join-Path $root 'scripts/ops/qualification_preparation.ps1')\n"
        "$contract=Assert-WeatherIntegrationAttemptManifest -ManifestPath (Join-Path $evidence 'manifest.json') -ExpectedSha256 " +
        quote(ref["sha256"]) + "\n" + body, encoding="utf-8")
    executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-File", str(path)],
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr


def test_public_manifest_routes_to_host_and_retains_separate_inert_gates(tmp_path):
    root, ref, preparation, arming = connected(tmp_path)
    # Manifest acceptance alone must fail both subsequent publication readers.
    invoke(tmp_path, root, ref, r'''
if((Get-WeatherIntegrationPrerequisite -AttemptContract $contract).Role -cne 'host'){throw 'wrong prerequisite'}
foreach($gate in @('Assert-WeatherQualificationPreparation','Assert-WeatherQualificationArming')){
    $refused=$false
    try{& $gate -AttemptContract $contract | Out-Null}catch{$refused=$true}
    if(-not $refused){throw 'manifest alone became execution authority'}
}
''')
    records.publish(root, "preparation-receipt.json", preparation)
    records.publish(root, "arming-receipt.json", arming)
    invoke(tmp_path, root, ref, r'''
$prepared=Assert-WeatherQualificationPreparation -AttemptContract $contract
$armed=Assert-WeatherQualificationArming -AttemptContract $contract -Historical
if($prepared.integration_eligible -or $armed.integration_eligible){throw 'reader upgraded integration authority'}
$refused=$false
try{Assert-WeatherQualificationArming -AttemptContract $contract | Out-Null}catch{$refused=$true}
if(-not $refused){throw 'historical arming permits a new launch'}
''')


@pytest.mark.parametrize("fault", ["controller", "environment", "preparation-child", "registration", "arming-child"])
def test_connected_readers_reject_one_rewritten_dependency(tmp_path, fault):
    root, ref, preparation, arming = connected(tmp_path)
    records.publish(root, "preparation-receipt.json", preparation)
    records.publish(root, "arming-receipt.json", arming)
    path = {"controller": "control/scripts/ops/integration_attempt_host.ps1", "environment": "environment.json",
        "preparation-child": "prepare-work/native.json", "registration": "registration-receipt.json",
        "arming-child": "arm-work/native.json"}[fault]
    (root / path).write_bytes((root / path).read_bytes() + b" ")
    with pytest.raises(AssertionError):
        invoke(tmp_path, root, ref, "Assert-WeatherQualificationPreparation -AttemptContract $contract | Out-Null\n"
            "Assert-WeatherQualificationArming -AttemptContract $contract -Historical | Out-Null")
