"""Memory of one loaded bundle, the per-day floor any streamed run must hold: loadmem.py BUNDLE (exam tree on PYTHONPATH).

Report: docs/roadmap/agent-report-2026-10-03-replay-streaming.md.
"""
import sys, json, time
from datetime import datetime, timezone
from maker_core.replay import ceilings
from maker_core.replay.bundle import HOST_MAX_BYTES, HOST_MAX_RECORDS, HOST_MAX_SECONDS, Limits
from maker_core.replay.pack_io import load_days
base = ceilings.process_memory()[1]
t = time.monotonic()
b = load_days([sys.argv[1]], Limits(HOST_MAX_BYTES, HOST_MAX_RECORDS, HOST_MAX_SECONDS), lambda: None,
              now=datetime(2026, 10, 20, tzinfo=timezone.utc))
cur, peak = ceilings.process_memory()
print(json.dumps(dict(records=len(b[0].records), input_bytes=b[0].input_bytes, seconds=round(time.monotonic()-t, 1),
                      retained_MiB=round((cur-base)/2**20, 1), peak_above_baseline_MiB=round((peak-base)/2**20, 1))))
