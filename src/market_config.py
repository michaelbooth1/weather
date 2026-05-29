import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo


TORONTO_TZ = ZoneInfo("America/Toronto")
TORONTO_EVENT_PREFIX = "highest-temperature-in-toronto-on"
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

    @property
    def target_date_str(self):
        return self.target_date.strftime("%Y%m%d")

    @property
    def display_date(self):
        return self.target_date.strftime("%B %-d, %Y") if os.name != "nt" else self.target_date.strftime("%B %#d, %Y")


def default_target_date():
    configured = os.environ.get(TARGET_DATE_ENV)
    if configured:
        return date.fromisoformat(configured)
    return datetime.now(TORONTO_TZ).date()


def event_slug_for_date(target_date):
    target_date = ensure_date(target_date)
    month = MONTH_NAMES[target_date.month]
    return f"{TORONTO_EVENT_PREFIX}-{month}-{target_date.day}-{target_date.year}"


def polymarket_url_for_slug(event_slug):
    return f"https://polymarket.com/event/{event_slug}"


def config_for_date(target_date=None):
    target_date = ensure_date(target_date or default_target_date())
    event_slug = event_slug_for_date(target_date)
    return MarketConfig(
        target_date=target_date,
        event_slug=event_slug,
        polymarket_url=polymarket_url_for_slug(event_slug),
    )


def date_from_event_slug(slug):
    if not slug:
        return None
    match = re.search(
        rf"{TORONTO_EVENT_PREFIX}-([a-z]+)-(\d{{1,2}})-(\d{{4}})",
        slug.lower(),
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
    target_date = date_from_event(event) or fallback_date or default_target_date()
    return config_for_date(target_date)


def ensure_date(value):
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))
