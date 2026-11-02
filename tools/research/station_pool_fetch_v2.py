"""Lane L48 station-pool fetch phases (v2: v1 RSS probe fixed with typed K32GetProcessMemoryInfo) (rule rule_station_pool.md sha256 33d5c67a..., rows 108 C / 109 K).

Network-bound light work, run directly (master 2026-11-01), never through the heavy wrapper:

  iem  -- IEM ASOS routine (report_type=3) and special (=4) CSVs per station and year 2021-25, Aug 01..Sep 30
          (UTC span to Oct 01 12Z), raw text included. Pool stations are fetched in the frozen sha256 order and
          filtered (F1..F5, timestamps / counts / T-group presence / temperature presence only; no temperature value
          is read) as each completes; the run stops at 300 survivors. The 11 market stations are fetched first,
          unfiltered (controls only).
  nbp  -- NBM NBP 07Z bulletins on the 300 Aug-Sep 2021-25 dates, streamed one at a time: S3 listing metadata
          (LastModified, ETag, Size, as lane L9 records them), full GET to a temp file, sha256, extract the wanted
          stations' blocks exactly as L9's Range fetcher delimits them, append one L9-shaped JSONL record, delete.

Standalone on purpose (only ``requests`` and the standard library): it never imports ``weather`` so it can run
with ``python -I``. Guards: RSS hard stop at 1 GB, free-space floor 8 GB (projected and live), runaway-error stop.
Resumable. Refuses any date after 2026-09-29.

Usage:
  python -I station_pool_fetch_v1.py iem --stations <s0_candidate_stations.json> --ids <s0_candidate_ids.txt> --root <corpus root>
  python -I station_pool_fetch_v1.py nbp --root <corpus root>
"""
from __future__ import annotations

import argparse
import csv
import ctypes
import ctypes.wintypes
import hashlib
import io
import json
import os
import re
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

IEM_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
BUCKET = "https://noaa-nbm-grib2-pds.s3.amazonaws.com"
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
HEADER_RE = re.compile(rb"^ ?([A-Z0-9]{3,6}) +NBM V\S+ +NBP +GUIDANCE", re.M)
TGROUP = re.compile(r"\bT[01]\d{3}[01]\d{3}\b")
LAST_ALLOWED = date(2026, 9, 29)
YEARS = (2021, 2022, 2023, 2024, 2025)
MARKETS = ("KATL", "KAUS", "KBKF", "KDAL", "KHOU", "KLAX", "KLGA", "KMIA", "KORD", "KSEA", "KSFO")
ORDER_SALT = "L48-station-pool-v1|"
TARGET = 300
DOSE = 100
IEM_SPACING_S = 5.0
FREE_FLOOR = 8 * 1024 ** 3
RSS_CAP = 1024 ** 3
IEM_PROJECTED_PER_REQUEST = 400 * 1024  # generous upper bound (S0 mean ~140 KB per 2-month file)
NBP_PROJECTED_PER_DATE = 40 * 1024 ** 2 + 2 * 1024 ** 2  # one bulletin in flight plus blocks
F2_ALL, F2_YEAR, F3_ALL, F3_YEAR, F4_MAX, F5_MIN = 0.95, 0.90, 0.90, 0.80, 20.0, 0.80


class Abort(RuntimeError):
    pass


# ------------------------------------------------------------------ guards

