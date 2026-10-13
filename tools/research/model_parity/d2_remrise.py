"""D2 deep dive on the remaining-rise / decided-band family (development only).

Registered before scoring (C:\\swarm\\registry.jsonl, agent d2): d2-c1, d2-c2, d2-c1s60, d2-r3f, d2-cov, d2-plan1,
d2-pairs. Pre-registered-candidate proposal: t3-r3 unchanged. Everything here is a development read; combined
candidates are POST-HOC sizing only (effect halved), never evidence.

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.d2_remrise
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h
from tools.research.model_parity import ladder_parity as lp
from tools.research.model_parity import t3_baselines as t3

OUT = Path(r"C:\swarm\out\d2")
OUT.mkdir(parents=True, exist_ok=True)
FROM, BEFORE = "from_20260823", "before_20260823"
G = lp.G
SEED, DRAWS, ALPHA = 20261004, 2000, 0.025


def stop_check():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")


def registered_ok():
    rows = [json.loads(x) for x in Path(r"C:\swarm\registry.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    ids = {r["id"] for r in rows if r.get("agent") == "d2"}
    need = {"d2-c1", "d2-c2", "d2-c1s60", "d2-r3f", "d2-cov", "d2-plan1", "d2-pairs"}
    assert need <= ids, need - ids
    return len(rows)


def band_vector(bands, cand):
    """Align a candidate frame to the bands order; NaN where absent."""
    m = bands[["row_key", "band_index"]].merge(cand[["row_key", "band_index", "p"]], on=["row_key", "band_index"],
                                               how="left")
    assert len(m) == len(bands)
    return m.p.to_numpy(float)


def frame(bands, p, cov_b):
    return bands.loc[cov_b, ["row_key", "band_index"]].assign(p=p[cov_b])


def combo(band_snap, nsn, base_p, base_cov_b, t3_p):
    t3cov = ~np.isnan(t3_p)
    prod = np.where(base_cov_b & t3cov, np.nan_to_num(base_p) * np.nan_to_num(t3_p), 0.0)
    tot = np.bincount(band_snap, weights=prod, minlength=nsn)[band_snap]
    use_prod = base_cov_b & t3cov & (tot > 0)
    # snapshot-level: product only when every band row of the snapshot qualifies
    snap_ok = np.bincount(band_snap, weights=(~use_prod).astype(float), minlength=nsn) == 0
    use = snap_ok[band_snap]
    out = np.where(use, prod / np.where(tot > 0, tot, 1.0), base_p)
    return out, base_cov_b, float(snap_ok.mean())


def main():
    stop_check()
    nreg = registered_ok()
    snaps, bands = h.candidate_inputs()
    assert (snaps["date"].astype(str) > "2026-09-29").sum() == 0
    d = h.data()
    band_snap = d.band_snap
    nsn = len(snaps)
    P = lp.Paired()
    served_b = P.served_b

    # ---------------- t3-r3 (registered, unchanged) from the LADDER capture; check reproduction
    t3c = pd.read_parquet(lp.OUT / "cap" / "t3_baselines" / "t3_r3_floor_plus_rise.parquet")
    t3_p = band_vector(bands, t3c)
    t3b, _ = P.snap_brier(t3c)
    chk = P.paired(t3b, served_b, "17-23", FROM)
    assert abs(chk["estimate"] - (-0.021906)) < 2e-6, chk
    print("t3-r3 reproduces 17-23", chk["estimate"], flush=True)

    # ---------------- rungs 1 and 2 (ladder functions, as run_rungs)
    S = lp.strengths(snaps)
    Bb = S["B"].to_numpy(float)[band_snap]
    sb = S["s"].to_numpy(float)[band_snap]
    hasB = ~np.isnan(S["B"].to_numpy(float))
    hasBb = hasB[band_snap]
    p1 = lp.lockin_on(bands, bands.p_served.to_numpy(float), Bb, sb)
    c = lp.renorm(bands[["row_key", "band_index"]].assign(p=p1))
    r1_p = c.p.to_numpy()
    pc1 = lp.c1_probs(snaps, bands, d.offsets)
    c1cov = ~np.isnan(pc1)
    base = np.where(c1cov, pc1, bands.p_served.to_numpy(float))
    p2c = lp.lockin_on(bands, np.nan_to_num(base), np.nan_to_num(Bb), np.where(hasBb, sb, 0.0))
    p2c = lp.renorm(bands[["row_key", "band_index"]].assign(p=p2c)).p.to_numpy()
    r2_p = np.where(c1cov, p2c, r1_p)
    r1b_arr, _ = P.snap_brier(frame(bands, r1_p, hasBb))
    r2b_arr, _ = P.snap_brier(frame(bands, r2_p, hasBb))
    assert np.nanmax(np.abs(r1b_arr - np.load(lp.OUT / "snapb_ladder-r1.npy"))) < 1e-12
    assert np.nanmax(np.abs(r2b_arr - np.load(lp.OUT / "snapb_ladder-r2.npy"))) < 1e-12
    print("rungs reproduce", flush=True)

    cands, snapb = {}, {"served": served_b, "ladder-r1": r1b_arr, "ladder-r2": r2b_arr, "t3-r3": t3b}
    facts = {}

    # ---------------- d2-c1 / d2-c2 (POST-HOC)
    p, cov, share = combo(band_snap, nsn, r2_p, hasBb, t3_p)
    cands["d2-c1"] = frame(bands, p, cov); facts["d2-c1_product_snapshot_share"] = share
    p, cov, share = combo(band_snap, nsn, r1_p, hasBb, t3_p)
    cands["d2-c2"] = frame(bands, p, cov); facts["d2-c2_product_snapshot_share"] = share

    # ---------------- d2-c1s60 (t3-r3s rebuilt)
    stop_check()
    cs, meta60 = t3.build(extra_lag_min=60)
    t3s_p = band_vector(bands, cs["t3-r3"])
    snapb["t3-r3s"], _ = P.snap_brier(cs["t3-r3"])
    p, cov, share = combo(band_snap, nsn, r2_p, hasBb, t3s_p)
    cands["d2-c1s60"] = frame(bands, p, cov); facts["d2-c1s60_product_snapshot_share"] = share

    # ---------------- d2-r3f (serve form: anchor = production floor bucket)
    stop_check()
    m = t3.load_metar()
    dd = t3.daily(m)
    rr = t3.remaining_rise_table(m, dd)
    rise = {}
    for (st, mo, H), g in rr.groupby(["station", "month", "hour"]):
        b0, pp = t3.smooth_pmf(g.rise.to_numpy())
        vals = b0 + np.arange(len(pp))
        neg = vals < 0
        p0 = pp[neg].sum()
        pp = pp[~neg].copy(); b0 = max(b0, 0)
        pp[0] += p0
        rise[(st, mo, H)] = (b0, pp)
    F = snaps["floor"].to_numpy(float)
    month = snaps.date.str[5:7].astype(int).to_numpy()
    st_arr, lh = snaps.station.to_numpy(), snaps.local_hour.to_numpy()
    kinds, lows, highs = bands.kind.to_numpy(), bands.low.to_numpy(), bands.high.to_numpy()
    offs, nb = d.offsets, snaps.n_bands.to_numpy()
    pf = np.full(len(bands), np.nan)
    for i in range(nsn):
        if not np.isfinite(F[i]):
            continue
        key = (st_arr[i], int(month[i]), int(lh[i]))
        if key not in rise:
            continue
        B = math.floor(F[i] + 0.5)
        rb, rp = rise[key]
        o, n = offs[i], nb[i]
        pf[o:o + n] = t3.band_probs(B + rb, rp, list(zip(kinds[o:o + n], lows[o:o + n], highs[o:o + n])))
    covf = ~np.isnan(pf)
    cands["d2-r3f"] = frame(bands, pf, covf)
    facts["d2-r3f_rise_cells"] = len(rise)

    # ---------------- d2-cov20 / d2-cov50
    md = snaps[["market", "date"]].drop_duplicates().sort_values(["market", "date"]).reset_index(drop=True)
    perm = np.random.default_rng(SEED).permutation(len(md))
    key_snap = snaps.market + "|" + snaps.date
    rk2key = dict(zip(snaps.row_key, key_snap))
    for frac in (20, 50):
        drop = set((md.market + "|" + md.date).to_numpy()[perm[: int(round(len(md) * frac / 100))]])
        keep = ~t3c.row_key.map(rk2key).isin(drop)
        cands[f"d2-cov{frac}"] = t3c[keep.to_numpy()]

    # ---------------- score
    res = {}
    for rid, cand in cands.items():
        stop_check()
        r = h.score(cand, name=rid.replace("-", "_"))
        assert r["rows_with_target_after_2026_09_29"] == 0
        if r["leakage_suspect_groups"]:
            Path(r"C:\swarm\STOP").write_text(f"d2: leakage suspect in {rid}: {r['leakage_suspect_groups']}\n")
            sys.exit("leakage suspect")
        h.save(r, OUT)
        (OUT / f"{rid}.md").write_text(h.markdown(r), encoding="utf-8")
        res[rid] = r
        snapb[rid], _ = P.snap_brier(cand)
        print(rid, {g: r["classes"][g]["class"] for g in r["classes"]}, flush=True)

    # ---------------- tables
    def tab(r, g, st):
        t = h.table_lookup(r, g, st, "all_row")
        tail = next((x for x in r["tail"] if x["group"] == g and x["stratum"] == st), {})
        return {"cand_minus_served": t["candidate_minus_served"]["estimate"],
                "cand_minus_served_ci95": t["candidate_minus_served"]["ci95"],
                "cand_minus_market": t["candidate_minus_market"]["estimate"],
                "cand_minus_market_ci95": t["candidate_minus_market"]["ci95"],
                "ratio": t["ratio_candidate_to_market"]["estimate"],
                "ratio_interpretable": t["ratio_candidate_to_market"]["interpretable"],
                "gap_closed": t["gap_closed_share"]["estimate"], "markets_negative": t["markets_negative"],
                "tail_removed": (tail.get("share_of_tail_excess_removed") or {}).get("estimate")}

    HG = ["00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all"]
    tables = {rid: {g: {st: tab(r, g, st) for st in (FROM, BEFORE)} | {"class": r["classes"][g]["class"]}
                    for g in HG} for rid, r in res.items()}
    pairs = {}
    comps = {"d2-c1": ["served", "ladder-r2", "t3-r3"], "d2-c2": ["served", "ladder-r1", "t3-r3"],
             "d2-c1s60": ["served", "d2-c1", "ladder-r2"], "d2-r3f": ["served", "t3-r3", "ladder-r1"],
             "d2-cov20": ["served", "t3-r3"], "d2-cov50": ["served", "t3-r3"],
             "t3-r3": ["served", "ladder-r1", "ladder-r2"], "t3-r3s": ["served", "t3-r3"]}
    for a, lst in comps.items():
        for b in lst:
            pairs[f"{a} - {b}"] = {f"{g}|{st}": P.paired(snapb[a], snapb[b], g, st)
                                   for g in G for st in (FROM, BEFORE)}

    # ---------------- d2-plan1 (BEFORE stratum only)
    LH, STR = P.LH, P.STR

    def cells(arr, lo, hi):
        mk = (LH >= lo) & (LH <= hi) & (STR == BEFORE)
        f = pd.DataFrame({"date": d.snaps.date[mk].to_numpy(), "market": d.snaps.market[mk].to_numpy(),
                          "delta": (arr - served_b)[mk]})
        return f.groupby(["date", "market"], sort=True).delta.mean().reset_index()

    def plan(cc, effects, ns):
        dates = sorted(cc.date.unique()); mkts = sorted(cc.market.unique())
        di = cc.date.map({x: k for k, x in enumerate(dates)}).to_numpy()
        mi = cc.market.map({x: k for k, x in enumerate(mkts)}).to_numpy()
        y = cc.delta.to_numpy(); ybar = y.mean()
        idx = np.array([d.key_index[(a, b)] for a, b in zip(cc.date, cc.market)])
        hv = h.interval(idx, y, effect=-effects[0])
        rng = np.random.default_rng(SEED)
        out = {"point_before": float(ybar), "dates": len(dates), "markets": len(mkts),
               "harness_crossed_before": {k: hv[k] for k in ("estimate", "ci95", "mde80", "power")},
               "per_market_mean": cc.groupby("market").delta.mean().round(5).to_dict(), "fixed": {}, "crossed": {}}
        for mode in ("fixed", "crossed"):
            for n in ns + ([None] if mode == "crossed" else []):
                e = np.empty(DRAWS); pm = np.empty((DRAWS, len(mkts)))
                for b in range(DRAWS):
                    wd = np.ones(len(dates)) if n is None else rng.multinomial(n, np.full(len(dates), 1 / len(dates)))
                    wm = np.ones(len(mkts)) if mode == "fixed" else rng.multinomial(len(mkts), np.full(len(mkts), 1 / len(mkts)))
                    w = (wd[di] * wm[mi]).astype(float)
                    e[b] = (w * y).sum() / w.sum() if w.sum() > 0 else np.nan
                    num = np.bincount(mi, w * y, len(mkts)); den = np.bincount(mi, w, len(mkts))
                    pm[b] = np.divide(num, den, out=np.full(len(mkts), np.nan), where=den > 0)
                ok = np.isfinite(e); e = e[ok]; pm = pm[ok]
                err = e - e.mean(); q = np.quantile(err, ALPHA)
                rec = {"mde80": float(np.quantile(err, 0.8) - q), "sd": float(err.std())}
                for ef in effects:
                    sig = err - ef < q
                    rec[f"power@{ef:.5f}"] = float(sig.mean())
                    if mode == "fixed":
                        mneg = (np.nan_to_num(pm - ybar - ef, nan=1.0) < 0).sum(axis=1) >= 8
                        rec[f"joint8of11@{ef:.5f}"] = float((sig & mneg).mean())
                out[mode]["inf" if n is None else str(n)] = rec
        return out

    NS = [20, 30, 45, 60, 90, 120, 180]
    power = {}
    for g in ("13-16", "00-16", "17-23", "15-16"):
        lo, hi = G[g]
        cc = cells(t3b, lo, hi)
        dev = -float(cc.delta.mean())
        power[g] = plan(cc, [dev / 2, dev], NS)
        power[g]["effects"] = {"half_before": dev / 2, "full_before": dev}
        print("plan", g, json.dumps({k: power[g][k] for k in ("point_before", "effects")}), flush=True)

    # ---------------- facts for the serve form
    t3cov_snap = np.zeros(nsn, bool); t3cov_snap[band_snap[~np.isnan(t3_p)]] = True
    facts["t3_coverage_snapshots"] = float(t3cov_snap.mean())
    facts["r3f_coverage_snapshots"] = float(np.bincount(band_snap, weights=covf.astype(float), minlength=nsn).astype(bool).mean())
    facts["candidate_share"] = {k: v["candidate_share"] for k, v in res.items()}
    facts["reason_counts"] = {k: v["reason_counts"] for k, v in res.items()}
    out = {"agent": "d2", "HARNESS_SHA256": h.harness_sha256(), "development": True, "registry_lines_at_run": nreg,
           "rows_after_0929": 0, "tables": tables, "pairs": pairs, "power": power, "facts": facts}
    (OUT / "d2_run.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")

    # ---------------- compact print
    def f4(x):
        return "n/a" if x is None else f"{x:+.4f}"
    for rid in res:
        print("\n==", rid)
        for g in HG:
            a = tables[rid][g][FROM]; b = tables[rid][g][BEFORE]
            print(f"{g}: c-s {f4(a['cand_minus_served'])} [{f4(a['cand_minus_served_ci95'][0])},{f4(a['cand_minus_served_ci95'][1])}]"
                  f" b {f4(b['cand_minus_served'])} c-m {f4(a['cand_minus_market'])} mk- {a['markets_negative']}"
                  f" closed {a['gap_closed']:.3f} tail {a['tail_removed']} [{tables[rid][g]['class']}]")
    for k, v in pairs.items():
        print("\n--", k)
        for g in ("00-16", "13-14", "15-16", "13-16", "17-23", "all"):
            a = v[f"{g}|{FROM}"]; b = v[f"{g}|{BEFORE}"]
            print(f"{g}: {f4(a['estimate'])} [{f4(a['ci95'][0])},{f4(a['ci95'][1])}] {a['markets_negative']}/{a['markets_n']}"
                  f" before {f4(b['estimate'])}")
    print(json.dumps(facts, indent=1, default=float)[:3000])


if __name__ == "__main__":
    main()
