"""Seal #166's D=12 fixture (churn 1, full density) for each named date: gen.py OUT_ROOT DATE...

MINUTES (environment, default 1440) shortens the day; trade rows scale with it (2,000 per full day).
Report: docs/roadmap/agent-report-2026-10-03-replay-memory.md.
"""
import sys, time
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from fixture import day_records, seal
root, minutes = Path(sys.argv[1]), int(__import__("os").environ.get("MINUTES", "1440"))
for d in sys.argv[2:]:
    day = date.fromisoformat(d)
    t = time.monotonic()
    conds, recs = day_records(day, 12, 1.0, 2000 * minutes // 1440, minutes=minutes)
    seal(root / d / "bundle", day, conds, recs)
    print(d, len(recs), round(time.monotonic() - t, 1), flush=True)
