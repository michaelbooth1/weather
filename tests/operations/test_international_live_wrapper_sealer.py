from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from weather.operations import international_live_wrapper_sealer as sealer


NOW = datetime.fromisoformat("2026-08-23T01:00:00-04:00")
CONDITION = "0x" + "1" * 64
TOKEN = "101"
COMMIT = "a" * 64
TREE = "b" * 64


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def candidate_payload(now: datetime = NOW) -> dict:
    current = now.astimezone(timezone.utc)
    created = current - timedelta(seconds=5)
    paper_generated = current - timedelta(seconds=10)
    paper_expires = paper_generated + timedelta(seconds=120)
    payload = {
        "schema_version": "mm_live_market_candidate_plan_v0.2",
        "status": "PASS",
        "created_at_utc": created.isoformat(),
        "expires_at_utc": paper_expires.isoformat(),
        "target_date": now.date().isoformat(),
        "platform": "polymarket_global",
        "settlement_unit": "pUSD",
        "selection_is_trading_authorization": False,
        "selection_policy": {
            "expected_bootstrap_scope": {
                "condition_id": CONDITION,
                "token_id": TOKEN,
            }
        },
        "selected": {
            "condition_id": CONDITION,
            "token_id": TOKEN,
            "tick_size": 0.01,
            "order_min_size": 5,
            "stage1_intent": {
                "side": "BUY",
                "price": 0.01,
                "size": 5,
                "notional_pusd": 0.05,
                "post_only": True,
            },
            "paper_quote_proof": {
                "condition_id": CONDITION,
                "token_id": TOKEN,
                "generated_at_utc": paper_generated.isoformat(),
                "expires_at_utc": paper_expires.isoformat(),
                "quote_ttl_seconds": 120,
                "quote_permission": True,
                "live_trade_permission": False,
            },
        },
    }
    payload["plan_sha256"] = sealer._canonical_payload_sha256(
        payload, omit="plan_sha256"
    )
    return payload


class GitStub:
    def __init__(self, *, ancestry: bool = True, dirty: str = ""):
        self.ancestry = ancestry
        self.dirty = dirty
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, _root: Path, args):
        command = tuple(args)
        self.calls.append(command)
        returncode = 0
        stdout = ""
        if command == ("rev-parse", "HEAD"):
            stdout = COMMIT + "\n"
        elif command == ("rev-parse", "master"):
            stdout = COMMIT + "\n"
        elif command == ("rev-parse", "origin/master"):
            stdout = COMMIT + "\n"
        elif command == ("rev-parse", "HEAD^{tree}"):
            stdout = TREE + "\n"
        elif command == ("branch", "--show-current"):
            stdout = "master\n"
        elif command[:2] == ("merge-base", "--is-ancestor"):
            returncode = 0 if self.ancestry else 1
        elif command == ("status", "--porcelain=v1", "--untracked-files=no"):
            stdout = self.dirty
        elif command[:3] == ("rev-parse", "-q", "--verify"):
            returncode = 1
        else:
            raise AssertionError(f"unexpected Git command: {command}")
        return subprocess.CompletedProcess(args, returncode, stdout, "")


