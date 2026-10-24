"""Lane L3 research: lane B's OLS + hard floor structure as an R0 challenger (US 11).

Offline, weather-only research. Nothing in serving, capture, release or Scheduler
imports this module, and the import itself refuses on the dedicated capture host
(see ``refuse_production_import``).

What it does, per market:

* builds the R0 trainer's own per-cutoff records (same code path as
  ``weather.calibration.feature_model._train_main`` with ``--target-date`` and
  ``--pit-forecast-corpus-manifest``) and its leave-one-year-out splits
  (``feature_blocked_validation_plan``), skipping rows exactly as the trainer does;
* recomputes the trainer's blocked-validation baseline for every row (the parity
  anchor against lane D's ``feature_model_blocked_validation_rows_<market>.jsonl``);
* scores challengers on the same rows as predictive distributions over integer
  native-unit buckets:

  - ``ols_floor``: OLS of the settlement bucket on (forecast_high, high_so_far,
    current_temp), discretised normal, no mass below round_half_up(high_so_far);
  - ``ols_floor_resid_hgb``: the same OLS plus a residual HGB (lane B's
    ``_OlsPlusResidualHgb``, claude/new-cities-m1-round2-20261024), sd from
    out-of-fold residuals by date, the floor applied after the residual;
  - ``bias_corrected_forecast``: forecast plus mean training bias (descriptive).

``compare`` joins the challenger rows with lane D's R0 rows on (hour, date),
checks row-set and baseline parity, and reports per hour and per market with
date-clustered bootstrap CIs and the pre-declared verdict (``C:\\t\\l3\\rule.md``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path


class ChallengerError(RuntimeError):
    """The research run cannot proceed honestly (parity, scope or host)."""


def refuse_production_import(os_name=None, identity=None):
    """Fail closed when imported on the dedicated capture host.

    On Windows the host identity must be provable; if it cannot be read, or it
    matches the tracked capture-host id, the import fails. Non-Windows hosts
    cannot be the capture host (it is a Windows installation). ``identity`` is a
    callable returning ``(host_id, capture_host_id)``; tests inject it.
    """
    if (os.name if os_name is None else os_name) != "nt":
        return
    if identity is None:
        identity = _tracked_identity
    try:
        host_id, capture_id = identity()
    except Exception as exc:  # identity not provable: refuse
        raise ImportError(
            f"r0_ols_floor_challenger refuses to import: host identity not provable ({exc})"
        ) from exc
    if not host_id or not capture_id or host_id == capture_id:
        raise ImportError(
            "r0_ols_floor_challenger is workstation research and refuses to import on "
            "the dedicated capture host (or where that cannot be ruled out)"
        )


def _tracked_identity():
    from weather.execution_host import current_execution_host_id, load_execution_host_assignment

    assignment = load_execution_host_assignment()
    return current_execution_host_id(), assignment["dedicated_capture_execution_host_id"]


refuse_production_import()

ROW_RECORD = "r0_ols_floor_challenger_rows"
SUMMARY_RECORD = "r0_ols_floor_challenger_summary"
RECORD_VERSION = 1
ARMS = (
    "r0_baseline", "ols_floor", "ols_floor_resid_hgb", "bias_corrected_forecast",
    "r0_repro", "r0_floor", "r0_floor_served", "r0_baseline_floor", "bias_corrected_forecast_floor",
)
# Arms whose distributions this module builds on the bucket grid (mass exactly 1).
GRID_ARMS = ("ols_floor", "ols_floor_resid_hgb", "bias_corrected_forecast", "bias_corrected_forecast_floor")
SERVED_FLOOR_MULTIPLIER = 1e-6  # model_distribution.distribution_hard_floor_stage
CHALLENGERS = ("ols_floor", "ols_floor_resid_hgb")
PRIMARY_MARKETS = ("atlanta", "austin", "chicago", "dallas", "denver")
SECONDARY_MARKETS = ("houston", "los-angeles", "miami", "nyc", "san-francisco", "seattle")
HEADLINE_HOURS = (7, 8, 9, 10, 11, 12)
SD_FLOOR = 0.3
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261024
PARITY_TOLERANCE = 1e-9
# Lane B's residual-HGB contract (new_city_corpus HGB_PARAMS, FIT_SEED, FIT_CV_FOLDS).
RESID_HGB_PARAMS = {
    "loss": "squared_error", "learning_rate": 0.05, "max_iter": 300, "max_leaf_nodes": 15,
    "min_samples_leaf": 40, "l2_regularization": 1.0, "early_stopping": False,
}
RESID_HGB_SEED = 20261023
RESID_CV_FOLDS = 5
FEATURES = ("forecast_high", "high_so_far", "current_temp")


# ---------------------------------------------------------------- distributions

def _phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bucket_grid(support, floor=None):
    """Contiguous integer grid from min(support, floor) to max(support)."""
    values = [int(b) for b in support]
    lo, hi = min(values), max(values)
    if floor is not None:
        lo = min(lo, int(floor))
        hi = max(hi, int(floor))
    return lo, hi


def discretised_normal(mu, sd, lo, hi, floor=None):
    """P(bucket b) for b in [lo, hi] from a normal on the half-up value.

    Tails beyond the grid fold into its end buckets, so the mass is exactly 1.
    With ``floor`` the normal is truncated at floor - 0.5 and renormalised: no
    bucket below the floor gets mass.
    """
    sd = max(float(sd), SD_FLOOR)
    mu = float(mu)
    start = lo if floor is None else max(lo, int(floor))
    cut = None if floor is None else float(start) - 0.5
    cdf = {}
    for b in range(start, hi + 2):
        cdf[b] = _phi((b - 0.5 - mu) / sd)
    lower = cdf[start] if cut is not None else 0.0
    probs = {}
    for b in range(lo, hi + 1):
        if b < start:
            probs[b] = 0.0
            continue
        left = lower if b == start else cdf[b]
        right = 1.0 if b == hi else cdf[b + 1]
        probs[b] = max(0.0, right - left)
    total = sum(probs.values())
    if total <= 1e-300:
        # The whole normal sits below the floor: all mass on the floor bucket.
        probs = {b: (1.0 if b == start else 0.0) for b in range(lo, hi + 1)}
        total = 1.0
    return {b: p / total for b, p in probs.items()}


def log_loss(probs, actual):
    p = probs.get(int(actual), 0.0)
    p = max(1e-15, min(1.0 - 1e-15, p))
    return -math.log(p)


def brier(probs, actual):
    return sum((p - (1.0 if b == int(actual) else 0.0)) ** 2 for b, p in probs.items()) + (
        0.0 if int(actual) in probs else 1.0
    )


# ---------------------------------------------------------------- fits

def feature_vector(record):
    fc = record.get("forecast_high")
    out = []
    for name in FEATURES:
        value = record.get(name)
        if value is None or (isinstance(value, float) and math.isnan(value)):
            value = fc
        out.append(float(value))
    return out


def _has_forecast(record):
    value = record.get("forecast_high")
    return value is not None and not (isinstance(value, float) and math.isnan(value))


def floor_of(record):
    from weather.units import round_half_up

    value = record.get("high_so_far")
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return round_half_up(value)


def observed_floor_bucket(high_so_far):
    """The hard-floor bucket at a cutoff: round_half_up of the observed high so far.

    ``high_so_far`` is the trainer record's field: the maximum of the market's history
    rows with ``minute_of_day <= cutoff_hour * 60`` (``build_historical_feature_record``).
    Returns None when it is missing.
    """
    return floor_of({"high_so_far": high_so_far})


def apply_hard_floor(probs, floor, multiplier=0.0):
    """Mass below ``floor`` times ``multiplier`` (0: removed), then renormalised.

    ``multiplier=1e-6`` is the served ``distribution_hard_floor_stage``. If no mass
    remains, all of it goes to the floor bucket. ``floor=None`` returns a copy.
    """
    if floor is None:
        return dict(probs)
    out = {int(b): (float(p) * multiplier if int(b) < floor else float(p)) for b, p in probs.items()}
    total = sum(out.values())
    if total <= 1e-300:
        out = {b: 0.0 for b in out}
        out[int(floor)] = 1.0
        return out
    return {b: p / total for b, p in out.items()}


def ols_fit(xs, ys):
    import numpy as np

    x = np.column_stack([np.ones(len(xs)), np.asarray(xs, dtype=float)])
    y = np.asarray(ys, dtype=float)
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    ddof = x.shape[1]
    sd = float(resid.std(ddof=ddof)) if len(y) > ddof else float("nan")
    return beta, sd


def ols_predict(beta, x):
    import numpy as np

    return float(beta[0] + np.dot(beta[1:], np.asarray(x, dtype=float)))


class OlsPlusResidualHgb:
    """OLS mean plus an unconstrained HGB on the OLS training residuals (lane B)."""

    def __init__(self, xs, ys):
        import numpy as np
        from sklearn.ensemble import HistGradientBoostingRegressor

        xs, ys = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
        self.beta, _ = ols_fit(xs, ys)
        self.resid_model = HistGradientBoostingRegressor(
            **RESID_HGB_PARAMS, random_state=RESID_HGB_SEED,
        ).fit(xs, ys - self._ols_mean(xs))

    def _ols_mean(self, xs):
        return self.beta[0] + xs @ self.beta[1:]

    def predict(self, xs):
        import numpy as np

        xs = np.asarray(xs, dtype=float)
        return self._ols_mean(xs) + self.resid_model.predict(xs)


def resid_hgb_with_cv_sd(xs, ys, dates):
    import numpy as np

    xs, ys = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    unique = sorted(set(dates))
    fold_of = {d: i % RESID_CV_FOLDS for i, d in enumerate(unique)}
    folds = np.asarray([fold_of[d] for d in dates])
    resid = np.empty(len(ys))
    for k in range(RESID_CV_FOLDS):
        held = folds == k
        resid[held] = ys[held] - OlsPlusResidualHgb(xs[~held], ys[~held]).predict(xs[held])
    return OlsPlusResidualHgb(xs, ys), float(resid.std(ddof=1))


def fit_fold(train_records):
    """All challenger fits for one (hour, training-fold)."""
    import numpy as np

    usable = [r for r in train_records if _has_forecast(r)]
    xs = [feature_vector(r) for r in usable]
    ys = [float(r["final_bucket"]) for r in usable]
    dates = [str(r["target_date"]) for r in usable]
    beta, sd = ols_fit(xs, ys)
    resid_model, resid_sd = resid_hgb_with_cv_sd(xs, ys, dates)
    bias_resid = [y - float(r["forecast_high"]) for y, r in zip(ys, usable)]
    bias = float(np.mean(bias_resid))
    bias_sd = float(np.std([b - bias for b in bias_resid], ddof=1))
    return {
        "n_train": len(usable),
        "dropped_no_forecast": len(train_records) - len(usable),
        "beta": beta, "ols_sd": sd,
        "resid_model": resid_model, "resid_sd": resid_sd,
        "bias": bias, "bias_sd": bias_sd,
    }


def challenger_distributions(fit, record, support):
    floor = floor_of(record)
    lo, hi = bucket_grid(support, floor)
    x = feature_vector(record)
    ols_mu = ols_predict(fit["beta"], x)
    resid_mu = float(fit["resid_model"].predict([x])[0])
    return {
        "ols_floor": discretised_normal(ols_mu, fit["ols_sd"], lo, hi, floor),
        "ols_floor_resid_hgb": discretised_normal(resid_mu, fit["resid_sd"], lo, hi, floor),
        "bias_corrected_forecast": discretised_normal(
            float(record["forecast_high"]) + fit["bias"], fit["bias_sd"], lo, hi, None
        ),
        "bias_corrected_forecast_floor": discretised_normal(
            float(record["forecast_high"]) + fit["bias"], fit["bias_sd"], lo, hi, floor
        ),
    }, {"ols_mu": ols_mu, "ols_sd": max(fit["ols_sd"], SD_FLOOR), "resid_mu": resid_mu,
        "resid_sd": max(fit["resid_sd"], SD_FLOOR), "floor": floor}


# ---------------------------------------------------------------- R0 rows

def r0_baseline_distribution(model, val_record, train_days, bucket_space, hour):
    """The trainer's blocked-validation baseline, line for line (feature_model._train_main)."""
    from weather.calibration.feature_model import blend, smoothed_dist
    from weather.units import round_half_up

    weights = model.calibrated_weights.get(str(hour)) if model.calibrated_weights else None
    w_int_base = weights.get("w_intraday_base", 0.36) if weights else 0.36
    w_wnd = weights.get("w_wind", 0.14) if weights else 0.14
    w_cld = weights.get("w_cloud", 0.12) if weights else 0.12
    p_clim = smoothed_dist([d["final_bucket"] for d in train_days], bucket_space, alpha=0.10)
    p_intraday = None
    n_intraday = 0
    val_observed_bucket = round_half_up(val_record.get("high_so_far"))
    if val_observed_bucket is not None:
        matching = [d for d in train_days if round_half_up(d["high_so_far"]) == val_observed_bucket]
        n_intraday = len(matching)
        if n_intraday >= 8:
            p_intraday = smoothed_dist([d["final_bucket"] for d in matching], bucket_space, alpha=0.05)
    p_wind = None
    val_wind = val_record.get("wind_group")
    if val_wind:
        matching = [d for d in train_days if d["wind_group"] == val_wind]
        if len(matching) >= 20:
            p_wind = smoothed_dist([d["final_bucket"] for d in matching], bucket_space, alpha=0.10)
    p_cloud = None
    val_cloud = val_record.get("cloud_group")
    if val_cloud:
        matching = [d for d in train_days if d["cloud_group"] == val_cloud]
        if len(matching) >= 20:
            p_cloud = smoothed_dist([d["final_bucket"] for d in matching], bucket_space, alpha=0.10)
    scores = p_clim.copy()
    if p_intraday is not None and n_intraday > 0:
        scores = blend(scores, p_intraday, w_int_base * (n_intraday / (n_intraday + 25)))
    if p_wind is not None:
        scores = blend(scores, p_wind, w_wnd)
    if p_cloud is not None:
        scores = blend(scores, p_cloud, w_cld)
    return scores


