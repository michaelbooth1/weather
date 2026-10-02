"""Disposable, stat-bound hash indexes for append-only capture manifests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time


MAX_INDEX_BYTES = 16 * 1024 * 1024


def signature(path):
    path = Path(path)
    try:
        stat = path.stat()
        return [str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
    except FileNotFoundError:
        return [str(path.resolve()), None]


def _sidecar(path, kind):
    return Path(path).with_name(f".{Path(path).name}.{kind}-index.json")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_index(path, kind):
    """Return an index only for exactly the source version it describes."""
    try:
        cache = _sidecar(path, kind)
        if cache.stat().st_size > MAX_INDEX_BYTES:
            return None
        payload = json.loads(cache.read_text(encoding="utf-8"))
        rows = payload["rows"]
        if (payload["revision"] == 1 and payload["source"] == signature(path)
                and isinstance(rows, dict) and payload["sha256"] == _digest(rows)):
            return rows
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def save_index(path, kind, rows, *, expected):
    """Cache publication is best effort; source evidence remains authoritative."""
    target = _sidecar(path, kind)
    temporary = target.with_name(f"{target.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        if signature(path) != expected:
            return
        text = json.dumps({"revision": 1, "source": expected, "rows": rows,
                           "sha256": _digest(rows)}, sort_keys=True)
        if len(text.encode("utf-8")) > MAX_INDEX_BYTES:
            return
        temporary.write_text(text, encoding="utf-8")
        if signature(path) == expected:
            os.replace(temporary, target)
    except OSError:
        pass
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def indexed(path, kind, build):
    cached = read_index(path, kind)
    if cached is not None:
        return cached
    before = signature(path)
    rows = build()
    save_index(path, kind, rows, expected=before)
    return rows


def forecast_key(source, kind):
    return json.dumps([source, kind], separators=(",", ":"))


def add_forecasts(index, rows):
    for row in rows:
        index[forecast_key(row.get("source"), row.get("forecast_kind"))] = row.get("payload_hash")


def add_first_seen(index, rows):
    for row in rows:
        digest = row.get("payload_hash")
        first = row.get("first_seen_at") or row.get("captured_at_utc")
        if digest and first and digest not in index:
            index[digest] = [first, row.get("first_seen_basis") or "existing_manifest"]
