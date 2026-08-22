"""Select a fresh public market for the bounded International lifecycle probe.

This command performs no authentication and cannot place or cancel orders. It
binds a current validated economics snapshot and a still-current successful
paper-only market-harvest quote to current public CLOB books, then chooses the
exact built-in weather token whose one-tick minimum-size BUY is nonmarketable
and within the adapter's single-order cap.
"""

from __future__ import annotations

import argparse
import codecs
import csv
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from weather.io import write_json_atomic
from weather.market.exchange_economics import (
    load_exchange_economics_gate,
    snapshot_hash,
)
from weather.market.market_config import ensure_date
from weather.market.market_microstructure_capture import ClobClient
from weather.market.market_registry import BUILTIN_SPECS
from weather.market.mm_policy import utc_now
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("mm_live_market_candidate_plan")
RUN_SCHEMA_VERSION = schema_version("mm_run")
QUOTE_SCHEMA_VERSION = schema_version("mm_quote_intent")
PLATFORM = "polymarket_global"
SETTLEMENT_UNIT = "pUSD"
MAX_SINGLE_ORDER_NOTIONAL = Decimal("10")
MIN_MIDPOINT = Decimal("0.20")
MAX_MIDPOINT = Decimal("0.80")
MAX_BOOK_SPREAD = Decimal("0.05")
MAX_ALTERNATES = 5
MAX_PLAN_AGE_SECONDS = 300
MAX_PAPER_QUOTE_TTL_SECONDS = 120
MAX_OPERATOR_PILOT_BUDGET_PUSD = Decimal("100")
MAX_DAILY_LOSS_PUSD = Decimal("25")
MAX_EVENT_NOTIONAL_PUSD = Decimal("25")
MAX_BAND_NOTIONAL_PUSD = Decimal("10")
MAX_PAPER_QUOTE_SIZE = Decimal("5")
PAPER_PROFILE = "market_harvest"


def _canonical_sha256(payload):
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def candidate_plan_sha256(payload):
    return _canonical_sha256({
        key: value for key, value in dict(payload or {}).items()
        if key != "plan_sha256"
    })


