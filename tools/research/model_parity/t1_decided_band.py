"""T1 decided-band collapse (upper-side floor). Model-parity swarm v2, development only.

Once the day's high is "in" by at-t METAR evidence, move served mass that sits on bands above the
running-max band down into the running-max band.

Two stages:
  fit   : choose the decided condition (X deg F fallen below the METAR running max for N consecutive
          routine hourly rows, from local hour H on; or past local sunset) and the residual-rise
          lookup q(state, k) ONLY on A-IEM METAR history with local date <= 2026-07-31 (May-Oct).
          Nothing is fitted on the 111h evaluation table. 89b's parameters are not used.
  score : apply the frozen rule to the evaluation table via the F1 harness (floor applied, served
          fallback, all-row primary).

Point in time: a METAR/SPECI row enters snapshot t only if available_utc (= valid + 10 min) <= the
snapshot's captured_at_utc and is_cor is False (rule 1); h.assert_point_in_time is called on every
joined value. The running max used for band placement is the captured floor (floor_bucket = the
harness rule-4 floor), which is a captured production input. No market input, no label, no
settlement value enters the candidate (rules 2-3).

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.t1_decided_band [fit|score]
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

METAR = Path(r"C:\swarm\data\iem\metar")
STATIONS = Path(r"C:\swarm\stations.json")
OUT = Path(r"C:\swarm\out\t1")
FIT_END = "2026-07-31"
FIT_MONTHS = {5, 6, 7, 8, 9, 10}
RISE_CAP = 0.03          # decided condition must have historical P(final >= R+1) <= 3%


def sunset_utc(date_str, lat, lon):
    """NOAA simplified solar equation (same as F3); sunset as UTC Timestamp."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    n = dt.timetuple().tm_yday
    g = 2 * math.pi / 365 * (n - 1 + 0.5)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    la = math.radians(lat)
    ha = math.degrees(math.acos(math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(decl))
                                - math.tan(la) * math.tan(decl)))
    minutes = 720 - 4 * (lon - ha) - eqt
    return pd.Timestamp(dt, tz="UTC") + pd.Timedelta(minutes=minutes)


def stations():
    return json.loads(STATIONS.read_text(encoding="utf-8"))["stations"]


def load_metar(station):
    m = pd.read_parquet(METAR / f"{station}.parquet",
                        columns=["tmpf", "report_type", "valid_utc", "available_utc", "local_date", "is_cor"])
    m = m[m.tmpf.notna()].copy()
    m["local_date"] = m.local_date.astype(str)
    return m.sort_values("available_utc").reset_index(drop=True)


def obs_features(m, t_utc, dates, lat, lon, tz, nmax=4):
    """PIT features at times t_utc (tz-aware UTC Series) for local dates `dates` (str array).

    Uses non-COR rows with available_utc <= t and local_date == date. Returns DataFrame with
    runmax, cur, def_k (deficit runmax - tmpf of the k-th latest routine row, k=1..nmax, NaN when
    that row is missing or from another date), past_sunset, local_hour_obs, last_avail.
    """
    mm = m[~m.is_cor].reset_index(drop=True)
    mm["runmax"] = mm.groupby("local_date").tmpf.cummax()
    avail = mm.available_utc.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    t = pd.Series(t_utc).dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    i = np.searchsorted(avail, t, side="right") - 1
    ok = i >= 0
    ii = np.maximum(i, 0)
    same = ok & (mm.local_date.to_numpy()[ii] == dates)
    runmax = np.where(same, mm.runmax.to_numpy()[ii], np.nan)
    cur = np.where(same, mm.tmpf.to_numpy()[ii], np.nan)
    rt = mm[mm.report_type == "routine"].reset_index(drop=True)
    ravail = rt.available_utc.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    k0 = np.searchsorted(ravail, t, side="right") - 1
    out = {"runmax": runmax, "cur": cur, "last_avail_idx": np.where(ok, ii, -1)}
    rdate = rt.local_date.to_numpy()
    rtmp = rt.tmpf.to_numpy()
    for k in range(1, nmax + 1):
        kk = k0 - (k - 1)
        good = (kk >= 0) & same
        kc = np.maximum(kk, 0)
        good &= rdate[kc] == dates
        out[f"def_{k}"] = np.where(good, runmax - rtmp[kc], np.nan)
    sun = {d: sunset_utc(d, lat, lon).tz_localize(None).to_datetime64() for d in np.unique(dates)}
    sunv = np.array([sun[d] for d in dates], dtype="datetime64[us]")
    out["past_sunset"] = t > sunv
    out["min_after_sunset"] = (t - sunv) / np.timedelta64(1, "m")
    return pd.DataFrame(out), (avail, ii, ok)


