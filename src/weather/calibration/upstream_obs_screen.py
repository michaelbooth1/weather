"""Lane L6 research screen: do upstream / nearby ASOS observations improve the 07-12 morning forecast?

Offline research only. Reads the IEM extract built by ``weather.sources.free_screens.iem_upstream``
(``<root>/upstream_obs/obs.parquet`` and ``selection.json``) and, for ``serve``, the input snapshots of the
development layout (never labels, prices or anything dated after 2026-09-29). Writes only under ``--out``.
No network. Pre-declared rule: ``C:\\t\\l6\\rule.md`` (sha256 recorded in the results record).

Point in time (AGENT_CONTEXT: observation instant, station-local date, nothing after emission):
- market station rows are usable from valid + 10 min, ring (AWOS/ASOS neighbour) rows from valid + 20 min;
- a "latest" value must be <= 90 min old at the cutoff; the 3-hour-ago value is the latest usable at t - 3 h;
- the running max is over the market station's same-local-date rows usable at t;
- the previous-day max is the complete previous local date (>= 20 routine rows).
History cutoffs are local H:30 for H = 7..12; serve cutoffs are each snapshot's ``captured_at_utc``.

Label (history only): dmax = half-up of the max over routine, non-COR market-station rows of the local date
(T-group F when present, else tmpf; routine = the station-year's modal report minute), >= 20 rows.

Model (fixed a priori, no tuning): ``HistGradientBoostingRegressor`` of y = dmax - R (R = running max) on
the OWN feature set (twin) and on OWN + UPSTREAM (candidate), pooled over stations and hours 7-12 with the
station as a categorical feature. Validation: blocked leave-one-year-out over 2021-2025 Aug-Sep (primary)
and Oct-Dec (reported). Serve: both models refit on all Aug-Sep 2021-2025 rows, nowcast N = R + y_hat.

CLI::

    python -m weather.calibration.upstream_obs_screen features --out DIR
    python -m weather.calibration.upstream_obs_screen loyo --out DIR
    python -m weather.calibration.upstream_obs_screen serve --out DIR --layout C:\\swarm\\v3layout
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_PRODUCTION_PREFIXES = ("weather.operations", "weather.market", "weather.model", "weather.serving",
                        "weather.trading", "weather.capture", "maker_core", "app")


def _refuse_production_import():
    """Fail closed when imported from a production package (research-only module)."""
    frame = sys._getframe(1)
    while frame is not None:
        name = frame.f_globals.get("__name__", "") or ""
        if any(name == p or name.startswith(p + ".") for p in _PRODUCTION_PREFIXES):
            raise ImportError(f"weather.calibration.upstream_obs_screen is research-only; imported from {name}")
        frame = frame.f_back


_refuse_production_import()

DEV_LAST = "2026-09-29"
DEFAULT_ROOT = Path(r"C:\Users\Michael\Documents\github\weather\data\research")
MARKET_LAT_MIN, RING_LAT_MIN = 10, 20
MAX_AGE_MIN = 90
HOURS = (7, 8, 9, 10, 11, 12)
MIN_ROUTINE = 20
SEED = 20260921
DRAWS = 2000
TRAIN_MONTHS_PRIMARY = (8, 9)
TRAIN_MONTHS_SECONDARY = (10, 11, 12)
HGB_PARAMS = dict(max_iter=300, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40, l2_regularization=1.0,
                  random_state=0)

OWN = ("hour_f", "doy", "station_code", "t", "td", "r", "t_minus_r", "tend3", "td_tend3", "u", "v", "spd",
       "cover", "log_ceiling", "prev_dmax", "prev_minus_t")
UP = ("n_ring", "ring_dt", "ring_dtd", "ring_cover", "ring_log_ceiling", "ring_dtend3", "flow_u", "flow_v",
      "uw_dt", "uw_dtd", "uw_cover", "uw_log_ceiling", "uw_dtend3", "adv", "pv_dt", "pv_dtd", "pv_cover")


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def half_up(x):
    return np.floor(np.asarray(x, float) + 0.5)


# ----------------------------------------------------------------------------- observations

def load(root):
    src = Path(root) / "upstream_obs"
    obs = pd.read_parquet(src / "obs.parquet")
    sel = json.loads((src / "selection.json").read_text(encoding="utf-8"))["markets"]
    obs = obs[~obs.is_cor].copy()
    obs["temp"] = np.where(np.isfinite(obs.tgroup_f), obs.tgroup_f, obs.tmpf)
    obs = obs[np.isfinite(obs.temp)]
    return obs, sel, {"obs_sha256": sha_file(src / "obs.parquet"), "selection_sha256": sha_file(src / "selection.json")}


def routine_mask(g):
    """Rows at the station-year's modal report minute (ASOS routine), per station."""
    minute = g.valid_utc.dt.minute
    year = g.valid_utc.dt.year
    modal = minute.groupby(year).agg(lambda m: int(m.mode().iloc[0]))
    return (minute == year.map(modal)).to_numpy()


