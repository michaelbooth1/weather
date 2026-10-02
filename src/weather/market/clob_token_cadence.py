"""Prospective complete token batches on identity changes or each UTC hour."""

import hashlib
import json
import os
from pathlib import Path
import time

from weather.market.market_microstructure_constants import TOKEN_COLUMNS


IDENTITY_FIELDS = tuple(name for name in TOKEN_COLUMNS
                        if not name.startswith("gamma_") and not name.startswith("captured_at_"))


def _signature(path):
    try:
        stat = Path(path).stat()
        return [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
    except FileNotFoundError:
        return None


def _key(rows, book_metadata):
    metadata = {str(row.get("clob_token_id")): row for row in book_metadata or []}
    values = []
    for row in rows:
        token = str(row.get("clob_token_id"))
        identity = {name: row.get(name) for name in IDENTITY_FIELDS}
        book = metadata.get(token, {})
        identity["tick_size"] = book.get("tick_size", row.get("tick_size"))
        identity["min_order_size"] = book.get("min_order_size", row.get("min_order_size"))
        values.append(identity)
    values.sort(key=lambda row: str(row.get("clob_token_id")))
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


def write_complete_batch(store, rows, book_metadata=None):
    """Caller holds the existing event writer guard; never rewrites old tapes."""
    rows = list(rows)
    if not rows:
        return 0
    stamp = str(rows[0].get("captured_at_utc") or "")
    local_day = str(rows[0].get("captured_at_local") or stamp)[:10]
    # A new hour forces a complete batch even if a static change occurred
    # near the end of the previous hour. Missing timestamps never skip writes.
    hour = stamp[:13] if len(stamp) >= 13 else None
    identity = _key(rows, book_metadata)
    cache_path = store.root / ".clob-token-batch.json"
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        unchanged = (
            hour is not None and cached.get("revision") == 1
            and cached.get("identity") == identity
            and cached.get("hour") == hour and cached.get("local_day") == local_day
            and cached.get("csv") == _signature(store.token_path)
            and cached.get("jsonl") == _signature(store.token_jsonl_path)
            and cached.get("csv") is not None and cached.get("jsonl") is not None
        )
    except (OSError, ValueError, TypeError, AttributeError):
        unchanged = False
    if unchanged:
        return 0
    store.append_csv(store.token_path, TOKEN_COLUMNS, rows)
    for row in rows:
        store.append_jsonl(store.token_jsonl_path, row)
    payload = {"revision": 1, "identity": identity, "hour": hour, "local_day": local_day,
               "csv": _signature(store.token_path), "jsonl": _signature(store.token_jsonl_path)}
    temporary = cache_path.with_name(f"{cache_path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.replace(temporary, cache_path)
    except OSError:
        pass  # failed cache publication merely causes an extra complete batch
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return len(rows)
