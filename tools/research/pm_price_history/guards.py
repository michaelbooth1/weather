"""Event-date and endpoint guards for the price-history comparator. They refuse in code.

Every event date is checked by ``require_admitted`` before any request for that event's prices,
and discovery drops refused events before any of their token ids are kept.

Refused event dates (local target dates), with their canon:

* after ``LAST_ADMITTED`` = 2026-09-29: dev data only (close-the-gap LANES.md common section;
  covers the 88a desk-study panel UTC 2026-10-15..10-30, the 2026-09-30..10-15 never-read span
  in LANE_RULES.md, and every forward / embargoed outcome);
* the sealed pre-boundary confirmation panels B and C, 2026-05-27..2026-07-30 inclusive
  (docs/operations/EXHAUSTION_REGISTER.md, panel table: B 05-27..06-30, C 07-01..07-30);
* the MG-1 reserved window, D0 = 2026-10-15 through a provisional last of 2026-11-28 that may only
  move later (docs/operations/reserved-confirmation-window.md status line;
  docs/research/morning-guidance-read-mg1-preregistration-2026-10-04.md; constants in
  ``weather.mg1_reserved_window``). Because the last date may move later, every date on or after
  ``MG1_FLOOR`` is refused here (open-ended), and ``is_reserved`` is consulted as well.

There is no override argument and no environment variable.
"""

from __future__ import annotations

from datetime import date, datetime
from urllib.parse import urlsplit

from weather import mg1_reserved_window as mg1

LAST_ADMITTED = date(2026, 9, 29)
SEALED_PANEL_FIRST = date(2026, 5, 27)
SEALED_PANEL_LAST = date(2026, 7, 30)

ALLOWED_HOSTS = frozenset({"gamma-api.polymarket.com", "clob.polymarket.com"})
ALLOWED_PATHS = {
    "gamma-api.polymarket.com": frozenset({"/series", "/events"}),
    "clob.polymarket.com": frozenset({"/prices-history"}),
}
FORBIDDEN_HEADER_PREFIXES = ("authorization", "cookie", "poly_", "poly-", "x-api-key", "l2-")


class GuardRefusal(RuntimeError):
    """A guard refused an event date, endpoint or header. Never caught to continue a fetch."""


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return None  # a datetime is ambiguous about the local target date
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) == 10:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def refusal_reason(event_date) -> str | None:
    """Return why ``event_date`` is refused, or None when it is admitted."""
    d = _as_date(event_date)
    if d is None:
        return "unreadable_event_date"
    if d > LAST_ADMITTED:
        return "after_last_admitted_2026_09_29"
    if SEALED_PANEL_FIRST <= d <= SEALED_PANEL_LAST:
        return "sealed_panel_2026_05_27_to_07_30"
    if d >= mg1.MG1_FLOOR or mg1.is_reserved(d):
        return "mg1_reserved_window"
    return None


def is_admitted(event_date) -> bool:
    return refusal_reason(event_date) is None


def require_admitted(event_date) -> date:
    reason = refusal_reason(event_date)
    if reason is not None:
        raise GuardRefusal(f"event date refused ({reason}): {event_date!r}")
    return _as_date(event_date)


def require_public_endpoint(url: str, headers=None) -> None:
    """Refuse anything but the public International Polymarket read endpoints, unauthenticated."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in ALLOWED_HOSTS:
        raise GuardRefusal(f"endpoint refused (host): {host or url!r}")
    if parts.path not in ALLOWED_PATHS[host]:
        raise GuardRefusal(f"endpoint refused (path): {host}{parts.path}")
    for name in dict(headers or {}):
        if str(name).lower().startswith(FORBIDDEN_HEADER_PREFIXES):
            raise GuardRefusal(f"header refused: {name}")
