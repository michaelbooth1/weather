"""D-DEFECT d2/d3: is T5's 13-16 increment over v2_mean the same mechanism as the evening defect? Development only.
Registered: d-defect-d2, d-defect-d3 (diagnostics). Run from C:\\pt\\swarm:
    python -m tools.research.model_parity.d_defect_t5_attribution
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h
from tools.research.model_parity import t5_nbh_latest as t5
from tools.research.model_parity import t1_decided_band as t1
from tools.research.model_parity import d_defect_evening_stage as dd

OUT = Path(r"C:\swarm\out\d-defect")
FROM, BEFORE = "from_20260823", "before_20260823"


def main():
    assert not Path(r"C:\swarm\STOP").exists()
    d = h.data()
    s, bands = t5.snapshot_frame()
    assert (d.snaps.row_key.to_numpy() == s.row_key.to_numpy()).all()
    nb = d.snaps.n_bands.to_numpy()
    served_b = np.add.reduceat(d.se_served, d.offsets) / nb
    market_b = np.add.reduceat(d.se_market, d.offsets) / nb

    def snap_brier(cand):
        pc, use, _ = h._candidate_vector(cand, d, False)
        return np.add.reduceat((pc - d.y) ** 2, d.offsets) / nb, use

    # T5 as registered
    idx = t5.load_nbh(extra_lag_min=0)
    t5c, ages, mus, _ = t5.build_candidate(idx, s, bands)
    t5_b, t5_use = snap_brier(t5c)
    # c1 (r-t5-inc-c1 form)
    snaps, cb = h.candidate_inputs()
    assert (snaps.row_key.to_numpy() == s.row_key.to_numpy()).all()
    cap = pd.to_datetime(snaps.captured_at_utc, utc=True, format="ISO8601")
    v2av = pd.to_datetime(snaps.v2_available_at, utc=True, format="ISO8601", errors="coerce")
    ok = (snaps.v2_mean.notna() & snaps.v2_stddev.notna() & v2av.notna() & (v2av <= cap) & snaps.floor.notna())
    h.assert_point_in_time(v2av[ok], cap[ok])
    kinds, lows, highs = cb.kind.to_numpy(), cb.low.to_numpy(), cb.high.to_numpy()
    p_out = np.full(len(cb), np.nan)
    for i in np.flatnonzero(ok.to_numpy()):
        mu = float(snaps.v2_mean.iat[i]); sig = max(float(snaps.v2_stddev.iat[i]), t5.SIG_MIN)
        B = math.floor(float(snaps.floor.iat[i]) + .5); o, n = d.offsets[i], nb[i]
        p = t5.band_probs(kinds[o:o + n], lows[o:o + n], highs[o:o + n], B, mu, sig)
        if p.sum() > 0:
            p_out[o:o + n] = p / p.sum()
    cov = ~np.isnan(p_out)
    c1_b, _ = snap_brier(cb.loc[cov, ["row_key", "band_index"]].assign(p=p_out[cov]))
    # T1-r2
    params = json.loads((t1.OUT / "fit_params.json").read_text(encoding="utf-8"))
    obs = pd.read_parquet(t1.OUT / "t1_obs_pit.parquet")
    t1c, _ = t1.build(snaps, cb, obs, params, "r2")
    t1_b, _ = snap_brier(t1c)
    # d-defect-r2 (restored S1+S2), same construction as d_defect_evening_stage
    sn = snaps.merge(obs[["row_key", "cur"]], on="row_key", how="left")
    F = sn.floor.to_numpy(float); B = dd.rhu(F)
    sn["B"] = B
    sn["s_heur"] = dd.heuristic_strength(sn.local_hour, F, sn.cur.to_numpy(float))
    sn["t"] = pd.to_datetime(sn.captured_at_utc, utc=True)
    srt = sn.sort_values(["market", "date", "t"])
    chg = srt.groupby(["market", "date"], sort=False)["B"].transform(lambda x: (x != x.shift()).cumsum())
    first_t = srt.assign(c=chg).groupby(["market", "date", "c"])["t"].transform("min")
    stood = ((srt.t - first_t).dt.total_seconds() / 60.0).reindex(sn.index)
    rates = dd.revision_rates()
    rate = np.array([rates.get(m, {}).get(int(hr), np.nan) for m, hr in zip(sn.market, sn.local_hour)])
    learned = np.where((sn.local_hour >= 17) & (stood >= 90) & ~np.isnan(rate), np.clip(1 - rate, 0, 1), 0.0)
    sn["s2"] = np.maximum(sn.s_heur.to_numpy(float), learned)
    sk = sn.set_index("row_key")
    bb = cb.copy(); bb["B"] = bb.row_key.map(sk.B)
    fac = dd.band_factor(bb, bb.B.to_numpy(float), bb.row_key.map(sk.s2).to_numpy(float))
    c = bb[["row_key", "band_index"]].assign(p=bb.p_served.to_numpy(float) * fac)
    c["p"] = c.p / c.groupby("row_key").p.transform("sum")
    c = c[c.row_key.isin(sk.index[sk.B.notna()])]
    r2_b, _ = snap_brier(c)

    LH = d.snaps.local_hour.to_numpy(); STR = d.snaps.stratum.to_numpy()
    Bk = np.floor(d.snaps.floor.to_numpy(float) + .5)
    collapsed = t5_use & (mus < Bk - 0.5)

    def paired(a, b, lo, hi, st, mask=None):
        m = (LH >= lo) & (LH <= hi) & (STR == st)
        dl = a - b
        if mask is not None:
            dl = np.where(mask, dl, 0.0)
        f = pd.DataFrame({"date": d.snaps.date[m].to_numpy(), "market": d.snaps.market[m].to_numpy(), "dl": dl[m]})
        cells = f.groupby(["date", "market"], sort=True).mean().reset_index()
        ix = np.array([d.key_index[(x, y)] for x, y in zip(cells.date, cells.market)])
        iv = h.interval(ix, cells.dl.to_numpy())
        pm = cells.groupby("market").dl.mean()
        return {"est": round(iv["estimate"], 5), "ci95": [round(v, 5) for v in iv["ci95"]],
                "mkts_neg": int((pm < 0).sum())}

    out = {"HARNESS_SHA256": h.harness_sha256(), "development": True}
    hours = {"13-16": (13, 16), "13-14": (13, 14), "15-16": (15, 16), "17-23": (17, 23)}
    for name, a, b in (("T5_minus_c1", t5_b, c1_b), ("T5_minus_T1r2", t5_b, t1_b),
                       ("T5_minus_ddr2", t5_b, r2_b), ("ddr2_minus_served", r2_b, served_b),
                       ("T1r2_minus_served", t1_b, served_b)):
        out[name] = {g: {st[:4]: paired(a, b, lo, hi, st) for st in (FROM, BEFORE)} for g, (lo, hi) in hours.items()}
    for g in ("13-16", "13-14", "15-16"):
        lo, hi = hours[g]
        m = (LH >= lo) & (LH <= hi)
        out.setdefault("collapse_share", {})[g] = float(collapsed[m].mean())
        out.setdefault("T5_minus_c1_by_state", {})[g] = {
            st[:4]: {"collapsed": paired(t5_b, c1_b, lo, hi, st, collapsed),
                     "open": paired(t5_b, c1_b, lo, hi, st, ~collapsed)} for st in (FROM, BEFORE)}
    (OUT / "t5_attribution.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
