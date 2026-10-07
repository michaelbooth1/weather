"""Shared platform identity checks and remediation metadata; no execution calls."""
from __future__ import annotations
import re
from datetime import timedelta
from weather.collection.redaction import has_unredacted_sensitive_url_parts
from weather.market.value_helpers import parse_time

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


def dict_value(payload, key):
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


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
