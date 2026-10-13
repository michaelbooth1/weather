"""D-RUNG1C: rung "ladder-r1c" = ladder-r2 + faithful restoration of the 13-19h lock-in stages S3-S5.

Development only. Rules registered in C:\\swarm\\registry.jsonl BEFORE the first score (mode ``register``).

S3 high_has_stood_lockin_context      src/weather/model/model_distribution_signals.py:476
S4 expanded_late_day_lockin_context   :581
S5 standing_high_partial_lockin_context :709 + apply_standing_high_partial_lockin :904
Wiring model_distribution.py:1245-1283: hard strength = max(S1..S4); S5 only when that max is 0.
Constants: model_distribution_constants.py:127-168 (Celsius deltas x 9/5 for the F markets).

Re-anchoring (as rung 1): lockin_high = max(history_max (None), guidance_floor) = harness floor F, bucket
B = round_half_up(F); high-first-reached from PIT METAR (valid + 10 min <= t, COR excluded; T1's loader).

Remaining hourly forecasts: production passes weather_forecast (paid, disabled), open_meteo, nws_hourly,
global_ensemble, eccc_city (US: empty). Their hourly rows are not in the 111h extract, so a declared proxy is
used: P1 = {Single-Runs HRRR (+3 h), NBH TMP (S3 LastModified), Single-Runs ECMWF IFS (+8 h)};
P2 = {Single-Runs HRRR (+3 h), Single-Runs NBM (+6 h)}; diagnostic = forecast conditions treated as met.

Run from C:\\pt\\swarm with the repo interpreter:
    python -m tools.research.model_parity.d_rung1c register
    python -m tools.research.model_parity.d_rung1c score
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
from tools.research.model_parity import d_defect_evening_stage as dd
from tools.research.model_parity import ladder_parity as lp
from tools.research.model_parity import t1_decided_band as t1

OUT = Path(r"C:\swarm\out\d-rung1c")
OUT.mkdir(parents=True, exist_ok=True)
REG = Path(r"C:\swarm\registry.jsonl")
SR = Path(r"C:\swarm\data\singleruns\singleruns_long.parquet")
NBH = Path(r"C:\swarm\data\nbh\nbh_tidy.parquet")
T3R3 = Path(r"C:\swarm\out\ladder\cap\t3_baselines\t3_r3_floor_plus_rise.parquet")
FROM, BEFORE = "from_20260823", "before_20260823"
BLOCKS = {"00-05": (0, 5), "06-09": (6, 9), "10-12": (10, 12), "13-14": (13, 14), "15-16": (15, 16),
          "13-16": (13, 16), "17-23": (17, 23), "00-16": (0, 16), "all": (0, 23)}
lp.G.update(BLOCKS)

# ---- production constants (model_distribution_constants.py), F markets: Celsius deltas x 1.8
C2F = 9.0 / 5.0
PEAK_DROP = 2.0 * C2F
S3_START, S3_END, S3_MIN, S3_NSRC = 13, 15, 60, 2
S3_FMARGIN, S3_ROLL = 0.25 * C2F, 0.25 * C2F
S4_START, S4_END, S4_STAND, S4_FMARGIN, S4_ROLL, S4_MAX = 15, 19, 60, 0.50 * C2F, 0.25 * C2F, 0.85
S5_START, S5_END, S5_MIN, S5_ROLL = 13, 19, 60, 0.25 * C2F
S5_UPMAX, S5_AGREE, S5_MAX = 1.25 * C2F, 3.0 * C2F, 0.55
S5_ONE, S5_TWO, S5_BASE = 0.55, 0.30, 0.18
ROWS_CAP = 12  # production rows[:12]

RULES = {
    "ladder-r1c": (
        "D-RUNG1C rung ladder-r1c (development): ladder-r2 exactly (MG-1 r-t5-inc-c1 base where covered, else served; "
        "S1 heuristic + S2 learned lock-in strength exactly as d-defect-r2/ladder-r1) PLUS a faithful restoration of the "
        "production 13-19h stages S3 high_has_stood_lockin_context (model_distribution_signals.py:476), S4 "
        "expanded_late_day_lockin_context (:581) and S5 standing_high_partial_lockin_context (:709) with "
        "apply_standing_high_partial_lockin (:904), production constants (model_distribution_constants.py:144-168, "
        "Celsius deltas x 9/5 for F markets) and production wiring (model_distribution.py:1245-1283): hard strength "
        "s = max(S1,S2,S3,S4) applied with apply_late_day_lockin retention (1-s)+s*0.05*0.15^(k-B-1) above bucket B; "
        "S5 applied only where that max is 0, retention (1-s5)+s5*{0.55 at k=B+1, 0.30 at B+2, 0.30*0.18^(k-B-2)}. "
        "Re-anchoring as rung 1: lockin_high = max(history_max (None since 2026-06-30), guidance_floor) = harness 81a "
        "floor F, B = round_half_up(F). High-first-reached (max_times[0]) = local valid time of the first PIT non-COR "
        "METAR/SPECI row of the target local day (available = valid+10 min <= t; T1 loader) with round_half_up(tmpf) "
        ">= B, else of the first row reaching the PIT METAR running max; stood = snapshot local minute-of-day minus "
        "that minute. Third-party current and official readings both = latest PIT METAR tmpf (production's US "
        "station_observations source is metar); official_current_stale = False. Remaining hourly forecasts: "
        "production passes weather_forecast (paid, disabled -> {}), open_meteo (Open-Meteo best_match hourly "
        "temperature_2m), nws_hourly (api.weather.gov forecastHourly), global_ensemble (Open-Meteo GFS ensemble mean) "
        "and eccc_city ({} for US). Their hourly rows are NOT in the 111h extract and production data may not be "
        "pulled, so PROXY P1 is declared before scoring: three free PIT sources standing in for the three live ones: "
        "Open-Meteo Single-Runs ncep_hrrr_conus (for open_meteo; latest run with run+3 h <= t having non-null values "
        "for the remaining hours, up to 3 runs back), NBH TMP hourly (for nws_hourly; latest cycle with S3 "
        "LastModified <= t) and Single-Runs ecmwf_ifs (for global_ensemble; run+8 h conservative <= t). Per source: "
        "values valid at local time >= the snapshot local time on the target local date, first 12; source max; count, "
        "ceiling, spread exactly as remaining_forecast_context. The lock-in is applied to the c1/served FINAL bands "
        "uniform within band as in rungs 1/2 (no S7 taper re-emulation), renormalised; harness floor; served fallback "
        "where F is missing. These are production's own afternoon stages and hours; no hour gate is chosen or added; "
        "nothing is tuned. The result depends on the forecast proxy."),
    "ladder-r1c-p2": (
        "D-RUNG1C sensitivity ladder-r1c-p2 (development): identical to ladder-r1c except the remaining-forecast proxy "
        "P2 = two sources only: Open-Meteo Single-Runs ncep_hrrr_conus (run+3 h) and Single-Runs ncep_nbm_conus "
        "(run+6 h), same row selection. Proxy sensitivity only; no tuning."),
    "d-rung1c-d-nofc": (
        "D-RUNG1C diagnostic d-rung1c-d-nofc (development, NOT a candidate): ladder-r1c with every remaining-forecast "
        "condition treated as satisfied (source count 3, ceiling = F, spread 0, upside 0). Upper bound of the restored "
        "S3-S5 under a forecast that never blocks; measures how much the result depends on the proxy."),
}


def stop_check():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")


def register():
    lines = []
    for rid, text in RULES.items():
        rec = {"id": rid, "agent": "d-rung1c", "text": text,
               "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
               "time_local": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
        lines.append(json.dumps(rec))
    with open(REG, "a", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln + "\n")
    print("registered", list(RULES))


# ----------------------------------------------------------------------------- PIT METAR first-reached

def metar_first_reached(snaps, B):
    """Per snapshot: local minute-of-day of max_times[0] (first PIT METAR row of the day reaching B, else the
    first row reaching the running max), and how it was found."""
    st = t1.stations()
    first_min = np.full(len(snaps), np.nan)
    how = np.full(len(snaps), "none", dtype=object)
    snaps = snaps.assign(_i=np.arange(len(snaps)), _B=B)
    snaps = snaps[snaps.local_hour.between(13, 19)]
    for s, g in snaps.groupby("station", sort=False):
        tz = st[s]["tzname"]
        m = t1.load_metar(s)
        m = m[~m.is_cor].sort_values("available_utc").reset_index(drop=True)
        m["vloc"] = m.valid_utc.dt.tz_convert(tz)
        m["vmin"] = m.vloc.dt.hour * 60 + m.vloc.dt.minute
        avail = m.available_utc.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
        t = pd.to_datetime(g.captured_at_utc, utc=True, format="ISO8601").dt.tz_localize(None).to_numpy()
        last = np.searchsorted(avail, t, side="right") - 1
        md = m.local_date.to_numpy()
        tmp = m.tmpf.to_numpy(float)
        rb = np.floor(tmp + 0.5)
        vmin = m.vmin.to_numpy(float)
        vutc = m.valid_utc.to_numpy()
        h.assert_point_in_time(m.available_utc.to_numpy()[last[last >= 0]], g.captured_at_utc.to_numpy()[last >= 0])
        # day start index per local date
        day_first = pd.Series(np.arange(len(m))).groupby(md).min().to_dict()
        for j, (li, d, Bv, ii) in enumerate(zip(last, g.date.to_numpy(), g._B.to_numpy(), g._i.to_numpy())):
            if li < 0 or d not in day_first or md[li] != d or np.isnan(Bv):
                continue
            a = day_first[d]
            # rows a..li available; restrict to the target date (sorted by availability; dates monotone)
            seg = slice(a, li + 1)
            sel = md[seg] == d
            if not sel.any():
                continue
            tt, rr, vv, uu = tmp[seg][sel], rb[seg][sel], vmin[seg][sel], vutc[seg][sel]
            order = np.argsort(uu, kind="stable")
            tt, rr, vv = tt[order], rr[order], vv[order]
            hit = np.flatnonzero(rr >= Bv)
            if len(hit):
                first_min[ii] = vv[hit[0]]
                how[ii] = "metar_reached_B"
            else:
                k = int(np.argmax(tt))
                first_min[ii] = vv[k]
                how[ii] = "metar_runmax_below_B"
    return first_min, how


# ----------------------------------------------------------------------------- forecast proxies

def _source_runs(df, avail_col, val_col):
    """{station: (avail sorted ndarray, list of (valid_utc ndarray, values ndarray))}"""
    out = {}
    for s, g in df.groupby("station", sort=False):
        runs = []
        av = []
        for (a, r), gr in g.groupby([avail_col, "run"], sort=True):
            gr = gr.sort_values("valid_utc")
            runs.append((gr.valid_utc.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(), gr[val_col].to_numpy(float)))
            av.append(pd.Timestamp(a).tz_convert("UTC").tz_localize(None).to_datetime64())
        out[s] = (np.array(av), runs)
    return out


def load_sources():
    sr = pd.read_parquet(SR, columns=["station", "model", "run_utc", "valid_utc", "temperature_2m",
                                      "available_utc_design", "available_utc_conservative"])
    sr = sr.rename(columns={"run_utc": "run"})
    hrrr = sr[sr.model == "ncep_hrrr_conus"].assign(avail=lambda x: x.run + pd.Timedelta(hours=3))
    nbm = sr[sr.model == "ncep_nbm_conus"].assign(avail=lambda x: x.run + pd.Timedelta(hours=6))
    ifs = sr[sr.model == "ecmwf_ifs"].assign(avail=lambda x: x.run + pd.Timedelta(hours=8))
    nbh = pd.read_parquet(NBH, columns=["station", "field", "value", "cycle_utc", "valid_utc", "available_utc"],
                          filters=[("field", "==", "TMP")])
    nbh = nbh.rename(columns={"cycle_utc": "run", "available_utc": "avail"}).assign(temperature_2m=lambda x: x.value.astype(float))
    return {"hrrr": _source_runs(hrrr, "avail", "temperature_2m"),
            "nbm": _source_runs(nbm, "avail", "temperature_2m"),
            "ifs": _source_runs(ifs, "avail", "temperature_2m"),
            "nbh": _source_runs(nbh, "avail", "temperature_2m")}


def remaining_max(src, station, t_utc, end_utc, back=3):
    """Source max over the first 12 non-null values valid in [t, end) of the latest available run (<= 3 back)."""
    if station not in src:
        return None
    av, runs = src[station]
    k = np.searchsorted(av, t_utc, side="right") - 1
    for kk in range(k, max(k - back, -1), -1):
        if kk < 0:
            break
        assert av[kk] <= t_utc
        v, x = runs[kk]
        m = (v >= t_utc) & (v < end_utc) & ~np.isnan(x)
        if m.any():
            return float(x[m][:ROWS_CAP].max())
    return None


# ----------------------------------------------------------------------------- stages

def stage_strengths(hour, F, cur, stood, smax_list):
    """Return (s3, s4, s5) for one snapshot. smax_list = per-source remaining maxima (list)."""
    s3 = s4 = s5 = 0.0
    if np.isnan(F) or np.isnan(cur) or np.isnan(stood):
        return s3, s4, s5
    cmh = cur - F
    n = len(smax_list)
    ceiling = max(smax_list) if n else None
    spread = (max(smax_list) - min(smax_list)) if n >= 2 else (0.0 if n else None)
    # S3
    if S3_START <= hour <= S3_END and stood >= S3_MIN and cmh <= -S3_ROLL and n >= S3_NSRC \
            and ceiling is not None and ceiling <= F + S3_FMARGIN:
        s3 = 1.0
    # S4
    if S4_START <= hour <= S4_END and stood >= S4_STAND and cmh <= -S4_ROLL \
            and not (ceiling is not None and ceiling > F + S4_FMARGIN):
        tp = max(0.0, min(1.0, (hour - S4_START) / max(1, S4_END - S4_START)))
        sp = max(0.0, min(1.0, stood / max(1, S4_STAND * 2)))
        dp = max(0.0, min(1.0, (-cmh) / max(PEAK_DROP, 0.1)))
        s4 = max(0.0, min(S4_MAX, 0.25 + 0.35 * tp + 0.15 * sp + 0.25 * dp))
    # S5 (official = cur; consistency factor 1.0 because third-party == official <= -margin)
    if S5_START <= hour <= S5_END and stood >= S5_MIN and cmh <= -S5_ROLL and n > 0 \
            and not (ceiling is not None and ceiling > F + S5_UPMAX):
        upside = max(0.0, ceiling - F)
        agree = 0.80 if spread is None else (1.0 if spread <= S5_AGREE else
                                            max(0.45, 1.0 - 0.40 * min(1.0, (spread - S5_AGREE) / max(S5_AGREE, 0.1))))
        upf = 1.0 - 0.40 * min(1.0, upside / max(S5_UPMAX, 0.1))
        tf = max(0.0, min(1.0, (hour - S5_START) / max(1, S5_END - S5_START)))
        sf = max(0.0, min(1.0, stood / max(1, S5_MIN * 2)))
        df = max(0.0, min(1.0, (-cmh) / max(PEAK_DROP, 0.1)))
        raw = S5_BASE + 0.14 * tf + 0.16 * sf + 0.20 * df
        s5 = max(0.0, min(S5_MAX, raw * agree * upf * 1.0))
    return s3, s4, s5


def band_factor2(bands, B, s_hard, s5):
    """Uniform-within-band mean retention: hard lock-in where s_hard > 0, else S5 partial where s5 > 0."""
    low = bands["low"].to_numpy(float)
    high = bands["high"].to_numpy(float)
    kind = bands["kind"].to_numpy()
    lo = np.where(kind == "lte", np.minimum(B, high), low)
    hi = np.where(kind == "gte", low, high)
    width = (hi - lo + 1).astype(int)
    acc = np.zeros(len(bands))
    use5 = (s_hard <= 0) & (s5 > 0)
    for j in range(int(width.max())):
        k = lo + j
        valid = j < width
        above = k - B
        fh = (1.0 - s_hard) + s_hard * dd.HEDGE * dd.BASE ** np.maximum(above - 1, 0)
        ret5 = np.where(above == 1, S5_ONE, np.where(above == 2, S5_TWO, S5_TWO * S5_BASE ** np.maximum(above - 2, 0)))
        f5 = (1.0 - s5) + s5 * ret5
        f = np.where(above <= 0, 1.0, np.where(use5, f5, fh))
        acc += np.where(valid, f, 0.0)
    return acc / width


# ----------------------------------------------------------------------------- build

def build_strengths(snaps, S):
    """Compute S3-S5 per snapshot under proxies P1, P2 and forecast-free; returns DataFrame."""
    F = S["floor"].to_numpy(float)
    B = S["B"].to_numpy(float)
    cur = S["cur"].to_numpy(float)
    lh = S.local_hour.to_numpy()
    first_min, how = metar_first_reached(snaps, B)
    loc = pd.to_datetime(snaps.captured_at_local.str.slice(0, 19))
    wall = (loc.dt.hour * 60 + loc.dt.minute).to_numpy(float)
    stood = wall - first_min
    srcs = load_sources()
    st = t1.stations()
    tutc = pd.to_datetime(snaps.captured_at_utc, utc=True, format="ISO8601").dt.tz_localize(None).to_numpy()
    out = {k: np.zeros(len(snaps)) for k in ("p1_s3", "p1_s4", "p1_s5", "p2_s3", "p2_s4", "p2_s5",
                                              "nf_s3", "nf_s4", "nf_s5", "p1_n", "p2_n")}
    sel = np.flatnonzero((lh >= 13) & (lh <= 19) & ~np.isnan(F))
    ends = {}
    for i in sel:
        stn = snaps.station.iat[i]
        d = snaps.date.iat[i]
        key = (stn, d)
        if key not in ends:
            tz = st[stn]["tzname"]
            ends[key] = (pd.Timestamp(d, tz=tz) + pd.Timedelta(days=1)).tz_convert("UTC").tz_localize(None).to_datetime64()
        end = ends[key]
        t = tutc[i]
        mx = {k: remaining_max(srcs[k], stn, t, end) for k in ("hrrr", "nbh", "ifs", "nbm")}
        p1 = [mx[k] for k in ("hrrr", "nbh", "ifs") if mx[k] is not None]
        p2 = [mx[k] for k in ("hrrr", "nbm") if mx[k] is not None]
        out["p1_n"][i], out["p2_n"][i] = len(p1), len(p2)
        for tag, lst in (("p1", p1), ("p2", p2), ("nf", [F[i]] * 3)):
            a, b, c = stage_strengths(int(lh[i]), F[i], cur[i], stood[i], lst)
            out[f"{tag}_s3"][i], out[f"{tag}_s4"][i], out[f"{tag}_s5"][i] = a, b, c
    df = pd.DataFrame(out)
    df["stood"] = stood
    df["first_how"] = how
    df["row_key"] = snaps.row_key.to_numpy()
    return df


def main_score():
    stop_check()
    snaps, bands = h.candidate_inputs()
    assert (snaps["date"].astype(str) > "2026-09-29").sum() == 0
    assert (snaps.unit == "F").all() if "unit" in snaps else True
    d = h.data()
    S = lp.strengths(snaps)            # B, s (S1/S2 exactly as rung 1/2), cur
    snaps = snaps.copy()
    if "captured_at_local" not in snaps or "station" not in snaps:
        extra = pd.read_parquet(r"C:\swarm\cache\snapshots.parquet", columns=["row_key", "captured_at_local", "station"])
        snaps = snaps.drop(columns=[c for c in ("captured_at_local", "station") if c in snaps]).merge(extra, on="row_key", how="left")
        assert (snaps.row_key.to_numpy() == S.row_key.to_numpy()).all()
    cache_f = OUT / "strengths.parquet"
    if cache_f.exists():
        ST = pd.read_parquet(cache_f)
        assert (ST.row_key.to_numpy() == snaps.row_key.to_numpy()).all()
    else:
        ST = build_strengths(snaps, S)
        ST.to_parquet(cache_f)
    stop_check()
    bs = d.band_snap
    Bb = S["B"].to_numpy(float)[bs]
    hasB = ~np.isnan(S["B"].to_numpy(float))
    hasBb = hasB[bs]
    s12 = S["s"].to_numpy(float)
    # rung 2 rebuilt (verify against ladder snapb)
    pc1 = lp.c1_probs(snaps, bands, d.offsets)
    c1cov = ~np.isnan(pc1)
    served = bands.p_served.to_numpy(float)
    base = np.where(c1cov, pc1, served)

    def rung(s_hard, s5):
        sh, s5b = np.where(hasB, s_hard, 0.0)[bs], np.where(hasB, s5, 0.0)[bs]
        fac = band_factor2(bands, np.nan_to_num(Bb), sh, s5b)
        pc = lp.renorm(bands[["row_key", "band_index"]].assign(p=np.nan_to_num(base) * fac)).p.to_numpy()
        pr1 = lp.renorm(bands[["row_key", "band_index"]].assign(p=served * fac)).p.to_numpy()
        p = np.where(c1cov, pc, pr1)
        return bands.loc[hasBb, ["row_key", "band_index"]].assign(p=p[hasBb])

    cands = {"ladder-r2-rebuilt": rung(s12, np.zeros(len(s12)))}
    diag = {}
    for rid, tag in (("ladder-r1c", "p1"), ("ladder-r1c-p2", "p2"), ("d-rung1c-d-nofc", "nf")):
        hard = np.maximum.reduce([s12, ST[f"{tag}_s3"].to_numpy(), ST[f"{tag}_s4"].to_numpy()])
        s5 = np.where(hard > 0, 0.0, ST[f"{tag}_s5"].to_numpy())
        cands[rid] = rung(hard, s5)
        lh = snaps.local_hour.to_numpy()
        dg = {}
        for g, (lo, hi) in BLOCKS.items():
            m = (lh >= lo) & (lh <= hi) & hasB
            if not m.any():
                continue
            dg[g] = {"snapshots": int(m.sum()),
                     "share_s12_pos": float((s12[m] > 0).mean()),
                     "share_s3_active": float((ST[f"{tag}_s3"].to_numpy()[m] > 0).mean()),
                     "share_s4_active": float((ST[f"{tag}_s4"].to_numpy()[m] > 0).mean()),
                     "share_hard_pos": float((hard[m] > 0).mean()),
                     "share_hard_raised_over_s12": float((hard[m] > s12[m] + 1e-12).mean()),
                     "share_s5_applied": float((s5[m] > 0).mean()),
                     "mean_hard": float(hard[m].mean()), "mean_s5_applied": float(s5[m].mean())}
        diag[rid] = dg
    lh = snaps.local_hour.to_numpy()
    m1319 = (lh >= 13) & (lh <= 19) & hasB
    diag["proxy_coverage_13_19"] = {
        "p1_sources_count_share": {str(k): float((ST.p1_n.to_numpy()[m1319] == k).mean()) for k in range(4)},
        "p2_sources_count_share": {str(k): float((ST.p2_n.to_numpy()[m1319] == k).mean()) for k in range(3)},
        "first_reached_how": ST.first_how[m1319].value_counts(normalize=True).to_dict(),
        "stood_ge_60_share": float((ST.stood.to_numpy()[m1319] >= 60).mean()),
        "cur_le_F_minus_0.45_share": float(((S["cur"].to_numpy() - S["floor"].to_numpy()) <= -0.45)[m1319].mean()),
    }

    P = lp.Paired()
    sb = {}
    res = {}
    for rid, cand in cands.items():
        stop_check()
        r = h.score(cand, name=rid.replace("-", "_"))
        if r["leakage_suspect_groups"]:
            Path(r"C:\swarm\STOP").write_text(f"d-rung1c: leakage suspect in {rid}: {r['leakage_suspect_groups']}\n")
            sys.exit("leakage suspect")
        h.save(r, OUT)
        res[rid] = r
        sb[rid], _ = P.snap_brier(cand)
        np.save(OUT / f"snapb_{rid}.npy", sb[rid])
        print(rid, {g: r["classes"][g]["class"] for g in r["classes"]}, flush=True)
    r2_ladder = np.load(Path(r"C:\swarm\out\ladder\snapb_ladder-r2.npy"))
    repro = float(np.nanmax(np.abs(sb["ladder-r2-rebuilt"] - r2_ladder)))
    print("r2 reproduction max abs diff", repro)
    assert repro < 1e-9, repro
    t3b, _ = P.snap_brier(pd.read_parquet(T3R3))

    # per-block tables
    table = {}
    for rid in ("ladder-r1c", "ladder-r1c-p2", "d-rung1c-d-nofc"):
        table[rid] = {}
        cvec = sb[rid]
        se_c = None
        for g in BLOCKS:
            row = {}
            for st_ in (FROM, BEFORE):
                c, idx = P.cells(g, st_, {"c": cvec, "s": P.served_b, "mk": P.market_b, "r2": r2_ladder, "t3": t3b})
                cm = h.interval(idx, (c.c - c.mk).to_numpy())
                ratio = h.interval(idx, c.c.to_numpy(), c.mk.to_numpy())
                gap = (c.s - c.mk).to_numpy()
                closed = h.interval(idx, (c.s - c.c).to_numpy(), gap)
                r2cm = h.interval(idx, (c.r2 - c.mk).to_numpy())
                r2cl = h.interval(idx, (c.s - c.r2).to_numpy(), gap)
                row[st_] = {"cand_minus_market": cm["estimate"], "cand_minus_market_ci95": cm["ci95"],
                            "ratio": ratio["estimate"], "ratio_ci95": ratio["ci95"],
                            "ratio_interpretable": bool(c.mk.mean() >= 0.005),
                            "gap_closed": closed["estimate"], "gap_closed_ci95": closed["ci95"],
                            "r2_minus_market": r2cm["estimate"], "r2_gap_closed": r2cl["estimate"],
                            "marginal_vs_r2": P.paired(cvec, r2_ladder, g, st_),
                            "vs_served": P.paired(cvec, P.served_b, g, st_),
                            "vs_t3r3": P.paired(cvec, t3b, g, st_),
                            "market_days": int(len(c))}
                # tail rows (this table's definition)
                if se_c is None:
                    pc, _, _ = h._candidate_vector(cands[rid], d, False)
                    se_c = (pc - d.y) ** 2
                lo, hi = BLOCKS[g]
                sel = (P.LH >= lo) & (P.LH <= hi) & (P.STR == st_)
                tl = h._tail(d, se_c, sel, h.CACHE)
                row[st_]["tail"] = {"band_rows": tl.get("tail_band_rows"),
                                    "share_of_tail_excess_removed": tl.get("share_of_tail_excess_removed")}
            table[rid][g] = row
        # r2 tail for comparison
    # r2 tail (from ladder rung) for 15-16 etc.
    pc2, _, _ = h._candidate_vector(cands["ladder-r2-rebuilt"], d, False)
    se2 = (pc2 - d.y) ** 2
    r2tail = {}
    for g, (lo, hi) in BLOCKS.items():
        sel = (P.LH >= lo) & (P.LH <= hi) & (P.STR == FROM)
        r2tail[g] = h._tail(d, se2, sel, h.CACHE).get("share_of_tail_excess_removed")
    out = {"agent": "d-rung1c", "HARNESS_SHA256": h.harness_sha256(), "development": True,
           "rows_after_0929": res["ladder-r1c"]["rows_with_target_after_2026_09_29"],
           "leakage_suspect_groups": {k: v["leakage_suspect_groups"] for k, v in res.items()},
           "r2_reproduction_max_abs_diff": repro,
           "classes": {k: {g: v["classes"][g]["class"] for g in v["classes"]} for k, v in res.items()},
           "reason_counts": {k: v["reason_counts"] for k, v in res.items()},
           "table": table, "r2_tail_from": r2tail, "diag": diag,
           "registry_ids": list(RULES)}
    (OUT / "scores.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    for rid in table:
        print("\n==", rid)
        for g in BLOCKS:
            f, b = table[rid][g][FROM], table[rid][g][BEFORE]
            mg, t3 = f["marginal_vs_r2"], f["vs_t3r3"]
            print(f"{g}: c-m {lp.ci(f['cand_minus_market'], f['cand_minus_market_ci95'])} (b {lp.fmt(b['cand_minus_market'])}) "
                  f"ratio {f['ratio']:.3f} closed {f['gap_closed']:.3f} [{f['gap_closed_ci95'][0]:.2f},{f['gap_closed_ci95'][1]:.2f}] "
                  f"(r2 {f['r2_gap_closed']:.3f}) | r1c-r2 {lp.ci(mg['estimate'], mg['ci95'])} {mg['markets_negative']}/{mg['markets_positive']} "
                  f"b {lp.fmt(b['marginal_vs_r2']['estimate'])} | -t3r3 {lp.ci(t3['estimate'], t3['ci95'])} {t3['markets_negative']}/11 "
                  f"b {lp.fmt(b['vs_t3r3']['estimate'])} | tail {f['tail']['share_of_tail_excess_removed']['estimate'] if f['tail']['share_of_tail_excess_removed'] else None}")
    print(json.dumps(diag, indent=1, default=float))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "score"
    if mode == "register":
        register()
    elif mode == "score":
        main_score()


# ----------------------------------------------------------------------------- descriptive attribution (no new rule)

def attribution():
    """Where the 15-16 / 13-14 residual of ladder-r1c sits, by the stage state of each snapshot (descriptive)."""
    stop_check()
    P = lp.Paired()
    d = P.d
    snaps, bands = h.candidate_inputs()
    S = lp.strengths(snaps)
    ST = pd.read_parquet(OUT / "strengths.parquet")
    assert (ST.row_key.to_numpy() == S.row_key.to_numpy()).all()
    s12 = S["s"].to_numpy(float)
    hard = np.maximum.reduce([s12, ST.p1_s3.to_numpy(), ST.p1_s4.to_numpy()])
    s5 = np.where(hard > 0, 0.0, ST.p1_s5.to_numpy())
    rolled = (S["cur"].to_numpy() - S["floor"].to_numpy()) <= -0.45
    r2b = np.load(Path(r"C:\swarm\out\ladder\snapb_ladder-r2.npy"))
    t3b, _ = P.snap_brier(pd.read_parquet(T3R3))
    c_r1c = np.load(OUT / "snapb_ladder-r1c.npy")
    out = {}
    states = {"stage_active(hard>0 or S5)": (hard > 0) | (s5 > 0),
              "no_stage": (hard <= 0) & (s5 <= 0),
              "rolled_over(cur<=F-0.45)": rolled,
              "not_rolled(cur>F-0.45 or missing)": ~rolled}
    for g in ("13-14", "15-16"):
        lo, hi = BLOCKS[g]
        blk = (P.LH >= lo) & (P.LH <= hi) & (P.STR == FROM)
        out[g] = {}
        for nm, mk in states.items():
            m = blk & mk
            out[g][nm] = {
                "snapshot_share_of_block": float(m.sum() / blk.sum()),
                "excess_share_r1c": float((c_r1c[m] - P.market_b[m]).sum() / (c_r1c[blk] - P.market_b[blk]).sum()),
                "r1c_minus_market_mean": float((c_r1c[m] - P.market_b[m]).mean()),
                "r1c_minus_r2": P.paired(c_r1c, r2b, g, FROM, mask=mk),
                "t3r3_minus_r1c": P.paired(t3b, c_r1c, g, FROM, mask=mk),
            }
            print(g, nm, json.dumps({k: (v if not isinstance(v, dict) else {kk: v[kk] for kk in ('estimate', 'ci95', 'markets_negative')})
                                     for k, v in out[g][nm].items()}, default=float))
    (OUT / "attribution.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "attr":
    attribution()
