"""T26 sensitivity (no new rule): re-run registered T1-r2 (frozen X,N,H,q) with METAR availability
max(valid+10 min, AWC receiptTime) for rows inside the AWC window (2026-09-04..09-29 UTC); rows outside
the window keep valid+10. Compared with T1-r2 at its own basis on the same population. Development only."""
import json
from pathlib import Path
import pandas as pd
from tools.research.model_parity import harness as h
from tools.research.model_parity import t1_decided_band as t1
from tools.research.model_parity import t26_metar_pit as t26

OUT = Path(r"C:\swarm\out\t26")
a = t26.load_awc()
rec = (a[~a.is_cor].sort_values("receipt_utc").groupby(["station", "valid_utc"]).receipt_utc.first())
orig = t1.load_metar


def load_receipt(station):
    m = orig(station)
    r = rec.xs(station, level=0) if station in rec.index.get_level_values(0) else pd.Series(dtype="datetime64[ns, UTC]")
    rr = m.valid_utc.map(r)
    m["available_utc"] = pd.concat([m.available_utc, rr], axis=1).max(axis=1)
    return m.sort_values("available_utc").reset_index(drop=True)


params = json.loads((t1.OUT / "fit_params.json").read_text(encoding="utf-8"))
snaps, bands = h.candidate_inputs()
assert (snaps.date <= "2026-09-29").all()
res = {}
for basis, loader in [("A_valid10", orig), ("Ap_max_valid10_receipt", load_receipt)]:
    t1.load_metar = loader
    obs = t1.snapshot_obs(snaps)
    cand, n = t1.build(snaps, bands, obs, params, "r2")
    for pop, where in [("all_dates", None), ("awc_window_ge_0905", lambda s: s.date >= "2026-09-05")]:
        r = h.score(cand, name=f"t26_t1r2_{basis}_{pop}", where=where)
        h.save(r, str(OUT))
        out = {"decided_snapshots": n, "classes_17_23": r["classes"]["17-23"].get("class") if isinstance(r["classes"]["17-23"], dict) else r["classes"]["17-23"]}
        for g in ["13-16", "17-23", "00-16", "all"]:
            for st in ["pooled", "from_20260823"]:
                try:
                    t = h.table_lookup(r, g, st, "all_row")
                    out[f"{g}|{st}"] = t["candidate_minus_served"]
                except Exception as e:
                    out[f"{g}|{st}"] = str(e)
        out["harness"] = r.get("harness_sha256") or r.get("HARNESS_SHA256")
        res[f"{basis}|{pop}"] = out
t1.load_metar = orig
(OUT / "t1_receipt_sensitivity.json").write_text(json.dumps(res, indent=1, default=str))
print(json.dumps(res, indent=1, default=str))
