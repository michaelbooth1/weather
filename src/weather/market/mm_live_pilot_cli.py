"""Fail-closed preparation CLI for the first International lifecycle probes.

The command accepts only public scope identifiers and paths. Authentication is
resolved from Windows Credential Manager references already present in the
process environment; secret values are never accepted as arguments or written
to artifacts. Exchange-mutating Stage 0 and Stage 1 functions are deliberately
not exposed by this parser; a separately reviewed host-owned wrapper must call
those library boundaries on an eligible machine. Stage 1 additionally requires
a fresh non-authorizing candidate plan bound to a successful paper-only quote.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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
from weather.market.mm_geoblock import collect_official_geoblock_evidence
from weather.market.mm_live_bootstrap import (
    collect_platform_bootstrap_payload,
    finalize_platform_bootstrap_payload,
    load_platform_bootstrap_gate,
)
from weather.market.mm_live_lifecycle_probe import (
    CONFIRMATION as STAGE1_CONFIRMATION,
    build_stage1_lifecycle_bundle,
    execute_stage1_lifecycle_probe,
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
from weather.schema_registry import schema_version


RECEIPT_SCHEMA_VERSION = schema_version("mm_live_pilot_command_receipt")
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


def _validate_stage1_bundle_lineage(args, mode: str, result_path: str | Path) -> dict:
    stage_name = "stage1_cancel_all" if mode == "cancel_all" else "stage1_dead_man"
    prefix = "cancel_all" if mode == "cancel_all" else "dead_man"
    seal_path = Path(getattr(args, f"{prefix}_seal_receipt")).resolve()
    command_path = Path(getattr(args, f"{prefix}_command_receipt")).resolve()
    execution_path = Path(getattr(args, f"{prefix}_execution_receipt")).resolve()
    result = Path(result_path).resolve()
    seal = _read_json_object(seal_path)
    command = _read_json_object(command_path)
    execution = _read_json_object(execution_path)
    seal_scope = seal.get("scope") if isinstance(seal.get("scope"), dict) else {}
    seal_wrapper = seal.get("wrapper") if isinstance(seal.get("wrapper"), dict) else {}
    execution_wrapper = (
        execution.get("wrapper") if isinstance(execution.get("wrapper"), dict) else {}
    )
    artifacts = execution.get("artifacts") if isinstance(execution.get("artifacts"), dict) else {}
    result_artifact = artifacts.get("result_out") or {}
    command_artifact = artifacts.get("command_receipt_out") or {}
    journal_artifact = artifacts.get("lifecycle_journal_out") or {}
    checks = {
        "seal": seal.get("schema_version") == "international_live_fixed_scope_seal_v0.2"
        and seal.get("status") == "PASS"
        and seal.get("stage") == stage_name,
        "seal_scope": seal_scope.get("target_date") == args.target_date
        and str(seal_scope.get("condition_id") or "").lower()
        == str(args.condition_id).lower()
        and str(seal_scope.get("token_id") or "") == str(args.token_id)
        and float(seal_scope.get("requested_budget_pusd")) == float(args.budget)
        and seal_scope.get("cancellation_mode") == mode,
        "command": command.get("schema_version") == RECEIPT_SCHEMA_VERSION
        and command.get("status") == "PASS"
        and command.get("command") == "stage1"
        and command.get("target_date") == args.target_date
        and str(command.get("condition_id") or "").lower()
        == str(args.condition_id).lower()
        and str(command.get("token_id") or "") == str(args.token_id)
        and float(command.get("requested_budget_pusd")) == float(args.budget)
        and command.get("cancellation_mode") == mode
        and (command.get("cleanup") or {}).get("ok") is True
        and command.get("exception_type") is None,
        "execution": execution.get("schema_version")
        == "international_live_fixed_scope_execution_v0.2"
        and execution.get("status") == "PASS"
        and execution.get("stage") == stage_name
        and execution.get("target_date") == args.target_date
        and str(execution.get("condition_id") or "").lower()
        == str(args.condition_id).lower()
        and str(execution.get("token_id") or "") == str(args.token_id)
        and float(execution.get("requested_budget_pusd")) == float(args.budget)
        and execution.get("cancellation_mode") == mode
        and execution.get("exception_type") is None,
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
        "result_sha256": _sha256_file(result),
        "journal_sha256": journal_artifact["sha256"],
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
    __slots__ = ("credentials", "client", "user_stream", "adapter")

    def __init__(self, *, credentials, client, user_stream, adapter):
        self.credentials = credentials
        self.client = client
        self.user_stream = user_stream
        self.adapter = adapter

    def __repr__(self) -> str:
        return "LivePilotContext(credentials=<redacted>, client=<redacted>, stream=<redacted>)"


def build_live_pilot_context(
    identity: dict,
    *,
    token_id: str,
    condition_id: str,
    user_stream_journal: str | Path,
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
    client = client_builder(credentials, identity)
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


def _cleanup_context(context: LivePilotContext | None) -> dict:
    outcome = {
        "attempted": context is not None,
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
            outcome["cancel_all_sent"],
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
    geoblock_collector=collect_official_geoblock_evidence,
    identity_gate=stage0_client_identity_gate,
) -> dict:
    """Create a current, public, IP-redacted Stage 0 identity manifest."""

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
        evidence = geoblock_collector()
        identity = {
            "schema_version": STAGE0_IDENTITY_SCHEMA_VERSION,
            "operator_authorization": STAGE0_AUTHORIZATION,
            "platform": "polymarket_global",
            "international_platform_confirmed": bool(
                args.confirm_international_platform
            ),
            "physical_location_matches_geoblock_confirmed": bool(
                args.confirm_physical_location_match
            ),
            "geoblock_circumvention_absent_confirmed": bool(
                args.confirm_no_circumvention
            ),
            "geographic_eligibility": evidence,
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
        receipt["geographic_eligibility"] = {
            key: evidence.get(key)
            for key in (
                "schema_version",
                "endpoint",
                "checked_at_utc",
                "http_status",
                "blocked",
                "country",
                "region",
                "official_response_fields_sha256",
                "requesting_ip_observed",
                "requesting_ip_retained",
                "proxy_configuration_absent",
                "evidence_sha256",
            )
        }
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
        raise RuntimeError("Stage 0 requires the exact read-only confirmation token")
    stage0_budget = _validate_budget(args.budget)
    if stage0_budget != 10.0:
        raise RuntimeError("first Stage 0 requires exactly 10 pUSD")
    credential_deadline = _require_current_deadline(
        getattr(args, "credential_resolution_deadline_utc", None),
        label="Stage 0 credential resolution",
    )
    paths = _require_new_distinct_paths(
        {
            "bootstrap": args.bootstrap_out,
            "receipt": args.receipt_out,
            "user_stream_journal": args.user_stream_journal,
        }
    )
    receipt = _receipt("stage0", args, paths)
    receipt["credential_resolution_attempted"] = False
    receipt["credential_values_read_in_memory"] = False
    receipt["exchange_mutation_attempted"] = False
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
        )
        receipt["credential_values_read_in_memory"] = True
        stream_waiter(
            context.user_stream,
            timeout_seconds=args.user_stream_ready_timeout_seconds,
        )
        receipt["exchange_mutation_attempted"] = True
        payload = bootstrap_collector(
            context.adapter,
            context.user_stream,
            identity,
            target_date=args.target_date,
            requested_budget_usdc=args.budget,
            secret_hygiene=credential_secret_hygiene(),
        )
    except BaseException as exc:
        operation_error = exc

    cleanup = _cleanup_context(context)
    receipt["cleanup"] = cleanup
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
        )
        receipt["credential_values_read_in_memory"] = True
        stream_waiter(
            context.user_stream,
            timeout_seconds=args.user_stream_ready_timeout_seconds,
        )
        result = lifecycle_executor(
            context.adapter,
            gate,
            confirmation=args.confirmation,
            cancellation_mode=args.cancellation_mode,
            journal_path=paths["lifecycle_journal"],
            submit_deadline_utc=submit_deadline_utc,
        )
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

    cleanup = _cleanup_context(context)
    receipt["cleanup"] = cleanup
    if operation_error is None and not cleanup["ok"]:
        operation_error = RuntimeError("final Stage 1 cleanup did not prove zero account state")
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
        help="Fetch current geoblock evidence and build the public Stage 0 identity.",
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
    identity.add_argument("--confirm-physical-location-match", action="store_true")
    identity.add_argument("--confirm-no-circumvention", action="store_true")
    identity.add_argument("--confirm-isolated-wallet", action="store_true")
    identity.add_argument("--confirmation", required=True)

    doctor = commands.add_parser(
        "doctor",
        help="Check keyless eligible-host setup without resolving credential values.",
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
    bundle.add_argument("--condition-id", required=True)
    bundle.add_argument("--token-id", required=True)
    bundle.add_argument("--budget", required=True, type=float)
    bundle.add_argument("--bootstrap", required=True)
    bundle.add_argument("--cancel-all-result", required=True)
    bundle.add_argument("--dead-man-result", required=True)
    bundle.add_argument("--cancel-all-seal-receipt", required=True)
    bundle.add_argument("--cancel-all-command-receipt", required=True)
    bundle.add_argument("--cancel-all-execution-receipt", required=True)
    bundle.add_argument("--dead-man-seal-receipt", required=True)
    bundle.add_argument("--dead-man-command-receipt", required=True)
    bundle.add_argument("--dead-man-execution-receipt", required=True)
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
