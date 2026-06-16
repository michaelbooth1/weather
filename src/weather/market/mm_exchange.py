"""Keyless exchange adapter harness for MM-2 live-pilot reconciliation.

This module owns the live adapter boundary. It is dry-run/read-only by default:
it can inspect a live-pilot run folder, verify item-45 gates, compare local
lifecycle state with fixture or read-only exchange snapshots, and append
reconciliation events. It does not load private keys or place orders unless a
future concrete adapter is explicitly wired behind the same gate checks.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import time
from collections import Counter
from pathlib import Path

try:
    from .market_making_run_constants import FILL_COLUMNS, SCHEMA_VERSION as RUN_SCHEMA_VERSION
    from .mm_policy import bool_value, maybe_float, utc_now
except ImportError:  # pragma: no cover - compatibility-wrapper execution
    from weather.market.market_making_run_constants import FILL_COLUMNS, SCHEMA_VERSION as RUN_SCHEMA_VERSION
    from weather.market.mm_policy import bool_value, maybe_float, utc_now


SCHEMA_VERSION = "mm_exchange_adapter_v0.1"
EXECUTION_MODES = {"dry-run", "read-only", "live"}

REQUIRED_ENV_BY_PLATFORM = {
    "polymarket_global": (
        "POLYMARKET_API_KEY",
        "POLYMARKET_API_SECRET",
        "POLYMARKET_API_PASSPHRASE",
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


def read_csv_rows(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def append_jsonl(path, rows):
    if not rows:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def append_csv(path, fieldnames, rows):
    if not rows:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", restval="")
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def read_jsonl_rows(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


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
    return row.get("lifecycle_key") or row.get("client_order_id") or row.get("order_key") or ""


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
        name for name in ("POLYMARKET_PRIVATE_KEY", "POLYMARKET_US_SECRET_KEY")
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
        path = "/heartbeats"
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
    return {
        "platform": platform,
        "supported_actions": sorted(actions),
        "post_only_supported": "create_post_only" in actions,
        "cancel_all_supported": "cancel_all" in actions,
        "heartbeat_supported": platform == "polymarket_global",
        "private_user_stream_supported": platform in {"polymarket_global", "polymarket_us"},
        "requires_external_secret_storage": True,
        "direct_secret_values_allowed": False,
    }


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
        return self.transport.request(
            plan["method"],
            plan["url"],
            headers=self._headers(plan),
            json_body=plan.get("body"),
        )

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


def lifecycle_events_from_user_events(user_events, now):
    events = []
    fill_rows = []
    for raw in user_events:
        event_type = str(raw.get("event_type") or raw.get("type") or "").lower()
        key = _lifecycle_key(raw)
        if not key:
            continue
        if event_type in {"fill", "filled", "trade"}:
            event = {
                "schema_version": RUN_SCHEMA_VERSION,
                "generated_at_utc": raw.get("generated_at_utc") or raw.get("filled_at_utc") or now.isoformat(),
                "transition": "filled",
                "lifecycle_key": key,
                "order_key": raw.get("order_key"),
                "exchange_order_id": raw.get("order_id") or raw.get("id"),
                "market_id": raw.get("market_id"),
                "event_slug": raw.get("event_slug"),
                "clob_token_id": raw.get("clob_token_id"),
                "side": raw.get("side"),
                "fill_price": maybe_float(raw.get("fill_price") or raw.get("price")),
                "fill_size": maybe_float(raw.get("fill_size") or raw.get("size")),
                "source": "exchange_user_stream",
            }
            events.append(event)
            fill_rows.append({
                "run_id": raw.get("run_id"),
                "generated_at_utc": event["generated_at_utc"],
                "mode": "live-pilot",
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
                "markout_30m": raw.get("markout_30m") or raw.get("markout_30m_usdc"),
                "simulator": "exchange_user_stream",
                "notes": raw.get("notes") or "",
            })
        elif event_type in {"cancel", "canceled", "cancelled", "rejected"}:
            events.append({
                "schema_version": RUN_SCHEMA_VERSION,
                "generated_at_utc": raw.get("generated_at_utc") or now.isoformat(),
                "transition": "rejected" if event_type == "rejected" else "canceled",
                "lifecycle_key": key,
                "order_key": raw.get("order_key"),
                "exchange_order_id": raw.get("order_id") or raw.get("id"),
                "market_id": raw.get("market_id"),
                "event_slug": raw.get("event_slug"),
                "clob_token_id": raw.get("clob_token_id"),
                "side": raw.get("side"),
                "reason": raw.get("reason") or f"exchange_{event_type}",
                "source": "exchange_user_stream",
            })
    return events, fill_rows


def build_reconciliation_report(payload):
    lines = [
        "# MM Exchange Adapter Reconciliation",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        "",
        "## Gate Summary",
        "",
        f"- Item-45 gates ok: `{str((payload.get('item45_gates') or {}).get('ok')).lower()}`",
        f"- Trading verbs enabled: `{str(payload.get('trading_verbs_enabled')).lower()}`",
        f"- Credential values redacted: `{str((payload.get('credential_diagnostics') or {}).get('values_redacted')).lower()}`",
        "",
        "## Adapter Request Plan",
        "",
        f"- Supported actions: `{', '.join(((payload.get('adapter_request_diagnostics') or {}).get('capability_matrix') or {}).get('supported_actions') or [])}`",
        f"- Ready plans: `{(payload.get('adapter_request_diagnostics') or {}).get('ready_plan_count')}`",
        f"- Blocked plans: `{(payload.get('adapter_request_diagnostics') or {}).get('blocked_plan_count')}`",
        "",
        "## Reconciliation",
        "",
        f"- Local live orders: `{payload.get('local_live_order_count')}`",
        f"- Exchange open orders: `{payload.get('exchange_open_order_count')}`",
        f"- Matched orders: `{payload.get('matched_order_count')}`",
        f"- Missing exchange orders: `{payload.get('missing_exchange_order_count')}`",
        f"- Extra exchange orders: `{payload.get('extra_exchange_order_count')}`",
        f"- User stream lifecycle events: `{payload.get('user_stream_event_count')}`",
        "",
        "## MM-2 Probe Status",
        "",
    ]
    for name, row in (payload.get("mm2_probe_status") or {}).items():
        lines.append(f"- `{name}`: `{row.get('status')}` - {row.get('detail')}")
    return "\n".join(lines) + "\n"


def _probe_observed(probe_evidence, name):
    value = (probe_evidence or {}).get(name)
    if isinstance(value, dict):
        return bool_value(value.get("passed") or value.get("observed") or value.get("ok"), False)
    return bool_value(value, False)


def _probe_detail(probe_evidence, name, fallback):
    value = (probe_evidence or {}).get(name)
    if isinstance(value, dict):
        return value.get("detail") or value.get("evidence") or fallback
    return fallback


def mm2_probe_status(payload, probe_evidence=None):
    probe_evidence = probe_evidence or {}
    events = payload.get("user_stream_lifecycle_events") or []
    event_types = Counter(row.get("transition") for row in events)
    cancel_observed = bool(event_types.get("canceled")) or _probe_observed(probe_evidence, "cancel_all_verification")
    return {
        "heartbeat_dead_man": {
            "status": "observed" if _probe_observed(probe_evidence, "heartbeat_dead_man") else "pending_real_probe",
            "detail": _probe_detail(
                probe_evidence,
                "heartbeat_dead_man",
                "requires a real heartbeat-lapse drill with a far-from-mid order",
            ),
        },
        "min_size_tick_post_only": {
            "status": "observed" if _probe_observed(probe_evidence, "min_size_tick_post_only") else "pending_real_probe",
            "detail": _probe_detail(
                probe_evidence,
                "min_size_tick_post_only",
                "requires real preview/rejection or client-side validation evidence",
            ),
        },
        "tiny_two_sided_quote": {
            "status": "observed" if payload.get("matched_order_count", 0) >= 2 else "pending",
            "detail": "requires two matched local/exchange order records for one band",
        },
        "cancel_all_verification": {
            "status": "observed" if cancel_observed else "pending",
            "detail": _probe_detail(
                probe_evidence,
                "cancel_all_verification",
                "requires cancel-all command plus zero open-order confirmation",
            ),
        },
        "user_stream_lifecycle": {
            "status": "observed" if event_types else "pending",
            "detail": f"user stream lifecycle transitions: {dict(sorted(event_types.items()))}",
        },
        "balance_reserve_reconciliation": {
            "status": "observed" if payload.get("balances") else "pending",
            "detail": "requires account balance snapshot from read-only adapter",
        },
        "reward_rebate_reconciliation": {
            "status": "observed" if payload.get("rewards") else "pending_next_cycle",
            "detail": "requires next payout-cycle reward/rebate snapshot",
        },
    }


def numeric_sum(rows, key):
    total = 0.0
    for row in rows or []:
        value = maybe_float(row.get(key))
        if value is not None:
            total += value
    return round(total, 6)


def first_numeric(mapping, *keys):
    mapping = mapping or {}
    for key in keys:
        value = maybe_float(mapping.get(key))
        if value is not None:
            return value
    return None


def actual_reward_rebate_usdc(rewards):
    rewards = rewards or {}
    total = first_numeric(rewards, "total_usdc", "total_reward_usdc", "total_rewards_usdc")
    if total is not None:
        return total
    values = [
        first_numeric(rewards, "maker_rebate_usdc", "maker_rebate"),
        first_numeric(rewards, "reward_rebate_usdc", "rebate_usdc"),
        first_numeric(rewards, "liquidity_reward_usdc", "liquidity_rewards_usdc", "reward_usdc"),
    ]
    values = [value for value in values if value is not None]
    return round(sum(values), 6) if values else None


def balance_amount_usdc(balances, *extra_keys):
    return first_numeric(
        balances,
        *extra_keys,
        "cash",
        "available_cash",
        "available_usdc",
        "usdc",
        "USDC",
        "pUSD",
        "pusd",
        "collateral",
        "balance",
        "total_usdc",
    )


def build_financial_reconciliation(reconciliation, quote_rows, fill_rows):
    balances = reconciliation.get("balances") or {}
    rewards = reconciliation.get("rewards") or {}
    fees = reconciliation.get("fees") or {}
    redemption = reconciliation.get("redemption_status") or {}
    expected_rebate = numeric_sum(quote_rows, "expected_rebate_value")
    expected_reward_score = numeric_sum(quote_rows, "expected_reward_score")
    actual_reward = actual_reward_rebate_usdc(rewards)
    actual_fees = first_numeric(
        fees,
        "paid_usdc",
        "fees_paid_usdc",
        "fee_usdc",
        "maker_fee_usdc",
        "taker_fee_usdc",
        "total_usdc",
    )
    redemption_usdc = first_numeric(
        redemption,
        "redemption_usdc",
        "settlement_redemption_usdc",
        "redeemed_usdc",
        "claimable_usdc",
        "payout_usdc",
    )
    settlement_pnl = first_numeric(
        redemption,
        "settlement_pnl_usdc",
        "realized_pnl_usdc",
        "pnl_usdc",
        "net_pnl_usdc",
    )
    starting_balance = balance_amount_usdc(
        balances,
        "starting_balance_usdc",
        "starting_cash_usdc",
        "cash_before",
        "initial_cash_usdc",
    )
    ending_balance = balance_amount_usdc(
        balances,
        "ending_balance_usdc",
        "ending_cash_usdc",
        "cash_after",
        "final_cash_usdc",
    )
    if starting_balance is not None and ending_balance is not None:
        balance_delta = round(ending_balance - starting_balance, 6)
    else:
        balance_delta = None
    actual_total_pnl = None
    if settlement_pnl is not None:
        actual_total_pnl = settlement_pnl
        if actual_reward is not None:
            actual_total_pnl += actual_reward
        if actual_fees is not None:
            actual_total_pnl -= actual_fees
        actual_total_pnl = round(actual_total_pnl, 6)
    missing = []
    if starting_balance is None or ending_balance is None:
        missing.append("balance_delta")
    if actual_reward is None:
        missing.append("actual_reward_rebate")
    if actual_fees is None:
        missing.append("actual_fees")
    if redemption_usdc is None:
        missing.append("redemption_status")
    if settlement_pnl is None:
        missing.append("settlement_pnl")
    return {
        "expected_rebate_value_usdc": expected_rebate,
        "expected_reward_score": expected_reward_score,
        "actual_reward_rebate_usdc": actual_reward,
        "reward_rebate_delta_usdc": None if actual_reward is None else round(actual_reward - expected_rebate, 6),
        "actual_fees_usdc": actual_fees,
        "redemption_usdc": redemption_usdc,
        "settlement_pnl_usdc": settlement_pnl,
        "starting_balance_usdc": starting_balance,
        "ending_balance_usdc": ending_balance,
        "balance_delta_usdc": balance_delta,
        "actual_total_pnl_after_fees_incentives_usdc": actual_total_pnl,
        "fill_notional_usdc": round(sum(
            (maybe_float(row.get("fill_price")) or 0.0) * (maybe_float(row.get("fill_size")) or 0.0)
            for row in fill_rows or []
        ), 6),
        "missing_evidence": missing,
        "complete": not missing,
    }


def build_pilot_report_payload(reconciliation, quote_rows, fill_rows, probe_status):
    fills = fill_rows or []
    financial = build_financial_reconciliation(reconciliation, quote_rows, fills)
    expected_rebate = numeric_sum(quote_rows, "expected_rebate_value")
    expected_reward_score = numeric_sum(quote_rows, "expected_reward_score")
    actual_reward = financial.get("actual_reward_rebate_usdc")
    markout_values = [
        maybe_float(row.get("markout_30m") or row.get("markout_30m_usdc"))
        for row in fills
    ]
    markout_values = [value for value in markout_values if value is not None]
    paper_quote_rows = [row for row in quote_rows if bool_value(row.get("quote_permission"), False)]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": reconciliation.get("generated_at_utc"),
        "run_id": reconciliation.get("run_id"),
        "target_date": reconciliation.get("target_date"),
        "status": reconciliation.get("status"),
        "live_fill_count": len(fills),
        "live_fill_size": numeric_sum(fills, "fill_size"),
        "live_notional_usdc": round(sum(
            (maybe_float(row.get("fill_price")) or 0.0) * (maybe_float(row.get("fill_size")) or 0.0)
            for row in fills
        ), 6),
        "live_cancellation_count": sum(1 for row in reconciliation.get("user_stream_lifecycle_events") or [] if row.get("transition") == "canceled"),
        "live_rejection_count": sum(1 for row in reconciliation.get("user_stream_lifecycle_events") or [] if row.get("transition") == "rejected"),
        "paper_counterfactual_quote_count": len(paper_quote_rows),
        "paper_counterfactual_expected_rebate_value": expected_rebate,
        "paper_counterfactual_expected_reward_score": expected_reward_score,
        "actual_reward_rebate_usdc": actual_reward,
        "reward_rebate_delta_usdc": None if actual_reward is None else round(actual_reward - expected_rebate, 6),
        "markout_30m_count": len(markout_values),
        "markout_30m_mean": None if not markout_values else round(sum(markout_values) / len(markout_values), 6),
        "probe_status": probe_status,
        "paper_counterfactual_available": bool(paper_quote_rows),
        "reward_rebate_reconciled": actual_reward is not None,
        "financial_reconciliation": financial,
        "financial_reconciliation_complete": financial.get("complete"),
        "markout_reconciled": bool(markout_values),
    }
    missing = []
    if not fills:
        missing.append("live_fills")
    if not paper_quote_rows:
        missing.append("paper_counterfactual_quotes")
    if actual_reward is None:
        missing.append("actual_reward_rebate")
    if not markout_values:
        missing.append("markout_30m")
    missing.extend(f"financial:{item}" for item in financial.get("missing_evidence") or [])
    payload["missing_evidence"] = missing
    payload["evidence_complete"] = not missing
    return payload


def render_pilot_report(payload):
    lines = [
        "# MM-2 Pilot Report",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Run: `{payload.get('run_id')}`",
        f"Status: `{payload.get('status')}`",
        f"Evidence complete: `{str(payload.get('evidence_complete')).lower()}`",
        "",
        "## Live Execution",
        "",
        f"- Fill count: `{payload.get('live_fill_count')}`",
        f"- Fill size: `{payload.get('live_fill_size')}`",
        f"- Fill notional: `{payload.get('live_notional_usdc')}`",
        f"- Cancellations: `{payload.get('live_cancellation_count')}`",
        f"- Rejections: `{payload.get('live_rejection_count')}`",
        "",
        "## Paper Counterfactual",
        "",
        f"- Quote rows: `{payload.get('paper_counterfactual_quote_count')}`",
        f"- Expected rebate value: `{payload.get('paper_counterfactual_expected_rebate_value')}`",
        f"- Expected reward score: `{payload.get('paper_counterfactual_expected_reward_score')}`",
        "",
        "## Reconciliation",
        "",
        f"- Actual reward/rebate: `{payload.get('actual_reward_rebate_usdc')}`",
        f"- Reward/rebate delta: `{payload.get('reward_rebate_delta_usdc')}`",
        f"- 30m markout mean: `{payload.get('markout_30m_mean')}`",
        f"- Missing evidence: `{', '.join(payload.get('missing_evidence') or []) or '-'}`",
        "",
        "## Financial Reconciliation",
        "",
        f"- Complete: `{str(payload.get('financial_reconciliation_complete')).lower()}`",
        f"- Actual fees: `{(payload.get('financial_reconciliation') or {}).get('actual_fees_usdc')}`",
        f"- Redemption: `{(payload.get('financial_reconciliation') or {}).get('redemption_usdc')}`",
        f"- Settlement P&L: `{(payload.get('financial_reconciliation') or {}).get('settlement_pnl_usdc')}`",
        f"- Balance delta: `{(payload.get('financial_reconciliation') or {}).get('balance_delta_usdc')}`",
        f"- Actual total P&L after fees/incentives: `{(payload.get('financial_reconciliation') or {}).get('actual_total_pnl_after_fees_incentives_usdc')}`",
    ]
    return "\n".join(lines) + "\n"


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
    lifecycle_events, fill_rows = lifecycle_events_from_user_events(user_events, now)
    balances = adapter.balances()
    allowances = adapter.allowances()
    positions = adapter.positions()
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