def decided_mask(f, X, N, H, local_hour, use_sunset=True):
    fallen = np.ones(len(f), bool)
    for k in range(1, N + 1):
        fallen &= (f[f"def_{k}"].to_numpy() >= X)
    fallen &= local_hour >= H
    m = fallen
    if use_sunset:
        m = m | (f.past_sunset.to_numpy() & ~np.isnan(f.runmax.to_numpy()))
    return m & ~np.isnan(f.runmax.to_numpy())


# --------------------------------------------------------------------------------------------- fit
def history_points():
    """One evaluation point per routine METAR availability time on history dates <= FIT_END."""
    st = stations()
    parts = []
    for s, meta in st.items():
        m = load_metar(s)
        m = m[m.local_date <= FIT_END]
        assert (m.local_date <= FIT_END).all()
        final = m.groupby("local_date").tmpf.max()        # label proxy (truth side only)
        nrows = m[m.report_type == "routine"].groupby("local_date").size()
        good_days = nrows[nrows >= 20].index
        pts = m[(m.report_type == "routine") & ~m.is_cor & m.local_date.isin(good_days)].copy()
        pts = pts[pd.to_datetime(pts.local_date).dt.month.isin(FIT_MONTHS)]
        t = pts.available_utc + pd.Timedelta(seconds=1)
        f, _ = obs_features(m, t.reset_index(drop=True), pts.local_date.to_numpy(), meta["lat"], meta["lon"],
                            meta["tzname"])
        lh = t.dt.tz_convert(meta["tzname"]).dt.hour.to_numpy()
        f["local_hour"] = lh
        f["station"] = s
        f["date"] = pts.local_date.to_numpy()
        f["rise"] = final.reindex(pts.local_date).to_numpy() - f.runmax.to_numpy()
        parts.append(f)
    return pd.concat(parts, ignore_index=True)


def fit():
    OUT.mkdir(parents=True, exist_ok=True)
    P = history_points()
    P = P[P.runmax.notna() & (P.local_hour >= 12)].reset_index(drop=True)
    print("history points (local hour >= 12):", len(P), "station-days", P.groupby(["station", "date"]).ngroups,
          "date range", P.date.min(), P.date.max())
    assert P.date.max() <= FIT_END
    lh = P.local_hour.to_numpy()
    rise1 = P.rise.to_numpy() >= 1
    rows = []
    # sunset-only condition
    sun = P.past_sunset.to_numpy()
    rows.append(dict(X=None, N=None, H=None, cond="sunset_only", n=int(sun.sum()),
                     coverage=float(sun.mean()), rise_rate=float(rise1[sun].mean())))
    for X in (1, 2, 3, 4, 5):
        for N in (1, 2, 3, 4):
            for H in range(12, 21):
                fm = decided_mask(P, X, N, H, lh, use_sunset=False)
                if fm.sum() < 200:
                    continue
                dm = fm | sun
                rows.append(dict(X=X, N=N, H=H, cond="fallen_only", n=int(fm.sum()), coverage=float(fm.mean()),
                                 rise_rate=float(rise1[fm].mean()),
                                 coverage_with_sunset=float(dm.mean()),
                                 rise_rate_with_sunset=float(rise1[dm].mean())))
    G = pd.DataFrame(rows)
    G.to_csv(OUT / "fit_grid.csv", index=False)
    ok = G[(G.cond == "fallen_only") & (G.rise_rate <= RISE_CAP)]
    best = ok.sort_values(["coverage_with_sunset", "X", "N"], ascending=[False, True, True]).iloc[0]
    X, N, H = int(best.X), int(best.N), int(best.H)
    print("grid best:", best.to_dict())
    # residual-rise lookup q(state, hour-bucket, k): P(final - R >= k)
    dm_f = decided_mask(P, X, N, H, lh, use_sunset=False)
    state = np.where(sun, "sunset", np.where(dm_f, "fallen", "none"))
    hb = np.where(lh <= 16, "12-16", np.where(lh <= 19, "17-19", "20-23"))
    P["state"], P["hb"] = state, hb
    q = {}
    for (stt, b), g in P[P.state != "none"].groupby(["state", "hb"]):
        q[f"{stt}|{b}"] = {"n": int(len(g)), "k1": float((g.rise >= 1).mean()), "k2": float((g.rise >= 2).mean()),
                           "k3": float((g.rise >= 3).mean())}
    per_station = {}
    for s, g in P[P.state != "none"].groupby("station"):
        per_station[s] = {"n": int(len(g)), "k1": float((g.rise >= 1).mean()), "k2": float((g.rise >= 2).mean())}
    params = {"X": X, "N": N, "H": H, "rise_cap": RISE_CAP, "fit_end": FIT_END, "fit_months": sorted(FIT_MONTHS),
              "n_points": int(len(P)), "grid_best": {k: (None if (isinstance(v, float) and np.isnan(v)) else v)
                                                       for k, v in best.to_dict().items()},
              "sunset_only": rows[0], "q": q, "per_station_decided": per_station}
    (OUT / "fit_params.json").write_text(json.dumps(params, indent=1, default=float), encoding="utf-8")
    print(json.dumps(params, indent=1, default=float))
    return params


