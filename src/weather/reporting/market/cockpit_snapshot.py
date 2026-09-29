"""Read-only owner cockpit snapshot: money, work, health and exam.

Every source is optional. A missing or unreadable source yields
``{"available": False, "reason": ...}`` instead of an exception, so the page
can always render what it has. Nothing here writes, registers, signs or
places anything; the wallet section uses only the GET-only LAN client.

Embargo: during a replay exam no policy P&L or policy comparison is shown for
panel dates. The money section therefore carries wallet aggregates only and
drops the per-campaign ledger book.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re

from weather.paths import data_path


SCHEMA = "owner_cockpit_snapshot_v1"
HOST_HEALTH_PATH = data_path("alerts", "host_health_latest.json")
DISK_TRAIL_PATH = data_path("alerts", "disk_free_trail.jsonl")
MAKER_EVIDENCE_ROOT = data_path("maker_evidence")
DISK_FLOORS_GIB = (50, 40)  # suite floor, 88a critical stop (DECISION_LOG 2026-09-25)
TRAIL_TAIL_BYTES = 64 * 1024
HEALTH_STALE_MINUTES = 60
OWNER_WAIT_DAYS = 3  # worktrack check fails pending owner requests older than this

# Constants, not derived: DECISION_LOG 2026-09-27 "Owner signs maker replay
# Clarification 1" (maker-replay-2026-10-15-v1) and "One-sided edge thesis"
# (one-sided-edge-v0 second candidate).
EXAMS = (
    {
        "candidate": "maker-replay-2026-10-15-v1",
        "source": "DECISION_LOG 2026-09-27: replay Clarification 1 (option A)",
        "calibration": (date(2026, 9, 27), date(2026, 9, 29)),
        "panel": (date(2026, 9, 30), date(2026, 10, 13)),
        "settlement": date(2026, 10, 14),
        "look": date(2026, 10, 15),
    },
    {
        "candidate": "one-sided-edge-v0",
        "source": "DECISION_LOG 2026-09-27: one-sided edge thesis (second candidate)",
        "calibration": None,
        "panel": (date(2026, 10, 16), date(2026, 10, 29)),
        "settlement": None,
        "look": date(2026, 10, 31),
    },
)
EMBARGO_NOTE = "No policy P&L or policy comparison is shown for panel dates (replay exam embargo)."


def unavailable(reason):
    return {"available": False, "reason": str(reason)}


def _utc(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _guard(reader, *args, **kwargs):
    try:
        return reader(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - each source fails closed on its own
        return unavailable(f"{type(exc).__name__}: {exc}")


# --- Health -----------------------------------------------------------------

def read_host_health(path, now):
    path = Path(path)
    if not path.is_file():
        return unavailable(f"missing {path.name}")
    record = _read_json(path)
    if not isinstance(record, dict):
        return unavailable(f"{path.name} is not an object")
    age = None
    if record.get("ts"):
        age = round((now - _utc(record["ts"])).total_seconds() / 60, 1)
    alerts = [
        {key: alert.get(key) for key in ("severity", "class", "flag", "act")}
        for alert in record.get("alerts") or [] if isinstance(alert, dict)
    ]
    return {
        "available": True,
        "ts": record.get("ts"),
        "age_minutes": age,
        "stale": age is None or age > HEALTH_STALE_MINUTES,
        "verdict": record.get("verdict"),
        "top_severity": record.get("top_severity"),
        "window": record.get("window"),
        "streak": record.get("streak"),
        "today": record.get("today"),
        "alerts": alerts,
        "notes": [str(note) for note in record.get("notes") or []],
    }


def _tail_lines(path, limit):
    with Path(path).open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - limit))
        raw = handle.read()
    lines = raw.split(b"\n")
    if size > limit:
        lines = lines[1:]  # the first line is probably cut
    return [line.decode("utf-8-sig", "replace").strip() for line in lines if line.strip()]


def read_disk_trail(path, now, *, tail_bytes=TRAIL_TAIL_BYTES):
    """Slope over the last 24 h, as status.ps1 computes it, plus days to floors."""
    path = Path(path)
    if not path.is_file():
        return unavailable(f"missing {path.name}")
    samples = []
    for line in _tail_lines(path, tail_bytes):
        try:
            row = json.loads(line)
            samples.append((_utc(row["ts"]), float(row["free_gb"])))
        except (ValueError, KeyError, TypeError):
            continue
    samples = sorted(sample for sample in samples if sample[0] <= now)
    if not samples:
        return unavailable(f"no readable samples in the tail of {path.name}")
    latest_ts, latest_free = samples[-1]
    reference = [sample for sample in samples if sample[0] <= latest_ts - timedelta(hours=24)]
    result = {
        "available": True,
        "latest_ts": latest_ts.isoformat(),
        "free_gib": round(latest_free, 1),
        "sample_age_minutes": round((now - latest_ts).total_seconds() / 60, 1),
        "slope_gib_per_day": None,
        "slope_reason": "trail tail has no sample at least 24 h older than the latest",
        "days_to": {str(floor): None for floor in DISK_FLOORS_GIB},
    }
    if reference:
        ref_ts, ref_free = reference[-1]
        hours = (latest_ts - ref_ts).total_seconds() / 3600
        slope = (latest_free - ref_free) / hours * 24
        result["slope_gib_per_day"] = round(slope, 2)
        result["slope_reason"] = f"{ref_ts.isoformat()} to {latest_ts.isoformat()}"
        for floor in DISK_FLOORS_GIB:
            headroom = latest_free - floor
            if headroom <= 0:
                result["days_to"][str(floor)] = 0.0
            elif slope < 0:
                result["days_to"][str(floor)] = round(headroom / -slope, 1)
    return result


# --- Maker evidence (88a) ---------------------------------------------------

_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_SEGMENT_RE = re.compile(r"\d{2}-[0-9a-f]{12}\Z")


def closed_utc_dates(root, today):
    """UTC dates before today whose every hourly segment carries a seal manifest."""
    closed, unsealed = [], []
    for day_dir in sorted(Path(root).iterdir()):
        if not day_dir.is_dir() or not _DAY_RE.match(day_dir.name) or day_dir.name >= today.isoformat():
            continue
        segments = [seg for seg in day_dir.iterdir() if seg.is_dir() and _SEGMENT_RE.match(seg.name)]
        sealed = segments and all((seg / "manifest.json").exists() or (seg / "manifest.json.gz").exists()
                                  for seg in segments)
        (closed if sealed else unsealed).append(day_dir.name)
    return closed, unsealed


def read_maker_evidence(root, now):
    root = Path(root)
    if not root.is_dir():
        return unavailable(f"missing {root.name}/")
    status_path = root / "status.json"
    status = _read_json(status_path) if status_path.is_file() else None
    closed, unsealed = closed_utc_dates(root, now.date())
    result = {
        "available": True,
        "status": None if status is None else {
            key: status.get(key) for key in ("state", "priority", "updated_at_utc", "cycles", "failed_cycles",
                                             "dry_run", "stream_capped", "compression_error")
        },
        "status_reason": None if status is not None else "missing status.json",
        "closed_dates": closed,
        "unsealed_past_dates": unsealed,
    }
    if status is not None and status.get("updated_at_utc"):
        result["status_age_minutes"] = round((now - _utc(status["updated_at_utc"])).total_seconds() / 60, 1)
    return result


# --- Work -------------------------------------------------------------------

def read_work(root, decision_log, now):
    from weather.reporting.roadmap import worktrack

    records = worktrack.load_records(root)
    rows = worktrack.decision_rows(decision_log)
    waiting = []
    for key, record in sorted(records.items()):
        for need in record["needs_owner"]:
            if need["status"] != "pending":
                continue
            age = (now - worktrack.instant(need["since"])).total_seconds() / 86400
            waiting.append({"id": key, "title": record["title"], "question": need["question"],
                            "since": str(need["since"]), "age_days": round(age, 1),
                            "overdue": age > OWNER_WAIT_DAYS})
    open_records = [r for r in records.values() if r["status"] not in ("landed", "closed")]
    ready = [key for key, record in sorted(records.items())
             if record["status"] not in ("landed", "closed") and not worktrack.blockers(record, records, rows)]
    waiting.sort(key=lambda row: -row["age_days"])
    return {
        "available": True,
        "record_count": len(records),
        "open_count": len(open_records),
        "by_status": dict(sorted(Counter(r["status"] for r in open_records).items())),
        "by_owner": dict(sorted(Counter(r["owner"] for r in open_records).items())),
        "waiting_on_owner": waiting,
        "overdue_owner_count": sum(row["overdue"] for row in waiting),
        "ready_to_land": ready,
        "check_issues": worktrack.check(records, rows, now),
    }


# --- Money ------------------------------------------------------------------

def _decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def reward_total(payload):
    """Sum ``earnings`` over the venue total rows; None when the shape is unknown."""
    total = payload.get("total") if isinstance(payload, dict) else None
    rows = total if isinstance(total, list) else [total] if isinstance(total, dict) else None
    if rows is None:
        return None
    values = [_decimal(row.get("earnings")) for row in rows if isinstance(row, dict)]
    if not values or any(value is None for value in values):
        return None
    return str(sum(values, Decimal(0)))


def read_wallet(reader, now):
    """Aggregate wallet facts only. P&L is shown only when the reader says OBSERVED/BLEED_LIMIT."""
    from weather.market.wallet_reader_security import ReaderError

    try:
        summary = reader("summary")
    except ReaderError as exc:
        return unavailable(f"wallet reader {getattr(exc, 'reason', 'refused')}")
    if not isinstance(summary, dict):
        return unavailable("wallet reader summary is not an object")
    status = summary.get("status")
    campaigns = summary.get("campaigns") if isinstance(summary.get("campaigns"), dict) else None
    reasons = list(summary.get("incomplete_reasons") or [])
    if campaigns is not None:
        reasons.extend(str(reason) for reason in campaigns.get("reasons") or [])
    complete = status in ("OBSERVED", "BLEED_LIMIT") and summary.get("campaign_pnl_pusd") is not None
    money = {
        "available": True,
        "status": status,
        "captured_at_utc": summary.get("captured_at_utc"),
        "cash_pusd": summary.get("cash_pusd"),
        "marked_positions_pusd": summary.get("marked_positions_pusd"),
        "pnl_pusd": summary.get("campaign_pnl_pusd") if complete else None,
        "pnl_reason": None if complete else (f"{status}: " + ", ".join(reasons) if reasons
                                             else f"{status}: no campaign P&L reported"),
        "bleed_limit_reached": summary.get("bleed_limit_reached"),
        "position_count": len(summary.get("positions") or []),
        "open_order_count": None if summary.get("open_orders") is None else len(summary["open_orders"]),
        "unredeemed_count": len(summary.get("unredeemed_positions") or []),
        "errors": sorted((summary.get("errors") or {}).keys()),
    }
    day = (now.date() - timedelta(days=1)).isoformat()
    try:
        rewards = reader("rewards", day=day)
        money["rewards"] = {"available": True, "date": day, "total_pusd": reward_total(rewards),
                            "payment_verified": bool(rewards.get("payment_verified"))}
    except ReaderError as exc:
        money["rewards"] = unavailable(f"wallet reader {getattr(exc, 'reason', 'refused')}")
    return money


def _default_wallet_reader(command, **kwargs):
    from weather.market.wallet_reader_client import read_account

    return read_account(command, timeout=5, **kwargs)


# --- Exam -------------------------------------------------------------------

def _phase(exam, today):
    panel_start, panel_end = exam["panel"]
    calibration = exam["calibration"]
    if calibration and today < calibration[0]:
        return "before calibration"
    if calibration and today <= calibration[1]:
        return "calibration"
    if today < panel_start:
        return "before panel"
    if today <= panel_end:
        return f"panel day {(today - panel_start).days + 1} of {(panel_end - panel_start).days + 1}"
    if exam["settlement"] and today <= exam["settlement"]:
        return "settlement"
    if today < exam["look"]:
        return "awaiting look"
    if today == exam["look"]:
        return "look day"
    return "look passed"


def exam_state(now, closed_dates=None):
    today = now.date()
    closed = set(closed_dates or ())
    rows = []
    for exam in EXAMS:
        panel_start, panel_end = exam["panel"]
        panel_days = [(panel_start + timedelta(days=n)).isoformat() for n in range((panel_end - panel_start).days + 1)]
        rows.append({
            "candidate": exam["candidate"],
            "source": exam["source"],
            "phase": _phase(exam, today),
            "calibration": None if exam["calibration"] is None else [d.isoformat() for d in exam["calibration"]],
            "panel": [panel_start.isoformat(), panel_end.isoformat()],
            "settlement": None if exam["settlement"] is None else exam["settlement"].isoformat(),
            "look": exam["look"].isoformat(),
            "days_to_look": (exam["look"] - today).days,
            "panel_days_closed": None if closed_dates is None else sum(day in closed for day in panel_days),
            "panel_days_total": len(panel_days),
        })
    return {"available": True, "exams": rows, "embargo": EMBARGO_NOTE}


# --- Snapshot ---------------------------------------------------------------

def collect_cockpit_snapshot(*, now=None, host_health_path=HOST_HEALTH_PATH, disk_trail_path=DISK_TRAIL_PATH,
                             maker_evidence_root=MAKER_EVIDENCE_ROOT, work_root=None, decision_log=None,
                             wallet_reader=_default_wallet_reader):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if work_root is None or decision_log is None:
        from weather.reporting.roadmap import worktrack

        work_root = worktrack.DEFAULT_ROOT if work_root is None else work_root
        decision_log = worktrack.DEFAULT_DECISIONS if decision_log is None else decision_log
    maker = _guard(read_maker_evidence, maker_evidence_root, now)
    closed = maker.get("closed_dates") if maker.get("available") else None
    return {
        "schema_version": SCHEMA,
        "generated_at_utc": now.isoformat(),
        "money": _guard(read_wallet, wallet_reader, now),
        "work": _guard(read_work, work_root, decision_log, now),
        "health": {
            "host": _guard(read_host_health, host_health_path, now),
            "disk": _guard(read_disk_trail, disk_trail_path, now),
            "maker_evidence": maker,
        },
        "exam": _guard(exam_state, now, closed),
    }
