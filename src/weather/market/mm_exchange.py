"""Keyless exchange adapter harness for MM-2 live-pilot reconciliation.

This module owns the live adapter boundary. It is dry-run/read-only by default:
it can inspect a live-pilot run folder, verify item-45 gates, compare local
lifecycle state with fixture or read-only exchange snapshots, and append
reconciliation events. It does not load private keys or place orders unless a
future concrete adapter is explicitly wired behind the same gate checks.

Ownership note: keep live adapter orchestration here. Side-effect-free probe,
pilot-report, financial-reconciliation, and Markdown helpers belong in
``weather.market.mm_exchange_reports``.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import time
from pathlib import Path

from weather.io import append_csv_rows, append_jsonl as io_append_jsonl, read_csv_rows as io_read_csv_rows, read_jsonl
from weather.market.market_making_run_constants import FILL_COLUMNS, SCHEMA_VERSION as RUN_SCHEMA_VERSION
from weather.market.mm_exchange_reports import (
    SCHEMA_VERSION,
    actual_reward_rebate_usdc,
    balance_amount_usdc,
    build_financial_reconciliation,
    build_pilot_report_payload,
    build_reconciliation_report,
    first_numeric,
    maker_rebate_reconciliation,
    mm2_probe_status,
    numeric_sum,
    render_pilot_report,
)
from weather.market.mm_policy import bool_value, maybe_float, utc_now


EXECUTION_MODES = {"dry-run", "read-only", "live"}

REQUIRED_ENV_BY_PLATFORM = {
    "polymarket_global": (
        "POLYMARKET_API_KEY_STORAGE_REF",
        "POLYMARKET_API_SECRET_STORAGE_REF",
        "POLYMARKET_API_PASSPHRASE_STORAGE_REF",
        "POLYMARKET_FUNDER_ADDRESS",
        "POLYMARKET_PRIVATE_KEY_STORAGE_REF",
    ),
    "polymarket_us": (
        "POLYMARKET_US_KEY_ID",
        "POLYMARKET_US_SECRET_KEY_STORAGE_REF",
    ),
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

PLATFORM_BASE_URLS = {
    "polymarket_global": "https://clob.polymarket.com",
    "polymarket_us": "https://api.polymarket.us",
}

GLOBAL_ACTIONS = {
    "create_post_only",
    "cancel_order",
    "cancel_all",
    "heartbeat",
    "open_orders",
    "get_order",
    "positions",
    "balances",
    "allowances",
    "rewards",
    "redemption_status",
}

US_ACTIONS = {
    "create_post_only",
    "preview_post_only",
    "cancel_order",
    "cancel_all",
    "open_orders",
    "get_order",
    "positions",
    "balances",
    "allowances",
    "rewards",
    "redemption_status",
}

US_LATENCY_STOPGAP_TEXT = "global rate limit exceeded"
US_LATENCY_STOPGAP_ORDER_ACTIONS = {"create_post_only"}
US_CANCEL_ACTIONS = {"cancel_order", "cancel_all"}


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(path)


def payload_text(value):
    if value is None:
        return ""
    if isinstance(value, dict):
        parts = []
        for key in ("message", "error", "errorMsg", "text", "detail", "status"):
            if value.get(key) not in (None, ""):
                parts.append(str(value.get(key)))
        if not parts:
            parts.extend(payload_text(child) for child in value.values())
        return " ".join(part for part in parts if part)
    if isinstance(value, (list, tuple)):
        return " ".join(payload_text(child) for child in value)
    return str(value)


def is_us_latency_stopgap_payload(value):
    return US_LATENCY_STOPGAP_TEXT in payload_text(value).lower()


def classify_polymarket_us_response(action, payload, http_status=None):
    if not is_us_latency_stopgap_payload(payload):
        return payload
    status_code = http_status
    if status_code is None and isinstance(payload, dict):
        status_code = payload.get("status") or payload.get("status_code")
    base = {
        "success": False,
        "platform": "polymarket_us",
        "action": action,
        "http_status": status_code,
        "exchange_message": payload_text(payload),
        "raw_response": payload,
    }
    if action in US_LATENCY_STOPGAP_ORDER_ACTIONS:
        return {
            **base,
            "status": "rejected",
            "reject_class": "latency_stopgap",
            "order_acceptance": "not_accepted",
            "rate_limit_backoff_required": False,
            "must_refresh_book_before_retry": True,
            "retry_guidance": "treat as stale-price protection; refresh book and recompute quote before any new order",
        }
    if action in US_CANCEL_ACTIONS:
        return {
            **base,
            "status": "unexpected_cancel_reject",
            "reject_class": "unexpected_latency_stopgap_on_cancel",
            "live_readiness_blocker": True,
            "retry_guidance": "pure cancels should not be blocked by the latency stopgap; verify open orders and escalate",
        }
    return {
        **base,
        "status": "rejected",
        "reject_class": "latency_stopgap_unknown_action",
        "live_readiness_blocker": True,
        "retry_guidance": "verify action semantics before retrying",
    }


def classify_polymarket_us_exception(action, exc):
    response = getattr(exc, "response", None)
    payload = None
    status_code = None
    if response is not None:
        status_code = getattr(response, "status_code", None)
        try:
            payload = response.json()
        except Exception:
            payload = getattr(response, "text", None)
    if payload is None:
        payload = str(exc)
    if not is_us_latency_stopgap_payload(payload):
        return None
    return classify_polymarket_us_response(action, payload, http_status=status_code)


def read_csv_rows(path):
    return io_read_csv_rows(path, attach_diagnostics=True)


def append_jsonl(path, rows):
    if not rows:
        return
    return io_append_jsonl(path, list(rows or []))


def append_csv(path, fieldnames, rows):
    if not rows:
        return
    return append_csv_rows(path, fieldnames, rows)


def read_jsonl_rows(path):
    return read_jsonl(path, skip_invalid=False)


def contains_secret_material(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in SECRET_FIELD_NAMES and child not in (None, "", False):
                return True
            if contains_secret_material(child):
                return True
    if isinstance(value, list):
        return any(contains_secret_material(child) for child in value)
    return False


def _lifecycle_key(row):
    return row.get("lifecycle_key") or row.get("client_order_id") or row.get("clientOrderId") or row.get("order_key") or ""


def money_value(value):
    if isinstance(value, dict):
        return value.get("value")
    return value


def us_private_ws_side(order):
    intent = str((order or {}).get("intent") or "").upper()
    side = str((order or {}).get("side") or "").upper()
    if intent == "ORDER_INTENT_SELL_LONG":
        return "YES_ASK"
    if intent == "ORDER_INTENT_BUY_SHORT":
        return "NO_BID"
    if intent == "ORDER_INTENT_SELL_SHORT":
        return "NO_ASK"
    if side == "ORDER_SIDE_SELL":
        return "YES_ASK"
    return "YES_BID"


def us_private_ws_event_type(execution_type):
    execution_type = str(execution_type or "").upper()
    if execution_type in {"EXECUTION_TYPE_PARTIAL_FILL", "EXECUTION_TYPE_FILL"}:
        return "fill"
    if execution_type == "EXECUTION_TYPE_CANCELED":
        return "canceled"
    if execution_type == "EXECUTION_TYPE_REPLACE":
        return "replaced"
    if execution_type == "EXECUTION_TYPE_REJECTED":
        return "rejected"
    if execution_type in {"EXECUTION_TYPE_EXPIRED", "EXECUTION_TYPE_DONE_FOR_DAY"}:
        return "expired"
    return ""


def normalize_us_private_ws_user_event(raw):
    update = (raw or {}).get("orderSubscriptionUpdate") or (raw or {}).get("order_subscription_update")
    if not isinstance(update, dict):
        return []
    execution = update.get("execution") or {}
    if not isinstance(execution, dict):
        return []
    order = execution.get("order") or {}
    if not isinstance(order, dict):
        order = {}
    event_type = us_private_ws_event_type(execution.get("type"))
    if not event_type:
        return []
    market_metadata = order.get("marketMetadata") or order.get("market_metadata") or {}
    market_slug = order.get("marketSlug") or order.get("market_slug")
    order_id = order.get("id") or execution.get("orderId") or execution.get("order_id")
    generated_at = (
        raw.get("generated_at_utc")
        or execution.get("transactTime")
        or execution.get("transact_time")
        or order.get("transactTime")
        or order.get("transact_time")
        or order.get("updateTime")
        or order.get("update_time")
    )
    normalized = {
        "event_type": event_type,
        "generated_at_utc": generated_at,
        "lifecycle_key": order.get("clientOrderId") or order.get("client_order_id") or raw.get("clientOrderId"),
        "order_key": order.get("clientOrderId") or order.get("client_order_id") or raw.get("clientOrderId"),
        "order_id": order_id,
        "exchange_execution_id": execution.get("id"),
        "exchange_execution_type": execution.get("type"),
        "trade_id": execution.get("tradeId") or execution.get("trade_id"),
        "market_slug": market_slug,
        "event_slug": market_metadata.get("eventSlug") or market_metadata.get("event_slug") or market_slug,
        "clob_token_id": order.get("tokenId") or order.get("token_id"),
        "side": us_private_ws_side(order),
        "fill_price": money_value(execution.get("lastPx") or execution.get("last_px")),
        "fill_size": execution.get("lastShares") or execution.get("last_shares"),
        "price": money_value(order.get("price")),
        "size": order.get("quantity"),
        "reason": execution.get("text") or order.get("text") or execution.get("type"),
        "source": "polymarket_us_private_ws",
    }
    return [normalized]


def normalize_user_event(raw):
    if not isinstance(raw, dict):
        return []
    if raw.get("orderSubscriptionUpdate") or raw.get("order_subscription_update"):
        return normalize_us_private_ws_user_event(raw)
    return [raw]


def run_context(run_folder):
    run_folder = Path(run_folder)
    return {
        "run_folder": run_folder,
        "run_config": read_json(run_folder / "run_config.json", {}) or {},
        "preflight": read_json(run_folder / "preflight.json", {}) or {},
        "summary": read_json(run_folder / "run_summary.json", {}) or {},
        "quote_rows": read_csv_rows(run_folder / "quote_intents_long.csv"),
        "lifecycle_rows": read_jsonl_rows(run_folder / "order_lifecycle.jsonl"),
    }


def item45_gate_summary(preflight):
    live_readiness = preflight.get("live_readiness") or {}
    data_layer = preflight.get("data_layer_live_gate") or {}
    platform = preflight.get("platform_verification_gate") or {}
    checks = {
        "preflight_pass": preflight.get("status") == "PASS",
        "mode_live_pilot": preflight.get("mode") == "live-pilot",
        "live_readiness_ok": bool(live_readiness.get("ok")),
        "data_layer_live_gate_ok": bool(data_layer.get("ok")),
        "platform_verification_gate_ok": bool(platform.get("ok")),
        "release_production_capable": preflight.get("release_production_capable") is True,
        "market_preflights_pass": all((row.get("status") == "PASS") for row in preflight.get("markets") or []),
    }
    missing = [name for name, ok in checks.items() if not ok]
    return {
        "ok": not missing,
        "checks": checks,
        "missing": missing,
        "platform": platform.get("platform"),
        "platform_path": platform.get("path"),
    }


def credential_diagnostics(platform, env=None):
    env = env if env is not None else os.environ
    required = REQUIRED_ENV_BY_PLATFORM.get(platform or "", ())
    present = {name: bool(env.get(name)) for name in required}
    forbidden_direct = [
        name
        for name in (
            "POLYMARKET_API_KEY",
            "POLYMARKET_API_SECRET",
            "POLYMARKET_API_PASSPHRASE",
            "POLYMARKET_PRIVATE_KEY",
            "POLYMARKET_US_SECRET_KEY",
        )
        if env.get(name)
    ]
    return {
        "platform": platform,
        "required_env_names": list(required),
        "present_env_names": [name for name, ok in present.items() if ok],
        "missing_env_names": [name for name, ok in present.items() if not ok],
        "forbidden_direct_secret_env_names_present": forbidden_direct,
        "values_redacted": True,
        "ok": bool(required) and all(present.values()) and not forbidden_direct,
    }


def canonical_json(payload):
    if payload is None:
        return ""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def current_timestamp_ms():
    return str(int(time.time() * 1000))


def encode_signature(signature):
    if signature is None:
        return None
    if isinstance(signature, str):
        return signature
    return base64.b64encode(signature).decode("ascii")


def signature_digest(signature):
    encoded = encode_signature(signature)
    if not encoded:
        return None
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def call_signer(signer, message):
    if signer is None:
        return None
    return signer(message.encode("utf-8"))


def redacted_header_map(names, signed=False):
    headers = {"Content-Type": "application/json"}
    for name in names:
        if name.endswith("SIGNATURE") or name == "X-PM-Signature":
            headers[name] = "<signed-redacted>" if signed else "<signature-unavailable>"
        else:
            headers[name] = "<redacted>"
    return headers


def us_order_intent(side):
    side = str(side or "").upper()
    if side in {"YES_BID", "BUY", "BUY_YES"}:
        return "ORDER_INTENT_BUY_LONG"
    if side in {"YES_ASK", "SELL", "SELL_YES"}:
        return "ORDER_INTENT_SELL_LONG"
    if side in {"NO_BID", "BUY_NO"}:
        return "ORDER_INTENT_BUY_SHORT"
    if side in {"NO_ASK", "SELL_NO"}:
        return "ORDER_INTENT_SELL_SHORT"
    return "ORDER_INTENT_BUY_LONG"


def global_order_side(side):
    side = str(side or "").upper()
    if side in {"YES_ASK", "NO_ASK", "SELL", "SELL_YES", "SELL_NO"}:
        return "SELL"
    return "BUY"


def leg_market_slug(leg, metadata=None):
    metadata = metadata or {}
    return metadata.get("market_slug") or leg.get("market_slug") or leg.get("event_slug") or ""


def build_us_limit_order_body(leg, metadata=None):
    return {
        "marketSlug": leg_market_slug(leg, metadata),
        "type": "ORDER_TYPE_LIMIT",
        "price": {
            "value": str(leg.get("price")),
            "currency": "USD",
        },
        "quantity": maybe_float(leg.get("size")),
        "tif": metadata.get("tif") or "TIME_IN_FORCE_GOOD_TILL_CANCEL",
        "intent": us_order_intent(leg.get("side")),
        "participateDontInitiate": True,
        "clientOrderId": leg.get("lifecycle_key") or leg.get("order_key"),
    }


def build_polymarket_us_request_plan(
    action,
    leg=None,
    metadata=None,
    signer=None,
    timestamp_ms=None,
    base_url=None,
):
    metadata = metadata or {}
    leg = leg or {}
    base_url = (base_url or PLATFORM_BASE_URLS["polymarket_us"]).rstrip("/")
    body = None
    method = "GET"
    path = "/v1/orders/open"
    if action == "create_post_only":
        method = "POST"
        path = "/v1/orders"
        body = build_us_limit_order_body(leg, metadata)
    elif action == "preview_post_only":
        method = "POST"
        path = "/v1/order/preview"
        body = build_us_limit_order_body(leg, metadata)
    elif action == "cancel_order":
        method = "POST"
        order_id = metadata.get("order_id") or leg.get("exchange_order_id") or leg.get("order_id") or "{orderId}"
        path = f"/v1/order/{order_id}/cancel"
        body = {"marketSlug": leg_market_slug(leg, metadata)}
    elif action == "cancel_all":
        method = "POST"
        path = "/v1/orders/open/cancel"
        slugs = metadata.get("slugs")
        if slugs is None:
            market_slug = leg_market_slug(leg, metadata)
            slugs = [market_slug] if market_slug else []
        body = {"slugs": slugs}
    elif action == "get_order":
        order_id = metadata.get("order_id") or leg.get("exchange_order_id") or leg.get("order_id") or "{orderId}"
        path = f"/v1/order/{order_id}"
    elif action == "positions":
        path = "/v1/portfolio/positions"
    elif action == "balances":
        path = "/v1/account/balances"
    elif action == "allowances":
        path = "/v1/account/balances"
    elif action == "rewards":
        path = "/v1/portfolio/activities"
    elif action == "redemption_status":
        path = "/v1/portfolio/positions"
    elif action != "open_orders":
        raise ValueError(f"unsupported Polymarket US action {action!r}")

    timestamp_ms = str(timestamp_ms or current_timestamp_ms())
    signature_payload = f"{timestamp_ms}{method}{path}"
    signature = call_signer(signer, signature_payload)
    return {
        "platform": "polymarket_us",
        "action": action,
        "method": method,
        "timestamp_ms": timestamp_ms,
        "base_url": base_url,
        "path": path,
        "url": base_url + path,
        "body": body,
        "body_sha256": hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest() if body is not None else None,
        "headers": redacted_header_map(("X-PM-Access-Key", "X-PM-Timestamp", "X-PM-Signature"), signed=signature is not None),
        "signature_payload": signature_payload,
        "signature_present": signature is not None,
        "signature_sha256": signature_digest(signature),
        "sends_secret_values": False,
        "ready": signature is not None,
        "blockers": [] if signature is not None else ["missing injected Polymarket US Ed25519 signer"],
    }


def build_global_clob_request_plan(
    action,
    leg=None,
    metadata=None,
    signer=None,
    timestamp_ms=None,
    base_url=None,
):
    metadata = metadata or {}
    leg = leg or {}
    base_url = (base_url or PLATFORM_BASE_URLS["polymarket_global"]).rstrip("/")
    body = None
    method = "GET"
    path = "/data/orders"
    blockers = []
    if action == "create_post_only":
        method = "POST"
        path = "/order"
        signed_order = metadata.get("signed_order")
        body = {
            "order": signed_order or {
                "tokenId": leg.get("clob_token_id"),
                "side": global_order_side(leg.get("side")),
                "price": leg.get("price"),
                "size": leg.get("size"),
                "signature": "<required-from-official-clob-client>",
            },
            "owner": metadata.get("owner") or "<api-key-owner-uuid>",
            "orderType": metadata.get("order_type") or "GTC",
            "postOnly": True,
        }
        if not signed_order:
            blockers.append("global CLOB order placement requires a pre-signed EIP-712 order payload")
    elif action == "cancel_order":
        method = "DELETE"
        path = "/order"
        body = {"orderID": metadata.get("order_id") or leg.get("exchange_order_id") or leg.get("order_id") or "{orderID}"}
    elif action == "cancel_all":
        method = "DELETE"
        path = "/cancel-all"
    elif action == "heartbeat":
        method = "POST"
        path = "/v1/heartbeats"
        body = {"heartbeat_id": metadata.get("heartbeat_id") or ""}
    elif action == "get_order":
        order_id = metadata.get("order_id") or leg.get("exchange_order_id") or leg.get("order_id") or "{orderID}"
        path = f"/data/order/{order_id}"
    elif action == "positions":
        path = "/positions"
    elif action == "balances":
        path = "/value"
    elif action == "allowances":
        path = "/data/orders"
        blockers.append("global allowance verification should be performed by the official CLOB client or wallet provider")
    elif action == "rewards":
        path = "/rewards/user/earnings"
    elif action == "redemption_status":
        path = "/positions"
    elif action != "open_orders":
        raise ValueError(f"unsupported Polymarket global action {action!r}")

    timestamp_ms = str(timestamp_ms or current_timestamp_ms())
    signature_payload = f"{timestamp_ms}{method}{path}{canonical_json(body)}"
    signature = call_signer(signer, signature_payload)
    if signature is None:
        blockers.append("missing injected global CLOB L2 header signer")
    return {
        "platform": "polymarket_global",
        "action": action,
        "method": method,
        "timestamp_ms": timestamp_ms,
        "base_url": base_url,
        "path": path,
        "url": base_url + path,
        "body": body,
        "body_sha256": hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest() if body is not None else None,
        "headers": redacted_header_map(
            ("POLY_ADDRESS", "POLY_API_KEY", "POLY_PASSPHRASE", "POLY_TIMESTAMP", "POLY_SIGNATURE"),
            signed=signature is not None,
        ),
        "signature_payload": signature_payload,
        "signature_present": signature is not None,
        "signature_sha256": signature_digest(signature),
        "sends_secret_values": False,
        "ready": not blockers,
        "blockers": blockers,
    }


def build_adapter_request_plan(platform, action, leg=None, metadata=None, signer=None, timestamp_ms=None):
    if platform == "polymarket_us":
        return build_polymarket_us_request_plan(action, leg=leg, metadata=metadata, signer=signer, timestamp_ms=timestamp_ms)
    if platform == "polymarket_global":
        return build_global_clob_request_plan(action, leg=leg, metadata=metadata, signer=signer, timestamp_ms=timestamp_ms)
    raise ValueError(f"unsupported platform {platform!r}")


def adapter_capability_matrix(platform):
    actions = US_ACTIONS if platform == "polymarket_us" else GLOBAL_ACTIONS if platform == "polymarket_global" else set()
    is_us = platform == "polymarket_us"
    is_global = platform == "polymarket_global"
    return {
        "platform": platform,
        "supported_actions": sorted(actions),
        "post_only_supported": "create_post_only" in actions,
        "maker_only_order_field": "participateDontInitiate" if is_us else "postOnly" if is_global else None,
        "cancel_all_supported": "cancel_all" in actions,
        "heartbeat_supported": is_global,
        "private_user_stream_supported": platform in {"polymarket_global", "polymarket_us"},
        "requires_private_user_stream_for_final_order_state": platform in {"polymarket_global", "polymarket_us"},
        "requires_cancel_all_zero_open_orders_verification": platform in {"polymarket_global", "polymarket_us"},
        "batched_order_results_require_stream_confirmation": is_us,
        "max_cancel_order_batch_size": 20 if is_us else None,
        "latency_stopgap_rejects_order_submit": is_us,
        "latency_stopgap_cancel_exempt": is_us,
        "requires_external_secret_storage": True,
        "direct_secret_values_allowed": False,
    }


def platform_live_readiness_notes(platform):
    if platform == "polymarket_us":
        return [
            {
                "code": "private_user_stream_required",
                "severity": "BLOCK_UNTIL_OBSERVED",
                "detail": "US order, cancel, and modify outcomes must be reconciled from the private WebSocket order stream before live-pilot scale.",
            },
            {
                "code": "cancel_all_requires_zero_open_orders_confirmation",
                "severity": "BLOCK_UNTIL_OBSERVED",
                "detail": "US cancel-all responses are not sufficient by themselves; verify zero open orders after cancel-all.",
            },
            {
                "code": "cancel_batch_size_limit",
                "severity": "REQUIRE_IMPLEMENTATION_IF_USED",
                "detail": "US batched order-cancel requests are capped at 20 orders; returned canceledOrderIds are only an echo/submission record, not final confirmation; any future batch-cancel path must chunk requests and reconcile final state from the private order stream.",
            },
            {
                "code": "latency_stopgap_reject_handling_required",
                "severity": "BLOCK_UNTIL_IMPLEMENTED",
                "detail": "US order and cancel-replace requests can receive latency stopgap rejects that should be treated as transient stale-price protection, while pure cancels remain allowed.",
            },
            {
                "code": "api_key_platform_eligibility_required",
                "severity": "BLOCK_UNTIL_OBSERVED",
                "detail": "US trading requires account/API-key eligibility outside the repo; local diagnostics must not read or print secret values.",
            },
        ]
    if platform == "polymarket_global":
        return [
            {
                "code": "heartbeat_dead_man_required",
                "severity": "BLOCK_UNTIL_OBSERVED",
                "detail": "Global CLOB heartbeat/dead-man cancel behavior must be observed with a harmless probe before live-pilot scale.",
            },
            {
                "code": "private_user_stream_required",
                "severity": "BLOCK_UNTIL_OBSERVED",
                "detail": "Global CLOB user-stream order and trade events must reconcile lifecycle state before live-pilot scale.",
            },
            {
                "code": "cancel_all_requires_zero_open_orders_confirmation",
                "severity": "BLOCK_UNTIL_OBSERVED",
                "detail": "Cancel-all must be followed by zero open-order confirmation.",
            },
        ]
    return [
        {
            "code": "unsupported_platform",
            "severity": "BLOCK_UNTIL_CONFIGURED",
            "detail": f"Unsupported platform {platform!r}; no live adapter readiness assumptions are valid.",
        }
    ]


def build_adapter_request_diagnostics(platform, local_orders, platform_gate=None):
    platform_gate = platform_gate or {}
    metadata = {
        "market_slug": platform_gate.get("event_slug") or platform_gate.get("market_slug"),
        "owner": platform_gate.get("api_key_owner"),
    }
    plans = []
    if platform in {"polymarket_global", "polymarket_us"}:
        sample_leg = local_orders[0] if local_orders else {}
        actions = ["open_orders", "cancel_all", "positions", "balances", "rewards", "redemption_status"]
        if sample_leg:
            actions.insert(0, "create_post_only")
            actions.insert(1, "cancel_order")
        if platform == "polymarket_global":
            actions.insert(0, "heartbeat")
        if platform == "polymarket_us":
            actions.insert(0, "preview_post_only")
        for action in actions:
            try:
                plans.append(build_adapter_request_plan(platform, action, leg=sample_leg, metadata=metadata))
            except ValueError as exc:
                plans.append({"platform": platform, "action": action, "ready": False, "blockers": [str(exc)]})
    return {
        "capability_matrix": adapter_capability_matrix(platform),
        "live_readiness_notes": platform_live_readiness_notes(platform),
        "request_plans": plans,
        "ready_plan_count": sum(1 for plan in plans if plan.get("ready")),
        "blocked_plan_count": sum(1 for plan in plans if not plan.get("ready")),
    }


class NullExchangeAdapter:
    """No-network adapter used for dry-run safety."""

    adapter_id = "null"
    supports_trading = False

    def diagnostics(self):
        return {
            "adapter_id": self.adapter_id,
            "supports_trading": False,
            "read_only": True,
            "reason": "no exchange client configured",
        }

    def open_orders(self):
        return []

    def user_events(self):
        return []

    def balances(self):
        return {}

    def allowances(self):
        return {}

    def positions(self):
        return []

    def position_evidence(self, positions=None):
        return {
            "status": "NOT_CONFIGURED",
            "query_scope": None,
            "maker_address": None,
            "condition_id": None,
            "rows": list(positions or []),
        }

    def rewards(self):
        return {}

    def fees(self):
        return {}

    def redemption_status(self):
        return {}

    def probe_evidence(self):
        return {}

    def place_order(self, _intent):
        raise RuntimeError("live trading verbs are disabled for NullExchangeAdapter")

    def cancel_all(self):
        raise RuntimeError("live trading verbs are disabled for NullExchangeAdapter")


class FixtureExchangeAdapter(NullExchangeAdapter):
    """Read-only adapter backed by a fixture payload for deterministic tests."""

    adapter_id = "fixture"

    def __init__(self, payload):
        self.payload = payload or {}

    def diagnostics(self):
        return {
            "adapter_id": self.adapter_id,
            "supports_trading": False,
            "read_only": True,
            **(self.payload.get("diagnostics") or {}),
        }

    def open_orders(self):
        return list(self.payload.get("open_orders") or [])

    def user_events(self):
        return list(self.payload.get("user_events") or [])

    def balances(self):
        return dict(self.payload.get("balances") or {})

    def allowances(self):
        return dict(self.payload.get("allowances") or {})

    def positions(self):
        return list(self.payload.get("positions") or [])

    def position_evidence(self, positions=None):
        return dict(self.payload.get("position_evidence") or {})

    def rewards(self):
        return dict(self.payload.get("rewards") or {})

    def fees(self):
        return dict(self.payload.get("fees") or {})

    def redemption_status(self):
        return dict(self.payload.get("redemption_status") or {})

    def probe_evidence(self):
        return dict(self.payload.get("probe_evidence") or {})


class RequestsTransport:
    """Thin wrapper around requests, isolated so tests can inject a fake."""

    def request(self, method, url, headers=None, json_body=None):
        import requests

        response = requests.request(method, url, headers=headers, json=json_body, timeout=20)
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()


class RecordingTransport:
    """Deterministic transport used by tests and dry adapter probes."""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.requests = []

    def request(self, method, url, headers=None, json_body=None):
        self.requests.append({
            "method": method,
            "url": url,
            "headers": dict(headers or {}),
            "json_body": json_body,
        })
        if self.responses:
            return self.responses.pop(0)
        return {}


class PolymarketUSHTTPAdapter(NullExchangeAdapter):
    adapter_id = "polymarket_us_http"
    supports_trading = True

    def __init__(self, key_id, signer, transport=None, base_url=None):
        self.key_id = key_id
        self.signer = signer
        self.transport = transport or RequestsTransport()
        self.base_url = (base_url or PLATFORM_BASE_URLS["polymarket_us"]).rstrip("/")

    def diagnostics(self):
        return {
            "adapter_id": self.adapter_id,
            "supports_trading": True,
            "read_only": False,
            "base_url": self.base_url,
            "key_id_present": bool(self.key_id),
            "signer_present": self.signer is not None,
            "secret_values_redacted": True,
        }

    def _headers(self, plan):
        signature = call_signer(self.signer, plan["signature_payload"])
        return {
            "Content-Type": "application/json",
            "X-PM-Access-Key": self.key_id,
            "X-PM-Timestamp": plan["timestamp_ms"],
            "X-PM-Signature": encode_signature(signature),
        }

    def _request(self, action, leg=None, metadata=None):
        plan = build_polymarket_us_request_plan(
            action,
            leg=leg,
            metadata=metadata,
            signer=self.signer,
            base_url=self.base_url,
        )
        if not self.key_id:
            raise RuntimeError("Polymarket US API key id is required")
        if not plan["ready"]:
            raise RuntimeError("; ".join(plan["blockers"]))
        try:
            payload = self.transport.request(
                plan["method"],
                plan["url"],
                headers=self._headers(plan),
                json_body=plan.get("body"),
            )
        except Exception as exc:
            classified = classify_polymarket_us_exception(action, exc)
            if classified is not None:
                return classified
            raise
        return classify_polymarket_us_response(action, payload)

    def open_orders(self):
        payload = self._request("open_orders")
        return payload.get("orders") or payload.get("data") or []

    def balances(self):
        return self._request("balances")

    def allowances(self):
        return self._request("allowances")

    def positions(self):
        payload = self._request("positions")
        positions = payload.get("positions") if isinstance(payload, dict) else None
        return positions if isinstance(positions, list) else payload

    def rewards(self):
        return self._request("rewards")

    def place_order(self, intent):
        return self._request("create_post_only", leg=intent)

    def preview_order(self, intent):
        return self._request("preview_post_only", leg=intent)

    def cancel_order(self, order_id, market_slug=None):
        return self._request("cancel_order", metadata={"order_id": order_id, "market_slug": market_slug})

    def cancel_all(self, slugs=None):
        return self._request("cancel_all", metadata={"slugs": slugs or []})

    def get_order(self, order_id):
        return self._request("get_order", metadata={"order_id": order_id})

    def redemption_status(self, market_slug=None):
        return self._request("redemption_status", metadata={"market_slug": market_slug})


class PolymarketGlobalHTTPAdapter(NullExchangeAdapter):
    adapter_id = "polymarket_global_http"
    supports_trading = True

    def __init__(self, api_key, address, passphrase, signer, transport=None, base_url=None):
        self.api_key = api_key
        self.address = address
        self.passphrase = passphrase
        self.signer = signer
        self.transport = transport or RequestsTransport()
        self.base_url = (base_url or PLATFORM_BASE_URLS["polymarket_global"]).rstrip("/")

    def diagnostics(self):
        return {
            "adapter_id": self.adapter_id,
            "supports_trading": True,
            "read_only": False,
            "base_url": self.base_url,
            "api_key_present": bool(self.api_key),
            "address_present": bool(self.address),
            "passphrase_present": bool(self.passphrase),
            "signer_present": self.signer is not None,
            "secret_values_redacted": True,
        }

    def _headers(self, plan):
        signature = call_signer(self.signer, plan["signature_payload"])
        return {
            "Content-Type": "application/json",
            "POLY_ADDRESS": self.address,
            "POLY_API_KEY": self.api_key,
            "POLY_PASSPHRASE": self.passphrase,
            "POLY_TIMESTAMP": plan["timestamp_ms"],
            "POLY_SIGNATURE": encode_signature(signature),
        }

    def _request(self, action, leg=None, metadata=None):
        plan = build_global_clob_request_plan(
            action,
            leg=leg,
            metadata=metadata,
            signer=self.signer,
            base_url=self.base_url,
        )
        missing = [
            name for name, value in (
                ("api_key", self.api_key),
                ("address", self.address),
                ("passphrase", self.passphrase),
            )
            if not value
        ]
        if missing:
            raise RuntimeError("missing global CLOB credentials: " + ", ".join(missing))
        if not plan["ready"]:
            raise RuntimeError("; ".join(plan["blockers"]))
        return self.transport.request(
            plan["method"],
            plan["url"],
            headers=self._headers(plan),
            json_body=plan.get("body"),
        )

    def open_orders(self):
        payload = self._request("open_orders")
        return payload.get("data") or payload.get("orders") or []

    def balances(self):
        return self._request("balances")

    def allowances(self):
        return self._request("allowances")

    def positions(self):
        return self._request("positions")

    def rewards(self):
        return self._request("rewards")

    def heartbeat(self, heartbeat_id=""):
        return self._request("heartbeat", metadata={"heartbeat_id": heartbeat_id})

    def place_order(self, intent):
        return self._request("create_post_only", leg=intent, metadata=intent)

    def cancel_order(self, order_id):
        return self._request("cancel_order", metadata={"order_id": order_id})

    def cancel_all(self):
        return self._request("cancel_all")

    def get_order(self, order_id):
        return self._request("get_order", metadata={"order_id": order_id})

    def redemption_status(self):
        return self._request("redemption_status")


def adapter_from_fixture(fixture_path=None):
    if not fixture_path:
        return NullExchangeAdapter()
    return FixtureExchangeAdapter(read_json(fixture_path, {}) or {})


def local_live_orders(lifecycle_rows):
    return [
        row for row in lifecycle_rows
        if row.get("transition") == "live_posted"
    ]


def match_exchange_orders(local_orders, exchange_orders):
    exchange_by_key = {
        _lifecycle_key(row): row
        for row in exchange_orders
        if _lifecycle_key(row)
    }
    matched = []
    missing_exchange = []
    matched_exchange_keys = set()
    for order in local_orders:
        key = _lifecycle_key(order)
        exchange = exchange_by_key.get(key)
        if exchange:
            matched_exchange_keys.add(key)
            matched.append({
                "lifecycle_key": key,
                "order_key": order.get("order_key"),
                "exchange_order_id": exchange.get("order_id") or exchange.get("id"),
                "market_id": order.get("market_id"),
                "clob_token_id": order.get("clob_token_id"),
                "side": order.get("side"),
                "local_remaining_size": maybe_float(order.get("remaining_size")),
                "exchange_remaining_size": maybe_float(exchange.get("remaining_size")),
                "exchange_status": exchange.get("status"),
            })
        else:
            missing_exchange.append({
                "lifecycle_key": key,
                "order_key": order.get("order_key"),
                "market_id": order.get("market_id"),
                "clob_token_id": order.get("clob_token_id"),
                "side": order.get("side"),
            })
    extra_exchange = [
        row for row in exchange_orders
        if _lifecycle_key(row) and _lifecycle_key(row) not in matched_exchange_keys
    ]
    return matched, missing_exchange, extra_exchange


def lifecycle_events_from_user_events(
    user_events,
    now,
    exchange_order_to_lifecycle=None,
):
    events = []
    fill_rows = []
    exchange_order_to_lifecycle = exchange_order_to_lifecycle or {}
    for source_raw in user_events:
        for raw in normalize_user_event(source_raw):
            event_type = str(raw.get("event_type") or raw.get("type") or "").lower()
            raw_key = _lifecycle_key(raw)
            key = exchange_order_to_lifecycle.get(raw_key, raw_key)
            if not key:
                continue
            if event_type in {"fill", "filled", "trade"}:
                event = {
                    "schema_version": RUN_SCHEMA_VERSION,
                    "generated_at_utc": raw.get("generated_at_utc") or raw.get("filled_at_utc") or now.isoformat(),
                    "transition": "filled",
                    "lifecycle_key": key,
                    "order_key": raw.get("order_key"),
                    "exchange_order_id": raw.get("order_id"),
                    "exchange_execution_id": raw.get("exchange_execution_id"),
                    "exchange_execution_type": raw.get("exchange_execution_type"),
                    "trade_id": raw.get("trade_id"),
                    "maker_address": raw.get("maker_address"),
                    "condition_id": raw.get("condition_id"),
                    "market_id": raw.get("market_id"),
                    "event_slug": raw.get("event_slug"),
                    "clob_token_id": raw.get("clob_token_id"),
                    "side": raw.get("side"),
                    "fill_price": maybe_float(raw.get("fill_price") or raw.get("price")),
                    "fill_size": maybe_float(raw.get("fill_size") or raw.get("size")),
                    "liquidity_role": str(raw.get("liquidity_role") or "").upper() or None,
                    "fee_rate_bps": maybe_float(raw.get("fee_rate_bps")),
                    "transaction_hash": raw.get("transaction_hash"),
                    "official_trade_status": raw.get("official_trade_status"),
                    "source": raw.get("source") or "exchange_user_stream",
                }
                events.append(event)
                fill_rows.append({
                    "run_id": raw.get("run_id"),
                    "generated_at_utc": event["generated_at_utc"],
                    "mode": "live-pilot",
                    "lifecycle_key": key,
                    "market_id": raw.get("market_id"),
                    "event_slug": raw.get("event_slug"),
                    "snapshot_id": raw.get("snapshot_id"),
                    "range_label": raw.get("range_label"),
                    "clob_token_id": raw.get("clob_token_id"),
                    "side": raw.get("side"),
                    "intended_price": raw.get("intended_price"),
                    "intended_size": raw.get("intended_size"),
                    "fill_status": "filled",
                    "fill_price": event["fill_price"],
                    "fill_size": event["fill_size"],
                    "exchange_order_id": event["exchange_order_id"],
                    "trade_id": event["trade_id"],
                    "transaction_hash": event["transaction_hash"],
                    "maker_address": event["maker_address"],
                    "condition_id": event["condition_id"],
                    "liquidity_role": event["liquidity_role"],
                    "fee_rate_bps": event["fee_rate_bps"],
                    "official_trade_status": event["official_trade_status"],
                    "maker_rebate_estimate_usdc": raw.get("maker_rebate_estimate_usdc"),
                    "markout_30m": raw.get("markout_30m") or raw.get("markout_30m_usdc"),
                    "simulator": raw.get("source") or "exchange_user_stream",
                    "notes": raw.get("notes") or raw.get("exchange_execution_type") or "",
                })
            elif event_type == "trade_pending":
                events.append({
                    "schema_version": RUN_SCHEMA_VERSION,
                    "generated_at_utc": raw.get("generated_at_utc") or now.isoformat(),
                    "transition": "fill_pending",
                    "lifecycle_key": key,
                    "exchange_order_id": raw.get("order_id"),
                    "trade_id": raw.get("trade_id"),
                    "market_id": raw.get("market_id"),
                    "event_slug": raw.get("event_slug"),
                    "clob_token_id": raw.get("clob_token_id"),
                    "side": raw.get("side"),
                    "fill_price": maybe_float(raw.get("fill_price") or raw.get("price")),
                    "fill_size": maybe_float(raw.get("fill_size") or raw.get("size")),
                    "liquidity_role": str(raw.get("liquidity_role") or "").upper() or None,
                    "official_trade_status": raw.get("official_trade_status"),
                    "source": raw.get("source") or "exchange_user_stream",
                })
            elif event_type in {"cancel", "canceled", "cancelled", "rejected", "replace", "replaced", "expired", "done_for_day"}:
                transition = {
                    "cancel": "canceled",
                    "cancelled": "canceled",
                    "replaced": "replaced",
                    "replace": "replaced",
                    "done_for_day": "expired",
                }.get(event_type, event_type)
                events.append({
                    "schema_version": RUN_SCHEMA_VERSION,
                    "generated_at_utc": raw.get("generated_at_utc") or now.isoformat(),
                    "transition": transition,
                    "lifecycle_key": key,
                    "order_key": raw.get("order_key"),
                    "exchange_order_id": raw.get("order_id") or raw.get("id"),
                    "exchange_execution_id": raw.get("exchange_execution_id"),
                    "exchange_execution_type": raw.get("exchange_execution_type"),
                    "trade_id": raw.get("trade_id"),
                    "market_id": raw.get("market_id"),
                    "event_slug": raw.get("event_slug"),
                    "clob_token_id": raw.get("clob_token_id"),
                    "side": raw.get("side"),
                    "reason": raw.get("reason") or f"exchange_{event_type}",
                    "source": raw.get("source") or "exchange_user_stream",
                })
    return events, fill_rows


def build_exchange_reconciliation(
    run_folder,
    execution_mode="dry-run",
    fixture_path=None,
    append_reconciliation=False,
    allow_live=False,
    now=None,
    env=None,
):
    if execution_mode not in EXECUTION_MODES:
        raise ValueError(f"unsupported execution_mode {execution_mode!r}")
    now = utc_now(now)
    context = run_context(run_folder)
    preflight = context["preflight"]
    item45 = item45_gate_summary(preflight)
    platform = item45.get("platform")
    creds = credential_diagnostics(platform, env=env)
    adapter = adapter_from_fixture(fixture_path)
    trading_verbs_enabled = (
        execution_mode == "live"
        and bool(allow_live)
        and item45["ok"]
        and creds["ok"]
        and bool(getattr(adapter, "supports_trading", False))
    )
    blockers = []
    if execution_mode == "live" and not allow_live:
        blockers.append("live execution requires --allow-live")
    if execution_mode == "live" and not item45["ok"]:
        blockers.append("item-45 gates are not all passing")
    if execution_mode == "live" and not creds["ok"]:
        blockers.append("credential diagnostics are incomplete")
    if execution_mode == "live" and not getattr(adapter, "supports_trading", False):
        blockers.append("no concrete trading adapter configured")

    exchange_orders = adapter.open_orders()
    local_orders = local_live_orders(context["lifecycle_rows"])
    request_diagnostics = build_adapter_request_diagnostics(
        platform,
        local_orders,
        platform_gate=preflight.get("platform_verification_gate") or {},
    )
    matched, missing_exchange, extra_exchange = match_exchange_orders(local_orders, exchange_orders)
    user_events = adapter.user_events()
    exchange_order_to_lifecycle = {
        str(row.get("exchange_order_id")): _lifecycle_key(row)
        for row in local_orders
        if row.get("exchange_order_id") and _lifecycle_key(row)
    }
    lifecycle_events, fill_rows = lifecycle_events_from_user_events(
        user_events,
        now,
        exchange_order_to_lifecycle=exchange_order_to_lifecycle,
    )
    balances = adapter.balances()
    allowances = adapter.allowances()
    positions = adapter.positions()
    position_evidence = adapter.position_evidence(positions)
    rewards = adapter.rewards()
    fees = adapter.fees()
    redemption_status = adapter.redemption_status()
    probe_evidence = adapter.probe_evidence()
    status = "BLOCK" if blockers else ("WARN" if missing_exchange or extra_exchange else "PASS")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_folder": str(Path(run_folder)),
        "run_id": preflight.get("run_id") or context["run_config"].get("run_id"),
        "target_date": preflight.get("target_date") or context["run_config"].get("target_date"),
        "execution_mode": execution_mode,
        "append_reconciliation": bool(append_reconciliation),
        "allow_live": bool(allow_live),
        "trading_verbs_enabled": trading_verbs_enabled,
        "status": status,
        "blockers": blockers,
        "item45_gates": item45,
        "credential_diagnostics": creds,
        "adapter_diagnostics": adapter.diagnostics(),
        "adapter_request_diagnostics": request_diagnostics,
        "local_live_order_count": len(local_orders),
        "exchange_open_order_count": len(exchange_orders),
        "matched_order_count": len(matched),
        "missing_exchange_order_count": len(missing_exchange),
        "extra_exchange_order_count": len(extra_exchange),
        "matched_orders": matched,
        "missing_exchange_orders": missing_exchange,
        "extra_exchange_orders": extra_exchange,
        "user_stream_event_count": len(lifecycle_events),
        "user_stream_lifecycle_events": lifecycle_events,
        "balances": balances,
        "allowances": allowances,
        "positions": positions,
        "position_evidence": position_evidence,
        "rewards": rewards,
        "fees": fees,
        "redemption_status": redemption_status,
        "probe_evidence": probe_evidence,
    }
    payload["mm2_probe_status"] = mm2_probe_status(payload, probe_evidence=probe_evidence)
    pilot_report = build_pilot_report_payload(
        payload,
        context["quote_rows"],
        fill_rows,
        payload["mm2_probe_status"],
    )
    run_folder = Path(run_folder)
    probe_path = run_folder / "mm2_probe_status.json"
    pilot_json_path = run_folder / "mm2_pilot_report.json"
    pilot_report_path = run_folder / "mm2_pilot_report.md"
    payload["mm2_probe_status_path"] = str(probe_path)
    payload["pilot_report_json_path"] = str(pilot_json_path)
    payload["pilot_report_path"] = str(pilot_report_path)
    if append_reconciliation:
        append_jsonl(run_folder / "order_lifecycle.jsonl", lifecycle_events)
        append_csv(run_folder / "fills_long.csv", FILL_COLUMNS, fill_rows)
        budget_events = [
            {
                "schema_version": RUN_SCHEMA_VERSION,
                "run_id": payload["run_id"],
                "generated_at_utc": event.get("generated_at_utc") or now.isoformat(),
                "event": f"exchange_{event.get('transition')}",
                "budget_action": "exchange_reconciliation",
                "market_id": event.get("market_id"),
                "event_slug": event.get("event_slug"),
                "lifecycle_key": event.get("lifecycle_key"),
                "exchange_order_id": event.get("exchange_order_id"),
                "fill_size": event.get("fill_size"),
                "fill_price": event.get("fill_price"),
                "detail": event.get("reason") or event.get("source") or "exchange lifecycle reconciliation",
            }
            for event in lifecycle_events
        ]
        append_jsonl(run_folder / "budget_ledger.jsonl", budget_events)
        risk_events = [
            {
                "schema_version": RUN_SCHEMA_VERSION,
                "run_id": payload["run_id"],
                "generated_at_utc": now.isoformat(),
                "severity": "warning" if status != "PASS" else "info",
                "category": "exchange_reconciliation",
                "reason": status.lower(),
                "detail": "; ".join(blockers) if blockers else "exchange reconciliation completed",
            }
        ]
        append_jsonl(run_folder / "risk_events.jsonl", risk_events)
    json_path = run_folder / "exchange_reconciliation.json"
    report_path = run_folder / "exchange_reconciliation.md"
    payload["json_path"] = str(json_path)
    payload["report_path"] = str(report_path)
    write_json(probe_path, {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": payload["run_id"],
        "probe_status": payload["mm2_probe_status"],
    })
    write_json(pilot_json_path, pilot_report)
    pilot_report_path.write_text(render_pilot_report(pilot_report), encoding="utf-8")
    write_json(json_path, payload)
    report_path.write_text(build_reconciliation_report(payload), encoding="utf-8")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run keyless MM exchange reconciliation.")
    parser.add_argument("--run-folder", required=True)
    parser.add_argument("--execution-mode", choices=sorted(EXECUTION_MODES), default="dry-run")
    parser.add_argument("--fixture", default=None, help="Read-only exchange snapshot fixture JSON.")
    parser.add_argument("--append-reconciliation", action="store_true")
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--now", default=None)
    args = parser.parse_args(argv)
    payload = build_exchange_reconciliation(
        args.run_folder,
        execution_mode=args.execution_mode,
        fixture_path=args.fixture,
        append_reconciliation=args.append_reconciliation,
        allow_live=args.allow_live,
        now=args.now,
    )
    print(
        "MM exchange reconciliation: "
        f"{payload['status']} matched={payload['matched_order_count']} "
        f"missing={payload['missing_exchange_order_count']} -> {payload['json_path']}"
    )
    return payload


if __name__ == "__main__":
    main()
