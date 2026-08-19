"""Small audited protocol gaps around the official International SDK.

The unified ``polymarket-client`` owns authenticated trading.  This module is
limited to public, read-only preflight requests and the CLOB dead-man
heartbeat, which the SDK does not currently expose.  It deliberately does not
provide a generic authenticated transport.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import re
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
from urllib.request import Request, urlopen


CLOB_HOST = "https://clob.polymarket.com"
RELAYER_HOST = "https://relayer-v2.polymarket.com"
HEARTBEAT_PATH = "/heartbeats"
EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
ALLOWED_TICK_SIZES = frozenset({
    Decimal("0.1"),
    Decimal("0.01"),
    Decimal("0.005"),
    Decimal("0.0025"),
    Decimal("0.001"),
    Decimal("0.0001"),
})
MAX_PROTOCOL_RESPONSE_BYTES = 1_000_000


def build_l2_hmac_signature(*, secret, timestamp, method, path, body=None):
    """Mirror the official SDK's documented L2 HMAC algorithm."""

    method_text = str(method or "").upper()
    path_text = str(path or "")
    if not method_text or not path_text.startswith("/"):
        raise ValueError("method and absolute request path are required")
    try:
        timestamp_value = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise ValueError("timestamp must be an integer") from exc
    message = f"{timestamp_value}{method_text}{path_text}"
    if body is not None:
        message += str(body)
    secret_text = str(secret or "")
    try:
        padded = secret_text + ("=" * ((-len(secret_text)) % 4))
        raw_secret = base64.urlsafe_b64decode(padded)
        if not raw_secret:
            raise ValueError("decoded secret is empty")
        digest = hmac.new(
            raw_secret,
            message.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    except (binascii.Error, TypeError, ValueError) as exc:
        raise RuntimeError("failed to compute the CLOB L2 signature") from exc
    return base64.urlsafe_b64encode(digest).decode("ascii")


def _read_json_response(response, *, label):
    try:
        status = getattr(response, "status", None)
        if status is None and hasattr(response, "getcode"):
            status = response.getcode()
        status = 200 if status is None else int(status)
        raw = response.read(MAX_PROTOCOL_RESPONSE_BYTES + 1)
    finally:
        close = getattr(response, "close", None)
        if close is not None:
            close()
    if status != 200:
        raise RuntimeError(f"{label} returned HTTP {status}")
    if len(raw) > MAX_PROTOCOL_RESPONSE_BYTES:
        raise RuntimeError(f"{label} exceeded the response safety limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} returned a non-object response")
    return payload


def _open_json(request, *, opener, timeout_seconds, label):
    timeout = float(timeout_seconds)
    if not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValueError("protocol timeout must be finite and in (0, 60] seconds")
    response = (opener or urlopen)(request, timeout=timeout)
    return _read_json_response(response, label=label)


def fetch_wallet_deployed(
    wallet_address,
    signature_type_id,
    *,
    opener=None,
    timeout_seconds=15.0,
):
    """Prove an existing Safe/deposit wallet without triggering deployment."""

    wallet = str(wallet_address or "").strip()
    if EVM_ADDRESS_RE.fullmatch(wallet) is None:
        raise ValueError("wallet_address must be a 20-byte EVM address")
    try:
        signature_type = int(signature_type_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("signature_type_id must be 2 or 3") from exc
    relayer_type = {2: "SAFE", 3: "WALLET"}.get(signature_type)
    if relayer_type is None:
        raise ValueError("signature_type_id must be 2 or 3")
    query = urlencode({"address": wallet, "type": relayer_type})
    request = Request(
        f"{RELAYER_HOST}/deployed?{query}",
        headers={"Accept": "application/json", "User-Agent": "weather-mm-live-probe/1"},
    )
    payload = _open_json(
        request,
        opener=opener,
        timeout_seconds=timeout_seconds,
        label="wallet deployment endpoint",
    )
    deployed = payload.get("deployed")
    if not isinstance(deployed, bool):
        raise RuntimeError("wallet deployment endpoint omitted a boolean deployed value")
    return deployed


def fetch_market_rule_endpoints(token_id, *, opener=None, timeout_seconds=15.0):
    """Cross-check the public rule endpoints omitted from the SDK API."""

    token = str(token_id or "").strip()
    if not token or len(token) > 256:
        raise ValueError("token_id must be a bounded nonempty string")
    query = urlencode({"token_id": token})
    observations = {}
    for label, path in (
        ("tick", "/tick-size"),
        ("neg_risk", "/neg-risk"),
        ("fee", "/fee-rate"),
    ):
        request = Request(
            f"{CLOB_HOST}{path}?{query}",
            headers={"Accept": "application/json", "User-Agent": "weather-mm-live-probe/1"},
        )
        observations[label] = _open_json(
            request,
            opener=opener,
            timeout_seconds=timeout_seconds,
            label=f"CLOB {path} endpoint",
        )

    try:
        tick_size = Decimal(str(observations["tick"].get("minimum_tick_size")))
        fee_rate_bps = Decimal(str(observations["fee"].get("base_fee")))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RuntimeError("market-rule endpoint returned a nonnumeric value") from exc
    neg_risk = observations["neg_risk"].get("neg_risk")
    if tick_size not in ALLOWED_TICK_SIZES:
        raise RuntimeError("market-rule endpoint returned an unsupported tick size")
    if not isinstance(neg_risk, bool):
        raise RuntimeError("market-rule endpoint omitted a boolean neg-risk value")
    if not fee_rate_bps.is_finite() or fee_rate_bps < 0:
        raise RuntimeError("market-rule endpoint returned an invalid fee rate")
    return {
        "token_id": token,
        "tick_size": tick_size,
        "neg_risk": neg_risk,
        "fee_rate_bps": fee_rate_bps,
    }


class OfficialHeartbeatSender:
    """One-purpose authenticated sender for ``POST /heartbeats`` only."""

    def __init__(
        self,
        *,
        signer_address,
        api_key,
        api_secret,
        api_passphrase,
        opener=None,
        clock=None,
        timeout_seconds=15.0,
    ):
        signer = str(signer_address or "").strip()
        if EVM_ADDRESS_RE.fullmatch(signer) is None:
            raise ValueError("signer_address must be a 20-byte EVM address")
        credentials = (str(api_key or ""), str(api_secret or ""), str(api_passphrase or ""))
        if not all(credentials):
            raise ValueError("complete API credentials are required")
        self._signer_address = signer
        self._api_key, self._api_secret, self._api_passphrase = credentials
        self._opener = opener
        self._clock = clock or time.time
        self._timeout_seconds = float(timeout_seconds)

    def __repr__(self):
        return "OfficialHeartbeatSender(credentials=<redacted>)"

    def send(self):
        timestamp = int(self._clock())
        signature = build_l2_hmac_signature(
            secret=self._api_secret,
            timestamp=timestamp,
            method="POST",
            path=HEARTBEAT_PATH,
            body=None,
        )
        request = Request(
            f"{CLOB_HOST}{HEARTBEAT_PATH}",
            data=b"",
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "POLY_ADDRESS": self._signer_address,
                "POLY_API_KEY": self._api_key,
                "POLY_PASSPHRASE": self._api_passphrase,
                "POLY_SIGNATURE": signature,
                "POLY_TIMESTAMP": str(timestamp),
                "User-Agent": "weather-mm-live-probe/1",
            },
        )
        payload = _open_json(
            request,
            opener=self._opener,
            timeout_seconds=self._timeout_seconds,
            label="CLOB heartbeat endpoint",
        )
        if payload != {"status": "ok"}:
            raise RuntimeError("CLOB heartbeat did not return the exact success acknowledgment")
        return {"status": "ok"}


__all__ = [
    "CLOB_HOST",
    "HEARTBEAT_PATH",
    "OfficialHeartbeatSender",
    "build_l2_hmac_signature",
    "fetch_market_rule_endpoints",
    "fetch_wallet_deployed",
]
