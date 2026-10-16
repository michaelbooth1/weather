"""R-STAT-T18: statistics refuter for T18 (t18-r1 rung x guidance EMOS). Development only.

Independent scoring (own floor/renormalise/fallback from the cache, own cell means, own W intervals),
paired marginal value over the t3-r3 rung, per-market / per-stratum / per-date signs, leave-one-market-out,
leave-one-week-out, availability-vs-outcome association, forking-path count from the registry,
and a fit-window stability diagnostic (not a rule). No new rules are registered.
Run: cd C:\\pt\\swarm; <repo python> tools\\research\\model_parity\\r-stat-t18_refute.py
"""
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\pt\swarm")
from tools.research.model_parity import harness as h  # noqa: E402
from tools.research.model_parity import t18_emos as t  # noqa: E402
from tools.research.model_parity import t5_nbh_latest as t5  # noqa: E402

OUT = Path(r"C:\swarm\out\refute-stat-t18")
OUT.mkdir(parents=True, exist_ok=True)
STOP = Path(r"C:\swarm\STOP")
CACHE = Path(r"C:\swarm\cache")
FROM, BEFORE = "from_20260823", "before_20260823"
GROUPS = {"00-05": (0, 5), "06-09": (6, 9), "10-12": (10, 12), "13-16": (13, 16), "17-23": (17, 23),
          "00-16": (0, 16), "all": (0, 23)}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def chk():
    if STOP.exists():
        sys.exit("STOP present")


chk()
res = {"agent": "r-stat-t18", "HARNESS_SHA256": h.harness_sha256()}

# ------------------------------------------------------------------ cache (own scoring, not harness _candidate_vector)
B = pd.read_parquet(CACHE / "bands.parquet", columns=["row_key", "band_index", "p_served", "p_market_yes",
                                                      "is_winner", "floor_impossible", "date"])
S = pd.read_parquet(CACHE / "snapshots.parquet", columns=["row_key", "market", "date", "stratum", "local_hour",
                                                          "n_bands", "floor", "captured_at_utc"])
assert (S.date <= "2026-09-29").all() and (B.date <= "2026-09-29").all()
res["rows_after_20260929"] = int((S.date > "2026-09-29").sum())
nb = S.n_bands.to_numpy()
off = np.r_[0, np.cumsum(nb)[:-1]]
assert (B.row_key.to_numpy()[off] == S.row_key.to_numpy()).all()
bsnap = np.repeat(np.arange(len(S)), nb)
y = B.is_winner.to_numpy(float)
ps = B.p_served.to_numpy(float)
pm = B.p_market_yes.to_numpy(float)
imp = B.floor_impossible.to_numpy(bool)
has_floor = S.floor.notna().to_numpy()
pos_of = pd.Series(np.arange(len(S)), index=S.row_key)


def snap_mean(v):
    return np.add.reduceat(v, off) / nb


served_b = snap_mean((ps - y) ** 2)
market_b = snap_mean((pm - y) ** 2)


def own_brier(cand):
    """Own implementation: place p, zero floor-impossible bands, renormalise, served fallback."""
    pc = np.full(len(B), np.nan)
    p_ix = pos_of.reindex(cand.row_key.to_numpy()).to_numpy().astype(int)
    pc[off[p_ix] + cand.band_index.to_numpy(int)] = cand.p.to_numpy(float)
    given = ~np.isnan(pc)
    ng = np.bincount(bsnap, weights=given, minlength=len(S))
    provided = ng == nb
    pc = np.where(imp & given, 0.0, pc)
    tot = np.bincount(bsnap, weights=np.where(given, pc, 0.0), minlength=len(S))
    use = provided & has_floor & (tot > 0)
    ub = use[bsnap]
    pcn = np.where(ub, pc / np.where(tot > 0, tot, 1.0)[bsnap], ps)
    return snap_mean((pcn - y) ** 2), use


W = np.load(CACHE / "W.npy")
keys = [tuple(k) for k in json.loads((CACHE / "W_keys.json").read_text())]
kidx = {k: i for i, k in enumerate(keys)}
LH = S.local_hour.to_numpy()
ST = S.stratum.to_numpy()


def cells(group, stratum, cols, mask=None):
    lo, hi = GROUPS[group]
    m = (LH >= lo) & (LH <= hi)
    if stratum != "pooled":
        m &= ST == stratum
    if mask is not None:
        m &= mask
    f = pd.DataFrame({"date": S.date.to_numpy()[m], "market": S.market.to_numpy()[m],
                      **{k: v[m] for k, v in cols.items()}})
    c = f.groupby(["date", "market"], sort=True).mean().reset_index()
    ix = np.array([kidx[(a, b)] for a, b in zip(c.date, c.market)])
    return c, ix