class R0Repro:
    """The trainer's per-cutoff R0 HGB path (allowlist ``r0:<market>``), fold by fold."""

    def __init__(self, model, records):
        from weather.calibration import feature_model as fm
        from weather.calibration.feature_column_allowlist import resolve_column_allowlist

        spec = model.spec
        plan = resolve_column_allowlist(
            f"r0:{spec.id}", market_spec=spec,
            known_wind_groups=fm.WIND_GROUPS, known_cloud_groups=fm.CLOUD_GROUPS,
        )
        wind, cloud = list(plan["all_wind_groups"]), list(plan["all_cloud_groups"])
        df, self.feature_cols = fm.feature_model_frame(
            records, wind, cloud, market_spec=spec, column_allowlist=plan,
        )
        numeric, _ = fm.feature_model_columns(wind, cloud, market_spec=spec, column_allowlist=plan)
        self.n_numeric = len(numeric)
        self.X = df[self.feature_cols].copy()
        self.y = df["final_bucket"].copy()
        self.allowlist_sha256 = plan["sha256"]
        self.leaf = fm.HGB_MIN_SAMPLES_LEAF
        self._fm = fm
        self._models = {}

    def distribution(self, train_indices, val_idx, p_clim):
        fm = self._fm
        matrices = fm.fold_local_feature_matrices(
            self.X, list(train_indices), [val_idx], self.feature_cols, self.n_numeric,
        )
        key = tuple(train_indices)
        if key not in self._models:
            hgb = fm.make_feature_hgb()
            hgb.fit(matrices["hgb_train"], self.y.iloc[list(train_indices)])
            self._models[key] = hgb
        hgb = self._models[key]
        raw = hgb.predict_proba(matrices["hgb_validation"])[0]
        prob = {int(c): float(p) for c, p in zip(hgb.classes_, raw)}
        return fm.blend(p_clim.copy(), prob, 0.80)


