"""Lane L13: local-day 2 m Tmax per member from one ECMWF ENS forward run (reader of the recorder's points.jsonl).

Reads ``<run dir>/points.jsonl`` written by ``ecmwf_ens_forward_recorder.py`` and buckets each 3-hour ``mx2t3``
window into the market's local settlement day with ``forward_local_day`` (timezone-aware, DST-correct: 2026-11-01 is
a 25-hour day in the US and Canada). A day's maximum uses only windows wholly inside it; a window that crosses local
midnight is reported as an edge window, never mixed in. ``complete`` is true when the inside windows cover every hour
of the local day. Read-only on the recorder output; it writes only to stdout or ``--out``. Research / shadow only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from forward_local_day import MARKET_TZ, daily_max  # noqa: E402


def daily_rows(points, param="mx2t3", value_key="bilinear_k"):
    groups = defaultdict(list)
    for p in points:
        if p.get("kind") != "point" or p.get("param") != param:
            continue
        end = dt.datetime.fromisoformat(p["valid_utc"])
        start = end - dt.timedelta(hours=int(p.get("window_h") or 0))
        groups[(p["run_utc"], p["market"], p["icao"], p["member"])].append(
            {"start_utc": start, "end_utc": end, "value": p[value_key]})
    out = []
    for (run, market, icao, member), rows in sorted(groups.items()):
        tz = MARKET_TZ[market]
        for day, d in daily_max(rows, tz).items():
            out.append({"run_utc": run, "market": market, "icao": icao, "member": member, "tz": tz,
                        "local_date": day, "param": param, "value_key": value_key, "tmax_k": d["max"],
                        "day_hours": d["day_hours"], "covered_hours": d["covered_hours"],
                        "complete": d["max"] is not None and d["covered_hours"] == d["day_hours"],
                        "edge_windows": d["edge_windows"], "edge_max_k": d["edge_max"],
                        "day_start_utc": d["day_start_utc"], "day_end_utc": d["day_end_utc"]})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", help="<recorder out>/<YYYYMMDDHH>")
    ap.add_argument("--value", default="bilinear_k", choices=("bilinear_k", "nearest_k"))
    ap.add_argument("--out", default=None, help="JSON-lines output path (default stdout)")
    args = ap.parse_args(argv)
    pts = [json.loads(line) for line in (Path(args.run_dir) / "points.jsonl").read_text("utf-8").splitlines() if line]
    rows = daily_rows(pts, value_key=args.value)
    text = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
