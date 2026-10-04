# Lowest-temperature desk study — addendum A1 analysis scripts (2026-10-02)

Evidence appendix to the "Addendum A1" section of [the report](agent-report-2026-10-02-lowest-temperature-desk-study.md),
per [pre-registration addendum A1](../research/lowest-temperature-desk-study-preregistration-addendum-2026-10-02.md)
(`d52b5cf9`). Outputs are in
[the A1 results JSON](agent-report-2026-10-02-lowest-temperature-desk-study-addendum-a1-results.json).

## Fetching the Q1 inputs (free, public, no credential)

Run from any shell with `curl` and Python 3.11+, in an empty working directory `iem/`. Every request ends at
2026-09-30T00:00Z, and whole-year responses are cut before anything is stored.

```bash
for st in ATL AUS BKF DAL HOU LAX LGA MIA ORD SEA SFO CYYZ; do
  q="station=$st&year1=2026&month1=7&day1=31&hour1=0&minute1=0&year2=2026&month2=9&day2=30&hour2=0&minute2=0&tz=Etc%2FUTC&format=onlycomma&latlon=no&missing=M&direct=no"
  curl -s -o $st.csv   "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?$q&data=tmpf&data=metar&trace=T&report_type=3&report_type=4"
  curl -s -o r_$st.csv "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?$q&data=tmpf&report_type=3"
done
```

```python
# cli.json and eccc_daily.json, rows dated 2026-09-30 or later dropped at parse
import json, urllib.request, csv, io
CUT = "2026-09-30"
out = {}
for st in "KATL KAUS KBKF KDAL KHOU KLAX KLGA KMIA KORD KSEA KSFO".split():
    d = json.load(urllib.request.urlopen(f"https://mesonet.agron.iastate.edu/json/cli.py?station={st}&year=2026", timeout=60))
    out[st] = [{k: r.get(k) for k in ("valid", "high", "low", "product", "station")} for r in d.get("results", [])
               if "2026-07-31" <= r.get("valid", "9") < CUT]
json.dump(out, open("cli.json", "w"))
u = ("https://climate.weather.gc.ca/climate_data/bulk_data_e.html?format=csv&stationID=51459&Year=2026&Month=9&Day=1"
     "&timeframe=2&submit=Download+Data")
rows = list(csv.DictReader(io.StringIO(urllib.request.urlopen(u, timeout=60).read().decode("utf-8-sig"))))
json.dump([{"date": x["Date/Time"], "min": x["Min Temp (°C)"], "name": x.get("Station Name"), "climate_id": x.get("Climate ID"),
            "minflag": x.get("Min Temp Flag")} for x in rows if "2026-07-31" <= x["Date/Time"] < CUT], open("eccc_daily.json", "w"))
```

KBKF and KDAL return no CLI rows from IEM; `q1.py` then uses the METAR 24-hour minimum group, as pre-registered.

## Running

```powershell
.\venv\Scripts\python.exe q1.py iem
.\venv\Scripts\python.exe q2.py data\forecast_payload_cas\sha256 iem <out-dir>
# q3.py imports lowtemp.py (the parent appendix's script) from the same directory
.\venv\Scripts\python.exe q3.py data\wunderground <out-dir>
```

`q2.py` reads the retained national NBP bulletins in the workstation payload store (about 6 GB, single process,
about 20 s). The workstation heavy-command wrapper accepts only allow-listed `weather.*` modules, so these read-only
scratch scripts ran directly.

## q1.py

