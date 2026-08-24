from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from weather.market import mm_geographic_eligibility as geography
from weather.operations import international_live_time_window as time_window
from weather.operations import international_live_session_runner as runner
from weather.operations import international_live_wrapper_sealer as sealer


NOW = datetime.fromisoformat("2026-08-23T01:00:00-04:00")
CONDITION = "0x" + "7" * 64
TOKEN = "7001"
WALLET = "0x" + "2" * 40


@pytest.fixture(autouse=True)
def private_attempt_root(monkeypatch):
    monkeypatch.setattr(
        runner,
        "validate_private_attempt_root",
        lambda path: {"status": "PASS", "path": str(path)},
    )
    monkeypatch.setattr(
        runner,
        "_default_overlay_file_provider",
        lambda _root, _hashes: {},
    )


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, dict):
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        path.write_text(str(payload), encoding="utf-8")
    return path


def write_geography(path: Path) -> Path:
    checked = NOW.astimezone(timezone.utc)
    decision = {"blocked": False, "country": "GB", "region": "ENG"}
    payload = {
        "agreement": True,
        "blocker_code": None,
        "checked_at_utc": geography._iso_utc(checked),
        "eligible": True,
        "endpoint": geography.GEOBLOCK_ENDPOINT,
        "fresh_until_utc": geography._iso_utc(
            checked + timedelta(seconds=geography.MAX_RECEIPT_AGE_SECONDS)
        ),
        "freshness_max_age_seconds": geography.MAX_RECEIPT_AGE_SECONDS,
        "official": {
            **decision,
            "decision_sha256": geography._canonical_digest(decision),
        },
        "operator_attestation": {
            "confirmation": geography.PHYSICAL_LOCATION_CONFIRMATION,
            "no_circumvention": True,
            "physical_location_eligible": True,
        },
        "privacy": {
            "source_address_retained": False,
            "secret_values_retained": False,
        },
        "receipt_payload_sha256": None,
        "response_binding": {
            "body_bytes": 80,
            "redacted_body_sha256": geography._canonical_digest(decision),
            "content_type": "application/json",
            "final_url": geography.GEOBLOCK_ENDPOINT,
            "http_status": 200,
        },
        "schema_version": geography.RECEIPT_SCHEMA_VERSION,
        "status": "PASS",
    }
    payload["receipt_payload_sha256"] = geography._payload_digest(payload)
    return write(path, payload)


class LaunchGitStub:
    def __init__(self, *, origin_commit=None, remote_commit=None, remote_failure=False):
        self.commit = "a" * 40
        self.tree = "b" * 40
        self.origin_commit = origin_commit or self.commit
        self.remote_commit = remote_commit or self.commit
        self.remote_failure = remote_failure
        self.calls = []

    def __call__(self, _root: Path, args):
        command = tuple(args)
        self.calls.append(command)
        if command == ("rev-parse", "--show-object-format"):
            return subprocess.CompletedProcess(args, 0, "sha1\n", "")
        if command in (("rev-parse", "HEAD"), ("rev-parse", "master")):
            return subprocess.CompletedProcess(args, 0, self.commit + "\n", "")
        if command == ("rev-parse", "origin/master"):
            return subprocess.CompletedProcess(args, 0, self.origin_commit + "\n", "")
        if command == ("rev-parse", "HEAD^{tree}"):
            return subprocess.CompletedProcess(args, 0, self.tree + "\n", "")
        if command == ("branch", "--show-current"):
            return subprocess.CompletedProcess(args, 0, "master\n", "")
        if command == (
            "ls-remote",
            "--exit-code",
            "--refs",
            "origin",
            sealer.REMOTE_MASTER_REF,
        ):
            return subprocess.CompletedProcess(
                args,
                2 if self.remote_failure else 0,
                (
                    ""
                    if self.remote_failure
                    else f"{self.remote_commit}\t{sealer.REMOTE_MASTER_REF}\n"
                ),
                "",
            )
        if command[:2] == ("merge-base", "--is-ancestor"):
            return subprocess.CompletedProcess(args, 0, "", "")
        if command == ("status", "--porcelain=v1", "--untracked-files=all"):
            return subprocess.CompletedProcess(args, 0, "", "")
        if command[:3] == ("rev-parse", "-q", "--verify"):
            return subprocess.CompletedProcess(args, 1, "", "")
        raise AssertionError(f"unexpected Git command: {command}")


def candidate(now=NOW, *, remaining_seconds=120, economics_acceptance=None):
    current = now.astimezone(timezone.utc)
    paper_generated = current
    created = current
    expires = current + timedelta(seconds=remaining_seconds)
    payload = {
        "schema_version": sealer.CANDIDATE_SCHEMA_VERSION,
        "status": "PASS",
        "created_at_utc": created.isoformat(),
        "expires_at_utc": expires.isoformat(),
        "target_date": now.date().isoformat(),
        "exchange_economics_snapshot_id": "xecon-" + "e" * 16,
        "exchange_economics_sha256": "e" * 32,
        "economics_acceptance": economics_acceptance,
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
            "fee_rate": 0.05,
            "neg_risk": False,
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
                "expires_at_utc": expires.isoformat(),
                "quote_ttl_seconds": remaining_seconds,
                "quote_permission": True,
                "live_trade_permission": False,
            },
        },
    }
    payload["plan_sha256"] = sealer._canonical_payload_sha256(
        payload, omit="plan_sha256"
    )
    return payload


