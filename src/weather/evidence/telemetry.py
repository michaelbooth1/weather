"""PL-5 per-family telemetry: writer-side counters, peak memory, throttled status, daily ledger.

No directory walk: every number comes from the writer's own counters (plan PL-5), so the status
file is a receipt, not an inventory. Status is rewritten at most every ``min_interval_seconds``;
the ledger gains one row per sealed UTC day.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from weather.evidence.envelope import canonical, utc_text
from weather.evidence.journal import atomic_bytes
from weather.schema_families import schema_version

STATUS_SCHEMA = schema_version("evidence_family_status")
LEDGER_SCHEMA = schema_version("evidence_family_ledger")


def process_memory() -> dict:
    """Current private/working-set bytes of this process (empty when unavailable)."""
    if os.name == "nt":
        from weather.operations.windows_process_metrics import windows_process_memory_metrics
        row = windows_process_memory_metrics(os.getpid()) or {}
        return {k: row[k] for k in ("private_bytes", "working_set_bytes") if k in row}
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return {"working_set_bytes": int(peak) * (1 if os.uname().sysname == "Darwin" else 1024)}
    except (ImportError, OSError, AttributeError):
        return {}


class FamilyTelemetry:
    def __init__(self, root, family, *, clock, min_interval_seconds=30.0, monotonic=time.monotonic):
        self.family_root = Path(root) / family
        self.family = family
        self.clock = clock
        self.min_interval = float(min_interval_seconds)
        self.monotonic = monotonic
        self.last_write = None
        self.peak = {"private_bytes": 0, "working_set_bytes": 0}
        self.requests = {"count": 0, "bytes": 0, "errors": 0, "http_429": 0}
        self.channels: dict[str, dict] = {}
        self.extra: dict = {}

    def sample_memory(self, sample=None):
        sample = process_memory() if sample is None else sample
        for key in self.peak:
            self.peak[key] = max(self.peak[key], int(sample.get(key) or 0))
        return sample

    def request(self, nbytes, *, error=False, status=None):
        self.requests["count"] += 1
        self.requests["bytes"] += int(nbytes or 0)
        self.requests["errors"] += int(bool(error))
        self.requests["http_429"] += int(status == 429)

    def channel(self, name, **values):
        self.channels.setdefault(name, {}).update(values)

    def payload(self, journal) -> dict:
        return {"schema_version": STATUS_SCHEMA, "family": self.family, "written_at_utc": utc_text(self.clock()),
                "pid": os.getpid(), "journal": dict(journal.counters), "hour_bytes": journal.hour_bytes,
                "hour_capped": journal.hour_capped, "cap_hit_hours": list(journal.cap_hit_hours[-48:]),
                "peak_memory": dict(self.peak), "requests": dict(self.requests),
                "channels": self.channels, **self.extra}

    def write_status(self, journal, *, force=False) -> bool:
        now = self.monotonic()
        if not force and self.last_write is not None and now - self.last_write < self.min_interval:
            return False
        self.sample_memory()
        self.family_root.mkdir(parents=True, exist_ok=True)
        atomic_bytes(self.family_root / "status.json", canonical(self.payload(journal)) + b"\n")
        self.last_write = now
        return True

    def ledger(self, journal, day, seal) -> None:
        row = {"schema_version": LEDGER_SCHEMA, "family": self.family, "day": day,
               "segments": len(seal.get("segments", [])), "journal": dict(journal.counters),
               "peak_memory": dict(self.peak), "requests": dict(self.requests),
               "cap_hit_hours": [h for h in journal.cap_hit_hours if h.startswith(day)],
               "written_at_utc": utc_text(self.clock())}
        self.family_root.mkdir(parents=True, exist_ok=True)
        with (self.family_root / "ledger.jsonl").open("ab") as handle:
            handle.write(canonical(row) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
