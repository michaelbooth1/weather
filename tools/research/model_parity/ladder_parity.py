"""LADDER: parity ladder from no-source controls (development only).

Rungs (registered in C:\\swarm\\registry.jsonl before scoring): ladder-r0 (served), ladder-r1 (= d-defect-r2
evening lock-in restoration on served final bands), ladder-r1b (inverted-calibration faithful restore + S7 taper
+ S7 gate), ladder-r2 (MG-1 r-t5-inc-c1 base where covered, lock-in on top), ladder-r2b (r2 with r1b fallback).
Paired source increments over rung 2 (ladder-inc-<id>) are computed by ``python -m ... ladder_parity inc``.

Run from C:\\pt\\swarm with the repo interpreter:
    python -m tools.research.model_parity.ladder_parity rungs
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h
from tools.research.model_parity import d_defect_evening_stage as dd
from tools.research.model_parity import t5_nbh_latest as t5

OUT = Path(r"C:\swarm\out\ladder")
OUT.mkdir(parents=True, exist_ok=True)
ART = Path(r"C:\pt\swarm\artifacts\calibration")
FROM, BEFORE = "from_20260823", "before_20260823"
G = {"00-05": (0, 5), "06-09": (6, 9), "10-12": (10, 12), "13-16": (13, 16), "17-23": (17, 23),
     "00-16": (0, 16), "all": (0, 23), "13-14": (13, 14), "15-16": (15, 16)}


HG = ["00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all"]


def stop_check():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")


# ----------------------------------------------------------------------------- strengths (d-defect-r2 exactly)

def strengths(snaps):
    """Return snaps (original order) with B and s (= d-defect-r2 s_r2)."""
    obs = pd.read_parquet(dd.OBS)[["row_key", "cur"]]
    s = snaps.merge(obs, on="row_key", how="left")
    assert len(s) == len(snaps) and (s.row_key.to_numpy() == snaps.row_key.to_numpy()).all()
    F = s["floor"].to_numpy(float)
    s["B"] = dd.rhu(F)
    s["s_heur"] = dd.heuristic_strength(s.local_hour, F, s["cur"].to_numpy(float))
    s["t"] = pd.to_datetime(s.captured_at_utc, utc=True)
    s["_ord"] = np.arange(len(s))
    s = s.sort_values(["market", "date", "t"]).reset_index(drop=True)
    grp = s.groupby(["market", "date"], sort=False)
    s["Bchg"] = grp["B"].transform(lambda x: (x != x.shift()).cumsum())
    first_t = s.groupby(["market", "date", "Bchg"])["t"].transform("min")
    stood = (s["t"] - first_t).dt.total_seconds() / 60.0
    rates = dd.revision_rates()
    rate = np.array([rates.get(m, {}).get(int(hr), np.nan) for m, hr in zip(s.market, s.local_hour)])
    learned = np.where((s.local_hour >= dd.LEARNED_START_H) & (stood >= dd.LEARNED_STAND_MIN) & ~np.isnan(rate),
                       np.clip(1.0 - rate, 0, 1), 0.0)
    s["s"] = np.maximum(s["s_heur"].to_numpy(float), learned)
    s = s.sort_values("_ord").reset_index(drop=True)
    assert (s.row_key.to_numpy() == snaps.row_key.to_numpy()).all()
    return s


def renorm(c):
    tot = c.groupby("row_key").p.transform("sum")
    return c.assign(p=c.p / tot)


def lockin_on(bands, base_p, B, s):
    """d-defect lock-in factor on band probabilities base_p (uniform within band)."""
    fac = dd.band_factor(bands, B, s)
    return base_p * fac


# ----------------------------------------------------------------------------- calibration temperature

def temperatures(snaps):
    T = np.full(len(snaps), np.nan)
    for m in snaps.market.unique():
        cfg = json.loads((ART / f"probability_calibration_{m}.json").read_text())["exact_distribution"]
        assert cfg.get("enabled", True) and float(cfg.get("prior_weight", 0.0)) == 0.0
        base = float(cfg.get("temperature", 1.0))
        byh = cfg.get("temperature_by_hour") or {}
        mm = (snaps.market == m).to_numpy()
        ch = pd.to_numeric(snaps.cutoff_hour, errors="coerce").to_numpy(float)[mm]
        T[mm] = [max(0.05, float(byh[str(int(c))])) if (not np.isnan(c) and str(int(c)) in byh)
                 else max(0.05, base) for c in ch]
    return T


def r1b_probs(bands, snap_idx, B, s, T):
    """Faithful restore+taper+gate emulation. Arrays are per band row (B, s, T broadcast)."""
    P = bands.p_served.to_numpy(float)
    kind = bands.kind.to_numpy()
    low = bands.low.to_numpy(float)
    high = bands.high.to_numpy(float)
    width = np.where(kind == "eq", high - low + 1, 1.0)
    k0 = np.where(kind == "lte", np.minimum(B, high), low)
    k1 = np.where(kind == "eq", low + 1, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        q = np.where(P > 0, (P / width) ** T, 0.0)

    def f(k):
        above = k - B
        return np.where(above <= 0, 1.0, (1.0 - s) + s * dd.HEDGE * dd.BASE ** np.maximum(above - 1, 0))

    m0 = q * f(k0)
    m1 = np.where(np.isnan(k1), 0.0, q * f(np.nan_to_num(k1)))
    nsn = int(snap_idx.max()) + 1
    tot = np.bincount(snap_idx, weights=m0 + m1, minlength=nsn)[snap_idx]
    m0, m1 = m0 / tot, m1 / tot
    Tp = 1.0 + (T - 1.0) * (1.0 - s)
    r0 = np.where(m0 > 0, m0 ** (1.0 / Tp), 0.0)
    r1 = np.where(m1 > 0, m1 ** (1.0 / Tp), 0.0)
    tot = np.bincount(snap_idx, weights=r0 + r1, minlength=nsn)[snap_idx]
    M, R = m0 + m1, (r0 + r1) / tot
    above = np.where(kind == "lte", False, low > B)
    Gt = np.where(above, np.minimum(R, M), R)
    excess = np.bincount(snap_idx, weights=R - Gt, minlength=nsn)[snap_idx]
    contains = np.where(kind == "lte", high >= B, np.where(kind == "gte", low <= B, (low <= B) & (high >= B)))
    # first containing band per snapshot gets the excess
    cont_idx = np.where(contains, np.arange(len(P)), len(P) + 1)
    first = pd.Series(cont_idx).groupby(snap_idx).transform("min").to_numpy()
    gets = (np.arange(len(P)) == first)
    out = Gt + np.where(gets, excess, 0.0)
    tot = np.bincount(snap_idx, weights=out, minlength=nsn)[snap_idx]
    return out / tot


# ----------------------------------------------------------------------------- MG-1 c1 (r-t5-inc-c1 form)

def c1_probs(snaps, bands, offs):
    cap = pd.to_datetime(snaps.captured_at_utc, utc=True, format="ISO8601")
    v2av = pd.to_datetime(snaps.v2_available_at, utc=True, format="ISO8601", errors="coerce")
    ok = (snaps.v2_mean.notna() & snaps.v2_stddev.notna() & v2av.notna() & (v2av <= cap) & snaps.floor.notna())
    h.assert_point_in_time(v2av[ok], cap[ok])
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
    return p_out


# ----------------------------------------------------------------------------- paired statistics

class Paired:
    def __init__(self):
        self.d = h.data()
        d = self.d
        nb = d.snaps.n_bands.to_numpy()
        self.served_b = np.add.reduceat(d.se_served, d.offsets) / nb
        self.market_b = np.add.reduceat(d.se_market, d.offsets) / nb
        self.LH = d.snaps.local_hour.to_numpy()
        self.STR = d.snaps.stratum.to_numpy()

    def snap_brier(self, cand):
        pc, use, _ = h._candidate_vector(cand, self.d, False)
        se = (pc - self.d.y) ** 2
        return np.add.reduceat(se, self.d.offsets) / self.d.snaps.n_bands.to_numpy(), use

    def cells(self, group, stratum, cols, mask=None):
        d = self.d
        lo, hi = G[group]
        m = (self.LH >= lo) & (self.LH <= hi)
        if stratum != "pooled":
            m &= self.STR == stratum
        if mask is not None:
            m &= mask
        f = pd.DataFrame({"date": d.snaps.date[m].to_numpy(), "market": d.snaps.market[m].to_numpy(),
                          **{k: v[m] for k, v in cols.items()}})
        c = f.groupby(["date", "market"], sort=True).mean().reset_index()
        idx = np.array([d.key_index[(x, y)] for x, y in zip(c.date, c.market)])
        return c, idx

    def paired(self, a_b, b_b, group, stratum, mask=None):
        c, idx = self.cells(group, stratum, {"a": a_b, "b": b_b, "s": self.served_b, "mk": self.market_b}, mask)
        dl = (c.a - c.b).to_numpy()
        iv = h.interval(idx, dl)
        pm = c.assign(dl=dl).groupby("market").dl.mean()
        gap = (c.s - c.mk).to_numpy()
        share = h.interval(idx, -dl, gap)
        return {"estimate": iv["estimate"], "ci95": iv["ci95"], "share_of_original_gap": share["estimate"],
                "share_ci95": share["ci95"], "markets_negative": int((pm < 0).sum()),
                "markets_positive": int((pm > 0).sum()), "markets_n": int(len(pm)), "market_days": int(len(c))}


def fmt(x, nd=4):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:+.{nd}f}"


def ci(e, c, nd=4):
    return f"{fmt(e, nd)} [{fmt(c[0], nd)}, {fmt(c[1], nd)}]"


# ----------------------------------------------------------------------------- rungs

def run_rungs():
    stop_check()
    snaps, bands = h.candidate_inputs()
    assert (snaps["date"].astype(str) > "2026-09-29").sum() == 0
    d = h.data()
    offs = d.offsets
    S = strengths(snaps)
    band_snap = d.band_snap
    Bb = S["B"].to_numpy(float)[band_snap]
    sb = S["s"].to_numpy(float)[band_snap]
    T = temperatures(snaps)
    Tb = T[band_snap]
    hasB = ~np.isnan(S["B"].to_numpy(float))
    hasBb = hasB[band_snap]

    cands = {}
    cands["ladder-r0"] = h.served_candidate()
    # r1 = d-defect-r2
    p1 = lockin_on(bands, bands.p_served.to_numpy(float), Bb, sb)
    c = renorm(bands[["row_key", "band_index"]].assign(p=p1))
    cands["ladder-r1"] = c[hasBb]
    # r1b
    sel_snap = hasB & (S["s"].to_numpy(float) > 0)
    selb = sel_snap[band_snap]
    sub = bands[selb].reset_index(drop=True)
    snap_idx = pd.factorize(sub.row_key)[0]
    p1b_sub = r1b_probs(sub, snap_idx, Bb[selb], sb[selb], Tb[selb])
    p1b = bands.p_served.to_numpy(float).copy()
    p1b[selb] = p1b_sub
    cands["ladder-r1b"] = bands.loc[selb, ["row_key", "band_index"]].assign(p=p1b[selb])
    # c1 base
    pc1 = c1_probs(snaps, bands, offs)
    c1cov = ~np.isnan(pc1)
    c1snap = np.zeros(len(snaps), bool)
    c1snap[band_snap[c1cov]] = True
    base = np.where(c1cov, pc1, bands.p_served.to_numpy(float))
    p2c = lockin_on(bands, np.nan_to_num(base), np.nan_to_num(Bb), np.where(hasBb, sb, 0.0))
    c2 = renorm(bands[["row_key", "band_index"]].assign(p=p2c))
    p2c = c2.p.to_numpy()
    p2 = np.where(c1cov, p2c, c.p.to_numpy())
    cands["ladder-r2"] = bands.loc[hasBb, ["row_key", "band_index"]].assign(p=p2[hasBb])
    p2b = np.where(c1cov, p2c, p1b)
    cov2b = c1cov | selb
    cands["ladder-r2b"] = bands.loc[cov2b, ["row_key", "band_index"]].assign(p=p2b[cov2b])
    cands["mg1-c1-alone"] = bands.loc[c1cov, ["row_key", "band_index"]].assign(p=pc1[c1cov])

    P = Paired()
    res, sb_arr = {}, {}
    for rid, cand in cands.items():
        stop_check()
        r = h.score(cand, name=rid.replace("-", "_"))
        if r["leakage_suspect_groups"]:
            Path(r"C:\swarm\STOP").write_text(f"ladder: leakage suspect in {rid}: {r['leakage_suspect_groups']}\n")
            sys.exit("leakage suspect")
        h.save(r, OUT)
        res[rid] = r
        sb_arr[rid], _ = P.snap_brier(cand)
        np.save(OUT / f"snapb_{rid}.npy", sb_arr[rid])
        print(rid, {g: r["classes"][g]["class"] for g in r["classes"]}, flush=True)
    np.save(OUT / "snapb_served.npy", P.served_b)

    # diagnostics: mass above floor band at 17-23
    above = np.where(bands.kind.to_numpy() == "lte", False, bands.low.to_numpy(float) > Bb)
    ev = (S.local_hour.to_numpy() >= 17)[band_snap] & hasBb
    nev = int(((S.local_hour.to_numpy() >= 17) & hasB).sum())
    full = {"ladder-r0": bands.p_served.to_numpy(float), "ladder-r1": c.p.to_numpy(), "ladder-r1b": p1b,
            "ladder-r2": p2, "ladder-r2b": p2b}
    diag = {"mass_above_floor_band_17_23_per_snapshot": {k: float(v[ev & above].sum() / nev) for k, v in full.items()},
            "market_mass_above_17_23": float(d.p_market[ev & above].sum() / nev),
            "realised_above_17_23": float(d.y[ev & above].sum() / nev),
            "c1_coverage_snapshots": float(c1snap.mean()),
            "c1_coverage_by_block": {g: float(c1snap[(P.LH >= lo) & (P.LH <= hi)].mean()) for g, (lo, hi) in G.items() if g in HG},
            "s_pos_share_by_block": {g: float((S["s"].to_numpy()[(P.LH >= lo) & (P.LH <= hi)] > 0).mean())
                                     for g, (lo, hi) in G.items() if g in HG},
            "r1b_snapshots": int(sel_snap.sum()),
            "temperature_17_23_mean": float(np.nanmean(T[P.LH >= 17]))}

    # tables
    order = ["ladder-r0", "ladder-r1", "ladder-r2"]
    prev = {"ladder-r1": "ladder-r0", "ladder-r2": "ladder-r1", "ladder-r1b": "ladder-r0", "ladder-r2b": "ladder-r1b",
            "mg1-c1-alone": "ladder-r0"}
    vs_r1 = {"ladder-r1b": "ladder-r1", "ladder-r2b": "ladder-r2"}
    table = {}
    for rid, r in res.items():
        table[rid] = {}
        for g in HG:
            row = {}
            for st in (FROM, BEFORE):
                t = h.table_lookup(r, g, st, "all_row")
                rat = t["ratio_candidate_to_market"]
                tail = next(x for x in r["tail"] if x["group"] == g and x["stratum"] == st)
                row[st] = {
                    "cand_minus_market": t["candidate_minus_market"]["estimate"],
                    "cand_minus_market_ci95": t["candidate_minus_market"]["ci95"],
                    "served_minus_market": t["served_minus_market"]["estimate"],
                    "ratio": rat["estimate"], "ratio_ci95": rat["ci95"], "ratio_interpretable": rat["interpretable"],
                    "market_brier": t["market"]["estimate"],
                    "cand_minus_served": t["candidate_minus_served"]["estimate"],
                    "cand_minus_served_ci95": t["candidate_minus_served"]["ci95"],
                    "gap_closed": t["gap_closed_share"]["estimate"], "gap_closed_ci95": t["gap_closed_share"]["ci95"],
                    "markets_negative_vs_served": t["markets_negative"],
                    "per_market_delta_vs_served": t["per_market_delta"],
                    "tail_excess_removed": tail.get("share_of_tail_excess_removed", {}).get("estimate"),
                    "tail_excess_removed_ci95": tail.get("share_of_tail_excess_removed", {}).get("ci95"),
                    "tail_band_rows": tail.get("tail_band_rows")}
                if rid in prev:
                    mg = P.paired(sb_arr[rid], sb_arr[prev[rid]], g, st)
                    row[st]["marginal_vs_" + prev[rid]] = mg
                if rid in vs_r1:
                    row[st]["vs_" + vs_r1[rid]] = P.paired(sb_arr[rid], sb_arr[vs_r1[rid]], g, st)
            row["class"] = r["classes"][g]["class"]
            table[rid][g] = row
    # tail definition facts
    tf = h.table_facts()
    out = {"agent": "ladder", "HARNESS_SHA256": h.harness_sha256(), "development": True,
           "rows_after_0929": res["ladder-r0"]["rows_with_target_after_2026_09_29"],
           "candidate_share": {k: v["candidate_share"] for k, v in res.items()},
           "reason_counts": {k: v["reason_counts"] for k, v in res.items()},
           "table": table, "diag": diag, "table_facts_tail": tf.get("tail") if isinstance(tf, dict) else None}
    (OUT / "rungs.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    print(json.dumps(diag, indent=1))
    for rid in list(order) + ["ladder-r1b", "ladder-r2b", "mg1-c1-alone"]:
        print("\n==", rid)
        for g in HG:
            f = table[rid][g][FROM]
            b = table[rid][g][BEFORE]
            mk = [k for k in f if k.startswith("marginal_vs_")]
            mtxt = ""
            if mk:
                m = f[mk[0]]
                mtxt = f" marg {ci(m['estimate'], m['ci95'])} {m['markets_negative']}/{m['markets_n']}"
            print(f"{g}: c-m {ci(f['cand_minus_market'], f['cand_minus_market_ci95'])} (before {fmt(b['cand_minus_market'])})"
                  f" ratio {f['ratio']:.3f}{'' if f['ratio_interpretable'] else '(n.i.)'} closed {fmt(f['gap_closed'], 3)}"
                  f" {ci(f['gap_closed'], f['gap_closed_ci95'], 3)}{mtxt} tail {fmt(f['tail_excess_removed'], 3)} [{table[rid][g]['class']}]")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "rungs"
    if mode == "rungs":
        run_rungs()


# ----------------------------------------------------------------------------- capture source candidates

def capture(modname):
    """Re-run a source hunter's registered main with outputs redirected; store every candidate it scores.

    Nothing is written to the source agent's output directory or the registry: OUT is redirected to
    C:\swarm\out\ladder\cap\<module>, register() is a no-op, h.save is a no-op.
    """
    import importlib
    stop_check()
    capdir = OUT / "cap" / modname
    capdir.mkdir(parents=True, exist_ok=True)
    mod = importlib.import_module(f"tools.research.model_parity.{modname}")
    mod.OUT = capdir
    if hasattr(mod, "register"):
        mod.register = lambda *a, **k: None
    real_score = h.score

    def cap_score(candidate, name="candidate", unfloored=False, where=None, **kw):
        if where is None and not unfloored:
            candidate[["row_key", "band_index", "p"]].to_parquet(capdir / f"{name}.parquet")
        return real_score(candidate, name=name, unfloored=unfloored, where=where, **kw)

    h.score = cap_score
    h.save = lambda res, out_dir: Path(capdir) / f"{res['name']}.score.json"
    if modname == "t11_sounding_bound":
        mod.main_score()
    else:
        mod.main()
    print("captured", sorted(p.name for p in capdir.glob("*.parquet")))


if __name__ == "__main__" and len(sys.argv) > 2 and sys.argv[1] == "capture":
    capture(sys.argv[2])


# ----------------------------------------------------------------------------- increments over rung 2

INC = {"t3": [("t3_baselines", "t3_r3_floor_plus_rise")],
       "t5": [("t5_nbh_latest", "t5_r1_nbh_latest")],
       "t6": [("t6_nbs_latest", "t6_r2_nbs"), ("t6_nbs_latest", "t6_r3_nbs")],
       "t7": [("t7_mos_consensus", "t7_r1"), ("t7_mos_consensus", "t7_r2")],
       "t8": [("t8_hrrr_latest", "t8_r2_hrrr_latest_cal")],
       "t9": [("t9_hrrr_lagged_ensemble", "t9_r1")],
       "t10": [("t10_ecmwf_ifs", "t10_r2_ifs_mix_cal")],
       "t11": [("t11_sounding_bound", "t11_t11_r1")],
       "t12": [("t12_nws_revision", "t12_r1")],
       "t13": [("t13_neighbour_anomaly", "t13_r3_served_nbr_current_tilt"),
               ("t13_neighbour_anomaly", "t13_r2_nbr_runmax_nowcast")],
       "t14": [("t14_cloud_conditioner", "t14_r4_served_cloud_tilt_low")]}


def run_increments():
    stop_check()
    P = Paired()
    r2 = np.load(OUT / "snapb_ladder-r2.npy")
    r1 = np.load(OUT / "snapb_ladder-r1.npy")
    out = {}
    for sid, lst in INC.items():
        for modname, name in lst:
            f = OUT / "cap" / modname / f"{name}.parquet"
            if not f.exists():
                out[f"{sid}:{name}"] = {"status": "NOT_CAPTURED"}
                print(sid, name, "not captured")
                continue
            cand = pd.read_parquet(f)
            cb, use = P.snap_brier(cand)
            rec = {"coverage": float(use.mean()), "vs_served": {}, "minus_r2": {}, "minus_r1": {}}
            for g in G:
                for st in (FROM, BEFORE):
                    rec["vs_served"][f"{g}|{st}"] = P.paired(cb, P.served_b, g, st)
                    rec["minus_r2"][f"{g}|{st}"] = P.paired(cb, r2, g, st)
                    rec["minus_r1"][f"{g}|{st}"] = P.paired(cb, r1, g, st)
            out[f"{sid}:{name}"] = rec
            print(f"\n== ladder-inc-{sid} {name} cov {rec['coverage']:.3f}")
            for g in G:
                a, b = rec["minus_r2"][f"{g}|{FROM}"], rec["minus_r2"][f"{g}|{BEFORE}"]
                v = rec["vs_served"][f"{g}|{FROM}"]
                print(f"{g}: vs served {fmt(v['estimate'])} | minus r2 from {ci(a['estimate'], a['ci95'])} "
                      f"{a['markets_negative']}/{a['markets_n']} before {fmt(b['estimate'])}")
    # residual composition after rung 2 (snapshot-weighted share of positive residual excess, from stratum)
    mk = P.market_b
    comp = {}
    for rid, arr in (("ladder-r0", P.served_b), ("ladder-r1", r1), ("ladder-r2", r2)):
        comp[rid] = {}
        for st in (FROM, BEFORE):
            m = P.STR == st
            tot = float((arr[m] - mk[m]).sum())
            comp[rid][st] = {g: float((arr[m & (P.LH >= lo) & (P.LH <= hi)] - mk[m & (P.LH >= lo) & (P.LH <= hi)]).sum()) / tot
                             for g, (lo, hi) in G.items() if g not in ("all", "13-14", "15-16")}
            comp[rid][st]["total_excess_sum"] = tot
    out["residual_composition_snapshot_weighted"] = comp
    print(json.dumps(comp, indent=1))
    (OUT / "increments.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "inc":
    run_increments()


def run_vs_t3():
    """Registered ladder-inc-vs-t3r3: source - t3-r3 paired (descriptive attribution)."""
    stop_check()
    P = Paired()
    t3b, _ = P.snap_brier(pd.read_parquet(OUT / "cap" / "t3_baselines" / "t3_r3_floor_plus_rise.parquet"))
    out = {}
    for sid, lst in INC.items():
        if sid == "t3":
            continue
        for modname, name in lst:
            cb, _ = P.snap_brier(pd.read_parquet(OUT / "cap" / modname / f"{name}.parquet"))
            out[f"{sid}:{name}"] = {f"{g}|{st}": P.paired(cb, t3b, g, st)
                                    for g in ("13-14", "15-16", "13-16", "17-23") for st in (FROM, BEFORE)}
            print(sid, name, " ".join(f"{g}: {ci(out[f'{sid}:{name}'][f'{g}|{FROM}']['estimate'], out[f'{sid}:{name}'][f'{g}|{FROM}']['ci95'])} "
                                      f"{out[f'{sid}:{name}'][f'{g}|{FROM}']['markets_negative']}/11"
                                      for g in ("13-14", "15-16", "17-23")))
    (OUT / "increments_vs_t3r3.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "vs_t3":
    run_vs_t3()