def session_fixture(
    tmp_path: Path,
    stage: str,
    *,
    remaining_seconds=120,
    now: datetime = NOW,
):
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    identity = write(
        attempt / sealer.INPUT_LAYOUTS[stage]["identity"],
        {"schema_version": "mm_stage0_client_identity_v0.3"},
    )
    credential = write(tmp_path / "credential.json", {"status": "PASS"})
    references = write(
        tmp_path / "references.json",
        {"status": "PASS", "wallet_address": WALLET},
    )
    accepted_economics = write(
        attempt / sealer.INPUT_LAYOUTS[stage]["accepted_economics_snapshot"],
        {"status": "PASS", "accepted": True},
    )
    economics_drift = write(
        attempt / sealer.INPUT_LAYOUTS[stage]["economics_drift_report"],
        {"status": "PASS", "rescore_required": False},
    )
    acknowledgment = sealer.economics_acceptance_acknowledgment(
        now.date().isoformat(),
        CONDITION,
        TOKEN,
        accepted_snapshot_file_sha256=sha(accepted_economics),
        drift_report_file_sha256=sha(economics_drift),
    )
    economics_acceptance = {
        "accepted_at_utc": now.astimezone(timezone.utc).isoformat(),
        "accepted_snapshot_file_sha256": sha(accepted_economics),
        "accepted_snapshot_id": "xecon-" + "e" * 16,
        "accepted_snapshot_sha256": "e" * 32,
        "drift_generated_at_utc": now.astimezone(timezone.utc).isoformat(),
        "drift_report_file_sha256": sha(economics_drift),
        "drift_status": "PASS",
        "operator_acknowledgment": acknowledgment,
        "operator_acknowledgment_matches_candidate": True,
        "required_operator_acknowledgment": acknowledgment,
        "rescore_required": False,
    }
    reviewed_source = write(tmp_path / "production/source", {"reviewed": True})
    production_python = tmp_path / "production/venv/Scripts/python.exe"
    production_python.parent.mkdir(parents=True, exist_ok=True)
    production_python.write_bytes(b"reviewed python")
    bootstrap_hashes = {}
    for relative in runner.SESSION_BOOTSTRAP_PATHS:
        source = tmp_path / "production" / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f"# reviewed {relative}\n", encoding="utf-8")
        bootstrap_hashes[relative] = sha(source)
    if stage != "stage0":
        lineage_paths = [
            "stage0/bootstrap.json",
            "stage0/command-receipt.json",
            "seal/stage0-seal-receipt.json",
            "session/stage0-run-receipt.json",
            "session/stage0-run-receipt.json.sha256",
            "stage0/wrapper-execution-receipt.json",
        ]
        if stage == "stage1_dead_man":
            lineage_paths.extend(
                [
                    "seal/stage1-cancel-all-seal-receipt.json",
                    "session/stage1_cancel_all-run-receipt.json",
                    "session/stage1_cancel_all-run-receipt.json.sha256",
                    "stage1-cancel-all/wrapper-execution-receipt.json",
                    "stage1-cancel-all/command-receipt.json",
                    "stage1-cancel-all/result.json",
                    "stage1-cancel-all/lifecycle.jsonl",
                ]
            )
        for relative in lineage_paths:
            write(attempt / relative, {"status": "PASS"})
    payload = {
        "schema_version": runner.SESSION_SCHEMA_VERSION,
        "manifest_sha256": None,
        "stage": stage,
        "production": {
            "root": str(tmp_path / "production"),
            "branch": "master",
            "commit": "a" * 40,
            "tree": "b" * 40,
            "python": str(production_python),
        },
        "scope": {
            "target_date": now.date().isoformat(),
            "condition_id": CONDITION,
            "token_id": TOKEN,
            "requested_budget_pusd": 10,
            "attempt_root": str(attempt.resolve()),
            "lease_workload": f"session-{stage}",
            "max_session_seconds": 120,
        },
        "inputs": {
            "identity": {"path": str(identity.resolve()), "sha256": sha(identity)},
            "credential_import_receipt": {
                "path": str(credential.resolve()),
                "sha256": sha(credential),
            },
            "credential_reference_manifest": {
                "path": str(references.resolve()),
                "sha256": sha(references),
            },
            "accepted_economics_snapshot": {
                "path": str(accepted_economics.resolve()),
                "sha256": sha(accepted_economics),
            },
            "economics_drift_report": {
                "path": str(economics_drift.resolve()),
                "sha256": sha(economics_drift),
            },
        },
        "economics_acceptance": economics_acceptance,
        "reviewed_status_flags": [],
        "template_sha256": {"python": "c" * 64, "launcher": "d" * 64},
        "source_sha256": {"source": sha(reviewed_source)},
        "production_python_sha256": sha(production_python),
        "session_bootstrap_sha256": bootstrap_hashes,
    }
    payload["manifest_sha256"] = runner._canonical_payload_sha256(payload)
    manifest = write(
        attempt / "inputs" / f"{stage}-session-manifest.json",
        payload,
    )
    manifest.with_suffix(manifest.suffix + ".sha256").write_text(
        f"{sha(manifest)}  {manifest.name}\n",
        encoding="ascii",
    )
    source_candidate = write(
        tmp_path / f"fresh-{stage}.json",
        candidate(
            now=now,
            remaining_seconds=remaining_seconds,
            economics_acceptance=economics_acceptance,
        ),
    )
    return attempt, manifest, source_candidate