# ------------------------------------------------------------------------------------------- score
RULES = {}


def snapshot_obs(snaps, extra_lag_min=0):
    """PIT METAR features for every snapshot (extra_lag_min: sensitivity, added to valid+10 min)."""
    from tools.research.model_parity import harness as h
    st = stations()
    parts = []
    for s, g in snaps.groupby("station", sort=False):
        meta = st[s]
        m = load_metar(s)
        if extra_lag_min:
            m["available_utc"] = m.available_utc + pd.Timedelta(minutes=extra_lag_min)
        t = pd.to_datetime(g.captured_at_utc, utc=True, format="ISO8601").reset_index(drop=True)
        f, (avail, ii, ok) = obs_features(m, t, g.date.to_numpy(), meta["lat"], meta["lon"], meta["tzname"])
        mm = m[~m.is_cor].reset_index(drop=True)
        h.assert_point_in_time(mm.available_utc.to_numpy()[ii][ok], g.captured_at_utc.to_numpy()[ok])
        f["row_key"] = g.row_key.to_numpy()
        parts.append(f)
    return pd.concat(parts, ignore_index=True)


def build(snaps, bands, obs, params, variant):
    """Return candidate frame (row_key, band_index, p) for decided snapshots only."""
    X, N, H = params["X"], params["N"], params["H"]
    s = snaps[["row_key", "local_hour", "floor", "floor_bucket", "station"]].merge(obs, on="row_key", how="left")
    lh = s.local_hour.to_numpy()
    sun = s.past_sunset.fillna(False).to_numpy().astype(bool) & s.runmax.notna().to_numpy()
    fallen = decided_mask(s.fillna({"runmax": np.nan}), X, N, H, lh, use_sunset=False)
    if variant == "r3":
        dec = sun
    else:
        dec = sun | fallen
    hb = np.where(lh <= 16, "12-16", np.where(lh <= 19, "17-19", "20-23"))
    state = np.where(sun, "sunset", "fallen")
    s["dec"], s["qkey"] = dec, [f"{a}|{b}" for a, b in zip(state, hb)]
    s = s[s.dec & s.floor.notna()]
    B = bands.merge(s[["row_key", "floor_bucket", "runmax", "qkey"]], on="row_key", how="inner")
    lo = np.where(B.kind == "lte", -np.inf, B.low.astype(float))
    hi = np.where(B.kind == "gte", np.inf, B.high.astype(float))
    R = B.floor_bucket.to_numpy(float)
    at = (lo <= R) & (R <= hi)
    above = lo > R
    B["is_at"], B["is_above"] = at, above
    # safety: METAR running max must not lie above the floor band (else floor/obs disagree: skip)
    B["hi_if_at"] = np.where(at, hi, np.nan)
    band_hi_at = B.groupby("row_key").hi_if_at.max()
    B["at_hi"] = B.row_key.map(band_hi_at)
    bad = (np.round(B.runmax) > B.at_hi) | B.at_hi.isna()
    B = B[~bad.to_numpy()].copy()
    p = B.p_served.to_numpy(float).copy()
    lo = np.where(B.kind == "lte", -np.inf, B.low.astype(float))
    R = B.floor_bucket.to_numpy(float)
    below = np.where(B.kind == "gte", np.inf, B.high.astype(float)) < R
    p[below] = 0.0                      # rule-4 floor (the harness applies it again)
    above = B.is_above.to_numpy()
    at = B.is_at.to_numpy()
    B["p0"] = p
    if variant in ("r1",):
        target_above = np.zeros(len(B))
    else:
        # calibrated residual rise: total above mass = min(served above, q(state, k))
        k = (B.at_hi.to_numpy() + 1 - R)
        kk = np.clip(np.round(k).astype(int), 1, 3)
        qv = np.array([params["q"].get(qk, {}).get(f"k{j}", np.nan) for qk, j in zip(B.qkey, kk)])
        target_above = qv
    B["tgt"] = target_above
    g = B.assign(pa=np.where(above, p, 0.0), pat=np.where(at, p, 0.0), pb=np.where(~above & ~at, p, 0.0))
    agg = g.groupby("row_key").agg(sa=("pa", "sum"), sat=("pat", "sum"), sb=("pb", "sum"), tgt=("tgt", "first"))
    agg["tgt"] = np.where(np.isnan(agg.tgt), agg.sa, np.minimum(agg.sa, agg.tgt))
    agg["scale"] = np.where(agg.sa > 0, agg.tgt / agg.sa, 1.0)
    agg["moved"] = agg.sa - agg.tgt
    B = B.join(agg[["scale", "moved", "sat"]], on="row_key")
    newp = np.where(above, p * B.scale.to_numpy(), p)
    # moved mass goes to the running-max band(s)
    nat = B.groupby("row_key").is_at.transform("sum").to_numpy()
    newp = np.where(at, newp + B.moved.to_numpy() / np.maximum(nat, 1), newp)
    B["p"] = newp
    tot = B.groupby("row_key").p.transform("sum").to_numpy()
    B = B[tot > 0]
    B["p"] = B.p / B.groupby("row_key").p.transform("sum")
    return B[["row_key", "band_index", "p"]].reset_index(drop=True), int(B.row_key.nunique())


