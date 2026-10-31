"""Read-only classification of execution-tape disconnects from gap rows.

Each market-day tape keeps an append-only gap ledger (``gaps-*.jsonl``): an
``OPEN`` row when a route stops being covered and a ``CLOSED`` row when a later
session proves it again.  One socket failure writes one ``OPEN`` row per route
on that connection, all sharing the session id, timestamp and reason.  This
command groups those rows back into socket-level events, classifies each
reason, and reports counts by local hour, dark seconds and session lifetimes.

It opens no connection, writes nothing unless ``--output`` is given, and reads
only the gap ledgers below ``--snapshots-root``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from weather.market.execution_tape_store import DEFAULT_SNAPSHOTS_ROOT, ensure_utc


DEFAULT_TIMEZONE = "America/Toronto"
DEFAULT_DAY_START_HOUR = 7
DEFAULT_DAY_END_HOUR = 23

# Ordered: the first matching pattern names the cause.
CAUSE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("silence_timeout", re.compile(r"before silence deadline")),
    ("confirmation_timeout", re.compile(r"subscription was not confirmed")),
    ("venue_close", re.compile(r"venue closed the websocket")),
    # Before the close code was read, a venue close frame and an empty data
    # frame both surfaced as this message.
    ("empty_frame", re.compile(r"websocket returned an empty frame")),
    ("connection_lost", re.compile(r"WebSocketConnectionClosedException")),
    ("connection_reset", re.compile(
        r"ConnectionResetError|ConnectionAbortedError|BrokenPipeError|WinError 1005[34]"
    )),
    ("handshake_rejected", re.compile(r"WebSocketBadStatusException|Handshake status")),
    ("tls_error", re.compile(r"SSL", re.IGNORECASE)),
    ("connect_failed", re.compile(
        r"gaierror|getaddrinfo|ConnectionRefusedError|WebSocketAddressException|WinError 10061"
    )),
    ("socket_timeout", re.compile(r"^(TimeoutError|WebSocketTimeoutException|timeout)\b")),
    ("tape_writer_error", re.compile(r"^(OSError|PermissionError|TornAppendError|ExecutionTape\w*Error)\b")),
    ("orderly_stop", re.compile(
        r"^(stop_requested|session_ended|message_limit_reached|capture_service_stopped|operator_stop)$"
    )),
    ("process_restart", re.compile(r"^(unclean_process_restart_from_|unhandled_)")),
    ("session_replaced", re.compile(r"^new_session_replaced_connected_session$")),
    ("startup", re.compile(r"^startup_connecting$")),
    ("seed_error", re.compile(r"^seed_error: ")),
)
VENUE_CLOSE_CODE = re.compile(r"code=(\d+|None)")


def classify_reason(reason: Any) -> str:
    text = str(reason or "")
    for cause, pattern in CAUSE_PATTERNS:
        if pattern.search(text):
            return cause
    return "other"


def venue_close_code(reason: Any) -> str | None:
    match = VENUE_CLOSE_CODE.search(str(reason or ""))
    return match.group(1) if match else None


def gap_ledgers(snapshots_root: str | Path, slug_glob: str = "*") -> list[Path]:
    root = Path(snapshots_root)
    return sorted(root.glob(f"{slug_glob}/execution_tape/gaps-*.jsonl"))


def _read_rows(path: Path) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    unreadable = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                unreadable += 1
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                unreadable += 1
    return rows, unreadable


def _percentiles(values: Iterable[float]) -> dict[str, Any]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {"n": 0}

    def at(fraction: float) -> float:
        return round(ordered[min(len(ordered) - 1, int(fraction * len(ordered)))], 3)

    return {
        "n": len(ordered),
        "sum": round(sum(ordered), 3),
        "p10": at(0.10),
        "median": round(statistics.median(ordered), 3),
        "p90": at(0.90),
        "max": round(ordered[-1], 3),
    }


def classify_disconnects(
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    *,
    local_date: str | date,
    timezone_name: str = DEFAULT_TIMEZONE,
    slug_glob: str = "*",
    day_start_hour: int = DEFAULT_DAY_START_HOUR,
    day_end_hour: int = DEFAULT_DAY_END_HOUR,
) -> dict[str, Any]:
    """Classify every gap that opened on ``local_date`` in ``timezone_name``."""

    target = date.fromisoformat(str(local_date))
    zone = ZoneInfo(timezone_name)
    inputs = []
    rows_by_route: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in gap_ledgers(snapshots_root, slug_glob):
        rows, unreadable = _read_rows(path)
        inputs.append({
            "path": str(path),
            "rows": len(rows),
            "unreadable_lines": unreadable,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
        for row in rows:
            route = f"{row.get('market_id')}:{row.get('target_date')}:{row.get('event_slug')}"
            rows_by_route[route].append(row)

    events: dict[tuple[str, str, str], dict[str, Any]] = {}
    lifecycle_rows = Counter()
    dark_by_cause: dict[str, list[float]] = defaultdict(list)
    for route, rows in rows_by_route.items():
        connected_since: datetime | None = None
        # Replay the route's ledger in event time: a CLOSED row happens when
        # coverage returned, an OPEN row when it stopped.
        for row in sorted(rows, key=lambda item: str(
            item.get("reconnected_at_utc") if item.get("gap_state") == "CLOSED"
            else item.get("disconnected_at_utc") or ""
        )):
            state = row.get("gap_state")
            if state == "CLOSED":
                if row.get("close_reason") == "websocket_connected" and row.get("reconnected_at_utc"):
                    connected_since = ensure_utc(row["reconnected_at_utc"])
                else:
                    connected_since = None
                if not row.get("disconnected_at_utc"):
                    continue
                opened = ensure_utc(row["disconnected_at_utc"]).astimezone(zone)
                if opened.date() == target:
                    dark_by_cause[classify_reason(row.get("reason"))].append(float(row.get("seconds_dark") or 0.0))
                continue
            if state != "OPEN" or not row.get("disconnected_at_utc"):
                continue
            at_utc = ensure_utc(row["disconnected_at_utc"])
            local = at_utc.astimezone(zone)
            lifetime = (at_utc - connected_since).total_seconds() if connected_since else None
            connected_since = None
            if local.date() != target:
                continue
            cause = classify_reason(row.get("reason"))
            lifecycle_rows[cause] += 1
            key = (str(row.get("session_id") or ""), str(row["disconnected_at_utc"]), str(row.get("reason") or ""))
            event = events.setdefault(key, {
                "cause": cause,
                "local_hour": local.hour,
                "was_ever_connected": bool(row.get("was_ever_connected")),
                "venue_close_code": venue_close_code(row.get("reason")) if cause == "venue_close" else None,
                "routes": set(),
                "lifetimes": [],
                "reason": str(row.get("reason") or ""),
            })
            event["routes"].add(route)
            if lifetime is not None:
                event["lifetimes"].append(lifetime)

    disconnects = [event for event in events.values() if event["was_ever_connected"]]
    by_cause = Counter(event["cause"] for event in disconnects)
    hourly: dict[int, Counter] = {hour: Counter() for hour in range(24)}
    for event in disconnects:
        hourly[event["local_hour"]][event["cause"]] += 1

    def is_day(hour: int) -> bool:
        return day_start_hour <= hour < day_end_hour

    day_hours = sum(1 for hour in range(24) if is_day(hour))
    split = {}
    for label, selector, hours in (
        ("daytime", is_day, day_hours),
        ("overnight", lambda hour: not is_day(hour), 24 - day_hours),
    ):
        counts = Counter()
        for hour in range(24):
            if selector(hour):
                counts.update(hourly[hour])
        split[label] = {
            "hours": hours,
            "socket_disconnects": sum(counts.values()),
            "per_hour": round(sum(counts.values()) / hours, 2) if hours else None,
            "by_cause": dict(counts.most_common()),
        }
    lifetimes_by_cause: dict[str, list[float]] = defaultdict(list)
    for event in disconnects:
        if event["lifetimes"]:
            lifetimes_by_cause[event["cause"]].append(statistics.median(event["lifetimes"]))
    examples: dict[str, Counter] = defaultdict(Counter)
    for event in events.values():
        examples[event["cause"]][event["reason"][:200]] += 1

    return {
        "local_date": target.isoformat(),
        "timezone": timezone_name,
        "snapshots_root": str(snapshots_root),
        "slug_glob": slug_glob,
        "definitions": {
            "lifecycle_row": "one OPEN gap row: one route stopped being covered",
            "socket_disconnect": "OPEN rows sharing session id, timestamp and reason on a route that had been connected",
            "daytime_hours": f"[{day_start_hour:02d}:00, {day_end_hour:02d}:00) local",
            "dark_seconds": "CLOSED rows whose gap opened on the date, attributed to the opening reason",
            "session_lifetime_seconds": "route proof (CLOSED websocket_connected) to the next OPEN row",
        },
        "inputs": inputs,
        "lifecycle_rows_by_cause": dict(lifecycle_rows.most_common()),
        "lifecycle_rows_total": sum(lifecycle_rows.values()),
        "socket_disconnects_total": len(disconnects),
        "startup_or_unconnected_events": sum(1 for event in events.values() if not event["was_ever_connected"]),
        "socket_disconnects_by_cause": dict(by_cause.most_common()),
        "venue_close_codes": dict(Counter(
            event["venue_close_code"] for event in disconnects if event["cause"] == "venue_close"
        ).most_common()),
        "hourly_socket_disconnects": {
            f"{hour:02d}": dict(counts.most_common()) for hour, counts in hourly.items()
        },
        "daytime_vs_overnight": split,
        "route_dark_seconds_by_cause": {
            cause: _percentiles(values) for cause, values in sorted(dark_by_cause.items())
        },
        "session_lifetime_seconds_by_cause": {
            cause: _percentiles(values) for cause, values in sorted(lifetimes_by_cause.items())
        },
        "reason_examples": {
            cause: [{"reason": reason, "events": count} for reason, count in counter.most_common(5)]
            for cause, counter in sorted(examples.items())
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--date", required=True, help="local date (YYYY-MM-DD) on which gaps opened")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--slug-glob", default="*", help="market-day directory glob, e.g. '*-on-september-29-2026'")
    parser.add_argument("--day-start-hour", type=int, default=DEFAULT_DAY_START_HOUR)
    parser.add_argument("--day-end-hour", type=int, default=DEFAULT_DAY_END_HOUR)
    parser.add_argument("--output", help="optional JSON path; stdout otherwise")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = classify_disconnects(
        args.snapshots_root,
        local_date=args.date,
        timezone_name=args.timezone,
        slug_glob=args.slug_glob,
        day_start_hour=args.day_start_hour,
        day_end_hour=args.day_end_hour,
    )
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