```python
"""Addendum A1 Q1: hourly-METAR-rows minimum (H) vs daily summary / CLI minimum (D). Pre-registration d52b5cf9.
usage: python q1.py <iem-dir>   (iem-dir holds <ST>.csv, r_<ST>.csv, cli.json, eccc_daily.json)"""
import csv, json, math, os, re, sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

D0 = sys.argv[1] if len(sys.argv) > 1 else "."
TZ = {"CYYZ": "America/Toronto", "ATL": "America/New_York", "AUS": "America/Chicago", "BKF": "America/Denver",
      "DAL": "America/Chicago", "HOU": "America/Chicago", "LAX": "America/Los_Angeles", "LGA": "America/New_York",
      "MIA": "America/New_York", "ORD": "America/Chicago", "SEA": "America/Los_Angeles", "SFO": "America/Los_Angeles"}
FIRST, LAST = date(2026, 8, 1), date(2026, 9, 28)
CAP = datetime(2026, 9, 30, tzinfo=timezone.utc)
T_RE = re.compile(r" T([01])(\d{3})([01])(\d{3})")
BODY_RE = re.compile(r" (M?\d{2})/(M?\d{2})? ")
G4_RE = re.compile(r"RMK.* 4([01])(\d{3})([01])(\d{3})(?= |$)")


def half_up(x):
    return math.floor(x + 0.5)


def c2f(c):
    return c * 9 / 5 + 32


def row_temp(st, metar, tmpf):
    """Native-unit temperature of one report: T group (tenths C) else body (whole C); F for K stations."""
    m = T_RE.search(metar or "")
    if m:
        c = (-1 if m[1] == "1" else 1) * int(m[2]) / 10
    else:
        b = BODY_RE.search(metar or "")
        if b:
            c = -int(b[1][1:]) if b[1].startswith("M") else int(b[1])
        elif tmpf not in (None, "", "M"):
            return float(tmpf) if st != "CYYZ" else (float(tmpf) - 32) * 5 / 9
        else:
            return None
    return c if st == "CYYZ" else c2f(c)


def lst(loc):
    return loc - (loc.dst() or timedelta(0))


def load(st):
    tz = ZoneInfo(TZ[st])
    routine = set()
    with open(os.path.join(D0, f"r_{st}.csv"), encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            routine.add(r["valid"])
    rows, seen, g4 = [], set(), {}
    with open(os.path.join(D0, f"{st}.csv"), encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            v = r["valid"]
            utc = datetime.strptime(v, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            assert utc < CAP
            if v in seen:
                continue
            seen.add(v)
            t = row_temp(st, r.get("metar"), r.get("tmpf"))
            loc = utc.astimezone(tz)
            g = G4_RE.search(r.get("metar") or "")
            if g and st != "CYYZ":
                ls = lst(loc)
                if ls.hour == 23 or ls.hour == 0:  # 24-h group of the report nearest 00:00 LST
                    mn = (-1 if g[3] == "1" else 1) * int(g[4]) / 10
                    g4[(ls - timedelta(hours=1)).date()] = half_up(c2f(mn))
            if t is not None:
                rows.append((loc, t, v in routine))
    return rows, g4


def daymins(rows, use_lst=False, routine_only=False):
    out = defaultdict(list)
    for loc, t, is_r in rows:
        if routine_only and not is_r:
            continue
        k = (lst(loc) if use_lst else loc).date()
        out[k].append(t)
    return {d: half_up(min(v)) for d, v in out.items()}


def bucket(st, x):
    return x if st == "CYYZ" else x // 2


def compare(st, a, b, days):
    n = val = bkt = lo = hi = 0
    for d in days:
        if d in a and d in b:
            n += 1
            val += a[d] != b[d]
            bkt += bucket(st, a[d]) != bucket(st, b[d])
            lo += b[d] < a[d]
            hi += b[d] > a[d]
    return {"n": n, "value_diff": val, "bucket_diff": bkt, "b_lower": lo, "b_higher": hi,
            "bucket_share": bkt / n if n else None}


def main():
    cli = json.load(open(os.path.join(D0, "cli.json")))
    eccc = json.load(open(os.path.join(D0, "eccc_daily.json")))
    days = [FIRST + timedelta(i) for i in range((LAST - FIRST).days + 1)]
    res = {}
    for st in TZ:
        rows, g4 = load(st)
        H = daymins(rows)
        H_r = daymins(rows, routine_only=True)
        H_lst = daymins(rows, use_lst=True)
        if st == "CYYZ":
            D = {date.fromisoformat(x["date"]): half_up(float(x["min"])) for x in eccc if x["min"] not in ("", None)}
            dsrc = "ECCC daily Min Temp, TORONTO INTL A 6158731 (tenths C rounded half up)"
        else:
            c = {date.fromisoformat(x["valid"]): int(x["low"]) for x in cli.get("K" + st, []) if x.get("low") not in (None, "M")}
            D, dsrc = (c, "NWS CLI (IEM)") if c else (g4, "METAR RMK 24-h minimum group at ~00:00 LST (no CLI)")
        res[st] = {"D_source": dsrc,
                   "days_with_H": sum(d in H for d in days), "days_with_D": sum(d in D for d in days),
                   "H_vs_D": compare(st, H, D, days),
                   "Hroutine_vs_H": compare(st, H, H_r, days),
                   "Hroutine_vs_D": compare(st, H_r, D, days),
                   "H_vs_HLST": compare(st, H, H_lst, days),
                   "HLST_vs_D": compare(st, H_lst, D, days)}
        if st != "CYYZ" and dsrc.startswith("NWS"):
            res[st]["H_vs_G4"] = compare(st, H, g4, days)
            res[st]["G4_vs_D"] = compare(st, g4, D, days)
        res[st]["examples_bucket_diff"] = [(str(d), H[d], D[d]) for d in days if d in H and d in D
                                           and bucket(st, H[d]) != bucket(st, D[d])][:5]
    json.dump(res, open(os.path.join(D0, "q1_results.json"), "w"), indent=1)
    for st, r in res.items():
        print(st, r["D_source"][:12], "HvD", r["H_vs_D"], "| Hr", r["Hroutine_vs_H"]["bucket_diff"],
              "| HvLST", r["H_vs_HLST"]["bucket_diff"], "| LSTvD", r["HLST_vs_D"]["bucket_diff"])


if __name__ == "__main__":
    main()
```

