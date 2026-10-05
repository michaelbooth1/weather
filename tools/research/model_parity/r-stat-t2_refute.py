"""R-STAT-T2: statistics refuter for T2 (t2-r1 remaining-rise nowcast), model-parity swarm v2.

Development only. Regenerates the t2-r1 candidate with the hunter's own functions (same rule, no
new rule registered), then scores it INDEPENDENTLY of harness.score: own floor mask, own Brier,
own market-day cells, intervals straight from C:\\swarm\\cache\\W.npy (sha256-checked) plus fresh
crossed / date-cluster / market-cluster bootstraps, jackknives (market, ISO week, date),
multiplicity from C:\\swarm\\registry.jsonl, and a coverage-vs-outcome association test.

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.r-stat-t2_refute
(the module name has a dash, so it is run as a path: python tools\\research\\model_parity\\r-stat-t2_refute.py)
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\pt\swarm")
from tools.research.model_parity import harness as h  # noqa: E402  (inputs + hunter numbers only)
from tools.research.model_parity import t2_remaining_rise as t2  # noqa: E402

OUT = Path(r"C:\swarm\out\refute-stat-t2")
OUT.mkdir(parents=True, exist_ok=True)
CACHE = Path(r"C:\swarm\cache")
BLOCKS = {"00-05": (0, 5), "06-09": (6, 9), "10-12": (10, 12), "13-16": (13, 16), "17-23": (17, 23),
          "00-16": (0, 16), "all": (0, 23)}
FROM, BEFORE = "from_20260823", "before_20260823"
LEAD_LINE, GAP_SHARE, MIN_MKTS = -0.0133, 0.05, 8


def sha(path):
    d = hashlib.sha256()
    with open(path, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            d.update(ch)
    return d.hexdigest()


# ------------------------------------------------------------------ 1. regenerate the t2-r1 candidate
def regenerate_r1():
    cache_p = OUT / "t2_r1_p_unfloored.npy"
    snaps, bands = h.candidate_inputs()
    if cache_p.exists():
        return snaps, bands, np.load(cache_p)
    assert t2.LAG_MIN == 10
    stations, tables = {}, {}
    for st in t2.TZ:
        m = t2.load_station(st)
        stations[st] = m
        tables[st] = t2.cell_dists(t2.history_table(st, m))
    snaps = snaps.copy()
    snaps["tmonth"] = snaps.date.str[5:7].astype(int)
    feats = []
    for st, g in snaps.groupby("station"):
        ok, M, T, db, sb, av = t2.state(stations[st], g.captured_at_utc, g.date.to_numpy())
        cap = t2.us(g.captured_at_utc)
        assert (av[ok] <= cap[ok]).all()
        feats.append(pd.DataFrame({"ok": ok, "M": M, "T": T, "db": db, "sb": sb, "av": av}, index=g.index))
    F = pd.concat(feats).loc[snaps.index]
    snaps = snaps.join(F)
    bands2 = bands.merge(snaps[["row_key", "station", "tmonth", "local_hour", "ok", "M", "db", "sb"]], on="row_key")
    assert (bands2.row_key.to_numpy() == bands.row_key.to_numpy()).all()  # order preserved
    p1 = np.full(len(bands2), np.nan)
    for rk, g in bands2.groupby("row_key", sort=False):
        r0 = g.iloc[0]
        if not r0.ok:
            continue
        pR, lvl = t2.lookup(tables[r0.station], int(r0.tmonth), int(r0.local_hour), int(r0.db), int(r0.sb))
        if pR is None:
            continue
        p1[g.index] = t2.band_probs(pR, int(r0.M), g.kind.to_numpy(), g.low.to_numpy(), g.high.to_numpy())
    np.save(cache_p, p1)
    snaps[["row_key", "ok", "M", "T", "db", "sb"]].to_parquet(OUT / "t2_state.parquet", index=False)
    return snaps, bands, p1


# ------------------------------------------------------------------ 2. independent scoring
def independent_score(p1):
    """Own floor mask + renormalisation + Brier; returns per-snapshot frame."""
    full_b = pd.read_parquet(CACHE / "bands.parquet")
    full_s = pd.read_parquet(CACHE / "snapshots.parquet")
    n = full_s.n_bands.to_numpy()
    off = np.concatenate([[0], np.cumsum(n)[:-1]])
    assert (full_b.row_key.to_numpy()[off] == full_s.row_key.to_numpy()).all()
    snap_of_band = np.repeat(np.arange(len(full_s)), n)
    y = full_b.is_winner.to_numpy(float)
    ps, pm = full_b.p_served.to_numpy(float), full_b.p_market_yes.to_numpy(float)
    given = ~np.isnan(p1)
    n_given = np.bincount(snap_of_band, weights=given, minlength=len(full_s))
    assert ((n_given == 0) | (n_given == n)).all(), "partial snapshots"
    provided = n_given == n
    has_floor = full_s.floor.notna().to_numpy()
    pc = np.where(given, p1, 0.0)
    pc[full_b.floor_impossible.to_numpy(bool)] = 0.0           # rule-4 mask (81a definition, own code)
    tot = np.bincount(snap_of_band, weights=pc, minlength=len(full_s))
    use = provided & has_floor & (tot > 0)
    reason = np.where(~provided, "absent", np.where(~has_floor, "missing_floor",
                      np.where(tot > 0, "candidate", "zero_mass_after_floor")))
    use_b = use[snap_of_band]
    pc = np.where(use_b, pc / np.where(tot > 0, tot, 1.0)[snap_of_band], ps)
    # own Brier: mean over bands of squared error
    def smean(v):
        return np.add.reduceat(v, off) / n
    f = full_s[["row_key", "date", "market", "stratum", "local_hour", "station", "winner",
                "settlement_high", "floor", "floor_bucket", "high_so_far"]].copy()
    f["served"] = smean((ps - y) ** 2)
    f["mkt"] = smean((pm - y) ** 2)
    f["cand"] = smean((pc - y) ** 2)
    f["use"] = use
    f["reason"] = reason
    # rise still to come after the snapshot's captured floor (outcome variable for selection test)
    f["remaining_rise_vs_floor"] = f.settlement_high - f.floor_bucket
    return f


def cells_for(f, block, stratum):
    lo, hi = BLOCKS[block]
    m = f.local_hour.between(lo, hi)
    if stratum != "pooled":
        m &= f.stratum == stratum
    c = f[m].groupby(["date", "market"], sort=True)[["served", "mkt", "cand", "use"]].mean().reset_index()
    c["delta"] = c.cand - c.served
    c["gap"] = c.served - c.mkt
    return c


def wload():
    W = np.load(CACHE / "W.npy")
    keys = [tuple(k) for k in json.loads((CACHE / "W_keys.json").read_text())]
    rec = json.loads((CACHE / "cache_receipt.json").read_text())
    assert sha(CACHE / "W.npy") == rec["W"]["sha256"] == rec["files"]["W.npy"]
    return W, {k: i for i, k in enumerate(keys)}


def w_ci(W, kidx, c, col="delta", q=(0.025, 0.975)):
    idx = np.array([kidx[(d, m)] for d, m in zip(c.date, c.market)])
    a = c[col].to_numpy(float)
    sub = W[:, idx]
    boot = (sub @ a) / sub.sum(1)
    return float(a.mean()), np.quantile(boot, q).tolist(), boot


def fresh_crossed(c, draws, seed, col="delta"):
    _, di = np.unique(c.date, return_inverse=True)
    _, mi = np.unique(c.market, return_inverse=True)
    d, m = di.max() + 1, mi.max() + 1
    rng = np.random.default_rng(seed)
    wd = rng.multinomial(d, np.full(d, 1 / d), size=draws)
    wm = rng.multinomial(m, np.full(m, 1 / m), size=draws)
    w = wd[:, di] * wm[:, mi]
    a = c[col].to_numpy(float)
    return (w @ a) / w.sum(1)


def cluster_boot(c, by, draws, seed, col="delta"):
    _, ci = np.unique(c[by], return_inverse=True)
    k = ci.max() + 1
    rng = np.random.default_rng(seed)
    w = rng.multinomial(k, np.full(k, 1 / k), size=draws)[:, ci]
    a = c[col].to_numpy(float)
    return (w @ a) / w.sum(1)


def q(b, lo=0.025, hi=0.975):
    return np.quantile(b, [lo, hi]).tolist()


def lead_check(est, hi, before_est, gap, mkts_neg):
    return {"interval_excludes_0": bool(hi < 0),
            "size": bool(est <= LEAD_LINE or est <= -GAP_SHARE * gap),
            "both_strata_neg": bool(est < 0 and before_est < 0),
            "markets_neg_ge_8": bool(mkts_neg >= MIN_MKTS),
            "LEAD": bool(hi < 0 and (est <= LEAD_LINE or est <= -GAP_SHARE * gap) and est < 0
                         and before_est < 0 and mkts_neg >= MIN_MKTS)}


def main():
    report = {"agent": "r-stat-t2", "development": True, "HARNESS_SHA256": h.harness_sha256(),
              "candidate_code_sha256": sha(Path(t2.__file__))}
    snaps, bands, p1 = regenerate_r1()
    f = independent_score(p1)
    assert (f.date <= "2026-09-29").all()
    report["rows_after_20260929"] = int((f.date > "2026-09-29").sum())
    report["coverage"] = {"candidate_share": float(f.use.mean()),
                          "reasons": f.reason.value_counts().to_dict()}
    W, kidx = wload()
    report["W"] = {"shape": list(W.shape), "row_weight_sum_mean": float(W.sum(1).mean()),
                   "col_mean_weight": float(W.mean()), "zero_share": float((W == 0).mean())}

    hunter = json.loads(Path(r"C:\swarm\out\t2\t2_r1_nowcast.score.json").read_text())
    def hunter_tab(g, s="from_20260823"):
        return next(t for t in hunter["tables"] if (t["group"], t["stratum"], t["population"]) == (g, s, "all_row"))

    per_block = {}
    for blk in BLOCKS:
        cf, cb = cells_for(f, blk, FROM), cells_for(f, blk, BEFORE)
        est, ci, boot = w_ci(W, kidx, cf)
        est_b, ci_b, _ = w_ci(W, kidx, cb)
        gap = float(cf.gap.mean())
        pm = cf.groupby("market").delta.mean()
        ht = hunter_tab(blk)
        hb = hunter_tab(blk, BEFORE)
        se = float(boot.std())
        entry = {
            "from": {"estimate": est, "ci95_W": ci, "boot_se": se, "z": est / se if se else None,
                     "p_two_sided_boot": float(2 * min((boot >= 0).mean(), (boot <= 0).mean())),
                     "market_days": int(len(cf)), "dates": int(cf.date.nunique()),
                     "served_minus_market_gap": gap, "gap_closed": float(-est / gap) if gap else None,
                     "cand_minus_market": float((cf.cand - cf.mkt).mean()),
                     "cand_minus_market_ci_W": w_ci(W, kidx, cf.assign(cm=cf.cand - cf.mkt), "cm")[1],
                     "markets_negative": int((pm < 0).sum()), "per_market": pm.round(6).to_dict(),
                     "share_market_days_negative": float((cf.delta < 0).mean()),
                     "share_market_days_positive": float((cf.delta > 0).mean()),
                     "median_delta": float(cf.delta.median())},
            "before": {"estimate": est_b, "ci95_W": ci_b, "market_days": int(len(cb)),
                       "markets_negative": int((cb.groupby("market").delta.mean() < 0).sum())},
            "hunter_from": {"estimate": ht["candidate_minus_served"]["estimate"],
                            "ci95": ht["candidate_minus_served"]["ci95"], "markets_negative": ht["markets_negative"]},
            "hunter_before_estimate": hb["candidate_minus_served"]["estimate"],
            "match_hunter_abs_diff": abs(est - ht["candidate_minus_served"]["estimate"]),
        }
        entry["lead_W"] = lead_check(est, ci[1], est_b, gap, int((pm < 0).sum()))
        # alternative inferences
        alt = {}
        for seed in (1, 2, 3):
            b = fresh_crossed(cf, 4000, seed)
            alt[f"crossed_seed{seed}"] = q(b)
        bd = cluster_boot(cf, "date", 4000, 11)
        bm = cluster_boot(cf, "market", 4000, 12)
        alt["date_cluster_only"] = q(bd)
        alt["market_cluster_only"] = q(bm)
        alt["date_cluster_p_two_sided"] = float(2 * min((bd >= 0).mean(), (bd <= 0).mean()))
        # t-interval on dates (36 clusters): mean of per-date deltas
        per_date = cf.groupby("date").delta.mean()
        tse = per_date.std(ddof=1) / np.sqrt(len(per_date))
        alt["date_t_interval"] = [float(per_date.mean() - 2.03 * tse), float(per_date.mean() + 2.03 * tse)]
        alt["dates_negative"] = f"{int((per_date < 0).sum())}/{len(per_date)}"
        alt["per_date"] = per_date.round(5).to_dict()
        # winsorised / trimmed
        lo_, hi_ = cf.delta.quantile([0.05, 0.95])
        alt["winsorised_5_95_mean"] = float(cf.delta.clip(lo_, hi_).mean())
        alt["trimmed_10pct_mean"] = float(cf.delta.sort_values().iloc[int(.1 * len(cf)):int(.9 * len(cf))].mean())
        entry["alt_inference"] = alt
        # jackknives
        jk = {}
        lom = {}
        for mk in sorted(cf.market.unique()):
            sub = cf[cf.market != mk]
            e, c_, _ = w_ci(W, kidx, sub)
            lom[mk] = {"estimate": e, "ci95_W": c_}
        jk["leave_one_market_out"] = lom
        jk["leave_one_market_out_worst_hi"] = max(v["ci95_W"][1] for v in lom.values())
        jk["leave_one_market_out_worst_est"] = max(v["estimate"] for v in lom.values())
        wk = pd.to_datetime(cf.date).dt.isocalendar().week.astype(int)
        cf2 = cf.assign(week=wk.to_numpy())
        low = {}
        for wv in sorted(cf2.week.unique()):
            sub = cf2[cf2.week != wv]
            e, c_, _ = w_ci(W, kidx, sub)
            low[int(wv)] = {"estimate": e, "ci95_W": c_, "dropped_market_days": int((cf2.week == wv).sum())}
        jk["leave_one_week_out"] = low
        jk["leave_one_week_out_worst_hi"] = max(v["ci95_W"][1] for v in low.values())
        jk["per_week_estimate"] = cf2.groupby("week").delta.mean().round(6).to_dict()
        jk["per_week_market_days"] = cf2.groupby("week").size().to_dict()
        lod = {}
        for dt in sorted(cf.date.unique()):
            sub = cf[cf.date != dt]
            lod[dt] = float(sub.delta.mean())
        jk["leave_one_date_out_max_est"] = max(lod.values())
        jk["leave_one_date_out_min_est"] = min(lod.values())
        # concentration of the gain
        neg = cf.delta[cf.delta < 0].sort_values()
        total = cf.delta.sum()
        jk["top5_market_days"] = [{"date": r.date, "market": r.market, "delta": round(r.delta, 5)}
                                  for r in cf.sort_values("delta").head(5).itertuples()]
        jk["share_of_net_gain_from_top_10pct_market_days"] = float(
            cf.delta.sort_values().head(max(1, int(round(.1 * len(cf))))).sum() / total) if total < 0 else None
        jk["share_of_net_gain_from_top_5pct_market_days"] = float(
            cf.delta.sort_values().head(max(1, int(round(.05 * len(cf))))).sum() / total) if total < 0 else None
        jk["estimate_without_top_5pct_market_days"] = float(
            cf.delta.sort_values().iloc[max(1, int(round(.05 * len(cf)))):].mean())
        entry["jackknife"] = jk
        # coverage vs outcome (selection on availability?)
        lo, hi = BLOCKS[blk]
        g = f[f.local_hour.between(lo, hi) & (f.stratum == FROM)]
        cov, unc = g[g.use], g[~g.use]
        def mw(a, b):
            from scipy.stats import mannwhitneyu
            if len(a) < 5 or len(b) < 5:
                return None
            return float(mannwhitneyu(a, b, alternative="two-sided").pvalue)
        rr_c = cov.remaining_rise_vs_floor.dropna()
        rr_u = unc.remaining_rise_vs_floor.dropna()
        sel = {"covered_snapshots": int(len(cov)), "uncovered_snapshots": int(len(unc)),
               "uncovered_reasons": unc.reason.value_counts().to_dict(),
               "served_brier_covered": float(cov.served.mean()), "served_brier_uncovered": float(unc.served.mean()) if len(unc) else None,
               "market_brier_covered": float(cov.mkt.mean()), "market_brier_uncovered": float(unc.mkt.mean()) if len(unc) else None,
               "gap_covered": float((cov.served - cov.mkt).mean()), "gap_uncovered": float((unc.served - unc.mkt).mean()) if len(unc) else None,
               "remaining_rise_vs_floor_mean_covered": float(rr_c.mean()) if len(rr_c) else None,
               "remaining_rise_vs_floor_mean_uncovered": float(rr_u.mean()) if len(rr_u) else None,
               "share_settled_at_or_below_floor_covered": float((rr_c <= 0).mean()) if len(rr_c) else None,
               "share_settled_at_or_below_floor_uncovered": float((rr_u <= 0).mean()) if len(rr_u) else None,
               "mannwhitney_p_remaining_rise": mw(rr_c, rr_u),
               "mannwhitney_p_served_brier": mw(cov.served, unc.served),
               "market_days_fully_covered": int((cf.use == 1).sum()),
               "delta_fully_covered_market_days": float(cf[cf.use == 1].delta.mean()) if (cf.use == 1).any() else None,
               "delta_partially_covered_market_days": float(cf[cf.use < 1].delta.mean()) if (cf.use < 1).any() else None,
               "corr_coverage_share_vs_delta_market_day": float(np.corrcoef(cf.use, cf.delta)[0, 1]) if cf.use.std() > 0 else None}
        entry["selection"] = sel
        per_block[blk] = entry

    report["blocks"] = per_block
    # multiplicity from the registry
    reg = [json.loads(l) for l in open(r"C:\swarm\registry.jsonl", encoding="utf-8") if l.strip()]
    agents = {}
    for r in reg:
        agents.setdefault(r["agent"], []).append(r["id"])
    n_rules = len(reg)
    n_groups = 7
    report["multiplicity"] = {"registry_rules_total": n_rules, "registry_agents": {k: len(v) for k, v in agents.items()},
                              "t2_rules": agents.get("t2", []),
                              "tests_registry_x_groups": n_rules * n_groups,
                              "bonferroni_alpha_rules_x_groups": 0.05 / (n_rules * n_groups),
                              "bonferroni_z_rules_x_groups": float(__import__("scipy").stats.norm.isf(0.05 / (n_rules * n_groups) / 2)),
                              "bonferroni_z_t2_only_4x7": float(__import__("scipy").stats.norm.isf(0.05 / 28 / 2)),
                              "registry_time_first_t2": min(r["time_local"] for r in reg if r["agent"] == "t2"),
                              "t2_first_score_file_mtime": pd.Timestamp(Path(r"C:\swarm\out\t2\t2_diag.json").stat().st_mtime, unit="s", tz="UTC").tz_convert("America/New_York").isoformat()}
    for blk in ("17-23", "13-16"):
        e = report["blocks"][blk]["from"]
        report["multiplicity"][f"{blk}_z"] = e["z"]
        report["multiplicity"][f"{blk}_survives_bonferroni_rules_x_groups"] = bool(abs(e["z"]) > report["multiplicity"]["bonferroni_z_rules_x_groups"])
        report["multiplicity"][f"{blk}_survives_bonferroni_t2_only"] = bool(abs(e["z"]) > report["multiplicity"]["bonferroni_z_t2_only_4x7"])
    (OUT / "result.json").write_text(json.dumps(report, indent=1, default=float), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "blocks"}, indent=1, default=float))
    for blk in ("17-23", "13-16", "00-16"):
        e = report["blocks"][blk]
        print(blk, "from est", round(e["from"]["estimate"], 6), "W ci", [round(x, 6) for x in e["from"]["ci95_W"]],
              "hunter", e["hunter_from"]["estimate"], e["hunter_from"]["ci95"], "mkts neg", e["from"]["markets_negative"],
              "LEAD", e["lead_W"]["LEAD"])
        print("  alt:", {k: v for k, v in e["alt_inference"].items() if k != "per_date"})
        print("  jk worst market hi", e["jackknife"]["leave_one_market_out_worst_hi"], "worst week hi", e["jackknife"]["leave_one_week_out_worst_hi"])
        print("  weeks", e["jackknife"]["per_week_estimate"])
        print("  sel", e["selection"])


if __name__ == "__main__":
    main()
