"""Official International Polymarket CLOB adapter boundary.

The adapter accepts an already-authenticated official SDK client. Secret
resolution and client construction deliberately stay outside this module so
private material never needs to enter repository config, command arguments, or
diagnostic artifacts.
"""

from __future__ import annotations

import math
import json
import hashlib
import re
import time
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from importlib import metadata
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from weather.market.market_making_run_constants import MAX_OPERATOR_PILOT_BUDGET_USDC
from weather.market.mm_policy import bool_value
from weather.market.mm_geoblock import (
    collect_official_geoblock_evidence,
    geoblock_evidence_gate,
)


OFFICIAL_CLOB_DISTRIBUTION = "polymarket-client"
OFFICIAL_CLOB_VERSION = "0.6.0"
MAX_STAGE1_ORDER_NOTIONAL = Decimal("10")
CURRENT_REBATES_URL = "https://clob.polymarket.com/rebates/current"
CURRENT_POSITIONS_URL = "https://data-api.polymarket.com/positions"
EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
EVM_SIGNATURE_RE = re.compile(r"^0x[0-9a-fA-F]{130}$")
CONDITION_ID_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NORMALIZED_USER_EVENT_FIELDS = frozenset({
    "clob_token_id",
    "condition_id",
    "event_type",
    "exchange_last_update",
    "exchange_match_time",
    "exchange_timestamp",
    "fee_rate_bps",
    "fill_price",
    "fill_size",
    "lifecycle_key",
    "liquidity_role",
    "maker_address",
    "official_event_type",
    "official_order_status",
    "official_order_transition",
    "official_trade_status",
    "order_id",
    "original_size",
    "outcome",
    "price",
    "raw_event_sha256",
    "side",
    "size_matched",
    "source",
    "trade_id",
    "transaction_hash",
})


