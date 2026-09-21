"""Checks 1, 2 and 4a on the served surface, retaining paired denominators."""
from __future__ import annotations

from collections import defaultdict
import json
import math

import numpy as np
import pandas as pd

from tools.research.missing_information.methods import (
    Band, band_probabilities, empirical_probabilities, summary,
)


def bucket(h):
    # Half-open bins remove the plan's overlapping endpoint notation.
    return "00-10" if h < 10 else "10-13" if h < 13 else "13-17" if h < 17 else "17-24"


def load_frame(path):
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            s = json.loads(line)
            y = np.eye(len(s["p_model"]))[s["winner"]]
            model = np.asarray(s["p_model"])
            market = np.asarray(s["p_market"])
            s["model_loss"] = float(np.mean((model - y) ** 2))
            s["market_loss"] = float(np.mean((market - y) ** 2))
            s["market_normalized_loss"] = float(np.mean((market / market.sum() - y) ** 2))
            s["excess"] = s["model_loss"] - s["market_loss"]
            s["excess_normalized"] = s["model_loss"] - s["market_normalized_loss"]
            s["disagreement"] = float(np.max(np.abs(model - market)) >= .30)
            m, k, w = int(model.argmax()), int(market.argmax()), s["winner"]
            s.update(mode_distance=abs(m-k), model_winner_distance=abs(m-w),
                     market_winner_distance=abs(k-w), model_cooler=float(m < k),
                     adjacent=float(abs(m-k) == 1), distant=float(abs(m-k) >= 2),
                     before_peak=float(s["hours_from_peak"] < 0) if s["hours_from_peak"] is not None else None)
            s["bucket"] = bucket(s["decimal_hour"])
            floor = s["station_max_since_7am_c"]
            impossible = [b["kind"] != "gte" and b["high"] < math.floor(floor + .5)
                          for b in s["bands"]] if floor is not None else None
            s["model_impossible_mass"] = float(model[impossible].sum()) if impossible is not None else None
            s["market_impossible_mass"] = float(market[impossible].sum()) if impossible is not None else None
            for name, value in s["features"].items():
                s["f_" + name] = value
            rows.append(s)
    return pd.DataFrame(rows)


def cells(frame, columns, extra=()):
    return frame.groupby(["date", "market", *extra], observed=True)[columns].mean().reset_index()


def compare(frame, market_column="market_loss"):
    f = frame.copy()
    f["paired_excess"] = f["model_loss"] - f[market_column]
    return {"model": summary(f, "model_loss"), "market": summary(f, market_column),
            "excess": summary(f, "paired_excess", alternative=.01),
            "ratio": summary(f, "model_loss", market_column, null=1, alternative=.30)}


def tail_selection(frame, amount="excess", rank=None):
    """Signed total, never silently clipped; rank snapshots, weight hour cells."""
    f = frame.sort_values(rank or amount, ascending=False, kind="stable").copy()
    total = f[amount].sum()
    if total <= 0:
        return f.iloc[:0]
    crossing = np.flatnonzero(f[amount].cumsum().to_numpy() >= .64 * total)
    return f.iloc[:int(crossing[0]) + 1] if len(crossing) else f.iloc[:0]


