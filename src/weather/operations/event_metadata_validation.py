"""Validate active-day Polymarket event metadata before evidence is countable."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from weather.market.market_config import config_for_date, date_from_event_slug, ensure_date
from weather.market.market_registry import all_specs, spec_for_id
from weather.market.polymarket_client import PolymarketClient
from weather.paths import config_path, data_path
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("event_metadata_validation")
DEFAULT_LOCATIONS = config_path("locations.json")
DEFAULT_EVENT_METADATA = config_path("location_market_events.json")
DEFAULT_JSON_OUT = data_path("backtest", "event_metadata_validation.json")
DEFAULT_REPORT_OUT = data_path("backtest", "event_metadata_validation_report.md")
DEFAULT_MAX_AGE_HOURS = 36.0
REFRESH_COMMAND = (
    "python -m weather.operations.location_config_refresh "
    "--locations config/locations.json --event-metadata config/location_market_events.json"
)
VALIDATION_COMMAND = (
    "python -m weather.operations.event_metadata_validation "
    "--target-date <YYYY-MM-DD>"
)
MANUAL_REVIEW_COMMAND = (
    "review Polymarket weather event template, outcome layout, and CLOB token mapping "
    "before counting active-day evidence"
)


def utc_now(value: str | datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    else:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return utc_now(str(value))
    except (TypeError, ValueError):
        return None


def load_json(path: str | Path, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    result = str(value).strip()
    return result or None


def bool_value(value: Any, default: bool | None = None) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y", "active", "enabled"}:
        return True
    if lowered in {"0", "false", "no", "n", "inactive", "closed", "disabled"}:
        return False
    return default


def event_slug(event: dict[str, Any]) -> str | None:
    return text(event.get("event_slug") or event.get("slug") or event.get("eventSlug"))


def event_id(event: dict[str, Any]) -> str | None:
    return text(event.get("event_id") or event.get("id") or event.get("eventId"))


def event_date(event: dict[str, Any]) -> str | None:
    return text(event.get("event_date")) or (
        date_from_event_slug(event_slug(event)) or None
    ) and date_from_event_slug(event_slug(event)).isoformat()


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validation_hash_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "validation_hash"}


def validation_content_hash(payload: dict[str, Any]) -> str:
    return stable_hash(_validation_hash_payload(payload))


def _outcomes_and_tokens(market: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(market.get("outcomes"), list) and all(isinstance(row, dict) for row in market.get("outcomes") or []):
        rows = []
        for index, outcome in enumerate(market.get("outcomes") or []):
            rows.append({
                "index": int(outcome.get("index") if outcome.get("index") not in (None, "") else index),
                "name": text(outcome.get("name") or outcome.get("outcome")),
                "token_id": text(outcome.get("token_id") or outcome.get("clob_token_id")),
            })
        return rows

    outcome_tokens = market.get("outcome_tokens")
    if isinstance(outcome_tokens, dict):
        names = ["Yes", "No"]
        extra = sorted(key for key in outcome_tokens if str(key).lower() not in {"yes", "no"})
        rows = []
        for index, name in enumerate([*names, *extra]):
            token_id = outcome_tokens.get(name)
            if token_id is None:
                token_id = outcome_tokens.get(name.lower())
            rows.append({"index": index, "name": name, "token_id": text(token_id)})
        return rows

    outcomes = parse_json_list(market.get("outcomes") or market.get("outcome_labels"))
    token_ids = parse_json_list(market.get("clobTokenIds") or market.get("clob_token_ids"))
    rows = []
    for index in range(max(len(outcomes), len(token_ids))):
        rows.append({
            "index": index,
            "name": text(outcomes[index]) if index < len(outcomes) else None,
            "token_id": text(token_ids[index]) if index < len(token_ids) else None,
        })
    return rows


def normalized_market(market: dict[str, Any]) -> dict[str, Any]:
    outcomes = _outcomes_and_tokens(market)
    yes_token_id = next(
        (row.get("token_id") for row in outcomes if str(row.get("name") or "").lower() == "yes"),
        text(market.get("yes_token_id")),
    )
    no_token_id = next(
        (row.get("token_id") for row in outcomes if str(row.get("name") or "").lower() == "no"),
        text(market.get("no_token_id")),
    )
    return {
        "polymarket_market_id": text(
            market.get("polymarket_market_id") or market.get("market_id") or market.get("id") or market.get("marketId")
        ),
        "condition_id": text(market.get("condition_id") or market.get("conditionId")),
        "range_label": text(
            market.get("range_label")
            or market.get("groupItemTitle")
            or market.get("group_item_title")
            or market.get("question")
        ),
        "question": text(market.get("question")),
        "enable_order_book": bool_value(
            market.get("enable_order_book") if "enable_order_book" in market else market.get("enableOrderBook"),
            default=None,
        ),
        "active": bool_value(market.get("active"), default=None),
        "closed": bool_value(market.get("closed"), default=None),
        "outcomes": outcomes,
        "yes_token_id": yes_token_id,
        "no_token_id": no_token_id,
    }


def _market_sort_key(market: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(market.get("range_label") or ""),
        str(market.get("polymarket_market_id") or ""),
        str(market.get("condition_id") or ""),
    )


def _token_hash_rows(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for market in sorted(markets, key=_market_sort_key):
        rows.append({
            "range_label": market.get("range_label"),
            "polymarket_market_id": market.get("polymarket_market_id"),
            "condition_id": market.get("condition_id"),
            "enable_order_book": market.get("enable_order_book"),
            "active": market.get("active"),
            "closed": market.get("closed"),
            "outcomes": [
                {
                    "index": row.get("index"),
                    "name": row.get("name"),
                    "token_id": row.get("token_id"),
                }
                for row in market.get("outcomes") or []
            ],
        })
    return rows


def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    markets = [
        normalized_market(row)
        for row in (event.get("markets") or [])
        if isinstance(row, dict)
    ]
    slug = event_slug(event)
    return {
        "event_id": event_id(event),
        "event_slug": slug,
        "event_date": event_date(event),
        "event_url": text(event.get("event_url")) or (f"https://polymarket.com/event/{slug}" if slug else None),
        "title": text(event.get("title") or event.get("question")),
        "end_date": text(event.get("end_date") or event.get("endDate")),
        "resolution_source_url": text(event.get("resolution_source_url") or event.get("resolutionSource")),
        "active": bool_value(event.get("active"), default=None),
        "closed": bool_value(event.get("closed"), default=None),
        "market_count": int(event.get("market_count") or len(markets) or 0),
        "markets": sorted(markets, key=_market_sort_key),
        "token_map_hash": stable_hash(_token_hash_rows(markets)) if markets else None,
        "condition_id_hash": stable_hash([
            row.get("condition_id")
            for row in sorted(markets, key=_market_sort_key)
        ]) if markets else None,
        "outcome_layout_hash": stable_hash([
            [outcome.get("name") for outcome in row.get("outcomes") or []]
            for row in sorted(markets, key=_market_sort_key)
        ]) if markets else None,
    }


def selected_specs(markets: str | list[str] | tuple[str, ...] | None = None):
    if markets in (None, "", "all"):
        return all_specs()
    if isinstance(markets, str):
        ids = [item.strip() for item in markets.split(",") if item.strip()]
    else:
        ids = [str(item).strip() for item in markets or [] if str(item).strip()]
    return [spec_for_id(item) for item in ids]


def locations_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("id")): row
        for row in payload.get("locations") or []
        if isinstance(row, dict) and row.get("id")
    }


def generated_locations_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("location_id")): row
        for row in payload.get("locations") or []
        if isinstance(row, dict) and row.get("location_id")
    }


def issue(
    code: str,
    category: str,
    detail: str,
    *,
    field: str | None = None,
    expected: Any = None,
    actual: Any = None,
    remediation_command: str | None = None,
    recoverable_same_day: bool = False,
    manual_review_required: bool = False,
) -> dict[str, Any]:
    return {
        "code": code,
        "category": category,
        "field": field,
        "detail": detail,
        "expected": expected,
        "actual": actual,
        "status": "BLOCK",
        "remediation_command": remediation_command or (
            MANUAL_REVIEW_COMMAND if manual_review_required else VALIDATION_COMMAND
        ),
        "recoverable_same_day": bool(recoverable_same_day),
        "manual_review_required": bool(manual_review_required),
    }


def stale_issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    return issue(
        code,
        "stale_generated_metadata",
        detail,
        remediation_command=REFRESH_COMMAND,
        recoverable_same_day=True,
        manual_review_required=False,
        **extra,
    )


def mismatch_issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    return issue(
        code,
        "metadata_mismatch",
        detail,
        remediation_command=MANUAL_REVIEW_COMMAND,
        recoverable_same_day=False,
        manual_review_required=True,
        **extra,
    )


def ambiguous_issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    return issue(
        code,
        "ambiguous_event_metadata",
        detail,
        remediation_command=MANUAL_REVIEW_COMMAND,
        recoverable_same_day=False,
        manual_review_required=True,
        **extra,
    )


def blank_token_issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    return issue(
        code,
        "blank_token_metadata",
        detail,
        remediation_command=MANUAL_REVIEW_COMMAND,
        recoverable_same_day=False,
        manual_review_required=True,
        **extra,
    )


def _metadata_age_issue(metadata_payload: dict[str, Any], now: datetime, max_age_hours: float) -> dict[str, Any] | None:
    generated_at = parse_timestamp(metadata_payload.get("generated_at_utc"))
    if generated_at is None:
        return stale_issue(
            "generated_metadata_timestamp_missing",
            "generated location_market_events metadata has no valid generated_at_utc timestamp",
            field="generated_at_utc",
        )
    age_hours = (now - generated_at).total_seconds() / 3600.0
    if age_hours > float(max_age_hours):
        return stale_issue(
            "generated_metadata_stale",
            f"generated location_market_events metadata is {age_hours:.1f} hours old",
            field="generated_at_utc",
            expected=f"<= {float(max_age_hours):.1f}h",
            actual=metadata_payload.get("generated_at_utc"),
        )
    return None


def _event_candidates(location_row: dict[str, Any], target_date: date, expected_slug: str) -> list[dict[str, Any]]:
    target = target_date.isoformat()
    return [
        event
        for event in location_row.get("active_events") or []
        if isinstance(event, dict)
        and (event.get("event_date") == target or event_slug(event) == expected_slug)
    ]


def _event_index(live_events: Any) -> dict[str, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    if isinstance(live_events, dict) and event_slug(live_events):
        events = [live_events]
    elif isinstance(live_events, dict):
        for key in ("events", "live_events"):
            if isinstance(live_events.get(key), list):
                events.extend(row for row in live_events.get(key) or [] if isinstance(row, dict))
        for value in live_events.values():
            if isinstance(value, dict) and event_slug(value):
                events.append(value)
            elif isinstance(value, list):
                events.extend(row for row in value if isinstance(row, dict) and event_slug(row))
    elif isinstance(live_events, list):
        events = [row for row in live_events if isinstance(row, dict)]
    indexed: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        slug = event_slug(event)
        if slug:
            indexed.setdefault(slug, []).append(event)
    return indexed


def _fetch_live_events(specs, target_date: date, timeout_seconds: float) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    indexed: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    for spec in specs:
        try:
            event = PolymarketClient(
                market_id=spec.id,
                target_date=target_date,
                timeout=timeout_seconds,
            ).get_event()
            slug = event_slug(event)
            if slug:
                indexed.setdefault(slug, []).append(event)
            else:
                errors[spec.id] = "live Gamma event response has no slug"
        except Exception as exc:  # noqa: BLE001 - validation must report all markets.
            errors[spec.id] = f"{type(exc).__name__}: {exc}"
    return indexed, errors


def _token_quality_issues(normalized: dict[str, Any], source: str) -> list[dict[str, Any]]:
    issues = []
    markets = normalized.get("markets") or []
    if not markets:
        issues.append(stale_issue(
            f"{source}_token_map_missing",
            f"{source} event metadata does not include normalized market/token rows",
            field=f"{source}.markets",
        ) if source == "generated" else blank_token_issue(
            f"{source}_token_map_missing",
            f"{source} Gamma event has no market/token rows",
            field=f"{source}.markets",
        ))
        return issues
    for market in markets:
        label = market.get("range_label") or market.get("polymarket_market_id") or "unknown range"
        if not market.get("condition_id"):
            issues.append(blank_token_issue(
                f"{source}_condition_id_blank",
                f"{source} market {label} has no condition id",
                field=f"{source}.markets.condition_id",
            ))
        if market.get("enable_order_book") is False:
            issues.append(blank_token_issue(
                f"{source}_order_book_disabled",
                f"{source} market {label} has order-book disabled",
                field=f"{source}.markets.enable_order_book",
            ))
        if market.get("closed") is True or market.get("active") is False:
            issues.append(mismatch_issue(
                f"{source}_market_inactive",
                f"{source} market {label} is closed or inactive",
                field=f"{source}.markets.active",
            ))
        names = {str(row.get("name") or "").lower(): row for row in market.get("outcomes") or []}
        for outcome_name in ("yes", "no"):
            outcome = names.get(outcome_name)
            if not outcome or not outcome.get("token_id"):
                issues.append(blank_token_issue(
                    f"{source}_{outcome_name}_token_id_blank",
                    f"{source} market {label} has no {outcome_name.upper()} CLOB token id",
                    field=f"{source}.markets.outcomes.{outcome_name}.token_id",
                ))
    return issues


def _compare_events(generated: dict[str, Any], live: dict[str, Any]) -> list[dict[str, Any]]:
    issues = []
    for field in ("event_id", "event_slug", "event_date", "end_date", "resolution_source_url"):
        expected = generated.get(field)
        actual = live.get(field)
        if expected not in (None, "") and actual not in (None, "") and expected != actual:
            issues.append(mismatch_issue(
                f"{field}_mismatch",
                f"generated {field} does not match live Gamma",
                field=field,
                expected=expected,
                actual=actual,
            ))
    if generated.get("market_count") and live.get("market_count") and generated.get("market_count") != live.get("market_count"):
        issues.append(mismatch_issue(
            "market_count_mismatch",
            "generated market count does not match live Gamma",
            field="market_count",
            expected=generated.get("market_count"),
            actual=live.get("market_count"),
        ))
    for field in ("outcome_layout_hash", "condition_id_hash", "token_map_hash"):
        expected = generated.get(field)
        actual = live.get(field)
        if expected and actual and expected != actual:
            issues.append(mismatch_issue(
                f"{field}_mismatch",
                f"generated {field} does not match live Gamma/CLOB metadata",
                field=field,
                expected=expected,
                actual=actual,
            ))
    if live.get("active") is False or live.get("closed") is True:
        issues.append(mismatch_issue(
            "live_event_inactive",
            "live Gamma event is closed or inactive for the target date",
            field="live_event.active",
            actual={"active": live.get("active"), "closed": live.get("closed")},
        ))
    return issues


def _first_remediation(issues: list[dict[str, Any]]) -> str | None:
    for row in issues:
        if row.get("remediation_command"):
            return row.get("remediation_command")
    return None


def _market_validation_row(
    spec,
    *,
    target_date: date,
    locations: dict[str, dict[str, Any]],
    generated_locations: dict[str, dict[str, Any]],
    metadata_payload: dict[str, Any],
    live_index: dict[str, list[dict[str, Any]]],
    live_errors: dict[str, str],
    now: datetime,
    max_age_hours: float,
) -> dict[str, Any]:
    config = config_for_date(target_date, spec.id)
    expected_slug = config.event_slug
    issues: list[dict[str, Any]] = []

    age_issue = _metadata_age_issue(metadata_payload, now, max_age_hours)
    if age_issue:
        issues.append(age_issue)

    durable_location = locations.get(spec.id) or {}
    durable_poly = durable_location.get("polymarket") or {}
    if durable_location and durable_poly.get("event_slug_prefix") != spec.slug_prefix:
        issues.append(mismatch_issue(
            "durable_location_prefix_mismatch",
            "durable location registry prefix does not match active market registry prefix",
            field="locations.polymarket.event_slug_prefix",
            expected=spec.slug_prefix,
            actual=durable_poly.get("event_slug_prefix"),
        ))
    if not durable_location:
        issues.append(mismatch_issue(
            "durable_location_missing",
            "market is registered but missing from durable locations registry",
            field="locations",
            expected=spec.id,
            actual=None,
        ))

    generated_location = generated_locations.get(spec.id) or {}
    if not generated_location:
        issues.append(stale_issue(
            "generated_location_missing",
            "market is missing from generated location_market_events metadata",
            field="location_market_events.locations",
            expected=spec.id,
            actual=None,
        ))
        candidates = []
    else:
        if generated_location.get("event_slug_prefix") != spec.slug_prefix:
            issues.append(mismatch_issue(
                "generated_location_prefix_mismatch",
                "generated event metadata prefix does not match active market registry prefix",
                field="location_market_events.locations.event_slug_prefix",
                expected=spec.slug_prefix,
                actual=generated_location.get("event_slug_prefix"),
            ))
        candidates = _event_candidates(generated_location, target_date, expected_slug)
        if not candidates:
            issues.append(stale_issue(
                "target_event_missing",
                "generated event metadata does not contain the target-date event",
                field="location_market_events.locations.active_events",
                expected=expected_slug,
                actual=generated_location.get("source_event_dates") or [],
            ))
        elif len(candidates) > 1:
            issues.append(ambiguous_issue(
                "ambiguous_generated_target_events",
                "generated event metadata has more than one candidate for the target-date event",
                field="location_market_events.locations.active_events",
                expected=expected_slug,
                actual=[event_slug(row) for row in candidates],
            ))

    generated_event = normalize_event(candidates[0]) if len(candidates) == 1 else {}
    if generated_event and generated_event.get("event_slug") != expected_slug:
        issues.append(mismatch_issue(
            "generated_event_slug_mismatch",
            "generated target-date event slug does not match market registry template",
            field="event_slug",
            expected=expected_slug,
            actual=generated_event.get("event_slug"),
        ))
    if generated_event:
        issues.extend(_token_quality_issues(generated_event, "generated"))

    live_candidates = list(live_index.get(expected_slug) or [])
    if live_errors.get(spec.id):
        issues.append(issue(
            "live_gamma_fetch_failed",
            "live_fetch",
            "live Gamma event fetch failed; active-day evidence cannot be counted without live validation",
            field="live_event",
            expected=expected_slug,
            actual=live_errors.get(spec.id),
            remediation_command=VALIDATION_COMMAND.replace("<YYYY-MM-DD>", target_date.isoformat()),
            recoverable_same_day=True,
            manual_review_required=False,
        ))
    elif not live_candidates:
        issues.append(issue(
            "live_event_missing",
            "live_fetch",
            "live Gamma metadata does not contain the target-date event",
            field="live_event",
            expected=expected_slug,
            actual=None,
            remediation_command=VALIDATION_COMMAND.replace("<YYYY-MM-DD>", target_date.isoformat()),
            recoverable_same_day=True,
            manual_review_required=False,
        ))
    elif len(live_candidates) > 1:
        issues.append(ambiguous_issue(
            "ambiguous_live_target_events",
            "live Gamma metadata has more than one candidate for the target-date event",
            field="live_event",
            expected=expected_slug,
            actual=[event_id(row) for row in live_candidates],
        ))

    live_event = normalize_event(live_candidates[0]) if len(live_candidates) == 1 else {}
    if live_event:
        issues.extend(_token_quality_issues(live_event, "live"))
    if generated_event and live_event:
        issues.extend(_compare_events(generated_event, live_event))

    status = "BLOCK" if issues else "PASS"
    first_issue = issues[0] if issues else {}
    return {
        "market_id": spec.id,
        "city": spec.city_label,
        "target_date": target_date.isoformat(),
        "event_slug": expected_slug,
        "status": status,
        "ok": status == "PASS",
        "active_day_evidence_countable": status == "PASS",
        "manual_review_required": any(row.get("manual_review_required") for row in issues),
        "recoverable_same_day": bool(issues) and all(row.get("recoverable_same_day") for row in issues),
        "issue_count": len(issues),
        "issue_counts": dict(sorted(Counter(row.get("category") for row in issues).items())),
        "first_issue": first_issue,
        "reason": "event metadata validated" if not issues else first_issue.get("detail"),
        "remediation_command": _first_remediation(issues),
        "generated_event": generated_event,
        "live_event": live_event,
        "issues": issues,
    }


def build_validation_payload(
    *,
    target_date: str | date | None = None,
    markets: str | list[str] | tuple[str, ...] | None = None,
    locations_path: str | Path = DEFAULT_LOCATIONS,
    event_metadata_path: str | Path = DEFAULT_EVENT_METADATA,
    locations_payload: dict[str, Any] | None = None,
    event_metadata_payload: dict[str, Any] | None = None,
    live_events: Any = None,
    fetch_live: bool = True,
    timeout_seconds: float = 10.0,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    now: str | datetime | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    now_dt = utc_now(now)
    target = ensure_date(target_date or now_dt.date())
    specs = selected_specs(markets)
    locations_payload = locations_payload if locations_payload is not None else (load_json(locations_path, {}) or {})
    event_metadata_payload = (
        event_metadata_payload
        if event_metadata_payload is not None
        else (load_json(event_metadata_path, {}) or {})
    )
    live_index = _event_index(live_events)
    live_errors: dict[str, str] = {}
    if fetch_live:
        fetched_index, live_errors = _fetch_live_events(specs, target, timeout_seconds)
        for slug, rows in fetched_index.items():
            live_index.setdefault(slug, []).extend(rows)

    rows = [
        _market_validation_row(
            spec,
            target_date=target,
            locations=locations_by_id(locations_payload),
            generated_locations=generated_locations_by_id(event_metadata_payload),
            metadata_payload=event_metadata_payload,
            live_index=live_index,
            live_errors=live_errors,
            now=now_dt,
            max_age_hours=max_age_hours,
        )
        for spec in specs
    ]
    status = "PASS" if all(row.get("status") == "PASS" for row in rows) else "BLOCK"
    issues = [issue for row in rows for issue in row.get("issues") or []]
    issue_counts = Counter(issue.get("category") for issue in issues)
    summary = {
        "status": status,
        "market_count": len(rows),
        "pass_count": sum(1 for row in rows if row.get("status") == "PASS"),
        "block_count": sum(1 for row in rows if row.get("status") != "PASS"),
        "issue_count": len(issues),
        "issue_counts": dict(sorted(issue_counts.items())),
        "stale_count": issue_counts.get("stale_generated_metadata", 0),
        "mismatch_count": issue_counts.get("metadata_mismatch", 0),
        "ambiguous_count": issue_counts.get("ambiguous_event_metadata", 0),
        "blank_token_count": issue_counts.get("blank_token_metadata", 0),
        "manual_review_required_market_count": sum(1 for row in rows if row.get("manual_review_required")),
        "recoverable_same_day_market_count": sum(1 for row in rows if row.get("recoverable_same_day")),
        "first_blocker": next((row for row in rows if row.get("status") != "PASS"), {}),
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "owner": "weather.operations.event_metadata_validation",
        "status": status,
        "target_date": target.isoformat(),
        "markets": [spec.id for spec in specs],
        "locations_path": str(locations_path),
        "event_metadata_path": str(event_metadata_path),
        "max_age_hours": float(max_age_hours),
        "live_fetch": {
            "enabled": bool(fetch_live),
            "timeout_seconds": float(timeout_seconds),
            "error_count": len(live_errors),
            "errors": live_errors,
        },
        "summary": summary,
        "market_rows": rows,
        "refresh_command": REFRESH_COMMAND,
        "validation_command": VALIDATION_COMMAND.replace("<YYYY-MM-DD>", target.isoformat()),
        "manual_review_command": MANUAL_REVIEW_COMMAND,
        "validation_hash": "",
    }
    payload["validation_hash"] = validation_content_hash(payload)
    for row in payload["market_rows"]:
        row["validation_hash"] = payload["validation_hash"]
    payload["summary"]["validation_hash"] = payload["validation_hash"]
    return payload


def gate_for_market(payload: dict[str, Any] | None, market_id: str) -> dict[str, Any]:
    if not payload:
        return {
            "required": True,
            "ok": False,
            "status": "BLOCK",
            "market_id": market_id,
            "reason": "event metadata validation artifact missing",
            "detail": "event metadata validation artifact missing",
            "issue_count": 1,
            "validation_hash": None,
            "remediation_command": VALIDATION_COMMAND,
            "recoverable_same_day": True,
            "manual_review_required": False,
        }
    rows = {
        row.get("market_id"): row
        for row in payload.get("market_rows") or []
        if isinstance(row, dict)
    }
    row = rows.get(market_id)
    if not row:
        return {
            "required": True,
            "ok": False,
            "status": "BLOCK",
            "market_id": market_id,
            "target_date": payload.get("target_date"),
            "reason": "event metadata validation row missing for market",
            "detail": "event metadata validation row missing for market",
            "issue_count": 1,
            "validation_hash": payload.get("validation_hash"),
            "remediation_command": payload.get("validation_command") or VALIDATION_COMMAND,
            "recoverable_same_day": True,
            "manual_review_required": False,
        }
    first_issue = row.get("first_issue") or {}
    return {
        "required": True,
        "ok": bool(row.get("ok")),
        "status": row.get("status"),
        "market_id": market_id,
        "target_date": row.get("target_date"),
        "event_slug": row.get("event_slug"),
        "reason": row.get("reason"),
        "detail": row.get("reason"),
        "issue_count": row.get("issue_count"),
        "issue_counts": row.get("issue_counts") or {},
        "first_issue_code": first_issue.get("code"),
        "first_issue_category": first_issue.get("category"),
        "validation_hash": row.get("validation_hash") or payload.get("validation_hash"),
        "remediation_command": row.get("remediation_command") or payload.get("validation_command"),
        "recoverable_same_day": bool(row.get("recoverable_same_day")),
        "manual_review_required": bool(row.get("manual_review_required")),
    }


def load_validation_payload(path: str | Path = DEFAULT_JSON_OUT) -> dict[str, Any] | None:
    payload = load_json(path, None)
    return payload if isinstance(payload, dict) else None


def load_gate_for_market(path: str | Path, market_id: str) -> dict[str, Any]:
    return gate_for_market(load_validation_payload(path), market_id)


def render_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Event Metadata Validation",
        "",
        f"Status: **{payload.get('status')}**",
        f"Target date: `{payload.get('target_date')}`",
        f"Validation hash: `{payload.get('validation_hash')}`",
        "",
        "## Summary",
        "",
        markdown_table(
            ["Metric", "Value"],
            [
                ["Markets", summary.get("market_count")],
                ["Passing", summary.get("pass_count")],
                ["Blocked", summary.get("block_count")],
                ["Issues", summary.get("issue_count")],
                ["Stale issues", summary.get("stale_count")],
                ["Mismatch issues", summary.get("mismatch_count")],
                ["Ambiguous issues", summary.get("ambiguous_count")],
                ["Blank-token issues", summary.get("blank_token_count")],
            ],
        ),
        "",
        "## Markets",
        "",
        markdown_table(
            ["Market", "Status", "Issues", "First Issue", "Command"],
            [
                [
                    row.get("market_id"),
                    row.get("status"),
                    row.get("issue_count"),
                    ((row.get("first_issue") or {}).get("code") or "-"),
                    row.get("remediation_command") or "-",
                ]
                for row in payload.get("market_rows") or []
            ],
        ),
    ]
    return "\n".join(lines) + "\n"


def write_outputs(
    payload: dict[str, Any],
    *,
    json_out: str | Path = DEFAULT_JSON_OUT,
    report_out: str | Path = DEFAULT_REPORT_OUT,
) -> tuple[Path, Path]:
    json_path = write_json(json_out, payload)
    report_path = Path(report_out)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description="Validate target-date Polymarket weather event metadata.")
    parser.add_argument("--target-date", default="", help="Target date to validate; defaults to today UTC.")
    parser.add_argument("--markets", default="all", help="Comma-separated market ids or all.")
    parser.add_argument("--locations", default=str(DEFAULT_LOCATIONS))
    parser.add_argument("--event-metadata", default=str(DEFAULT_EVENT_METADATA))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--events-json", default="", help="Fixture live events JSON instead of live Gamma fetch.")
    parser.add_argument("--no-live-fetch", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS)
    args = parser.parse_args(argv)
    live_events = None
    if args.events_json:
        live_events = load_json(args.events_json, [])
    payload = build_validation_payload(
        target_date=args.target_date or None,
        markets=args.markets,
        locations_path=args.locations,
        event_metadata_path=args.event_metadata,
        live_events=live_events,
        fetch_live=not args.no_live_fetch,
        timeout_seconds=args.timeout_seconds,
        max_age_hours=args.max_age_hours,
    )
    json_out, report_out = write_outputs(payload, json_out=args.json_out, report_out=args.report_out)
    print(f"Event metadata validation: {payload['status']} json={json_out} report={report_out}")
    return payload


if __name__ == "__main__":
    main()
