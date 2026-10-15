"""PL-1 embargo: the two code owners' windows applied to reads and fetches (no third copy).

Windows come only from ``maker_core.shadow.admission.EMBARGO_WINDOWS`` (``full`` and ``outcome``
kinds) and ``weather.mg1_reserved_window.window`` (plan §0 conflict 11, contract "Embargo").

Read purposes: ``capture_check`` (outcome-blind operational read), ``outcome_join`` and
``candidate=<name>`` (point-in-time candidate work).

- a day in a ``full`` window is refused for every purpose;
- a day in an ``outcome`` window or the MG-1 reserved range is refused for ``outcome_join`` and
  every candidate, and allowed for ``capture_check``.

Fetch side (:func:`embargo_guard`): a backfill or sweep keyed to an event or target date inside
any window is refused before the request is sent. A ``live`` current-state poll is outcome-blind
capture and is allowed in every window, but never for an event date already in the past.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from maker_core.shadow.admission import EMBARGO_WINDOWS, FULL, OUTCOME, utc_day
from weather.mg1_reserved_window import window as mg1_window

CAPTURE_CHECK = "capture_check"
OUTCOME_JOIN = "outcome_join"
CANDIDATE = "candidate"
CANDIDATE_PREFIX = "candidate="
MG1_RESERVED = "mg1_reserved"
FETCH_MODES = ("live", "backfill", "sweep")


class EmbargoRefused(PermissionError):
    def __init__(self, reason: str, **detail):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def parse_purpose(purpose: str) -> tuple[str, str | None]:
    text = str(purpose or "")
    if text in (CAPTURE_CHECK, OUTCOME_JOIN):
        return text, None
    if text.startswith(CANDIDATE_PREFIX) and len(text) > len(CANDIDATE_PREFIX):
        return CANDIDATE, text[len(CANDIDATE_PREFIX):]
    raise ValueError(f"unknown read purpose {purpose!r}: use capture_check, outcome_join or candidate=<name>")


def _day_text(day) -> str:
    if isinstance(day, datetime):
        day = day.astimezone(timezone.utc).date()
    return utc_day(day)


def day_scopes(day) -> tuple[str, ...]:
    """Every scope covering ``day``: ``full``, ``outcome`` and/or ``mg1_reserved``."""
    text = _day_text(day)
    scopes = {scope for start, end, scope, _ in EMBARGO_WINDOWS if start <= text <= end}
    start, end = mg1_window()
    value = date.fromisoformat(text)
    if value >= start and (end is None or value <= end):
        scopes.add(MG1_RESERVED)
    return tuple(sorted(scopes))


def read_refusal(day, purpose: str) -> str | None:
    """The refusal reason for reading ``day`` for ``purpose``, else None."""
    kind, _ = parse_purpose(purpose)
    scopes = day_scopes(day)
    if FULL in scopes:
        return "full_window"
    if kind != CAPTURE_CHECK:
        if OUTCOME in scopes:
            return "outcome_window"
        if MG1_RESERVED in scopes:
            return "mg1_reserved_window"
    return None


def check_read(day, purpose: str) -> None:
    reason = read_refusal(day, purpose)
    if reason:
        raise EmbargoRefused(reason, day=_day_text(day), purpose=purpose)


def embargo_guard(family: str, event_date, *, mode: str = "backfill", today=None) -> dict:
    """Refuse a request keyed to an embargoed event date before it is sent; return the decision."""
    if mode not in FETCH_MODES:
        raise ValueError(f"unknown fetch mode {mode!r}")
    text = _day_text(event_date)
    now_day = (today or datetime.now(timezone.utc).date())
    if isinstance(now_day, datetime):
        now_day = now_day.astimezone(timezone.utc).date()
    decision = {"family": family, "event_date": text, "mode": mode}
    if mode == "live":
        # Event-local dates run up to a day behind UTC; anything older is not a live poll.
        if date.fromisoformat(text) < now_day - timedelta(days=1):
            raise EmbargoRefused("live_mode_for_past_event_date", **decision)
        return {**decision, "decision": "allowed_live_capture"}
    scopes = day_scopes(text)
    if scopes:
        raise EmbargoRefused("fetch_event_date_embargoed", scopes=list(scopes), **decision)
    return {**decision, "decision": "allowed"}
