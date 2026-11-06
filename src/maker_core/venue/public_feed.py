"""Credential-free, GET-only public reads of International Polymarket.

Four reads exist: a CLOB order book by asset, the CLOB reward record of one
condition, Gamma events by slug, and the public data-api trade prints of one
condition (``/v2/trades?condition=``; never a ``user`` filter). There is no order, cancel, signing,
account, heartbeat or authenticated route here, and no reader takes a
credential. Polymarket US hosts, redirects, ambient proxies, query strings
outside the allowlist and oversized replies are refused.
Contract: docs/operations/maker-shadow-runner.md.
"""
import json
import math
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

CLOB_HOST = "clob.polymarket.com"
GAMMA_HOST = "gamma-api.polymarket.com"
DATA_HOST = "data-api.polymarket.com"
TRADES_LIMIT = 500
TRADES_FILTER_AMOUNT = "0.01"
MAX_TRADES_PAGES = 20
MAX_CURSOR_LENGTH = 4096
MAX_REPLY_BYTES = 2_000_000
MAX_SLUGS = 20
CONDITION = re.compile(r"0x[0-9a-f]{64}\Z")
ASSET = re.compile(r"[0-9]{1,100}\Z")
SLUG = re.compile(r"[a-z0-9-]{1,200}\Z")


def book_url(asset_id):
    return f"https://{CLOB_HOST}/book?" + urlencode({"token_id": str(asset_id)})


def rewards_url(condition_id):
    return f"https://{CLOB_HOST}/rewards/markets/{condition_id}"


def events_url(slugs):
    return f"https://{GAMMA_HOST}/events?" + urlencode([("slug", s) for s in sorted(slugs)])


def trades_url(condition_id, cursor=None):
    query = [("condition", condition_id), ("limit", TRADES_LIMIT), ("taker_only", "true"),
             ("filter_type", "TOKENS"), ("filter_amount", TRADES_FILTER_AMOUNT)]
    if cursor is not None:
        query.append(("cursor", cursor))
    return f"https://{DATA_HOST}/v2/trades?" + urlencode(query)


def public_url(url):
    """Return ``url`` unchanged when it is one of the four allowlisted reads, else raise."""
    try:
        parts = urlsplit(url)
        query = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True) if parts.query else []
        clean = (parts.scheme == "https" and parts.username is None and parts.password is None
                 and parts.port is None and not parts.fragment and parts.netloc == parts.hostname)
    except ValueError:
        clean = False
    if clean and parts.hostname == CLOB_HOST:
        if (parts.path == "/book" and len(query) == 1 and query[0][0] == "token_id"
                and ASSET.fullmatch(query[0][1])):
            return url
        prefix = "/rewards/markets/"
        if parts.path.startswith(prefix) and CONDITION.fullmatch(parts.path[len(prefix):]) and not query:
            return url
    if (clean and parts.hostname == GAMMA_HOST and parts.path == "/events" and 0 < len(query) <= MAX_SLUGS
            and all(key == "slug" and SLUG.fullmatch(value) for key, value in query)):
        return url
    if (clean and parts.hostname == DATA_HOST and parts.path == "/v2/trades" and len(query) in (5, 6)
            and query[0][0] == "condition" and CONDITION.fullmatch(query[0][1])
            and query[1:5] == [("limit", str(TRADES_LIMIT)), ("taker_only", "true"),
                               ("filter_type", "TOKENS"), ("filter_amount", TRADES_FILTER_AMOUNT)]
            and (len(query) == 5 or (query[5][0] == "cursor" and 0 < len(query[5][1]) <= MAX_CURSOR_LENGTH
                                    and all(32 < ord(c) < 127 for c in query[5][1])))):
        return url
    raise ValueError("not_an_allowlisted_public_read")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class UrllibTransport:
    """The only network path: one bounded GET without proxy, redirect or credential."""

    def __init__(self, *, timeout=5.0, opener=None):
        self.timeout = timeout
        self.opener = opener or build_opener(ProxyHandler({}), _NoRedirect())
        self.requests = 0

    def get(self, url):
        url = public_url(url)
        request = Request(url, method="GET", headers={"User-Agent": "Mozilla/5.0 weather-maker-shadow/0.1",
                                                      "Accept": "application/json"})
        if request.get_method() != "GET":
            raise ValueError("public_read_must_be_get")
        self.requests += 1
        with self.opener.open(request, timeout=self.timeout) as response:
            raw = response.read(MAX_REPLY_BYTES + 1)
            if response.status != 200 or response.geturl() != url or len(raw) > MAX_REPLY_BYTES:
                raise ValueError("public_read_refused")
            return raw


class FixtureTransport:
    """No-network mode: serves recorded replies by exact allowlisted URL; anything else is refused."""

    def __init__(self, replies):
        self.replies = {public_url(url): value for url, value in dict(replies).items()}
        self.requests = []

    def get(self, url):
        url = public_url(url)
        self.requests.append(url)
        if url not in self.replies:
            raise LookupError("fixture_reply_missing")
        value = self.replies[url]
        return value if isinstance(value, bytes) else json.dumps(value).encode("utf-8")


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("trades_duplicate_json_field")
        result[key] = value
    return result


