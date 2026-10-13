"""T27-INDEP-R1: independent re-implementation of registered rule d-defect-r2 (= ladder-r1).

Written from the registry text and the production code only (model_distribution_signals.py
late_day_lockin_strength :377, learned_lockin_strength :408, apply_late_day_lockin :880;
model_distribution.py distribution_late_day_lockin_stage :1176; calibration_runtime.py
revision_up_probability :697 with SETTLEMENT_CUTOFF_HOURS = range(8, 21) :28;
model_distribution_constants.py :127-143). d_defect_evening_stage.py and ladder_parity.py were
NOT read before this file was written and scored. Development only. No new rule.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\pt\swarm")
sys.path.insert(0, str(ROOT))
from tools.research.model_parity import harness as h  # noqa: E402

OUT = Path(r"C:\swarm\out\t27")
ART = ROOT / "artifacts" / "calibration"
OBS = Path(r"C:\swarm\out\t1\t1_obs_pit.parquet")

# production constants (model_distribution_constants.py:127-143)
LATE_LOCKIN_START_HOUR = 15
LATE_LOCKIN_FULL_HOUR = 17
LATE_LOCKIN_PEAK_DROP_F = 2.0 * 9.0 / 5.0   # spec.scale_delta(2.0 C) for F markets
LATE_LOCKIN_HEDGE = 0.05
LATE_LOCKIN_BASE = 0.15
LEARNED_LOCKIN_START_HOUR = 17
LEARNED_LOCKIN_STAND_MINUTES = 90
CUTOFF_HOURS = tuple(range(8, 21))           # calibration_runtime.py:28
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def round_half_up(x):
    return np.floor(np.asarray(x, float) + 0.5)


def revision_rates(clamp=True):
    """market -> {hour: revision_up_rate} following revision_up_probability (n >= min_context_n)."""
    out = {}
    for path in ART.glob("settlement_lag_model_*.json"):
        market = path.stem.replace("settlement_lag_model_", "")
        if market.endswith("family"):
            continue
        art = json.loads(path.read_text(encoding="utf-8"))
        ctx = art.get("revision_contexts") or {}
        min_n = int((art.get("component") or {}).get("min_context_n", 20))
        rates = {}
        for hour in range(24):
            hh = max(CUTOFF_HOURS[0], min(CUTOFF_HOURS[-1], hour)) if clamp else hour
            row = ctx.get(f"hour={hh}")
            if row and int(row.get("n", 0)) >= min_n:
                rates[hour] = float(row["revision_up_rate"])
        out[market] = rates
    return out


def strengths(snaps, clamp=True, stood_mode="eq", fractional_hour=False):
    """Per-snapshot lock-in strength s = max(S1 heuristic, S2 learned); also B and parts."""
    obs = pd.read_parquet(OBS, columns=["row_key", "cur"])
    s = snaps[["row_key", "market", "date", "local_hour", "captured_at_utc", "captured_at_local",
               "floor"]].merge(obs, on="row_key", how="left", validate="one_to_one")
    assert (s.row_key.to_numpy() == snaps.row_key.to_numpy()).all()
    F = s.floor.to_numpy(float)
    B = round_half_up(F)
    cur = s.cur.to_numpy(float)
    if fractional_hour:
        loc = pd.to_datetime(s.captured_at_local.str.slice(0, 19))
        hour = (loc.dt.hour + loc.dt.minute / 60.0).to_numpy(float)
    else:
        hour = s.local_hour.to_numpy(float)
    # S1 late_day_lockin_strength (:377): time factor x past-peak factor
    tf = np.where(hour <= LATE_LOCKIN_START_HOUR, 0.0,
                  np.where(hour >= LATE_LOCKIN_FULL_HOUR, 1.0,
                           (hour - LATE_LOCKIN_START_HOUR) / (LATE_LOCKIN_FULL_HOUR - LATE_LOCKIN_START_HOUR)))
    drop = F - cur
    pf = np.where(drop <= 0, 0.0, np.where(drop >= LATE_LOCKIN_PEAK_DROP_F, 1.0, drop / LATE_LOCKIN_PEAK_DROP_F))
    heur = np.where(np.isfinite(F) & np.isfinite(cur), tf * pf, 0.0)
    # S2 learned_lockin_strength (:408): hour >= 17, bucket stood >= 90 min, 1 - revision_up_rate
    t = pd.to_datetime(s.captured_at_utc, utc=True)
    s["t"] = t
    s["B"] = B
    s = s.reset_index(drop=True)
    s["pos"] = np.arange(len(s))
    first = np.full(len(s), np.nan)
    for _, g in s.sort_values("t").groupby(["market", "date"], sort=False):
        bvals = g.B.to_numpy(float)
        tsec = (g.t - EPOCH).dt.total_seconds().to_numpy()
        pos = g.pos.to_numpy()
        for i in range(len(g)):
            b = bvals[i]
            if not np.isfinite(b):
                continue
            prior = bvals[: i + 1]
            if stood_mode == "eq":
                hit = np.flatnonzero(prior == b)
            elif stood_mode == "ge":
                hit = np.flatnonzero(prior >= b)
            else:  # "run": start of the current unbroken run at this bucket
                j = i
                while j - 1 >= 0 and bvals[j - 1] == b:
                    j -= 1
                hit = np.array([j])
            first[pos[i]] = tsec[hit[0]]
    tnow = (t - EPOCH).dt.total_seconds().to_numpy()
    stood = (tnow - first) / 60.0
    rates = revision_rates(clamp=clamp)
    lh = s.local_hour.to_numpy(int)
    rate = np.array([rates.get(m, {}).get(int(hh), np.nan) for m, hh in zip(s.market, lh)])
    learned = np.where((lh >= LEARNED_LOCKIN_START_HOUR) & (stood >= LEARNED_LOCKIN_STAND_MINUTES)
                       & np.isfinite(rate) & np.isfinite(B), np.clip(1.0 - rate, 0.0, 1.0), 0.0)
    strength = np.where(np.isfinite(B), np.maximum(heur, learned), 0.0)
    return pd.DataFrame({"row_key": s.row_key, "B": B, "cur": cur, "heur": heur, "learned": learned,
                         "stood": stood, "s": strength})


def band_factors(bands, snaps, st, lte_mode="high"):
    """Per-band mean lock-in factor over the band's integers (apply_late_day_lockin :880)."""
    n = snaps.n_bands.to_numpy()
    B = np.repeat(st.B.to_numpy(float), n)
    S = np.repeat(st.s.to_numpy(float), n)
    kind = bands.kind.to_numpy()
    lo = bands.low.to_numpy(float)
    hi = bands.high.to_numpy(float)
    if lte_mode == "high":
        lo_i = np.where(kind == "lte", hi, lo)      # lte band = its high integer (my reading)
    else:                                           # "feasible": floor-feasible integers B..high
        lo_i = np.where(kind == "lte", np.where(np.isfinite(B), np.minimum(B, hi), hi), lo)
    hi_i = np.where(kind == "gte", lo, hi)          # gte band = its low integer
    width = hi_i - lo_i + 1
    assert (width >= 1).all() and width.max() <= 60
    lo_i = np.where(np.isfinite(lo_i), lo_i, 0.0)
    fac = np.zeros(len(bands))
    for off in range(int(width.max())):
        k = lo_i + off
        valid = off < width
        above = k - B
        f = np.where(above <= 0, 1.0, (1.0 - S) + S * LATE_LOCKIN_HEDGE * LATE_LOCKIN_BASE ** np.maximum(above - 1, 0))
        fac += np.where(valid, f, 0.0)
    return fac / width


