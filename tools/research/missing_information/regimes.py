"""Check 5: descriptive weather tags with missingness and crossed intervals."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

from weather.market.market_registry import REGISTRY
from tools.research.missing_information.checks import cells, tail_selection
from tools.research.missing_information.methods import crossed_weights


def load_observations(root):
    frames = []
    for spec in REGISTRY.values():
        if spec.icao not in {"CYYZ", "KATL", "KAUS", "KBKF", "KDAL", "KHOU", "KLAX", "KLGA", "KMIA", "KORD", "KSEA", "KSFO"}:
            continue
        for report_type in (3, 4):
            path = root / f"{spec.icao}-{report_type}.csv"
            if not path.exists():
                continue
            f = pd.read_csv(path, na_values=["M"], low_memory=False)
            if not len(f):
                continue
            f["utc"] = pd.to_datetime(f.valid, utc=True)
            local = f.utc.dt.tz_convert(spec.timezone)
            f["date"] = local.dt.strftime("%Y-%m-%d")
            f["hour"] = local.dt.hour
            f["market"] = spec.id
            f["report_type"] = report_type
            frames.append(f)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def observation_tags(day, coastal):
    result = {}
    if day.empty:
        return result
    d = day.sort_values("utc").drop_duplicates(["utc", "metar"])
    active = d[d.hour.between(10, 15)]
    def low_ceiling(part):
        valid = np.zeros(len(part), bool)
        low = np.zeros(len(part), bool)
        for i in range(1, 5):
            sky, height = part.get(f"skyc{i}"), part.get(f"skyl{i}")
            if sky is None or height is None:
                continue
            h = pd.to_numeric(height, errors="coerce")
            valid |= sky.notna().to_numpy()
            low |= (sky.isin(["BKN", "OVC", "VV"]) & (h < 5000)).to_numpy()
        return float(low.any()) if valid.any() else None
    result["low_ceiling"] = low_ceiling(active)
    result["coastal_stratus"] = low_ceiling(d[d.hour.between(6, 9)]) if coastal else None
    wx = d.get("wxcodes")
    result["thunder_or_showers"] = float(wx.fillna("").astype(str).str.contains("TS|SH").any()) if wx is not None else None
    shifts, fronts = [], []
    values = d.to_dict("records")
    for i, current in enumerate(values):
        for previous in values[:i]:
            hours = (current["utc"]-previous["utc"]).total_seconds()/3600
            if not 0 < hours <= 3:
                continue
            a, b = current.get("drct"), previous.get("drct")
            if pd.isna(a) or pd.isna(b):
                continue
            angle = abs(float(a)-float(b)) % 360
            shift = min(angle, 360-angle) >= 90
            shifts.append(shift)
            cd, pdw, ca, pa = (current.get("dwpf"), previous.get("dwpf"), current.get("alti"), previous.get("alti"))
            if any(pd.isna(v) for v in (cd, pdw, ca, pa)):
                continue
            fronts.append(shift and (pdw-cd)*5/9 >= 3 and ca > pa)
    result["wind_shift"] = float(any(shifts)) if shifts else None
    result["front_proxy"] = float(any(fronts)) if fronts else None
    result["observation_count"] = len(d)
    return result


def odds_summary(frame, tag):
    f = frame.dropna(subset=[tag]).copy()
    n, d, m = len(f), f.date.nunique(), f.market.nunique()
    support = {"market_days": n, "date_clusters": d, "market_clusters": m, "missing_days": len(frame)-n}
    if not n:
        return {**support, "status": "NO_DATA"}
    if f[tag].nunique() < 2:
        return {**support, "status": "NO_TAG_VARIATION", "observed_tag_value": float(f[tag].iloc[0]),
                "odds_ratio": None, "ci95": None, "power_at_or2": None, "mde80_odds_ratio": None}
    def log_or(w):
        tail = f["tail"].to_numpy(bool)
        tagged = f[tag].to_numpy(bool)
        a, b, c, dd = [np.sum(w * mask, axis=-1) for mask in (
            tail & tagged, tail & ~tagged, ~tail & tagged, ~tail & ~tagged)]
        return np.log((a+.5)*(dd+.5)/((b+.5)*(c+.5)))
    estimate = float(log_or(np.ones(n)))
    tail = f[f["tail"]]
    rest = f[~f["tail"]]
    support.update(tail_days=len(tail), non_tail_days=len(rest),
                   tag_rate_tail=float(tail[tag].mean()) if len(tail) else None,
                   tag_rate_non_tail=float(rest[tag].mean()) if len(rest) else None)
    if d < 2 or m < 2 or len(tail) == 0 or len(rest) == 0:
        return {**support, "status": "INSUFFICIENT_CLUSTERS", "odds_ratio": math.exp(estimate)}
    w = crossed_weights(f.date, f.market)
    boot = log_or(w)
    error = boot-estimate
    critical = np.quantile(abs(error), .95)
    power = lambda effect: float(np.mean(np.abs(error + effect) > critical))
    low, high = 0., max(critical*10, 1e-9)
    for _ in range(50):
        mid = (low+high)/2
        if power(mid) >= .8:
            high = mid
        else:
            low = mid
    ci = np.exp(np.quantile(boot, [.025, .975])).tolist()
    return {**support, "status": "DESCRIPTIVE" if power(math.log(2)) >= .8 else "UNPOWERED_AT_OR2",
            "odds_ratio": math.exp(estimate), "ci95": ci,
            "mde80_log_or": high, "mde80_odds_ratio": math.exp(min(high, 700)),
            "power_at_or2": power(math.log(2)), "correction": "Haldane-Anscombe +0.5",
            "interval_scope": "conditional on descriptive tail membership; not prospective prediction"}


def check5(frame, observations, output):
    obs_groups = {(date, market): group for (date, market), group in observations.groupby(["date", "market"])} if len(observations) else {}
    daily = []
    for (stratum, date, market), day in frame.groupby(["stratum", "date", "market"], observed=True):
        day = day.sort_values("captured_at_utc")
        first = day.iloc[0]
        peaks = day.dropna(subset=["hours_from_peak"])
        peak_hour = (peaks.iloc[0].decimal_hour-peaks.iloc[0].hours_from_peak) if len(peaks) else None
        row = {"stratum": stratum, "date": date, "market": market,
               "excess": day.groupby("hour").excess.mean().sum(),
               "non_diurnal": float(peak_hour < 11 or peak_hour > 18) if peak_hour is not None else None,
               "peak_hour": peak_hour, "last_hour": day.decimal_hour.max()}
        morning = day[day.decimal_hour <= 8].dropna(subset=["nws_forecast_max_c"])
        if len(morning):
            r = morning.iloc[-1]
            # 08:00 as-of with <=2h maximum age, never a future snapshot.
            row["guidance_bust"] = float(abs(r.settlement_high-r.nws_forecast_max_c) >= (3 if r.unit == "F" else 3*5/9)) if r.decimal_hour >= 6 else None
        row.update(observation_tags(obs_groups.get((date, market), pd.DataFrame()), bool(first.coastal)))
        for tag, field in (("mrms", "f_mrms_convective_interruption"), ("marine", "f_marine_layer_suppression")):
            values = day[field].dropna() if field in day else pd.Series(dtype=float)
            row[tag] = float((values > 0).any()) if len(values) else None
        for tag, fields in (("disagreement_over_2C", ["f_forecast_disagreement", "forecast_disagreement"]),
                            ("ensemble_spread_over_2C", ["f_forecast_global_ensemble_spread", "f_ensemble_std", "f_ensemble_spread", "f_global_ensemble_std"])):
            present = next((field for field in fields if field in day and day[field].notna().any()), None)
            row[tag] = float((day[present] > (3.6 if first.unit == "F" else 2)).any()) if present else None
        daily.append(row)
    df = pd.DataFrame(daily)
    result = {}
    tags = ["non_diurnal", "low_ceiling", "coastal_stratus", "wind_shift", "thunder_or_showers", "front_proxy",
            "guidance_bust", "mrms", "marine", "disagreement_over_2C", "ensemble_spread_over_2C"]
    for tag in tags:
        if tag not in df:
            df[tag] = np.nan
    for stratum, f in df.groupby("stratum", observed=True):
        f = f.copy()
        tail = tail_selection(f)
        f["tail"] = f.index.isin(tail.index)
        f.to_csv(output / f"regime_days_{stratum}.csv", index=False)
        result[stratum] = {"tail_days": len(tail), "total_days": len(f),
                           "tags": {tag: odds_summary(f, tag) for tag in tags}}
    return result
