"""D-DEFECT: emulate restoring the no-op late-day lock-in stages on captured inputs (development only).

Rules registered in C:\\swarm\\registry.jsonl before the first score: d-defect-r1, d-defect-r2, d-defect-d1.
Run from C:\\pt\\swarm with the repo interpreter:
    python -m tools.research.model_parity.d_defect_evening_stage
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h

OUT = Path(r"C:\swarm\out\d-defect")
OBS = Path(r"C:\swarm\out\t1\t1_obs_pit.parquet")
ART = Path(r"C:\pt\swarm\artifacts\calibration")

# Production constants (src/weather/model/model_distribution_constants.py:127-143), F markets.
START_H, FULL_H = 15, 17
PEAK_DROP_F = 2.0 * 9.0 / 5.0
HEDGE, BASE = 0.05, 0.15
LEARNED_START_H, LEARNED_STAND_MIN = 17, 90


def rhu(x):
    return np.floor(np.asarray(x, dtype=float) + 0.5)


def heuristic_strength(hour, anchor, cur):
    hour = np.asarray(hour, dtype=float)
    tf = np.clip((hour - START_H) / (FULL_H - START_H), 0.0, 1.0)
    tf = np.where(hour <= START_H, 0.0, tf)
    drop = anchor - cur
    pf = np.clip(drop / PEAK_DROP_F, 0.0, 1.0)
    s = tf * pf
    return np.where(np.isnan(s), 0.0, s)


def revision_rates():
    rates = {}
    for f in ART.glob("settlement_lag_model_*.json"):
        market = f.stem.replace("settlement_lag_model_", "")
        d = json.loads(f.read_text())
        rc = d.get("revision_contexts") or {}
        min_n = int((d.get("component") or {}).get("min_context_n", 20))
        hours = sorted(int(k.split("=")[1]) for k in rc if k.startswith("hour="))
        lo, hi = 8, 20  # CUTOFF_HOURS clamp as in settlement_lag_model.revision_up_probability
        rates[market] = {}
        for hr in range(24):
            row = rc.get(f"hour={max(lo, min(hi, hr))}")
            if row and int(row.get("n", 0)) >= min_n:
                rates[market][hr] = float(row["revision_up_rate"])
    return rates


def band_factor(bands, B, s):
    """Mean over integers in each band of the lock-in retention factor (uniform within band)."""
    low = bands["low"].to_numpy(float)
    high = bands["high"].to_numpy(float)
    kind = bands["kind"].to_numpy()
    lo = np.where(kind == "lte", np.minimum(B, high), low)
    hi = np.where(kind == "gte", low, high)
    out = np.ones(len(bands))
    width = (hi - lo + 1).astype(int)
    maxw = int(width.max())
    acc = np.zeros(len(bands))
    for j in range(maxw):
        k = lo + j
        valid = j < width
        above = k - B
        f = np.where(above <= 0, 1.0, (1.0 - s) + s * HEDGE * BASE ** np.maximum(above - 1, 0))
        acc += np.where(valid, f, 0.0)
    out = acc / width
    return out


def main():
    assert not Path(r"C:\swarm\STOP").exists()
    snaps, bands = h.candidate_inputs()
    obs = pd.read_parquet(OBS)[["row_key", "cur"]]
    snaps = snaps.merge(obs, on="row_key", how="left")
    assert (snaps["date"].astype(str) > "2026-09-29").sum() == 0
    F = snaps["floor"].to_numpy(float)
    B = rhu(F)
    snaps["B"] = B
    print("gpf >= high_so_far share:", float((snaps.guidance_physical_floor >= snaps.high_so_far - 1e-9).mean()),
          "trusted_current_max non-null:", int(snaps.trusted_current_max.notna().sum()))
    s_heur = heuristic_strength(snaps.local_hour, F, snaps["cur"].to_numpy(float))
    snaps["s_heur"] = s_heur

    # learned lock-in: stood minutes of the anchor bucket from prior snapshots of the market-day
    snaps["t"] = pd.to_datetime(snaps.captured_at_utc, utc=True)
    snaps = snaps.sort_values(["market", "date", "t"]).reset_index(drop=True)
    grp = snaps.groupby(["market", "date"], sort=False)
    # first time the running bucket reached its current value (B is non-decreasing in practice; use exact match)
    snaps["Bchg"] = grp["B"].transform(lambda x: (x != x.shift()).cumsum())
    first_t = snaps.groupby(["market", "date", "Bchg"])["t"].transform("min")
    stood = (snaps["t"] - first_t).dt.total_seconds() / 60.0
    rates = revision_rates()
    rate = np.array([rates.get(m, {}).get(int(hr), np.nan) for m, hr in zip(snaps.market, snaps.local_hour)])
    learned = np.where((snaps.local_hour >= LEARNED_START_H) & (stood >= LEARNED_STAND_MIN) & ~np.isnan(rate),
                       np.clip(1.0 - rate, 0, 1), 0.0)
    snaps["s_learn"] = learned
    snaps["s_r2"] = np.maximum(snaps["s_heur"].to_numpy(float), learned)  # aligned after the sort

    sk = snaps.set_index("row_key")
    bb = bands.copy()
    bb["B"] = bb.row_key.map(sk["B"])
    diag = {}
    cands = {}
    for rid, scol, need_cur in (("d-defect-r1", "s_heur", True), ("d-defect-r2", "s_r2", False)):
        s = bb.row_key.map(sk[scol]).to_numpy(float)
        fac = band_factor(bb, bb["B"].to_numpy(float), s)
        p = bb.p_served.to_numpy(float) * fac
        c = bb[["row_key", "band_index"]].assign(p=p)
        tot = c.groupby("row_key").p.transform("sum")
        c["p"] = c.p / tot
        covered = sk.index[sk["B"].notna() & (sk["cur"].notna() if need_cur else True)]
        c = c[c.row_key.isin(covered)]
        cands[rid] = c
        ev = sk[sk.local_hour >= 17]
        diag[rid] = {"share_17_23_strength_pos": float((ev[scol] > 0).mean()),
                     "share_17_23_strength_ge_0.95": float((ev[scol] >= 0.95).mean()),
                     "mean_strength_17_23": float(ev[scol].mean()),
                     "covered_snapshots": int(len(covered))}
    # d1 unconditional collapse to the floor band at 17-23
    fb = bb.row_key.map(sk["floor_bucket"]).to_numpy(float)
    low, high, kind = bb.low.to_numpy(float), bb.high.to_numpy(float), bb.kind.to_numpy()
    infl = np.where(kind == "lte", fb <= high, np.where(kind == "gte", fb >= low, (fb >= low) & (fb <= high)))
    ev_keys = set(sk.index[(sk.local_hour >= 17) & sk.floor_bucket.notna()])
    d1 = bb[["row_key", "band_index"]].assign(p=infl.astype(float))
    d1 = d1[d1.row_key.isin(ev_keys)]
    cands["d-defect-d1"] = d1

    summary = {}
    for rid, c in cands.items():
        res = h.score(c, name=rid.replace("-", "_"))
        h.save(res, OUT)
        md = h.markdown(res)
        (OUT / f"{rid}.md").write_text(md, encoding="utf-8")
        row = {}
        for g in ("00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all"):
            try:
                tf = h.table_lookup(res, g, "from_20260823", "all_row")
                tb = h.table_lookup(res, g, "before_20260823", "all_row")
            except Exception as e:  # noqa: BLE001
                row[g] = {"error": str(e)}
                continue
            row[g] = {"from": tf["candidate_minus_served"]["estimate"],
                      "from_ci95": tf["candidate_minus_served"]["ci95"],
                      "before": tb["candidate_minus_served"]["estimate"],
                      "cand_minus_market_from": tf["candidate_minus_market"]["estimate"],
                      "cand_minus_market_ci95": tf["candidate_minus_market"].get("ci95"),
                      "gap_closed_from": tf.get("gap_closed_share"),
                      "class": res["classes"].get(g, {}).get("class")}
        row["leakage_suspect_groups"] = res.get("leakage_suspect_groups")
        row["reason_counts"] = res.get("reason_counts")
        summary[rid] = row
        print(md)

    # descriptive: mean mass above the floor band at 17-23 (evaluation side reads labels from the cache)
    lab = pd.read_parquet(r"C:\swarm\cache\bands.parquet", columns=["row_key", "band_index", "p_market_yes", "is_winner"])
    for rid in ("d-defect-r1", "d-defect-r2"):
        c = cands[rid]
        m = bb[["row_key", "band_index", "p_served", "low", "kind", "B"]].merge(c, on=["row_key", "band_index"], how="left")
        m["p"] = m.p.fillna(m.p_served)
        m = m.merge(lab, on=["row_key", "band_index"])
        m["hour"] = m.row_key.map(sk["local_hour"])
        fbk = m.row_key.map(sk["floor_bucket"])
        above = np.where(m.kind == "lte", False, m.low > fbk)
        ev = m[(m.hour >= 17) & above]
        n = m[m.hour >= 17].row_key.nunique()
        diag[rid]["mass_above_floor_band_17_23"] = {
            "served": float(ev.p_served.sum() / n), "candidate": float(ev.p.sum() / n),
            "market": float(ev.p_market_yes.sum() / n), "realised": float(ev.is_winner.sum() / n)}
    out = {"agent": "d-defect", "HARNESS_SHA256": h.harness_sha256(), "summary": summary, "diag": diag,
           "development": True, "rows_after_0929": 0}
    (OUT / "result.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"diag": diag}, indent=1))


if __name__ == "__main__":
    main()
