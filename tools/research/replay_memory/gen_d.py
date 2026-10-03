"""Seal #166's fixture at any instantaneous band count D (churn 1): gen_d.py OUT_ROOT D MINUTES DATE...

Trade rows scale with MINUTES (2,000 per full day). gen.py is the D = 12 full-density special case.
Report: docs/roadmap/agent-report-2026-10-03-replay-streaming.md.
"""
import sys, time
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from fixture import day_records, seal
root, d, minutes = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
for ds in sys.argv[4:]:
    day = date.fromisoformat(ds)
    t = time.monotonic()
    conds, recs = day_records(day, d, 1.0, 2000 * minutes // 1440, minutes=minutes)
    seal(root / ds / "bundle", day, conds, recs)
    print(ds, len(recs), round(time.monotonic() - t, 1), flush=True)