def market_series(obs, icao, tz):
    g = obs[(obs.role == "market") & (obs.station == icao[1:])].sort_values("valid_utc").copy()
    g["local_date"] = g.valid_utc.dt.tz_convert(tz).dt.strftime("%Y-%m-%d")
    g["routine"] = routine_mask(g)
    g["avail"] = g.valid_utc + pd.Timedelta(minutes=MARKET_LAT_MIN)
    g["rmax"] = g.groupby("local_date").temp.cummax()
    rt = g[g.routine]
    day = rt.groupby("local_date").agg(n=("temp", "size"), mx=("temp", "max"))
    mx = day.mx.where(day.n >= MIN_ROUTINE)
    dmax = pd.Series(half_up(mx), index=day.index).dropna()
    if (dmax.index > DEV_LAST).any():
        raise AssertionError(f"{icao}: labels after {DEV_LAST}")
    return g, dmax


def _asof(q, s, tcol, cols, prefix, max_age=MAX_AGE_MIN):
    """Latest row of ``s`` with avail <= q[tcol]; values older than max_age (by valid time) become NaN."""
    left = q[[tcol]].reset_index().sort_values(tcol)
    right = s[["avail", "valid_utc", *cols]].sort_values("avail")
    m = pd.merge_asof(left, right, left_on=tcol, right_on="avail", direction="backward").set_index("index")
    m = m.reindex(q.index)
    stale = (q[tcol] - m.valid_utc) > pd.Timedelta(minutes=max_age)
    out = pd.DataFrame(index=q.index)
    for c in cols:
        out[f"{prefix}{c}"] = m[c].where(~stale)
    return out


def _uv(drct, sknt):
    d, s = np.asarray(drct, float), np.asarray(sknt, float)
    return -s * np.sin(np.radians(d)), -s * np.cos(np.radians(d))


