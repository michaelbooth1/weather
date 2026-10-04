"""T19 tail lens (model-parity swarm v2, development only; DESIGN section 4).

Re-scores registered candidates on the EF 1/1f severity-tail band rows of THIS table
(band rows with served SE > market SE and |p_served - p_market| >= 0.30; harness definition,
6.075% of band rows / 70.38% of positive excess here; EF's 4.387% / 64.14% was measured on the
sealed pre-boundary corpus and is stated beside it, never reproduced) and reports per-market sign
consistency on those rows.

No new rule is registered (T19 re-scores existing registered rules only).

Two sub-commands, run from C:\\pt\\swarm with the repo interpreter:
    python -m tools.research.model_parity.t19_tail_lens capture <module> [entry]
        Re-runs a hunter's registered entry point in-process with every write redirected:
        writes under C:\\swarm\\out\\<other> land in C:\\swarm\\out\\t19\\cap\\<module>\\redir\\..., the
        registry/phase log are shadowed (never appended), other C:\\swarm or repo writes raise.
        Every unfloored, unrestricted candidate passed to h.score is stored as parquet.
    python -m tools.research.model_parity.t19_tail_lens lens
        Tail lens over every captured candidate (T19 captures + LADDER captures + refute-stat-t3).
"""
from __future__ import annotations

import builtins
import io
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(r"C:\swarm\out\t19")
CAP = OUT / "cap"
SWARM = Path(r"C:\swarm")
STOP = SWARM / "STOP"
FROM, BEFORE = "from_20260823", "before_20260823"
GROUPS = ["00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all"]


def stop_check():
    if STOP.exists():
        sys.exit("STOP present: " + STOP.read_text(encoding="utf-8", errors="replace")[:200])


# ----------------------------------------------------------------------------- write guard

def _install_guard(capdir: Path):
    redir = capdir / "redir"
    shadow = capdir / "registry_shadow.jsonl"
    own = str(OUT).lower()
    out_root = str(SWARM / "out").lower()

    def remap(p):
        try:
            s = os.path.abspath(os.fspath(p))
        except TypeError:
            return p
        low = s.lower()
        if low.startswith(own) or low == str(STOP).lower():
            return s
        if low in (str(SWARM / "registry.jsonl").lower(), str(SWARM / "phase_log.jsonl").lower()):
            return str(shadow)
        if low.startswith(out_root + os.sep):
            rel = s[len(out_root) + 1:]
            t = redir / rel
            t.parent.mkdir(parents=True, exist_ok=True)
            return str(t)
        if low.startswith(str(SWARM).lower()) or low.startswith(r"c:\pt\swarm"):
            raise PermissionError(f"t19 guard: write outside t19 refused: {s}")
        return s

    real_open = io.open

    def g_open(file, mode="r", *a, **k):
        if isinstance(file, (str, bytes, os.PathLike)) and any(c in mode for c in "wax+"):
            file = remap(file)
        return real_open(file, mode, *a, **k)

    builtins.open = g_open
    io.open = g_open
    real_pq, real_csv = pd.DataFrame.to_parquet, pd.DataFrame.to_csv

    def g_pq(self, path=None, *a, **k):
        return real_pq(self, remap(path) if path is not None else path, *a, **k)

    def g_csv(self, path_or_buf=None, *a, **k):
        if isinstance(path_or_buf, (str, os.PathLike)):
            path_or_buf = remap(path_or_buf)
        return real_csv(self, path_or_buf, *a, **k)

    pd.DataFrame.to_parquet, pd.DataFrame.to_csv = g_pq, g_csv
    try:
        import pyarrow.parquet as pq
        real_wt = pq.write_table
        pq.write_table = lambda table, where, *a, **k: real_wt(
            table, remap(where) if isinstance(where, (str, os.PathLike)) else where, *a, **k)
    except Exception:
        pass
    real_mkdir = Path.mkdir

    def g_mkdir(self, *a, **k):
        low = os.path.abspath(str(self)).lower()
        if low.startswith(out_root + os.sep) and not low.startswith(own):
            return None  # other agents' directories already exist; never create/alter them
        return real_mkdir(self, *a, **k)

    Path.mkdir = g_mkdir


# ----------------------------------------------------------------------------- capture

