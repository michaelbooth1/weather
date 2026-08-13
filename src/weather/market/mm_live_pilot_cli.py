"""Fail-closed operator CLI for the first International lifecycle probes.

The command accepts only public scope identifiers and paths. Authentication is
resolved from Windows Credential Manager references already present in the
process environment; secret values are never accepted as arguments or written
to artifacts. Stage 1 remains limited to the exact one-submit lifecycle core.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from weather.io import write_json_atomic
from weather.market.mm_credentials import (
    STAGE0_AUTHORIZATION,
    STAGE0_IDENTITY_SCHEMA_VERSION,
    build_pinned_clob_client,
    credential_secret_hygiene,
    load_global_credential_bundle,
    stage0_client_identity_gate,
)
from weather.market.mm_geoblock import collect_official_geoblock_evidence
from weather.market.mm_live_bootstrap import (
    collect_platform_bootstrap_payload,
    finalize_platform_bootstrap_payload,
    load_platform_bootstrap_gate,
)
from weather.market.mm_live_lifecycle_probe import (
    CANCELLATION_MODES,
    CONFIRMATION as STAGE1_CONFIRMATION,
    build_stage1_lifecycle_bundle,
    execute_stage1_lifecycle_probe,
)
from weather.market.mm_official_adapter import (
    OFFICIAL_CLOB_DISTRIBUTION,
    OFFICIAL_CLOB_VERSION,
    OfficialPolymarketGlobalAdapter,
    exact_current_positions_evidence,
    fetch_current_positions,
)
from weather.market.mm_user_stream import OfficialUserStreamReader
from weather.market.market_making_preflight import (
    INTERNATIONAL_SETTLEMENT_UNIT,
    SIGNATURE_TYPE_IDS,
)
from weather.schema_registry import schema_version


RECEIPT_SCHEMA_VERSION = schema_version("mm_live_pilot_command_receipt")
MAX_PILOT_BUDGET = 100.0
BUNDLE_CONFIRMATION = "INTERNATIONAL_POLYMARKET_STAGE1_BUILD_BUNDLE"
IDENTITY_CONFIRMATION = "INTERNATIONAL_POLYMARKET_PREPARE_STAGE0_IDENTITY"


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
    client_builder=build_pinned_clob_client,
    user_stream_factory=OfficialUserStreamReader,
    adapter_factory=OfficialPolymarketGlobalAdapter,
    position_fetcher=fetch_current_positions,
) -> LivePilotContext:
    """Resolve credentials in memory and wire all authoritative live readers."""

    credentials = credential_loader(env)
    client = client_builder(credentials, identity)
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

    adapter = adapter_factory(
        client,
        token_id=token,
        user_event_reader=user_stream.events,
        user_event_health_reader=user_stream.health,
        position_reader=position_reader,
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
    except Exception as exc:  # receipt records type only; never raw SDK text
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
        except Exception as exc:
            outcome["exception_type"] = outcome["exception_type"] or type(exc).__name__
    outcome["ok"] = all(
        (
            outcome["cancel_all_sent"],
            outcome["zero_open_orders_verified"],
            outcome["zero_positions_verified"],
            outcome["user_stream_stopped"],
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
            "pilot_wallet_max_funding_usdc": budget,
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
    _validate_budget(args.budget)
    paths = _require_new_distinct_paths(
        {
            "bootstrap": args.bootstrap_out,
            "receipt": args.receipt_out,
            "user_stream_journal": args.user_stream_journal,
        }
    )
    receipt = _receipt("stage0", args, paths)
    context = None
    operation_error = None
    payload = None
    try:
        identity = _read_json_object(args.identity)
        context = context_builder(
            identity,
            token_id=args.token_id,
            condition_id=args.condition_id,
            user_stream_journal=paths["user_stream_journal"],
        )
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
        )
    except Exception as exc:
        operation_error = exc

    cleanup = _cleanup_context(context)
    receipt["cleanup"] = cleanup
    if operation_error is None and not cleanup["ok"]:
        operation_error = RuntimeError("final Stage 0 cleanup did not prove zero account state")
    if operation_error is None:
        try:
            payload = bootstrap_finalizer(payload, context.user_stream)
        except Exception as exc:
            operation_error = exc
    if operation_error is None:
        try:
            write_json_atomic(paths["bootstrap"], payload, trailing_newline=True)
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


def run_stage1(
    args,
    *,
    context_builder=build_live_pilot_context,
    stream_waiter=wait_for_user_stream,
    bootstrap_loader=load_platform_bootstrap_gate,
    lifecycle_executor=execute_stage1_lifecycle_probe,
) -> dict:
    if args.confirmation != STAGE1_CONFIRMATION:
        raise RuntimeError("Stage 1 requires the exact lifecycle confirmation token")
    _validate_budget(args.budget)
    paths = _require_new_distinct_paths(
        {
            "result": args.result_out,
            "receipt": args.receipt_out,
            "user_stream_journal": args.user_stream_journal,
            "lifecycle_journal": args.lifecycle_journal,
        }
    )
    receipt = _receipt("stage1", args, paths)
    context = None
    operation_error = None
    result = None
    try:
        identity = _read_json_object(args.identity)
        gate = bootstrap_loader(
            args.bootstrap,
            args.target_date,
            requested_budget_usdc=args.budget,
            expected_token_id=args.token_id,
            expected_condition_id=args.condition_id,
        )
        if not gate.get("ok"):
            raise RuntimeError("Stage 1 platform bootstrap gate is not passing")
        context = context_builder(
            identity,
            token_id=args.token_id,
            condition_id=args.condition_id,
            user_stream_journal=paths["user_stream_journal"],
        )
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
        )
    except Exception as exc:
        operation_error = exc

    cleanup = _cleanup_context(context)
    receipt["cleanup"] = cleanup
    if operation_error is None and not cleanup["ok"]:
        operation_error = RuntimeError("final Stage 1 cleanup did not prove zero account state")
    if operation_error is None:
        try:
            write_json_atomic(paths["result"], result, trailing_newline=True)
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


def run_bundle(
    args,
    *,
    bootstrap_loader=load_platform_bootstrap_gate,
    bundle_builder=build_stage1_lifecycle_bundle,
) -> dict:
    """Offline binding of the two distinct Stage 1 journal-backed results."""

    if args.confirmation != BUNDLE_CONFIRMATION:
        raise RuntimeError("Stage 1 bundle requires the exact offline confirmation token")
    _validate_budget(args.budget)
    paths = _require_new_distinct_paths(
        {
            "bundle": args.bundle_out,
            "receipt": args.receipt_out,
        }
    )
    receipt = _receipt("bundle", args, paths)
    operation_error = None
    bundle = None
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
        cancel_all_result = _read_json_object(args.cancel_all_result)
        dead_man_result = _read_json_object(args.dead_man_result)
        bundle = bundle_builder(gate, cancel_all_result, dead_man_result)
    except Exception as exc:
        operation_error = exc
    receipt["cleanup"] = {
        "attempted": False,
        "ok": True,
        "reason": "offline_command_no_exchange_state",
    }
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


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--identity", required=True)
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--condition-id", required=True)
    parser.add_argument("--token-id", required=True)
    parser.add_argument("--budget", required=True, type=float)
    parser.add_argument("--user-stream-journal", required=True)
    parser.add_argument("--receipt-out", required=True)
    parser.add_argument("--user-stream-ready-timeout-seconds", type=float, default=45.0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    identity = commands.add_parser(
        "prepare-identity",
        help="Fetch current geoblock evidence and build the public Stage 0 identity.",
    )
    identity.add_argument("--funder-address", required=True)
    identity.add_argument("--wallet-type", required=True)
    identity.add_argument(
        "--signature-type",
        choices=sorted(SIGNATURE_TYPE_IDS),
        required=True,
    )
    identity.add_argument("--budget", required=True, type=float)
    identity.add_argument("--identity-out", required=True)
    identity.add_argument("--receipt-out", required=True)
    identity.add_argument("--confirm-international-platform", action="store_true")
    identity.add_argument("--confirm-physical-location-match", action="store_true")
    identity.add_argument("--confirm-no-circumvention", action="store_true")
    identity.add_argument("--confirm-isolated-wallet", action="store_true")
    identity.add_argument("--confirmation", required=True)

    stage0 = commands.add_parser("stage0", help="Collect the pre-order International account bootstrap.")
    _add_common_arguments(stage0)
    stage0.add_argument("--bootstrap-out", required=True)
    stage0.add_argument("--confirmation", required=True)

    stage1 = commands.add_parser("stage1", help="Run exactly one Stage 1 cancellation proof.")
    _add_common_arguments(stage1)
    stage1.add_argument("--bootstrap", required=True)
    stage1.add_argument("--cancellation-mode", choices=sorted(CANCELLATION_MODES), required=True)
    stage1.add_argument("--lifecycle-journal", required=True)
    stage1.add_argument("--result-out", required=True)
    stage1.add_argument("--confirmation", required=True)

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
    bundle.add_argument("--bundle-out", required=True)
    bundle.add_argument("--receipt-out", required=True)
    bundle.add_argument("--confirmation", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare-identity":
            receipt = run_prepare_identity(args)
        elif args.command == "stage0":
            receipt = run_stage0(args)
        elif args.command == "stage1":
            receipt = run_stage1(args)
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
