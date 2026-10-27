"""L5 morning-loss diagnosis: per market-day weather-regime features from OUR captured replay inputs.

Development research only (target dates <= 2026-09-29). Reads, per replay folder, the FIRST line and the LAST
line whose ``captured_at_local`` falls on the target date. Lines are located by seeking and reading only the
timestamp prefix; a line captured after the target date is never parsed. Offline: no network, no production
writes. Pre-declared definitions: C:\\t\\l5\\plan.md (Analysis 3).

    python tools/research/morning_loss/extract_regimes.py --replay-root <...\\snapshots> \\
        --layout C:\\swarm\\v3layout --out C:\\t\\l5\\regimes.parquet
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
from pathlib import Path

import pandas as pd

DEV_LAST = dt.date(2026, 9, 29)
TS_RE = re.compile(rb'"captured_at_local":\s*"([^"]+)"')
PREFIX = 800
WX_RE = re.compile(r"[-+]?(MI|BC|PR|DR|BL|SH|TS|FZ)?(DZ|RA|SN|SG|PL|GR|GS|UP)*")
CEIL_RE = re.compile(r"(BKN|OVC|VV)(\d{3})")


def _ts_at(f, pos):
    f.seek(pos)
    m = TS_RE.search(f.read(PREFIX))
    return dt.datetime.fromisoformat(m.group(1).decode()) if m else None


def _next_line_start(f, off, size):
    if off == 0:
        return 0
    f.seek(off - 1)
    f.readline()  # discard (never parsed)
    pos = f.tell()
    return pos if pos < size else None


def first_and_last_on_date(path, target):
    """Return (first_record, last_on_date_record); only those two lines are json-parsed."""
    size = path.stat().st_size
    with open(path, "rb") as f:
        first_ts = _ts_at(f, 0)
        if first_ts is None or first_ts.date() > target:
            return None, None
        f.seek(0)
        first = json.loads(f.readline())
        lo, hi = 0, size  # invariant: line at lo is on/before target; answer in [lo, hi)
        while hi - lo > 2_000_000:
            mid = (lo + hi) // 2
            pos = _next_line_start(f, mid, size)
            if pos is None or pos >= hi:
                hi = mid
                continue
            ts = _ts_at(f, pos)
            if ts is not None and ts.date() <= target:
                lo = pos
            else:
                hi = mid
        best, pos = lo, lo
        while pos is not None and pos < size:
            ts = _ts_at(f, pos)
            if ts is None or ts.date() > target:
                break
            best = pos
            f.seek(pos)
            f.readline()
            pos = f.tell()
        f.seek(best)
        last = json.loads(f.readline())
    if dt.datetime.fromisoformat(last["captured_at_local"]).date() != target:
        raise RuntimeError(f"{path}: last on-date line mismatch")
    return first, last


def _num(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _hour(row):
    return int(row["datetime"][11:13])


def metar_features(rows):
    rows = sorted({r["datetime"]: r for r in rows if r.get("datetime")}.values(), key=lambda r: r["datetime"])
    out = {"n_metar": len(rows)}
    if not rows:
        return out
    times = [dt.datetime.fromisoformat(r["datetime"]) for r in rows]
    shift = dew = False
    max_dir_change = 0.0
    max_dew_drop = 0.0
    for i, (ri, ti) in enumerate(zip(rows, times)):
        if _hour(ri) > 15:
            continue
        for rj, tj in zip(rows[i + 1:], times[i + 1:]):
            if (tj - ti).total_seconds() > 3 * 3600 or _hour(rj) > 15:
                break
            di, dj = _num(ri.get("wind_dir")), _num(rj.get("wind_dir"))
            si, sj = _num(ri.get("wind_speed")) or 0, _num(rj.get("wind_speed")) or 0
            if di is not None and dj is not None and si >= 6 and sj >= 6:
                d = abs((float(dj) - float(di) + 180) % 360 - 180)
                max_dir_change = max(max_dir_change, d)
                shift |= d >= 90
            pi, pj = _num(ri.get("dewpoint_native")), _num(rj.get("dewpoint_native"))
            if pi is not None and pj is not None:
                max_dew_drop = max(max_dew_drop, float(pi) - float(pj))
                dew |= float(pi) - float(pj) >= 8
    out.update(max_dir_change=max_dir_change, max_dew_drop=max_dew_drop, R1_frontal=bool(shift or dew))
    low_ceiling, n_morning, precip, ceil_min = 0, 0, False, math.inf
    for r in rows:
        h = _hour(r)
        body = (r.get("raw") or "").split(" RMK")[0].split()[2:]
        if 6 <= h <= 12:
            n_morning += 1
            ceils = [int(m.group(2)) * 100 for t in body if (m := CEIL_RE.fullmatch(t[:6]))]
            if ceils and min(ceils) <= 3000:
                low_ceiling += 1
            if ceils:
                ceil_min = min(ceil_min, min(ceils))
        if h <= 15:
            for t in body:
                if t.startswith("VC") or not WX_RE.fullmatch(t):
                    continue
                if any(code in t for code in ("RA", "DZ", "TS", "SH", "GR")):
                    precip = True
    out.update(low_ceiling_frac=(low_ceiling / n_morning) if n_morning else math.nan,
               R2_cloud=bool(n_morning and low_ceiling / n_morning >= 0.5), R3_precip=precip,
               min_ceiling_06_12=ceil_min if math.isfinite(ceil_min) else math.nan)
    by_hour = {}
    for r in rows:
        if r.get("temp_native") is not None:
            by_hour[_hour(r)] = float(r["temp_native"])
    lows = [v for h, v in by_hour.items() if h <= 8]
    out.update(obs_min_00_08=min(lows) if lows else math.nan, obs_t06=by_hour.get(6, math.nan),
               obs_t11=by_hour.get(11, math.nan), obs_t12=by_hour.get(12, math.nan))
    return out


def forecast_features(first, target):
    out = {}
    om = ((first.get("sources") or {}).get("open_meteo") or {}).get("data") or {}
    rows = [r for r in om.get("day_rows") or [] if str(r.get("valid_time", ""))[:10] == target.isoformat()]
    by_hour = {int(r["time"][:2]): r for r in rows if r.get("temp_native") is not None}
    lows = [float(r["temp_native"]) for h, r in by_hour.items() if h <= 8]
    out["fc_min_00_08"] = min(lows) if lows else math.nan
    out["fc_t06"] = float(by_hour[6]["temp_native"]) if 6 in by_hour else math.nan
    out["fc_t11"] = float(by_hour[11]["temp_native"]) if 11 in by_hour else math.nan
    out["fc_low_cloud_06_12"] = (sum(float(by_hour[h].get("low_cloud") or 0) for h in range(6, 13) if h in by_hour)
                                 / max(1, sum(1 for h in range(6, 13) if h in by_hour)))
    out["fc_precip_00_15"] = sum(float(r.get("precipitation") or 0) for h, r in by_hour.items() if h <= 15)
    out["fc_first_captured_local"] = first.get("captured_at_local")
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--replay-root", required=True)
    p.add_argument("--layout", required=True)
    p.add_argument("--first-date", default="2026-08-15")
    p.add_argument("--out", required=True)
    p.add_argument("--obs-out", help="optional parquet of hourly METAR temps (market, date, label_hour, temp_f)")
    a = p.parse_args(argv)
    obs = []
    snaps = pd.read_parquet(Path(a.layout) / "inputs_snapshots.parquet",
                            columns=["market", "date", "event_slug"]).drop_duplicates()
    snaps = snaps[(snaps.date >= a.first_date) & (snaps.date <= DEV_LAST.isoformat())]
    recs = []
    for i, r in enumerate(snaps.sort_values(["date", "market"]).itertuples()):
        target = dt.date.fromisoformat(r.date)
        if target > DEV_LAST:
            raise SystemExit("refused: date after 2026-09-29")
        path = Path(a.replay_root) / r.event_slug / "replay_inputs.jsonl"
        rec = {"market": r.market, "date": r.date}
        if not path.exists():
            rec["status"] = "missing_folder"
            recs.append(rec)
            continue
        first, last = first_and_last_on_date(path, target)
        if first is None:
            rec["status"] = "no_on_date_line"
            recs.append(rec)
            continue
        metar = ((last.get("sources") or {}).get("metar") or {}).get("data") or {}
        rec.update(status="ok", last_captured_local=last["captured_at_local"])
        for row in metar.get("rows") or []:
            if row.get("datetime", "")[:10] == r.date and _num(row.get("temp_native")) is not None:
                obs.append({"market": r.market, "date": r.date, "label_hour": _hour(row),
                            "label_time": row["datetime"], "temp_f": _num(row.get("temp_native"))})
        rec.update(metar_features(metar.get("rows") or []))
        rec.update(forecast_features(first, target))
        recs.append(rec)
        if i % 50 == 0:
            print(i, r.market, r.date, flush=True)
    df = pd.DataFrame(recs)
    df["overnight_low_gap"] = df.fc_min_00_08 - df.obs_min_00_08
    df["R4_low_gap"] = df.overnight_low_gap.abs() >= 3
    df["tendency_anomaly"] = (df.obs_t11 - df.obs_t06) - (df.fc_t11 - df.fc_t06)
    df["R6_tendency"] = df.tendency_anomaly.abs() >= 3
    df.to_parquet(a.out, index=False)
    if a.obs_out:
        pd.DataFrame(obs).drop_duplicates(["market", "date", "label_time"]).to_parquet(a.obs_out, index=False)
    print(df.status.value_counts().to_string())


if __name__ == "__main__":
    main()
