"""Evidence-mode classification for market-making runs."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo


EVIDENCE_MODE_AUTO = "auto"
EVIDENCE_MODE_ACTIVE_DAY = "active_day_live_forward"
EVIDENCE_MODE_POST_SETTLEMENT = "post_settlement_evaluation"
EVIDENCE_MODE_OPERATOR_DRILL = "operator_drill"
EVIDENCE_MODES = {
    EVIDENCE_MODE_ACTIVE_DAY,
    EVIDENCE_MODE_POST_SETTLEMENT,
    EVIDENCE_MODE_OPERATOR_DRILL,
}
EVIDENCE_MODE_CHOICES = {EVIDENCE_MODE_AUTO, *EVIDENCE_MODES}
DEFAULT_ACTIVE_WINDOW_START = "07:00"
DEFAULT_ACTIVE_WINDOW_END = "20:00"


def parse_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def parse_hhmm(value):
    if isinstance(value, time):
        return value
    hour, minute = str(value).split(":", 1)
    return time(int(hour), int(minute))


def classify_market_making_evidence(
    target_date,
    *,
    now=None,
    timezone_name="America/Toronto",
    requested_mode=EVIDENCE_MODE_AUTO,
    run_mode="paper-live-forward",
    active_window_start=DEFAULT_ACTIVE_WINDOW_START,
    active_window_end=DEFAULT_ACTIVE_WINDOW_END,
):
    requested_mode = str(requested_mode or EVIDENCE_MODE_AUTO)
    if requested_mode not in EVIDENCE_MODE_CHOICES:
        raise ValueError(f"unsupported evidence mode: {requested_mode}")

    tz = ZoneInfo(timezone_name)
    parsed_now = parse_datetime(now) or datetime.now(timezone.utc)
    if parsed_now.tzinfo is None:
        parsed_now = parsed_now.replace(tzinfo=tz)
    local_now = parsed_now.astimezone(tz)
    target = parse_date(target_date)
    start = parse_hhmm(active_window_start)
    end = parse_hhmm(active_window_end)

    if requested_mode != EVIDENCE_MODE_AUTO:
        evidence_mode = requested_mode
        reason = "operator override"
    elif str(run_mode) != "paper-live-forward":
        evidence_mode = EVIDENCE_MODE_OPERATOR_DRILL
        reason = f"run mode {run_mode} is not paper-live-forward"
    elif target < local_now.date():
        evidence_mode = EVIDENCE_MODE_POST_SETTLEMENT
        reason = "target date is before local run date"
    elif target > local_now.date():
        evidence_mode = EVIDENCE_MODE_OPERATOR_DRILL
        reason = "target date is after local run date"
    elif local_now.time() < start:
        evidence_mode = EVIDENCE_MODE_OPERATOR_DRILL
        reason = "run started before active-day evidence window"
    elif local_now.time() > end:
        evidence_mode = EVIDENCE_MODE_POST_SETTLEMENT
        reason = "run started after active-day evidence window"
    else:
        evidence_mode = EVIDENCE_MODE_ACTIVE_DAY
        reason = "run started inside active-day evidence window"

    counts = evidence_mode == EVIDENCE_MODE_ACTIVE_DAY and str(run_mode) == "paper-live-forward"
    return {
        "evidence_mode": evidence_mode,
        "requested_evidence_mode": requested_mode,
        "counts_toward_live_forward_gate": bool(counts),
        "reason": reason,
        "target_date": target.isoformat(),
        "timezone": timezone_name,
        "run_started_at_utc": parsed_now.astimezone(timezone.utc).isoformat(),
        "run_started_at_local": local_now.isoformat(),
        "local_run_date": local_now.date().isoformat(),
        "active_window_start_local": start.strftime("%H:%M"),
        "active_window_end_local": end.strftime("%H:%M"),
    }
