"""R-T5-INC targeted refuter for T5 (t5-r1): PIT per cycle + increment over captured NBM v2_mean.
Rules registered in C:\\swarm\\registry.jsonl (r-t5-inc-c1, -p1, -d1, -d2) before any score. Development only.
Run: cd C:\\pt\\swarm; <repo python> tools\\research\\model_parity\\r-t5-inc_refute.py
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\pt\swarm")
from tools.research.model_parity import harness as h  # noqa: E402
from tools.research.model_parity import t5_nbh_latest as t5  # noqa: E402

OUT = Path(r"C:\swarm\out\r-t5-inc")
OUT.mkdir(parents=True, exist_ok=True)
if Path(r"C:\swarm\STOP").exists():
    sys.exit("STOP present")
d = h.data()
s, bands = t5.snapshot_frame()
FROM, BEFORE = "from_20260823", "before_20260823"

# ---------------------------------------------------------------- tidy available_utc == ledger LastModified
led = {}
for line in open(r"C:\swarm\data\nbh\ledger.jsonl", encoding="utf-8"):
    r = json.loads(line)
    if r.get("product") == "nbh" and r.get("status") == "ok":
        led[pd.Timestamp(r["date"] + f"T{int(r['cycle']):02d}:00Z")] = pd.Timestamp(r["s3_last_modified"])
tid = pd.read_parquet(t5.NBH, columns=["cycle_utc", "available_utc", "field"], filters=[("field", "==", "TMP")])
tav = tid.groupby("cycle_utc").available_utc.agg(["min", "max"])
mism = 0
for c, row in tav.iterrows():
    L = led[pd.Timestamp(c)]
    if row["min"] != row["max"] or pd.Timestamp(row["min"]) != L:
        mism += 1
tidy_check = {"cycles_in_tidy": int(len(tav)), "ledger_cycles": len(led), "available_utc_vs_ledger_mismatch": mism}
print("tidy vs ledger", tidy_check, flush=True)


# ---------------------------------------------------------------- instrumented T5 (records every cycle used)
def remaining_used(si, t, end):
    ok = np.flatnonzero(si.avail <= t)
    if not len(ok):
        return None
    order = ok[np.argsort(-si.cyc[ok])]
    hours = np.arange(((t // 3600_000_000_000) + 1) * 3600_000_000_000, end + 1, 3600_000_000_000, dtype=np.int64)
    if not len(hours):
        return None
    need = set(hours.tolist())
    vals = {}
    used = []
    for i in order[:6]:
        x = si.c[i]
        hit = False
        for v, tm, sd in zip(x["v"], x["tmp"], x["tsd"]):
            if v in need and v not in vals:
                vals[v] = (tm, sd)
                hit = True
        if hit:
            used.append(i)
        if len(vals) == len(need):
            break
    if len(vals) < len(need):
        return None
    return used


def q(x):
    return [round(float(v), 1) for v in np.quantile(x, [0, .1, .5, .9, 1])]


def pit_audit(idx):
    rows = []
    for st, tt, end in s[["station", "t_ns", "end_ns"]].to_numpy():
        si = idx.get(st)
        if si is None:
            continue
        u = remaining_used(si, int(tt), int(end))
        if u is None:
            continue
        for k, i in enumerate(u):
            rows.append((st, si.c[i]["cycle"].value, si.c[i]["avail"].value, int(tt), k == 0))
    a = pd.DataFrame(rows, columns=["station", "cycle", "avail", "t", "latest"])
    a["use_minus_lm_min"] = (a.t - a.avail) / 6e10
    viol = int((a.t < a.avail).sum())
    a["cyc_hour"] = pd.to_datetime(a.cycle, utc=True).dt.hour
    first = a.groupby(["station", "cycle"]).agg(first_t=("t", "min"), avail=("avail", "first"),
                                                 cyc_hour=("cyc_hour", "first")).reset_index()
    first["first_use_minus_lm_min"] = (first.first_t - first.avail) / 6e10
    dist_first = {int(hh): {"n_station_cycles": int(len(g)), "q0_10_50_90_100_min": q(g.first_use_minus_lm_min)}
                  for hh, g in first.groupby("cyc_hour")}
    dist_latest = {int(hh): {"n_uses": int(len(g)), "q0_10_50_90_100_min": q(g.use_minus_lm_min)}
                   for hh, g in a[a.latest].groupby("cyc_hour")}
    cd = pd.to_datetime(first.cycle, utc=True)
    late = first[(cd.dt.strftime("%Y-%m-%d") == "2026-09-24") & (first.cyc_hour <= 12)]
    late_info = {"station_cycles_0924_00_12Z_used": int(len(late)),
                 "min_first_use_minus_lm_min": float(late.first_use_minus_lm_min.min()) if len(late) else None,
                 "min_first_use_minus_cycle_time_h": float(((late.first_t - late.cycle) / 3.6e12).min())
                 if len(late) else None}
    return {"cycle_uses": int(len(a)), "latest_cycle_uses": int(a.latest.sum()),
            "fallback_cycle_uses": int((~a.latest).sum()),
            "violations_use_before_lastmodified": viol,
            "first_use_minus_lastmodified_by_cycle_hour": dist_first,
            "latest_use_minus_lastmodified_by_cycle_hour": dist_latest, "late_0924": late_info}


# ---------------------------------------------------------------- per-snapshot Brier for a candidate
def snap_brier(cand):
    pc, use, _ = h._candidate_vector(cand, d, False)
    se = (pc - d.y) ** 2
    return np.add.reduceat(se, d.offsets) / d.snaps.n_bands.to_numpy(), use


served_b = np.add.reduceat(d.se_served, d.offsets) / d.snaps.n_bands.to_numpy()
market_b = np.add.reduceat(d.se_market, d.offsets) / d.snaps.n_bands.to_numpy()
G = {"00-05": (0, 5), "06-09": (6, 9), "10-12": (10, 12), "13-16": (13, 16), "17-23": (17, 23),
     "00-16": (0, 16), "all": (0, 23)}
assert (d.snaps.row_key.to_numpy() == s.row_key.to_numpy()).all()
LH = d.snaps.local_hour.to_numpy()
STR = d.snaps.stratum.to_numpy()


def cells_for(group, stratum, cols, mask=None):
    lo, hi = G[group]
    m = (LH >= lo) & (LH <= hi)
    if stratum != "pooled":
        m &= STR == stratum
    if mask is not None:
        m &= mask
    f = pd.DataFrame({"date": d.snaps.date[m].to_numpy(), "market": d.snaps.market[m].to_numpy(),
                      **{k: v[m] for k, v in cols.items()}})
    cells = f.groupby(["date", "market"], sort=True).mean().reset_index()
    idx = np.array([d.key_index[(x, y)] for x, y in zip(cells.date, cells.market)])
    return cells, idx


def paired(a_b, b_b, group, stratum, mask=None):
    cells, idx = cells_for(group, stratum, {"a": a_b, "b": b_b, "s": served_b, "mk": market_b}, mask)
    dl = (cells.a - cells.b).to_numpy()
    iv = h.interval(idx, dl)
    gap = float((cells.s - cells.mk).mean())
    pm = cells.assign(dl=dl).groupby("market").dl.mean()
    return {"estimate": iv["estimate"], "ci95": iv["ci95"], "served_minus_market_gap": gap,
            "markets_negative": int((pm < 0).sum()), "markets_n": int(len(pm)), "market_days": int(len(cells)),
            "per_market": {k: round(float(v), 6) for k, v in pm.items()}}


def lead_conditions(tab, group):
    f, b = tab[(group, FROM)], tab[(group, BEFORE)]
    c = {"interval_excludes_0": f["ci95"][1] < 0,
         "size": f["estimate"] <= -0.0133 or f["estimate"] <= -0.05 * f["served_minus_market_gap"],
         "both_strata_negative": f["estimate"] < 0 and b["estimate"] < 0,
         "ge8_markets_negative": f["markets_negative"] >= 8}
    cls = "LEAD" if all(c.values()) else ("WEAK" if f["estimate"] < 0 else
                                          ("HARM" if f["ci95"][0] > 0 else "NULL"))
    return {"class": cls, **{k: bool(v) for k, v in c.items()}}


def full(a_b, b_b, mask=None):
    tab = {(g, st): paired(a_b, b_b, g, st, mask) for g in G for st in (BEFORE, FROM, "pooled")}
    return tab, {g: lead_conditions(tab, g) for g in G}


def summ(r):
    tl = lambda g, st: h.table_lookup(r, g, st, "all_row")
    return {"classes": {g: r["classes"][g]["class"] for g in r["classes"]},
            "from_all_row": {g: {"estimate": tl(g, FROM)["candidate_minus_served"]["estimate"],
                                 "ci95": tl(g, FROM)["candidate_minus_served"]["ci95"],
                                 "markets_negative": tl(g, FROM)["markets_negative"],
                                 "cand_minus_market": tl(g, FROM)["candidate_minus_market"]["estimate"],
                                 "cand_minus_market_ci95": tl(g, FROM)["candidate_minus_market"]["ci95"],
                                 "served_minus_market": tl(g, FROM)["served_minus_market"]["estimate"]}
                             for g in G},
            "before_all_row": {g: {"estimate": tl(g, BEFORE)["candidate_minus_served"]["estimate"],
                                   "ci95": tl(g, BEFORE)["candidate_minus_served"]["ci95"],
                                   "markets_negative": tl(g, BEFORE)["markets_negative"]} for g in G},
            "candidate_share": r["candidate_share"], "reason_counts": r["reason_counts"]}


res = {"HARNESS_SHA256": h.harness_sha256(), "tidy_check": tidy_check}

# ---------------------------------------------------------------- T5 (as registered) + lag stress
t5b = {}
for lag in (0, 15, 60):
    idx = t5.load_nbh(extra_lag_min=lag)
    if lag == 0:
        res["pit"] = pit_audit(idx)
        print("PIT", res["pit"]["violations_use_before_lastmodified"], res["pit"]["late_0924"], flush=True)
    cand, ages, mus, reasons = t5.build_candidate(idx, s, bands)
    r = h.score(cand, name=f"t5_r1_lag{lag}")
    assert not r["leakage_suspect_groups"]
    h.save(r, OUT)
    t5b[lag] = snap_brier(cand)
    res[f"t5_lag{lag}"] = {"reasons": reasons, **summ(r)}
    print("lag", lag, res[f"t5_lag{lag}"]["classes"], flush=True)

# ---------------------------------------------------------------- c1: v2_mean-only, t5-r1 form
snaps, _ = h.candidate_inputs()
cap = pd.to_datetime(snaps.captured_at_utc, utc=True, format="ISO8601")
v2av = pd.to_datetime(snaps.v2_available_at, utc=True, format="ISO8601", errors="coerce")
ok = (snaps.v2_mean.notna() & snaps.v2_stddev.notna() & v2av.notna() & (v2av <= cap) & snaps.floor.notna())
h.assert_point_in_time(v2av[ok], cap[ok])
offs = d.offsets
nb = snaps.n_bands.to_numpy()
kinds, lows, highs = bands.kind.to_numpy(), bands.low.to_numpy(), bands.high.to_numpy()
p_out = np.full(len(bands), np.nan)
for i in np.flatnonzero(ok.to_numpy()):
    mu = float(snaps.v2_mean.iat[i])
    sig = max(float(snaps.v2_stddev.iat[i]), t5.SIG_MIN)
    B = math.floor(float(snaps.floor.iat[i]) + .5)
    o, n = offs[i], nb[i]
    p = t5.band_probs(kinds[o:o + n], lows[o:o + n], highs[o:o + n], B, mu, sig)
    if p.sum() > 0:
        p_out[o:o + n] = p / p.sum()
cov = ~np.isnan(p_out)
c1 = bands.loc[cov, ["row_key", "band_index"]].assign(p=p_out[cov])
rc1 = h.score(c1, name="r-t5-inc-c1")
assert not rc1["leakage_suspect_groups"]
h.save(rc1, OUT)
c1b, c1use = snap_brier(c1)
res["c1"] = summ(rc1)
print("c1", res["c1"]["classes"], flush=True)

# ---------------------------------------------------------------- paired increments
t5_b, t5use = t5b[0]
tab, cls = full(t5_b, c1b)
res["p1_T5_minus_c1_all_row"] = {"classes": cls, "tables": {f"{g}|{st}": v for (g, st), v in tab.items()}}
tabm, clsm = full(t5_b, c1b, mask=t5use & c1use)
res["p1_T5_minus_c1_both_covered"] = {"label": "selected on availability", "classes": clsm,
                                      "tables": {f"{g}|{st}": v for (g, st), v in tabm.items()}}
c1_on = np.where(t5use, c1b, served_b)
tab2, cls2 = full(t5_b, c1_on)
res["d2_T5_minus_c1_onT5cov"] = {"classes": cls2, "tables": {f"{g}|{st}": v for (g, st), v in tab2.items()}}
share = {}
for g in G:
    for st in (FROM, BEFORE, "pooled"):
        cells, idx = cells_for(g, st, {"t5": t5_b - served_b, "c1": c1b - served_b, "c1on": c1_on - served_b})
        share[f"{g}|{st}"] = {"c1_share_of_t5_gain": h.interval(idx, -cells.c1, -cells.t5),
                              "c1_onT5cov_share": h.interval(idx, -cells.c1on, -cells.t5)}
res["share"] = share
res["coverage"] = {"t5": float(t5use.mean()), "c1": float(c1use.mean()), "both": float((t5use & c1use).mean())}
for g in G:
    print(g, "T5-c1 from", {k: tab[(g, FROM)][k] for k in ("estimate", "ci95", "markets_negative")},
          "before", round(tab[(g, BEFORE)]["estimate"], 5), cls[g]["class"],
          "| share", round(share[f"{g}|{FROM}"]["c1_share_of_t5_gain"]["estimate"], 3), flush=True)
(OUT / "result.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
print("done")
