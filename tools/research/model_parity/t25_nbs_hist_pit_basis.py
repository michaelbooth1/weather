"""T25 (spare): PIT-basis sensitivity of t6-r3's history fit (IEM mos_NBS). Development only.

Registers no rules. Re-fits t6-r3's (b, s) with the history-cycle availability basis replaced
(cycles < 2026-08-01 only; evaluation inputs keep their measured S3 LastModified), rebuilds the
t6-r3 candidate with the hunter's own code, scores it with the harness, and counts changed rows.
Run: cd C:\pt\swarm; <repo python> -m tools.research.model_parity.t25_nbs_hist_pit_basis
"""
from __future__ import annotations
import copy, json, sys
from pathlib import Path
import numpy as np, pandas as pd
from tools.research.model_parity import harness as h
from tools.research.model_parity import t6_nbs_latest as t6

OUT = Path(r"C:\swarm\out\t25")
CUT = pd.Timestamp("2026-08-01T00:00Z")
GROUPS = ("00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all")


def per_hour_median_lag():
    lags = {}
    for line in open(r"C:\swarm\data\iem\mos\nbm_text_lastmodified.jsonl", encoding="utf-8"):
        r = json.loads(line)
        o = r.get("objects", {}).get(f"blend_nbstx.t{r['hour']:02d}z")
        if o:
            c = pd.Timestamp(f"{r['date']}T{r['hour']:02d}:00Z")
            lags.setdefault(r["hour"], []).append((pd.Timestamp(o["last_modified"]) - c).total_seconds())
    led = Path(r"C:\swarm\data\nbh\ledger.jsonl")
    for line in led.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("product") == "nbs" and r.get("status") == "ok" and r.get("s3_last_modified"):
            c = pd.Timestamp(f"{r['date']}T{int(r['cycle']):02d}:00Z")
            lags.setdefault(int(r["cycle"]), []).append((pd.Timestamp(r["s3_last_modified"]) - c).total_seconds())
    return {hh: pd.Timedelta(seconds=float(np.median(v))) for hh, v in lags.items()}


def variant(cycles, kind):
    med = per_hour_median_lag() if kind == "nominal_median_lag" else None
    out = {}
    for st, lst in cycles.items():
        new = []
        for x in lst:
            if x["cycle"] >= CUT:
                new.append(x); continue
            y = dict(x)
            if kind == "plus60":
                y["avail"] = x["avail"] + pd.Timedelta(minutes=60)
            elif kind == "plus120":
                y["avail"] = x["avail"] + pd.Timedelta(minutes=120)
            elif kind == "nominal_median_lag":
                y["avail"] = x["cycle"] + med[x["cycle"].hour]
            elif kind == "runtime_zero":
                y["avail"] = x["cycle"]
            elif kind == "six_hourly_only":
                if x["cycle"].hour not in (0, 6, 12, 18):
                    continue
            elif kind == "v50_only":
                if x["cycle"] < pd.Timestamp("2026-05-06T00:00Z"):
                    continue
            new.append(y)
        out[st] = new
    return out


def fit_ages(cycles):
    """cycle age (h) of the selected cycle at the simulated history snapshots, by mode (diagnostic)."""
    return None


def main():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")
    cycles, info = t6.load_cycles()
    s, bands = t6.snapshot_frame()
    assert (s.date <= "2026-09-29").all()
    res_all, cands = {}, {}
    kinds = ["asis", "plus60", "plus120", "nominal_median_lag", "runtime_zero", "six_hourly_only", "v50_only"]
    for kind in kinds:
        if Path(r"C:\swarm\STOP").exists():
            sys.exit("STOP present")
        cv = cycles if kind == "asis" else variant(cycles, kind)
        old = t6.HIST_START
        if kind == "v50_only":
            t6.HIST_START = "2026-05-06"
        params, fstats = t6.fit_r3(cv)
        t6.HIST_START = old
        # evaluation inputs: always the original cycles (measured LastModified)
        cand, modes, ages = t6.build_candidate("r2", cycles, s, bands, params)
        cands[kind] = cand.set_index(["row_key", "band_index"]).p
        res = h.score(cand, name=f"t25_t6r3_hist_{kind}")
        tabs = {}
        for g in GROUPS:
            t = h.table_lookup(res, g, "from_20260823", "all_row")
            tb = h.table_lookup(res, g, "before_20260823", "all_row")
            tabs[g] = {"from_cms": t["candidate_minus_served"]["estimate"], "from_ci": t["candidate_minus_served"]["ci95"],
                       "before_cms": tb["candidate_minus_served"]["estimate"],
                       "mkts_neg": t.get("markets_negative"), "class": res["classes"][g]["class"]}
        res_all[kind] = {"params": {k: list(v) for k, v in params.items()}, "fit_stats": fstats, "tables": tabs,
                         "harness": res["harness_sha256"] if "harness_sha256" in res else h.harness_sha256(),
                         "leakage_suspect_groups": res.get("leakage_suspect_groups")}
        print(kind, res_all[kind]["params"], {g: (round(v["from_cms"], 5), v["class"]) for g, v in tabs.items()}, flush=True)
    base = cands["asis"]
    snap_block = s.set_index("row_key")[["block", "stratum"]]
    for kind in kinds[1:]:
        a, b = base.align(cands[kind], join="outer")
        d = (a - b).abs()
        chg = d[d > 1e-9]
        rk = chg.index.get_level_values(0).unique()
        res_all[kind]["changed_band_rows"] = int(len(chg))
        res_all[kind]["changed_snapshots"] = int(len(rk))
        res_all[kind]["max_abs_dp"] = float(d.max())
        res_all[kind]["mean_abs_dp_changed"] = float(chg.mean()) if len(chg) else 0.0
        res_all[kind]["changed_snapshots_from_stratum"] = int((snap_block.loc[rk].stratum == "from_20260823").sum())
        res_all[kind]["delta_vs_asis_from"] = {g: res_all[kind]["tables"][g]["from_cms"] - res_all["asis"]["tables"][g]["from_cms"] for g in GROUPS}
        res_all[kind]["class_changes"] = {g: (res_all["asis"]["tables"][g]["class"], res_all[kind]["tables"][g]["class"])
                                         for g in GROUPS if res_all[kind]["tables"][g]["class"] != res_all["asis"]["tables"][g]["class"]}
    out = {"agent": "t25", "HARNESS_SHA256": h.harness_sha256(), "n_snapshots": int(len(s)),
           "n_band_rows_scored_candidate": int(len(base)), "load_info": info, "variants": res_all}
    (OUT / "t25_hist_basis.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: {kk: v.get(kk) for kk in ("params", "changed_snapshots", "changed_snapshots_from_stratum", "max_abs_dp", "class_changes")} for k, v in res_all.items()}, indent=1, default=str))


if __name__ == "__main__":
    main()