def fake_sealer(attempt: Path, stage: str):
    def seal(spec_path, **_kwargs):
        spec_path = Path(spec_path).resolve()
        spec = json.loads(spec_path.read_text())
        wrapper = attempt / sealer.OUTPUT_LAYOUTS[stage]["python_wrapper"]
        launcher = attempt / sealer.OUTPUT_LAYOUTS[stage]["launcher"]
        launcher.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_text("# sealed wrapper\n", encoding="utf-8")
        launcher.write_text("# sealed launcher\n", encoding="utf-8")
        seal_path = attempt / sealer.OUTPUT_LAYOUTS[stage]["seal_receipt"]
        seal_payload = {
            "schema_version": sealer.RECEIPT_SCHEMA_VERSION,
            "status": "PASS",
            "stage": stage,
            "production": spec["production"],
            "scope": {
                **spec["scope"],
                "cancellation_mode": (
                    "not_applicable"
                    if stage == "stage0"
                    else ("cancel_all" if stage == "stage1_cancel_all" else "dead_man")
                ),
                "reviewed_status_flags": spec["reviewed_status_flags"],
            },
            "wrapper": {"path": str(wrapper.resolve()), "sha256": sha(wrapper)},
            "launcher": {"path": str(launcher.resolve()), "sha256": sha(launcher)},
            "seal_spec": {"path": str(spec_path), "sha256": sha(spec_path)},
            "inputs": [
                {"role": role, **record}
                for role, record in sorted(spec["inputs"].items())
            ],
        }
        write(seal_path, seal_payload)
        seal_sidecar = seal_path.with_suffix(seal_path.suffix + ".sha256")
        seal_sidecar.write_text(
            f"{sha(seal_path)}  {seal_path.name}\n", encoding="ascii"
        )
        return {
            "status": "PASS",
            "stage": stage,
            "wrapper": {
                "path": str(wrapper.resolve()),
                "sha256": sha(wrapper),
            },
            "launcher": {
                "path": str(launcher.resolve()),
                "sha256": sha(launcher),
            },
            "seal_receipt": {
                "path": str(seal_path.resolve()),
                "sha256": sha(seal_path),
            },
            "seal_receipt_sidecar": str(seal_sidecar.resolve()),
        }

    return seal


