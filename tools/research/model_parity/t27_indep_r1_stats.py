"""T27-INDEP-R1 part 2/3: comparison with D-DEFECT/LADDER, statistics refutation of rung 1 at 17-23,
and the S7 (calibration taper / gate) attribution diagnostic t27-d-s7. Development only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

ROOT = Path(r"C:\pt\swarm")
sys.path.insert(0, str(ROOT))
from tools.research.model_parity import harness as h  # noqa: E402
from tools.research.model_parity import t27_indep_r1 as T  # noqa: E402

OUT = Path(r"C:\swarm\out\t27")
LAD = Path(r"C:\swarm\out\ladder")
DDF = Path(r"C:\swarm\out\d-defect")
STRATA = ("before_20260823", "from_20260823", "pooled")
key = lambda t: (t["group"], t["stratum"], t["population"])  # noqa: E731


# ------------------------------------------------------------------ 1. comparison
def compare_tables(mine, other):
    M = {key(t): t for t in mine["tables"]}
    O = {key(t): t for t in other["tables"]}
    out = {"max_abs_diff_estimate_or_ci": 0.0, "where": None, "per_block": {}}
    for k, t in O.items():
        if t.get("status") == "NO_DATA":
            continue
        for fld in ("candidate_minus_served", "candidate_minus_market", "gap_closed_share"):
            a = [M[k][fld]["estimate"]] + M[k][fld]["ci95"]
            b = [t[fld]["estimate"]] + t[fld]["ci95"]
            for j, (x, y) in enumerate(zip(a, b)):
                if abs(x - y) > out["max_abs_diff_estimate_or_ci"]:
                    out["max_abs_diff_estimate_or_ci"] = abs(x - y)
                    out["where"] = [*k, fld, ["estimate", "lo", "hi"][j], x, y]
        if k[2] == "all_row":
            out["per_block"]["|".join(k[:2])] = {
                "mine": M[k]["candidate_minus_served"]["estimate"],
                "other": t["candidate_minus_served"]["estimate"],
                "diff": M[k]["candidate_minus_served"]["estimate"] - t["candidate_minus_served"]["estimate"]}
    return out


def snap_diff(a, b):
    d = np.abs(a - b)
    return {"max_abs": float(d.max()), "n_gt_1e-9": int((d > 1e-9).sum())}


# ------------------------------------------------------------------ 2. statistics
def cells(delta_snap, group_lo, group_hi, stratum):
    d = h.data()
    s = d.snaps
    m = s.local_hour.between(group_lo, group_hi).to_numpy().copy()
    if stratum != "pooled":
        m &= (s.stratum == stratum).to_numpy()
    f = pd.DataFrame({"date": s.date[m].to_numpy(), "market": s.market[m].to_numpy(), "d": delta_snap[m]})
    c = f.groupby(["date", "market"], sort=True).d.mean().reset_index()
    c["idx"] = [d.key_index[(a, b)] for a, b in zip(c.date, c.market)]
    c["week"] = pd.to_datetime(c.date).dt.isocalendar().week.astype(int).to_numpy()
    return c


def cluster_boot(c, col, draws=20000, seed=20261004):
    rng = np.random.default_rng(seed)
    units = np.array(sorted(c[col].unique()))
    pos = {u: i for i, u in enumerate(units)}
    u_of = c[col].map(pos).to_numpy()
    counts = rng.multinomial(len(units), np.full(len(units), 1 / len(units)), size=draws)  # draws x units
    w = counts[:, u_of]
    est = (w * c.d.to_numpy()).sum(1) / w.sum(1)
    return est


def summarize_boot(point, boot, z_bonf):
    se = float(np.std(boot, ddof=1))
    return {"estimate": point, "ci95_pct": np.quantile(boot, [.025, .975]).tolist(), "se": se,
            "share_draws_ge_0": float((boot >= 0).mean()),
            "bonferroni_normal": [point - z_bonf * se, point + z_bonf * se],
            "excludes_0_bonferroni": bool(point + z_bonf * se < 0)}


def refute(delta_snap, n_rules):
    alpha = 0.05 / n_rules
    z = float(sps.norm.ppf(1 - alpha / 2))
    alpha7 = 0.05 / (134 * 7)
    z7 = float(sps.norm.ppf(1 - alpha7 / 2))
    res = {"n_rules": n_rules, "alpha_bonf": alpha, "z_bonf": z, "z_bonf_134x7": z7, "blocks": {}}
    for g, lo, hi in (("17-23", 17, 23), ("13-16", 13, 16), ("00-16", 0, 16)):
        for st in STRATA:
            c = cells(delta_snap, lo, hi, st)
            point = float(c.d.mean())
            wi = h.interval(c.idx.to_numpy(), c.d.to_numpy())
            wboot = h._ratio_boot(h.data().w, c.idx.to_numpy(), c.d.to_numpy(), np.ones(len(c)))
            out = {"market_days": len(c), "dates": int(c.date.nunique()), "W": wi,
                   "W_bonf": summarize_boot(point, wboot, z), "W_bonf_134x7": summarize_boot(point, wboot, z7)}
            out["date_only"] = summarize_boot(point, cluster_boot(c, "date"), z)
            out["market_only"] = summarize_boot(point, cluster_boot(c, "market"), z)
            out["market_only_134x7"] = summarize_boot(point, cluster_boot(c, "market"), z7)
            pm = c.groupby("market").d.mean()
            tt = sps.ttest_1samp(pm.to_numpy(), 0.0)
            tcrit = float(sps.t.ppf(1 - alpha / 2, len(pm) - 1))
            out["market_t"] = {"n": int(len(pm)), "mean": float(pm.mean()), "t": float(tt.statistic),
                               "p_two_sided": float(tt.pvalue), "t_crit_bonf": tcrit,
                               "passes_bonf": bool(abs(tt.statistic) > tcrit and pm.mean() < 0),
                               "markets_negative": int((pm < 0).sum()),
                               "sign_test_p_one_sided": float(sps.binomtest(int((pm < 0).sum()), len(pm), 0.5,
                                                                            alternative="greater").pvalue)}
            out["lomo"] = {m: float(c[c.market != m].d.mean()) for m in sorted(c.market.unique())}
            out["lowo"] = {int(wk): float(c[c.week != wk].d.mean()) for wk in sorted(c.week.unique())}
            out["lomo_max"] = max(out["lomo"].values())
            out["lowo_max"] = max(out["lowo"].values())
            pdte = c.groupby("date").d.mean()
            out["dates_negative"] = [int((pdte < 0).sum()), int(len(pdte))]
            res["blocks"][f"{g}|{st}"] = out
    return res


# ------------------------------------------------------------------ 3. S7 diagnostic
def temps():
    out = {}
    for p in (ROOT / "artifacts" / "calibration").glob("probability_calibration_*.json"):
        m = p.stem.replace("probability_calibration_", "")
        a = json.loads(p.read_text(encoding="utf-8"))
        ed = a.get("exact_distribution") or {}
        assert float(ed.get("prior_weight", 0.0)) == 0.0
        out[m] = (float(ed.get("temperature", 1.0)), {k: float(v) for k, v in (ed.get("temperature_by_hour") or {}).items()},
                  bool(ed.get("enabled", True)))
    return out


def lockin_ret(k, B, s):
    above = k - B
    return np.where(above <= 0, 1.0, (1 - s) + s * T.LATE_LOCKIN_HEDGE * T.LATE_LOCKIN_BASE ** np.maximum(above - 1, 0))


def s7_one(P, kind, lo, hi, B, s, Tb):
    """Return band vectors for (r1, untapered, tapered, tapered+gate) for one snapshot."""
    nb = len(P)
    keys, band_of, wts = [], [], []
    for i in range(nb):
        if kind[i] == "lte":
            ks = [hi[i]]
        elif kind[i] == "gte":
            ks = [lo[i]]
        else:
            ks = list(range(int(lo[i]), int(hi[i]) + 1))
        for k in ks:
            keys.append(k)
            band_of.append(i)
            wts.append(P[i] / len(ks))
    k = np.array(keys, float)
    bo = np.array(band_of)
    w = np.array(wts)
    T_ = max(0.05, Tb)
    q = np.where(w > 0, w ** T_, 0.0)
    q /= q.sum()
    m = q * lockin_ret(k, B, s)
    m /= m.sum()

    def cal(x, temp):
        if abs(temp - 1) < 1e-9:
            return x
        y = np.where(x > 0, x ** (1 / temp), 0.0)
        return y / y.sum()

    def bands(x):
        return np.bincount(bo, weights=x, minlength=nb)

    Tp = 1 + (T_ - 1) * (1 - s)
    untap = bands(cal(m, T_))
    tap = bands(cal(m, Tp))
    mb = bands(m)
    above = np.array([(lo[i] > B) if kind[i] != "lte" else False for i in range(nb)])
    contains = np.array([(lo[i] <= B <= hi[i]) if kind[i] == "eq" else (B <= hi[i] if kind[i] == "lte" else B >= lo[i])
                         for i in range(nb)])
    gate = tap.copy()
    excess = np.where(above, np.maximum(gate - mb, 0), 0).sum()
    gate = np.where(above, np.minimum(gate, mb), gate)
    if contains.any():
        gate[np.argmax(contains)] += excess
    gate /= gate.sum()
    r1 = P * np.array([lockin_ret(np.arange(int(lo[i]) if kind[i] != "lte" else int(hi[i]),
                                            (int(hi[i]) if kind[i] != "gte" else int(lo[i])) + 1), B, s).mean()
                       for i in range(nb)])
    r1 = r1 / r1.sum()
    return {"r1": r1, "untapered": untap, "tapered": tap, "tapered_gate": gate, "lockin_only": mb,
            "above": above, "Tp": Tp, "T": T_}


def s7_diag(st):
    snaps, bands = h.candidate_inputs()
    tp = temps()
    n = snaps.n_bands.to_numpy()
    off = np.concatenate([[0], np.cumsum(n)[:-1]])
    kind = bands.kind.to_numpy()
    lo = bands.low.to_numpy()
    hi = bands.high.to_numpy()
    P = bands.p_served.to_numpy(float)
    s_arr = st.s.to_numpy(float)
    B_arr = st.B.to_numpy(float)
    variants = ("r1", "untapered", "tapered", "tapered_gate")
    out = {v: P.copy() for v in variants}
    mass = []
    for i in np.flatnonzero(s_arr > 0):
        a, b = off[i], off[i] + n[i]
        mkt = snaps.market.iat[i]
        base, byh, enabled = tp[mkt]
        ch = snaps.cutoff_hour.iat[i]
        Tb = byh.get(str(int(ch)), base) if ch is not None and str(ch) not in ("", "None", "nan") else base
        if not enabled:
            Tb = 1.0
        r = s7_one(P[a:b], kind[a:b], lo[a:b], hi[a:b], B_arr[i], s_arr[i], Tb)
        for v in variants:
            out[v][a:b] = r[v]
        ab = r["above"]
        mass.append({"pos": int(i), "hour": int(snaps.local_hour.iat[i]), "stratum": snaps.stratum.iat[i], "s": s_arr[i],
                     "T": r["T"], "Tp": r["Tp"], "served": float(P[a:b][ab].sum()),
                     "lockin_only": float(r["lockin_only"][ab].sum()),
                     **{v: float(r[v][ab].sum()) for v in variants}})
    return out, pd.DataFrame(mass)


def atl_example():
    snaps, bands = h.candidate_inputs()
    rk = "atlanta|20260920T235554262432-0400"
    sb = bands[bands.row_key == rk]
    sn = snaps[snaps.row_key == rk].iloc[0]
    base, byh, _ = temps()["atlanta"]
    Tb = byh.get(str(int(sn.cutoff_hour)), base)
    B = float(T.round_half_up(sn.floor))
    rows = []
    for s in (0.0, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 1.0):
        r = s7_one(sb.p_served.to_numpy(float), sb.kind.to_numpy(), sb.low.to_numpy(), sb.high.to_numpy(), B, s, Tb)
        ab = r["above"]
        rows.append({"s": s, "T": Tb, "T_taper": r["Tp"], "above_after_lockin": float(r["lockin_only"][ab].sum()),
                     "above_untapered": float(r["untapered"][ab].sum()), "above_tapered": float(r["tapered"][ab].sum()),
                     "above_tapered_gate": float(r["tapered_gate"][ab].sum()), "above_r1": float(r["r1"][ab].sum())})
    return {"row_key": rk, "cutoff_hour": sn.cutoff_hour, "B": B, "served_above": float(sb.p_served.to_numpy()[
        np.array([(l > B) if k != "lte" else False for k, l in zip(sb.kind, sb.low)])].sum()), "grid": rows}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"HARNESS_SHA256": h.harness_sha256(), "development": True}
    # 1. comparisons
    mine1 = json.load(open(OUT / "t27_indep_r1.score.json"))
    mine2 = json.load(open(OUT / "t27_indep_ladder_r2.score.json"))
    res["compare"] = {
        "r1_vs_d_defect_r2": compare_tables(mine1, json.load(open(DDF / "d_defect_r2.score.json"))),
        "r1_vs_ladder_r1": compare_tables(mine1, json.load(open(LAD / "ladder_r1.score.json"))),
        "r2_vs_ladder_r2": compare_tables(mine2, json.load(open(LAD / "ladder_r2.score.json"))),
    }
    sb1 = np.load(OUT / "snapb_t27_indep_r1.npy")
    sb2 = np.load(OUT / "snapb_t27_indep_ladder_r2.npy")
    res["compare"]["snap_r1_vs_ladder_r1"] = snap_diff(sb1, np.load(LAD / "snapb_ladder-r1.npy"))
    res["compare"]["snap_r2_vs_ladder_r2"] = snap_diff(sb2, np.load(LAD / "snapb_ladder-r2.npy"))
    # reconciliation: adopt D-DEFECT's two conventions -> expect bit-level agreement
    c_alt, _ = T.candidate({"stood_mode": "run"}, lte_mode="feasible")
    sba, _ = T.snapshot_brier(c_alt)
    res["compare"]["snap_r1_dd_conventions_vs_ladder_r1"] = snap_diff(sba, np.load(LAD / "snapb_ladder-r1.npy"))
    c_alt2 = T.candidate_r2({"stood_mode": "run"}, lte_mode="feasible")
    sba2, _ = T.snapshot_brier(c_alt2)
    res["compare"]["snap_r2_dd_conventions_vs_ladder_r2"] = snap_diff(sba2, np.load(LAD / "snapb_ladder-r2.npy"))
    for nm, cc in (("stood_only", T.candidate({"stood_mode": "run"})[0]), ("lte_only", T.candidate(lte_mode="feasible")[0])):
        res["compare"][f"snap_r1_{nm}_vs_ladder_r1"] = snap_diff(T.snapshot_brier(cc)[0], np.load(LAD / "snapb_ladder-r1.npy"))
    # 2. statistics
    d = h.data()
    served = h._snapshot_mean(d, d.se_served)
    n_rules = sum(1 for _ in open(r"C:\swarm\registry.jsonl", encoding="utf-8"))
    res["stats_rung1_t27"] = refute(sb1 - served, n_rules)
    res["stats_rung1_ladder_r1"] = refute(np.load(LAD / "snapb_ladder-r1.npy") - served, n_rules)
    # 3. S7 diagnostic
    st = T.strengths(h.candidate_inputs()[0])
    vec, mass = s7_diag(st)
    snapb = {}
    for v, p in vec.items():
        snapb[v] = h._snapshot_mean(d, (p - d.y) ** 2)
    np.save(OUT / "snapb_s7_tapered_gate.npy", snapb["tapered_gate"])
    s7 = {"mass_above_B_band_mean": {}, "paired": {}}
    for (g, lo, hi) in (("17-23", 17, 23), ("13-16", 13, 16)):
        for stt in STRATA:
            mm = mass[(mass.hour >= lo) & (mass.hour <= hi)]
            if stt != "pooled":
                mm = mm[mm.stratum == stt]
            s7["mass_above_B_band_mean"][f"{g}|{stt}"] = {k: float(mm[k].mean()) for k in
                                                         ("served", "lockin_only", "r1", "untapered", "tapered", "tapered_gate", "s", "T", "Tp")}
            s7["mass_above_B_band_mean"][f"{g}|{stt}"]["n_snapshots_s_pos"] = int(len(mm))
            for a, b in (("tapered", "r1"), ("tapered_gate", "tapered"), ("tapered_gate", "r1"), ("untapered", "tapered"),
                         ("untapered", "r1")):
                c = cells(snapb[a] - snapb[b], lo, hi, stt)
                s7["paired"][f"{g}|{stt}|{a}-{b}"] = h.interval(c.idx.to_numpy(), c.d.to_numpy())
    lr1b = np.load(LAD / "snapb_ladder-r1b.npy")
    s7["tapered_gate_vs_ladder_r1b_snap"] = snap_diff(snapb["tapered_gate"], lr1b)
    c = cells(snapb["tapered_gate"] - lr1b, 17, 23, "from_20260823")
    s7["tapered_gate_minus_ladder_r1b_17_23_from"] = float(c.d.mean())
    # s-strata of the gate effect at 17-23
    m17 = mass[mass.hour >= 17]
    bins = pd.cut(m17.s, [0, 0.5, 0.9, 0.99, 1.0], include_lowest=True)
    s7["by_s_bin_17_23"] = {str(k): {"n": int(len(g)), "share": float(len(g) / len(m17)),
                                     **{v: float(g[v].mean()) for v in ("served", "lockin_only", "r1", "untapered", "tapered", "tapered_gate")}}
                            for k, g in m17.groupby(bins, observed=True)}
    res["s7"] = s7
    res["atl_example"] = atl_example()
    (OUT / "stats_s7.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    print(json.dumps({k: res["compare"][k] for k in res["compare"] if k.startswith("snap")}, indent=1))
    print(json.dumps(res["atl_example"], indent=1, default=float))


if __name__ == "__main__":
    main()
