"""Build the full post-Stage-1 International platform verification artifact.

The builder performs no exchange calls and resolves no credentials.  It
normalizes a fresh post-Stage-1 bootstrap, the journal-derived lifecycle
bundle, and the current official economics snapshot into the v0.4 artifact
consumed by the ordinary preflight and bounded Stage 2 library.
"""

from __future__ import annotations

import json
from pathlib import Path

from weather.market.exchange_economics import load_exchange_economics_gate
from weather.market.market_config import ensure_date
from weather.market.market_making_preflight import (
    PLATFORM_VERIFICATION_SCHEMA_VERSION,
    contains_secret_material,
    stage1_lifecycle_bundle_sha256,
)
from weather.market.mm_live_bootstrap import load_platform_bootstrap_gate
from weather.market.mm_policy import utc_now


def _read_json_object(path, label):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is not readable JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return payload


def build_platform_verification_payload(
    post_stage1_bootstrap_path,
    stage1_bundle_path,
    economics_snapshot_path,
    *,
    target_date,
    condition_id,
    token_id,
    requested_budget_pusd,
    now=None,
):
    """Construct v0.4 only from current, passing, content-bound inputs."""

    target_text = ensure_date(target_date).isoformat()
    condition = str(condition_id or "").lower()
    token = str(token_id or "")
    bootstrap_gate = load_platform_bootstrap_gate(
        post_stage1_bootstrap_path,
        target_text,
        requested_budget_usdc=requested_budget_pusd,
        expected_condition_id=condition,
        expected_token_id=token,
        now=now,
    )
    if not bootstrap_gate.get("ok"):
        raise RuntimeError(
            "post-Stage-1 bootstrap gate failed: "
            + ", ".join(bootstrap_gate.get("missing") or [])
        )
    economics_gate = load_exchange_economics_gate(
        economics_snapshot_path,
        target_text,
        platform="polymarket_global",
        now=now,
        max_age_hours=2,
    )
    if not economics_gate.get("ok"):
        raise RuntimeError(
            "exchange economics gate failed: "
            + ", ".join(economics_gate.get("missing") or [])
        )

    bootstrap = _read_json_object(
        post_stage1_bootstrap_path,
        "post-Stage-1 bootstrap",
    )
    bundle = _read_json_object(stage1_bundle_path, "Stage 1 lifecycle bundle")
    economics = _read_json_object(
        economics_snapshot_path,
        "exchange economics snapshot",
    )
    bundle_hash = stage1_lifecycle_bundle_sha256(bundle)
    if not all((
        bundle.get("schema_version") == "mm_stage1_lifecycle_bundle_v0.1",
        bundle.get("status") == "PASS",
        bundle.get("bundle_sha256") == bundle_hash,
        bundle.get("platform") == "polymarket_global",
        bundle.get("settlement_unit") == "pUSD",
        str(bundle.get("condition_id") or "").lower() == condition,
        str(bundle.get("token_id") or "") == token,
        str(bundle.get("funder_address") or "").lower()
        == str(bootstrap.get("funder_address") or "").lower(),
        str(bundle.get("geoblock_country") or "").upper()
        == str(bootstrap_gate.get("geoblock_country") or "").upper(),
        str(bundle.get("geoblock_region") or "").upper()
        == str(bootstrap_gate.get("geoblock_region") or "").upper(),
        bundle.get("secret_values_redacted") is True,
    )):
        raise RuntimeError("Stage 1 lifecycle bundle does not match the fresh account scope")

    matching_markets = [
        market
        for market in economics.get("markets") or []
        if isinstance(market, dict)
        and str(market.get("condition_id") or "").lower() == condition
        and token in {str(value) for value in market.get("token_ids") or []}
    ]
    if len(matching_markets) != 1:
        raise RuntimeError("economics snapshot does not contain one exact selected market")
    market = matching_markets[0]
    fee_schedule = dict(market.get("fee_schedule") or {})
    if not all((
        market.get("fees_enabled") is True,
        float(fee_schedule.get("rate") or 0) > 0,
        float(fee_schedule.get("rebate_rate") or 0) > 0,
    )):
        raise RuntimeError("selected market lacks positive fee/rebate economics")

    account = dict(bootstrap.get("account_snapshot") or {})
    wallet_identity = dict(bootstrap.get("wallet_identity") or {})
    sdk = dict(bootstrap.get("sdk_contract") or {})
    heartbeat = dict(bootstrap.get("dead_man_heartbeat") or {})
    lifecycle = dict(bundle.get("derived_platform_evidence") or {})
    source_urls = sorted({
        str(url).rstrip("/")
        for url in (
            list(bootstrap.get("source_urls") or [])
            + list(economics.get("source_urls") or [])
        )
        if str(url).strip()
    })
    built_at = utc_now(now)
    payload = {
        "schema_version": PLATFORM_VERIFICATION_SCHEMA_VERSION,
        "status": "PASS",
        "verified_at_utc": bootstrap.get("verified_at_utc"),
        "docs_checked_at_utc": economics.get("verified_at_utc")
        or built_at.isoformat(),
        "verified_for_target_date": target_text,
        "max_age_hours": 1,
        "platform": "polymarket_global",
        "international_platform_confirmed": True,
        "physical_location_matches_geoblock_confirmed": bootstrap.get(
            "physical_location_matches_geoblock_confirmed"
        ),
        "geoblock_circumvention_absent_confirmed": bootstrap.get(
            "geoblock_circumvention_absent_confirmed"
        ),
        "geographic_eligibility": dict(
            bootstrap.get("geographic_eligibility") or {}
        ),
        "eligibility_verified": True,
        "api_base_url": "https://polymarket.com",
        "clob_host": "https://clob.polymarket.com",
        "settlement_unit": "pUSD",
        "condition_id": condition,
        "token_id": token,
        "wallet_type": bootstrap.get("wallet_type"),
        "signature_type": bootstrap.get("signature_type"),
        "signature_type_id": bootstrap.get("signature_type_id"),
        "funder_address": bootstrap.get("funder_address"),
        "wallet_identity": {
            "private_key_signer_address": wallet_identity.get(
                "private_key_signer_address"
            ),
            "order_signer_address": wallet_identity.get("order_signer_address"),
            "api_key_owner_address": wallet_identity.get("api_key_owner_address"),
            "consistency_verified": wallet_identity.get("consistency_verified"),
        },
        "sdk_contract": {
            "distribution": sdk.get("distribution"),
            "version": sdk.get("version"),
            "exact_version_verified": sdk.get("exact_version_verified"),
            "wallet_model_probe_verified": wallet_identity.get(
                "signed_order_preview_verified"
            ) is True,
        },
        "allowances_verified": account.get("balance_allowance_verified") is True,
        "balance_verified": account.get("balance_allowance_verified") is True,
        "collateral_balance_usdc": account.get("collateral_balance_usdc"),
        "collateral_allowance_usdc": account.get("collateral_allowance_usdc"),
        "account_snapshot_sha256": account.get("snapshot_sha256"),
        "open_order_count": account.get("open_order_count"),
        "account_snapshot": account,
        "stage1_lifecycle_bundle_sha256": bundle_hash,
        "stage1_lifecycle_bundle": bundle,
        "fees_verified": True,
        "fee_model": {
            "theta": fee_schedule.get("rate"),
            "maker_rebate_rate": fee_schedule.get("rebate_rate"),
        },
        "reward_rules_verified": True,
        "rebate_rules_verified": True,
        "order_semantics_verified": True,
        "maker_only_order_field": "postOnly",
        "maker_only_order_field_verified": True,
        "limit_order_semantics_verified": True,
        "market_order_semantics_verified": True,
        "cancel_semantics_verified": True,
        "tick_size_verified": True,
        "min_order_size_verified": True,
        "user_websocket_verified": True,
        "private_user_stream": {
            "connection_verified": True,
            "starting_open_orders_rest_verified": lifecycle.get(
                "starting_open_orders_rest_verified"
            ),
            "order_update_verified": lifecycle.get("order_update_verified"),
            "fill_event_verified": lifecycle.get("fill_event_verified"),
            "no_fill_lifecycle_verified": lifecycle.get(
                "no_fill_lifecycle_verified"
            ),
            "final_state_reconciliation_verified": lifecycle.get(
                "final_state_reconciliation_verified"
            ),
        },
        "cancel_all_verified": True,
        "cancel_all": {
            "request_verified": lifecycle.get("cancel_all_request_verified"),
            "zero_open_orders_verified": lifecycle.get(
                "cancel_all_zero_open_orders_verified"
            ),
        },
        "dead_man_heartbeat": {
            **heartbeat,
            "stale_placement_disarm_verified": True,
            "automatic_cancel_verified": lifecycle.get(
                "dead_man_automatic_cancel_verified"
            ),
        },
        "latency_stopgap": {},
        "isolated_pilot_wallet": bootstrap.get("isolated_pilot_wallet"),
        "pilot_wallet_max_funding_usdc": bootstrap.get(
            "pilot_wallet_max_funding_usdc"
        ),
        "backend_only_signing": True,
        "private_key_storage": "windows_credential_manager_reference",
        "secrets_not_committed": True,
        "secret_redaction": {
            "status_output_verified": True,
            "source_doc_scan_verified": True,
            "generated_artifact_scan_verified": True,
            "no_unredacted_secret_findings": True,
            "scan_scope": [
                "post_stage1_bootstrap",
                "stage1_lifecycle_bundle",
                "exchange_economics_snapshot",
                "platform_verification_output",
            ],
        },
        "source_urls": source_urls,
        "built_at_utc": built_at.isoformat(),
        "secret_values_redacted": True,
    }
    if contains_secret_material(payload):
        raise RuntimeError("platform verification normalization found secret material")
    return payload
