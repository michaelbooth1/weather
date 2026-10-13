"""A-IEM-1: tidy raw IEM METAR/SPECI chunks into per-station parquet + MANIFEST.json.

Columns: station (ICAO), iem_id, valid_utc, available_utc (= valid_utc + 10 min), local_date,
local_time, report_type (routine|speci), is_cor, tmpf (IEM), tgroup_c (T-group tenths, deg C),
tgroup_f (unrounded F from T-group), main_temp_c (body integer temp), dwpf, sknt, drct, gust,
skyc1..4, skyl1..4, metar, maintenance_flag ($), source_file.
Availability basis: METAR/SPECI valid time + 10 minutes (DESIGN rule 1). COR reports are flagged
(is_cor) and must be excluded from candidate inputs; they are kept for audit.
"""
import datetime as dt
import glob
import gzip
import hashlib
import io
import json
import os
import re
import sys
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = r"C:\swarm\data\iem"
RAW = os.path.join(ROOT, "raw_metar")
OUT = os.path.join(ROOT, "metar")
STATIONS = json.load(open(r"C:\swarm\stations.json"))["stations"]
TGRP = re.compile(r"\sT([01])(\d{3})([01])?(\d{3})?(?=\s|$)")
BODY_T = re.compile(r"\s(M?\d{2})/(M?\d{2})?(?=\s)")
COR = re.compile(r"^\S+\s+\d{6}Z\s+(?:AUTO\s+)?COR\b|\sCOR\s")
LAST_LOCAL = dt.date(2026, 9, 29)
FIRST = dt.date(2024, 5, 1)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def parse_tgroup(m):
    if not m:
        return None
    t = int(m.group(2)) / 10.0
    return -t if m.group(1) == "1" else t


def body_temp(metar):
    pre = metar.split(" RMK")[0]
    m = BODY_T.search(pre + " ")
    if not m:
        return None
    s = m.group(1)
    return -int(s[1:]) if s.startswith("M") else int(s)


def load_station(icao):
    frames = []
    for fn in sorted(glob.glob(os.path.join(RAW, f"{icao}_*.csv.gz"))):
        rtype = os.path.basename(fn).split("_")[1]
        with gzip.open(fn, "rt", encoding="utf-8") as f:
            first = f.readline()
            df = pd.read_csv(f, dtype=str, keep_default_na=False)
        df["report_type"] = rtype
        df["source_file"] = os.path.basename(fn)
        frames.append(df)
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    tz = ZoneInfo(STATIONS[icao]["tzname"])
    df["valid_utc"] = pd.to_datetime(df["valid"], format="%Y-%m-%d %H:%M", utc=True)
    df["available_utc"] = df["valid_utc"] + pd.Timedelta(minutes=10)
    loc = df["valid_utc"].dt.tz_convert(tz)
    df["local_time"] = loc.dt.strftime("%Y-%m-%dT%H:%M%z")
    df["local_date"] = loc.dt.date
    for c in ["tmpf", "dwpf", "sknt", "drct", "gust", "skyl1", "skyl2", "skyl3", "skyl4"]:
        df[c] = pd.to_numeric(df[c].replace({"M": None, "T": None}), errors="coerce")
    for c in ["skyc1", "skyc2", "skyc3", "skyc4"]:
        df[c] = df[c].replace({"M": None})
    df["metar"] = df["metar"].astype(str)
    df["is_cor"] = df["metar"].str.contains(COR)
    df["tgroup_c"] = [parse_tgroup(TGRP.search(" " + m.split(" RMK", 1)[1]) if " RMK" in m else None)
                      for m in df["metar"]]
    df["tgroup_f"] = df["tgroup_c"] * 9.0 / 5.0 + 32.0
    df["main_temp_c"] = [body_temp(m) for m in df["metar"]]
    df["maintenance_flag"] = df["metar"].str.rstrip().str.endswith("$")
    df.insert(0, "iem_id", df.pop("station"))
    df.insert(0, "station", icao)
    df = df.drop(columns=["valid"])
    df = df[(df["local_date"] <= LAST_LOCAL)]
    n_before = len(df)
    df = df.drop_duplicates(subset=["valid_utc", "report_type", "metar"])
    df = df.sort_values(["valid_utc", "report_type"]).reset_index(drop=True)
    assert (df["local_date"] <= LAST_LOCAL).all()
    return df, n_before - len(df)


