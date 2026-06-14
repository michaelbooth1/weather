import os
import re
from dataclasses import dataclass
from datetime import date, datetime

from market_registry import DEFAULT_MARKET_ID, TORONTO, spec_for_id, spec_for_slug

# Back-compat aliases: callers historically imported these Toronto constants here.
TORONTO_TZ = TORONTO.tz
TORONTO_EVENT_PREFIX = TORONTO.slug_prefix
TARGET_DATE_ENV = "TORONTO_MARKET_DATE"

MONTH_NAMES = {
    1: "january",
    2: "february",
    3: "march",
    4: "april",
    5: "may",
    6: "june",
    7: "july",
    8: "august",
    9: "september",
    10: "october",
    11: "november",
    12: "december",
}

MONTH_LOOKUP = {name: number for number, name in MONTH_NAMES.items()}


@dataclass(frozen=True)
class MarketConfig:
    target_date: date
    event_slug: str
    polymarket_url: str
    market_id: str = DEFAULT_MARKET_ID

    @property
    def spec(self):
        return spec_for_id(self.market_id)

    @property
    def target_date_str(self):
        return self.target_date.strftime("%Y%m%d")

    @property
    def display_date(self):
        return self.target_date.strftime("%B %-d, %Y") if os.name != "nt" else self.target_date.strftime("%B %#d, %Y")


def default_target_date(tz=TORONTO_TZ):
    configured = os.environ.get(TARGET_DATE_ENV)
    if configured:
        return date.fromisoformat(configured)
    return datetime.now(tz).date()


def event_slug_for_date(target_date, market_id=DEFAULT_MARKET_ID):
    target_date = ensure_date(target_date)
    spec = spec_for_id(market_id)
    month = MONTH_NAMES[target_date.month]
    return f"{spec.slug_prefix}-{month}-{target_date.day}-{target_date.year}"


def polymarket_url_for_slug(event_slug):
    return f"https://polymarket.com/event/{event_slug}"


def config_for_date(target_date=None, market_id=DEFAULT_MARKET_ID):
    target_date = ensure_date(target_date or default_target_date(spec_for_id(market_id).tz))
    event_slug = event_slug_for_date(target_date, market_id)
    return MarketConfig(
        target_date=target_date,
        event_slug=event_slug,
        polymarket_url=polymarket_url_for_slug(event_slug),
        market_id=market_id,
    )


def market_id_from_slug(slug):
    spec = spec_for_slug(slug)
    return spec.id if spec else None


def date_from_event_slug(slug):
    """Parse the target date from any registered market's event slug."""
    if not slug:
        return None
    spec = spec_for_slug(slug)
    if not spec:
        return None
    match = re.search(
        rf"{re.escape(spec.slug_prefix)}-([a-z]+)-(\d{{1,2}})-(\d{{4}})",
        str(slug).lower(),
    )
    if not match:
        return None
    month = MONTH_LOOKUP.get(match.group(1))
    if not month:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(2)))
    except ValueError:
        return None


def date_from_event(event):
    if not event:
        return None
    return date_from_event_slug(event.get("slug") or event.get("eventSlug") or "")


def config_from_event(event, fallback_date=None):
    slug = (event or {}).get("slug") or (event or {}).get("eventSlug") or ""
    market_id = market_id_from_slug(slug) or DEFAULT_MARKET_ID
    target_date = date_from_event(event) or fallback_date or default_target_date(spec_for_id(market_id).tz)
    return config_for_date(target_date, market_id)


def ensure_date(value):
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))
