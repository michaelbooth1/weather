"""Row 28 outcome-blind integrity-cap input counts (v3: r3 deciding tier = seasons ending 2021..2025 only).

Reads ONLY `local_date` and `row_count` from WU daily_summary.csv (no temperature column is parsed or kept),
the NBP 07Z S3 listing TSV (date, LastModified, size) and the L47b count.json (counts only).
Deciding tier: 12-17..05-31 of 2021-2025 plus 2026-01-01..2026-05-26. Nothing on or after 2026-05-27 is read
(rows with later dates are skipped before any field other than local_date is touched).
Usage: python -I cap_counts_v2.py <wunderground_root> <nbp_listing_tsv> <l47b_count_json> <out_json>
"""
import csv, json, sys
from collections import defaultdict
from datetime import date, timedelta, datetime

WU, NBP_TSV, L47B, OUT = sys.argv[1:5]
STATIONS = {"katl": "atlanta", "kaus": "austin", "kbkf": "denver", "kdal": "dallas", "khou": "houston",
            "klax": "los-angeles", "klga": "nyc", "kmia": "miami", "kord": "chicago", "ksea": "seattle",
            "ksfo": "san-francisco"}
MIN_ROWS = 18
HARD_END = date(2026, 5, 26)


def deciding(d):
    # r3 (master ruling 11-02): 2026 season (2025-12-17..2026-05-26) is descriptive, not deciding.
    if 2021 <= d.year <= 2025:
        return (d.month <= 5) or (d.month == 12 and d.day >= 17 and d.year <= 2024)
    return False


def spring_dst(y):  # US: second Sunday of March
    d = date(y, 3, 8)
    while d.weekday() != 6:
        d += timedelta(days=1)
    return d


dates = []
d = date(2021, 1, 1)
while d <= HARD_END:
    if deciding(d):
        dates.append(d)
    d += timedelta(days=1)
dst = {spring_dst(y) for y in range(2021, 2026)}

res = {"deciding_dates": len(dates), "dst_dates": sorted(str(x) for x in dst), "markets": {}}
for st, mk in STATIONS.items():
    rc = {}
    with open(f"{WU}/{st}/daily/daily_summary.csv", newline="", encoding="utf-8") as fh:
        rd = csv.reader(fh)
        hdr = next(rd)
        i_d, i_n = hdr.index("local_date"), hdr.index("row_count")
        for row in rd:
            try:
                dd = date.fromisoformat(row[i_d])
            except ValueError:
                continue
            if dd > HARD_END or not deciding(dd):
                continue
            rc[dd] = int(float(row[i_n] or 0))
    partial = [x for x in dates if x in rc and rc[x] < MIN_ROWS]
    missing = [x for x in dates if x not in rc]
    res["markets"][mk] = {
        "partial": len(partial), "missing": len(missing),
        "partial_on_dst": sum(1 for x in partial if x in dst),
        "dst_dates_partial": sorted(str(x) for x in partial if x in dst),
        "non_dst_partial_by_year": {y: sum(1 for x in partial if x.year == y and x not in dst) for y in range(2021, 2027)},
        "missing_by_year": {y: sum(1 for x in missing if x.year == y) for y in range(2021, 2027)},
    }

# NBP 07Z: 2021-25 from the S3 listing; 2026 from L47b count.json (nbp_available per market-month)
nbp = {"absent": [], "late_ge_12z": [], "late_ge_15z": []}
with open(NBP_TSV, encoding="utf-8") as fh:
    for line in fh:
        p = line.rstrip("\n").split("\t")
        dd = date.fromisoformat(p[0])
        if not deciding(dd):
            continue
        if p[1] == "ABSENT":
            nbp["absent"].append(p[0]); continue
        lm = datetime.fromisoformat(p[1].replace("Z", "+00:00"))
        lag_h = (lm - datetime(dd.year, dd.month, dd.day, 7, tzinfo=lm.tzinfo)).total_seconds() / 3600
        if lag_h >= 5: nbp["late_ge_12z"].append(p[0])
        if lag_h >= 8: nbp["late_ge_15z"].append(p[0])
cnt = json.load(open(L47B, encoding="utf-8"))["cells"]
n26 = defaultdict(lambda: [0, 0])
for k, v in cnt.items():
    mk, ym, ver = k.split("|")
    n26[mk][0] += v["target_dates"]; n26[mk][1] += v["nbp_available"]
nbp["2026_target_vs_available_by_market"] = dict(n26)
res["nbp07"] = nbp

us10 = [m for m in STATIONS.values() if m != "denver"]
n_md10 = len(dates) * 10
bad10 = sum(res["markets"][m]["partial"] + res["markets"][m]["missing"] for m in us10)
dst10 = sum(res["markets"][m]["partial_on_dst"] for m in us10)
res["summary_us10"] = {"market_dates": n_md10, "partial_plus_missing": bad10, "of_which_dst_day": dst10,
                       "share_pct_incl_dst": round(100.0 * bad10 / n_md10, 3),
                       "share_pct_after_dst_rule": round(100.0 * (bad10 - dst10) / (n_md10 - 10 * len(dst)), 3)}
den = res["markets"]["denver"]
res["summary_denver"] = {"market_dates": len(dates), "partial_plus_missing": den["partial"] + den["missing"]}
json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1, sort_keys=True)
print(json.dumps({k: res[k] for k in ("deciding_dates", "summary_us10", "summary_denver")}, indent=1))
print("nbp absent:", nbp["absent"], "late>=12Z:", len(nbp["late_ge_12z"]), "late>=15Z:", len(nbp["late_ge_15z"]))
print("2026 nbp:", dict(n26))
for m, v in res["markets"].items():
    print(m, v["partial"], v["missing"], "dst", v["partial_on_dst"], "nondst", v["non_dst_partial_by_year"], "miss", v["missing_by_year"])