## q2.py

```python
"""Addendum A1 Q2: NBP TXN 12Z-valid minima -> p10..p90 per station-date. Pre-registration d52b5cf9.
usage: python q2.py <payload-cas-sha256-dir> <iem-dir> <out-dir>     (no scoring against markets)"""
import csv, glob, json, math, os, re, statistics, sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

CAS, IEM, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
CAP = datetime(2026, 9, 30, tzinfo=timezone.utc)
STATIONS = ["KATL", "KAUS", "KBKF", "KDAL", "KHOU", "KLAX", "KLGA", "KMIA", "KORD", "KSEA", "KSFO", "CYYZ"]
TZ = {"CYYZ": "America/Toronto", "KATL": "America/New_York", "KAUS": "America/Chicago", "KBKF": "America/Denver",
      "KDAL": "America/Chicago", "KHOU": "America/Chicago", "KLAX": "America/Los_Angeles", "KLGA": "America/New_York",
      "KMIA": "America/New_York", "KORD": "America/Chicago", "KSEA": "America/Los_Angeles", "KSFO": "America/Los_Angeles"}
ROWS = {"TXNP1": "p10", "TXNP2": "p25", "TXNP5": "p50", "TXNP7": "p75", "TXNP9": "p90", "TXNMN": "mean", "TXNSD": "sd"}
HDR = re.compile(r"^ (\w{4})\s+NBM V[\d.]+ NBP GUIDANCE\s+(\d+)/(\d+)/(\d{4})\s+(\d{2})00 UTC")


def parse_block(lines, issue):
    day_line, utc_line = lines[1], lines[2]
    rows = {ln[:7].strip(): ln for ln in lines[3:] if ln[:7].strip() in ROWS}
    # group k (split on '|') -> UTC date, rolling month/year forward from the issue date
    days, cur = [], issue.date()
    for seg in day_line.split("|"):
        m = re.search(r"[A-Z]{3}\s+(\d{2})", seg)
        if not m:
            continue
        dn = int(m[1])
        while cur.day != dn:
            cur += timedelta(days=1)
        days.append(cur)
    cols = []
    for m in re.finditer(r"\d{2}", utc_line[4:]):
        e = m.end() + 4
        grp = utc_line[:e].count("|")
        while grp >= len(days):  # trailing unlabelled group = the following UTC date
            days.append(days[-1] + timedelta(days=1))
        cols.append((datetime.combine(days[grp], datetime.min.time(), timezone.utc) + timedelta(hours=int(m[0])), e))
    out = []
    for valid, e in cols:
        vals = {}
        for code, name in ROWS.items():
            ln = rows.get(code, "")
            s = ln[e - 3:e].strip() if len(ln) >= e else ""
            vals[name] = float(s) if re.fullmatch(r"-?\d+", s) else None
        out.append((valid, vals))
    return out


def main():
    recs, seen = [], set()
    files = [f for f in glob.glob(os.path.join(CAS, "*", "*.blob")) if os.path.getsize(f) > 5_000_000]
    for f in sorted(files):
        with open(f, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().split("\n")
        i = 0
        while i < len(lines):
            m = HDR.match(lines[i])
            if m and m[1] in STATIONS:
                st = m[1]
                issue = datetime(int(m[4]), int(m[2]), int(m[3]), int(m[5]), tzinfo=timezone.utc)
                key = (st, issue)
                if issue < CAP and key not in seen:
                    seen.add(key)
                    cols = parse_block(lines[i:i + 40], issue)
                    for j, (valid, v) in enumerate(cols):
                        if valid.hour != 12 or valid >= CAP:
                            continue  # EF 10k: only 12Z-valid TXN tokens are minima
                        nb = [cols[k][1]["mean"] for k in (j - 1, j + 1) if 0 <= k < len(cols) and cols[k][0].hour == 0]
                        recs.append({"station": st, "valid_date": str(valid.date()), "cycle": issue.strftime("%Y%m%dT%HZ"),
                                     "lead_h": (valid - issue).total_seconds() / 3600, **v,
                                     "below_00z_neighbours": all(v["mean"] is not None and n is not None and v["mean"] < n
                                                                 for n in nb) if nb else None,
                                     "file": os.path.basename(f)[:16]})
            i += 1
    full = [r for r in recs if all(r[k] is not None for k in ("p10", "p25", "p50", "p75", "p90"))]
    with open(os.path.join(OUT, "q2_nbp_txn_minima.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(full[0]))
        w.writeheader(); w.writerows(sorted(full, key=lambda r: (r["station"], r["valid_date"], r["lead_h"])))
    # headline: latest cycle issued before the token valid time
    head = {}
    for r in full:
        k = (r["station"], r["valid_date"])
        if r["lead_h"] > 0 and (k not in head or r["lead_h"] < head[k]["lead_h"]):
            head[k] = r
    # provenance check 3: p50 minus observed IEM min, local 19:00 previous day .. 08:00 (rounded half up)
    obs = {}
    for st in STATIONS:
        f = os.path.join(IEM, (st if st == "CYYZ" else st[1:]) + ".csv")
        tz = ZoneInfo(TZ[st])
        with open(f, encoding="utf-8") as fh:
            obs[st] = [(datetime.strptime(r["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).astimezone(tz), float(r["tmpf"]))
                       for r in csv.DictReader(fh) if r["tmpf"] not in ("M", "")]
    summ = {}
    for st in STATIONS:
        rs = [r for r in full if r["station"] == st]
        if not rs:
            summ[st] = {"rows": 0}; continue
        bands = defaultdict(list)
        for r in rs:
            b = "0-24" if r["lead_h"] <= 24 else "24-48" if r["lead_h"] <= 48 else "48-72" if r["lead_h"] <= 72 else ">72"
            bands[b].append(r["p90"] - r["p10"])
        mono = sum(r["p10"] <= r["p25"] <= r["p50"] <= r["p75"] <= r["p90"] for r in rs)
        nbr = [r["below_00z_neighbours"] for r in rs if r["below_00z_neighbours"] is not None]
        offs = []
        tz = ZoneInfo(TZ[st])
        for (s, d), r in head.items():
            if s != st:
                continue
            dd = date.fromisoformat(d)
            lo = datetime(dd.year, dd.month, dd.day, 8, tzinfo=tz) - timedelta(hours=13)
            hi = datetime(dd.year, dd.month, dd.day, 8, tzinfo=tz)
            w = [t for loc, t in obs[st] if lo <= loc <= hi]
            if len(w) >= 10 and dd >= date(2026, 8, 1):
                offs.append(r["p50"] - math.floor(min(w) + 0.5))
        summ[st] = {"rows": len(rs), "station_dates": len({r["valid_date"] for r in rs}),
                    "cycles": len({r["cycle"] for r in rs}), "valid_first": min(r["valid_date"] for r in rs),
                    "valid_last": max(r["valid_date"] for r in rs),
                    "median_p90_minus_p10_by_lead": {k: statistics.median(v) for k, v in sorted(bands.items())},
                    "monotone_share": mono / len(rs),
                    "below_both_00z_neighbours_share": sum(nbr) / len(nbr) if nbr else None,
                    "provenance_obs_check": {"n": len(offs), "median_p50_minus_obs_min_F": statistics.median(offs) if offs else None,
                                             "abs_le_3F_share": sum(abs(x) <= 3 for x in offs) / len(offs) if offs else None}}
    json.dump({"summary": summ, "headline": {f"{k[0]}|{k[1]}": v for k, v in sorted(head.items())},
               "bulletins": len({r["cycle"] for r in recs}), "cycles_by_hour": {h: len({r["cycle"] for r in recs if r["cycle"].endswith(h + "Z")})
                                                                       for h in ("00", "01", "07", "12", "13", "19")},
               "dropped_incomplete": len(recs) - len(full)},
              open(os.path.join(OUT, "q2_results.json"), "w"), indent=1, default=str)
    for st, s in summ.items():
        print(st, json.dumps(s))


if __name__ == "__main__":
    main()
```