def main():
    manifest = {
        "agent": "a-iem-1", "source": "IEM ASOS asos.py METAR/SPECI",
        "url_pattern": ("https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=<IEM_ID>"
                        "&data=tmpf&data=dwpf&data=sknt&data=drct&data=gust&data=skyc1..4&data=skyl1..4"
                        "&data=metar&sts=<UTC>&ets=<UTC>&tz=Etc/UTC&format=onlycomma&report_type=<3|4>"),
        "window": {"priority": "2026-07-25..2026-09-29 (local dates)",
                   "history": "2024-05-01..2026-07-24", "upper_bound": "local midnight ending 2026-09-29 per station; rows with local_date >= 2026-09-30 dropped (0 kept)"},
        "availability_basis": ("METAR/SPECI valid time (UTC) + 10 minutes = available_utc. COR reports flagged "
                               "is_cor=True and must be excluded from candidate inputs. IEM tmpf may be revised/"
                               "derived; raw METAR text and T-group are the primary values."),
        "report_type": "requested separately: 3 = routine, 4 = SPECI (IEM report_type)",
        "generated_local": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "files": [], "coverage": {},
    }
    for icao in sorted(STATIONS):
        res = load_station(icao)
        if res is None:
            continue
        df, ndup = res
        out = os.path.join(OUT, f"{icao}.parquet")
        df.to_parquet(out, index=False)
        days = df.groupby("local_date")
        routine = df[df.report_type == "routine"].groupby("local_date").size()
        speci = df[df.report_type == "speci"].groupby("local_date").size()
        tg = df[df.tgroup_c.notna()].groupby("local_date").size()
        all_days = pd.date_range(FIRST, LAST_LOCAL, freq="D").date
        cov = {}
        for d in all_days:
            cov[str(d)] = [int(routine.get(d, 0)), int(speci.get(d, 0)), int(tg.get(d, 0))]
        win = [d for d in all_days if d >= dt.date(2026, 7, 25)]
        manifest["coverage"][icao] = {
            "columns": ["routine_rows", "speci_rows", "rows_with_tgroup"],
            "rows": int(len(df)), "cor_rows": int(df.is_cor.sum()), "dups_dropped": int(ndup),
            "days_with_ge20_routine_all": int(sum(1 for d in all_days if cov[str(d)][0] >= 20)),
            "days_total_all": len(all_days),
            "days_with_ge20_routine_window": int(sum(1 for d in win if cov[str(d)][0] >= 20)),
            "days_total_window": len(win),
            "tgroup_fraction": round(float(df.tgroup_c.notna().mean()), 4),
            "per_day": cov,
        }
        manifest["files"].append({"path": f"metar/{icao}.parquet", "bytes": os.path.getsize(out), "sha256": sha(out)})
    for fn in sorted(glob.glob(os.path.join(RAW, "*.csv.gz"))):
        manifest["files"].append({"path": "raw_metar/" + os.path.basename(fn), "bytes": os.path.getsize(fn), "sha256": sha(fn)})
    tmp = os.path.join(OUT, "MANIFEST.json.tmp")
    json.dump(manifest, open(tmp, "w"), indent=1, default=str)
    os.replace(tmp, os.path.join(OUT, "MANIFEST.json"))
    for icao, c in manifest["coverage"].items():
        print(icao, c["rows"], "cor", c["cor_rows"], "win", c["days_with_ge20_routine_window"], "/", c["days_total_window"],
              "all", c["days_with_ge20_routine_all"], "/", c["days_total_all"], "tg", c["tgroup_fraction"])


if __name__ == "__main__":
    main()