def check1(frame):
    result = {}
    columns = ["model_loss", "market_loss", "market_normalized_loss", "excess", "excess_normalized"]
    for stratum, f in frame.groupby("stratum", observed=True):
        hourly = cells(f, columns, ["hour"])
        out = {"by_hour": {int(h): {"raw": compare(g), "normalized": compare(g, "market_normalized_loss")}
                           for h, g in hourly.groupby("hour", observed=True)}}
        total = hourly.excess.sum()
        out["after_noon_share"] = float(hourly.loc[hourly.hour >= 12, "excess"].sum() / total) if total > 0 else None
        out["after_noon_share_note"] = "signed summed market-day-hour excess, may fall outside [0,1]"
        daily_total = hourly.groupby(["date", "market"])["excess"].sum().rename("total")
        daily_late = hourly[hourly.hour >= 12].groupby(["date", "market"])["excess"].sum().rename("late")
        shares = pd.concat([daily_total, daily_late], axis=1).fillna(0).reset_index()
        out["after_noon_share_interval"] = summary(shares, "late", "total", null=.6, alternative=.1)
        for name, mask in (("morning_06_10", hourly.hour.between(6, 9)),
                           ("afternoon_13_17", hourly.hour.between(13, 16))):
            out[name] = {"raw": compare(hourly[mask]), "normalized": compare(hourly[mask], "market_normalized_loss")}
        # Pair the morning/afternoon comparison on exactly the same market-days.
        am = cells(hourly[hourly.hour.between(6, 9)], columns).set_index(["date", "market"])
        pm = cells(hourly[hourly.hour.between(13, 16)], columns).set_index(["date", "market"])
        matched = am.join(pm, lsuffix="_am", rsuffix="_pm", how="inner").reset_index()
        matched["excess_rise"] = matched.excess_pm - matched.excess_am
        out["paired_excess_rise"] = summary(matched, "excess_rise", alternative=.01)
        # Frozen peak-relative bins; missing peak is explicitly excluded.
        bins = [-np.inf, -6, -3, -1, 0, 1, 3, np.inf]
        labels = ["<=-6", "-6:-3", "-3:-1", "-1:0", "0:1", "1:3", ">3"]
        f = f.copy()
        f["peak_bin"] = pd.cut(f.hours_from_peak, bins=bins, labels=labels, right=True)
        peak_cells = cells(f.dropna(subset=["peak_bin"]), columns, ["peak_bin", "hour"])
        out["by_peak"] = {str(p): compare(g) for p, g in peak_cells.groupby("peak_bin", observed=True)}
        lags = []
        for (date, market), day in hourly.groupby(["date", "market"]):
            day = day.sort_values("hour")
            for row in day.itertuples():
                future = day[(day.hour >= row.hour) & (day.model_loss <= row.market_loss)]
                lags.append({"date": date, "market": market, "hour": row.hour,
                             "lag": float(future.hour.iloc[0]-row.hour) if len(future) else None,
                             "right_censored": not len(future), "followup_hours": int(day.hour.max()-row.hour)})
        lf = pd.DataFrame(lags)
        out["lag_by_hour"] = {int(h): {"resolved": int(g.lag.notna().sum()), "censored": int(g.right_censored.sum()),
                                        "quartiles_resolved_only": g.lag.quantile([.25, .5, .75]).tolist()}
                              for h, g in lf.groupby("hour")}
        am_ratio = out["morning_06_10"]["raw"]["ratio"].get("estimate")
        pm_ratio = out["afternoon_13_17"]["raw"]["ratio"].get("estimate")
        out["frozen_reading"] = {
            "intraday_rule": bool(total > 0 and out["after_noon_share"] >= .6 and am_ratio is not None and pm_ratio is not None and pm_ratio > am_ratio),
            "preday_rule": bool(am_ratio is not None and am_ratio >= 1.3),
            "clock_skip_rule": bool(am_ratio is not None and pm_ratio is not None and am_ratio >= 1.3 and pm_ratio <= am_ratio),
        }
        result[stratum] = out
    return result


def check2(frame):
    result = {}
    metrics = ["mode_distance", "model_winner_distance", "market_winner_distance", "model_cooler",
               "adjacent", "distant", "before_peak", "model_impossible_mass", "market_impossible_mass"]
    for stratum, f in frame.groupby("stratum", observed=True):
        f = f.copy()
        count = f.groupby(["date", "market", "hour"]).snapshot_id.transform("count")
        f["weighted_excess"] = f.excess / count
        tail = tail_selection(f, "weighted_excess", rank="excess")
        out = {}
        for name, g in (("all", f), ("disagreement", f[f.disagreement == 1]), ("tail", tail)):
            hour = cells(g, metrics, ["hour"])
            out[name] = {metric: summary(hour, metric, alternative=.1) for metric in metrics}
            out[name]["snapshots"] = len(g)
        out["tail_raw_cadence_sensitivity_snapshots"] = len(tail_selection(f))
        instrument = []
        for (date, market), day in f.groupby(["date", "market"]):
            day = day.sort_values("captured_at_utc")
            for window, sub in (("final", day), ("before18", day[day.decimal_hour < 18])):
                sub = sub.dropna(subset=["station_max_since_7am_c"])
                if not len(sub):
                    continue
                last = sub.iloc[-1]
                instrument.append({"date": date, "market": market, "window": window,
                                   "delta": int(last.settlement_bucket-math.floor(last.station_max_since_7am_c+.5)),
                                   "last_hour": float(last.decimal_hour)})
        inst = pd.DataFrame(instrument)
        out["instrument"] = instrument
        out["instrument_histograms"] = {}
        if len(inst):
            inst["off_zero"] = (inst.delta != 0).astype(float)
            for window, g in inst.groupby("window"):
                out["instrument_histograms"][window] = {m: {int(k): int(v) for k, v in x.delta.value_counts().items()}
                                                        for m, x in g.groupby("market")}
                out[f"{window}_off_zero"] = summary(g, "off_zero", null=.1, alternative=.1)
        out["interpretation_limit"] = "A nonzero histogram can reflect feed coverage or source differences; it does not isolate precision. Final max is a captured partial-day proxy."
        result[stratum] = out
    return result


