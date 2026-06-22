"""Preflight gates and remediation helpers for market-making runs."""

from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta
from pathlib import Path

from weather.market.market_config import ensure_date
from weather.market.market_making_run_constants import (
    PLATFORM_VERIFICATION_SCHEMA_VERSION,
    SCHEMA_VERSION,
)
from weather.market.mm_policy import bool_value, maybe_float, parse_time, utc_now

CLOB_TOKEN_ARTIFACT_KEYS = ("clob_tokens", "clob_tokens_raw")
CLOB_RAW_BOOK_ARTIFACT_KEYS = (
    "order_books_summary",
    "order_books_raw",
    "order_books_long",
    "order_books_long_gzip",
)


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
    "api_secret",
    "mnemonic",
    "password",
    "private_key",
    "secret",
    "seed",
    "seed_phrase",
}
SUPPORTED_PLATFORM_IDS = {"polymarket_global", "polymarket_us"}
SUPPORTED_SIGNATURE_TYPES = {"EOA", "POLY_PROXY", "GNOSIS_SAFE", "POLY_1271"}
SUPPORTED_SIGNATURE_TYPE_IDS = {0, 1, 2, 3}


def contains_secret_material(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in SECRET_FIELD_NAMES and child not in (None, "", False):
                return True
            if contains_secret_material(child):
                return True
    elif isinstance(value, list):
        return any(contains_secret_material(child) for child in value)
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


def load_platform_verification_gate(path, target_date, mode, now=None):
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
    fee_rate = maybe_float(
        fee_model.get("taker_fee_rate")
        or fee_model.get("theta")
        or payload.get("weather_taker_fee_rate")
    )
    maker_rebate_rate = maybe_float(
        fee_model.get("maker_rebate_rate")
        or payload.get("maker_rebate_rate")
    )
    checks = {
        "schema_version_supported": payload.get("schema_version") == PLATFORM_VERIFICATION_SCHEMA_VERSION,
        "target_date_matches": evidence_target == target_text,
        "verified_at_recent": recent_utc_timestamp(payload.get("verified_at_utc"), now, max_age_hours),
        "docs_checked_recent": recent_utc_timestamp(payload.get("docs_checked_at_utc"), now, max_age_hours),
        "platform_supported": payload.get("platform") in SUPPORTED_PLATFORM_IDS,
        "account_jurisdiction_recorded": non_empty_text(payload.get("account_jurisdiction")),
        "eligibility_verified": bool_value(payload.get("eligibility_verified"), False),
        "api_base_url_recorded": non_empty_text(payload.get("api_base_url")),
        "clob_host_recorded": non_empty_text(payload.get("clob_host")),
        "wallet_type_recorded": non_empty_text(payload.get("wallet_type")),
        "signature_type_supported": supported_signature_type(payload),
        "funder_address_recorded": non_empty_text(payload.get("funder_address")),
        "allowances_verified": bool_value(payload.get("allowances_verified"), False),
        "balance_verified": bool_value(payload.get("balance_verified"), False),
        "fees_verified": bool_value(payload.get("fees_verified"), False),
        "fee_parameters_recorded": fee_rate is not None and maker_rebate_rate is not None,
        "reward_rules_verified": bool_value(payload.get("reward_rules_verified"), False),
        "rebate_rules_verified": bool_value(payload.get("rebate_rules_verified"), False),
        "order_semantics_verified": bool_value(payload.get("order_semantics_verified"), False),
        "limit_order_semantics_verified": bool_value(payload.get("limit_order_semantics_verified"), False),
        "market_order_semantics_verified": bool_value(payload.get("market_order_semantics_verified"), False),
        "cancel_semantics_verified": bool_value(payload.get("cancel_semantics_verified"), False),
        "tick_size_verified": bool_value(payload.get("tick_size_verified"), False),
        "min_order_size_verified": bool_value(payload.get("min_order_size_verified"), False),
        "user_websocket_verified": bool_value(payload.get("user_websocket_verified"), False),
        "cancel_all_verified": bool_value(payload.get("cancel_all_verified"), False),
        "isolated_pilot_wallet": bool_value(payload.get("isolated_pilot_wallet"), False),
        "pilot_wallet_cap_recorded": pilot_wallet_cap is not None and pilot_wallet_cap > 0,
        "backend_only_signing": bool_value(payload.get("backend_only_signing"), False),
        "private_key_storage_recorded": non_empty_text(payload.get("private_key_storage")),
        "secrets_not_committed": bool_value(payload.get("secrets_not_committed"), False),
        "no_secret_material": not contains_secret_material(payload),
        "source_urls_recorded": any(non_empty_text(url) for url in source_urls),
    }
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
        "account_jurisdiction": payload.get("account_jurisdiction"),
        "wallet_type": payload.get("wallet_type"),
        "signature_type": payload.get("signature_type"),
        "signature_type_id": payload.get("signature_type_id"),
        "api_base_url": payload.get("api_base_url"),
        "clob_host": payload.get("clob_host"),
        "pilot_wallet_max_funding_usdc": pilot_wallet_cap,
        "checks": checks,
        "missing": missing,
        "reason": "ok" if not missing else "platform verification missing live account proof: " + ", ".join(missing),
    }