def prepare(
    tmp_path: Path,
    *,
    stage: str = "stage0",
    candidate: dict | None = None,
):
    production = tmp_path / "production"
    attempt = tmp_path / "ops" / "2026-08-23" / "attempt-1"
    attempt.mkdir(parents=True)
    python = production / "venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"test interpreter placeholder")

    repository = Path(sealer.REPO_ROOT)
    template_relatives = {
        sealer.PYTHON_TEMPLATE_PATHS[stage],
        sealer.LAUNCHER_TEMPLATE_PATH,
    }
    for relative in template_relatives:
        destination = production / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repository / relative, destination)
    for relative in set(sealer.LIVE_SOURCE_PATHS[stage]) | {
        sealer.WORKLOAD_ADMISSION_PATH
    }:
        path = production / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"reviewed source: {relative}\n", encoding="utf-8")

    credential = write_json(
        tmp_path / "credential-import-receipt.json",
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
            "checks": {"all_public_import_checks": True},
            "missing": [],
            "rollback_attempted": False,
            "rollback_ok": None,
            "source_deletion_required_after_transfer": True,
        },
    )
    credential_manifest = write_json(
        tmp_path / "credential-reference-manifest.json",
        {
            "schema_version": "mm_live_credential_reference_manifest_v0.1",
            "platform": "polymarket_global",
            "wallet_type": "gnosis_safe",
            "signature_type": "POLY_GNOSIS_SAFE",
            "signature_type_id": 2,
            "wallet_address": "0x" + "2" * 40,
            "funder_address": "0x" + "3" * 40,
            "credential_references": {
                "POLYMARKET_API_KEY_STORAGE_REF": "wincred://Weather/Test/Key",
                "POLYMARKET_API_SECRET_STORAGE_REF": "wincred://Weather/Test/Secret",
                "POLYMARKET_API_PASSPHRASE_STORAGE_REF": "wincred://Weather/Test/Passphrase",
                "POLYMARKET_PRIVATE_KEY_STORAGE_REF": "wincred://Weather/Test/PrivateKey",
            },
            "public_environment": {
                "POLYMARKET_FUNDER_ADDRESS": "0x" + "3" * 40,
            },
            "secret_values_retained": False,
            "ignored_relayers_rpc_and_self_assertions": True,
        },
    )
    identity_payload = {
        "schema_version": "mm_stage0_client_identity_v0.2",
        "platform": "polymarket_global",
        "pilot_wallet_max_funding_usdc": 100,
    }
    plan = candidate or candidate_payload()
    if stage == "stage0":
        input_paths = {
            "identity": write_json(attempt / "inputs/stage0-identity.json", identity_payload),
            "scope_plan": write_json(attempt / "inputs/stage0-scope-plan.json", plan),
            "credential_import_receipt": credential,
            "credential_reference_manifest": credential_manifest,
        }
    else:
        stage0_receipt = {
            "schema_version": "mm_live_pilot_command_receipt_v0.1",
            "status": "PASS",
            "command": "stage0",
            "target_date": NOW.date().isoformat(),
            "condition_id": CONDITION,
            "token_id": TOKEN,
            "requested_budget_pusd": 10,
            "cleanup": {"ok": True},
            "exception_type": None,
        }
        identity_name = (
            "stage1-identity.json"
            if stage == "stage1_cancel_all"
            else "stage1-dead-man-identity.json"
        )
        candidate_name = (
            "stage1-cancel-all-candidate.json"
            if stage == "stage1_cancel_all"
            else "stage1-dead-man-candidate.json"
        )
        identity_path = write_json(attempt / "inputs" / identity_name, identity_payload)
        bootstrap_path = write_json(attempt / "stage0/bootstrap.json", {"status": "PASS"})
        stage0_receipt_path = write_json(
            attempt / "stage0/command-receipt.json", stage0_receipt
        )
        stream_path = attempt / "stage0/user-stream.jsonl"
        stream_path.write_text('{"event_type":"stream_stopped"}\n', encoding="utf-8")
        stage0_wrapper = attempt / "wrappers/stage0.py"
        stage0_wrapper.parent.mkdir(parents=True, exist_ok=True)
        stage0_wrapper.write_text("# sealed stage0 wrapper\n", encoding="utf-8")
        stage0_seal = {
            "schema_version": sealer.RECEIPT_SCHEMA_VERSION,
            "status": "PASS",
            "stage": "stage0",
            "production": {"commit": COMMIT},
            "scope": {
                "target_date": NOW.date().isoformat(),
                "condition_id": CONDITION,
                "token_id": TOKEN,
                "requested_budget_pusd": 10,
            },
            "wrapper": {"path": str(stage0_wrapper), "sha256": sha256(stage0_wrapper)},
            "credential_import_receipt": {
                "path": str(credential.resolve()),
                "sha256": sha256(credential),
            },
            "credential_reference_manifest": {
                "path": str(credential_manifest.resolve()),
                "sha256": sha256(credential_manifest),
            },
        }
        stage0_seal_path = write_json(
            attempt / "seal/stage0-seal-receipt.json", stage0_seal
        )
        stage0_execution = {
            "schema_version": "international_live_fixed_scope_execution_v0.2",
            "status": "PASS",
            "stage": "stage0",
            "production_tip": COMMIT,
            "target_date": NOW.date().isoformat(),
            "condition_id": CONDITION,
            "token_id": TOKEN,
            "requested_budget_pusd": 10,
            "exception_type": None,
            "wrapper": {"path": str(stage0_wrapper), "sha256": sha256(stage0_wrapper)},
            "artifacts": {
                "bootstrap_out": {
                    "path": str(bootstrap_path.resolve()),
                    "sha256": sha256(bootstrap_path),
                },
                "command_receipt_out": {
                    "path": str(stage0_receipt_path.resolve()),
                    "sha256": sha256(stage0_receipt_path),
                },
                "user_stream_journal_out": {
                    "path": str(stream_path.resolve()),
                    "sha256": sha256(stream_path),
                },
            },
        }
        stage0_execution_path = write_json(
            attempt / "stage0/wrapper-execution-receipt.json", stage0_execution
        )
        input_paths = {
            "identity": identity_path,
            "bootstrap": bootstrap_path,
            "stage0_receipt": stage0_receipt_path,
            "stage0_seal_receipt": stage0_seal_path,
            "stage0_wrapper_execution_receipt": stage0_execution_path,
            "candidate_plan": write_json(attempt / "inputs" / candidate_name, plan),
            "credential_import_receipt": credential,
            "credential_reference_manifest": credential_manifest,
        }
    source_hashes = {
        relative: sha256(production / relative)
        for relative in sorted(
            set(sealer.LIVE_SOURCE_PATHS[stage]) | {sealer.WORKLOAD_ADMISSION_PATH}
        )
    }
    spec = {
        "schema_version": sealer.SPEC_SCHEMA_VERSION,
        "stage": stage,
        "prepared_at_local": NOW.isoformat(),
        "production": {
            "root": str(production.resolve()),
            "branch": "master",
            "commit": COMMIT,
            "tree": TREE,
            "python": str(python.resolve()),
        },
        "scope": {
            "target_date": NOW.date().isoformat(),
            "condition_id": CONDITION,
            "token_id": TOKEN,
            "requested_budget_pusd": 10,
            "run_not_before_local": (NOW - timedelta(seconds=5)).isoformat(),
            "run_not_after_local": (NOW + timedelta(seconds=60)).isoformat(),
            "attempt_root": str(attempt.resolve()),
            "lease_workload": f"live-test-{stage}-attempt-1",
        },
        "inputs": {
            role: {"path": str(path.resolve()), "sha256": sha256(path)}
            for role, path in input_paths.items()
        },
        "reviewed_status_flags": [],
        "template_sha256": {
            "python": sha256(production / sealer.PYTHON_TEMPLATE_PATHS[stage]),
            "launcher": sha256(production / sealer.LAUNCHER_TEMPLATE_PATH),
        },
        "source_sha256": source_hashes,
    }
    spec_path = write_json(attempt / "inputs" / f"{stage}-seal-spec.json", spec)
    return production, attempt, spec_path, spec


