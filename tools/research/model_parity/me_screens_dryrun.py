"""Model-edge week-1 development screens: H2 dry run (OUTCOME-FREE by construction).

Imports only the outcome-free v3 modules (v3_gate, v3_inputs, v3_arms, v3_dryrun); never names or
opens a label or market file. Run through ``test_me_screens_dev.py`` (phase ``dryrun``) under
``scripts\\ops\\workstation_heavy.ps1 -Kind pytest -Queue``.

Besides the v3 dry run per arm it records the outcome-free facts the screens need to decide what
can be screened on this workstation:

- lever 7: whether the captured ``open_meteo_hrrr_high_delta`` (forecast_high + delta = the
  Open-Meteo multimodel HRRR day high) is the same quantity as the captured ``hrrr_high`` the v2 swarm
  already tested (t8-c2, t9-c2); v2 quantile coverage;
- lever 13: ``trusted_current_max`` coverage (the lever-5 open stage 13 input);
- lever 6: which markets the dev layout holds (Toronto is not in it).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import v3_dryrun, v3_gate, v3_inputs

HERE = Path(__file__).resolve().parent
ARMS = ("me_arm_l7_v2q.py", "me_arm_l13_bt.py", "v3_arm_mg1_like.py", "v3_arm_served.py")


def input_facts(snaps):
    num = lambda c: pd.to_numeric(snaps[c], errors="coerce")
    fh, dl, hr = num("forecast_high"), num("open_meteo_hrrr_high_delta"), num("hrrr_high")
    implied = fh + dl
    both = implied.notna() & hr.notna()
    diff = (implied - hr)[both].abs()
    q = ["v2_p10", "v2_p25", "v2_p50", "v2_p75", "v2_p90"]
    qok = snaps[q].apply(pd.to_numeric, errors="coerce").notna().all(axis=1)
    avail = pd.to_datetime(snaps.v2_available_at, utc=True, errors="coerce")
    cap = pd.to_datetime(snaps.captured_at_utc, utc=True, errors="coerce")
    pit = qok & avail.notna() & (avail <= cap)
    mean_ok = num("v2_mean").notna() & num("v2_stddev").notna() & avail.notna() & (avail <= cap)
    tcm = num("trusted_current_max")
    return {
        "markets": sorted(snaps.market.astype(str).unique()),
        "toronto_rows": int((snaps.market.astype(str) == "toronto").sum()),
        "dates": [str(snaps.date.min()), str(snaps.date.max())], "snapshots": int(len(snaps)),
        "om_hrrr_implied_vs_hrrr_high": {
            "implied_present": int(implied.notna().sum()), "hrrr_high_present": int(hr.notna().sum()),
            "both_present": int(both.sum()),
            "abs_diff_quantiles": diff.quantile([0, .5, .9, .99, 1]).round(4).tolist() if len(diff) else None,
            "share_abs_diff_le_0p05": float((diff <= 0.05).mean()) if len(diff) else None,
            "share_abs_diff_le_0p5": float((diff <= 0.5).mean()) if len(diff) else None,
            "implied_present_without_hrrr_high": int((implied.notna() & hr.isna()).sum())},
        "v2_quantiles": {"all_five_present": int(qok.sum()), "pit_usable": int(pit.sum()),
                         "mg1_mean_sd_pit_usable": int(mean_ok.sum()),
                         "pit_usable_not_mg1": int((pit & ~mean_ok).sum())},
        "trusted_current_max": {"present": int(tcm.notna().sum()),
                                "by_market": tcm.notna().groupby(snaps.market.astype(str)).sum().astype(int).to_dict()},
        "high_so_far_present": int(num("high_so_far").notna().sum()),
    }


def run(layout, gate=None, purpose="development"):
    gate = gate or v3_gate.default_gate()
    out = {"purpose_requested": purpose, "gate": gate.identity(), "arms": {}}
    for name in ARMS:
        rep = v3_dryrun.dry_run(layout, [str(HERE / name)], purpose, gate)
        arm = next(iter(rep["arms"].values()))
        out["totals"], out["blocks"], out["markets"] = rep["totals"], rep["blocks"], rep["markets"]
        out["arms"][name] = {k: arm[k] for k in ("family", "reads_nbm_guidance", "declared_inputs", "code_sha256",
                                                  "eligible", "eligible_and_countable", "refused_dates")} | {
            "block_eligible_share": {g: b["eligible_share"] for g, b in arm["blocks"].items()},
            "market_eligible": {m: v["eligible"]["rows"] for m, v in arm["markets"].items()}}
    snaps, _, _ = v3_inputs.read_inputs(layout, gate, "model_edge_screen_coverage", False, purpose="coverage")
    out["input_facts"] = input_facts(snaps)
    out["outcome_free"] = True
    return out
