"""A-IEM-3: combine neighbour METAR raw CSVs into one parquet, coverage per market x neighbour x local day, MANIFEST."""
import datetime as dt, gzip, hashlib, io, json, re
from pathlib import Path
import pandas as pd

ROOT = Path(r"C:\swarm\data\iem\neighbours")
RAW = ROOT / "raw"
stations = json.load(open(r"C:\swarm\stations.json"))["stations"]
sel = json.load(open(ROOT / "selection.json"))
TGRP = re.compile(r"\bT([01])(\d{3})([01])(\d{3})\b")
COR = re.compile(r"\bCOR\b")

frames = []
for st, s in sel.items():
    for c in s["selected"]:
        for rname, rt in (("routine", 3), ("speci", 4)):
            p = RAW / f"{c['sid']}_{rname}.csv.gz"
            if not p.exists():
                continue
            df = pd.read_csv(p, dtype=str, keep_default_na=False)
            if df.empty:
                continue
            df["market_station"] = st
            df["neighbour_network"] = c["network"]
            df["dist_km"] = c["dist_km"]
            df["report_type"] = rt
            df["report_type_name"] = rname
            frames.append(df)
d = pd.concat(frames, ignore_index=True)
d = d.rename(columns={"station": "neighbour_sid", "valid": "valid_utc"})
d["valid_utc"] = pd.to_datetime(d["valid_utc"], utc=True)
d["tmpf"] = pd.to_numeric(d["tmpf"].replace({"M": None}), errors="coerce")
d["is_cor"] = d["metar"].str.contains(COR)
m = d["metar"].str.extract(TGRP)
tc = pd.to_numeric(m[1], errors="coerce") / 10.0
d["t_group_c"] = tc.where(m[0] != "1", -tc)
d["available_utc_min"] = d["valid_utc"] + pd.Timedelta(minutes=10)
assert d["valid_utc"].max() < pd.Timestamp("2026-09-30T00:00Z"), "row dated >= 2026-09-30"
assert d["valid_utc"].min() >= pd.Timestamp("2026-05-01T00:00Z")
n_ge_0930 = int((d["valid_utc"] >= pd.Timestamp("2026-09-30T00:00Z")).sum())
d = d.sort_values(["market_station", "neighbour_sid", "valid_utc", "report_type"]).reset_index(drop=True)
cols = ["market_station", "neighbour_sid", "neighbour_network", "dist_km", "valid_utc", "available_utc_min",
        "report_type", "report_type_name", "is_cor", "tmpf", "t_group_c", "metar"]
out = ROOT / "neighbours_metar.parquet"
d[cols].to_parquet(out, index=False)

# coverage per market x neighbour x market-local day (usable = tmpf present, not COR)
cov_rows = []
days = pd.date_range("2026-05-01", "2026-09-29", freq="D").date
for st, s in sel.items():
    tz = stations[st]["tzname"]
    sub = d[(d["market_station"] == st)].copy()
    sub["local_date"] = sub["valid_utc"].dt.tz_convert(tz).dt.date
    sub = sub[sub["tmpf"].notna() & ~sub["is_cor"]]
    g = sub.groupby(["neighbour_sid", "local_date", "report_type_name"]).size().unstack(fill_value=0)
    for c in s["selected"]:
        for day in days:
            key = (c["sid"], day)
            r = g.loc[key] if key in g.index else None
            cov_rows.append(dict(market_station=st, neighbour_sid=c["sid"], local_date=str(day),
                                 routine_rows=int(r.get("routine", 0)) if r is not None else 0,
                                 speci_rows=int(r.get("speci", 0)) if r is not None else 0))
cov = pd.DataFrame(cov_rows)
cov["has_18_routine"] = cov["routine_rows"] >= 18
cov_path = ROOT / "coverage_station_day.csv"
cov.to_csv(cov_path, index=False)
# note: the local date 2026-09-29 is truncated at 2026-09-30T00:00Z (evening hours missing for all zones)