def seal(spec_path: Path, production: Path, git: GitStub | None = None):
    return sealer.seal_fixed_scope(
        spec_path,
        now=NOW,
        git_runner=git or GitStub(),
        powershell_parser=lambda _source: None,
        sdk_validator=lambda _path, _sha: {"status": "PASS"},
        template_root=production,
        sealer_repo_root=production,
    )


def test_stage0_seal_generates_only_fixed_artifacts_and_hash_sidecar(tmp_path):
    production, attempt, spec_path, _spec = prepare(tmp_path)

    result = seal(spec_path, production)

    wrapper = attempt / "wrappers/stage0.py"
    launcher = attempt / "wrappers/stage0.ps1"
    receipt_path = attempt / "seal/stage0-seal-receipt.json"
    sidecar = attempt / "seal/stage0-seal-receipt.json.sha256"
    assert result["status"] == "PASS"
    assert result["live_mutation_attempted"] is False
    assert result["credential_value_read"] is False
    wrapper_text = wrapper.read_text(encoding="utf-8")
    ast.parse(wrapper_text)
    assert "TEMPLATE_SEALED = True" in wrapper_text
    assert "__SEAL_" not in wrapper_text
    assert "live_cli.run_stage0(" in wrapper_text
    assert "live_cli.run_stage1(" not in wrapper_text
    assert "_prompt_until(expected_confirmation)" in wrapper_text
    assert wrapper_text.count("load_stage1_candidate_gate(") == 2
    assert "activate_live_sdk_overlay(" in wrapper_text
    launcher_text = launcher.read_text(encoding="utf-8-sig")
    assert "param()" in launcher_text
    assert "$args.Count -ne 0" in launcher_text
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["validation"]["candidate_ttl_and_scope"] == "PASS"
    assert receipt["production"]["required_interrupt_cleanup_ancestor"] == (
        sealer.REQUIRED_INTERRUPT_CLEANUP_ANCESTOR
    )
    assert receipt["wrapper"]["sha256"] == sha256(wrapper)
    assert receipt["launcher"]["sha256"] == sha256(launcher)
    assert sidecar.read_text(encoding="ascii") == (
        f"{sha256(receipt_path)}  {receipt_path.name}\n"
    )
    assert not (attempt / "stage0/bootstrap.json").exists()
    assert not (attempt / "stage0/command-receipt.json").exists()