def write_execution(
    attempt: Path,
    stage: str,
    *,
    status="PASS",
    mutation=False,
    credential=True,
    wrapper_override=None,
):
    wrapper = attempt / sealer.OUTPUT_LAYOUTS[stage]["python_wrapper"]
    path = attempt / sealer.OUTPUT_LAYOUTS[stage]["wrapper_execution_receipt"]
    layout = sealer.OUTPUT_LAYOUTS[stage]
    doctor = write(attempt / layout["doctor_receipt"], {"status": "PASS"})
    geography_precredential = write_geography(
        attempt / layout["geography_precredential_receipt"]
    )
    stream = attempt / layout["user_stream_journal"]
    stream.parent.mkdir(parents=True, exist_ok=True)
    if stage == "stage0":
        stream.write_text('{"event_type":"stream_stopped"}\n', encoding="utf-8")
    else:
        mode = "cancel_all" if stage == "stage1_cancel_all" else "dead_man"
        order_id = f"{mode}-order"
        stream.write_text(
            "".join(
                json.dumps(row, separators=(",", ":")) + "\n"
                for row in (
                    {
                        "schema_version": "mm_user_stream_journal_v0.1",
                        "event_type": "user_event",
                        "payload": {"orderID": order_id, "status": "live"},
                    },
                    {
                        "schema_version": "mm_user_stream_journal_v0.1",
                        "event_type": "user_event",
                        "payload": {
                            "orderID": order_id,
                            "status": "canceled",
                            "size_matched": "0",
                        },
                    },
                    {
                        "schema_version": "mm_user_stream_journal_v0.1",
                        "event_type": "stream_stopped",
                    },
                )
            ),
            encoding="utf-8",
        )
    command_path = attempt / layout["command_receipt"]
    artifacts = {
        "doctor_receipt_out": {"path": str(doctor.resolve()), "sha256": sha(doctor)},
        "geography_precredential_receipt_out": {
            "path": str(geography_precredential.resolve()),
            "sha256": sha(geography_precredential),
        },
        "user_stream_journal_out": {
            "path": str(stream.resolve()),
            "sha256": sha(stream),
        },
    }
    command_paths = {
        "receipt": str(command_path.resolve()),
        "user_stream_journal": str(stream.resolve()),
    }
    if stage == "stage0":
        geography_premutation = write_geography(
            attempt / layout["geography_premutation_receipt"]
        )
        geography_payload = json.loads(geography_premutation.read_text())
        bootstrap = write(
            attempt / layout["bootstrap"],
            {
                "schema_version": "mm_platform_bootstrap_v0.4",
                "status": "PASS",
                "mutation_geographic_eligibility": {
                    key: geography_payload[key]
                    for key in (
                        "status",
                        "eligible",
                        "endpoint",
                        "receipt_payload_sha256",
                        "checked_at_utc",
                        "fresh_until_utc",
                        "freshness_max_age_seconds",
                    )
                },
            },
        )
        artifacts["bootstrap_out"] = {
            "path": str(bootstrap.resolve()),
            "sha256": sha(bootstrap),
        }
        artifacts["geography_premutation_receipt_out"] = {
            "path": str(geography_premutation.resolve()),
            "sha256": sha(geography_premutation),
        }
        command_paths["bootstrap"] = str(bootstrap.resolve())
        command_paths["geography_premutation_receipt"] = str(
            geography_premutation.resolve()
        )
    else:
        geography_presubmit = write_geography(
            attempt / layout["geography_presubmit_receipt"]
        )
        artifacts["geography_presubmit_receipt_out"] = {
            "path": str(geography_presubmit.resolve()),
            "sha256": sha(geography_presubmit),
        }
        candidate_path = attempt / sealer.INPUT_LAYOUTS[stage]["candidate_plan"]
        candidate_payload = json.loads(candidate_path.read_text())
        journal = attempt / layout["lifecycle_journal"]
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text('{"event_type":"probe_passed"}\n', encoding="utf-8")
        mode = "cancel_all" if stage == "stage1_cancel_all" else "dead_man"
        result = write(
            attempt / layout["result"],
            {
                "schema_version": "mm_live_lifecycle_probe_v0.3",
                "status": "PASS",
                "platform": "polymarket_global",
                "settlement_unit": "pUSD",
                "cancellation_mode": mode,
                "condition_id": CONDITION,
                "token_id": TOKEN,
                "candidate_plan_sha256": sha(candidate_path),
                "candidate_semantic_plan_sha256": candidate_payload["plan_sha256"],
                "bootstrap_schema_version": "mm_platform_bootstrap_v0.4",
                "bootstrap_sha256": sha(attempt / "stage0/bootstrap.json"),
                "heartbeat_acknowledged": True,
                "submit_boundary_heartbeat_acknowledged": True,
                "submit_boundary_market_rules_verified": True,
                "submit_boundary_geography_before_heartbeat_verified": True,
                "post_sign_order_placement_boundary_verified": True,
                "candidate_fee_rate": 0.05,
                "current_fee_rate_bps": 500,
                "candidate_neg_risk": False,
                "current_neg_risk": False,
                "starting_zero_open_orders_verified": True,
                "starting_zero_positions_verified": True,
                "intent": {
                    "token_id": TOKEN,
                    "side": "BUY",
                    "price": 0.01,
                    "size": 5.0,
                },
                "order_notional_usdc": 0.05,
                "order_id": f"{mode}-order",
                "placement_status": "live",
                "open_order_observed": True,
                "authoritative_user_event_observed": True,
                "cancellation_observed": True,
                "zero_open_orders_verified": True,
                "zero_positions_verified": True,
                "no_trade_lifecycle_event_observed": True,
                "terminal_rest_order_verified": True,
                "terminal_rest_zero_matched_verified": True,
                "account_trades_rest_verified": True,
                "scoped_account_trade_count": 0,
                "post_cancel_quiescence_seconds": 2.0,
                "submit_collateral_balance_usdc": 100.0,
                "submit_collateral_allowance_usdc": 100.0,
                "submit_collateral_snapshot_sha256": "a" * 64,
                "post_cancel_collateral_snapshot_sha256": "a" * 64,
                "collateral_no_fill_reconciliation_verified": True,
                "terminal_user_event_observed": True,
                "user_stream_journal_path": str(stream.resolve()),
                "user_stream_journal_sha256": sha(stream),
                "cleanup_final_user_stream_journal_sha256": sha(stream),
                "user_stream_journal_row_count": 3,
                "user_stream_scoped_order_event_count": 2,
                "secret_values_redacted": True,
                "cancel_response_present": mode == "cancel_all",
                "cancellation_elapsed_seconds": 0 if mode == "cancel_all" else 12,
                "journal_path": str(journal.resolve()),
                "journal_sha256": sha(journal),
            },
        )
        artifacts.update(
            {
                "result_out": {"path": str(result.resolve()), "sha256": sha(result)},
                "lifecycle_journal_out": {
                    "path": str(journal.resolve()),
                    "sha256": sha(journal),
                },
            }
        )
        command_paths.update(
            {
                "result": str(result.resolve()),
                "lifecycle_journal": str(journal.resolve()),
            }
        )
    command = {
        "schema_version": "mm_live_pilot_command_receipt_v0.2",
        "status": "PASS",
        "command": "stage0" if stage == "stage0" else "stage1",
        "target_date": NOW.date().isoformat(),
        "condition_id": CONDITION,
        "token_id": TOKEN,
        "requested_budget_pusd": 10,
        "cleanup": {"ok": True},
        "credential_values_read_in_memory": True,
        "exception_type": None,
        "paths": command_paths,
        "credential_topology": {
            "manifest_wallet_address": WALLET,
            "derived_signer_matches_manifest": True,
            "api_owner_matches_manifest": True,
            "order_signer_matches_manifest": True,
            "funder_matches_identity": True,
        },
    }
    if stage == "stage0":
        command["exchange_mutation_attempted"] = True
        command["mutation_geographic_eligibility"] = {
            "path": artifacts["geography_premutation_receipt_out"]["path"],
            "sha256": artifacts["geography_premutation_receipt_out"]["sha256"],
        }
    else:
        command["cancellation_mode"] = mode
        command["exchange_mutation_attempted"] = True
    command["order_submit_attempted"] = stage != "stage0"
    command["authenticated_exchange_write_attempted"] = True
    write(command_path, command)
    artifacts["command_receipt_out"] = {
        "path": str(command_path.resolve()),
        "sha256": sha(command_path),
    }
    host_attestations = [
        {
            "checked_at_local": NOW.isoformat(),
            "status_json_sha256": "9" * 64,
            "status_flag_sha256": [],
        }
        for _index in range(2 if stage == "stage0" else 3)
    ]
    write(
        path,
        {
            "schema_version": sealer.EXECUTION_SCHEMA_VERSION,
            "status": status,
            "stage": stage,
            "phase": "complete" if status == "PASS" else "stage1_command",
            "production_tip": "a" * 40,
            "target_date": NOW.date().isoformat(),
            "condition_id": CONDITION,
            "token_id": TOKEN,
            "requested_budget_pusd": 10,
            "cancellation_mode": (
                None
                if stage == "stage0"
                else ("cancel_all" if stage == "stage1_cancel_all" else "dead_man")
            ),
            "wrapper": wrapper_override
            or {"path": str(wrapper.resolve()), "sha256": sha(wrapper)},
            "artifacts": artifacts,
            "live_mutation_attempted": mutation,
            "order_submit_attempted": stage != "stage0" if mutation else False,
            "authenticated_exchange_write_attempted": mutation,
            "credential_values_read_in_memory": credential,
            "confirmation_scope_display_sha256": "8" * 64,
            "host_attestations": host_attestations,
            "exception_type": None if status == "PASS" else "RuntimeError",
        },
    )


