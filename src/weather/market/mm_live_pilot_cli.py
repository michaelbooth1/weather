"""Fail-closed preparation CLI for the first International lifecycle probes.

The command accepts only public scope identifiers and paths. Authentication is
resolved from Windows Credential Manager references already present in the
process environment; secret values are never accepted as arguments or written
to artifacts. Exchange-mutating Stage 0 and Stage 1 functions are deliberately
not exposed by this parser; a separately reviewed host-owned wrapper must call
those library boundaries. Stage 1 additionally requires
a fresh non-authorizing candidate plan bound to a successful paper-only quote.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from weather.io import write_json_atomic
from weather.market.mm_credentials import (
    FUNDER_ENV,
    REFERENCE_ENV,
    STAGE0_AUTHORIZATION,
    STAGE0_IDENTITY_SCHEMA_VERSION,
    build_unified_clob_client,
    credential_secret_hygiene,
    load_global_credential_bundle,
    parse_wincred_reference,
    stage0_client_identity_gate,
)
from weather.market.mm_exchange import credential_diagnostics
from weather.market.mm_geographic_eligibility import (
    GeographicEligibilityError,
    validate_geographic_eligibility_receipt,
)
from weather.market.mm_live_bootstrap import (
    collect_platform_bootstrap_payload,
    finalize_platform_bootstrap_payload,
    load_platform_bootstrap_gate,
)
from weather.market.mm_live_lifecycle_probe import (
    CONFIRMATION as STAGE1_CONFIRMATION,
    build_stage1_lifecycle_bundle,
    execute_stage1_lifecycle_probe,
    verify_stage1_user_stream_journal,
)
from weather.market.mm_live_candidate_cli import load_stage1_candidate_gate
from weather.market.mm_official_adapter import (
    OFFICIAL_CLOB_DISTRIBUTION,
    OFFICIAL_CLOB_VERSION,
    OfficialPolymarketGlobalAdapter,
    CONDITION_ID_RE,
    exact_current_positions_evidence,
    fetch_current_positions,
    installed_official_clob_version,
)
from weather.market.mm_official_transport import (
    OfficialHeartbeatSender,
    fetch_market_rule_endpoints,
)
from weather.market.mm_user_stream import OfficialUserStreamReader
from weather.market.market_making_preflight import (
    INTERNATIONAL_SETTLEMENT_UNIT,
    SIGNATURE_TYPE_IDS,
)
from weather.market.market_making_run_constants import MAX_OPERATOR_PILOT_BUDGET_USDC
from weather.market.market_config import ensure_date
from weather.market.market_registry import REGISTRY as MARKET_REGISTRY
from weather.operations.live_path_security import (
    LivePathSecurityError,
    launcher_host_attestations_are_valid,
    validate_production_python_runtime_binding,
)
from weather.schema_registry import schema_version


RECEIPT_SCHEMA_VERSION = schema_version("mm_live_pilot_command_receipt")
FIXED_SCOPE_SEAL_SCHEMA_VERSION = schema_version(
    "international_live_fixed_scope_seal"
)
FIXED_SCOPE_EXECUTION_SCHEMA_VERSION = schema_version(
    "international_live_fixed_scope_execution"
)
MAX_PILOT_BUDGET = MAX_OPERATOR_PILOT_BUDGET_USDC
BUNDLE_CONFIRMATION = "INTERNATIONAL_POLYMARKET_STAGE1_BUILD_BUNDLE"
IDENTITY_CONFIRMATION = "INTERNATIONAL_POLYMARKET_PREPARE_STAGE0_IDENTITY"
DOCTOR_CONFIRMATION = "INTERNATIONAL_POLYMARKET_STAGE0_KEYLESS_DOCTOR"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json_object(path: str | Path) -> dict:
    candidate = Path(path)
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read required JSON object: {candidate}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"required JSON artifact is not an object: {candidate}")
    return payload


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validated_interpreter_binding(production: dict) -> dict | None:
    try:
        return validate_production_python_runtime_binding(production)
    except LivePathSecurityError:
        return None


def _validate_stage1_bundle_lineage(args, mode: str, result_path: str | Path) -> dict:
    stage_name = "stage1_cancel_all" if mode == "cancel_all" else "stage1_dead_man"
    prefix = "cancel_all" if mode == "cancel_all" else "dead_man"
    seal_path = Path(getattr(args, f"{prefix}_seal_receipt")).resolve()
    command_path = Path(getattr(args, f"{prefix}_command_receipt")).resolve()
    execution_path = Path(getattr(args, f"{prefix}_execution_receipt")).resolve()
    run_path = Path(getattr(args, f"{prefix}_run_receipt")).resolve()
    result = Path(result_path).resolve()
    seal = _read_json_object(seal_path)
    command = _read_json_object(command_path)
    execution = _read_json_object(execution_path)
    run = _read_json_object(run_path)
    result_payload = _read_json_object(result)
    seal_scope = seal.get("scope") if isinstance(seal.get("scope"), dict) else {}
    attempt_root = Path(str(seal_scope.get("attempt_root") or "")).resolve()
    stage_folder = "stage1-cancel-all" if mode == "cancel_all" else "stage1-dead-man"
    expected_paths = {
        "seal": attempt_root / "seal" / f"{stage_folder}-seal-receipt.json",
        "run": attempt_root / "session" / f"{stage_name}-run-receipt.json",
        "execution": attempt_root / stage_folder / "wrapper-execution-receipt.json",
        "command": attempt_root / stage_folder / "command-receipt.json",
        "result": attempt_root / stage_folder / "result.json",
        "journal": attempt_root / stage_folder / "lifecycle.jsonl",
        "stream": attempt_root / stage_folder / "user-stream.jsonl",
        "geography_precredential": (
            attempt_root / stage_folder / "geography-precredential-receipt.json"
        ),
        "geography_presubmit": (
            attempt_root / stage_folder / "geography-presubmit-receipt.json"
        ),
        "manifest": attempt_root / "inputs" / f"{stage_name}-session-manifest.json",
        "composition": attempt_root / "session" / f"{stage_name}-composition-receipt.json",
        "intent": attempt_root / "session" / f"{stage_name}-run-intent.json",
    }
    seal_wrapper = seal.get("wrapper") if isinstance(seal.get("wrapper"), dict) else {}
    execution_wrapper = (
        execution.get("wrapper") if isinstance(execution.get("wrapper"), dict) else {}
    )
    artifacts = execution.get("artifacts") if isinstance(execution.get("artifacts"), dict) else {}
    result_artifact = artifacts.get("result_out") or {}
    command_artifact = artifacts.get("command_receipt_out") or {}
    journal_artifact = artifacts.get("lifecycle_journal_out") or {}
    stream_artifact = artifacts.get("user_stream_journal_out") or {}
    geography_precredential_artifact = (
        artifacts.get("geography_precredential_receipt_out") or {}
    )
    geography_presubmit_artifact = (
        artifacts.get("geography_presubmit_receipt_out") or {}
    )
    geography_artifacts_ok = True
    for artifact, expected_path in (
        (geography_precredential_artifact, expected_paths["geography_precredential"]),
        (geography_presubmit_artifact, expected_paths["geography_presubmit"]),
    ):
        artifact_path = Path(str(artifact.get("path") or "")).resolve()
        try:
            geography_payload = _read_json_object(artifact_path)
            validate_geographic_eligibility_receipt(
                geography_payload,
                require_fresh=False,
            )
        except (RuntimeError, GeographicEligibilityError):
            geography_artifacts_ok = False
        geography_artifacts_ok = geography_artifacts_ok and (
            artifact_path == expected_path
            and artifact_path.is_file()
            and _sha256_file(artifact_path) == artifact.get("sha256")
        )
    run_child = run.get("child_execution") or {}
    run_topology = run.get("credential_topology") or {}
    seal_production = seal.get("production") or {}
    interpreter_binding = _validated_interpreter_binding(seal_production)
    reviewed_status_flags = seal_scope.get("reviewed_status_flags")
    expected_status_flag_hashes = (
        [row.get("sha256") for row in reviewed_status_flags]
        if isinstance(reviewed_status_flags, list)
        and all(isinstance(row, dict) for row in reviewed_status_flags)
        else None
    )
    market = MARKET_REGISTRY.get(str(seal_scope.get("market_id") or ""))
    command_paths = command.get("paths") or {}
    credential_topology = command.get("credential_topology") or {}
    run_sidecar = run_path.with_suffix(run_path.suffix + ".sha256")
    expected_run_sidecar = f"{_sha256_file(run_path)}  {run_path.name}\n"
    final_stream_evidence = verify_stage1_user_stream_journal(
        expected_paths["stream"],
        result_payload,
    )
    run_lineage_ok = True
    expected_run_lineage = {
        "session_manifest": expected_paths["manifest"],
        "composition_receipt": expected_paths["composition"],
        "run_intent": expected_paths["intent"],
        "seal_receipt": expected_paths["seal"],
    }
    for role, expected_path in expected_run_lineage.items():
        record = run.get(role) or {}
        record_path = Path(str(record.get("path") or "")).resolve()
        run_lineage_ok = run_lineage_ok and (
            record_path == expected_path
            and record_path.is_file()
            and _sha256_file(record_path) == record.get("sha256")
        )
    run_manifest = run.get("session_manifest") or {}
    manifest_sidecar = expected_paths["manifest"].with_suffix(
        expected_paths["manifest"].suffix + ".sha256"
    )
    run_lineage_ok = run_lineage_ok and (
        Path(str(run_manifest.get("sidecar_path") or "")).resolve()
        == manifest_sidecar
        and manifest_sidecar.is_file()
        and _sha256_file(manifest_sidecar) == run_manifest.get("sidecar_sha256")
    )
    checks = {
        "seal": seal.get("schema_version") == FIXED_SCOPE_SEAL_SCHEMA_VERSION
        and seal.get("status") == "PASS"
        and seal.get("stage") == stage_name,
        "production": seal_production.get("commit") == args.expected_production_tip,
        "interpreter_binding": interpreter_binding is not None,
        "seal_scope": seal_scope.get("target_date") == args.target_date
        and market is not None
        and seal_scope.get("market_timezone") == market.timezone
        and str(seal_scope.get("condition_id") or "").lower()
        == str(args.condition_id).lower()
        and str(seal_scope.get("token_id") or "") == str(args.token_id)
        and float(seal_scope.get("requested_budget_pusd")) == float(args.budget)
        and seal_scope.get("cancellation_mode") == mode,
        "execution_host": seal_scope.get("execution_host_profile")
        in {"capture_colocated_v1", "portable_execution_v1"}
        and len(str(seal_scope.get("execution_host_id") or "")) == 64
        and execution.get("execution_host_profile")
        == seal_scope.get("execution_host_profile")
        and execution.get("execution_host_id") == seal_scope.get("execution_host_id")
        and run.get("execution_host_profile")
        == seal_scope.get("execution_host_profile")
        and run.get("execution_host_id") == seal_scope.get("execution_host_id"),
        "canonical_paths": seal_path == expected_paths["seal"]
        and run_path == expected_paths["run"]
        and execution_path == expected_paths["execution"]
        and command_path == expected_paths["command"]
        and result == expected_paths["result"]
        and Path(str(journal_artifact.get("path") or "")).resolve()
        == expected_paths["journal"]
        and Path(str(stream_artifact.get("path") or "")).resolve()
        == expected_paths["stream"],
        "command": command.get("schema_version") == RECEIPT_SCHEMA_VERSION
        and command.get("status") == "PASS"
        and command.get("command") == "stage1"
        and command.get("target_date") == args.target_date
        and str(command.get("condition_id") or "").lower()
        == str(args.condition_id).lower()
        and str(command.get("token_id") or "") == str(args.token_id)
        and float(command.get("requested_budget_pusd")) == float(args.budget)
        and command.get("cancellation_mode") == mode
        and command.get("exchange_mutation_attempted") is True
        and command.get("authenticated_exchange_write_attempted") is True
        and command.get("order_submit_attempted") is True
        and len(credential_topology) == 5
        and all(
            value is True
            for key, value in credential_topology.items()
            if key != "manifest_wallet_address"
        )
        and (command.get("cleanup") or {}).get("ok") is True
        and command.get("exception_type") is None,
        "command_paths": command_paths.get("result") == str(result)
        and command_paths.get("receipt") == str(command_path)
        and command_paths.get("user_stream_journal")
        == stream_artifact.get("path")
        and command_paths.get("lifecycle_journal")
        == journal_artifact.get("path"),
        "execution": execution.get("schema_version")
        == FIXED_SCOPE_EXECUTION_SCHEMA_VERSION
        and execution.get("status") == "PASS"
        and execution.get("stage") == stage_name
        and execution.get("target_date") == args.target_date
        and str(execution.get("condition_id") or "").lower()
        == str(args.condition_id).lower()
        and str(execution.get("token_id") or "") == str(args.token_id)
        and float(execution.get("requested_budget_pusd")) == float(args.budget)
        and execution.get("cancellation_mode") == mode
        and execution.get("production_tip") == args.expected_production_tip
        and execution.get("phase") == "complete"
        and execution.get("credential_values_read_in_memory") is True
        and execution.get("live_mutation_attempted") is True
        and execution.get("order_submit_attempted") is True
        and execution.get("authenticated_exchange_write_attempted") is True
        and execution.get("exception_type") is None,
        "execution_lease_lineage": (
            launcher_host_attestations_are_valid(
                execution.get("host_attestations"),
                expected_execution_host_profile=seal_scope.get(
                    "execution_host_profile"
                ),
                expected_execution_host_id=seal_scope.get("execution_host_id"),
                expected_status_flag_sha256=expected_status_flag_hashes,
            )
        ),
        "execution_artifacts": set(artifacts)
        == {
            "doctor_receipt_out",
            "geography_precredential_receipt_out",
            "geography_presubmit_receipt_out",
            "result_out",
            "command_receipt_out",
            "user_stream_journal_out",
            "lifecycle_journal_out",
        }
        and geography_artifacts_ok,
        "wrapper": seal_wrapper.get("path") == execution_wrapper.get("path")
        and seal_wrapper.get("sha256") == execution_wrapper.get("sha256"),
        "result": result_artifact.get("path") == str(result)
        and result_artifact.get("sha256") == _sha256_file(result),
        "command_artifact": command_artifact.get("path") == str(command_path)
        and command_artifact.get("sha256") == _sha256_file(command_path),
        "journal_artifact": bool(journal_artifact.get("path"))
        and len(str(journal_artifact.get("sha256") or "")) == 64
        and Path(str(journal_artifact.get("path"))).is_file()
        and _sha256_file(journal_artifact["path"]) == journal_artifact["sha256"],
        "stream_artifact": bool(stream_artifact.get("path"))
        and len(str(stream_artifact.get("sha256") or "")) == 64
        and Path(str(stream_artifact.get("path"))).is_file()
        and _sha256_file(stream_artifact["path"]) == stream_artifact["sha256"],
        "result_stream_journal": Path(
            str(result_payload.get("user_stream_journal_path") or "")
        ).resolve()
        == Path(str(stream_artifact.get("path") or "")).resolve()
        and result_payload.get("user_stream_journal_sha256")
        == stream_artifact.get("sha256")
        and result_payload.get("cleanup_final_user_stream_journal_sha256")
        == stream_artifact.get("sha256")
        and final_stream_evidence.get("sha256")
        == result_payload.get("user_stream_journal_sha256")
        and final_stream_evidence.get("terminal_stream_stopped_verified") is True
        and type(result_payload.get("user_stream_scoped_order_event_count")) is int
        and result_payload.get("user_stream_scoped_order_event_count") >= 2,
        "result_terminal_no_fill": (
            result_payload.get("schema_version")
            == "mm_live_lifecycle_probe_v0.3"
            and result_payload.get("submit_boundary_heartbeat_acknowledged") is True
            and result_payload.get("submit_boundary_market_rules_verified") is True
            and result_payload.get(
                "submit_boundary_geography_before_heartbeat_verified"
            )
            is True
            and result_payload.get(
                "post_sign_order_placement_boundary_verified"
            )
            is True
            and result_payload.get("terminal_rest_order_verified") is True
            and result_payload.get("terminal_rest_zero_matched_verified") is True
            and result_payload.get("account_trades_rest_verified") is True
            and result_payload.get("scoped_account_trade_count") == 0
            and result_payload.get("post_cancel_quiescence_seconds") == 2.0
            and result_payload.get("terminal_user_event_observed") is True
        ),
        "result_journal": Path(
            str(result_payload.get("journal_path") or "")
        ).resolve()
        == Path(str(journal_artifact.get("path") or "")).resolve(),
        "run": run.get("schema_version") == "international_live_session_run_v0.4"
        and run.get("status") == "PASS"
        and run.get("stage") == stage_name
        and run.get("live_mutation_attempted") is True
        and run.get("order_submit_attempted") is True
        and run.get("authenticated_exchange_write_attempted") is True
        and run.get("credential_values_read_in_memory") is True
        and len(run_topology) == 5
        and all(
            value is True
            for key, value in run_topology.items()
            if key != "manifest_wallet_address"
        )
        and run_child.get("validation") == "PASS"
        and run_child.get("status") == "PASS"
        and run_child.get("phase") == "complete"
        and run_child.get("path") == str(execution_path)
        and run_child.get("sha256") == _sha256_file(execution_path)
        and run.get("candidate_sha256")
        == result_payload.get("candidate_plan_sha256")
        and (run.get("seal_receipt") or {}).get("path") == str(seal_path)
        and (run.get("seal_receipt") or {}).get("sha256")
        == _sha256_file(seal_path)
        and run.get("launcher") == seal.get("launcher")
        and run.get("wrapper") == seal.get("wrapper")
        and run_lineage_ok,
        "run_sidecar": run_sidecar.is_file()
        and run_sidecar.read_text(encoding="ascii") == expected_run_sidecar,
    }
    missing = [name for name, passed in checks.items() if not passed]
    if missing:
        raise RuntimeError(
            f"Stage 1 {mode} seal/command/execution lineage failed: "
            + ", ".join(missing)
        )
    return {
        "mode": mode,
        "seal_receipt_sha256": _sha256_file(seal_path),
        "command_receipt_sha256": _sha256_file(command_path),
        "execution_receipt_sha256": _sha256_file(execution_path),
        "run_receipt_sha256": _sha256_file(run_path),
        "result_sha256": _sha256_file(result),
        "journal_sha256": journal_artifact["sha256"],
        "market_id": market.id,
        "market_timezone": market.timezone,
        "interpreter_binding": interpreter_binding,
    }


def _require_new_distinct_paths(paths: dict[str, str | Path]) -> dict[str, Path]:
    resolved = {name: Path(value).resolve() for name, value in paths.items()}
    if len(set(resolved.values())) != len(resolved):
        raise RuntimeError("live-pilot output and journal paths must be distinct")
    existing = [name for name, path in resolved.items() if path.exists()]
    if existing:
        raise RuntimeError(
            "live-pilot output paths must be new: " + ", ".join(sorted(existing))
        )
    for parent in {path.parent for path in resolved.values()}:
        try:
            parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".mm-live-pilot-write-probe-",
                dir=parent,
                delete=True,
            ) as handle:
                handle.write(b"write-probe\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise RuntimeError(
                f"live-pilot output directory is not durably writable: {parent}"
            ) from exc
    return resolved


class LivePilotContext:
    __slots__ = ("credentials", "client", "user_stream", "adapter", "credential_topology")

    def __init__(self, *, credentials, client, user_stream, adapter, credential_topology):
        self.credentials = credentials
        self.client = client
        self.user_stream = user_stream
        self.adapter = adapter
        self.credential_topology = credential_topology

    def __repr__(self) -> str:
        return "LivePilotContext(credentials=<redacted>, client=<redacted>, stream=<redacted>)"


def build_live_pilot_context(
    identity: dict,
    *,
    token_id: str,
    condition_id: str,
    user_stream_journal: str | Path,
    expected_wallet_address: str,
    env=None,
    credential_loader=load_global_credential_bundle,
    client_builder=build_unified_clob_client,
    user_stream_factory=OfficialUserStreamReader,
    adapter_factory=OfficialPolymarketGlobalAdapter,
    position_fetcher=fetch_current_positions,
    heartbeat_sender_factory=OfficialHeartbeatSender,
    market_rule_fetcher=fetch_market_rule_endpoints,
) -> LivePilotContext:
    """Resolve credentials in memory and wire all authoritative live readers."""

    credentials = credential_loader(env)
    client = client_builder(
        credentials,
        identity,
        expected_signer_address=expected_wallet_address,
    )
    try:
        maker_address = str(credentials.funder).strip()
        condition = str(condition_id).strip().lower()
        token = str(token_id).strip()
        user_stream = user_stream_factory(
            api_key=credentials.api_key,
            secret=credentials.api_secret,
            passphrase=credentials.api_passphrase,
            maker_address=maker_address,
            condition_id=condition,
            token_id=token,
            journal_path=user_stream_journal,
        )

        def position_reader():
            return position_fetcher(maker_address, condition)

        heartbeat_sender = heartbeat_sender_factory(
            signer_address=client.signer,
            api_key=credentials.api_key,
            api_secret=credentials.api_secret,
            api_passphrase=credentials.api_passphrase,
        )

        def market_rule_reader():
            return market_rule_fetcher(token)

        adapter = adapter_factory(
            client,
            token_id=token,
            user_event_reader=user_stream.events,
            user_event_health_reader=user_stream.health,
            position_reader=position_reader,
            heartbeat_sender=heartbeat_sender,
            market_rule_reader=market_rule_reader,
            maker_address=maker_address,
            condition_id=condition,
            authoritative_readers_verified=True,
            max_order_notional=10.0,
        )
        if not adapter.diagnostics().get("supports_trading"):
            raise RuntimeError("official adapter did not verify the authoritative reader boundary")
        return LivePilotContext(
            credentials=credentials,
            client=client,
            user_stream=user_stream,
            adapter=adapter,
            credential_topology={
                "manifest_wallet_address": str(expected_wallet_address).lower(),
                "derived_signer_matches_manifest": str(client.signer).lower()
                == str(expected_wallet_address).lower(),
                "api_owner_matches_manifest": str(client.signer).lower()
                == str(expected_wallet_address).lower(),
                "order_signer_matches_manifest": str(client.signer).lower()
                == str(expected_wallet_address).lower(),
                "funder_matches_identity": maker_address.lower()
                == str(identity.get("funder_address") or "").lower(),
            },
        )
    except BaseException:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
        raise


def wait_for_user_stream(
    user_stream,
    *,
    timeout_seconds: float = 45.0,
    monotonic_clock=time.monotonic,
    sleeper=time.sleep,
) -> dict:
    timeout = float(timeout_seconds)
    if not 1 <= timeout <= 120:
        raise ValueError("user-stream ready timeout must be between 1 and 120 seconds")
    user_stream.start()
    deadline = monotonic_clock() + timeout
    while monotonic_clock() <= deadline:
        evidence = user_stream.bootstrap_evidence()
        if all(
            (
                evidence.get("account_wide_subscription_sent") is True,
                evidence.get("server_pong_observed") is True,
                evidence.get("transport_active") is True,
                evidence.get("transport_state")
                in {"TRANSPORT_CONNECTED_UNPROVEN", "SUBSCRIPTION_PROVEN"},
            )
        ):
            return evidence
        health = user_stream.health()
        if health.get("state") == "FAILED":
            raise RuntimeError("authoritative user stream failed before readiness")
        sleeper(0.1)
    raise RuntimeError("authoritative user stream did not become ready before its deadline")


def _cleanup_context(
    context: LivePilotContext | None,
    *,
    cancel_all_required: bool = True,
) -> dict:
    outcome = {
        "attempted": context is not None,
        "cancel_all_required": bool(cancel_all_required),
        "cancel_all_sent": False,
        "zero_open_orders_verified": False,
        "zero_positions_verified": False,
        "user_stream_stopped": False,
        "client_closed": False,
        "user_stream_journal_sha256": None,
        "ok": context is None,
        "exception_type": None,
    }
    if context is None:
        return outcome
    try:
        if cancel_all_required:
            context.adapter.cancel_all()
            outcome["cancel_all_sent"] = True
        outcome["zero_open_orders_verified"] = not bool(context.adapter.open_orders())
        positions = context.adapter.positions()
        evidence = context.adapter.position_evidence(positions)
        outcome["zero_positions_verified"] = (
            not bool(positions)
            and exact_current_positions_evidence(
                evidence,
                maker_address=context.adapter.maker_address,
                condition_id=context.adapter.condition_id,
                rows=positions,
            )
        )
    except BaseException as exc:  # receipt records type only; never raw SDK text
        outcome["exception_type"] = type(exc).__name__
    finally:
        try:
            context.user_stream.stop()
            stream_evidence = context.user_stream.bootstrap_evidence()
            stream_health = context.user_stream.health()
            outcome["user_stream_stopped"] = bool(
                stream_health.get("state") == "STOPPED"
                and stream_evidence.get("transport_active") is False
                and stream_evidence.get("transport_state") == "STOPPED"
            )
            journal_sha256 = str(stream_evidence.get("journal_sha256") or "")
            if len(journal_sha256) == 64:
                outcome["user_stream_journal_sha256"] = journal_sha256
        except BaseException as exc:
            outcome["exception_type"] = outcome["exception_type"] or type(exc).__name__
        try:
            close = getattr(context.client, "close", None)
            if not callable(close):
                raise RuntimeError("official client does not expose close")
            close()
            outcome["client_closed"] = True
        except BaseException as exc:
            outcome["exception_type"] = outcome["exception_type"] or type(exc).__name__
    outcome["ok"] = all(
        (
            outcome["cancel_all_sent"] or not outcome["cancel_all_required"],
            outcome["zero_open_orders_verified"],
            outcome["zero_positions_verified"],
            outcome["user_stream_stopped"],
            outcome["client_closed"],
            outcome["exception_type"] is None,
        )
    )
    return outcome


def _receipt(command: str, args, paths: dict[str, Path]) -> dict:
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "started_at_utc": _utc_iso(),
        "finished_at_utc": None,
        "status": "STARTING",
        "command": command,
        "platform": "polymarket_global",
        "settlement_unit": "pUSD",
        "target_date": getattr(args, "target_date", None),
        "condition_id": (
            str(args.condition_id).lower()
            if getattr(args, "condition_id", None) is not None
            else None
        ),
        "token_id": (
            str(args.token_id) if getattr(args, "token_id", None) is not None else None
        ),
        "requested_budget_pusd": float(args.budget),
        "cancellation_mode": getattr(args, "cancellation_mode", None),
        "paths": {name: str(path) for name, path in paths.items()},
        "exception_type": None,
        "cleanup": None,
        "secret_values_redacted": True,
    }


def _validate_budget(value) -> float:
    budget = float(value)
    if not 0 < budget <= MAX_PILOT_BUDGET:
        raise RuntimeError("requested budget must be greater than zero and at most 100 pUSD")
    return budget


def _require_current_deadline(value, *, label: str) -> str:
    try:
        deadline = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"{label} deadline is invalid") from exc
    if deadline.tzinfo is None or datetime.now(timezone.utc) >= deadline.astimezone(
        timezone.utc
    ):
        raise RuntimeError(f"{label} deadline has expired")
    return deadline.isoformat()


def run_prepare_identity(
    args,
    *,
    identity_gate=stage0_client_identity_gate,
) -> dict:
    """Create a public Stage 0 identity manifest."""

    if args.confirmation != IDENTITY_CONFIRMATION:
        raise RuntimeError("identity preparation requires the exact confirmation token")
    budget = _validate_budget(args.budget)
    wallet_cap = _validate_budget(args.wallet_cap)
    if budget != 10.0 or wallet_cap != 100.0 or budget > wallet_cap:
        raise RuntimeError(
            "first identity requires a 10 pUSD request and separate 100 pUSD wallet cap"
        )
    paths = _require_new_distinct_paths(
        {
            "identity": args.identity_out,
            "receipt": args.receipt_out,
        }
    )
    receipt = _receipt("prepare-identity", args, paths)
    receipt["cleanup"] = {
        "attempted": False,
        "ok": True,
        "reason": "read_only_command_no_exchange_authentication",
    }
    operation_error = None
    identity = None
    try:
        signature_type = str(args.signature_type).upper()
        signature_type_id = SIGNATURE_TYPE_IDS[signature_type]
        identity = {
            "schema_version": STAGE0_IDENTITY_SCHEMA_VERSION,
            "operator_authorization": STAGE0_AUTHORIZATION,
            "platform": "polymarket_global",
            "international_platform_confirmed": bool(
                args.confirm_international_platform
            ),
            "clob_host": "https://clob.polymarket.com",
            "settlement_unit": INTERNATIONAL_SETTLEMENT_UNIT,
            "chain_id": 137,
            "sdk_distribution": OFFICIAL_CLOB_DISTRIBUTION,
            "sdk_version": OFFICIAL_CLOB_VERSION,
            "wallet_type": str(args.wallet_type).strip(),
            "signature_type": signature_type,
            "signature_type_id": signature_type_id,
            "funder_address": str(args.funder_address).strip(),
            "isolated_pilot_wallet": bool(args.confirm_isolated_wallet),
            "pilot_wallet_max_funding_usdc": wallet_cap,
        }
        gate = identity_gate(identity)
        receipt["checks"] = dict(gate.get("checks") or {})
        receipt["missing"] = list(gate.get("missing") or [])
        if not gate.get("ok"):
            raise RuntimeError("prepared Stage 0 identity did not pass its public gate")
    except Exception as exc:
        operation_error = exc
    if operation_error is None:
        try:
            write_json_atomic(paths["identity"], identity, trailing_newline=True)
        except Exception as exc:
            operation_error = exc
    if operation_error is None:
        receipt["status"] = "PASS"
    else:
        receipt["status"] = "FAIL"
        receipt["exception_type"] = type(operation_error).__name__
    receipt["finished_at_utc"] = _utc_iso()
    write_json_atomic(paths["receipt"], receipt, trailing_newline=True)
    if operation_error is not None:
        raise operation_error
    return receipt


def run_doctor(
    args,
    *,
    env=None,
    sdk_version_getter=installed_official_clob_version,
    platform_name=os.name,
) -> dict:
    """Run the complete keyless setup check without resolving any credential."""

    if args.confirmation != DOCTOR_CONFIRMATION:
        raise RuntimeError("keyless doctor requires the exact confirmation token")
    budget = _validate_budget(args.budget)
    paths = _require_new_distinct_paths({"receipt": args.receipt_out})
    receipt = _receipt("doctor", args, paths)
    receipt["cleanup"] = {
        "attempted": False,
        "ok": True,
        "reason": "keyless_command_no_credential_resolution_or_exchange_authentication",
    }
    receipt["sdk_overlay_activation"] = getattr(
        args, "sdk_overlay_activation", None
    )
    process_env = env if env is not None else os.environ
    operation_error = None
    try:
        identity = _read_json_object(args.identity)
        public_funder = str(process_env.get(FUNDER_ENV) or "").strip()
        identity_result = stage0_client_identity_gate(
            identity,
            expected_funder=public_funder if public_funder else "missing-public-funder",
        )
        diagnostics = credential_diagnostics("polymarket_global", env=process_env)
        reference_shapes_valid = True
        for variable_name in REFERENCE_ENV.values():
            try:
                parse_wincred_reference(process_env.get(variable_name))
            except (TypeError, ValueError):
                reference_shapes_valid = False
        installed_version = sdk_version_getter()
        try:
            ensure_date(args.target_date)
            target_date_valid = True
        except (TypeError, ValueError):
            target_date_valid = False
        token_text = str(args.token_id or "").strip()
        condition_text = str(args.condition_id or "").strip().lower()
        try:
            wallet_cap = float(identity.get("pilot_wallet_max_funding_usdc"))
        except (TypeError, ValueError):
            wallet_cap = None
        checks = {
            "windows_credential_resolver_available": platform_name == "nt",
            "stage0_identity_gate_passes": identity_result.get("ok") is True,
            "credential_reference_variables_complete": diagnostics.get("ok") is True,
            "credential_reference_shapes_valid": reference_shapes_valid,
            "direct_secret_environment_absent": not bool(
                diagnostics.get("forbidden_direct_secret_env_names_present")
            ),
            "public_funder_present": bool(public_funder),
            "public_funder_matches_identity": bool(public_funder)
            and public_funder.lower()
            == str(identity.get("funder_address") or "").lower(),
            "official_sdk_exact_version_installed": installed_version
            == OFFICIAL_CLOB_VERSION,
            "target_date_valid": target_date_valid,
            "condition_id_valid": CONDITION_ID_RE.fullmatch(condition_text) is not None,
            "token_id_valid": token_text.isdigit() and int(token_text) > 0,
            "requested_budget_within_identity_cap": wallet_cap is not None
            and 0 < budget <= wallet_cap <= MAX_PILOT_BUDGET,
        }
        missing = [name for name, passed in checks.items() if not passed]
        receipt["checks"] = checks
        receipt["missing"] = missing
        receipt["identity_missing"] = list(identity_result.get("missing") or [])
        receipt["credential_reference_name_count"] = len(REFERENCE_ENV)
        receipt["credential_reference_present_count"] = len(
            diagnostics.get("present_env_names") or []
        ) - (1 if FUNDER_ENV in (diagnostics.get("present_env_names") or []) else 0)
        receipt["official_sdk_required_version"] = OFFICIAL_CLOB_VERSION
        receipt["official_sdk_installed_version"] = installed_version
        if missing:
            raise RuntimeError("keyless doctor found blocking setup checks")
    except Exception as exc:
        operation_error = exc
    receipt["status"] = "PASS" if operation_error is None else "FAIL"
    if operation_error is not None:
        receipt["exception_type"] = type(operation_error).__name__
    receipt["finished_at_utc"] = _utc_iso()
    write_json_atomic(paths["receipt"], receipt, trailing_newline=True)
    if operation_error is not None:
        raise operation_error
    return receipt


def run_stage0(
    args,
    *,
    context_builder=build_live_pilot_context,
    stream_waiter=wait_for_user_stream,
    bootstrap_collector=collect_platform_bootstrap_payload,
    bootstrap_finalizer=finalize_platform_bootstrap_payload,
) -> dict:
    if args.confirmation != STAGE0_AUTHORIZATION:
        raise RuntimeError(
            "Stage 0 requires the exact heartbeat/account-wide-cancel-all/"
            "no-order confirmation token"
        )
    pre_mutation_attestor = getattr(args, "pre_mutation_attestor", None)
    if not callable(pre_mutation_attestor):
        raise RuntimeError("Stage 0 requires the sealed pre-mutation attestor")
    stage0_budget = _validate_budget(args.budget)
    if stage0_budget != 10.0:
        raise RuntimeError("first Stage 0 requires exactly 10 pUSD")
    try:
        candidate_fee_rate = float(args.expected_candidate_fee_rate)
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeError("Stage 0 requires the sealed candidate fee rate") from exc
    candidate_neg_risk = getattr(args, "expected_candidate_neg_risk", None)
    if (
        not math.isfinite(candidate_fee_rate)
        or candidate_fee_rate <= 0
        or not isinstance(candidate_neg_risk, bool)
    ):
        raise RuntimeError("Stage 0 requires exact eligible candidate market rules")
    credential_deadline = _require_current_deadline(
        getattr(args, "credential_resolution_deadline_utc", None),
        label="Stage 0 credential resolution",
    )
    paths = _require_new_distinct_paths(
        {
            "bootstrap": args.bootstrap_out,
            "receipt": args.receipt_out,
            "user_stream_journal": args.user_stream_journal,
            "geography_premutation_receipt": (
                args.geography_premutation_receipt
            ),
        }
    )
    receipt = _receipt("stage0", args, paths)
    receipt["credential_resolution_attempted"] = False
    receipt["credential_values_read_in_memory"] = False
    receipt["exchange_mutation_attempted"] = False
    receipt["order_submit_attempted"] = False
    receipt["authenticated_exchange_write_attempted"] = False
    receipt["candidate_market_rules"] = {
        "fee_rate": candidate_fee_rate,
        "neg_risk": candidate_neg_risk,
    }
    context = None
    operation_error = None
    payload = None
    try:
        identity = _read_json_object(args.identity)
        _require_current_deadline(
            credential_deadline,
            label="Stage 0 credential resolution",
        )
        receipt["credential_resolution_attempted"] = True
        receipt["credential_values_read_in_memory"] = "UNKNOWN"
        context = context_builder(
            identity,
            token_id=args.token_id,
            condition_id=args.condition_id,
            user_stream_journal=paths["user_stream_journal"],
            expected_wallet_address=args.expected_wallet_address,
        )
        receipt["credential_topology"] = dict(context.credential_topology)
        if not all(context.credential_topology.values()):
            raise RuntimeError("current credential topology differs from sealed public identity")
        receipt["credential_values_read_in_memory"] = True
        stream_waiter(
            context.user_stream,
            timeout_seconds=args.user_stream_ready_timeout_seconds,
        )
        payload = bootstrap_collector(
            context.adapter,
            context.user_stream,
            identity,
            target_date=args.target_date,
            requested_budget_usdc=args.budget,
            secret_hygiene=credential_secret_hygiene(),
            expected_candidate_fee_rate=candidate_fee_rate,
            expected_candidate_neg_risk=candidate_neg_risk,
            pre_mutation_attestor=pre_mutation_attestor,
        )
    except BaseException as exc:
        operation_error = exc

    cleanup = _cleanup_context(
        context,
        # Stage 0 never places an order.  The bootstrap collector owns its one
        # geography-gated cancel-all write; an outer cleanup cancel would be a
        # redundant authenticated mutation with no current geography receipt.
        cancel_all_required=False,
    )
    if context is not None:
        receipt["authenticated_exchange_write_attempted"] = True
        receipt["exchange_mutation_attempted"] = True
    receipt["cleanup"] = cleanup
    geography_path = paths["geography_premutation_receipt"]
    if geography_path.is_file():
        receipt["mutation_geographic_eligibility"] = {
            "path": str(geography_path),
            "sha256": _sha256_file(geography_path),
        }
    if operation_error is None and not cleanup["ok"]:
        operation_error = RuntimeError("final Stage 0 cleanup did not prove zero account state")
    if operation_error is None:
        try:
            payload = bootstrap_finalizer(payload, context.user_stream)
        except BaseException as exc:
            operation_error = exc
    if operation_error is None:
        try:
            write_json_atomic(paths["bootstrap"], payload, trailing_newline=True)
        except BaseException as exc:
            operation_error = exc
    if operation_error is None:
        receipt["status"] = "PASS"
    else:
        receipt["status"] = "FAIL"
        receipt["exception_type"] = type(operation_error).__name__
    receipt["finished_at_utc"] = _utc_iso()
    write_json_atomic(paths["receipt"], receipt, trailing_newline=True)
    if operation_error is not None:
        raise operation_error
    return receipt


def run_stage1(
    args,
    *,
    context_builder=build_live_pilot_context,
    stream_waiter=wait_for_user_stream,
    bootstrap_loader=load_platform_bootstrap_gate,
    candidate_loader=load_stage1_candidate_gate,
    lifecycle_executor=execute_stage1_lifecycle_probe,
) -> dict:
    if args.confirmation != STAGE1_CONFIRMATION:
        raise RuntimeError("Stage 1 requires the exact lifecycle confirmation token")
    pre_submit_attestor = getattr(args, "pre_submit_attestor", None)
    if not callable(pre_submit_attestor):
        raise RuntimeError("Stage 1 requires the sealed pre-submit attestor")
    stage1_budget = _validate_budget(args.budget)
    if stage1_budget != 10.0:
        raise RuntimeError("first Stage 1 probe requires exactly 10 pUSD")
    submit_deadline_utc = getattr(args, "submit_deadline_utc", None)
    if not submit_deadline_utc:
        raise RuntimeError("Stage 1 requires an exact submit deadline")
    credential_deadline = _require_current_deadline(
        getattr(args, "credential_resolution_deadline_utc", None),
        label="Stage 1 credential resolution",
    )
    paths = _require_new_distinct_paths(
        {
            "result": args.result_out,
            "receipt": args.receipt_out,
            "user_stream_journal": args.user_stream_journal,
            "lifecycle_journal": args.lifecycle_journal,
        }
    )
    receipt = _receipt("stage1", args, paths)
    receipt["credential_resolution_attempted"] = False
    receipt["credential_values_read_in_memory"] = False
    receipt["exchange_mutation_attempted"] = False
    receipt["order_submit_attempted"] = False
    receipt["authenticated_exchange_write_attempted"] = False
    context = None
    operation_error = None
    result = None
    try:
        identity = _read_json_object(args.identity)
        candidate_gate = candidate_loader(
            args.candidate_plan,
            args.target_date,
            expected_token_id=args.token_id,
            expected_condition_id=args.condition_id,
        )
        receipt["candidate_gate"] = dict(candidate_gate)
        gate = bootstrap_loader(
            args.bootstrap,
            args.target_date,
            requested_budget_usdc=args.budget,
            expected_token_id=args.token_id,
            expected_condition_id=args.condition_id,
        )
        if not gate.get("ok"):
            raise RuntimeError("Stage 1 platform bootstrap gate is not passing")
        _require_current_deadline(
            credential_deadline,
            label="Stage 1 credential resolution",
        )
        receipt["credential_resolution_attempted"] = True
        receipt["credential_values_read_in_memory"] = "UNKNOWN"
        context = context_builder(
            identity,
            token_id=args.token_id,
            condition_id=args.condition_id,
            user_stream_journal=paths["user_stream_journal"],
            expected_wallet_address=args.expected_wallet_address,
        )
        receipt["credential_topology"] = dict(context.credential_topology)
        if not all(context.credential_topology.values()):
            raise RuntimeError("current credential topology differs from sealed public identity")
        receipt["credential_values_read_in_memory"] = True
        stream_waiter(
            context.user_stream,
            timeout_seconds=args.user_stream_ready_timeout_seconds,
        )
        receipt["authenticated_exchange_write_attempted"] = True
        receipt["exchange_mutation_attempted"] = True
        result = lifecycle_executor(
            context.adapter,
            gate,
            confirmation=args.confirmation,
            cancellation_mode=args.cancellation_mode,
            journal_path=paths["lifecycle_journal"],
            submit_deadline_utc=submit_deadline_utc,
            pre_submit_attestor=pre_submit_attestor,
            expected_candidate_intent=candidate_gate["stage1_intent"],
            expected_candidate_tick_size=candidate_gate["tick_size"],
            expected_candidate_order_min_size=candidate_gate["order_min_size"],
            expected_candidate_fee_rate=candidate_gate["fee_rate"],
            expected_candidate_neg_risk=candidate_gate["neg_risk"],
        )
        receipt["exchange_mutation_attempted"] = True
        receipt["order_submit_attempted"] = True
        result = dict(result or {})
        result["candidate_plan_sha256"] = candidate_gate["plan_sha256"]
        result["candidate_semantic_plan_sha256"] = candidate_gate[
            "semantic_plan_sha256"
        ]
        result["paper_run_config_sha256"] = candidate_gate[
            "paper_run_config_sha256"
        ]
        result["paper_quote_intents_sha256"] = candidate_gate[
            "paper_quote_intents_sha256"
        ]
        result["paper_quote_row_sha256"] = candidate_gate[
            "paper_quote_row_sha256"
        ]
    except BaseException as exc:
        operation_error = exc

    cleanup = _cleanup_context(
        context,
        cancel_all_required=operation_error is not None,
    )
    if context is not None:
        receipt["authenticated_exchange_write_attempted"] = True
        receipt["exchange_mutation_attempted"] = True
    lifecycle_path = Path(paths["lifecycle_journal"])
    if lifecycle_path.is_file():
        try:
            receipt["order_submit_attempted"] = any(
                json.loads(line).get("event_type") == "submit_started"
                for line in lifecycle_path.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            )
        except (OSError, json.JSONDecodeError):
            receipt["order_submit_attempted"] = "UNKNOWN"
    receipt["cleanup"] = cleanup
    if operation_error is None and not cleanup["ok"]:
        operation_error = RuntimeError("final Stage 1 cleanup did not prove zero account state")
    if operation_error is None:
        try:
            cleanup_stream_sha256 = str(
                cleanup.get("user_stream_journal_sha256") or ""
            )
            if len(cleanup_stream_sha256) != 64:
                raise RuntimeError(
                    "Stage 1 cleanup omitted the final user-stream journal hash"
                )
            result["user_stream_journal_path"] = str(
                paths["user_stream_journal"].resolve()
            )
            result["user_stream_journal_sha256"] = cleanup_stream_sha256
            result[
                "cleanup_final_user_stream_journal_sha256"
            ] = cleanup_stream_sha256
            stream_evidence = verify_stage1_user_stream_journal(
                paths["user_stream_journal"],
                result,
            )
            result["user_stream_journal_row_count"] = stream_evidence["row_count"]
            result["user_stream_scoped_order_event_count"] = stream_evidence[
                "scoped_order_event_count"
            ]
        except BaseException as exc:
            operation_error = exc
    if operation_error is None:
        try:
            write_json_atomic(paths["result"], result, trailing_newline=True)
        except BaseException as exc:
            operation_error = exc
    if operation_error is None:
        receipt["status"] = "PASS"
    else:
        receipt["status"] = "FAIL"
        receipt["exception_type"] = type(operation_error).__name__
    receipt["finished_at_utc"] = _utc_iso()
    write_json_atomic(paths["receipt"], receipt, trailing_newline=True)
    if operation_error is not None:
        raise operation_error
    return receipt


def run_bundle(
    args,
    *,
    bootstrap_loader=load_platform_bootstrap_gate,
    bundle_builder=build_stage1_lifecycle_bundle,
) -> dict:
    """Offline binding of the two distinct Stage 1 journal-backed results."""

    if args.confirmation != BUNDLE_CONFIRMATION:
        raise RuntimeError("Stage 1 bundle requires the exact offline confirmation token")
    bundle_budget = _validate_budget(args.budget)
    if bundle_budget != 10.0:
        raise RuntimeError("first Stage 1 bundle requires exactly 10 pUSD")
    paths = _require_new_distinct_paths(
        {
            "bundle": args.bundle_out,
            "receipt": args.receipt_out,
        }
    )
    receipt = _receipt("bundle", args, paths)
    operation_error = None
    bundle = None
    lineages = None
    try:
        gate = bootstrap_loader(
            args.bootstrap,
            args.target_date,
            requested_budget_usdc=args.budget,
            expected_token_id=args.token_id,
            expected_condition_id=args.condition_id,
        )
        if not gate.get("ok"):
            raise RuntimeError("Stage 1 bundle bootstrap gate is not passing")
        if (
            float(gate.get("requested_budget_usdc")) != 10.0
            or float(gate.get("pilot_wallet_max_funding_usdc")) != 100.0
        ):
            raise RuntimeError(
                "Stage 1 bundle does not preserve the 10 pUSD request and 100 pUSD cap"
            )
        cancel_all_result = _read_json_object(args.cancel_all_result)
        dead_man_result = _read_json_object(args.dead_man_result)
        lineages = {
            "cancel_all": _validate_stage1_bundle_lineage(
                args, "cancel_all", args.cancel_all_result
            ),
            "dead_man": _validate_stage1_bundle_lineage(
                args, "dead_man", args.dead_man_result
            ),
        }
        if (
            lineages["cancel_all"]["market_id"]
            != lineages["dead_man"]["market_id"]
            or lineages["cancel_all"]["market_timezone"]
            != lineages["dead_man"]["market_timezone"]
            or lineages["cancel_all"]["interpreter_binding"]
            != lineages["dead_man"]["interpreter_binding"]
        ):
            raise RuntimeError("Stage 1 bundle market/interpreter lineage does not match")
        bundle = bundle_builder(gate, cancel_all_result, dead_man_result)
    except Exception as exc:
        operation_error = exc
    receipt["cleanup"] = {
        "attempted": False,
        "ok": True,
        "reason": "offline_command_no_exchange_state",
    }
    receipt["stage1_lineage"] = lineages
    if operation_error is None:
        try:
            write_json_atomic(paths["bundle"], bundle, trailing_newline=True)
        except Exception as exc:
            operation_error = exc
    if operation_error is None:
        receipt["status"] = "PASS"
    else:
        receipt["status"] = "FAIL"
        receipt["exception_type"] = type(operation_error).__name__
    receipt["finished_at_utc"] = _utc_iso()
    write_json_atomic(paths["receipt"], receipt, trailing_newline=True)
    if operation_error is not None:
        raise operation_error
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    identity = commands.add_parser(
        "prepare-identity",
        help="Build the public Stage 0 identity.",
    )
    identity.add_argument("--funder-address", required=True)
    identity.add_argument(
        "--wallet-type",
        choices=["deposit_wallet", "gnosis_safe"],
        required=True,
    )
    identity.add_argument(
        "--signature-type",
        choices=["POLY_1271", "POLY_GNOSIS_SAFE"],
        required=True,
    )
    identity.add_argument("--budget", required=True, type=float)
    identity.add_argument("--wallet-cap", required=True, type=float)
    identity.add_argument("--identity-out", required=True)
    identity.add_argument("--receipt-out", required=True)
    identity.add_argument("--confirm-international-platform", action="store_true")
    identity.add_argument("--confirm-isolated-wallet", action="store_true")
    identity.add_argument("--confirmation", required=True)

    doctor = commands.add_parser(
        "doctor",
        help="Check keyless host setup without resolving credential values.",
    )
    doctor.add_argument("--identity", required=True)
    doctor.add_argument("--target-date", required=True)
    doctor.add_argument("--condition-id", required=True)
    doctor.add_argument("--token-id", required=True)
    doctor.add_argument("--budget", required=True, type=float)
    doctor.add_argument("--receipt-out", required=True)
    doctor.add_argument("--sdk-overlay-manifest")
    doctor.add_argument("--sdk-overlay-manifest-sha256")
    doctor.add_argument("--confirmation", required=True)

    bundle = commands.add_parser(
        "bundle",
        help="Offline verification and binding of the two Stage 1 results and journals.",
    )
    bundle.add_argument("--target-date", required=True)
    bundle.add_argument("--expected-production-tip", required=True)
    bundle.add_argument("--condition-id", required=True)
    bundle.add_argument("--token-id", required=True)
    bundle.add_argument("--budget", required=True, type=float)
    bundle.add_argument("--bootstrap", required=True)
    bundle.add_argument("--cancel-all-result", required=True)
    bundle.add_argument("--dead-man-result", required=True)
    bundle.add_argument("--cancel-all-seal-receipt", required=True)
    bundle.add_argument("--cancel-all-command-receipt", required=True)
    bundle.add_argument("--cancel-all-execution-receipt", required=True)
    bundle.add_argument("--cancel-all-run-receipt", required=True)
    bundle.add_argument("--dead-man-seal-receipt", required=True)
    bundle.add_argument("--dead-man-command-receipt", required=True)
    bundle.add_argument("--dead-man-execution-receipt", required=True)
    bundle.add_argument("--dead-man-run-receipt", required=True)
    bundle.add_argument("--bundle-out", required=True)
    bundle.add_argument("--receipt-out", required=True)
    bundle.add_argument("--confirmation", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare-identity":
            receipt = run_prepare_identity(args)
        elif args.command == "doctor":
            manifest = getattr(args, "sdk_overlay_manifest", None)
            manifest_hash = getattr(args, "sdk_overlay_manifest_sha256", None)
            if bool(manifest) != bool(manifest_hash):
                raise RuntimeError(
                    "keyless doctor SDK overlay path and hash must be supplied together"
                )
            if manifest:
                from weather.market.live_sdk_overlay import activate_live_sdk_overlay

                args.sdk_overlay_activation = activate_live_sdk_overlay(
                    manifest,
                    manifest_hash,
                )
            receipt = run_doctor(args)
        else:
            receipt = run_bundle(args)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "command": args.command,
                    "exception_type": type(exc).__name__,
                    "receipt_path": str(args.receipt_out),
                    "secret_values_redacted": True,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "command": receipt["command"],
                "receipt_path": str(args.receipt_out),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