## q3.py

```python
"""Addendum A1 Q3: share of daily lows reached at/after 18:00 local, by month. Pre-registration d52b5cf9.
Reuses load/days/eligible from the parent analysis appendix (lowtemp.py, same directory).
usage: python q3.py <repo>/data/wunderground <out-dir>"""
import json, os, random, sys
from collections import defaultdict
import lowtemp as lt

lt.ROOT = sys.argv[1]
OUT = sys.argv[2]
YRS = list(range(2016, 2026))


def main():
    stations = sorted(lt.TZ)
    # cnt[st][month][year] = [first>=18, last>=18, eligible]
    cnt = {st: defaultdict(lambda: defaultdict(lambda: [0, 0, 0])) for st in stations}
    y26 = {st: defaultdict(lambda: [0, 0, 0]) for st in stations}
    for st in stations:
        dd = lt.days(lt.load(st, range(2016, 2027)), st)
        for d, obs in dd.items():
            if not lt.eligible(obs):
                continue
            obs = sorted(obs)
            m = min(t for _, _, t in obs)
            hs = [h for h, _, t in obs if t == m]
            c = cnt[st][d.month][d.year] if 2016 <= d.year <= 2025 else (y26[st][d.month] if d.year == 2026 else None)
            if c is None:
                continue
            c[0] += hs[0] >= 18; c[1] += hs[-1] >= 18; c[2] += 1

    def share(st, mo, ys, k):
        a = sum(cnt[st][mo][y][k] for y in ys); n = sum(cnt[st][mo][y][2] for y in ys)
        return a / n if n else None

    res = {"per_city": {}, "fleet": {}, "y2026_fleet": {}}
    for st in stations:
        res["per_city"][st] = {mo: {"first_ge18": share(st, mo, YRS, 0), "last_ge18": share(st, mo, YRS, 1),
                                    "n": sum(cnt[st][mo][y][2] for y in YRS)} for mo in range(1, 13)}
    rng = random.Random(20261002)
    for mo in range(1, 13):
        def fleet(ys, k):
            v = [share(st, mo, ys, k) for st in stations]
            v = [x for x in v if x is not None]
            return sum(v) / len(v)
        draws = sorted(fleet([rng.choice(YRS) for _ in YRS], 0) for _ in range(10000))
        res["fleet"][mo] = {"first_ge18": fleet(YRS, 0), "lo": draws[250], "hi": draws[9749], "last_ge18": fleet(YRS, 1),
                            "n": sum(cnt[st][mo][y][2] for st in stations for y in YRS)}
        v = [y26[st][mo] for st in stations if y26[st][mo][2]]
        if v:
            res["y2026_fleet"][mo] = {"first_ge18": sum(a[0] / a[2] for a in v) / len(v), "cities": len(v),
                                      "n": sum(a[2] for a in v)}
    json.dump(res, open(os.path.join(OUT, "q3_results.json"), "w"), indent=1)
    for mo, r in res["fleet"].items():
        print(mo, {k: round(x, 3) if isinstance(x, float) else x for k, x in r.items()},
              {st: round(res["per_city"][st][mo]["first_ge18"], 2) for st in stations})
    print("2026", {m: round(r["first_ge18"], 3) for m, r in res["y2026_fleet"].items()})


if __name__ == "__main__":
    main()
```