def features(q, obs, sel_market, icao, tz, station_code, market_g, dmax):
    """Feature frame for queries ``q`` (columns t_utc, local_date) of one market. Index preserved."""
    q = q.copy()
    q["t3"] = q.t_utc - pd.Timedelta(hours=3)
    cols = ["temp", "dwpf", "drct", "sknt", "cover", "ceiling_ft"]
    now = _asof(q, market_g, "t_utc", cols, "")
    ago = _asof(q, market_g, "t3", ["temp", "dwpf"], "a_")
    # running max of the same local date, usable at t
    left = q[["t_utc", "local_date"]].reset_index().sort_values("t_utc")
    right = market_g[["avail", "local_date", "rmax"]].sort_values("avail")
    rm = pd.merge_asof(left, right, left_on="t_utc", right_on="avail", by="local_date",
                       direction="backward").set_index("index").reindex(q.index)
    local = q.t_utc.dt.tz_convert(tz)
    f = pd.DataFrame(index=q.index)
    f["hour_f"] = local.dt.hour + local.dt.minute / 60.0
    f["doy"] = local.dt.dayofyear
    f["station_code"] = station_code
    f["t"], f["td"], f["r"] = now.temp, now.dwpf, rm.rmax
    f["r"] = np.fmax(f.r.to_numpy(float), f.t.to_numpy(float))
    f["t_minus_r"] = f.t - f.r
    f["tend3"], f["td_tend3"] = now.temp - ago.a_temp, now.dwpf - ago.a_dwpf
    u, v = _uv(now.drct, now.sknt)
    calm = (now.sknt == 0).to_numpy()
    f["u"], f["v"] = np.where(calm, 0.0, u), np.where(calm, 0.0, v)
    f["spd"] = now.sknt
    f["cover"] = now.cover
    f["log_ceiling"] = np.log10(np.where(np.isfinite(now.ceiling_ft), now.ceiling_ft,
                                         np.where(np.isfinite(now.cover), 30000.0, np.nan)).clip(100))
    prev = (pd.to_datetime(q.local_date) - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
    f["prev_dmax"] = prev.map(dmax).astype(float)
    f["prev_minus_t"] = f.prev_dmax - f.t
    # ring
    here = (sel_market["lat"], sel_market["lon"])
    ring = sel_market["selected"]
    dt, dtd, cov, lce, dten, uu, vv, brg, dist, pv = [], [], [], [], [], [], [], [], [], []
    for c in ring:
        s = obs[(obs.role == "ring") & (obs.station == c["sid"]) & (obs.market == sel_market["market"])]
        if s.empty:
            continue
        s = s.sort_values("valid_utc").assign(avail=lambda x: x.valid_utc + pd.Timedelta(minutes=RING_LAT_MIN))
        a = _asof(q, s, "t_utc", cols, "")
        b = _asof(q, s, "t3", ["temp"], "a_")
        dt.append((a.temp - f.t).to_numpy(float))
        dtd.append((a.dwpf - f.td).to_numpy(float))
        cov.append(a.cover.to_numpy(float))
        lce.append(np.log10(np.where(np.isfinite(a.ceiling_ft), a.ceiling_ft,
                                     np.where(np.isfinite(a.cover), 30000.0, np.nan)).clip(100)))
        dten.append(((a.temp - b.a_temp) - f.tend3).to_numpy(float))
        ru, rv = _uv(a.drct, a.sknt)
        rcalm = (a.sknt == 0).to_numpy()
        uu.append(np.where(rcalm, 0.0, ru))
        vv.append(np.where(rcalm, 0.0, rv))
        brg.append(c["bearing_deg"])
        dist.append(c["dist_km"])
        pv.append(bool(c["upwind_prevailing"]))
    n = len(dt)
    nanv = np.full(len(q), np.nan)
    if n == 0:
        for k in UP:
            f[k] = nanv
        return f
    DT, DTD, COV, LCE, DTEN = map(np.vstack, (dt, dtd, cov, lce, dten))
    UU, VV = np.vstack(uu), np.vstack(vv)
    with np.errstate(invalid="ignore", divide="ignore"):
        f["n_ring"] = np.isfinite(DT).sum(axis=0)
        f["ring_dt"], f["ring_dtd"] = np.nanmean(DT, 0), np.nanmean(DTD, 0)
        f["ring_cover"], f["ring_log_ceiling"] = np.nanmean(COV, 0), np.nanmean(LCE, 0)
        f["ring_dtend3"] = np.nanmean(DTEN, 0)
        # flow: vector mean of the market station's and ring winds (toward-vector components)
        allu = np.vstack([UU, f.u.to_numpy(float)[None, :]])
        allv = np.vstack([VV, f.v.to_numpy(float)[None, :]])
        fu, fv = np.nanmean(allu, 0), np.nanmean(allv, 0)
        f["flow_u"], f["flow_v"] = fu, fv
        flow_from = (np.degrees(np.arctan2(-fu, -fv)) + 360.0) % 360.0
        fspd = np.hypot(fu, fv)
        B = np.asarray(brg)[:, None]
        W = np.clip(np.cos(np.radians(flow_from[None, :] - B)), 0.0, None)
        W = np.where(np.isfinite(DT) & np.isfinite(W), W, 0.0)
        ws = W.sum(0)
        ok = ws > 0.05

        def wmean(X):
            Xf = np.where(np.isfinite(X), X, 0.0)
            Wx = np.where(np.isfinite(X), W, 0.0)
            s = Wx.sum(0)
            return np.where(s > 0.05, (Wx * Xf).sum(0) / np.where(s > 0, s, 1), np.nan)

        f["uw_dt"], f["uw_dtd"], f["uw_cover"] = wmean(DT), wmean(DTD), wmean(COV)
        f["uw_log_ceiling"], f["uw_dtend3"] = wmean(LCE), wmean(DTEN)
        wdist = np.where(ok, (W * np.asarray(dist)[:, None]).sum(0) / np.where(ok, ws, 1), np.nan)
        f["adv"] = f.uw_dt.to_numpy(float) * fspd * 1.852 / wdist   # F per hour toward the station
        P = np.asarray(pv)
        if P.any():
            f["pv_dt"], f["pv_dtd"], f["pv_cover"] = (np.nanmean(DT[P], 0), np.nanmean(DTD[P], 0),
                                                      np.nanmean(COV[P], 0))
        else:
            f["pv_dt"] = f["pv_dtd"] = f["pv_cover"] = nanv
    return f


def history_queries(dates, tz):
    rows = []
    for d in dates:
        for h in HOURS:
            rows.append((d, h))
    q = pd.DataFrame(rows, columns=["local_date", "hour"])
    loc = pd.to_datetime(q.local_date) + pd.to_timedelta(q.hour, unit="h") + pd.Timedelta(minutes=30)
    q["t_utc"] = loc.dt.tz_localize(tz, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    return q.dropna(subset=["t_utc"]).reset_index(drop=True)


def stations(sel):
    return sorted(sel)  # market ICAOs


def build_history(root):
    obs, sel, prov = load(root)
    frames = []
    for code, icao in enumerate(stations(sel)):
        m = sel[icao]
        g, dmax = market_series(obs, icao, m["timezone"])
        dates = [d for d in dmax.index if d <= "2025-12-31" and int(d[5:7]) >= 8]
        q = history_queries(dates, m["timezone"])
        f = features(q, obs, m, icao, m["timezone"], code, g, dmax)
        f["station"], f["local_date"], f["hour"] = icao, q.local_date, q.hour
        f["dmax"] = q.local_date.map(dmax).to_numpy(float)
        f["year"] = q.local_date.str[:4].astype(int)
        f["month"] = q.local_date.str[5:7].astype(int)
        frames.append(f)
    out = pd.concat(frames, ignore_index=True)
    out = out[np.isfinite(out.r) & np.isfinite(out.t) & np.isfinite(out.dmax)].reset_index(drop=True)
    out["y"] = out.dmax - out.r
    return out, prov


# ----------------------------------------------------------------------------- model

def make_model(cols):
    from sklearn.ensemble import HistGradientBoostingRegressor

    cat = [list(cols).index("station_code")]
    return HistGradientBoostingRegressor(categorical_features=cat, **HGB_PARAMS)


def fit_predict(train, test, cols):
    model = make_model(cols)
    model.fit(train[list(cols)].to_numpy(float), train.y.to_numpy(float))
    return model.predict(test[list(cols)].to_numpy(float))


def cluster_ci(diff, clusters, draws=DRAWS, seed=SEED):
    """Mean of per-row ``diff`` with a cluster (date) bootstrap 95% interval."""
    frame = pd.DataFrame({"d": diff, "c": clusters})
    per = frame.groupby("c").d.agg(["sum", "size"])
    s, n = per["sum"].to_numpy(), per["size"].to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(s), size=(draws, len(s)))
    boot = s[idx].sum(1) / n[idx].sum(1)
    return float(s.sum() / n.sum()), float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))