ENTRIES = {
    # module: (original OUT dirs to seed, entry callable spec)
    "t1_decided_band": ("t1", "score_all:r1,r2,r3,r2lag60"),
    "t2_remaining_rise": ("t2", "main"),
    "t4_obs_trend_nowcast": ("t4", "main"),
    "t15_diurnal_projection": ("t15", "main"),
    "t16_settlement_mechanics": ("t16", "main"),
    "t17_info_arrival": ("t17", "main"),
    "t18_emos": ("t18", "main"),
    "t18_controls": ("t18", "main"),
    "t6_nbs_controls": ("t6", "main"),
    "t7_controls": ("t7", "main"),
    "t9_extra_pairs": ("t9", "main"),
    "d_defect_evening_stage": ("d-defect", "main"),
    "ladder_parity": ("ladder", "run_rungs"),
    "t3_baselines": ("t3", "main_sensitivity"),
    "t13_neighbour_anomaly": ("t13", "main"),
}


def capture(modname, entry=None, tag=None):
    import importlib
    stop_check()
    seed, default_entry = ENTRIES.get(modname, (None, "main"))
    entry = entry or default_entry
    capdir = CAP / (tag or modname)
    capdir.mkdir(parents=True, exist_ok=True)
    work = capdir / "work"
    work.mkdir(exist_ok=True)
    if seed:  # copy small non-score inputs (fit params, metas) so the module can read them from its OUT
        src = SWARM / "out" / seed
        for f in src.iterdir():
            if f.is_file() and not f.name.endswith(".score.json") and f.stat().st_size < 200_000_000:
                if not (work / f.name).exists():
                    shutil.copy2(f, work / f.name)
    _install_guard(capdir)
    from tools.research.model_parity import harness as h
    mod = importlib.import_module(f"tools.research.model_parity.{modname}")
    mod.OUT = work
    for dep in ("t", "t18_emos"):
        if modname == "t18_controls" and hasattr(mod, dep):
            getattr(mod, dep).OUT = work
    if modname == "t18_controls":
        import tools.research.model_parity.t18_emos as te
        te.OUT = work
    real_score = h.score
    names = []

    def cap_score(candidate, name="candidate", unfloored=False, where=None, **kw):
        if where is None and not unfloored:
            candidate[["row_key", "band_index", "p"]].to_parquet(capdir / f"{name}.parquet")
            names.append(name)
        return real_score(candidate, name=name, unfloored=unfloored, where=where, **kw)

    h.score = cap_score
    h.save = lambda res, out_dir: Path(capdir) / f"{res['name']}.score.json"
    fn, _, arg = entry.partition(":")
    f = getattr(mod, fn)
    if arg:
        f(tuple(arg.split(",")))
    else:
        f()
    print("captured", names)
    (capdir / "captured.json").write_text(json.dumps({"module": modname, "entry": entry, "names": names,
                                                      "time_local": datetime.now().isoformat()}, indent=1))


# ----------------------------------------------------------------------------- lens

def tail_lens(cand, h, d, cache):
    """Tail-row metrics for one candidate frame. Uses the harness candidate vector and _tail."""
    pc, use, reason = h._candidate_vector(cand, d, False)
    se_c = (pc - d.y) ** 2
    frame = d.snaps[["date", "market", "stratum", "local_hour"]]
    lh = frame.local_hour.to_numpy()
    st = frame.stratum.to_numpy()
    out = {"coverage": float(use.mean())}
    excess = d.se_served - d.se_market
    improve = d.se_served - se_c
    bm = d.bands.market.to_numpy()
    for g in GROUPS:
        lo, hi = next((a, b) for n, a, b in h.GROUPS if n == g)
        gm = (lh >= lo) & (lh <= hi)
        for s in (FROM, BEFORE, "pooled"):
            sm = gm if s == "pooled" else gm & (st == s)
            t = h._tail(d, se_c, sm, cache)
            if t.get("status") == "NO_DATA":
                out[f"{g}|{s}"] = t
                continue
            band_sel = sm[d.band_snap] & d.tail
            band_all = sm[d.band_snap]
            # per market: share of that market's tail excess removed (ratio of sums over its tail rows)
            mk = pd.DataFrame({"m": bm[band_sel], "imp": improve[band_sel], "exc": excess[band_sel]})
            pm = mk.groupby("m").sum()
            share = (pm.imp / pm.exc)
            imp_all = float(improve[band_all].sum())
            imp_tail = float(improve[band_sel].sum())
            out[f"{g}|{s}"] = {
                "tail_band_rows": t["tail_band_rows"], "market_days": t["market_days"],
                "share_of_tail_excess_removed": t["share_of_tail_excess_removed"],
                "mean_delta_per_tail_band_row": t["mean_delta_per_tail_band_row"],
                "per_market_tail_share_removed": {k: float(v) for k, v in share.items()},
                "markets_tail_improved": int((share > 0).sum()), "markets_tail_harmed": int((share < 0).sum()),
                "markets_n": int(len(share)),
                "tail_part_of_all_row_improvement": (imp_tail / imp_all) if imp_all != 0 else None,
                "all_row_improvement_sum": imp_all, "tail_improvement_sum": imp_tail,
                "nontail_improvement_sum": imp_all - imp_tail,
            }
    return out


