"""Read-only classification of 88a public stream drops from its journals.

The maker-evidence capture (88a) writes a ``stream_lifecycle`` row when a
public socket connects or disconnects and a ``stream_gap`` row when a session
ends on an error, both per channel (``trades`` or ``updates``) and per
subscription (one socket per 100 tokens).  This command replays those rows per
socket, classifies each gap's ``error_type: error`` text, and reports drops by
cause, channel and local hour, dark seconds to the next connect, and session
lifetimes.  It is the 88a sibling of ``weather.market.execution_tape_disconnects``
and shares its network cause patterns.

It opens no connection, writes nothing unless ``--output`` is given, and reads
only ``stream_lifecycle`` and ``stream_gap`` journals (plain or gzip) below
``--root``.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from weather.market.execution_tape_disconnects import (
    CAUSE_PATTERNS as NETWORK_CAUSE_PATTERNS,
    DEFAULT_DAY_END_HOUR,
    DEFAULT_DAY_START_HOUR,
    DEFAULT_TIMEZONE,
    _percentiles,
    venue_close_code,
)
from weather.market.maker_evidence_store import decode_body
from weather.paths import data_path

DEFAULT_ROOT = data_path("maker_evidence")
JOURNALS = ("stream_lifecycle", "stream_gap")

# Ordered: 88a's own messages first, then the execution-tape network patterns.
CAUSE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("silence_timeout", re.compile(r"public stream inbound silence")),
    ("venue_close", re.compile(r"venue closed the websocket")),
    # Before the opcode was read, a venue close frame and an empty data frame
    # both surfaced as this message.
    ("empty_frame", re.compile(r"public socket closed")),
    ("message_bound", re.compile(r"exceeds byte bound|oversized public control frame")),
    ("bad_payload", re.compile(r"non-object event|^(JSONDecodeError|UnicodeDecodeError)\b")),
    ("journal_writer_error", re.compile(r"^(OSError|PermissionError|FileNotFoundError)\b")),
) + tuple(item for item in NETWORK_CAUSE_PATTERNS if item[0] in {
    "connection_lost", "connection_reset", "handshake_rejected", "tls_error", "connect_failed", "socket_timeout",
})


def classify_gap(error_type, error):
    text = f"{error_type or ''}: {error or ''}"
    for cause, pattern in CAUSE_PATTERNS:
        if pattern.search(text):
            return cause
    return "other"


def journal_files(root, utc_days):
    """Each segment's lifecycle/gap journal, preferring the plain file while both exist."""
    files = []
    for day in utc_days:
        for folder in sorted(Path(root, day).glob("*")):
            if not folder.is_dir():
                continue
            for kind in JOURNALS:
                plain = folder / (kind + ".jsonl")
                zipped = plain.with_suffix(".jsonl.gz")
                if plain.exists() or zipped.exists():
                    files.append(plain if plain.exists() else zipped)
    return files


def _rows(path, root):
    stored = path.read_bytes()
    raw = gzip.decompress(stored) if path.suffix == ".gz" else stored
    segment = path.parent.relative_to(root).as_posix()
    rows, unreadable = [], 0
    for line in raw.splitlines():
        try:
            row = json.loads(line)
            body = json.loads(decode_body(row))
        except (ValueError, KeyError, TypeError):
            unreadable += 1
            continue
        if row.get("kind") in JOURNALS and isinstance(body, dict):
            rows.append({"at": datetime.fromisoformat(row["captured_at_utc"]), "segment": segment,
                         "sequence": int(row["sequence"]), "kind": row["kind"], "body": body})
    return rows, unreadable, hashlib.sha256(stored).hexdigest()