def loyo(hist, months):
    h = hist[hist.month.isin(months)].reset_index(drop=True)
    pred_own, pred_up = np.full(len(h), np.nan), np.full(len(h), np.nan)
    for year in sorted(h.year.unique()):
        te = (h.year == year).to_numpy()
        pred_own[te] = fit_predict(h[~te], h[te], OWN)
        pred_up[te] = fit_predict(h[~te], h[te], OWN + UP)
    e_own, e_up = (pred_own - h.y) ** 2, (pred_up - h.y) ** 2
    rows = []
    for label, mask in [("07-12", np.ones(len(h), bool))] + [(f"h{x:02d}", (h.hour == x).to_numpy()) for x in HOURS]:
        d = (e_up - e_own)[mask]
        clusters = h.local_date[mask]
        point, lo, hi = cluster_ci(d.to_numpy(), clusters.to_numpy())
        rows.append({"rows": label, "n": int(mask.sum()), "n_dates": int(clusters.nunique()),
                     "rmse_own": float(np.sqrt(e_own[mask].mean())), "rmse_up": float(np.sqrt(e_up[mask].mean())),
                     "mse_up_minus_own": point, "ci95": [lo, hi]})
    per_station = []
    for st, g in h.groupby("station"):
        m = (h.station == st).to_numpy()
        point, lo, hi = cluster_ci((e_up - e_own)[m].to_numpy(), h.local_date[m].to_numpy())
        per_station.append({"station": st, "rmse_own": float(np.sqrt(e_own[m].mean())),
                            "rmse_up": float(np.sqrt(e_up[m].mean())), "mse_up_minus_own": point, "ci95": [lo, hi]})
    per_year = [{"year": int(y), "rmse_own": float(np.sqrt(e_own[(h.year == y).to_numpy()].mean())),
                 "rmse_up": float(np.sqrt(e_up[(h.year == y).to_numpy()].mean()))} for y in sorted(h.year.unique())]
    return {"months": list(months), "rows": rows, "per_station": per_station, "per_year": per_year}


