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
from weather.market.exchange_economics import (
    accept_snapshot_baseline,
    build_snapshot_payload,
)
from weather.market import mm_live_candidate_cli as candidate_cli
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
    assert "& $python -I -S -B -c" in text
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


def discovery_payload(*, constrained: bool = False) -> dict:
    created = NOW.astimezone(timezone.utc) - timedelta(seconds=5)
    paper_generated = NOW.astimezone(timezone.utc) - timedelta(seconds=10)
    expires = paper_generated + timedelta(seconds=120)
    payload = {
        "schema_version": candidate_cli.SCHEMA_VERSION,
        "status": "PASS",
        "created_at_utc": created.isoformat(),
        "expires_at_utc": expires.isoformat(),
        "target_date": NOW.date().isoformat(),
        "platform": "polymarket_global",
        "settlement_unit": "pUSD",
        "exchange_economics_snapshot_id": "xecon-" + "e" * 16,
        "exchange_economics_sha256": "e" * 32,
        "economics_gate_ok": True,
        "economics_gate_missing": [],
        "substrate_preflight": {
            "schema_version": candidate_cli.SUBSTRATE_PREFLIGHT_SCHEMA_VERSION,
            "receipt_sha256": "0" * 64,
            "checked_at_utc": created.isoformat(),
            "expires_at_utc": (
                created
                + timedelta(
                    seconds=candidate_cli.MAX_SUBSTRATE_PREFLIGHT_AGE_SECONDS
                )
            ).isoformat(),
            "market_id": "toronto",
            "target_date": NOW.date().isoformat(),
            "event_slug": "toronto-high-temperature-test",
            "validation_hash": "1" * 64,
            "event_metadata_file_sha256": "2" * 64,
            "event_metadata_validation_file_sha256": "3" * 64,
            "observation_status_file_sha256": "4" * 64,
            "economics_snapshot_file_sha256": "5" * 64,
            "accepted_snapshot_file_sha256": "6" * 64,
            "economics_drift_report_file_sha256": "7" * 64,
            "paper_run_config_file_sha256": "a" * 64,
            "paper_preflight_file_sha256": "8" * 64,
            "paper_quote_intents_file_sha256": "b" * 64,
            "clob_tokens_file_sha256": "9" * 64,
            "order_books_summary_file_sha256": "c" * 64,
            "source_status_long_file_sha256": "d" * 64,
            "network_access": False,
            "credential_access": False,
            "exchange_contact": False,
            "exchange_mutation": False,
        },
        "selection_is_trading_authorization": False,
        "secret_values_retained": False,
        "selection_policy": {
            "built_in_locations_only": True,
            "positive_fee_and_rebate_required": True,
            "midpoint_interval": [0.2, 0.8],
            "max_spread": 0.05,
            "minimum_tick_buy_must_be_nonmarketable": True,
            "book_tick_min_size_and_neg_risk_must_be_current": True,
            "plan_max_age_seconds": 300,
            "max_single_order_notional_pusd": 10,
            "successful_current_market_harvest_quote_required": True,
            "expected_bootstrap_scope": {
                "condition_id": CONDITION if constrained else None,
                "token_id": TOKEN if constrained else None,
            },
            "ranking": "spread_asc_then_best_level_depth_desc_then_midpoint_distance",
        },
        "paper_quote_evidence": {
            "run_config_sha256": "a" * 64,
            "quote_intents_sha256": "b" * 64,
            "quote_intents_row_count": 1,
            "market_id": "toronto",
            "run_id": "paper-run-1",
        },
        "candidate_count": 1,
        "selected": {
            "location_id": "toronto",
            "event_date": NOW.date().isoformat(),
            "event_slug": "toronto-high-temperature-test",
            "question": "Will Toronto reach the selected high-temperature range?",
            "condition_id": CONDITION,
            "token_id": TOKEN,
            "outcome_index": 0,
            "best_bid": 0.32,
            "best_ask": 0.33,
            "midpoint": 0.325,
            "spread": 0.01,
            "best_bid_depth": 100,
            "best_ask_depth": 100,
            "order_min_size": 5,
            "tick_size": 0.01,
            "neg_risk": False,
            "fee_rate": 0.05,
            "maker_rebate_rate": 0.25,
            "reward_min_size": 20,
            "reward_max_spread_cents": 4.5,
            "current_book_within_reward_spread": True,
            "lifecycle_probe_reward_min_size_met": False,
            "book_sha256": "c" * 64,
            "stage1_intent": {
                "side": "BUY",
                "price": 0.01,
                "size": 5,
                "notional_pusd": 0.05,
                "post_only": True,
            },
            "paper_quote_proof": {
                "run_id": "paper-run-1",
                "market_id": "toronto",
                "target_date": NOW.date().isoformat(),
                "condition_id": CONDITION,
                "token_id": TOKEN,
                "range_label": "test-range",
                "exchange_economics_snapshot_id": "xecon-" + "e" * 16,
                "exchange_economics_hash": "e" * 32,
                "policy_hash": "paper-policy-hash",
                "generated_at_utc": paper_generated.isoformat(),
                "expires_at_utc": expires.isoformat(),
                "quote_ttl_seconds": 120,
                "bid_price": 0.31,
                "bid_size": 5,
                "ask_price": 0.34,
                "ask_size": 5,
                "quote_risk_pusd": 4.85,
                "quote_permission": True,
                "live_trade_permission": False,
                "two_sided_post_only_intent": True,
                "reward_and_rebate_assumed_zero": True,
                "quote_row_sha256": "d" * 64,
            },
        },
        "alternates": [],
        "missing": [],
    }
    payload["plan_sha256"] = candidate_cli.candidate_plan_sha256(payload)
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
    current_economics = write_json(
        sources / "current-economics.json",
        build_snapshot_payload(
            target_date=NOW.date().isoformat(),
            verified_at_utc=(
                NOW.astimezone(timezone.utc) - timedelta(seconds=30)
            ).isoformat(),
            platform="polymarket_global",
            condition_id=CONDITION,
            token_ids=[TOKEN, "102"],
            reward_daily_rate_usdc=1,
            rewards_min_size=20,
            rewards_max_spread_cents=4.5,
        ),
    )
    accepted_economics = sources / "accepted-economics.json"
    economics_drift = sources / "economics-drift.json"
    accept_snapshot_baseline(
        snapshot_path=current_economics,
        accepted_snapshot_path=accepted_economics,
        drift_report_path=economics_drift,
        target_date=NOW.date().isoformat(),
        now=NOW - timedelta(seconds=20),
        max_age_hours=2,
        acknowledge_payout_asset_conflict=True,
    )
    accepted_payload = json.loads(accepted_economics.read_text(encoding="utf-8"))
    drift_payload = json.loads(economics_drift.read_text(encoding="utf-8"))
    discovery_data = discovery_payload(constrained=constrained)
    discovery_data["exchange_economics_snapshot_id"] = accepted_payload[
        "snapshot_id"
    ]
    discovery_data["exchange_economics_sha256"] = accepted_payload[
        "exchange_economics_hash"
    ]
    discovery_data["selected"]["paper_quote_proof"].update(
        {
            "exchange_economics_snapshot_id": accepted_payload["snapshot_id"],
            "exchange_economics_hash": accepted_payload[
                "exchange_economics_hash"
            ],
        }
    )
    acknowledgment = candidate_cli.economics_acceptance_acknowledgment(
        NOW.date().isoformat(),
        CONDITION,
        TOKEN,
        accepted_snapshot_file_sha256=sha(accepted_economics),
        drift_report_file_sha256=sha(economics_drift),
    )
    discovery_data["economics_acceptance"] = {
        "accepted_at_utc": accepted_payload["accepted_at_utc"],
        "accepted_snapshot_file_sha256": sha(accepted_economics),
        "accepted_snapshot_id": accepted_payload["snapshot_id"],
        "accepted_snapshot_sha256": accepted_payload[
            "exchange_economics_hash"
        ],
        "drift_generated_at_utc": drift_payload["generated_at_utc"],
        "drift_report_file_sha256": sha(economics_drift),
        "drift_status": "PASS",
        "operator_acknowledgment": acknowledgment,
        "operator_acknowledgment_matches_candidate": True,
        "required_operator_acknowledgment": acknowledgment,
        "rescore_required": False,
    }
    discovery_data["substrate_preflight"][
        "accepted_snapshot_file_sha256"
    ] = sha(accepted_economics)
    discovery_data["substrate_preflight"][
        "economics_drift_report_file_sha256"
    ] = sha(economics_drift)
    discovery_data["plan_sha256"] = candidate_cli.candidate_plan_sha256(
        discovery_data
    )
    discovery = write_json(sources / "discovery.json", discovery_data)
    attempt = tmp_path / "attempt"
    for name in launcher_sealer.ATTEMPT_DIRECTORIES:
        (attempt / name).mkdir(parents=True, exist_ok=True)

    def inventory(stage, root):
        root = Path(root)
        git_executable = fixed_sealer.canonical_git_executable()
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
                "local_master": "a" * 40,
                "cached_origin_master": "a" * 40,
                "remote_master": "a" * 40,
                "remote_master_ref": fixed_sealer.REMOTE_MASTER_REF,
                "live_remote_master_equal": True,
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
        "accepted_economics": accepted_economics,
        "economics_drift": economics_drift,
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
        "accepted_economics_snapshot_source_path": prepared[
            "accepted_economics"
        ],
        "economics_drift_report_source_path": prepared["economics_drift"],
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
        "accepted_economics_snapshot",
        "economics_drift_report",
    }
    for role, source_key in {
        "identity": "identity",
        "credential_import_receipt": "credential_receipt",
        "credential_reference_manifest": "credential_manifest",
        "accepted_economics_snapshot": "accepted_economics",
        "economics_drift_report": "economics_drift",
    }.items():
        copied = Path(manifest["inputs"][role]["path"])
        assert copied.is_relative_to(prepared["attempt"])
        assert copied.read_bytes() == Path(prepared[source_key]).read_bytes()
        assert manifest["inputs"][role]["sha256"] == sha(copied)
    assert Path(receipt["staged_public_inputs"]["discovery_plan"]["path"]).read_bytes() == prepared[
        "discovery"
    ].read_bytes()
    assert manifest["economics_acceptance"] == json.loads(
        prepared["discovery"].read_text(encoding="utf-8")
    )["economics_acceptance"]
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


