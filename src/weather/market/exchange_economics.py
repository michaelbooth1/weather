"""Exchange economics snapshot validation and drift reporting.

This module owns the paper/shadow evidence gate for platform economics.  The
live account/platform submission gate remains in ``market_making_preflight``.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from weather.market.market_config import ensure_date
from weather.market.market_making_preflight import (
    SUPPORTED_PLATFORM_IDS,
    non_empty_text,
    recent_utc_timestamp,
)
from weather.market.mm_policy import maybe_float, parse_time, utc_now
from weather.paths import config_path, data_path, docs_path
from weather.schema_registry import schema_version


SNAPSHOT_SCHEMA_VERSION = schema_version("exchange_economics_snapshot")
DRIFT_SCHEMA_VERSION = schema_version("exchange_economics_drift")
DEFAULT_PLATFORM = "polymarket_global"
DEFAULT_MAX_AGE_HOURS = 24.0
DEFAULT_TEMPLATE = docs_path("research", "exchange_economics_snapshot_template.json")
DEFAULT_EVENT_METADATA = config_path("location_market_events.json")
DEFAULT_SNAPSHOT = data_path() / "backtest" / "exchange_economics_snapshot.json"
DEFAULT_ACCEPTED_SNAPSHOT = data_path() / "backtest" / "exchange_economics_accepted_snapshot.json"
DEFAULT_DRIFT_REPORT = data_path() / "backtest" / "exchange_economics_drift.json"
RUN_CAPTURE_FILENAME = "exchange_economics_snapshot.json"

SNAPSHOT_ID_PREFIX = "xecon"
CURRENT_EVIDENCE_BASIS = "current_exchange_economics"
STALE_EVIDENCE_BASIS = "paper_stale_exchange_economics"

GLOBAL_PLATFORM = "polymarket_global"
GAMMA_EVENT_BY_SLUG_URL = "https://gamma-api.polymarket.com/events/slug/{slug}"
CLOB_CURRENT_REWARDS_URL = "https://clob.polymarket.com/rewards/markets/current"
GLOBAL_SOURCE_URLS = (
    "https://docs.polymarket.com/trading/fees",
    "https://docs.polymarket.com/programs/maker-rebates",
    "https://docs.polymarket.com/programs/liquidity-rewards",
    "https://docs.polymarket.com/api-reference/rewards/get-current-active-rewards-configurations",
    "https://docs.polymarket.com/api-reference/rebates/get-current-rebated-fees-for-a-maker",
)
GLOBAL_SOURCE_MARKDOWN_URLS = {
    url: f"{url}.md"
    for url in GLOBAL_SOURCE_URLS
}
MAX_SOURCE_RESPONSE_BYTES = 2 * 1024 * 1024

MATERIAL_FIELD_PATHS = (
    ("fee_model",),
    ("maker_rebate",),
    ("liquidity_rewards",),
    ("reward_formula",),
    ("market_rules", "tick_size"),
    ("market_rules", "min_order_size"),
    ("market_rules", "order_semantics"),
    ("api_order_semantics",),
    ("order_semantics",),
    ("market_fee_rule_profiles",),
)
RUNTIME_SNAPSHOT_FIELDS = {
    "accepted_at_utc",
    "accepted_from_snapshot_path",
    "accepted_gate",
    "exchange_economics_hash",
    "published_at_utc",
    "published_from_template",
    "snapshot_hash",
    "snapshot_id",
    "source_hash",
    "source_hash_sha256",
    "target_date",
    "verified_at_utc",
    "verified_for_target_date",
}
SOURCE_HASH_METADATA_FIELDS = {"source_hash", "source_hash_sha256"}


def _json_hash(payload, length=24):
    import hashlib

    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:length]


def _load_json(path):
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _canonical_json_bytes(payload):
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def _default_fetch_json(url, *, timeout_seconds=20.0):
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "weather-exchange-economics/0.2",
        },
    )
    with urlopen(request, timeout=float(timeout_seconds)) as response:
        body = response.read()
        status = getattr(response, "status", None) or response.getcode()
        content_type = response.headers.get("Content-Type", "")
    if int(status) != 200:
        raise ValueError(f"exchange economics source returned HTTP {status}: {url}")
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"exchange economics source returned invalid JSON: {url}") from exc
    return payload, {
        "url": url,
        "http_status": int(status),
        "content_type": content_type,
        "response_bytes": len(body),
        "response_sha256": _sha256_bytes(body),
    }


def _call_fetch_json(fetch_json, url, *, timeout_seconds):
    result = fetch_json(url, timeout_seconds=timeout_seconds)
    if isinstance(result, tuple) and len(result) == 2:
        payload, evidence = result
    else:
        payload = result
        body = _canonical_json_bytes(payload)
        evidence = {
            "url": url,
            "http_status": 200,
            "content_type": "application/json",
            "response_bytes": len(body),
            "response_sha256": _sha256_bytes(body),
        }
    evidence = dict(evidence or {})
    evidence.setdefault("url", url)
    evidence.setdefault("http_status", 200)
    if not non_empty_text(str(evidence.get("response_sha256") or "")):
        evidence["response_sha256"] = _sha256_bytes(_canonical_json_bytes(payload))
    return payload, evidence


def _default_fetch_text(url, *, timeout_seconds=20.0):
    request = Request(
        url,
        headers={
            "Accept": "text/markdown, text/plain;q=0.9",
            "User-Agent": "weather-exchange-economics/0.3",
        },
    )
    with urlopen(request, timeout=float(timeout_seconds)) as response:
        body = response.read(MAX_SOURCE_RESPONSE_BYTES + 1)
        status = getattr(response, "status", None) or response.getcode()
        content_type = response.headers.get("Content-Type", "")
    if int(status) != 200:
        raise ValueError(f"exchange economics rule source returned HTTP {status}: {url}")
    if len(body) > MAX_SOURCE_RESPONSE_BYTES:
        raise ValueError(f"exchange economics rule source exceeded size limit: {url}")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"exchange economics rule source was not UTF-8: {url}") from exc
    return text, {
        "url": url,
        "http_status": int(status),
        "content_type": content_type,
        "response_bytes": len(body),
        "response_sha256": _sha256_bytes(body),
    }


def _call_fetch_text(fetch_text, url, *, timeout_seconds):
    result = fetch_text(url, timeout_seconds=timeout_seconds)
    if isinstance(result, tuple) and len(result) == 2:
        source_text, evidence = result
    else:
        source_text = result
        evidence = {}
    if not isinstance(source_text, str) or not source_text.strip():
        raise ValueError(f"exchange economics rule source returned empty text: {url}")
    body = source_text.encode("utf-8")
    if len(body) > MAX_SOURCE_RESPONSE_BYTES:
        raise ValueError(f"exchange economics rule source exceeded size limit: {url}")
    evidence = dict(evidence or {})
    evidence.setdefault("url", url)
    evidence.setdefault("http_status", 200)
    evidence.setdefault("content_type", "text/markdown")
    evidence.setdefault("response_bytes", len(body))
    evidence.setdefault("response_sha256", _sha256_bytes(body))
    return source_text, evidence


def _normalized_rule_text(value):
    return " ".join(str(value or "").lower().split())


def _rule_document_semantic_checks(canonical_url, source_text):
    text = _normalized_rule_text(source_text)
    no_spaces = text.replace(" ", "")
    if canonical_url.endswith("/trading/fees"):
        return {
            "fee_formula": "fee=c×feerate×p×(1-p)" in no_spaces,
            "weather_fee_schedule": (
                "| weather" in text and "| 0.05" in text and "| 25%" in text
            ),
            "precision_and_floor": all((
                "rounded to 5 decimal places" in text,
                "0.00001 usdc" in text,
                "anything smaller rounds to zero" in text,
            )),
        }
    if canonical_url.endswith("/programs/maker-rebates"):
        return {
            "daily_pusd": "paid daily in pusd" in text,
            "minimum_payout": (
                "minimum accrued rebate" in text and "1 pusd" in text
            ),
            "weather_rebate_share": (
                "| weather" in text and "| 25%" in text
            ),
            "fee_equivalent_formula": (
                "fee_equivalent=c×feerate×p×(1-p)" in no_spaces
            ),
            "per_market_scope": "totals are calculated per market" in text,
        }
    if canonical_url.endswith("/programs/liquidity-rewards"):
        return {
            "resting_limit_orders": "posting resting limit orders" in text,
            "daily_distribution": "daily at midnight utc" in text,
            "market_specific_qualification": all((
                "minimum qualifying order size" in text,
                "max spread" in text,
                "min size cutoff" in text,
            )),
            "q_scoring": "q<sub>" in text,
            "single_sided_adjustment": "single-sided" in text,
        }
    if canonical_url.endswith("get-current-active-rewards-configurations"):
        return {
            "endpoint_path": "/rewards/markets/current" in text,
            "condition_identity": "condition_id" in text,
            "market_parameters": all((
                "rewards_max_spread" in text,
                "rewards_min_size" in text,
                "total_daily_rate" in text,
            )),
        }
    if canonical_url.endswith("get-current-rebated-fees-for-a-maker"):
        return {
            "endpoint_path": "/rebates/current" in text,
            "unauthenticated": "does not require authentication" in text,
            "request_scope": all(("maker_address" in text, "yyyy-mm-dd" in text)),
            "response_scope": all((
                "condition_id" in text,
                "asset_address" in text,
                "maker_address" in text,
                "rebated_fees_usdc" in text,
            )),
            "response_unit_usdc": (
                "usdc amount rebated" in text
                or "rebated fee amount in usdc" in text
            ),
        }
    return {"recognized_rule_document": False}


def _fetch_global_rule_documents(fetch_text, *, timeout_seconds):
    documents = []
    for canonical_url, source_url in GLOBAL_SOURCE_MARKDOWN_URLS.items():
        source_text, proof = _call_fetch_text(
            fetch_text,
            source_url,
            timeout_seconds=timeout_seconds,
        )
        documents.append({
            "canonical_url": canonical_url,
            **proof,
            "semantic_checks": _rule_document_semantic_checks(canonical_url, source_text),
        })
    return documents


def _event_rows_for_global_snapshot(event_metadata, target_date):
    from weather.market.market_registry import all_specs

    target_text = _target_text(target_date)
    configured_ids = {spec.id for spec in all_specs()}
    selected = []
    present_ids = set()
    for location in (event_metadata or {}).get("locations") or []:
        location_id = str(location.get("location_id") or location.get("id") or "").strip()
        if location_id not in configured_ids:
            continue
        candidates = []
        for event in location.get("active_events") or []:
            event_date = _target_text(event.get("event_date"))
            if target_text and event_date and event_date < target_text:
                continue
            if event.get("active") is False or event.get("closed") is True:
                continue
            if non_empty_text(str(event.get("event_slug") or "")):
                candidates.append(event)
        if not candidates and non_empty_text(str(location.get("latest_event_slug") or "")):
            latest_date = max(
                (_target_text(value) for value in location.get("source_event_dates") or []),
                default=None,
            )
            if not target_text or not latest_date or latest_date >= target_text:
                candidates.append({
                    "event_slug": location.get("latest_event_slug"),
                    "event_date": latest_date,
                    "markets": [],
                })
        for event in candidates:
            present_ids.add(location_id)
            selected.append({
                "location_id": location_id,
                "event_slug": str(event.get("event_slug")),
                "event_date": _target_text(event.get("event_date")),
                "registry_markets": list(event.get("markets") or []),
            })
    selected.sort(key=lambda row: (row.get("event_date") or "", row["location_id"], row["event_slug"]))
    return selected, sorted(configured_ids - present_ids)


def _parse_token_ids(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [value]
    return [str(item) for item in (value or []) if non_empty_text(str(item))]


def _fetch_current_rewards(fetch_json, *, timeout_seconds, page_limit=500, max_pages=50):
    rows = []
    evidence = []
    cursor = None
    seen_cursors = set()
    for _page in range(int(max_pages)):
        query = {"limit": int(page_limit)}
        if cursor:
            query["next_cursor"] = cursor
        url = f"{CLOB_CURRENT_REWARDS_URL}?{urlencode(query)}"
        payload, proof = _call_fetch_json(fetch_json, url, timeout_seconds=timeout_seconds)
        evidence.append(proof)
        rows.extend((payload or {}).get("data") or [])
        next_cursor = str((payload or {}).get("next_cursor") or "").strip()
        if not next_cursor or next_cursor in {"LTE=", "-1"}:
            break
        if next_cursor in seen_cursors:
            raise ValueError(f"current rewards pagination repeated cursor {next_cursor!r}")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    else:
        raise ValueError(f"current rewards pagination exceeded {max_pages} pages")
    return rows, evidence


def _uniform_value(rows, path):
    values = []
    for row in rows:
        value = _dig(row, path)
        if value is not None:
            values.append(value)
    if not values:
        return None
    return values[0] if all(value == values[0] for value in values) else None


def collect_global_snapshot_payload(
    *,
    target_date=None,
    event_metadata_path=DEFAULT_EVENT_METADATA,
    now=None,
    fetch_json=None,
    fetch_text=None,
    timeout_seconds=20.0,
):
    """Fetch and content-bind current International Polymarket economics.

    The tracked event registry chooses the exact weather conditions in scope;
    Gamma supplies condition/token identity plus fee/tick/min-size fields, and
    the CLOB rewards endpoint supplies current per-condition reward campaigns.
    """

    now_dt = utc_now(now)
    target_text = _target_text(target_date or now_dt.date())
    event_metadata_path = Path(event_metadata_path)
    event_metadata = _load_json(event_metadata_path)
    if event_metadata is None:
        raise ValueError(f"invalid or missing event metadata: {event_metadata_path}")
    event_rows, missing_locations = _event_rows_for_global_snapshot(event_metadata, target_text)
    if not event_rows:
        raise ValueError(f"event metadata has no active configured weather events on/after {target_text}")
    if missing_locations:
        raise ValueError(
            "event metadata is missing active events for configured markets: "
            + ", ".join(missing_locations)
        )

    fetch_json = fetch_json or _default_fetch_json
    fetch_text = fetch_text or _default_fetch_text
    rule_documents = _fetch_global_rule_documents(
        fetch_text,
        timeout_seconds=timeout_seconds,
    )
    response_evidence = []
    gamma_events = []
    for selected in event_rows:
        url = GAMMA_EVENT_BY_SLUG_URL.format(slug=quote(selected["event_slug"], safe=""))
        event_payload, proof = _call_fetch_json(fetch_json, url, timeout_seconds=timeout_seconds)
        response_evidence.append(proof)
        if str((event_payload or {}).get("slug") or "") != selected["event_slug"]:
            raise ValueError(f"Gamma event identity mismatch for {selected['event_slug']}")
        gamma_events.append((selected, event_payload))

    reward_rows, reward_evidence = _fetch_current_rewards(
        fetch_json,
        timeout_seconds=timeout_seconds,
    )
    response_evidence.extend(reward_evidence)
    rewards_by_condition = {
        str(row.get("condition_id") or "").lower(): row
        for row in reward_rows
        if non_empty_text(str(row.get("condition_id") or ""))
    }

    markets = []
    registry_conditions = set()
    gamma_conditions = set()
    for selected, event_payload in gamma_events:
        registered_by_condition = {
            str(row.get("condition_id") or "").lower(): row
            for row in selected.get("registry_markets") or []
            if non_empty_text(str(row.get("condition_id") or ""))
        }
        registry_conditions.update(registered_by_condition)
        for market in (event_payload or {}).get("markets") or []:
            condition_id = str(market.get("conditionId") or market.get("condition_id") or "").lower()
            if not condition_id:
                continue
            if registered_by_condition and condition_id not in registered_by_condition:
                continue
            gamma_conditions.add(condition_id)
            registered = registered_by_condition.get(condition_id) or {}
            gamma_tokens = _parse_token_ids(market.get("clobTokenIds") or market.get("tokens"))
            registered_tokens = sorted(
                str(item.get("token_id"))
                for item in registered.get("outcomes") or []
                if non_empty_text(str(item.get("token_id") or ""))
            )
            if registered_tokens and sorted(gamma_tokens) != registered_tokens:
                raise ValueError(f"Gamma token identity mismatch for condition {condition_id}")
            reward = rewards_by_condition.get(condition_id) or {}
            fee_schedule = market.get("feeSchedule") or {}
            rewards_config = list(reward.get("rewards_config") or [])
            daily_rate = maybe_float(reward.get("total_daily_rate"))
            if daily_rate is None:
                daily_rate = sum(maybe_float(item.get("rate_per_day")) or 0.0 for item in rewards_config)
            markets.append({
                "location_id": selected["location_id"],
                "event_date": selected.get("event_date"),
                "event_slug": selected["event_slug"],
                "event_id": str(event_payload.get("id") or ""),
                "market_id": str(market.get("id") or registered.get("polymarket_market_id") or ""),
                "condition_id": condition_id,
                "question": market.get("question") or registered.get("question") or "",
                "token_ids": gamma_tokens,
                # Preserve the API type so validation can require a real JSON
                # boolean.  ``bool("false")`` is truthy and would turn a
                # malformed/string-valued response into fee-enabled evidence.
                "fees_enabled": market.get("feesEnabled"),
                "fee_schedule": {
                    "rate": maybe_float(fee_schedule.get("rate")),
                    "exponent": maybe_float(fee_schedule.get("exponent")),
                    "taker_only": fee_schedule.get("takerOnly"),
                    "rebate_rate": maybe_float(fee_schedule.get("rebateRate")),
                },
                "order_min_size": maybe_float(market.get("orderMinSize")),
                "order_price_min_tick_size": maybe_float(market.get("orderPriceMinTickSize")),
                "liquidity_rewards": {
                    "current_daily_rate_usdc": daily_rate,
                    "rewards_min_size": maybe_float(
                        reward.get("rewards_min_size")
                        if reward.get("rewards_min_size") is not None
                        else market.get("rewardsMinSize")
                    ),
                    "rewards_max_spread_cents": maybe_float(
                        reward.get("rewards_max_spread")
                        if reward.get("rewards_max_spread") is not None
                        else market.get("rewardsMaxSpread")
                    ),
                    "active_configs": rewards_config,
                },
            })
    if registry_conditions and gamma_conditions != registry_conditions:
        missing = sorted(registry_conditions - gamma_conditions)
        extra = sorted(gamma_conditions - registry_conditions)
        raise ValueError(
            f"Gamma/registry condition coverage mismatch: missing={missing[:5]} extra={extra[:5]}"
        )
    if not markets:
        raise ValueError("Gamma events contained no selected weather conditions")
    markets.sort(key=lambda row: (row["event_date"] or "", row["location_id"], row["condition_id"]))

    registry_bytes = event_metadata_path.read_bytes()
    fetched_at = now_dt.isoformat()
    fee_rate = _uniform_value(markets, ("fee_schedule", "rate"))
    rebate_rate = _uniform_value(markets, ("fee_schedule", "rebate_rate"))
    tick_size = _uniform_value(markets, ("order_price_min_tick_size",))
    min_order_size = _uniform_value(markets, ("order_min_size",))
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "platform": GLOBAL_PLATFORM,
        "platform_surface": "international_clob",
        "verified_for_target_date": target_text,
        "target_date": target_text,
        "effective_date": target_text,
        "verified_at_utc": fetched_at,
        "max_age_hours": DEFAULT_MAX_AGE_HOURS,
        "source_urls": list(GLOBAL_SOURCE_URLS) + sorted({row["url"] for row in response_evidence}),
        "source_verification": {
            "mode": "live_api_content_bound",
            "fetched_at_utc": fetched_at,
            "event_metadata_path": str(event_metadata_path),
            "event_metadata_sha256": _sha256_bytes(registry_bytes),
            "configured_market_count": len({row["location_id"] for row in event_rows}),
            "event_count": len(event_rows),
            "condition_count": len(markets),
            "registry_condition_count": len(registry_conditions),
            "gamma_condition_count": len(gamma_conditions),
            "reward_condition_match_count": sum(
                1 for row in markets if row["condition_id"] in rewards_by_condition
            ),
            "responses": response_evidence,
            "rule_documents": rule_documents,
        },
        "fee_model": {
            "name": "polymarket_global_per_condition_fee_schedule_v1",
            "taker_fee_model": "fee = shares * rate * price * (1 - price)",
            "taker_fee_rate": fee_rate,
            "maker_fee_rate": 0.0,
            "flattening_fee_rate": fee_rate,
            "fee_precision_decimals": 5,
            "minimum_nonzero_fee_usdc": 0.00001,
            "subminimum_fee_rounds_to_zero": True,
            "per_condition_source_of_truth": "markets[].fee_schedule",
            "fees_charged_when": "trade_executes",
        },
        "maker_rebate": {
            "formula": "maker_rebate = executed_maker_fee_weight * fee_schedule.rebate_rate",
            "pool_share": rebate_rate,
            "maker_rebate_rate": rebate_rate,
            "credited_when": "daily_after_eligible_resting_liquidity_executes",
            "documented_payout_asset": "pUSD",
            "program_documented_payout_asset": "pUSD",
            "reconciliation_api_amount_field": "rebated_fees_usdc",
            "reconciliation_api_documented_amount_unit": "USDC",
            "documentation_asset_terms_conflict": True,
            "actual_payout_asset_status": "wallet_reconciliation_required",
            "minimum_accrued_payout_pusd": 1.0,
            "payout_cadence": "daily",
            "calculation_scope": "per_market",
            "paper_accounting_unit": "usd_equivalent",
            "requires_resting_fill": True,
            "requires_actual_reconciliation": True,
            "requires_minimum_payout_reconciliation": True,
            "requires_payout_asset_reconciliation": True,
            "actual_reconciliation_endpoint": "https://clob.polymarket.com/rebates/current",
            "actual_reconciliation_endpoint_requires_auth": False,
        },
        "liquidity_rewards": {
            "formula": "polymarket_global_Q_score_market_specific",
            "parameters_market_specific": True,
            "per_condition_source_of_truth": "markets[].liquidity_rewards",
            "primary_pnl_assumption_usdc": 0.0,
            "actual_payout_evidence": False,
            "single_sided_midrange_divisor": 3.0,
            "two_sided_required_outside_probability_interval": [0.1, 0.9],
        },
        "market_rules": {
            "tick_size": tick_size,
            "min_order_size": min_order_size,
            "tick_size_field": "orderPriceMinTickSize",
            "min_order_size_field": "orderMinSize",
            "market_specific_fields_required": True,
            "order_semantics": {
                "matching": "continuous_price_time_priority",
                "maker_only_field": "postOnly",
                "cancel": "open orders may be canceled before fill",
            },
        },
        "api_order_semantics": {
            "order_type": "GTC limit order by default",
            "maker_only_field": "postOnly",
            "partial_fill": "allowed",
            "private_user_stream_required_for_own_final_state": True,
        },
        "order_semantics": {
            "clob": "continuous_price_time_priority",
            "limit_order": "price_or_better",
            "fees_on_cancel": False,
            "fees_on_reject": False,
            "fees_on_expire": False,
        },
        "markets": markets,
    }
    payload["source_hash"] = source_proof_hash(payload)
    payload["source_hash_sha256"] = payload["source_hash"]
    payload["snapshot_id"] = snapshot_id(payload)
    payload["exchange_economics_hash"] = snapshot_hash(payload)
    return payload


def collect_and_publish_global_snapshot(
    *,
    snapshot_path=DEFAULT_SNAPSHOT,
    target_date=None,
    event_metadata_path=DEFAULT_EVENT_METADATA,
    now=None,
    fetch_json=None,
    fetch_text=None,
    timeout_seconds=20.0,
    max_age_hours=None,
):
    payload = collect_global_snapshot_payload(
        target_date=target_date,
        event_metadata_path=event_metadata_path,
        now=now,
        fetch_json=fetch_json,
        fetch_text=fetch_text,
        timeout_seconds=timeout_seconds,
    )
    gate = _check_snapshot_payload(
        payload,
        path=snapshot_path,
        target_date=target_date or payload.get("verified_for_target_date"),
        platform=GLOBAL_PLATFORM,
        now=now,
        max_age_hours=max_age_hours,
    )
    if not gate.get("ok"):
        raise ValueError(gate.get("reason") or "collected global economics snapshot did not validate")
    out = write_json(snapshot_path, payload)
    return {
        "status": "PASS",
        "snapshot_path": str(out),
        "snapshot_id": gate.get("snapshot_id"),
        "snapshot_hash": gate.get("snapshot_hash"),
        "source_hash": gate.get("source_hash"),
        "gate": gate,
        "payload": payload,
    }


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _dig(payload, path):
    current = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _source_urls(payload):
    urls = _as_list(payload.get("source_urls"))
    metadata = payload.get("source_metadata") or {}
    urls.extend(_as_list(metadata.get("source_urls")))
    sources = payload.get("sources") or []
    if isinstance(sources, list):
        for row in sources:
            if isinstance(row, dict):
                urls.extend(_as_list(row.get("url")))
                urls.extend(_as_list(row.get("source_url")))
    return [str(url).strip() for url in urls if non_empty_text(str(url))]


def _source_hash(payload):
    metadata = payload.get("source_metadata") or {}
    return (
        payload.get("source_hash")
        or payload.get("source_hash_sha256")
        or metadata.get("source_hash")
        or metadata.get("source_hash_sha256")
    )


def source_proof_hash(payload):
    payload = payload or {}
    source_metadata = {
        key: value
        for key, value in (payload.get("source_metadata") or {}).items()
        if key not in SOURCE_HASH_METADATA_FIELDS
    }
    source_payload = {
        "source_urls": sorted(set(_source_urls(payload))),
        "sources": payload.get("sources") or [],
        "source_metadata": source_metadata,
        "source_evidence": payload.get("source_evidence") or {},
        "source_verification": payload.get("source_verification") or {},
    }
    return _json_hash(source_payload, length=32)


def _target_text(value):
    if not value:
        return None
    if isinstance(value, date):
        return value.isoformat()
    try:
        return ensure_date(value).isoformat()
    except (TypeError, ValueError):
        return str(value)


def normalized_economics_payload(payload):
    """Return only material economics fields for stable hashing/drift checks."""
    payload = payload or {}
    market_rules = payload.get("market_rules") or {}
    if "tick_size" not in market_rules and payload.get("tick_size") is not None:
        market_rules = {**market_rules, "tick_size": payload.get("tick_size")}
    if "min_order_size" not in market_rules and payload.get("min_order_size") is not None:
        market_rules = {**market_rules, "min_order_size": payload.get("min_order_size")}
    return {
        "platform": payload.get("platform"),
        "platform_surface": payload.get("platform_surface"),
        "fee_model": payload.get("fee_model") or {},
        "maker_rebate": payload.get("maker_rebate") or {},
        "liquidity_rewards": payload.get("liquidity_rewards") or {},
        "reward_formula": payload.get("reward_formula"),
        "market_rules": market_rules,
        "api_order_semantics": payload.get("api_order_semantics") or {},
        "order_semantics": payload.get("order_semantics") or {},
        "markets": payload.get("markets") or [],
    }


def normalized_drift_payload(payload):
    """Return economics rules without daily condition/token identity churn."""

    normalized = normalized_economics_payload(payload)
    by_location = {}
    for market in normalized.pop("markets", []):
        profile = {
            "fees_enabled": market.get("fees_enabled"),
            "fee_schedule": market.get("fee_schedule") or {},
            "order_min_size": market.get("order_min_size"),
            "order_price_min_tick_size": market.get("order_price_min_tick_size"),
        }
        by_location.setdefault(str(market.get("location_id") or ""), []).append(profile)
    normalized["market_fee_rule_profiles"] = [
        {
            "location_id": location_id,
            "profiles": sorted(
                profiles,
                key=lambda row: _canonical_json_bytes(row),
            ),
        }
        for location_id, profiles in sorted(by_location.items())
    ]
    return normalized


def snapshot_hash(payload):
    return _json_hash(normalized_economics_payload(payload), length=32)


def snapshot_id(payload):
    existing = str((payload or {}).get("snapshot_id") or "").strip()
    if existing:
        return existing
    return f"{SNAPSHOT_ID_PREFIX}-{snapshot_hash(payload)[:16]}"


def _fee_rate(payload, *names):
    fee_model = (payload or {}).get("fee_model") or {}
    for name in names:
        value = fee_model.get(name)
        if value is None:
            value = payload.get(name)
        parsed = maybe_float(value)
        if parsed is not None:
            return parsed
    return None


def _positive_field(value):
    parsed = maybe_float(value)
    return parsed is not None and parsed > 0


def _valid_nonnegative_field(value):
    parsed = maybe_float(value)
    return parsed is not None and parsed >= 0


def _validated_market_rules(payload):
    rules = dict((payload or {}).get("market_rules") or {})
    if payload.get("tick_size") is not None:
        rules.setdefault("tick_size", payload.get("tick_size"))
    if payload.get("min_order_size") is not None:
        rules.setdefault("min_order_size", payload.get("min_order_size"))
    return rules


def _evidence_target(payload):
    return (
        payload.get("verified_for_target_date")
        or payload.get("target_date")
        or payload.get("run_date")
    )


def _global_market_economics_checks(payload):
    payload = payload or {}
    markets = payload.get("markets") or []
    verification = payload.get("source_verification") or {}
    responses = verification.get("responses") or []
    rule_documents = verification.get("rule_documents") or []
    condition_ids = [str(row.get("condition_id") or "").lower() for row in markets]
    token_ids = [
        str(token_id)
        for row in markets
        for token_id in row.get("token_ids") or []
    ]

    def valid_market(row):
        fee = row.get("fee_schedule") or {}
        rewards = row.get("liquidity_rewards") or {}
        return all((
            non_empty_text(str(row.get("event_slug") or "")),
            non_empty_text(str(row.get("condition_id") or "")),
            len(row.get("token_ids") or []) >= 2,
            row.get("fees_enabled") is True,
            _positive_field(fee.get("rate")),
            maybe_float(fee.get("exponent")) == 1.0,
            fee.get("taker_only") is True,
            _positive_field(fee.get("rebate_rate")),
            _positive_field(row.get("order_min_size")),
            _positive_field(row.get("order_price_min_tick_size")),
            _valid_nonnegative_field(rewards.get("current_daily_rate_usdc")),
            _valid_nonnegative_field(rewards.get("rewards_min_size")),
            _valid_nonnegative_field(rewards.get("rewards_max_spread_cents")),
        ))

    response_proof_ok = bool(responses) and all(
        int(row.get("http_status") or 0) == 200
        and non_empty_text(str(row.get("url") or ""))
        and len(str(row.get("response_sha256") or "")) == 64
        for row in responses
    )
    expected_rule_urls = set(GLOBAL_SOURCE_URLS)
    observed_rule_urls = {
        str(row.get("canonical_url") or "")
        for row in rule_documents
    }
    rule_document_proof_ok = (
        observed_rule_urls == expected_rule_urls
        and len(rule_documents) == len(expected_rule_urls)
        and all(
            int(row.get("http_status") or 0) == 200
            and row.get("url") == GLOBAL_SOURCE_MARKDOWN_URLS.get(row.get("canonical_url"))
            and len(str(row.get("response_sha256") or "")) == 64
            and int(row.get("response_bytes") or 0) > 0
            for row in rule_documents
        )
    )
    rule_document_semantics_ok = (
        rule_document_proof_ok
        and all(
            bool(row.get("semantic_checks"))
            and all(value is True for value in row["semantic_checks"].values())
            for row in rule_documents
        )
    )
    maker_rebate = payload.get("maker_rebate") or {}
    expected_count = int(verification.get("condition_count") or 0)
    registry_count = int(verification.get("registry_condition_count") or 0)
    gamma_count = int(verification.get("gamma_condition_count") or 0)
    return {
        "global_live_api_content_bound": verification.get("mode") == "live_api_content_bound",
        "global_source_response_hashes_recorded": response_proof_ok,
        "global_official_rule_urls_recorded": expected_rule_urls.issubset(set(_source_urls(payload))),
        "global_rule_document_hashes_recorded": rule_document_proof_ok,
        "global_rule_document_semantics_verified": rule_document_semantics_ok,
        "global_event_metadata_hash_recorded": len(str(verification.get("event_metadata_sha256") or "")) == 64,
        "global_markets_recorded": bool(markets),
        "global_market_economics_complete": bool(markets) and all(valid_market(row) for row in markets),
        "global_condition_ids_unique": bool(condition_ids) and len(condition_ids) == len(set(condition_ids)),
        "global_token_ids_unique": bool(token_ids) and len(token_ids) == len(set(token_ids)),
        "global_registry_gamma_condition_coverage": (
            bool(markets)
            and expected_count == len(markets)
            and registry_count == len(markets)
            and gamma_count == len(markets)
        ),
        "global_primary_liquidity_reward_assumption_zero": maybe_float(
            ((payload.get("liquidity_rewards") or {}).get("primary_pnl_assumption_usdc"))
        ) == 0.0,
        "global_actual_rebate_reconciliation_required": (
            maker_rebate.get("requires_actual_reconciliation") is True
        ),
        "global_fee_precision_recorded": (
            maybe_float((payload.get("fee_model") or {}).get("fee_precision_decimals")) == 5.0
            and maybe_float((payload.get("fee_model") or {}).get("minimum_nonzero_fee_usdc")) == 0.00001
            and (payload.get("fee_model") or {}).get("subminimum_fee_rounds_to_zero") is True
        ),
        "global_rebate_minimum_payout_recorded": (
            maybe_float(maker_rebate.get("minimum_accrued_payout_pusd")) == 1.0
            and maker_rebate.get("payout_cadence") == "daily"
            and maker_rebate.get("calculation_scope") == "per_market"
            and maker_rebate.get("requires_minimum_payout_reconciliation") is True
        ),
        "global_rebate_payout_asset_reconciliation_required": (
            maker_rebate.get("documented_payout_asset") == "pUSD"
            and maker_rebate.get("program_documented_payout_asset") == "pUSD"
            and maker_rebate.get("reconciliation_api_amount_field")
            == "rebated_fees_usdc"
            and maker_rebate.get("reconciliation_api_documented_amount_unit")
            == "USDC"
            and maker_rebate.get("documentation_asset_terms_conflict") is True
            and maker_rebate.get("actual_payout_asset_status")
            == "wallet_reconciliation_required"
            and maker_rebate.get("requires_payout_asset_reconciliation") is True
            and maker_rebate.get("actual_reconciliation_endpoint")
            == "https://clob.polymarket.com/rebates/current"
            and maker_rebate.get("actual_reconciliation_endpoint_requires_auth") is False
        ),
        "global_post_only_semantics_recorded": (
            (payload.get("api_order_semantics") or {}).get("maker_only_field") == "postOnly"
        ),
    }


def _check_snapshot_payload(payload, *, path=None, target_date=None, platform=DEFAULT_PLATFORM, now=None, max_age_hours=None):
    now = utc_now(now)
    target_text = _target_text(target_date)
    max_age = maybe_float(max_age_hours) or maybe_float((payload or {}).get("max_age_hours")) or DEFAULT_MAX_AGE_HOURS
    effective_date = _target_text((payload or {}).get("effective_date"))
    evidence_target = _target_text(_evidence_target(payload or {}))
    market_rules = _validated_market_rules(payload or {})
    source_urls = _source_urls(payload or {})
    fee_model = (payload or {}).get("fee_model") or {}
    rebate = (payload or {}).get("maker_rebate") or {}
    rewards = (payload or {}).get("liquidity_rewards") or {}
    order_semantics = (payload or {}).get("order_semantics") or {}
    api_order_semantics = (payload or {}).get("api_order_semantics") or {}

    taker_fee_rate = _fee_rate(payload, "taker_fee_rate", "theta")
    maker_fee_rate = _fee_rate(payload, "maker_fee_rate")
    flattening_fee_rate = _fee_rate(payload, "flattening_fee_rate")
    maker_rebate_rate = maybe_float(
        rebate.get("maker_rebate_rate")
        or rebate.get("pool_share")
        or payload.get("maker_rebate_rate")
        or payload.get("maker_rebate_pool_share")
    )

    checks = {
        "schema_version_supported": (payload or {}).get("schema_version") == SNAPSHOT_SCHEMA_VERSION,
        "platform_supported": (payload or {}).get("platform") in SUPPORTED_PLATFORM_IDS,
        "platform_matches": platform in (None, "", (payload or {}).get("platform")),
        "effective_date_recorded": effective_date is not None,
        "effective_date_not_after_target": (
            target_text is None or effective_date is None or effective_date <= target_text
        ),
        # A proof taken on date X covers any target on or before X: rules
        # effective after the target are already rejected by
        # effective_date_not_after_target, and verified_at_recent enforces
        # freshness. Strict equality blocked every active-day consumer (MM
        # preflight, taker) because the daily refresh stamps its verification
        # once per day (2026-07-11: MM blocked on target 07-11 vs proof 07-10).
        "target_date_matches": (
            target_text is None or evidence_target is None or evidence_target >= target_text
        ),
        "verified_at_recent": recent_utc_timestamp((payload or {}).get("verified_at_utc"), now, max_age),
        "source_urls_recorded": bool(source_urls),
        "source_hash_recorded": non_empty_text(str(_source_hash(payload or {}) or "")),
        "source_hash_matches_content": (
            non_empty_text(str(_source_hash(payload or {}) or ""))
            and str(_source_hash(payload or {})) == source_proof_hash(payload or {})
        ),
        "snapshot_hash_matches_content": (
            str((payload or {}).get("exchange_economics_hash") or (payload or {}).get("snapshot_hash") or "")
            == snapshot_hash(payload or {})
        ),
        "snapshot_id_matches_content": (
            str((payload or {}).get("snapshot_id") or "")
            == f"{SNAPSHOT_ID_PREFIX}-{snapshot_hash(payload or {})[:16]}"
        ),
        "fee_model_recorded": non_empty_text(str(fee_model.get("taker_fee_model") or fee_model.get("name") or "")),
        "taker_fee_rate_recorded": _valid_nonnegative_field(taker_fee_rate),
        "maker_fee_rate_recorded": _valid_nonnegative_field(maker_fee_rate),
        "flattening_fee_rate_recorded": _valid_nonnegative_field(flattening_fee_rate),
        "maker_rebate_formula_recorded": non_empty_text(
            str(rebate.get("formula") or (payload or {}).get("maker_rebate_formula") or "")
        ),
        "maker_rebate_rate_recorded": _positive_field(maker_rebate_rate),
        "reward_formula_recorded": non_empty_text(
            str(rewards.get("formula") or (payload or {}).get("reward_formula") or "")
        ),
        "tick_size_recorded": _positive_field(market_rules.get("tick_size")),
        "min_order_size_recorded": _positive_field(market_rules.get("min_order_size")),
        "order_semantics_recorded": bool(order_semantics or market_rules.get("order_semantics")),
        "api_order_semantics_recorded": bool(api_order_semantics),
    }
    if (payload or {}).get("platform") == GLOBAL_PLATFORM:
        global_checks = _global_market_economics_checks(payload)
        checks.update(global_checks)
        # International tick/minimum fields are condition-specific. A
        # heterogeneous fleet has no truthful aggregate scalar; exact
        # per-condition completeness is the gate.
        checks["tick_size_recorded"] = global_checks["global_market_economics_complete"]
        checks["min_order_size_recorded"] = global_checks["global_market_economics_complete"]
    missing = [name for name, ok in checks.items() if not ok]
    economics_hash = snapshot_hash(payload or {})
    return {
        "required": True,
        "ok": not missing,
        "status": "PASS" if not missing else "BLOCK",
        "evidence_basis": CURRENT_EVIDENCE_BASIS if not missing else STALE_EVIDENCE_BASIS,
        "path": str(path) if path else None,
        "schema_version": (payload or {}).get("schema_version"),
        "snapshot_id": snapshot_id(payload or {}),
        "snapshot_hash": economics_hash,
        "exchange_economics_hash": economics_hash,
        "source_hash": _source_hash(payload or {}),
        "platform": (payload or {}).get("platform"),
        "platform_surface": (payload or {}).get("platform_surface"),
        "target_date": target_text,
        "verified_for_target_date": evidence_target,
        "effective_date": effective_date,
        "verified_at_utc": (payload or {}).get("verified_at_utc"),
        "max_age_hours": max_age,
        "source_urls": source_urls,
        "checks": checks,
        "missing": missing,
        "reason": "ok" if not missing else "exchange-economics snapshot missing current proof: " + ", ".join(missing),
    }


def load_exchange_economics_gate(
    path=DEFAULT_SNAPSHOT,
    target_date=None,
    *,
    platform=DEFAULT_PLATFORM,
    now=None,
    max_age_hours=None,
    required=True,
):
    if not required:
        return {"required": False, "ok": True, "status": "PASS", "reason": "not required"}
    path = Path(path) if path else None
    if path is None:
        return {
            "required": True,
            "ok": False,
            "status": "BLOCK",
            "path": None,
            "target_date": _target_text(target_date),
            "evidence_basis": STALE_EVIDENCE_BASIS,
            "reason": "no exchange-economics snapshot path provided",
            "missing": ["snapshot_path"],
        }
    if not path.exists():
        return {
            "required": True,
            "ok": False,
            "status": "BLOCK",
            "path": str(path),
            "target_date": _target_text(target_date),
            "platform": platform,
            "evidence_basis": STALE_EVIDENCE_BASIS,
            "reason": "exchange-economics snapshot artifact missing",
            "missing": ["snapshot_missing"],
        }
    payload = _load_json(path)
    if payload is None:
        return {
            "required": True,
            "ok": False,
            "status": "BLOCK",
            "path": str(path),
            "target_date": _target_text(target_date),
            "platform": platform,
            "evidence_basis": STALE_EVIDENCE_BASIS,
            "reason": "invalid exchange-economics snapshot JSON",
            "missing": ["snapshot_invalid_json"],
        }
    return _check_snapshot_payload(
        payload,
        path=path,
        target_date=target_date,
        platform=platform,
        now=now,
        max_age_hours=max_age_hours,
    )


def exchange_economics_artifact_fields(gate):
    gate = gate or {}
    return {
        "exchange_economics_status": gate.get("status"),
        "exchange_economics_evidence_basis": gate.get("evidence_basis"),
        "exchange_economics_snapshot_id": gate.get("snapshot_id"),
        "exchange_economics_hash": gate.get("snapshot_hash") or gate.get("exchange_economics_hash"),
        "exchange_economics_source_hash": gate.get("source_hash"),
        "exchange_economics_verified_at_utc": gate.get("verified_at_utc"),
        "exchange_economics_effective_date": gate.get("effective_date"),
        "exchange_economics_platform": gate.get("platform"),
    }


def bind_legs_to_market_economics(legs, snapshot_payload, gate=None):
    """Bind paper legs to exact International condition economics by token id."""

    gate = gate or {}
    required = bool(gate.get("required"))
    source_gate_ok = not required or bool(gate.get("ok"))
    markets = (snapshot_payload or {}).get("markets") or []
    by_token = {}
    for market in markets:
        for token_id in market.get("token_ids") or []:
            by_token[str(token_id)] = market
    missing = []
    bound = 0

    def bind_one(leg):
        nonlocal bound
        token_id = str(leg.get("clob_token_id") or leg.get("asset_id") or "")
        # A token match cannot rehabilitate stale, tampered, wrong-platform, or
        # otherwise invalid required evidence.  Keep legacy fixture/config
        # fallback only for explicitly non-required gates; production paper
        # economics must become zero/unbound when its source gate is not PASS.
        market = by_token.get(token_id) if source_gate_ok else None
        if market is None:
            missing_fields = {
                "exchange_economics_bound": False,
                "exchange_economics_condition_id": "",
                "liquidity_reward_daily_rate_usdc": 0.0,
                "liquidity_reward_primary_assumption_usdc": 0.0,
                "maker_rebate_payout_asset": "",
                "maker_rebate_minimum_accrued_payout_pusd": None,
            }
            if required:
                missing_fields.update({
                    "maker_rebate_fee_rate": 0.0,
                    "maker_rebate_pool_share": 0.0,
                    "flattening_fee_rate": 0.0,
                })
            leg.update(missing_fields)
            missing.append(token_id or "(missing_token_id)")
            return
        fee = market.get("fee_schedule") or {}
        rewards = market.get("liquidity_rewards") or {}
        leg.update({
            "exchange_economics_bound": True,
            "exchange_economics_condition_id": market.get("condition_id") or "",
            "maker_rebate_fee_rate": maybe_float(fee.get("rate")) or 0.0,
            "maker_rebate_pool_share": maybe_float(fee.get("rebate_rate")) or 0.0,
            "flattening_fee_rate": maybe_float(fee.get("rate")) or 0.0,
            "maker_rebate_payout_asset": (
                ((snapshot_payload or {}).get("maker_rebate") or {}).get(
                    "documented_payout_asset"
                )
                or ""
            ),
            "maker_rebate_minimum_accrued_payout_pusd": maybe_float(
                ((snapshot_payload or {}).get("maker_rebate") or {}).get(
                    "minimum_accrued_payout_pusd"
                )
            ),
            "liquidity_reward_daily_rate_usdc": maybe_float(
                rewards.get("current_daily_rate_usdc")
            ) or 0.0,
            "liquidity_reward_primary_assumption_usdc": maybe_float(
                ((snapshot_payload or {}).get("liquidity_rewards") or {}).get(
                    "primary_pnl_assumption_usdc"
                )
            ) or 0.0,
            "rewards_min_size": maybe_float(rewards.get("rewards_min_size")),
            "rewards_max_spread_cents": maybe_float(
                rewards.get("rewards_max_spread_cents")
            ),
        })
        bound += 1
    update_each = getattr(legs, "update_each", None)
    if update_each:
        update_each(bind_one)
    else:
        for leg in legs or []:
            bind_one(leg)
    total = len(legs or [])
    coverage = {
        "required": required,
        "source_gate_ok": source_gate_ok,
        "platform": (snapshot_payload or {}).get("platform"),
        "leg_count": total,
        "bound_leg_count": bound,
        "missing_leg_count": len(missing),
        "missing_token_ids": sorted(set(missing))[:50],
        "ok": source_gate_ok and not missing,
    }
    return coverage


def bind_legs_to_run_snapshots(legs, *, required, platform=DEFAULT_PLATFORM):
    """Bind every paper leg to the snapshot frozen by its own run folder."""

    from weather.market.exchange_economics_run_capture import (
        bind_legs_to_run_snapshots as bind_run_snapshots,
    )

    return bind_run_snapshots(legs, required=required, platform=platform)


def gate_with_leg_coverage(gate, coverage):
    gate = deepcopy(gate or {})
    if not gate.get("required"):
        gate["leg_coverage"] = coverage
        return gate
    ok = bool((coverage or {}).get("ok"))
    checks = dict(gate.get("checks") or {})
    checks["paper_leg_condition_economics_bound"] = ok
    gate["checks"] = checks
    gate["leg_coverage"] = coverage
    if ok:
        return gate
    missing = list(gate.get("missing") or [])
    if "paper_leg_condition_economics_bound" not in missing:
        missing.append("paper_leg_condition_economics_bound")
    gate.update({
        "ok": False,
        "status": "BLOCK",
        "evidence_basis": STALE_EVIDENCE_BASIS,
        "missing": missing,
        "reason": (
            "exchange-economics snapshot does not bind every paper leg to exact "
            f"condition/token economics: {(coverage or {}).get('missing_leg_count', 0)} missing"
        ),
    })
    return gate


def compare_snapshots(current, accepted):
    changes = []
    current_econ = normalized_drift_payload(current or {})
    accepted_econ = normalized_drift_payload(accepted or {})
    for path in MATERIAL_FIELD_PATHS:
        old = _dig(accepted_econ, path)
        new = _dig(current_econ, path)
        if old != new:
            changes.append({
                "field": ".".join(path),
                "accepted": old,
                "current": new,
            })
    return changes


def build_drift_report(
    snapshot_path=DEFAULT_SNAPSHOT,
    accepted_snapshot_path=DEFAULT_ACCEPTED_SNAPSHOT,
    *,
    target_date=None,
    platform=DEFAULT_PLATFORM,
    now=None,
    max_age_hours=None,
):
    current_gate = load_exchange_economics_gate(
        snapshot_path,
        target_date,
        platform=platform,
        now=now,
        max_age_hours=max_age_hours,
    )
    current_payload = _load_json(snapshot_path) if snapshot_path and Path(snapshot_path).exists() else {}
    accepted_payload = _load_json(accepted_snapshot_path) if accepted_snapshot_path and Path(accepted_snapshot_path).exists() else None
    changes = compare_snapshots(current_payload, accepted_payload) if accepted_payload else []
    rescore_required = bool(changes)
    status = "BLOCK" if (not current_gate.get("ok") or rescore_required) else "PASS"
    return {
        "schema_version": DRIFT_SCHEMA_VERSION,
        "generated_at_utc": utc_now(now).isoformat(),
        "status": status,
        "target_date": _target_text(target_date),
        "platform": platform,
        "snapshot_path": str(snapshot_path) if snapshot_path else None,
        "accepted_snapshot_path": str(accepted_snapshot_path) if accepted_snapshot_path else None,
        "current_gate": current_gate,
        "current_snapshot_id": current_gate.get("snapshot_id"),
        "current_snapshot_hash": current_gate.get("snapshot_hash"),
        "accepted_snapshot_id": snapshot_id(accepted_payload) if accepted_payload else None,
        "accepted_snapshot_hash": snapshot_hash(accepted_payload) if accepted_payload else None,
        "accepted_snapshot_present": accepted_payload is not None,
        "material_change_count": len(changes),
        "material_changes": changes,
        "rescore_required": rescore_required,
        "blockers": (
            [
                {
                    "code": "exchange_economics_snapshot_not_current",
                    "detail": current_gate.get("reason"),
                }
            ]
            if not current_gate.get("ok")
            else []
        )
        + (
            [
                {
                    "code": "exchange_economics_material_drift_rescore_required",
                    "detail": f"{len(changes)} material exchange-economics field(s) changed; rescore paper evidence",
                }
            ]
            if rescore_required
            else []
        ),
    }


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def capture_run_snapshot(snapshot_path, run_folder, gate):
    """Freeze one exact validated economics snapshot inside a maker run.

    Append ticks may reuse the capture but may not replace it. This prevents a
    multi-tick run from silently mixing condition identities or economics
    evidence after the shared current snapshot refreshes.
    """

    from weather.market.exchange_economics_run_capture import (
        capture_run_snapshot as capture_snapshot,
    )

    return capture_snapshot(snapshot_path, run_folder, gate)


def write_drift_report(payload, path=DEFAULT_DRIFT_REPORT):
    return write_json(path, payload)


def load_snapshot_template(path=DEFAULT_TEMPLATE):
    path = Path(path)
    payload = _load_json(path)
    if payload is None:
        raise ValueError(f"invalid or missing exchange-economics template: {path}")
    return payload


def prepare_snapshot_from_template(
    template_payload,
    *,
    target_date=None,
    verified_at_utc=None,
    platform=DEFAULT_PLATFORM,
    now=None,
):
    now_dt = utc_now(now)
    target_text = _target_text(target_date or _evidence_target(template_payload or {}) or now_dt.date())
    verified_at = verified_at_utc or now_dt.isoformat()
    payload = deepcopy(template_payload or {})
    for field in RUNTIME_SNAPSHOT_FIELDS:
        payload.pop(field, None)
    payload["schema_version"] = payload.get("schema_version") or SNAPSHOT_SCHEMA_VERSION
    payload["platform"] = platform or payload.get("platform") or DEFAULT_PLATFORM
    payload["verified_for_target_date"] = target_text
    payload["target_date"] = target_text
    payload["verified_at_utc"] = verified_at
    payload["source_hash"] = source_proof_hash(payload)
    payload["source_hash_sha256"] = payload["source_hash"]
    payload["snapshot_id"] = snapshot_id(payload)
    payload["exchange_economics_hash"] = snapshot_hash(payload)
    return payload


def publish_snapshot_from_template(
    *,
    template_path=DEFAULT_TEMPLATE,
    snapshot_path=DEFAULT_SNAPSHOT,
    target_date=None,
    platform=DEFAULT_PLATFORM,
    now=None,
    max_age_hours=None,
):
    template = load_snapshot_template(template_path)
    payload = prepare_snapshot_from_template(
        template,
        target_date=target_date,
        platform=platform,
        now=now,
    )
    payload["published_at_utc"] = payload["verified_at_utc"]
    payload["published_from_template"] = str(template_path)
    gate = _check_snapshot_payload(
        payload,
        path=snapshot_path,
        target_date=target_date or payload.get("verified_for_target_date"),
        platform=platform,
        now=now,
        max_age_hours=max_age_hours,
    )
    if not gate.get("ok"):
        raise ValueError(gate.get("reason") or "exchange-economics snapshot template did not validate")
    out = write_json(snapshot_path, payload)
    return {
        "status": "PASS",
        "snapshot_path": str(out),
        "template_path": str(template_path),
        "target_date": payload.get("verified_for_target_date"),
        "snapshot_id": gate.get("snapshot_id"),
        "snapshot_hash": gate.get("snapshot_hash"),
        "source_hash": gate.get("source_hash"),
        "gate": gate,
        "payload": payload,
    }


def accept_snapshot_baseline(
    *,
    snapshot_path=DEFAULT_SNAPSHOT,
    accepted_snapshot_path=DEFAULT_ACCEPTED_SNAPSHOT,
    drift_report_path=DEFAULT_DRIFT_REPORT,
    target_date=None,
    platform=DEFAULT_PLATFORM,
    now=None,
    max_age_hours=None,
    acknowledge_payout_asset_conflict=False,
):
    gate = load_exchange_economics_gate(
        snapshot_path,
        target_date,
        platform=platform,
        now=now,
        max_age_hours=max_age_hours,
    )
    if not gate.get("ok"):
        raise ValueError(gate.get("reason") or "exchange-economics snapshot is not current")
    payload = _load_json(snapshot_path)
    if payload is None:
        raise ValueError(f"invalid exchange-economics snapshot JSON: {snapshot_path}")
    payout_terms_conflict = (
        (payload.get("maker_rebate") or {}).get("documentation_asset_terms_conflict")
        is True
    )
    if payout_terms_conflict and acknowledge_payout_asset_conflict is not True:
        raise ValueError(
            "explicit payout-asset conflict acknowledgement is required before "
            "accepting the International economics baseline"
        )
    accepted_payload = deepcopy(payload)
    accepted_payload["accepted_at_utc"] = utc_now(now).isoformat()
    accepted_payload["accepted_from_snapshot_path"] = str(snapshot_path)
    accepted_payload["accepted_gate"] = {
        "status": gate.get("status"),
        "evidence_basis": gate.get("evidence_basis"),
        "snapshot_id": gate.get("snapshot_id"),
        "snapshot_hash": gate.get("snapshot_hash"),
        "source_hash": gate.get("source_hash"),
        "verified_at_utc": gate.get("verified_at_utc"),
        "verified_for_target_date": gate.get("verified_for_target_date"),
        "payout_asset_conflict_acknowledged": bool(
            acknowledge_payout_asset_conflict
        ),
    }
    accepted_out = write_json(accepted_snapshot_path, accepted_payload)
    drift = build_drift_report(
        snapshot_path=snapshot_path,
        accepted_snapshot_path=accepted_out,
        target_date=target_date,
        platform=platform,
        now=now,
        max_age_hours=max_age_hours,
    )
    drift_out = write_drift_report(drift, drift_report_path) if drift_report_path else None
    return {
        "status": "PASS" if drift.get("status") == "PASS" else drift.get("status"),
        "accepted_snapshot_path": str(accepted_out),
        "drift_report_path": str(drift_out) if drift_out else None,
        "gate": gate,
        "drift": drift,
    }


def build_snapshot_payload(
    *,
    target_date,
    verified_at_utc,
    platform=DEFAULT_PLATFORM,
    effective_date=None,
    source_hash="source-docs-sha256-test",
    source_urls=None,
    tick_size=0.01,
    min_order_size=5.0,
    taker_fee_rate=0.05,
    maker_fee_rate=0.0,
    maker_rebate_pool_share=0.25,
    flattening_fee_rate=0.05,
    reward_formula="polymarket_global_Q_score_market_specific",
    condition_id="0x" + "1" * 64,
    token_ids=None,
    reward_daily_rate_usdc=0.0,
    rewards_min_size=20.0,
    rewards_max_spread_cents=4.5,
):
    token_ids = token_ids or ["101", "102"]
    source_urls = source_urls or list(GLOBAL_SOURCE_URLS)
    source_response = {
        "url": "https://gamma-api.polymarket.com/events/slug/test-weather-event",
        "http_status": 200,
        "content_type": "application/json",
        "response_bytes": 123,
        "response_sha256": "a" * 64,
    }
    rule_documents = [
        {
            "canonical_url": canonical_url,
            "url": source_url,
            "http_status": 200,
            "content_type": "text/markdown",
            "response_bytes": 123,
            "response_sha256": hashlib.sha256(source_url.encode("utf-8")).hexdigest(),
            "semantic_checks": {"test_fixture_verified": True},
        }
        for canonical_url, source_url in GLOBAL_SOURCE_MARKDOWN_URLS.items()
    ]
    market = {
        "location_id": "toronto",
        "event_date": _target_text(target_date),
        "event_slug": "test-weather-event",
        "event_id": "1",
        "market_id": "1",
        "condition_id": str(condition_id).lower(),
        "question": "Test weather condition?",
        "token_ids": [str(item) for item in token_ids],
        "fees_enabled": True,
        "fee_schedule": {
            "rate": taker_fee_rate,
            "exponent": 1.0,
            "taker_only": True,
            "rebate_rate": maker_rebate_pool_share,
        },
        "order_min_size": min_order_size,
        "order_price_min_tick_size": tick_size,
        "liquidity_rewards": {
            "current_daily_rate_usdc": reward_daily_rate_usdc,
            "rewards_min_size": rewards_min_size,
            "rewards_max_spread_cents": rewards_max_spread_cents,
            "active_configs": [],
        },
    }
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "platform": platform,
        "platform_surface": "international_clob",
        "verified_for_target_date": _target_text(target_date),
        "target_date": _target_text(target_date),
        "effective_date": _target_text(effective_date or target_date),
        "verified_at_utc": verified_at_utc,
        "max_age_hours": DEFAULT_MAX_AGE_HOURS,
        "source_urls": list(source_urls),
        "source_verification": {
            "mode": "live_api_content_bound",
            "fetched_at_utc": verified_at_utc,
            "event_metadata_path": "test/location_market_events.json",
            "event_metadata_sha256": "b" * 64,
            "configured_market_count": 1,
            "event_count": 1,
            "condition_count": 1,
            "registry_condition_count": 1,
            "gamma_condition_count": 1,
            "reward_condition_match_count": 1,
            "responses": [source_response],
            "rule_documents": rule_documents,
        },
        "fee_model": {
            "name": "polymarket_global_per_condition_fee_schedule_v1",
            "taker_fee_model": "fee = shares * rate * price * (1 - price)",
            "taker_fee_rate": taker_fee_rate,
            "maker_fee_rate": maker_fee_rate,
            "flattening_fee_rate": flattening_fee_rate,
            "fee_precision_decimals": 5,
            "minimum_nonzero_fee_usdc": 0.00001,
            "subminimum_fee_rounds_to_zero": True,
            "per_condition_source_of_truth": "markets[].fee_schedule",
        },
        "maker_rebate": {
            "formula": "maker_rebate = executed_maker_fee_weight * fee_schedule.rebate_rate",
            "pool_share": maker_rebate_pool_share,
            "maker_rebate_rate": maker_rebate_pool_share,
            "documented_payout_asset": "pUSD",
            "program_documented_payout_asset": "pUSD",
            "reconciliation_api_amount_field": "rebated_fees_usdc",
            "reconciliation_api_documented_amount_unit": "USDC",
            "documentation_asset_terms_conflict": True,
            "actual_payout_asset_status": "wallet_reconciliation_required",
            "minimum_accrued_payout_pusd": 1.0,
            "payout_cadence": "daily",
            "calculation_scope": "per_market",
            "paper_accounting_unit": "usd_equivalent",
            "requires_resting_fill": True,
            "requires_actual_reconciliation": True,
            "requires_minimum_payout_reconciliation": True,
            "requires_payout_asset_reconciliation": True,
            "actual_reconciliation_endpoint": "https://clob.polymarket.com/rebates/current",
            "actual_reconciliation_endpoint_requires_auth": False,
        },
        "liquidity_rewards": {
            "formula": reward_formula,
            "parameters_market_specific": True,
            "per_condition_source_of_truth": "markets[].liquidity_rewards",
            "primary_pnl_assumption_usdc": 0.0,
            "actual_payout_evidence": False,
            "single_sided_midrange_divisor": 3.0,
            "two_sided_required_outside_probability_interval": [0.1, 0.9],
        },
        "market_rules": {
            "tick_size": tick_size,
            "min_order_size": min_order_size,
            "tick_size_field": "orderPriceMinTickSize",
            "min_order_size_field": "orderMinSize",
            "market_specific_fields_required": True,
            "order_semantics": {
                "matching": "continuous_price_time_priority",
                "maker_only_field": "postOnly",
                "cancel": "open orders may be canceled before fill",
            },
        },
        "api_order_semantics": {
            "order_type": "GTC limit order by default",
            "maker_only_field": "postOnly",
            "partial_fill": "allowed",
            "private_user_stream_required_for_own_final_state": True,
        },
        "order_semantics": {
            "clob": "continuous_price_time_priority",
            "limit_order": "price_or_better",
            "fees_on_cancel": False,
            "fees_on_reject": False,
            "fees_on_expire": False,
        },
        "markets": [market],
    }
    payload["source_hash"] = source_proof_hash(payload)
    payload["source_hash_sha256"] = payload["source_hash"]
    payload["snapshot_id"] = snapshot_id(payload)
    payload["exchange_economics_hash"] = snapshot_hash(payload)
    return payload


def _add_drift_args(parser):
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    parser.add_argument("--accepted-snapshot", default=str(DEFAULT_ACCEPTED_SNAPSHOT))
    parser.add_argument("--target-date", default="")
    parser.add_argument("--platform", default=DEFAULT_PLATFORM)
    parser.add_argument("--now", default=None)
    parser.add_argument("--json-out", default=str(DEFAULT_DRIFT_REPORT))
    return parser


def main(argv=None):
    parser = argparse.ArgumentParser(description="Publish, accept, or validate exchange economics snapshots.")
    sub = parser.add_subparsers(dest="command")

    collect_global = sub.add_parser(
        "collect-global",
        help="Fetch and content-bind current International Polymarket per-condition economics.",
    )
    collect_global.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    collect_global.add_argument("--event-metadata", default=str(DEFAULT_EVENT_METADATA))
    collect_global.add_argument("--target-date", default="")
    collect_global.add_argument("--now", default=None)
    collect_global.add_argument("--timeout-seconds", type=float, default=20.0)
    collect_global.add_argument("--max-age-hours", type=float, default=None)

    publish = sub.add_parser("publish", help="Stamp and validate a runtime snapshot from the tracked template.")
    publish.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    publish.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    publish.add_argument("--target-date", default="")
    publish.add_argument("--platform", default=DEFAULT_PLATFORM)
    publish.add_argument("--now", default=None)
    publish.add_argument("--max-age-hours", type=float, default=None)
    publish.add_argument("--accept", action="store_true", help="Also promote the published snapshot to the accepted baseline.")
    publish.add_argument(
        "--acknowledge-payout-asset-conflict",
        action="store_true",
        help="Acknowledge the official pUSD/USDC payout-amount terminology conflict before baseline acceptance.",
    )
    publish.add_argument("--accepted-snapshot", default=str(DEFAULT_ACCEPTED_SNAPSHOT))
    publish.add_argument("--json-out", default=str(DEFAULT_DRIFT_REPORT))

    accept = sub.add_parser("accept", help="Promote a current validated snapshot to the accepted baseline.")
    accept.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    accept.add_argument("--accepted-snapshot", default=str(DEFAULT_ACCEPTED_SNAPSHOT))
    accept.add_argument("--target-date", default="")
    accept.add_argument("--platform", default=DEFAULT_PLATFORM)
    accept.add_argument("--now", default=None)
    accept.add_argument("--max-age-hours", type=float, default=None)
    accept.add_argument("--json-out", default=str(DEFAULT_DRIFT_REPORT))
    accept.add_argument(
        "--acknowledge-payout-asset-conflict",
        action="store_true",
        help="Acknowledge the official pUSD/USDC payout-amount terminology conflict before baseline acceptance.",
    )

    drift = sub.add_parser("drift", help="Validate current snapshot and compare it to the accepted baseline.")
    _add_drift_args(drift)

    _add_drift_args(parser)
    args = parser.parse_args(argv)
    if args.command == "collect-global":
        payload = collect_and_publish_global_snapshot(
            snapshot_path=args.snapshot,
            target_date=args.target_date or None,
            event_metadata_path=args.event_metadata,
            now=args.now,
            timeout_seconds=args.timeout_seconds,
            max_age_hours=args.max_age_hours,
        )
        print(f"International exchange economics snapshot: {payload['status']} -> {payload['snapshot_path']}")
        return payload
    if args.command == "publish":
        payload = publish_snapshot_from_template(
            template_path=args.template,
            snapshot_path=args.snapshot,
            target_date=args.target_date or None,
            platform=args.platform,
            now=args.now,
            max_age_hours=args.max_age_hours,
        )
        print(f"Exchange economics snapshot: {payload['status']} -> {payload['snapshot_path']}")
        if args.accept:
            payload["acceptance"] = accept_snapshot_baseline(
                snapshot_path=args.snapshot,
                accepted_snapshot_path=args.accepted_snapshot,
                drift_report_path=args.json_out,
                target_date=args.target_date or None,
                platform=args.platform,
                now=args.now,
                max_age_hours=args.max_age_hours,
                acknowledge_payout_asset_conflict=(
                    args.acknowledge_payout_asset_conflict
                ),
            )
            print(f"Accepted baseline: {payload['acceptance']['status']} -> {payload['acceptance']['accepted_snapshot_path']}")
        return payload
    if args.command == "accept":
        payload = accept_snapshot_baseline(
            snapshot_path=args.snapshot,
            accepted_snapshot_path=args.accepted_snapshot,
            drift_report_path=args.json_out,
            target_date=args.target_date or None,
            platform=args.platform,
            now=args.now,
            max_age_hours=args.max_age_hours,
            acknowledge_payout_asset_conflict=(
                args.acknowledge_payout_asset_conflict
            ),
        )
        print(f"Accepted baseline: {payload['status']} -> {payload['accepted_snapshot_path']}")
        return payload
    payload = build_drift_report(
        snapshot_path=args.snapshot,
        accepted_snapshot_path=args.accepted_snapshot,
        target_date=args.target_date or None,
        platform=args.platform,
        now=args.now,
    )
    out = write_drift_report(payload, args.json_out)
    print(f"Exchange economics drift: {payload['status']} -> {out}")
    return payload


if __name__ == "__main__":
    main()