# ----------------------------------------------------------------------------- serve (dev snapshots)

def serve(root, layout, out):
    hist, prov = build_history(root)
    train = hist[hist.month.isin(TRAIN_MONTHS_PRIMARY)].reset_index(drop=True)
    obs, sel, _ = load(root)
    snaps = pd.read_parquet(Path(layout) / "inputs_snapshots.parquet",
                            columns=["row_key", "station", "date", "captured_at_utc", "local_hour"])
    if (snaps.date.astype(str) > DEV_LAST).any():
        raise AssertionError("layout snapshot after 2026-09-29")
    snaps = snaps[snaps.local_hour.isin(HOURS)].reset_index(drop=True)
    frames = []
    for code, icao in enumerate(stations(sel)):
        m = sel[icao]
        s = snaps[snaps.station == icao]
        if s.empty:
            continue
        g, dmax = market_series(obs, icao, m["timezone"])
        q = pd.DataFrame({"t_utc": pd.to_datetime(s.captured_at_utc, utc=True).to_numpy(),
                          "local_date": s.date.astype(str).to_numpy()}, index=s.index)
        q["t_utc"] = pd.to_datetime(q.t_utc, utc=True)
        f = features(q, obs, m, icao, m["timezone"], code, g, dmax)
        f["row_key"] = s.row_key
        frames.append(f)
    feat = pd.concat(frames)
    ok = np.isfinite(feat.r) & np.isfinite(feat.t)
    feat = feat[ok]
    own = make_model(OWN).fit(train[list(OWN)].to_numpy(float), train.y.to_numpy(float))
    up = make_model(OWN + UP).fit(train[list(OWN + UP)].to_numpy(float), train.y.to_numpy(float))
    res = pd.DataFrame({"row_key": feat.row_key.to_numpy(),
                        "n_own": feat.r.to_numpy(float) + own.predict(feat[list(OWN)].to_numpy(float)),
                        "n_up": feat.r.to_numpy(float) + up.predict(feat[list(OWN + UP)].to_numpy(float)),
                        "n_ring": feat.n_ring.to_numpy(float)})
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "nowcasts.parquet"
    res.to_parquet(path, index=False)
    feat.to_parquet(out / "serve_features.parquet", index=False)
    manifest = dict(prov, nowcasts_sha256=sha_file(path), rows=int(len(res)), train_rows=int(len(train)),
                    snapshots_07_12=int(len(snaps)), layout_snapshots_sha256=sha_file(Path(layout) / "inputs_snapshots.parquet"),
                    hgb=HGB_PARAMS, own=list(OWN), up=list(UP))
    (out / "nowcasts_manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.upstream_obs_screen")
    parser.add_argument("command", choices=("features", "loyo", "serve"))
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--out", required=True)
    parser.add_argument("--layout", default=r"C:\swarm\v3layout")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.command == "features":
        hist, prov = build_history(args.root)
        hist.to_parquet(out / "history_features.parquet", index=False)
        summary = dict(prov, rows=int(len(hist)), coverage={k: float(np.isfinite(hist[k]).mean()) for k in OWN + UP})
        (out / "history_features.json").write_text(json.dumps(summary, indent=1, sort_keys=True), encoding="utf-8")
        print(json.dumps({k: v for k, v in summary.items() if k != "coverage"}, indent=1))
    elif args.command == "loyo":
        hist, prov = build_history(args.root)
        result = dict(prov, hgb=HGB_PARAMS, primary=loyo(hist, TRAIN_MONTHS_PRIMARY),
                      secondary=loyo(hist, TRAIN_MONTHS_SECONDARY))
        (out / "loyo.json").write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
        print(json.dumps(result["primary"]["rows"], indent=1))
    else:
        print(json.dumps(serve(args.root, args.layout, out), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