def test_seal_refuses_to_overwrite_a_spent_namespace(tmp_path):
    production, attempt, spec_path, _spec = prepare(tmp_path)
    seal(spec_path, production)
    wrapper = attempt / "wrappers/stage0.py"
    before = wrapper.read_bytes()

    with pytest.raises(sealer.SealError, match="must be new"):
        seal(spec_path, production)

    assert wrapper.read_bytes() == before


def test_seal_refuses_expired_candidate_before_writing(tmp_path):
    candidate = candidate_payload()
    expired = datetime.fromisoformat(candidate["created_at_utc"]) - timedelta(seconds=1)
    candidate["expires_at_utc"] = expired.isoformat()
    candidate["plan_sha256"] = sealer._canonical_payload_sha256(
        candidate, omit="plan_sha256"
    )
    production, attempt, spec_path, _spec = prepare(tmp_path, candidate=candidate)

    with pytest.raises(sealer.SealError, match="candidate plan gate failed"):
        seal(spec_path, production)

    assert not (attempt / "wrappers/stage0.py").exists()


def test_seal_refuses_input_hash_mismatch_before_writing(tmp_path):
    production, attempt, spec_path, spec = prepare(tmp_path)
    spec["inputs"]["identity"]["sha256"] = "0" * 64
    write_json(spec_path, spec)

    with pytest.raises(sealer.SealError, match="hash-mismatched"):
        seal(spec_path, production)

    assert not (attempt / "wrappers/stage0.py").exists()


def test_seal_refuses_source_hash_mismatch_before_writing(tmp_path):
    production, attempt, spec_path, spec = prepare(tmp_path)
    relative = sealer.LIVE_SOURCE_PATHS["stage0"][0]
    spec["source_sha256"][relative] = "0" * 64
    write_json(spec_path, spec)

    with pytest.raises(sealer.SealError, match="source hash changed"):
        seal(spec_path, production)

    assert not (attempt / "wrappers/stage0.py").exists()


def test_seal_refuses_without_interrupt_cleanup_ancestry(tmp_path):
    production, attempt, spec_path, _spec = prepare(tmp_path)

    with pytest.raises(sealer.SealError, match="interrupt-cleanup"):
        seal(spec_path, production, GitStub(ancestry=False))

    assert not (attempt / "wrappers/stage0.py").exists()


