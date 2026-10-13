"""T16 auxiliary: paired r1 - r2 (headroom increment) and near-rounding-edge lens (development only).

Uses the harness's own floored candidate vector (h._candidate_vector) and W interval (h.interval);
no scoring formula is re-implemented beyond the per-snapshot band-mean squared error the harness uses.
Reads labels only through the harness data object, for scoring. Run after t16_settlement_mechanics.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h
from tools.research.model_parity.t16_settlement_mechanics import OUT, load_station, state, TZ


def snap_loss(d, cand):
    pc, use, _ = h._candidate_vector(cand, d, False)
    return np.add.reduceat((pc - d.y) ** 2, d.offsets) / d.snaps.n_bands.to_numpy(), use


def cell_interval(d, frame, col):
    cells = frame.groupby(["date", "market"], sort=True)[col].mean().reset_index()
    idx = np.array([d.key_index[(a, b)] for a, b in zip(cells.date, cells.market)])
    out = h.interval(idx, cells[col].to_numpy())
    out["market_days"] = int(len(cells))
    out["snapshots"] = int(len(frame))
    return out


def main():
    d = h.data()
    z = np.load(OUT / "t16_probs_lag10.npz", allow_pickle=False)
    base = pd.DataFrame({"row_key": z["row_key"], "band_index": z["band_index"]})
    losses = {}
    for k in ("p1", "p2"):
        p = z[k]
        cov = ~np.isnan(p)
        c = base[cov].assign(p=p[cov])
        c = c[c.groupby("row_key").p.transform("sum") > 0]
        losses[k], _ = snap_loss(d, c)
    served = np.add.reduceat(d.se_served, d.offsets) / d.snaps.n_bands.to_numpy()
    f = d.snaps[["row_key", "date", "market", "stratum", "local_hour", "station", "captured_at_utc"]].copy()
    f["r1_minus_r2"] = losses["p1"] - losses["p2"]
    f["r1_minus_served"] = losses["p1"] - served
    # headroom state for the near-edge lens (state only, PIT as in the main module)
    hb = pd.Series(-1, index=f.index)
    for st, g in f.groupby("station"):
        s, _ = load_station(st)
        ok, M, T, db, sb, hbin, H, av = state(s, g.captured_at_utc, g.date.to_numpy())
        hb.loc[g.index] = np.where(ok, hbin, -1)
    f["hb"] = hb.to_numpy()
    blocks = {"00-16": (0, 16), "13-16": (13, 16), "17-23": (17, 23), "all": (0, 23)}
    out = {"HARNESS_SHA256": h.harness_sha256(), "development": True}
    for bname, (lo, hi) in blocks.items():
        for stratum in ("before_20260823", "from_20260823"):
            m = f.local_hour.between(lo, hi) & (f.stratum == stratum)
            out[f"{bname}|{stratum}|r1-r2|all"] = cell_interval(d, f[m], "r1_minus_r2")
            for b in (0, 1, 2):
                mm = m & (f.hb == b)
                if mm.sum() > 50:
                    out[f"{bname}|{stratum}|r1-r2|hb{b}"] = cell_interval(d, f[mm], "r1_minus_r2")
                    out[f"{bname}|{stratum}|r1-served|hb{b}"] = cell_interval(d, f[mm], "r1_minus_served")
    json.dump(out, open(OUT / "t16_paired.json", "w"), indent=1)
    for k, v in out.items():
        if isinstance(v, dict):
            print(k, round(v["estimate"], 6), [round(x, 6) for x in v["ci95"]], v["market_days"], v["snapshots"])


if __name__ == "__main__":
    main()