def _invalid_json_constant(value):
    raise ValueError("trades_non_json_numeric_constant")


class PublicFeed:
    """Parsed public reads over an injected transport. It has no mutation method by construction."""

    def __init__(self, transport):
        if not callable(getattr(transport, "get", None)):
            raise TypeError("public_transport_required")
        self.transport = transport

    def _json(self, url):
        return json.loads(self.transport.get(url))

    def book(self, asset_id):
        if not ASSET.fullmatch(str(asset_id)):
            raise ValueError("invalid_asset_id")
        value = self._json(book_url(asset_id))
        if not isinstance(value, dict) or str(value.get("asset_id")) != str(asset_id):
            raise ValueError("book_asset_mismatch")
        return value

    def reward_terms(self, condition_id):
        """The single current CLOB reward record of the condition, or None when it has none."""
        condition_id = str(condition_id).lower()
        if not CONDITION.fullmatch(condition_id):
            raise ValueError("invalid_condition_id")
        value = self._json(rewards_url(condition_id))
        rows = value.get("data") if isinstance(value, dict) else None
        if not isinstance(rows, list) or len(rows) > 1:
            raise ValueError("reward_reply_refused")
        if rows and str(rows[0].get("condition_id", "")).lower() != condition_id:
            raise ValueError("reward_condition_mismatch")
        return rows[0] if rows else None

    def trades(self, condition_id):
        """Complete served trade feed of one condition, within page and aggregate byte budgets."""
        condition_id = str(condition_id).lower()
        if not CONDITION.fullmatch(condition_id):
            raise ValueError("invalid_condition_id")
        rows, seen, cursor, total_bytes = [], set(), None, 0
        for _ in range(MAX_TRADES_PAGES):
            raw = self.transport.get(trades_url(condition_id, cursor))
            if not isinstance(raw, bytes):
                raise ValueError("trades_reply_refused")
            total_bytes += len(raw)
            if total_bytes > MAX_REPLY_BYTES:
                raise ValueError("trades_reply_bytes_exhausted")
            value = json.loads(raw, object_pairs_hook=_unique_json_object, parse_constant=_invalid_json_constant)
            if (not isinstance(value, dict) or value.get("error") is not None
                    or not isinstance(value.get("data"), list)):
                raise ValueError("trades_reply_refused")
            page, pagination = value["data"], value.get("pagination")
            if not isinstance(pagination, dict) or type(pagination.get("has_more")) is not bool:
                raise ValueError("trades_pagination_refused")
            if "next_cursor" not in pagination or len(page) > TRADES_LIMIT:
                raise ValueError("trades_pagination_refused")
            for row in page:
                if not isinstance(row, dict):
                    raise ValueError("trades_row_refused")
                # v2 wire fields -> the existing PublicReads / paper / recorder interface.
                if (not isinstance(row.get("condition_id"), str)
                        or row["condition_id"].lower() != condition_id
                        or not isinstance(row.get("token_id"), str)
                        or not ASSET.fullmatch(row["token_id"])
                        or not isinstance(row.get("transaction_hash"), str)
                        or not row["transaction_hash"]
                        or row.get("side") not in ("BUY", "SELL")
                        or type(row.get("timestamp")) is not int or row["timestamp"] <= 0):
                    raise ValueError("trades_row_refused")
                try:
                    datetime.fromtimestamp(row["timestamp"], tz=timezone.utc)
                except (OverflowError, OSError, ValueError) as exc:
                    raise ValueError("trades_timestamp_refused") from exc
                for field in ("size", "price"):
                    number = row.get(field)
                    try:
                        invalid = type(number) not in (int, float) or not math.isfinite(number)
                    except OverflowError:
                        invalid = True
                    if invalid:
                        raise ValueError("trades_numeric_field_refused")
                if row["size"] <= 0 or not 0 <= row["price"] <= 1:
                    raise ValueError("trades_numeric_field_refused")
                rows.append(dict(row, conditionId=condition_id, asset=row["token_id"],
                                 transactionHash=row["transaction_hash"]))
            cursor = pagination["next_cursor"]
            if not pagination["has_more"]:
                if cursor is not None:
                    raise ValueError("trades_pagination_refused")
                return rows
            if (not isinstance(cursor, str) or not 0 < len(cursor) <= MAX_CURSOR_LENGTH
                    or cursor in seen or not page or not all(32 < ord(c) < 127 for c in cursor)):
                raise ValueError("trades_cursor_refused")
            seen.add(cursor)
        raise ValueError("trades_page_budget_exhausted")

    def events(self, slugs):
        slugs = sorted(set(slugs))
        if not 0 < len(slugs) <= MAX_SLUGS:
            raise ValueError("slug_batch_out_of_bounds")
        value = self._json(events_url(slugs))
        if not isinstance(value, list) or any(not isinstance(row, dict) or row.get("slug") not in slugs
                                              for row in value):
            raise ValueError("events_reply_refused")
        return value


__all__ = ["CLOB_HOST", "GAMMA_HOST", "FixtureTransport", "PublicFeed", "UrllibTransport",
           "book_url", "events_url", "public_url", "rewards_url", "trades_url"]