def _decimal(value):
    if isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _bool_value(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _parse_utc(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("paper quote evidence has an invalid UTC timestamp") from exc
    if parsed.tzinfo is None:
        raise RuntimeError("paper quote evidence timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _is_sha256(value):
    text = str(value or "").lower()
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _scan_hashed_csv(path, visitor):
    digest = hashlib.sha256()
    decoder = codecs.getincrementaldecoder("utf-8-sig")()
    row_count = 0
    with Path(path).open("rb") as handle:
        def decoded_lines():
            for raw_line in handle:
                digest.update(raw_line)
                yield decoder.decode(raw_line)
            tail = decoder.decode(b"", final=True)
            if tail:
                yield tail

        for row in csv.DictReader(decoded_lines()):
            row_count += 1
            visitor(row)
    return row_count, digest.hexdigest()


def _load_paper_quote_evidence(
    run_config_path,
    quote_intents_path,
    *,
    target_date,
    economics_snapshot_id,
    economics_hash,
    now,
):
    config_raw = Path(run_config_path).read_bytes()
    try:
        config = json.loads(config_raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("paper run config is invalid JSON") from exc
    if not isinstance(config, dict):
        raise RuntimeError("paper run config must be a JSON object")
    policy = dict(config.get("policy_config") or {})
    shadow = dict(config.get("shadow_safety") or {})
    markets = list(config.get("markets") or [])
    budget = _decimal(config.get("budget_usdc"))
    policy_limits = {
        "quote_size": MAX_PAPER_QUOTE_SIZE,
        "quote_ttl_seconds": MAX_PAPER_QUOTE_TTL_SECONDS,
        "max_daily_loss": MAX_DAILY_LOSS_PUSD,
        "max_event_notional": MAX_EVENT_NOTIONAL_PUSD,
        "max_band_notional": MAX_BAND_NOTIONAL_PUSD,
    }
    config_checks = {
        "schema": config.get("schema_version") == RUN_SCHEMA_VERSION,
        "profile": config.get("permission_profile") == PAPER_PROFILE,
        "paper_mode": config.get("mode") == "paper-live-forward",
        "target_date": config.get("target_date") == target_date,
        "one_market": len(markets) == 1 and markets[0] in {spec.id for spec in BUILTIN_SPECS},
        "budget": budget is not None and Decimal("0") < budget <= MAX_OPERATOR_PILOT_BUDGET_PUSD,
        "live_mutation_disabled": shadow.get("live_trade_permission_allowed") is False,
        "private_keys_disabled": shadow.get("loads_private_keys") is False,
        "order_posting_disabled": shadow.get("posts_orders") is False,
        "economics_snapshot": config.get("exchange_economics_snapshot_id") == economics_snapshot_id,
        "economics_hash": config.get("exchange_economics_hash") == economics_hash,
    }
    for name, ceiling in policy_limits.items():
        value = _decimal(policy.get(name))
        config_checks[f"policy_{name}"] = (
            value is not None and Decimal("0") < value <= Decimal(str(ceiling))
        )
    missing_config = [name for name, valid in config_checks.items() if not valid]
    if missing_config:
        raise RuntimeError(
            "paper run config does not satisfy the live-pilot proof contract: "
            + ", ".join(missing_config)
        )

    current = utc_now(now)
    qualifying = {}

    def consider(row):
        generated = None
        try:
            generated = _parse_utc(row.get("generated_at_utc"))
        except RuntimeError:
            pass
        ttl = _decimal(row.get("quote_ttl_seconds"))
        bid = _decimal(row.get("bid_price"))
        ask = _decimal(row.get("ask_price"))
        bid_size = _decimal(row.get("bid_size"))
        ask_size = _decimal(row.get("ask_size"))
        quote_risk = _decimal(row.get("quote_risk_usdc"))
        row_budget = _decimal(row.get("run_budget_usdc"))
        token = str(row.get("clob_token_id") or "")
        condition = str(row.get("condition_id") or "").lower()
        row_checks = all((
            generated is not None,
            row.get("schema_version") == QUOTE_SCHEMA_VERSION,
            ttl is not None and Decimal("0") < ttl <= MAX_PAPER_QUOTE_TTL_SECONDS,
            generated is not None and generated <= current <= generated + timedelta(seconds=float(ttl or 0)),
            row.get("run_id") == config.get("run_id"),
            row.get("target_date") == target_date,
            row.get("run_mode") == "paper-live-forward",
            row.get("preflight_status") == "PASS",
            row.get("market_id") == markets[0],
            row.get("known_edge_permission") == PAPER_PROFILE,
            row.get("model_variant_probability_source") == "market_mid_no_model",
            _bool_value(row.get("shadow_mode")),
            _bool_value(row.get("quote_permission")),
            not _bool_value(row.get("live_trade_permission")),
            row.get("action") == "QUOTE",
            str(row.get("side") or "").upper() == "TWO_SIDED",
            row.get("budget_action") == "reserved",
            row.get("exchange_economics_snapshot_id") == economics_snapshot_id,
            row.get("exchange_economics_hash") == economics_hash,
            row.get("policy_hash") == config.get("policy_hash"),
            token.isdigit() and int(token) > 0,
            len(condition) == 66 and condition.startswith("0x")
            and all(character in "0123456789abcdef" for character in condition[2:]),
            bid is not None and ask is not None and Decimal("0") < bid < ask < Decimal("1"),
            bid_size is not None and bid_size > 0,
            ask_size is not None and ask_size > 0,
            quote_risk is not None and Decimal("0") < quote_risk <= MAX_BAND_NOTIONAL_PUSD,
            row_budget is not None and row_budget == budget,
            quote_risk is not None and budget is not None and quote_risk <= budget,
            row.get("expected_reward_score") in {"0", "0.0", "0.00"},
            row.get("expected_rebate_value") in {"0", "0.0", "0.00"},
        ))
        if not row_checks:
            return
        row_binding = {
            "run_id": row["run_id"],
            "market_id": row["market_id"],
            "target_date": row["target_date"],
            "condition_id": condition,
            "token_id": token,
            "range_label": row.get("range_label"),
            "exchange_economics_snapshot_id": economics_snapshot_id,
            "exchange_economics_hash": economics_hash,
            "policy_hash": row.get("policy_hash"),
            "generated_at_utc": generated.isoformat(),
            "expires_at_utc": (generated + timedelta(seconds=float(ttl))).isoformat(),
            "quote_ttl_seconds": float(ttl),
            "bid_price": float(bid),
            "bid_size": float(bid_size),
            "ask_price": float(ask),
            "ask_size": float(ask_size),
            "quote_risk_pusd": float(quote_risk),
            "quote_permission": True,
            "live_trade_permission": False,
            "two_sided_post_only_intent": True,
            "reward_and_rebate_assumed_zero": True,
        }
        row_binding["quote_row_sha256"] = _canonical_sha256(row)
        qualifying[(condition, token)] = row_binding

    row_count, quote_intents_sha256 = _scan_hashed_csv(
        quote_intents_path,
        consider,
    )
    if not qualifying:
        raise RuntimeError("paper quote evidence contains no current qualifying quote-permission row")
    return {
        "run_config_sha256": hashlib.sha256(config_raw).hexdigest(),
        "quote_intents_sha256": quote_intents_sha256,
        "quote_intents_row_count": row_count,
        "market_id": markets[0],
        "run_id": config.get("run_id"),
        "qualifying": qualifying,
    }


def _book_levels(book, side):
    levels = []
    for row in book.get(side) or []:
        price = _decimal(row.get("price")) if isinstance(row, dict) else None
        size = _decimal(row.get("size")) if isinstance(row, dict) else None
        if price is not None and size is not None and 0 < price < 1 and size > 0:
            levels.append((price, size))
    return levels


def _candidate_for_book(market, token_id, outcome_index, book):
    if str(book.get("asset_id") or "") != str(token_id):
        return None
    condition_id = str(market.get("condition_id") or "").lower()
    observed_condition = str(book.get("market") or "").lower()
    if observed_condition != condition_id:
        return None
    bids = _book_levels(book, "bids")
    asks = _book_levels(book, "asks")
    if not bids or not asks:
        return None
    best_bid = max(price for price, _size in bids)
    best_ask = min(price for price, _size in asks)
    if best_bid >= best_ask:
        return None
    spread = best_ask - best_bid
    midpoint = (best_bid + best_ask) / 2
    min_size = _decimal(market.get("order_min_size"))
    tick_size = _decimal(market.get("order_price_min_tick_size"))
    book_min_size = _decimal(book.get("min_order_size"))
    book_tick_size = _decimal(book.get("tick_size"))
    book_neg_risk = book.get("neg_risk")
    fee = dict(market.get("fee_schedule") or {})
    fee_rate = _decimal(fee.get("rate"))
    rebate_rate = _decimal(fee.get("rebate_rate"))
    if not all((
        market.get("fees_enabled") is True,
        min_size is not None and min_size > 0,
        tick_size is not None and 0 < tick_size < 1,
        book_min_size == min_size,
        book_tick_size == tick_size,
        isinstance(book_neg_risk, bool),
        fee_rate is not None and fee_rate > 0,
        rebate_rate is not None and rebate_rate > 0,
        best_ask > tick_size,
        MIN_MIDPOINT <= midpoint <= MAX_MIDPOINT,
        spread <= MAX_BOOK_SPREAD,
        min_size * tick_size <= MAX_SINGLE_ORDER_NOTIONAL,
    )):
        return None
    best_bid_depth = sum(size for price, size in bids if price == best_bid)
    best_ask_depth = sum(size for price, size in asks if price == best_ask)
    rewards = dict(market.get("liquidity_rewards") or {})
    reward_max_spread = _decimal(rewards.get("rewards_max_spread_cents"))
    reward_min_size = _decimal(rewards.get("rewards_min_size"))
    result = {
        "location_id": market.get("location_id"),
        "event_date": market.get("event_date"),
        "event_slug": market.get("event_slug"),
        "question": market.get("question"),
        "condition_id": condition_id,
        "token_id": str(token_id),
        "outcome_index": int(outcome_index),
        "best_bid": float(best_bid),
        "best_ask": float(best_ask),
        "midpoint": float(midpoint),
        "spread": float(spread),
        "best_bid_depth": float(best_bid_depth),
        "best_ask_depth": float(best_ask_depth),
        "order_min_size": float(min_size),
        "tick_size": float(tick_size),
        "neg_risk": book_neg_risk,
        "fee_rate": float(fee_rate),
        "maker_rebate_rate": float(rebate_rate),
        "reward_min_size": float(reward_min_size)
        if reward_min_size is not None else None,
        "reward_max_spread_cents": float(reward_max_spread)
        if reward_max_spread is not None else None,
        "current_book_within_reward_spread": (
            reward_max_spread is not None
            and spread * 100 <= reward_max_spread
        ),
        "lifecycle_probe_reward_min_size_met": (
            reward_min_size is not None and min_size >= reward_min_size
        ),
        "book_sha256": _canonical_sha256(book),
    }
    result["stage1_intent"] = {
        "side": "BUY",
        "price": float(tick_size),
        "size": float(min_size),
        "notional_pusd": float(tick_size * min_size),
        "post_only": True,
    }
    return result


def select_live_pilot_candidate(
    economics_snapshot,
    target_date,
    plan_out,
    *,
    paper_run_config,
    paper_quote_intents,
    expected_condition_id=None,
    expected_token_id=None,
    now=None,
    book_reader=None,
):
    target_text = ensure_date(target_date).isoformat()
    output = Path(plan_out).resolve()
    if output.exists():
        raise RuntimeError("candidate-plan output path must be new")
    output.parent.mkdir(parents=True, exist_ok=True)
    gate = load_exchange_economics_gate(
        economics_snapshot,
        target_text,
        platform=PLATFORM,
        now=now,
        max_age_hours=2,
    )
    created_at = utc_now(now)
    expected_condition = str(expected_condition_id or "").lower()
    expected_token = str(expected_token_id or "")
    if bool(expected_condition) != bool(expected_token):
        raise RuntimeError("expected condition and token constraints must be supplied together")
    base = {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCK",
        "created_at_utc": created_at.isoformat(),
        "expires_at_utc": (
            created_at + timedelta(seconds=MAX_PLAN_AGE_SECONDS)
        ).isoformat(),
        "target_date": target_text,
        "platform": PLATFORM,
        "settlement_unit": SETTLEMENT_UNIT,
        "exchange_economics_snapshot_id": gate.get("snapshot_id"),
        "exchange_economics_sha256": gate.get("exchange_economics_hash"),
        "economics_gate_ok": gate.get("ok") is True,
        "economics_gate_missing": list(gate.get("missing") or []),
        "selection_is_trading_authorization": False,
        "secret_values_retained": False,
        "selection_policy": {
            "built_in_locations_only": True,
            "positive_fee_and_rebate_required": True,
            "midpoint_interval": [float(MIN_MIDPOINT), float(MAX_MIDPOINT)],
            "max_spread": float(MAX_BOOK_SPREAD),
            "minimum_tick_buy_must_be_nonmarketable": True,
            "book_tick_min_size_and_neg_risk_must_be_current": True,
            "plan_max_age_seconds": MAX_PLAN_AGE_SECONDS,
            "max_single_order_notional_pusd": float(MAX_SINGLE_ORDER_NOTIONAL),
            "successful_current_market_harvest_quote_required": True,
            "expected_bootstrap_scope": {
                "condition_id": expected_condition or None,
                "token_id": expected_token or None,
            },
            "ranking": "spread_asc_then_best_level_depth_desc_then_midpoint_distance",
        },
        "paper_quote_evidence": None,
        "candidate_count": 0,
        "selected": None,
        "alternates": [],
        "missing": [],
    }
    if not gate.get("ok"):
        base["missing"] = ["current_exchange_economics_gate"]
        base["plan_sha256"] = candidate_plan_sha256(base)
        write_json_atomic(output, base, trailing_newline=True)
        return base
    snapshot = json.loads(Path(economics_snapshot).read_text(encoding="utf-8-sig"))
    if snapshot_hash(snapshot) != gate.get("exchange_economics_hash"):
        raise RuntimeError("economics snapshot changed after validation")
    paper_evidence = _load_paper_quote_evidence(
        paper_run_config,
        paper_quote_intents,
        target_date=target_text,
        economics_snapshot_id=gate.get("snapshot_id"),
        economics_hash=gate.get("exchange_economics_hash"),
        now=now,
    )
    base["paper_quote_evidence"] = {
        key: value for key, value in paper_evidence.items() if key != "qualifying"
    }
    built_in_locations = {spec.id for spec in BUILTIN_SPECS}
    markets = [
        row for row in snapshot.get("markets") or []
        if row.get("location_id") in built_in_locations
        and row.get("location_id") == paper_evidence["market_id"]
        and row.get("event_date") == target_text
    ]
    token_map = {}
    for market in markets:
        for outcome_index, token_id in enumerate(market.get("token_ids") or []):
            token_map[str(token_id)] = (market, outcome_index)
    reader = book_reader or ClobClient(timeout=15).get_order_books
    books = reader(list(token_map))
    candidates = []
    for book in books or []:
        if not isinstance(book, dict):
            continue
        token_id = str(book.get("asset_id") or "")
        bound = token_map.get(token_id)
        if bound is None:
            continue
        condition_id = str(bound[0].get("condition_id") or "").lower()
        if expected_condition and (
            condition_id != expected_condition or token_id != expected_token
        ):
            continue
        paper_quote = paper_evidence["qualifying"].get((condition_id, token_id))
        if paper_quote is None:
            continue
        candidate = _candidate_for_book(bound[0], token_id, bound[1], book)
        if candidate is not None:
            candidate["paper_quote_proof"] = paper_quote
            candidates.append(candidate)
    candidates.sort(key=lambda row: (
        row["spread"],
        -(row["best_bid_depth"] + row["best_ask_depth"]),
        abs(row["midpoint"] - 0.5),
        row["location_id"],
        row["token_id"],
    ))
    base["candidate_count"] = len(candidates)
    if candidates:
        base["status"] = "PASS"
        base["selected"] = candidates[0]
        base["alternates"] = candidates[1:1 + MAX_ALTERNATES]
        paper_expiry = _parse_utc(candidates[0]["paper_quote_proof"]["expires_at_utc"])
        ordinary_expiry = created_at + timedelta(seconds=MAX_PLAN_AGE_SECONDS)
        base["expires_at_utc"] = min(ordinary_expiry, paper_expiry).isoformat()
    else:
        base["missing"] = ["current_paper_proved_safe_fee_eligible_book_candidate"]
    base["plan_sha256"] = candidate_plan_sha256(base)
    write_json_atomic(output, base, trailing_newline=True)
    return base


def load_stage1_candidate_gate(
    plan_path,
    target_date,
    *,
    expected_condition_id,
    expected_token_id,
    now=None,
):
    raw = Path(plan_path).read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Stage 1 candidate plan is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Stage 1 candidate plan must be a JSON object")
    selected = dict(payload.get("selected") or {})
    paper = dict(selected.get("paper_quote_proof") or {})
    intent = dict(selected.get("stage1_intent") or {})
    condition = str(expected_condition_id or "").lower()
    token = str(expected_token_id or "")
    current = utc_now(now)
    try:
        created = _parse_utc(payload.get("created_at_utc"))
        expires = _parse_utc(payload.get("expires_at_utc"))
        paper_generated = _parse_utc(paper.get("generated_at_utc"))
        paper_expires = _parse_utc(paper.get("expires_at_utc"))
    except RuntimeError:
        created = expires = paper_generated = paper_expires = datetime.min.replace(
            tzinfo=timezone.utc
        )
    paper_ttl = _decimal(paper.get("quote_ttl_seconds"))
    notional = _decimal(intent.get("notional_pusd"))
    price = _decimal(intent.get("price"))
    size = _decimal(intent.get("size"))
    best_bid = _decimal(selected.get("best_bid"))
    best_ask = _decimal(selected.get("best_ask"))
    spread = _decimal(selected.get("spread"))
    tick_size = _decimal(selected.get("tick_size"))
    min_size = _decimal(selected.get("order_min_size"))
    paper_bid = _decimal(paper.get("bid_price"))
    paper_ask = _decimal(paper.get("ask_price"))
    paper_bid_size = _decimal(paper.get("bid_size"))
    paper_ask_size = _decimal(paper.get("ask_size"))
    paper_risk = _decimal(paper.get("quote_risk_pusd"))
    evidence = dict(payload.get("paper_quote_evidence") or {})
    policy = dict(payload.get("selection_policy") or {})
    expected_scope = dict(policy.get("expected_bootstrap_scope") or {})
    expected_effective_expiry = min(
        created + timedelta(seconds=MAX_PLAN_AGE_SECONDS),
        paper_expires,
    )
    expected_paper_expiry = (
        paper_generated + timedelta(seconds=float(paper_ttl))
        if paper_ttl is not None
        else datetime.min.replace(tzinfo=timezone.utc)
    )
    checks = {
        "schema": payload.get("schema_version") == SCHEMA_VERSION,
        "status": payload.get("status") == "PASS",
        "plan_hash": payload.get("plan_sha256") == candidate_plan_sha256(payload),
        "platform": payload.get("platform") == PLATFORM,
        "settlement_unit": payload.get("settlement_unit") == SETTLEMENT_UNIT,
        "target_date": payload.get("target_date") == ensure_date(target_date).isoformat(),
        "non_authorizing": payload.get("selection_is_trading_authorization") is False,
        "economics": payload.get("economics_gate_ok") is True,
        "created": created <= current,
        "current": current <= expires and current <= paper_expires,
        "expiry_contract": expires == expected_effective_expiry,
        "paper_expiry_contract": paper_expires == expected_paper_expiry,
        "paper_generated_before_plan": paper_generated <= created,
        "paper_ttl": paper_ttl is not None
        and Decimal("0") < paper_ttl <= MAX_PAPER_QUOTE_TTL_SECONDS,
        "condition": str(selected.get("condition_id") or "").lower() == condition,
        "token": str(selected.get("token_id") or "") == token,
        "scope_format": (
            len(condition) == 66
            and condition.startswith("0x")
            and all(character in "0123456789abcdef" for character in condition[2:])
            and token.isdigit()
            and int(token) > 0
        ),
        "constrained_scope": (
            str(expected_scope.get("condition_id") or "").lower() == condition
            and str(expected_scope.get("token_id") or "") == token
        ),
        "paper_condition": str(paper.get("condition_id") or "").lower() == condition,
        "paper_token": str(paper.get("token_id") or "") == token,
        "paper_run": str(paper.get("run_id") or "") == str(evidence.get("run_id") or ""),
        "paper_market": str(paper.get("market_id") or "")
        == str(evidence.get("market_id") or "")
        == str(selected.get("location_id") or ""),
        "paper_economics": (
            paper.get("exchange_economics_snapshot_id")
            == payload.get("exchange_economics_snapshot_id")
            and paper.get("exchange_economics_hash")
            == payload.get("exchange_economics_sha256")
        ),
        "paper_policy": bool(str(paper.get("policy_hash") or "")),
        "paper_permission": paper.get("quote_permission") is True,
        "paper_mutation_disabled": paper.get("live_trade_permission") is False,
        "paper_two_sided": paper.get("two_sided_post_only_intent") is True,
        "paper_zero_reward_assumption": paper.get("reward_and_rebate_assumed_zero") is True,
        "paper_quote_shape": all((
            paper_bid is not None,
            paper_ask is not None,
            Decimal("0") < paper_bid < paper_ask < Decimal("1"),
            paper_bid_size is not None and paper_bid_size > 0,
            paper_ask_size is not None and paper_ask_size > 0,
            paper_risk is not None
            and Decimal("0") < paper_risk <= MAX_BAND_NOTIONAL_PUSD,
            min_size is not None,
            paper_bid_size is not None and min_size is not None
            and paper_bid_size >= min_size,
            paper_ask_size is not None and min_size is not None
            and paper_ask_size >= min_size,
            tick_size is not None,
            paper_bid is not None and tick_size is not None
            and paper_bid % tick_size == 0,
            paper_ask is not None and tick_size is not None
            and paper_ask % tick_size == 0,
            best_ask is not None and paper_bid is not None and paper_bid < best_ask,
            best_bid is not None and paper_ask is not None and paper_ask > best_bid,
        )),
        "paper_hashes": all(
            _is_sha256(evidence.get(field))
            for field in ("run_config_sha256", "quote_intents_sha256")
        ) and _is_sha256(paper.get("quote_row_sha256"))
        and int(evidence.get("quote_intents_row_count") or 0) > 0,
        "current_book": all((
            best_bid is not None,
            best_ask is not None,
            Decimal("0") < best_bid < best_ask < Decimal("1"),
            spread is not None and Decimal("0") < spread <= MAX_BOOK_SPREAD,
        )),
        "intent": all((
            intent.get("side") == "BUY",
            intent.get("post_only") is True,
            price is not None and tick_size is not None and price == tick_size,
            size is not None and min_size is not None and size == min_size,
            best_ask is not None and price is not None and price < best_ask,
            notional is not None and Decimal("0") < notional <= MAX_SINGLE_ORDER_NOTIONAL,
        )),
    }
    missing = [name for name, valid in checks.items() if not valid]
    if missing:
        raise RuntimeError("Stage 1 candidate gate failed: " + ", ".join(missing))
    return {
        "ok": True,
        "plan_sha256": hashlib.sha256(raw).hexdigest(),
        "semantic_plan_sha256": payload["plan_sha256"],
        "condition_id": condition,
        "token_id": token,
        "expires_at_utc": expires.isoformat(),
        "paper_quote_expires_at_utc": paper_expires.isoformat(),
        "paper_run_config_sha256": evidence["run_config_sha256"],
        "paper_quote_intents_sha256": evidence["quote_intents_sha256"],
        "paper_quote_row_sha256": paper["quote_row_sha256"],
        "stage1_intent": dict(intent),
        "tick_size": float(tick_size),
        "order_min_size": float(min_size),
    }


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--economics-snapshot", required=True)
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--paper-run-config", required=True)
    parser.add_argument("--paper-quote-intents", required=True)
    parser.add_argument("--expected-condition-id")
    parser.add_argument("--expected-token-id")
    parser.add_argument("--plan-out", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = select_live_pilot_candidate(
            args.economics_snapshot,
            args.target_date,
            args.plan_out,
            paper_run_config=args.paper_run_config,
            paper_quote_intents=args.paper_quote_intents,
            expected_condition_id=args.expected_condition_id,
            expected_token_id=args.expected_token_id,
        )
    except Exception as exc:
        print(f"candidate selection failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    if result["status"] != "PASS":
        print("candidate selection BLOCK", file=sys.stderr)
        return 1
    print("candidate selection PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
