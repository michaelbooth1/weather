"""Bounded public-response evidence and current-reward page validation.

This is the exchange-economics collector's source boundary, not account or
payment evidence. Historical hash-only snapshots remain readable.
"""

from __future__ import annotations

import base64
import binascii
from datetime import date, datetime, timezone
import hashlib
import json
import math
import re


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_RESPONSE_BYTES = 16 * 1024 * 1024
RESPONSE_BODY_FIELDS = frozenset({
    "response_body_base64", "retrieved_at_utc", "response_origin", "request_method",
})
CONDITION_RE = re.compile(r"0x[0-9a-fA-F]{64}\Z")
ASSET_RE = re.compile(r"0x[0-9a-fA-F]{40}\Z")


def _unique_json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("exchange economics source contains duplicate JSON keys")
        result[key] = value
    return result


def _invalid_json_constant(value):
    raise ValueError("exchange economics source contains a nonfinite JSON number")


def _finite_json_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("exchange economics source contains a nonfinite JSON number")
    return number


def json_response_payload(body):
    if not isinstance(body, bytes) or len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("exchange economics source exceeded size limit")
    try:
        return json.loads(
            body.decode("utf-8-sig"), object_pairs_hook=_unique_json_pairs,
            parse_constant=_invalid_json_constant, parse_float=_finite_json_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("exchange economics source returned invalid JSON") from exc


def response_evidence(body, *, url, http_status, content_type, origin):
    """Retain exact response bytes; caller-generated JSON is labelled separately."""
    if not isinstance(body, bytes) or len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("exchange economics source exceeded size limit")
    return {
        "url": url, "request_method": "GET", "http_status": http_status, "content_type": content_type,
        "response_bytes": len(body),
        "response_sha256": hashlib.sha256(body).hexdigest(),
        "response_body_base64": base64.b64encode(body).decode("ascii"),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "response_origin": origin,
    }


def response_evidence_valid(evidence, *, require_body=False):
    """Validate additive raw evidence without upgrading legacy hash-only rows."""
    if not isinstance(evidence, dict):
        return False
    if not require_body and not RESPONSE_BODY_FIELDS.intersection(evidence):
        return True
    try:
        if not RESPONSE_BODY_FIELDS.issubset(evidence):
            return False
        encoded = evidence["response_body_base64"]
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_RESPONSE_BYTES + 2) // 3):
            return False
        body = base64.b64decode(encoded, validate=True)
        observed = datetime.fromisoformat(evidence["retrieved_at_utc"].replace("Z", "+00:00"))
        return all((
            observed.tzinfo is not None and observed.utcoffset() is not None,
            evidence["response_origin"] in {"http_response_bytes", "caller_supplied_canonical_json", "caller_supplied_text"},
            evidence.get("request_method") == "GET",
            isinstance(evidence.get("url"), str) and bool(evidence["url"].strip()),
            type(evidence.get("http_status")) is int and evidence["http_status"] == 200,
            isinstance(evidence.get("content_type"), str),
            base64.b64encode(body).decode("ascii") == encoded,
            len(body) <= MAX_RESPONSE_BYTES,
            type(evidence.get("response_bytes")) is int,
            evidence.get("response_bytes") == len(body),
            evidence.get("response_sha256") == hashlib.sha256(body).hexdigest(),
        ))
    except (ValueError, TypeError, AttributeError, binascii.Error):
        return False


def response_payload_matches(evidence, payload, *, text=False):
    """Check newly supplied parsed results against complete captured bytes."""
    if not response_evidence_valid(evidence, require_body=True):
        return False
    try:
        body = base64.b64decode(evidence["response_body_base64"], validate=True)
        if text:
            return body.decode("utf-8-sig") == payload
        observed = json_response_payload(body)
        return json.dumps(observed, sort_keys=True, allow_nan=False) == json.dumps(
            payload, sort_keys=True, allow_nan=False,
        )
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return False


def check_response_budget(evidence):
    """Bound one snapshot's retained bodies before base64/JSON amplification."""
    sizes = [row.get("response_bytes", 0) for row in evidence]
    if any(type(size) is not int or size < 0 for size in sizes):
        raise ValueError("exchange economics response size metadata is invalid")
    if sum(sizes) > MAX_TOTAL_RESPONSE_BYTES:
        raise ValueError("exchange economics captured responses exceeded total size limit")


def _nonnegative_number(value):
    try:
        return type(value) in {int, float} and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _calendar_date(value):
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def current_reward_page(payload, *, page_limit, seen_conditions):
    """Reject incomplete pages and duplicate conditions before projecting rows.

    The documented terminal cursor is LTE=. An empty nonterminal page, repeated
    condition or missing required page field cannot establish campaign absence.
    ``seen_conditions`` belongs to one bounded pagination attempt only.
    """
    if not isinstance(payload, dict) or "error" in payload or not {"data", "count", "limit", "next_cursor"} <= payload.keys():
        raise ValueError("current rewards response is missing required page fields")
    rows, count, limit, cursor = (payload[key] for key in ("data", "count", "limit", "next_cursor"))
    if (
        not isinstance(rows, list) or type(count) is not int or type(limit) is not int
        or not 1 <= limit <= page_limit or count != len(rows) or not 0 <= count <= limit
        or not isinstance(cursor, str) or not cursor or cursor != cursor.strip()
        or len(cursor) > 4096 or cursor == "-1"
    ):
        raise ValueError("current rewards response has invalid page metadata")
    if not rows and cursor != "LTE=":
        raise ValueError("current rewards empty page lacks terminal cursor")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("current rewards row is not an object")
        condition = row.get("condition_id")
        if not isinstance(condition, str) or not CONDITION_RE.fullmatch(condition):
            raise ValueError("current rewards condition identity is invalid")
        condition = condition.lower()
        if condition in seen_conditions:
            raise ValueError("current rewards response repeats a condition")
        seen_conditions.add(condition)
        if not all(_nonnegative_number(row.get(key)) for key in (
            "rewards_min_size", "rewards_max_spread", "total_daily_rate",
        )) or not isinstance(row.get("rewards_config"), list):
            raise ValueError("current rewards row economics are incomplete or invalid")
        seen_allocations = set()
        for config in row["rewards_config"]:
            if (
                not isinstance(config, dict)
                or type(config.get("id")) is not int or config["id"] < 0
                or not isinstance(config.get("asset_address"), str)
                or not ASSET_RE.fullmatch(config["asset_address"])
                or not _calendar_date(config.get("start_date"))
                or not _calendar_date(config.get("end_date"))
                or config["start_date"] > config["end_date"]
                or not _nonnegative_number(config.get("rate_per_day"))
                or not _nonnegative_number(config.get("total_rewards"))
            ):
                raise ValueError("current rewards allocation is incomplete or invalid")
            key = (config["id"], config["asset_address"].lower())
            if key in seen_allocations:
                raise ValueError("current rewards response repeats an allocation")
            seen_allocations.add(key)
    return rows, cursor
