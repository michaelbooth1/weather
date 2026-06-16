"""Source-adapter orchestration primitives."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SourceAdapter:
    name: str
    fetch: object


def fetch_source(name, fetcher, *, fetched_at, clock=time.perf_counter):
    started = clock()
    try:
        return name, {
            "ok": True,
            "data": fetcher(),
            "latency_ms": round((clock() - started) * 1000.0, 1),
            "fetched_at": fetched_at,
        }
    except Exception as exc:  # noqa: BLE001 - source failures are surfaced as data
        return name, {
            "ok": False,
            "error": str(exc),
            "latency_ms": round((clock() - started) * 1000.0, 1),
            "fetched_at": fetched_at,
        }


def fetch_source_group(fetchers, *, timezone, now_fn=None, max_workers=None):
    fetchers = dict(fetchers or {})
    if not fetchers:
        return {}
    now_fn = now_fn or (lambda: datetime.now(timezone))
    fetched_at = now_fn().isoformat()
    results = {}
    workers = max_workers or len(fetchers)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_source, name, fetcher, fetched_at=fetched_at): name
            for name, fetcher in fetchers.items()
        }
        for future in as_completed(futures):
            name, payload = future.result()
            results[name] = payload
    return results