def _official_event_hash(raw):
    encoded = json.dumps(
        raw,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def exact_current_positions_evidence(
    evidence,
    *,
    maker_address,
    condition_id,
    rows=None,
):
    """Validate the complete official maker/condition positions request."""

    if not isinstance(evidence, dict):
        return False
    maker = str(maker_address or "").strip().lower()
    condition = str(condition_id or "").strip().lower()
    try:
        parsed = urlsplit(str(evidence.get("request_url") or ""))
        query = parse_qs(parsed.query, keep_blank_values=True)
    except (TypeError, ValueError):
        return False
    expected_query = {
        "user": [maker],
        "market": [condition],
        "sizeThreshold": ["0"],
        "limit": ["500"],
        "offset": ["0"],
    }
    observed_query = {
        key: [str(value).lower() for value in values]
        for key, values in query.items()
    }
    expected_query = {
        key: [str(value).lower() for value in values]
        for key, values in expected_query.items()
    }
    return all((
        EVM_ADDRESS_RE.fullmatch(maker) is not None,
        CONDITION_ID_RE.fullmatch(condition) is not None,
        evidence.get("status") == "OBSERVED",
        evidence.get("query_scope") == "exact_maker_condition",
        str(evidence.get("maker_address") or "").lower() == maker,
        str(evidence.get("condition_id") or "").lower() == condition,
        evidence.get("http_status") == 200,
        SHA256_RE.fullmatch(str(evidence.get("response_sha256") or "")) is not None,
        isinstance(evidence.get("rows"), list),
        rows is None or evidence.get("rows") == rows,
        parsed.scheme.lower() == "https",
        parsed.netloc.lower() == "data-api.polymarket.com",
        parsed.path == "/positions",
        not parsed.fragment,
        observed_query == expected_query,
    ))


def _validated_normalized_official_user_event(
    row,
    *,
    maker_address,
    condition_id,
    token_id,
):
    """Validate the allowlisted output of ``OfficialUserStreamReader``."""

    if not isinstance(row, dict) or row.get("source") != "polymarket_global_user_ws":
        raise RuntimeError("official normalized user event has an invalid source")
    unexpected = set(row) - NORMALIZED_USER_EVENT_FIELDS
    if unexpected:
        raise RuntimeError("official normalized user event contains non-allowlisted fields")
    if str(row.get("maker_address") or "").lower() != str(maker_address or "").lower():
        raise RuntimeError("official normalized user event is outside the pilot maker scope")
    if str(row.get("condition_id") or "").lower() != str(condition_id or "").lower():
        raise RuntimeError("official normalized user event is outside the pilot condition scope")
    if str(row.get("clob_token_id") or "") != str(token_id or ""):
        raise RuntimeError("official normalized user event is outside the pilot token scope")
    if not SHA256_RE.fullmatch(str(row.get("raw_event_sha256") or "")):
        raise RuntimeError("official normalized user event has no raw-event proof hash")
    order_id = str(row.get("order_id") or "").strip()
    if not order_id or str(row.get("lifecycle_key") or "") != order_id:
        raise RuntimeError("official normalized user event has invalid order identity")

    event_type = str(row.get("event_type") or "").lower()
    official_type = str(row.get("official_event_type") or "").lower()
    if official_type == "order":
        expected_event = {
            "PLACEMENT": "order",
            "UPDATE": "order",
            "CANCELLATION": "canceled",
        }.get(str(row.get("official_order_transition") or "").upper())
        if event_type != expected_event:
            raise RuntimeError("official normalized order event has inconsistent lifecycle state")
    elif official_type == "trade":
        trade_status = str(row.get("official_trade_status") or "").upper()
        expected_event = (
            "trade" if trade_status == "CONFIRMED"
            else "rejected" if trade_status == "FAILED"
            else "trade_pending" if trade_status in {"MATCHED", "MINED", "RETRYING"}
            else None
        )
        if event_type != expected_event:
            raise RuntimeError("official normalized trade event has inconsistent lifecycle state")
        if str(row.get("liquidity_role") or "").upper() not in {"MAKER", "TAKER"}:
            raise RuntimeError("official normalized trade event has invalid liquidity role")
        if not str(row.get("trade_id") or "").strip():
            raise RuntimeError("official normalized trade event has no trade id")
        if event_type == "trade" and not str(row.get("transaction_hash") or "").strip():
            raise RuntimeError("confirmed official trade has no transaction hash")
    else:
        raise RuntimeError("official normalized user event has an invalid event type")
    return dict(row)


def normalize_official_user_event(
    raw,
    *,
    maker_address,
    condition_id,
    token_id,
):
    """Normalize one exact-scope International user event into order-local rows."""

    if not isinstance(raw, dict):
        raise RuntimeError("official user stream returned a non-object event")
    event_type = str(raw.get("event_type") or "").strip().lower()
    if event_type not in {"order", "trade"}:
        raise RuntimeError("official user stream returned an unknown event type")
    observed_condition = str(raw.get("market") or "").strip().lower()
    observed_token = str(raw.get("asset_id") or "").strip()
    if observed_condition != str(condition_id or "").lower() or observed_token != str(token_id or ""):
        raise RuntimeError("official user event is outside the pilot condition/token scope")
    expected_maker = str(maker_address or "").strip().lower()
    observed_maker = str(raw.get("maker_address") or "").strip().lower()
    raw_event_sha256 = _official_event_hash(raw)

    if event_type == "order":
        if observed_maker != expected_maker:
            raise RuntimeError("official order event is outside the pilot maker scope")
        order_id = str(raw.get("id") or "").strip()
        if not order_id:
            raise RuntimeError("official order event has no order id")
        order_transition = str(raw.get("type") or "").strip().upper()
        normalized_type = {
            "PLACEMENT": "order",
            "UPDATE": "order",
            "CANCELLATION": "canceled",
        }.get(order_transition)
        if normalized_type is None:
            raise RuntimeError("official order event has an unknown transition")
        return [{
            "event_type": normalized_type,
            "official_event_type": "order",
            "official_order_transition": order_transition,
            "official_order_status": raw.get("status"),
            "lifecycle_key": order_id,
            "order_id": order_id,
            "maker_address": expected_maker,
            "condition_id": observed_condition,
            "clob_token_id": observed_token,
            "side": raw.get("side"),
            "price": raw.get("price"),
            "original_size": raw.get("original_size"),
            "size_matched": raw.get("size_matched"),
            "outcome": raw.get("outcome"),
            "exchange_timestamp": raw.get("timestamp") or raw.get("created_at"),
            "raw_event_sha256": raw_event_sha256,
            "source": "polymarket_global_user_ws",
        }]

    trade_id = str(raw.get("id") or "").strip()
    trade_status = str(raw.get("status") or "").strip().upper()
    if not trade_id or trade_status not in {
        "MATCHED",
        "MINED",
        "CONFIRMED",
        "RETRYING",
        "FAILED",
    }:
        raise RuntimeError("official trade event has an invalid id or lifecycle status")
    normalized_type = (
        "trade" if trade_status == "CONFIRMED"
        else "rejected" if trade_status == "FAILED"
        else "trade_pending"
    )
    liquidity_role = str(raw.get("trader_side") or "").strip().upper()
    common = {
        "event_type": normalized_type,
        "official_event_type": "trade",
        "official_trade_status": trade_status,
        "trade_id": trade_id,
        "condition_id": observed_condition,
        "clob_token_id": observed_token,
        "transaction_hash": raw.get("transaction_hash"),
        "liquidity_role": liquidity_role,
        "maker_address": expected_maker,
        "outcome": raw.get("outcome"),
        "exchange_timestamp": raw.get("timestamp"),
        "exchange_match_time": raw.get("match_time") or raw.get("matchtime"),
        "exchange_last_update": raw.get("last_update"),
        "raw_event_sha256": raw_event_sha256,
        "source": "polymarket_global_user_ws",
    }
    if liquidity_role == "TAKER":
        if observed_maker != expected_maker:
            raise RuntimeError("official taker trade event is outside the pilot maker scope")
        order_id = str(raw.get("taker_order_id") or "").strip()
        if not order_id:
            raise RuntimeError("official taker trade event has no taker order id")
        return [{
            **common,
            "lifecycle_key": order_id,
            "order_id": order_id,
            "side": raw.get("side"),
            "fill_price": raw.get("price"),
            "fill_size": raw.get("size"),
            "fee_rate_bps": raw.get("fee_rate_bps"),
        }]
    if liquidity_role != "MAKER":
        raise RuntimeError("official trade event has an unknown liquidity role")

    maker_rows = [
        row
        for row in raw.get("maker_orders") or []
        if isinstance(row, dict)
        and str(row.get("maker_address") or "").lower() == expected_maker
        and str(row.get("asset_id") or "") == observed_token
    ]
    if not maker_rows:
        raise RuntimeError("official maker trade event does not identify the pilot maker order")
    normalized = []
    for maker_row in maker_rows:
        order_id = str(maker_row.get("order_id") or "").strip()
        if not order_id:
            raise RuntimeError("official maker trade row has no order id")
        normalized.append({
            **common,
            "lifecycle_key": order_id,
            "order_id": order_id,
            "side": maker_row.get("side"),
            "fill_price": maker_row.get("price"),
            "fill_size": maker_row.get("matched_amount"),
            "fee_rate_bps": maker_row.get("fee_rate_bps"),
        })
    return normalized


def fetch_current_maker_rebates(
    maker_address,
    rebate_date,
    *,
    opener=None,
    timeout_seconds=15.0,
    return_evidence=False,
    now=None,
):
    """Read the official public per-condition maker-rebate endpoint."""

    maker_text = str(maker_address or "").strip()
    if not EVM_ADDRESS_RE.fullmatch(maker_text):
        raise ValueError("maker_address must be a 20-byte EVM address")
    date_text = str(rebate_date or "").strip()
    try:
        parsed_date = date.fromisoformat(date_text)
    except ValueError as exc:
        raise ValueError("rebate_date must use YYYY-MM-DD") from exc
    if parsed_date.isoformat() != date_text:
        raise ValueError("rebate_date must use canonical YYYY-MM-DD")
    query = urlencode({"date": date_text, "maker_address": maker_text})
    request = Request(
        f"{CURRENT_REBATES_URL}?{query}",
        headers={"Accept": "application/json", "User-Agent": "weather-mm-live-probe/1"},
    )
    response = (opener or urlopen)(request, timeout=float(timeout_seconds))
    try:
        status = getattr(response, "status", None)
        if status is None and hasattr(response, "getcode"):
            status = response.getcode()
        status = 200 if status is None else int(status)
        raw = response.read()
    finally:
        close = getattr(response, "close", None)
        if close is not None:
            close()
    if status != 200:
        raise RuntimeError(f"maker-rebate endpoint returned HTTP {status}")
    if len(raw) > 5_000_000:
        raise RuntimeError("maker-rebate response exceeded the 5 MB safety limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("maker-rebate endpoint returned invalid JSON") from exc
    if not isinstance(payload, list):
        raise RuntimeError("maker-rebate endpoint did not return a list")
    normalized = []
    for row in payload:
        if not isinstance(row, dict):
            raise RuntimeError("maker-rebate response contains a non-object row")
        row_date = str(row.get("date") or "")
        row_maker = str(row.get("maker_address") or "")
        condition_id = str(row.get("condition_id") or "")
        asset_address = str(row.get("asset_address") or "")
        try:
            amount = Decimal(str(row.get("rebated_fees_usdc")))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise RuntimeError("maker-rebate row amount is not numeric") from exc
        if row_date != date_text or row_maker.lower() != maker_text.lower():
            raise RuntimeError("maker-rebate row scope does not match the request")
        if not CONDITION_ID_RE.fullmatch(condition_id):
            raise RuntimeError("maker-rebate row condition_id is invalid")
        if not EVM_ADDRESS_RE.fullmatch(asset_address):
            raise RuntimeError("maker-rebate row asset_address is invalid")
        if not amount.is_finite() or amount < 0:
            raise RuntimeError("maker-rebate row amount must be finite and nonnegative")
        normalized.append({
            "date": row_date,
            "condition_id": condition_id.lower(),
            "asset_address": asset_address.lower(),
            "maker_address": row_maker.lower(),
            "rebated_fees_usdc": str(amount),
        })
    if return_evidence:
        observed_at = now
        if observed_at is None:
            observed_at = datetime.now(timezone.utc)
        elif isinstance(observed_at, str):
            observed_at = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        return {
            "status": "OBSERVED",
            "query_scope": "exact_maker_date",
            "query_date": date_text,
            "maker_address": maker_text.lower(),
            "request_url": request.full_url,
            "http_status": status,
            "queried_at_utc": observed_at.astimezone(timezone.utc).isoformat(),
            "response_sha256": hashlib.sha256(raw).hexdigest(),
            "rows": normalized,
        }
    return normalized


def fetch_current_positions(
    maker_address,
    condition_id,
    *,
    opener=None,
    timeout_seconds=15.0,
):
    """Read and content-bind the exact maker/condition current-position query."""

    maker_text = str(maker_address or "").strip()
    condition_text = str(condition_id or "").strip().lower()
    if not EVM_ADDRESS_RE.fullmatch(maker_text):
        raise ValueError("maker_address must be a 20-byte EVM address")
    if not CONDITION_ID_RE.fullmatch(condition_text):
        raise ValueError("condition_id must be a 32-byte condition identifier")
    query = urlencode({
        "user": maker_text,
        "market": condition_text,
        "sizeThreshold": 0,
        "limit": 500,
        "offset": 0,
    })
    request = Request(
        f"{CURRENT_POSITIONS_URL}?{query}",
        headers={"Accept": "application/json", "User-Agent": "weather-mm-live-probe/1"},
    )
    response = (opener or urlopen)(request, timeout=float(timeout_seconds))
    try:
        status = getattr(response, "status", None)
        if status is None and hasattr(response, "getcode"):
            status = response.getcode()
        status = 200 if status is None else int(status)
        raw = response.read()
    finally:
        close = getattr(response, "close", None)
        if close is not None:
            close()
    if status != 200:
        raise RuntimeError(f"current-position endpoint returned HTTP {status}")
    if len(raw) > 5_000_000:
        raise RuntimeError("current-position response exceeded the 5 MB safety limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("current-position endpoint returned invalid JSON") from exc
    if not isinstance(payload, list):
        raise RuntimeError("current-position endpoint did not return a list")
    rows = []
    for row in payload:
        if not isinstance(row, dict):
            raise RuntimeError("current-position response contains a non-object row")
        observed_maker = str(row.get("proxyWallet") or "").strip().lower()
        observed_condition = str(row.get("conditionId") or "").strip().lower()
        asset = str(row.get("asset") or "").strip()
        try:
            size = Decimal(str(row.get("size")))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise RuntimeError("current-position row size is not numeric") from exc
        if observed_maker != maker_text.lower() or observed_condition != condition_text:
            raise RuntimeError("current-position row scope does not match the exact query")
        if not asset or not size.is_finite() or size < 0:
            raise RuntimeError("current-position row has invalid asset or size")
        rows.append({
            "proxyWallet": observed_maker,
            "conditionId": observed_condition,
            "asset": asset,
            "size": str(size),
            "avgPrice": row.get("avgPrice"),
            "currentValue": row.get("currentValue"),
            "cashPnl": row.get("cashPnl"),
            "realizedPnl": row.get("realizedPnl"),
            "redeemable": row.get("redeemable"),
            "mergeable": row.get("mergeable"),
        })
    return {
        "status": "OBSERVED",
        "query_scope": "exact_maker_condition",
        "maker_address": maker_text.lower(),
        "condition_id": condition_text,
        "request_url": request.full_url,
        "http_status": status,
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "row_count": len(rows),
        "rows": rows,
    }


def installed_official_clob_version():
    try:
        return metadata.version(OFFICIAL_CLOB_DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return None


def require_official_clob_version(version=None):
    installed = version if version is not None else installed_official_clob_version()
    if installed != OFFICIAL_CLOB_VERSION:
        observed = installed or "not installed"
        raise RuntimeError(
            f"{OFFICIAL_CLOB_DISTRIBUTION}=={OFFICIAL_CLOB_VERSION} is required; "
            f"observed {observed}"
        )
    return installed


def _required_number(value, label):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be finite and greater than zero")
    return number


def _required_decimal(value, label):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{label} must be finite and greater than zero")
    return number


def _nonnegative_decimal(value, label):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{label} must be finite and nonnegative")
    return number


def _required_utc_datetime(value, label):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _value(payload, *names):
    for name in names:
        if isinstance(payload, dict):
            value = payload.get(name)
        else:
            value = getattr(payload, name, None)
        if value is not None and value != "":
            return value
    return None


def _plain_sdk_value(value):
    """Normalize typed SDK models without retaining private client state."""

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json", by_alias=False)
    if isinstance(value, dict):
        return {key: _plain_sdk_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_sdk_value(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    return value


def _paginator_items(paginator):
    iterator = getattr(paginator, "iter_items", None)
    if not callable(iterator):
        raise RuntimeError("official SDK did not return the required paginator")
    return [_plain_sdk_value(item) for item in iterator()]


def _level_prices(levels):
    prices = []
    for level in levels or []:
        raw = _value(level, "price")
        try:
            price = Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if price.is_finite() and 0 < price < 1:
            prices.append(price)
    return prices


class OfficialPolymarketGlobalAdapter:
    """Protocol adapter around the pinned unified official CLOB client.

    Trading remains disabled unless callers also supply authoritative user
    events and position readers. This prevents an authenticated REST client
    from being mistaken for a reconciliation-complete live implementation.
    """

    adapter_id = "polymarket_global_official_clob"

    def __init__(
        self,
        client,
        *,
        token_id=None,
        user_event_reader=None,
        user_event_health_reader=None,
        position_reader=None,
        redemption_reader=None,
        rebate_reader=None,
        rebate_date=None,
        maker_address=None,
        condition_id=None,
        rebate_payout_cycle_complete=False,
        heartbeat_sender=None,
        market_rule_reader=None,
        sdk_version=None,
        authoritative_readers_verified=False,
        monotonic_clock=None,
        utc_clock=None,
        sleeper=None,
        heartbeat_max_age_seconds=7.5,
        market_rules_max_age_seconds=10.0,
        max_order_notional=10.0,
        cancel_verify_attempts=20,
        cancel_verify_interval_seconds=0.25,
        geoblock_checker=None,
    ):
        self.sdk_version = require_official_clob_version(sdk_version)
        self.client = client
        self.token_id = str(token_id or "").strip() or None
        self.user_event_reader = user_event_reader
        self.user_event_health_reader = user_event_health_reader
        self.position_reader = position_reader
        self.redemption_reader = redemption_reader
        self.rebate_reader = rebate_reader
        self.rebate_date = str(rebate_date or "").strip() or None
        self.maker_address = str(maker_address or "").strip() or None
        self.condition_id = str(condition_id or "").strip().lower() or None
        self.rebate_payout_cycle_complete = bool(rebate_payout_cycle_complete)
        self.heartbeat_sender = heartbeat_sender
        self.market_rule_reader = market_rule_reader
        self.authoritative_readers_verified = bool(authoritative_readers_verified)
        self.monotonic_clock = monotonic_clock or time.monotonic
        self.utc_clock = utc_clock or (lambda: datetime.now(timezone.utc))
        self.sleeper = sleeper or time.sleep
        self.heartbeat_max_age_seconds = _required_number(
            heartbeat_max_age_seconds,
            "heartbeat_max_age_seconds",
        )
        self.market_rules_max_age_seconds = _required_number(
            market_rules_max_age_seconds,
            "market_rules_max_age_seconds",
        )
        requested_max_order_notional = _required_decimal(
            max_order_notional,
            "max_order_notional",
        )
        self.max_order_notional = min(
            requested_max_order_notional,
            MAX_STAGE1_ORDER_NOTIONAL,
        )
        self.cancel_verify_attempts = max(1, int(cancel_verify_attempts))
        self.cancel_verify_interval_seconds = max(
            0.0,
            float(cancel_verify_interval_seconds),
        )
        self.geoblock_checker = geoblock_checker or collect_official_geoblock_evidence
        self.supports_trading = bool(
            self.token_id
            and user_event_reader
            and user_event_health_reader
            and position_reader
            and heartbeat_sender
            and market_rule_reader
            and EVM_ADDRESS_RE.fullmatch(self.maker_address or "")
            and CONDITION_ID_RE.fullmatch(self.condition_id or "")
            and self.authoritative_readers_verified
        )
        self._balance_allowance = None
        self._last_position_evidence = None
        self._heartbeat_acknowledgment_count = 0
        self._last_heartbeat_monotonic = None
        self._market_rules = None
        self._stage1_capability = None
        self._stage1_capability_consumed = False
        self._stage1_authorization_sha256 = None
        self._stage1_geoblock_country = None
        self._stage1_geoblock_region = None
        self._stage1_signature_type_id = None
        self._stage2_capability = None
        self._stage2_capability_consumed = False
        self._stage2_authorization_sha256 = None
        self._stage2_geoblock_country = None
        self._stage2_geoblock_region = None
        self._stage2_signature_type_id = None
        self._stage2_max_order_notional = None
        self._stage2_expires_at_utc = None
        self._last_geoblock_gate = None
        self._probe = {
            "sdk_version_verified": True,
            "heartbeat_acknowledged": False,
            "cancel_all_requested": False,
            "cancel_all_zero_open_orders_verified": False,
            "post_only_forced": True,
        }

    def authorize_stage1_lifecycle(self, bootstrap_gate):
        """Issue one opaque, single-submit capability bound to observed Stage 0."""

        gate = dict(bootstrap_gate or {})
        checks = gate.get("checks")
        try:
            requested_budget = Decimal(str(gate.get("requested_budget_usdc")))
            wallet_cap = Decimal(str(gate.get("pilot_wallet_max_funding_usdc")))
        except (InvalidOperation, TypeError, ValueError):
            requested_budget = wallet_cap = None
        operator_cap = Decimal(str(MAX_OPERATOR_PILOT_BUDGET_USDC))
        binding = {
            "supports_trading": self.supports_trading,
            "required": gate.get("required") is True,
            "ok": gate.get("ok") is True,
            "schema": gate.get("schema_version") == "mm_platform_bootstrap_v0.2",
            "status": gate.get("status") == "PASS",
            "platform": gate.get("platform") == "polymarket_global",
            "settlement_unit": gate.get("settlement_unit") == "pUSD",
            "checks": (
                isinstance(checks, dict)
                and bool(checks)
                and all(value is True for value in checks.values())
            ),
            "missing": gate.get("missing") == [],
            "account_snapshot": len(str(gate.get("account_snapshot_sha256") or "")) == 64,
            "geoblock_evidence": len(str(gate.get("geoblock_evidence_sha256") or "")) == 64,
            "geoblock_country": bool(str(gate.get("geoblock_country") or "").strip()),
            "token": str(gate.get("token_id") or "") == str(self.token_id or ""),
            "condition": str(gate.get("condition_id") or "").lower()
            == str(self.condition_id or "").lower(),
            "maker": str(gate.get("funder_address") or "").lower()
            == str(self.maker_address or "").lower(),
            "sdk": str(gate.get("sdk_version") or "") == str(self.sdk_version or ""),
            "signature_type": gate.get("signature_type_id") in {0, 1, 2, 3},
            "wallet_cap": (
                wallet_cap is not None
                and wallet_cap.is_finite()
                and Decimal("0") < wallet_cap <= operator_cap
            ),
            "requested_budget": (
                requested_budget is not None
                and requested_budget.is_finite()
                and Decimal("0") < requested_budget <= operator_cap
                and wallet_cap is not None
                and requested_budget <= wallet_cap
            ),
        }
        missing = [name for name, valid in binding.items() if not valid]
        if missing:
            raise RuntimeError(
                "official adapter Stage 1 authorization failed: " + ", ".join(missing)
            )
        if self._stage1_capability is not None:
            raise RuntimeError("official adapter Stage 1 authorization is single-use per adapter")
        current_geo = self._require_current_geo_eligibility(
            expected_country=gate.get("geoblock_country"),
            expected_region=gate.get("geoblock_region"),
        )
        self._stage1_capability = object()
        self._stage1_capability_consumed = False
        self._stage1_authorization_sha256 = _official_event_hash(gate)
        self._stage1_geoblock_country = current_geo["country"]
        self._stage1_geoblock_region = current_geo["region"]
        self._stage1_signature_type_id = int(gate.get("signature_type_id"))
        self._probe.update({
            "stage1_capability_issued": True,
            "stage1_capability_consumed": False,
            "stage1_bootstrap_sha256": self._stage1_authorization_sha256,
            "stage1_geoblock_evidence_sha256": current_geo["evidence_sha256"],
        })
        return self._stage1_capability

    def authorize_stage2_maker_session(self, platform_gate, session_envelope):
        """Issue one opaque BUY-only submit capability from v0.4 evidence."""

        gate = dict(platform_gate or {})
        envelope = dict(session_envelope or {})
        checks = gate.get("checks")
        heartbeat = gate.get("dead_man_heartbeat") or {}
        try:
            budget = _required_decimal(
                envelope.get("session_budget_pusd"),
                "Stage 2 session budget",
            )
            order_cap = _required_decimal(
                envelope.get("max_order_notional_pusd"),
                "Stage 2 order cap",
            )
            event_cap = _required_decimal(
                envelope.get("max_event_notional_pusd"),
                "Stage 2 event cap",
            )
            daily_loss_cap = _required_decimal(
                envelope.get("max_daily_loss_pusd"),
                "Stage 2 daily-loss cap",
            )
            band_cap = _required_decimal(
                envelope.get("max_band_notional_pusd"),
                "Stage 2 band cap",
            )
            ttl = _required_decimal(
                envelope.get("quote_ttl_seconds"),
                "Stage 2 quote TTL",
            )
            verified_budget = _required_decimal(
                gate.get("requested_budget_usdc"),
                "verified pilot budget",
            )
            wallet_cap = _required_decimal(
                gate.get("pilot_wallet_max_funding_usdc"),
                "verified wallet cap",
            )
            daily_loss_before = _nonnegative_decimal(
                envelope.get("daily_loss_before_pusd"),
                "Stage 2 daily loss before",
            )
            event_notional_before = _nonnegative_decimal(
                envelope.get("event_notional_before_pusd"),
                "Stage 2 event notional before",
            )
            band_notional_before = _nonnegative_decimal(
                envelope.get("band_notional_before_pusd"),
                "Stage 2 band notional before",
            )
            heartbeat_count = _required_decimal(
                heartbeat.get("acknowledgment_count"),
                "verified heartbeat acknowledgment count",
            )
            heartbeat_cadence = _required_decimal(
                heartbeat.get("cadence_seconds"),
                "verified heartbeat cadence",
            )
            quote_expires_at = _required_utc_datetime(
                envelope.get("quote_expires_at_utc"),
                "Stage 2 quote expiry",
            )
            paper_expires_at = _required_utc_datetime(
                (envelope.get("paper_counterfactual") or {}).get(
                    "expires_at_utc"
                ),
                "Stage 2 paper expiry",
            )
            capture_expires_at = _required_utc_datetime(
                (envelope.get("public_execution_capture") or {}).get(
                    "expires_at_utc"
                ),
                "Stage 2 capture expiry",
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeError("official adapter Stage 2 numeric binding failed") from exc
        envelope_content = {
            key: value
            for key, value in envelope.items()
            if key != "envelope_sha256"
        }
        paper_binding = envelope.get("paper_counterfactual") or {}
        capture_binding = envelope.get("public_execution_capture") or {}
        expires_at = min(quote_expires_at, paper_expires_at, capture_expires_at)
        current_utc = self.utc_clock()
        if current_utc.tzinfo is None:
            current_utc = current_utc.replace(tzinfo=timezone.utc)
        current_utc = current_utc.astimezone(timezone.utc)
        binding = {
            "supports_trading": self.supports_trading,
            "required": gate.get("required") is True,
            "ok": gate.get("ok") is True,
            "schema": gate.get("schema_version") == "mm_platform_verification_v0.4",
            "status_checks": (
                isinstance(checks, dict)
                and bool(checks)
                and all(value is True for value in checks.values())
            ),
            "missing": gate.get("missing") == [],
            "artifact": SHA256_RE.fullmatch(
                str(gate.get("artifact_sha256") or "")
            ) is not None,
            "platform": gate.get("platform") == "polymarket_global",
            "settlement_unit": gate.get("settlement_unit") == "pUSD",
            "condition": str(gate.get("condition_id") or "").lower()
            == str(self.condition_id or "").lower()
            == str(envelope.get("condition_id") or "").lower(),
            "token": str(gate.get("token_id") or "")
            == str(self.token_id or "")
            == str(envelope.get("token_id") or ""),
            "maker": str(gate.get("funder_address") or "").lower()
            == str(self.maker_address or "").lower()
            == str(envelope.get("funder_address") or "").lower(),
            "sdk": (
                (gate.get("sdk_contract") or {}).get("distribution")
                == OFFICIAL_CLOB_DISTRIBUTION
                and (gate.get("sdk_contract") or {}).get("version")
                == self.sdk_version
                == OFFICIAL_CLOB_VERSION
                and (gate.get("sdk_contract") or {}).get("exact_version_verified")
                is True
            ),
            "stage1_bundle": SHA256_RE.fullmatch(
                str(gate.get("stage1_lifecycle_bundle_sha256") or "")
            ) is not None
            and envelope.get("stage1_lifecycle_bundle_sha256")
            == gate.get("stage1_lifecycle_bundle_sha256"),
            "platform_artifact_binding": envelope.get(
                "platform_verification_sha256"
            ) == gate.get("artifact_sha256"),
            "target": bool(str(gate.get("target_date") or ""))
            and str(envelope.get("target_date") or "")
            == str(gate.get("target_date") or ""),
            "heartbeat": all((
                heartbeat.get("endpoint") == "/heartbeats",
                heartbeat.get("endpoint_verified") is True,
                heartbeat.get("request_body_absent_verified") is True,
                heartbeat.get("two_acknowledgments_verified") is True,
                heartbeat_count >= Decimal("2"),
                heartbeat.get("acknowledgment_verified") is True,
                Decimal("0") < heartbeat_cadence <= Decimal("5"),
                heartbeat.get("stale_placement_disarm_verified") is True,
                heartbeat.get("automatic_cancel_verified") is True,
            )),
            "envelope_schema": (
                envelope.get("schema_version")
                == "mm_live_stage2_session_envelope_v0.1"
            ),
            "envelope_hash": (
                SHA256_RE.fullmatch(
                    str(envelope.get("envelope_sha256") or "")
                ) is not None
                and envelope.get("envelope_sha256")
                == _official_event_hash(envelope_content)
            ),
            "decision_hashes": all((
                SHA256_RE.fullmatch(
                    str(envelope.get("quote_decision_sha256") or "")
                ) is not None,
                SHA256_RE.fullmatch(
                    str(envelope.get("market_preflight_sha256") or "")
                ) is not None,
            )),
            "one_submit": envelope.get("max_network_submits") == 1,
            "post_only": envelope.get("post_only_required") is True,
            "buy_only": envelope.get("backed_buy_only") is True,
            "naked_sell": envelope.get("naked_sell_forbidden") is True,
            "non_raisable": envelope.get("risk_ceilings_non_raisable") is True,
            "budget": (
                budget <= verified_budget <= wallet_cap <= Decimal("100")
            ),
            "order_cap": (
                order_cap <= self.max_order_notional <= Decimal("10")
            ),
            "daily_loss_cap": daily_loss_cap <= Decimal("25"),
            "event_cap": event_cap <= Decimal("25"),
            "band_cap": band_cap <= Decimal("10"),
            "ttl": ttl <= Decimal("120"),
            "daily_loss_before": daily_loss_before < daily_loss_cap,
            "event_before": event_notional_before < event_cap,
            "band_before": band_notional_before < band_cap,
            "paper_binding": all((
                SHA256_RE.fullmatch(
                    str(paper_binding.get("artifact_sha256") or "")
                ) is not None,
                SHA256_RE.fullmatch(
                    str(paper_binding.get("quote_row_sha256") or "")
                ) is not None,
                bool(str(paper_binding.get("expires_at_utc") or "")),
            )),
            "capture_binding": all((
                SHA256_RE.fullmatch(
                    str(capture_binding.get("probe_receipt_sha256") or "")
                ) is not None,
                SHA256_RE.fullmatch(
                    str(capture_binding.get("live_status_sha256") or "")
                ) is not None,
                SHA256_RE.fullmatch(
                    str(capture_binding.get("market_day_status_sha256") or "")
                ) is not None,
                SHA256_RE.fullmatch(
                    str(capture_binding.get("seed_sha256") or "")
                ) is not None,
                bool(str(capture_binding.get("expires_at_utc") or "")),
            )),
            "evidence_current": current_utc < expires_at,
            "signature_type": gate.get("signature_type_id") in {2, 3},
        }
        missing = [name for name, valid in binding.items() if not valid]
        if missing:
            raise RuntimeError(
                "official adapter Stage 2 authorization failed: " + ", ".join(missing)
            )
        if self._stage1_capability is not None or self._stage2_capability is not None:
            raise RuntimeError("official adapter permits one authorization lane per instance")
        current_geo = self._require_current_geo_eligibility(
            expected_country=gate.get("geoblock_country"),
            expected_region=gate.get("geoblock_region"),
        )
        self._stage2_capability = object()
        self._stage2_capability_consumed = False
        self._stage2_authorization_sha256 = _official_event_hash(envelope)
        self._stage2_geoblock_country = current_geo["country"]
        self._stage2_geoblock_region = current_geo["region"]
        self._stage2_signature_type_id = int(gate.get("signature_type_id"))
        self._stage2_max_order_notional = min(
            order_cap,
            budget,
            daily_loss_cap - daily_loss_before,
            event_cap - event_notional_before,
            band_cap - band_notional_before,
        )
        self._stage2_expires_at_utc = expires_at
        self._probe.update({
            "stage2_capability_issued": True,
            "stage2_capability_consumed": False,
            "stage2_envelope_sha256": envelope["envelope_sha256"],
            "stage2_geoblock_evidence_sha256": current_geo["evidence_sha256"],
            "stage2_max_network_submits": 1,
            "stage2_backed_buy_only": True,
            "stage2_effective_order_notional_cap": str(
                self._stage2_max_order_notional
            ),
        })
        return self._stage2_capability

    def _require_current_geo_eligibility(self, *, expected_country=None, expected_region=None):
        """Fetch and validate current physical eligibility without retaining an IP."""

        try:
            evidence = self.geoblock_checker()
        except Exception as exc:
            self._probe["geoblock_error"] = type(exc).__name__
            raise RuntimeError("current official geoblock proof is unavailable") from exc
        gate = geoblock_evidence_gate(evidence)
        self._last_geoblock_gate = gate
        if not gate["ok"]:
            self._probe["geoblock_blocked"] = True
            self._probe["geoblock_country"] = gate.get("country")
            self._probe["geoblock_region"] = gate.get("region")
            raise RuntimeError(
                "current official geoblock proof blocks order mutation: "
                + ", ".join(gate["missing"])
            )
        if (
            expected_country is not None
            and str(gate.get("country") or "").upper()
            != str(expected_country or "").upper()
        ):
            raise RuntimeError("current geoblock country differs from the authorized bootstrap")
        if (
            expected_region is not None
            and str(gate.get("region") or "").upper()
            != str(expected_region or "").upper()
        ):
            raise RuntimeError("current geoblock region differs from the authorized bootstrap")
        self._probe["geoblock_blocked"] = False
        self._probe["geoblock_country"] = gate.get("country")
        self._probe["geoblock_region"] = gate.get("region")
        self._probe["geoblock_evidence_sha256"] = gate.get("evidence_sha256")
        return gate

    def diagnostics(self):
        blockers = []
        if self.user_event_reader is None:
            blockers.append("authoritative user-event reader is absent")
        if self.user_event_health_reader is None:
            blockers.append("authoritative user-event health reader is absent")
        if self.position_reader is None:
            blockers.append("authoritative position reader is absent")
        if self.heartbeat_sender is None:
            blockers.append("audited heartbeat sender is absent")
        if self.market_rule_reader is None:
            blockers.append("public market-rule cross-check reader is absent")
        if self.token_id is None:
            blockers.append("single allowed token is absent")
        if not EVM_ADDRESS_RE.fullmatch(self.maker_address or ""):
            blockers.append("exact maker address is absent or invalid")
        if not CONDITION_ID_RE.fullmatch(self.condition_id or ""):
            blockers.append("exact condition id is absent or invalid")
        if not self.authoritative_readers_verified:
            blockers.append("authoritative readers are not verified")
        return {
            "adapter_id": self.adapter_id,
            "platform": "polymarket_global",
            "supports_trading": self.supports_trading,
            "read_only": not self.supports_trading,
            "stage1_capability_issued": self._stage1_capability is not None,
            "stage1_capability_consumed": self._stage1_capability_consumed,
            "stage2_capability_issued": self._stage2_capability is not None,
            "stage2_capability_consumed": self._stage2_capability_consumed,
            "order_submit_armed": bool(
                (
                    self._stage1_capability is not None
                    and not self._stage1_capability_consumed
                )
                or (
                    self._stage2_capability is not None
                    and not self._stage2_capability_consumed
                )
            ),
            "geoblock_checked": self._last_geoblock_gate is not None,
            "geoblock_country": (
                self._last_geoblock_gate or {}
            ).get("country"),
            "geoblock_region": (
                self._last_geoblock_gate or {}
            ).get("region"),
            "geoblock_allows_orders": (
                self._last_geoblock_gate or {}
            ).get("ok") is True,
            "geoblock_evidence_sha256": (
                self._last_geoblock_gate or {}
            ).get("evidence_sha256"),
            "stage1_geoblock_evidence_sha256": self._probe.get(
                "stage1_geoblock_evidence_sha256"
            ),
            "sdk_distribution": OFFICIAL_CLOB_DISTRIBUTION,
            "sdk_version": self.sdk_version,
            "sdk_version_pinned": self.sdk_version == OFFICIAL_CLOB_VERSION,
            "max_order_notional": str(self.max_order_notional),
            "max_order_notional_ceiling": str(MAX_STAGE1_ORDER_NOTIONAL),
            "token_id_present": self.token_id is not None,
            "user_event_reader_present": self.user_event_reader is not None,
            "user_event_health_reader_present": self.user_event_health_reader is not None,
            "position_reader_present": self.position_reader is not None,
            "heartbeat_sender_present": self.heartbeat_sender is not None,
            "market_rule_reader_present": self.market_rule_reader is not None,
            "authoritative_readers_verified": self.authoritative_readers_verified,
            "redemption_reader_present": self.redemption_reader is not None,
            "rebate_reader_present": self.rebate_reader is not None,
            "rebate_scope_present": bool(
                self.rebate_date and self.maker_address and self.condition_id
            ),
            "rebate_payout_cycle_complete": self.rebate_payout_cycle_complete,
            "secret_values_redacted": True,
            "blockers": blockers,
        }

    def _require_order_placement(self):
        if not self.supports_trading:
            raise RuntimeError(
                "official CLOB order placement requires verified authoritative user-event "
                "and position readers"
            )
        self._require_user_stream_active()
        if not self._probe["heartbeat_acknowledged"]:
            raise RuntimeError("official CLOB order placement requires an acknowledged heartbeat")
        heartbeat_age = self.monotonic_clock() - self._last_heartbeat_monotonic
        if heartbeat_age > self.heartbeat_max_age_seconds:
            self._probe["heartbeat_acknowledged"] = False
            self._probe["heartbeat_stale"] = True
            raise RuntimeError("official CLOB order placement requires a fresh heartbeat")

    def _require_user_stream_active(self):
        health = self.user_event_health_reader() if self.user_event_health_reader else {}
        if not isinstance(health, dict) or health.get("state") not in {
            "TRANSPORT_CONNECTED_UNPROVEN",
            "SUBSCRIPTION_PROVEN",
        }:
            raise RuntimeError("authoritative user-event stream is not active")
        return health

    def _require_market_rules(self, token_id):
        rules = self._market_rules
        if not rules or rules["token_id"] != token_id:
            raise RuntimeError("post-only order requires a fresh market-rules snapshot")
        rules_age = self.monotonic_clock() - rules["observed_monotonic"]
        if rules_age > self.market_rules_max_age_seconds:
            self._probe["market_rules_stale"] = True
            raise RuntimeError("post-only order requires a fresh market-rules snapshot")
        return rules

    def open_orders(self):
        return _paginator_items(self.client.list_open_orders())

    def user_events(self):
        if self.user_event_reader is None:
            return []
        self._require_user_stream_active()
        normalized = []
        for row in self.user_event_reader() or []:
            if (
                isinstance(row, dict)
                and row.get("source") == "polymarket_global_user_ws"
                and row.get("raw_event_sha256")
            ):
                normalized.append(_validated_normalized_official_user_event(
                    row,
                    maker_address=self.maker_address,
                    condition_id=self.condition_id,
                    token_id=self.token_id,
                ))
            else:
                normalized.extend(normalize_official_user_event(
                    row,
                    maker_address=self.maker_address,
                    condition_id=self.condition_id,
                    token_id=self.token_id,
                ))
        return normalized

    def _balance_allowance_snapshot(self):
        if self._balance_allowance is None:
            observed = self.client.get_balance_allowance(asset_type="COLLATERAL")
            self._balance_allowance = _plain_sdk_value(observed or {})
        return self._balance_allowance

    def balances(self):
        payload = self._balance_allowance_snapshot()
        if not isinstance(payload, dict):
            return payload
        return {
            key: payload.get(key)
            for key in ("asset_type", "balance", "signature_type")
            if key in payload
        }

    def allowances(self):
        payload = self._balance_allowance_snapshot()
        if not isinstance(payload, dict):
            return payload
        return payload.get("allowances") or {}

    def refresh_collateral_evidence(self):
        """Read and content-bind current authenticated collateral state."""

        self._balance_allowance = None
        payload = self._balance_allowance_snapshot()
        if not isinstance(payload, dict):
            raise RuntimeError("collateral balance/allowance response is not a mapping")
        allowances = payload.get("allowances")
        if payload.get("balance") in (None, "") or not isinstance(allowances, dict):
            raise RuntimeError("collateral balance/allowance response is incomplete")
        return {
            "status": "OBSERVED",
            "query_scope": "authenticated_collateral_balance_allowance",
            "balance_atomic": payload.get("balance"),
            "allowances_atomic": dict(allowances),
            "response_sha256": _official_event_hash(payload),
        }

    def positions(self):
        if self.position_reader is None:
            self._last_position_evidence = None
            return []
        observed = self.position_reader()
        if isinstance(observed, dict):
            rows = observed.get("rows")
            if not isinstance(rows, list):
                raise RuntimeError("position reader evidence has no row list")
            self._last_position_evidence = dict(observed)
            return list(rows)
        self._last_position_evidence = None
        return list(observed or [])

    def position_evidence(self, positions=None):
        rows = list(positions or [])
        scope_valid = bool(
            EVM_ADDRESS_RE.fullmatch(self.maker_address or "")
            and CONDITION_ID_RE.fullmatch(self.condition_id or "")
        )
        evidence = dict(self._last_position_evidence or {})
        observed = bool(
            self.position_reader is not None
            and self.authoritative_readers_verified
            and scope_valid
            and exact_current_positions_evidence(
                evidence,
                maker_address=self.maker_address,
                condition_id=self.condition_id,
                rows=rows,
            )
        )
        return {
            "status": "OBSERVED" if observed else "NOT_CONFIGURED",
            "query_scope": "exact_maker_condition" if observed else None,
            "maker_address": self.maker_address,
            "condition_id": self.condition_id,
            "rows": rows,
            "response_sha256": evidence.get("response_sha256") if observed else None,
            "request_url": evidence.get("request_url") if observed else None,
            "http_status": evidence.get("http_status") if observed else None,
        }

    def rewards(self):
        maker_rebate_evidence = {
            "query_date": self.rebate_date,
            "maker_address": self.maker_address,
            "condition_id": self.condition_id,
            "payout_cycle_complete": self.rebate_payout_cycle_complete,
            "rows": [],
            "status": "NOT_CONFIGURED",
        }
        if self.rebate_reader is not None:
            observed = self.rebate_reader()
            if isinstance(observed, dict):
                maker_rebate_evidence.update(observed)
                maker_rebate_evidence["rows"] = list(observed.get("rows") or [])
            else:
                maker_rebate_evidence["rows"] = list(observed or [])
                maker_rebate_evidence["status"] = "UNBOUND_RESPONSE"
        return {
            "current_markets": _paginator_items(self.client.list_current_rewards()),
            "maker_rebate_evidence": maker_rebate_evidence,
        }

    def fees(self):
        if not self.token_id or not self._market_rules:
            return {}
        return {
            "token_id": self.token_id,
            "fee_rate_bps": str(self._market_rules["fee_rate_bps"]),
        }

    def closed_only_mode(self):
        return self.client.get_closed_only_mode()

    def redemption_status(self):
        return self.redemption_reader() if self.redemption_reader else {}

    def probe_evidence(self):
        return dict(self._probe)

    def refresh_market_rules(self):
        if not self.token_id:
            raise RuntimeError("market-rules refresh requires the adapter's single allowed token")
        if self.market_rule_reader is None:
            raise RuntimeError("market-rules refresh requires public endpoint cross-checks")
        book = self.client.get_order_book(token_id=self.token_id)
        observed_token = str(_value(book, "asset_id", "asset", "token_id") or "").strip()
        observed_condition = str(
            _value(book, "market", "condition_id", "conditionId") or ""
        ).strip().lower()
        if observed_token != self.token_id:
            raise RuntimeError("order-book token differs from the adapter's single allowed token")
        if observed_condition != self.condition_id:
            raise RuntimeError("order-book condition differs from the adapter's exact condition")
        min_order_size = _required_decimal(
            _value(book, "min_order_size", "minimum_order_size"),
            "current min order size",
        )
        book_tick_size = _required_decimal(
            _value(book, "tick_size", "minimum_tick_size"),
            "current book tick size",
        )
        endpoints = self.market_rule_reader()
        if not isinstance(endpoints, dict) or str(endpoints.get("token_id") or "") != self.token_id:
            raise RuntimeError("market-rule endpoint evidence differs from the adapter token")
        endpoint_tick_size = _required_decimal(
            endpoints.get("tick_size"),
            "current tick-size endpoint value",
        )
        if book_tick_size != endpoint_tick_size:
            raise RuntimeError("order-book and tick-size endpoint values disagree")
        neg_risk = _value(book, "neg_risk", "negRisk")
        if not isinstance(neg_risk, bool):
            raise RuntimeError("current order book does not declare neg-risk state")
        if endpoints.get("neg_risk") is not neg_risk:
            raise RuntimeError("order-book and neg-risk endpoint values disagree")
        try:
            fee_rate_bps = Decimal(str(endpoints.get("fee_rate_bps")))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise RuntimeError("current fee-rate endpoint value is invalid") from exc
        if not fee_rate_bps.is_finite() or fee_rate_bps < 0:
            raise RuntimeError("current fee-rate endpoint value is invalid")
        bid_prices = _level_prices(_value(book, "bids") or [])
        ask_prices = _level_prices(_value(book, "asks") or [])
        self._market_rules = {
            "token_id": self.token_id,
            "condition_id": self.condition_id,
            "min_order_size": min_order_size,
            "tick_size": book_tick_size,
            "neg_risk": neg_risk,
            "fee_rate_bps": fee_rate_bps,
            "best_bid": max(bid_prices) if bid_prices else None,
            "best_ask": min(ask_prices) if ask_prices else None,
            "observed_monotonic": self.monotonic_clock(),
        }
        self._probe.update({
            "market_rules_verified": True,
            "market_rules_stale": False,
            "market_condition_id": self.condition_id,
            "market_min_order_size": str(min_order_size),
            "market_tick_size": str(book_tick_size),
            "market_neg_risk": neg_risk,
            "market_fee_rate_bps": str(fee_rate_bps),
            "market_best_bid": str(self._market_rules["best_bid"])
            if self._market_rules["best_bid"] is not None
            else None,
            "market_best_ask": str(self._market_rules["best_ask"])
            if self._market_rules["best_ask"] is not None
            else None,
        })
        return {
            key: (str(value) if isinstance(value, Decimal) else value)
            for key, value in self._market_rules.items()
            if key != "observed_monotonic"
        }

    def _signed_order_identity_proof(
        self,
        signed_order,
        *,
        token_id,
        expected_signature_type_id,
    ):
        """Validate public signed-order identity and return a redacted proof."""

        signer = str(_value(signed_order, "signer") or "").strip().lower()
        maker = str(_value(signed_order, "maker") or "").strip().lower()
        signed_token = str(
            _value(signed_order, "tokenId", "token_id", "asset_id") or ""
        ).strip()
        signed_signature_type = _value(
            signed_order,
            "signatureType",
            "signature_type",
        )
        signature = str(_value(signed_order, "signature") or "").strip()
        client_signer = str(getattr(self.client, "signer", "") or "").strip().lower()
        post_only = _value(signed_order, "post_only", "postOnly")
        order_type = str(_value(signed_order, "order_type", "orderType") or "").upper()
        try:
            signed_signature_type = int(signed_signature_type)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("signed order omitted its signature type") from exc
        expected_order_signer = (
            str(self.maker_address or "").lower()
            if signed_signature_type == 3
            else client_signer
        )
        checks = {
            "client_signer_valid": EVM_ADDRESS_RE.fullmatch(client_signer) is not None,
            "order_signer_matches_wallet_topology": (
                signer == expected_order_signer
                and EVM_ADDRESS_RE.fullmatch(signer) is not None
            ),
            "maker_matches_funder": (
                maker == str(self.maker_address or "").lower()
                and EVM_ADDRESS_RE.fullmatch(maker) is not None
            ),
            "token_matches": signed_token == str(token_id),
            "signature_type_matches": (
                signed_signature_type == int(expected_signature_type_id)
            ),
            "signature_valid": EVM_SIGNATURE_RE.fullmatch(signature) is not None,
            "post_only_forced": post_only is True,
            "order_type_is_gtc": order_type == "GTC",
        }
        missing = [name for name, valid in checks.items() if not valid]
        if missing:
            raise RuntimeError("signed-order identity mismatch: " + ", ".join(missing))
        content = {
            "signer_address": signer,
            "maker_address": maker,
            "token_id": signed_token,
            "signature_type_id": signed_signature_type,
            "post_only": post_only,
            "order_type": order_type,
            "signature": signature,
        }
        return {
            "client_signer_address": client_signer,
            "order_signer_address": signer,
            "maker_address": maker,
            "token_id": signed_token,
            "signature_type_id": signed_signature_type,
            "signed_order_sha256": _official_event_hash(content),
            "signature_observed": True,
            "signature_retained": False,
        }

    def preview_signed_order(self, intent, *, expected_signature_type_id):
        """Build, validate, and hash one order locally without posting it.

        This proves the Stage 0 signer/funder/signature-type topology before a
        wallet can be treated as order-capable.  The raw signature and signed
        order are deliberately not returned or retained.
        """

        intent = dict(intent or {})
        token_id = str(
            intent.get("clob_token_id")
            or intent.get("token_id")
            or self.token_id
            or ""
        ).strip()
        if not token_id or token_id != self.token_id:
            raise RuntimeError("signed-order preview token differs from the adapter token")
        price = _required_decimal(intent.get("price"), "preview price")
        size = _required_decimal(intent.get("size"), "preview size")
        rules = self._require_market_rules(token_id)
        if size < rules["min_order_size"]:
            raise RuntimeError("signed-order preview size is below the current market minimum")
        if price >= 1 or price % rules["tick_size"] != 0:
            raise RuntimeError("signed-order preview price is outside the current tick grid")
        side = str(intent.get("side") or "").upper()
        if side != "BUY":
            raise RuntimeError("Stage 0 signed-order preview must be a backed BUY")
        try:
            signature_type_id = int(expected_signature_type_id)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("signed-order preview requires a numeric signature type") from exc
        if signature_type_id not in {0, 1, 2, 3}:
            raise RuntimeError("signed-order preview signature type is unsupported")

        expiration = int(intent.get("expiration") or 0)
        signed_order = self.client.create_limit_order(
            token_id=token_id,
            price=price,
            size=size,
            side=side,
            post_only=True,
            expiration=expiration or None,
        )
        proof = self._signed_order_identity_proof(
            signed_order,
            token_id=token_id,
            expected_signature_type_id=signature_type_id,
        )
        self._probe.update({
            "signed_order_preview_verified": True,
            "signed_order_preview_sha256": proof["signed_order_sha256"],
            "signed_order_preview_signature_retained": False,
        })
        return {
            "status": "VERIFIED_NON_POSTING_PREVIEW",
            **proof,
        }

    def heartbeat(self):
        if not self.supports_trading:
            raise RuntimeError(
                "official CLOB heartbeat requires verified authoritative user-event and position readers"
            )
        response = self.heartbeat_sender.send()
        acknowledged = response == {"status": "ok"}
        self._probe["heartbeat_acknowledged"] = acknowledged
        self._probe["heartbeat_stale"] = False
        if acknowledged:
            self._heartbeat_acknowledgment_count += 1
            self._probe["heartbeat_acknowledgment_count"] = (
                self._heartbeat_acknowledgment_count
            )
            self._last_heartbeat_monotonic = self.monotonic_clock()
        else:
            self._last_heartbeat_monotonic = None
            raise RuntimeError("heartbeat response did not acknowledge status ok")
        return response

    def place_order(
        self,
        intent,
        *,
        stage1_capability=None,
        stage2_capability=None,
    ):
        self._require_order_placement()
        if stage1_capability is not None and stage2_capability is not None:
            raise RuntimeError("official CLOB submit cannot receive two capabilities")
        intent = dict(intent or {})
        token_id = str(intent.get("clob_token_id") or intent.get("token_id") or self.token_id or "").strip()
        if not token_id:
            raise ValueError("post-only order requires a CLOB token id")
        if self.token_id is not None and token_id != self.token_id:
            raise RuntimeError("order token differs from the adapter's single allowed token")
        price = _required_decimal(intent.get("price"), "price")
        if price >= 1:
            raise ValueError("price must be below one")
        size = _required_decimal(intent.get("size"), "size")
        rules = self._require_market_rules(token_id)
        if size < rules["min_order_size"]:
            raise RuntimeError("order size is below the current market minimum")
        if price % rules["tick_size"] != 0:
            raise RuntimeError("order price does not align to the current market tick size")
        if price * size > self.max_order_notional:
            raise RuntimeError("order notional exceeds the adapter pilot cap")
        side = str(intent.get("side") or "").upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if side == "BUY" and rules["best_ask"] is not None and price >= rules["best_ask"]:
            raise RuntimeError("post-only BUY would cross the fresh best ask")
        if side == "SELL" and rules["best_bid"] is not None and price <= rules["best_bid"]:
            raise RuntimeError("post-only SELL would cross the fresh best bid")
        closed_only = self.closed_only_mode()
        if isinstance(closed_only, bool):
            closed_only_enabled = closed_only
        elif isinstance(closed_only, dict) and (
            "closed_only" in closed_only or "closedOnly" in closed_only
        ):
            closed_only_enabled = bool_value(
                closed_only.get("closed_only")
                if "closed_only" in closed_only
                else closed_only.get("closedOnly"),
                False,
            )
        else:
            raise RuntimeError(
                "closed-only account check did not return an authoritative boolean"
            )
        if closed_only_enabled:
            raise RuntimeError("account is in closed-only mode")
        if side == "SELL":
            if not bool_value(intent.get("owned_inventory_verified"), False):
                raise RuntimeError("SELL requires verified owned outcome inventory")
            owned = 0.0
            for position in self.positions():
                position_token = str(
                    position.get("asset")
                    or position.get("asset_id")
                    or position.get("token_id")
                    or ""
                )
                if position_token != token_id:
                    continue
                raw_size = position.get("size") or position.get("balance") or position.get("amount") or 0
                try:
                    position_size = float(raw_size)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(position_size) and position_size > 0:
                    owned += position_size
            if owned < size:
                raise RuntimeError("SELL size exceeds authoritative owned outcome inventory")
        stage1_authorized = bool(
            self._stage1_capability is not None
            and stage1_capability is self._stage1_capability
            and not self._stage1_capability_consumed
        )
        stage2_authorized = bool(
            self._stage2_capability is not None
            and stage2_capability is self._stage2_capability
            and not self._stage2_capability_consumed
        )
        if not stage1_authorized and not stage2_authorized:
            if self._stage2_capability is None and stage2_capability is None:
                raise RuntimeError(
                    "official CLOB submit requires the unconsumed Stage 1 lifecycle capability"
                )
            raise RuntimeError(
                "official CLOB submit requires one unconsumed authorized capability"
            )
        if stage1_authorized and stage2_authorized:
            raise RuntimeError("official CLOB submit cannot use two authorization lanes")
        if stage2_authorized:
            if side != "BUY":
                raise RuntimeError("Stage 2 capability permits backed BUY orders only")
            current_utc = self.utc_clock()
            if current_utc.tzinfo is None:
                current_utc = current_utc.replace(tzinfo=timezone.utc)
            current_utc = current_utc.astimezone(timezone.utc)
            if (
                self._stage2_expires_at_utc is None
                or current_utc >= self._stage2_expires_at_utc
            ):
                raise RuntimeError("Stage 2 evidence expired before official submit")
            if price * size > self._stage2_max_order_notional:
                raise RuntimeError("order notional exceeds the frozen Stage 2 cap")
            self._stage2_capability_consumed = True
            self._probe["stage2_capability_consumed"] = True
            expected_country = self._stage2_geoblock_country
            expected_region = self._stage2_geoblock_region
            expected_signature_type_id = self._stage2_signature_type_id
        else:
            self._stage1_capability_consumed = True
            self._probe["stage1_capability_consumed"] = True
            expected_country = self._stage1_geoblock_country
            expected_region = self._stage1_geoblock_region
            expected_signature_type_id = self._stage1_signature_type_id
        self._require_current_geo_eligibility(
            expected_country=expected_country,
            expected_region=expected_region,
        )
        expiration = int(intent.get("expiration") or 0)
        # Do not use place_limit_order. The unified client convenience method
        # may mutate token allowances before retrying. Signing is local; the
        # post_order call below is this capability's only network submit.
        signed_order = self.client.create_limit_order(
            token_id=token_id,
            price=price,
            size=size,
            side=side,
            post_only=True,
            expiration=expiration or None,
        )
        signed_proof = self._signed_order_identity_proof(
            signed_order,
            token_id=token_id,
            expected_signature_type_id=expected_signature_type_id,
        )
        self._probe["submitted_signed_order_sha256"] = signed_proof[
            "signed_order_sha256"
        ]
        try:
            response = self.client.post_order(signed_order)
        except Exception:
            self._probe["ambiguous_order_submit"] = True
            try:
                self.cancel_all()
            except Exception as cancel_exc:
                self._probe["emergency_cancel_error"] = type(cancel_exc).__name__
            raise
        self._probe["post_only_order_attempted"] = True
        order_id = _value(response, "orderID", "order_id")
        status = str(_value(response, "status") or "").lower()
        successful = _value(response, "ok", "success") is True
        trade_ids = _value(response, "tradeIDs", "trade_ids") or []
        transaction_hashes = _value(
            response,
            "transactionsHashes",
            "transactions_hashes",
            "transaction_hashes",
        ) or []
        self._probe["last_order_id"] = str(order_id) if order_id else None
        self._probe["last_order_status"] = status or None
        if not successful or not order_id or status != "live" or trade_ids or transaction_hashes:
            self._probe["post_only_response_invalid"] = True
            self.cancel_all()
            raise RuntimeError(
                "post-only placement did not return an execution-free live order; cancel-all sent"
            )
        return _plain_sdk_value(response)

    def get_order(self, order_id):
        return _plain_sdk_value(self.client.get_order(order_id=str(order_id)))

    def cancel_order(self, order_id):
        return _plain_sdk_value(self.client.cancel_order(order_id=str(order_id)))

    def cancel_all(self):
        response = self.client.cancel_all()
        self._probe["cancel_all_requested"] = True
        remaining = []
        for attempt in range(self.cancel_verify_attempts):
            remaining = self.open_orders()
            if not remaining:
                break
            if attempt + 1 < self.cancel_verify_attempts and self.cancel_verify_interval_seconds:
                self.sleeper(self.cancel_verify_interval_seconds)
        self._probe["cancel_all_zero_open_orders_verified"] = len(remaining) == 0
        self._probe["cancel_all_remaining_open_order_count"] = len(remaining)
        self._probe["heartbeat_acknowledged"] = False
        self._last_heartbeat_monotonic = None
        if self._stage1_capability is not None and not self._stage1_capability_consumed:
            self._stage1_capability_consumed = True
            self._probe["stage1_capability_consumed"] = True
            self._probe["stage1_capability_disarmed_by_cancel_all"] = True
        if self._stage2_capability is not None and not self._stage2_capability_consumed:
            self._stage2_capability_consumed = True
            self._probe["stage2_capability_consumed"] = True
            self._probe["stage2_capability_disarmed_by_cancel_all"] = True
        if remaining:
            raise RuntimeError("cancel-all did not converge to zero open orders")
        return _plain_sdk_value(response)
