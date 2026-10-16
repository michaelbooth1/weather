# Lowest-temperature desk study — analysis script (2026-10-02)

Evidence appendix to [the report](agent-report-2026-10-02-lowest-temperature-desk-study.md). Save the block as `lowtemp.py`
and run it with the project interpreter; it reads only `data/wunderground/<icao>/hourly` and writes `lowtemp_results.json`.
Deviations D1/D2 were added after the pre-registration and are labelled in the code.

```python
"""Lowest-temperature desk study, per pre-registration aa1fbdac. Read-only on data/wunderground."""
import json, glob, os, sys, random
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# usage: python lowtemp.py <repo>/data/wunderground <output-dir>
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "wunderground")
OUT = sys.argv[2] if len(sys.argv) > 2 else "."
TZ = {"cyyz": "America/Toronto", "katl": "America/New_York", "kaus": "America/Chicago", "kbkf": "America/Denver",
      "kdal": "America/Chicago", "khou": "America/Chicago", "klax": "America/Los_Angeles", "klga": "America/New_York",
      "kmia": "America/New_York", "kord": "America/Chicago", "ksea": "America/Los_Angeles", "ksfo": "America/Los_Angeles"}
CITY = {"cyyz": "toronto", "katl": "atlanta", "kaus": "austin", "kbkf": "denver", "kdal": "dallas", "khou": "houston",
        "klax": "los-angeles", "klga": "nyc", "kmia": "miami", "kord": "chicago", "ksea": "seattle", "ksfo": "san-francisco"}


def load(st, years):
    rows, seen = [], set()
    tz = ZoneInfo(TZ[st])
    for y in years:
        for f in sorted(glob.glob(os.path.join(ROOT, st, "hourly", f"year={y}", "month=*", "observations.jsonl"))):
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    r = json.loads(line)
                    t = r.get("temp_native")
                    u = r.get("valid_time_utc")
                    if t is None or u is None or u in seen:
                        continue
                    seen.add(u)
                    utc = datetime.fromisoformat(u)
                    loc = utc.astimezone(tz)
                    rows.append((loc, float(t)))
    return rows


def wrh_keep(st, minute):
    return (56 <= minute or minute <= 4) if st == "cyyz" else (51 <= minute <= 59)


def days(rows, st, lst=False, wrh=False):
    out = defaultdict(list)
    for loc, t in rows:
        if wrh and not wrh_keep(st, loc.minute):
            continue
        if lst and loc.dst():
            loc = loc - loc.dst()  # shift to standard-time clock
        out[loc.date()].append((loc.hour, loc.minute, t))
    return out


def eligible(obs, wrh=False):
    hours = {h for h, _, _ in obs}
    return len(hours) >= 20 and len(hours & set(range(9))) >= 7


def undercut(obs, cut=9, margin=1):
    am = [t for h, _, t in obs if h < cut]
    pm = [t for h, _, t in obs if h >= cut]
    if not am or not pm:
        return None
    return (min(am) - min(pm)) >= margin - 1e-9 if margin > 1 else min(pm) < min(am)


def in_primary(d):
    return 2016 <= d.year <= 2025 and (d.month, d.day) >= (10, 15)


def boot(city_year_counts, cities, years, n=10000, seed=20261002):
    """city_year_counts[c][y] = (undercut, eligible). Equal-weight city mean; resample years jointly."""
    rng = random.Random(seed)
    def stat(ys):
        ps = []
        for c in cities:
            u = sum(city_year_counts[c].get(y, (0, 0))[0] for y in ys)
            e = sum(city_year_counts[c].get(y, (0, 0))[1] for y in ys)
            if e:
                ps.append(u / e)
        return sum(ps) / len(ps) if ps else float("nan")
    pt = stat(years)
    draws = sorted(stat([rng.choice(years) for _ in years]) for _ in range(n))
    return pt, draws[int(0.025 * n)], draws[int(0.975 * n) - 1]


def verdict(lo, hi, thr=0.30):
    return "FALSIFIED" if lo > thr else ("SURVIVES" if hi <= thr else "INCONCLUSIVE")


def run_f1(data, sel, cut=9, margin=1, years=None):
    cyc = {}
    for st, dd in data.items():
        cy = defaultdict(lambda: [0, 0])
        for d, obs in dd.items():
            if not sel(d) or not eligible(obs):
                continue
            u = undercut(obs, cut, margin)
            if u is None:
                continue
            cy[d.year][0] += int(u)
            cy[d.year][1] += 1
        cyc[st] = {y: tuple(v) for y, v in cy.items()}
    res = {}
    for st in data:
        res[st] = boot({st: cyc[st]}, [st], years)
    res["FLEET"] = boot(cyc, list(data), years)
    n = {st: sum(v[1] for v in cyc[st].values()) for st in data}
    return res, n


def main():
    stations = sorted(TZ)
    full = {st: load(st, range(2016, 2027)) for st in stations}
    base = {st: days(full[st], st) for st in stations}
    yrs = list(range(2016, 2026))
    report = {}

    # Primary F1
    res, n = run_f1(base, in_primary, years=yrs)
    report["primary"] = {k: {"p": v[0], "lo": v[1], "hi": v[2], "verdict": verdict(v[1], v[2]), "n": n.get(k)} for k, v in res.items()}

    # Sensitivities
    sens = {}
    full_year = lambda d: 2016 <= d.year <= 2025
    sens["full_year_2016_2025"] = run_f1(base, full_year, years=yrs)
    sens["y2026_jan_aug"] = run_f1(base, lambda d: d.year == 2026, years=[2026])
    sens["cut06"] = run_f1(base, in_primary, cut=6, years=yrs)
    sens["cut12"] = run_f1(base, in_primary, cut=12, years=yrs)
    sens["margin2"] = run_f1(base, in_primary, margin=2, years=yrs)
    wrh = {st: days(full[st], st, wrh=True) for st in stations}
    sens["wrh_hourly_proxy"] = run_f1(wrh, in_primary, years=yrs)
    lst = {st: days(full[st], st, lst=True) for st in stations}
    sens["lst_day"] = run_f1(lst, in_primary, years=yrs)
    report["sensitivities"] = {k: {s: {"p": v[0][s][0], "lo": v[0][s][1], "hi": v[0][s][2], "verdict": verdict(v[0][s][1], v[0][s][2]), "n": v[1].get(s)} for s in v[0]} for k, v in sens.items()}

    # Hour-of-minimum (first/last attainment) and decided-by curve
    hom = {}
    for label, sel in (("primary", in_primary), ("full_year", full_year)):
        for st in stations:
            first = [0] * 24; last = [0] * 24; dec = [0] * 24; ne = 0
            for d, obs in base[st].items():
                if not sel(d) or not eligible(obs):
                    continue
                ne += 1
                obs = sorted(obs)
                m = min(t for _, _, t in obs)
                hs = [h for h, _, t in obs if t == m]
                first[hs[0]] += 1; last[hs[-1]] += 1
                if label == "primary":
                    run = float("inf")
                    byh = defaultdict(list)
                    for h, _, t in obs:
                        byh[h].append(t)
                    for h in range(24):
                        if byh.get(h):
                            run = min(run, min(byh[h]))
                        dec[h] += int(run == m)
            hom.setdefault(label, {})[st] = {"n": ne, "first": first, "last": last, "decided_by_end_of_hour": dec if label == "primary" else None}
    report["hour_of_minimum"] = hom

    # Deviation D1 (added after the pre-registration): crossed year x city bootstrap of fleet F1.
    cyc = {}
    for st in stations:
        cy = defaultdict(lambda: [0, 0])
        for d, obs in base[st].items():
            if in_primary(d) and eligible(obs):
                u = undercut(obs)
                if u is not None:
                    cy[d.year][0] += int(u); cy[d.year][1] += 1
        cyc[st] = cy
    def fleet(cs, ys):
        ps = [sum(cyc[c][y][0] for y in ys) / sum(cyc[c][y][1] for y in ys) for c in cs]
        return sum(ps) / len(ps)
    rng = random.Random(20261002)
    dr = sorted(fleet([rng.choice(stations) for _ in stations], [rng.choice(yrs) for _ in yrs]) for _ in range(10000))
    report["deviation_d1_crossed_fleet"] = {"p": fleet(stations, yrs), "lo": dr[250], "hi": dr[9749]}

    # Deviation D2 (exploratory): undercut-after-09:00 share by calendar month, full year 2016-2025.
    bym = {}
    for st in stations:
        m = defaultdict(lambda: [0, 0])
        for d, obs in base[st].items():
            if 2016 <= d.year <= 2025 and eligible(obs):
                u = undercut(obs)
                if u is not None:
                    m[d.month][0] += int(u); m[d.month][1] += 1
        bym[st] = {k: v[0] / v[1] for k, v in sorted(m.items())}
    report["deviation_d2_by_month"] = bym
    print("D1", report["deviation_d1_crossed_fleet"])
    with open(os.path.join(OUT, "lowtemp_results.json"), "w") as fh:
        json.dump(report, fh, indent=1, default=str)
    print(json.dumps(report["primary"], indent=1))
    for k, v in report["sensitivities"].items():
        print(k, {s: (round(x["p"], 3), x["verdict"]) for s, x in v.items()})


if __name__ == "__main__":
    main()
```