def candidate(variant=None, lte_mode="high"):
    variant = variant or {}
    snaps, bands = h.candidate_inputs()
    st = strengths(snaps, **variant)
    fac = band_factors(bands, snaps, st, lte_mode=lte_mode)
    p = bands.p_served.to_numpy(float) * fac
    covered = np.repeat(np.isfinite(st.B.to_numpy(float)), snaps.n_bands.to_numpy())
    cand = bands.loc[covered, ["row_key", "band_index"]].assign(p=p[covered])
    return cand, st


def _phi(z):
    from scipy.special import ndtr  # noqa: PLC0415
    return ndtr(z)


def c1_base(snaps, bands):
    """ladder-r2 base (r-t5-inc-c1 form, from the registry text): X ~ N(v2_mean, max(v2_stddev, 1))
    integer-discretised, H = max(B, X), band probabilities. Returns (p per band, covered per band)."""
    mu = snaps.v2_mean.to_numpy(float)
    sd = np.maximum(snaps.v2_stddev.to_numpy(float), 1.0)
    F = snaps.floor.to_numpy(float)
    B = round_half_up(F)
    avail = pd.to_datetime(snaps.v2_available_at, utc=True, errors="coerce")
    cap = pd.to_datetime(snaps.captured_at_utc, utc=True)
    cov = np.isfinite(mu) & np.isfinite(snaps.v2_stddev.to_numpy(float)) & np.isfinite(F) & \
        avail.notna().to_numpy() & (avail <= cap).fillna(False).to_numpy()
    n = snaps.n_bands.to_numpy()
    MU, SD, BB = (np.repeat(a, n) for a in (mu, sd, B))
    kind = bands.kind.to_numpy()
    lo = bands.low.to_numpy(float)
    hi = bands.high.to_numpy(float)

    def cdf_h(x):  # P(H <= x) for integer x, H = max(B, X)
        return np.where(x < BB, 0.0, _phi((x + 0.5 - MU) / SD))

    upper = np.where(kind == "gte", np.inf, hi)
    lower = np.where(kind == "lte", -np.inf, lo)
    p_up = np.where(np.isinf(upper), 1.0, cdf_h(np.where(np.isinf(upper), 0, upper)))
    p_lo = np.where(np.isinf(lower), 0.0, cdf_h(np.where(np.isinf(lower), 0, lower) - 1))
    p = np.clip(p_up - p_lo, 0.0, None)
    return p, np.repeat(cov, n)


