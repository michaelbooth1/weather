"""T9 extra paired marginals (development only; registers nothing, all candidates already registered):
t9-r1 / t9-r2 vs r-t5-inc-c1 (captured NBM v2_mean control, the known 79a/81a/111h morning route),
rebuilt with R-T5-INC's exact construction (t5 band_probs, sigma = max(v2_stddev, 1)).

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.t9_extra_pairs
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h
from tools.research.model_parity import t5_nbh_latest as t5
from tools.research.model_parity import t9_hrrr_lagged_ensemble as t9

OUT = Path(r"C:\swarm\out\t9")


def main():
    t9.check_registered()
    snaps, bands = h.candidate_inputs()
    bands = bands.reset_index(drop=True)
    d = h.data()
    offs = d.offsets
    meta = json.loads((OUT / "t9_meta.json").read_text(encoding="utf-8"))
    p4 = {int(k): v for k, v in meta["params_r1"].items()}
    runs = t9.load_runs(0.0)
    mu4, sd4, n4, _ = t9.serve_members(runs, snaps, 4)
    hh = snaps.local_hour.to_numpy()
    b = lambda k: np.array([p4[int(x)][k] for x in hh])
    r1 = t9.cand_from(mu4 + b("b"), b("s"), snaps, bands, offs)
    r2 = t9.cand_from(mu4 + b("b"), np.sqrt(b("s0") ** 2 + np.nan_to_num(sd4) ** 2), snaps, bands, offs)
    # r-t5-inc-c1 exactly as in r-t5-inc_refute.py
    cap = pd.to_datetime(snaps.captured_at_utc, utc=True, format="ISO8601")
    v2av = pd.to_datetime(snaps.v2_available_at, utc=True, format="ISO8601", errors="coerce")
    ok = (snaps.v2_mean.notna() & snaps.v2_stddev.notna() & v2av.notna() & (v2av <= cap) & snaps.floor.notna())
    h.assert_point_in_time(v2av[ok], cap[ok])
    nb = snaps.n_bands.to_numpy()
    kinds, lows, highs = bands.kind.to_numpy(), bands.low.to_numpy(), bands.high.to_numpy()
    p_out = np.full(len(bands), np.nan)
    for i in np.flatnonzero(ok.to_numpy()):
        mu = float(snaps.v2_mean.iat[i]); sig = max(float(snaps.v2_stddev.iat[i]), t5.SIG_MIN)
        B = math.floor(float(snaps.floor.iat[i]) + .5)
        o, n = offs[i], nb[i]
        p = t5.band_probs(kinds[o:o + n], lows[o:o + n], highs[o:o + n], B, mu, sig)
        if p.sum() > 0:
            p_out[o:o + n] = p / p.sum()
    cov = ~np.isnan(p_out)
    c1 = bands.loc[cov, ["row_key", "band_index"]].assign(p=p_out[cov])
    rc1 = h.score(c1, name="t9_rebuilt_r-t5-inc-c1")
    fr = d.snaps[["row_key", "date", "market", "stratum", "local_hour"]].copy()
    for name, c in {"t9-r1": r1, "t9-r2": r2, "r-t5-inc-c1": c1}.items():
        pc, _ = t9.floored(c, d)
        fr[name] = np.add.reduceat((pc - d.y) ** 2, d.offsets) / nb
    # 50/50 equal-weight blend (POST-HOC diagnostic only, not a candidate): does HRRR add to v2?
    out = {"rebuilt_c1_00-16_from": h.table_lookup(rc1, "00-16", "from_20260823")["candidate_minus_served"],
           "rebuilt_c1_06-09_from": h.table_lookup(rc1, "06-09", "from_20260823")["candidate_minus_served"],
           "paired": [t9.paired(d, fr, "t9-r1", "r-t5-inc-c1", "HRRR lagged ensemble vs captured NBM v2_mean control"),
                      t9.paired(d, fr, "t9-r2", "r-t5-inc-c1", "HRRR lagged ensemble+spread vs captured v2_mean control")]}
    (OUT / "t9_extra_pairs.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    for pr in out["paired"]:
        print(pr["pair"], {g: (round(v[t9.FROM]["estimate"], 5), [round(x, 5) for x in v[t9.FROM]["ci95"]],
                               v[t9.FROM]["markets_negative"], round(v[t9.BEFORE]["estimate"], 5))
                           for g, v in pr["tables"].items()}, flush=True)
    print("c1 rebuilt", out["rebuilt_c1_00-16_from"]["estimate"])


if __name__ == "__main__":
    main()
