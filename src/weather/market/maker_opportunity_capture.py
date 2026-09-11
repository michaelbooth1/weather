"""Bounded, unauthenticated International maker-opportunity evidence capture.

This command captures a preselected public universe; it never selects markets,
constructs orders, queries accounts, or upgrades configured rates to earnings.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote, urlencode

from weather.market.exchange_economics import (
    _call_fetch_json, _call_fetch_text, _default_fetch_json, _default_fetch_text,
)
from weather.market.exchange_economics_sources import (
    CONDITION_RE, check_response_budget, json_response_payload,
)
from weather.market.market_config import date_from_event_slug, event_slug_for_date
from weather.market.market_registry import spec_for_slug
from weather.paths import data_path
from weather.schema_registry import schema_version

MAX_CONDITIONS = 6
MAX_REWARD_PAGES = 2
MAX_PACKET_BYTES = 32 * 1024 * 1024
RULE_URLS = (
    "https://docs.polymarket.com/programs/liquidity-rewards.md",
    "https://docs.polymarket.com/trading/place-orders.md",
    "https://docs.polymarket.com/market-data/prices-order-books.md",
    "https://docs.polymarket.com/market-data/market-details.md",
    "https://docs.polymarket.com/api-reference/rewards/get-raw-rewards-for-a-specific-market.md",
    "https://docs.polymarket.com/trading/fees.md",
    "https://docs.polymarket.com/programs/maker-rebates.md",
    "https://docs.polymarket.com/resources/contracts.md",
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def selection_rows(selection):
    """Validate the fixed scope before any request, including native event identity."""
    if not isinstance(selection, dict) or not isinstance(selection.get("policy_id"), str) or not selection["policy_id"].strip():
        raise ValueError("selection:policy_missing")
    rows = selection.get("selected")
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_CONDITIONS:
        raise ValueError("selection:condition_bound")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("selection:row_invalid")
        condition, slug = row.get("condition_id"), row.get("event_slug")
        if not isinstance(condition, str) or not CONDITION_RE.fullmatch(condition) or condition != condition.lower() or condition in seen:
            raise ValueError("selection:condition_invalid_or_duplicate")
        spec = spec_for_slug(slug) if isinstance(slug, str) else None
        target = date_from_event_slug(slug) if spec else None
        if spec is None or target is None or slug != event_slug_for_date(target, spec.id):
            raise ValueError("selection:event_not_canonical")
        if row.get("location_id") != spec.id or row.get("target_date") != target.isoformat():
            raise ValueError("selection:native_market_or_date_mismatch")
        seen.add(condition)
    return rows


def gamma_market(payload, row):
    if not isinstance(payload, dict) or payload.get("slug") != row["event_slug"] or not isinstance(payload.get("markets"), list):
        raise ValueError("gamma:event_identity")
    matches = [market for market in payload["markets"] if isinstance(market, dict) and market.get("conditionId") == row["condition_id"]]
    if len(matches) != 1:
        raise ValueError("gamma:condition_missing_or_duplicate")
    return matches[0]


def token_map(market):
    """Outcomes are explicitly named; sorted token IDs never establish YES/NO."""
    def array(value):
        if isinstance(value, str):
            value = json_response_payload(value.encode("utf-8"))
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError("gamma:binary_token_mapping")
        return value

    outcomes, tokens = array(market.get("outcomes")), array(market.get("clobTokenIds"))
    if any(not isinstance(outcome, str) for outcome in outcomes):
        raise ValueError("gamma:outcome_invalid")
    named = dict(zip((outcome.upper() for outcome in outcomes), tokens))
    if set(named) != {"YES", "NO"} or any(not isinstance(token, str) or not re.fullmatch(r"[1-9][0-9]*", token) for token in tokens) or len(set(tokens)) != 2:
        raise ValueError("gamma:token_identity")
    return named


def reward_page(payload, condition):
    """Only a terminal, internally consistent exact-condition page proves completeness."""
    if not isinstance(payload, dict) or "error" in payload:
        raise ValueError("rewards:invalid_response")
    rows, count, limit, cursor = (payload.get(key) for key in ("data", "count", "limit", "next_cursor"))
    if (not isinstance(rows, list) or type(count) is not int or count != len(rows)
            or type(limit) is not int or not 1 <= limit <= 100 or not 0 <= count <= limit
            or not isinstance(cursor, str) or not cursor or cursor != cursor.strip() or len(cursor) > 4096
            or (not rows and cursor != "LTE=")):
        raise ValueError("rewards:pagination_invalid")
    if any(not isinstance(row, dict) or row.get("condition_id") != condition for row in rows):
        raise ValueError("rewards:condition_mismatch")
    return rows, cursor


def collect(selection, *, selection_sha256, fetch_json=_default_fetch_json, fetch_text=_default_fetch_text, timeout_seconds=15):
    rows = selection_rows(selection)
    if not re.fullmatch(r"[0-9a-f]{64}", selection_sha256):
        raise ValueError("selection:hash_invalid")
    if not 0 < timeout_seconds <= 20:
        raise ValueError("capture:timeout_bound")
    packet = {
        "schema_version": schema_version("maker_opportunity_capture"),
        "platform": "polymarket_global", "status": "INCOMPLETE",
        "started_at_utc": utc_now(), "finished_at_utc": None,
        "selection": selection, "selection_sha256": selection_sha256,
        "selection_canonical_sha256": hashlib.sha256(json.dumps(selection, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
        "responses": [], "errors": [], "live_order_authority": False,
    }

    def get(role, url, condition=None, text=False):
        payload, evidence = (_call_fetch_text(fetch_text, url, timeout_seconds=timeout_seconds)
                             if text else _call_fetch_json(fetch_json, url, timeout_seconds=timeout_seconds))
        record = {"role": role, "condition_id": condition, "evidence": evidence}
        check_response_budget([item["evidence"] for item in packet["responses"]] + [evidence])
        packet["responses"].append(record)
        return payload

    phase = "rules"
    try:
        for url in RULE_URLS:
            get("rule", url, text=True)
        for row in rows:
            condition = row["condition_id"]
            phase = condition
            market = gamma_market(get("gamma", "https://gamma-api.polymarket.com/events/slug/" + quote(row["event_slug"], safe=""), condition), row)
            tokens = token_map(market)
            if row.get("token_ids") is not None and row["token_ids"] != tokens:
                raise ValueError("selection:token_mapping_changed")
            info = get("clob_market", "https://clob.polymarket.com/clob-markets/" + condition, condition)
            if not isinstance(info, dict) or "error" in info:
                raise ValueError("clob_market:invalid_response")
            cursor = None
            seen_cursors = set()
            reward_rows = []
            for _ in range(MAX_REWARD_PAGES):
                url = "https://clob.polymarket.com/rewards/markets/" + condition
                # Default sponsored=false is explicit: never add a folded rate twice.
                url += "?" + urlencode({"sponsored": "false", **({"next_cursor": cursor} if cursor else {})})
                page_rows, cursor = reward_page(get("rewards", url, condition), condition)
                reward_rows.extend(page_rows)
                if cursor == "LTE=":
                    break
                if cursor in seen_cursors:
                    raise ValueError("rewards:cursor_repeated")
                seen_cursors.add(cursor)
            else:
                raise ValueError("rewards:page_bound_without_terminal")
            if len(reward_rows) > 1:
                raise ValueError("rewards:duplicate_condition_rows")
            for outcome in ("YES", "NO"):
                book = get("book_" + outcome.lower(), "https://clob.polymarket.com/book?" + urlencode({"token_id": tokens[outcome]}), condition)
                if not isinstance(book, dict) or book.get("market") != condition or book.get("asset_id") != tokens[outcome]:
                    raise ValueError("book:identity_mismatch")
        packet["status"] = "CAPTURED"
    except (ValueError, OSError, TimeoutError) as exc:
        # Completed responses survive a later failure. Never write partial success.
        packet["errors"].append({"phase": phase, "error_type": type(exc).__name__, "message": str(exc)[:600]})
    packet["finished_at_utc"] = utc_now()
    return packet


def read_json(path, *, max_bytes=MAX_PACKET_BYTES):
    path = Path(path)
    if path.stat().st_size > max_bytes:
        raise ValueError("input:file_size_bound")
    with path.open("rb") as handle:
        body = handle.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError("input:file_size_bound")
    return parse_json_bytes(body, max_bytes=max_bytes), hashlib.sha256(body).hexdigest()


def parse_json_bytes(body, *, max_bytes=MAX_PACKET_BYTES):
    if not isinstance(body, bytes) or len(body) > max_bytes:
        raise ValueError("input:file_size_bound")
    # json_response_payload has the stricter per-HTTP-response bound; packet
    # containers are larger but reject duplicate keys and nonfinite constants too.
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("input:duplicate_key")
            value[key] = item
        return value
    def invalid(value):
        raise ValueError("input:nonfinite_number")
    return json.loads(body.decode("utf-8-sig"), object_pairs_hook=unique, parse_constant=invalid)


def write_new_json(path, payload):
    path = Path(path)
    body = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if len(body.encode("utf-8")) > MAX_PACKET_BYTES:
        raise ValueError("output:file_size_bound")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(body)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--selection-sha256", required=True)
    parser.add_argument("--output", type=Path, default=data_path("backtest", "maker_opportunity_capture.json"))
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("output already exists; use a new attempt path")
    selection, digest = read_json(args.selection, max_bytes=1024 * 1024)
    if digest != args.selection_sha256:
        parser.error("selection hash differs from the reviewed manifest")
    packet = collect(selection, selection_sha256=digest)
    packet["producer"] = {"module_file": str(Path(__file__).resolve()), "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    write_new_json(args.output, packet)
    print(json.dumps({"status": packet["status"], "responses": len(packet["responses"]), "output": str(args.output), "errors": packet["errors"]}))
    return 0 if packet["status"] == "CAPTURED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
