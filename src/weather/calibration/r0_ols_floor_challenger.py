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
ALL_MARKETS = PRIMARY_MARKETS + SECONDARY_MARKETS
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

def feature_vector(record, features=FEATURES):
    fc = record.get("forecast_high")
    out = []
    for name in features:
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


def fit_fold(train_records, features=FEATURES):
    """All challenger fits for one (hour, training-fold)."""
    import numpy as np

    usable = [r for r in train_records if _has_forecast(r)]
    xs = [feature_vector(r, features) for r in usable]
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
        "bias": bias, "bias_sd": bias_sd, "features": tuple(features),
    }


def challenger_distributions(fit, record, support):
    floor = floor_of(record)
    lo, hi = bucket_grid(support, floor)
    x = feature_vector(record, fit.get("features", FEATURES))
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


# ---------------------------------------------------------------- dev window (end-to-end vs served)

DEV_FIRST = date(2026, 7, 30)
DEV_LAST = date(2026, 9, 29)
DEV_ARMS = ("ols_floor", "ols_floor_resid_hgb", "bias_corrected_forecast_floor")
DEV_VARIANTS = {
    # name: (features, forecast source)
    "main": (FEATURES, "pit_2026"),
    "served_forecast": (FEATURES, "layout_served"),
    "two_feature": (("forecast_high", "high_so_far"), "pit_2026"),
    # dev_rule.md clarification 1: high_so_far (and so the floor) from lane L8's shared serve-time
    # function weather.model.observed_running_max.running_max_since_midnight (imported, not rewritten).
    "l8_high_so_far": (FEATURES, "pit_2026"),
    # dev_rule.md clarification 4: arm A' = arm A (L8 high_so_far) plus the NBM mean, fitted on the historical
    # rows with lane L9's PIT NBM corpus (L9's loader, imported), scored with the captured v2 mean MG-1 uses.
    "nbm_hist": (FEATURES + ("nbm_mean",), "pit_2026"),
    # MG-2 pick rule clarification 2: arm A_N (L9's N2 recipe), forecast_high replaced by the captured NBM 07Z mean;
    # trained on L9's PIT NBM corpus, served with the captured v2 mean; a dev snapshot without it is not emitted.
    "nbm_n2": (("nbm_mean", "high_so_far", "current_temp"), "captured_nbm"),
}
DEV_DEFAULT_VARIANTS = ("main", "served_forecast", "two_feature")
L8_VARIANT = "l8_high_so_far"
NBM_VARIANT = "nbm_hist"
N2_VARIANT = "nbm_n2"
NBM_VARIANTS = (NBM_VARIANT, N2_VARIANT)
_CAPTURED_LOCAL = None
_METAR_TIME = None


def metar_observation_instant(row, tz):
    """Observation instant of a captured METAR row: the raw DDHHMMZ group, else ``datetime``.

    The v3 parser's ``datetime`` is AWC's nominal report hour (a :52 report reads as the
    next hour), so the raw group is preferred (AGENT_CONTEXT, metar-parser-v4 semantics).
    """
    import re
    from datetime import datetime, timedelta, timezone

    global _METAR_TIME
    if _METAR_TIME is None:
        _METAR_TIME = re.compile(r"\b(\d{2})(\d{2})(\d{2})Z\b")
    nominal = row.get("datetime")
    nominal_dt = datetime.fromisoformat(nominal) if nominal else None
    match = _METAR_TIME.search(str(row.get("raw") or ""))
    if match and nominal_dt is not None:
        day, hour, minute = (int(g) for g in match.groups())
        anchor = nominal_dt.astimezone(timezone.utc)
        best = None
        for shift in (-1, 0, 1):  # the DD group may sit in the previous or next UTC month day
            base = (anchor + timedelta(days=shift)).replace(hour=0, minute=0, second=0, microsecond=0)
            if base.day != day:
                continue
            cand = base.replace(hour=hour, minute=minute)
            if best is None or abs(cand - anchor) < abs(best - anchor):
                best = cand
        if best is not None and abs(best - anchor) <= timedelta(hours=3):
            return best.astimezone(tz), "raw_ddhhmmz"
    if nominal_dt is not None:
        return nominal_dt.astimezone(tz), "nominal_datetime"
    return None, "missing"


def observations_at_cutoff(rows, target_date, cutoff_hour, tz):
    """(current_temp, high_so_far, n) from METAR rows of ``target_date`` observed at or before h:00.

    Same semantics as the trainer's ``build_historical_feature_record``: rows of the local
    target date with observation minute <= cutoff_hour * 60; current = the latest such row.
    """
    from datetime import datetime, time

    cutoff = datetime.combine(target_date, time(int(cutoff_hour), 0), tzinfo=tz)
    kept = {}
    for row in rows or []:
        temp = row.get("temp_native")
        if temp is None:
            continue
        instant, _ = metar_observation_instant(row, tz)
        if instant is None or instant.date() != target_date or instant > cutoff:
            continue
        kept[instant] = float(temp)  # one value per observation instant (corrections overwrite)
    if not kept:
        return None, None, 0
    latest = max(kept)
    return kept[latest], max(kept.values()), len(kept)


def scan_replay_observations(folder, market_id, target_date, tz, hours, unit=None):
    """Per cutoff hour, METAR features from the last replay snapshot captured in [h:00, h+1:00).

    Only that snapshot's ``sources.metar.data.rows`` are read; rows are kept only when observed
    at or before h:00 (so at or before the snapshot). Returns {hour: record}.
    With ``unit``, also ``high_so_far_l8``: lane L8's ``running_max_since_midnight`` on the same
    snapshot's ``sources.station.data`` and ``sources.metar.data`` (cutoff h, now = capture time).
    """
    import re
    from datetime import datetime

    global _CAPTURED_LOCAL
    if _CAPTURED_LOCAL is None:
        _CAPTURED_LOCAL = re.compile(r'"captured_at_local":\s*"([^"]+)"')
    path = Path(folder) / "replay_inputs.jsonl"
    chosen = {}
    with open(path, "rb") as handle:
        offset = 0
        for line in handle:
            match = _CAPTURED_LOCAL.search(line[:4096].decode("utf-8", "replace"))
            if match:
                local = datetime.fromisoformat(match.group(1)).astimezone(tz)
                if local.date() == target_date and local.hour in hours:
                    chosen[local.hour] = (local, offset, len(line))
            offset += len(line)
        out = {}
        for hour, (local, start, size) in sorted(chosen.items()):
            handle.seek(start)
            snapshot = json.loads(handle.read(size))
            sources = snapshot.get("sources") or {}
            metar = (sources.get("metar") or {}).get("data") or {}
            current, high, n = observations_at_cutoff(metar.get("rows"), target_date, hour, tz)
            out[hour] = {"market": market_id, "target_date": target_date.isoformat(), "hour": hour,
                         "replay_snapshot_id": snapshot.get("snapshot_id"),
                         "replay_captured_at_local": local.isoformat(),
                         "current_temp": current, "high_so_far": high, "n_rows": n}
            if unit is not None:
                from weather.model.observed_running_max import running_max_since_midnight

                station = (sources.get("station") or {}).get("data") or {}
                value, first = running_max_since_midnight(
                    station, metar, target_date=target_date, tz=tz, unit=unit, cutoff_hour=hour, now=local)
                out[hour]["high_so_far_l8"] = value
                out[hour]["high_so_far_l8_first_minute"] = first
    return out


