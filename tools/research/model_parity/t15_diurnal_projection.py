"""T15 diurnal-curve projection (model-parity swarm v2, development only).

Rule family (registered in C:\\swarm\\registry.jsonl as t15-r1, t15-r2, t15-r3 before any score):

  Station-month diurnal shape from IEM METAR history (local dates <= 2026-07-31 only):
    for every history obs i on a local day (routine + SPECI, COR excluded, tmpf):
      ratio_i = (max of obs at or after i on that day - T_i) / (day max - min of obs up to i),
      kept when the denominator >= 2 F; r(station, target month, local half-hour bin) = median ratio
      over months {m-1, m, m+1}, smoothed over +/- 1 bin, clipped to [0, 1.5].
  At snapshot t (PIT METAR: available = valid + 10 min <= captured_at_utc, COR excluded, same
  local date): T_now = latest obs, Tmin = min obs so far today, M = max obs so far today,
  G = captured guidance high (forecast_high for r1/r2, nws_grid_high for r3),
  A = max(G - Tmin, 0), P = max(M, T_now + r(bin of T_now's local valid time) * A).
  r1: served (floor-masked) integer pmf shifted so its mean equals P (shape kept).
  r2: discretised Normal(P, sigma_block); sigma_block = RMS(settlement_high - P) on the BEFORE
      stratum only (rule 3/7), per local-hour block.
  r3: r1 with G = nws_grid_high.
  Uncovered rows (no same-day obs, no G) fall back to served. Floor applied by the harness.

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.t15_diurnal_projection
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

METAR = Path(r"C:\swarm\data\iem\metar")
OUT = Path(r"C:\swarm\out\t15")
HIST_END = "2026-07-31"
NBIN = 48
RULES = {
    "t15-r1": ("forecast_high", "shift"),
    "t15-r2": ("forecast_high", "normal"),
    "t15-r3": ("nws_grid_high", "shift"),
    "t15-r4": ("forecast_high", "normal_ctrl"),
}


def _naive(series):
    return pd.Series(series).dt.tz_convert("UTC").dt.tz_localize(None).dt.as_unit("us").to_numpy()


def load_metar(station):
    m = pd.read_parquet(METAR / f"{station}.parquet",
                        columns=["tmpf", "valid_utc", "available_utc", "local_time", "local_date", "is_cor"])
    m = m[~m.is_cor & m.tmpf.notna()].copy()
    m["local_date"] = m.local_date.astype(str)
    lt = m.local_time.astype(str)
    m["bin"] = lt.str[11:13].astype(int) * 2 + (lt.str[14:16].astype(int) >= 30).astype(int)
    return m.sort_values("valid_utc").reset_index(drop=True)


def diurnal_shape(m):
    """r[month, bin] from history <= HIST_END."""
    hist = m[m.local_date <= HIST_END].copy()
    assert hist.local_date.max() <= HIST_END
    g = hist.groupby("local_date", sort=False)
    n = g.tmpf.transform("size")
    hist = hist[n >= 18].copy()
    g = hist.groupby("local_date", sort=False)
    hist["cmin"] = g.tmpf.cummin()
    hist["dmax"] = g.tmpf.transform("max")
    rev = hist.iloc[::-1]
    hist["fut"] = rev.groupby("local_date", sort=False).tmpf.cummax().iloc[::-1]
    den = hist.dmax - hist.cmin
    hist = hist[den >= 2].copy()
    hist["ratio"] = (hist.fut - hist.tmpf) / (hist.dmax - hist.cmin)
    hist["month"] = hist.local_date.str[5:7].astype(int)
    r = {}
    for mo in (8, 9):
        sub = hist[hist.month.isin([mo - 1, mo, mo + 1])]
        med = sub.groupby("bin").ratio.median().reindex(range(NBIN))
        med = med.interpolate(limit_direction="both")
        arr = med.to_numpy()
        sm = (np.roll(arr, 1) + arr + np.roll(arr, -1)) / 3.0
        r[mo] = np.clip(sm, 0.0, 1.5)
    return r


def obs_features(snaps):
    parts = []
    shapes = {}
    for station, g in snaps.groupby("station", sort=False):
        m = load_metar(station)
        shapes[station] = diurnal_shape(m)
        m = m.sort_values("available_utc").reset_index(drop=True)
        gd = m.groupby("local_date", sort=False)
        m["cmin"] = gd.tmpf.cummin()   # cumulative over availability order == obs order (lag constant)
        m["cmax"] = gd.tmpf.cummax()
        avail = _naive(m.available_utc)
        t = _naive(pd.to_datetime(g.captured_at_utc, utc=True, format="ISO8601"))
        i = np.searchsorted(avail, t, side="right") - 1
        ok = i >= 0
        ii = np.where(ok, i, 0)
        same = ok & (m.local_date.to_numpy()[ii] == g.date.to_numpy())
        h.assert_point_in_time(m.available_utc.to_numpy()[ii][same], g.captured_at_utc.to_numpy()[same])
        mo = g.date.str[5:7].astype(int).to_numpy()
        b = m["bin"].to_numpy()[ii]
        rr = np.array([shapes[station][x][y] if x in (8, 9) else np.nan for x, y in zip(mo, b)])
        parts.append(pd.DataFrame({
            "row_key": g.row_key.to_numpy(),
            "t_now": np.where(same, m.tmpf.to_numpy()[ii], np.nan),
            "tmin": np.where(same, m.cmin.to_numpy()[ii], np.nan),
            "mmax": np.where(same, m.cmax.to_numpy()[ii], np.nan),
            "r": np.where(same, rr, np.nan),
        }))
    return pd.concat(parts, ignore_index=True), shapes


def projection(snaps, feats, gcol, ctrl=False):
    f = snaps[["row_key", "block", "stratum", gcol]].merge(feats, on="row_key", how="left")
    G = f[gcol].to_numpy(float)
    A = np.maximum(G - f.tmin.to_numpy(), 0.0)
    P = np.maximum(f.mmax.to_numpy(), f.t_now.to_numpy() + f.r.to_numpy() * A)
    if ctrl:  # r4 control: no diurnal shape, P = max(M, G), same coverage as r2
        P = np.where(np.isnan(P), np.nan, np.maximum(f.mmax.to_numpy(), G))
    f["P"] = P
    return f


def candidates(bands, P_by_key, mode, sigma_by_key=None):
    """Return candidate frame for covered rows."""
    b = bands[bands.row_key.isin(P_by_key.index)].copy()
    b = b.sort_values(["row_key", "band_index"]).reset_index(drop=True)
    out_p = np.empty(len(b))
    keys = b.row_key.to_numpy()
    starts = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])
    ends = np.r_[starts[1:], len(b)]
    lo_all = b.low.to_numpy(float); hi_all = b.high.to_numpy(float); kind_all = b.kind.to_numpy()
    ps_all = b.p_served.to_numpy(float) * (~b.floor_impossible.to_numpy(bool))
    Pk = P_by_key.reindex(keys[starts]).to_numpy()
    Sk = sigma_by_key.reindex(keys[starts]).to_numpy() if sigma_by_key is not None else None
    keep = np.ones(len(b), bool)
    for j, (s, e) in enumerate(zip(starts, ends)):
        lo, hi, kind, ps = lo_all[s:e], hi_all[s:e], kind_all[s:e], ps_all[s:e]
        gmin = int(lo.min()) - 30
        gmax = int(hi.max()) + 30
        grid = np.arange(gmin, gmax + 1)
        if mode == "shift":
            if ps.sum() <= 0:
                keep[s:e] = False; continue
            ps = ps / ps.sum()
            pmf = np.zeros(len(grid))
            for k in range(e - s):
                if kind[k] == "lte":
                    pts = np.arange(int(lo[k]) - 2, int(lo[k]) + 1)
                elif kind[k] == "gte":
                    pts = np.arange(int(lo[k]), int(lo[k]) + 3)
                else:
                    pts = np.arange(int(lo[k]), int(hi[k]) + 1)
                pmf[pts - gmin] += ps[k] / len(pts)
            mu = float((pmf * grid).sum())
            d = Pk[j] - mu
            fl = math.floor(d); w = d - fl
            new = (1 - w) * np.roll(pmf, fl) + w * np.roll(pmf, fl + 1)
        else:
            sg = max(Sk[j], 0.5)
            from math import erf
            cdf = 0.5 * (1 + np.vectorize(erf)((grid + 0.5 - Pk[j]) / (sg * math.sqrt(2))))
            new = np.diff(np.r_[0.0, cdf])
            new[-1] += 1 - cdf[-1]
        q = np.empty(e - s)
        for k in range(e - s):
            if kind[k] == "lte":
                q[k] = new[grid <= lo[k]].sum()
            elif kind[k] == "gte":
                q[k] = new[grid >= lo[k]].sum()
            else:
                q[k] = new[(grid >= lo[k]) & (grid <= hi[k])].sum()
        out_p[s:e] = q
    b["p"] = out_p
    return b.loc[keep, ["row_key", "band_index", "p"]]


def rule_texts():
    base = __doc__.split("Run:")[0]
    return {
        "t15-r1": "T15 r1 diurnal-curve projection, shift: " + base +
                  " Variant r1 = G forecast_high, served floor-masked integer pmf shifted so mean = P.",
        "t15-r2": "T15 r2 diurnal-curve projection, normal: " + base +
                  " Variant r2 = G forecast_high, discretised Normal(P, sigma_block), sigma fitted on before stratum.",
        "t15-r3": "T15 r3 diurnal-curve projection, shift with NWS grid: " + base +
                  " Variant r3 = G nws_grid_high, served pmf shifted so mean = P.",
        "t15-r4": "T15 r4 CONTROL (decomposition diagnostic for r2, no diurnal shape): " + base +
                  " Variant r4 = same coverage and sigma procedure as r2 but P = max(M, forecast_high);"
                  " discretised Normal(P, sigma_block fitted on before stratum).",
    }


def register():
    reg = Path(r"C:\swarm\registry.jsonl")
    existing = reg.read_text(encoding="utf-8") if reg.exists() else ""
    for rid, text in rule_texts().items():
        if f'"id": "{rid}"' in existing:
            continue
        line = json.dumps({"id": rid, "agent": "t15", "text": text,
                           "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                           "time_local": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        with open(reg, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def before_labels():
    """settlement_high for BEFORE-stratum snapshots only (sigma fit for r2; rule 3/7)."""
    s = pd.read_parquet(r"C:\swarm\cache\snapshots.parquet")
    s = s[s.stratum == "before_20260823"]
    col = "settlement_high"
    key = s["market"].astype(str) + "|" + s["snapshot_id"].astype(str)
    return pd.Series(s[col].to_numpy(float), index=key.to_numpy())


def main():
    if Path(r"C:\swarm\STOP").exists():
        print("STOP present"); return
    OUT.mkdir(parents=True, exist_ok=True)
    snaps, bands = h.candidate_inputs()
    assert (snaps.date > "2026-09-29").sum() == 0
    feats, shapes = obs_features(snaps)
    register()
    summary = {"HARNESS_SHA256": h.harness_sha256(), "rules": {}, "shape_r": {
        st: {str(mo): [round(float(x), 3) for x in v] for mo, v in d.items()} for st, d in shapes.items()}}
    lab = before_labels()
    for rid, (gcol, mode) in RULES.items():
        if Path(r"C:\swarm\STOP").exists():
            print("STOP present"); return
        f = projection(snaps, feats, gcol, ctrl=(mode == "normal_ctrl"))
        mode_c = "normal" if mode == "normal_ctrl" else mode
        cov = f.P.notna()
        sig = None
        diag = {}
        if mode_c == "normal":
            fb = f[cov & (f.stratum == "before_20260823")].copy()
            fb["y"] = lab.reindex(fb.row_key.to_numpy()).to_numpy()
            fb = fb[fb.y.notna()]
            sig_block = fb.groupby("block").apply(lambda x: float(np.sqrt(np.mean((x.y - x.P) ** 2))))
            diag["sigma_block_before"] = sig_block.round(3).to_dict()
            sig = pd.Series(f.block.map(sig_block).to_numpy(), index=f.row_key.to_numpy())[cov.to_numpy()]
        if True:  # before-stratum projection diagnostic (labels before only)
            fb = f[cov & (f.stratum == "before_20260823")].copy()
            fb["y"] = lab.reindex(fb.row_key.to_numpy()).to_numpy()
            fb["G"] = fb[gcol]
            diag["before_mae_P_by_block"] = fb.groupby("block").apply(
                lambda x: float(np.nanmean(np.abs(x.y - x.P)))).round(3).to_dict()
            diag["before_mae_G_by_block"] = fb.groupby("block").apply(
                lambda x: float(np.nanmean(np.abs(x.y - x.G)))).round(3).to_dict()
            diag["before_bias_P_by_block"] = fb.groupby("block").apply(
                lambda x: float(np.nanmean(x.y - x.P))).round(3).to_dict()
        P_by_key = pd.Series(f.P.to_numpy(), index=f.row_key.to_numpy())[cov.to_numpy()]
        cand = candidates(bands, P_by_key, mode_c, sig)
        name = rid.replace("-", "_") + ("_diurnal_" + mode + "_" + gcol)
        res = h.score(cand, name=name)
        h.save(res, OUT)
        md = h.markdown(res)
        (OUT / f"{name}.md").write_text(md, encoding="utf-8")
        print(md)
        summary["rules"][rid] = {"name": name, "coverage_rows": int(cov.sum()), "total_rows": int(len(f)),
                                 "classes": {k: v.get("class") for k, v in res["classes"].items()},
                                 "leakage_suspect_groups": res.get("leakage_suspect_groups"),
                                 "diag": diag}
    (OUT / "t15_summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v["classes"] for k, v in summary["rules"].items()}, indent=1))


if __name__ == "__main__":
    main()