def build_r0_records(market_id, target_date, manifests):
    """The R0 trainer's records, bucket space and model for one market."""
    from weather.calibration import feature_model as fm
    from weather.calibration.feature_model_training_inputs import (
        PITForecastCorpusUnion,
        select_training_days,
    )
    from weather.model.toronto_model import INTRADAY_CUTOFF_HOURS, TorontoHighTempModel

    model = TorontoHighTempModel(market_id=market_id, target_date=target_date)
    union = PITForecastCorpusUnion(
        list(manifests), model.spec.id, target_year=target_date.year,
        required_cutoff_hours=INTRADAY_CUTOFF_HOURS,
    )
    cache = model.historical_target_cache()
    daily, day_counts = select_training_days(
        cache["daily"], forecast_years=union.years, target_date=target_date,
    )
    raw = fm.build_feature_records_for_model(
        model, daily, cache["by_date"], None, None, forecast_resolver=union,
    )
    return {
        "model": model,
        "records": raw,
        "bucket_space": cache["bucket_space"],
        "day_counts": day_counts,
        "corpus_ids": [row["corpus_id"] for row in union.corpora],
        "unit": model.spec.unit,
    }


def score_market(market_id, target_date, manifests):
    """Per-row losses of every arm on exactly the trainer's blocked-validation rows."""
    from weather.calibration.feature_model import feature_blocked_validation_plan, smoothed_dist

    built = build_r0_records(market_id, target_date, manifests)
    model, raw, support = built["model"], built["records"], built["bucket_space"]
    rows = []
    stats = {"floor_above_label": 0, "fallback_no_forecast": 0, "dropped_train_no_forecast": 0}
    for hour in sorted(raw):
        records = raw[hour]
        if not records:
            continue
        plan = feature_blocked_validation_plan(records)
        train_by_val = plan["train_indices_by_validation_index"]
        repro = R0Repro(model, records)
        stats["r0_allowlist_sha256"] = repro.allowlist_sha256
        stats["r0_hgb_min_samples_leaf"] = repro.leaf
        fits = {}
        for val_idx, record in enumerate(records):
            train_indices = train_by_val.get(val_idx) or []
            if not train_indices or len({records[i]["final_bucket"] for i in train_indices}) < 2:
                continue  # the trainer skips this row too
            key = tuple(train_indices)
            train_days = [records[i] for i in train_indices]
            if key not in fits:
                fits[key] = fit_fold(train_days)
                stats["dropped_train_no_forecast"] += fits[key]["dropped_no_forecast"]
            actual = int(record["final_bucket"])
            base = r0_baseline_distribution(model, record, train_days, support, hour)
            floor = floor_of(record)
            p_clim = smoothed_dist([d["final_bucket"] for d in train_days], support, alpha=0.10)
            r0 = repro.distribution(train_indices, val_idx, p_clim)
            dists = {
                "r0_baseline": base,
                "r0_repro": r0,
                "r0_floor": apply_hard_floor(r0, floor),
                "r0_floor_served": apply_hard_floor(r0, floor, SERVED_FLOOR_MULTIPLIER),
                "r0_baseline_floor": apply_hard_floor(base, floor),
            }
            detail = {}
            if _has_forecast(record):
                challenger, detail = challenger_distributions(fits[key], record, support)
                dists.update(challenger)
            else:
                stats["fallback_no_forecast"] += 1
                for arm in GRID_ARMS:
                    dists[arm] = base
            if floor is not None and floor > actual:
                stats["floor_above_label"] += 1
            row = {
                "market_id": market_id,
                "hour": int(hour),
                "validation_date": str(record["target_date"]),
                "validation_year": int(str(record["target_date"])[:4]),
                "actual": actual,
                "floor": floor,
                "forecast_high": record.get("forecast_high"),
                "high_so_far": record.get("high_so_far"),
            }
            row.update({k: (None if v is None else round(float(v), 6)) for k, v in detail.items() if k != "floor"})
            for arm, probs in dists.items():
                row[f"{arm}_log_loss"] = log_loss(probs, actual)
                row[f"{arm}_brier"] = brier(probs, actual)
                row[f"{arm}_mass"] = round(sum(probs.values()), 12)
            rows.append(row)
    meta = {
        "market_id": market_id,
        "target_date": target_date.isoformat(),
        "unit": built["unit"],
        "corpus_ids": built["corpus_ids"],
        "day_counts": built["day_counts"],
        "n_rows": len(rows),
        **stats,
    }
    return rows, meta


