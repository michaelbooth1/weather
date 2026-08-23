from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import subprocess

import pytest

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


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(tmp_path: Path):
    repo = tmp_path / "production"
    python = repo / "venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"not invoked in preparation tests")
    source = repo / "src/weather/operations/international_live_session_runner.py"
    source.parent.mkdir(parents=True)
    source.write_text("# reviewed runner source\n", encoding="utf-8")
    for relative in runner.SESSION_BOOTSTRAP_PATHS:
        bootstrap_source = repo / relative
        bootstrap_source.parent.mkdir(parents=True, exist_ok=True)
        if not bootstrap_source.exists():
            bootstrap_source.write_text(
                f"# reviewed {relative}\n", encoding="utf-8"
            )
    template = repo / "scripts/ops/international_live_templates/fixed_session_launcher.ps1.tmpl"
    template.parent.mkdir(parents=True)
    shutil.copyfile(launcher_sealer.TEMPLATE_PATH, template)
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    manifest = attempt / "inputs/stage0-session-manifest.json"
    manifest.parent.mkdir(parents=True)
    payload = {
        "schema_version": runner.SESSION_SCHEMA_VERSION,
        "stage": "stage0",
        "production": {"root": str(repo.resolve()), "python": str(python.resolve())},
        "scope": {"attempt_root": str(attempt.resolve())},
        "production_python_sha256": sha(python),
        "session_bootstrap_sha256": {
            relative: sha(repo / relative)
            for relative in runner.SESSION_BOOTSTRAP_PATHS
        },
    }
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    sidecar = manifest.with_suffix(manifest.suffix + ".sha256")
    sidecar.write_text(f"{sha(manifest)}  {manifest.name}\n", encoding="ascii")
    return repo, template, attempt, manifest


def prepare(repo, template, manifest):
    return launcher_sealer.prepare_fixed_session_launcher(
        manifest,
        sha(manifest),
        repo_root=repo,
        template_path=template,
        powershell_parser=lambda _source: None,
        attempt_root_validator=lambda path: {"status": "PASS", "path": str(path)},
    )


def test_preparer_writes_no_argument_hash_bound_launcher_and_review_receipt(tmp_path):
    repo, template, attempt, manifest = fixture(tmp_path)

    receipt = prepare(repo, template, manifest)

    launcher = Path(receipt["launcher"]["path"])
    text = launcher.read_text(encoding="utf-8-sig")
    assert receipt["status"] == "PASS"
    assert receipt["no_argument_surface"] is True
    assert "param()" in text
    assert "$MyInvocation.UnboundArguments.Count -ne 0" in text
    assert sha(manifest) in text
    assert "--expected-session-manifest-sha256" in text
    assert "[IO.FileShare]::Read" in text
    assert "source_sha256.psobject.Properties" in text
    assert "Get-ChildItem -LiteralPath $attemptRoot -File -Recurse" in text
    assert "& $python -I -c" in text
    assert "PYTHONPATH" not in text
    assert receipt["production_python"]["sha256"] == sha(
        repo / "venv/Scripts/python.exe"
    )
    assert set(receipt["session_bootstrap_sha256"]) == set(
        runner.SESSION_BOOTSTRAP_PATHS
    )
    assert {
        "src/weather/operations/international_live_session_runner.py",
        "src/weather/operations/international_live_wrapper_sealer.py",
        "src/weather/operations/live_path_security.py",
    }.issubset(receipt["session_bootstrap_sha256"])
    assert (attempt / "session/stage0-launcher-review.json.sha256").is_file()


def test_no_argument_launcher_rejects_manifest_and_sidecar_rewrite(tmp_path):
    repo, template, attempt, manifest = fixture(tmp_path)
    receipt = prepare(repo, template, manifest)
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


