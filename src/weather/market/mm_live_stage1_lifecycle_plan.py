"""Build a fail-closed plan for one bounded Stage 1 order lifecycle.

Stage 1 verifies direct order submission and cancellation plumbing.  It binds
an exact Stage 0 condition/token scope to current public book and official
market-rule evidence, then describes only the smallest valid nonmarketable
post-only BUY.  Spread, midpoint, depth, paper permission, fee positivity,
rebates, rewards, and expected economics are deliberately not Stage 1 gates.

The plan is selection evidence, not live-trading authorization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from weather.market.market_config import config_for_date, ensure_date
from weather.market.market_microstructure_capture import ClobClient
from weather.market.market_registry import BUILTIN_SPECS
from weather.market.mm_live_stage0_scope import (
    EVENT_METADATA_BINDING_KEYS,
    EVENT_METADATA_SCHEMA_VERSION,
    current_gamma_binding_ok,
    load_current_stage0_event_metadata_gate,
)
from weather.market.mm_official_transport import (
    ALLOWED_TICK_SIZES,
    fetch_market_rule_endpoints,
)
from weather.market.mm_policy import utc_now
from weather.operations.live_path_security import (
    assert_no_ambient_market_registry_override,
    validate_nonreparse_directory,
    validate_regular_nonreparse_file,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("mm_live_stage1_lifecycle_plan")
PLATFORM = "polymarket_global"
SETTLEMENT_UNIT = "pUSD"
PURPOSE = "stage1_minimum_nonmarketable_post_only_buy_lifecycle_plan"

# Stage 1 owner: direct lifecycle safety.  The 10 pUSD bound is the reviewed,
# non-raisable first-pilot per-order loss/notional cap, not a profitability
# heuristic.  The five-minute TTL is derived from the portable session and
# cleanup envelope and matches the immediately upstream Stage 0 scope plan.
MAX_SINGLE_ORDER_NOTIONAL_PUSD = Decimal("10")
MAX_PLAN_AGE_SECONDS = 300

TOP_LEVEL_KEYS = {
    "schema_version",
    "status",
    "purpose",
    "created_at_utc",
    "expires_at_utc",
    "target_date",
    "platform",
    "settlement_unit",
    "event_metadata",
    "current_gamma",
    "selection_is_trading_authorization",
    "secret_values_retained",
    "lifecycle_policy",
    "selected",
    "missing",
    "plan_sha256",
}
POLICY_KEYS = {
    "exact_stage0_scope_required",
    "current_condition_token_mapping_required",
    "current_book_and_official_rules_required",
    "fee_rate_may_be_zero",
    "minimum_tick_buy_must_be_nonmarketable",
    "post_only_required",
    "max_single_order_notional_pusd",
    "stage2_quote_economics_are_not_stage1_gates",
    "plan_max_age_seconds",
    "expected_stage0_scope",
}
SELECTED_KEYS = {
    "location_id",
    "event_date",
    "event_slug",
    "question",
    "condition_id",
    "token_id",
    "outcome_index",
    "best_ask",
    "order_min_size",
    "tick_size",
    "neg_risk",
    "fee_rate",
    "fee_rate_bps",
    "book_sha256",
    "stage1_intent",
}
INTENT_KEYS = {"side", "price", "size", "notional_pusd", "post_only"}
EXPECTED_SCOPE_KEYS = {"condition_id", "token_id"}


def _reject_duplicate_pairs(pairs):
    payload = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key: {key}")
        payload[key] = value
    return payload


def _read_json_object(path, *, label):
    source = validate_regular_nonreparse_file(path)
    try:
        raw = source.read_bytes()
        payload = json.loads(
            raw.decode("utf-8-sig"),
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(f"{label} is not readable JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return source, payload, raw


def _canonical_sha256(payload):
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stage1_lifecycle_plan_sha256(payload):
    """Return the semantic hash for a Stage 1 lifecycle plan."""

    return _canonical_sha256(
        {
            key: value
            for key, value in dict(payload or {}).items()
            if key != "plan_sha256"
        }
    )


def _write_new_json(path: Path, payload: dict) -> None:
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _decimal(value):
    if isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _parse_utc(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Stage 1 lifecycle evidence has an invalid UTC timestamp") from exc
    if parsed.tzinfo is None:
        raise RuntimeError("Stage 1 lifecycle timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _is_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _condition_ok(value):
    condition = str(value or "").lower()
    return (
        len(condition) == 66
        and condition.startswith("0x")
        and all(character in "0123456789abcdef" for character in condition[2:])
    )


def _token_ok(value):
    token = str(value or "")
    return bool(token) and token[0] in "123456789" and token.isdigit()


def _policy(expected_condition, expected_token):
    return {
        "exact_stage0_scope_required": True,
        "current_condition_token_mapping_required": True,
        "current_book_and_official_rules_required": True,
        "fee_rate_may_be_zero": True,
        "minimum_tick_buy_must_be_nonmarketable": True,
        "post_only_required": True,
        "max_single_order_notional_pusd": float(
            MAX_SINGLE_ORDER_NOTIONAL_PUSD
        ),
        "stage2_quote_economics_are_not_stage1_gates": True,
        "plan_max_age_seconds": MAX_PLAN_AGE_SECONDS,
        "expected_stage0_scope": {
            "condition_id": expected_condition,
            "token_id": expected_token,
        },
    }


def _matching_event_market(metadata, expected_condition, expected_token):
    matches = []
    for event_market in metadata["event_markets"]:
        condition = str(event_market.get("condition_id") or "").lower()
        if condition != expected_condition:
            continue
        for outcome in event_market.get("outcomes") or []:
            if str(outcome.get("token_id") or "") == expected_token:
                matches.append((event_market, outcome.get("outcome_index")))
    return matches[0] if len(matches) == 1 else None


def _strict_book_levels(book, side):
    rows = book.get(side)
    if not isinstance(rows, list):
        return None
    levels = []
    for row in rows:
        price = _decimal(row.get("price")) if isinstance(row, dict) else None
        size = _decimal(row.get("size")) if isinstance(row, dict) else None
        if not (
            price is not None
            and Decimal("0") < price < Decimal("1")
            and size is not None
            and size > 0
        ):
            return None
        levels.append((price, size))
    return levels


def _selection_for_evidence(
    event_market,
    outcome_index,
    expected_token,
    book,
    rules,
):
    condition = str(event_market.get("condition_id") or "").lower()
    token = str(rules.get("token_id") or "") if isinstance(rules, dict) else ""
    if not (
        isinstance(book, dict)
        and isinstance(rules, dict)
        and set(rules)
        == {"token_id", "tick_size", "neg_risk", "fee_rate_bps"}
        and token == expected_token
        and str(book.get("asset_id") or "") == token
        and str(book.get("market") or "").lower() == condition
    ):
        return None, "current_public_book_and_official_rule_identity"

    minimum = _decimal(book.get("min_order_size"))
    book_tick = _decimal(book.get("tick_size"))
    rule_tick = _decimal(rules.get("tick_size"))
    fee_rate_bps = _decimal(rules.get("fee_rate_bps"))
    book_neg_risk = book.get("neg_risk")
    rule_neg_risk = rules.get("neg_risk")
    bids = _strict_book_levels(book, "bids")
    asks = _strict_book_levels(book, "asks")
    if not (
        minimum is not None
        and minimum > 0
        and book_tick in ALLOWED_TICK_SIZES
        and rule_tick in ALLOWED_TICK_SIZES
        and isinstance(book_neg_risk, bool)
        and isinstance(rule_neg_risk, bool)
        and bids is not None
        and asks is not None
    ):
        return None, "valid_current_public_book_and_official_rules"
    if book_tick != rule_tick or book_neg_risk is not rule_neg_risk:
        return None, "exact_book_rule_tick_and_neg_risk"
    if fee_rate_bps is None or fee_rate_bps < 0:
        return None, "finite_nonnegative_current_fee_rate"

    best_ask = min((price for price, _size in asks), default=None)
    if best_ask is not None and not book_tick < best_ask:
        return None, "minimum_tick_buy_nonmarketable"
    notional = book_tick * minimum
    if not Decimal("0") < notional <= MAX_SINGLE_ORDER_NOTIONAL_PUSD:
        return None, "minimum_order_notional_within_10_pusd"

    fee_rate = fee_rate_bps / Decimal("10000")
    return {
        "location_id": event_market["location_id"],
        "event_date": event_market["event_date"],
        "event_slug": event_market["event_slug"],
        "question": event_market["question"],
        "condition_id": condition,
        "token_id": token,
        "outcome_index": outcome_index,
        "best_ask": float(best_ask) if best_ask is not None else None,
        "order_min_size": float(minimum),
        "tick_size": float(book_tick),
        "neg_risk": book_neg_risk,
        "fee_rate": float(fee_rate),
        "fee_rate_bps": float(fee_rate_bps),
        "book_sha256": _canonical_sha256(book),
        "stage1_intent": {
            "side": "BUY",
            "price": float(book_tick),
            "size": float(minimum),
            "notional_pusd": float(notional),
            "post_only": True,
        },
    }, None


def select_stage1_lifecycle_plan(
    event_metadata,
    target_date,
    plan_out,
    *,
    expected_condition_id,
    expected_token_id,
    now=None,
    book_reader=None,
    rule_reader=None,
    gamma_reader=None,
):
    """Write one immutable, non-authorizing Stage 1 lifecycle plan."""

    assert_no_ambient_market_registry_override()
    target = ensure_date(target_date).isoformat()
    output_input = Path(plan_out)
    if not output_input.is_absolute():
        raise RuntimeError("Stage 1 lifecycle-plan output path must be absolute")
    output_parent = validate_nonreparse_directory(output_input.parent)
    output = output_parent / output_input.name
    if output.exists() or output.is_symlink():
        raise RuntimeError("Stage 1 lifecycle-plan output path must be new")

    expected_condition = str(expected_condition_id or "").lower()
    expected_token = str(expected_token_id or "")
    if not (
        _condition_ok(expected_condition)
        and _token_ok(expected_token)
    ):
        raise RuntimeError("expected Stage 0 condition/token scope is malformed")

    metadata = load_current_stage0_event_metadata_gate(
        event_metadata,
        target,
        now=now,
        gamma_reader=gamma_reader,
        expected_condition_id=expected_condition,
        expected_token_id=expected_token,
    )
    # Start the plan lifetime after current Gamma has been read and compared.
    created = utc_now(now)
    metadata_binding = {
        key: metadata[key] for key in EVENT_METADATA_BINDING_KEYS
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCK",
        "purpose": PURPOSE,
        "created_at_utc": created.isoformat(),
        "expires_at_utc": (
            created + timedelta(seconds=MAX_PLAN_AGE_SECONDS)
        ).isoformat(),
        "target_date": target,
        "platform": PLATFORM,
        "settlement_unit": SETTLEMENT_UNIT,
        "event_metadata": metadata_binding,
        "current_gamma": metadata["current_gamma"],
        "selection_is_trading_authorization": False,
        "secret_values_retained": False,
        "lifecycle_policy": _policy(expected_condition, expected_token),
        "selected": None,
        "missing": [],
    }

    bound = _matching_event_market(
        metadata,
        expected_condition,
        expected_token,
    )
    if bound is None:
        payload["missing"] = ["active_stage0_condition_token_mapping"]
    else:
        reader = book_reader or ClobClient(timeout=15).get_order_books
        books = reader([expected_token])
        if not (
            isinstance(books, list)
            and len(books) == 1
            and isinstance(books[0], dict)
        ):
            payload["missing"] = ["one_current_public_order_book"]
        else:
            rules_reader = rule_reader or fetch_market_rule_endpoints
            rules = rules_reader(expected_token)
            selected, missing = _selection_for_evidence(
                bound[0],
                bound[1],
                expected_token,
                books[0],
                rules,
            )
            if selected is None:
                payload["missing"] = [missing]
            else:
                payload["selected"] = selected
                payload["status"] = "PASS"

    payload["plan_sha256"] = stage1_lifecycle_plan_sha256(payload)
    _write_new_json(output, payload)
    return payload


def _selected_shape_ok(selected):
    if not isinstance(selected, dict) or set(selected) != SELECTED_KEYS:
        return False
    intent = selected.get("stage1_intent")
    if not isinstance(intent, dict) or set(intent) != INTENT_KEYS:
        return False

    best_ask = _decimal(selected.get("best_ask"))
    minimum = _decimal(selected.get("order_min_size"))
    tick = _decimal(selected.get("tick_size"))
    fee_rate = _decimal(selected.get("fee_rate"))
    fee_rate_bps = _decimal(selected.get("fee_rate_bps"))
    price = _decimal(intent.get("price"))
    size = _decimal(intent.get("size"))
    notional = _decimal(intent.get("notional_pusd"))
    outcome_index = selected.get("outcome_index")
    fee_binding_ok = (
        fee_rate is not None
        and fee_rate_bps is not None
        and fee_rate >= 0
        and fee_rate_bps >= 0
        and fee_rate == fee_rate_bps / Decimal("10000")
    )
    intent_binding_ok = (
        tick is not None
        and minimum is not None
        and price == tick
        and size == minimum
        and notional is not None
        and notional == tick * minimum
        and Decimal("0") < notional <= MAX_SINGLE_ORDER_NOTIONAL_PUSD
    )
    nonmarketable_ok = (
        best_ask is None
        or tick is not None
        and tick < best_ask
    )
    return all(
        (
            isinstance(selected.get("location_id"), str),
            bool(str(selected.get("event_slug") or "").strip()),
            bool(str(selected.get("question") or "").strip()),
            _condition_ok(selected.get("condition_id")),
            _token_ok(selected.get("token_id")),
            isinstance(outcome_index, int),
            not isinstance(outcome_index, bool),
            outcome_index in (0, 1),
            selected.get("best_ask") is None
            or best_ask is not None
            and Decimal("0") < best_ask < Decimal("1"),
            minimum is not None and minimum > 0,
            tick in ALLOWED_TICK_SIZES,
            isinstance(selected.get("neg_risk"), bool),
            fee_binding_ok,
            _is_sha256(selected.get("book_sha256")),
            intent.get("side") == "BUY",
            intent.get("post_only") is True,
            intent_binding_ok,
            nonmarketable_ok,
        )
    )


def _load_stage1_lifecycle_plan_gate(
    plan_path,
    *,
    target_date=None,
    expected_condition_id=None,
    expected_token_id=None,
    use_bound_scope=False,
    now=None,
):
    assert_no_ambient_market_registry_override()
    _source, payload, raw = _read_json_object(
        plan_path,
        label="Stage 1 lifecycle plan",
    )
    from weather.market.mm_credentials import contains_secret_material

    selected_value = payload.get("selected")
    selected = dict(selected_value) if isinstance(selected_value, dict) else {}
    policy_value = payload.get("lifecycle_policy")
    policy = dict(policy_value) if isinstance(policy_value, dict) else {}
    metadata_value = payload.get("event_metadata")
    metadata = dict(metadata_value) if isinstance(metadata_value, dict) else {}
    gamma_value = payload.get("current_gamma")
    gamma = dict(gamma_value) if isinstance(gamma_value, dict) else {}
    scope_value = policy.get("expected_stage0_scope")
    scope = dict(scope_value) if isinstance(scope_value, dict) else {}

    if use_bound_scope:
        condition = str(scope.get("condition_id") or "").lower()
        token = str(scope.get("token_id") or "")
    else:
        condition = str(expected_condition_id or "").lower()
        token = str(expected_token_id or "")
    current = utc_now(now)
    try:
        created = _parse_utc(payload.get("created_at_utc"))
        expires = _parse_utc(payload.get("expires_at_utc"))
        metadata_generated = _parse_utc(metadata.get("generated_at_utc"))
    except RuntimeError:
        invalid = datetime.min.replace(tzinfo=timezone.utc)
        created = expires = metadata_generated = invalid
    try:
        canonical_target = ensure_date(payload.get("target_date")).isoformat()
    except (TypeError, ValueError):
        canonical_target = ""
    try:
        expected_target = (
            canonical_target
            if use_bound_scope
            else ensure_date(target_date).isoformat()
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Stage 1 lifecycle target date is invalid") from exc
    expected_policy = _policy(condition, token)
    built_in_locations = {spec.id for spec in BUILTIN_SPECS}
    selected_condition = str(selected.get("condition_id") or "").lower()
    selected_token = str(selected.get("token_id") or "")
    try:
        expected_slug = config_for_date(
            expected_target,
            selected.get("location_id"),
        ).event_slug
    except (KeyError, TypeError, ValueError):
        expected_slug = ""

    checks = {
        "exact_schema_shape": (
            isinstance(selected_value, dict)
            and isinstance(policy_value, dict)
            and isinstance(metadata_value, dict)
            and isinstance(gamma_value, dict)
            and isinstance(scope_value, dict)
            and set(payload) == TOP_LEVEL_KEYS
            and set(selected) == SELECTED_KEYS
            and set(policy) == POLICY_KEYS
            and set(metadata) == EVENT_METADATA_BINDING_KEYS
            and set(scope) == EXPECTED_SCOPE_KEYS
        ),
        "schema": payload.get("schema_version") == SCHEMA_VERSION,
        "status": payload.get("status") == "PASS",
        "purpose": payload.get("purpose") == PURPOSE,
        "plan_hash": (
            payload.get("plan_sha256")
            == stage1_lifecycle_plan_sha256(payload)
        ),
        "platform": payload.get("platform") == PLATFORM,
        "settlement_unit": payload.get("settlement_unit") == SETTLEMENT_UNIT,
        "target_date": (
            payload.get("target_date") == canonical_target == expected_target
            and selected.get("event_date") == expected_target
        ),
        "non_authorizing": (
            payload.get("selection_is_trading_authorization") is False
        ),
        "secret_free": (
            payload.get("secret_values_retained") is False
            and not contains_secret_material(payload)
        ),
        "event_metadata_binding": (
            metadata.get("schema_version") == EVENT_METADATA_SCHEMA_VERSION
            and _is_sha256(metadata.get("file_sha256"))
            and metadata_generated <= created
        ),
        "current_gamma_binding": current_gamma_binding_ok(
            gamma,
            plan_created_at=created,
            event_slug=selected.get("event_slug"),
            condition_id=condition,
            token_id=token,
            staged_contracts=metadata.get("event_contracts"),
            require_exact_event=True,
        ),
        "created": created <= current,
        "current": current < expires,
        "expiry_contract": (
            expires == created + timedelta(seconds=MAX_PLAN_AGE_SECONDS)
        ),
        "selection_policy": policy == expected_policy,
        "exact_stage0_scope": (
            _condition_ok(condition)
            and _token_ok(token)
            and selected_condition == condition
            and selected_token == token
        ),
        "selected_lifecycle": (
            _selected_shape_ok(selected)
            and selected.get("location_id") in built_in_locations
            and selected.get("event_slug") == expected_slug
        ),
        "complete": payload.get("missing") == [],
    }
    missing = sorted(name for name, passed in checks.items() if not passed)
    if missing:
        raise RuntimeError(
            "Stage 1 lifecycle-plan gate failed: " + ", ".join(missing)
        )
    return {
        "ok": True,
        "plan_sha256": hashlib.sha256(raw).hexdigest(),
        "semantic_plan_sha256": payload["plan_sha256"],
        "target_date": expected_target,
        "market_id": selected["location_id"],
        "event_slug": selected["event_slug"],
        "condition_id": condition,
        "token_id": token,
        "created_at_utc": created.isoformat(),
        "expires_at_utc": expires.isoformat(),
        "event_metadata": dict(metadata),
        "current_gamma": dict(gamma),
        "tick_size": float(selected["tick_size"]),
        "order_min_size": float(selected["order_min_size"]),
        "neg_risk": selected["neg_risk"],
        "fee_rate": float(selected["fee_rate"]),
        "fee_rate_bps": float(selected["fee_rate_bps"]),
        "best_ask": selected["best_ask"],
        "stage1_intent": dict(selected["stage1_intent"]),
    }


def load_stage1_lifecycle_discovery_gate(plan_path, *, now=None):
    """Load a plan using its exact, mandatory Stage 0 scope binding."""

    return _load_stage1_lifecycle_plan_gate(
        plan_path,
        use_bound_scope=True,
        now=now,
    )


def load_stage1_lifecycle_plan_gate(
    plan_path,
    target_date,
    *,
    expected_condition_id,
    expected_token_id,
    now=None,
):
    """Load a plan only when an external Stage 0 scope matches exactly."""

    return _load_stage1_lifecycle_plan_gate(
        plan_path,
        target_date=target_date,
        expected_condition_id=expected_condition_id,
        expected_token_id=expected_token_id,
        now=now,
    )


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-metadata", required=True)
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--expected-condition-id", required=True)
    parser.add_argument("--expected-token-id", required=True)
    parser.add_argument("--plan-out", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = select_stage1_lifecycle_plan(
            args.event_metadata,
            args.target_date,
            args.plan_out,
            expected_condition_id=args.expected_condition_id,
            expected_token_id=args.expected_token_id,
        )
    except Exception as exc:
        print(
            f"Stage 1 lifecycle-plan selection failed: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1
    if result["status"] != "PASS":
        print("Stage 1 lifecycle-plan selection BLOCK", file=sys.stderr)
        return 1
    print("Stage 1 lifecycle-plan selection PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
