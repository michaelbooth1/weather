"""R-PIT-T7 refuter: re-run T7 r1/r2/r4 with availability shifted for ALL models (incl. measured NBE).

Development only. Not a new rule (refuter sensitivity of registered t7-r1/r2/r4). Reuses the T7 module's
functions unchanged; only the availability column is shifted (+1 h, +2 h), in both the history fit and
scoring, exactly as t7-r3 did for the unmeasured lags. Also: n_x/txn valid-hour sensitivity (14:00/16:00
instead of the a-priori 15:00) for r2, to check that the 15:00 choice is not a tuned hour gate.
Run from C:\\pt\\swarm:  <repo python> -m tools.research.model_parity.r-pit-t7_shift  (via runpy)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from tools.research.model_parity import harness as h
from tools.research.model_parity import t7_mos_consensus as t7

OUT = Path(r"C:\swarm\out\refute-pit-t7")
BLOCKS = ["00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all"]


def summarise(res):
    row = {}
    for g in BLOCKS:
        t = h.table_lookup(res, g, "from_20260823", "all_row")["candidate_minus_served"]
        tb = h.table_lookup(res, g, "before_20260823", "all_row")["candidate_minus_served"]
        row[g] = {"from": round(t["estimate"], 6), "ci95": [round(x, 6) for x in t["ci95"]],
                  "before": round(tb["estimate"], 6), "class": res["classes"][g]["class"]}
    return {"name": res.get("name"), "candidate_share": res.get("candidate_share"),
            "leakage_suspect_groups": res.get("leakage_suspect_groups"), "blocks": row}


def make_day_bounds(peak_h):
    def day_bounds(station, date):
        tz = ZoneInfo(t7.STATIONS[station]["tzname"])
        d0 = datetime.fromisoformat(date).replace(tzinfo=tz)
        start = pd.Timestamp(d0).value
        end = pd.Timestamp(d0 + timedelta(days=1)).value
        peak = pd.Timestamp(d0 + timedelta(hours=peak_h)).value
        l10 = pd.Timestamp(d0 + timedelta(hours=10)).value
        l18 = pd.Timestamp(d0 + timedelta(hours=18)).value
        nx_ft = pd.Timestamp(date, tz="UTC").value + 24 * t7.NS_H
        return start, end, peak, l10, l18, nx_ft
    return day_bounds


def run(tag, lag, models, which, peak_h=15):
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")
    t7.MEASURED = set()            # shift every model, including the measured NBE
    t7.day_bounds = make_day_bounds(peak_h)
    runs = t7.load_runs(lag)
    par, _ = t7.fit(runs, models, TRUTH)
    rec = t7.build(runs, models, par, SNAPS, BANDS, check_pit=True)
    cand = t7.candidates(rec, par, BANDS, which)
    res = h.score(cand, name=f"refute_pit_t7_{tag}")
    h.save(res, OUT)
    s = summarise(res)
    s.update(lag_all_models_h=lag, models=models, rule=which, peak_h=peak_h, HARNESS_SHA256=h.harness_sha256())
    print(json.dumps(s), flush=True)
    return s


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    SNAPS, BANDS = h.candidate_inputs()
    assert (SNAPS.date > "2026-09-29").sum() == 0
    TRUTH = t7.metar_truth()
    all5 = list(t7.MODELS)
    jobs = [("r2_base_check", 0.0, all5, "r2", 15),
            ("r1_all+1h", 1.0, all5, "r1", 15), ("r2_all+1h", 1.0, all5, "r2", 15),
            ("r1_all+2h", 2.0, all5, "r1", 15), ("r2_all+2h", 2.0, all5, "r2", 15),
            ("r4_nbe+1h", 1.0, ["NBE"], "r2", 15), ("r4_nbe+2h", 2.0, ["NBE"], "r2", 15),
            ("r2_peak14", 0.0, all5, "r2", 14), ("r2_peak16", 0.0, all5, "r2", 16)]
    only = set(sys.argv[1:])
    out = []
    for j in jobs:
        if only and j[0] not in only:
            continue
        out.append(run(*j))
        (OUT / "shift_results.json").write_text(json.dumps(out, indent=1))
