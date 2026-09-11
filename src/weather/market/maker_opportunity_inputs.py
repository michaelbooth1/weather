"""Validate a bounded maker capture and expose its observed market/book inputs."""
from __future__ import annotations

import base64
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from urllib.parse import quote, urlencode

from weather.market.exchange_economics_sources import (
    ASSET_RE, check_response_budget, json_response_payload, response_evidence_valid,
)
from weather.market.maker_opportunity_capture import (
    MAX_REWARD_PAGES, RULE_URLS, gamma_market, reward_page, selection_rows, token_map,
)
from weather.schema_registry import schema_version


def number(value, name, *, positive=False):
    if type(value) not in (str, int, float, Decimal):
        raise ValueError(name + ":number_required")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(name + ":invalid_number") from exc
    if not parsed.is_finite() or parsed < 0 or (positive and parsed == 0) or parsed > Decimal("1e18") or not -18 <= parsed.as_tuple().exponent <= 18:
        raise ValueError(name + ":number_out_of_range")
    return parsed


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp:missing")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp:invalid") from exc
    if result.utcoffset() is None:
        raise ValueError("timestamp:timezone_required")
    return result.astimezone(timezone.utc)


def captured_payload(record, *, text=False):
    evidence = record["evidence"]
    if not response_evidence_valid(evidence, require_body=True):
        raise ValueError("source:raw_response_invalid")
    body = base64.b64decode(evidence["response_body_base64"], validate=True)
    return body.decode("utf-8-sig") if text else json_response_payload(body)


def _book(payload, condition, token):
    if not isinstance(payload, dict) or payload.get("market") != condition or payload.get("asset_id") != token:
        raise ValueError("book:identity_mismatch")
    levels = {}
    for side in ("bids", "asks"):
        raw = payload.get(side)
        if not isinstance(raw, list) or not 1 <= len(raw) <= 10000:
            raise ValueError("book:missing_or_unbounded_" + side)
        prices = []
        for level in raw:
            if not isinstance(level, dict):
                raise ValueError("book:level_invalid")
            price = number(level.get("price"), "book_price", positive=True)
            number(level.get("size"), "book_size", positive=True)
            if price >= 1:
                raise ValueError("book:price_out_of_range")
            prices.append(price)
        if len(set(prices)) != len(prices):
            raise ValueError("book:duplicate_price_level")
        levels[side] = max(prices) if side == "bids" else min(prices)
    minimum = number(payload.get("min_order_size"), "book_minimum", positive=True)
    tick = number(payload.get("tick_size"), "book_tick", positive=True)
    if tick >= 1 or levels["bids"] >= levels["asks"]:
        raise ValueError("book:tick_or_crossing_invalid")
    if any(price % tick for price in levels.values()):
        raise ValueError("book:best_price_off_tick")
    return {"best_bid": levels["bids"], "best_ask": levels["asks"], "minimum_shares": minimum,
            "tick": tick, "exchange_timestamp": payload.get("timestamp"), "exchange_hash": payload.get("hash")}


def _allocations(raw):
    if not isinstance(raw, list):
        raise ValueError("rewards:allocations_missing")
    seen = set()
    for item in raw:
        if not isinstance(item, dict) or type(item.get("id")) is not int or item["id"] < 0:
            raise ValueError("rewards:allocation_id")
        asset = item.get("asset_address")
        if not isinstance(asset, str) or not ASSET_RE.fullmatch(asset) or asset.lower() == "0x" + "0" * 40:
            raise ValueError("rewards:asset_invalid")
        key = (item["id"], asset.lower())
        if key in seen:
            raise ValueError("rewards:allocation_duplicate")
        seen.add(key)
        for name in ("start_date", "end_date"):
            value = item.get(name)
            if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                raise ValueError("rewards:calendar_date_invalid")
        if item["start_date"] > item["end_date"]:
            raise ValueError("rewards:calendar_interval_invalid")
        number(item.get("rate_per_day"), "configured_rate")
        number(item.get("total_rewards"), "configured_total")
    return raw