RULE_TEXT = {
    "r1": ("T1-r1 full decided-band collapse. At snapshot t, using non-COR METAR/SPECI rows with valid+10min <= "
           "captured_at_utc and local date = target date: decided := (past local sunset by NOAA solar equation, "
           "zenith 90.833) OR (local hour >= H AND the latest N routine METAR rows of the day each have tmpf <= "
           "METAR running max - X). X,N,H fitted on A-IEM METAR history (local dates <= 2026-07-31, months 5-10) "
           "as the max-coverage grid point (X in 1..5, N in 1..4, H in 12..20) whose historical P(final hourly max "
           ">= running max + 1F) <= 3%. When decided, all served mass on bands wholly above the band containing the "
           "captured floor_bucket is moved into that band; floor applied; renormalise. Skip (served fallback) if "
           "round(METAR running max) > that band's upper edge, or no floor."),
    "r2": ("T1-r2 calibrated decided-band collapse. Same decided condition and band placement as T1-r1 (same "
           "fitted X,N,H). When decided, total served mass above the floor band is capped at q(state,hour-bucket,k) "
           "= historical P(final - running max >= k) from A-IEM history <= 2026-07-31 (state in {sunset, fallen}, "
           "hour bucket 12-16/17-19/20-23, k = floor band upper edge + 1 - floor_bucket, clipped 1..3); above "
           "bands scaled proportionally; freed mass into the floor band; floor applied; renormalise; same skips."),
    "r2lag60": ("T1-r2lag60 sensitivity of T1-r2 (same frozen X,N,H,q): every METAR/SPECI row is treated as "
                "available only at valid + 60 min instead of valid + 10 min. Diagnostic of availability timing."),
    "r3": ("T1-r3 sunset-only calibrated collapse. As T1-r2 but decided := past local sunset only (no fallen "
           "condition), q from the history sunset cells."),
}


def register(ids):
    reg = Path(r"C:\swarm\registry.jsonl")
    have = set()
    if reg.exists():
        for line in reg.read_text(encoding="utf-8").splitlines():
            try:
                have.add(json.loads(line)["id"])
            except Exception:
                pass
    for i in ids:
        rid = f"t1-{i}"
        if rid in have:
            continue
        text = RULE_TEXT[i]
        rec = {"id": rid, "agent": "t1", "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest(),
               "time_local": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        with open(reg, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")


def score_all(variants=("r1", "r2", "r3")):
    from tools.research.model_parity import harness as h
    params = json.loads((OUT / "fit_params.json").read_text(encoding="utf-8"))
    snaps, bands = h.candidate_inputs()
    assert (snaps.date <= "2026-09-29").all()
    obs = snapshot_obs(snaps)
    obs.to_parquet(OUT / "t1_obs_pit.parquet")
    register(variants)
    results = {}
    for v in variants:
        if v == "r2lag60":
            cand, ncov = build(snaps, bands, snapshot_obs(snaps, extra_lag_min=50), params, "r2")
        else:
            cand, ncov = build(snaps, bands, obs, params, v)
        res = h.score(cand, name=f"t1_{v}_decided_band")
        h.save(res, OUT)
        (OUT / f"t1_{v}.md").write_text(h.markdown(res), encoding="utf-8")
        results[v] = res
        print(v, "covered snapshots", ncov)
        print(h.markdown(res))
        if res.get("leakage_suspect_groups"):
            print("LEAKAGE SUSPECT", res["leakage_suspect_groups"])
    return results


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fit"
    if cmd == "fit":
        fit()
    elif cmd == "score":
        score_all(tuple(sys.argv[2:]) or ("r1", "r2", "r3"))