def discover():
    found = []
    for root in (CAP, SWARM / "out" / "ladder" / "cap"):
        if root.exists():
            for p in sorted(root.glob("*/*.parquet")):
                if p.parent.name == "work" or "redir" in p.parts:
                    continue
                found.append(p)
    for p in (SWARM / "out" / "refute-stat-t3" / "cand_r3s.parquet",):
        if p.exists():
            found.append(p)
    return found


def lens():
    stop_check()
    from tools.research.model_parity import harness as h
    d = h.data()
    cache = h.CACHE
    facts = h.table_facts()
    rows = {}
    seen = {}
    for p in discover():
        stop_check()
        cand = pd.read_parquet(p)
        if not {"row_key", "band_index", "p"} <= set(cand.columns):
            print("skip (not a candidate frame)", p)
            continue
        cand = cand[["row_key", "band_index", "p"]]
        key = f"{p.parent.name}/{p.stem}"
        try:
            res = h.score(cand, name=key)
        except Exception as e:  # noqa: BLE001
            print("score failed", key, e)
            rows[key] = {"path": str(p), "error": repr(e)}
            continue
        if res.get("leakage_suspect_groups"):
            STOP.write_text(f"t19: leakage suspect in {key}: {res['leakage_suspect_groups']}\n")
            sys.exit("leakage suspect " + key)
        tl = tail_lens(cand, h, d, cache)
        cls = {g: res["classes"][g]["class"] for g in GROUPS}
        allrow = {}
        for g in GROUPS:
            for s in (FROM, BEFORE):
                t = h.table_lookup(res, g, s, "all_row")
                if t.get("status") == "NO_DATA":
                    continue
                allrow[f"{g}|{s}"] = {"est": t["candidate_minus_served"]["estimate"],
                                      "ci95": t["candidate_minus_served"]["ci95"],
                                      "markets_negative": t["markets_negative"],
                                      "markets_n": t["market_clusters"],
                                      "per_market_delta": t["per_market_delta"],
                                      "gap_closed_share": t["gap_closed_share"]["estimate"]}
        h_ = __import__("hashlib").sha256(pd.util.hash_pandas_object(cand, index=False).values.tobytes()).hexdigest()
        rows[key] = {"path": str(p), "cand_sha256": h_, "duplicate_of": seen.get(h_),
                     "classes": cls, "all_row": allrow, "tail": tl,
                     "candidate_share": res["candidate_share"]}
        seen.setdefault(h_, key)
        print(key, cls["17-23"], cls["00-16"],
              "tail17-23 from", round(tl.get(f"17-23|{FROM}", {}).get("share_of_tail_excess_removed", {}).get("estimate", float("nan")), 4)
              if isinstance(tl.get(f"17-23|{FROM}", {}).get("share_of_tail_excess_removed"), dict) else "-",
              flush=True)
    result = {"agent": "t19", "HARNESS_SHA256": h.harness_sha256(), "development": True,
              "rows_with_target_after_2026_09_29": d.receipt["rows_with_target_after_2026_09_29"],
              "max_target_date": str(d.snaps.date.max()),
              "table_tail_facts": facts.get("tail"),
              "ef_tail_reference": {"band_row_share": 0.04387, "share_of_positive_excess": 0.6414,
                                    "panel": "sealed pre-boundary replay corpus (09-44a); not reproduced"},
              "time_local": datetime.now().isoformat(), "candidates": rows}
    (OUT / "t19_lens.json").write_text(json.dumps(result, indent=1, default=float), encoding="utf-8")
    print("wrote", OUT / "t19_lens.json", len(rows))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "lens"
    if cmd == "capture":
        capture(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] != "-" else None,
                sys.argv[4] if len(sys.argv) > 4 else None)
    else:
        lens()