def check4(frame, output):
    f = frame.copy()
    fields = [f"f_nbm_prob_tmax_p{p}" for p in (10, 25, 50, 75, 90)] + ["f_nbm_prob_tmax_mean", "f_nbm_prob_tmax_stddev"]
    for name in fields:
        if name not in f:
            f[name] = np.nan
    f["nbm_percentiles_present"] = f[fields[:5]].notna().all(axis=1).astype(float)
    f["nbm_present"] = f[fields].notna().all(axis=1).astype(float)
    coverage = {}
    for key in ("market", "hour", "date"):
        c = f.groupby(["stratum", key], observed=True).agg(
            snapshots=("nbm_present", "count"), percentiles_filled=("nbm_percentiles_present", "sum"),
            percentiles_fill=("nbm_percentiles_present", "mean"), cdf_fields_filled=("nbm_present", "sum"),
            cdf_fields_fill=("nbm_present", "mean"))
        c.to_csv(output / f"nbm_fill_by_{key}.csv")
        coverage[key] = c.reset_index().to_dict("records")
    losses = []
    for row in f.itertuples():
        data = row._asdict()
        bands = [Band(**b) for b in row.bands]
        y = np.eye(len(bands))[row.winner]
        if row.nbm_present:
            for name, floor in (("nbm_raw", None), ("nbm_floor", row.station_max_since_7am_c)):
                if name == "nbm_floor" and pd.isna(floor):
                    continue
                try:
                    p = band_probabilities(bands, [data[k] for k in fields[:5]], data[fields[5]], data[fields[6]], floor)
                except ValueError:
                    continue
                losses.append({"date": row.date, "market": row.market, "stratum": row.stratum,
                               "bucket": row.bucket, "hour": row.hour, "variant": name,
                               "candidate_loss": float(np.mean((p-y)**2)), "model_loss": row.model_loss,
                               "market_loss": row.market_loss, "market_normalized_loss": row.market_normalized_loss,
                               "training_dates": 0})
    f["hrrr_point"] = f.get("f_forecast_high", np.nan) + f.get("f_open_meteo_hrrr_high_delta", np.nan)
    for variant, column in (("nws", "nws_forecast_max_c"), ("open_meteo", "open_meteo_max_c"), ("hrrr", "hrrr_point")):
        for (stratum, market, time_bucket), group in f.groupby(["stratum", "market", "bucket"], observed=True):
            earlier = []
            for date, day in group.sort_values("date").groupby("date", sort=True):
                valid = day.dropna(subset=[column])
                if len(earlier) >= 5:
                    errors = np.array([v for _, v in earlier])
                    for row in valid.itertuples():
                        point = row._asdict()[column]
                        bands = [Band(**b) for b in row.bands]
                        p = empirical_probabilities(bands, point, errors)
                        y = np.eye(len(bands))[row.winner]
                        losses.append({"date": date, "market": market, "stratum": stratum,
                                       "bucket": time_bucket, "hour": row.hour, "variant": variant,
                                       "candidate_loss": float(np.mean((p-y)**2)), "model_loss": row.model_loss,
                                       "market_loss": row.market_loss, "market_normalized_loss": row.market_normalized_loss,
                                       "training_dates": len(earlier), "latest_training_date": earlier[-1][0]})
                if len(valid):
                    # One residual per market-date-bucket, equal weighting of observed hours.
                    hourly_point = valid.groupby("hour", observed=True)[column].mean().mean()
                    earlier.append((date, float(valid.settlement_high.iloc[0] - hourly_point)))
    lf = pd.DataFrame(losses)
    lf.to_csv(output / "guidance_paired_snapshot_scores.csv", index=False)
    results = []
    if len(lf):
        for (stratum, variant, time_bucket), group in lf.groupby(["stratum", "variant", "bucket"], observed=True):
            c = cells(group, ["candidate_loss", "model_loss", "market_loss", "market_normalized_loss"], ["hour"])
            c["delta_market"] = c.candidate_loss-c.market_loss
            c["delta_model"] = c.candidate_loss-c.model_loss
            results.append({"stratum": stratum, "variant": variant, "bucket": time_bucket,
                            "snapshots": len(group), "candidate": summary(c, "candidate_loss"),
                            "vs_market": summary(c, "delta_market", alternative=.01),
                            "vs_model": summary(c, "delta_model", alternative=.01),
                            "ratio_market": summary(c, "candidate_loss", "market_loss", null=1.1, alternative=.1),
                            "ratio_market_normalized": summary(c, "candidate_loss", "market_normalized_loss", null=1.1, alternative=.1)})
    return {"coverage": coverage, "paired_comparisons": results,
            "kernel": "empirical residuals on >=5 earlier dates, per market, stratum and bucket; no same-date fit",
            "invalid_nbm_note": "Complete field coverage is not successful probability construction; compare paired score support."}
