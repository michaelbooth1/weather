"""D-CAP1 (model-parity swarm v2, development only): METAR reportTime date-keying check.

Descriptive, no scoring, no registry rule. Three checks:

1. On the AWC Data API rows fetched by T26 (C:\\swarm\\out\\t26\\raw, 2026-09-04..09-29): does
   ``reportTime`` (the field production's ``parse_metar_payload`` keys rows on) fall on a different
   station-local date from ``obsTime``; and is AWC ``temp`` equal to the RMK T-group tenths?
2. On the IEM METAR history (C:\\swarm\\data\\iem\\metar, local dates 2024-05-01..2026-09-29): emulate
   production's keying (routine reports observed at local 23:45-23:59 carry a reportTime of next-day
   00:00 local, so they move to the next local date) and count station-days where the
   since-midnight max differs from the valid-time max, by month.
3. On the harness cache (C:\\swarm\\cache\\snapshots.parquet / bands.parquet, targets <= 2026-09-29):
   rows where the captured floor bucket exceeds the settlement bucket, and whether the winning band was
   floor-masked there.

Writes C:\\swarm\\out\\d-cap1\\d_cap1_facts.json.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

AWC_DIR = r"C:\swarm\out\t26\raw"
IEM_DIR = r"C:\swarm\data\iem\metar"
CACHE = r"C:\swarm\cache"
OUT = r"C:\swarm\out\d-cap1\d_cap1_facts.json"
TZ = {
    "KATL": "America/New_York", "KAUS": "America/Chicago", "KBKF": "America/Denver",
    "KDAL": "America/Chicago", "KHOU": "America/Chicago", "KLAX": "America/Los_Angeles",
    "KLGA": "America/New_York", "KMIA": "America/New_York", "KORD": "America/Chicago",
    "KSEA": "America/Los_Angeles", "KSFO": "America/Los_Angeles",
}
LAST_DATE = pd.Timestamp("2026-09-29")


def awc_check() -> dict:
    total = tgroup = tenth_mismatch = date_shift = 0
    shift_types: dict[str, int] = {}
    rt_minus_obs = []
    fields: set[str] = set()
    for path in sorted(glob.glob(os.path.join(AWC_DIR, "awc_K*.json"))):
        station = os.path.basename(path)[4:8]
        zone = ZoneInfo(TZ[station])
        for row in json.load(open(path, encoding="utf-8")):
            total += 1
            fields.update(row.keys())
            match = re.search(r" T([01])(\d{3})([01])(\d{3})", row.get("rawOb", ""))
            if match:
                tgroup += 1
                value = int(match.group(2)) / 10 * (-1 if match.group(1) == "1" else 1)
                if row.get("temp") is None or abs(value - row["temp"]) > 0.01:
                    tenth_mismatch += 1
            obs = dt.datetime.fromtimestamp(row["obsTime"], dt.timezone.utc)
            rep = dt.datetime.fromisoformat(row["reportTime"].replace("Z", "+00:00"))
            rt_minus_obs.append((rep - obs).total_seconds() / 60)
            if obs.astimezone(zone).date() != rep.astimezone(zone).date():
                date_shift += 1
                kind = row.get("metarType", "?")
                shift_types[kind] = shift_types.get(kind, 0) + 1
    arr = np.array(rt_minus_obs)
    return {
        "reports": total,
        "fields": sorted(fields),
        "with_tgroup": tgroup,
        "temp_ne_tgroup_tenths": tenth_mismatch,
        "reportTime_local_date_ne_obsTime_local_date": date_shift,
        "date_shift_by_metarType": shift_types,
        "reportTime_minus_obsTime_min": {
            "min": float(arr.min()), "p50": float(np.median(arr)),
            "p90": float(np.quantile(arr, 0.9)), "max": float(arr.max()),
        },
    }


def iem_emulation() -> dict:
    frames = []
    for path in sorted(glob.glob(os.path.join(IEM_DIR, "K*.parquet"))):
        d = pd.read_parquet(path, columns=["local_time", "local_date", "report_type", "tmpf", "tgroup_f", "is_cor"])
        d = d[~d.is_cor]
        s = d.local_time.astype(str)
        hour = s.str[11:13].astype(int)
        minute = s.str[14:16].astype(int)
        d["ld"] = pd.to_datetime(d.local_date.astype(str))
        d["t"] = np.floor(d.tgroup_f.fillna(d.tmpf) + 0.5)
        push = (d.report_type == "routine") & (hour == 23) & (minute >= 45)
        true_max = d.groupby("ld").t.max()
        keep = d[~push].groupby("ld").t.max()
        carried = d[push].groupby("ld").t.max()
        carried.index = carried.index + pd.Timedelta(days=1)
        prod = pd.concat([keep, carried], axis=1).max(axis=1)
        j = pd.concat([true_max.rename("true"), prod.rename("prod")], axis=1).dropna()
        j = j[(j.index >= "2024-05-02") & (j.index <= LAST_DATE)]
        j["station"] = os.path.basename(path)[:4]
        frames.append(j)
    j = pd.concat(frames)
    j["over"] = j["prod"] > j["true"]
    j["under"] = j["prod"] < j["true"]
    j["month"] = j.index.month
    octdec = j[j.month.isin([10, 11, 12])]
    augsep26 = j[j.index >= "2026-08-01"]
    return {
        "station_days": int(len(j)),
        "over_days": int(j.over.sum()),
        "under_days": int(j.under.sum()),
        "max_over_F": float((j["prod"] - j["true"])[j.over].max()),
        "over_rate_by_month": {int(k): round(float(v), 4) for k, v in j.groupby("month").over.mean().items()},
        "under_rate_by_month": {int(k): round(float(v), 4) for k, v in j.groupby("month").under.mean().items()},
        "oct_dec": {
            "station_days": int(len(octdec)), "over_rate": round(float(octdec.over.mean()), 4),
            "under_rate": round(float(octdec.under.mean()), 4),
            "over_rate_by_station": {k: round(float(v), 3) for k, v in octdec.groupby("station").over.mean().items()},
        },
        "aug_sep_2026_over": [
            {"station": r.station, "date": str(i.date()), "valid_time_max": float(r["true"]), "emulated_floor": float(r["prod"])}
            for i, r in augsep26[augsep26.over].iterrows()
        ],
    }


def cache_check() -> dict:
    s = pd.read_parquet(os.path.join(CACHE, "snapshots.parquet"),
                        columns=["row_key", "station", "target_date", "floor_bucket", "settlement_bucket"])
    assert (pd.to_datetime(s.target_date.astype(str)) <= LAST_DATE).all()
    over = s[s.floor_bucket > s.settlement_bucket]
    b = pd.read_parquet(os.path.join(CACHE, "bands.parquet"),
                        columns=["row_key", "low", "high", "p_served", "is_winner", "floor_impossible"])
    w = b[b.row_key.isin(over.row_key) & b.is_winner.astype(bool)].merge(over, on="row_key")
    out = []
    for (station, date), g in w.groupby(["station", w.target_date.astype(str)]):
        out.append({
            "station": station, "date": date, "snapshots": int(len(g)),
            "winner_band": [float(g.low.iloc[0]), float(g.high.iloc[0])],
            "winner_floor_masked_share": float(g.floor_impossible.astype(float).mean()),
            "mean_p_served_on_winner": round(float(g.p_served.mean()), 4),
        })
    return {"rows_floor_bucket_gt_settlement_bucket": int(len(over)), "table_rows": int(len(s)), "days": out}


def main() -> None:
    facts = {
        "agent": "d-cap1", "label": "development, descriptive, nothing scored",
        "awc": awc_check(), "iem_emulation": iem_emulation(), "cache": cache_check(),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(facts, fh, indent=1, default=str)
    print(json.dumps(facts, indent=1, default=str))


if __name__ == "__main__":
    main()
