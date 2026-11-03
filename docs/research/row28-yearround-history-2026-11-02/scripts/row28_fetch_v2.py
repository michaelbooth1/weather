"""Row 28 INPUTS-ONLY fetch (lane L59): NBM NBP Dec-May bulletins + R-P2 IEM pool extension.

v2 adds ``--gap`` to both phases (master 11-02 ruling (a)3: close arm C's pool training gap):
  nbp --gap  -- cycle 07 on Jun 01..Jul 31 and Oct 01..Dec 16 of 2021-2025 (690 dates).
  iem --gap  -- one request per (station, year, type) spanning Y-05-31 00Z .. Y-12-17 12Z, Y = 2021..2025
                (overlaps the Aug-Sep span L48 already holds; files land under ``gap{Y}.csv``).
Everything else (guards, receipts, helpers) is v1 unchanged.

Network-bound light work (master 11-01 ruling), run directly with ``python -I``; it never imports ``weather``.
Network primitives (S3 listing, streamed GET, L9-delimited block extraction, IEM GET with retries, error
budget) are imported unchanged from lane L48's ``station_pool_fetch_v2.py`` (sha256 pinned below).

Phases:
  nbp  -- for every date in the request list, cycle 07 (plus the 01/00 add-on for the 8 absent/late dates):
          S3 listing metadata, full GET streamed to a temp file, sha256, extract the 11 market + 300 R-P2 pool
          stations' blocks, append one L48/L9-shaped JSONL record, delete the bulletin.
  iem  -- IEM ASOS routine (3) and special (4) CSVs for the 11 markets + 300 R-P2 pool stations, one request per
          (station, season-year, type), season Y = (Y-1)-12-16 00Z .. Y-06-01 12Z for Y = 2022..2025 and
          2020-12-31 00Z .. 2021-06-01 12Z for Y = 2021. Raw CSV kept (small), receipted.

Inputs only: nothing here reads a temperature, an observation value or a label. Integrity output is counts,
dates, sizes and posted times only.

Date guard: the request list is generated here and asserted BEFORE the first request: no date in
2026-05-27..2026-07-30 and none >= 2026-09-30 (in practice everything is <= 2025-12-31).
Free-space guard: stop cleanly if C: free bytes would fall below 45 GiB (hard floor 40 GiB).

Usage:
  python -I row28_fetch_v1.py nbp --root <out root> --l48 <station_pool_fetch_v2.py> --listing <nbp07_listing_decmay.tsv>
          --classes <rp2_classes.json> --station-set <L48 station_set.json> [--addon]
  python -I row28_fetch_v1.py iem --root <out root> --l48 <...> --classes <...> --station-set <...> --stations <s0_candidate_stations.json>
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

L48_SHA256 = "98ddd33e9671c0ca723a7d735e0c4513e74fd64c76827551cdda82fd40c2ef5c"
CLASSES_SHA256 = "35d0090dddf7b082c5ce0d777cf488c09bbcf6baead14c786e68c39fbafe1689"
SEALED = (date(2026, 5, 27), date(2026, 7, 30))
HARD_FROM = date(2026, 9, 30)
STOP_FREE = 45 * 1024 ** 3
FLOOR_FREE = 40 * 1024 ** 3
ADDON_DATES = ("2021-01-22", "2021-02-11", "2022-01-06", "2023-01-20", "2023-05-24", "2024-04-16",
               "2024-04-21", "2024-05-15")
IEM_SEASONS = (2021, 2022, 2023, 2024, 2025)


class Stop(RuntimeError):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_l48(path):
    got = sha256_file(path)
    if got != L48_SHA256:
        raise Stop(f"L48 fetcher sha {got} != pinned {L48_SHA256}")
    spec = importlib.util.spec_from_file_location("l48_station_pool_fetch_v2", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def assert_dates(days):
    bad = [d for d in days if (SEALED[0] <= d <= SEALED[1]) or d >= HARD_FROM]
    if bad:
        raise Stop(f"forbidden dates in request list: {bad[:5]}")
    if not days:
        raise Stop("empty request list")


def free_guard(root, upcoming=0):
    free = shutil.disk_usage(root).free
    if free < FLOOR_FREE:
        raise Stop(f"free {free} below the 40 GiB floor")
    if free - upcoming < STOP_FREE:
        raise Stop(f"free {free} minus upcoming {upcoming} below the 45 GiB stop line")
    return free


def wanted_stations(classes_path, station_set_path, l48):
    if sha256_file(classes_path) != CLASSES_SHA256:
        raise Stop("rp2_classes.json sha mismatch")
    survivors = json.loads(Path(station_set_path).read_text(encoding="utf-8"))["survivors"]
    cls = json.loads(Path(classes_path).read_text(encoding="utf-8"))
    pool = set(cls["stations"]) if isinstance(cls["stations"], dict) else {s["icao"] for s in cls["stations"]}
    pool -= set(l48.MARKETS)  # the classes file also classifies the 11 market stations
    if set(survivors) != pool or len(pool) != 300:
        raise Stop(f"station_set survivors ({len(survivors)}) != rp2 class pool ({len(pool)})")
    return sorted(pool), list(l48.MARKETS)


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(root, name, rec):
    with open(Path(root) / name, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


# ------------------------------------------------------------------ NBP

def gap_days():
    out = []
    for y in IEM_SEASONS:
        for a, b in ((date(y, 6, 1), date(y, 7, 31)), (date(y, 10, 1), date(y, 12, 16))):
            d = a
            while d <= b:
                out.append(d)
                d += timedelta(days=1)
    return out


def nbp_requests(listing_path, addon, gap=False):
    if gap:
        reqs = [(d, "07") for d in gap_days()]
        assert_dates([d for d, _ in reqs])
        return reqs
    days = []
    for line in Path(listing_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            days.append(date.fromisoformat(line.split("\t")[0]))
    days = sorted(set(days))
    if addon:
        reqs = [(date.fromisoformat(d), c) for d in ADDON_DATES for c in ("01", "00")]
    else:
        reqs = [(d, "07") for d in days]
    assert_dates([d for d, _ in reqs])
    return reqs


def cmd_nbp(args):
    import requests

    l48 = load_l48(args.l48)
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    pool, markets = wanted_stations(args.classes, args.station_set, l48)
    wanted = set(pool) | set(markets)
    reqs = nbp_requests(args.listing, args.addon, args.gap)
    tag = "gap_c07" if args.gap else ("addon_01_00" if args.addon else "c07")
    sink_path = root / f"nbp_station_blocks_{tag}.jsonl"
    done = set()
    if sink_path.exists():
        for line in sink_path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done.add((r["utc_date"], r["cycle"]))
    tmp_dir = root / "nbp_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    budget = l48.ErrorBudget()
    free_guard(root, 64 * 1024 ** 2)
    print(json.dumps({"pid": os.getpid(), "start_utc": now_utc(), "phase": tag, "requests": len(reqs),
                      "first": reqs[0][0].isoformat(), "last": reqs[-1][0].isoformat(),
                      "stations": len(wanted)}), flush=True)
    total = 0
    for n, (day, cycle) in enumerate(reqs):
        if (day.isoformat(), cycle) in done:
            continue
        free_guard(root, 64 * 1024 ** 2)
        key = f"blend.{day:%Y%m%d}/{cycle}/text/blend_nbptx.t{cycle}z"
        meta = l48.s3_listing(session, key, budget)
        rec = {"utc_date": day.isoformat(), "cycle": cycle, "key": key, "object": meta, "stations": {}}
        receipt = {"source": "noaa-nbm-grib2-pds (free, official)", "url": f"{l48.BUCKET}/{key}", "key": key,
                   "listing": meta, "fetched_utc": now_utc()}
        if meta:
            tmp = tmp_dir / f"{day:%Y%m%d}_{cycle}.txt"
            size, digest, headers = l48.stream_to(session, f"{l48.BUCKET}/{key}", tmp, budget)
            content = tmp.read_bytes()
            tmp.unlink()
            blocks = l48.extract_blocks(content, wanted)
            del content
            rec["stations"] = {st: blocks.get(st) for st in sorted(wanted)}
            rec["download"] = {"bytes": size, "sha256": digest, **headers,
                               "size_matches_listing": size == meta["size"]}
            total += size
            receipt.update({"bytes": size, "sha256": digest, **headers,
                            "stations_found": sum(1 for v in blocks.values() if v)})
        else:
            receipt.update({"bytes": 0, "absent": True})
        line = json.dumps(rec, sort_keys=True)
        receipt["record_sha256"] = hashlib.sha256(line.encode("utf-8")).hexdigest()
        with open(sink_path, "a", encoding="utf-8") as sink:
            sink.write(line + "\n")
        log(root, f"receipts_nbp_{tag}.jsonl", receipt)
        if n % 25 == 0:
            print(f"{day} {cycle} n={n} GB={total / 2**30:.2f} free={shutil.disk_usage(root).free / 2**30:.1f}GiB "
                  f"fails={budget.fail}/{budget.n}", flush=True)
        time.sleep(0.5)
    print(json.dumps({"finished_utc": now_utc(), "phase": tag, "bytes_downloaded_this_run": total}), flush=True)
    return 0


# ------------------------------------------------------------------ IEM

def iem_window(season, gap=False):
    if gap:
        return (datetime(season, 5, 31, tzinfo=timezone.utc), datetime(season, 12, 17, 12, tzinfo=timezone.utc))
    sts = datetime(2020, 12, 31, tzinfo=timezone.utc) if season == 2021 else datetime(season - 1, 12, 16,
                                                                                     tzinfo=timezone.utc)
    ets = datetime(season, 6, 1, 12, tzinfo=timezone.utc)
    return sts, ets


def iem_url(l48, sid, season, rtype, gap=False):
    sts, ets = iem_window(season, gap)
    params = [("station", sid), ("data", "tmpc"), ("data", "metar"), ("tz", "Etc/UTC"), ("format", "onlycomma"),
              ("latlon", "no"), ("missing", "M"), ("trace", "T"), ("direct", "no"), ("report_type", str(rtype)),
              ("sts", sts.strftime("%Y-%m-%dT%H:%MZ")), ("ets", ets.strftime("%Y-%m-%dT%H:%MZ"))]
    return f"{l48.IEM_URL}?{urlencode(params)}"


def cmd_iem(args):
    import requests

    l48 = load_l48(args.l48)
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    pool, markets = wanted_stations(args.classes, args.station_set, l48)
    meta = json.loads(Path(args.stations).read_text(encoding="utf-8"))
    days = []
    for s in IEM_SEASONS:
        sts, ets = iem_window(s, args.gap)
        d = sts.date()
        while d <= ets.date():
            days.append(d)
            d += timedelta(days=1)
    assert_dates(days)
    stations = list(markets) + list(pool)
    session = requests.Session()
    budget = l48.ErrorBudget()
    free_guard(root, 2 * 1024 ** 3)
    print(json.dumps({"pid": os.getpid(), "start_utc": now_utc(), "phase": "iem_gap" if args.gap else "iem", "stations": len(stations),
                      "requests": len(stations) * len(IEM_SEASONS) * 2,
                      "last_day": max(days).isoformat()}), flush=True)
    n = 0
    total = 0
    for icao in stations:
        sid = meta[icao]["sid"]
        for season in IEM_SEASONS:
            for rtype, folder in ((3, "routine"), (4, "special")):
                path = root / "raw" / "iem" / icao.lower() / folder / (f"gap{season}.csv" if args.gap else f"season{season}.csv")
                if path.exists():
                    continue
                free_guard(root, 4 * 1024 ** 2)
                url = iem_url(l48, sid, season, rtype, args.gap)
                status, body = l48.iem_get(session, url, budget)
                rec = {"source": "IEM ASOS asos.py (free, official)", "url": url, "icao": icao, "season": season,
                       "report_type": rtype, "status": status, "bytes": len(body),
                       "sha256": hashlib.sha256(body).hexdigest(), "fetched_utc": now_utc()}
                if status == 200:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_suffix(".part")
                    tmp.write_bytes(body)
                    os.replace(tmp, path)
                    rec["file"] = str(path)
                    total += len(body)
                log(root, "receipts_iem_gap.jsonl" if args.gap else "receipts_iem.jsonl", rec)
                n += 1
                if n % 50 == 0:
                    print(f"{icao} n={n} GB={total / 2**30:.3f} free={shutil.disk_usage(root).free / 2**30:.1f}GiB "
                          f"fails={budget.fail}/{budget.n}", flush=True)
                time.sleep(l48.IEM_SPACING_S)
    print(json.dumps({"finished_utc": now_utc(), "phase": "iem_gap" if args.gap else "iem", "bytes_this_run": total}), flush=True)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("nbp", "iem"):
        p = sub.add_parser(name)
        p.add_argument("--root", required=True)
        p.add_argument("--l48", required=True)
        p.add_argument("--classes", required=True)
        p.add_argument("--station-set", required=True)
        if name == "nbp":
            p.add_argument("--listing", default="")
            p.add_argument("--addon", action="store_true")
        else:
            p.add_argument("--stations", required=True)
        p.add_argument("--gap", action="store_true")
    args = ap.parse_args(argv)
    try:
        return cmd_nbp(args) if args.cmd == "nbp" else cmd_iem(args)
    except Stop as exc:
        print(json.dumps({"stop": str(exc), "utc": now_utc()}), flush=True)
        return 3
    except Exception as exc:  # l48.Abort and network failures: stop cleanly, resumable
        print(json.dumps({"abort": f"{type(exc).__name__}: {exc}", "utc": now_utc()}), flush=True)
        return 4


if __name__ == "__main__":
    sys.exit(main())
