"""Validate supplied daily liquidity-earnings pages without claiming payment.

No network, credential resolution, SDK construction or report mutation occurs
here. Complete raw pages prove their internal scope and pagination only.
"""

from __future__ import annotations

import base64
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import json
import re
from urllib.parse import parse_qs, urlsplit

from weather.market.exchange_economics_sources import (
    MAX_TOTAL_RESPONSE_BYTES,
    response_evidence_valid,
)
from weather.schema_registry import schema_version

SCHEMA_VERSION = schema_version("mm_liquidity_earnings_evidence")
MAX_PAGES = 50
PAGE_LIMIT = 100
TERMINAL_CURSOR = "LTE="
ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}\Z")
CONDITION_RE = re.compile(r"0x[0-9a-fA-F]{64}\Z")
RAW_FIELDS = (
    "url", "request_method", "http_status", "content_type", "response_bytes",
    "response_sha256", "response_body_base64", "retrieved_at_utc", "response_origin",
)


def _address(value, label):
    if not isinstance(value, str) or ADDRESS_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be an EVM address")
    return value.lower()


def _day(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("query date must be an ISO calendar date")
    try:
        result = date.fromisoformat(value)
    except ValueError:
        raise ValueError("query date must be an ISO calendar date") from None
    if result.isoformat() != value:
        raise ValueError("query date must be an ISO calendar date")
    return result


def _utc(value):
    try:
        if not isinstance(value, str) or len(value) > 40:
            raise ValueError
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("evidence requires an aware timestamp") from None


def _decimal(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("earnings values must be exact finite nonnegative numbers")
    text = str(value)
    if len(text) > 128:
        raise ValueError("earnings number exceeds its precision budget")
    try:
        number = Decimal(text)
        if not number.is_finite() or number < 0 or number > Decimal("1e18"):
            raise ValueError
        if number.as_tuple().exponent < -18 or number.as_tuple().exponent > 18:
            raise ValueError
    except (ValueError, InvalidOperation):
        raise ValueError("earnings number is outside supported bounds") from None
    return number


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("earnings response contains duplicate JSON keys")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("earnings response contains a nonfinite number")


def _payload(body):
    try:
        value = json.loads(
            body.decode("utf-8-sig"), object_pairs_hook=_unique_pairs,
            parse_float=Decimal, parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, InvalidOperation):
        raise ValueError("earnings response is not valid bounded JSON") from None
    if not isinstance(value, dict):
        raise ValueError("earnings response must be an object")
    if "error" in value or "errors" in value:
        raise ValueError("earnings response contains an error envelope")
    return value


def _request(evidence, *, query_date, maker, signature_type, sponsored, cursor):
    try:
        url = urlsplit(evidence["url"])
        query = parse_qs(url.query, keep_blank_values=True, strict_parsing=True)
    except (ValueError, TypeError):
        raise ValueError("earnings request URL is invalid") from None
    if (url.scheme != "https" or url.netloc != "clob.polymarket.com"
            or url.path != "/rewards/user" or url.fragment):
        raise ValueError("earnings request must use the exact official endpoint")
    expected = {"date": [query_date], "signature_type": [str(signature_type)]}
    if cursor is not None:
        expected["next_cursor"] = [cursor]
    if "maker_address" in query:
        expected["maker_address"] = [maker]
    if sponsored or "sponsored" in query:
        expected["sponsored"] = ["true" if sponsored else "false"]
    if query != expected:
        raise ValueError("earnings request differs from its exact expected scope")


def _row(raw, *, query_day, maker, page_index, row_index, response_hash):
    if not isinstance(raw, dict):
        raise ValueError("earnings rows must be objects")
    condition = raw.get("condition_id")
    if not isinstance(condition, str) or CONDITION_RE.fullmatch(condition) is None:
        raise ValueError("earnings condition identity is invalid")
    row_maker = _address(raw.get("maker_address"), "row maker")
    if row_maker != maker:
        raise ValueError("earnings row belongs to another maker")
    source_date = raw.get("date")
    if source_date == query_day.isoformat():
        row_day = query_day
    else:
        instant = _utc(source_date)
        if any((instant.hour, instant.minute, instant.second, instant.microsecond)):
            raise ValueError("earnings date is not a UTC calendar boundary")
        row_day = instant.date()
    if row_day != query_day:
        raise ValueError("earnings row belongs to another date")
    amount = _decimal(raw.get("earnings"))
    rate = _decimal(raw.get("asset_rate"))
    asset = _address(raw.get("asset_address"), "earnings asset")
    return {
        "query_date": query_day.isoformat(), "source_date": source_date,
        "condition_id": condition.lower(), "maker_address": row_maker,
        "asset_address": asset, "earnings": format(amount, "f"),
        "asset_rate": format(rate, "f"), "page_index": page_index,
        "row_index": row_index, "response_sha256": response_hash,
    }


def normalize_liquidity_earnings_pages(
    pages, *, query_date, maker_address, signature_type, as_of_utc,
    sponsored=False, max_age_seconds=3600,
):
    """Validate a complete supplied sequence; raise instead of inventing zero.

    The required clock/freshness scope applies to response retrieval, not payout
    finality. Historical dates remain accrual observations, never paid income.
    Signature type 3 is refused until the earnings interface documents it.
    """
    query_day = _day(query_date)
    maker = _address(maker_address, "expected maker")
    as_of = _utc(as_of_utc)
    if query_day > as_of.date():
        raise ValueError("earnings query date is in the future")
    if type(signature_type) is not int or signature_type not in {0, 1, 2}:
        raise ValueError("earnings signature type is unsupported")
    if type(sponsored) is not bool:
        raise ValueError("sponsored scope must be an explicit boolean")
    if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 86400:
        raise ValueError("freshness budget must be 1 to 86400 seconds")
    if not isinstance(pages, (list, tuple)) or not 1 <= len(pages) <= MAX_PAGES:
        raise ValueError("earnings evidence requires 1 to 50 complete pages")

    records, retained, seen, cursors, totals = [], [], set(), set(), {}
    cursor, previous_time, total_bytes = None, None, 0
    for page_index, evidence in enumerate(pages):
        if not response_evidence_valid(evidence, require_body=True):
            raise ValueError("earnings page lacks valid raw response evidence")
        if evidence["content_type"].split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("earnings page content type is not JSON")
        _request(
            evidence, query_date=query_date, maker=maker,
            signature_type=signature_type, sponsored=sponsored, cursor=cursor,
        )
        retrieved = _utc(evidence["retrieved_at_utc"])
        age = (as_of - retrieved).total_seconds()
        if age < 0 or age > max_age_seconds or (
            previous_time is not None and retrieved < previous_time
        ):
            raise ValueError("earnings retrieval times are future, stale or unordered")
        previous_time = retrieved
        total_bytes += evidence["response_bytes"]
        if total_bytes > MAX_TOTAL_RESPONSE_BYTES:
            raise ValueError("earnings evidence exceeds the total raw-byte budget")
        payload = _payload(base64.b64decode(evidence["response_body_base64"], validate=True))
        rows, count, limit = payload.get("data"), payload.get("count"), payload.get("limit")
        if (not isinstance(rows, list) or type(count) is not int
                or type(limit) is not int or not 1 <= limit <= PAGE_LIMIT
                or count != len(rows) or not 0 <= count <= limit):
            raise ValueError("earnings page data/count/limit is inconsistent")
        next_cursor = payload.get("next_cursor")
        if (not isinstance(next_cursor, str) or not 1 <= len(next_cursor) <= 512
                or any(ord(char) < 33 or ord(char) > 126 for char in next_cursor)):
            raise ValueError("earnings page omits a valid cursor")
        terminal = next_cursor == TERMINAL_CURSOR
        if terminal != (page_index == len(pages) - 1):
            raise ValueError("earnings pages must end exactly at the terminal cursor")
        if not terminal and (not rows or next_cursor in cursors):
            raise ValueError("earnings pages contain an empty page or cursor cycle")
        cursors.add(next_cursor)
        for row_index, raw in enumerate(rows):
            record = _row(
                raw, query_day=query_day, maker=maker, page_index=page_index,
                row_index=row_index, response_hash=evidence["response_sha256"],
            )
            identity = (record["condition_id"], record["asset_address"])
            if identity in seen:
                raise ValueError("earnings contain duplicate condition/asset identity")
            seen.add(identity)
            records.append(record)
            asset = record["asset_address"]
            with localcontext() as context:
                context.prec = 60
                totals[asset] = totals.get(asset, Decimal(0)) + Decimal(record["earnings"])
        retained.append({field: evidence[field] for field in RAW_FIELDS})
        cursor = next_cursor

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ACCRUAL_OBSERVED" if records else "COMPLETE_EMPTY_SCOPE",
        "query_date": query_date, "maker_address": maker,
        "signature_type": signature_type, "sponsored": sponsored,
        "as_of_utc": as_of.isoformat(), "max_age_seconds": max_age_seconds,
        "pagination_complete": True, "terminal_cursor": TERMINAL_CURSOR,
        "page_count": len(retained), "row_count": len(records),
        "source_authenticity_verified": False, "payment_verified": False,
        "accrual_finality_verified": False, "accrual_linkage_verified": False,
        "account_cash_completeness_verified": False,
        "paid_incentive_amount": None,
        "earnings_by_asset": {key: format(value, "f") for key, value in sorted(totals.items())},
        "rows": records, "pages": retained,
    }
