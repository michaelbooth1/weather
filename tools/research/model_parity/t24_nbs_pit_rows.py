"""T24 (spare): quantify how many scored rows change under independently re-derived NBS availability.

Development only; registers no rules. Imports T6's code unchanged and swaps only the availability map.
Bases (per blend_nbstx object):
  B0  A-NBH MANIFEST s3_last_modified (what T6 / refuters used)
  B1  T24's own HEAD Last-Modified, re-measured 2026-10-04 (s3_remeasure.jsonl)
  B2  B1 + 5 min   (realistic production poll / ingest latency)
  B3  B1 + 15 min
  B5  counterfactual, late objects only: objects > 30 min over their cycle-hour median moved to that median
      (28 objects; 13 of them are the 2026-09-24 00-12Z S3 backlog). NOT PIT-admissible either.
  B4  counterfactual "on time": min(B1, cycle + that cycle-hour's median lag) -- NOT PIT-admissible
      (no first-availability evidence exists for re-uploaded objects; bucket unversioned). Upper bound of
      what the conservative basis can be costing.
Counts per basis: snapshots whose r2 (mode, cycle, mu, sigma) change vs B0, by block; then harness score
of t6-r2 / t6-r3 (r3 params frozen at the B0 fit) for B1 and B4 and the delta vs B0.
Run: cd C:\\pt\\swarm; <repo python> tools\\research\\model_parity\\t24_nbs_pit_rows.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\pt\swarm")
from tools.research.model_parity import harness as h  # noqa: E402
from tools.research.model_parity import t6_nbs_latest as t6  # noqa: E402

OUT = Path(r"C:\swarm\out\t24")
REM = OUT / "s3_remeasure.jsonl"
GROUPS = ("00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all")
SHA = "8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74"


def stop():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")


def maps():
    m0 = t6.lastmodified_map()  # B0 (ledger + manifest), exactly as T6
    m1 = {}
    for line in REM.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["head"].get("status") == 200:
            m1[(r["date"], int(r["cycle"]))] = pd.Timestamp(r["head"]["last_modified"]).tz_convert("UTC")
    assert set(m1) == set(m0), (len(m1), len(m0))
    lag = pd.DataFrame([(k[1], (v - (pd.Timestamp(k[0], tz="UTC") + pd.Timedelta(hours=k[1]))))
                        for k, v in m1.items()], columns=["hh", "lag"])
    med = lag.groupby("hh").lag.median()
    m4 = {k: min(v, pd.Timestamp(k[0], tz="UTC") + pd.Timedelta(hours=k[1]) + med[k[1]]) for k, v in m1.items()}
    m5 = {k: (m4[k] if (m1[k] - m4[k]) > pd.Timedelta(minutes=30) else v) for k, v in m1.items()}
    bases = {"B0": (m0, 0), "B1": (m1, 0), "B2": (m1, 5), "B3": (m1, 15), "B4": (m4, 0), "B5": (m5, 0)}
    diff01 = sum(1 for k in m0 if m0[k] != m1[k])
    moved4 = {f"{k[0]} {k[1]:02d}Z": round((m1[k] - m4[k]).total_seconds() / 60, 1) for k in m1 if m4[k] < m1[k]}
    return bases, diff01, moved4, med


def params_for(cycles, s):
    idx = {st: t6.StationIndex(c) for st, c in cycles.items()}
    out = []
    for st, t, dn, end in s[["station", "t_ns", "dnext00_ns", "end_ns"]].to_numpy():
        si = idx.get(st)
        mp = None if si is None else t6.mode_params(si, int(t), int(dn), int(end), "r2")
        if mp is None:
            out.append(("NONE", np.nan, np.nan, -1))
        else:
            out.append((mp[0], float(mp[1]), float(mp[2]), int(mp[3]["cycle"].value)))
    return out


def brief(res):
    o = {}
    for g in GROUPS:
        t = h.table_lookup(res, g, "from_20260823", "all_row")
        c = t["candidate_minus_served"]
        o[g] = {"class": res["classes"][g]["class"], "est": c["estimate"], "ci95": c["ci95"],
                "mkts_neg": t.get("markets_negative")}
    return o


def main():
    stop()
    assert h.harness_sha256() == SHA
    bases, diff01, moved4, med = maps()
    print("B0 vs B1 differing objects:", diff01, "; B4 moved objects:", len(moved4), flush=True)
    s, bands = t6.snapshot_frame()
    assert (s.date <= "2026-09-29").all()
    real_lm = t6.lastmodified_map
    cyc = {}
    for b, (mp, lag) in bases.items():
        t6.lastmodified_map = (lambda m=mp: dict(m))
        cyc[b] = t6.load_cycles(lag)[0]
    t6.lastmodified_map = real_lm
    par = {b: params_for(cyc[b], s) for b in bases}
    summary = {"HARNESS_SHA256": h.harness_sha256(), "objects_B0_ne_B1": diff01,
               "B4_objects_moved_earlier_min": moved4,
               "median_lag_min_by_cycle": {int(k): round(v.total_seconds() / 60, 1) for k, v in med.items()},
               "n_snapshots": len(s), "changes_vs_B0": {}, "scores": {}}
    blocks = s.block.to_numpy()
    dates = s.date.astype(str).to_numpy()
    for b in bases:
        if b == "B0":
            continue
        ch = {"any": Counter(), "cycle": Counter(), "mode": Counter(), "mu_or_sigma": Counter(),
              "coverage": Counter(), "by_target_date": Counter()}
        for i, (a, c) in enumerate(zip(par["B0"], par[b])):
            if a == c or (a[0] == c[0] and a[3] == c[3] and np.allclose(a[1:3], c[1:3], equal_nan=True)):
                continue
            blk = blocks[i]
            ch["any"][blk] += 1
            ch["by_target_date"][dates[i]] += 1
            if a[3] != c[3]:
                ch["cycle"][blk] += 1
            if a[0] != c[0]:
                ch["mode"][blk] += 1
            if (a[0] == "NONE") != (c[0] == "NONE"):
                ch["coverage"][blk] += 1
            if a[0] == c[0] and not np.allclose(a[1:3], c[1:3], equal_nan=True):
                ch["mu_or_sigma"][blk] += 1
        summary["changes_vs_B0"][b] = {k: dict(sorted(v.items())) | {"total": sum(v.values())}
                                       for k, v in ch.items()}
        print(b, summary["changes_vs_B0"][b]["any"], flush=True)
    cyc0 = cyc["B0"]
    params, _ = t6.fit_r3(t6.load_cycles(0)[0])
    for b in ("B0", "B1", "B4", "B5"):
        stop()
        for rid, prm in (("t6-r2", None), ("t6-r3", params)):
            cand, modes, ages = t6.build_candidate("r2", cyc[b], s, bands, prm)
            if b not in ("B4", "B5"):
                t6.full_pit_check(cyc[b], s, "r2")
            res = h.score(cand, name=f"t24_{rid.replace('-', '_')}_{b}")
            assert res["rows_with_target_after_2026_09_29"] == 0
            if res["leakage_suspect_groups"]:
                Path(r"C:\swarm\STOP").write_text(f"t24 leakage suspect {rid} {b}\n")
                sys.exit("leakage suspect")
            h.save(res, OUT)
            summary["scores"][f"{rid}|{b}"] = brief(res)
            print(b, rid, {g: (v["class"], round(v["est"], 5)) for g, v in summary["scores"][f"{rid}|{b}"].items()},
                  flush=True)
    _ = cyc0
    (OUT / "t24_rows.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
