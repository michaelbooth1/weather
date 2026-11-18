"""IEM 1-minute ASOS (NCEI DSI-6405/6406) for the US settlement stations: fetch and parse.

Source role: supporting observation, research only. **Not point in time at serve**: NCEI publishes
the 1-minute archive 18-36 h (often more) after the fact, so a screen built on it is a *training
proxy* for a live high-frequency feed (MADIS 1-/5-minute ASOS or HF-METAR). A screen that uses it
must degrade it to the live product's cadence, resolution and latency before it counts.

Values: ``tmpf`` whole degrees F as served by IEM. Gaps are absent rows. Upper bound: every request
ends at local midnight closing 2026-09-29 for the station, so no later observation is fetched.

CLI::

    python -m weather.sources.free_screens.iem_onemin fetch [--root DIR] [--start 2024-01-01]
    python -m weather.sources.free_screens.iem_onemin build [--root DIR]
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from weather.sources.free_screens import common

SOURCE = "iem_onemin"
URL = ("https://mesonet.agron.iastate.edu/cgi-bin/request/asos1min.py?station={sid}&vars=tmpf"
       "&sts={sts}&ets={ets}&sample=1min&what=download&tz=UTC&delim=comma&gis=no")
SCHEMA = "free_screens_iem_onemin/1"


def stations():
    return common.us_stations() + (common.DENVER_PROXY,)


def requests_plan(start_utc):
    plan = []
    for st in stations():
        end = common.local_day_end_utc(st.timezone)
        for a, b in common.month_windows(start_utc, end):
            plan.append((st, a, b))
    return plan


def parse_csv(text):
    """IEM asos1min CSV -> rows (icao, valid_utc, tmpf). Missing/'M' values are dropped."""
    rows = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        sid = (row.get("station") or "").strip()
        valid = (row.get("valid(UTC)") or row.get("valid") or "").strip()
        tmpf = (row.get("tmpf") or "").strip()
        if not sid or not valid or tmpf in ("", "M"):
            continue
        try:
            value = float(tmpf)
        except ValueError:
            continue
        rows.append(("K" + sid if len(sid) == 3 else sid, valid, value))
    return rows


def fetch(root, start_utc, session=None, log=print):
    import requests

    session = session or requests.Session()
    src = Path(root) / SOURCE
    receipts = common.ReceiptLog(src)
    plan = requests_plan(start_utc)
    for i, (st, a, b) in enumerate(plan, 1):
        key = f"{st.icao}|{common.utc_stamp(a)}|{common.utc_stamp(b)}"
        if receipts.is_done(key):
            continue
        url = URL.format(sid=st.icao[1:], sts=common.utc_stamp(a), ets=common.utc_stamp(b))
        resp = common.polite_get(session, url)
        body = resp.content
        rows = parse_csv(body.decode("utf-8", "replace")) if resp.status_code == 200 else []
        name = f"{st.icao}_{a:%Y%m%d%H}_{b:%Y%m%d%H}.csv.gz"
        rel, sha = common.store_gzip(src, name, body)
        receipts.record({"key": key, "file": rel, "sha256": sha, "url": url, "status": resp.status_code,
                         "bytes": len(body), "rows": len(rows), "station": st.icao,
                         "start_utc": a.isoformat(), "end_utc": b.isoformat(),
                         "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        log(f"[{i}/{len(plan)}] {key} rows={len(rows)} bytes={len(body)}")


def build(root):
    """Concatenate receipts into ``<root>/iem_onemin/onemin.parquet`` (icao, valid_utc, tmpf) + manifest."""
    src = Path(root) / SOURCE
    receipts = common.ReceiptLog(src)
    frames = []
    for row in sorted(receipts.done.values(), key=lambda r: r["key"]):
        body = gzip.decompress((src / row["file"]).read_bytes()).decode("utf-8", "replace")
        parsed = parse_csv(body)
        if parsed:
            frames.append(pd.DataFrame(parsed, columns=["icao", "valid_utc", "tmpf"]))
    frame = pd.concat(frames, ignore_index=True)
    frame["valid_utc"] = pd.to_datetime(frame.valid_utc, utc=True)
    frame = frame.drop_duplicates(["icao", "valid_utc"]).sort_values(["icao", "valid_utc"]).reset_index(drop=True)
    out = src / "onemin.parquet"
    frame.to_parquet(out, index=False)
    manifest = {"schema": SCHEMA, "file": out.name, "sha256": common.sha256_bytes(out.read_bytes()),
                "rows": int(len(frame)), "receipts": len(receipts.done),
                "bytes_fetched": int(sum(r["bytes"] for r in receipts.done.values())),
                "per_station": {k: {"rows": int(len(g)), "first": g.valid_utc.min().isoformat(),
                                    "last": g.valid_utc.max().isoformat()}
                                for k, g in frame.groupby("icao")},
                "point_in_time": False,
                "latency_note": "NCEI 1-minute archive, published 18-36 h+ after the fact; training proxy only"}
    (src / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m weather.sources.free_screens.iem_onemin")
    parser.add_argument("command", choices=("fetch", "build"))
    parser.add_argument("--root", default=str(common.DEFAULT_ROOT))
    parser.add_argument("--start", default="2024-01-01")
    args = parser.parse_args(argv)
    if args.command == "fetch":
        start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
        fetch(args.root, start, log=lambda m: print(m, flush=True))
    else:
        print(json.dumps(build(args.root), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