@pytest.mark.parametrize("stage", sealer.STAGES)
def test_composer_accepts_only_manifest_and_fresh_candidate_for_each_stage(
    tmp_path, stage
):
    attempt, manifest, fresh = session_fixture(tmp_path, stage)
    launched = []

    result = runner.compose_and_run_live_session(
        manifest,
        fresh,
        expected_session_manifest_sha256=sha(manifest),
        now=NOW,
        seal_function=fake_sealer(attempt, stage),
        launcher_runner=lambda path: (
            launched.append(path)
            or write_execution(attempt, stage, mutation=True)
            or subprocess.CompletedProcess([str(path)], 0, "", "")
        ),
    )

    assert result["status"] == "PASS"
    assert result["stage"] == stage
    assert len(launched) == 1
    assert (attempt / "session" / f"{stage}-composition-receipt.json").is_file()
    assert (attempt / "session" / f"{stage}-run-receipt.json").is_file()


def test_composer_accepts_exact_0030_toronto_boundary_without_backdating_scope(
    tmp_path,
):
    stage = "stage0"
    current = datetime.fromisoformat("2026-08-23T00:30:00-04:00")
    attempt, manifest, fresh = session_fixture(tmp_path, stage, now=current)

    result = runner.compose_and_run_live_session(
        manifest,
        fresh,
        expected_session_manifest_sha256=sha(manifest),
        now=current,
        seal_function=fake_sealer(attempt, stage),
        launcher_runner=lambda path: (
            write_execution(attempt, stage, mutation=True)
            or subprocess.CompletedProcess([str(path)], 0, "", "")
        ),
    )

    spec = json.loads((attempt / "inputs/stage0-seal-spec.json").read_text())
    assert spec["scope"]["run_not_before_local"] == current.isoformat()
    assert result["status"] == "PASS"


def test_launch_boundary_refuses_stale_cached_origin_despite_matching_live_remote(
    tmp_path,
):
    production = {
        "root": str(tmp_path),
        "branch": "master",
        "commit": "a" * 40,
        "tree": "b" * 40,
        "python": str(tmp_path / "python.exe"),
    }

    with pytest.raises(
        runner.SessionCompositionError,
        match="live remote production equality failed",
    ):
        runner._verify_launch_git_state(
            production,
            git_runner=LaunchGitStub(
                origin_commit="c" * 40,
                remote_commit="a" * 40,
            ),
        )


def test_launch_boundary_refuses_live_remote_lookup_failure(tmp_path):
    production = {
        "root": str(tmp_path),
        "branch": "master",
        "commit": "a" * 40,
        "tree": "b" * 40,
        "python": str(tmp_path / "python.exe"),
    }
    git = LaunchGitStub(remote_failure=True)

    with pytest.raises(
        runner.SessionCompositionError,
        match="live remote production equality failed",
    ):
        runner._verify_launch_git_state(
            production,
            git_runner=git,
        )

    assert (
        "ls-remote",
        "--exit-code",
        "--refs",
        "origin",
        sealer.REMOTE_MASTER_REF,
    ) in git.calls