def wint(ix, a, b=None):
    sub = W[:, ix]
    b = np.ones(len(a)) if b is None else b
    bo = (sub @ a) / (sub @ b)
    est = float(a.sum() / b.sum())
    sd = float(np.std(bo, ddof=1))
    return {"est": est, "ci95": [float(x) for x in np.quantile(bo, [.025, .975])], "boot_sd": sd,
            "boot_share_ge0": float((bo >= 0).mean())}


def paired(a_b, b_b, group, stratum, mask=None, detail=False):
    c, ix = cells(group, stratum, {"a": a_b, "b": b_b, "s": served_b, "mk": market_b}, mask)
    dl = (c.a - c.b).to_numpy()
    r = wint(ix, dl)
    r["gap_served_minus_market"] = float((c.s - c.mk).mean())
    pmk = c.assign(dl=dl).groupby("market").dl.mean()
    r["markets_neg"] = int((pmk < 0).sum())
    r["markets"] = int(len(pmk))
    r["market_days"] = int(len(c))
    if detail:
        r["per_market"] = {k: round(float(v), 5) for k, v in pmk.sort_values().items()}
        pdt = c.assign(dl=dl).groupby("date").dl.mean()
        r["dates_neg"] = int((pdt < 0).sum())
        r["dates"] = int(len(pdt))
        wk = pd.to_datetime(c.date)
        wk = ((wk - pd.Timestamp("2026-08-01")).dt.days // 7).to_numpy()
        pw = pd.Series(dl).groupby(wk).mean()
        r["per_week"] = {int(k): round(float(v), 5) for k, v in pw.items()}
        # leave-one-market-out / leave-one-week-out point estimates (equal market-day mean)
        lomo = {mk: float(dl[c.market.to_numpy() != mk].mean()) for mk in pmk.index}
        lowo = {int(w): float(dl[wk != w].mean()) for w in np.unique(wk)}
        r["lomo_max"] = max(lomo.values())
        r["lomo_argmax"] = max(lomo, key=lomo.get)
        r["lowo_max"] = max(lowo.values())
        r["lowo_argmax"] = int(max(lowo, key=lowo.get))
        # LOMO with W interval for the most influential market dropped
        drop = min(pmk.index, key=lambda k: pmk[k])
        keep = c.market.to_numpy() != drop
        r["drop_top_market"] = {"market": drop, **wint(ix[keep], dl[keep])}
        r["top_market_share_of_sum"] = float(dl[c.market.to_numpy() == drop].sum() / dl.sum())
    return r


def lead(tab_from, tab_before):
    f = tab_from
    c = {"interval_excludes_0": f["ci95"][1] < 0,
         "size": f["est"] <= -0.0133 or f["est"] <= -0.05 * f["gap_served_minus_market"],
         "both_strata_negative": f["est"] < 0 and tab_before["est"] < 0,
         "ge8_markets_negative": f["markets_neg"] >= 8}
    cls = "LEAD" if all(c.values()) else ("WEAK" if f["est"] < 0 else ("HARM" if f["ci95"][0] > 0 else "NULL"))
    return {"class": cls, **{k: bool(v) for k, v in c.items()}}


# ------------------------------------------------------------------ rebuild T18 candidates (stored thetas)
chk()
log("build inputs")
run = json.loads((t.OUT / "t18_run.json").read_text(encoding="utf-8"))
ctl = json.loads((t.OUT / "t18_controls.json").read_text(encoding="utf-8"))
chosen = run["chosen"]
th1 = np.r_[run["theta_r1"]["a"], [run["theta_r1"][f"b_{k}"] for k in chosen], np.log(run["theta_r1"]["sigma"])]
th0 = np.r_[run["theta_c0"]["a"], np.log(run["theta_c0"]["sigma"])]
thc1 = np.r_[ctl["theta_c1"]["a"], ctl["theta_c1"]["b_v2_mean"], np.log(ctl["theta_c1"]["sigma"])]
s, bands, prior, src, meta = t.build_inputs()
assert (s.row_key.to_numpy() == S.row_key.to_numpy()).all()
cov = s.covered.to_numpy()
tr = cov & (s.stratum == BEFORE).to_numpy() & s.Y.notna().to_numpy()
eobs = np.minimum((s.Y.to_numpy()[tr] - s.R.to_numpy()[tr]).astype(int), t.G - 1)
mtr = t.Model(s, prior, src, tr)
# refit check: the stored r1 theta is reproducible from the registered procedure
th1_re, nll1_re, ok1 = t.fit(mtr, eobs, chosen)
res["refit_r1"] = {"theta_stored": th1.tolist(), "theta_refit_default_start": th1_re.tolist(),
                   "train_nll_refit": nll1_re, "train_nll_stored": run["train_nll"]["r1"]}
log("refit", th1_re, nll1_re)
# label leakage audit: Y only enters through training rows (before stratum, dates <= 08-22)
res["train_rows"] = int(tr.sum())
res["train_max_date"] = str(s.date[tr].max())
mall = t.Model(s, prior, src, cov)
G = t.G


def bandsof(pmf_cov):
    full = np.full((len(s), G), np.nan)
    full[cov] = pmf_cov
    return t.to_bands(s, bands, full, cov)


cands = {"r1": bandsof(mall.pmf(th1, chosen)), "c0": bandsof(mall.pmf(th0, [])),
         "c1": bandsof(mall.pmf(thc1, ["v2_mean"])), "rung": bandsof(prior[cov])}
# r1s (+60 min sources)
cap = pd.to_datetime(s.captured_at_utc, utc=True)
src_s = dict(src)
for col, av in (("v2_mean", "v2_available_at"), ("hrrr_high", "hrrr_fetched_at")):
    a = pd.to_datetime(s[av], utc=True, errors="coerce") + pd.Timedelta(minutes=60)
    use = np.isfinite(src[col]) & (a <= cap).to_numpy()
    src_s[col] = np.where(use, src[col], np.nan)
src_s["forecast_high"] = np.full(len(s), np.nan)
cands["r1s"] = bandsof(t.Model(s, prior, src_s, cov).pmf(th1, chosen))

# r-t5-inc-c1 (registered control by r-t5-inc): v2 Gaussian zero-parameter, rebuilt per its script
snaps, _ = h.candidate_inputs()
v2av = pd.to_datetime(snaps.v2_available_at, utc=True, format="ISO8601", errors="coerce")
capq = pd.to_datetime(snaps.captured_at_utc, utc=True, format="ISO8601")
okv = (snaps.v2_mean.notna() & snaps.v2_stddev.notna() & v2av.notna() & (v2av <= capq) & snaps.floor.notna())
kinds, lows, highs = bands.kind.to_numpy(), bands.low.to_numpy(), bands.high.to_numpy()
p_out = np.full(len(bands), np.nan)
for i in np.flatnonzero(okv.to_numpy()):
    mu = float(snaps.v2_mean.iat[i]); sig = max(float(snaps.v2_stddev.iat[i]), t5.SIG_MIN)
    Bf = math.floor(float(snaps.floor.iat[i]) + .5)
    o, n = off[i], nb[i]
    p = t5.band_probs(kinds[o:o + n], lows[o:o + n], highs[o:o + n], Bf, mu, sig)
    if p.sum() > 0:
        p_out[o:o + n] = p / p.sum()
cv = ~np.isnan(p_out)
cands["t5inc_c1"] = bands.loc[cv, ["row_key", "band_index"]].assign(p=p_out[cv])

chk()
log("own scoring")
sb, use = {}, {}
for k, c in cands.items():
    sb[k], use[k] = own_brier(c)
res["coverage"] = {k: float(v.mean()) for k, v in use.items()}

# ------------------------------------------------------------------ 1. independent from/before tables vs served, vs rung
pairs = {"r1-served": ("r1", None), "r1-rung": ("r1", "rung"), "c1-rung": ("c1", "rung"),
         "r1-c1": ("r1", "c1"), "c0-rung": ("c0", "rung"), "r1s-served": ("r1s", None),
         "rung-served": ("rung", None), "c1-served": ("c1", None),
         "r1-t5incc1": ("r1", "t5inc_c1"), "c1-t5incc1": ("c1", "t5inc_c1"), "t5incc1-served": ("t5inc_c1", None)}
tabs = {}
for pn, (a, b) in pairs.items():
    tabs[pn] = {}
    for g in GROUPS:
        fr = paired(sb[a], served_b if b is None else sb[b], g, FROM, detail=pn in ("r1-served", "r1-rung", "c1-rung"))
        be = paired(sb[a], served_b if b is None else sb[b], g, BEFORE)
        tabs[pn][g] = {"from": fr, "before": be, "lead": lead(fr, be)}
    log(pn, {g: (round(tabs[pn][g]["from"]["est"], 5), tabs[pn][g]["lead"]["class"]) for g in GROUPS})
res["tables"] = tabs

# harness cross-check (r1 vs served, from, all-row)
hs = json.loads((t.OUT / "t18_r1_emos.score.json").read_text(encoding="utf-8"))
xc = {}
for g in GROUPS:
    tl = h.table_lookup(hs, g, FROM, "all_row")["candidate_minus_served"]
    xc[g] = {"harness": tl["estimate"], "harness_ci": tl["ci95"], "own": tabs["r1-served"][g]["from"]["est"],
             "own_ci": tabs["r1-served"][g]["from"]["ci95"]}
res["harness_crosscheck_r1_served_from"] = xc

# ------------------------------------------------------------------ 2. availability vs outcome
chk()
avail = {}
covm = use["r1"]
hrrr_ok = np.isfinite(src["hrrr_high"])
for g in ("00-16", "17-23", "all"):
    lo, hi = GROUPS[g]
    for stv in (FROM, BEFORE):
        m = (LH >= lo) & (LH <= hi) & (ST == stv)
        avail[f"{g}|{stv}"] = {
            "covered_share": float(covm[m].mean()),
            "served_minus_market_covered": float((served_b - market_b)[m & covm].mean()),
            "served_minus_market_fallback": float((served_b - market_b)[m & ~covm].mean()) if (m & ~covm).any() else None,
            "hrrr_pit_share": float(hrrr_ok[m].mean()),
            "served_minus_market_hrrr_on": float((served_b - market_b)[m & hrrr_ok].mean()),
            "served_minus_market_hrrr_off": float((served_b - market_b)[m & ~hrrr_ok].mean()) if (m & ~hrrr_ok).any() else None,
            "r1_minus_c1_hrrr_on": float((sb["r1"] - sb["c1"])[m & hrrr_ok].mean()),
            "r1_minus_c1_hrrr_off": float((sb["r1"] - sb["c1"])[m & ~hrrr_ok].mean()) if (m & ~hrrr_ok).any() else None,
        }
# matched (covered rows only) r1 - served, selected on availability
avail["matched_r1_served_00-16_from"] = paired(sb["r1"], served_b, "00-16", FROM, mask=covm)
avail["v2_pit_rows"] = int(np.isfinite(src["v2_mean"]).sum())
res["availability"] = avail

# ------------------------------------------------------------------ 3. fit-window stability diagnostic (not a rule)
chk()
half = tr & (s.date <= "2026-08-11").to_numpy()
eh = np.minimum((s.Y.to_numpy()[half] - s.R.to_numpy()[half]).astype(int), G - 1)
mh = t.Model(s, prior, src, half)
thh, nllh, okh = t.fit(mh, eh, chosen)
rh = bandsof(mall.pmf(thh, chosen))
sbh, _ = own_brier(rh)
late_before = (ST == BEFORE) & (S.date.to_numpy() > "2026-08-11")
res["fit_window_diag"] = {
    "label": "diagnostic, not a rule: r1 form refit on 08-01..08-11 only",
    "theta": thh.tolist(), "theta_full": th1.tolist(),
    "from_00-16_vs_served": paired(sbh, served_b, "00-16", FROM),
    "from_00-16_vs_rung": paired(sbh, sb["rung"], "00-16", FROM),
    "before_late_half_00-16_vs_rung_out_of_sample": paired(sbh, sb["rung"], "00-16", BEFORE, mask=late_before),
    "before_late_half_00-16_vs_served_out_of_sample": paired(sbh, served_b, "00-16", BEFORE, mask=late_before)}
log("fitwin", res["fit_window_diag"]["from_00-16_vs_rung"]["est"],
    res["fit_window_diag"]["before_late_half_00-16_vs_rung_out_of_sample"]["est"])

# ------------------------------------------------------------------ 4. forking paths
reg = [json.loads(x) for x in Path(r"C:\swarm\registry.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
nrule = len(reg)
fk = {"registry_rules_now": nrule, "t18_rules": sum(1 for r in reg if r.get("agent") == "t18"),
      "t18_registration_times": {r["id"]: r["time_local"] for r in reg if r.get("agent") == "t18"}}
for pn in ("r1-served", "r1-rung"):
    for g in GROUPS:
        fr = tabs[pn][g]["from"]
        z = fr["est"] / fr["boot_sd"]
        p2 = math.erfc(abs(z) / math.sqrt(2))
        fk[f"{pn}|{g}"] = {"z": z, "p_two_sided": p2, "bonferroni_p_rules_x_7blocks": min(1.0, p2 * nrule * 7)}
res["forking"] = fk

(OUT / "result_raw.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
log("done")
