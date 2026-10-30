"""Lane L13: local-day maximum per series from ECCC GEM forward runs (reader of the recorder's points.jsonl).

Reads ``<recorder out>/<model>/<YYYYMMDDHH>/points.jsonl`` files written by ``eccc_gem_forward_recorder.py`` and
summarises each series (model, product, run, station, member) per local settlement day with
``forward_daily.local_day_summary``: timezone-aware, one run and member at a time, with ``status`` ``exact``,
``bounded`` or ``partial`` for the 6-hour maximum and ``hourly`` or ``partial`` for 2 m temperature. Read-only on the
recorder output; it writes only to stdout or ``--out``. Research / shadow only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from forward_daily import group_series, local_day_summary  # noqa: E402

KEYS = ("model", "product", "run_utc", "market", "icao", "member")


def daily_rows(points, value_key="bilinear_k"):
    series = []
    for p in points:
        if p.get("kind") != "point":
            continue
        end = dt.datetime.fromisoformat(p["valid_utc"])
        series.append({**{k: p.get(k) for k in KEYS}, "tz": p["tz"], "start_utc": end - dt.timedelta(
            hours=int(p.get("window_h") or 0)), "end_utc": end, "value": p[value_key]})
    out = []
    for key, rows in sorted(group_series(series, KEYS).items(), key=lambda kv: tuple(map(str, kv[0]))):
        tzs = {r["tz"] for r in rows}
        if len(tzs) != 1:
            raise ValueError(f"{key}: timezones {sorted(tzs)}")
        tz = tzs.pop()
        for day, d in local_day_summary(rows, tz).items():
            out.append({**dict(zip(KEYS, key)), "tz": tz, "local_date": day, "value_key": value_key, **d})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dirs", nargs="+", help="<recorder out>/<model>/<YYYYMMDDHH>")
    ap.add_argument("--value", default="bilinear_k", choices=("bilinear_k", "nearest_k"))
    ap.add_argument("--out", default=None, help="JSON-lines output path (default stdout)")
    args = ap.parse_args(argv)
    pts = []
    for run_dir in args.run_dirs:
        text = (Path(run_dir) / "points.jsonl").read_text("utf-8")
        pts.extend(json.loads(line) for line in text.splitlines() if line)
    text = "".join(json.dumps(r, sort_keys=True) + "\n" for r in daily_rows(pts, value_key=args.value))
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