# ---------------------------------------------------------------- comparison

def read_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


LANE_D_FLOORED = "r0_floored_lane_d"


def join_r0(rows, r0_rows):
    """Attach lane D's per-row R0 losses; refuse on any row-set or baseline mismatch.

    Adds ``r0_*`` (raw R0) and, when lane D's rows carry them, ``r0_floored_lane_d_*``.
    Returns the joined rows and a parity record (baseline, R0-repro and floored R0).
    """
    mine = {(int(r["hour"]), str(r["validation_date"])): r for r in rows}
    theirs = {(int(r["hour"]), str(r["validation_date"])): r for r in r0_rows}
    if set(mine) != set(theirs):
        only_mine = sorted(set(mine) - set(theirs))[:5]
        only_theirs = sorted(set(theirs) - set(mine))[:5]
        raise ChallengerError(
            f"row sets differ: {len(set(mine) - set(theirs))} only here {only_mine}, "
            f"{len(set(theirs) - set(mine))} only in R0 {only_theirs}"
        )
    parity = {"max_baseline_abs_diff": 0.0, "max_r0_repro_abs_diff": None,
              "lane_d_floored": bool(r0_rows) and all("hgb_floored_log_loss" in r for r in r0_rows),
              "max_floored_vs_zero_floor_abs_diff": None, "max_floored_vs_served_floor_abs_diff": None}

    def track(name, value):
        parity[name] = value if parity[name] is None else max(parity[name], value)

    out = []
    for key in sorted(mine):
        a, b = mine[key], theirs[key]
        parity["max_baseline_abs_diff"] = max(
            parity["max_baseline_abs_diff"],
            abs(float(a["r0_baseline_log_loss"]) - float(b["baseline_log_loss"])),
        )
        joined = dict(a)
        joined["r0_log_loss"] = float(b["hgb_log_loss"])
        joined["r0_brier"] = float(b["hgb_brier"])
        if "r0_repro_log_loss" in a:
            track("max_r0_repro_abs_diff", abs(float(a["r0_repro_log_loss"]) - float(b["hgb_log_loss"])))
        if parity["lane_d_floored"]:
            joined[f"{LANE_D_FLOORED}_log_loss"] = float(b["hgb_floored_log_loss"])
            joined[f"{LANE_D_FLOORED}_brier"] = float(b.get("hgb_floored_brier", float("nan")))
            if "r0_floor_log_loss" in a:
                track("max_floored_vs_zero_floor_abs_diff",
                      abs(float(a["r0_floor_log_loss"]) - float(b["hgb_floored_log_loss"])))
                track("max_floored_vs_served_floor_abs_diff",
                      abs(float(a["r0_floor_served_log_loss"]) - float(b["hgb_floored_log_loss"])))
        out.append(joined)
    if parity["max_baseline_abs_diff"] > PARITY_TOLERANCE:
        raise ChallengerError(
            f"baseline parity fails: max |diff| {parity['max_baseline_abs_diff']:.3g} > {PARITY_TOLERANCE}"
        )
    parity["r0_repro_ok"] = (
        parity["max_r0_repro_abs_diff"] is not None and parity["max_r0_repro_abs_diff"] <= PARITY_TOLERANCE
    )
    return out, parity