def test_manifest_builder_rejects_create_new_credential_evidence(tmp_path):
    prepared = manifest_builder_fixture(tmp_path)
    receipt_path = prepared["credential_receipt"]
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["credential_mode"] = "create_new"
    payload["credential_value_count_written"] = 4
    payload["credential_value_count_existing_exact_verified"] = 0
    payload["credential_store_mutation_attempted"] = True
    write_json(receipt_path, payload)

    with pytest.raises(
        launcher_sealer.SessionLauncherSealError,
        match="requires compare-only credential evidence",
    ):
        build_manifest(prepared)

    assert list((prepared["attempt"] / "inputs").iterdir()) == []


def test_manifest_builder_rejects_drift_report_not_bound_by_discovery(tmp_path):
    prepared = manifest_builder_fixture(tmp_path)
    drift = prepared["economics_drift"]
    payload = json.loads(drift.read_text(encoding="utf-8"))
    payload["generated_at_utc"] = (
        datetime.fromisoformat(payload["generated_at_utc"])
        + timedelta(seconds=1)
    ).isoformat()
    write_json(drift, payload)

    with pytest.raises(
        launcher_sealer.SessionLauncherSealError,
        match="economics acceptance does not match its source evidence",
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
        match="requires compare-only credential evidence",
    ):
        build_manifest(prepared)

    assert list((prepared["attempt"] / "inputs").iterdir()) == []


def test_launcher_revalidates_staged_compare_only_credential_evidence(tmp_path):
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
    credential_payload["credential_mode"] = "create_new"
    credential_payload["credential_value_count_written"] = 4
    credential_payload["credential_value_count_existing_exact_verified"] = 0
    credential_payload["credential_store_mutation_attempted"] = True
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
        match="staged first-session credential evidence is not compare-only",
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
            "--accepted-economics-snapshot-source",
            "accepted-economics.json",
            "--economics-drift-report-source",
            "economics-drift.json",
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
