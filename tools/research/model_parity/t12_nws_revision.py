"""T12 (model-parity swarm v2, development only): NWS forecast revision direction, TABLE ONLY.

Question: when the captured NWS gridpoint high (nws_grid_high_raw) changes between nws_grid_updated_at
stamps during the target day, does shifting served mass in the direction of the latest revision
improve Brier?

Rules (registered in C:\\swarm\\registry.jsonl before the first score):
  t12-r1  momentum shift, fixed alpha = +0.5 (declared a priori, zero fitted parameters)
  t12-r2  same shift with alpha fitted on the BEFORE stratum only (grid -1..+1 step 0.25, floored Brier)

Point in time: the only input besides served probabilities is nws_grid_high_raw as captured by
production at each snapshot. Each value's availability is its nws_grid_fetched_at, asserted
<= captured_at_utc with h.assert_point_in_time. The revision at snapshot t uses only snapshots of the
same market-day with captured_at_utc <= t. No market, no labels (labels read only for the r2 fit,
restricted to stratum before_20260823).

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.t12_nws_revision
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h

OUT = Path(r"C:\swarm\out\t12")
REGISTRY = Path(r"C:\swarm\registry.jsonl")
BEFORE = "before_20260823"
ALPHA_GRID = [round(a, 2) for a in np.arange(-1.0, 1.0001, 0.25)]

RULES = {
    "t12-r1": (
        "T12 NWS revision momentum, fixed alpha=+0.5. At snapshot t of a market-day, take the captured "
        "nws_grid_high_raw values of that market-day's snapshots with captured_at_utc <= t (each with "
        "nws_grid_fetched_at <= its captured_at_utc). If the value has changed at least once, let rd = latest "
        "value - the value it replaced (the latest revision). Translate served probabilities by s = 0.5*rd "
        "degrees on the integer-degree grid (band mass spread uniformly over its integer degrees, tails as edge "
        "points, linear interpolation for fractional shifts, edge clipping), re-aggregate to bands, apply the "
        "harness rule-4 floor and renormalise. No revision yet -> served fallback. All hours, all markets."
    ),
    "t12-r2": (
        "T12 NWS revision momentum, alpha fitted on the before stratum only: identical to t12-r1 except "
        "s = alpha*rd where alpha is chosen from {-1,-0.75,...,+1} to minimise floored band Brier over "
        "before_20260823 rows that carry a revision (one pooled alpha, all hours). From stratum never used "
        "in fitting."
    ),
    "t12-c1": (
        "T12 CONTROL (placebo, not a candidate): identical to t12-r1 but alpha=-0.5 (shift AGAINST the latest "
        "NWS revision). Same rows, same blur magnitude; isolates direction from the smoothing of a half-degree shift."
    ),
    "t12-c2": (
        "T12 CONTROL (direction-free blur, not a candidate): on the same rows as t12-r1, p = 0.5*shift(+0.5*|rd|) "
        "+ 0.5*shift(-0.5*|rd|) of served on the integer-degree grid, floored and renormalised. Measures how much "
        "of t12-r1 is symmetric smoothing (a closed recalibration thread) rather than revision direction."
    ),
}


def register():
    existing = set()
    if REGISTRY.exists():
        for line in REGISTRY.read_text(encoding="utf-8").splitlines():
            try:
                existing.add(json.loads(line)["id"])
            except Exception:
                pass
    for rid, text in RULES.items():
        if rid in existing:
            continue
        rec = {"id": rid, "agent": "t12", "text": text,
               "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
               "time_local": datetime.now().isoformat(timespec="seconds")}
        with open(REGISTRY, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")


def revisions(snaps):
    """Per snapshot: latest revision rd (NaN if none yet) and hours since that revision. PIT."""
    s = snaps[["row_key", "market", "date", "captured_at_utc", "nws_grid_high_raw",
               "nws_grid_fetched_at", "unit"]].copy()
    have = s.nws_grid_high_raw.notna()
    h.assert_point_in_time(pd.to_datetime(s.loc[have, "nws_grid_fetched_at"], utc=True, format="ISO8601"),
                           pd.to_datetime(s.loc[have, "captured_at_utc"], utc=True, format="ISO8601"))
    s["ca"] = pd.to_datetime(s.captured_at_utc, utc=True, format="ISO8601")
    s = s.sort_values(["market", "date", "ca"], kind="mergesort")
    rd = np.full(len(s), np.nan)
    ago = np.full(len(s), np.nan)
    vals = s.nws_grid_high_raw.to_numpy()
    ts = s.ca.to_numpy()
    keys = (s.market + "|" + s.date).to_numpy()
    cur = prev = np.nan
    tchg = None
    lastkey = None
    for i in range(len(s)):
        if keys[i] != lastkey:
            cur = prev = np.nan
            tchg = None
            lastkey = keys[i]
        x = vals[i]
        if not np.isnan(x):
            if np.isnan(cur):
                cur = x
            elif x != cur:
                prev, cur, tchg = cur, x, ts[i]
        if not np.isnan(prev):
            rd[i] = cur - prev
            ago[i] = (ts[i] - tchg) / np.timedelta64(1, "h")
    s["rd"] = rd
    s["rev_age_h"] = ago
    return s.set_index("row_key")[["rd", "rev_age_h", "unit"]]


def _band_groups(bands):
    b = bands.sort_values(["row_key", "band_index"], kind="mergesort")
    return b


def shifted_probs(bands, shift_by_row):
    """Translate each covered snapshot's served distribution by shift_by_row[row_key] degrees."""
    b = _band_groups(bands[bands.row_key.isin(shift_by_row.index)])
    rk = b.row_key.to_numpy()
    starts = np.flatnonzero(np.r_[True, rk[1:] != rk[:-1]])
    ends = np.r_[starts[1:], len(b)]
    kind = b.kind.to_numpy()
    low = b.low.to_numpy().astype(int)
    high = b.high.to_numpy().astype(int)
    p = b.p_served.to_numpy().astype(float)
    out = np.empty(len(b))
    shifts = shift_by_row.reindex(rk[starts]).to_numpy()
    for j, (a, e) in enumerate(zip(starts, ends)):
        k, lo, hi, pp = kind[a:e], low[a:e], high[a:e], p[a:e]
        # integer-degree positions: lte -> high, gte -> low, eq -> low..high
        g0 = min(np.where(k == "lte", hi, lo).min(), lo.min())
        g1 = max(np.where(k == "gte", lo, hi).max(), hi.max())
        n = g1 - g0 + 1
        pmf = np.zeros(n)
        idx_ranges = []
        for t in range(e - a):
            if k[t] == "lte":
                r0 = r1 = hi[t] - g0
            elif k[t] == "gte":
                r0 = r1 = lo[t] - g0
            else:
                r0, r1 = lo[t] - g0, hi[t] - g0
            idx_ranges.append((r0, r1))
            pmf[r0:r1 + 1] += pp[t] / (r1 - r0 + 1)
        s = shifts[j]
        kf = int(np.floor(s))
        f = s - kf
        q = np.zeros(n)
        pos = np.arange(n)
        np.add.at(q, np.clip(pos + kf, 0, n - 1), (1 - f) * pmf)
        np.add.at(q, np.clip(pos + kf + 1, 0, n - 1), f * pmf)
        out[a:e] = [q[r0:r1 + 1].sum() for r0, r1 in idx_ranges]
    return b[["row_key", "band_index"]].assign(p=out)


