"""Read-only health of the config-driven capture families (status.ps1 and the cockpit).

One row per family in ``config/capture_families.json``, read from its bounded
atomic ``data/maker_evidence_families/<id>/status.json``; journals are never
enumerated. The alarms are the 88a ones: while the family's Scheduler task is
registered and enabled, a status older than 180 s or a state other than
``CAPTURING`` is a FLAG. The one exception is the family's own brake: a family
stopped at its ``stop_below_free_gib`` floor is a WARN with its reason, because
it is protecting the 88a disk, not failing to capture.

Task names follow the registrar convention ``WeatherMakerEvidence<PascalId>``.
Before a family's task exists its row is informational only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

from weather.paths import config_path, data_path

FAMILY_CONFIG = config_path("capture_families.json")
FAMILIES_ROOT = data_path("maker_evidence_families")
CONFIG_MAX_BYTES = 65536
STATUS_MAX_BYTES = 262144  # the 88a status bound in status.ps1
STALE_SECONDS = 180  # the 88a freshness alarm in status.ps1
FAMILY_ID = re.compile(r"[a-z][a-z0-9_]{0,40}\Z")
FLOOR_STATE = "STOPPED_FAMILY_DISK_FLOOR"
GIB = 1024**3


def task_name(family_id):
    """Registrar convention: lowest_temperature -> WeatherMakerEvidenceLowestTemperature."""
    return "WeatherMakerEvidence" + "".join(part.capitalize() for part in family_id.split("_"))


def configured_families(path=FAMILY_CONFIG):
    raw = Path(path).read_bytes()
    if len(raw) > CONFIG_MAX_BYTES:
        raise ValueError("capture family config exceeds byte limit")
    payload = json.loads(raw.decode("utf-8-sig"))
    if payload.get("format_version") != 1 or not isinstance(payload.get("families"), dict):
        raise ValueError("unsupported capture family config")
    families = []
    for family_id, row in sorted(payload["families"].items()):
        if not FAMILY_ID.fullmatch(family_id):
            raise ValueError(f"invalid capture family id: {family_id!r}")
        families.append({"id": family_id, "task_name": task_name(family_id),
                         "stop_below_free_gib": int(row["stop_below_free_gib"]),
                         "max_conditions": int(row["max_conditions"])})
    return families


def _utc(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


def _read_status(path):
    if not path.is_file():
        return None, "missing status.json"
    if path.stat().st_size > STATUS_MAX_BYTES:
        return None, "status exceeds byte bound"
    try:
        status = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return None, f"status unreadable ({type(exc).__name__})"
    if not isinstance(status, dict):
        return None, "status is not an object"
    return status, None


def _request_rate(status):
    http, elapsed = status.get("http"), status.get("elapsed_seconds")
    if not isinstance(http, dict) or not isinstance(elapsed, (int, float)) or elapsed <= 0:
        return None
    return round(http.get("requests", 0) * 60 / elapsed, 1)


def assess_family(family, root, now, *, task_state=None):
    """Return one row: what the family is doing and whether it needs attention.

    ``task_state`` is the Scheduler state string, ``"absent"`` when no task is
    registered, or ``None`` when the caller cannot see the Scheduler (cockpit):
    then a family that has written a status is held to the alarms.
    """
    floor_bytes = family["stop_below_free_gib"] * GIB
    status, problem = _read_status(Path(root) / family["id"] / "status.json")
    row = {"family": family["id"], "task_name": family["task_name"], "task_state": task_state,
           "floor_gib": family["stop_below_free_gib"], "state": None, "age_seconds": None,
           "conditions": None, "max_conditions": family["max_conditions"], "missing_events": None,
           "free_gib": None, "disk_floor": "unknown", "requests_per_minute": None,
           "failed_cycles": None, "last_error": None, "severity": "OK", "reason": None}
    if status is not None:
        free = status.get("free_bytes")
        row.update(state=status.get("state"), conditions=status.get("universe_size"),
                   failed_cycles=status.get("failed_cycles"), last_error=status.get("last_error"),
                   requests_per_minute=_request_rate(status))
        if isinstance(status.get("missing_events"), list):
            row["missing_events"] = len(status["missing_events"])
        if isinstance(free, (int, float)):
            row["free_gib"] = round(free / GIB, 1)
            row["disk_floor"] = "below" if free < floor_bytes else "above"
        if row["state"] == FLOOR_STATE:
            row["disk_floor"] = "stopped"
        try:
            row["age_seconds"] = int((now - _utc(status["updated_at_utc"])).total_seconds())
        except (KeyError, TypeError, ValueError):
            problem = "status has no valid updated_at_utc"

    armed = task_state not in ("absent", "Disabled") and (task_state is not None or status is not None)
    if not armed:
        row["severity"] = "INFO"
        row["reason"] = ("task disabled" if task_state == "Disabled" else
                         "task not registered" if task_state == "absent" else "no status yet")
    elif problem is not None:
        row["severity"], row["reason"] = "FLAG", problem
    elif row["age_seconds"] > STALE_SECONDS:
        row["severity"] = "FLAG"
        row["reason"] = f"status stale ({row['age_seconds']}s, state {row['state']})"
    elif row["state"] == FLOOR_STATE:
        # A planned brake at the family's own floor keeps the disk for 88a: not a capture failure.
        row["severity"] = "WARN"
        row["reason"] = (f"stopped at its own {row['floor_gib']} GiB free-space floor "
                         f"(free {row['free_gib']} GiB); a planned brake protecting 88a, not a capture failure")
    elif row["state"] != "CAPTURING":
        row["severity"] = "FLAG"
        row["reason"] = f"state {row['state']}" + (f": {row['last_error']}" if row["last_error"] else "")
    return row


def family_line(row):
    """One status.ps1 line; '-' where the status cannot say."""
    def show(value, suffix=""):
        return "-" if value is None else f"{value}{suffix}"
    floor = {"stopped": "STOPPED at", "below": "BELOW", "above": "above"}.get(row["disk_floor"], "unknown vs")
    return (f"{row['family']}: {show(row['state'], '')} ({row['severity']}), "
            f"age {show(row['age_seconds'], 's')}, {show(row['conditions'])}/{row['max_conditions']} conditions, "
            f"free {show(row['free_gib'], ' GiB')} {floor} {row['floor_gib']} GiB floor, "
            f"{show(row['requests_per_minute'])} req/min, task {show(row['task_state'], '')}")


def alarm_text(row):
    """status.ps1 FLAG/WARN text; never matches the watchdog's capture/disk class patterns."""
    return f"CAPTURE_FAMILY {row['family']}: {row['reason']}"


