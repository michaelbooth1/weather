"""A-IEM-4 build: parse raw 1-minute ASOS chunks -> per-station parquet, coverage per station-local-day,
MANIFEST.json. TRUTH / LABEL USE ONLY (not point in time). Run with C:\\swarm\\venv\\Scripts\\python.exe.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

OUT = Path(r"C:\swarm\data\iem\onemin")
RAW = OUT / "raw"
STATIONS = json.loads(Path(r"C:\swarm\stations.json").read_text())["stations"]
FIRST, LAST = pd.Timestamp("2026-07-25"), pd.Timestamp("2026-09-29")
URL_PATTERN = ("https://mesonet.agron.iastate.edu/cgi-bin/request/asos1min.py?station={iem_id}&vars=tmpf"
               "&sts={YYYY-mm-ddTHH:MMZ}&ets={YYYY-mm-ddTHH:MMZ}&sample=1min&what=download&tz=UTC&delim=comma&gis=no")


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> None:
    files, cov_rows = [], []
    days = pd.date_range(FIRST, LAST, freq="D")
    for icao, st in STATIONS.items():
        parts = []
        for fn in sorted(RAW.glob(f"{icao}_*.csv.gz")):
            files.append(fn)
            with gzip.open(fn, "rb") as fh:
                df = pd.read_csv(io.BytesIO(fh.read()), na_values=["M", ""], dtype={"tmpf": "float64"})
            parts.append(df)
        df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(
            columns=["station", "station_name", "valid(UTC)", "tmpf"])
        df = df.rename(columns={"valid(UTC)": "valid_utc"})
        df["valid_utc"] = pd.to_datetime(df["valid_utc"], utc=True)
        df["tmpf"] = pd.to_numeric(df["tmpf"], errors="coerce")
        df = df.drop_duplicates("valid_utc").sort_values("valid_utc")
        df["icao"] = icao
        df["local_date"] = df["valid_utc"].dt.tz_convert(st["tzname"]).dt.tz_localize(None).dt.normalize()
        df = df[(df["local_date"] >= FIRST) & (df["local_date"] <= LAST)]
        out = df[["icao", "valid_utc", "tmpf", "local_date"]].copy()
        out["local_date"] = out["local_date"].dt.date.astype(str)
        pq = OUT / f"{icao}.parquet"
        out.to_parquet(pq, index=False)
        files.append(pq)
        g = df.dropna(subset=["tmpf"]).groupby("local_date")
        for d in days:
            if d in g.groups:
                sub = g.get_group(d)
                lh = sub["valid_utc"].dt.tz_convert(st["tzname"]).dt.hour
                gaps = sub["valid_utc"].diff().dt.total_seconds().div(60).fillna(1)
                cov_rows.append(dict(icao=icao, local_date=str(d.date()), minutes_valid=int(len(sub)),
                                     coverage_frac=round(len(sub) / 1440, 4),
                                     hours_with_data=int(lh.nunique()),
                                     minutes_valid_10_18_local=int(((lh >= 10) & (lh < 18)).sum()),
                                     max_gap_min=int(gaps.max()),
                                     tmax_1min_f=float(sub["tmpf"].max())))
            else:
                cov_rows.append(dict(icao=icao, local_date=str(d.date()), minutes_valid=0, coverage_frac=0.0,
                                     hours_with_data=0, minutes_valid_10_18_local=0, max_gap_min=None,
                                     tmax_1min_f=None))
    cov = pd.DataFrame(cov_rows)
    cov_path = OUT / "coverage_station_day.csv"
    cov.to_csv(cov_path, index=False)
    files.append(cov_path)
    files.append(OUT / "fetch.log")
    per_station = {}
    for icao, g in cov.groupby("icao"):
        per_station[icao] = dict(
            days=int(len(g)), days_any=int((g.minutes_valid > 0).sum()),
            days_ge_90pct=int((g.coverage_frac >= 0.9).sum()),
            days_full_10_18_local=int((g.minutes_valid_10_18_local >= 456).sum()),  # >=95% of 480
            minutes_valid=int(g.minutes_valid.sum()), coverage_frac=round(g.minutes_valid.sum() / (1440 * len(g)), 4))
    manifest = dict(
        source="IEM ASOS 1-minute (asos1min.py; NCEI DSI-6405/6406 1-minute ASOS archive)",
        agent="a-iem-4", sub="onemin",
        use="TRUTH/LABEL USE ONLY. NOT POINT IN TIME (NCEI 1-minute archive, 18-36 h+ delay, QC/back-filled). "
            "Never a candidate input (DESIGN hard rule 1).",
        point_in_time=False,
        availability_basis="none: not point in time; retrieved 2026-10-04 ~01:00 local from IEM archive; "
                           "treat as available only after the fact (labels/truth).",
        url_pattern=URL_PATTERN, variable="tmpf (whole deg F as served by IEM)",
        window_local_days="2026-07-25..2026-09-29 per station time zone (request window = local midnight "
                          "07-25 .. local midnight 09-30, expressed in UTC; split at UTC month starts)",
        retrieved_local=datetime.now().strftime("%Y-%m-%d %H:%M"),
        politeness="sequential, one connection, >= 2 s spacing, backoff 60 s doubling on 429/503/'Too many requests'",
        caveats=[
            "KBKF (Buckley SFB, military) has no 1-minute data at IEM: empty response for the window and for a "
            "2024-06 probe; 0 coverage.",
            "Other stations have partial minute coverage (gaps are absent rows in the IEM archive); see "
            "coverage_station_day.csv. Use minutes_valid_10_18_local/max_gap_min before trusting tmax_1min_f.",
            "tmax_1min_f is the max of 1-minute tmpf per local day (whole deg F); truth/diagnostic only.",
        ],
        coverage_per_station=per_station,
        coverage_station_day_file="coverage_station_day.csv",
        files=[dict(path=str(p.relative_to(OUT)).replace("\\", "/"), bytes=p.stat().st_size, sha256=sha(p))
               for p in files],
        fetch_code=r"C:\pt\swarm\tools\research\model_parity\a-iem-4_onemin_fetch.py",
        build_code=r"C:\pt\swarm\tools\research\model_parity\a-iem-4_onemin_build.py",
    )
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps(per_station, indent=1))


if __name__ == "__main__":
    main()