def candidate_r2(variant=None, lte_mode="high"):
    snaps, bands = h.candidate_inputs()
    st = strengths(snaps, **(variant or {}))
    fac = band_factors(bands, snaps, st, lte_mode=lte_mode)
    pc1, cov = c1_base(snaps, bands)
    base = np.where(cov, pc1, bands.p_served.to_numpy(float))
    covered = np.repeat(np.isfinite(st.B.to_numpy(float)), snaps.n_bands.to_numpy())
    cand = bands.loc[covered, ["row_key", "band_index"]].assign(p=(base * fac)[covered])
    return cand


def snapshot_brier(cand):
    """Per-snapshot candidate Brier exactly as harness.score computes it (served fallback)."""
    d = h.data()
    pc, use, _ = h._candidate_vector(cand, d, False)
    return h._snapshot_mean(d, (pc - d.y) ** 2), use


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cand, st = candidate()
    res = h.score(cand, name="t27_indep_r1")
    h.save(res, OUT)
    sb, use = snapshot_brier(cand)
    np.save(OUT / "snapb_t27_indep_r1.npy", sb)
    st.to_parquet(OUT / "t27_strengths.parquet")
    print(h.markdown(res))
    cand2 = candidate_r2()
    res2 = h.score(cand2, name="t27_indep_ladder_r2")
    h.save(res2, OUT)
    sb2, _ = snapshot_brier(cand2)
    np.save(OUT / "snapb_t27_indep_ladder_r2.npy", sb2)
    print(h.markdown(res2))


if __name__ == "__main__":
    main()
