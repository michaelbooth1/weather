"""Preflight gates and remediation helpers for market-making runs."""

from __future__ import annotations

import json
import hashlib
import re
from collections import Counter
from datetime import timedelta
from pathlib import Path

from weather.collection.redaction import has_unredacted_sensitive_url_parts
from weather.market.market_config import ensure_date
from weather.market.market_making_run_constants import (
    MAX_OPERATOR_PILOT_BUDGET_USDC,
    PLATFORM_VERIFICATION_SCHEMA_VERSION,
    SCHEMA_VERSION,
)
from weather.market.mm_official_adapter import (
    CONDITION_ID_RE,
    OFFICIAL_CLOB_DISTRIBUTION,
    OFFICIAL_CLOB_VERSION,
)
from weather.market.mm_policy import bool_value, maybe_float, parse_time, utc_now

CLOB_TOKEN_ARTIFACT_KEYS = ("clob_tokens", "clob_tokens_raw")
CLOB_RAW_BOOK_ARTIFACT_KEYS = (
    "order_books_summary",
    "order_books_raw",
    # Gzip-tiered canonical tape. Same bytes, smaller; see data_layer_audit_collectors.
    "order_books_raw_gzip",
    "order_books_long",
    "order_books_long_gzip",
)
PLATFORM_BOOTSTRAP_SCHEMA_VERSION = "mm_platform_bootstrap_v0.6"
LIVE_LIFECYCLE_PROBE_SCHEMA_VERSION = "mm_live_lifecycle_probe_v0.3"
STAGE1_LIFECYCLE_BUNDLE_SCHEMA_VERSION = "mm_stage1_lifecycle_bundle_v0.3"
POST_CANCEL_QUIESCENCE_SECONDS = 2.0


def _has_any_artifact(row, keys):
    presence = row.get("artifact_presence") or {}
    return any(bool(presence.get(key)) for key in keys)


