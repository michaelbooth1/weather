"""Read-only daily reward capture using a caller-qualified authentication context.

Only GET /rewards/user is supported. No SDK, credential discovery, wallet setup,
retries, redirects, sessions, order operations or payment inference occurs here.
"""

from __future__ import annotations

import base64
from datetime import date, datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import ssl
import time
from urllib.parse import urlencode

from weather.market.exchange_economics_sources import (
    MAX_RESPONSE_BYTES,
    MAX_TOTAL_RESPONSE_BYTES,
    json_response_payload,
)
from weather.market.mm_liquidity_earnings_evidence import (
    ADDRESS_RE,
    MAX_PAGES,
    PAGE_LIMIT,
    TERMINAL_CURSOR,
    normalize_liquidity_earnings_pages,
)
from weather.schema_registry import schema_version

SCHEMA_VERSION = schema_version("mm_liquidity_earnings_capture")
HOST = "clob.polymarket.com"
ENDPOINT = "/rewards/user"
MAX_CAPTURE_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 10
AUTH_HEADER_NAMES = frozenset({
    "POLY_ADDRESS", "POLY_API_KEY", "POLY_PASSPHRASE", "POLY_SIGNATURE", "POLY_TIMESTAMP",
})
SECRET_HEADER_NAMES = AUTH_HEADER_NAMES - {"POLY_ADDRESS", "POLY_TIMESTAMP"}
ATTRIBUTION_GAPS = (
    "authoritative_earned_period_condition_asset_to_distribution",
    "distribution_to_confirmed_transaction_log",
    "payout_cycle_finality",
    "whole_account_cash_completeness",
)


def _now():
    return datetime.now(timezone.utc)


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("capture clock must return an aware datetime")
    return value.astimezone(timezone.utc)


def _address(value):
    if not isinstance(value, str) or ADDRESS_RE.fullmatch(value) is None:
        raise ValueError("capture requires an explicit EVM address")
    return value.lower()


def _scope(query_date, maker_address, signer_address, signature_type, sponsored, now):
    if not isinstance(query_date, str) or len(query_date) != 10:
        raise ValueError("capture date must be an ISO calendar date")
    day = date.fromisoformat(query_date)
    if day.isoformat() != query_date or day > now.date():
        raise ValueError("capture date is invalid or in the future")
    maker, signer = _address(maker_address), _address(signer_address)
    if type(signature_type) is not int or signature_type not in {0, 1, 2}:
        raise ValueError("capture signature type is unsupported")
    if type(sponsored) is not bool:
        raise ValueError("capture sponsored scope must be boolean")
    if signature_type == 0 and maker != signer:
        raise ValueError("EOA maker and signer must match")
    return {
        "query_date": query_date, "maker_address": maker, "signer_address": signer,
        "signature_type": signature_type, "sponsored": sponsored,
    }


def _headers(provider, scope, query):
    # Callback exceptions and secret values must never enter the receipt.
    supplied = provider("GET", ENDPOINT, dict(query))
    if not isinstance(supplied, dict) or set(supplied) != AUTH_HEADER_NAMES:
        raise ValueError("invalid authentication headers")
    headers = dict(supplied)
    if any(not isinstance(value, str) or not 1 <= len(value) <= 4096
           or any(ord(char) < 33 or ord(char) > 126 for char in value)
           for value in headers.values()):
        raise ValueError("invalid authentication headers")
    if _address(headers["POLY_ADDRESS"]) != scope["signer_address"]:
        raise ValueError("authentication signer differs from declared signer")
    return headers


