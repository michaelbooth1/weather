"""Refresh volatile location market metadata from Polymarket Gamma events."""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import config_path
from weather.schema_registry import schema_version


LOCATION_REGISTRY_SCHEMA_VERSION = schema_version("location_registry")
LOCATION_MARKET_EVENTS_SCHEMA_VERSION = schema_version("location_market_events")

DEFAULT_LOCATIONS = config_path("locations.json")
DEFAULT_EVENT_METADATA = config_path("location_market_events.json")
DEFAULT_TAG_SLUG = "highest-temperature"
DEFAULT_CATEGORY_URL = "https://polymarket.com/weather/high-temperature"
DEFAULT_GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events"
DEFAULT_LIMIT = 100
USER_AGENT = "Mozilla/5.0 weather-location-config-refresh/0.1"

EVENT_DATE_RE = re.compile(
    r"^highest-temperature-in-(?P<location>.+)-on-"
    r"(?P<month>[a-z]+)-(?P<day>\d{1,2})-(?P<year>\d{4})$"
)
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
VOLATILE_POLYMARKET_FIELDS = {
    "latest_event_slug",
    "latest_event_url",
    "source_event_count",
    "source_event_dates",
    "active_events",
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def gamma_events_url(*, tag_slug: str, active: bool, closed: bool, limit: int, offset: int) -> str:
    return DEFAULT_GAMMA_EVENTS_URL + "?" + urllib.parse.urlencode({
        "tag_slug": tag_slug,
        "active": str(active).lower(),
        "closed": str(closed).lower(),
        "limit": int(limit),
        "offset": offset if isinstance(offset, str) else int(offset),
    }, safe="{}")


def fetch_gamma_events(
    *,
    tag_slug: str = DEFAULT_TAG_SLUG,
    active: bool = True,
    closed: bool = False,
    limit: int = DEFAULT_LIMIT,
    timeout_seconds: float = 30.0,
    max_pages: int = 20,
) -> tuple[list[dict], list[int]]:
    events: list[dict] = []
    offsets: list[int] = []
    for page in range(int(max_pages)):
        offset = page * int(limit)
        url = gamma_events_url(
            tag_slug=tag_slug,
            active=active,
            closed=closed,
            limit=limit,
            offset=offset,
        )
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            page_events = json.loads(response.read().decode("utf-8"))
        if not isinstance(page_events, list):
            raise ValueError("Gamma events response must be a list")
        offsets.append(offset)
        events.extend(row for row in page_events if isinstance(row, dict))
        if len(page_events) < int(limit):
            break
    return events, offsets


def event_date_from_slug(slug: str) -> str | None:
    match = EVENT_DATE_RE.match(str(slug or "").lower())
    if not match:
        return None
    month = MONTHS.get(match.group("month"))
    if not month:
        return None
    try:
        return datetime(int(match.group("year")), month, int(match.group("day"))).date().isoformat()
    except ValueError:
        return None


def prefix_map(locations_payload: dict) -> dict[str, str]:
    output: dict[str, str] = {}
    for row in locations_payload.get("locations") or []:
        polymarket = row.get("polymarket") or {}
        prefix = polymarket.get("event_slug_prefix")
        location_id = row.get("id")
        if prefix and location_id:
            output[str(prefix).lower()] = str(location_id)
    return dict(sorted(output.items(), key=lambda item: len(item[0]), reverse=True))


def location_id_for_event(event: dict, prefixes: dict[str, str]) -> str | None:
    slug = str(event.get("slug") or event.get("eventSlug") or "").lower()
    for prefix, location_id in prefixes.items():
        if slug.startswith(f"{prefix}-"):
            return location_id
    return None


def event_market_count(event: dict) -> int:
    markets = event.get("markets") or []
    return len(markets) if isinstance(markets, list) else 0


def parse_json_list(value):
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


def bool_value(value):
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y", "active", "enabled"}:
        return True
    if lowered in {"0", "false", "no", "n", "inactive", "closed", "disabled"}:
        return False
    return None


def normalized_market(market: dict) -> dict:
    outcomes = parse_json_list(market.get("outcomes"))
    token_ids = parse_json_list(market.get("clobTokenIds") or market.get("clob_token_ids"))
    outcome_rows = []
    for index in range(max(len(outcomes), len(token_ids))):
        outcome_rows.append({
            "index": index,
            "name": str(outcomes[index]) if index < len(outcomes) else "",
            "token_id": str(token_ids[index]) if index < len(token_ids) else "",
        })
    outcome_tokens = {
        str(row["name"]): row["token_id"]
        for row in outcome_rows
        if row.get("name")
    }
    return {
        "polymarket_market_id": str(market.get("id") or market.get("marketId") or ""),
        "condition_id": str(market.get("conditionId") or market.get("condition_id") or ""),
        "range_label": (
            market.get("groupItemTitle")
            or market.get("group_item_title")
            or market.get("question")
        ),
        "question": market.get("question"),
        "enable_order_book": bool_value(market.get("enableOrderBook") if "enableOrderBook" in market else market.get("enable_order_book")),
        "active": bool_value(market.get("active")),
        "closed": bool_value(market.get("closed")),
        "outcomes": outcome_rows,
        "outcome_tokens": outcome_tokens,
    }


def normalized_event(event: dict) -> dict:
    slug = event.get("slug") or event.get("eventSlug")
    markets = [
        normalized_market(market)
        for market in event.get("markets") or []
        if isinstance(market, dict)
    ]
    return {
        "event_id": str(event.get("id") or event.get("eventId") or ""),
        "event_date": event_date_from_slug(slug),
        "event_slug": slug,
        "event_url": f"https://polymarket.com/event/{slug}" if slug else None,
        "title": event.get("title"),
        "end_date": event.get("endDate") or event.get("end_date"),
        "resolution_source_url": event.get("resolutionSource") or event.get("resolution_source"),
        "market_count": event_market_count(event),
        "markets": markets,
    }


def build_location_market_events(
    locations_payload: dict,
    events: list[dict],
    *,
    generated_at_utc: str | None = None,
    tag_slug: str = DEFAULT_TAG_SLUG,
    active: bool = True,
    closed: bool = False,
    limit: int = DEFAULT_LIMIT,
    offsets: list[int] | None = None,
) -> dict:
    prefixes = prefix_map(locations_payload)
    by_location: dict[str, list[dict]] = {row.get("id"): [] for row in locations_payload.get("locations") or []}
    unmatched_locations = set()
    for event in events:
        location_id = location_id_for_event(event, prefixes)
        if not location_id:
            slug = str(event.get("slug") or event.get("eventSlug") or "")
            match = EVENT_DATE_RE.match(slug.lower())
            if match:
                unmatched_locations.add(match.group("location"))
            continue
        by_location.setdefault(location_id, []).append(normalized_event(event))

    locations = []
    for row in locations_payload.get("locations") or []:
        location_id = row.get("id")
        polymarket = row.get("polymarket") or {}
        active_events = sorted(
            by_location.get(location_id) or [],
            key=lambda item: (item.get("event_date") or "", item.get("event_slug") or ""),
        )
        latest = active_events[-1] if active_events else {}
        locations.append({
            "location_id": location_id,
            "event_slug_prefix": polymarket.get("event_slug_prefix"),
            "series_slug": polymarket.get("series_slug"),
            "latest_event_slug": latest.get("event_slug"),
            "latest_event_url": latest.get("event_url"),
            "source_event_count": len(active_events),
            "source_event_dates": [event.get("event_date") for event in active_events if event.get("event_date")],
            "active_events": active_events,
        })

    missing_from_api = [
        row.get("id")
        for row in locations_payload.get("locations") or []
        if row.get("id") and not by_location.get(row.get("id"))
    ]
    return {
        "schema_version": LOCATION_MARKET_EVENTS_SCHEMA_VERSION,
        "status": "generated_snapshot",
        "owner": "weather.operations.location_config_refresh",
        "generated_at_utc": generated_at_utc or utc_iso(),
        "source": {
            "category_url": DEFAULT_CATEGORY_URL,
            "gamma_events_query": gamma_events_url(
                tag_slug=tag_slug,
                active=active,
                closed=closed,
                limit=limit,
                offset="{offset}",
            ),
            "tag_slug": tag_slug,
            "active": bool(active),
            "closed": bool(closed),
            "event_count": len(events),
            "location_count": sum(1 for row in locations if row.get("source_event_count")),
            "api_page_size": int(limit),
            "api_offsets_fetched": list(offsets or []),
            "locations_in_api_not_file": sorted(unmatched_locations),
            "locations_in_file_not_api": sorted(missing_from_api),
        },
        "locations": locations,
    }


def durable_locations_payload(
    locations_payload: dict,
    *,
    event_metadata_path: str | Path = DEFAULT_EVENT_METADATA,
    generated_at_utc: str | None = None,
) -> dict:
    generated_at_utc = generated_at_utc or utc_iso()
    output = dict(locations_payload)
    output["schema_version"] = LOCATION_REGISTRY_SCHEMA_VERSION
    output["status"] = "durable_location_registry"
    output["owner"] = "weather.market"
    output["freshness_policy"] = {
        "source": "hand-authored durable location and station facts",
        "event_metadata_path": str(Path(event_metadata_path).as_posix()),
        "volatile_event_metadata": "config/location_market_events.json",
    }
    output["event_metadata"] = {
        "last_refreshed_at_utc": generated_at_utc,
        "path": str(Path(event_metadata_path).as_posix()),
        "schema_version": LOCATION_MARKET_EVENTS_SCHEMA_VERSION,
    }
    output["volatile_fields"] = []
    output.pop("source", None)
    output.pop("generated_at", None)

    stable_locations = []
    for row in output.get("locations") or []:
        stable = dict(row)
        polymarket = dict(stable.get("polymarket") or {})
        for key in VOLATILE_POLYMARKET_FIELDS:
            polymarket.pop(key, None)
        stable["polymarket"] = polymarket
        stable_locations.append(stable)
    output["locations"] = stable_locations
    return output


def refresh_configs(
    *,
    locations_path: str | Path = DEFAULT_LOCATIONS,
    event_metadata_path: str | Path = DEFAULT_EVENT_METADATA,
    events: list[dict] | None = None,
    generated_at_utc: str | None = None,
) -> tuple[dict, dict]:
    locations_payload = load_json(locations_path)
    offsets: list[int] = []
    if events is None:
        events, offsets = fetch_gamma_events()
    generated_at_utc = generated_at_utc or utc_iso()
    event_payload = build_location_market_events(
        locations_payload,
        list(events or []),
        generated_at_utc=generated_at_utc,
        offsets=offsets,
    )
    durable_payload = durable_locations_payload(
        locations_payload,
        event_metadata_path=event_metadata_path,
        generated_at_utc=generated_at_utc,
    )
    return durable_payload, event_payload


def main(argv=None):
    parser = argparse.ArgumentParser(description="Refresh generated location market-event metadata.")
    parser.add_argument("--locations", default=str(DEFAULT_LOCATIONS))
    parser.add_argument("--event-metadata", default=str(DEFAULT_EVENT_METADATA))
    parser.add_argument("--events-json", default="", help="Optional fixture events JSON instead of live Gamma fetch.")
    args = parser.parse_args(argv)
    events = None
    if args.events_json:
        payload = load_json(args.events_json)
        events = payload.get("events") if isinstance(payload, dict) else payload
    locations_payload, event_payload = refresh_configs(
        locations_path=args.locations,
        event_metadata_path=args.event_metadata,
        events=events,
    )
    write_json(args.locations, locations_payload)
    write_json(args.event_metadata, event_payload)
    print(
        "Location config refresh: locations={locations} events={events}".format(
            locations=len(locations_payload.get("locations") or []),
            events=event_payload.get("source", {}).get("event_count", 0),
        )
    )
    return locations_payload, event_payload


if __name__ == "__main__":
    main()