def _date_matrix(rows_by_market, arm, ref, metric, hours):
    """Per market: {date: mean over the date's rows in ``hours`` of (arm - ref)}."""
    out = {}
    for market, rows in rows_by_market.items():
        acc = defaultdict(list)
        for r in rows:
            if int(r["hour"]) in hours:
                acc[r["validation_date"]].append(r[f"{arm}_{metric}"] - r[f"{ref}_{metric}"])
        out[market] = {d: (sum(v) / len(v), len(v)) for d, v in acc.items()}
    return out


def bootstrap_delta(rows_by_market, arm, ref, metric, hours, *, crossed=False):
    """Equal-weight market mean of row-mean deltas; date-clustered (or crossed) CI.

    A market's delta is the mean over its rows (the date mean weighted by row
    count); a draw resamples validation dates jointly across markets, and in the
    crossed variant also resamples markets.
    """
    import numpy as np

    per = _date_matrix(rows_by_market, arm, ref, metric, hours)
    markets = sorted(m for m in per if per[m])
    dates = sorted({d for m in markets for d in per[m]})
    if not markets or not dates:
        return None
    idx = {d: i for i, d in enumerate(dates)}
    sums = np.zeros((len(markets), len(dates)))
    counts = np.zeros((len(markets), len(dates)))
    for j, m in enumerate(markets):
        for d, (mean, n) in per[m].items():
            sums[j, idx[d]] = mean * n
            counts[j, idx[d]] = n
    market_means = sums.sum(axis=1) / counts.sum(axis=1)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = rng.integers(0, len(dates), size=(BOOTSTRAP_DRAWS, len(dates)))
    weights = np.zeros((BOOTSTRAP_DRAWS, len(dates)))
    for k in range(BOOTSTRAP_DRAWS):
        weights[k] = np.bincount(draws[k], minlength=len(dates))
    boot_sums = weights @ sums.T  # draws x markets
    boot_counts = weights @ counts.T
    with np.errstate(invalid="ignore", divide="ignore"):
        boot_market = boot_sums / boot_counts
    per_market = {}
    for j, m in enumerate(markets):
        col = boot_market[:, j]
        col = col[np.isfinite(col)]
        lo, hi = np.percentile(col, [2.5, 97.5])
        per_market[m] = {
            "delta": float(market_means[j]), "ci95": [float(lo), float(hi)],
            "n_rows": int(counts[j].sum()), "n_dates": int((counts[j] > 0).sum()),
        }
    if crossed:
        mrng = np.random.default_rng(BOOTSTRAP_SEED + 1)
        mdraws = mrng.integers(0, len(markets), size=(BOOTSTRAP_DRAWS, len(markets)))
        pooled_boot = np.array([np.nanmean(boot_market[k, mdraws[k]]) for k in range(BOOTSTRAP_DRAWS)])
    else:
        pooled_boot = np.nanmean(boot_market, axis=1)
    lo, hi = np.percentile(pooled_boot, [2.5, 97.5])
    return {
        "pooled": {"delta": float(market_means.mean()), "ci95": [float(lo), float(hi)],
                   "n_markets": len(markets), "n_dates": len(dates)},
        "per_market": per_market,
    }