def _event_folders(replay_root):
    import re

    pattern = re.compile(r"^highest-temperature-in-(.+)-on-([a-z]+)-(\d+)-(\d{4})$")
    months = {m: i for i, m in enumerate(
        ("january", "february", "march", "april", "may", "june", "july", "august", "september",
         "october", "november", "december"), start=1)}
    for folder in sorted(Path(replay_root, "snapshots").iterdir()):
        match = pattern.match(folder.name)
        if not match:
            continue
        slug, month, day, year = match.groups()
        yield slug, date(int(year), months[month], int(day)), folder


def dev_emit(*, layout, replay_root, train_manifests, dev_manifest, out_dir, markets,
             variants=DEV_DEFAULT_VARIANTS, obs_from=None, nbm_corpus=None):
    """Fit on the Aug-Sep 2021-25 corpus, emit candidate distributions for the dev snapshots.

    ``obs_from``: a previous run's ``dev_features.jsonl`` (same replay scan) instead of rescanning;
    refused for the ``l8_high_so_far`` variant unless its rows carry ``high_so_far_l8``.
    ``nbm_corpus``: lane L9's ``nbm_pit_corpus_rows.jsonl``, required by the ``nbm_hist`` variant.
    """
    import pandas as pd
    from zoneinfo import ZoneInfo

    from weather.calibration.feature_model_training_inputs import PITForecastCorpusUnion
    from weather.market.market_registry import spec_for_id
    from weather.model.toronto_model import INTRADAY_CUTOFF_HOURS

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    snaps = pd.read_parquet(Path(layout) / "inputs_snapshots.parquet", columns=[
        "snapshot_id", "market", "target_date", "local_hour", "cutoff_hour", "forecast_high", "high_so_far"])
    if (pd.to_datetime(snaps.target_date).dt.date > DEV_LAST).any():
        raise ChallengerError("layout holds a snapshot after 2026-09-29")
    hours = set(int(h) for h in INTRADAY_CUTOFF_HOURS)
    variants = tuple(variants)
    unknown = [v for v in variants if v not in DEV_VARIANTS]
    if unknown:
        raise ChallengerError(f"unknown dev variants {unknown}")
    want_nbm = any(v in variants for v in NBM_VARIANTS)
    want_l8 = L8_VARIANT in variants or want_nbm
    nbm_table = None
    if want_nbm:
        if nbm_corpus is None:
            raise ChallengerError("the NBM variants need --nbm-corpus")
        from weather.calibration import ols_floor_ladder

        nbm_table = ols_floor_ladder.load_nbm(nbm_corpus)
        snaps = snaps.join(pd.read_parquet(Path(layout) / "inputs_snapshots.parquet", columns=[
            "v2_mean", "v2_stddev", "v2_available_at", "captured_at_utc"]))
        from weather.calibration.r0_ols_floor_devfit import usable_v2_mean

        snaps["nbm_usable"] = usable_v2_mean(snaps)
    audit = {"markets": {}, "variants": {k: {"features": list(DEV_VARIANTS[k][0]), "forecast": DEV_VARIANTS[k][1]}
                                         for k in variants}}
    if want_nbm:
        audit["nbm_corpus"] = {"path": str(nbm_corpus), "sha256": _sha256(nbm_corpus),
                               "loader": ols_floor_ladder.__name__,
                               "loader_sha256": _sha256(ols_floor_ladder.__file__)}
    if want_l8:
        from weather.model import observed_running_max

        audit["l8_function"] = {"module": observed_running_max.__name__,
                                "sha256": _sha256(observed_running_max.__file__)}
    stored_obs = defaultdict(dict)
    if obs_from is not None:
        for rec in read_jsonl(obs_from):
            stored_obs[rec["market"]][(rec["target_date"], int(rec["hour"]))] = rec
        audit["obs_from"] = {"path": str(obs_from), "sha256": _sha256(obs_from)}
    writers = {(arm, variant): open(out / f"dev_{variant}_{arm}.jsonl", "w", encoding="utf-8")
               for arm in DEV_ARMS for variant in variants}
    feature_rows = []
    try:
        for market in markets:
            spec = spec_for_id(market)
            tz = ZoneInfo(spec.timezone)
            built = build_r0_records(market, date(2026, 9, 7), train_manifests)
            support = built["bucket_space"]
            fits = {}
            for hour, records in built["records"].items():
                if want_nbm:
                    for r in records:
                        value, cycle = ols_floor_ladder.nbm_at_cutoff(
                            nbm_table, market, str(r["target_date"])[:10], hour, spec.timezone)
                        r["nbm_mean"] = value  # None: imputed with forecast_high by feature_vector
                        key = f"train_nbm_cycle_{cycle}" if cycle else "train_nbm_missing"
                        audit.setdefault("nbm_train", {}).setdefault(market, defaultdict(int))[key] += 1
                for variant in variants:
                    fits[(hour, variant)] = fit_fold(records, DEV_VARIANTS[variant][0])
            dev_union = PITForecastCorpusUnion([dev_manifest], spec.id, target_year=2027,
                                               required_cutoff_hours=INTRADAY_CUTOFF_HOURS)
            obs = {}
            if obs_from is not None:
                obs = dict(stored_obs.get(market, {}))
                if want_l8 and any("high_so_far_l8" not in rec for rec in obs.values()):
                    raise ChallengerError("--obs-from rows lack high_so_far_l8; rescan for the L8 variant")
            else:
                unit = spec.display_unit if want_l8 else None
                for slug, target, folder in _event_folders(replay_root):
                    if not (DEV_FIRST <= target <= DEV_LAST) or slug != market:
                        continue
                    for hour, rec in scan_replay_observations(folder, market, target, tz, hours,
                                                              unit=unit).items():
                        obs[(target.isoformat(), hour)] = rec
            stats = defaultdict(int)
            msnaps = snaps[snaps.market == market]
            for row in msnaps.itertuples(index=False):
                try:
                    hour = int(str(row.cutoff_hour))
                except ValueError:
                    hour = None
                if hour not in hours:
                    stats["outside_cutoff_hours"] += 1
                    continue
                if int(row.local_hour) < hour:
                    # e.g. a 03:00 snapshot served at effective cutoff 07: the features at 07:00
                    # would use later observations, so it is not emitted (served fallback).
                    stats["local_hour_before_cutoff"] += 1
                    continue
                key = (str(row.target_date)[:10], hour)
                rec = obs.get(key)
                if rec is None or (rec["high_so_far"] is None and rec.get("high_so_far_l8") is None):
                    stats["no_replay_observation"] += 1
                    continue
                pit = dev_union.resolve(key[0], hour)["forecast_high"]
                served_fc = None if row.forecast_high != row.forecast_high else float(row.forecast_high)
                for variant in variants:
                    features, source = DEV_VARIANTS[variant]
                    if source == "captured_nbm":
                        nbm = float(row.nbm_usable)
                        fc = nbm if math.isfinite(nbm) else None
                    else:
                        fc = pit if source == "pit_2026" else served_fc
                    if fc is None:
                        stats[f"{variant}_no_forecast"] += 1
                        continue
                    record = {"forecast_high": fc, "high_so_far": rec["high_so_far"],
                              "current_temp": rec["current_temp"]}
                    if variant in NBM_VARIANTS:
                        nbm = float(row.nbm_usable)
                        record["nbm_mean"] = nbm if math.isfinite(nbm) else None
                        if record["nbm_mean"] is None:
                            stats[f"{variant}_nbm_imputed_forecast"] += 1
                    if variant in (L8_VARIANT,) + NBM_VARIANTS:
                        value = rec.get("high_so_far_l8")
                        if value is None:
                            stats[f"{variant}_no_l8_value"] += 1
                            continue
                        if rec["high_so_far"] is None:
                            stats[f"{variant}_main_high_so_far_missing"] += 1
                        elif floor_of({"high_so_far": value}) != floor_of(rec):
                            stats[f"{variant}_floor_differs_from_main"] += 1
                        record["high_so_far"] = value
                    if any(record[f] is None for f in features if f != "nbm_mean"):
                        stats[f"{variant}_missing_feature"] += 1
                        continue
                    dists, _ = challenger_distributions(fits[(hour, variant)], record, support)
                    for arm in DEV_ARMS:
                        writers[(arm, variant)].write(json.dumps({
                            "market": market, "snapshot_id": row.snapshot_id, "target_date": key[0],
                            "distribution": {str(b): p for b, p in dists[arm].items() if p > 0}},
                            sort_keys=True) + "\n")
                    stats[f"{variant}_emitted"] += 1
                layout_hsf = None if row.high_so_far != row.high_so_far else float(row.high_so_far)
                if layout_hsf is not None and rec["high_so_far"] is not None and                         floor_of({"high_so_far": layout_hsf}) != floor_of(rec):
                    stats["floor_differs_from_layout_high_so_far"] += 1
                stats["snapshots_in_cutoff_hours"] += 1
            for (target, hour), rec in sorted(obs.items()):
                try:
                    rec["pit_forecast_high"] = dev_union.resolve(target, hour)["forecast_high"]
                except Exception as exc:  # recorded, never silently filled
                    rec["pit_forecast_error"] = str(exc)
                feature_rows.append(rec)
            audit["markets"][market] = dict(stats, replay_hours=len(obs),
                                            training_corpora=built["corpus_ids"],
                                            training_day_counts=built["day_counts"])
            print(f"{market}: {dict(stats)}", flush=True)
    finally:
        for handle in writers.values():
            handle.close()
    with open(out / "dev_features.jsonl", "w", encoding="utf-8") as handle:
        for rec in feature_rows:
            handle.write(json.dumps(rec, sort_keys=True) + "\n")
    audit["files"] = {path.name: _sha256(path) for path in sorted(out.glob("dev_*.jsonl"))}
    (out / "dev_emit_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True), encoding="utf-8")
    return audit


DEV_GROUPS = (
    ("00-05", 0, 5), ("06-09", 6, 9), ("10-12", 10, 12), ("13-16", 13, 16), ("17-23", 17, 23),
    ("00-16", 0, 16), ("all", 0, 23), ("07-12", 7, 12), ("12-16", 12, 16),
) + tuple((f"h{h:02d}", h, h) for h in range(7, 21))
DEV_STANDARD_BLOCKS = ("00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all")


def _date_weights(dates, draws, seed):
    import numpy as np

    _, di = np.unique(np.asarray(dates), return_inverse=True)
    d = di.max() + 1
    rng = np.random.default_rng(seed)
    return rng.multinomial(d, np.full(d, 1 / d), size=draws)[:, di]


MG1_CONTROL_0712_EXCESS = 0.012  # lane L7 atlas: MG-1 pooled 07-12 excess over market 0.011957
DEV_MG1_GATE_BLOCKS = ("07-12", "06-09", "10-12", "12-16", "13-16", "00-16", "all")
PRIMARY_POOL = "PRIMARY5"


def covered_mask(table, frame):
    """Per snapshot: True where ``Table.candidate_vector`` uses the candidate (not served fallback).

    Mirrors the scorecard's own reason codes; ``_vector`` checks the count against them.
    """
    import numpy as np

    frame = frame[frame.row_key.isin(table.snap_pos.index)]
    pos = table.snap_pos.reindex(frame.row_key.to_numpy()).to_numpy().astype(int)
    given = np.zeros(len(table.bands), dtype=bool)
    pc = np.zeros(len(table.bands))
    flat = table.offsets[pos] + frame.band_index.to_numpy(int)
    given[flat] = True
    pc[flat] = frame.p.to_numpy(float)
    pc[table.impossible] = 0.0
    n_given = np.bincount(table.band_snap, weights=given, minlength=len(table.snaps))
    total = np.bincount(table.band_snap, weights=pc, minlength=len(table.snaps))
    return (n_given == table.n) & table.has_floor & (total > 0)


def _vector(table, frame):
    p, reasons = table.candidate_vector(frame)
    cov = covered_mask(table, frame)
    if int(cov.sum()) != int(reasons.get("candidate", 0)):
        raise ChallengerError(f"coverage mask {int(cov.sum())} != scorecard candidate count {reasons}")
    return p, cov, reasons


def _candidate_frame(source, table, lay, folds, data):
    """``<jsonl>`` (distributions), ``module:<path>`` (walk-forward, the scorecard's own contract) or
    ``builtin:mg1`` (lane L7's ``loss_atlas.mg1_frame``)."""
    if source == "builtin:mg1":
        from weather.reporting.scorecards import loss_atlas

        return loss_atlas.mg1_frame(table), {"kind": "builtin", "name": "mg1",
                                             "loss_atlas_code_sha256": _sha256(loss_atlas.__file__)}
    if source.startswith("module:"):
        spec = data.CandidateSpec("module", source[len("module:"):])
        frame, meta = data.module_predictions(spec, lay, folds)
        meta = dict(meta, kind="module", walk_forward="enforced_fit_per_fold")
        return frame, meta
    spec = data.CandidateSpec("distributions", str(source), "2025-12-31", False)
    return data.distribution_predictions(spec, lay, folds)


def _source_sha(source):
    if source == "builtin:mg1":
        return None
    return _sha256(source[len("module:"):] if source.startswith("module:") else source)


def dev_score(layout, candidates, start="2026-08-01", end="2026-09-29", with_mg1=True, references=None,
              expect_brier_vs_mg1=None):
    """Score candidate distribution files with dev_scorecard's own machinery, unchanged.

    Per candidate, reference (served; MG-1 when ``with_mg1``), scope (blended = every scored
    snapshot with served fallback; covered = the candidate's own snapshots, vs MG-1 those covered
    by both) and group (the scorecard's blocks plus 07-12, 12-16 and each hour 07..20), pooled over
    the 11 markets, over the 5 primary markets and per market: R_candidate, R_reference and
    dR = mean_cell(Brier_c - Brier_ref) / mean_cell(Brier_m), with the scorecard's crossed
    date x market interval and a date-clustered interval (same draws, seed).
    MG-1 is lane L7's ``loss_atlas.mg1_frame``, imported; its 07-12 excess control runs first.
    """
    import numpy as np

    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data

    start_d, end_d = data.check_range(start, end)
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    table = sc.Table(lay, scored)
    date_w = _date_weights([k[0] for k in table.keys], sc.DRAWS, sc.SEED)
    out = {"population": {"n_dates": len(scored), "n_market_days": len(table.keys),
                          "first_date": scored[0], "last_date": scored[-1]},
           "layout_manifest_sha256": lay.manifest_sha256, "scorecard_code_sha256": sc.code_sha256(),
           "candidates": {}}
    market_b = table.brier(table.p_market)
    everything = np.ones(len(table.snaps), dtype=bool)
    refs = {"served": (table.brier(table.p_served), everything)}
    w0712 = (table.local_hour >= 7) & (table.local_hour <= 12)
    if with_mg1:
        from weather.reporting.scorecards import loss_atlas

        p_mg1, cov_mg1, reasons_mg1 = _vector(table, loss_atlas.mg1_frame(table))
        mg1_b = table.brier(p_mg1)
        _, e = table.cells(mg1_b - market_b, w0712)
        excess = float(e.mean())
        out["mg1_control"] = {"source": "weather.reporting.scorecards.loss_atlas.mg1_frame",
                              "loss_atlas_code_sha256": _sha256(loss_atlas.__file__),
                              "excess_over_market_07_12": excess, "expected": MG1_CONTROL_0712_EXCESS,
                              "coverage": reasons_mg1,
                              "passed": round(excess, 3) == MG1_CONTROL_0712_EXCESS}
        if not out["mg1_control"]["passed"]:
            raise ChallengerError(f"MG-1 positive control failed: 07-12 excess {excess:.5f} "
                                  f"does not round to {MG1_CONTROL_0712_EXCESS}")
        refs["mg1"] = (mg1_b, cov_mg1)
    for ref_name, source in (references or {}).items():
        frame, meta = _candidate_frame(source, table, lay, folds, data)
        p_ref, cov_ref, reasons_ref = _vector(table, frame)
        refs[ref_name] = (table.brier(p_ref), cov_ref)
        out.setdefault("references", {})[ref_name] = {"source": source, "sha256": _source_sha(source),
                                                      "coverage": reasons_ref, "meta": meta}
    pools = [(sc.ALL_MARKETS, None), (PRIMARY_POOL, set(PRIMARY_MARKETS))] + [
        (m, {m}) for m in sorted(set(table.markets))]
    for name, path in candidates.items():
        frame, meta = _candidate_frame(path, table, lay, folds, data)
        p, cov, reasons = _vector(table, frame)
        cand_b = table.brier(p)
        brier_vs_mg1 = None
        if "mg1" in refs:
            _, d = table.cells(cand_b - refs["mg1"][0], w0712)
            brier_vs_mg1 = float(d.mean())
            expected = (expect_brier_vs_mg1 or {}).get(name)
            if expected is not None and abs(brier_vs_mg1 - expected) > 1e-6:
                raise ChallengerError(f"positive control failed: {name} 07-12 Brier - MG-1 {brier_vs_mg1:.7f} "
                                      f"!= expected {expected:.7f}")
        coverage = {}
        for market in sorted(set(table.markets)):
            mm = table.markets == market
            coverage[market] = {f"{h:02d}": [int((cov & mm & (table.local_hour == h)).sum()),
                                             int((mm & (table.local_hour == h)).sum())] for h in range(24)}
        rows = []
        for ref_name, (ref_b, ref_cov) in refs.items():
            for scope in ("blended", "covered"):
                base_mask = (cov & ref_cov) if scope == "covered" else everything
                for market, members in pools:
                    in_pool = everything if members is None else np.isin(table.markets, sorted(members))
                    for group, lo, hi in DEV_GROUPS:
                        mask = base_mask & in_pool & (table.local_hour >= lo) & (table.local_hour <= hi)
                        if not mask.any():
                            continue
                        idx, c = table.cells(cand_b, mask)
                        _, r_ = table.cells(ref_b, mask)
                        _, m = table.cells(market_b, mask)
                        ref_key = "R_served" if ref_name == "served" else "R_reference"
                        rows.append({
                            "reference": ref_name, "scope": scope, "market": market, "group": group,
                            "n_market_days": int(len(idx)), "n_snapshots": int(mask.sum()),
                            "R_candidate": sc.ratio_interval(table.w[:, idx], c, m),
                            ref_key: sc.ratio_interval(table.w[:, idx], r_, m),
                            "dR_crossed": sc.ratio_interval(table.w[:, idx], c - r_, m),
                            "dR_date_clustered": sc.ratio_interval(date_w[:, idx], c - r_, m)})
        out["candidates"][name] = {"source": str(path), "sha256": _source_sha(path), "coverage": reasons,
                                   "brier_minus_mg1_07_12": brier_vs_mg1,
                                   "brier_minus_mg1_07_12_expected": (expect_brier_vs_mg1 or {}).get(name),
                                   "coverage_by_market_hour": coverage, "meta": meta, "rows": rows}
    return out


# Clarification 1 (2026-10-25) appended; the original rule was 5898bfb0... (recorded inside the file).
# Clarification 2 (2026-10-25, option N) appended; the clarification-1 rule was 2f2c5994....
# Clarification 2 erratum (dewpoint from the T-group, as IEM dwpf); clarification 2 as first recorded was 52cef556....
PICK_RULE_SHA256 = "deb3eae31fb19cc96c90d1a9267f292e8a819fae1784c7b8b950071be99ceffb"
PICK_SEED = 20261025
PICK_HOURS = (13, 14, 15, 16)
# Clarification 2 (d): A_N - MG-1 at 13-16, recorded in C:/t/mg2/control_refit_armA.json (sha 714f1c51...).
PICK_CONTROL = -0.3915437386366088
PICK_CONTROL_TOL = 0.005


def dev_pick(layout, default, challengers, parity, rule_path, simpler="arm_a",
             start="2026-08-01", end="2026-09-29", control=PICK_CONTROL, control_only=False):
    """MG-2 afternoon-slot pick, exactly as ``C:/t/mg2/afternoon_pick_rule.md`` (sha pinned).

    ``default``: arm A's source; ``challengers``: {name: source}; ``parity``: {name: bool}, each lane's
    documented serve-parity check. Rows: snapshots at local hours 13-16 that every candidate covers.
    dR = R(challenger) - R(arm A) in the scorecard's Brier-ratio units, pooled over the 11 markets;
    intervals crossed (the scorecard's own draws) and date-clustered (2,000 draws, seed 20261025).
    """
    if _sha256(rule_path) != PICK_RULE_SHA256:
        raise ChallengerError(f"pick rule sha {_sha256(rule_path)} != pinned {PICK_RULE_SHA256}")
    if not control_only and set(parity) != set(challengers):
        raise ChallengerError("a serve-parity verdict is needed for every challenger")
    import numpy as np

    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas

    start_d, end_d = data.check_range(start, end)
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    table = sc.Table(lay, scored)
    date_w = _date_weights([k[0] for k in table.keys], sc.DRAWS, PICK_SEED)
    market_b = table.brier(table.p_market)
    vec, meta = {}, {}
    for name, source in {"arm_a": default, **challengers}.items():
        frame, m = _candidate_frame(source, table, lay, folds, data)
        p, cov, reasons = _vector(table, frame)
        vec[name] = (table.brier(p), cov)
        meta[name] = {"source": source, "sha256": _source_sha(source), "coverage": reasons}
    p_mg1, _, _ = _vector(table, loss_atlas.mg1_frame(table))
    mg1_b = table.brier(p_mg1)
    in_hours = np.isin(table.local_hour, PICK_HOURS)
    rows = in_hours.copy()
    for _, cov in vec.values():
        rows &= cov
    primary = np.isin(table.markets, sorted(PRIMARY_MARKETS))

    def stat(a, b, mask, weights):
        idx, c = table.cells(a, mask)
        _, r_ = table.cells(b, mask)
        _, m = table.cells(market_b, mask)
        return sc.ratio_interval(weights[:, idx], c - r_, m)

    def both(a, b, mask):
        return {"crossed": stat(a, b, mask, table.w), "date_clustered": stat(a, b, mask, date_w)}

    a_b = vec["arm_a"][0]
    control_value = control
    control = both(a_b, mg1_b, rows)
    control_ok = abs(control["date_clustered"]["estimate"] - control_value) <= PICK_CONTROL_TOL
    out = {"rule": str(rule_path), "rule_sha256": PICK_RULE_SHA256, "seed_date_clustered": PICK_SEED,
           "crossed_draws": "dev_scorecard Table.w (seed %d)" % sc.SEED,
           "rows": {"n_snapshots": int(rows.sum()), "n_in_hours": int(in_hours.sum()),
                    "n_primary": int((rows & primary).sum())},
           "candidates": meta,
           "control": {"arm_a_minus_mg1": control, "expected": control_value, "tolerance": PICK_CONTROL_TOL,
                       "passed": bool(control_ok)},
           "challengers": {}}
    upper = control["date_clustered"]["ci95"][1]
    out["control"]["clause_d_upper_ci_below_0"] = bool(upper is not None and upper < 0)
    if control_only:
        # Clarification 2 (d): the control is recorded before any challenger row is read.
        out["control"].pop("passed")
        out["control"].pop("expected")
        return out
    if upper is None or upper >= 0:
        # Clarification 1 (d): no afternoon half; MG-2 = MG-1 + L6 own-obs stack, the pick is not run.
        out["pick"] = {"candidate": None, "reason": "clarification (d): arm A - MG-1 date-clustered upper CI >= 0",
                       "eligible": []}
        return out
    eligible = []
    for name in challengers:
        b = vec[name][0]
        pooled = both(b, a_b, rows)
        hours = {f"h{h:02d}": both(b, a_b, rows & (table.local_hour == h)) for h in PICK_HOURS}
        prim = both(b, a_b, rows & primary)
        mg1 = both(b, mg1_b, rows)
        c1 = bool(parity[name])
        c2 = all(pooled[k]["ci95"][1] is not None and pooled[k]["ci95"][1] < 0 for k in pooled)
        c3 = not any(v["date_clustered"]["ci95"][0] is not None and v["date_clustered"]["ci95"][0] > 0
                     for v in hours.values())
        c4 = prim["date_clustered"]["estimate"] < 0
        ok = c1 and c2 and c3 and c4
        out["challengers"][name] = {"dR_vs_arm_a": pooled, "by_hour": hours, "primary5": prim,
                                    "dR_vs_mg1": mg1,
                                    "conditions": {"1_serve_parity": c1, "2_upper_below_0_both": c2,
                                                   "3_no_ci_worse_hour": c3, "4_primary5_point_below_0": c4},
                                    "eligible": ok}
        if ok:
            eligible.append(name)
    if not control_ok:
        pick, why = "arm_a", "positive control failed: pick void, arm A stands"
    elif not eligible:
        pick, why = "arm_a", "no challenger eligible"
    elif len(eligible) == 1:
        pick, why = eligible[0], "one challenger eligible"
    else:
        x, y = eligible[:2]
        diff = both(vec[x][0], vec[y][0], rows)
        out["eligible_difference"] = {"pair": [x, y], **diff}
        lo, hi = diff["date_clustered"]["ci95"]
        if lo is not None and lo <= 0 <= hi:
            pick, why = simpler, "both eligible, difference interval contains 0: the simpler one"
        else:
            pick = min(eligible, key=lambda n: out["challengers"][n]["dR_vs_arm_a"]["date_clustered"]["estimate"])
            why = "both eligible: lower pooled point dR"
    out["pick"] = {"candidate": pick, "reason": why, "eligible": eligible}
    return out


# ---------------------------------------------------------------- L6 own-obs stack on captured METAR (pick rule cl. 2 (e))

L6_MARKET_LAT_MIN = 10
L6_MAX_AGE_MIN = 90
_COVER = {"CLR": 0.0, "SKC": 0.0, "NCD": 0.0, "NSC": 0.0, "FEW": .25, "SCT": .5, "BKN": .75, "OVC": 1.0, "VV": 1.0}


def parse_captured_metar(raw, anchor_utc):
    """One captured METAR row -> the fields lane L6's IEM extract carries (None when unparseable).

    Observation instant from the raw DDHHMMZ group (nearest to ``anchor_utc``); temperature and dewpoint from the
    T-group when present, else the body (IEM ``dwpf`` follows the T-group; pick rule clarification 2 erratum); wind, cover and ceiling
    as ``iem_upstream`` (cover = max layer, ceiling = lowest BKN/OVC/VV base).
    """
    import re
    from datetime import timedelta

    m = re.search(r"\b(\d{2})(\d{2})(\d{2})Z\b", raw or "")
    if not m:
        return None
    day, hh, mm = (int(g) for g in m.groups())
    valid = None
    for shift in (-1, 0, 1):
        base = (anchor_utc + timedelta(days=shift)).replace(hour=0, minute=0, second=0, microsecond=0)
        if base.day == day:
            cand = base.replace(hour=hh, minute=mm)
            if valid is None or abs(cand - anchor_utc) < abs(valid - anchor_utc):
                valid = cand
    if valid is None:
        return None

    def c2f(c):
        return c * 9.0 / 5.0 + 32.0

    body = re.search(r"\s(M?\d{2})/(M?\d{2})?(?=\s)", raw)
    tg = re.search(r"\bT([01])(\d{3})([01])(\d{3})\b", raw)
    temp = dwpf = None
    if body:
        temp = c2f(int(body.group(1).replace("M", "-")))
        dwpf = c2f(int(body.group(2).replace("M", "-"))) if body.group(2) else None
    if tg:
        temp = c2f((-1 if tg.group(1) == "1" else 1) * int(tg.group(2)) / 10.0)
        dwpf = c2f((-1 if tg.group(3) == "1" else 1) * int(tg.group(4)) / 10.0)
    w = re.search(r"\b(\d{3}|VRB)(\d{2,3})(?:G\d{2,3})?KT\b", raw)
    drct = sknt = None
    if w:
        drct = None if w.group(1) == "VRB" else float(w.group(1))
        sknt = float(w.group(2))
    covers, ceiling = [], None
    for k in re.finditer(r"\b(FEW|SCT|BKN|OVC|VV)(\d{3})|\b(CLR|SKC|NCD|NSC)\b", raw):
        if k.group(3):
            covers.append(0.0)
            continue
        covers.append(_COVER[k.group(1)])
        if k.group(1) in ("BKN", "OVC", "VV") and ceiling is None:
            ceiling = int(k.group(2)) * 100.0
    return {"valid": valid, "temp": temp, "dwpf": dwpf, "drct": drct, "sknt": sknt,
            "cover": max(covers) if covers else None, "ceiling_ft": ceiling,
            "is_cor": " COR " in f" {raw} "}


def _json_value_after(line, key, start=0):
    """Decode the JSON value that follows ``"key":`` at or after ``start`` (no whole-line parse)."""
    at = line.find(f'"{key}":', start)
    if at < 0:
        return None, -1
    pos = at + len(key) + 3
    while line[pos] == " ":
        pos += 1
    value, end = json.JSONDecoder().raw_decode(line, pos)
    return value, end


def _captured_rows(line, station):
    """The captured ``sources.metar.data.rows`` of one replay line."""
    start = line.find('"sources":')
    if start < 0:
        return []
    metar_at = line.find('"metar":', start)
    if metar_at < 0:
        return []
    section, _ = _json_value_after(line, "metar", start)
    rows = ((section or {}).get("data") or {}).get("rows") or []
    return [r for r in rows if str(r.get("station_id") or station) == station]


def l6_captured_features(snapshot_rows, captured, tz, station_code, prev_dmax):
    """L6 OWN features at each snapshot from that snapshot's own captured METAR rows (L6's semantics)."""
    from datetime import timedelta

    import numpy as np
    import pandas as pd

    lag = timedelta(minutes=L6_MARKET_LAT_MIN)
    out = []
    for key, cap_utc, local_date in snapshot_rows:
        rows = [r for r in captured.get(key, []) if not r["is_cor"] and r["temp"] is not None]
        usable = sorted((r for r in rows if r["valid"] + lag <= cap_utc), key=lambda r: r["valid"])

        def asof(t):
            cand = [r for r in usable if r["valid"] + lag <= t]
            if not cand or (t - cand[-1]["valid"]) > timedelta(minutes=L6_MAX_AGE_MIN):
                return None
            return cand[-1]

        now, ago = asof(cap_utc), asof(cap_utc - timedelta(hours=3))
        same_day = [r["temp"] for r in usable if r["valid"].astimezone(tz).date().isoformat() == local_date]
        loc = cap_utc.astimezone(tz)
        nan = float("nan")
        t = now["temp"] if now else nan
        td = now["dwpf"] if now and now["dwpf"] is not None else nan
        r_ = float(np.fmax(max(same_day) if same_day else nan, t))
        drct = now["drct"] if now and now["drct"] is not None else nan
        sknt = now["sknt"] if now and now["sknt"] is not None else nan
        calm = sknt == 0
        u = 0.0 if calm else -sknt * math.sin(math.radians(drct))
        v = 0.0 if calm else -sknt * math.cos(math.radians(drct))
        cover = now["cover"] if now and now["cover"] is not None else nan
        ceil = now["ceiling_ft"] if now else None
        log_ceiling = (math.log10(max(ceil, 100.0)) if ceil is not None
                       else (math.log10(30000.0) if math.isfinite(cover) else nan))
        prev = prev_dmax.get(local_date, nan)
        out.append({"row_key": key, "hour_f": loc.hour + loc.minute / 60.0, "doy": loc.timetuple().tm_yday,
                    "station_code": station_code, "t": t, "td": td, "r": r_, "t_minus_r": t - r_,
                    "tend3": (t - ago["temp"]) if ago else nan,
                    "td_tend3": (td - ago["dwpf"]) if ago and ago["dwpf"] is not None else nan,
                    "u": u, "v": v, "spd": sknt, "cover": cover, "log_ceiling": log_ceiling,
                    "prev_dmax": prev, "prev_minus_t": prev - t})
    return pd.DataFrame(out)


def routine_dmax(rows, tz, local_date, min_routine=20):
    """Half-up max of a day's routine (modal-minute), non-COR rows; None below ``min_routine`` rows."""
    from collections import Counter

    day = [r for r in rows if not r["is_cor"] and r["temp"] is not None
           and r["valid"].astimezone(tz).date().isoformat() == local_date]
    if not day:
        return None
    modal = Counter(r["valid"].minute for r in day).most_common(1)[0][0]
    routine = [r["temp"] for r in day if r["valid"].minute == modal]
    if len(routine) < min_routine:
        return None
    return float(math.floor(max(routine) + 0.5))


def l6_captured_nowcasts(layout, replay_root, research_root, out_dir):
    """Lane L6's own-obs nowcast N_own re-specified on the captured METAR rows (pick rule clarification 2 (e)).

    Features per snapshot come only from that snapshot's captured METAR rows (usable from observation + 10 min,
    the training rule); the previous-day max from the previous local day's last captured snapshot. Model: L6's
    own history fit, unchanged (``upstream_obs_screen.build_history`` + ``make_model(OWN)``, imported). Positive
    control first: that fit applied to L6's IEM serve features must reproduce L6's ``n_own`` (to 1e-9).
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    import numpy as np
    import pandas as pd

    from weather.calibration import upstream_obs_screen as l6

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    screen = Path(research_root) / "upstream_obs" / "screen"
    hist, prov = l6.build_history(research_root)
    train = hist[hist.month.isin(l6.TRAIN_MONTHS_PRIMARY)].reset_index(drop=True)
    own = l6.make_model(l6.OWN).fit(train[list(l6.OWN)].to_numpy(float), train.y.to_numpy(float))
    iem = pd.read_parquet(screen / "serve_features.parquet")
    ref = pd.read_parquet(screen / "nowcasts.parquet").set_index("row_key")
    again = iem.r.to_numpy(float) + own.predict(iem[list(l6.OWN)].to_numpy(float))
    gap = float(np.nanmax(np.abs(again - ref.n_own.reindex(iem.row_key).to_numpy(float))))
    if not gap < 1e-9:
        raise ChallengerError(f"L6 positive control failed: refit n_own differs from L6's by {gap}")
    _, sel, _ = l6.load(research_root)
    codes = {icao: code for code, icao in enumerate(l6.stations(sel))}
    snaps = pd.read_parquet(Path(layout) / "inputs_snapshots.parquet",
                            columns=["row_key", "station", "market", "date", "local_hour", "snapshot_id"])
    if (snaps.date.astype(str) > DEV_LAST.isoformat()).any():
        raise ChallengerError("layout holds a snapshot after 2026-09-29")
    station_of = snaps.groupby("market").station.first().to_dict()
    snaps = snaps[snaps.local_hour.isin(l6.HOURS)]
    wanted = {(r.market, r.snapshot_id): (r.row_key, str(r.date)[:10]) for r in snaps.itertuples(index=False)}
    captured, snap_rows, last_rows = defaultdict(dict), defaultdict(list), defaultdict(dict)
    stats = defaultdict(int)
    for market, target, folder in _event_folders(replay_root):
        if market not in station_of or not (DEV_FIRST - timedelta(days=1) <= target <= DEV_LAST):
            continue
        path = folder / "replay_inputs.jsonl"
        if not path.is_file():
            continue
        station = station_of[market]
        last = None
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                head = line[:line.find('"sources":')] if '"sources":' in line else line
                sid, _ = _json_value_after(head, "snapshot_id")
                cap_s, _ = _json_value_after(head, "captured_at_utc")
                if cap_s is None:
                    continue
                cap = datetime.fromisoformat(cap_s)
                last = (line, cap)
                hit = wanted.get((market, sid))
                if hit is None:
                    continue
                key, local_date = hit
                captured[market][key] = [p for p in (parse_captured_metar(r.get("raw"), cap)
                                                     for r in _captured_rows(line, station)) if p is not None]
                snap_rows[market].append((key, cap, local_date))
                stats["snapshots_scanned"] += 1
        if last is not None:
            last_rows[market][target.isoformat()] = [
                p for p in (parse_captured_metar(r.get("raw"), last[1]) for r in _captured_rows(last[0], station))
                if p is not None]
    frames = []
    for market in sorted(snap_rows):
        station = station_of[market]
        tz = ZoneInfo(sel[station]["timezone"])
        prev = {}
        for day in sorted({d for _, _, d in snap_rows[market]}):
            before = (datetime.fromisoformat(day) - timedelta(days=1)).date().isoformat()
            value = routine_dmax(last_rows[market].get(before, []), tz, before)
            if value is None:
                stats["prev_dmax_missing_days"] += 1
            else:
                prev[day] = value
        frames.append(l6_captured_features(snap_rows[market], captured[market], tz, codes[station], prev))
    feat = pd.concat(frames, ignore_index=True)
    ok = np.isfinite(feat.r) & np.isfinite(feat.t)
    stats["no_usable_row"] = int((~ok).sum())
    feat = feat[ok].reset_index(drop=True)
    res = pd.DataFrame({"row_key": feat.row_key, "n_own": feat.r.to_numpy(float) + own.predict(
        feat[list(l6.OWN)].to_numpy(float)), "n_up": np.nan, "n_ring": np.nan})
    res.to_parquet(out / "nowcasts.parquet", index=False)
    feat.to_parquet(out / "serve_features.parquet", index=False)
    joined = feat.set_index("row_key").join(iem.set_index("row_key")[list(l6.OWN)], rsuffix="_iem", how="inner")
    parity = {}
    for col in ("t", "td", "r", "tend3", "spd", "cover", "log_ceiling", "prev_dmax"):
        d = (joined[col] - joined[f"{col}_iem"]).dropna()
        parity[col] = {"n": int(len(d)), "share_within_0.05": float((d.abs() <= 0.05).mean()) if len(d) else None,
                       "mad": float(d.abs().mean()) if len(d) else None,
                       "captured_nan_iem_present": int((joined[col].isna() & joined[f"{col}_iem"].notna()).sum()),
                       "iem_nan_captured_present": int((joined[col].notna() & joined[f"{col}_iem"].isna()).sum())}
    nd = (res.set_index("row_key").n_own - ref.n_own).dropna()
    manifest = dict(prov, positive_control_max_abs_gap=gap, rows=int(len(res)), stats=dict(stats),
                    parity_vs_iem=parity,
                    n_own_vs_iem={"n": int(len(nd)), "mad": float(nd.abs().mean()),
                                  "share_within_0.05": float((nd.abs() <= 0.05).mean())},
                    iem_rows=int(len(ref)), nowcasts_sha256=_sha256(out / "nowcasts.parquet"),
                    layout_snapshots_sha256=_sha256(Path(layout) / "inputs_snapshots.parquet"),
                    l6_module_sha256=_sha256(l6.__file__))
    (out / "nowcasts_manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


def _rows(scores, arm, reference="served", scope="blended"):
    return {(r["market"], r["group"]): r for r in scores["candidates"][arm]["rows"]
            if r.get("reference", "served") == reference and r.get("scope", "blended") == scope}


def dev_verdict(scores, arms=("ols_floor", "ols_floor_resid_hgb")):
    """dev_rule.md: dR < 0 at pooled 07-12 with CI excluding 0, no standard block worse beyond CI."""
    result = {}
    for arm in arms:
        rows = _rows(scores, arm)
        head = rows[("ALL", "07-12")]
        checks = {}
        for kind in ("dR_crossed", "dR_date_clustered"):
            lo, hi = head[kind]["ci95"]
            worse = [g for g in DEV_STANDARD_BLOCKS if ("ALL", g) in rows
                     and rows[("ALL", g)][kind]["ci95"][0] is not None and rows[("ALL", g)][kind]["ci95"][0] > 0]
            checks[kind] = {"estimate": head[kind]["estimate"], "ci95": [lo, hi], "blocks_worse": worse,
                            "beats_served": bool(hi is not None and hi < 0 and not worse)}
        result[arm] = checks
    return result


def dev_mg1_gate(scores, arm="ols_floor", pool="ALL", scope="blended"):
    """dev_rule.md clarification 1: no interval (either kind) wholly above 0 at 07-12 or a gate block."""
    if not (scores.get("mg1_control") or {}).get("passed"):
        return {"arm": arm, "pool": pool, "scope": scope, "no_worse_than_mg1": None,
                "reason": "MG-1 positive control missing or failed"}
    rows = _rows(scores, arm, "mg1", scope)
    worse = []
    for group in DEV_MG1_GATE_BLOCKS:
        row = rows.get((pool, group))
        if row is None:
            continue
        for kind in ("dR_crossed", "dR_date_clustered"):
            lo = row[kind]["ci95"][0]
            if lo is not None and lo > 0:
                worse.append(f"{group}:{kind}")
    head = rows[(pool, "07-12")]
    return {"arm": arm, "pool": pool, "scope": scope,
            "dR_07_12": {k: {"estimate": head[k]["estimate"], "ci95": head[k]["ci95"]}
                         for k in ("dR_crossed", "dR_date_clustered")},
            "ci_worse": worse, "no_worse_than_mg1": not worse}


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
    repro_or_all = repro_ok if parity else rows_by_market  # without lane D rows R0-repro is unchecked
    plan = (
        ("VERDICT (rule clarification 2)", r0_joined, LANE_D_FLOORED, PRIMARY_MARKETS, True),
        ("CONTROL floor + forecast", rows_by_market, "bias_corrected_forecast_floor", PRIMARY_MARKETS, True),
        ("CONTROL own R0-repro + floor (repro parity passed)", repro_ok, "r0_floor", PRIMARY_MARKETS, False),
        ("DESCRIPTIVE raw R0", r0_joined, "r0", PRIMARY_MARKETS, False),
        ("SECONDARY (other six) vs baseline", rows_by_market, "r0_baseline", SECONDARY_MARKETS, True),
        ("DESCRIPTIVE other six vs floor + forecast", rows_by_market, "bias_corrected_forecast_floor",
         SECONDARY_MARKETS, False),
        ("DESCRIPTIVE other six vs own R0-repro + floor", rows_by_market, "r0_floor", SECONDARY_MARKETS, False),
        # Clarification 3 (Aug-Sep: no R0 comparator); descriptive for Oct-Dec.
        ("ALL 11 vs baseline + floor (e)", rows_by_market, "r0_baseline_floor", ALL_MARKETS, True),
        ("ALL 11 vs forecast + floor (f)", rows_by_market, "bias_corrected_forecast_floor", ALL_MARKETS, True),
        ("PRIMARY five vs baseline + floor (e)", rows_by_market, "r0_baseline_floor", PRIMARY_MARKETS, True),
        ("ALL 11 vs own R0-repro + floor", repro_or_all, "r0_floor", ALL_MARKETS, False),
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
    emit = sub.add_parser("dev-emit", help="fit on Aug-Sep 2021-25, emit dev-window candidate distributions")
    emit.add_argument("--layout", required=True)
    emit.add_argument("--replay-root", required=True)
    emit.add_argument("--train-manifest", action="append", required=True)
    emit.add_argument("--dev-manifest", required=True)
    emit.add_argument("--markets", default=",".join(PRIMARY_MARKETS + SECONDARY_MARKETS))
    emit.add_argument("--out-dir", required=True)
    emit.add_argument("--variants", default=",".join(DEV_DEFAULT_VARIANTS))
    emit.add_argument("--obs-from", default=None, help="reuse a previous run's dev_features.jsonl")
    emit.add_argument("--nbm-corpus", default=None, help="lane L9 PIT NBM corpus rows (nbm_hist variant)")
    dscore = sub.add_parser("dev-score", help="score emitted candidates with dev_scorecard; apply dev_rule.md")
    dscore.add_argument("--layout", required=True)
    dscore.add_argument("--candidate", action="append", required=True, help="<name>=<jsonl>")
    dscore.add_argument("--rule", default=None)
    dscore.add_argument("--no-mg1", action="store_true", help="skip the MG-1 reference")
    dscore.add_argument("--reference", action="append", default=[],
                        help="<name>=<jsonl | module:<path> | builtin:mg1> scored as an extra reference")
    dscore.add_argument("--expect-brier-vs-mg1", action="append", default=[],
                        help="<candidate>=<value>: positive control, 07-12 Brier minus MG-1 to 1e-6")
    dscore.add_argument("--out", required=True)
    pick = sub.add_parser("dev-pick", help="MG-2 afternoon-slot pick under the pinned pick rule")
    pick.add_argument("--layout", required=True)
    pick.add_argument("--arm-a", required=True, help="arm A source (jsonl | module:<path>)")
    pick.add_argument("--challenger", action="append", default=[], help="<name>=<source>")
    pick.add_argument("--parity", action="append", default=[], help="<name>=pass|fail")
    pick.add_argument("--control-only", action="store_true",
                      help="record arm A - MG-1 at 13-16 on arm A's rows only; no challenger is read")
    pick.add_argument("--rule", required=True)
    pick.add_argument("--control", type=float, default=PICK_CONTROL,
                      help="recorded arm A - MG-1 13-16 control (pick rule clarification 1 (c))")
    pick.add_argument("--out", required=True)
    l6c = sub.add_parser("l6-captured", help="L6 own-obs nowcasts from the captured METAR rows (pick rule cl. 2 (e))")
    l6c.add_argument("--layout", required=True)
    l6c.add_argument("--replay-root", required=True)
    l6c.add_argument("--research-root", required=True)
    l6c.add_argument("--out-dir", required=True)
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
        if args.command == "l6-captured":
            manifest = l6_captured_nowcasts(args.layout, args.replay_root, args.research_root, args.out_dir)
            print(json.dumps({k: manifest[k] for k in ("positive_control_max_abs_gap", "rows", "stats",
                                                        "n_own_vs_iem", "parity_vs_iem")}, indent=1))
            return 0
        if args.command == "dev-pick":
            chal = dict(item.split("=", 1) for item in args.challenger)
            parity = {k: v == "pass" for k, v in (item.split("=", 1) for item in args.parity)}
            result = dev_pick(args.layout, args.arm_a, chal, parity, args.rule, control=args.control,
                              control_only=args.control_only)
            Path(args.out).write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
            print(json.dumps({"control": result["control"], "pick": result.get("pick")}, indent=1))
            return 0
        if args.command == "dev-emit":
            audit = dev_emit(layout=args.layout, replay_root=args.replay_root,
                             train_manifests=args.train_manifest, dev_manifest=args.dev_manifest,
                             out_dir=args.out_dir, markets=args.markets.split(","),
                             variants=args.variants.split(","),
                             obs_from=args.obs_from, nbm_corpus=args.nbm_corpus)
            print(json.dumps(audit["files"], indent=1))
            return 0
        if args.command == "dev-score":
            scores = dev_score(args.layout, dict(spec.partition("=")[::2] for spec in args.candidate),
                               with_mg1=not args.no_mg1,
                               references=dict(spec.partition("=")[::2] for spec in args.reference),
                               expect_brier_vs_mg1={k: float(v) for k, v in (
                                   spec.partition("=")[::2] for spec in args.expect_brier_vs_mg1)})
            scores["verdict"] = dev_verdict(scores) if all(
                a in scores["candidates"] for a in ("ols_floor", "ols_floor_resid_hgb")) else None
            if "mg1_control" in scores:
                scores["mg1_gate"] = {f"{arm}|{pool}|{scope}": dev_mg1_gate(scores, arm, pool, scope)
                                      for arm in scores["candidates"] for pool in ("ALL", PRIMARY_POOL)
                                      for scope in ("blended", "covered")}
            scores["rule_sha256"] = _sha256(args.rule) if args.rule else None
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(scores, indent=1, sort_keys=True), encoding="utf-8")
            print(json.dumps(scores["verdict"], indent=1))
            return 0
        return _compare_command(args)
    except ChallengerError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