def classify_stream_drops(root=DEFAULT_ROOT, *, local_date, timezone_name=DEFAULT_TIMEZONE,
                          day_start_hour=DEFAULT_DAY_START_HOUR, day_end_hour=DEFAULT_DAY_END_HOUR):
    """Classify every 88a stream session that ended on ``local_date`` in ``timezone_name``."""
    target = date.fromisoformat(str(local_date))
    zone = ZoneInfo(timezone_name)
    root = Path(root)
    utc_days = [(target + timedelta(days=offset)).isoformat() for offset in (-1, 0, 1, 2)]
    inputs, by_socket = [], defaultdict(list)
    for path in journal_files(root, utc_days):
        rows, unreadable, sha = _rows(path, root)
        inputs.append({"path": str(path), "rows": len(rows), "unreadable_lines": unreadable, "sha256": sha})
        for row in rows:
            body = row["body"]
            subscription = (body.get("subscription") or {}).get("sha256", "")
            by_socket[(str(body.get("channel")), subscription)].append(row)

    drops = []
    for (channel, _), rows in by_socket.items():
        # A session's disconnected row precedes its gap row; both carry the time reading stopped.
        rows.sort(key=lambda row: (row["at"], row["kind"] == "stream_gap", row["segment"], row["sequence"]))
        connected_at = ended = dark_from = None
        for row in rows:
            body, at = row["body"], row["at"]
            state = body.get("state") if row["kind"] == "stream_lifecycle" else "gap"
            if state == "connected":
                if dark_from is not None:
                    dark_from["dark_seconds"] = (at - dark_from["at"]).total_seconds()
                connected_at, ended, dark_from = at, None, None
            elif state == "disconnected":
                ended = {"at": at, "cause": "orderly_stop", "channel": channel, "was_connected": True,
                         "lifetime": (at - connected_at).total_seconds() if connected_at else None,
                         "error": "", "dark_seconds": None}
                drops.append(ended)
                dark_from = dark_from or ended
                connected_at = None
            elif state == "gap":
                cause = classify_gap(body.get("error_type"), body.get("error"))
                error = f"{body.get('error_type')}: {body.get('error')}"
                if ended is not None:
                    ended.update(cause=cause, error=error)  # The gap row of the session that just ended.
                else:
                    failure = {"at": at, "cause": cause, "channel": channel, "was_connected": False,
                               "lifetime": None, "error": error, "dark_seconds": None}
                    drops.append(failure)
                    dark_from = dark_from or failure
                ended = None

    on_date = [drop for drop in drops if drop["at"].astimezone(zone).date() == target]
    socket_drops = [drop for drop in on_date if drop["was_connected"] and drop["cause"] != "orderly_stop"]
    hourly = {hour: Counter() for hour in range(24)}
    for drop in socket_drops:
        hourly[drop["at"].astimezone(zone).hour][drop["channel"] + ":" + drop["cause"]] += 1

    def is_day(hour):
        return day_start_hour <= hour < day_end_hour

    split = {}
    for label, selector in (("daytime", is_day), ("overnight", lambda hour: not is_day(hour))):
        hours = [hour for hour in range(24) if selector(hour)]
        counts = sum((hourly[hour] for hour in hours), Counter())
        split[label] = {"hours": len(hours), "socket_drops": sum(counts.values()),
                        "per_hour": round(sum(counts.values()) / len(hours), 2) if hours else None,
                        "by_channel_cause": dict(counts.most_common())}
    lifetimes, dark = defaultdict(list), defaultdict(list)
    for drop in on_date:
        if drop["dark_seconds"] is not None:
            dark[drop["cause"]].append(drop["dark_seconds"])
        if drop["lifetime"] is not None:
            lifetimes[drop["cause"]].append(drop["lifetime"])
    examples = defaultdict(Counter)
    for drop in on_date:
        if drop["error"]:
            examples[drop["cause"]][drop["error"][:200]] += 1
    return {
        "local_date": target.isoformat(),
        "timezone": timezone_name,
        "root": str(root),
        "definitions": {
            "socket": "one (channel, subscription sha256) pair; 88a opens one socket per 100 tokens per channel",
            "socket_drop": "a session that had connected and ended with a stream_gap row",
            "connect_failure": "a stream_gap row with no connected session before it (connect or handshake failed)",
            "orderly_stop": "a disconnected row with no gap: stop, token-set replacement, window end or daily cap",
            "daytime_hours": f"[{day_start_hour:02d}:00, {day_end_hour:02d}:00) local",
            "dark_seconds": "first drop or failure after a connect, to the next connected row on the same socket key",
            "session_lifetime_seconds": "connected row to the disconnected row",
        },
        "inputs": inputs,
        "socket_drops_total": len(socket_drops),
        "socket_drops_by_cause": dict(Counter(drop["cause"] for drop in socket_drops).most_common()),
        "socket_drops_by_channel_cause": dict(Counter(
            drop["channel"] + ":" + drop["cause"] for drop in socket_drops).most_common()),
        "connect_failures_by_cause": dict(Counter(
            drop["cause"] for drop in on_date if not drop["was_connected"]).most_common()),
        "orderly_stops_by_channel": dict(Counter(
            drop["channel"] for drop in on_date if drop["cause"] == "orderly_stop").most_common()),
        "venue_close_codes": dict(Counter(
            venue_close_code(drop["error"]) for drop in socket_drops if drop["cause"] == "venue_close").most_common()),
        "hourly_socket_drops": {f"{hour:02d}": dict(counts.most_common()) for hour, counts in hourly.items()},
        "daytime_vs_overnight": split,
        "dark_seconds_by_cause": {cause: _percentiles(values) for cause, values in sorted(dark.items())},
        "session_lifetime_seconds_by_cause": {
            cause: _percentiles(values) for cause, values in sorted(lifetimes.items())},
        "error_examples": {cause: [{"error": text, "drops": count} for text, count in counter.most_common(5)]
                           for cause, counter in sorted(examples.items())},
    }


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--date", required=True, help="local date (YYYY-MM-DD) on which sessions ended")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--day-start-hour", type=int, default=DEFAULT_DAY_START_HOUR)
    parser.add_argument("--day-end-hour", type=int, default=DEFAULT_DAY_END_HOUR)
    parser.add_argument("--output", help="optional JSON path; stdout otherwise")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    report = classify_stream_drops(args.root, local_date=args.date, timezone_name=args.timezone,
                                   day_start_hour=args.day_start_hour, day_end_hour=args.day_end_hour)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