def mean_loss(rows_by_market, arm, metric, hours):
    means = []
    for rows in rows_by_market.values():
        vals = [r[f"{arm}_{metric}"] for r in rows if int(r["hour"]) in hours]
        if vals:
            means.append(sum(vals) / len(vals))
    return sum(means) / len(means) if means else None


def verdict(result):
    pooled = result["pooled"]
    no_market_worse = all(v["ci95"][0] <= 0 for v in result["per_market"].values())
    return bool(pooled["delta"] < 0 and pooled["ci95"][1] < 0 and no_market_worse)


REPORT_ARMS = (
    "ols_floor", "ols_floor_resid_hgb", "bias_corrected_forecast_floor", "bias_corrected_forecast",
    "r0_floored_lane_d", "r0_floor", "r0_floor_served", "r0_baseline_floor", "r0_baseline", "r0",
)


def compare(rows_by_market, *, reference, markets, required_markets, label="", decisive=True):
    """Each challenger against ``reference`` under the pre-declared two criteria."""
    scoped = {m: rows_by_market[m] for m in markets
              if m in rows_by_market and rows_by_market[m]
              and f"{reference}_log_loss" in rows_by_market[m][0]}
    if not scoped:
        return None
    complete = set(required_markets) <= set(scoped)
    hours_all = sorted({int(r["hour"]) for rows in scoped.values() for r in rows})
    present = set.intersection(*(set(rows[0]) for rows in scoped.values()))
    arms = [a for a in REPORT_ARMS if a != reference and f"{a}_log_loss" in present]
    out = {"label": label, "reference": reference, "markets": sorted(scoped), "complete": complete,
           "decisive": decisive, "headline": {}, "per_hour": {}, "mean_loss": {}}
    for arm in arms + [reference]:
        out["mean_loss"][arm] = {
            metric: mean_loss(scoped, arm, metric, HEADLINE_HOURS) for metric in ("log_loss", "brier")
        }
    for arm in arms:
        head = {}
        for metric in ("log_loss", "brier"):
            head[metric] = bootstrap_delta(scoped, arm, reference, metric, HEADLINE_HOURS)
        head["log_loss_crossed"] = bootstrap_delta(
            scoped, arm, reference, "log_loss", HEADLINE_HOURS, crossed=True
        )["pooled"]
        head["passes_two_criteria"] = verdict(head["log_loss"]) if complete else None
        out["headline"][arm] = head
        out["per_hour"][arm] = {
            str(h): {metric: bootstrap_delta(scoped, arm, reference, metric, (h,))["pooled"]
                     for metric in ("log_loss", "brier")}
            for h in hours_all
        }
    contenders = [a for a in CHALLENGERS if a in out["headline"]]
    winners = [a for a in contenders if out["headline"][a]["passes_two_criteria"]]
    if not complete:
        out["verdict"] = "PROVISIONAL (not every required market has rows)"
    elif not winners:
        out["verdict"] = f"no challenger passes against {reference}"
    else:
        best = min(winners, key=lambda a: (out["headline"][a]["log_loss"]["pooled"]["delta"],
                                           CHALLENGERS.index(a)))
        out["verdict"] = f"{best} passes against {reference}"
    return out