def test_stage1_seal_is_cancel_all_only_and_binds_stage0(tmp_path):
    production, attempt, spec_path, _spec = prepare(
        tmp_path, stage="stage1_cancel_all"
    )

    result = seal(spec_path, production)

    wrapper = attempt / "wrappers/stage1-cancel-all.py"
    text = wrapper.read_text(encoding="utf-8")
    assert result["stage"] == "stage1_cancel_all"
    assert "live_cli.run_stage1(" in text
    assert "CANCELLATION_MODE = 'cancel_all'" in text
    assert "STAGE_NAME = 'stage1_cancel_all'" in text
    assert "live_cli.run_stage0(" not in text
    assert "stage2" not in text.lower()
    assert "_prompt_until(expected_confirmation)" in text
    assert "_assert_window_current()" in text
    assert "activate_live_sdk_overlay(" in text
    receipt = json.loads(
        (attempt / "seal/stage1-cancel-all-seal-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["scope"]["cancellation_mode"] == "cancel_all"


def test_stage1_dead_man_seal_is_distinct_and_fixed(tmp_path):
    production, attempt, spec_path, _spec = prepare(
        tmp_path, stage="stage1_dead_man"
    )

    result = seal(spec_path, production)

    wrapper = attempt / "wrappers/stage1-dead-man.py"
    text = wrapper.read_text(encoding="utf-8")
    assert result["stage"] == "stage1_dead_man"
    assert "CANCELLATION_MODE = 'dead_man'" in text
    assert "STAGE_NAME = 'stage1_dead_man'" in text
    assert "submit_deadline_utc=SCOPE[\"run_not_after_local\"]" in text
    receipt = json.loads(
        (attempt / "seal/stage1-dead-man-seal-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["scope"]["cancellation_mode"] == "dead_man"


def test_stage1_seal_refuses_stage0_scope_mismatch(tmp_path):
    production, attempt, spec_path, _spec = prepare(
        tmp_path, stage="stage1_cancel_all"
    )
    receipt_path = attempt / "stage0/command-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["token_id"] = "999"
    write_json(receipt_path, receipt)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["inputs"]["stage0_receipt"]["sha256"] = sha256(receipt_path)
    write_json(spec_path, spec)

    with pytest.raises(sealer.SealError, match="Stage 0 receipt"):
        seal(spec_path, production)

    assert not (attempt / "wrappers/stage1-cancel-all.py").exists()


def test_stage1_seal_refuses_bootstrap_not_bound_by_stage0_execution(tmp_path):
    production, attempt, spec_path, spec = prepare(
        tmp_path, stage="stage1_cancel_all"
    )
    bootstrap = attempt / "stage0/bootstrap.json"
    write_json(bootstrap, {"status": "PASS", "replacement": True})
    spec["inputs"]["bootstrap"]["sha256"] = sha256(bootstrap)
    write_json(spec_path, spec)

    with pytest.raises(sealer.SealError, match="lineage"):
        seal(spec_path, production)


def test_seal_refuses_nonpass_credential_import_receipt(tmp_path):
    production, _attempt, spec_path, spec = prepare(tmp_path)
    receipt = Path(spec["inputs"]["credential_import_receipt"]["path"])
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["status"] = "FAIL"
    write_json(receipt, payload)
    spec["inputs"]["credential_import_receipt"]["sha256"] = sha256(receipt)
    write_json(spec_path, spec)

    with pytest.raises(sealer.SealError, match="clean PASS"):
        seal(spec_path, production)


def test_seal_refuses_incomplete_credential_reference_manifest(tmp_path):
    production, _attempt, spec_path, spec = prepare(tmp_path)
    manifest = Path(spec["inputs"]["credential_reference_manifest"]["path"])
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    del payload["credential_references"]["POLYMARKET_API_SECRET_STORAGE_REF"]
    write_json(manifest, payload)
    spec["inputs"]["credential_reference_manifest"]["sha256"] = sha256(manifest)
    write_json(spec_path, spec)

    with pytest.raises(sealer.SealError, match="credential references"):
        seal(spec_path, production)


@pytest.mark.parametrize(
    "template_name",
    ["stage0.py.tmpl", "stage1_cancel_all.py.tmpl"],
)
def test_repository_templates_refuse_before_weather_import(template_name, tmp_path):
    template = Path(sealer.REPO_ROOT) / "scripts/ops/international_live_templates" / template_name
    source = template.read_text(encoding="utf-8")
    tree = ast.parse(source)
    sealed_assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "TEMPLATE_SEALED" for target in node.targets)
    ]
    assert len(sealed_assignments) == 1
    assert isinstance(sealed_assignments[0].value, ast.Constant)
    assert sealed_assignments[0].value.value is False
    assert source.index("_assert_sealed()") < source.index("from weather.market")


def test_inventory_is_read_only_and_reports_ancestry_state(tmp_path):
    production, attempt, _spec_path, _spec = prepare(tmp_path)
    before = sorted(path.relative_to(attempt) for path in attempt.rglob("*"))

    result = sealer.build_public_inventory(
        "stage0", production, git_runner=GitStub(ancestry=False)
    )

    after = sorted(path.relative_to(attempt) for path in attempt.rglob("*"))
    assert result["status"] == "BLOCK"
    assert result["production"]["interrupt_cleanup_ancestor_integrated"] is False
    assert result["live_mutation_attempted"] is False
    assert before == after
