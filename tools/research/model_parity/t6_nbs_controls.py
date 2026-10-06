"""T6 controls and paired marginals (model-parity swarm v2, development only).

Controls (registered before scoring; not candidates, scored only to attribute t6-r2/t6-r3):
  t6-c1  schedule-only collapse, NO NBS VALUES: same PIT cycle selection as t6-r2 decides the mode;
         TXN-mode rows -> served fallback (no candidate); REM/REM0-mode rows -> X = -inf, i.e. all mass
         on the floor band (H = B). r2 - c1 isolates the NBS TMP/TXN values from "collapse once the
         latest bulletin no longer carries today's max".
  t6-c2  captured-NBM centre: identical to t6-r2 except in TXN mode the centre and spread are the
         snapshot's captured NBM v2_mean and max(v2_stddev, 1) (only where v2_available_at <=
         captured_at_utc; else served fallback). REM rows identical to t6-r2. r2 - c2 isolates NBS TXN
         against what production already captures.
Paired marginals (W intervals via harness.interval, identical floor/fallback through the harness's own
candidate-vector builder): r2/r3 vs t3-r3 rung, vs c1, vs c2; c1 vs t3-r3.

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.t6_nbs_controls
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h
from tools.research.model_parity import t6_nbs_latest as t6
from tools.research.model_parity import t3_baselines as t3

OUT = Path(r"C:\swarm\out\t6")
FROM, BEFORE = "from_20260823", "before_20260823"
GROUPS = {"00-05": (0, 5), "06-09": (6, 9), "10-12": (10, 12), "13-16": (13, 16), "17-23": (17, 23),
          "00-16": (0, 16), "all": (0, 23)}

RULES = {
    "t6-c1": "T6-c1 CONTROL (attribution only): schedule-only collapse with no NBS values. Mode from the "
             "t6-r2 PIT cycle selection (latest NBS cycle with S3 LastModified <= captured_at_utc). TXN mode "
             "-> served fallback. REM or REM0 mode -> X = -inf, all mass on the floor band B = floor(F+0.5), "
             "F = harness rule-4 floor. Paired with t6-r2/r3 to isolate the NBS values.",
    "t6-c2": "T6-c2 CONTROL (attribution only): identical to t6-r2 except in TXN mode mu = captured NBM "
             "v2_mean and sigma = max(v2_stddev, 1) (only where v2_available_at <= captured_at_utc; else "
             "served fallback). REM/REM0 rows as t6-r2. Paired with t6-r2 to isolate NBS TXN against the "
             "captured NBM v2 centre.",
}


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def register():
    reg = Path(r"C:\swarm\registry.jsonl")
    have = {json.loads(x)["id"] for x in reg.read_text(encoding="utf-8").splitlines() if x.strip()}
    for rid, text in RULES.items():
        if rid in have:
            continue
        rec = {"id": rid, "agent": "t6", "text": text,
               "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
               "time_local": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
        with open(reg, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")


def build_controls(cycles, s, bands, snaps_full):
    idx = {st: t6.StationIndex(c) for st, c in cycles.items()}
    offs = np.concatenate([[0], np.cumsum(s.n_bands.to_numpy())[:-1]]).astype(int)
    kinds, lows, highs = bands.kind.to_numpy(), bands.low.to_numpy(), bands.high.to_numpy()
    p1 = np.full(len(bands), np.nan)
    p2 = np.full(len(bands), np.nan)
    v2m = snaps_full.v2_mean.to_numpy(float)
    v2s = snaps_full.v2_stddev.to_numpy(float)
    v2a = pd.to_datetime(snaps_full.v2_available_at, utc=True, errors="coerce")
    cap = pd.to_datetime(snaps_full.captured_at_utc, utc=True)
    v2ok = (v2a.notna() & (v2a <= cap) & np.isfinite(v2m)).to_numpy()
    # rule 1 tripwire on every v2 value used
    h.assert_point_in_time(list(v2a[v2ok]), list(cap[v2ok]))
    recs = s[["station", "t_ns", "end_ns", "dnext00_ns", "floor", "n_bands"]].to_numpy()
    av, cp = [], []
    modes = np.full(len(s), "NONE", dtype=object)
    for i, (st, t, end, dn, F, n) in enumerate(recs):
        si = idx.get(st)
        if si is None or F is None or not np.isfinite(F):
            continue
        mp = t6.mode_params(si, int(t), int(dn), int(end), "r2")
        if mp is None:
            continue
        mode, mu, sig, c = mp
        modes[i] = mode
        av.append(c["avail"])
        cp.append(pd.Timestamp(int(t), tz="UTC"))
        B = math.floor(float(F) + .5)
        o = offs[i]
        sl = slice(o, o + n)
        if mode in ("REM", "REM0"):
            q = t6.band_probs(kinds[sl], lows[sl], highs[sl], B, -math.inf, 1.0)
            if q.sum() > 0:
                p1[sl] = q / q.sum()
            q = t6.band_probs(kinds[sl], lows[sl], highs[sl], B, mu, sig)
            if q.sum() > 0:
                p2[sl] = q / q.sum()
        elif mode == "TXN" and v2ok[i]:
            q = t6.band_probs(kinds[sl], lows[sl], highs[sl], B, v2m[i], max(v2s[i] if np.isfinite(v2s[i]) else 1., 1.))
            if q.sum() > 0:
                p2[sl] = q / q.sum()
    h.assert_point_in_time(av, cp)
    out = {}
    for name, p in (("t6-c1", p1), ("t6-c2", p2)):
        cov = ~np.isnan(p)
        c = bands.loc[cov, ["row_key", "band_index"]].copy()
        c["p"] = p[cov]
        out[name] = c
    return out, modes


def paired(d, frames, pairs):
    """frames: name -> floored per-band prob vector (harness _candidate_vector). Paired a - b tables."""
    fr = d.snaps[["row_key", "date", "market", "stratum", "local_hour"]].copy()
    for k, pc in frames.items():
        fr[k] = h._snapshot_mean(d, (pc - d.y) ** 2)
    fr["served"] = h._snapshot_mean(d, d.se_served)
    fr["market_loss"] = h._snapshot_mean(d, d.se_market)
    out = {}
    for a, b in pairs:
        res = {}
        for g, (lo, hi) in GROUPS.items():
            for stt in (BEFORE, FROM, "pooled"):
                m = fr.local_hour.between(lo, hi)
                if stt != "pooled":
                    m &= fr.stratum == stt
                c = fr[m].groupby(["date", "market"], sort=True)[[a, b]].mean().reset_index()
                idx = np.array([d.key_index[(x, y)] for x, y in zip(c.date, c.market)])
                diff = (c[a] - c[b]).to_numpy()
                iv = h.interval(idx, diff)
                pm = c.assign(dd=diff).groupby("market").dd.mean()
                res[f"{g}|{stt}"] = {"estimate": iv["estimate"], "ci95": iv["ci95"],
                                     "markets_negative": int((pm < 0).sum()),
                                     "markets_positive": int((pm > 0).sum()), "market_days": int(len(c))}
        out[f"{a} - {b}"] = res
    return out


def main():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")
    register()
    d = h.data()
    log("loading cycles")
    cycles, info = t6.load_cycles()
    s, bands = t6.snapshot_frame()
    snaps_full, _ = h.candidate_inputs()
    assert (snaps_full.row_key.to_numpy() == s.row_key.to_numpy()).all()
    assert (s.date <= "2026-09-29").all()
    params, _ = t6.fit_r3(cycles)
    log("r3 params", params)
    cands = {}
    cands["t6-r2"], _, _ = t6.build_candidate("r2", cycles, s, bands, None)
    cands["t6-r3"], _, _ = t6.build_candidate("r2", cycles, s, bands, params)
    ctl, modes = build_controls(cycles, s, bands, snaps_full)
    cands.update(ctl)
    t3c, _ = t3.build()
    cands["t3-r3"] = t3c["t3-r3"]
    results = {}
    for name in ("t6-c1", "t6-c2"):
        if Path(r"C:\swarm\STOP").exists():
            sys.exit("STOP present")
        res = h.score(cands[name], name=name.replace("-", "_") + "_control")
        assert res["rows_with_target_after_2026_09_29"] == 0
        if res["leakage_suspect_groups"]:
            Path(r"C:\swarm\STOP").write_text(f"t6 leakage suspect {name} {res['leakage_suspect_groups']}\n")
            sys.exit("leakage suspect")
        h.save(res, OUT)
        (OUT / f"{res['name']}.md").write_text(h.markdown(res), encoding="utf-8")
        results[name] = {g: v["class"] for g, v in res["classes"].items()}
        log(name, results[name])
        print(h.markdown(res))
    frames = {}
    for k, c in cands.items():
        pc, use, _ = h._candidate_vector(c, d, False)
        frames[k] = pc
    pairs = [("t6-r2", "t3-r3"), ("t6-r3", "t3-r3"), ("t6-c1", "t3-r3"), ("t6-r2", "t6-c1"),
             ("t6-r3", "t6-c1"), ("t6-r2", "t6-c2"), ("t6-r3", "t6-r2")]
    pr = paired(d, frames, pairs)
    mc = pd.Series(modes).value_counts().to_dict()
    mb = pd.crosstab(s.block.to_numpy(), modes)
    out = {"agent": "t6", "HARNESS_SHA256": h.harness_sha256(), "control_classes": results,
           "paired": pr, "modes": {k: int(v) for k, v in mc.items()},
           "mode_by_block": {r: {c: int(mb.loc[r, c]) for c in mb.columns} for r in mb.index}}
    (OUT / "t6_controls.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    for k, v in pr.items():
        print("==", k)
        for g in GROUPS:
            r = v[f"{g}|{FROM}"]
            rb = v[f"{g}|{BEFORE}"]
            print(f"  {g:6s} from {r['estimate']:+.6f} [{r['ci95'][0]:+.6f},{r['ci95'][1]:+.6f}] "
                  f"{r['markets_negative']}/{r['markets_positive']}  before {rb['estimate']:+.6f}")
    print(json.dumps(out["mode_by_block"]))
    log("done")


if __name__ == "__main__":
    main()