# ---------------------------------------------------------------- report

def _fmt(entry):
    lo, hi = entry["ci95"]
    return f"{entry['delta']:+.3f} [{lo:+.3f}, {hi:+.3f}]"


def markdown_report(summary):
    lines = []
    for block in summary["comparisons"]:
        ref = block["reference"]
        lines.append(f"## {block['label']}: against `{ref}` ({', '.join(block['markets'])}) - {block['verdict']}\n")
        lines.append("07-12 mean loss across markets (equal weight):\n")
        lines.append("| arm | log loss | Brier |")
        lines.append("| --- | --- | --- |")
        for arm, vals in block["mean_loss"].items():
            ll, br = vals["log_loss"], vals["brier"]
            lines.append(f"| {arm} | {ll:.4f} | {br:.4f} |")
        lines.append("")
        lines.append(f"07-12 delta vs `{ref}` (negative is better), date-clustered 95% CI:\n")
        lines.append("| arm | market | log loss | Brier |")
        lines.append("| --- | --- | --- | --- |")
        for arm, head in block["headline"].items():
            lines.append(f"| {arm} | **pooled** | {_fmt(head['log_loss']['pooled'])} | "
                         f"{_fmt(head['brier']['pooled'])} |")
            for market in sorted(head["log_loss"]["per_market"]):
                lines.append(f"| {arm} | {market} | {_fmt(head['log_loss']['per_market'][market])} | "
                             f"{_fmt(head['brier']['per_market'][market])} |")
            lines.append(f"| {arm} | pooled, crossed date x market CI | "
                         f"{_fmt(head['log_loss_crossed'])} | |")
        lines.append("")
        lines.append(f"Per hour, pooled delta vs `{ref}` (log loss; Brier):\n")
        arms = list(block["per_hour"])
        lines.append("| hour | " + " | ".join(arms) + " |")
        lines.append("| --- |" + " --- |" * len(arms))
        for hour in sorted(block["per_hour"][arms[0]], key=int):
            cells = []
            for arm in arms:
                cell = block["per_hour"][arm][hour]
                cells.append(f"{_fmt(cell['log_loss'])}; {cell['brier']['delta']:+.3f}")
            label = f"**{int(hour):02d}**" if int(hour) in (7, 12) else f"{int(hour):02d}"
            lines.append(f"| {label} | " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI

def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _score_command(args):
    target = date.fromisoformat(args.target_date)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for market in args.markets.split(","):
        rows, meta = score_market(market, target, args.pit_forecast_corpus_manifest)
        last = max(r["validation_date"] for r in rows) if rows else None
        if last and last > "2025-12-31":
            raise ChallengerError(f"{market}: a validation date after 2025-12-31 ({last})")
        rows_path = out_dir / f"challenger_rows_{market}.jsonl"
        with open(rows_path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        meta.update({"record": ROW_RECORD, "record_version": RECORD_VERSION,
                     "rows_sha256": _sha256(rows_path),
                     "manifests": list(args.pit_forecast_corpus_manifest)})
        (out_dir / f"challenger_meta_{market}.json").write_text(
            json.dumps(meta, indent=1, sort_keys=True), encoding="utf-8")
        print(f"{market}: {meta['n_rows']} rows, floor>label {meta['floor_above_label']}, "
              f"fallback {meta['fallback_no_forecast']}")
    return 0


def _compare_command(args):
    rows_dir = Path(args.rows_dir)
    rows_by_market = {}
    parity = {}
    for path in sorted(rows_dir.glob("challenger_rows_*.jsonl")):
        market = path.stem[len("challenger_rows_"):]
        rows_by_market[market] = read_jsonl(path)
    for market, rows in rows_by_market.items():
        bad = [r for r in rows if any(
            f"{a}_mass" in r and abs(r[f"{a}_mass"] - 1.0) > 1e-9 for a in ARMS)]
        if bad:
            raise ChallengerError(f"{market}: {len(bad)} rows whose mass is not 1")
    r0_joined = {}
    for spec in args.r0_rows or []:
        market, _, path = spec.partition("=")
        if market not in rows_by_market:
            raise ChallengerError(f"no challenger rows for {market}")
        joined, record = join_r0(rows_by_market[market], read_jsonl(path))
        r0_joined[market] = joined
        parity[market] = dict(record, n_rows=len(joined), r0_rows_sha256=_sha256(path), r0_rows_path=path)
    repro_ok = {m: rows for m, rows in rows_by_market.items() if parity.get(m, {}).get("r0_repro_ok")}
    plan = (
        ("VERDICT (rule clarification 2)", r0_joined, LANE_D_FLOORED, PRIMARY_MARKETS, True),
        ("CONTROL floor + forecast", rows_by_market, "bias_corrected_forecast_floor", PRIMARY_MARKETS, True),
        ("CONTROL own R0-repro + floor (repro parity passed)", repro_ok, "r0_floor", PRIMARY_MARKETS, False),
        ("DESCRIPTIVE raw R0", r0_joined, "r0", PRIMARY_MARKETS, False),
        ("SECONDARY (other six) vs baseline", rows_by_market, "r0_baseline", SECONDARY_MARKETS, True),
        ("DESCRIPTIVE other six vs floor + forecast", rows_by_market, "bias_corrected_forecast_floor",
         SECONDARY_MARKETS, False),
        ("DESCRIPTIVE other six vs own R0-repro + floor", rows_by_market, "r0_floor", SECONDARY_MARKETS, False),
    )
    comparisons = [c for c in (
        compare(rows, reference=ref, markets=markets, required_markets=markets, label=label, decisive=decisive)
        for label, rows, ref, markets, decisive in plan
    ) if c is not None]
    summary = {
        "record": SUMMARY_RECORD, "record_version": RECORD_VERSION,
        "rule_sha256": _sha256(args.rule) if args.rule else None,
        "parity": parity,
        "row_files": {m: _sha256(rows_dir / f"challenger_rows_{m}.jsonl") for m in rows_by_market},
        "bootstrap": {"draws": BOOTSTRAP_DRAWS, "seed": BOOTSTRAP_SEED,
                      "cluster": "validation date, jointly across markets"},
        "comparisons": comparisons,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=1, sort_keys=True), encoding="utf-8")
    out.with_suffix(".md").write_text(markdown_report(summary), encoding="utf-8")
    print(json.dumps(parity, indent=1, sort_keys=True))
    print(markdown_report(summary))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.r0_ols_floor_challenger")
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score", help="score every arm on the R0 trainer's blocked rows")
    score.add_argument("--markets", required=True)
    score.add_argument("--target-date", required=True)
    score.add_argument("--pit-forecast-corpus-manifest", action="append", required=True)
    score.add_argument("--out-dir", required=True)
    cmp_ = sub.add_parser("compare", help="join with lane D's R0 rows and apply the rule")
    cmp_.add_argument("--rows-dir", required=True)
    cmp_.add_argument("--r0-rows", action="append", help="<market>=<feature_model_blocked_validation_rows path>")
    cmp_.add_argument("--rule", default=None)
    cmp_.add_argument("--out", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "score":
            return _score_command(args)
        return _compare_command(args)
    except ChallengerError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
