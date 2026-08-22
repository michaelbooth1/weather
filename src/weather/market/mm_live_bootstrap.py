"""Fail-closed pre-order gate for the first International lifecycle probe.

The full ``mm_platform_verification`` artifact intentionally requires evidence
that only a live order can produce. This module owns the narrower, read-only
bootstrap proof needed before that first order. It does not place orders or
make the general market-making runner accept partial verification.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path

from weather.market.market_making_preflight import (
    INTERNATIONAL_SETTLEMENT_UNIT,
    contains_secret_material,
    dict_value,
    non_empty_text,
    pilot_wallet_identity_topology_checks,
    recent_utc_timestamp,
    signature_type_consistent,
    valid_evm_address,
)
from weather.market.market_making_run_constants import MAX_OPERATOR_PILOT_BUDGET_USDC
from weather.market.market_config import ensure_date
from weather.market.mm_official_adapter import (
    CONDITION_ID_RE,
    OFFICIAL_CLOB_DISTRIBUTION,
    OFFICIAL_CLOB_VERSION,
    exact_current_positions_evidence,
)
from weather.market.mm_policy import bool_value, maybe_float, utc_now
from weather.market.mm_credentials import stage0_client_identity_gate
SCHEMA_VERSION = "mm_platform_bootstrap_v0.3"
PLATFORM_ID = "polymarket_global"
API_BASE_URL = "https://polymarket.com"
CLOB_HOST = "https://clob.polymarket.com"
HEARTBEAT_ENDPOINT = "/heartbeats"
MAX_BOOTSTRAP_AGE_HOURS = 1.0
MAX_STAGE0_USER_STREAM_JOURNAL_BYTES = 10_000_000
REQUIRED_SOURCE_URLS = {
    "https://github.com/Polymarket/py-sdk/tree/c8fb84bb51e60f790239056be7be0f5cc337d2e0",
    "https://docs.polymarket.com/getting-started/migrate-from-previous-sdks",
    "https://docs.polymarket.com/api-reference/trade/send-heartbeat",
    "https://docs.polymarket.com/api-reference/authentication",
    "https://docs.polymarket.com/trading/overview",
    "https://docs.polymarket.com/api-reference/core/get-current-positions-for-a-user",
    "https://docs.polymarket.com/api-reference/wss/user",
    "https://docs.polymarket.com/trading/orders/overview",
    "https://docs.polymarket.com/trading/fees",
    "https://docs.polymarket.com/api-reference/market-data/get-fee-rate",
    "https://docs.polymarket.com/programs/maker-rebates",
    "https://docs.polymarket.com/concepts/pusd",
}
ATOMIC_COLLATERAL_SCALE = Decimal("1000000")


def _canonical_sha256(payload):
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def account_snapshot_sha256(account_snapshot):
    return _canonical_sha256({
        key: value
        for key, value in dict(account_snapshot or {}).items()
        if key != "snapshot_sha256"
    })


def _atomic_collateral_to_usdc(value, field_name):
    if isinstance(value, bool):
        raise RuntimeError(f"{field_name} must be an integer atomic collateral amount")
    text = str(value or "").strip()
    if not text.isdigit():
        raise RuntimeError(f"{field_name} must be an integer atomic collateral amount")
    try:
        amount = Decimal(text) / ATOMIC_COLLATERAL_SCALE
    except InvalidOperation as exc:
        raise RuntimeError(f"{field_name} is invalid") from exc
    if not amount.is_finite() or amount < 0:
        raise RuntimeError(f"{field_name} is invalid")
    return amount


def _closed_only_value(payload):
    if isinstance(payload, bool):
        return payload
    if not isinstance(payload, dict):
        raise RuntimeError("closed-only response must be boolean or an object")
    if "closed_only" in payload:
        value = payload["closed_only"]
    elif "closedOnly" in payload:
        value = payload["closedOnly"]
    else:
        raise RuntimeError("closed-only response omitted its state")
    if not isinstance(value, bool):
        raise RuntimeError("closed-only response state must be boolean")
    return value


def collect_platform_bootstrap_payload(
    adapter,
    user_stream,
    stage0_identity,
    *,
    target_date,
    requested_budget_usdc,
    secret_hygiene,
    now=None,
    monotonic_clock=None,
    sleeper=None,
    heartbeat_cadence_seconds=5.0,
):
    """Collect the observed, secret-free gate required before the first order."""

    identity_gate = stage0_client_identity_gate(stage0_identity, now=now)
    if not identity_gate["ok"]:
        raise RuntimeError(
            "Stage 0 client identity is invalid: " + ", ".join(identity_gate["missing"])
        )
    identity = identity_gate["identity"]
    requested_budget = maybe_float(requested_budget_usdc)
    wallet_cap = identity_gate["pilot_wallet_max_funding_usdc"]
    if (
        requested_budget is None
        or not math.isfinite(requested_budget)
        or requested_budget <= 0
        or requested_budget > wallet_cap
    ):
        raise RuntimeError("requested Stage 0 budget is outside the isolated wallet cap")
    if not getattr(adapter, "supports_trading", False):
        raise RuntimeError("Stage 0 collector requires the verified official adapter boundary")
    if str(getattr(adapter, "maker_address", "") or "").lower() != str(
        identity.get("funder_address") or ""
    ).lower():
        raise RuntimeError("adapter maker does not match the Stage 0 funder")
    if not isinstance(secret_hygiene, dict) or not all(
        secret_hygiene.get(key) is True
        for key in (
            "credentials_by_reference_verified",
            "direct_secret_environment_absent_verified",
            "diagnostic_redaction_verified",
        )
    ):
        raise RuntimeError("Stage 0 secret-hygiene proof is incomplete")

    user_stream_evidence = user_stream.bootstrap_evidence()
    if not all((
        user_stream_evidence.get("account_wide_subscription_sent") is True,
        user_stream_evidence.get("server_pong_observed") is True,
        user_stream_evidence.get("transport_active") is True,
        user_stream_evidence.get("transport_state") in {
            "TRANSPORT_CONNECTED_UNPROVEN",
            "SUBSCRIPTION_PROVEN",
        },
        len(str(user_stream_evidence.get("subscription_shape_sha256") or "")) == 64,
        len(str(user_stream_evidence.get("journal_sha256") or "")) == 64,
    )):
        raise RuntimeError("Stage 0 user stream has no proven server heartbeat")

    client = getattr(adapter, "client", None)
    signer_address = str(getattr(client, "signer", "") if client is not None else "").strip()
    if not valid_evm_address(signer_address):
        raise RuntimeError("pinned SDK did not expose a valid signer address")

    balances = adapter.balances()
    allowances = adapter.allowances()
    if not isinstance(balances, dict) or not isinstance(allowances, dict) or not allowances:
        raise RuntimeError("collateral balance/allowance response is incomplete")
    collateral_balance = _atomic_collateral_to_usdc(balances.get("balance"), "balance")
    collateral_allowances = [
        _atomic_collateral_to_usdc(value, "allowance")
        for value in allowances.values()
    ]
    collateral_allowance = min(collateral_allowances)
    if collateral_balance < Decimal(str(requested_budget)):
        raise RuntimeError("collateral balance does not back the requested Stage 0 budget")
    if collateral_balance > Decimal(str(wallet_cap)):
        raise RuntimeError("collateral balance exceeds the isolated wallet cap")
    if collateral_allowance < Decimal(str(requested_budget)):
        raise RuntimeError("collateral allowance does not back the requested Stage 0 budget")

    open_orders = adapter.open_orders()
    if open_orders:
        raise RuntimeError("Stage 0 requires zero open orders")
    positions = adapter.positions()
    position_evidence = adapter.position_evidence(positions)
    if positions or not exact_current_positions_evidence(
        position_evidence,
        maker_address=adapter.maker_address,
        condition_id=adapter.condition_id,
        rows=positions,
    ):
        raise RuntimeError("Stage 0 requires an observed exact-scope zero-position query")
    closed_only = _closed_only_value(adapter.closed_only_mode())
    if closed_only:
        raise RuntimeError("Stage 0 account is in closed-only mode")

    market_rules = adapter.refresh_market_rules()
    if str(market_rules.get("token_id") or "") != str(adapter.token_id):
        raise RuntimeError("Stage 0 market rules do not match the adapter token")
    fee_evidence = adapter.fees()
    fee_rate_bps = maybe_float(fee_evidence.get("fee_rate_bps"))
    if fee_rate_bps is None or not math.isfinite(fee_rate_bps) or fee_rate_bps <= 0:
        raise RuntimeError("Stage 0 selected market has no positive fee/rebate eligibility")

    signed_preview = adapter.preview_signed_order(
        {
            "token_id": str(adapter.token_id),
            "price": market_rules.get("tick_size"),
            "size": market_rules.get("min_order_size"),
            "side": "BUY",
            "expiration": 0,
        },
        expected_signature_type_id=identity.get("signature_type_id"),
    )
    if not all((
        signed_preview.get("status") == "VERIFIED_NON_POSTING_PREVIEW",
        str(signed_preview.get("client_signer_address") or "").lower()
        == signer_address.lower(),
        str(signed_preview.get("order_signer_address") or "").lower()
        == (
            str(identity.get("funder_address") or "").lower()
            if identity.get("signature_type_id") == 3
            else signer_address.lower()
        ),
        str(signed_preview.get("maker_address") or "").lower()
        == str(identity.get("funder_address") or "").lower(),
        str(signed_preview.get("token_id") or "") == str(adapter.token_id),
        signed_preview.get("signature_type_id") == identity.get("signature_type_id"),
        signed_preview.get("signature_observed") is True,
        signed_preview.get("signature_retained") is False,
        len(str(signed_preview.get("signed_order_sha256") or "")) == 64,
    )):
        raise RuntimeError("Stage 0 signed-order preview did not prove wallet topology")

    cadence = float(heartbeat_cadence_seconds)
    if not 0 < cadence <= 5:
        raise RuntimeError("Stage 0 heartbeat cadence must be in (0, 5] seconds")
    clock = monotonic_clock or time.monotonic
    sleep = sleeper or time.sleep
    try:
        first_started = clock()
        first = adapter.heartbeat()
        first_elapsed = clock() - first_started
        sleep(cadence)
        second_started = clock()
        second = adapter.heartbeat()
        second_elapsed = clock() - second_started
        if (
            first != {"status": "ok"}
            or second != {"status": "ok"}
            or first_elapsed < 0
            or second_elapsed < 0
            or first_elapsed > 7.5
            or second_elapsed > 7.5
        ):
            raise RuntimeError("Stage 0 did not prove two current heartbeat acknowledgments")
    except Exception:
        try:
            adapter.cancel_all()
        except Exception:
            pass
        raise

    cancel_response = adapter.cancel_all()
    if adapter.open_orders():
        raise RuntimeError("Stage 0 cancel-all was not followed by zero open orders")
    user_stream_evidence = user_stream.bootstrap_evidence()
    if not all((
        user_stream_evidence.get("account_wide_subscription_sent") is True,
        user_stream_evidence.get("server_pong_observed") is True,
        user_stream_evidence.get("transport_active") is True,
        user_stream_evidence.get("transport_state") in {
            "TRANSPORT_CONNECTED_UNPROVEN",
            "SUBSCRIPTION_PROVEN",
        },
        len(str(user_stream_evidence.get("subscription_shape_sha256") or "")) == 64,
        len(str(user_stream_evidence.get("journal_sha256") or "")) == 64,
    )):
        raise RuntimeError("Stage 0 user stream stopped before bootstrap completed")
    diagnostics = adapter.diagnostics()
    now_dt = utc_now(now)
    account_snapshot = {
        "balance_allowance_verified": True,
        "collateral_balance_usdc": float(collateral_balance),
        "collateral_allowance_usdc": float(collateral_allowance),
        "closed_only_mode_verified": True,
        "closed_only": False,
        "zero_open_orders_verified": True,
        "open_order_count": 0,
        "position_query_exact_scope_verified": True,
        "zero_positions_verified": True,
        "position_count": 0,
        "source_response_sha256": _canonical_sha256({
            "balances": balances,
            "allowances": allowances,
            "open_orders": open_orders,
            "positions": position_evidence,
            "closed_only": False,
        }),
    }
    account_snapshot["snapshot_sha256"] = account_snapshot_sha256(account_snapshot)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "verified_at_utc": now_dt.isoformat(),
        "verified_for_target_date": ensure_date(target_date).isoformat(),
        "max_age_hours": MAX_BOOTSTRAP_AGE_HOURS,
        "platform": "polymarket_global",
        "international_platform_confirmed": True,
        "api_base_url": API_BASE_URL,
        "clob_host": CLOB_HOST,
        "settlement_unit": INTERNATIONAL_SETTLEMENT_UNIT,
        "wallet_type": identity.get("wallet_type"),
        "signature_type": identity.get("signature_type"),
        "signature_type_id": identity.get("signature_type_id"),
        "funder_address": identity.get("funder_address"),
        "wallet_identity": {
            "private_key_signer_address": signer_address,
            "order_signer_address": signed_preview["order_signer_address"],
            "api_key_owner_address": signer_address,
            "api_key_authentication_verified": True,
            "signed_order_preview_verified": True,
            "signed_order_preview_sha256": signed_preview["signed_order_sha256"],
            "signed_order_preview_signature_retained": False,
            "consistency_verified": True,
        },
        "isolated_pilot_wallet": True,
        "pilot_wallet_max_funding_usdc": wallet_cap,
        "requested_budget_usdc": requested_budget,
        "sdk_contract": {
            "distribution": diagnostics.get("sdk_distribution"),
            "version": diagnostics.get("sdk_version"),
            "exact_version_verified": diagnostics.get("sdk_version_pinned") is True,
            "stage0_identity_verified": True,
        },
        "account_snapshot": account_snapshot,
        "market_snapshot": {
            "condition_id": str(adapter.condition_id).lower(),
            "token_id": str(adapter.token_id),
            "book_verified": True,
            "fee_eligibility_verified": True,
            "fee_rate_bps": fee_rate_bps,
            "min_order_size": market_rules.get("min_order_size"),
            "tick_size": market_rules.get("tick_size"),
            "neg_risk": market_rules.get("neg_risk"),
            "best_bid": market_rules.get("best_bid"),
            "best_ask": market_rules.get("best_ask"),
        },
        "user_stream": user_stream_evidence,
        "dead_man_heartbeat": {
            "endpoint": HEARTBEAT_ENDPOINT,
            "endpoint_verified": True,
            "request_body_absent_verified": True,
            "two_acknowledgments_verified": True,
            "acknowledgment_count": 2,
            "acknowledgment_verified": True,
            "cadence_seconds": cadence,
            "first_ack_seconds": first_elapsed,
            "second_ack_seconds": second_elapsed,
            "heartbeat_acknowledgments_sha256": _canonical_sha256([first, second]),
        },
        "cancel_all": {
            "request_verified": True,
            "response_sha256": _canonical_sha256(cancel_response),
            "zero_open_orders_verified": True,
        },
        "secret_hygiene": dict(secret_hygiene),
        "source_urls": sorted(REQUIRED_SOURCE_URLS),
    }


def finalize_platform_bootstrap_payload(payload, user_stream, *, now=None):
    """Bind a finite Stage 0 artifact to the journal after a clean stream stop.

    The collector proves the stream was active. Stopping that stream appends a
    terminal journal row, so the hash captured while active is necessarily a
    prefix hash. This finalizer preserves the active-at-collection fact while
    replacing the prefix hash with the final durable journal hash.
    """

    finalized = deepcopy(dict(payload or {}))
    collected = dict(finalized.get("user_stream") or {})
    if not all(
        (
            collected.get("account_wide_subscription_sent") is True,
            collected.get("server_pong_observed") is True,
            collected.get("transport_active") is True,
            collected.get("transport_state")
            in {"TRANSPORT_CONNECTED_UNPROVEN", "SUBSCRIPTION_PROVEN"},
            len(str(collected.get("journal_sha256") or "")) == 64,
        )
    ):
        raise RuntimeError("Stage 0 payload lacks active user-stream proof to finalize")
    health = user_stream.health()
    durable = user_stream.bootstrap_evidence()
    if not all(
        (
            health.get("state") == "STOPPED",
            health.get("failure_type") in {None, ""},
            durable.get("transport_active") is False,
            durable.get("transport_state") == "STOPPED",
            len(str(durable.get("journal_sha256") or "")) == 64,
        )
    ):
        raise RuntimeError("Stage 0 user stream did not finalize cleanly")
    journal_path_text = str(getattr(user_stream, "journal_path", "") or "").strip()
    journal_path = Path(journal_path_text).resolve() if journal_path_text else None
    try:
        if (
            journal_path is None
            or not journal_path.is_file()
            or journal_path.stat().st_size > MAX_STAGE0_USER_STREAM_JOURNAL_BYTES
        ):
            raise RuntimeError("Stage 0 user-stream journal is missing or oversized")
        journal_bytes = journal_path.read_bytes()
    except OSError as exc:
        raise RuntimeError("Stage 0 user-stream journal is not readable") from exc
    journal_lines = journal_bytes.splitlines(keepends=True)
    try:
        terminal_row = json.loads(journal_lines[-1].decode("utf-8"))
    except (IndexError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Stage 0 user-stream journal has no valid terminal row") from exc
    prefix_sha256 = hashlib.sha256(b"".join(journal_lines[:-1])).hexdigest()
    durable_sha256 = hashlib.sha256(journal_bytes).hexdigest()
    if not all(
        (
            terminal_row.get("event_type") == "stream_stopped",
            prefix_sha256 == str(collected.get("journal_sha256") or ""),
            durable_sha256 == str(durable.get("journal_sha256") or ""),
        )
    ):
        raise RuntimeError("Stage 0 user-stream journal does not bind collection to stop")
    finalized["user_stream"] = {
        **collected,
        "transport_active_at_collection": True,
        "transport_state_at_collection": collected.get("transport_state"),
        "journal_sha256_at_collection": collected.get("journal_sha256"),
        "transport_active": False,
        "transport_state": "STOPPED",
        "transport_stopped_cleanly_after_collection": True,
        "journal_path": str(journal_path),
        "journal_sha256": durable_sha256,
        "journal_finalized_at_utc": utc_now(now).isoformat(),
    }
    return finalized


def _fail(path, reason):
    return {
        "required": True,
        "ok": False,
        "path": str(path) if path else None,
        "reason": reason,
        "checks": {},
        "missing": ["bootstrap_artifact_available"],
    }


def load_platform_bootstrap_gate(
    path,
    target_date,
    *,
    requested_budget_usdc,
    expected_token_id=None,
    expected_condition_id=None,
    now=None,
):
    """Validate a read-only bootstrap artifact for one exact pilot market."""

    path = Path(path) if path else None
    if path is None:
        return _fail(path, "no platform-bootstrap path provided")
    if not path.exists():
        return _fail(path, "platform-bootstrap artifact missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return _fail(path, f"invalid platform-bootstrap JSON: {exc}")

    now = utc_now(now)
    target_text = ensure_date(target_date).isoformat()
    max_age_hours = maybe_float(payload.get("max_age_hours"))
    if max_age_hours is None or not 0 < max_age_hours <= MAX_BOOTSTRAP_AGE_HOURS:
        max_age_hours = MAX_BOOTSTRAP_AGE_HOURS
    requested_budget = maybe_float(requested_budget_usdc)
    wallet_cap = maybe_float(payload.get("pilot_wallet_max_funding_usdc"))
    wallet_identity = dict_value(payload, "wallet_identity")
    sdk = dict_value(payload, "sdk_contract")
    account = dict_value(payload, "account_snapshot")
    market = dict_value(payload, "market_snapshot")
    user_stream = dict_value(payload, "user_stream")
    final_journal_path_text = str(user_stream.get("journal_path") or "").strip()
    final_journal_sha256 = None
    final_journal_prefix_sha256 = None
    final_journal_terminal_event = None
    if final_journal_path_text:
        try:
            final_journal_path = Path(final_journal_path_text)
            if (
                not final_journal_path.is_file()
                or final_journal_path.stat().st_size
                > MAX_STAGE0_USER_STREAM_JOURNAL_BYTES
            ):
                raise OSError("journal missing or oversized")
            final_journal_bytes = final_journal_path.read_bytes()
            final_journal_lines = final_journal_bytes.splitlines(keepends=True)
            final_journal_sha256 = hashlib.sha256(final_journal_bytes).hexdigest()
            final_journal_prefix_sha256 = hashlib.sha256(
                b"".join(final_journal_lines[:-1])
            ).hexdigest()
            final_journal_terminal_event = json.loads(
                final_journal_lines[-1].decode("utf-8")
            ).get("event_type")
        except (OSError, IndexError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            final_journal_sha256 = None
            final_journal_prefix_sha256 = None
            final_journal_terminal_event = None
    heartbeat = dict_value(payload, "dead_man_heartbeat")
    cancel_all = dict_value(payload, "cancel_all")
    secret_hygiene = dict_value(payload, "secret_hygiene")
    source_urls = payload.get("source_urls") or []
    if isinstance(source_urls, str):
        source_urls = [source_urls]
    cadence_seconds = maybe_float(heartbeat.get("cadence_seconds"))
    collateral_balance = maybe_float(account.get("collateral_balance_usdc"))
    collateral_allowance = maybe_float(account.get("collateral_allowance_usdc"))
    open_order_count = maybe_float(account.get("open_order_count"))
    position_count = maybe_float(account.get("position_count"))
    min_order_size = maybe_float(market.get("min_order_size"))
    tick_size = maybe_float(market.get("tick_size"))
    token_id = str(market.get("token_id") or "").strip()
    condition_id = str(market.get("condition_id") or "").strip()
    wallet_topology_checks = pilot_wallet_identity_topology_checks(
        payload,
        wallet_identity,
    )

    checks = {
        "schema_version_supported": payload.get("schema_version") == SCHEMA_VERSION,
        "status_pass": payload.get("status") == "PASS",
        "target_date_matches": payload.get("verified_for_target_date") == target_text,
        "verified_at_recent": recent_utc_timestamp(
            payload.get("verified_at_utc"),
            now,
            max_age_hours,
        ),
        "platform_is_international": payload.get("platform") == PLATFORM_ID,
        "api_base_url_exact": str(payload.get("api_base_url") or "").rstrip("/").lower()
        == API_BASE_URL,
        "clob_host_exact": str(payload.get("clob_host") or "").rstrip("/").lower()
        == CLOB_HOST,
        "settlement_unit_is_native_pusd": payload.get("settlement_unit")
        == INTERNATIONAL_SETTLEMENT_UNIT,
        "signature_type_consistent": signature_type_consistent(payload),
        "private_key_signer_address_valid": valid_evm_address(
            wallet_identity.get("private_key_signer_address")
        ),
        "order_signer_address_valid": valid_evm_address(
            wallet_identity.get("order_signer_address")
        ),
        "api_key_owner_address_valid": valid_evm_address(
            wallet_identity.get("api_key_owner_address")
        ),
        "funder_address_valid": valid_evm_address(payload.get("funder_address")),
        "wallet_identity_consistency_verified": bool_value(
            wallet_identity.get("consistency_verified"),
            False,
        ),
        "api_key_authentication_verified": bool_value(
            wallet_identity.get("api_key_authentication_verified"),
            False,
        ),
        "signed_order_preview_verified": (
            bool_value(wallet_identity.get("signed_order_preview_verified"), False)
            and len(str(wallet_identity.get("signed_order_preview_sha256") or "")) == 64
            and wallet_identity.get("signed_order_preview_signature_retained") is False
        ),
        **wallet_topology_checks,
        "isolated_pilot_wallet": bool_value(payload.get("isolated_pilot_wallet"), False),
        "wallet_cap_within_operator_limit": (
            wallet_cap is not None
            and 0 < wallet_cap <= MAX_OPERATOR_PILOT_BUDGET_USDC
        ),
        "requested_budget_within_wallet_cap": (
            requested_budget is not None
            and requested_budget > 0
            and wallet_cap is not None
            and requested_budget <= wallet_cap
        ),
        "sdk_distribution_exact": sdk.get("distribution") == OFFICIAL_CLOB_DISTRIBUTION,
        "sdk_version_exact": sdk.get("version") == OFFICIAL_CLOB_VERSION,
        "sdk_exact_version_verified": bool_value(sdk.get("exact_version_verified"), False),
        "sdk_stage0_identity_verified": bool_value(
            sdk.get("stage0_identity_verified"),
            False,
        ),
        "account_balance_allowance_verified": bool_value(
            account.get("balance_allowance_verified"),
            False,
        ),
        "account_balance_backs_requested_budget": (
            collateral_balance is not None
            and requested_budget is not None
            and collateral_balance >= requested_budget
        ),
        "account_balance_within_wallet_cap": (
            collateral_balance is not None
            and wallet_cap is not None
            and collateral_balance <= wallet_cap
        ),
        "account_allowance_backs_requested_budget": (
            collateral_allowance is not None
            and requested_budget is not None
            and collateral_allowance >= requested_budget
        ),
        "account_snapshot_hash_recorded": len(
            str(account.get("snapshot_sha256") or "")
        ) == 64,
        "account_snapshot_hash_matches_content": (
            str(account.get("snapshot_sha256") or "")
            == account_snapshot_sha256(account)
        ),
        "account_closed_only_mode_verified": bool_value(
            account.get("closed_only_mode_verified"),
            False,
        ),
        "account_not_closed_only": account.get("closed_only") is False,
        "account_zero_open_orders_verified": bool_value(
            account.get("zero_open_orders_verified"),
            False,
        ),
        "account_open_order_count_zero": open_order_count == 0.0,
        "account_position_query_exact_scope_verified": bool_value(
            account.get("position_query_exact_scope_verified"),
            False,
        ),
        "account_zero_positions_verified": bool_value(
            account.get("zero_positions_verified"),
            False,
        ),
        "account_position_count_zero": position_count == 0.0,
        "market_condition_id_recorded": bool(CONDITION_ID_RE.fullmatch(condition_id)),
        "market_token_id_recorded": token_id.isdigit() and int(token_id) > 0,
        "market_expected_condition_matches": (
            expected_condition_id is None or condition_id == str(expected_condition_id)
        ),
        "market_expected_token_matches": (
            expected_token_id is None or token_id == str(expected_token_id)
        ),
        "market_book_verified": bool_value(market.get("book_verified"), False),
        "market_fee_eligibility_verified": bool_value(
            market.get("fee_eligibility_verified"),
            False,
        ),
        "market_min_order_size_valid": min_order_size is not None and min_order_size > 0,
        "market_tick_size_valid": tick_size is not None and 0 < tick_size < 1,
        "market_neg_risk_recorded": isinstance(market.get("neg_risk"), bool),
        "user_stream_account_wide_request_recorded": bool_value(
            user_stream.get("account_wide_subscription_sent"),
            False,
        ),
        "user_stream_server_pong_observed": bool_value(
            user_stream.get("server_pong_observed"),
            False,
        ),
        "user_stream_cleanly_finalized": (
            bool_value(user_stream.get("transport_active_at_collection"), False)
            and user_stream.get("transport_state_at_collection") in {
                "TRANSPORT_CONNECTED_UNPROVEN",
                "SUBSCRIPTION_PROVEN",
            }
            and user_stream.get("transport_active") is False
            and user_stream.get("transport_state") == "STOPPED"
            and bool_value(
                user_stream.get("transport_stopped_cleanly_after_collection"),
                False,
            )
            and len(str(user_stream.get("journal_sha256_at_collection") or "")) == 64
            and len(str(user_stream.get("journal_sha256") or "")) == 64
        ),
        "user_stream_final_journal_content_bound": (
            final_journal_sha256 is not None
            and final_journal_sha256 == str(user_stream.get("journal_sha256") or "")
            and final_journal_prefix_sha256
            == str(user_stream.get("journal_sha256_at_collection") or "")
            and final_journal_terminal_event == "stream_stopped"
        ),
        "user_stream_subscription_shape_hash_recorded": len(
            str(user_stream.get("subscription_shape_sha256") or "")
        ) == 64,
        "user_stream_journal_hash_recorded": len(
            str(user_stream.get("journal_sha256") or "")
        ) == 64,
        "user_stream_silence_timeout_verified": (
            maybe_float(user_stream.get("heartbeat_seconds")) is not None
            and maybe_float(user_stream.get("inbound_silence_seconds")) is not None
            and maybe_float(user_stream.get("heartbeat_seconds")) > 0
            and maybe_float(user_stream.get("inbound_silence_seconds"))
            > maybe_float(user_stream.get("heartbeat_seconds"))
        ),
        "heartbeat_endpoint_verified": (
            heartbeat.get("endpoint") == HEARTBEAT_ENDPOINT
            and bool_value(heartbeat.get("endpoint_verified"), False)
        ),
        "heartbeat_request_body_absent_verified": bool_value(
            heartbeat.get("request_body_absent_verified"),
            False,
        ),
        "heartbeat_two_acknowledgments_verified": (
            bool_value(heartbeat.get("two_acknowledgments_verified"), False)
            and heartbeat.get("acknowledgment_count") == 2
            and len(str(heartbeat.get("heartbeat_acknowledgments_sha256") or "")) == 64
        ),
        "heartbeat_acknowledgment_verified": bool_value(
            heartbeat.get("acknowledgment_verified"),
            False,
        ),
        "heartbeat_cadence_verified": cadence_seconds is not None and 0 < cadence_seconds <= 5,
        "cancel_all_request_verified": bool_value(cancel_all.get("request_verified"), False),
        "cancel_all_zero_open_orders_verified": bool_value(
            cancel_all.get("zero_open_orders_verified"),
            False,
        ),
        "credentials_by_reference_verified": bool_value(
            secret_hygiene.get("credentials_by_reference_verified"),
            False,
        ),
        "direct_secret_environment_absent_verified": bool_value(
            secret_hygiene.get("direct_secret_environment_absent_verified"),
            False,
        ),
        "diagnostic_redaction_verified": bool_value(
            secret_hygiene.get("diagnostic_redaction_verified"),
            False,
        ),
        "no_secret_material": not contains_secret_material(payload),
        "source_urls_recorded": any(non_empty_text(url) for url in source_urls),
        "required_source_urls_recorded": REQUIRED_SOURCE_URLS.issubset(
            {str(url).rstrip("/") for url in source_urls}
        ),
    }
    missing = [name for name, ok in checks.items() if not ok]
    return {
        "required": True,
        "ok": not missing,
        "path": str(path),
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "target_date": target_text,
        "verified_at_utc": payload.get("verified_at_utc"),
        "platform": payload.get("platform"),
        "settlement_unit": payload.get("settlement_unit"),
        "sdk_distribution": sdk.get("distribution"),
        "sdk_version": sdk.get("version"),
        "signature_type": payload.get("signature_type"),
        "signature_type_id": payload.get("signature_type_id"),
        "funder_address": payload.get("funder_address"),
        "requested_budget_usdc": requested_budget,
        "pilot_wallet_max_funding_usdc": wallet_cap,
        "collateral_balance_usdc": collateral_balance,
        "collateral_allowance_usdc": collateral_allowance,
        "account_snapshot_sha256": account.get("snapshot_sha256"),
        "condition_id": condition_id,
        "token_id": token_id,
        "checks": checks,
        "missing": missing,
        "reason": "ok" if not missing else "platform bootstrap proof missing: " + ", ".join(missing),
    }
