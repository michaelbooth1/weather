from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

from tests.live_candidate_fixture import (
    build_stage0_event_metadata_payload,
    build_stage0_scope_payload,
)
from weather.market.mm_credentials import (
    STAGE0_AUTHORIZATION,
    STAGE0_IDENTITY_SCHEMA_VERSION,
)
from weather.operations import international_live_session_launcher_sealer as launcher_sealer
from weather.operations import international_live_session_runner as runner
from weather.operations import international_live_wrapper_sealer as fixed_sealer
from weather.operations.live_path_security import canonical_windows_powershell


NOW = datetime.fromisoformat("2026-08-23T01:00:00-04:00")
CONDITION = "0x" + "1" * 64
TOKEN = "101"
WINDOWS_POWERSHELL_REQUIRED = pytest.mark.skipif(
    os.name != "nt",
    reason="requires Windows PowerShell",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_fixed_session_launcher_locks_the_reviewed_real_git_payload() -> None:
    text = launcher_sealer.TEMPLATE_PATH.read_text(encoding="utf-8-sig")

    assert "manifestPayload.production.git_executable" in text
    assert "manifestPayload.production.git_executable_sha256" in text
    assert "Add-LockedExactFile" in text


def fixture(tmp_path: Path):
    prepared = manifest_builder_fixture(tmp_path)
    build_receipt = build_manifest(prepared)
    manifest = Path(build_receipt["session_manifest"]["path"])
    return (
        prepared["production"],
        prepared["outer_template"],
        prepared["attempt"],
        manifest,
        Path(build_receipt["build_receipt_path"]),
    )


def prepare(repo, template, manifest, build_receipt):
    return launcher_sealer.prepare_fixed_session_launcher(
        manifest,
        sha(manifest),
        sha(build_receipt),
        repo_root=repo,
        template_path=template,
        powershell_parser=lambda _source: None,
        attempt_root_validator=lambda path: {"status": "PASS", "path": str(path)},
        capture_assignment_validator=lambda *_args, **_kwargs: {},
        portable_assignment_validator=lambda *_args, **_kwargs: {},
        now=NOW,
    )


def test_preparer_writes_no_argument_hash_bound_launcher_and_review_receipt(tmp_path):
    repo, template, attempt, manifest, build_receipt = fixture(tmp_path)

    receipt = prepare(repo, template, manifest, build_receipt)

    launcher = Path(receipt["launcher"]["path"])
    text = launcher.read_text(encoding="utf-8-sig")
    assert receipt["status"] == "PASS"
    assert receipt["schema_version"] == launcher_sealer.LAUNCHER_REVIEW_SCHEMA_VERSION
    assert receipt["no_argument_surface"] is True
    assert "param()" in text
    assert "$MyInvocation.UnboundArguments.Count -ne 0" in text
    assert sha(manifest) in text
    assert sha(build_receipt) in text
    assert "--expected-session-manifest-sha256" in text
    assert "[IO.FileShare]::Read" in text
    assert "source_sha256.psobject.Properties" in text
    assert "Get-ChildItem -LiteralPath $attemptRoot -File -Recurse" in text
    assert "& $python -I -S -B -c" not in text
    assert "__SESSION_WINDOWS_JOB_HELPER_SHA256__" not in text
    assert "Start-WeatherInteractiveProcessInJob" in text
    assert text.index("$child.WaitForExit()") < text.index(
        "$job.TerminateAndWait(5000)"
    )
    assert "PYTHONPATH" not in text
    assert receipt["production_python"]["sha256"] == sha(
        repo / "venv/Scripts/python.exe"
    )
    assert set(receipt["session_bootstrap_sha256"]) == set(
        runner.SESSION_BOOTSTRAP_PATHS
    )
    assert {
        "src/weather/operations/international_live_session_runner.py",
        "src/weather/operations/international_live_time_window.py",
        "src/weather/operations/international_live_wrapper_sealer.py",
        "src/weather/operations/live_path_security.py",
    }.issubset(receipt["session_bootstrap_sha256"])
    assert (attempt / "session/stage0-launcher-review.json.sha256").is_file()
    assert receipt["manifest_build_receipt"] == {
        "path": str(build_receipt.resolve()),
        "sha256": sha(build_receipt),
    }
    assert receipt["session_manifest"]["semantic_sha256"] == json.loads(
        manifest.read_text(encoding="utf-8")
    )["manifest_sha256"]


@WINDOWS_POWERSHELL_REQUIRED
def test_forced_outer_launcher_exit_kills_session_runner_tree(tmp_path):
    repo = tmp_path / "production"
    python = Path(sys.executable).resolve()
    site_packages = python.parent.parent / "Lib/site-packages"
    if not site_packages.is_dir():
        pytest.skip("test interpreter does not use the required Windows venv layout")

    job_relative = fixed_sealer.WINDOWS_JOB_HELPER_PATH
    job_script = repo / job_relative
    job_script.parent.mkdir(parents=True)
    shutil.copyfile(fixed_sealer.REPO_ROOT / job_relative, job_script)

    runner_relative = "src/weather/operations/international_live_session_runner.py"
    runner_source = repo / runner_relative
    runner_source.parent.mkdir(parents=True)
    (runner_source.parents[1] / "__init__.py").write_text("", encoding="utf-8")
    (runner_source.parent / "__init__.py").write_text("", encoding="utf-8")
    runner_source.write_text(
        "import os, pathlib, subprocess, sys, time\n"
        "code = (\"import os,pathlib,time;time.sleep(2.5);\"\n"
        "        \"pathlib.Path(os.environ['WEATHER_OUTER_JOB_SURVIVED']).write_text('survived')\")\n"
        "grandchild = subprocess.Popen([sys.executable, '-c', code])\n"
        "pathlib.Path(os.environ['WEATHER_OUTER_JOB_READY']).write_text(\n"
        "    f'{os.getpid()},{grandchild.pid}'\n"
        ")\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    git_payload = repo / "git.exe"
    git_payload.write_bytes(b"reviewed git payload")

    attempt = tmp_path / "attempt"
    inputs = attempt / "inputs"
    incoming = attempt / "incoming"
    session = attempt / "session"
    for directory in (inputs, incoming, session):
        directory.mkdir(parents=True)
    manifest = inputs / "stage0-session-manifest.json"
    manifest_payload = {
        "production_python_sha256": sha(python),
        "production": {
            "git_executable": str(git_payload.resolve()),
            "git_executable_sha256": sha(git_payload),
        },
        "session_bootstrap_sha256": {runner_relative: sha(runner_source)},
        "source_sha256": {job_relative: sha(job_script)},
        "inputs": {},
        "scope": {"attempt_root": str(attempt.resolve())},
    }
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    sidecar = manifest.with_suffix(manifest.suffix + ".sha256")
    sidecar.write_text(f"{sha(manifest)}  {manifest.name}\n", encoding="ascii")
    build_receipt = inputs / "stage0-manifest-build-receipt.json"
    build_receipt.write_text("{}\n", encoding="utf-8")
    candidate = incoming / "fresh-stage0-candidate.json"
    candidate.write_text("{}\n", encoding="utf-8")

    replacements = {
        "__SESSION_REPO_ROOT__": str(repo.resolve()),
        "__SESSION_PYTHON__": str(python),
        "__SESSION_PYTHON_SHA256__": sha(python),
        "__SESSION_RUNNER_SOURCE__": str(runner_source.resolve()),
        "__SESSION_RUNNER_SHA256__": sha(runner_source),
        "__SESSION_MANIFEST__": str(manifest.resolve()),
        "__SESSION_MANIFEST_SHA256__": sha(manifest),
        "__SESSION_CANDIDATE_INBOX__": str(candidate.resolve()),
        "__SESSION_MANIFEST_SIDECAR__": str(sidecar.resolve()),
        "__SESSION_MANIFEST_SIDECAR_SHA256__": sha(sidecar),
        "__SESSION_MANIFEST_BUILD_RECEIPT__": str(build_receipt.resolve()),
        "__SESSION_MANIFEST_BUILD_RECEIPT_SHA256__": sha(build_receipt),
        "__SESSION_WINDOWS_JOB_HELPER_SHA256__": sha(job_script),
    }
    source = launcher_sealer.TEMPLATE_PATH.read_text(encoding="utf-8-sig")
    for marker, value in replacements.items():
        source = launcher_sealer._replace(source, marker, value)
    assert "__SESSION_" not in source
    launcher_path = tmp_path / "outer-session-launcher.ps1"
    launcher_path.write_text(source, encoding="utf-8-sig")

    ready = tmp_path / "outer-runner-ready.txt"
    survived = tmp_path / "outer-grandchild-survived.txt"
    environment = {
        **os.environ,
        "WEATHER_OUTER_JOB_READY": str(ready),
        "WEATHER_OUTER_JOB_SURVIVED": str(survived),
    }
    launcher = subprocess.Popen(
        [
            str(canonical_windows_powershell()),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(launcher_path),
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            if launcher.poll() is not None:
                stdout, stderr = launcher.communicate()
                pytest.fail(f"outer launcher exited before readiness: {stdout} {stderr}")
            time.sleep(0.05)
        assert ready.is_file(), "contained session runner did not reach readiness"
        launcher.terminate()
        launcher.wait(timeout=10)
    finally:
        if launcher.poll() is None:
            launcher.kill()
            launcher.wait(timeout=10)

    time.sleep(3)
    assert not survived.exists()


@WINDOWS_POWERSHELL_REQUIRED
def test_no_argument_launcher_rejects_manifest_and_sidecar_rewrite(tmp_path):
    repo, template, attempt, manifest, build_receipt = fixture(tmp_path)
    receipt = prepare(repo, template, manifest, build_receipt)
    candidate = attempt / "incoming/fresh-stage0-candidate.json"
    candidate.write_text("{}", encoding="utf-8")
    payload = json.loads(manifest.read_text())
    payload["scope"]["attempt_root"] = str((tmp_path / "other").resolve())
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    manifest.with_suffix(manifest.suffix + ".sha256").write_text(
        f"{sha(manifest)}  {manifest.name}\n", encoding="ascii"
    )

    result = subprocess.run(
        [
            str(canonical_windows_powershell()),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            receipt["launcher"]["path"],
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "fixed session locked-file hash changed" in (
        result.stdout + result.stderr
    )


def write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def manifest_builder_fixture(tmp_path: Path, *, constrained=False):
    production = tmp_path / "production"
    python = production / "venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"reviewed production interpreter")
    (production / "venv/Lib/site-packages").mkdir(parents=True)
    for relative in {
        *fixed_sealer.LIVE_SOURCE_PATHS["stage0"],
        fixed_sealer.WORKLOAD_ADMISSION_PATH,
        *runner.SESSION_BOOTSTRAP_PATHS,
    }:
        path = production / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"reviewed source: {relative}\n", encoding="utf-8")
    for relative in {
        fixed_sealer.PYTHON_TEMPLATE_PATHS["stage0"],
        fixed_sealer.LAUNCHER_TEMPLATE_PATH,
    }:
        path = production / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"reviewed template: {relative}\n", encoding="utf-8")
    outer_template_relative = launcher_sealer.TEMPLATE_PATH.relative_to(
        launcher_sealer.REPO_ROOT
    )
    outer_template = production / outer_template_relative
    outer_template.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(launcher_sealer.TEMPLATE_PATH, outer_template)

    sources = tmp_path / "public-sources"
    identity = write_json(
        sources / "identity.json",
        {
            "schema_version": STAGE0_IDENTITY_SCHEMA_VERSION,
            "operator_authorization": STAGE0_AUTHORIZATION,
            "platform": "polymarket_global",
            "international_platform_confirmed": True,
            "clob_host": "https://clob.polymarket.com",
            "settlement_unit": "pUSD",
            "chain_id": 137,
            "sdk_distribution": "polymarket-client",
            "sdk_version": "0.6.0",
            "wallet_type": "gnosis_safe",
            "signature_type": "POLY_GNOSIS_SAFE",
            "signature_type_id": 2,
            "funder_address": "0x" + "3" * 40,
            "isolated_pilot_wallet": True,
            "pilot_wallet_max_funding_usdc": 100,
        },
    )
    credential_receipt = write_json(
        sources / "credential-import-receipt.json",
        {
            "schema_version": "mm_live_credential_import_receipt_v0.4",
            "status": "PASS",
            "platform": "polymarket_global",
            "prepared_at_utc": NOW.astimezone(timezone.utc).isoformat(),
            "execution_host_id": launcher_sealer.current_execution_host_id(),
            "execution_principal_id": (
                launcher_sealer.current_execution_principal_id()
            ),
            "source_outside_repository_verified": True,
            "source_acl_private_confirmed": True,
            "credential_value_count_expected": 4,
            "credential_value_count_written": 0,
            "credential_mode": "verify_existing_exact",
            "credential_value_count_existing_exact_verified": 4,
            "credential_store_mutation_attempted": False,
            "credential_values_retained": False,
            "ignored_source_key_count": 0,
            "checks": {
                name: True
                for name in fixed_sealer.EXPECTED_CREDENTIAL_IMPORT_CHECKS
            },
            "missing": [],
            "rollback_attempted": False,
            "rollback_ok": None,
            "source_deletion_required_after_transfer": True,
        },
    )
    credential_manifest = write_json(
        sources / "credential-reference-manifest.json",
        {
            "schema_version": "mm_live_credential_reference_manifest_v0.1",
            "platform": "polymarket_global",
            "wallet_type": "gnosis_safe",
            "signature_type": "POLY_GNOSIS_SAFE",
            "signature_type_id": 2,
            "wallet_address": "0x" + "2" * 40,
            "funder_address": "0x" + "3" * 40,
            "credential_references": dict(
                fixed_sealer.EXPECTED_CREDENTIAL_REFERENCES
            ),
            "public_environment": {
                "POLYMARKET_FUNDER_ADDRESS": "0x" + "3" * 40,
            },
            "secret_values_retained": False,
            "ignored_relayers_rpc_and_self_assertions": True,
        },
    )
    event_metadata = write_json(
        sources / "location-market-events.json",
        build_stage0_event_metadata_payload(
            generated_at=NOW.astimezone(timezone.utc) - timedelta(days=14),
            target_date=NOW.date().isoformat(),
            condition_id=CONDITION,
            token_id=TOKEN,
            alternate_token_id="102",
        ),
    )
    discovery_data = build_stage0_scope_payload(
        now=NOW,
        target_date=NOW.date().isoformat(),
        condition_id=CONDITION,
        token_id=TOKEN,
        alternate_token_id="102",
        event_metadata_file_sha256=sha(event_metadata),
        event_metadata_generated_at=(
            NOW.astimezone(timezone.utc) - timedelta(days=14)
        ),
        constrained=constrained,
        best_bid=0.19,
        best_ask=0.44,
    )
    discovery = write_json(sources / "discovery.json", discovery_data)
    attempt = tmp_path / "attempt"
    for name in launcher_sealer.ATTEMPT_DIRECTORIES:
        (attempt / name).mkdir(parents=True, exist_ok=True)

    def inventory(
        stage,
        root,
        *,
        execution_host_profile="capture_colocated_v1",
    ):
        root = Path(root)
        git_executable = fixed_sealer.canonical_git_executable()
        branch = (
            fixed_sealer.PORTABLE_EXECUTION_AUTHORIZED_TOPIC_BRANCH
            if execution_host_profile == "portable_execution_v1"
            else "master"
        )
        master_tip = "c" * 40 if branch != "master" else "a" * 40
        source_paths = set(fixed_sealer.LIVE_SOURCE_PATHS[stage]) | {
            fixed_sealer.WORKLOAD_ADMISSION_PATH
        }
        return {
            "schema_version": fixed_sealer.INVENTORY_SCHEMA_VERSION,
            "status": "PASS",
            "stage": stage,
            "execution_host_profile": execution_host_profile,
            "production": {
                "root": str(root.resolve()),
                "branch": branch,
                "commit": "a" * 40,
                "local_branch_tip": "a" * 40,
                "cached_origin_branch_tip": "a" * 40,
                "remote_branch_tip": "a" * 40,
                "remote_branch_ref": f"refs/heads/{branch}",
                "live_remote_branch_equal": True,
                "local_master": master_tip,
                "cached_origin_master": master_tip,
                "remote_master": master_tip,
                "remote_master_ref": fixed_sealer.REMOTE_MASTER_REF,
                "live_remote_master_equal": True,
                "live_remote_master_ancestor": True,
                "worktree_policy_clean": True,
                "tree": "b" * 40,
                "object_format": "sha1",
                "python": str((root / "venv/Scripts/python.exe").resolve()),
                "python_sha256": sha(root / "venv/Scripts/python.exe"),
                "git_executable": str(git_executable),
                "git_executable_sha256": sha(git_executable),
                "canonical_origin_url": fixed_sealer.CANONICAL_ORIGIN_URL,
                "interrupt_cleanup_ancestor_integrated": True,
            },
            "template_sha256": {
                "python": sha(root / fixed_sealer.PYTHON_TEMPLATE_PATHS[stage]),
                "launcher": sha(root / fixed_sealer.LAUNCHER_TEMPLATE_PATH),
            },
            "source_sha256": {
                relative: sha(root / relative)
                for relative in sorted(source_paths)
            },
            "session_bootstrap_sha256": {
                relative: sha(root / relative)
                for relative in runner.SESSION_BOOTSTRAP_PATHS
            },
            "live_mutation_attempted": False,
            "credential_value_read": False,
        }

    return {
        "production": production,
        "attempt": attempt,
        "identity": identity,
        "credential_receipt": credential_receipt,
        "credential_manifest": credential_manifest,
        "event_metadata": event_metadata,
        "discovery": discovery,
        "inventory": inventory,
        "outer_template": outer_template,
    }


def build_manifest(prepared, **overrides):
    workload = launcher_sealer._canonical_lease_workload(
        prepared["attempt"], "stage0"
    )
    arguments = {
        "stage": "stage0",
        "discovery_plan_path": prepared["discovery"],
        "identity_source_path": prepared["identity"],
        "credential_import_receipt_source_path": prepared[
            "credential_receipt"
        ],
        "credential_reference_manifest_source_path": prepared[
            "credential_manifest"
        ],
        "event_metadata_source_path": prepared["event_metadata"],
        "attempt_root": prepared["attempt"],
        "lease_workload": workload,
        "execution_host_profile": "capture_colocated_v1",
        "production_root": prepared["production"],
        "now": NOW,
        "inventory_builder": prepared["inventory"],
        "git_state_validator": lambda _production: None,
        "attempt_root_validator": lambda path: {
            "status": "PASS",
            "path": str(path),
        },
        "capture_assignment_validator": lambda *_args, **_kwargs: {},
        "portable_assignment_validator": lambda *_args, **_kwargs: {},
    }
    arguments.update(overrides)
    return launcher_sealer.prepare_fixed_session_manifest(**arguments)


def test_manifest_builder_stages_public_inputs_and_writes_exact_hash_contract(tmp_path):
    prepared = manifest_builder_fixture(tmp_path)

    receipt = build_manifest(prepared)

    manifest_path = Path(receipt["session_manifest"]["path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sidecar = manifest_path.with_suffix(manifest_path.suffix + ".sha256")
    assert receipt["status"] == "PASS"
    assert receipt["live_mutation_attempted"] is False
    assert receipt["credential_values_read_in_memory"] is False
    assert manifest_path == (
        prepared["attempt"] / "inputs/stage0-session-manifest.json"
    ).resolve()
    assert sidecar.read_text(encoding="ascii") == (
        f"{sha(manifest_path)}  {manifest_path.name}\n"
    )
    assert manifest["manifest_sha256"] == runner._canonical_payload_sha256(
        manifest
    )
    expected_workload = launcher_sealer._canonical_lease_workload(
        prepared["attempt"], "stage0"
    )
    assert manifest["scope"] == {
        "target_date": NOW.date().isoformat(),
        "condition_id": CONDITION,
        "token_id": TOKEN,
        "requested_budget_pusd": 10,
        "attempt_root": str(prepared["attempt"].resolve()),
        "lease_workload": expected_workload,
        "execution_host_profile": "capture_colocated_v1",
        "execution_host_id": launcher_sealer.current_execution_host_id(),
        "market_id": "toronto",
        "market_timezone": "America/Toronto",
        "max_session_seconds": 120,
    }
    assert set(manifest["inputs"]) == {
        "identity",
        "credential_import_receipt",
        "credential_reference_manifest",
        "event_metadata",
    }
    for role, source_key in {
        "identity": "identity",
        "credential_import_receipt": "credential_receipt",
        "credential_reference_manifest": "credential_manifest",
        "event_metadata": "event_metadata",
    }.items():
        copied = Path(manifest["inputs"][role]["path"])
        assert copied.is_relative_to(prepared["attempt"])
        assert copied.read_bytes() == Path(prepared[source_key]).read_bytes()
        assert manifest["inputs"][role]["sha256"] == sha(copied)
    assert Path(receipt["staged_public_inputs"]["discovery_plan"]["path"]).read_bytes() == prepared[
        "discovery"
    ].read_bytes()
    assert "economics_acceptance" not in manifest
    assert Path(receipt["build_receipt_path"]).is_file()
    launcher_receipt = launcher_sealer.prepare_fixed_session_launcher(
        manifest_path,
        sha(manifest_path),
        sha(Path(receipt["build_receipt_path"])),
        repo_root=prepared["production"],
        template_path=prepared["outer_template"],
        powershell_parser=lambda _source: None,
        attempt_root_validator=lambda path: {
            "status": "PASS",
            "path": str(path),
        },
        capture_assignment_validator=lambda *_args, **_kwargs: {},
        portable_assignment_validator=lambda *_args, **_kwargs: {},
        now=NOW,
    )
    assert launcher_receipt["status"] == "PASS"
    assert launcher_receipt["session_manifest"]["sha256"] == sha(manifest_path)


@pytest.mark.parametrize("mode", ["create_new", "verify_existing_exact"])
@pytest.mark.parametrize("age", [timedelta(hours=3), timedelta(days=365)])
def test_manifest_and_launcher_reuse_host_bound_credential_provenance(
    tmp_path, mode, age
):
    prepared = manifest_builder_fixture(tmp_path)
    receipt_path = prepared["credential_receipt"]
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["credential_mode"] = mode
    payload["credential_value_count_written"] = 4 if mode == "create_new" else 0
    payload["credential_value_count_existing_exact_verified"] = (
        0 if mode == "create_new" else 4
    )
    payload["credential_store_mutation_attempted"] = mode == "create_new"
    payload["prepared_at_utc"] = (NOW - age).isoformat()
    write_json(receipt_path, payload)
    original = receipt_path.read_bytes()
    build_receipt = build_manifest(prepared)
    manifest_path = Path(build_receipt["session_manifest"]["path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    staged = Path(manifest["inputs"]["credential_import_receipt"]["path"])
    assert staged.read_bytes() == receipt_path.read_bytes() == original
    assert build_receipt["credential_values_read_in_memory"] is False
    launcher_receipt = prepare(
        prepared["production"], prepared["outer_template"], manifest_path,
        Path(build_receipt["build_receipt_path"]),
    )
    assert launcher_receipt["status"] == "PASS"


def test_manifest_builder_rejects_event_metadata_not_bound_by_discovery(tmp_path):
    prepared = manifest_builder_fixture(tmp_path)
    event_metadata = prepared["event_metadata"]
    payload = json.loads(event_metadata.read_text(encoding="utf-8"))
    payload["locations"][0]["active_events"][0]["title"] = "Changed title"
    write_json(event_metadata, payload)

    with pytest.raises(
        launcher_sealer.SessionLauncherSealError,
        match="does not match its stage-specific source evidence",
    ):
        build_manifest(prepared)

    assert list((prepared["attempt"] / "inputs").iterdir()) == []


def test_manifest_builder_rejects_legacy_create_credential_evidence(tmp_path):
    prepared = manifest_builder_fixture(tmp_path)
    receipt_path = prepared["credential_receipt"]
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "mm_live_credential_import_receipt_v0.1"
    payload["credential_value_count_written"] = 4
    del payload["credential_mode"]
    del payload["credential_value_count_existing_exact_verified"]
    del payload["credential_store_mutation_attempted"]
    del payload["prepared_at_utc"]
    del payload["execution_host_id"]
    del payload["execution_principal_id"]
    write_json(receipt_path, payload)

    with pytest.raises(
        launcher_sealer.SessionLauncherSealError,
        match="requires exact host/principal-bound credential provenance",
    ):
        build_manifest(prepared)

    assert list((prepared["attempt"] / "inputs").iterdir()) == []


def test_launcher_revalidates_staged_credential_provenance(tmp_path):
    prepared = manifest_builder_fixture(tmp_path)
    build_receipt = build_manifest(prepared)
    manifest_path = Path(build_receipt["session_manifest"]["path"])
    build_receipt_path = Path(build_receipt["build_receipt_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    staged_receipt_path = Path(
        manifest["inputs"]["credential_import_receipt"]["path"]
    )
    credential_payload = json.loads(
        staged_receipt_path.read_text(encoding="utf-8")
    )
    credential_payload["execution_principal_id"] = "0" * 64
    write_json(staged_receipt_path, credential_payload)
    staged_receipt_sha256 = sha(staged_receipt_path)

    manifest["inputs"]["credential_import_receipt"]["sha256"] = (
        staged_receipt_sha256
    )
    manifest["manifest_sha256"] = runner._canonical_payload_sha256(manifest)
    manifest_path.write_bytes(launcher_sealer._canonical_json(manifest))
    sidecar_path = manifest_path.with_suffix(manifest_path.suffix + ".sha256")
    sidecar_path.write_text(
        f"{sha(manifest_path)}  {manifest_path.name}\n",
        encoding="ascii",
    )

    receipt_payload = json.loads(build_receipt_path.read_text(encoding="utf-8"))
    staged_record = receipt_payload["staged_public_inputs"][
        "credential_import_receipt"
    ]
    staged_record["sha256"] = staged_receipt_sha256
    staged_record["bytes"] = staged_receipt_path.stat().st_size
    receipt_payload["session_manifest"]["sha256"] = sha(manifest_path)
    receipt_payload["session_manifest"]["semantic_sha256"] = manifest[
        "manifest_sha256"
    ]
    receipt_payload["session_manifest_sidecar"]["sha256"] = sha(sidecar_path)
    build_receipt_path.write_bytes(
        launcher_sealer._canonical_json(receipt_payload)
    )

    with pytest.raises(
        launcher_sealer.SessionLauncherSealError,
        match="staged credential provenance is not an exact host/principal-bound result",
    ):
        prepare(
            prepared["production"],
            prepared["outer_template"],
            manifest_path,
            build_receipt_path,
        )

    assert list((prepared["attempt"] / "session").glob("*")) == []


def test_launcher_rejects_rehashed_manifest_not_bound_by_builder_receipt(tmp_path):
    prepared = manifest_builder_fixture(tmp_path)
    build_receipt = build_manifest(prepared)
    manifest_path = Path(build_receipt["session_manifest"]["path"])
    receipt_path = Path(build_receipt["build_receipt_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["reviewed_status_flags"] = [
        {
            "sha256": "f" * 64,
            "review": "Hand-authored review cannot replace builder provenance.",
        }
    ]
    manifest["manifest_sha256"] = runner._canonical_payload_sha256(manifest)
    manifest_path.write_bytes(launcher_sealer._canonical_json(manifest))
    manifest_path.with_suffix(manifest_path.suffix + ".sha256").write_text(
        f"{sha(manifest_path)}  {manifest_path.name}\n",
        encoding="ascii",
    )

    with pytest.raises(
        launcher_sealer.SessionLauncherSealError,
        match="does not exactly bind",
    ):
        prepare(
            prepared["production"],
            prepared["outer_template"],
            manifest_path,
            receipt_path,
        )

    assert list((prepared["attempt"] / "session").glob("*")) == []


def test_launcher_rejects_missing_canonical_builder_receipt(tmp_path):
    prepared = manifest_builder_fixture(tmp_path)
    build_receipt = build_manifest(prepared)
    manifest_path = Path(build_receipt["session_manifest"]["path"])
    Path(build_receipt["build_receipt_path"]).unlink()

    with pytest.raises(
        launcher_sealer.SessionLauncherSealError,
        match="build receipt is absent",
    ):
        launcher_sealer.prepare_fixed_session_launcher(
            manifest_path,
            sha(manifest_path),
            "0" * 64,
            repo_root=prepared["production"],
            template_path=prepared["outer_template"],
            powershell_parser=lambda _source: None,
            attempt_root_validator=lambda path: {
                "status": "PASS",
                "path": str(path),
            },
            capture_assignment_validator=lambda *_args, **_kwargs: {},
            portable_assignment_validator=lambda *_args, **_kwargs: {},
            now=NOW,
        )

    assert list((prepared["attempt"] / "session").glob("*")) == []


def test_launcher_rejects_semantically_tampered_builder_receipt(tmp_path):
    prepared = manifest_builder_fixture(tmp_path)
    build_receipt = build_manifest(prepared)
    manifest_path = Path(build_receipt["session_manifest"]["path"])
    receipt_path = Path(build_receipt["build_receipt_path"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["fixed_budget_pusd"] = 11
    receipt_path.write_bytes(launcher_sealer._canonical_json(payload))

    with pytest.raises(
        launcher_sealer.SessionLauncherSealError,
        match="does not exactly bind",
    ):
        prepare(
            prepared["production"],
            prepared["outer_template"],
            manifest_path,
            receipt_path,
        )

    assert list((prepared["attempt"] / "session").glob("*")) == []


def test_manifest_builder_rejects_constrained_or_expired_discovery_before_writes(tmp_path):
    prepared = manifest_builder_fixture(tmp_path, constrained=True)

    with pytest.raises(
        launcher_sealer.SessionLauncherSealError,
        match="unconstrained",
    ):
        build_manifest(prepared)

    assert list(prepared["attempt"].rglob("*.*")) == []


def test_manifest_builder_rejects_secret_material_in_discovery_before_writes(tmp_path):
    prepared = manifest_builder_fixture(tmp_path)
    payload = json.loads(prepared["discovery"].read_text(encoding="utf-8"))
    payload["api_secret"] = "must-not-be-read-as-a-public-plan"
    payload["plan_sha256"] = fixed_sealer._canonical_payload_sha256(
        payload, omit="plan_sha256"
    )
    write_json(prepared["discovery"], payload)

    with pytest.raises(
        launcher_sealer.SessionLauncherSealError,
        match="secret_free",
    ):
        build_manifest(prepared)

    assert list(prepared["attempt"].rglob("*.*")) == []


def test_manifest_builder_rejects_inventory_drift_before_writes(tmp_path):
    prepared = manifest_builder_fixture(tmp_path)
    inventory = prepared["inventory"]("stage0", prepared["production"])
    relative = next(iter(inventory["source_sha256"]))
    inventory["source_sha256"][relative] = "0" * 64

    with pytest.raises(
        launcher_sealer.SessionLauncherSealError,
        match="source hash changed",
    ):
        build_manifest(
            prepared,
            inventory_builder=lambda _stage, _root, **_kwargs: inventory,
        )

    assert list(prepared["attempt"].rglob("*.*")) == []


def test_manifest_builder_rechecks_inventory_immediately_before_publication(tmp_path):
    prepared = manifest_builder_fixture(tmp_path)
    relative = next(iter(fixed_sealer.LIVE_SOURCE_PATHS["stage0"]))
    calls = 0

    def mutate_on_final_check(_production):
        nonlocal calls
        calls += 1
        if calls == 2:
            (prepared["production"] / relative).write_text(
                "changed after initial inventory validation\n",
                encoding="utf-8",
            )

    with pytest.raises(
        launcher_sealer.SessionLauncherSealError,
        match="source hash changed",
    ):
        build_manifest(prepared, git_state_validator=mutate_on_final_check)

    assert calls == 2
    assert list(prepared["attempt"].rglob("*.*")) == []


def test_manifest_builder_rejects_noncanonical_lease_workload_before_writes(tmp_path):
    prepared = manifest_builder_fixture(tmp_path)

    with pytest.raises(
        launcher_sealer.SessionLauncherSealError,
        match="canonical unique attempt workload",
    ):
        build_manifest(prepared, lease_workload="InternationalLive-reused")

    assert list(prepared["attempt"].rglob("*.*")) == []


def test_manifest_builder_refuses_spent_namespace_and_duplicate_workload(tmp_path):
    prepared = manifest_builder_fixture(tmp_path)
    first = build_manifest(prepared)
    manifest_path = Path(first["session_manifest"]["path"])
    original = manifest_path.read_bytes()

    with pytest.raises(
        launcher_sealer.SessionLauncherSealError,
        match="already bound|already spent",
    ):
        build_manifest(prepared)

    assert manifest_path.read_bytes() == original


def test_manifest_builder_stages_optional_reviewed_status_flags_contract(tmp_path):
    prepared = manifest_builder_fixture(tmp_path)
    reviews = write_json(
        tmp_path / "public-sources/reviewed-flags.json",
        [
            {
                "sha256": "c" * 64,
                "review": "Reviewed capture warning is understood and accepted.",
            }
        ],
    )

    receipt = build_manifest(
        prepared,
        reviewed_status_flags_path=reviews,
    )

    manifest = json.loads(
        Path(receipt["session_manifest"]["path"]).read_text(encoding="utf-8")
    )
    assert manifest["reviewed_status_flags"] == [
        {
            "sha256": "c" * 64,
            "review": "Reviewed capture warning is understood and accepted.",
        }
    ]
    staged = receipt["staged_public_inputs"]["reviewed_status_flags"]
    assert Path(staged["path"]).read_bytes() == reviews.read_bytes()


def test_manifest_builder_binds_portable_execution_host_without_capture_flags(
    tmp_path,
):
    prepared = manifest_builder_fixture(tmp_path)

    receipt = build_manifest(
        prepared,
        execution_host_profile="portable_execution_v1",
    )

    manifest = json.loads(
        Path(receipt["session_manifest"]["path"]).read_text(encoding="utf-8")
    )
    assert manifest["scope"]["execution_host_profile"] == "portable_execution_v1"
    assert manifest["scope"]["execution_host_id"] == (
        launcher_sealer.current_execution_host_id()
    )
    assert manifest["scope"]["max_session_seconds"] == 240
    assert manifest["production"]["branch"] == (
        fixed_sealer.PORTABLE_EXECUTION_AUTHORIZED_TOPIC_BRANCH
    )
    assert receipt["fixed_max_session_seconds"] == 240
    assert manifest["reviewed_status_flags"] == []


def test_manifest_builder_refuses_capture_status_exceptions_for_portable_host(
    tmp_path,
):
    prepared = manifest_builder_fixture(tmp_path)
    reviews = write_json(
        tmp_path / "public-sources/reviewed-flags.json",
        [
            {
                "sha256": "c" * 64,
                "review": "This capture-host exception cannot move to PC2.",
            }
        ],
    )

    with pytest.raises(
        launcher_sealer.SessionLauncherSealError,
        match="do not consume capture-host status exceptions",
    ):
        build_manifest(
            prepared,
            execution_host_profile="portable_execution_v1",
            reviewed_status_flags_path=reviews,
        )

    assert list(prepared["attempt"].rglob("*.*")) == []


def test_manifest_builder_refuses_invalid_execution_host_identity_before_writes(
    tmp_path,
):
    prepared = manifest_builder_fixture(tmp_path)

    with pytest.raises(
        launcher_sealer.SessionLauncherSealError,
        match="execution host identity is invalid",
    ):
        build_manifest(
            prepared,
            execution_host_id_provider=lambda: "not-a-sha256",
        )

    assert list(prepared["attempt"].rglob("*.*")) == []


def test_attempt_initializer_creates_only_private_canonical_directories(tmp_path):
    production = tmp_path / "production"
    production.mkdir()
    attempt = tmp_path / "attempt"

    def creator(root):
        for name in launcher_sealer.ATTEMPT_DIRECTORIES:
            (root / name).mkdir(parents=True, exist_ok=True)

    receipt = launcher_sealer.initialize_private_attempt_root(
        attempt,
        production_root=production,
        directory_creator=creator,
        attempt_root_validator=lambda path: {
            "status": "PASS",
            "path": str(path),
        },
    )

    assert receipt["status"] == "PASS"
    assert set(receipt["directories"]) == {"inputs", "incoming", "session"}
    assert set(receipt["lease_workloads"]) == set(fixed_sealer.STAGES)
    assert list(attempt.rglob("*.*")) == []
    with pytest.raises(
        launcher_sealer.SessionLauncherSealError,
        match="already spent",
    ):
        launcher_sealer.initialize_private_attempt_root(
            attempt,
            production_root=production,
            directory_creator=creator,
            attempt_root_validator=lambda _path: {"status": "PASS"},
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL contract")
def test_default_attempt_initializer_applies_the_private_acl(tmp_path):
    production = tmp_path / "production"
    production.mkdir()
    attempt = tmp_path / "secure-attempt"

    receipt = launcher_sealer.initialize_private_attempt_root(
        attempt,
        production_root=production,
    )

    assert receipt["status"] == "PASS"
    assert receipt["security"]["broad_write_count"] == 0
    assert receipt["security"]["current_user_write"] is True


def test_manifest_cli_has_no_typed_scope_or_ceiling_override_surface():
    parser = launcher_sealer.build_parser()

    args = parser.parse_args(
        [
            "prepare-manifest",
            "--stage",
            "stage0",
            "--discovery-plan",
            "discovery.json",
            "--identity-source",
            "identity.json",
            "--credential-import-receipt-source",
            "import.json",
            "--credential-reference-manifest-source",
            "references.json",
            "--event-metadata-source",
            "location-market-events.json",
            "--attempt-root",
            r"C:\attempt",
            "--lease-workload",
            "InternationalLive-stage0-unique",
            "--execution-host-profile",
            "capture_colocated_v1",
        ]
    )

    assert not hasattr(args, "target_date")
    assert not hasattr(args, "condition_id")
    assert not hasattr(args, "token_id")
    assert not hasattr(args, "budget")
    assert not hasattr(args, "max_session_seconds")

    launcher_args = parser.parse_args(
        [
            "prepare-launcher",
            "--session-manifest",
            "manifest.json",
            "--expected-session-manifest-sha256",
            "a" * 64,
            "--expected-manifest-build-receipt-sha256",
            "b" * 64,
        ]
    )
    assert launcher_args.expected_manifest_build_receipt_sha256 == "b" * 64
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "prepare-launcher",
                "--session-manifest",
                "manifest.json",
                "--expected-session-manifest-sha256",
                "a" * 64,
            ]
        )
