"""F3 gap atlas (model-parity swarm v2, development only). BEFORE stratum only.

Decomposes served-minus-market Brier excess by market x local-hour block x at-t METAR obs state x
band position (relative to the PIT METAR running max), and draws the market information-arrival
curve (market Brier vs minutes since the latest routine METAR). The market is the scoreboard only.

Point in time: an observation enters snapshot t only if its available_utc (= valid + 10 min, from
A-IEM) <= captured_at_utc; COR reports excluded (rule 1). From-stratum rows are dropped up front
(DESIGN section 2: the from-stratum atlas is Phase 5 only).

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.f3_atlas
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h

METAR = Path(r"C:\swarm\data\iem\metar")
STATIONS = Path(r"C:\swarm\stations.json")
OUT = Path(r"C:\swarm\out\f3")
ATLAS = Path(r"C:\swarm\atlas")
STRATUM = "before_20260823"
TREND_LAG_MIN = 45          # trend = current - last obs valid >= 45 min before the current obs


def sunset_utc(date_str, lat, lon):
    """NOAA simplified solar equation; returns sunset as a UTC pandas Timestamp."""
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
    minutes = 720 - 4 * (lon - ha) - eqt      # sunset in minutes after 00 UTC of that date
    return pd.Timestamp(dt, tz="UTC") + pd.Timedelta(minutes=minutes)


def _naive(series):
    """tz-aware UTC series -> numpy datetime64[us] (naive UTC)."""
    return pd.Series(series).dt.tz_convert("UTC").dt.tz_localize(None).dt.as_unit("us").to_numpy()


def obs_state(snaps):
    """PIT METAR state per snapshot (no market, no labels)."""
    st = json.loads(STATIONS.read_text(encoding="utf-8"))["stations"]
    parts = []
    for station, g in snaps.groupby("station", sort=False):
        m = pd.read_parquet(METAR / f"{station}.parquet",
                            columns=["tmpf", "report_type", "valid_utc", "available_utc", "local_date", "is_cor"])
        m = m[~m.is_cor & m.tmpf.notna()].sort_values("available_utc").reset_index(drop=True)
        m["local_date"] = m.local_date.astype(str)
        m["runmax"] = m.groupby("local_date").tmpf.cummax()
        avail = _naive(m.available_utc)
        valid = _naive(m.valid_utc)
        rout = m[m.report_type == "routine"].reset_index(drop=True)
        t = _naive(pd.to_datetime(g.captured_at_utc, utc=True, format="ISO8601"))
        i = np.searchsorted(avail, t, side="right") - 1
        ok = i >= 0
        ii = np.where(ok, i, 0)
        same_day = ok & (m.local_date.to_numpy()[ii] == g.date.to_numpy())
        h.assert_point_in_time(m.available_utc.to_numpy()[ii][ok], g.captured_at_utc.to_numpy()[ok])
        cur = np.where(ok, m.tmpf.to_numpy()[ii], np.nan)
        cur_valid = valid[ii]
        j = np.searchsorted(valid, cur_valid - np.timedelta64(TREND_LAG_MIN, "m"), side="right") - 1
        prev = np.where(ok & (j >= 0), m.tmpf.to_numpy()[np.maximum(j, 0)], np.nan)
        prev_age = (cur_valid - valid[np.maximum(j, 0)]) / np.timedelta64(1, "m")
        prev = np.where(prev_age <= 120, prev, np.nan)
        k = np.searchsorted(_naive(rout.available_utc), t, side="right") - 1
        rvalid = _naive(rout.valid_utc)[np.maximum(k, 0)]
        lat, lon = st[station]["lat"], st[station]["lon"]
        sunsets = {dd: sunset_utc(dd, lat, lon) for dd in g.date.unique()}
        sun = _naive(pd.to_datetime(g.date.map(sunsets), utc=True))
        parts.append(pd.DataFrame({
            "row_key": g.row_key.to_numpy(),
            "metar_runmax": np.where(same_day, m.runmax.to_numpy()[ii], np.nan),
            "metar_current": np.where(same_day, cur, np.nan),
            "metar_trend_1h": np.where(same_day, cur - prev, np.nan),
            "min_since_obs_valid": np.where(ok, (t - cur_valid) / np.timedelta64(1, "m"), np.nan),
            "min_since_routine_valid": np.where(k >= 0, (t - rvalid) / np.timedelta64(1, "m"), np.nan),
            "past_sunset": t > sun,
            "sunset_utc": sun,
        }))
    o = pd.concat(parts, ignore_index=True)
    o["deficit"] = o.metar_runmax - o.metar_current
    tr = o.metar_trend_1h
    o["trend"] = np.select([tr.isna(), tr >= 1, tr <= -1], ["na", "rising", "falling"], "flat")
    o["state"] = np.select(
        [o.metar_runmax.isna(), o.past_sunset, o.deficit >= 3, o.deficit >= 1,
         (o.deficit == 0) & (o.trend == "rising")],
        ["no_obs_today", "past_sunset", "off_max_3plus", "off_max_1_2", "at_max_rising"],
        "at_max_flat_or_falling")
    return o


def band_position(bands, runmax):
    lo, hi, kind = bands.low.to_numpy(float), bands.high.to_numpy(float), bands.kind.to_numpy()
    lo = np.where(kind == "lte", -np.inf, lo)
    hi = np.where(kind == "gte", np.inf, hi)
    r = np.round(runmax)
    return np.select([np.isnan(r), hi < r, lo > r], ["no_obs", "below", "above"], "at")


def main():
    if Path(r"C:\swarm\STOP").exists():
        raise SystemExit("STOP present")
    OUT.mkdir(parents=True, exist_ok=True)
    ATLAS.mkdir(parents=True, exist_ok=True)
    d = h.data()
    sel = (d.snaps.stratum == STRATUM).to_numpy()
    assert (d.snaps.date[sel] <= "2026-08-22").all() and (d.snaps.date <= h.LAST_TARGET_DATE).all()
    snaps_in, _ = h.candidate_inputs()
    snaps_in = snaps_in[sel].reset_index(drop=True)
    o = obs_state(snaps_in)
    o = snaps_in[["row_key", "market", "station", "date", "local_hour", "block", "captured_at_utc",
                  "high_so_far", "floor"]].merge(o, on="row_key", how="left", validate="1:1")
    o.to_parquet(ATLAS / "f3_obs_state_before.parquet", index=False)   # input-safe: no market/labels

    # scoreboard (labels and market): band-level excess contributions, snapshot-weighted
    bsel = sel[d.band_snap]
    nb = d.snaps.n_bands.to_numpy()[d.band_snap]
    B = d.bands.loc[bsel, ["row_key", "market", "date", "local_hour", "block", "kind", "low", "high"]].copy()
    B["c_served"] = (d.se_served / nb)[bsel]
    B["c_market"] = (d.se_market / nb)[bsel]
    B["excess"] = B.c_served - B.c_market
    B["tail"] = d.tail[bsel]
    B["over_market"] = (d.p_served - d.p_market)[bsel]   # served minus market probability
    B["is_winner"] = d.y[bsel]
    B = B.merge(o[["row_key", "state", "trend", "metar_runmax", "past_sunset", "min_since_routine_valid"]],
                on="row_key", how="left")
    B["band_pos"] = band_position(B, B.metar_runmax.to_numpy())
    B["tail_excess"] = np.where(B.tail, B.excess.clip(lower=0), 0.0)
    total = B.excess.sum()
    nsnap_total = int(sel.sum())

    def cells(keys):
        g = B.groupby(keys, observed=True)
        t = g.agg(excess=("excess", "sum"), served_loss=("c_served", "sum"), market_loss=("c_market", "sum"),
                  tail_excess=("tail_excess", "sum"),
                  mass_over_market=("over_market", "sum"), band_rows=("excess", "size")).reset_index()
        ns = B.drop_duplicates("row_key").groupby([k for k in keys if k != "band_pos"], observed=True).size()
        t["share_of_excess"] = t.excess / total
        return t, ns

    # 1) block x state (snapshot-level)
    S = o.copy()
    snap_ex = B.groupby("row_key")[["excess", "c_served", "c_market"]].sum()
    S = S.join(snap_ex, on="row_key")
    S["served_minus_market"] = S.excess
    key_index = d.key_index

    def ci_mean(frame, mask):
        """Mean excess per snapshot in mask, ratio of sums over market-day cells (W)."""
        f = frame.assign(a=np.where(mask, frame.excess, 0.0), b=mask.astype(float))
        c = f.groupby(["date", "market"])[["a", "b"]].sum().reset_index()
        c = c[c.b > 0]
        idx = np.array([key_index[(x, y)] for x, y in zip(c.date, c.market)])
        r = h.interval(idx, c.a.to_numpy(), c.b.to_numpy())
        return r["estimate"], r["ci95"]

    rows = []
    for blk in [b[0] for b in h.BLOCKS]:
        bm = (S.block == blk).to_numpy()
        for stt in sorted(S.state.unique()):
            m = bm & (S.state == stt).to_numpy()
            if m.sum() < 30:
                continue
            est, ci = ci_mean(S, m)
            rows.append({"block": blk, "state": stt, "snapshots": int(m.sum()),
                         "snap_share_of_block": float(m.sum() / bm.sum()),
                         "served_brier": float(S.c_served[m].mean()), "market_brier": float(S.c_market[m].mean()),
                         "mean_excess": est, "mean_excess_ci95": ci,
                         "share_of_total_excess": float(S.excess[m].sum() / total)})
    T1 = pd.DataFrame(rows)
    T1.to_parquet(ATLAS / "f3_block_state_before.parquet", index=False)

    # 2) block x state x band_pos (band-level)
    T2, _ = cells(["block", "state", "band_pos"])
    T2.to_parquet(ATLAS / "f3_block_state_bandpos_before.parquet", index=False)
    T2b, _ = cells(["block", "band_pos"])

    # 3) market x block (+ state) shares
    T3, _ = cells(["market", "block", "state"])
    T3.to_parquet(ATLAS / "f3_market_block_state_before.parquet", index=False)
    T3m = B.groupby(["market", "block"]).excess.sum().unstack("block") / total

    # 4) information-arrival curve: market Brier vs minutes since latest routine METAR valid
    S["min_bin"] = pd.cut(S.min_since_routine_valid, [0, 15, 20, 25, 30, 40, 50, 60, 75, 1e9], right=False,
                          labels=["<15", "15-19", "20-24", "25-29", "30-39", "40-49", "50-59", "60-74", "75+"])
    S["hourcell"] = S.date + "|" + S.market + "|" + S.local_hour.astype(str)
    S["mkt_resid"] = S.c_market - S.groupby("hourcell").c_market.transform("mean")
    S["srv_resid"] = S.c_served - S.groupby("hourcell").c_served.transform("mean")
    arr = S.groupby(["block", "min_bin"], observed=True).agg(
        snapshots=("row_key", "size"), market_brier=("c_market", "mean"), served_brier=("c_served", "mean"),
        market_resid_within_hour=("mkt_resid", "mean"), served_resid_within_hour=("srv_resid", "mean")
    ).reset_index()
    arr_all = S.groupby("min_bin", observed=True).agg(
        snapshots=("row_key", "size"), market_brier=("c_market", "mean"), served_brier=("c_served", "mean"),
        market_resid_within_hour=("mkt_resid", "mean"), served_resid_within_hour=("srv_resid", "mean")
    ).reset_index().assign(block="all")
    ARR = pd.concat([arr, arr_all], ignore_index=True)
    ARR["min_bin"] = ARR.min_bin.astype(str)
    ARR.to_parquet(ATLAS / "f3_arrival_curve_before.parquet", index=False)
    # one contrast with an interval: first 15 min after a routine METAR becomes available (valid+10..+25)
    # vs 40-59 min after valid, within-hour residual, pooled
    early = S.min_since_routine_valid.between(10, 25).to_numpy()
    late = S.min_since_routine_valid.between(40, 60).to_numpy()

    def contrast(col):
        f = S.assign(e=np.where(early, S[col], 0.0), ne=early.astype(float),
                     l=np.where(late, S[col], 0.0), nl=late.astype(float))
        c = f.groupby(["date", "market"])[["e", "ne", "l", "nl"]].sum().reset_index()
        c = c[(c["ne"] > 0) & (c["nl"] > 0)]
        idx = np.array([key_index[(x, y)] for x, y in zip(c.date, c.market)])
        w = d.w[:, idx]
        boot = (w @ c["e"].to_numpy()) / (w @ c["ne"].to_numpy()) - (w @ c["l"].to_numpy()) / (w @ c["nl"].to_numpy())
        pt = c["e"].sum() / c["ne"].sum() - c["l"].sum() / c["nl"].sum()
        return float(pt), np.quantile(boot[np.isfinite(boot)], [.025, .975]).tolist()

    con = {"NOTE": "confounded with minute-of-hour (routine METARs are at :51-:56); see event_step",
           "market_resid_early_minus_late": contrast("mkt_resid"),
           "served_resid_early_minus_late": contrast("srv_resid")}

    # 5) event-centred step test (descriptive scoreboard analysis, not a candidate): for each routine
    # METAR valid time V, snapshots with x = t - V in [-30, 30) min; residual vs that event window's mean;
    # step = mean resid x in [5,25) minus x in [-20,0). Placebo = same at V+30 (half past; no routine obs).
    # A smooth within-hour trend gives the same step in both; real - placebo isolates a jump at the obs.
    ev_rows = []
    tt = _naive(pd.to_datetime(S.captured_at_utc, utc=True, format="ISO8601"))
    xs = np.full(len(S), np.nan)
    evv = np.full(len(S), np.datetime64("NaT"), dtype="datetime64[us]")
    for station in S.station.unique():
        m = pd.read_parquet(METAR / f"{station}.parquet", columns=["report_type", "valid_utc", "is_cor"])
        v = np.sort(_naive(m.valid_utc[(m.report_type == "routine") & ~m.is_cor]))
        mk = (S.station == station).to_numpy()
        t0 = tt[mk]
        q = np.searchsorted(v, t0 - np.timedelta64(30, "m"), side="right")   # first V > t-30
        q = np.minimum(q, len(v) - 1)
        V = v[q]
        x = (t0 - V) / np.timedelta64(1, "m")
        okx = (x >= -30) & (x < 30)
        xs[mk] = np.where(okx, x, np.nan)
        evv[mk] = np.where(okx, V, np.datetime64("NaT"))
    S["x_real"] = xs
    S["ev_real"] = evv
    xp = (S.x_real + 30) % 60 - 30   # x relative to V+30 (or V-30)
    S["x_plac"] = xp
    S["ev_plac"] = np.where(S.x_real >= 0, S.ev_real + pd.Timedelta(minutes=30),
                            S.ev_real - pd.Timedelta(minutes=30))
    S["xbin"] = (np.floor(S.x_real / 5) * 5)

    def step(col, xcol, evcol, blockmask):
        f = S[blockmask & S[xcol].notna()].copy()
        f["cell"] = f.date + "|" + f.market + "|" + f[evcol].astype(str)
        f["r"] = f[col] - f.groupby("cell")[col].transform("mean")
        aft = f[xcol].between(5, 24.999).to_numpy()
        bef = f[xcol].between(-20, -0.001).to_numpy()
        f = f.assign(a=np.where(aft, f.r, 0.0), na=aft.astype(float), b=np.where(bef, f.r, 0.0), nb=bef.astype(float))
        c = f.groupby(["date", "market"])[["a", "na", "b", "nb"]].sum()
        return c

    def step_ci(col, blockmask):
        cr = step(col, "x_real", "ev_real", blockmask)
        cp = step(col, "x_plac", "ev_plac", blockmask)
        c = cr.join(cp, lsuffix="_r", rsuffix="_p", how="inner").reset_index()
        idx = np.array([key_index[(x, y)] for x, y in zip(c.date, c.market)])
        w = d.w[:, idx]

        def s(wv, sfx):
            return (wv @ c["a" + sfx]) / (wv @ c["na" + sfx]) - (wv @ c["b" + sfx]) / (wv @ c["nb" + sfx])
        one = np.ones((1, len(c)))
        pr, pp = s(one, "_r")[0], s(one, "_p")[0]
        br, bp = s(w, "_r"), s(w, "_p")
        dd = br - bp
        q = lambda a: np.quantile(a[np.isfinite(a)], [.025, .975]).tolist()
        return {"real_step": float(pr), "real_ci95": q(br), "placebo_step": float(pp), "placebo_ci95": q(bp),
                "real_minus_placebo": float(pr - pp), "real_minus_placebo_ci95": q(dd)}

    event_step = {}
    for blk, lo, hi in h.BLOCKS + (("all", 0, 23),):
        bm = S.local_hour.between(lo, hi)
        event_step[blk] = {"market": step_ci("c_market", bm), "served": step_ci("c_served", bm),
                           "excess": step_ci("excess", bm)}
    curve = S[S.x_real.notna()].assign(
        cell=lambda f: f.date + "|" + f.block + "|" + f.market + "|" + f.ev_real.astype(str))
    curve["mr"] = curve.c_market - curve.groupby("cell").c_market.transform("mean")
    curve["sr"] = curve.c_served - curve.groupby("cell").c_served.transform("mean")
    EC = curve.groupby(["block", "xbin"]).agg(snapshots=("row_key", "size"), market_resid=("mr", "mean"),
                                              served_resid=("sr", "mean")).reset_index()
    EC.to_parquet(ATLAS / "f3_event_curve_before.parquet", index=False)
    con["event_step"] = event_step

    # 6) probability mass above the PIT METAR running-max band: served vs market vs realised
    B["p_s"] = d.p_served[bsel]
    B["p_m"] = d.p_market[bsel]
    ab = B[B.band_pos == "above"].groupby("row_key")[["p_s", "p_m", "is_winner"]].sum()
    S2 = S[["row_key", "block", "state", "date", "market"]].join(ab, on="row_key").fillna(
        {"p_s": 0.0, "p_m": 0.0, "is_winner": 0.0})
    S2 = S2[S.metar_runmax.notna().to_numpy()]
    AB = S2.groupby(["block", "state"]).agg(snapshots=("row_key", "size"), served_p_above=("p_s", "mean"),
                                            market_p_above=("p_m", "mean"),
                                            realised_above=("is_winner", "mean"),
                                            market_days=("date", lambda x: 0)).reset_index()
    AB["market_days"] = S2.groupby(["block", "state"]).apply(
        lambda g: g.groupby(["date", "market"]).ngroups).to_numpy()
    AB.to_parquet(ATLAS / "f3_mass_above_runmax_before.parquet", index=False)
    print(AB.round(4).to_string())
    cad = S.sort_values(["market", "captured_at_utc"]).groupby("market").captured_at_utc.apply(
        lambda s_: pd.to_datetime(s_, format="ISO8601").diff().dt.total_seconds().median() / 60)
    con["snapshot_cadence_median_min"] = cad.to_dict()

    res = {"agent": "f3", "HARNESS_SHA256": h.harness_sha256(), "stratum": STRATUM,
           "snapshots": nsnap_total, "market_days": int(S.groupby(["date", "market"]).ngroups),
           "dates": int(S.date.nunique()), "total_excess_snapshot_sum": float(total),
           "served_brier": float(S.c_served.mean()), "market_brier": float(S.c_market.mean()),
           "rows_after_2026_09_29": int((d.snaps.date > h.LAST_TARGET_DATE).sum()),
           "state_counts": S.state.value_counts().to_dict(),
           "metar_runmax_vs_high_so_far": {
               "both_present": int((S.metar_runmax.notna() & S.high_so_far.notna()).sum()),
               "mean_abs_diff": float((S.metar_runmax - S.high_so_far).abs().mean()),
               "share_equal_rounded": float((np.round(S.metar_runmax) == np.round(S.high_so_far))[
                   S.metar_runmax.notna() & S.high_so_far.notna()].mean())},
           "arrival_contrast": con,
           "time_local": datetime.now().isoformat(timespec="seconds")}
    (OUT / "result.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    pd.set_option("display.width", 250, "display.max_rows", 500, "display.max_columns", 30)
    print(json.dumps(res, indent=1, default=str))
    print(T1.round(5).to_string())
    print((T2b.assign(sh=T2b.share_of_excess.round(4))).to_string())
    print(T2[T2.share_of_excess.abs() > 0.01].sort_values("share_of_excess", ascending=False).round(5).to_string())
    print(T3m.round(4).to_string())
    print(ARR.round(5).to_string())
    print(EC.round(5).to_string())


if __name__ == "__main__":
    main()
