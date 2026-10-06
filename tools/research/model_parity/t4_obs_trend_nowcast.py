"""T4 obs-trend nowcast (model-parity swarm v2, development only).

Remaining-rise nowcast: P(final METAR max - PIT running max | station, local hour, deficit, METAR slope
over ~1 h and ~3 h, sky cover, wind), fitted ONLY on METAR history with local dates <= 2026-07-31
(rule 3), months within +-1 of the target month. Hierarchical shrinkage (K = 20 pseudo-rows toward
the parent cell). The same feature function builds the history grid and the evaluation snapshots
(train/serve parity).

Point in time (rule 1): an observation enters snapshot t only if its available_utc (= METAR/SPECI
valid + 10 min, A-IEM) <= captured_at_utc; COR reports excluded; running max over the target local
date only. No market input (rule 2), no winner/settlement input (rule 3); history labels are METAR
day maxima for days <= 2026-07-31. The harness applies the rule-4 floor.

Rules (registered in C:\\swarm\\registry.jsonl before scoring):
  t4-r1  full nowcast (levels station-hour > deficit > slope1h > sky > slope3h > wind), all hours
         with a same-day PIT obs; served fallback otherwise.
  t4-r2  ablation: T2-style (station-hour > deficit only), same coverage.
  t4-r3  mixture w*r1 + (1-w)*served, single global w from {0.1,...,0.9} chosen on the BEFORE
         stratum all-row pooled candidate Brier (via harness score), then scored on everything.

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.t4_obs_trend_nowcast
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h

METAR = Path(r"C:\swarm\data\iem\metar")
STATIONS = Path(r"C:\swarm\stations.json")
OUT = Path(r"C:\swarm\out\t4")
STOP = Path(r"C:\swarm\STOP")
HIST_END = "2026-07-31"
RMAX = 30
K = 20.0
GRID_MIN = 15
EXTRA_LAG_MIN = 0          # sensitivity: extra minutes of METAR availability lag (train and serve alike)
SKY_ORD = {"CLR": 0, "SKC": 0, "NSC": 0, "NCD": 0, "FEW": 1, "SCT": 2, "BKN": 3, "OVC": 4, "VV": 4,
           "VV ": 4}


def _naive(series):
    return pd.Series(series).dt.tz_convert("UTC").dt.tz_localize(None).dt.as_unit("us").to_numpy()


def load_metar(station):
    m = pd.read_parquet(METAR / f"{station}.parquet",
                        columns=["tmpf", "report_type", "valid_utc", "available_utc", "local_date", "is_cor",
                                 "sknt", "skyc1", "skyc2", "skyc3", "skyc4"])
    m["local_date"] = m.local_date.astype(str)
    return m


def day_labels(m):
    """History truth: METAR day max (all reports with tmpf) per local date; complete days only."""
    g = m[m.tmpf.notna()].groupby("local_date")
    lab = pd.DataFrame({"fmax": g.tmpf.max(),
                        "n_routine": m[m.report_type == "routine"].groupby("local_date").size()})
    lab = lab[lab.n_routine.fillna(0) >= 20]
    return lab.fmax


def obs_features(m, t_utc, dates):
    """PIT features per query (t_utc tz-aware strings/Timestamps, dates = target local date str).

    Inputs: non-COR rows with available_utc <= t. Returns DataFrame with runmax, cur, deficit,
    s1, s3, sky, wind, cur_age_min, ok (same-day obs exists) and used_available (for PIT assert).
    """
    x = m[~m.is_cor & m.tmpf.notna()].sort_values("available_utc").reset_index(drop=True)
    x["runmax"] = x.groupby("local_date").tmpf.cummax()
    avail = _naive(x.available_utc)
    valid = _naive(x.valid_utc)
    temp = x.tmpf.to_numpy()
    t = _naive(pd.to_datetime(pd.Series(t_utc), utc=True, format="ISO8601"))
    t = t - np.timedelta64(EXTRA_LAG_MIN, "m")
    i = np.searchsorted(avail, t, side="right") - 1
    ok = i >= 0
    ii = np.maximum(i, 0)
    ok &= x.local_date.to_numpy()[ii] == np.asarray(dates)
    cur = temp[ii]
    cv = valid[ii]

    def back(minutes, max_age):
        j = np.searchsorted(valid, cv - np.timedelta64(minutes, "m"), side="right") - 1
        jj = np.maximum(j, 0)
        age = (cv - valid[jj]) / np.timedelta64(1, "m")
        return np.where((j >= 0) & (age <= max_age), cur - temp[jj], np.nan)

    s1 = back(50, 90)
    s3 = back(170, 210)
    sky = np.full(len(x), -1)
    for c in ("skyc1", "skyc2", "skyc3", "skyc4"):
        v = x[c].map(lambda s: SKY_ORD.get(str(s).strip(), -1) if isinstance(s, str) else -1).to_numpy()
        sky = np.maximum(sky, v)
    wind = x.sknt.to_numpy()
    out = pd.DataFrame({
        "ok": ok,
        "runmax": np.where(ok, x.runmax.to_numpy()[ii], np.nan),
        "cur": np.where(ok, cur, np.nan),
        "s1": np.where(ok, s1, np.nan), "s3": np.where(ok, s3, np.nan),
        "sky": np.where(ok, sky[ii], -1), "wind": np.where(ok, wind[ii], np.nan),
        "cur_age_min": (t - cv) / np.timedelta64(1, "m"),
        "used_available": x.available_utc.to_numpy()[ii],
    })
    out["deficit"] = out.runmax - out.cur
    return out


def buckets(f, hour):
    d = f.deficit.to_numpy()
    s1 = f.s1.to_numpy()
    s3 = f.s3.to_numpy()
    w = f.wind.to_numpy()
    sk = f.sky.to_numpy()
    b = pd.DataFrame({"hour": np.asarray(hour, int)})
    b["dbin"] = np.select([d <= 0, d <= 1, d <= 2, d <= 4], [0, 1, 2, 3], 4)
    b["s1bin"] = np.select([np.isnan(s1), s1 <= -2, s1 <= -1, s1 < 1, s1 < 2], [5, 0, 1, 2, 3], 4)
    b["s3bin"] = np.select([np.isnan(s3), s3 <= -4, s3 <= -1, s3 <= 2, s3 <= 5], [5, 0, 1, 2, 3], 4)
    b["skybin"] = np.select([sk < 0, sk <= 1, sk == 2], [3, 0, 1], 2)
    b["wbin"] = np.select([np.isnan(w), w < 6, w <= 12], [3, 0, 1], 2)
    return b


LEVELS_FULL = [["hour"], ["dbin"], ["s1bin"], ["skybin"], ["s3bin"], ["wbin"]]
LEVELS_T2 = [["hour"], ["dbin"]]


def history_grid(station, m, tz, months):
    lab = day_labels(m)
    days = [d for d in lab.index if d <= HIST_END and int(d[5:7]) in months]
    zi = ZoneInfo(tz)
    ts, ds, hrs = [], [], []
    for d in days:
        y, mo, dd = map(int, d.split("-"))
        base = datetime(y, mo, dd, tzinfo=zi)
        for k in range(0, 24 * 60, GRID_MIN):
            loc = (base + timedelta(minutes=k))
            loc = datetime(y, mo, dd, loc.hour, loc.minute, tzinfo=zi) if loc.date() == base.date() else None
            if loc is None:
                continue
            ts.append(loc.astimezone(ZoneInfo("UTC")).isoformat())
            ds.append(d)
            hrs.append(loc.hour)
    f = obs_features(m, ts, ds)
    b = buckets(f, hrs)
    r = lab.reindex(ds).to_numpy() - f.runmax.to_numpy()
    keep = f.ok.to_numpy() & np.isfinite(r)
    b = b[keep].reset_index(drop=True)
    r = np.clip(np.round(r[keep]), 0, RMAX).astype(int)
    assert max(ds) <= HIST_END
    return b, r, len(days)


CARD = {"hour": 24, "dbin": 5, "s1bin": 6, "skybin": 4, "s3bin": 6, "wbin": 4}


def _key(b, cols):
    key = np.zeros(len(b), np.int64)
    mult = 1
    for c in cols:
        key += b[c].to_numpy(np.int64) * mult
        mult *= CARD[c]
    return key


class Shrunk:
    """Hierarchical shrinkage histogram over remaining rise 0..RMAX."""

    def __init__(self, b, r, levels):
        self.levels = levels
        self.tables = []
        cols = []
        for lv in levels:
            cols = cols + lv
            key = _key(b, cols)
            codes, uniq = pd.factorize(key)
            cnt = np.zeros((len(uniq), RMAX + 1))
            np.add.at(cnt, (codes, r), 1)
            self.tables.append((list(cols), dict(zip(uniq, range(len(uniq)))), cnt))

    def predict(self, b):
        n = len(b)
        p = None
        for cols, index, cnt in self.tables:
            key = pd.Series(_key(b, cols))
            pos = key.map(index).to_numpy()
            has = ~pd.isna(pos)
            c = np.zeros((n, RMAX + 1))
            c[has] = cnt[pos[has].astype(int)]
            tot = c.sum(1, keepdims=True)
            if p is None:
                p = np.where(tot > 0, c / np.maximum(tot, 1), np.nan)
            else:
                p = np.where(tot > 0, (c + K * p) / (tot + K), p)
        return p


def band_probs(bands, snap_pos, M, P):
    """P over final max F = M + r -> band probabilities (eq [low,high], lte <= high, gte >= low)."""
    cdf = np.cumsum(P, axis=1)

    def cdf_at(row, x):          # P(F <= x)
        k = (x - M[row]).astype(int)
        v = cdf[row, np.clip(k, 0, RMAX)]
        return np.where(k < 0, 0.0, np.where(k >= RMAX, 1.0, v))

    kind = bands.kind.to_numpy()
    lo = bands.low.to_numpy(float)
    hi = bands.high.to_numpy(float)
    row = snap_pos
    p_hi = cdf_at(row, hi)
    p_lo = cdf_at(row, lo - 1)
    return np.clip(np.where(kind == "lte", p_hi, np.where(kind == "gte", 1.0 - p_lo, p_hi - p_lo)), 0.0, None)


def build(levels_by_name):
    st = json.loads(STATIONS.read_text(encoding="utf-8"))["stations"]
    snaps, bands = h.candidate_inputs()
    assert snaps.date.max() <= "2026-09-29"
    preds = {n: np.full((len(snaps), RMAX + 1), np.nan) for n in levels_by_name}
    feat_all = pd.DataFrame(index=snaps.index, columns=["runmax", "deficit", "s1", "s3", "sky", "wind", "ok"])
    fit_info = {}
    for station, g in snaps.groupby("station", sort=False):
        m = load_metar(station)
        f = obs_features(m, g.captured_at_utc.to_numpy(), g.date.to_numpy())
        okm = f.ok.to_numpy()
        h.assert_point_in_time(f.used_available.to_numpy()[okm], g.captured_at_utc.to_numpy()[okm])
        assert (f.cur_age_min.to_numpy()[okm] >= 10).all()     # valid + 10 min lag
        b = buckets(f, g.local_hour.to_numpy())
        for col in feat_all.columns:
            feat_all.loc[g.index, col] = f[col].to_numpy()
        month = g.date.str[5:7].astype(int).to_numpy()
        for mo in np.unique(month):
            hb, hr, ndays = history_grid(station, m, st[station]["tzname"], {mo - 1, mo, mo + 1})
            fit_info[f"{station}-{mo:02d}"] = {"history_days": ndays, "grid_rows": int(len(hr))}
            sel = (month == mo) & okm
            for name, levels in levels_by_name.items():
                model = Shrunk(hb, hr, levels)
                pr = model.predict(b[sel].reset_index(drop=True))
                idx = g.index.to_numpy()[sel]
                preds[name][idx] = pr
        print(station, "done", flush=True)
    return snaps, bands, feat_all, preds, fit_info


def candidates(snaps, bands, feat_all, preds):
    pos = pd.Series(np.arange(len(snaps)), index=snaps.row_key)
    snap_pos = pos.reindex(bands.row_key).to_numpy()
    M = feat_all.runmax.to_numpy(float)
    out = {}
    for name, P in preds.items():
        cov = np.isfinite(P).all(1) & np.isfinite(M)
        Pz = np.where(np.isfinite(P), P, 0.0)
        Mz = np.where(np.isfinite(M), M, 0.0)
        pb = band_probs(bands, snap_pos, Mz, Pz)
        keep = cov[snap_pos]
        out[name] = (bands.loc[keep, ["row_key", "band_index"]].assign(p=pb[keep]).reset_index(drop=True), cov)
    return out


def register(rules):
    import hashlib
    reg = Path(r"C:\swarm\registry.jsonl")
    have = reg.read_text(encoding="utf-8") if reg.exists() else ""
    for rid, text in rules.items():
        if f'"id": "{rid}"' in have:
            continue
        line = json.dumps({"id": rid, "agent": "t4", "text": text,
                           "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                           "time_local": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")})
        with reg.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


RULES_DIAG = {
    "t4-d1": ("T4 PIT sensitivity (diagnostic of t4-r1/t4-r3, not a new candidate): identical to t4-r1 and t4-r3 "
              "(w fixed at the t4-r3 before-stratum choice) but every METAR/SPECI is treated as available 30 min "
              "after valid (EXTRA_LAG_MIN=20 on top of +10), in both the history grid and the snapshots."),
}


def paired(c_a, c_b):
    """Diagnostic: per-block paired delta (a - b) all-row with harness W intervals (harness internals)."""
    d = h.data()
    out = {}
    se = []
    for c in (c_a, c_b):
        pc, use, _ = h._candidate_vector(c, d, False)
        se.append(h._snapshot_mean(d, (pc - d.y) ** 2))
    fr = d.snaps[["date", "market", "stratum", "local_hour"]].copy()
    fr["delta"] = se[0] - se[1]
    for g, lo, hi in h.GROUPS:
        for st in ("before_20260823", "from_20260823"):
            sel = fr.local_hour.between(lo, hi) & (fr.stratum == st)
            cells = fr[sel].groupby(["date", "market"]).delta.mean().reset_index()
            idx = np.array([d.key_index[(a, b)] for a, b in zip(cells.date, cells.market)])
            out[f"{g}|{st}"] = h.interval(idx, cells.delta.to_numpy())
    return out


def diagnostics():
    global EXTRA_LAG_MIN
    register(RULES_DIAG)
    res = {}
    snaps, bands, feat, preds, _ = build({"t4-r1": LEVELS_FULL, "t4-r2": LEVELS_T2})
    cands = candidates(snaps, bands, feat, preds)
    res["paired_r1_minus_r2"] = paired(cands["t4-r1"][0], cands["t4-r2"][0])
    w = json.loads((OUT / "t4_extra.json").read_text())["w_best"]
    ps = bands.set_index(["row_key", "band_index"]).p_served
    EXTRA_LAG_MIN = 20
    snaps, bands, feat, preds, _ = build({"t4-r1": LEVELS_FULL})
    c1 = candidates(snaps, bands, feat, preds)["t4-r1"][0]
    r = h.score(c1, name="t4_d1_r1_lag30")
    h.save(r, OUT)
    print(h.markdown(r), flush=True)
    sp = ps.reindex(pd.MultiIndex.from_frame(c1[["row_key", "band_index"]])).to_numpy()
    r = h.score(c1.assign(p=w * c1.p.to_numpy() + (1 - w) * sp), name="t4_d1_r3_lag30")
    h.save(r, OUT)
    print(h.markdown(r), flush=True)
    (OUT / "t4_paired.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")


RULES = {
    "t4-r1": ("T4 obs-trend nowcast full: at snapshot t, from IEM METAR/SPECI non-COR rows with available_utc="
              "valid+10min <= captured_at_utc on the target local date: running max M (tmpf), current T, "
              "deficit M-T bins {0,1,2,3-4,5+}, slope1h=T-temp(obs valid >=50 min before, age<=90) bins "
              "{<=-2,-1,0,+1,>=+2,na}, slope3h=T-temp(obs valid >=170 min before, age<=210) bins "
              "{<=-4,-3..-1,0..2,3..5,>=6,na}, sky=max cover of latest obs {CLR/FEW,SCT,BKN/OVC/VV,na}, "
              "wind sknt {<6,6-12,>12,na}, local hour. P(remaining rise r=0..30 F) from METAR history "
              "(local dates <= 2026-07-31, months target+-1, complete days >=20 routine rows; label = METAR day "
              "max) on a 15-min grid with the same feature code; hierarchical shrinkage K=20 along station-hour > "
              "deficit > slope1h > sky > slope3h > wind. Band p = P(M+r in band). Coverage: snapshots with a "
              "same-day PIT obs; else served fallback. Harness floor applied. All hours."),
    "t4-r2": ("T4 ablation (T2-style): identical to t4-r1 but shrinkage levels station-hour > deficit only "
              "(no slope, sky, wind)."),
    "t4-r3": ("T4 mixture: p = w*p_t4r1 + (1-w)*p_served on t4-r1 covered snapshots (served elsewhere), single "
              "global w chosen from {0.1,0.2,...,0.9} minimising harness all-row pooled candidate Brier on the "
              "before_20260823 stratum only (00-23 aggregate 'all'), then scored on all rows."),
}


def main():
    if STOP.exists():
        sys.exit("STOP present")
    OUT.mkdir(parents=True, exist_ok=True)
    register(RULES)
    snaps, bands, feat, preds, fit_info = build({"t4-r1": LEVELS_FULL, "t4-r2": LEVELS_T2})
    cands = candidates(snaps, bands, feat, preds)
    results = {}
    for name in ("t4-r1", "t4-r2"):
        if STOP.exists():
            sys.exit("STOP present")
        cand, cov = cands[name]
        res = h.score(cand, name=name.replace("-", "_"))
        h.save(res, OUT)
        results[name] = res
        print(h.markdown(res), flush=True)
        if res["leakage_suspect_groups"]:
            print("LEAKAGE SUSPECT", res["leakage_suspect_groups"])
    # r3: mixture, w tuned on the before stratum only
    cand1, cov1 = cands["t4-r1"]
    ps = bands.set_index(["row_key", "band_index"]).p_served
    served_p = ps.reindex(pd.MultiIndex.from_frame(cand1[["row_key", "band_index"]])).to_numpy()
    tune = {}
    for w in [round(0.1 * k, 1) for k in range(1, 10)]:
        c = cand1.assign(p=w * cand1.p.to_numpy() + (1 - w) * served_p)
        r = h.score(c, name=f"t4_r3_tune_w{w}", where=lambda s: s.stratum == "before_20260823")
        tune[w] = h.table_lookup(r, "all", "before_20260823", "all_row")["candidate"]["estimate"]
    w_best = min(tune, key=tune.get)
    print("tune", tune, "best", w_best, flush=True)
    c = cand1.assign(p=w_best * cand1.p.to_numpy() + (1 - w_best) * served_p)
    res = h.score(c, name="t4_r3")
    res["w_best"] = w_best
    res["tune_before_brier"] = tune
    h.save(res, OUT)
    results["t4-r3"] = res
    print(h.markdown(res), flush=True)
    cov = cands["t4-r1"][1]
    extra = {"fit_info": fit_info,
             "coverage_by_block": pd.Series(cov).groupby(snaps.block.to_numpy()).mean().to_dict(),
             "w_best": w_best, "tune_before_brier": tune}
    (OUT / "t4_extra.json").write_text(json.dumps(extra, indent=1, default=float), encoding="utf-8")


if __name__ == "__main__":
    if "--diag" in sys.argv:
        diagnostics()
    else:
        main()