def validate_packet(packet, *, require_http=True):
    """Reparse exact retained bodies; validate scope, chronology and pagination."""
    if not isinstance(packet, dict) or packet.get("schema_version") != schema_version("maker_opportunity_capture"):
        raise ValueError("capture:schema")
    if packet.get("platform") != "polymarket_global" or packet.get("status") != "CAPTURED" or packet.get("errors") != [] or packet.get("live_order_authority") is not False:
        raise ValueError("capture:incomplete_or_wrong_mode")
    selection = packet.get("selection")
    rows = selection_rows(selection)
    if packet.get("selection_canonical_sha256") != hashlib.sha256(json.dumps(selection, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest():
        raise ValueError("capture:selection_changed")
    started, ended = timestamp(packet.get("started_at_utc")), timestamp(packet.get("finished_at_utc"))
    if ended < started:
        raise ValueError("capture:chronology")
    records = packet.get("responses")
    if not isinstance(records, list) or len(records) > len(RULE_URLS) + len(rows) * (4 + MAX_REWARD_PAGES):
        raise ValueError("capture:response_bound")
    check_response_budget([record.get("evidence", {}) for record in records if isinstance(record, dict)])
    index, seen_urls, synthetic = {}, set(), False
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("evidence"), dict):
            raise ValueError("capture:response_invalid")
        evidence = record["evidence"]
        if not response_evidence_valid(evidence, require_body=True):
            raise ValueError("source:raw_response_invalid")
        observed = timestamp(evidence["retrieved_at_utc"])
        if not started <= observed <= ended:
            raise ValueError("source:outside_capture_interval")
        if evidence["response_origin"] != "http_response_bytes":
            synthetic = True
            if require_http:
                raise ValueError("source:synthetic_not_public_capture")
        url = evidence["url"]
        if url in seen_urls:
            raise ValueError("source:duplicate_url")
        seen_urls.add(url)
        key = (record.get("condition_id"), record.get("role"))
        index.setdefault(key, []).append(record)
    consumed = set()

    def one(condition, role, url):
        found = index.get((condition, role), [])
        if len(found) != 1 or found[0]["evidence"]["url"] != url:
            raise ValueError(role + ":missing_duplicate_or_url_mismatch")
        consumed.add(url)
        return found[0]

    rules = {}
    rule_records = index.get((None, "rule"), [])
    if len(rule_records) != len(RULE_URLS):
        raise ValueError("rules:incomplete")
    for url in RULE_URLS:
        found = [record for record in rule_records if record["evidence"]["url"] == url]
        if len(found) != 1:
            raise ValueError("rules:missing_or_duplicate")
        rules[url] = {"text": captured_payload(found[0], text=True), "evidence": found[0]["evidence"]}
        consumed.add(url)
    derived = []
    for row in rows:
        condition = row["condition_id"]
        gamma = one(condition, "gamma", "https://gamma-api.polymarket.com/events/slug/" + quote(row["event_slug"], safe=""))
        market = gamma_market(captured_payload(gamma), row)
        tokens = token_map(market)
        if row.get("token_ids") is not None and tokens != row["token_ids"]:
            raise ValueError("selection:token_mapping_changed")
        info_record = one(condition, "clob_market", "https://clob.polymarket.com/clob-markets/" + condition)
        info = captured_payload(info_record)
        if not isinstance(info, dict) or not isinstance(info.get("t"), list) or len(info["t"]) != 2:
            raise ValueError("clob_market:token_mapping")
        mapped = {}
        for token in info["t"]:
            if not isinstance(token, dict) or not isinstance(token.get("o"), str):
                raise ValueError("clob_market:token_mapping")
            mapped[token["o"].upper()] = token.get("t")
        if mapped != tokens:
            raise ValueError("clob_market:token_disagreement")
        pages = index.get((condition, "rewards"), [])
        if not 1 <= len(pages) <= MAX_REWARD_PAGES:
            raise ValueError("rewards:page_count")
        cursor, rewards = None, []
        for page_number, record in enumerate(pages):
            url = "https://clob.polymarket.com/rewards/markets/" + condition + "?" + urlencode({"sponsored": "false", **({"next_cursor": cursor} if cursor else {})})
            if record["evidence"]["url"] != url:
                raise ValueError("rewards:cursor_request_disagreement")
            consumed.add(url)
            page_rows, cursor = reward_page(captured_payload(record), condition)
            rewards.extend(page_rows)
            if cursor == "LTE=" and page_number != len(pages) - 1:
                raise ValueError("rewards:pages_after_terminal")
        if cursor != "LTE=" or len(rewards) > 1:
            raise ValueError("rewards:incomplete_or_duplicate")
        reward = rewards[0] if rewards else None
        if reward:
            _allocations(reward.get("rewards_config"))
            number(reward.get("rewards_min_size"), "reward_minimum", positive=True)
            number(reward.get("rewards_max_spread"), "reward_spread", positive=True)
            if reward.get("event_slug") not in (None, row["event_slug"]):
                raise ValueError("rewards:event_disagreement")
            raw_tokens = reward.get("tokens")
            if not isinstance(raw_tokens, list) or len(raw_tokens) != 2 or any(not isinstance(token, dict) or not isinstance(token.get("outcome"), str) for token in raw_tokens):
                raise ValueError("rewards:token_mapping")
            if {token["outcome"].upper(): token.get("token_id") for token in raw_tokens} != tokens:
                raise ValueError("rewards:token_disagreement")
        books = {}
        for outcome in ("YES", "NO"):
            record = one(condition, "book_" + outcome.lower(), "https://clob.polymarket.com/book?" + urlencode({"token_id": tokens[outcome]}))
            books[outcome] = {**_book(captured_payload(record), condition, tokens[outcome]), "evidence": record["evidence"]}
        if books["YES"]["minimum_shares"] != books["NO"]["minimum_shares"] or books["YES"]["tick"] != books["NO"]["tick"]:
            raise ValueError("books:term_disagreement")
        if number(info.get("mos"), "clob_minimum", positive=True) != books["YES"]["minimum_shares"] or number(info.get("mts"), "clob_tick", positive=True) != books["YES"]["tick"]:
            raise ValueError("clob_market:book_term_disagreement")
        term_records = [gamma, info_record, *pages]
        components = {record["evidence"]["url"]: record["evidence"]["response_sha256"] for record in term_records}
        components.update({outcome + "_book": books[outcome]["evidence"]["response_sha256"] for outcome in books})
        term_time = max([timestamp(record["evidence"]["retrieved_at_utc"]) for record in term_records] + [timestamp(book["evidence"]["retrieved_at_utc"]) for book in books.values()])
        term_proof = {"sha256": hashlib.sha256(json.dumps(components, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                      "captured_at_utc": term_time.isoformat(), "component_sha256": components, "kind": "derived_terms_source_manifest"}
        derived.append({"selection": row, "market": market, "tokens": tokens, "clob_market": info, "rewards": reward,
                        "books": books, "terms_evidence": term_proof, "reward_evidence": pages[-1]["evidence"]})
    if consumed != seen_urls:
        raise ValueError("capture:unexpected_response_scope")
    return {"rows": derived, "rules": rules, "as_of": ended, "synthetic": synthetic}