def test_live_remote_proof_is_on_the_launch_action_path():
    source = Path(runner.__file__).read_text(encoding="utf-8")
    compose = source[source.index("def compose_and_run_live_session(") :]

    assert compose.index("_verify_launch_git_state(") < compose.index(
        "launcher_timeout_seconds = min("
    ) < compose.index("process = launcher_runner(")


@pytest.mark.parametrize(
    ("current", "expected_to_run"),
    [
        (datetime.fromisoformat("2026-08-23T08:57:40-04:00"), True),
        (datetime.fromisoformat("2026-08-23T08:57:40.000001-04:00"), False),
    ],
)
def test_composer_reserves_full_cleanup_grace_before_nine(
    tmp_path, current, expected_to_run
):
    stage = "stage0"
    attempt, manifest, fresh = session_fixture(tmp_path, stage, now=current)
    assert runner.COOPERATIVE_CLEANUP_GRACE_SECONDS == (
        time_window.LIVE_WINDOW_CLEANUP_RESERVE_SECONDS
    )
    assert runner.COOPERATIVE_CLEANUP_GRACE_SECONDS == 20

    if not expected_to_run:
        with pytest.raises(
            runner.SessionCompositionError,
            match="candidate-derived.*00:30-09:00 America/Toronto",
        ):
            runner.compose_and_run_live_session(
                manifest,
                fresh,
                expected_session_manifest_sha256=sha(manifest),
                now=current,
                seal_function=lambda *_args, **_kwargs: pytest.fail(
                    "sealer must not run"
                ),
                launcher_runner=lambda _path: pytest.fail("launcher must not run"),
            )
        assert not (attempt / "inputs/stage0-scope-plan.json").exists()
        assert not (attempt / "inputs/stage0-seal-spec.json").exists()
        return

    result = runner.compose_and_run_live_session(
        manifest,
        fresh,
        expected_session_manifest_sha256=sha(manifest),
        now=current,
        seal_function=fake_sealer(attempt, stage),
        launcher_runner=lambda path: (
            write_execution(attempt, stage, mutation=True)
            or subprocess.CompletedProcess([str(path)], 0, "", "")
        ),
    )

    assert result["launcher_absolute_deadline"] == "2026-08-23T08:59:40-04:00"
    assert result["cooperative_cleanup_grace_seconds"] == 20


@pytest.mark.parametrize("stage", sealer.STAGES)
@pytest.mark.parametrize(
    "current",
    [
        datetime.fromisoformat("2026-08-23T00:29:00-04:00"),
        datetime.fromisoformat("2026-08-23T08:59:00-04:00"),
        datetime.fromisoformat("2026-08-23T09:00:00-04:00"),
        datetime.fromisoformat("2026-08-23T12:00:00-04:00"),
        datetime.fromisoformat("2026-08-23T18:00:00-04:00"),
    ],
)
def test_composer_refuses_ineligible_toronto_window_before_attempt_writes(
    tmp_path, stage, current
):
    attempt, manifest, fresh = session_fixture(
        tmp_path,
        stage,
        now=current,
    )

    with pytest.raises(
        runner.SessionCompositionError,
        match="candidate-derived.*00:30-09:00 America/Toronto",
    ):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=sha(manifest),
            now=current,
            seal_function=lambda *_args, **_kwargs: pytest.fail(
                "sealer must not run"
            ),
            launcher_runner=lambda _path: pytest.fail("launcher must not run"),
        )

    candidate_role = "scope_plan" if stage == "stage0" else "candidate_plan"
    assert not (attempt / sealer.INPUT_LAYOUTS[stage][candidate_role]).exists()
    assert not (attempt / "inputs" / f"{stage}-seal-spec.json").exists()
    assert not (attempt / "session" / f"{stage}-composition-receipt.json").exists()
    assert not (attempt / "session" / f"{stage}-run-intent.json").exists()
    assert not (attempt / sealer.OUTPUT_LAYOUTS[stage]["python_wrapper"]).exists()


def test_composer_rechecks_supported_window_at_execution_boundary(tmp_path):
    stage = "stage1_cancel_all"
    current = datetime.fromisoformat("2026-08-23T08:57:00-04:00")
    attempt, manifest, fresh = session_fixture(tmp_path, stage, now=current)

    with pytest.raises(
        runner.SessionCompositionError,
        match="execution and cleanup boundary.*00:30-09:00 America/Toronto",
    ):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=sha(manifest),
            now=current,
            clock=lambda: datetime.fromisoformat("2026-08-23T09:00:00-04:00"),
            seal_function=fake_sealer(attempt, stage),
            launcher_runner=lambda _path: pytest.fail("launcher must not run"),
        )


def test_composer_refuses_candidate_without_launch_reserve(tmp_path):
    attempt, manifest, fresh = session_fixture(
        tmp_path, "stage0", remaining_seconds=20
    )

    with pytest.raises(runner.SessionCompositionError, match="too little"):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=sha(manifest),
            now=NOW,
            seal_function=fake_sealer(attempt, "stage0"),
            launcher_runner=lambda _path: pytest.fail("launcher must not run"),
        )