REMEDIATION_RULES = {
    "active_event": {
        "root_cause": "missing_active_event",
        "owner": "market registry / Gamma event discovery",
        "suggested_command": "python -m weather.market.market_microstructure refresh-tokens",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "snapshot_model_rows": {
        "root_cause": "missing_snapshot_model_rows",
        "owner": "weather snapshot/model loop",
        "suggested_command": "python -m weather.collection.snapshot_tracker --status",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "model_freshness": {
        "root_cause": "stale_model_row",
        "owner": "weather snapshot/model loop",
        "roadmap_owner_items": ["161", "157"],
        "suggested_command": "python -m weather.collection.snapshot_tracker --status",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "source_status_rows": {
        "root_cause": "missing_source_status_row",
        "owner": "snapshot source-status writer",
        "suggested_command": "python -m weather.collection.snapshot_tracker --backfill-source-status --overwrite-source-status",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "source_status_fresh": {
        "root_cause": "stale_source_status_row",
        "owner": "snapshot source-status writer",
        "suggested_command": "python -m weather.collection.snapshot_tracker --status",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "clob_tokens": {
        "root_cause": "missing_clob_tokens",
        "owner": "CLOB token discovery",
        "suggested_command": "python -m weather.market.market_microstructure refresh-tokens",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "clob_discovery": {
        "root_cause": "blank_or_inactive_clob_discovery",
        "owner": "CLOB token discovery / Gamma event discovery",
        "suggested_command": "python -m weather.market.market_microstructure capture --market all",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "clob_books": {
        "root_cause": "missing_clob_book_rows",
        "owner": "CLOB book loop",
        "suggested_command": "python -m weather.market.market_microstructure status",
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
        "suggested_command": "python -m weather.market.market_microstructure ensure",
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
        "suggested_command": "python -m weather.reporting.promotion_refresh",
        "recoverable_same_day": False,
        "counts_after_failure": False,
    },
    "reward_metadata": {
        "root_cause": "missing_reward_metadata",
        "owner": "CLOB book/token metadata",
        "suggested_command": "python -m weather.market.market_microstructure ensure",
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
        "suggested_command": "python -m weather.reporting.data_layer_audit --fleet --json",
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


def build_preflight_remediation(preflight, now, previous=None):
    previous_by_key = {
        row.get("incident_key"): row
        for row in ((previous or {}).get("incidents") or [])
        if row.get("incident_key")
    }
    incidents = []
    owner_counts = Counter()
    root_counts = Counter()
    for market in preflight.get("markets", []):
        for gate in market.get("gates") or []:
            if gate.get("ok"):
                continue
            rule = REMEDIATION_RULES.get(gate.get("name"), {
                "root_cause": gate.get("name") or "unknown_preflight_failure",
                "owner": "unknown",
                "suggested_command": "inspect preflight.json",
                "recoverable_same_day": False,
                "counts_after_failure": False,
            })
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
                "suggested_command": rule["suggested_command"],
                "recoverable_same_day": bool(rule["recoverable_same_day"]),
                "can_still_count_live_forward_day": bool(rule["counts_after_failure"]),
                "alert_within_seconds": 60,
                "last_good_artifact": remediation_last_good_artifact(market, gate.get("name") or ""),
            }
            incidents.append(incident)
            owner_counts[incident["owner"]] += 1
            root_counts[incident["root_cause"]] += 1
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