def _write_new(path, payload):
    body = (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    return {"file": path.name, "sha256": hashlib.sha256(body).hexdigest()}


def _response(body, url, status, content_type, observed):
    return {
        "url": url, "request_method": "GET", "http_status": status,
        "content_type": content_type, "response_bytes": len(body),
        "response_sha256": hashlib.sha256(body).hexdigest(),
        "response_body_base64": base64.b64encode(body).decode("ascii"),
        "retrieved_at_utc": observed.isoformat(), "response_origin": "http_response_bytes",
    }


def _read_request(query, scope, headers_provider, remaining_bytes, deadline, clock, monotonic):
    path = ENDPOINT + "?" + urlencode(query)
    url = "https://" + HOST + path
    started = _utc(clock())
    record = {
        "schema_version": SCHEMA_VERSION, "kind": "request",
        "request_started_at_utc": started.isoformat(),
        "request": {"method": "GET", "url": url},
        "auth_header_names": sorted(AUTH_HEADER_NAMES),
        "cursor_in": query.get("next_cursor"), "cursor_out": None,
        "body_complete": False, "network_request_attempted": False,
        "error": None, "response": None,
    }
    body, status, content_type, connection, headers = bytearray(), None, "", None, {}
    limit = min(MAX_RESPONSE_BYTES, remaining_bytes)
    stage = "authentication_failed"
    try:
        headers = _headers(headers_provider, scope, query)
        stage = "transport_failed"
        remaining = deadline - monotonic()
        if remaining <= 0:
            record["error"] = "capture_deadline_exceeded"
        else:
            connection = http.client.HTTPSConnection(
                HOST, timeout=min(REQUEST_TIMEOUT_SECONDS, remaining),
                context=ssl.create_default_context(),
            )
            headers.update({"Accept": "application/json", "Accept-Encoding": "identity"})
            record["network_request_attempted"] = True
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            status = response.status
            content_type = response.getheader("Content-Type", "")[:256]
            encoding = response.getheader("Content-Encoding", "identity")
            declared = response.getheader("Content-Length")
            if declared is not None and (not declared.isascii() or not declared.isdecimal()
                                         or len(declared) > 20):
                record["error"] = "invalid_content_length"
            else:
                while record["error"] is None:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        record["error"] = "capture_deadline_exceeded"
                        break
                    if connection.sock is not None:
                        connection.sock.settimeout(min(REQUEST_TIMEOUT_SECONDS, remaining))
                    chunk = response.read1(min(65536, limit - len(body) + 1))
                    if not chunk:
                        record["body_complete"] = True
                        break
                    body.extend(chunk)
                    if len(body) > limit:
                        del body[limit:]
                        record["error"] = "response_byte_budget_exceeded"
                if record["body_complete"] and declared is not None and int(declared) != len(body):
                    record["body_complete"] = False
                    record["error"] = "incomplete_response_body"
            if record["error"] is None and monotonic() > deadline:
                record["error"] = "capture_deadline_exceeded"
            if record["error"] is None and not record["body_complete"]:
                record["error"] = "incomplete_response_body"
            if record["error"] is None and status != 200:
                record["error"] = "http_status_not_success"
            if record["error"] is None and encoding.lower().strip() not in {"", "identity"}:
                record["error"] = "encoded_response_unsupported"
            if record["error"] is None and content_type.split(";", 1)[0].strip().lower() != "application/json":
                record["error"] = "response_content_type_not_json"
    except Exception:
        record["error"] = stage
    finally:
        if connection is not None:
            connection.close()
    observed = _utc(clock())
    record["request_finished_at_utc"] = observed.isoformat()
    # Preserve failure bytes too, unless a server echoes an authentication secret.
    # Such an attempt is unusable; never persist the secret to retain a body.
    secrets = [headers[key] for key in SECRET_HEADER_NAMES if headers.get(key)]
    if any(secret.encode() in body or json.dumps(secret)[1:-1].encode() in body
           or secret in content_type for secret in secrets):
        record["error"] = "response_contains_authentication_secret"
        record["body_complete"] = False
        record["response_body_withheld"] = True
    else:
        record["response"] = _response(bytes(body), url, status, content_type, observed)
    return record


def capture_liquidity_earnings(
    *, query_date, maker_address, signer_address, signature_type, headers_provider,
    output_dir, sponsored=False, clock=_now, monotonic=time.monotonic,
):
    """Capture one exact account/date into a new absolute attempt directory.

    The caller must qualify the signer/maker/signature-type association and
    supply existing L2 headers via provider(method, endpoint_path, query).
    The callback owns authentication signing semantics; it must not provision
    credentials or mutate a wallet. Header values and exception messages are
    never persisted. Incomplete attempts retain available raw response prefixes.
    A complete capture remains accrual evidence, never a paid-cash result.
    """
    started = _utc(clock())
    scope = _scope(query_date, maker_address, signer_address, signature_type, sponsored, started)
    if not callable(headers_provider):
        raise ValueError("capture requires a qualified authentication callback")
    root = Path(output_dir)
    if not root.is_absolute():
        raise ValueError("capture output directory must be absolute")
    root.mkdir(parents=True, exist_ok=False)
    _write_new(root / "intent.json", {
        "schema_version": SCHEMA_VERSION, "kind": "intent", "scope": scope,
        "started_at_utc": started.isoformat(), "max_pages": MAX_PAGES,
        "max_response_bytes": MAX_RESPONSE_BYTES, "max_total_bytes": MAX_TOTAL_RESPONSE_BYTES,
        "max_capture_seconds": MAX_CAPTURE_SECONDS,
    })
    deadline = monotonic() + MAX_CAPTURE_SECONDS
    result = {
        "schema_version": SCHEMA_VERSION, "kind": "capture", "scope": scope,
        "started_at_utc": started.isoformat(), "status": "INCOMPLETE",
        "error": None, "pagination_complete": False, "requests": [], "earnings": None,
        "request_count": 0, "network_request_count": 0,
        "payment_verified": False, "paid_incentive_amount": None,
        "accrual_linkage_verified": False, "account_cash_completeness_verified": False,
        "source_authenticity_verified": False, "identity_binding_verified": False,
        "attribution_status": "ATTRIBUTION_BLOCKED", "missing_evidence": list(ATTRIBUTION_GAPS),
        "live_authority": False,
    }
    query = {
        "date": query_date, "signature_type": str(signature_type),
        "maker_address": scope["maker_address"], "sponsored": "true" if sponsored else "false",
    }
    pages, cursors, total_bytes = [], set(), 0
    for sequence in range(1, MAX_PAGES + 1):
        if total_bytes >= MAX_TOTAL_RESPONSE_BYTES or monotonic() >= deadline:
            result["error"] = "capture_budget_exhausted"
            break
        record = _read_request(
            query, scope, headers_provider, MAX_TOTAL_RESPONSE_BYTES - total_bytes,
            deadline, clock, monotonic,
        )
        record["sequence"] = sequence
        result["network_request_count"] += int(record["network_request_attempted"])
        evidence = record["response"]
        if evidence is not None:
            total_bytes += evidence["response_bytes"]
        if record["error"] is None:
            try:
                payload = json_response_payload(base64.b64decode(evidence["response_body_base64"]))
                rows, count, limit = payload.get("data"), payload.get("count"), payload.get("limit")
                cursor = payload.get("next_cursor")
                if (not isinstance(rows, list) or type(count) is not int
                        or type(limit) is not int or not 1 <= limit <= PAGE_LIMIT
                        or count != len(rows) or not 0 <= count <= limit
                        or not isinstance(cursor, str) or not 1 <= len(cursor) <= 512
                        or any(ord(char) < 33 or ord(char) > 126 for char in cursor)
                        or cursor != TERMINAL_CURSOR and (not rows or cursor in cursors)
                        or "error" in payload or "errors" in payload):
                    raise ValueError
                record["cursor_out"] = cursor
                cursors.add(cursor)
                pages.append(evidence)
            except (ValueError, AttributeError, TypeError):
                record["error"] = "invalid_earnings_page"
        result["requests"].append(_write_new(root / f"request-{sequence:03d}.json", record))
        result["request_count"] = sequence
        if record["error"] is not None:
            result["error"] = record["error"]
            break
        if cursor == TERMINAL_CURSOR:
            try:
                normalized = normalize_liquidity_earnings_pages(
                    pages, query_date=query_date, maker_address=scope["maker_address"],
                    signature_type=signature_type, sponsored=sponsored,
                    as_of_utc=_utc(clock()).isoformat(),
                )
                result["earnings"] = {key: value for key, value in normalized.items() if key != "pages"}
                result["status"] = "COMPLETE"
                result["pagination_complete"] = True
            except ValueError:
                result["error"] = "earnings_scope_or_evidence_invalid"
            break
        query["next_cursor"] = cursor
    else:
        result["error"] = "page_budget_exhausted"
    result["finished_at_utc"] = _utc(clock()).isoformat()
    result["retained_response_bytes"] = total_bytes
    _write_new(root / "capture.json", result)
    return result
