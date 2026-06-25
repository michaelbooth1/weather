"""Current-window daily-roll log health and archived incident separation."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from weather.io import read_jsonl, write_json_atomic
from weather.paths import data_path
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("daily_roll_log_hygiene")
DEFAULT_CURRENT_WINDOW_HOURS = 24.0
DEFAULT_JSON_OUT = data_path("backtest", "daily_roll_log_hygiene.json")
DEFAULT_INCIDENTS_OUT = data_path("backtest", "daily_roll_log_incidents.jsonl")
DEFAULT_CURRENT_LOG_ROOT = data_path("backtest", "daily_roll_current_logs")
DEFAULT_LOG_SOURCES = {
    "streamlit": data_path("logs", "streamlit_stderr.log"),
    "daily_refresh": data_path("logs", "daily_refresh.log"),
    "snapshot": data_path("snapshots", "loop_console.log"),
    "clob": data_path("snapshots", "clob_loop_console.log"),
    "observation_trigger": data_path("snapshots", "observation_trigger_console.log"),
    "taker": data_path("taker_runs", "daily_roll_console.log"),
    "maker": data_path("mm_runs", "daily_roll_console.log"),
}

ISO_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.\d+)?(?:Z|[+-][0-9]{2}:?[0-9]{2})?)"
)
DISK_PATTERNS = (
    "no space left on device",
    "winerror 112",
    "there is not enough space on the disk",
    "enospc",
    "disk full",
)
ENCODING_PATTERNS = (
    "unicodedecodeerror",
    "unicodeencodeerror",
    "codec can't decode",
    "codec can't encode",
    "charmap codec",
    "utf-8 codec",
)
GENERIC_ERROR_PATTERNS = (
    "traceback",
    "exception",
    "critical",
    " error ",
    "error:",
    "failed",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if re.search(r"[+-]\d{4}$", text):
        text = text[:-5] + text[-5:-2] + ":" + text[-2:]
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def timestamp_from_line(line: str) -> datetime | None:
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = {}
        for key in (
            "timestamp",
            "time",
            "created_at_utc",
            "generated_at_utc",
            "ts",
            "asctime",
        ):
            parsed = parse_time(payload.get(key))
            if parsed is not None:
                return parsed
    match = ISO_RE.search(stripped)
    if not match:
        return None
    return parse_time(match.group("ts").replace(" ", "T"))


def classify_error(line: str) -> str | None:
    stripped = line.strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            status = str(payload.get("status") or payload.get("level") or payload.get("severity") or "").casefold()
            if status in {"error", "exception", "failed", "critical", "fatal"}:
                return "console_error"
            top_level_error = next(
                (
                    value
                    for value in (
                        payload.get("error"),
                        payload.get("exception"),
                        payload.get("traceback"),
                    )
                    if value not in (None, "", False)
                ),
                None,
            )
            if top_level_error is None:
                return None
            text = f" {str(top_level_error).casefold()} "
            if any(pattern in text for pattern in DISK_PATTERNS):
                return "blocked_by_disk"
            if any(pattern in text for pattern in ENCODING_PATTERNS):
                return "encoding_error"
            return "console_error"
    text = f" {line.casefold()} "
    if any(pattern in text for pattern in DISK_PATTERNS):
        return "blocked_by_disk"
    if any(pattern in text for pattern in ENCODING_PATTERNS):
        return "encoding_error"
    if any(pattern in text for pattern in GENERIC_ERROR_PATTERNS):
        return "console_error"
    return None


def normalize_message(line: str) -> str:
    text = re.sub(r"\d{4}-\d{2}-\d{2}[T ][0-9:.+-Z]+", "<timestamp>", line)
    text = re.sub(r"\b\d+\b", "<n>", text)
    text = " ".join(text.strip().split())
    return text[:240]


def incident_id(loop: str, category: str, normalized_message: str) -> str:
    digest = hashlib.sha1(
        f"{loop}|{category}|{normalized_message}".encode("utf-8", errors="ignore")
    ).hexdigest()[:16]
    return f"daily_roll_{digest}"


def parse_log_sources(value: str | None) -> dict[str, Path]:
    if not value:
        return {}
    output = {}
    for item in str(value).split(","):
        if not item.strip():
            continue
        if "=" not in item:
            continue
        loop, path = item.split("=", 1)
        loop = loop.strip()
        if loop:
            output[loop] = Path(path.strip())
    return output


def read_existing_incidents(path: str | Path) -> dict[str, dict[str, Any]]:
    rows = read_jsonl(path)
    incidents = {}
    for row in rows:
        if isinstance(row, dict) and row.get("incident_id"):
            incidents[str(row["incident_id"])] = dict(row)
    return incidents


def _line_rows(loop: str, path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    try:
        inherited_timestamp = None
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, start=1):
                text = line.rstrip("\n")
                timestamp = timestamp_from_line(text)
                timestamp_inherited = False
                if timestamp is not None:
                    inherited_timestamp = timestamp
                elif inherited_timestamp is not None:
                    timestamp = inherited_timestamp
                    timestamp_inherited = True
                rows.append({
                    "loop": loop,
                    "path": str(path),
                    "line_number": number,
                    "timestamp_utc": timestamp.isoformat() if timestamp is not None else None,
                    "timestamp_inherited": timestamp_inherited,
                    "message": text,
                })
    except OSError as exc:
        rows.append({
            "loop": loop,
            "path": str(path),
            "line_number": None,
            "timestamp_utc": None,
            "message": f"failed to read log: {type(exc).__name__}: {exc}",
            "read_error": True,
        })
    return rows


def _error_row(row: dict[str, Any], *, category: str) -> dict[str, Any]:
    normalized = normalize_message(row.get("message") or "")
    loop = str(row.get("loop") or "unknown")
    return {
        "incident_id": incident_id(loop, category, normalized),
        "loop": loop,
        "category": category,
        "root_cause_category": category,
        "normalized_message": normalized,
        "sample_message": row.get("message"),
        "path": row.get("path"),
        "line_number": row.get("line_number"),
        "seen_at_utc": row.get("timestamp_utc"),
    }


def _merge_incident(existing: dict[str, Any] | None, error: dict[str, Any]) -> dict[str, Any]:
    existing = dict(existing or {})
    first_seen = existing.get("first_seen_utc") or error.get("seen_at_utc")
    last_seen = max(
        [value for value in [existing.get("last_seen_utc"), error.get("seen_at_utc")] if value],
        default=error.get("seen_at_utc"),
    )
    occurrence_count = int(existing.get("occurrence_count") or 0) + 1
    return {
        **existing,
        "incident_id": error.get("incident_id"),
        "loop": error.get("loop"),
        "category": error.get("category"),
        "root_cause_category": error.get("root_cause_category"),
        "normalized_message": error.get("normalized_message"),
        "sample_message": error.get("sample_message"),
        "first_seen_utc": first_seen,
        "last_seen_utc": last_seen,
        "incident_date": str(first_seen or "")[:10],
        "occurrence_count": occurrence_count,
        "resolution": "archived_historical",
        "resolution_detail": "outside current health window",
    }


def _source_rows(log_sources: dict[str, Path]) -> list[dict[str, Any]]:
    rows = []
    for loop, path in sorted(log_sources.items()):
        path = Path(path)
        rows.append({
            "loop": loop,
            "path": str(path),
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() else 0,
        })
    return rows


def current_signature_groups(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for error in errors:
        key = (
            str(error.get("loop") or "unknown"),
            str(error.get("category") or "unknown"),
            str(error.get("normalized_message") or ""),
        )
        group = grouped.setdefault(
            key,
            {
                "loop": key[0],
                "category": key[1],
                "normalized_message": key[2],
                "incident_id": error.get("incident_id"),
                "occurrence_count": 0,
                "first_seen_utc": error.get("seen_at_utc"),
                "last_seen_utc": error.get("seen_at_utc"),
                "sample_message": error.get("sample_message"),
                "sample_path": error.get("path"),
                "sample_line_number": error.get("line_number"),
            },
        )
        group["occurrence_count"] += 1
        seen_at = error.get("seen_at_utc")
        if seen_at:
            values = [value for value in [group.get("first_seen_utc"), seen_at] if value]
            group["first_seen_utc"] = min(values) if values else seen_at
            values = [value for value in [group.get("last_seen_utc"), seen_at] if value]
            group["last_seen_utc"] = max(values) if values else seen_at
    return sorted(
        grouped.values(),
        key=lambda row: (
            str(row.get("loop") or ""),
            str(row.get("category") or ""),
            str(row.get("normalized_message") or ""),
        ),
    )


def build_payload(
    *,
    log_sources: dict[str, str | Path] | None = None,
    incidents_path: str | Path = DEFAULT_INCIDENTS_OUT,
    current_window_hours: float = DEFAULT_CURRENT_WINDOW_HOURS,
    as_of: str | datetime | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at_utc or utc_now_iso()
    current = parse_time(as_of) or parse_time(generated_at) or datetime.now(timezone.utc)
    window_hours = float(current_window_hours)
    window_start = current - timedelta(hours=window_hours)
    sources = {
        loop: Path(path)
        for loop, path in (log_sources or DEFAULT_LOG_SOURCES).items()
    }
    existing_incidents = read_existing_incidents(incidents_path)
    incidents = dict(existing_incidents)
    current_errors = []
    historical_errors = []
    current_lines_by_loop: dict[str, list[str]] = {loop: [] for loop in sources}

    for loop, path in sorted(sources.items()):
        for row in _line_rows(loop, path):
            timestamp = parse_time(row.get("timestamp_utc"))
            is_current = timestamp is None or timestamp >= window_start
            if is_current:
                current_lines_by_loop.setdefault(loop, []).append(row.get("message") or "")
            category = classify_error(row.get("message") or "")
            if not category:
                continue
            error = _error_row(row, category=category)
            if is_current:
                if error["incident_id"] in existing_incidents:
                    error["recurrence_of_incident_id"] = error["incident_id"]
                current_errors.append(error)
            else:
                historical_errors.append(error)
                incidents[error["incident_id"]] = _merge_incident(
                    incidents.get(error["incident_id"]),
                    error,
                )

    recurring_ids = sorted({
        row.get("recurrence_of_incident_id")
        for row in current_errors
        if row.get("recurrence_of_incident_id")
    })
    for incident in incidents.values():
        if incident.get("incident_id") in recurring_ids:
            incident["resolution"] = "recurring_current_window"
            incident["resolution_detail"] = "historical incident reappeared in current log window"

    category_counts = Counter(row.get("category") for row in current_errors)
    signature_groups = current_signature_groups(current_errors)
    missing_logs = [row for row in _source_rows(sources) if not row.get("exists")]
    status = "BLOCK" if current_errors else ("WARN" if missing_logs else "PASS")
    blockers = [
        {
            "loop": row.get("loop"),
            "category": row.get("category"),
            "detail": row.get("normalized_message"),
            "incident_id": row.get("incident_id"),
            "recurrence_of_incident_id": row.get("recurrence_of_incident_id"),
            "path": row.get("path"),
            "line_number": row.get("line_number"),
        }
        for row in current_errors[:25]
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "status": status,
        "as_of_utc": current.isoformat(),
        "current_window": {
            "hours": window_hours,
            "start_utc": window_start.isoformat(),
            "end_utc": current.isoformat(),
        },
        "summary": {
            "status": status,
            "loop_count": len(sources),
            "missing_log_count": len(missing_logs),
            "current_blocker_count": len(current_errors),
            "current_signature_count": len(signature_groups),
            "historical_error_count": len(historical_errors),
            "archived_incident_count": len(incidents),
            "recurring_incident_count": len(recurring_ids),
            "current_category_counts": dict(sorted(category_counts.items())),
        },
        "sources": _source_rows(sources),
        "missing_logs": missing_logs,
        "current_blockers": blockers,
        "current_signature_groups": signature_groups,
        "historical_errors_archived": historical_errors[:50],
        "incidents": sorted(incidents.values(), key=lambda row: (
            str(row.get("last_seen_utc") or ""),
            str(row.get("incident_id") or ""),
        )),
        "incident_paths": {
            "jsonl": str(incidents_path),
        },
        "current_window_line_counts": {
            loop: len(lines) for loop, lines in sorted(current_lines_by_loop.items())
        },
        "_current_window_lines": current_lines_by_loop,
    }


def write_incidents(path: str | Path, incidents: list[dict[str, Any]]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in incidents:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    return path


def write_current_logs(root: str | Path, current_lines_by_loop: dict[str, list[str]]) -> dict[str, str]:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for loop, lines in sorted((current_lines_by_loop or {}).items()):
        path = root / f"{loop}.current.log"
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        outputs[loop] = str(path)
    return outputs


def write_outputs(
    payload: dict[str, Any],
    *,
    json_out: str | Path = DEFAULT_JSON_OUT,
    incidents_out: str | Path = DEFAULT_INCIDENTS_OUT,
    current_log_root: str | Path = DEFAULT_CURRENT_LOG_ROOT,
) -> tuple[Path, Path, Path]:
    current_lines = payload.get("_current_window_lines") or {}
    current_logs = write_current_logs(current_log_root, current_lines)
    incidents_path = write_incidents(incidents_out, payload.get("incidents") or [])
    json_payload = {
        key: value
        for key, value in payload.items()
        if not str(key).startswith("_")
    }
    json_payload["incident_paths"] = {"jsonl": str(incidents_path)}
    json_payload["current_window_log_paths"] = current_logs
    json_path = write_json_atomic(json_out, json_payload, trailing_newline=True)
    return json_path, incidents_path, Path(current_log_root)
