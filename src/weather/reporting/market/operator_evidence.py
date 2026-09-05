"""Bounded local reads and observation age for the monitoring UI.

These helpers describe evidence; they never grant execution permission.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import hashlib
import math
from pathlib import Path
import stat


MAX_JSON_BYTES = 2 * 1024 * 1024
TIMESTAMP_KEYS = (
    "generated_at_utc", "updated_at_utc", "finished_at_local",
    "created_at_utc", "created_at_local", "recorded_at_utc", "checked_at_utc", "ts",
)


def checked_local_path(path, *, root=None):
    path = Path(path).absolute()
    if root is not None:
        path.relative_to(Path(root).absolute())
    for component in (path, *path.parents):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Linked evidence paths are not supported.")
    return path


def scalar_fields(payload, fields):
    result = {}
    for key in fields:
        value = payload.get(key)
        if isinstance(value, str):
            value = value[:1024]
        elif isinstance(value, float) and not math.isfinite(value):
            value = None
        elif value is not None and not isinstance(value, (bool, int, float)):
            value = None
        result[key] = value
    return result


def parse_timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def evidence_timestamp(payload):
    if not isinstance(payload, dict):
        return None
    return next((payload[key] for key in TIMESTAMP_KEYS if payload.get(key)), None)


def freshness(artifact, *, now=None, max_age_seconds=300):
    """Use producer time, never file mtime; reject future, expired or undated data."""
    now = now or datetime.now(timezone.utc)
    if not artifact.get("available"):
        return {"status": "COLLECTING" if artifact.get("loading") else "UNAVAILABLE", "age_seconds": None,
                "detail": artifact.get("error") or "No observation available."}
    payload = artifact.get("payload") or {}
    timestamp = evidence_timestamp(payload)
    observed = parse_timestamp(timestamp)
    if observed is None:
        return {"status": "UNDATED", "age_seconds": None,
                "detail": "Producer timestamp is missing or invalid."}
    age = (now - observed).total_seconds()
    expiry_value = payload.get("expires_at_utc") or payload.get("valid_until_utc")
    expiry = parse_timestamp(expiry_value) if expiry_value else None
    expired = bool(expiry_value and (expiry is None or now >= expiry))
    status = "CURRENT"
    if age < -30:
        status = "CLOCK ERROR"
    elif expired or age > max_age_seconds:
        status = "STALE"
    return {"status": status, "age_seconds": max(0, age), "observed_at": timestamp,
            "detail": f"{status.lower()}: observed {timestamp}"}


def read_artifact(path, *, root=None, max_bytes=MAX_JSON_BYTES):
    path = Path(path)
    result = {"available": False, "path": str(path)}
    try:
        path = checked_local_path(path, root=root)
        if not path.is_file() or path.stat().st_size > max_bytes:
            raise ValueError("Evidence is not a regular file within the read limit.")
        with path.open("rb") as handle:
            raw = handle.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError("Evidence exceeds the read limit.")
        payload = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("Evidence must be a JSON object.")
        result.update(available=True, payload=payload,
                      sha256=hashlib.sha256(raw).hexdigest(),
                      recorded_at=evidence_timestamp(payload))
    except (OSError, ValueError, UnicodeError) as exc:
        result["error"] = "Evidence file is missing." if isinstance(exc, FileNotFoundError) else str(exc)
    return result
