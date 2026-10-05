"""T23 spare: INDEPENDENT re-implementation of registered rule t5-r1 (development only).

Written from the registry text of t5-r1 alone (sha256 c6cd29cb...7231e2), without reading
t5_nbh_latest.py. No new rule is registered; this scores the same rule under a different name.

Rule (registry text, paraphrased): at snapshot t (station, local target date D, E = local midnight
ending D), NBH cycles are eligible iff S3 LastModified <= captured_at_utc. For every hourly valid
time v in (t, E], take TMP/TSD from the latest eligible cycle carrying v. mu = max TMP,
sigma = max(TSD at argmax v, 1). X ~ N(mu, sigma) discretised on integers; H = max(B, X), B =
floor(F + 0.5), F = harness rule-4 floor; band p = P(H in band). No eligible cycle or any v
uncovered -> served fallback. Zero fitted parameters, all hours.

Interpretation choices (the registry text is silent on them; recorded in the report):
  * "latest" = largest cycle_utc among eligible cycles (not latest LastModified).
  * argmax ties -> the earliest valid time v among the tied maxima.
  * TSD missing at the argmax hour from the cycle that supplied TMP there -> served fallback.
  * Local midnight uses the snapshot's own UTC offset (captured_at_local); no DST change in Aug-Sep.
  * Snapshot without a rule-4 floor: B = -inf (the harness then falls back as missing_floor).

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.t23_t5r1_reimpl
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import ndtr

from tools.research.model_parity import harness as h

OUT = Path(r"C:\swarm\out\t23")
NBH = Path(r"C:\swarm\data\nbh\nbh_tidy.parquet")
HOUR_NS = 3_600_000_000_000


def load_nbh():
    n = pd.read_parquet(NBH, filters=[("field", "in", ["TMP", "TSD"])],
                        columns=["station", "field", "value", "cycle_utc", "valid_utc", "available_utc"])
    out = {}
    for st, g in n.groupby("station"):
        cyc = g.drop_duplicates("cycle_utc")[["cycle_utc", "available_utc"]].sort_values("cycle_utc")
        cycles = cyc.cycle_utc.to_numpy("datetime64[ns]").astype(np.int64)
        avail = cyc.available_utc.to_numpy("datetime64[ns]").astype(np.int64)
        h0 = cycles.min() // HOUR_NS
        vh = g.valid_utc.to_numpy("datetime64[ns]").astype(np.int64) // HOUR_NS
        assert (g.valid_utc.dt.minute == 0).all()
        ncols = int(vh.max() - h0 + 1)
        tmp = np.full((len(cycles), ncols), np.nan)
        tsd = np.full((len(cycles), ncols), np.nan)
        ci = np.searchsorted(cycles, g.cycle_utc.to_numpy("datetime64[ns]").astype(np.int64))
        col = (vh - h0).astype(int)
        isT = (g.field == "TMP").to_numpy()
        tmp[ci[isT], col[isT]] = g.value.to_numpy(float)[isT]
        tsd[ci[~isT], col[~isT]] = g.value.to_numpy(float)[~isT]
        out[st] = dict(cycles=cycles, avail=avail, h0=int(h0), tmp=tmp, tsd=tsd)
    return out


def build():
    snaps, bands = h.candidate_inputs()
    nbh = load_nbh()
    n = len(snaps)
    mu = np.full(n, np.nan)
    sig = np.full(n, np.nan)
    reason = np.array(["ok"] * n, dtype=object)
    latest_avail = np.full(n, np.iinfo(np.int64).min, dtype=np.int64)  # for the PIT assertion
    used_avail_max = np.full(n, np.iinfo(np.int64).min, dtype=np.int64)
    ties = 0
    t_ns = pd.to_datetime(snaps.captured_at_utc, utc=True).to_numpy("datetime64[ns]").astype(np.int64)
    # E = local midnight ending D, at the snapshot's own offset
    loc = snaps.captured_at_local.astype(str)
    offs = pd.to_timedelta(loc.str[-6:].str.replace(":", "", regex=False)
                           .map(lambda s: f"{s[0]}{s[1:3]}h{s[3:5]}m")).to_numpy("timedelta64[ns]").astype(np.int64)
    d_ns = pd.to_datetime(snaps.date).to_numpy("datetime64[ns]").astype(np.int64)
    e_ns = d_ns + 24 * HOUR_NS - offs    # local 00:00 of D+1 expressed in UTC
    stations = snaps.station.to_numpy()
    for i in range(n):
        S = nbh.get(stations[i])
        if S is None:
            reason[i] = "no_station"; continue
        t, E = t_ns[i], e_ns[i]
        if E <= t:
            reason[i] = "no_remaining_hours"; continue
        first_h = t // HOUR_NS + 1          # first top-of-hour strictly after t
        last_h = E // HOUR_NS               # E itself is top of hour
        vcols = np.arange(first_h, last_h + 1) - S["h0"]
        elig = np.flatnonzero(S["avail"] <= t)
        if elig.size == 0:
            reason[i] = "no_eligible_cycle"; continue
        # only cycles that could still carry v > t matter (horizon 25 h)
        elig = elig[S["cycles"][elig] >= (first_h - 25) * HOUR_NS]
        if elig.size == 0 or (vcols < 0).any() or (vcols >= S["tmp"].shape[1]).any():
            reason[i] = "uncovered_hour"; continue
        T = S["tmp"][np.ix_(elig, vcols)]
        has = ~np.isnan(T)
        if not has.any(axis=0).all():
            reason[i] = "uncovered_hour"; continue
        # latest eligible cycle carrying each v: last row (cycles ascending) with a value
        rows = T.shape[0] - 1 - np.argmax(has[::-1], axis=0)
        vals = T[rows, np.arange(len(vcols))]
        j = int(np.argmax(vals))            # earliest v among tied maxima
        if (vals == vals[j]).sum() > 1:
            ties += 1
        cyc_row = elig[rows[j]]
        s = S["tsd"][cyc_row, vcols[j]]
        if np.isnan(s):
            reason[i] = "no_tsd_at_argmax"; continue
        mu[i] = vals[j]
        sig[i] = max(float(s), 1.0)
        used_avail_max[i] = S["avail"][elig[np.unique(rows)]].max()
    ok = reason == "ok"
    # Rule 1 assertion on every cycle used by every covered snapshot
    h.assert_point_in_time(pd.to_datetime(used_avail_max[ok], utc=True),
                           pd.to_datetime(t_ns[ok], utc=True))

    floor = snaps.floor.to_numpy(float)
    B = np.where(np.isfinite(floor), np.floor(floor + 0.5), -np.inf)
    # band probabilities via H's CDF: F_H(k) = 0 if k < B else Phi((k + .5 - mu) / sigma)
    pos = h.data().snap_pos.reindex(bands.row_key.to_numpy()).to_numpy().astype(int)
    m, s_, b_ = mu[pos], sig[pos], B[pos]
    low = bands.low.to_numpy(float); high = bands.high.to_numpy(float)
    kind = bands.kind.to_numpy()

    def FH(k):
        return np.where(k < b_, 0.0, ndtr((k + 0.5 - m) / s_))

    p = np.where(kind == "lte", FH(high),
                 np.where(kind == "gte", 1.0 - FH(low - 1), FH(high) - FH(low - 1)))
    cov_band = ok[pos]
    cand = bands.loc[cov_band, ["row_key", "band_index"]].assign(p=np.clip(p[cov_band], 0, None))
    diag = dict(n_snapshots=int(n), covered=int(ok.sum()),
                reasons={k: int(v) for k, v in pd.Series(reason).value_counts().items()},
                argmax_ties=int(ties))
    return cand, diag, snaps.assign(mu=mu, sigma=sig, reason=reason)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    cand, diag, sn = build()
    diag["build_seconds"] = round(time.time() - t0, 1)
    res = h.score(cand, name="t23_t5r1_reimpl")
    h.save(res, OUT)
    (OUT / "t23_t5r1_reimpl.md").write_text(h.markdown(res), encoding="utf-8")
    sn[["row_key", "mu", "sigma", "reason"]].to_parquet(OUT / "t23_mu_sigma.parquet")
    print(json.dumps(diag))
    print(h.markdown(res))
    json.dump(diag, open(OUT / "t23_diag.json", "w"), indent=1)


if __name__ == "__main__":
    main()
