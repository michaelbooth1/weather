"""Information-event calendar and quote-pull gate helpers.

The calendar is deterministic and offline: it combines source-specific weather
print windows, model release/update windows, market timing, and configured
manual platform/reward events into policy-ready gate decisions.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from weather.paths import config_path

from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import REGISTRY, spec_for_id
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("info_event_calendar")
DEFAULT_CONFIG_PATH = config_path() / "info_event_calendar.json"

PULL_ACTIONS = {"pull", "suppress", "block", "no_quote"}
WIDEN_ACTIONS = {"widen", "wide"}
EVENT_PRIORITY = {
    "suppress": 0,
    "pull": 0,
    "block": 0,
    "no_quote": 0,
    "widen": 1,
    "wide": 1,
    "observe": 2,
    "none": 3,
}


DEFAULT_CALENDAR_CONFIG = {
    "schema_version": SCHEMA_VERSION,
    "enabled": True,
    "horizon_minutes": 360,
    "observed_prints": {
        "metar": {
            "enabled": True,
            "minutes": [52],
            "pre_seconds": 300,
            "post_seconds": 420,
            "action": "suppress",
            "reason_code": "INFO_EVENT_METAR_PRINT",
            "event_class": "metar_print_window",
            "label": "METAR expected print",
        },
        "eccc_swob": {
            "enabled": True,
            "minutes": [0, 10, 20, 30, 40, 50],
            "pre_seconds": 15,
            "post_seconds": 75,
            "action": "suppress",
            "reason_code": "INFO_EVENT_SWOB_PRINT",
            "event_class": "swob_print_window",
            "label": "SWOB expected print",
        },
        "wu_current": {
            "enabled": True,
            "minutes": [0, 15, 30, 45],
            "pre_seconds": 30,
            "post_seconds": 90,
            "action": "widen",
            "reason_code": "INFO_EVENT_WU_CURRENT_PRINT",
            "event_class": "wu_current_print_window",
            "label": "WU current expected update",
        },
    },
    "nwp_release_cycles": {
        "enabled": True,
        "cycle_hours_utc": [0, 6, 12, 18],
        "release_delay_minutes": 210,
        "pre_minutes": 10,
        "post_minutes": 25,
        "action": "suppress",
        "reason_code": "INFO_EVENT_NWP_RELEASE",
        "event_class": "nwp_release_cycle",
        "label": "NWP release cycle",
    },
    "forecast_archive_update": {
        "enabled": True,
        "local_time": "06:30",
        "pre_minutes": 10,
        "post_minutes": 20,
        "action": "widen",
        "reason_code": "INFO_EVENT_FORECAST_ARCHIVE",
        "event_class": "forecast_archive_update",
        "label": "forecast archive update",
    },
    "market_timing": {
        "enabled": True,
        "open_local_time": "00:00",
        "close_local_time": "23:59",
        "resolution_local_time": "00:10",
        "open_pre_minutes": 5,
        "open_post_minutes": 15,
        "close_pre_minutes": 30,
        "close_post_minutes": 20,
        "resolution_pre_minutes": 15,
        "resolution_post_minutes": 45,
        "open_action": "widen",
        "close_action": "suppress",
        "resolution_action": "suppress",
    },
    "reward_campaign_epochs": {
        "enabled": True,
        "events": [],
        "default_action": "widen",
        "reason_code": "INFO_EVENT_REWARD_EPOCH",
    },
    "platform_maintenance": {
        "enabled": True,
        "events": [],
        "default_action": "suppress",
        "reason_code": "INFO_EVENT_PLATFORM_MAINTENANCE",
    },
    "manual_events": [],
}


def parse_time(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def utc_now(value=None):
    return parse_time(value) or datetime.now(timezone.utc)


def _deep_merge(base, override):
    merged = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_calendar_config(path=DEFAULT_CONFIG_PATH, overrides=None):
    """Load calendar config, falling back to built-in defaults when absent."""
    payload = {}
    source_state = "default"
    path = Path(path) if path not in (None, "") else None
    if path and path.exists():
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        source_state = "file"
    config = _deep_merge(DEFAULT_CALENDAR_CONFIG, payload)
    config = _deep_merge(config, overrides or {})
    config["schema_version"] = SCHEMA_VERSION
    config["source_path"] = str(path) if path else ""
    config["source_state"] = source_state
    return config


def _parse_local_time(value, default):
    if not value:
        return default
    try:
        hour, minute = str(value).split(":", 1)
        return time(int(hour), int(minute))
    except (TypeError, ValueError):
        return default


def _event_id(market_id, event_class, scheduled_at):
    stamp = scheduled_at.strftime("%Y%m%dT%H%M%SZ")
    return f"{market_id}:{event_class}:{stamp}"


def _event(
    market_id,
    event_class,
    label,
    scheduled_at,
    starts_at,
    ends_at,
    action,
    reason_code,
    source="",
    event_slug="",
    detail="",
):
    scheduled_at = scheduled_at.astimezone(timezone.utc)
    starts_at = starts_at.astimezone(timezone.utc)
    ends_at = ends_at.astimezone(timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": _event_id(market_id, event_class, scheduled_at),
        "market_id": market_id,
        "event_slug": event_slug or "",
        "event_class": event_class,
        "event_label": label,
        "source": source,
        "scheduled_at_utc": scheduled_at.isoformat(),
        "starts_at_utc": starts_at.isoformat(),
        "ends_at_utc": ends_at.isoformat(),
        "action": normalize_action(action),
        "reason_code": reason_code,
        "reason_detail": detail or f"{label} for {market_id}",
    }


def normalize_action(value):
    text = str(value or "observe").strip().lower()
    if text in {"none", "clear", "observe", "allow"}:
        return "observe"
    if text in WIDEN_ACTIONS:
        return "widen"
    if text in PULL_ACTIONS:
        return "suppress"
    return text


def _scheduled_hourly_events(market_id, event_slug, source, spec_config, now, horizon):
    if not spec_config.get("enabled", True):
        return []
    minutes = [int(value) for value in spec_config.get("minutes") or []]
    if not minutes:
        return []
    max_pre = max(0.0, float(spec_config.get("pre_seconds") or 0.0))
    max_post = max(0.0, float(spec_config.get("post_seconds") or 0.0))
    start = now - timedelta(seconds=max_pre, minutes=60)
    end = now + timedelta(minutes=float(horizon), seconds=max_post)
    cursor = start.replace(minute=0, second=0, microsecond=0)
    rows = []
    while cursor <= end:
        for minute in minutes:
            if minute < 0 or minute > 59:
                continue
            scheduled = cursor + timedelta(minutes=minute)
            rows.append(_event(
                market_id,
                spec_config.get("event_class") or f"{source}_print_window",
                spec_config.get("label") or f"{source} print",
                scheduled,
                scheduled - timedelta(seconds=max_pre),
                scheduled + timedelta(seconds=max_post),
                spec_config.get("action") or "suppress",
                spec_config.get("reason_code") or f"INFO_EVENT_{source.upper()}_PRINT",
                source=source,
                event_slug=event_slug,
            ))
        cursor += timedelta(hours=1)
    return rows


def _nwp_events(market_id, event_slug, config, now, horizon):
    item = config.get("nwp_release_cycles") or {}
    if not item.get("enabled", True):
        return []
    release_delay = timedelta(minutes=float(item.get("release_delay_minutes") or 0.0))
    pre = timedelta(minutes=float(item.get("pre_minutes") or 0.0))
    post = timedelta(minutes=float(item.get("post_minutes") or 0.0))
    start_day = (now - timedelta(days=1)).date()
    end = now + timedelta(minutes=float(horizon), days=1)
    rows = []
    for day_offset in range(4):
        day = start_day + timedelta(days=day_offset)
        for hour in item.get("cycle_hours_utc") or []:
            scheduled = datetime(day.year, day.month, day.day, int(hour), tzinfo=timezone.utc) + release_delay
            if scheduled - pre <= end and scheduled + post >= now - pre:
                rows.append(_event(
                    market_id,
                    item.get("event_class") or "nwp_release_cycle",
                    item.get("label") or "NWP release cycle",
                    scheduled,
                    scheduled - pre,
                    scheduled + post,
                    item.get("action") or "suppress",
                    item.get("reason_code") or "INFO_EVENT_NWP_RELEASE",
                    source="nwp",
                    event_slug=event_slug,
                ))
    return rows


def _forecast_archive_events(spec, market_id, event_slug, config, now, horizon):
    item = config.get("forecast_archive_update") or {}
    if not item.get("enabled", True):
        return []
    local_t = _parse_local_time(item.get("local_time"), time(6, 30))
    pre = timedelta(minutes=float(item.get("pre_minutes") or 0.0))
    post = timedelta(minutes=float(item.get("post_minutes") or 0.0))
    local_now = now.astimezone(spec.tz)
    rows = []
    for day_offset in (-1, 0, 1):
        local_day = local_now.date() + timedelta(days=day_offset)
        scheduled_local = datetime.combine(local_day, local_t, tzinfo=spec.tz)
        scheduled = scheduled_local.astimezone(timezone.utc)
        if scheduled - pre <= now + timedelta(minutes=float(horizon)) and scheduled + post >= now - pre:
            rows.append(_event(
                market_id,
                item.get("event_class") or "forecast_archive_update",
                item.get("label") or "forecast archive update",
                scheduled,
                scheduled - pre,
                scheduled + post,
                item.get("action") or "widen",
                item.get("reason_code") or "INFO_EVENT_FORECAST_ARCHIVE",
                source="forecast_archive",
                event_slug=event_slug,
            ))
    return rows


def _target_date_for_row(event_slug, spec, now):
    parsed = date_from_event_slug(event_slug)
    if parsed:
        return parsed
    return now.astimezone(spec.tz).date()


def _market_timing_events(spec, market_id, event_slug, config, now, horizon):
    item = config.get("market_timing") or {}
    if not item.get("enabled", True):
        return []
    target = _target_date_for_row(event_slug, spec, now)
    rows = []
    definitions = [
        (
            "market_open",
            "market open",
            _parse_local_time(item.get("open_local_time"), time(0, 0)),
            target,
            float(item.get("open_pre_minutes") or 0.0),
            float(item.get("open_post_minutes") or 0.0),
            item.get("open_action") or "widen",
            "INFO_EVENT_MARKET_OPEN",
        ),
        (
            "market_close",
            "market close",
            _parse_local_time(item.get("close_local_time"), time(23, 59)),
            target,
            float(item.get("close_pre_minutes") or 0.0),
            float(item.get("close_post_minutes") or 0.0),
            item.get("close_action") or "suppress",
            "INFO_EVENT_MARKET_CLOSE",
        ),
        (
            "market_resolution",
            "market resolution",
            _parse_local_time(item.get("resolution_local_time"), time(0, 10)),
            target + timedelta(days=1),
            float(item.get("resolution_pre_minutes") or 0.0),
            float(item.get("resolution_post_minutes") or 0.0),
            item.get("resolution_action") or "suppress",
            "INFO_EVENT_MARKET_RESOLUTION",
        ),
    ]
    horizon_end = now + timedelta(minutes=float(horizon))
    for event_class, label, local_t, local_day, pre_min, post_min, action, reason in definitions:
        scheduled = datetime.combine(local_day, local_t, tzinfo=spec.tz).astimezone(timezone.utc)
        pre = timedelta(minutes=pre_min)
        post = timedelta(minutes=post_min)
        if scheduled - pre <= horizon_end and scheduled + post >= now - pre:
            rows.append(_event(
                market_id,
                event_class,
                label,
                scheduled,
                scheduled - pre,
                scheduled + post,
                action,
                reason,
                source="market",
                event_slug=event_slug,
            ))
    return rows


def _manual_event_rows(market_id, event_slug, items, default_action, default_reason):
    rows = []
    for index, item in enumerate(items or []):
        markets = item.get("markets") or item.get("market_ids") or item.get("market_id") or "*"
        if isinstance(markets, str):
            markets = [value.strip() for value in markets.split(",") if value.strip()]
        if "*" not in markets and market_id not in markets:
            continue
        starts = parse_time(item.get("starts_at_utc") or item.get("start_utc") or item.get("start"))
        ends = parse_time(item.get("ends_at_utc") or item.get("end_utc") or item.get("end"))
        scheduled = parse_time(item.get("scheduled_at_utc") or item.get("time_utc")) or starts
        if starts is None and scheduled is not None:
            starts = scheduled
        if ends is None and scheduled is not None:
            ends = scheduled + timedelta(minutes=float(item.get("duration_minutes") or 0.0))
        if scheduled is None or starts is None or ends is None or ends <= starts:
            continue
        event_class = item.get("event_class") or item.get("class") or "manual_information_event"
        row = _event(
            market_id,
            event_class,
            item.get("label") or item.get("name") or event_class.replace("_", " "),
            scheduled,
            starts,
            ends,
            item.get("action") or default_action,
            item.get("reason_code") or default_reason,
            source=item.get("source") or "manual",
            event_slug=item.get("event_slug") or event_slug,
            detail=item.get("reason_detail") or item.get("detail") or "",
        )
        row["event_id"] = item.get("event_id") or f"{row['event_id']}:{index}"
        rows.append(row)
    return rows


def scheduled_events_for_market(market_id, now=None, event_slug="", horizon_minutes=None, config=None):
    """Return scheduled information events for one market around ``now``."""
    now = utc_now(now)
    config = _deep_merge(DEFAULT_CALENDAR_CONFIG, config or {})
    config["schema_version"] = SCHEMA_VERSION
    horizon = float(horizon_minutes if horizon_minutes is not None else config.get("horizon_minutes", 360))
    spec = spec_for_id(market_id) if market_id in REGISTRY else None
    if spec is None:
        return []
    rows = []
    observed = config.get("observed_prints") or {}
    for source, source_config in observed.items():
        if source in {"eccc_swob", "swob"} and "eccc_swob" not in spec.sources:
            continue
        if source == "metar" and "metar" not in spec.sources:
            continue
        if source == "wu_current" and "wu_current" not in spec.sources:
            continue
        rows.extend(_scheduled_hourly_events(market_id, event_slug, source, source_config, now, horizon))
    if any(source in spec.sources for source in ("weather_forecast", "open_meteo", "global_ensemble", "nws_hourly", "nws_grid")):
        rows.extend(_nwp_events(market_id, event_slug, config, now, horizon))
        rows.extend(_forecast_archive_events(spec, market_id, event_slug, config, now, horizon))
    rows.extend(_market_timing_events(spec, market_id, event_slug, config, now, horizon))
    reward = config.get("reward_campaign_epochs") or {}
    if reward.get("enabled", True):
        rows.extend(_manual_event_rows(
            market_id,
            event_slug,
            reward.get("events") or [],
            reward.get("default_action") or "widen",
            reward.get("reason_code") or "INFO_EVENT_REWARD_EPOCH",
        ))
    maintenance = config.get("platform_maintenance") or {}
    if maintenance.get("enabled", True):
        rows.extend(_manual_event_rows(
            market_id,
            event_slug,
            maintenance.get("events") or [],
            maintenance.get("default_action") or "suppress",
            maintenance.get("reason_code") or "INFO_EVENT_PLATFORM_MAINTENANCE",
        ))
    rows.extend(_manual_event_rows(
        market_id,
        event_slug,
        config.get("manual_events") or [],
        "suppress",
        "INFO_EVENT_MANUAL",
    ))
    rows.sort(key=lambda row: (row.get("starts_at_utc") or "", EVENT_PRIORITY.get(row.get("action"), 9), row.get("event_id") or ""))
    return rows


def _active_at(event, now):
    starts = parse_time(event.get("starts_at_utc"))
    ends = parse_time(event.get("ends_at_utc"))
    return starts is not None and ends is not None and starts <= now < ends


def _future_event(event, now):
    starts = parse_time(event.get("starts_at_utc"))
    return starts is not None and starts >= now


def exception_permits_event(active_event, policy_config):
    """Return exception metadata when a suppressing event is explicitly permitted."""
    if not active_event:
        return None
    if not bool_value(policy_config.get("event_gate_exception_enabled"), False):
        return None
    classes = policy_config.get("event_gate_exception_event_classes") or ""
    if isinstance(classes, str):
        classes = [value.strip() for value in classes.split(",") if value.strip()]
    event_class = active_event.get("event_class")
    if "*" not in classes and event_class not in classes:
        return None
    evidence_status = str(policy_config.get("event_gate_exception_evidence_status") or "").strip().upper()
    if evidence_status not in {"PASS", "PAPER_PASS", "LIVE_FORWARD_PASS"}:
        return None
    evidence_id = str(policy_config.get("event_gate_exception_evidence_id") or "").strip()
    risk_cap = finite_float(policy_config.get("event_gate_exception_risk_cap_usdc"))
    if not evidence_id or risk_cap is None or risk_cap <= 0:
        return None
    return {
        "exception_id": evidence_id,
        "evidence_status": evidence_status,
        "risk_cap_usdc": risk_cap,
        "reason": "explicit event-window exception backed by passing paper/live-forward slice and bounded risk cap",
    }


def event_gate_for_market(market_id, now=None, event_slug="", config=None, policy_config=None):
    now = utc_now(now)
    config = _deep_merge(DEFAULT_CALENDAR_CONFIG, config or {})
    config["schema_version"] = SCHEMA_VERSION
    policy_config = policy_config or {}
    if not bool_value(config.get("enabled"), True):
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": now.isoformat(),
            "market_id": market_id,
            "event_slug": event_slug or "",
            "status": "DISABLED",
            "action": "none",
            "reason_code": "INFO_EVENT_GATE_DISABLED",
            "reason_detail": "information-event calendar disabled",
            "active_events": [],
            "next_event": None,
            "exception": None,
        }
    events = scheduled_events_for_market(
        market_id,
        now=now,
        event_slug=event_slug,
        horizon_minutes=config.get("horizon_minutes", 360),
        config=config,
    )
    active = [event for event in events if _active_at(event, now)]
    future = [event for event in events if _future_event(event, now)]
    active.sort(key=lambda row: (EVENT_PRIORITY.get(row.get("action"), 9), row.get("starts_at_utc") or "", row.get("event_id") or ""))
    future.sort(key=lambda row: (row.get("starts_at_utc") or "", EVENT_PRIORITY.get(row.get("action"), 9), row.get("event_id") or ""))
    primary = active[0] if active else None
    next_event = future[0] if future else None
    exception = exception_permits_event(primary, policy_config)
    if primary and primary.get("action") == "suppress" and exception:
        status = "EXCEPTION"
        action = "allow_exception"
        reason_code = "INFO_EVENT_EXCEPTION_ALLOWED"
        reason_detail = exception["reason"]
    elif primary and primary.get("action") == "suppress":
        status = "PULL"
        action = "suppress"
        reason_code = primary.get("reason_code") or "INFO_EVENT_PULL"
        reason_detail = primary.get("reason_detail") or "information event pull window"
    elif primary and primary.get("action") == "widen":
        status = "WIDEN"
        action = "widen"
        reason_code = primary.get("reason_code") or "INFO_EVENT_WIDEN"
        reason_detail = primary.get("reason_detail") or "information event widen window"
    elif primary:
        status = "OBSERVE"
        action = "observe"
        reason_code = primary.get("reason_code") or "INFO_EVENT_OBSERVE"
        reason_detail = primary.get("reason_detail") or "information event observe window"
    else:
        status = "CLEAR"
        action = "none"
        reason_code = "INFO_EVENT_CLEAR"
        reason_detail = "no active information-event gate"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "market_id": market_id,
        "event_slug": event_slug or "",
        "status": status,
        "action": action,
        "reason_code": reason_code,
        "reason_detail": reason_detail,
        "active_events": active,
        "next_event": next_event,
        "exception": exception,
    }


def event_gate_for_row(row, now=None, config=None, policy_config=None):
    return event_gate_for_market(
        row.get("market_id") or "",
        now=now,
        event_slug=row.get("event_slug") or "",
        config=config,
        policy_config=policy_config,
    )


def quote_event_gate_fields(gate):
    gate = gate or {}
    active = (gate.get("active_events") or [{}])[0]
    next_event = gate.get("next_event") or {}
    exception = gate.get("exception") or {}
    return {
        "event_gate_schema_version": gate.get("schema_version") or SCHEMA_VERSION,
        "event_gate_status": gate.get("status") or "UNKNOWN",
        "event_gate_action": gate.get("action") or "none",
        "event_gate_reason_code": gate.get("reason_code") or "",
        "event_gate_reason_detail": gate.get("reason_detail") or "",
        "event_gate_event_id": active.get("event_id") or "",
        "event_gate_event_class": active.get("event_class") or "",
        "event_gate_source": active.get("source") or "",
        "event_gate_starts_at_utc": active.get("starts_at_utc") or "",
        "event_gate_ends_at_utc": active.get("ends_at_utc") or "",
        "event_gate_next_event_id": next_event.get("event_id") or "",
        "event_gate_next_event_class": next_event.get("event_class") or "",
        "event_gate_next_event_at_utc": next_event.get("starts_at_utc") or "",
        "event_gate_exception_id": exception.get("exception_id") or "",
        "event_gate_exception_risk_cap_usdc": exception.get("risk_cap_usdc") or "",
    }


def bool_value(value, default=False):
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "pass"}:
        return True
    if text in {"0", "false", "no", "n", "fail"}:
        return False
    return default


def finite_float(value, default=None):
    if value in (None, ""):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _truthy_quote(value):
    return bool_value(value, False)


def summarize_event_gate_rows(rows):
    rows = list(rows or [])
    statuses = Counter(row.get("event_gate_status") or "UNKNOWN" for row in rows)
    actions = Counter(row.get("event_gate_action") or "none" for row in rows)
    reasons = Counter(row.get("event_gate_reason_code") or "-" for row in rows)
    active = {}
    next_events = {}
    for row in rows:
        event_id = row.get("event_gate_event_id")
        if event_id and event_id not in active:
            active[event_id] = {
                "event_id": event_id,
                "market_id": row.get("market_id") or "",
                "event_class": row.get("event_gate_event_class") or "",
                "source": row.get("event_gate_source") or "",
                "starts_at_utc": row.get("event_gate_starts_at_utc") or "",
                "ends_at_utc": row.get("event_gate_ends_at_utc") or "",
                "action": row.get("event_gate_action") or "",
                "reason_code": row.get("event_gate_reason_code") or "",
            }
        next_id = row.get("event_gate_next_event_id")
        market_id = row.get("market_id") or ""
        if next_id and market_id and market_id not in next_events:
            next_events[market_id] = {
                "event_id": next_id,
                "market_id": market_id,
                "event_class": row.get("event_gate_next_event_class") or "",
                "starts_at_utc": row.get("event_gate_next_event_at_utc") or "",
            }
    return {
        "schema_version": SCHEMA_VERSION,
        "row_count": len(rows),
        "status_counts": dict(sorted(statuses.items())),
        "action_counts": dict(sorted(actions.items())),
        "reason_counts": dict(sorted(reasons.items())),
        "pull_rows": actions.get("suppress", 0),
        "widen_rows": actions.get("widen", 0),
        "exception_rows": actions.get("allow_exception", 0),
        "quote_rows_during_event": sum(
            1 for row in rows
            if _truthy_quote(row.get("quote_permission"))
            and (row.get("event_gate_status") or "") in {"WIDEN", "EXCEPTION", "OBSERVE"}
        ),
        "active_events": sorted(active.values(), key=lambda row: (row.get("starts_at_utc") or "", row.get("event_id") or "")),
        "next_events": sorted(next_events.values(), key=lambda row: (row.get("starts_at_utc") or "", row.get("market_id") or "")),
    }


def score_event_gate_decisions(quote_rows, fill_rows=None):
    quote_row_count = 0
    suppressed_count = 0
    widened_count = 0
    exception_count = 0
    opportunity = 0.0
    avoided = 0.0
    evidence_rows = 0
    by_class = Counter()
    for row in quote_rows or []:
        quote_row_count += 1
        action = row.get("event_gate_action") or ""
        relevant = False
        if action == "suppress" and not _truthy_quote(row.get("quote_permission")):
            suppressed_count += 1
            relevant = True
            edge = finite_float(row.get("edge"), 0.0) or 0.0
            size = finite_float(row.get("bid_size"), None)
            if size in (None, 0.0):
                size = finite_float(row.get("ask_size"), None)
            if size in (None, 0.0):
                size = finite_float(row.get("quote_size"), 5.0) or 5.0
            opportunity += max(0.0, abs(edge)) * max(0.0, size)
            value = finite_float(
                row.get("event_gate_avoided_toxicity_usdc")
                or row.get("avoided_toxicity_usdc")
                or row.get("markout_30m_adverse_usdc")
            )
            if value is not None:
                avoided += max(0.0, value)
                evidence_rows += 1
        elif action == "widen":
            widened_count += 1
            relevant = True
        elif action == "allow_exception":
            exception_count += 1
            relevant = True
        if relevant:
            by_class[row.get("event_gate_event_class") or "unknown"] += 1
    exception_bad_markout = 0
    exception_net = 0.0
    exception_fill_rows = 0
    for row in fill_rows or []:
        if (row.get("event_gate_action") or "") != "allow_exception":
            continue
        exception_fill_rows += 1
        markout = finite_float(row.get("markout_30m_per_share"))
        if markout is not None and markout < 0:
            exception_bad_markout += 1
        exception_net += finite_float(row.get("net_pnl_after_fees_incentives_usdc"), 0.0) or 0.0
    return {
        "schema_version": SCHEMA_VERSION,
        "quote_rows": quote_row_count,
        "suppressed_rows": suppressed_count,
        "widen_rows": widened_count,
        "exception_rows": exception_count,
        "suppressed_opportunity_cost_usdc": round(opportunity, 6),
        "avoided_toxicity_usdc": round(avoided, 6),
        "avoided_toxicity_evidence_rows": evidence_rows,
        "exception_fill_rows": exception_fill_rows,
        "exception_negative_markout_fills": exception_bad_markout,
        "exception_net_pnl_after_fees_incentives_usdc": round(exception_net, 6),
        "by_event_class": dict(sorted(by_class.items())),
        "narrowing_gate": (
            "NEEDS_MARKOUT_EVIDENCE"
            if suppressed_count and evidence_rows < suppressed_count
            else "EVIDENCE_READY"
        ),
    }
