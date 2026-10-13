"""T7 attribution controls t7-c1 (centre = captured NBM v2_mean) and t7-c2 (centre = captured
nws_grid_high), with t7-r1's history-fitted b_h/s_h (no refit). Development only; registered in
C:\\swarm\\registry.jsonl. Run after t7_mos_consensus (reads C:\\swarm\\out\\t7\\t7_meta.json).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h
from tools.research.model_parity.t7_mos_consensus import band_probs

OUT = Path(r"C:\swarm\out\t7")


def main():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")
    par = {int(k): v for k, v in json.loads((OUT / "t7_meta.json").read_text())["meta"]["r1"]["params"].items()}
    snaps, bands = h.candidate_inputs()
    cap = pd.to_datetime(snaps.captured_at_utc, utc=True, format="ISO8601")
    v2av = pd.to_datetime(snaps.v2_available_at, utc=True, format="ISO8601", errors="coerce")
    ok_v2 = snaps.v2_mean.notna() & v2av.notna() & (v2av <= cap)
    h.assert_point_in_time(v2av[ok_v2], cap[ok_v2])
    centres = {"c1": snaps.v2_mean.where(ok_v2), "c2": snaps.nws_grid_high}
    bands = bands.sort_values(["row_key", "band_index"])
    groups = {rk: b for rk, b in bands.groupby("row_key", sort=False)}
    for name, cen in centres.items():
        out = []
        for rk, c, hh in zip(snaps.row_key, cen, snaps.local_hour):
            if not np.isfinite(c):
                continue
            b = groups[rk]
            p = band_probs(b, c + par[int(hh)]["b1"], par[int(hh)]["s1"], False)
            if p.sum() > 0:
                out.append(pd.DataFrame({"row_key": rk, "band_index": b.band_index.to_numpy(), "p": p}))
        cand = pd.concat(out, ignore_index=True)
        res = h.score(cand, name=f"t7_{name}")
        h.save(res, OUT)
        print(h.markdown(res)); sys.stdout.flush()


if __name__ == "__main__":
    main()
