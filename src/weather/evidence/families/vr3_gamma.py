"""VR-3 Gamma event + Rules journal (journal only; never writes ``config/``).

- ``events_active``: every interval, ``/events?active=true&closed=false`` for both series
  (``highest-temperature`` and ``lowest-temperature`` tag slugs). Each event is one change-only row
  keyed by event id, hashing the Rules text, resolution source, negRisk, dates, rewards, UMA status,
  closed time, outcome prices and volume/liquidity. ``event_date`` from the slug goes in the
  envelope so readers can apply the embargo windows.
- Source-change gate (WARN first): an event whose ``resolutionSource`` differs from the city's
  ``settlement.resolution_source_url`` in ``locations.json`` writes a ``warn`` row once per
  (event, source) pair. Nothing is blocked or rewritten.
- ``events_closed_sweep``: once per local day in its ``run_local`` window, for each recent event date
  the fetch-side embargo guard runs first (``mode=sweep``); refused dates are journalled as ``guard``
  rows and never fetched. Allowed dates are fetched per event slug.

``WeatherLocationConfigRefresh`` stays the sole writer of ``config/location_market_events.json``.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from weather.evidence.embargo import EmbargoRefused
from weather.evidence.families.common import item, json_body

PARSER_VERSION = "vr3-gamma-1"
DEFAULT_TAG_SLUGS = ("highest-temperature", "lowest-temperature")
SLUG_RE = re.compile(r"^(?P<series>highest|lowest)-temperature-in-(?P<city>.+)-on-"
                     r"(?P<month>[a-z]+)-(?P<day>\d{1,2})-(?P<year>\d{4})$")
EVENT_FIELDS = ("id", "slug", "title", "description", "resolutionSource", "negRisk", "startDate", "endDate",
                "closedTime", "active", "closed", "archived", "volume", "liquidity")
MARKET_FIELDS = ("id", "conditionId", "groupItemTitle", "question", "description", "resolutionSource",
                 "outcomes", "outcomePrices", "clobTokenIds", "umaResolutionStatus", "clobRewards", "negRisk",
                 "closed", "closedTime", "volume", "liquidity", "endDate")


def parse_slug(slug) -> dict | None:
    from weather.operations.location_config_refresh import MONTHS
    match = SLUG_RE.match(str(slug or "").lower())
    if not match or match.group("month") not in MONTHS:
        return None
    try:
        day = date(int(match.group("year")), MONTHS[match.group("month")], int(match.group("day")))
    except ValueError:
        return None
    return {"series": match.group("series"), "city": match.group("city"), "event_date": day.isoformat()}


def city_map(locations) -> dict:
    """Slug city part (from ``event_slug_prefix``) → ``{location, resolution_source_url}``."""
    out = {}
    for row in locations:
        prefix = str((row.get("polymarket") or {}).get("event_slug_prefix") or "").lower()
        match = re.fullmatch(r"highest-temperature-in-(.+)-on", prefix)
        if match:
            out[match.group(1)] = {"location": row["id"],
                                   "resolution_source_url": (row.get("settlement") or {}).get("resolution_source_url")}
    return out


def _norm_url(value) -> str:
    return str(value or "").strip().lower().rstrip("/")


def event_item(event, cities) -> tuple[dict, dict | None] | None:
    slug = event.get("slug")
    parsed = parse_slug(slug)
    if parsed is None:
        return None
    city = cities.get(parsed["city"])
    body = {**{k: event.get(k) for k in EVENT_FIELDS}, "series": parsed["series"],
            "location": city["location"] if city else None,
            "markets": [{k: m.get(k) for k in MARKET_FIELDS} for m in event.get("markets") or []
                        if isinstance(m, dict)]}
    mismatch = None
    if city and event.get("resolutionSource") and _norm_url(event["resolutionSource"]) != _norm_url(
            city["resolution_source_url"]):
        mismatch = {"event_id": str(event.get("id")), "slug": slug, "location": city["location"],
                    "venue_source": event.get("resolutionSource"), "declared_source": city["resolution_source_url"]}
    row = item(str(event.get("id")), body, parser_version=PARSER_VERSION,
               provider_time=event.get("updatedAt"), event_date=parsed["event_date"])
    return row, mismatch


def _events_url(base, *, tag_slug, active, closed, limit, offset):
    from weather.operations.location_config_refresh import gamma_events_url
    url = gamma_events_url(tag_slug=tag_slug, active=active, closed=closed, limit=limit, offset=offset)
    return url if base is None else url.replace("https://gamma-api.polymarket.com/events", base, 1)


def sweep_slugs(cities, series, day) -> list[str]:
    from weather.operations.location_config_refresh import MONTHS
    month = {v: k for k, v in MONTHS.items()}[day.month]
    return [f"{s}-temperature-in-{c}-on-{month}-{day.day}-{day.year}" for s in series for c in sorted(cities)]


def build(cfg, locations):
    from weather.evidence.child import Channel
    cities = city_map(locations)
    channels = cfg["channels"]
    tag_slugs = tuple(cfg.get("tag_slugs", DEFAULT_TAG_SLUGS))
    base = cfg.get("base_url")

    def record_events(ctx, events, meta):
        items = []
        for event in events:
            built = event_item(event, cities) if isinstance(event, dict) else None
            if built is None:
                continue
            row, mismatch = built
            items.append(row)
            if mismatch:
                marker = (mismatch["event_id"], _norm_url(mismatch["venue_source"]))
                warned = ctx.state.setdefault("source_warned", set())
                if marker not in warned:
                    warned.add(marker)
                    ctx.warn("resolution_source_differs_from_locations", **mismatch)
        return ctx.record(items, meta=meta)

    def poll_active(ctx):
        spec = channels["events_active"]
        limit, max_pages = int(spec.get("limit", 100)), int(spec.get("max_pages", 10))
        for tag in tag_slugs:
            events = []
            for page in range(max_pages):
                response = ctx.fetch(_events_url(base, tag_slug=tag, active=True, closed=False, limit=limit,
                                                 offset=page * limit))
                if response.status != 200:
                    ctx.gap("http_status", status=response.status, tag_slug=tag, page=page)
                    break
                rows = json_body(response)
                rows = rows if isinstance(rows, list) else []
                events.extend(rows)
                if len(rows) < limit:
                    break
            record_events(ctx, events, {"tag_slug": tag, "events": len(events)})

    def poll_closed_sweep(ctx):
        spec = channels["events_closed_sweep"]
        today = ctx.now().date()
        series = [t.split("-")[0] for t in tag_slugs]
        for back in range(int(spec.get("lookback_days_from", 2)), int(spec.get("lookback_days_to", 4)) + 1):
            day = today - timedelta(days=back)
            try:
                ctx.guard(day.isoformat(), mode="sweep")
            except EmbargoRefused:
                continue
            events = []
            for slug in sweep_slugs(cities, series, day):
                response = ctx.fetch(f"{base or 'https://gamma-api.polymarket.com/events'}?slug={slug}")
                if response.status != 200:
                    ctx.gap("http_status", status=response.status, slug=slug)
                    continue
                rows = json_body(response)
                events.extend(rows if isinstance(rows, list) else [])
                ctx.sleep(float(spec.get("spacing_seconds", 0.25)))
            record_events(ctx, events, {"sweep_event_date": day.isoformat(), "events": len(events)})

    out = []
    for name, poll in (("events_active", poll_active), ("events_closed_sweep", poll_closed_sweep)):
        spec = channels.get(name)
        if spec and spec.get("enabled", True):
            out.append(Channel(name, float(spec["interval_seconds"]), poll, optional=bool(spec.get("optional", True)),
                               run_local=tuple(tuple(w) for w in spec.get("run_local", []))))
    return out