summary = {}
for st, s in sel.items():
    cs = cov[cov["market_station"] == st]
    per_nb = {nb: dict(days_with_any=int((g2.routine_rows + g2.speci_rows > 0).sum()),
                        days_ge18_routine=int(g2.has_18_routine.sum()), n_days=len(g2))
              for nb, g2 in cs.groupby("neighbour_sid")}
    byday = cs.groupby("local_date")["has_18_routine"].sum()
    summary[st] = dict(within_50km=s["within_50km"], selected=[(c["sid"], c["dist_km"], c["network"]) for c in s["selected"]],
                       not_selected=s["not_selected"], per_neighbour=per_nb,
                       days_with_ge1_neighbour_ge18_routine=int((byday >= 1).sum()),
                       days_with_ge3_neighbours_ge18_routine=int((byday >= 3).sum()),
                       min_neighbours_ge18_on_a_day=int(byday.min()), n_days=int(len(byday)))


def sha(p):
    h = hashlib.sha256(); h.update(Path(p).read_bytes()); return h.hexdigest()

files = []
for p in sorted(ROOT.rglob("*")):
    if p.is_file() and p.name not in ("MANIFEST.json",):
        files.append(dict(path=str(p.relative_to(ROOT)).replace("\\", "/"), bytes=p.stat().st_size, sha256=sha(p)))
manifest = dict(
    source="IEM ASOS/AWOS METAR via asos.py, neighbours of the 11 market stations",
    agent="a-iem-3", development=True, status="COMPLETE",
    created_local=f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}",
    url_pattern="https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=<SID>&data=tmpf&data=metar&tz=Etc/UTC&format=onlycomma&latlon=no&missing=M&trace=T&direct=no&report_type=<3|4>&sts=2026-05-01T00:00Z&ets=2026-09-30T00:00Z",
    metadata_url_pattern="https://mesonet.agron.iastate.edu/geojson/network/<ST>_ASOS.geojson",
    networks_scanned=sorted({c["network"] for s in sel.values() for c in s["selected"]} | set(json.load(open(ROOT / "selection.json")) and [])) ,
    selection_rule="haversine <= 50 km from stations.json lat/lon; candidates from GA,TX,CO,CA,NY,FL,IL,WA plus adjacent NJ,CT,IN,WI _ASOS networks (AWOS sites are included in these networks, flag is_awos in selection.json); archive must overlap window; market station itself excluded; closest 6 kept",
    window_valid_utc=["2026-05-01T00:00Z", "2026-09-30T00:00Z (exclusive)"],
    window_note="local date 2026-09-29 is truncated at 00Z 09-30 (evening hours missing; Pacific loses 17:00-23:59 PDT). No row dated >= 2026-09-30 was requested.",
    rows_valid_ge_20260930=n_ge_0930,
    rows_total=int(len(d)), rows_cor=int(d["is_cor"].sum()), rows_tmpf_missing=int(d["tmpf"].isna().sum()),
    availability_basis="METAR/SPECI valid time (valid_utc) + >= 10 min feed lag (column available_utc_min = valid + 10 min, DESIGN rule 1 minimum). COR reports flagged is_cor and must be excluded as inputs. IEM may hold late-ingested or corrected values; valid time is the only availability evidence; no per-report receipt time exists. Not 1-minute data.",
    report_type="3 = routine METAR, 4 = SPECI (requested separately, column report_type)",
    t_group="t_group_c parsed from raw METAR remark T-group (tenths C) where present",
    columns=cols,
    files=files,
    coverage_file="coverage_station_day.csv (market x neighbour x market-local date: usable routine/speci rows, has_18_routine)",
    coverage_summary=summary,
    caveat_lot="KORD neighbour LOT is the NWS Chicago office site (Romeoville), in IL_ASOS.",
)
manifest["networks_scanned"] = ["GA_ASOS", "TX_ASOS", "CO_ASOS", "CA_ASOS", "NY_ASOS", "FL_ASOS", "IL_ASOS", "WA_ASOS",
                                "NJ_ASOS", "CT_ASOS", "IN_ASOS", "WI_ASOS"]
json.dump(manifest, open(ROOT / "MANIFEST.json", "w"), indent=1, default=str)
print(json.dumps({k: (v["days_with_ge3_neighbours_ge18_routine"], v["min_neighbours_ge18_on_a_day"], len(v["selected"])) for k, v in summary.items()}))
print("rows", len(d), "cor", int(d["is_cor"].sum()), "missing tmpf", int(d["tmpf"].isna().sum()))
