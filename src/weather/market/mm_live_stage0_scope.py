"""Select and validate a public scope for the no-order Stage 0 bootstrap.

Stage 0 proves wallet/account connectivity, heartbeats, and account-wide
cancel-all without submitting an order. Its plan binds generated International
event/condition/token metadata to an exact plan-time Gamma identity/status
comparison and current public CLOB book rules. Spread, midpoint, depth, fees,
rebates, rewards, paper quote
permission, and expected profitability are deliberately not eligibility gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from weather.market.market_config import config_for_date, ensure_date
from weather.market.market_microstructure_capture import ClobClient
from weather.market.market_registry import BUILTIN_SPECS
from weather.market.mm_policy import utc_now
from weather.operations.live_path_security import (
    assert_no_ambient_market_registry_override,
    validate_nonreparse_directory,
    validate_regular_nonreparse_file,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("mm_live_stage0_scope_plan")
EVENT_METADATA_SCHEMA_VERSION = schema_version("location_market_events")
PLATFORM = "polymarket_global"
SETTLEMENT_UNIT = "pUSD"
PURPOSE = "stage0_heartbeat_account_wide_cancel_all_no_order_scope"
# Derived envelope: 240s maximum portable session + 20s cooperative-cleanup
# reserve + 40s bounded composition/revalidation margin. Review this TTL if
# any envelope changes or observed preparation latency approaches the margin.
PLAN_PREPARATION_MARGIN_SECONDS = 40
MAX_PLAN_AGE_SECONDS = 240 + 20 + PLAN_PREPARATION_MARGIN_SECONDS
MAX_ALTERNATES = 5
GAMMA_EVENT_BY_SLUG_URL = "https://gamma-api.polymarket.com/events/slug/{slug}"
GAMMA_USER_AGENT = "weather-mm-live-stage0-scope/0.1"
# Stage 0/1 plan-generation liveness budget, not a venue or quote-quality
# threshold. One constrained Gamma read must fail closed early enough to leave
# room inside the separately enforced 40-second preparation margin. Review
# against observed endpoint latency if it approaches this first-pilot budget.
GAMMA_TIMEOUT_SECONDS = 15

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
    "scope_policy",
    "scope_count",
    "selected",
    "alternates",
    "missing",
    "plan_sha256",
}
EVENT_METADATA_BINDING_KEYS = {
    "schema_version",
    "file_sha256",
    "generated_at_utc",
    "event_contracts",
}
CURRENT_GAMMA_KEYS = {"checked_at_utc", "event_contracts"}
CURRENT_GAMMA_EVENT_KEYS = {
    "event_slug",
    "event_id",
    "contract",
    "contract_sha256",
    "staged_contract_sha256",
}
GAMMA_CONTRACT_KEYS = {
    "event_slug",
    "event_id",
    "active",
    "closed",
    "markets",
}
GAMMA_MARKET_CONTRACT_KEYS = {
    "market_id",
    "enable_order_book",
    "active",
    "closed",
    "outcomes",
}
GAMMA_OUTCOME_CONTRACT_KEYS = {"index", "name", "token_id"}
EVENT_METADATA_TOP_LEVEL_KEYS = {
    "schema_version",
    "status",
    "owner",
    "generated_at_utc",
    "source",
    "locations",
}
EVENT_METADATA_SOURCE_KEYS = {
    "category_url",
    "gamma_events_query",
    "tag_slug",
    "active",
    "closed",
    "event_count",
    "location_count",
    "api_page_size",
    "api_offsets_fetched",
    "locations_in_api_not_file",
    "locations_in_file_not_api",
}
SCOPE_KEYS = {
    "location_id",
    "event_date",
    "event_slug",
    "question",
    "condition_id",
    "token_id",
    "outcome_index",
    "best_bid",
    "best_ask",
    "order_min_size",
    "tick_size",
    "neg_risk",
    "book_sha256",
}
POLICY_KEYS = {
    "built_in_locations_only",
    "current_condition_token_mapping_required",
    "current_book_identity_and_rules_required",
    "quote_economics_are_not_stage0_gates",
    "ranking_is_nonblocking_diagnostic",
    "event_metadata_age_is_nonblocking_telemetry",
    "plan_max_age_seconds",
    "expected_bootstrap_scope",
    "ranking",
}


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


def stage0_scope_plan_sha256(payload):
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
        raise RuntimeError("Stage 0 evidence has an invalid UTC timestamp") from exc
    if parsed.tzinfo is None:
        raise RuntimeError("Stage 0 evidence timestamp must be timezone-aware")
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


def _json_list(value):
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, list) else None


def _default_gamma_event_reader(event_slug):
    url = GAMMA_EVENT_BY_SLUG_URL.format(
        slug=urllib.parse.quote(str(event_slug or ""), safe=""),
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": GAMMA_USER_AGENT},
    )
    with urllib.request.urlopen(
        request,
        timeout=GAMMA_TIMEOUT_SECONDS,
    ) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("current Gamma event response must be a JSON object")
    return payload


def _valid_event(location, event, *, target, expected_slug):
    if not isinstance(event, dict):
        return None
    event_id = str(event.get("event_id") or "")
    if not (
        event.get("event_date") == target
        and event.get("event_slug") == expected_slug
        and bool(event_id)
        and bool(str(event.get("title") or "").strip())
    ):
        return None
    markets = event.get("markets")
    if not (
        isinstance(markets, list)
        and markets
        and event.get("market_count") == len(markets)
    ):
        return None
    normalized = []
    seen_conditions = set()
    seen_market_ids = set()
    seen_tokens = set()
    for market in markets:
        if not isinstance(market, dict):
            return None
        condition = str(market.get("condition_id") or "").lower()
        market_id = str(market.get("polymarket_market_id") or "")
        outcomes = market.get("outcomes")
        if not (
            _condition_ok(condition)
            and condition not in seen_conditions
            and bool(market_id)
            and market_id not in seen_market_ids
            and market.get("enable_order_book") is True
            and market.get("active") is True
            and market.get("closed") is False
            and bool(str(market.get("question") or "").strip())
            and isinstance(outcomes, list)
            and len(outcomes) == 2
        ):
            return None
        normalized_outcomes = []
        for expected_index, outcome in enumerate(outcomes):
            token = str(outcome.get("token_id") or "") if isinstance(outcome, dict) else ""
            if not (
                isinstance(outcome, dict)
                and outcome.get("index") == expected_index
                and bool(str(outcome.get("name") or "").strip())
                and _token_ok(token)
                and token not in seen_tokens
            ):
                return None
            seen_tokens.add(token)
            normalized_outcomes.append(
                {
                    "outcome_index": expected_index,
                    "outcome_name": str(outcome.get("name") or "").strip(),
                    "token_id": token,
                }
            )
        seen_conditions.add(condition)
        seen_market_ids.add(market_id)
        normalized.append(
            {
                "location_id": location["location_id"],
                "event_date": target,
                "event_slug": expected_slug,
                "event_id": event_id,
                "polymarket_market_id": market_id,
                "condition_id": condition,
                "question": market["question"],
                "outcomes": normalized_outcomes,
            }
        )
    return normalized


def _generated_gamma_contract(event_markets):
    events = {}
    for row in event_markets:
        slug = row["event_slug"]
        event = events.setdefault(
            slug,
            {
                "event_slug": slug,
                "event_id": row["event_id"],
                "active": True,
                "closed": False,
                "markets": {},
            },
        )
        if event["event_id"] != row["event_id"]:
            raise RuntimeError(
                f"generated event identity is ambiguous for {slug}"
            )
        condition = row["condition_id"]
        if condition in event["markets"]:
            raise RuntimeError(
                f"generated condition mapping is ambiguous for {slug}"
            )
        event["markets"][condition] = {
            "market_id": row["polymarket_market_id"],
            "enable_order_book": True,
            "active": True,
            "closed": False,
            "outcomes": [
                {
                    "index": outcome["outcome_index"],
                    "name": outcome["outcome_name"].casefold(),
                    "token_id": outcome["token_id"],
                }
                for outcome in row["outcomes"]
            ],
        }
    return events


def _current_gamma_contract(payload, *, expected_slug):
    if not isinstance(payload, dict):
        raise RuntimeError("current Gamma event response must be a JSON object")
    event_id = str(payload.get("id") or payload.get("eventId") or "")
    event_slug = str(payload.get("slug") or payload.get("eventSlug") or "")
    if not event_id or event_slug != expected_slug:
        raise RuntimeError("current Gamma event identity does not match")
    if payload.get("active") is not True or payload.get("closed") is not False:
        raise RuntimeError("current Gamma event is closed or inactive")
    markets = payload.get("markets")
    if not isinstance(markets, list) or not markets:
        raise RuntimeError("current Gamma event has no market mapping")

    normalized = {}
    seen_tokens = set()
    for market in markets:
        if not isinstance(market, dict):
            raise RuntimeError("current Gamma market mapping is malformed")
        condition = str(
            market.get("conditionId") or market.get("condition_id") or ""
        ).lower()
        market_id = str(market.get("id") or market.get("marketId") or "")
        enable_order_book = (
            market.get("enableOrderBook")
            if "enableOrderBook" in market
            else market.get("enable_order_book")
        )
        if not (
            _condition_ok(condition)
            and condition not in normalized
            and bool(market_id)
            and enable_order_book is True
            and market.get("active") is True
            and market.get("closed") is False
        ):
            raise RuntimeError(
                "current Gamma market identity or status is invalid"
            )
        outcomes = _json_list(market.get("outcomes"))
        token_ids = _json_list(
            market.get("clobTokenIds") or market.get("clob_token_ids")
        )
        if not (
            isinstance(outcomes, list)
            and isinstance(token_ids, list)
            and len(outcomes) == len(token_ids) == 2
        ):
            raise RuntimeError("current Gamma outcome/token mapping is malformed")
        normalized_outcomes = []
        for index, (name_value, token_value) in enumerate(
            zip(outcomes, token_ids, strict=True)
        ):
            name = str(name_value or "").strip()
            token = str(token_value or "")
            if not name or not _token_ok(token) or token in seen_tokens:
                raise RuntimeError(
                    "current Gamma outcome/token mapping is malformed"
                )
            seen_tokens.add(token)
            normalized_outcomes.append(
                {"index": index, "name": name.casefold(), "token_id": token}
            )
        normalized[condition] = {
            "market_id": market_id,
            "enable_order_book": True,
            "active": True,
            "closed": False,
            "outcomes": normalized_outcomes,
        }
    return {
        "event_slug": event_slug,
        "event_id": event_id,
        "active": True,
        "closed": False,
        "markets": normalized,
    }


def _normalized_gamma_contract_ok(contract, *, expected_slug):
    if not isinstance(contract, dict) or set(contract) != GAMMA_CONTRACT_KEYS:
        return False
    if not (
        contract.get("event_slug") == expected_slug
        and isinstance(contract.get("event_id"), str)
        and bool(contract.get("event_id").strip())
        and contract.get("active") is True
        and contract.get("closed") is False
    ):
        return False
    markets = contract.get("markets")
    if not isinstance(markets, dict) or not markets:
        return False
    seen_market_ids = set()
    seen_tokens = set()
    for condition, market in markets.items():
        if not (
            _condition_ok(condition)
            and isinstance(market, dict)
            and set(market) == GAMMA_MARKET_CONTRACT_KEYS
            and isinstance(market.get("market_id"), str)
            and bool(market.get("market_id").strip())
            and market.get("market_id") not in seen_market_ids
            and market.get("enable_order_book") is True
            and market.get("active") is True
            and market.get("closed") is False
        ):
            return False
        outcomes = market.get("outcomes")
        if not isinstance(outcomes, list) or len(outcomes) != 2:
            return False
        seen_market_ids.add(market["market_id"])
        for expected_index, outcome in enumerate(outcomes):
            if not (
                isinstance(outcome, dict)
                and set(outcome) == GAMMA_OUTCOME_CONTRACT_KEYS
                and outcome.get("index") == expected_index
                and isinstance(outcome.get("name"), str)
                and bool(outcome.get("name").strip())
                and isinstance(outcome.get("token_id"), str)
                and _token_ok(outcome.get("token_id"))
                and outcome.get("token_id") not in seen_tokens
            ):
                return False
            seen_tokens.add(outcome["token_id"])
    return True


def _contract_contains_scope(contract, *, condition_id, token_id):
    market = contract.get("markets", {}).get(str(condition_id or "").lower())
    return isinstance(market, dict) and any(
        outcome.get("token_id") == str(token_id or "")
        for outcome in market.get("outcomes", [])
        if isinstance(outcome, dict)
    )


def current_gamma_binding_ok(
    binding,
    *,
    plan_created_at,
    event_slug,
    condition_id,
    token_id,
    staged_contracts,
    require_exact_event,
):
    """Validate auditable current-Gamma evidence bound into a plan.

    The 40-second observation-to-plan bound is the already-owned preparation
    reserve in the 300-second containment envelope, not a market heuristic.
    """

    if not isinstance(binding, dict) or set(binding) != CURRENT_GAMMA_KEYS:
        return False
    try:
        observed_at = _parse_utc(binding.get("checked_at_utc"))
    except RuntimeError:
        return False
    observation_age = plan_created_at - observed_at
    contracts = binding.get("event_contracts")
    if (
        not isinstance(contracts, list)
        or not contracts
        or not isinstance(staged_contracts, dict)
        or not staged_contracts
    ):
        return False
    slugs = []
    event_ids = []
    for row in contracts:
        contract = row.get("contract") if isinstance(row, dict) else None
        staged_contract = (
            staged_contracts.get(row.get("event_slug"))
            if isinstance(row, dict)
            else None
        )
        if not (
            isinstance(row, dict)
            and set(row) == CURRENT_GAMMA_EVENT_KEYS
            and isinstance(row.get("event_slug"), str)
            and bool(row.get("event_slug").strip())
            and isinstance(row.get("event_id"), str)
            and bool(row.get("event_id").strip())
            and _is_sha256(row.get("contract_sha256"))
            and _is_sha256(row.get("staged_contract_sha256"))
            and _normalized_gamma_contract_ok(
                contract,
                expected_slug=row.get("event_slug"),
            )
            and row.get("event_id") == contract.get("event_id")
            and row.get("contract_sha256") == _canonical_sha256(contract)
            and row.get("staged_contract_sha256")
            == row.get("contract_sha256")
            and staged_contract == contract
            and row.get("staged_contract_sha256")
            == _canonical_sha256(staged_contract)
        ):
            return False
        slugs.append(row["event_slug"])
        event_ids.append(row["event_id"])
    matching = [
        row
        for row in contracts
        if row.get("event_slug") == event_slug
        and _contract_contains_scope(
            row.get("contract"),
            condition_id=condition_id,
            token_id=token_id,
        )
    ]
    return (
        timedelta(0) <= observation_age
        <= timedelta(seconds=PLAN_PREPARATION_MARGIN_SECONDS)
        and len(matching) == 1
        and (not require_exact_event or len(contracts) == 1)
        and (require_exact_event or set(slugs) == set(staged_contracts))
        and len(slugs) == len(set(slugs))
        and len(event_ids) == len(set(event_ids))
    )


def current_gamma_event_contract_evidence(
    payload,
    *,
    expected_slug,
    staged_contract,
):
    """Return the public, normalized contract identity for one Gamma event."""

    contract = _current_gamma_contract(payload, expected_slug=expected_slug)
    if contract != staged_contract:
        raise RuntimeError(
            "current Gamma event/condition/token contract differs from staged metadata"
        )
    return contract, {
        "event_slug": expected_slug,
        "event_id": contract["event_id"],
        "contract": contract,
        "contract_sha256": _canonical_sha256(contract),
        "staged_contract_sha256": _canonical_sha256(staged_contract),
    }


def load_current_stage0_event_metadata_gate(
    event_metadata_path,
    target_date,
    *,
    now=None,
    gamma_reader=None,
    expected_condition_id=None,
    expected_token_id=None,
):
    """Bind staged metadata to current Gamma identity and token mapping.

    This current-state gate is used by plan generation, not offline plan
    loaders. Generated-file age remains telemetry: exact current Gamma
    equality is the authority. The staged file is re-read after current-state
    checks so the returned hash cannot describe changed input.
    """

    observed = load_stage0_event_metadata_gate(
        event_metadata_path,
        target_date,
        now=now,
    )
    generated_events = observed["event_contracts"]
    expected_condition = str(expected_condition_id or "").lower()
    expected_token = str(expected_token_id or "")
    if bool(expected_condition) != bool(expected_token):
        raise RuntimeError(
            "current Gamma rebind condition/token constraints must be paired"
        )
    if expected_condition:
        matching_slugs = {
            row["event_slug"]
            for row in observed["event_markets"]
            if row["condition_id"] == expected_condition
            and any(
                outcome["token_id"] == expected_token
                for outcome in row["outcomes"]
            )
        }
        if len(matching_slugs) != 1:
            raise RuntimeError(
                "Stage 0 current Gamma rebind failed: expected "
                "condition/token mapping is not unique"
            )
        event_slug = next(iter(matching_slugs))
        generated_events = {event_slug: generated_events[event_slug]}
    reader = gamma_reader or _default_gamma_event_reader
    current_contracts = []
    for event_slug, generated in sorted(generated_events.items()):
        try:
            _current, current_evidence = current_gamma_event_contract_evidence(
                reader(event_slug),
                expected_slug=event_slug,
                staged_contract=generated,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Stage 0 current Gamma rebind failed for {event_slug}: {exc}"
            ) from exc
        current_contracts.append(current_evidence)

    binding = {key: observed[key] for key in EVENT_METADATA_BINDING_KEYS}
    validate_bound_stage0_event_metadata(
        event_metadata_path,
        binding,
        target_date=target_date,
        now=now,
    )
    observed["current_gamma"] = {
        "checked_at_utc": utc_now(now).isoformat(),
        "event_contracts": current_contracts,
    }
    return observed


def load_stage0_event_metadata_gate(event_metadata_path, target_date, *, now=None):
    """Validate generated event identity without exchange economics."""

    assert_no_ambient_market_registry_override()
    source_path, payload, raw = _read_json_object(
        event_metadata_path,
        label="Stage 0 event metadata",
    )
    target = ensure_date(target_date).isoformat()
    current = utc_now(now)
    try:
        generated = _parse_utc(payload.get("generated_at_utc"))
    except RuntimeError:
        generated = datetime.min.replace(tzinfo=timezone.utc)
        generated_valid = False
    else:
        generated_valid = True
    source = payload.get("source")
    source = source if isinstance(source, dict) else {}
    locations = payload.get("locations")
    locations = locations if isinstance(locations, list) else []
    built_in_ids = {spec.id for spec in BUILTIN_SPECS}
    location_by_id = {
        str(row.get("location_id") or ""): row
        for row in locations
        if isinstance(row, dict)
        and str(row.get("location_id") or "") in built_in_ids
    }
    recognized_location_ids = [
        str(row.get("location_id") or "")
        for row in locations
        if isinstance(row, dict)
        and str(row.get("location_id") or "") in built_in_ids
    ]
    event_markets = []
    for spec in BUILTIN_SPECS:
        location = location_by_id.get(spec.id)
        if location is None or location.get("event_slug_prefix") != spec.slug_prefix:
            continue
        expected_slug = config_for_date(target, spec.id).event_slug
        candidates = [
            event
            for event in location.get("active_events") or []
            if isinstance(event, dict)
            and (
                event.get("event_date") == target
                or event.get("event_slug") == expected_slug
            )
        ]
        if len(candidates) != 1:
            continue
        normalized = _valid_event(
            location,
            candidates[0],
            target=target,
            expected_slug=expected_slug,
        )
        if normalized is not None:
            event_markets.extend(normalized)
    condition_ids = [row["condition_id"] for row in event_markets]
    token_ids = [
        outcome["token_id"]
        for row in event_markets
        for outcome in row["outcomes"]
    ]
    checks = {
        "exact_file_shape": (
            set(payload) == EVENT_METADATA_TOP_LEVEL_KEYS
            and set(source) == EVENT_METADATA_SOURCE_KEYS
            and isinstance(payload.get("locations"), list)
        ),
        "schema": payload.get("schema_version") == EVENT_METADATA_SCHEMA_VERSION,
        "generated_snapshot": (
            payload.get("status") == "generated_snapshot"
            and payload.get("owner") == "weather.operations.location_config_refresh"
        ),
        # Age is telemetry, not authority. The exact target-date active mapping
        # is re-bound to current CLOB identity/rules and the plan itself lasts
        # only five minutes; an invented age cutoff would add no safety proof.
        "valid_timestamp": generated_valid,
        "not_from_future": generated_valid and generated <= current,
        "international_active_source": (
            source.get("category_url")
            == "https://polymarket.com/weather/high-temperature"
            and source.get("tag_slug") == "highest-temperature"
            and source.get("active") is True
            and source.get("closed") is False
            and "gamma-api.polymarket.com/events" in str(
                source.get("gamma_events_query") or ""
            )
            and isinstance(source.get("event_count"), int)
            and not isinstance(source.get("event_count"), bool)
            and source.get("event_count") >= 0
            and isinstance(source.get("location_count"), int)
            and not isinstance(source.get("location_count"), bool)
            and source.get("location_count") >= 0
            and isinstance(source.get("api_page_size"), int)
            and not isinstance(source.get("api_page_size"), bool)
            and source.get("api_page_size") > 0
            and isinstance(source.get("api_offsets_fetched"), list)
            and all(
                isinstance(offset, int)
                and not isinstance(offset, bool)
                and offset >= 0
                for offset in source.get("api_offsets_fetched")
            )
            and isinstance(source.get("locations_in_api_not_file"), list)
            and isinstance(source.get("locations_in_file_not_api"), list)
        ),
        "current_builtin_event": bool(event_markets),
        "unique_builtin_locations": (
            len(recognized_location_ids) == len(set(recognized_location_ids))
        ),
        "unique_conditions": len(condition_ids) == len(set(condition_ids)),
        "unique_tokens": len(token_ids) == len(set(token_ids)),
        "stable": source_path.read_bytes() == raw,
    }
    missing = sorted(name for name, passed in checks.items() if not passed)
    if missing:
        raise RuntimeError(
            "Stage 0 event metadata gate failed: " + ", ".join(missing)
        )
    return {
        "schema_version": EVENT_METADATA_SCHEMA_VERSION,
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "generated_at_utc": generated.isoformat(),
        "target_date": target,
        "event_markets": event_markets,
        "event_contracts": _generated_gamma_contract(event_markets),
    }


def validate_bound_stage0_event_metadata(
    event_metadata_path,
    binding,
    *,
    target_date,
    current_gamma=None,
    now=None,
):
    """Revalidate staged metadata and optional Gamma proof against one plan."""

    observed = load_stage0_event_metadata_gate(
        event_metadata_path,
        target_date,
        now=now,
    )
    expected = dict(binding) if isinstance(binding, dict) else {}
    actual = {key: observed[key] for key in EVENT_METADATA_BINDING_KEYS}
    if set(expected) != EVENT_METADATA_BINDING_KEYS or expected != actual:
        raise RuntimeError("Stage 0 event metadata differs from the scope binding")
    if current_gamma is not None:
        if (
            not isinstance(current_gamma, dict)
            or set(current_gamma) != CURRENT_GAMMA_KEYS
            or not isinstance(current_gamma.get("event_contracts"), list)
            or not current_gamma["event_contracts"]
        ):
            raise RuntimeError("current Gamma evidence is malformed")
        staged_contracts = observed["event_contracts"]
        for row in current_gamma["event_contracts"]:
            slug = row.get("event_slug") if isinstance(row, dict) else None
            staged_contract = staged_contracts.get(slug)
            if not (
                staged_contract is not None
                and row.get("contract") == staged_contract
                and row.get("event_id") == staged_contract.get("event_id")
                and row.get("staged_contract_sha256")
                == _canonical_sha256(staged_contract)
            ):
                raise RuntimeError(
                    "current Gamma evidence differs from bound staged metadata"
                )
    return observed


def _book_levels(book, side):
    levels = []
    for row in book.get(side) or []:
        price = _decimal(row.get("price")) if isinstance(row, dict) else None
        size = _decimal(row.get("size")) if isinstance(row, dict) else None
        if (
            price is not None
            and size is not None
            and Decimal("0") < price < Decimal("1")
            and size > 0
        ):
            levels.append((price, size))
    return levels


def _scope_for_book(event_market, token_id, outcome_index, book):
    token = str(token_id or "")
    condition = str(event_market.get("condition_id") or "").lower()
    if not (
        _token_ok(token)
        and _condition_ok(condition)
        and isinstance(outcome_index, int)
        and not isinstance(outcome_index, bool)
        and outcome_index >= 0
    ):
        return None
    if str(book.get("asset_id") or "") != token:
        return None
    if str(book.get("market") or "").lower() != condition:
        return None
    minimum = _decimal(book.get("min_order_size"))
    tick = _decimal(book.get("tick_size"))
    neg_risk = book.get("neg_risk")
    if not (
        minimum is not None
        and minimum > 0
        and tick is not None
        and Decimal("0") < tick < Decimal("1")
        and isinstance(neg_risk, bool)
    ):
        return None
    bids = _book_levels(book, "bids")
    asks = _book_levels(book, "asks")
    best_bid = max((price for price, _size in bids), default=None)
    best_ask = min((price for price, _size in asks), default=None)
    return {
        "location_id": event_market["location_id"],
        "event_date": event_market["event_date"],
        "event_slug": event_market["event_slug"],
        "question": event_market["question"],
        "condition_id": condition,
        "token_id": token,
        "outcome_index": outcome_index,
        # Diagnostics only: empty, crossed, extreme, or wide books remain
        # eligible for a heartbeat/cancel-all/no-order bootstrap.
        "best_bid": float(best_bid) if best_bid is not None else None,
        "best_ask": float(best_ask) if best_ask is not None else None,
        "order_min_size": float(minimum),
        "tick_size": float(tick),
        "neg_risk": neg_risk,
        "book_sha256": _canonical_sha256(book),
    }


def _soft_rank(scope):
    bid = _decimal(scope.get("best_bid"))
    ask = _decimal(scope.get("best_ask"))
    ordinary = bid is not None and ask is not None and bid < ask
    spread = ask - bid if ordinary else Decimal("Infinity")
    midpoint_distance = (
        abs(((bid + ask) / 2) - Decimal("0.5"))
        if ordinary
        else Decimal("Infinity")
    )
    return (
        0 if ordinary else 1,
        spread,
        midpoint_distance,
        scope["location_id"],
        scope["condition_id"],
        scope["outcome_index"],
        int(scope["token_id"]),
    )


def select_stage0_scope(
    event_metadata,
    target_date,
    plan_out,
    *,
    expected_condition_id=None,
    expected_token_id=None,
    now=None,
    book_reader=None,
    gamma_reader=None,
):
    """Write one immutable, non-authorizing Stage 0 public scope plan."""

    assert_no_ambient_market_registry_override()
    target = ensure_date(target_date).isoformat()
    output_input = Path(plan_out)
    if not output_input.is_absolute():
        raise RuntimeError("Stage 0 scope-plan output path must be absolute")
    output_parent = validate_nonreparse_directory(output_input.parent)
    output = output_parent / output_input.name
    if output.exists() or output.is_symlink():
        raise RuntimeError("Stage 0 scope-plan output path must be new")
    expected_condition = str(expected_condition_id or "").lower()
    expected_token = str(expected_token_id or "")
    if bool(expected_condition) != bool(expected_token):
        raise RuntimeError(
            "expected condition and token constraints must be supplied together"
        )
    if expected_condition and not (
        _condition_ok(expected_condition) and _token_ok(expected_token)
    ):
        raise RuntimeError("expected Stage 0 condition/token scope is malformed")

    metadata = load_current_stage0_event_metadata_gate(
        event_metadata,
        target,
        now=now,
        gamma_reader=gamma_reader,
        expected_condition_id=expected_condition or None,
        expected_token_id=expected_token or None,
    )
    # The plan clock starts only after the current Gamma read completes. This
    # preserves the full five-minute plan lifetime and truthfully orders the
    # current-state evidence before plan creation.
    created = utc_now(now)
    metadata_binding = {
        key: metadata[key] for key in EVENT_METADATA_BINDING_KEYS
    }
    base = {
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
        "scope_policy": {
            "built_in_locations_only": True,
            "current_condition_token_mapping_required": True,
            "current_book_identity_and_rules_required": True,
            "quote_economics_are_not_stage0_gates": True,
            "ranking_is_nonblocking_diagnostic": True,
            "event_metadata_age_is_nonblocking_telemetry": True,
            "plan_max_age_seconds": MAX_PLAN_AGE_SECONDS,
            "expected_bootstrap_scope": {
                "condition_id": expected_condition or None,
                "token_id": expected_token or None,
            },
            "ranking": (
                "two_sided_uncrossed_then_spread_then_midpoint_distance_"
                "then_identity_without_exclusion"
            ),
        },
        "scope_count": 0,
        "selected": None,
        "alternates": [],
        "missing": [],
    }

    token_map = {}
    for event_market in metadata["event_markets"]:
        for outcome in event_market["outcomes"]:
            token_map[outcome["token_id"]] = (
                event_market,
                outcome["outcome_index"],
            )
    reader = book_reader or ClobClient(timeout=15).get_order_books
    books = reader(sorted(token_map, key=int))
    scopes = []
    for book in books or []:
        if not isinstance(book, dict):
            continue
        token = str(book.get("asset_id") or "")
        bound = token_map.get(token)
        if bound is None:
            continue
        condition = str(bound[0].get("condition_id") or "").lower()
        if expected_condition and (
            condition != expected_condition or token != expected_token
        ):
            continue
        scope = _scope_for_book(bound[0], token, bound[1], book)
        if scope is not None:
            scopes.append(scope)
    # Ranking is a convenience heuristic only. It cannot exclude a structural
    # scope for spread, midpoint, depth, or book shape.
    scopes.sort(key=_soft_rank)
    base["scope_count"] = len(scopes)
    if scopes:
        base["selected"] = scopes[0]
        base["alternates"] = scopes[1 : 1 + MAX_ALTERNATES]
        base["status"] = "PASS"
    else:
        base["missing"] = ["current_structurally_bound_stage0_scope"]
    base["plan_sha256"] = stage0_scope_plan_sha256(base)
    _write_new_json(output, base)
    return base


def _scope_shape_ok(scope):
    if not isinstance(scope, dict) or set(scope) != SCOPE_KEYS:
        return False
    best_bid = _decimal(scope.get("best_bid"))
    best_ask = _decimal(scope.get("best_ask"))
    tick = _decimal(scope.get("tick_size"))
    minimum = _decimal(scope.get("order_min_size"))
    outcome_index = scope.get("outcome_index")
    diagnostics_ok = all(
        raw is None
        or parsed is not None
        and Decimal("0") < parsed < Decimal("1")
        for raw, parsed in (
            (scope.get("best_bid"), best_bid),
            (scope.get("best_ask"), best_ask),
        )
    )
    return all(
        (
            isinstance(scope.get("location_id"), str),
            bool(str(scope.get("event_slug") or "").strip()),
            bool(str(scope.get("question") or "").strip()),
            _condition_ok(scope.get("condition_id")),
            _token_ok(scope.get("token_id")),
            isinstance(outcome_index, int),
            not isinstance(outcome_index, bool),
            outcome_index >= 0,
            diagnostics_ok,
            tick is not None,
            Decimal("0") < tick < Decimal("1"),
            minimum is not None,
            minimum > 0,
            isinstance(scope.get("neg_risk"), bool),
            _is_sha256(scope.get("book_sha256")),
        )
    )


def _load_stage0_scope_plan_gate(
    plan_path,
    *,
    target_date=None,
    expected_condition_id=None,
    expected_token_id=None,
    require_unconstrained=False,
    now=None,
):
    assert_no_ambient_market_registry_override()
    _source, payload, raw = _read_json_object(
        plan_path,
        label="Stage 0 scope plan",
    )
    from weather.market.mm_credentials import contains_secret_material

    selected_value = payload.get("selected")
    selected = dict(selected_value) if isinstance(selected_value, dict) else {}
    policy_value = payload.get("scope_policy")
    policy = dict(policy_value) if isinstance(policy_value, dict) else {}
    metadata_value = payload.get("event_metadata")
    metadata = dict(metadata_value) if isinstance(metadata_value, dict) else {}
    gamma_value = payload.get("current_gamma")
    gamma = dict(gamma_value) if isinstance(gamma_value, dict) else {}
    expected_scope_value = policy.get("expected_bootstrap_scope")
    expected_scope = (
        dict(expected_scope_value) if isinstance(expected_scope_value, dict) else {}
    )
    selected_condition = str(selected.get("condition_id") or "").lower()
    selected_token = str(selected.get("token_id") or "")
    condition = (
        selected_condition
        if require_unconstrained
        else str(expected_condition_id or "").lower()
    )
    token = selected_token if require_unconstrained else str(expected_token_id or "")
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
            ensure_date(target_date).isoformat()
            if target_date is not None
            else canonical_target
        )
    except (TypeError, ValueError):
        expected_target = ""
    scope_contract = (
        isinstance(expected_scope_value, dict)
        and set(expected_scope) == {"condition_id", "token_id"}
    )
    if require_unconstrained:
        scope_contract = scope_contract and all(
            expected_scope.get(field) is None
            for field in ("condition_id", "token_id")
        )
        scope_check_name = "unconstrained_scope"
    else:
        scope_contract = scope_contract and (
            str(expected_scope.get("condition_id") or "").lower() == condition
            and str(expected_scope.get("token_id") or "") == token
        )
        scope_check_name = "constrained_scope"
    expected_policy = {
        "built_in_locations_only": True,
        "current_condition_token_mapping_required": True,
        "current_book_identity_and_rules_required": True,
        "quote_economics_are_not_stage0_gates": True,
        "ranking_is_nonblocking_diagnostic": True,
        "event_metadata_age_is_nonblocking_telemetry": True,
        "plan_max_age_seconds": MAX_PLAN_AGE_SECONDS,
        "expected_bootstrap_scope": expected_scope_value,
        "ranking": (
            "two_sided_uncrossed_then_spread_then_midpoint_distance_"
            "then_identity_without_exclusion"
        ),
    }
    alternates = payload.get("alternates")
    scope_count = payload.get("scope_count")
    built_in_locations = {spec.id for spec in BUILTIN_SPECS}
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
            and set(payload) == TOP_LEVEL_KEYS
            and set(selected) == SCOPE_KEYS
            and set(policy) == POLICY_KEYS
            and set(metadata) == EVENT_METADATA_BINDING_KEYS
        ),
        "schema": payload.get("schema_version") == SCHEMA_VERSION,
        "status": payload.get("status") == "PASS",
        "purpose": payload.get("purpose") == PURPOSE,
        "plan_hash": (
            payload.get("plan_sha256") == stage0_scope_plan_sha256(payload)
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
            require_exact_event=not require_unconstrained,
        ),
        "created": created <= current,
        "current": current < expires,
        "expiry_contract": (
            expires == created + timedelta(seconds=MAX_PLAN_AGE_SECONDS)
        ),
        "selection_policy": policy == expected_policy,
        scope_check_name: scope_contract,
        "selected_scope": (
            _scope_shape_ok(selected)
            and selected_condition == condition
            and selected_token == token
            and selected.get("location_id") in built_in_locations
            and selected.get("event_slug") == expected_slug
        ),
        "scope_set": (
            isinstance(scope_count, int)
            and not isinstance(scope_count, bool)
            and scope_count >= 1
            and isinstance(alternates, list)
            and len(alternates) <= MAX_ALTERNATES
            and scope_count >= 1 + len(alternates)
            and all(_scope_shape_ok(row) for row in alternates)
            and payload.get("missing") == []
        ),
    }
    missing = sorted(name for name, passed in checks.items() if not passed)
    if missing:
        label = (
            "Stage 0 scope discovery"
            if require_unconstrained
            else "Stage 0 constrained scope"
        )
        raise RuntimeError(f"{label} gate failed: " + ", ".join(missing))
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
    }


def load_stage0_scope_discovery_gate(plan_path, *, now=None):
    return _load_stage0_scope_plan_gate(
        plan_path,
        require_unconstrained=True,
        now=now,
    )


def load_stage0_scope_gate(
    plan_path,
    target_date,
    *,
    expected_condition_id,
    expected_token_id,
    now=None,
):
    return _load_stage0_scope_plan_gate(
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
    parser.add_argument("--expected-condition-id")
    parser.add_argument("--expected-token-id")
    parser.add_argument("--plan-out", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = select_stage0_scope(
            args.event_metadata,
            args.target_date,
            args.plan_out,
            expected_condition_id=args.expected_condition_id,
            expected_token_id=args.expected_token_id,
        )
    except Exception as exc:
        print(f"Stage 0 scope selection failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    if result["status"] != "PASS":
        print("Stage 0 scope selection BLOCK", file=sys.stderr)
        return 1
    print("Stage 0 scope selection PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