def collect(*, now=None, config=FAMILY_CONFIG, root=FAMILIES_ROOT, task_states=None):
    """Every configured family; ``task_states`` maps task name -> state (absent when missing)."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows = []
    for family in configured_families(config):
        state = None if task_states is None else task_states.get(family["task_name"], "absent")
        row = assess_family(family, root, now, task_state=state)
        row["line"] = family_line(row)
        rows.append(row)
    return {"families": rows,
            "flags": [alarm_text(row) for row in rows if row["severity"] == "FLAG"],
            "warns": [alarm_text(row) for row in rows if row["severity"] == "WARN"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=FAMILY_CONFIG)
    parser.add_argument("--root", type=Path, default=FAMILIES_ROOT)
    parser.add_argument("--task-state", action="append", default=[], metavar="TASK=STATE",
                        help="Scheduler state of a registered task; an unlisted family task is absent")
    args = parser.parse_args(argv)
    states = dict(item.split("=", 1) for item in args.task_state)
    try:
        payload = collect(config=args.config, root=args.root, task_states=states)
    except Exception as exc:  # noqa: BLE001 - the monitor must report, never crash
        payload = {"families": [], "warns": [],
                   "flags": [f"CAPTURE_FAMILY status unavailable: {type(exc).__name__}: {exc}"]}
    sys.stdout.write(json.dumps(payload) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