class _PMC(ctypes.Structure):
    _fields_ = [("cb", ctypes.wintypes.DWORD), ("PageFaultCount", ctypes.wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def rss_bytes():
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(_PMC)
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
    k32.K32GetProcessMemoryInfo.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(_PMC), ctypes.wintypes.DWORD]
    k32.K32GetProcessMemoryInfo.restype = ctypes.wintypes.BOOL
    if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        raise Abort("GetProcessMemoryInfo failed")
    return int(pmc.WorkingSetSize)


def guard(root, upcoming_bytes=0):
    rss = rss_bytes()
    if rss > RSS_CAP:
        raise Abort(f"RSS {rss} over 1 GB")
    free = shutil.disk_usage(root).free
    if free - upcoming_bytes < FREE_FLOOR:
        raise Abort(f"free space {free} minus upcoming {upcoming_bytes} below the 8 GB floor")
    return rss, free


class ErrorBudget:
    def __init__(self):
        self.n = 0
        self.fail = 0
        self.consecutive = 0

    def record(self, ok):
        self.n += 1
        if ok:
            self.consecutive = 0
            return
        self.fail += 1
        self.consecutive += 1
        if self.consecutive >= 20:
            raise Abort("20 consecutive request failures")
        if self.n >= 100 and self.fail / self.n > 0.10:
            raise Abort(f"failure share {self.fail}/{self.n} above 10%")


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(root, name, rec):
    with open(Path(root) / name, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(rec, sort_keys=True) + "\n")


# ------------------------------------------------------------------ IEM

def iem_url(sid, year, report_type):
    params = [("station", sid), ("data", "tmpc"), ("data", "metar"), ("tz", "Etc/UTC"), ("format", "onlycomma"),
              ("latlon", "no"), ("missing", "M"), ("trace", "T"), ("direct", "no"),
              ("report_type", str(report_type)),
              ("sts", f"{year}-08-01T00:00Z"), ("ets", f"{year}-10-01T12:00Z")]
    return f"{IEM_URL}?{urlencode(params)}"


def iem_get(session, url, budget):
    for attempt in range(4):  # one try plus at most 3 retries
        ok = False
        try:
            r = session.get(url, timeout=180)
            ok = r.status_code == 200
            if ok:
                budget.record(True)
                return r.status_code, r.content
        except requests.RequestException:
            pass
        budget.record(False)
        time.sleep(IEM_SPACING_S * (attempt + 2))
    return None, b""


def fetch_station(session, root, icao, sid, budget):
    """Both report types for every year; returns {(year, type): path or None}."""
    out = {}
    for year in YEARS:
        for rtype, folder in ((3, "routine"), (4, "special")):
            path = Path(root) / "raw" / "iem" / icao.lower() / folder / f"{year}.csv"
            if path.exists():
                out[(year, rtype)] = path
                continue
            guard(root, IEM_PROJECTED_PER_REQUEST)
            url = iem_url(sid, year, rtype)
            status, body = iem_get(session, url, budget)
            rec = {"source": "IEM ASOS asos.py (free, official)", "url": url, "icao": icao, "year": year,
                   "report_type": rtype, "status": status, "bytes": len(body),
                   "sha256": hashlib.sha256(body).hexdigest(), "fetched_utc": now_utc()}
            if status == 200:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".part")
                tmp.write_bytes(body)
                os.replace(tmp, path)
                rec["file"] = str(path)
                out[(year, rtype)] = path
            else:
                out[(year, rtype)] = None
            log(root, "receipts_iem.jsonl", rec)
            time.sleep(IEM_SPACING_S)
    return out


def _rows(path):
    if path is None:
        return []
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return [r for r in csv.DictReader(io.StringIO(text)) if r.get("valid")]