def test_composer_rechecks_candidate_after_seal_before_launch(tmp_path):
    attempt, manifest, fresh = session_fixture(tmp_path, "stage1_cancel_all")
    destination = attempt / sealer.INPUT_LAYOUTS["stage1_cancel_all"]["candidate_plan"]

    with pytest.raises(runner.SessionCompositionError, match="changed before launch"):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=sha(manifest),
            now=NOW,
            seal_function=fake_sealer(attempt, "stage1_cancel_all"),
            before_launch=lambda: destination.write_text("tampered", encoding="utf-8"),
            launcher_runner=lambda _path: pytest.fail("launcher must not run"),
        )


def test_composer_uses_effective_cutoff_after_one_second_composition(tmp_path):
    stage = "stage0"
    attempt, manifest, fresh = session_fixture(tmp_path, stage)

    result = runner.compose_and_run_live_session(
        manifest,
        fresh,
        expected_session_manifest_sha256=sha(manifest),
        now=NOW,
        clock=lambda: NOW + timedelta(seconds=1),
        seal_function=fake_sealer(attempt, stage),
        launcher_runner=lambda path: (
            write_execution(attempt, stage, mutation=True)
            or subprocess.CompletedProcess([str(path)], 0, "", "")
        ),
    )

    assert result["effective_deadline_remaining_seconds_before_launch"] == 119


def test_composer_refuses_after_composition_consumes_launch_reserve(tmp_path):
    stage = "stage0"
    attempt, manifest, fresh = session_fixture(tmp_path, stage)

    with pytest.raises(runner.SessionCompositionError, match="pre-submit launch reserve"):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=sha(manifest),
            now=NOW,
            clock=lambda: NOW + timedelta(seconds=31),
            seal_function=fake_sealer(attempt, stage),
            launcher_runner=lambda _path: pytest.fail("launcher must not run"),
        )


def test_composer_parser_has_no_scope_or_budget_overrides():
    parser = runner.build_parser()
    destinations = {action.dest for action in parser._actions}
    assert destinations == {
        "help",
        "session_manifest",
        "candidate",
        "expected_session_manifest_sha256",
    }
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "AssignProcessToJobObject" in source
    assert "KILL_ON_JOB_CLOSE" in source
    assert "CREATE_SUSPENDED" in source


@pytest.mark.parametrize("mutation", [False, True])
def test_runner_propagates_nonzero_child_pre_or_post_submit_facts(
    tmp_path, mutation
):
    stage = "stage1_cancel_all"
    attempt, manifest, fresh = session_fixture(tmp_path, stage)

    def launch(path):
        write_execution(
            attempt,
            stage,
            status="FAIL",
            mutation=mutation,
            credential=True,
        )
        return subprocess.CompletedProcess([str(path)], 1, "", "")

    with pytest.raises(runner.SessionCompositionError, match="validated PASS"):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=sha(manifest),
            now=NOW,
            seal_function=fake_sealer(attempt, stage),
            launcher_runner=launch,
        )

    receipt = json.loads(
        (attempt / "session/stage1_cancel_all-run-receipt.json").read_text()
    )
    assert receipt["status"] == "FAIL"
    assert receipt["live_mutation_attempted"] is mutation
    assert receipt["credential_values_read_in_memory"] is True


@pytest.mark.parametrize("tampered", [False, True])
def test_runner_marks_missing_or_tampered_execution_receipt_unknown(
    tmp_path, tampered
):
    stage = "stage0"
    attempt, manifest, fresh = session_fixture(tmp_path, stage)

    def launch(path):
        if tampered:
            write_execution(
                attempt,
                stage,
                wrapper_override={"path": "wrong", "sha256": "0" * 64},
            )
        return subprocess.CompletedProcess([str(path)], 0, "", "")

    with pytest.raises(runner.SessionCompositionError, match="validated PASS"):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=sha(manifest),
            now=NOW,
            seal_function=fake_sealer(attempt, stage),
            launcher_runner=launch,
        )

    receipt = json.loads(
        (attempt / "session/stage0-run-receipt.json").read_text()
    )
    assert receipt["status"] == "UNKNOWN"
    assert receipt["live_mutation_attempted"] == "UNKNOWN"
    assert receipt["child_execution"]["validation"] in {"UNKNOWN", "FAIL"}


def test_runner_emits_terminal_unknown_on_keyboard_interrupt(tmp_path):
    stage = "stage1_dead_man"
    attempt, manifest, fresh = session_fixture(tmp_path, stage)

    with pytest.raises(KeyboardInterrupt):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=sha(manifest),
            now=NOW,
            seal_function=fake_sealer(attempt, stage),
            launcher_runner=lambda _path: (_ for _ in ()).throw(KeyboardInterrupt()),
        )

    receipt = json.loads(
        (attempt / "session/stage1_dead_man-run-receipt.json").read_text()
    )
    assert receipt["status"] == "INTERRUPTED"
    assert receipt["launcher_exception_type"] == "KeyboardInterrupt"
    assert receipt["live_mutation_attempted"] == "UNKNOWN"