def load_data_layer_live_gate(path, target_date, mode):
    required = mode == "live-pilot"
    if not required:
        return {"required": False, "ok": True, "reason": "not required outside live-pilot"}
    path = Path(path) if path else None
    if path is None:
        return {"required": True, "ok": False, "path": None, "reason": "no data-layer audit path provided"}
    if not path.exists():
        return {"required": True, "ok": False, "path": str(path), "reason": "data-layer audit artifact missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return {"required": True, "ok": False, "path": str(path), "reason": f"invalid data-layer audit JSON: {exc}"}
    snapshots = payload.get("snapshots") or {}
    clob = snapshots.get("clob_features") or {}
    target_text = ensure_date(target_date).isoformat()
    target_folders = [
        row for row in snapshots.get("folders") or []
        if row.get("target_date") == target_text
    ]
    target_token_days = sum(
        1 for row in target_folders
        if int(row.get("rows_with_market_token_ids") or 0) > 0
    )
    target_clob_feature_days = sum(
        1 for row in target_folders
        if ((row.get("artifact_presence") or {}).get("clob_features"))
    )
    target_clob_token_artifact_days = sum(
        1 for row in target_folders
        if _has_any_artifact(row, CLOB_TOKEN_ARTIFACT_KEYS)
    )
    target_raw_book_artifact_days = sum(
        1 for row in target_folders
        if _has_any_artifact(row, CLOB_RAW_BOOK_ARTIFACT_KEYS)
    )
    target_book_available_days = sum(
        1 for row in target_folders
        if int(((row.get("clob_features") or {}).get("book_available_rows")) or 0) > 0
    )
    checks = {
        "has_market_token_ids": bool(snapshots.get("has_market_token_ids")),
        "clob_feature_rows": int(clob.get("row_count") or 0) > 0,
        "clob_book_available_rows": int(clob.get("book_available_rows") or 0) > 0,
        "target_date_folder_present": bool(target_folders),
        "target_date_token_ids": target_token_days > 0,
        "target_date_clob_features": target_clob_feature_days > 0,
        "target_date_clob_token_artifact": target_clob_token_artifact_days > 0,
        "target_date_raw_book_artifact": target_raw_book_artifact_days > 0,
        "target_date_book_available": target_book_available_days > 0,
    }
    missing = [name for name, ok in checks.items() if not ok]
    return {
        "required": True,
        "ok": not missing,
        "path": str(path),
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "gate_summary_status": (payload.get("gate_summary") or {}).get("status"),
        "target_date": target_text,
        "checks": checks,
        "missing": missing,
        "reason": "ok" if not missing else "data-layer audit missing live CLOB proof: " + ", ".join(missing),
        "target_date_folder_count": len(target_folders),
        "target_date_token_days": target_token_days,
        "target_date_clob_feature_days": target_clob_feature_days,
        "target_date_clob_token_artifact_days": target_clob_token_artifact_days,
        "target_date_raw_book_artifact_days": target_raw_book_artifact_days,
        "target_date_book_available_days": target_book_available_days,
    }


SECRET_FIELD_NAMES = {
    "access_token",
    "api_key",
    "api_secret",
    "apikey",
    "auth_token",
    "client_secret",
    "mnemonic",
    "password",
    "private_key",
    "secret",
    "secret_key",
    "seed",
    "seed_phrase",
    "token",
}
SUPPORTED_PLATFORM_IDS = {"polymarket_global"}
SUPPORTED_SIGNATURE_TYPES = {"EOA", "POLY_PROXY", "POLY_GNOSIS_SAFE", "POLY_1271"}
SUPPORTED_SIGNATURE_TYPE_IDS = {0, 1, 2, 3}
SIGNATURE_TYPE_IDS = {
    "EOA": 0,
    "POLY_PROXY": 1,
    "POLY_GNOSIS_SAFE": 2,
    "POLY_1271": 3,
}
PILOT_WALLET_SIGNATURE_TYPES = {
    "gnosis_safe": ("POLY_GNOSIS_SAFE", 2),
    "deposit_wallet": ("POLY_1271", 3),
}
INTERNATIONAL_SETTLEMENT_UNIT = "pUSD"


def contains_secret_material(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in SECRET_FIELD_NAMES and child not in (None, "", False):
                return True
            if contains_secret_material(child):
                return True
    elif isinstance(value, list):
        return any(contains_secret_material(child) for child in value)
    elif isinstance(value, str):
        return has_unredacted_sensitive_url_parts(value)
    return False


def non_empty_text(value):
    return isinstance(value, str) and bool(value.strip())


def recent_utc_timestamp(value, now, max_age_hours):
    parsed = parse_time(value)
    if parsed is None:
        return False
    if parsed > now + timedelta(minutes=5):
        return False
    return (now - parsed) <= timedelta(hours=max_age_hours)


def supported_signature_type(payload):
    raw_type = payload.get("signature_type")
    if isinstance(raw_type, str) and raw_type.strip().upper() in SUPPORTED_SIGNATURE_TYPES:
        return True
    raw_id = payload.get("signature_type_id")
    try:
        return int(raw_id) in SUPPORTED_SIGNATURE_TYPE_IDS
    except (TypeError, ValueError):
        return False


def signature_type_consistent(payload):
    raw_type = payload.get("signature_type")
    raw_id = payload.get("signature_type_id")
    if not isinstance(raw_type, str):
        return False
    expected_id = SIGNATURE_TYPE_IDS.get(raw_type.strip().upper())
    try:
        return expected_id is not None and int(raw_id) == expected_id
    except (TypeError, ValueError):
        return False


def valid_evm_address(value):
    return isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{40}", value.strip()) is not None


def pilot_wallet_signature_topology(payload):
    wallet_type = str(payload.get("wallet_type") or "").strip().lower()
    expected = PILOT_WALLET_SIGNATURE_TYPES.get(wallet_type)
    if expected is None:
        return False
    expected_name, expected_id = expected
    return (
        str(payload.get("signature_type") or "").strip().upper() == expected_name
        and payload.get("signature_type_id") == expected_id
    )


def pilot_wallet_identity_topology_checks(payload, wallet_identity):
    """Prove the two supported International pilot wallet relationships."""

    wallet_identity = dict(wallet_identity or {})
    private_key_signer = str(
        wallet_identity.get("private_key_signer_address") or ""
    ).strip().lower()
    order_signer = str(
        wallet_identity.get("order_signer_address") or ""
    ).strip().lower()
    api_key_owner = str(
        wallet_identity.get("api_key_owner_address") or ""
    ).strip().lower()
    funder_address = str(payload.get("funder_address") or "").strip().lower()
    signature_type_id = payload.get("signature_type_id")
    expected_order_signer = (
        funder_address if signature_type_id == 3 else private_key_signer
    )
    return {
        "pilot_wallet_signature_topology": pilot_wallet_signature_topology(payload),
        "private_key_signer_matches_api_key_owner": (
            valid_evm_address(private_key_signer)
            and private_key_signer == api_key_owner
        ),
        "order_signer_matches_wallet_topology": (
            valid_evm_address(order_signer)
            and order_signer == expected_order_signer
        ),
        "signer_funder_relation_matches_wallet_topology": (
            valid_evm_address(private_key_signer)
            and valid_evm_address(funder_address)
            and private_key_signer != funder_address
        ),
    }


def valid_clob_token_id(value):
    text = str(value or "").strip()
    return text.isdigit() and int(text) > 0


def platform_account_snapshot_sha256(account_snapshot):
    """Hash the full account snapshot while excluding only its self-hash."""

    payload = {
        key: value
        for key, value in dict(account_snapshot or {}).items()
        if key != "snapshot_sha256"
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stage1_lifecycle_bundle_sha256(bundle):
    """Hash a Stage 1 bundle while excluding only its own content hash."""

    payload = {
        key: value
        for key, value in dict(bundle or {}).items()
        if key != "bundle_sha256"
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_sha256(value):
    return re.fullmatch(r"[0-9a-f]{64}", str(value or "")) is not None


def _stage1_probe_hardening_checks(
    probe,
    lifecycle_journal,
    user_stream_journal,
    *,
    lifecycle_budget,
    wallet_cap,
):
    """Validate the v0.3 proofs that an upstream PASS boolean cannot replace."""

    candidate_fee_rate = maybe_float(probe.get("candidate_fee_rate"))
    current_fee_rate_bps = maybe_float(probe.get("current_fee_rate_bps"))
    collateral_balance = maybe_float(probe.get("submit_collateral_balance_usdc"))
    collateral_allowance = maybe_float(probe.get("submit_collateral_allowance_usdc"))
    quiescence_seconds = maybe_float(probe.get("post_cancel_quiescence_seconds"))
    lifecycle_row_count = lifecycle_journal.get("row_count")
    stream_row_count = user_stream_journal.get("row_count")
    scoped_stream_count = user_stream_journal.get("scoped_order_event_count")
    reported_stream_row_count = probe.get("user_stream_journal_row_count")
    reported_scoped_stream_count = probe.get(
        "user_stream_scoped_order_event_count"
    )

    return {
        "action_time_market_rules_verified": all((
            probe.get("submit_boundary_heartbeat_acknowledged") is True,
            probe.get("submit_boundary_market_rules_verified") is True,
            probe.get(
                "submit_boundary_geography_before_heartbeat_verified"
            )
            is True,
            probe.get("post_sign_order_placement_boundary_verified") is True,
            candidate_fee_rate is not None and candidate_fee_rate >= 0,
            current_fee_rate_bps is not None and current_fee_rate_bps >= 0,
            (
                candidate_fee_rate is not None
                and current_fee_rate_bps is not None
                and candidate_fee_rate == current_fee_rate_bps / 10_000
            ),
            type(probe.get("candidate_neg_risk")) is bool,
            probe.get("candidate_neg_risk") is probe.get("current_neg_risk"),
        )),
        "action_time_collateral_verified": all((
            lifecycle_budget is not None and lifecycle_budget > 0,
            (
                collateral_balance is not None
                and lifecycle_budget is not None
                and collateral_balance >= lifecycle_budget
            ),
            (
                collateral_balance is not None
                and wallet_cap is not None
                and collateral_balance <= wallet_cap
            ),
            (
                collateral_allowance is not None
                and lifecycle_budget is not None
                and collateral_allowance >= lifecycle_budget
            ),
            probe.get("collateral_no_fill_reconciliation_verified") is True,
            _is_sha256(probe.get("submit_collateral_snapshot_sha256")),
            probe.get("submit_collateral_snapshot_sha256")
            == probe.get("post_cancel_collateral_snapshot_sha256"),
        )),
        "terminal_rest_and_account_trades_verified": all((
            probe.get("terminal_rest_order_verified") is True,
            probe.get("terminal_rest_zero_matched_verified") is True,
            _is_sha256(probe.get("terminal_rest_order_sha256")),
            probe.get("account_trades_rest_verified") is True,
            type(probe.get("scoped_account_trade_count")) is int,
            probe.get("scoped_account_trade_count") == 0,
        )),
        "post_cancel_quiescence_verified": (
            quiescence_seconds == POST_CANCEL_QUIESCENCE_SECONDS
        ),
        "lifecycle_journal_bound": all((
            non_empty_text(probe.get("journal_path")),
            lifecycle_journal.get("path") == probe.get("journal_path"),
            _is_sha256(probe.get("journal_sha256")),
            lifecycle_journal.get("sha256") == probe.get("journal_sha256"),
            type(lifecycle_row_count) is int and lifecycle_row_count > 0,
        )),
        "final_user_stream_journal_bound": all((
            non_empty_text(probe.get("user_stream_journal_path")),
            user_stream_journal.get("path")
            == probe.get("user_stream_journal_path"),
            _is_sha256(probe.get("user_stream_journal_sha256")),
            user_stream_journal.get("sha256")
            == probe.get("user_stream_journal_sha256"),
            _is_sha256(
                probe.get("cleanup_final_user_stream_journal_sha256")
            ),
            probe.get("cleanup_final_user_stream_journal_sha256")
            == probe.get("user_stream_journal_sha256"),
            user_stream_journal.get("terminal_stream_stopped_verified") is True,
            type(stream_row_count) is int and stream_row_count > 0,
            type(reported_stream_row_count) is int,
            reported_stream_row_count == stream_row_count,
            type(scoped_stream_count) is int and scoped_stream_count >= 0,
            type(reported_scoped_stream_count) is int,
            reported_scoped_stream_count == scoped_stream_count,
        )),
    }


def dict_value(payload, key):
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def maker_only_order_field_supported(payload):
    expected = {
        "polymarket_us": "participateDontInitiate",
        "polymarket_global": "postOnly",
    }.get(payload.get("platform"))
    if expected is None:
        return False
    return str(payload.get("maker_only_order_field") or "").strip() == expected


def load_platform_verification_gate(path, target_date, mode, now=None, requested_budget_usdc=None):
    required = mode == "live-pilot"
    if not required:
        return {"required": False, "ok": True, "reason": "not required outside live-pilot"}
    path = Path(path) if path else None
    if path is None:
        return {"required": True, "ok": False, "path": None, "reason": "no platform-verification path provided"}
    if not path.exists():
        return {"required": True, "ok": False, "path": str(path), "reason": "platform-verification artifact missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return {"required": True, "ok": False, "path": str(path), "reason": f"invalid platform-verification JSON: {exc}"}

    now = utc_now(now)
    target_text = ensure_date(target_date).isoformat()
    evidence_target = payload.get("verified_for_target_date") or payload.get("target_date")
    max_age_hours = maybe_float(payload.get("max_age_hours"))
    if max_age_hours is None or max_age_hours <= 0:
        max_age_hours = 24.0
    fee_model = payload.get("fee_model") or payload.get("weather_fee_model") or {}
    source_urls = payload.get("source_urls") or []
    if isinstance(source_urls, str):
        source_urls = [source_urls]
    pilot_wallet_cap = maybe_float(payload.get("pilot_wallet_max_funding_usdc"))
    requested_budget = maybe_float(requested_budget_usdc)
    collateral_balance = maybe_float(payload.get("collateral_balance_usdc"))
    collateral_allowance = maybe_float(payload.get("collateral_allowance_usdc"))
    open_order_count = maybe_float(payload.get("open_order_count"))
    account_snapshot = dict_value(payload, "account_snapshot")
    fee_rate = maybe_float(
        fee_model.get("taker_fee_rate")
        or fee_model.get("theta")
        or payload.get("weather_taker_fee_rate")
    )
    maker_rebate_rate = maybe_float(
        fee_model.get("maker_rebate_rate")
        or payload.get("maker_rebate_rate")
    )
    private_stream = dict_value(payload, "private_user_stream")
    cancel_all = dict_value(payload, "cancel_all")
    latency_stopgap = dict_value(payload, "latency_stopgap")
    secret_redaction = dict_value(payload, "secret_redaction")
    wallet_identity = dict_value(payload, "wallet_identity")
    sdk = dict_value(payload, "sdk_contract")
    heartbeat = dict_value(payload, "dead_man_heartbeat")
    lifecycle_bundle = dict_value(payload, "stage1_lifecycle_bundle")
    wallet_topology_checks = pilot_wallet_identity_topology_checks(
        payload,
        wallet_identity,
    )
    lifecycle_results = dict_value(lifecycle_bundle, "lifecycle_results")
    cancel_probe = dict_value(lifecycle_results, "cancel_all")
    dead_man_probe = dict_value(lifecycle_results, "dead_man")
    lifecycle_derived = dict_value(lifecycle_bundle, "derived_platform_evidence")
    lifecycle_journals = dict_value(lifecycle_bundle, "journal_evidence")
    user_stream_journals = dict_value(
        lifecycle_bundle,
        "user_stream_journal_evidence",
    )
    lifecycle_bundle_hash = str(lifecycle_bundle.get("bundle_sha256") or "")
    lifecycle_bundle_budget = maybe_float(lifecycle_bundle.get("requested_budget_usdc"))
    cancel_probe_notional = maybe_float(cancel_probe.get("order_notional_usdc"))
    dead_man_probe_notional = maybe_float(dead_man_probe.get("order_notional_usdc"))
    dead_man_elapsed = maybe_float(dead_man_probe.get("cancellation_elapsed_seconds"))
    is_us_platform = payload.get("platform") == "polymarket_us"
    heartbeat_cadence = maybe_float(heartbeat.get("cadence_seconds"))
    checks = {
        "schema_version_supported": payload.get("schema_version") == PLATFORM_VERIFICATION_SCHEMA_VERSION,
        "status_pass": payload.get("status") == "PASS",
        "target_date_matches": evidence_target == target_text,
        "verified_at_recent": recent_utc_timestamp(payload.get("verified_at_utc"), now, max_age_hours),
        "docs_checked_recent": recent_utc_timestamp(payload.get("docs_checked_at_utc"), now, max_age_hours),
        "platform_supported": payload.get("platform") in SUPPORTED_PLATFORM_IDS,
        "api_base_url_is_international": str(payload.get("api_base_url") or "").rstrip("/").lower()
        == "https://polymarket.com",
        "clob_host_is_international": str(payload.get("clob_host") or "").rstrip("/").lower()
        == "https://clob.polymarket.com",
        "settlement_unit_is_native_pusd": payload.get("settlement_unit")
        == INTERNATIONAL_SETTLEMENT_UNIT,
        "wallet_type_recorded": non_empty_text(payload.get("wallet_type")),
        "signature_type_supported": supported_signature_type(payload),
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
        **wallet_topology_checks,
        "sdk_distribution_exact": sdk.get("distribution") == OFFICIAL_CLOB_DISTRIBUTION,
        "sdk_version_exact": sdk.get("version") == OFFICIAL_CLOB_VERSION,
        "sdk_exact_version_verified": bool_value(sdk.get("exact_version_verified"), False),
        "sdk_wallet_model_probe_verified": bool_value(
            sdk.get("wallet_model_probe_verified"),
            False,
        ),
        "allowances_verified": bool_value(payload.get("allowances_verified"), False),
        "balance_verified": bool_value(payload.get("balance_verified"), False),
        "collateral_balance_backs_budget": (
            collateral_balance is not None
            and collateral_balance > 0
            and (requested_budget is None or collateral_balance >= requested_budget)
        ),
        "collateral_balance_within_wallet_cap": (
            collateral_balance is not None
            and pilot_wallet_cap is not None
            and collateral_balance <= pilot_wallet_cap
        ),
        "collateral_allowance_backs_budget": (
            collateral_allowance is not None
            and collateral_allowance > 0
            and (requested_budget is None or collateral_allowance >= requested_budget)
        ),
        "account_snapshot_hash_recorded": len(
            str(payload.get("account_snapshot_sha256") or "")
        ) == 64,
        "account_snapshot_hash_matches_content": (
            bool(account_snapshot)
            and str(account_snapshot.get("snapshot_sha256") or "")
            == str(payload.get("account_snapshot_sha256") or "")
            == platform_account_snapshot_sha256(account_snapshot)
        ),
        "account_snapshot_fields_match": all((
            maybe_float(account_snapshot.get("collateral_balance_usdc"))
            == collateral_balance,
            maybe_float(account_snapshot.get("collateral_allowance_usdc"))
            == collateral_allowance,
            maybe_float(account_snapshot.get("open_order_count"))
            == open_order_count,
        )),
        "stage1_lifecycle_bundle_schema_supported": (
            lifecycle_bundle.get("schema_version")
            == STAGE1_LIFECYCLE_BUNDLE_SCHEMA_VERSION
        ),
        "stage1_lifecycle_bundle_status_pass": lifecycle_bundle.get("status") == "PASS",
        "stage1_lifecycle_bundle_created_recent": recent_utc_timestamp(
            lifecycle_bundle.get("created_at_utc"),
            now,
            max_age_hours,
        ),
        "stage1_lifecycle_bundle_platform_matches": (
            lifecycle_bundle.get("platform") == payload.get("platform") == "polymarket_global"
        ),
        "stage1_lifecycle_bundle_settlement_unit_matches": (
            lifecycle_bundle.get("settlement_unit")
            == payload.get("settlement_unit")
            == INTERNATIONAL_SETTLEMENT_UNIT
            and cancel_probe.get("settlement_unit") == INTERNATIONAL_SETTLEMENT_UNIT
            and dead_man_probe.get("settlement_unit") == INTERNATIONAL_SETTLEMENT_UNIT
        ),
        "stage1_lifecycle_bundle_hash_matches_content": all((
            len(lifecycle_bundle_hash) == 64,
            lifecycle_bundle_hash == str(payload.get("stage1_lifecycle_bundle_sha256") or ""),
            lifecycle_bundle_hash == stage1_lifecycle_bundle_sha256(lifecycle_bundle),
        )),
        "stage1_lifecycle_bundle_identity_matches": all((
            str(lifecycle_bundle.get("funder_address") or "").lower()
            == str(payload.get("funder_address") or "").lower(),
            bool(str(lifecycle_bundle.get("condition_id") or "")),
            CONDITION_ID_RE.fullmatch(
                str(lifecycle_bundle.get("condition_id") or "").lower()
            ) is not None,
            valid_clob_token_id(lifecycle_bundle.get("token_id")),
            len(str(lifecycle_bundle.get("bootstrap_sha256") or "")) == 64,
        )),
        "stage1_lifecycle_bundle_budget_matches": (
            lifecycle_bundle_budget is not None
            and lifecycle_bundle_budget > 0
            and lifecycle_bundle_budget <= MAX_OPERATOR_PILOT_BUDGET_USDC
            and (requested_budget is None or requested_budget <= lifecycle_bundle_budget)
            and (pilot_wallet_cap is None or lifecycle_bundle_budget <= pilot_wallet_cap)
        ),
        "stage1_cancel_all_probe_verified": all((
            cancel_probe.get("schema_version") == LIVE_LIFECYCLE_PROBE_SCHEMA_VERSION,
            cancel_probe.get("status") == "PASS",
            recent_utc_timestamp(cancel_probe.get("completed_at_utc"), now, max_age_hours),
            cancel_probe.get("platform") == "polymarket_global",
            cancel_probe.get("cancellation_mode") == "cancel_all",
            cancel_probe.get("bootstrap_sha256") == lifecycle_bundle.get("bootstrap_sha256"),
            cancel_probe.get("placement_status") == "live",
            bool(str(cancel_probe.get("order_id") or "")),
            cancel_probe.get("heartbeat_acknowledged") is True,
            cancel_probe.get("starting_zero_open_orders_verified") is True,
            cancel_probe.get("starting_zero_positions_verified") is True,
            cancel_probe.get("open_order_observed") is True,
            cancel_probe.get("authoritative_user_event_observed") is True,
            cancel_probe.get("cancellation_observed") is True,
            cancel_probe.get("terminal_user_event_observed") is True,
            cancel_probe.get("no_trade_lifecycle_event_observed") is True,
            cancel_probe.get("cancel_response_present") is True,
            cancel_probe.get("zero_open_orders_verified") is True,
            cancel_probe.get("zero_positions_verified") is True,
            len(str(cancel_probe.get("journal_sha256") or "")) == 64,
        )),
        "stage1_dead_man_probe_verified": all((
            dead_man_probe.get("schema_version") == LIVE_LIFECYCLE_PROBE_SCHEMA_VERSION,
            dead_man_probe.get("status") == "PASS",
            recent_utc_timestamp(dead_man_probe.get("completed_at_utc"), now, max_age_hours),
            dead_man_probe.get("platform") == "polymarket_global",
            dead_man_probe.get("cancellation_mode") == "dead_man",
            dead_man_probe.get("bootstrap_sha256") == lifecycle_bundle.get("bootstrap_sha256"),
            dead_man_probe.get("placement_status") == "live",
            bool(str(dead_man_probe.get("order_id") or "")),
            dead_man_probe.get("heartbeat_acknowledged") is True,
            dead_man_probe.get("starting_zero_open_orders_verified") is True,
            dead_man_probe.get("starting_zero_positions_verified") is True,
            dead_man_probe.get("open_order_observed") is True,
            dead_man_probe.get("authoritative_user_event_observed") is True,
            dead_man_probe.get("cancellation_observed") is True,
            dead_man_probe.get("terminal_user_event_observed") is True,
            dead_man_probe.get("no_trade_lifecycle_event_observed") is True,
            dead_man_probe.get("cancel_response_present") is False,
            dead_man_probe.get("zero_open_orders_verified") is True,
            dead_man_probe.get("zero_positions_verified") is True,
            dead_man_elapsed is not None and 10 <= dead_man_elapsed <= 15,
            len(str(dead_man_probe.get("journal_sha256") or "")) == 64,
        )),
        "stage1_probe_orders_are_distinct": (
            bool(str(cancel_probe.get("order_id") or ""))
            and bool(str(dead_man_probe.get("order_id") or ""))
            and str(cancel_probe.get("order_id")) != str(dead_man_probe.get("order_id"))
        ),
        "stage1_probe_identity_and_budget_match": all((
            lifecycle_bundle.get("bootstrap_schema_version")
            == PLATFORM_BOOTSTRAP_SCHEMA_VERSION,
            cancel_probe.get("bootstrap_schema_version")
            == lifecycle_bundle.get("bootstrap_schema_version"),
            dead_man_probe.get("bootstrap_schema_version")
            == lifecycle_bundle.get("bootstrap_schema_version"),
            str(cancel_probe.get("condition_id") or "").lower()
            == str(dead_man_probe.get("condition_id") or "").lower()
            == str(lifecycle_bundle.get("condition_id") or "").lower(),
            str(cancel_probe.get("token_id") or "")
            == str(dead_man_probe.get("token_id") or "")
            == str(lifecycle_bundle.get("token_id") or ""),
            cancel_probe_notional is not None
            and lifecycle_bundle_budget is not None
            and 0 < cancel_probe_notional <= lifecycle_bundle_budget,
            dead_man_probe_notional is not None
            and lifecycle_bundle_budget is not None
            and 0 < dead_man_probe_notional <= lifecycle_bundle_budget,
            cancel_probe.get("secret_values_redacted") is True,
            dead_man_probe.get("secret_values_redacted") is True,
            lifecycle_bundle.get("secret_values_redacted") is True,
            str(cancel_probe.get("journal_sha256") or "")
            != str(dead_man_probe.get("journal_sha256") or ""),
        )),
        "stage1_derived_evidence_matches_platform_fields": all((
            lifecycle_derived.get("starting_open_orders_rest_verified") is True
            and private_stream.get("starting_open_orders_rest_verified") is True,
            lifecycle_derived.get("order_update_verified") is True
            and private_stream.get("order_update_verified") is True,
            lifecycle_derived.get("fill_event_verified") is False
            and private_stream.get("fill_event_verified") is False,
            lifecycle_derived.get("no_fill_lifecycle_verified") is True
            and private_stream.get("no_fill_lifecycle_verified") is True,
            lifecycle_derived.get("final_state_reconciliation_verified") is True
            and private_stream.get("final_state_reconciliation_verified") is True,
            lifecycle_derived.get("terminal_order_rest_verified") is True
            and private_stream.get("terminal_order_rest_verified") is True,
            lifecycle_derived.get("account_trades_rest_verified") is True
            and private_stream.get("account_trades_rest_verified") is True,
            lifecycle_derived.get("final_user_stream_journals_verified") is True
            and private_stream.get("final_user_stream_journals_verified") is True,
            lifecycle_derived.get("action_time_collateral_verified") is True
            and private_stream.get("action_time_collateral_verified") is True,
            lifecycle_derived.get("no_fill_collateral_reconciliation_verified")
            is True
            and private_stream.get("no_fill_collateral_reconciliation_verified")
            is True,
            lifecycle_derived.get("cancel_all_request_verified") is True
            and cancel_all.get("request_verified") is True,
            lifecycle_derived.get("cancel_all_zero_open_orders_verified") is True
            and cancel_all.get("zero_open_orders_verified") is True,
            lifecycle_derived.get("dead_man_automatic_cancel_verified") is True
            and heartbeat.get("automatic_cancel_verified") is True,
            lifecycle_derived.get("heartbeat_acknowledgment_verified") is True
            and heartbeat.get("acknowledgment_verified") is True,
        )),
        "open_order_count_zero": open_order_count == 0.0,
        "fees_verified": bool_value(payload.get("fees_verified"), False),
        "fee_parameters_recorded": fee_rate is not None and maker_rebate_rate is not None,
        "reward_rules_verified": bool_value(payload.get("reward_rules_verified"), False),
        "rebate_rules_verified": bool_value(payload.get("rebate_rules_verified"), False),
        "order_semantics_verified": bool_value(payload.get("order_semantics_verified"), False),
        "maker_only_order_field_supported": maker_only_order_field_supported(payload),
        "maker_only_order_field_verified": bool_value(payload.get("maker_only_order_field_verified"), False),
        "limit_order_semantics_verified": bool_value(payload.get("limit_order_semantics_verified"), False),
        "market_order_semantics_verified": bool_value(payload.get("market_order_semantics_verified"), False),
        "cancel_semantics_verified": bool_value(payload.get("cancel_semantics_verified"), False),
        "tick_size_verified": bool_value(payload.get("tick_size_verified"), False),
        "min_order_size_verified": bool_value(payload.get("min_order_size_verified"), False),
        "user_websocket_verified": bool_value(payload.get("user_websocket_verified"), False),
        "private_user_stream_connection_verified": bool_value(private_stream.get("connection_verified"), False),
        "private_user_stream_starting_state_verified": bool_value(
            private_stream.get("starting_open_orders_rest_verified"),
            False,
        ),
        "private_user_stream_order_update_verified": bool_value(private_stream.get("order_update_verified"), False),
        "private_user_stream_fill_or_no_fill_lifecycle_verified": (
            bool_value(private_stream.get("fill_event_verified"), False)
            or bool_value(private_stream.get("no_fill_lifecycle_verified"), False)
        ),
        "private_user_stream_final_state_reconciliation_verified": bool_value(
            private_stream.get("final_state_reconciliation_verified"),
            False,
        ),
        "private_user_stream_terminal_order_rest_verified": bool_value(
            private_stream.get("terminal_order_rest_verified"),
            False,
        ),
        "private_user_stream_account_trades_rest_verified": bool_value(
            private_stream.get("account_trades_rest_verified"),
            False,
        ),
        "private_user_stream_final_journals_verified": bool_value(
            private_stream.get("final_user_stream_journals_verified"),
            False,
        ),
        "private_user_stream_action_time_collateral_verified": bool_value(
            private_stream.get("action_time_collateral_verified"),
            False,
        ),
        "private_user_stream_no_fill_collateral_reconciliation_verified": bool_value(
            private_stream.get("no_fill_collateral_reconciliation_verified"),
            False,
        ),
        "cancel_all_verified": bool_value(payload.get("cancel_all_verified"), False),
        "cancel_all_request_verified": bool_value(cancel_all.get("request_verified"), False),
        "cancel_all_zero_open_orders_verified": bool_value(cancel_all.get("zero_open_orders_verified"), False),
        "dead_man_heartbeat_endpoint_verified": (
            str(heartbeat.get("endpoint") or "").strip() == "/heartbeats"
            and bool_value(heartbeat.get("endpoint_verified"), False)
        ),
        "dead_man_heartbeat_request_body_absent_verified": bool_value(
            heartbeat.get("request_body_absent_verified"),
            False,
        ),
        "dead_man_heartbeat_two_acknowledgments_verified": (
            bool_value(heartbeat.get("two_acknowledgments_verified"), False)
            and heartbeat.get("acknowledgment_count") == 2
        ),
        "dead_man_heartbeat_acknowledgment_verified": bool_value(
            heartbeat.get("acknowledgment_verified"),
            False,
        ),
        "dead_man_heartbeat_cadence_verified": (
            heartbeat_cadence is not None and 0 < heartbeat_cadence <= 5
        ),
        "dead_man_heartbeat_stale_placement_disarm_verified": bool_value(
            heartbeat.get("stale_placement_disarm_verified"),
            False,
        ),
        "dead_man_heartbeat_automatic_cancel_verified": bool_value(
            heartbeat.get("automatic_cancel_verified"),
            False,
        ),
        "latency_stopgap_order_reject_handling_verified": (
            not is_us_platform or bool_value(latency_stopgap.get("order_reject_handling_verified"), False)
        ),
        "latency_stopgap_book_refresh_before_retry_verified": (
            not is_us_platform or bool_value(latency_stopgap.get("book_refresh_before_retry_verified"), False)
        ),
        "latency_stopgap_cancel_exemption_verified": (
            not is_us_platform or bool_value(latency_stopgap.get("cancel_exemption_verified"), False)
        ),
        "isolated_pilot_wallet": bool_value(payload.get("isolated_pilot_wallet"), False),
        "pilot_wallet_cap_recorded": pilot_wallet_cap is not None and pilot_wallet_cap > 0,
        "pilot_wallet_cap_within_operator_limit": (
            pilot_wallet_cap is not None
            and 0 < pilot_wallet_cap <= MAX_OPERATOR_PILOT_BUDGET_USDC
        ),
        "requested_budget_within_pilot_wallet_cap": (
            requested_budget is None
            or (
                pilot_wallet_cap is not None
                and 0 < requested_budget <= pilot_wallet_cap
            )
        ),
        "backend_only_signing": bool_value(payload.get("backend_only_signing"), False),
        "private_key_storage_recorded": non_empty_text(payload.get("private_key_storage")),
        "secrets_not_committed": bool_value(payload.get("secrets_not_committed"), False),
        "secret_redaction_status_output_verified": bool_value(
            secret_redaction.get("status_output_verified"),
            False,
        ),
        "secret_redaction_source_doc_scan_verified": bool_value(
            secret_redaction.get("source_doc_scan_verified"),
            False,
        ),
        "secret_redaction_generated_artifact_scan_verified": bool_value(
            secret_redaction.get("generated_artifact_scan_verified"),
            False,
        ),
        "secret_redaction_no_unredacted_findings": bool_value(
            secret_redaction.get("no_unredacted_secret_findings"),
            False,
        ),
        "secret_redaction_scan_scope_recorded": bool(secret_redaction.get("scan_scope")),
        "no_secret_material": not contains_secret_material(payload),
        "source_urls_recorded": any(non_empty_text(url) for url in source_urls),
        "native_pusd_source_recorded": (
            "https://docs.polymarket.com/concepts/pusd"
            in {str(url).rstrip("/") for url in source_urls}
        ),
    }
    cancel_hardening = _stage1_probe_hardening_checks(
        cancel_probe,
        dict_value(lifecycle_journals, "cancel_all"),
        dict_value(user_stream_journals, "cancel_all"),
        lifecycle_budget=lifecycle_bundle_budget,
        wallet_cap=pilot_wallet_cap,
    )
    dead_man_hardening = _stage1_probe_hardening_checks(
        dead_man_probe,
        dict_value(lifecycle_journals, "dead_man"),
        dict_value(user_stream_journals, "dead_man"),
        lifecycle_budget=lifecycle_bundle_budget,
        wallet_cap=pilot_wallet_cap,
    )
    checks.update({
        f"stage1_cancel_all_{name}": passed
        for name, passed in cancel_hardening.items()
    })
    checks.update({
        f"stage1_dead_man_{name}": passed
        for name, passed in dead_man_hardening.items()
    })
    journal_paths = (
        cancel_probe.get("journal_path"),
        dead_man_probe.get("journal_path"),
        cancel_probe.get("user_stream_journal_path"),
        dead_man_probe.get("user_stream_journal_path"),
    )
    journal_hashes = (
        cancel_probe.get("journal_sha256"),
        dead_man_probe.get("journal_sha256"),
        cancel_probe.get("user_stream_journal_sha256"),
        dead_man_probe.get("user_stream_journal_sha256"),
    )
    checks["stage1_lifecycle_and_user_stream_journals_are_distinct"] = all((
        all(non_empty_text(value) for value in journal_paths),
        len(set(journal_paths)) == len(journal_paths),
        all(_is_sha256(value) for value in journal_hashes),
        len(set(journal_hashes)) == len(journal_hashes),
    ))
    missing = [name for name, ok in checks.items() if not ok]
    return {
        "required": True,
        "ok": not missing,
        "path": str(path),
        "schema_version": payload.get("schema_version"),
        "target_date": target_text,
        "verified_for_target_date": evidence_target,
        "verified_at_utc": payload.get("verified_at_utc"),
        "docs_checked_at_utc": payload.get("docs_checked_at_utc"),
        "max_age_hours": max_age_hours,
        "platform": payload.get("platform"),
        "wallet_type": payload.get("wallet_type"),
        "signature_type": payload.get("signature_type"),
        "signature_type_id": payload.get("signature_type_id"),
        "international_platform_confirmed": payload.get("international_platform_confirmed"),
        "api_base_url": payload.get("api_base_url"),
        "clob_host": payload.get("clob_host"),
        "settlement_unit": payload.get("settlement_unit"),
        "maker_only_order_field": payload.get("maker_only_order_field"),
        "pilot_wallet_max_funding_usdc": pilot_wallet_cap,
        "requested_budget_usdc": requested_budget,
        "collateral_balance_usdc": collateral_balance,
        "collateral_allowance_usdc": collateral_allowance,
        "account_snapshot_sha256": payload.get("account_snapshot_sha256"),
        "stage1_lifecycle_bundle_sha256": payload.get("stage1_lifecycle_bundle_sha256"),
        "open_order_count": open_order_count,
        "operator_pilot_budget_limit_usdc": MAX_OPERATOR_PILOT_BUDGET_USDC,
        "sdk_contract": {
            "distribution": sdk.get("distribution"),
            "version": sdk.get("version"),
            "exact_version_verified": sdk.get("exact_version_verified"),
            "wallet_model_probe_verified": sdk.get("wallet_model_probe_verified"),
        },
        "wallet_identity": {
            "private_key_signer_address": wallet_identity.get("private_key_signer_address"),
            "order_signer_address": wallet_identity.get("order_signer_address"),
            "api_key_owner_address": wallet_identity.get("api_key_owner_address"),
            "consistency_verified": wallet_identity.get("consistency_verified"),
        },
        "dead_man_heartbeat": {
            "endpoint": heartbeat.get("endpoint"),
            "endpoint_verified": heartbeat.get("endpoint_verified"),
            "request_body_absent_verified": heartbeat.get("request_body_absent_verified"),
            "two_acknowledgments_verified": heartbeat.get("two_acknowledgments_verified"),
            "acknowledgment_count": heartbeat.get("acknowledgment_count"),
            "acknowledgment_verified": heartbeat.get("acknowledgment_verified"),
            "cadence_seconds": heartbeat_cadence,
            "stale_placement_disarm_verified": heartbeat.get("stale_placement_disarm_verified"),
            "automatic_cancel_verified": heartbeat.get("automatic_cancel_verified"),
        },
        "secret_redaction": {
            "status_output_verified": secret_redaction.get("status_output_verified"),
            "source_doc_scan_verified": secret_redaction.get("source_doc_scan_verified"),
            "generated_artifact_scan_verified": secret_redaction.get("generated_artifact_scan_verified"),
            "no_unredacted_secret_findings": secret_redaction.get("no_unredacted_secret_findings"),
            "scan_scope": secret_redaction.get("scan_scope") or [],
        },
        "checks": checks,
        "missing": missing,
        "reason": "ok" if not missing else "platform verification missing live account proof: " + ", ".join(missing),
    }


REMEDIATION_RULES = {
    "active_event": {
        "root_cause": "missing_active_event",
        "owner": "market registry / Gamma event discovery",
        "suggested_command": "python -m weather.market.market_microstructure capture --market all --date <YYYY-MM-DD>",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "event_metadata_validation": {
        "root_cause": "event_metadata_validation_blocked",
        "owner": "weather.operations.event_metadata_validation",
        "suggested_command": "python -m weather.operations.event_metadata_validation --target-date <YYYY-MM-DD>",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "snapshot_model_rows": {
        "root_cause": "missing_snapshot_model_rows",
        "owner": "weather snapshot/model loop",
        "suggested_command": "python -m weather.collection.snapshot_tracker --force --market all --date <YYYY-MM-DD>",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "model_freshness": {
        "root_cause": "stale_model_row",
        "owner": "weather snapshot/model loop",
        "roadmap_owner_items": ["161", "157"],
        "suggested_command": "python -m weather.collection.snapshot_tracker --force --market all --date <YYYY-MM-DD>",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "source_status_rows": {
        "root_cause": "missing_source_status_row",
        "owner": "snapshot source-status writer",
        "suggested_command": "python -m weather.collection.snapshot_tracker --force --market all --date <YYYY-MM-DD>",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "source_status_fresh": {
        "root_cause": "stale_source_status_row",
        "owner": "snapshot source-status writer",
        "suggested_command": "python -m weather.collection.snapshot_tracker --force --market all --date <YYYY-MM-DD>",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "source_status_degradation": {
        "root_cause": "source_status_degradation_blocked",
        "owner": "snapshot source-status writer / optional provider source",
        "suggested_command": (
            "python -m weather.collection.snapshot_tracker "
            "--backfill-source-status --overwrite-source-status"
        ),
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "clob_tokens": {
        "root_cause": "missing_clob_tokens",
        "owner": "CLOB token discovery",
        "suggested_command": "python -m weather.market.market_microstructure capture --market all --date <YYYY-MM-DD>",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "clob_discovery": {
        "root_cause": "blank_or_inactive_clob_discovery",
        "owner": "CLOB token discovery / Gamma event discovery",
        "suggested_command": "python -m weather.market.market_microstructure capture --market all --date <YYYY-MM-DD>",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "clob_books": {
        "root_cause": "missing_clob_book_rows",
        "owner": "CLOB book loop",
        "suggested_command": "python -m weather.market.market_microstructure raw-refresh --market all --date <YYYY-MM-DD> --strict",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "clob_features": {
        "root_cause": "missing_clob_feature_rows",
        "owner": "CLOB feature builder",
        "suggested_command": "python -m weather.market.market_microstructure_features",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "clob_freshness": {
        "root_cause": "stale_clob_book_tape",
        "owner": "CLOB book supervisor",
        "roadmap_owner_items": ["161"],
        "suggested_command": "python -m weather.market.market_microstructure raw-refresh --market all --date <YYYY-MM-DD> --strict",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "observation_trigger": {
        "root_cause": "watcher_stale",
        "owner": "observation-trigger supervisor",
        "roadmap_owner_items": ["161"],
        "suggested_command": "python -m weather.operations.observation_trigger ensure",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "promotion_state": {
        "root_cause": "promotion_blocked_or_missing",
        "owner": "promotion refresh",
        "suggested_command": "python -m weather.reporting.promotion.promotion_refresh",
        "recoverable_same_day": False,
        "counts_after_failure": False,
    },
    "reward_metadata": {
        "root_cause": "missing_reward_metadata",
        "owner": "CLOB book/token metadata",
        "suggested_command": "python -m weather.market.market_microstructure capture --market all --date <YYYY-MM-DD>",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "live_account_gate": {
        "root_cause": "live_gate_blocked",
        "owner": "live account/platform readiness",
        "suggested_command": "review live-readiness JSON and run cancel-all probe",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "data_layer_live_gate": {
        "root_cause": "data_layer_live_gate_blocked",
        "owner": "data-layer audit / CLOB capture",
        "suggested_command": "python -m weather.reporting.data_quality.data_layer_audit --fleet --json",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "platform_verification_gate": {
        "root_cause": "platform_verification_gate_blocked",
        "owner": "live account/platform readiness",
        "suggested_command": "refresh platform-verification JSON from current platform docs and account probes",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "exchange_economics_gate": {
        "root_cause": "exchange_economics_gate_blocked",
        "owner": "exchange economics snapshot",
        "suggested_command": "refresh exchange_economics_snapshot.json from current platform docs and rerun paper scoring",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
}


def remediation_last_good_artifact(market_row, gate_name):
    folder = market_row.get("folder") or ""
    if gate_name.startswith("source_status"):
        return {
            "artifact": str(Path(folder) / "source_status_long.csv") if folder else "",
            "latest_snapshot_id": market_row.get("latest_snapshot_id"),
            "latest_capture_utc": market_row.get("latest_capture_utc"),
            "source_status_rows": market_row.get("source_status_rows"),
        }
    if gate_name.startswith("clob"):
        audit = market_row.get("book_audit") or {}
        filename = "clob_tokens.csv" if gate_name == "clob_tokens" else "order_books_summary.csv"
        if gate_name == "clob_features":
            filename = "clob_features_long.csv"
        return {
            "artifact": str(Path(folder) / filename) if folder else "",
            "last_capture_utc": audit.get("last_capture_utc"),
            "trailing_age_seconds": audit.get("trailing_age_seconds"),
            "gaps_over_threshold": audit.get("gaps_over_threshold"),
            "max_counted_gap_seconds": audit.get("max_counted_gap_seconds"),
        }
    return {
        "artifact": folder,
        "latest_snapshot_id": market_row.get("latest_snapshot_id"),
        "latest_capture_utc": market_row.get("latest_capture_utc"),
    }


def remediation_suggested_command(command, target_date):
    text = str(command or "inspect preflight.json")
    if "<YYYY-MM-DD>" in text and target_date:
        text = text.replace("<YYYY-MM-DD>", ensure_date(target_date).isoformat())
    return text


def _positive_number(value):
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def remediation_rule_for_gate(market_row, gate, base_rule):
    rule = dict(base_rule)
    if gate.get("name") == "clob_freshness":
        audit = market_row.get("book_audit") or {}
        if _positive_number(audit.get("gaps_over_threshold")):
            rule["root_cause"] = "clob_book_tape_gap_over_threshold"
            rule["suggested_command"] = (
                "python -m weather.market.market_microstructure audit --strict --date <YYYY-MM-DD>"
            )
            rule["recoverable_same_day"] = False
            rule["counts_after_failure"] = False
    return rule


def source_status_auth_prerequisite_fields(market_row, gate, suggested_command):
    if gate.get("name") != "source_status_degradation":
        return {}
    degradation = market_row.get("source_status_degradation") or {}
    settlement_auth_failures = maybe_float(
        degradation.get("settlement_auth_failure_source_count")
    )
    if settlement_auth_failures is None:
        detail = gate.get("detail") or ""
        if "settlement_auth_failures=" in detail:
            marker = detail.split("settlement_auth_failures=", 1)[1].split()[0]
            settlement_auth_failures = maybe_float(marker)
    if not _positive_number(settlement_auth_failures):
        return {}
    return {
        "optional_provider_auth_failure": True,
        "external_prerequisite": "verify free-source replacement coverage, then rebuild source status",
        "repair_sequence": [
            suggested_command,
            "rerun current-target paper-live-forward/readiness after source status is rebuilt",
        ],
    }


def build_preflight_remediation(preflight, now, previous=None):
    previous_by_key = {
        row.get("incident_key"): row
        for row in ((previous or {}).get("incidents") or [])
        if row.get("incident_key")
    }
    incidents = []
    owner_counts = Counter()
    root_counts = Counter()

    def append_incident(incident):
        incidents.append(incident)
        owner_counts[incident["owner"]] += 1
        root_counts[incident["root_cause"]] += 1

    for market in preflight.get("markets", []):
        for gate in market.get("gates") or []:
            if gate.get("ok"):
                continue
            base_rule = REMEDIATION_RULES.get(gate.get("name"), {
                "root_cause": gate.get("name") or "unknown_preflight_failure",
                "owner": "unknown",
                "suggested_command": "inspect preflight.json",
                "recoverable_same_day": False,
                "counts_after_failure": False,
            })
            rule = remediation_rule_for_gate(market, gate, base_rule)
            detail = gate.get("detail") or ""
            key = "|".join([
                str(market.get("market_id") or ""),
                str(gate.get("name") or ""),
                str(rule["root_cause"]),
                detail,
            ])
            prior = previous_by_key.get(key) or {}
            incident = {
                "incident_key": key,
                "run_id": preflight.get("run_id"),
                "generated_at_utc": now.isoformat(),
                "first_seen_utc": prior.get("first_seen_utc") or now.isoformat(),
                "last_seen_utc": now.isoformat(),
                "market_id": market.get("market_id"),
                "event_slug": market.get("event_slug"),
                "status": market.get("status"),
                "gate": gate.get("name"),
                "severity": gate.get("severity"),
                "root_cause": rule["root_cause"],
                "owner": rule["owner"],
                "roadmap_owner_items": list(rule.get("roadmap_owner_items") or []),
                "detail": detail,
                "suggested_command": remediation_suggested_command(
                    rule["suggested_command"],
                    preflight.get("target_date"),
                ),
                "recoverable_same_day": bool(rule["recoverable_same_day"]),
                "can_still_count_live_forward_day": bool(rule["counts_after_failure"]),
                "alert_within_seconds": 60,
                "last_good_artifact": remediation_last_good_artifact(market, gate.get("name") or ""),
            }
            incident.update(source_status_auth_prerequisite_fields(
                market,
                gate,
                incident["suggested_command"],
            ))
            append_incident(incident)
    useful_work = preflight.get("useful_work_liveness") or {}
    if useful_work.get("enforced"):
        for blocker in useful_work.get("blockers") or []:
            gate_name = blocker.get("gate") or "useful_work_liveness"
            root_cause = blocker.get("root_cause") or gate_name
            detail = blocker.get("detail") or ""
            key = "|".join([
                "run",
                str(blocker.get("market_id") or "*"),
                str(gate_name),
                str(root_cause),
                detail,
            ])
            prior = previous_by_key.get(key) or {}
            incident = {
                "incident_key": key,
                "run_id": preflight.get("run_id"),
                "generated_at_utc": now.isoformat(),
                "first_seen_utc": prior.get("first_seen_utc") or now.isoformat(),
                "last_seen_utc": now.isoformat(),
                "market_id": blocker.get("market_id") or "*",
                "event_slug": None,
                "status": useful_work.get("status"),
                "gate": gate_name,
                "severity": blocker.get("severity") or "block",
                "root_cause": root_cause,
                "owner": blocker.get("owner") or "unknown",
                "roadmap_owner_items": list(blocker.get("roadmap_owner_items") or []),
                "detail": detail,
                "suggested_command": remediation_suggested_command(
                    blocker.get("suggested_command") or "inspect preflight.json",
                    preflight.get("target_date"),
                ),
                "recoverable_same_day": bool(blocker.get("recoverable_same_day", True)),
                "can_still_count_live_forward_day": bool(blocker.get("can_still_count_live_forward_day", False)),
                "alert_within_seconds": 60,
                "last_good_artifact": {
                    "artifact": blocker.get("status_path") or blocker.get("last_good_artifact") or "",
                    "last_good_timestamp": blocker.get("last_good_timestamp"),
                    "age_seconds": blocker.get("age_seconds"),
                    "stale_threshold_seconds": blocker.get("stale_threshold_seconds"),
                    "markets": blocker.get("markets") or [],
                },
            }
            append_incident(incident)
    has_missing = any(row.get("severity") != "stale" for row in incidents)
    status = "PASS" if not incidents else ("BLOCK" if has_missing else "WARN")
    non_countable = [
        row["incident_key"]
        for row in incidents
        if not row.get("can_still_count_live_forward_day")
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": preflight.get("run_id"),
        "target_date": preflight.get("target_date"),
        "mode": preflight.get("mode"),
        "status": status,
        "incident_count": len(incidents),
        "alert_within_seconds": 60,
        "counts_toward_live_forward_gate": preflight.get("status") == "PASS" and not incidents,
        "non_countable_incidents": non_countable,
        "root_cause_counts": dict(sorted(root_counts.items())),
        "owner_counts": dict(sorted(owner_counts.items())),
        "incidents": incidents,
    }


def remediation_risk_events(remediation):
    rows = []
    for incident in remediation.get("incidents") or []:
        rows.append({
            "run_id": remediation.get("run_id"),
            "generated_at_utc": remediation.get("generated_at_utc"),
            "severity": "warning" if incident.get("severity") == "stale" else "critical",
            "category": "preflight_remediation",
            "market_id": incident.get("market_id"),
            "reason": incident.get("root_cause"),
            "detail": incident.get("detail"),
            "owner": incident.get("owner"),
            "suggested_command": incident.get("suggested_command"),
            "alert_within_seconds": incident.get("alert_within_seconds"),
        })
    return rows