def fit_alpha(snaps, bands, rev):
    """Pick alpha on the BEFORE stratum only (labels read for before rows only)."""
    lab = pd.read_parquet(r"C:\swarm\cache\bands.parquet",
                          columns=["row_key", "band_index", "stratum", "is_winner"])
    lab = lab[lab.stratum == BEFORE]
    assert set(lab.stratum.unique()) == {BEFORE}
    before_keys = set(snaps.loc[snaps.stratum == BEFORE, "row_key"])
    rv = rev[rev.rd.notna() & rev.index.isin(before_keys)]
    bb = bands[bands.row_key.isin(rv.index)]
    lab = lab.set_index(["row_key", "band_index"]).is_winner.astype(float)
    curve = {}
    for a in ALPHA_GRID:
        c = shifted_probs(bb, rv.rd * a) if a != 0 else bb[["row_key", "band_index"]].assign(
            p=bb.p_served.to_numpy())
        c = c.merge(bb[["row_key", "band_index", "floor_impossible"]], on=["row_key", "band_index"])
        c.loc[c.floor_impossible, "p"] = 0.0
        tot = c.groupby("row_key").p.transform("sum")
        c["p"] = np.where(tot > 0, c.p / tot, np.nan)
        y = lab.reindex(pd.MultiIndex.from_frame(c[["row_key", "band_index"]])).to_numpy()
        se = (c.p.to_numpy() - y) ** 2
        curve[a] = float(np.nanmean(pd.Series(se).groupby(c.row_key.to_numpy()).sum()))
    best = min(curve, key=curve.get)
    return best, curve


def main():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")
    OUT.mkdir(parents=True, exist_ok=True)
    snaps, bands = h.candidate_inputs()
    assert snaps.date.max() <= "2026-09-29"
    assert set(snaps.unit.dropna().unique()) <= {"F"}, snaps.unit.unique()
    rev = revisions(snaps)
    cov = rev.rd.notna()
    info = {"rows_with_revision": int(cov.sum()), "rows": int(len(rev)),
            "rd_counts": {str(k): int(v) for k, v in rev.rd.value_counts().sort_index().items()}}
    alpha, curve = fit_alpha(snaps, bands, rev)
    info["r2_alpha_fit_before"] = alpha
    info["r2_before_brier_curve"] = curve
    print(json.dumps(info, indent=1))
    register()
    results = {}
    for rid, a in (("t12-r1", 0.5), ("t12-r2", alpha)):
        rv = rev[cov]
        if a == 0:
            cand = bands[bands.row_key.isin(rv.index)][["row_key", "band_index"]].assign(
                p=bands[bands.row_key.isin(rv.index)].p_served.to_numpy())
        else:
            cand = shifted_probs(bands, rv.rd * a)
        res = h.score(cand, name=rid.replace("-", "_"))
        if res.get("leakage_suspect_groups"):
            Path(r"C:\swarm\STOP").write_text(f"t12 leakage tripwire {rid}: {res['leakage_suspect_groups']}\n")
            raise SystemExit("leakage tripwire")
        h.save(res, OUT)
        print(h.markdown(res))
        results[rid] = {"alpha": a, "classes": res["classes"]}
    rv = rev[cov]
    for rid, kind in (("t12-c1", "placebo"), ("t12-c2", "blur")):
        if kind == "placebo":
            cand = shifted_probs(bands, rv.rd * -0.5)
        else:
            up = shifted_probs(bands, rv.rd.abs() * 0.5)
            dn = shifted_probs(bands, rv.rd.abs() * -0.5)
            cand = up.assign(p=0.5 * up.p.to_numpy() + 0.5 * dn.p.to_numpy())
        res = h.score(cand, name=rid.replace("-", "_"))
        assert not res.get("leakage_suspect_groups")
        h.save(res, OUT)
        print(h.markdown(res))
        results[rid] = {"classes": res["classes"]}
    (OUT / "t12_info.json").write_text(json.dumps(info, indent=1))
    print(json.dumps({"HARNESS_SHA256": h.harness_sha256()}))


if __name__ == "__main__":
    main()
