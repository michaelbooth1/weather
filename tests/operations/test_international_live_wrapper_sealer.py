from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from weather.operations import international_live_time_window as time_window
from weather.operations import international_live_wrapper_sealer as sealer


NOW = datetime.fromisoformat("2026-08-23T01:00:00-04:00")
CONDITION = "0x" + "1" * 64
TOKEN = "101"
COMMIT = "a" * 40
TREE = "b" * 40


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
    def __init__(
        self,
        *,
        ancestry: bool = True,
        dirty: str = "",
        commit: str = COMMIT,
        tree: str = TREE,
    ):
        self.ancestry = ancestry
        self.dirty = dirty
        self.commit = commit
        self.tree = tree
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, _root: Path, args):
        command = tuple(args)
        self.calls.append(command)
        returncode = 0
        stdout = ""
        if command == ("rev-parse", "HEAD"):
            stdout = self.commit + "\n"
        elif command == ("rev-parse", "--show-object-format"):
            stdout = "sha1\n"
        elif command == ("rev-parse", "master"):
            stdout = self.commit + "\n"
        elif command == ("rev-parse", "origin/master"):
            stdout = self.commit + "\n"
        elif command == ("rev-parse", "HEAD^{tree}"):
            stdout = self.tree + "\n"
        elif command == ("branch", "--show-current"):
            stdout = "master\n"
        elif command[:2] == ("merge-base", "--is-ancestor"):
            returncode = 0 if self.ancestry else 1
        elif command == ("status", "--porcelain=v1", "--untracked-files=all"):
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
            "checks": {
                name: True
                for name in sealer.EXPECTED_CREDENTIAL_IMPORT_CHECKS
            },
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
                **sealer.EXPECTED_CREDENTIAL_REFERENCES,
            },
            "public_environment": {
                "POLYMARKET_FUNDER_ADDRESS": "0x" + "3" * 40,
            },
            "secret_values_retained": False,
            "ignored_relayers_rpc_and_self_assertions": True,
        },
    )
    identity_payload = {
        "schema_version": "mm_stage0_client_identity_v0.3",
        "operator_authorization": "INTERNATIONAL_POLYMARKET_STAGE0_HEARTBEAT_AND_ACCOUNT_WIDE_CANCEL_ALL_NO_ORDER",
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
            "schema_version": "mm_live_pilot_command_receipt_v0.2",
            "status": "PASS",
            "command": "stage0",
            "target_date": NOW.date().isoformat(),
            "condition_id": CONDITION,
            "token_id": TOKEN,
            "requested_budget_pusd": 10,
            "cleanup": {"ok": True},
            "credential_values_read_in_memory": True,
            "exchange_mutation_attempted": True,
            "order_submit_attempted": False,
            "authenticated_exchange_write_attempted": True,
            "credential_topology": {
                "manifest_wallet_address": "0x" + "2" * 40,
                "derived_signer_matches_manifest": True,
                "api_owner_matches_manifest": True,
                "order_signer_matches_manifest": True,
                "funder_matches_identity": True,
            },
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
        stage0_launcher = attempt / "wrappers/stage0.ps1"
        stage0_launcher.write_text("# sealed stage0 launcher\n", encoding="utf-8")
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
                "attempt_root": str(attempt.resolve()),
            },
            "wrapper": {"path": str(stage0_wrapper), "sha256": sha256(stage0_wrapper)},
            "launcher": {"path": str(stage0_launcher), "sha256": sha256(stage0_launcher)},
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
            "schema_version": "international_live_fixed_scope_execution_v0.4",
            "status": "PASS",
            "stage": "stage0",
            "phase": "complete",
            "production_tip": COMMIT,
            "target_date": NOW.date().isoformat(),
            "condition_id": CONDITION,
            "token_id": TOKEN,
            "requested_budget_pusd": 10,
            "exception_type": None,
            "credential_values_read_in_memory": True,
            "live_mutation_attempted": True,
            "order_submit_attempted": False,
            "authenticated_exchange_write_attempted": True,
            "host_attestations": [
                {
                    "checked_at_local": NOW.isoformat(),
                    "status_json_sha256": "9" * 64,
                    "status_flag_sha256": [],
                }
                for _index in range(2)
            ],
            "wrapper": {"path": str(stage0_wrapper), "sha256": sha256(stage0_wrapper)},
            "artifacts": {
                "doctor_receipt_out": {
                    "path": str(
                        write_json(
                            attempt / "stage0/doctor-receipt.json", {"status": "PASS"}
                        ).resolve()
                    ),
                    "sha256": sha256(attempt / "stage0/doctor-receipt.json"),
                },
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
        stage0_manifest = write_json(
            attempt / "inputs/stage0-session-manifest.json", {"status": "PASS"}
        )
        stage0_manifest_sidecar = stage0_manifest.with_suffix(
            stage0_manifest.suffix + ".sha256"
        )
        stage0_manifest_sidecar.write_text(
            f"{sha256(stage0_manifest)}  {stage0_manifest.name}\n", encoding="ascii"
        )
        stage0_composition = write_json(
            attempt / "session/stage0-composition-receipt.json", {"status": "PASS"}
        )
        stage0_intent = write_json(
            attempt / "session/stage0-run-intent.json", {"status": "ARMED"}
        )
        stage0_run = write_json(
            attempt / "session/stage0-run-receipt.json",
            {
                "schema_version": "international_live_session_run_v0.3",
                "status": "PASS",
                "stage": "stage0",
                "live_mutation_attempted": True,
                "order_submit_attempted": False,
                "authenticated_exchange_write_attempted": True,
                "credential_values_read_in_memory": True,
                "session_manifest": {
                    "path": str(stage0_manifest.resolve()),
                    "sha256": sha256(stage0_manifest),
                    "sidecar_path": str(stage0_manifest_sidecar.resolve()),
                    "sidecar_sha256": sha256(stage0_manifest_sidecar),
                },
                "composition_receipt": {
                    "path": str(stage0_composition.resolve()),
                    "sha256": sha256(stage0_composition),
                },
                "run_intent": {
                    "path": str(stage0_intent.resolve()),
                    "sha256": sha256(stage0_intent),
                },
                "seal_receipt": {
                    "path": str(stage0_seal_path.resolve()),
                    "sha256": sha256(stage0_seal_path),
                },
                "child_execution": {
                    "validation": "PASS",
                    "status": "PASS",
                    "phase": "complete",
                    "path": str(stage0_execution_path.resolve()),
                    "sha256": sha256(stage0_execution_path),
                },
                "wrapper": stage0_seal["wrapper"],
                "launcher": stage0_seal["launcher"],
            },
        )
        stage0_run_sidecar = attempt / "session/stage0-run-receipt.json.sha256"
        stage0_run_sidecar.write_text(
            f"{sha256(stage0_run)}  {stage0_run.name}\n", encoding="ascii"
        )
        input_paths = {
            "identity": identity_path,
            "bootstrap": bootstrap_path,
            "stage0_receipt": stage0_receipt_path,
            "stage0_seal_receipt": stage0_seal_path,
            "stage0_run_receipt": stage0_run,
            "stage0_run_receipt_sidecar": stage0_run_sidecar,
            "stage0_wrapper_execution_receipt": stage0_execution_path,
            "candidate_plan": write_json(attempt / "inputs" / candidate_name, plan),
            "credential_import_receipt": credential,
            "credential_reference_manifest": credential_manifest,
        }
        if stage == "stage1_dead_man":
            cancel_candidate = write_json(
                attempt / "inputs/stage1-cancel-all-candidate.json",
                candidate_payload(),
            )
            cancel_wrapper = attempt / "wrappers/stage1-cancel-all.py"
            cancel_wrapper.write_text("# sealed cancel wrapper\n", encoding="utf-8")
            cancel_launcher = attempt / "wrappers/stage1-cancel-all.ps1"
            cancel_launcher.write_text("# sealed cancel launcher\n", encoding="utf-8")
            cancel_stream = attempt / "stage1-cancel-all/user-stream.jsonl"
            cancel_stream.parent.mkdir(parents=True, exist_ok=True)
            cancel_stream.write_text(
                '{"event_type":"stream_stopped"}\n', encoding="utf-8"
            )
            cancel_doctor = write_json(
                attempt / "stage1-cancel-all/doctor-receipt.json", {"status": "PASS"}
            )
            cancel_journal = attempt / "stage1-cancel-all/lifecycle.jsonl"
            cancel_journal.parent.mkdir(parents=True, exist_ok=True)
            cancel_journal.write_text('{"event_type":"probe_passed"}\n', encoding="utf-8")
            cancel_result = write_json(
                attempt / "stage1-cancel-all/result.json",
                {
                    "schema_version": "mm_live_lifecycle_probe_v0.2",
                    "status": "PASS",
                    "cancellation_mode": "cancel_all",
                    "condition_id": CONDITION,
                    "token_id": TOKEN,
                    "candidate_plan_sha256": sha256(cancel_candidate),
                    "order_id": "cancel-order",
                    "placement_status": "live",
                    "zero_open_orders_verified": True,
                    "zero_positions_verified": True,
                    "no_trade_lifecycle_event_observed": True,
                    "terminal_user_event_observed": True,
                    "cancel_response_present": True,
                    "journal_path": str(cancel_journal.resolve()),
                    "journal_sha256": sha256(cancel_journal),
                },
            )
            cancel_command = write_json(
                attempt / "stage1-cancel-all/command-receipt.json",
                {
                    "schema_version": "mm_live_pilot_command_receipt_v0.2",
                    "status": "PASS",
                    "command": "stage1",
                    "cancellation_mode": "cancel_all",
                    "target_date": NOW.date().isoformat(),
                    "condition_id": CONDITION,
                    "token_id": TOKEN,
                    "requested_budget_pusd": 10,
                    "credential_values_read_in_memory": True,
                    "exchange_mutation_attempted": True,
                    "order_submit_attempted": True,
                    "authenticated_exchange_write_attempted": True,
                    "credential_topology": {
                        "manifest_wallet_address": "0x" + "2" * 40,
                        "derived_signer_matches_manifest": True,
                        "api_owner_matches_manifest": True,
                        "order_signer_matches_manifest": True,
                        "funder_matches_identity": True,
                    },
                    "cleanup": {"ok": True},
                    "exception_type": None,
                    "paths": {
                        "result": str(cancel_result.resolve()),
                        "receipt": str(
                            (attempt / "stage1-cancel-all/command-receipt.json").resolve()
                        ),
                        "user_stream_journal": str(cancel_stream.resolve()),
                        "lifecycle_journal": str(cancel_journal.resolve()),
                    },
                },
            )
            cancel_execution = write_json(
                attempt / "stage1-cancel-all/wrapper-execution-receipt.json",
                {
                    "schema_version": "international_live_fixed_scope_execution_v0.4",
                    "status": "PASS",
                    "stage": "stage1_cancel_all",
                    "phase": "complete",
                    "production_tip": COMMIT,
                    "target_date": NOW.date().isoformat(),
                    "condition_id": CONDITION,
                    "token_id": TOKEN,
                    "requested_budget_pusd": 10,
                    "exception_type": None,
                    "live_mutation_attempted": True,
                    "order_submit_attempted": True,
                    "authenticated_exchange_write_attempted": True,
                    "credential_values_read_in_memory": True,
                    "wrapper": {
                        "path": str(cancel_wrapper.resolve()),
                        "sha256": sha256(cancel_wrapper),
                    },
                    "launcher": {
                        "path": str(cancel_launcher.resolve()),
                        "sha256": sha256(cancel_launcher),
                    },
                    "artifacts": {
                        "doctor_receipt_out": {
                            "path": str(cancel_doctor.resolve()),
                            "sha256": sha256(cancel_doctor),
                        },
                        "result_out": {
                            "path": str(cancel_result.resolve()),
                            "sha256": sha256(cancel_result),
                        },
                        "command_receipt_out": {
                            "path": str(cancel_command.resolve()),
                            "sha256": sha256(cancel_command),
                        },
                        "user_stream_journal_out": {
                            "path": str(cancel_stream.resolve()),
                            "sha256": sha256(cancel_stream),
                        },
                        "lifecycle_journal_out": {
                            "path": str(cancel_journal.resolve()),
                            "sha256": sha256(cancel_journal),
                        },
                    },
                },
            )
            cancel_seal = write_json(
                attempt / "seal/stage1-cancel-all-seal-receipt.json",
                {
                    "schema_version": sealer.RECEIPT_SCHEMA_VERSION,
                    "status": "PASS",
                    "stage": "stage1_cancel_all",
                    "production": {"commit": COMMIT},
                    "scope": {
                        "target_date": NOW.date().isoformat(),
                        "condition_id": CONDITION,
                        "token_id": TOKEN,
                        "requested_budget_pusd": 10,
                        "cancellation_mode": "cancel_all",
                        "attempt_root": str(attempt.resolve()),
                    },
                    "wrapper": {
                        "path": str(cancel_wrapper.resolve()),
                        "sha256": sha256(cancel_wrapper),
                    },
                    "launcher": {
                        "path": str(cancel_launcher.resolve()),
                        "sha256": sha256(cancel_launcher),
                    },
                    "inputs": [
                        {
                            "role": "candidate_plan",
                            "path": str(cancel_candidate.resolve()),
                            "sha256": sha256(cancel_candidate),
                        }
                    ],
                },
            )
            cancel_manifest = write_json(
                attempt / "inputs/stage1_cancel_all-session-manifest.json",
                {"status": "PASS"},
            )
            cancel_manifest_sidecar = cancel_manifest.with_suffix(
                cancel_manifest.suffix + ".sha256"
            )
            cancel_manifest_sidecar.write_text(
                f"{sha256(cancel_manifest)}  {cancel_manifest.name}\n",
                encoding="ascii",
            )
            cancel_composition = write_json(
                attempt / "session/stage1_cancel_all-composition-receipt.json",
                {"status": "PASS"},
            )
            cancel_intent = write_json(
                attempt / "session/stage1_cancel_all-run-intent.json",
                {"status": "ARMED"},
            )
            cancel_run = write_json(
                attempt / "session/stage1_cancel_all-run-receipt.json",
                {
                    "schema_version": "international_live_session_run_v0.3",
                    "status": "PASS",
                    "stage": "stage1_cancel_all",
                    "live_mutation_attempted": True,
                    "order_submit_attempted": True,
                    "authenticated_exchange_write_attempted": True,
                    "credential_values_read_in_memory": True,
                    "candidate_sha256": sha256(cancel_candidate),
                    "session_manifest": {
                        "path": str(cancel_manifest.resolve()),
                        "sha256": sha256(cancel_manifest),
                        "sidecar_path": str(cancel_manifest_sidecar.resolve()),
                        "sidecar_sha256": sha256(cancel_manifest_sidecar),
                    },
                    "composition_receipt": {
                        "path": str(cancel_composition.resolve()),
                        "sha256": sha256(cancel_composition),
                    },
                    "run_intent": {
                        "path": str(cancel_intent.resolve()),
                        "sha256": sha256(cancel_intent),
                    },
                    "seal_receipt": {
                        "path": str(cancel_seal.resolve()),
                        "sha256": sha256(cancel_seal),
                    },
                    "wrapper": {
                        "path": str(cancel_wrapper.resolve()),
                        "sha256": sha256(cancel_wrapper),
                    },
                    "launcher": {
                        "path": str(cancel_launcher.resolve()),
                        "sha256": sha256(cancel_launcher),
                    },
                    "child_execution": {
                        "validation": "PASS",
                        "status": "PASS",
                        "phase": "complete",
                        "path": str(cancel_execution.resolve()),
                        "sha256": sha256(cancel_execution),
                    },
                },
            )
            cancel_run_sidecar = attempt / "session/stage1_cancel_all-run-receipt.json.sha256"
            cancel_run_sidecar.write_text(
                f"{sha256(cancel_run)}  {cancel_run.name}\n", encoding="ascii"
            )
            input_paths.update(
                {
                    "cancel_all_seal_receipt": cancel_seal,
                    "cancel_all_run_receipt": cancel_run,
                    "cancel_all_run_receipt_sidecar": cancel_run_sidecar,
                    "cancel_all_wrapper_execution_receipt": cancel_execution,
                    "cancel_all_command_receipt": cancel_command,
                    "cancel_all_result": cancel_result,
                    "cancel_all_lifecycle_journal": cancel_journal,
                }
            )
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


def seal(
    spec_path: Path,
    production: Path,
    git: GitStub | None = None,
    *,
    now: datetime = NOW,
):
    return sealer.seal_fixed_scope(
        spec_path,
        now=now,
        git_runner=git or GitStub(),
        powershell_parser=lambda _source: None,
        sdk_validator=lambda _path, _sha: {"status": "PASS"},
        attempt_root_validator=lambda path: {
            "status": "PASS",
            "path": str(path),
        },
        template_root=production,
        sealer_repo_root=production,
    )


@pytest.mark.parametrize(
    ("start", "stop", "expected"),
    [
        ("2026-08-23T00:29:59-04:00", "2026-08-23T00:31:00-04:00", False),
        ("2026-08-23T00:30:00-04:00", "2026-08-23T00:31:00-04:00", True),
        ("2026-08-23T08:59:00-04:00", "2026-08-23T08:59:39-04:00", True),
        ("2026-08-23T08:59:00-04:00", "2026-08-23T08:59:40-04:00", True),
        (
            "2026-08-23T08:59:00-04:00",
            "2026-08-23T08:59:40.000001-04:00",
            False,
        ),
        ("2026-08-23T08:59:00-04:00", "2026-08-23T09:00:00-04:00", False),
        ("2026-08-23T09:00:00-04:00", "2026-08-23T09:01:00-04:00", False),
        ("2026-08-23T11:59:00-04:00", "2026-08-23T12:01:00-04:00", False),
        ("2026-08-23T17:59:00-04:00", "2026-08-23T18:01:00-04:00", False),
        ("2026-08-23T23:59:00-04:00", "2026-08-24T00:01:00-04:00", False),
    ],
)
def test_supported_execution_window_has_exact_toronto_boundaries(
    start, stop, expected
):
    assert time_window.execution_window_is_supported(
        datetime.fromisoformat(start),
        datetime.fromisoformat(stop),
        target_date="2026-08-23",
    ) is expected


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
    assert (
        "INTERNATIONAL_POLYMARKET_STAGE0_"
        "HEARTBEAT_AND_ACCOUNT_WIDE_CANCEL_ALL_NO_ORDER"
        in wrapper_text
    )
    assert '"order_submit_expected": False' in wrapper_text
    assert '"authenticated_heartbeat_write_expected": True' in wrapper_text
    assert '"cancel_all_cleanup_expected": True' in wrapper_text
    assert '"cancel_all_scope": "ACCOUNT_WIDE"' in wrapper_text
    assert '"cleanup_reserve_seconds": 20' in wrapper_text
    assert '"contained_process_end_local"' in wrapper_text
    host_guard = wrapper_text.split("def _assert_host_state()", 1)[1].split(
        "\ndef ", 1
    )[0]
    assert "_assert_window_current()" in host_guard
    assert 'ZoneInfo("America/Toronto")' in wrapper_text
    assert wrapper_text.count("load_stage1_candidate_gate(") == 2
    assert "activate_live_sdk_overlay(" in wrapper_text
    main_body = wrapper_text.split("def main()", 1)[1]
    assert main_body.index("live_cli.run_doctor(") < main_body.index(
        "_prompt_until(expected_confirmation)"
    )
    assert main_body.index("_prompt_until(expected_confirmation)") < main_body.index(
        "live_cli.run_stage0("
    )
    assert wrapper_text.split("def main()", 1)[1].count("_assert_host_state()") == 2
    launcher_text = launcher.read_text(encoding="utf-8-sig")
    assert "param()" in launcher_text
    assert "$MyInvocation.UnboundArguments.Count -ne 0" in launcher_text
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


@pytest.mark.parametrize(
    "current",
    [
        datetime.fromisoformat("2026-08-23T00:29:30-04:00"),
        datetime.fromisoformat("2026-08-23T08:59:30-04:00"),
        datetime.fromisoformat("2026-08-23T12:00:00-04:00"),
        datetime.fromisoformat("2026-08-23T18:00:00-04:00"),
        datetime.fromisoformat("2026-08-23T23:59:00-04:00"),
    ],
)
def test_seal_refuses_ineligible_toronto_window_before_outputs(tmp_path, current):
    production, attempt, spec_path, spec = prepare(
        tmp_path,
        candidate=candidate_payload(current),
    )
    spec["prepared_at_local"] = current.isoformat()
    spec["scope"].update(
        target_date=current.date().isoformat(),
        run_not_before_local=(current - timedelta(seconds=5)).isoformat(),
        run_not_after_local=(current + timedelta(seconds=60)).isoformat(),
    )
    write_json(spec_path, spec)

    with pytest.raises(sealer.SealError, match="00:30-09:00 America/Toronto"):
        seal(spec_path, production, now=current)

    for relative in sealer.OUTPUT_LAYOUTS["stage0"].values():
        assert not (attempt / relative).exists()


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


def test_seal_refuses_untracked_python_shadow_path(tmp_path):
    production, attempt, spec_path, _spec = prepare(tmp_path)

    with pytest.raises(sealer.SealError, match="untracked"):
        seal(spec_path, production, GitStub(dirty="?? sitecustomize.py\n"))

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
    assert '"cleanup_reserve_seconds": 20' in text
    assert '"contained_process_end_local"' in text
    host_guard = text.split("def _assert_host_state()", 1)[1].split("\ndef ", 1)[0]
    assert "_assert_window_current()" in host_guard
    assert 'ZoneInfo("America/Toronto")' in text
    assert "activate_live_sdk_overlay(" in text
    assert text.split("def main()", 1)[1].count("_assert_host_state()") == 2
    assert "pre_submit_attestor=_assert_host_state" in text
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
    assert '"stage": STAGE_NAME' in text
    assert '"stage": "stage1_cancel_all"' not in text
    assert "submit_deadline_utc=SCOPE[\"run_not_after_local\"]" in text
    assert 'float(result.get("cancellation_elapsed_seconds")) >= 10' in text
    assert 'float(result.get("cancellation_elapsed_seconds")) <= 15' in text
    assert "cancel_all" in text
    receipt = json.loads(
        (attempt / "seal/stage1-dead-man-seal-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["scope"]["cancellation_mode"] == "dead_man"


def test_stage1_dead_man_refuses_failed_cancel_all_predecessor(tmp_path):
    production, _attempt, spec_path, spec = prepare(
        tmp_path, stage="stage1_dead_man"
    )
    run_path = Path(spec["inputs"]["cancel_all_run_receipt"]["path"])
    run = json.loads(run_path.read_text())
    run["status"] = "FAIL"
    write_json(run_path, run)
    spec["inputs"]["cancel_all_run_receipt"]["sha256"] = sha256(run_path)
    write_json(spec_path, spec)

    with pytest.raises(sealer.SealError, match="cancel-all PASS lineage"):
        seal(spec_path, production)


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


def test_stage1_seal_refuses_tampered_stage0_run_receipt(tmp_path):
    production, _attempt, spec_path, spec = prepare(
        tmp_path, stage="stage1_cancel_all"
    )
    run_path = Path(spec["inputs"]["stage0_run_receipt"]["path"])
    run = json.loads(run_path.read_text())
    run["status"] = "FAIL"
    write_json(run_path, run)
    sidecar = Path(spec["inputs"]["stage0_run_receipt_sidecar"]["path"])
    sidecar.write_text(f"{sha256(run_path)}  {run_path.name}\n", encoding="ascii")
    spec["inputs"]["stage0_run_receipt"]["sha256"] = sha256(run_path)
    spec["inputs"]["stage0_run_receipt_sidecar"]["sha256"] = sha256(sidecar)
    write_json(spec_path, spec)

    with pytest.raises(sealer.SealError, match="Stage 0.*lineage"):
        seal(spec_path, production)


def test_stage1_seal_refuses_predecessor_attempt_root_ancestor(tmp_path):
    production, attempt, spec_path, spec = prepare(
        tmp_path, stage="stage1_cancel_all"
    )
    seal_path = Path(spec["inputs"]["stage0_seal_receipt"]["path"])
    prior_seal = json.loads(seal_path.read_text())
    prior_seal["scope"]["attempt_root"] = str(attempt.parent.resolve())
    write_json(seal_path, prior_seal)
    spec["inputs"]["stage0_seal_receipt"]["sha256"] = sha256(seal_path)
    write_json(spec_path, spec)

    with pytest.raises(sealer.SealError, match="Stage 0.*lineage"):
        seal(spec_path, production)

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


def test_seal_refuses_incomplete_credential_import_check_set(tmp_path):
    production, _attempt, spec_path, spec = prepare(tmp_path)
    receipt = Path(spec["inputs"]["credential_import_receipt"]["path"])
    payload = json.loads(receipt.read_text())
    payload["checks"] = {"all_public_import_checks": True}
    write_json(receipt, payload)
    spec["inputs"]["credential_import_receipt"]["sha256"] = sha256(receipt)
    write_json(spec_path, spec)

    with pytest.raises(sealer.SealError, match="exact clean PASS"):
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


def test_seal_refuses_duplicate_or_nonfixed_credential_targets(tmp_path):
    production, _attempt, spec_path, spec = prepare(tmp_path)
    manifest = Path(spec["inputs"]["credential_reference_manifest"]["path"])
    payload = json.loads(manifest.read_text())
    payload["credential_references"]["POLYMARKET_API_KEY_STORAGE_REF"] = (
        payload["credential_references"]["POLYMARKET_API_SECRET_STORAGE_REF"]
    )
    write_json(manifest, payload)
    spec["inputs"]["credential_reference_manifest"]["sha256"] = sha256(manifest)
    write_json(spec_path, spec)

    with pytest.raises(sealer.SealError, match="exact public contract"):
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


def test_every_stage_binds_complete_status_attestation_source_closure():
    python_closure = set(sealer.repository_python_source_paths(sealer.REPO_ROOT))
    for stage in sealer.STAGES:
        assert set(sealer.STATUS_ATTESTATION_SOURCE_PATHS).issubset(
            sealer.LIVE_SOURCE_PATHS[stage]
        )
        assert python_closure.issubset(sealer.LIVE_SOURCE_PATHS[stage])


def test_real_repository_inventory_and_git_preflight_use_sha1_object_ids():
    root = Path(sealer.REPO_ROOT)
    inventory = sealer.build_public_inventory("stage0", root)
    head = inventory["production"]["commit"]
    tree = inventory["production"]["tree"]
    assert inventory["production"]["object_format"] == "sha1"
    assert len(head) == len(tree) == 40

    def reviewed_master_proxy(repo_root, args):
        command = tuple(args)
        if command in {
            ("rev-parse", "master"),
            ("rev-parse", "origin/master"),
        }:
            return subprocess.CompletedProcess(args, 0, head + "\n", "")
        if command == ("branch", "--show-current"):
            return subprocess.CompletedProcess(args, 0, "master\n", "")
        if command[:2] == ("merge-base", "--is-ancestor"):
            return subprocess.CompletedProcess(args, 0, "", "")
        if command == ("status", "--porcelain=v1", "--untracked-files=all"):
            return subprocess.CompletedProcess(args, 0, "", "")
        return sealer._default_git_runner(repo_root, args)

    facts = sealer._verify_git_state(
        {
            "root": str(root),
            "branch": "master",
            "commit": head,
            "tree": tree,
            "python": str(root / "venv/Scripts/python.exe"),
        },
        git_runner=reviewed_master_proxy,
    )
    assert facts["object_format"] == "sha1"


def test_real_repository_inventory_object_ids_flow_through_a_dry_seal(tmp_path):
    inventory = sealer.build_public_inventory("stage0", sealer.REPO_ROOT)
    commit = inventory["production"]["commit"]
    tree = inventory["production"]["tree"]
    production, _attempt, spec_path, spec = prepare(tmp_path)
    spec["production"]["commit"] = commit
    spec["production"]["tree"] = tree
    write_json(spec_path, spec)

    result = seal(
        spec_path,
        production,
        GitStub(commit=commit, tree=tree),
    )

    receipt = json.loads(Path(result["seal_receipt"]["path"]).read_text())
    assert receipt["production"]["commit"] == commit
    assert receipt["production"]["tree"] == tree
