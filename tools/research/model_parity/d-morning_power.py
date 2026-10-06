"""D-MORNING planning diagnostic (registry id d-morning-plan1). Development only; sizing, never evidence.

Reconstructs the registered control r-t5-inc-c1 exactly as in r-t5-inc_refute.py and, on the BEFORE stratum
only (DESIGN rule 7), plans power for a prospective morning-route pre-registration under the fixed-market
date-clustered estimand and the crossed date x market estimand.
Run: cd C:\\pt\\swarm; <repo python> tools\\research\\model_parity\\d-morning_power.py
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

OUT = Path(r"C:\swarm\out\d-morning")
OUT.mkdir(parents=True, exist_ok=True)
if Path(r"C:\swarm\STOP").exists():
    sys.exit("STOP present")
BEFORE = "before_20260823"
DRAWS, SEED, ALPHA = 2000, 20261004, 0.025

d = h.data()
snaps, bands = h.candidate_inputs()
cap = pd.to_datetime(snaps.captured_at_utc, utc=True, format="ISO8601")
v2av = pd.to_datetime(snaps.v2_available_at, utc=True, format="ISO8601", errors="coerce")
ok = (snaps.v2_mean.notna() & snaps.v2_stddev.notna() & v2av.notna() & (v2av <= cap) & snaps.floor.notna())
h.assert_point_in_time(v2av[ok], cap[ok])
offs, nb = d.offsets, snaps.n_bands.to_numpy()
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
pc, use, _ = h._candidate_vector(c1, d, False)
c1b = np.add.reduceat((pc - d.y) ** 2, offs) / nb
served_b = np.add.reduceat(d.se_served, offs) / nb
LH = d.snaps.local_hour.to_numpy()
STR = d.snaps.stratum.to_numpy()
assert (d.snaps.date.to_numpy() <= "2026-09-29").all()


def cells(lo, hi):
    m = (LH >= lo) & (LH <= hi) & (STR == BEFORE)
    f = pd.DataFrame({"date": d.snaps.date[m].to_numpy(), "market": d.snaps.market[m].to_numpy(),
                      "delta": (c1b - served_b)[m]})
    return f.groupby(["date", "market"], sort=True).delta.mean().reset_index()


def plan(c, effects, ns):
    dates = sorted(c.date.unique())
    mkts = sorted(c.market.unique())
    di = c.date.map({x: k for k, x in enumerate(dates)}).to_numpy()
    mi = c.market.map({x: k for k, x in enumerate(mkts)}).to_numpy()
    y = c.delta.to_numpy()
    point = float(y.mean())
    idx = np.array([d.key_index[(a, b)] for a, b in zip(c.date, c.market)])
    crossed_dev = h.interval(idx, y, effect=-.0075)
    rng = np.random.default_rng(SEED)
    out = {"point_before": point, "dates": len(dates), "markets": len(mkts), "market_days": int(len(c)),
           "crossed_harness_before": {k: crossed_dev[k] for k in ("estimate", "ci95", "mde80", "power")},
           "per_market_mean": c.groupby("market").delta.mean().round(5).to_dict(), "plans": {}}

    def errs(n, mode):
        e = np.empty(DRAWS)
        for b in range(DRAWS):
            wd = np.ones(len(dates)) if n is None else rng.multinomial(n, np.full(len(dates), 1 / len(dates)))
            wm = np.ones(len(mkts)) if mode == "fixed" else rng.multinomial(len(mkts), np.full(len(mkts), 1 / len(mkts)))
            w = wd[di] * wm[mi]
            e[b] = (w * y).sum() / w.sum() if w.sum() > 0 else np.nan
        e = e[np.isfinite(e)]
        return e - e.mean()

    for mode in ("fixed", "crossed"):
        res = {}
        for n in ns + ([None] if mode == "crossed" else []):
            e = errs(n, mode)
            q = np.quantile(e, ALPHA)
            sd = float(e.std())
            mde80 = float(np.quantile(e, 0.8) - q)  # smallest shift with 80% power: P(err - s < q) = .8
            res["inf" if n is None else str(n)] = {"sd": sd, "mde80": mde80,
                                                   **{f"power@{ef:.6f}": float(np.mean(e - ef < q)) for ef in effects}}
        out["plans"][mode] = res
    return out


NS = [10, 15, 20, 30, 45, 60, 90, 120, 180]
result = {"id": "d-morning-plan1", "HARNESS_SHA256": h.harness_sha256(), "development": True,
          "alpha_one_sided": ALPHA, "draws": DRAWS, "seed": SEED, "c1_coverage": float(use.mean())}
c016 = cells(0, 16)
dev = -float(c016.delta.mean())
EFF = [dev / 2, 0.006672, dev]
result["00-16"] = plan(c016, EFF, NS)
result["17-23"] = plan(cells(17, 23), [0.003, 0.006672], [20, 45, 90])
result["effects_00_16"] = {"half_before": dev / 2, "81a_C1_pooled": 0.006672, "full_before": dev}
(OUT / "power.json").write_text(json.dumps(result, indent=1, default=float), encoding="utf-8")
print(json.dumps(result, indent=1, default=float))


# ---- refinement: fixed-market N 20..30 and joint power with the >= 8/11 per-market sign condition (plug-in:
# future per-market means = before-stratum per-market deviation from the overall mean + shift (-e) + date noise)
def joint(c, effects, ns):
    dates = sorted(c.date.unique()); mkts = sorted(c.market.unique())
    di = c.date.map({x: k for k, x in enumerate(dates)}).to_numpy()
    mi = c.market.map({x: k for k, x in enumerate(mkts)}).to_numpy()
    y = c.delta.to_numpy(); ybar = y.mean()
    rng = np.random.default_rng(SEED + 1)
    out = {}
    for n in ns:
        tot = np.empty(DRAWS); pm = np.empty((DRAWS, len(mkts)))
        for b in range(DRAWS):
            wd = rng.multinomial(n, np.full(len(dates), 1 / len(dates)))
            w = wd[di].astype(float)
            tot[b] = (w * y).sum() / w.sum()
            num = np.bincount(mi, w * y, len(mkts)); den = np.bincount(mi, w, len(mkts))
            pm[b] = np.divide(num, den, out=np.full(len(mkts), np.nan), where=den > 0)
        err = tot - tot.mean(); q = np.quantile(err, ALPHA)
        res = {}
        for ef in effects:
            # shifted world: every cell moves by (-e - ybar), i.e. overall mean becomes -e
            sig_ok = err - ef < q
            mk_neg = (np.nan_to_num(pm - ybar - ef, nan=1.0) < 0).sum(axis=1) >= 8
            res[f"{ef:.6f}"] = {"power_interval": float(sig_ok.mean()), "power_joint_8of11": float((sig_ok & mk_neg).mean())}
        out[str(n)] = res
    return out


result["00-16_fixed_joint"] = joint(c016, EFF, [20, 22, 24, 26, 28, 30, 35, 45])
(OUT / "power.json").write_text(json.dumps(result, indent=1, default=float), encoding="utf-8")
print(json.dumps(result["00-16_fixed_joint"], indent=1))