def discovery_payload(*, constrained: bool = False) -> dict:
    created = NOW.astimezone(timezone.utc) - timedelta(seconds=5)
    paper_generated = NOW.astimezone(timezone.utc) - timedelta(seconds=10)
    expires = paper_generated + timedelta(seconds=120)
    payload = {
        "schema_version": fixed_sealer.CANDIDATE_SCHEMA_VERSION,
        "status": "PASS",
        "created_at_utc": created.isoformat(),
        "expires_at_utc": expires.isoformat(),
        "target_date": NOW.date().isoformat(),
        "platform": "polymarket_global",
        "settlement_unit": "pUSD",
        "selection_is_trading_authorization": False,
        "secret_values_retained": False,
        "selection_policy": {
            "expected_bootstrap_scope": {
                "condition_id": CONDITION if constrained else None,
                "token_id": TOKEN if constrained else None,
            }
        },
        "selected": {
            "condition_id": CONDITION,
            "token_id": TOKEN,
            "paper_quote_proof": {
                "condition_id": CONDITION,
                "token_id": TOKEN,
                "generated_at_utc": paper_generated.isoformat(),
                "expires_at_utc": expires.isoformat(),
                "quote_ttl_seconds": 120,
            },
        },
    }
    payload["plan_sha256"] = fixed_sealer._canonical_payload_sha256(
        payload, omit="plan_sha256"
    )
    return payload


def manifest_builder_fixture(tmp_path: Path, *, constrained=False):
    production = tmp_path / "production"
    python = production / "venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"reviewed production interpreter")
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
            "schema_version": "mm_live_credential_import_receipt_v0.1",
            "status": "PASS",
            "platform": "polymarket_global",
            "source_outside_repository_verified": True,
            "source_acl_private_confirmed": True,
            "credential_value_count_expected": 4,
            "credential_value_count_written": 4,
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
    discovery = write_json(
        sources / "discovery.json",
        discovery_payload(constrained=constrained),
    )
    attempt = tmp_path / "attempt"
    for name in launcher_sealer.ATTEMPT_DIRECTORIES:
        (attempt / name).mkdir(parents=True, exist_ok=True)

    def inventory(stage, root):
        root = Path(root)
        source_paths = set(fixed_sealer.LIVE_SOURCE_PATHS[stage]) | {
            fixed_sealer.WORKLOAD_ADMISSION_PATH
        }
        return {
            "schema_version": fixed_sealer.INVENTORY_SCHEMA_VERSION,
            "status": "PASS",
            "stage": stage,
            "production": {
                "root": str(root.resolve()),
                "branch": "master",
                "commit": "a" * 40,
                "tree": "b" * 40,
                "object_format": "sha1",
                "python": str((root / "venv/Scripts/python.exe").resolve()),
                "python_sha256": sha(root / "venv/Scripts/python.exe"),
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
        "attempt_root": prepared["attempt"],
        "lease_workload": workload,
        "production_root": prepared["production"],
        "now": NOW,
        "inventory_builder": prepared["inventory"],
        "git_state_validator": lambda _production: None,
        "attempt_root_validator": lambda path: {
            "status": "PASS",
            "path": str(path),
        },
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
        "max_session_seconds": 120,
    }
    assert set(manifest["inputs"]) == {
        "identity",
        "credential_import_receipt",
        "credential_reference_manifest",
    }
    for role, source_key in {
        "identity": "identity",
        "credential_import_receipt": "credential_receipt",
        "credential_reference_manifest": "credential_manifest",
    }.items():
        copied = Path(manifest["inputs"][role]["path"])
        assert copied.is_relative_to(prepared["attempt"])
        assert copied.read_bytes() == Path(prepared[source_key]).read_bytes()
        assert manifest["inputs"][role]["sha256"] == sha(copied)
    assert Path(receipt["staged_public_inputs"]["discovery_plan"]["path"]).read_bytes() == prepared[
        "discovery"
    ].read_bytes()
    assert Path(receipt["build_receipt_path"]).is_file()
    launcher_receipt = launcher_sealer.prepare_fixed_session_launcher(
        manifest_path,
        sha(manifest_path),
        repo_root=prepared["production"],
        template_path=prepared["outer_template"],
        powershell_parser=lambda _source: None,
        attempt_root_validator=lambda path: {
            "status": "PASS",
            "path": str(path),
        },
    )
    assert launcher_receipt["status"] == "PASS"
    assert launcher_receipt["session_manifest"]["sha256"] == sha(manifest_path)


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
        match="secret material",
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
            inventory_builder=lambda _stage, _root: inventory,
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
            "--attempt-root",
            r"C:\attempt",
            "--lease-workload",
            "InternationalLive-stage0-unique",
        ]
    )

    assert not hasattr(args, "target_date")
    assert not hasattr(args, "condition_id")
    assert not hasattr(args, "token_id")
    assert not hasattr(args, "budget")
    assert not hasattr(args, "max_session_seconds")