@pytest.mark.parametrize(
    "tamper",
    ["missing_artifact", "phase", "credential", "mutation", "scope"],
)
def test_runner_rejects_under_validated_pass_execution_receipt(tmp_path, tamper):
    stage = "stage1_cancel_all"
    attempt, manifest, fresh = session_fixture(tmp_path, stage)

    def launch(path):
        write_execution(attempt, stage, status="PASS", mutation=True, credential=True)
        execution_path = attempt / sealer.OUTPUT_LAYOUTS[stage][
            "wrapper_execution_receipt"
        ]
        payload = json.loads(execution_path.read_text())
        if tamper == "missing_artifact":
            del payload["artifacts"]["user_stream_journal_out"]
        elif tamper == "phase":
            payload["phase"] = "stage1_command"
        elif tamper == "credential":
            payload["credential_values_read_in_memory"] = "UNKNOWN"
        elif tamper == "mutation":
            payload["live_mutation_attempted"] = False
        else:
            payload["production_tip"] = "b" * 40
        execution_path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess([str(path)], 0, "", "")

    with pytest.raises(runner.SessionCompositionError, match="validated PASS"):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=sha(manifest),
            now=NOW,
            seal_function=fake_sealer(attempt, stage),
            launcher_runner=launch,
        )

    receipt = json.loads(
        (attempt / "session/stage1_cancel_all-run-receipt.json").read_text()
    )
    assert receipt["status"] == "UNKNOWN"
    assert receipt["child_execution"]["validation"] == "FAIL"


def test_runner_rejects_rewritten_manifest_even_with_new_self_hash(tmp_path):
    _attempt, manifest, fresh = session_fixture(tmp_path, "stage0")
    reviewed_sha256 = sha(manifest)
    payload = json.loads(manifest.read_text())
    payload["scope"]["requested_budget_pusd"] = 11
    payload["manifest_sha256"] = runner._canonical_payload_sha256(payload)
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(runner.SessionCompositionError, match="reviewed session manifest"):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=reviewed_sha256,
            now=NOW,
            launcher_runner=lambda _path: pytest.fail("launcher must not run"),
        )


def test_runner_atomically_claims_terminal_namespace_before_launch(tmp_path):
    attempt, manifest, fresh = session_fixture(tmp_path, "stage0")
    terminal = attempt / "session/stage0-run-receipt.json"

    with pytest.raises(runner.SessionCompositionError, match="namespace is already spent"):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=sha(manifest),
            now=NOW,
            seal_function=fake_sealer(attempt, "stage0"),
            before_launch=lambda: terminal.write_text("raced", encoding="utf-8"),
            launcher_runner=lambda _path: pytest.fail("launcher must not run"),
        )

    assert terminal.read_text(encoding="utf-8") == "raced"


@pytest.mark.skipif(os.name != "nt", reason="Windows Job containment is Windows-only")
def test_default_launcher_runner_executes_safe_child_inside_job(tmp_path):
    script = tmp_path / "safe-exit.ps1"
    script.write_text("exit 0\n", encoding="utf-8")

    result = runner._default_launcher_runner(script)

    assert result.returncode == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows Job containment is Windows-only")
def test_default_runner_allows_cooperative_ctrl_break_cleanup(tmp_path):
    script = tmp_path / "cooperative.ps1"
    script.write_text(
        "Start-Sleep -Milliseconds 1500\nexit 3\n",
        encoding="utf-8",
    )

    started = time.monotonic()
    absolute_deadline = datetime.now().astimezone() + timedelta(seconds=1)
    with pytest.raises(runner.LauncherControlError) as caught:
        runner._default_launcher_runner(
            script,
            timeout_seconds=5,
            absolute_deadline=absolute_deadline,
            cleanup_grace_seconds=3,
        )

    assert caught.value.cooperative is True
    assert caught.value.forced is False
    assert time.monotonic() - started < 4


@pytest.mark.skipif(os.name != "nt", reason="Windows Job containment is Windows-only")
def test_default_runner_forces_unresponsive_contained_tree(tmp_path):
    code = (
        "import signal,time;"
        "signal.signal(signal.SIGBREAK,signal.SIG_IGN);"
        "time.sleep(30)"
    )
    script = tmp_path / "unresponsive.ps1"
    script.write_text(
        f"& '{sys.executable}' -c \"{code}\"\nexit $LASTEXITCODE\n",
        encoding="utf-8",
    )

    with pytest.raises(runner.LauncherControlError) as caught:
        runner._default_launcher_runner(
            script,
            timeout_seconds=1,
            cleanup_grace_seconds=1,
        )

    assert caught.value.cooperative is False
    assert caught.value.forced is True


@pytest.mark.skipif(os.name != "nt", reason="Windows share-mode locking is Windows-only")
def test_default_runner_denies_write_delete_race_for_sealed_artifact(tmp_path):
    script = tmp_path / "bounded.ps1"
    script.write_text("Start-Sleep -Seconds 2\nexit 0\n", encoding="utf-8")
    protected = tmp_path / "lazy_sdk_module.py"
    protected.write_text("# lazy reviewed import\n", encoding="utf-8")
    outcome = {}

    def run():
        outcome["result"] = runner._default_launcher_runner(
            script,
            protected_files={protected: sha(protected)},
            timeout_seconds=5,
        )

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.5)
    with pytest.raises(PermissionError):
        protected.write_text("tampered", encoding="utf-8")
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert outcome["result"].returncode == 0
    assert protected.read_text() == "# lazy reviewed import\n"