def station_filter(files, tz_name):
    """F1..F5 on Aug 01..Sep 29 local days. Reads timestamps, counts, T-group and temperature PRESENCE only."""
    tz = ZoneInfo(tz_name)
    res = {"years": {}}
    all_t = all_tg = 0
    complete_total = 0
    special_total = 0
    minutes = Counter()
    f1 = True
    f2_year_ok = f3_year_ok = True
    for year in YEARS:
        first, last = date(year, 8, 1), date(year, 9, 29)
        ndays = (last - first).days + 1
        routine = _rows(files.get((year, 3)))
        special = _rows(files.get((year, 4)))
        if not routine:
            f1 = False
        by_day = {}
        n_t = n_tg = 0
        for r in routine:
            utc = datetime.strptime(r["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            local = utc.astimezone(tz)
            if not (first <= local.date() <= last):
                continue
            minutes[utc.minute] += 1
            has_temp = (r.get("tmpc") or "M") not in ("M", "")
            if not has_temp:
                continue
            n_t += 1
            n_tg += bool(TGROUP.search(r.get("metar") or ""))
            by_day.setdefault(local.date(), []).append(local)
        n_special = 0
        for r in special:
            local = datetime.strptime(r["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).astimezone(tz)
            n_special += first <= local.date() <= last
        complete = 0
        d = first
        while d <= last:
            ts = sorted(by_day.get(d, []))
            if len(ts) >= 18:
                start = datetime(d.year, d.month, d.day, tzinfo=tz)
                end = datetime.combine(d + timedelta(days=1), datetime.min.time(), tzinfo=tz)
                edges = [start] + ts + [end]
                gap = max((b - a).total_seconds() / 60.0 for a, b in zip(edges, edges[1:]))
                complete += gap <= 180.0
            d += timedelta(days=1)
        tg_share = n_tg / n_t if n_t else 0.0
        c_share = complete / ndays
        f2_year_ok &= tg_share >= F2_YEAR
        f3_year_ok &= c_share >= F3_YEAR
        all_t += n_t
        all_tg += n_tg
        complete_total += complete
        special_total += n_special
        res["years"][year] = {"routine_rows": len(routine), "routine_with_temp_in_window": n_t,
                              "tgroup_share": round(tg_share, 4), "complete_days": complete,
                              "complete_share": round(c_share, 4), "special_in_window": n_special}
    days = 60 * len(YEARS)
    tg_all = all_tg / all_t if all_t else 0.0
    c_all = complete_total / days
    sp_day = special_total / days
    modal_share = (minutes.most_common(1)[0][1] / sum(minutes.values())) if minutes else 0.0
    res.update({
        "F1": f1, "F2": tg_all >= F2_ALL and f2_year_ok, "F3": c_all >= F3_ALL and f3_year_ok,
        "F4": sp_day <= F4_MAX, "F5": modal_share >= F5_MIN,
        "tgroup_share": round(tg_all, 4), "complete_share": round(c_all, 4),
        "special_per_day": round(sp_day, 3), "modal_minute": minutes.most_common(1)[0][0] if minutes else None,
        "modal_minute_share": round(modal_share, 4),
    })
    res["survives"] = all(res[k] for k in ("F1", "F2", "F3", "F4", "F5"))
    return res


def pool_order(ids):
    return sorted((i for i in ids if i not in MARKETS),
                  key=lambda icao: hashlib.sha256((ORDER_SALT + icao).encode("utf-8")).hexdigest())


def cmd_iem(args):
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    meta = json.loads(Path(args.stations).read_text(encoding="utf-8"))
    ids = [x.strip() for x in Path(args.ids).read_text(encoding="utf-8").split() if x.strip()]
    order = pool_order(ids)
    if len(order) != 1354:
        raise Abort(f"universe is {len(order)}, expected 1354")
    projected = (len(MARKETS) + int(TARGET / 0.70)) * len(YEARS) * 2 * IEM_PROJECTED_PER_REQUEST
    guard(root, projected)
    (root / "pool_order.txt").write_text("\n".join(order) + "\n", encoding="utf-8")
    done = {}
    filt_path = root / "filter_log.jsonl"
    if filt_path.exists():
        for line in filt_path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            done[rec["icao"]] = rec
    session = requests.Session()
    budget = ErrorBudget()
    print(json.dumps({"pid": os.getpid(), "start_utc": now_utc(), "projected_bytes": projected}), flush=True)
    for icao in MARKETS:
        fetch_station(session, root, icao, meta[icao]["sid"], budget)
    print(f"markets fetched {now_utc()} rss={rss_bytes()}", flush=True)
    survivors = [i for i in order if done.get(i, {}).get("survives")]
    for idx, icao in enumerate(order):
        if len(survivors) >= TARGET:
            break
        if icao in done:
            continue
        files = fetch_station(session, root, icao, meta[icao]["sid"], budget)
        res = station_filter(files, meta[icao]["tz"])
        rec = {"icao": icao, "order_index": idx, "filtered_utc": now_utc(), **res}
        log(root, "filter_log.jsonl", rec)
        done[icao] = rec
        if res["survives"]:
            survivors.append(icao)
        rss, free = guard(root)
        print(f"{idx} {icao} survives={res['survives']} n={len(survivors)} rss={rss // 2**20}MB "
              f"free={free / 2**30:.1f}GB fails={budget.fail}/{budget.n}", flush=True)
    final = {"survivors": survivors[:TARGET], "dose_subset": survivors[:DOSE], "n_survivors": len(survivors[:TARGET]),
             "n_fetched_pool": len(done), "order_exhausted": len(survivors) < TARGET, "finished_utc": now_utc()}
    (root / "station_set.json").write_text(json.dumps(final, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in final.items() if k not in ("survivors", "dose_subset")}), flush=True)
    return 0


# ------------------------------------------------------------------ NBP

def nbp_dates():
    out = []
    for year in YEARS:
        d = date(year, 8, 1)
        while d <= date(year, 9, 29):
            if d > LAST_ALLOWED:
                raise Abort("date after 2026-09-29")
            out.append(d)
            d += timedelta(days=1)
    return out


def s3_listing(session, key, budget):
    for attempt in range(5):
        try:
            r = session.get(BUCKET + "/", params={"list-type": "2", "prefix": key}, timeout=60)
            if r.status_code == 200:
                budget.record(True)
                root = ET.fromstring(r.content)
                for c in root.findall(f"{NS}Contents"):
                    if c.findtext(f"{NS}Key") == key:
                        return {"last_modified": c.findtext(f"{NS}LastModified"),
                                "size": int(c.findtext(f"{NS}Size")),
                                "etag": (c.findtext(f"{NS}ETag") or "").strip('"')}
                return None
        except (requests.RequestException, ET.ParseError):
            pass
        budget.record(False)
        time.sleep(2 ** attempt)
    raise Abort(f"listing failed: {key}")


def stream_to(session, url, path, budget):
    for attempt in range(5):
        try:
            h = hashlib.sha256()
            n = 0
            with session.get(url, stream=True, timeout=120) as r:
                if r.status_code != 200:
                    raise requests.RequestException(f"status {r.status_code}")
                with open(path, "wb") as sink:
                    for chunk in r.iter_content(1 << 20):
                        sink.write(chunk)
                        h.update(chunk)
                        n += len(chunk)
                headers = {"last_modified_http": r.headers.get("Last-Modified"), "etag_http": r.headers.get("ETag")}
            budget.record(True)
            return n, h.hexdigest(), headers
        except requests.RequestException:
            budget.record(False)
            if path.exists():
                path.unlink()
            time.sleep(2 ** attempt)
    raise Abort(f"download failed: {url}")


def extract_blocks(content, wanted):
    """Blocks delimited exactly as L9's Range fetcher: header-line start to the next header-line start."""
    heads = [(m.group(1).decode(), m.start()) for m in HEADER_RE.finditer(content)]
    out = {}
    for i, (sid, start) in enumerate(heads):
        if sid in wanted and sid not in out:
            end = heads[i + 1][1] if i + 1 < len(heads) else len(content)
            out[sid] = {"offset": start, "block": content[start:end].decode("ascii", "replace")}
    return out


def cmd_nbp(args):
    root = Path(args.root)
    station_set = json.loads((root / "station_set.json").read_text(encoding="utf-8"))
    wanted = set(station_set["survivors"]) | set(MARKETS)
    dates = nbp_dates()
    sink_path = root / "nbp_station_blocks_pool.jsonl"
    done = set()
    if sink_path.exists():
        for line in sink_path.read_text(encoding="utf-8").splitlines():
            done.add(json.loads(line)["utc_date"])
    guard(root, NBP_PROJECTED_PER_DATE + len(dates) * len(wanted) * 4096)
    tmp_dir = root / "nbp_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    budget = ErrorBudget()
    print(json.dumps({"pid": os.getpid(), "start_utc": now_utc(), "dates": len(dates), "stations": len(wanted)}),
          flush=True)
    total = 0
    for n, day in enumerate(dates):
        if day.isoformat() in done:
            continue
        guard(root, NBP_PROJECTED_PER_DATE)
        key = f"blend.{day:%Y%m%d}/07/text/blend_nbptx.t07z"
        meta = s3_listing(session, key, budget)
        rec = {"utc_date": day.isoformat(), "cycle": "07", "key": key, "object": meta, "stations": {}}
        if meta:
            tmp = tmp_dir / f"{day:%Y%m%d}_07.txt"
            size, digest, headers = stream_to(session, f"{BUCKET}/{key}", tmp, budget)
            content = tmp.read_bytes()
            tmp.unlink()
            blocks = extract_blocks(content, wanted)
            del content
            rec["stations"] = {st: blocks.get(st) for st in sorted(wanted)}
            rec["download"] = {"bytes": size, "sha256": digest, **headers, "size_matches_listing": size == meta["size"]}
            total += size
            log(root, "receipts_nbp.jsonl", {"source": "noaa-nbm-grib2-pds (free, official)", "key": key,
                                             "bytes": size, "sha256": digest, **headers,
                                             "listing": meta, "fetched_utc": now_utc(),
                                             "stations_found": sum(1 for v in blocks.values() if v)})
        with open(sink_path, "a", encoding="utf-8") as sink:
            sink.write(json.dumps(rec, sort_keys=True) + "\n")
        rss, free = guard(root)
        if n % 10 == 0:
            print(f"{day} n={n} GB={total / 2**30:.2f} rss={rss // 2**20}MB free={free / 2**30:.1f}GB "
                  f"fails={budget.fail}/{budget.n}", flush=True)
        time.sleep(0.5)
    print(json.dumps({"finished_utc": now_utc(), "bytes": total}), flush=True)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("iem")
    a.add_argument("--stations", required=True)
    a.add_argument("--ids", required=True)
    a.add_argument("--root", required=True)
    b = sub.add_parser("nbp")
    b.add_argument("--root", required=True)
    f = sub.add_parser("filter-smoke", help="run F1..F5 on already-fetched files of one station (no network)")
    f.add_argument("--root", required=True)
    f.add_argument("--icao", required=True)
    f.add_argument("--tz", required=True)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "iem":
            return cmd_iem(args)
        if args.cmd == "nbp":
            return cmd_nbp(args)
        base = Path(args.root) / "raw" / "iem" / args.icao.lower()
        files = {(y, t): (base / f / f"{y}.csv") if (base / f / f"{y}.csv").exists() else None
                 for y in YEARS for t, f in ((3, "routine"), (4, "special"))}
        print(json.dumps(station_filter(files, args.tz), indent=1))
        return 0
    except Abort as exc:
        print(json.dumps({"abort": str(exc), "utc": now_utc()}), flush=True)
        return 3


if __name__ == "__main__":
    sys.exit(main())
