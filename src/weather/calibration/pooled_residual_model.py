"""Research only: one pooled multi-market model in residual space (lane L2, 2026-10-24).

R0 fits one small HGB classifier per market and cutoff hour on about 75 days. This
module pools the US 11 into one model per cutoff hour, in residual space, and scores
it against R0 on R0's own blocked leave-one-year-out rows. The pass/pick rule is
pre-declared outside the repository (C:\\t\\l2\\rule.md, sha256 recorded in the
report) and is summarised in :data:`ARMS`.

Stages (each a CLI subcommand; heavy ones run only through
``scripts/ops/workstation_heavy.ps1`` on the non-capture workstation):

``extract``
    For one market and centre date, build the trainer's own per-cutoff records
    (``feature_model.build_feature_records_for_model`` on
    ``TorontoHighTempModel(target_date=centre)``, r0 allowlist, verified PIT
    corpora, no ambient archive) and pickle them with the allowlist plan, the
    bucket space and the baseline weights.
``evaluate``
    Score R0 (recomputed with the trainer's functions, one fit per held-out year)
    and the pooled arms on identical rows; write one JSONL of per-row losses per arm.
``report``
    Paired deltas against R0 with date-clustered bootstrap CIs, per hour and per
    market, 07-12 called out, and the pre-declared decision.

Boundaries: offline, no network, never imported by serving, capture or release
code (an import on the dedicated capture host, or where that cannot be proved
otherwise, raises :class:`ProductionImportRefused`). Outputs must lie outside the
repository. Inputs are the local WU history and PIT corpora for years before the
centre year (2021-2025); nothing dated after 2026-09-29 is read.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import pickle
from collections import defaultdict
from datetime import date
from pathlib import Path

from weather.paths import CONFIG_ROOT, REPO_ROOT


class ProductionImportRefused(ImportError):
    """This research module may not load on the capture host or unproved hosts."""


def _refuse_production_import():
    """Fail closed unless this is provably not the dedicated capture host."""
    from weather.execution_host import (
        DEFAULT_EXECUTION_HOST_ASSIGNMENT_PATH,
        current_execution_host_id,
    )

    try:
        assignment = json.loads(
            Path(DEFAULT_EXECUTION_HOST_ASSIGNMENT_PATH).read_text(encoding="utf-8")
        )
        capture_id = str(assignment["dedicated_capture_execution_host_id"])
        here = current_execution_host_id()
    except Exception as exc:  # noqa: BLE001 - any doubt refuses
        raise ProductionImportRefused(
            "pooled_residual_model refuses to load: the host is not provably a "
            f"non-capture workstation ({type(exc).__name__})"
        ) from exc
    if not capture_id or here == capture_id:
        raise ProductionImportRefused(
            "pooled_residual_model refuses to load on the dedicated capture host"
        )


_refuse_production_import()


R0_MARKETS = (
    "atlanta", "austin", "chicago", "dallas", "denver", "houston",
    "los-angeles", "miami", "nyc", "san-francisco", "seattle",
)
VALIDATION_CENTRE = "2026-11-24"
OCT_DEC_CENTRES = ("2026-10-10", "2026-10-25", "2026-11-09", "2026-11-24", "2026-12-09", "2026-12-24")
AUG_SEP_CENTRES = ("2026-08-08", "2026-08-23", "2026-09-07", "2026-09-22")
WINDOW_HOURS = (7, 8, 9, 10, 11, 12)
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261024
FLOOR_MIX_CLIM = 0.02
KERNEL_BANDWIDTH = 0.25
MIN_SCALE = 0.5
# Arm -> (centres, market id feature, day-of-year feature). Fixed by the rule.
ARMS = {
    "P0": {"centres": (VALIDATION_CENTRE,), "market_id": False, "doy": False},
    "P1": {"centres": (VALIDATION_CENTRE,), "market_id": True, "doy": False},
    "P2": {"centres": OCT_DEC_CENTRES, "market_id": False, "doy": True},
    "P3": {"centres": OCT_DEC_CENTRES + AUG_SEP_CENTRES, "market_id": False, "doy": True},
}
LEVEL_COLUMNS = ("high_so_far", "current_temp", "live_reading_temp")
MEAN_HGB_PARAMS = dict(
    max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40,
    l2_regularization=1.0, early_stopping=False, random_state=42,
)
SCALE_HGB_PARAMS = dict(
    max_iter=100, learning_rate=0.05, max_leaf_nodes=7, min_samples_leaf=40,
    early_stopping=False, random_state=42,
)


class PooledModelError(ValueError):
    """An input breaks the row, fold or output contract."""


# --------------------------------------------------------------------------- io


def require_output_outside_repo(path):
    """Research output never lands in the repository (no production path)."""
    resolved = Path(path).resolve()
    repo = Path(REPO_ROOT).resolve()
    if resolved == repo or repo in resolved.parents:
        raise PooledModelError(f"output must be outside the repository: {resolved}")
    return resolved


def records_path(root, market, centre):
    return Path(root) / f"records_{market}_{centre}.pkl.gz"


def season_of(centre):
    return "aug_sep" if str(centre)[5:7] in ("08", "09") else "oct_dec"


def station_coordinates(markets=R0_MARKETS, path=None):
    payload = json.loads(Path(path or CONFIG_ROOT / "locations.json").read_text(encoding="utf-8"))
    by_id = {row.get("id"): row for row in payload.get("locations", [])}
    out = {}
    for market in markets:
        coords = (by_id.get(market) or {}).get("coordinates") or {}
        if not all(key in coords for key in ("lat", "lon", "elevation_m")):
            raise PooledModelError(f"no station coordinates for {market}")
        out[market] = (float(coords["lat"]), float(coords["lon"]), float(coords["elevation_m"]))
    return out


# ---------------------------------------------------------------------- extract


def extract_market(market, centre, manifests, out_root):
    """Build the trainer's per-cutoff records for one market and centre (heavy)."""
    from weather.calibration import feature_model as fm
    from weather.calibration.feature_column_allowlist import resolve_column_allowlist
    from weather.calibration.feature_model_training_inputs import (
        PITForecastCorpusUnion,
        require_market_history,
        select_training_days,
    )

    out_root = require_output_outside_repo(out_root)
    target = records_path(out_root, market, centre)
    if target.exists():
        raise PooledModelError(f"refusing to overwrite {target}")
    centre_date = date.fromisoformat(str(centre))
    model = fm.TorontoHighTempModel(market_id=market, target_date=centre_date)
    spec = model.spec
    plan = resolve_column_allowlist(
        f"r0:{market}", market_spec=spec,
        known_wind_groups=fm.WIND_GROUPS, known_cloud_groups=fm.CLOUD_GROUPS,
    )
    require_market_history(spec)
    union = PITForecastCorpusUnion(
        list(manifests), spec.id, target_year=centre_date.year,
        required_cutoff_hours=fm.INTRADAY_CUTOFF_HOURS,
    )
    cache = model.historical_target_cache()
    daily, counts = select_training_days(
        cache["daily"], training_years=None, forecast_years=union.years, target_date=centre_date,
    )
    raw = fm.build_feature_records_for_model(
        model, daily, cache["by_date"], None, None,
        marine_water_contrast_index=fm.load_marine_water_contrast_features(spec=spec),
        reanalysis_synoptic_index=fm.load_reanalysis_synoptic_features(spec=spec),
        forecast_resolver=union,
    )
    payload = {
        "market": market,
        "centre": str(centre),
        "unit": spec.unit,
        "plan": plan,
        "bucket_space": list(cache["bucket_space"]),
        "calibrated_weights": model.calibrated_weights or {},
        "days_by_year": counts,
        "corpus_union": union.record(),
        "records": {int(hour): list(rows) for hour, rows in raw.items()},
    }
    out_root.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    with gzip.open(tmp, "wb") as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(target)
    return target, {"days_by_year": counts, "union_sha256": payload["corpus_union"]["union_sha256"]}


def load_records(root, market, centre):
    with gzip.open(records_path(root, market, centre), "rb") as handle:
        return pickle.load(handle)


# ----------------------------------------------------------- R0 (trainer's arm)


def _year_groups(records):
    """Validation indices grouped by their (year-only) training set."""
    from weather.calibration import feature_model as fm

    plan = fm.feature_blocked_validation_plan(records)
    groups = defaultdict(list)
    for val_idx, train in plan["train_indices_by_validation_index"].items():
        groups[tuple(train)].append(int(val_idx))
    return {train: sorted(vals) for train, vals in groups.items()}


def _baseline_scores(fm, records, train_days, val_row, bucket_space, weights):
    """The trainer's baseline blend for one validation row (verbatim logic)."""
    w_int_base = weights.get("w_intraday_base", 0.36) if weights else 0.36
    w_wnd = weights.get("w_wind", 0.14) if weights else 0.14
    w_cld = weights.get("w_cloud", 0.12) if weights else 0.12
    p_clim = fm.smoothed_dist([d["final_bucket"] for d in train_days], bucket_space, alpha=0.10)
    scores = p_clim.copy()
    observed = fm.round_half_up(val_row["high_so_far"])
    if observed is not None:
        matching = [d for d in train_days if fm.round_half_up(d["high_so_far"]) == observed]
        if len(matching) >= 8:
            p_int = fm.smoothed_dist([d["final_bucket"] for d in matching], bucket_space, alpha=0.05)
            scores = fm.blend(scores, p_int, w_int_base * (len(matching) / (len(matching) + 25)))
    for key, weight in (("wind_group", w_wnd), ("cloud_group", w_cld)):
        value = val_row.get(key)
        if value:
            matching = [d for d in train_days if d.get(key) == value]
            if len(matching) >= 20:
                scores = fm.blend(
                    scores,
                    fm.smoothed_dist([d["final_bucket"] for d in matching], bucket_space, alpha=0.10),
                    weight,
                )
    return p_clim, scores


def score_r0_market(payload):
    """R0 and the trainer baseline on one market's validation rows."""
    from weather.calibration import feature_model as fm

    plan = payload["plan"]
    bucket_space = payload["bucket_space"]
    rows = []
    for hour in sorted(payload["records"]):
        records = payload["records"][hour]
        if not records:
            continue
        df, feature_cols = fm.feature_model_frame(
            records, plan["all_wind_groups"], plan["all_cloud_groups"],
            market_spec=None, column_allowlist=plan,
        )
        X = df[feature_cols].copy()
        y = df["final_bucket"].copy()
        n_numeric = len(plan["numeric_feature_names"])
        weights = (payload["calibrated_weights"] or {}).get(str(hour))
        for train, vals in _year_groups(records).items():
            train = list(train)
            if not train or len(set(y.iloc[train])) < 2:
                continue
            train_days = [records[i] for i in train]
            mats = fm.fold_local_feature_matrices(X, train, vals, feature_cols, n_numeric)
            hgb = fm.make_feature_hgb()
            hgb.fit(mats["hgb_train"], y.iloc[train])
            probs = hgb.predict_proba(mats["hgb_validation"])
            for pos, val_idx in enumerate(vals):
                row = records[val_idx]
                actual = df.iloc[val_idx]["final_bucket"]
                p_clim, base = _baseline_scores(fm, records, train_days, row, bucket_space, weights)
                hgb_dict = {int(c): float(p) for c, p in zip(hgb.classes_, probs[pos])}
                blended = fm.blend(p_clim.copy(), hgb_dict, 0.80)
                vdate = str(df.iloc[val_idx]["target_date"])
                rows.append({
                    "market": payload["market"], "hour": int(hour),
                    "validation_date": vdate, "validation_year": int(vdate[:4]),
                    "R0_log_loss": fm.log_loss(blended, actual),
                    "R0_brier": fm.brier_score(blended, actual),
                    "baseline_log_loss": fm.log_loss(base, actual),
                    "baseline_brier": fm.brier_score(base, actual),
                })
    return rows


def r0_parity(rows, lane_d_rows_path):
    """Max abs difference of hgb_log_loss against lane D's trainer output."""
    theirs = {}
    with open(lane_d_rows_path, encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            theirs[(int(row["hour"]), str(row["validation_date"]))] = float(row["hgb_log_loss"])
    ours = {(r["hour"], r["validation_date"]): r["R0_log_loss"] for r in rows}
    if set(ours) != set(theirs):
        return {"keys_match": False, "ours": len(ours), "theirs": len(theirs), "max_abs_diff": None}
    diff = max(abs(ours[k] - theirs[k]) for k in ours) if ours else 0.0
    return {"keys_match": True, "rows": len(ours), "max_abs_diff": diff}


# ------------------------------------------------------------------- pooled arm


def pooled_frame(payloads, coords):
    """One row per (market, centre, hour, day) with the pooled-model inputs."""
    import numpy as np
    import pandas as pd

    common = None
    for payload in payloads:
        names = list(payload["plan"]["numeric_feature_names"])
        common = names if common is None else [c for c in common if c in names]
    wind = sorted({g for p in payloads for g in p["plan"]["all_wind_groups"]})
    cloud = sorted({g for p in payloads for g in p["plan"]["all_cloud_groups"]})
    out = []
    for payload in payloads:
        lat, lon, elev = coords[payload["market"]]
        for hour, records in payload["records"].items():
            for rec in records:
                tdate = date.fromisoformat(str(rec["target_date"])[:10])
                row = {
                    "market": payload["market"], "centre": payload["centre"],
                    "season": season_of(payload["centre"]), "hour": int(hour),
                    "target_date": tdate.isoformat(), "year": tdate.year,
                    "y": float(rec["final_bucket"]),
                    "F": _num(rec.get("high_so_far")), "fh": _num(rec.get("forecast_high")),
                    "lat": lat, "lon": lon, "elev": elev,
                    "doy_sin": math.sin(2 * math.pi * tdate.timetuple().tm_yday / 365.25),
                    "doy_cos": math.cos(2 * math.pi * tdate.timetuple().tm_yday / 365.25),
                }
                for column in common:
                    row[f"x_{column}"] = _num(rec.get(column))
                for group in wind:
                    row[f"x_wind_{group}"] = 1.0 if rec.get("wind_group") == group else 0.0
                for group in cloud:
                    row[f"x_cloud_{group}"] = 1.0 if rec.get("cloud_group") == group else 0.0
                out.append(row)
    frame = pd.DataFrame(out)
    frame["market_code"] = frame["market"].map({m: i for i, m in enumerate(R0_MARKETS)}).astype(float)
    if frame["market_code"].isna().any():
        raise PooledModelError("a pooled row has a market outside the US 11")
    frame["y"] = frame["y"].astype(float)
    return frame, np.array(common)


def _num(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return out if math.isfinite(out) else float("nan")


class MeanModel:
    """Steps 1-4 of the rule: in-fold bias, OLS on the floor gap, HGB on its residual."""

    def __init__(self, *, market_id, doy):
        self.market_id = market_id
        self.doy = doy

    def _anchors(self, frame):
        import numpy as np

        keys_b = list(zip(frame["market"], frame["season"]))
        keys_n = list(zip(frame["market"], frame["centre"]))
        bias = np.array([self.bias.get(k, self.bias_global) for k in keys_b])
        normal = np.array([self.normal.get(k, self.normal_by_market.get(k[0], self.normal_global)) for k in keys_n])
        fh = frame["fh"].to_numpy(dtype=float)
        mu0 = np.where(np.isfinite(fh), fh + bias, normal)
        g = frame["F"].to_numpy(dtype=float) - mu0
        g = np.where(np.isfinite(g), g, 0.0)
        return mu0, g, bias, normal

    def features(self, frame):
        import numpy as np

        mu0, g, bias, normal = self._anchors(frame)
        cols = [frame[c].to_numpy(dtype=float) for c in self.x_columns]
        for level in LEVEL_COLUMNS:
            name = f"x_{level}"
            if name in frame:
                cols.append(frame[name].to_numpy(dtype=float) - mu0)
        cols += [g, np.maximum(g, 0.0), mu0 - normal,
                 frame["lat"].to_numpy(float), frame["lon"].to_numpy(float), frame["elev"].to_numpy(float),
                 normal, bias]
        if self.doy:
            cols += [frame["doy_sin"].to_numpy(float), frame["doy_cos"].to_numpy(float)]
        if self.market_id:
            cols.append(frame["market_code"].to_numpy(float))
        return np.column_stack(cols), mu0, g

    def fit(self, frame):
        import numpy as np
        from sklearn.ensemble import HistGradientBoostingRegressor

        has_fh = frame["fh"].notna()
        diff = (frame["y"] - frame["fh"])[has_fh]
        self.bias = diff.groupby([frame["market"][has_fh], frame["season"][has_fh]]).mean().to_dict()
        self.bias_global = float(diff.mean()) if len(diff) else 0.0
        self.normal = frame.groupby(["market", "centre"])["y"].mean().to_dict()
        self.normal_by_market = frame.groupby("market")["y"].mean().to_dict()
        self.normal_global = float(frame["y"].mean())
        self.x_columns = [c for c in frame.columns if c.startswith("x_")]
        X, mu0, g = self.features(frame)
        r = frame["y"].to_numpy(float) - mu0
        design = np.column_stack([np.ones_like(g), g, np.maximum(g, 0.0)])
        self.ols, *_ = np.linalg.lstsq(design, r, rcond=None)
        resid = r - design @ self.ols
        cat = [X.shape[1] - 1] if self.market_id else None
        self.hgb = HistGradientBoostingRegressor(categorical_features=cat, **MEAN_HGB_PARAMS)
        self.hgb.fit(X, resid)
        return self

    def predict(self, frame):
        import numpy as np

        X, mu0, g = self.features(frame)
        design = np.column_stack([np.ones_like(g), g, np.maximum(g, 0.0)])
        return mu0 + design @ self.ols + self.hgb.predict(X), X


def fit_pooled(train, *, market_id, doy):
    """Mean model on all training rows plus an inner-LOYO scale model and z set."""
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingRegressor

    errors = np.full(len(train), np.nan)
    years = sorted(train["year"].unique())
    if len(years) < 2:
        raise PooledModelError("the scale model needs at least two training years")
    for year in years:
        inner = (train["year"] != year).to_numpy()
        model = MeanModel(market_id=market_id, doy=doy).fit(train[inner])
        pred, _ = model.predict(train[~inner])
        errors[~inner] = train["y"].to_numpy(float)[~inner] - pred
    mean = MeanModel(market_id=market_id, doy=doy).fit(train)
    X, _, _ = mean.features(train)
    yhat_oof = train["y"].to_numpy(float) - errors
    floor_gap = np.nan_to_num(yhat_oof - train["F"].to_numpy(float), nan=0.0)
    scale = HistGradientBoostingRegressor(**SCALE_HGB_PARAMS)
    scale.fit(np.column_stack([X, floor_gap]), np.abs(errors))
    s_train = np.maximum(MIN_SCALE, scale.predict(np.column_stack([X, floor_gap])) * math.sqrt(math.pi / 2))
    return {"mean": mean, "scale": scale, "z": errors / s_train}


def predictive_distribution(yhat, s, floor, z, bucket_space, p_clim):
    """Kernel-smoothed standardised errors, floor-censored, 2% climatology mix."""
    import numpy as np
    from scipy.special import ndtr

    lo = math.floor(yhat + s * (float(np.min(z)) - 1.5))
    hi = math.ceil(yhat + s * (float(np.max(z)) + 1.5))
    ks = np.arange(lo, hi + 1)
    edges = np.append(ks - 0.5, hi + 0.5)
    t = (edges - yhat) / s
    cdf = ndtr((t[:, None] - z[None, :]) / KERNEL_BANDWIDTH).mean(axis=1)
    mass = np.diff(cdf)
    mass = mass / mass.sum()
    dist = {int(k): float(m) for k, m in zip(ks, mass)}
    if floor is not None and math.isfinite(floor):
        from weather.units import round_half_up

        fb = int(round_half_up(floor))
        below = sum(v for k, v in dist.items() if k < fb)
        dist = {k: v for k, v in dist.items() if k >= fb}
        dist[fb] = dist.get(fb, 0.0) + below
    out = {k: (1.0 - FLOOR_MIX_CLIM) * v for k, v in dist.items()}
    for k, v in p_clim.items():
        out[int(k)] = out.get(int(k), 0.0) + FLOOR_MIX_CLIM * float(v)
    total = sum(out.values())
    return {k: v / total for k, v in out.items()}


def score_pooled_arm(arm, frame, validation_payloads, hours=None):
    """Per-row losses of one pooled arm on the validation (11-24) rows."""
    import numpy as np
    from weather.calibration import feature_model as fm

    spec = ARMS[arm]
    usable = frame[frame["centre"].isin(spec["centres"])]
    val_all = frame[frame["centre"] == VALIDATION_CENTRE]
    buckets = {p["market"]: p["bucket_space"] for p in validation_payloads}
    rows = []
    for hour in sorted(set(val_all["hour"]) if hours is None else hours):
        at_hour = usable[usable["hour"] == hour]
        val_hour = val_all[val_all["hour"] == hour]
        for year in sorted(val_hour["year"].unique()):
            train = at_hour[at_hour["year"] != year].reset_index(drop=True)
            val = val_hour[val_hour["year"] == year].reset_index(drop=True)
            fitted = fit_pooled(train, market_id=spec["market_id"], doy=spec["doy"])
            yhat, X = fitted["mean"].predict(val)
            gap = np.nan_to_num(yhat - val["F"].to_numpy(float), nan=0.0)
            s = np.maximum(MIN_SCALE, fitted["scale"].predict(np.column_stack([X, gap])) * math.sqrt(math.pi / 2))
            clim_train = train[train["centre"] == VALIDATION_CENTRE]
            for i in range(len(val)):
                market = val.at[i, "market"]
                p_clim = fm.smoothed_dist(
                    [int(v) for v in clim_train.loc[clim_train["market"] == market, "y"]],
                    buckets[market], alpha=0.10,
                )
                dist = predictive_distribution(
                    float(yhat[i]), float(s[i]), float(val.at[i, "F"]), fitted["z"], buckets[market], p_clim,
                )
                actual = int(val.at[i, "y"])
                rows.append({
                    "market": market, "hour": int(hour),
                    "validation_date": val.at[i, "target_date"], "validation_year": int(year),
                    f"{arm}_log_loss": fm.log_loss(dist, actual),
                    f"{arm}_brier": fm.brier_score(dist, actual),
                    f"{arm}_mean": float(yhat[i]), f"{arm}_scale": float(s[i]),
                })
    return rows


# ----------------------------------------------------------------------- report


def bootstrap_deltas(rows, arm, *, hours=WINDOW_HOURS, metric="log_loss", draws=BOOTSTRAP_DRAWS,
                     seed=BOOTSTRAP_SEED, crossed=False):
    """Fleet and per-market paired deltas (arm - R0) with date-cluster bootstrap draws."""
    import numpy as np

    sel = [r for r in rows if r["hour"] in hours]
    markets = sorted({r["market"] for r in sel})
    dates = sorted({r["validation_date"] for r in sel})
    d_idx = {d: i for i, d in enumerate(dates)}
    m_idx = {m: i for i, m in enumerate(markets)}
    sums = np.zeros((len(markets), len(dates)))
    counts = np.zeros((len(markets), len(dates)))
    for r in sel:
        delta = r[f"{arm}_{metric}"] - r[f"R0_{metric}"]
        sums[m_idx[r["market"]], d_idx[r["validation_date"]]] += delta
        counts[m_idx[r["market"]], d_idx[r["validation_date"]]] += 1
    per_market = sums.sum(axis=1) / counts.sum(axis=1)
    rng = np.random.default_rng(seed)
    fleet_draws = np.empty(draws)
    market_draws = np.empty((draws, len(markets)))
    for b in range(draws):
        w = np.bincount(rng.integers(0, len(dates), len(dates)), minlength=len(dates))
        with np.errstate(invalid="ignore", divide="ignore"):
            pm = (sums * w).sum(axis=1) / (counts * w).sum(axis=1)
        market_draws[b] = pm
        if crossed:
            mw = np.bincount(rng.integers(0, len(markets), len(markets)), minlength=len(markets))
            fleet_draws[b] = np.nansum(pm * mw) / mw[np.isfinite(pm)].sum()
        else:
            fleet_draws[b] = np.nanmean(pm)
    return {
        "markets": markets, "dates": len(dates), "rows": len(sel),
        "per_market": dict(zip(markets, per_market.tolist())),
        "fleet": float(np.mean(per_market)),
        "fleet_draws": fleet_draws, "market_draws": market_draws,
    }


def percentile_ci(values, level):
    import numpy as np

    tail = (1.0 - level) / 2.0 * 100.0
    return float(np.nanpercentile(values, tail)), float(np.nanpercentile(values, 100.0 - tail))


def decide(rows, arms):
    """Apply the pre-declared rule (C:\\t\\l2\\rule.md)."""
    level_fleet = 1.0 - 0.05 / len(ARMS)
    verdicts = {}
    for arm in arms:
        boot = bootstrap_deltas(rows, arm)
        fleet_ci = percentile_ci(boot["fleet_draws"], level_fleet)
        worse = []
        market_ci = {}
        for j, market in enumerate(boot["markets"]):
            ci = percentile_ci(boot["market_draws"][:, j], 0.95)
            market_ci[market] = ci
            if ci[0] > 0:
                worse.append(market)
        verdicts[arm] = {
            "fleet_delta": boot["fleet"], "fleet_ci_bonferroni": fleet_ci,
            "fleet_ci_95": percentile_ci(boot["fleet_draws"], 0.95),
            "markets_worse": worse, "per_market": boot["per_market"], "market_ci_95": market_ci,
            "passes": fleet_ci[1] < 0 and not worse,
            "dates": boot["dates"], "rows": boot["rows"],
        }
    passing = [a for a in arms if verdicts[a]["passes"]]
    pick = min(passing, key=lambda a: (verdicts[a]["fleet_delta"], list(ARMS).index(a))) if passing else None
    return verdicts, pick


def merge_rows(r0_rows, arm_rows):
    """Join per-row losses on (market, hour, validation_date); keys must match exactly."""
    key = lambda r: (r["market"], r["hour"], r["validation_date"])  # noqa: E731
    merged = {key(r): dict(r) for r in r0_rows}
    for arm, rows in arm_rows.items():
        keys = {key(r) for r in rows}
        if keys != set(merged):
            raise PooledModelError(f"{arm} rows do not match R0 rows ({len(keys)} vs {len(merged)})")
        for r in rows:
            merged[key(r)].update({k: v for k, v in r.items() if k.startswith(arm + "_")})
    return list(merged.values())


def _read_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_jsonl(path, rows):
    if Path(path).exists():
        raise PooledModelError(f"refusing to overwrite {path}")
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def report_markdown(rows, arms, rule_path):
    verdicts, pick = decide(rows, arms)
    rule_sha = hashlib.sha256(Path(rule_path).read_bytes()).hexdigest() if rule_path else None
    lines = [f"# L2 pooled residual model vs R0 (leaf 20), centre {VALIDATION_CENTRE}", "",
             f"Rule: {rule_path} sha256 {rule_sha}", ""]
    lines += ["## Decision (07-12, log loss, arm - R0; negative = arm better)", "",
              "| Arm | fleet delta | Bonferroni CI (98.75%) | 95% CI | markets CI-worse | passes |",
              "| --- | --- | --- | --- | --- | --- |"]
    for arm in arms:
        v = verdicts[arm]
        lines.append(f"| {arm} | {v['fleet_delta']:+.4f} | [{v['fleet_ci_bonferroni'][0]:+.4f}, "
                     f"{v['fleet_ci_bonferroni'][1]:+.4f}] | [{v['fleet_ci_95'][0]:+.4f}, {v['fleet_ci_95'][1]:+.4f}] | "
                     f"{', '.join(v['markets_worse']) or 'none'} | {v['passes']} |")
    lines += ["", f"Pick: {pick or 'none (KILL)'}; date clusters {verdicts[arms[0]]['dates']}, "
              f"markets {len(verdicts[arms[0]]['per_market'])}, rows {verdicts[arms[0]]['rows']}.", ""]
    if pick:
        crossed = bootstrap_deltas(rows, pick, crossed=True)
        ci = percentile_ci(crossed["fleet_draws"], 0.95)
        lines += [f"Robustness (crossed date x market, 95%): [{ci[0]:+.4f}, {ci[1]:+.4f}]"
                  + (" -- includes 0" if ci[0] <= 0 <= ci[1] else ""), ""]
    lines += ["## Per market, 07-12 log loss delta (95% date-clustered CI)", "",
              "| Market | " + " | ".join(arms) + " |", "| --- |" + " --- |" * len(arms)]
    for market in verdicts[arms[0]]["per_market"]:
        cells = []
        for arm in arms:
            v = verdicts[arm]
            lo, hi = v["market_ci_95"][market]
            cells.append(f"{v['per_market'][market]:+.3f} [{lo:+.3f}, {hi:+.3f}]")
        lines.append(f"| {market} | " + " | ".join(cells) + " |")
    for metric in ("log_loss", "brier"):
        lines += ["", f"## Per hour, fleet {metric} delta vs R0 (95% date-clustered CI); levels", "",
                  "| Hour | R0 | baseline-R0 | " + " | ".join(f"{a}-R0" for a in arms) + " |",
                  "| --- | --- | --- |" + " --- |" * len(arms)]
        for hour in sorted({r["hour"] for r in rows}):
            hr = [r for r in rows if r["hour"] == hour]
            r0 = sum(r[f"R0_{metric}"] for r in hr) / len(hr)
            cells = []
            for arm in ["baseline"] + list(arms):
                b = bootstrap_deltas(rows, arm, hours=(hour,), metric=metric)
                lo, hi = percentile_ci(b["fleet_draws"], 0.95)
                cells.append(f"{b['fleet']:+.3f} [{lo:+.3f}, {hi:+.3f}]")
            tag = " (07-12)" if hour in WINDOW_HOURS else ""
            lines.append(f"| {hour:02d}{tag} | {r0:.3f} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n", verdicts, pick


# -------------------------------------------------------------------------- CLI


def _parse(argv=None):
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.pooled_residual_model",
                                     description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract", help="trainer records for markets x centres (heavy)")
    ex.add_argument("--markets", default=",".join(R0_MARKETS))
    ex.add_argument("--centres", default=VALIDATION_CENTRE)
    ex.add_argument("--manifest", action="append", required=True, dest="manifests")
    ex.add_argument("--out", required=True)
    ev = sub.add_parser("evaluate", help="R0 and pooled arms on identical rows (heavy)")
    ev.add_argument("--records", required=True)
    ev.add_argument("--arms", default="R0,P0,P1")
    ev.add_argument("--markets", default=",".join(R0_MARKETS))
    ev.add_argument("--hours", default=None, help="comma list (smoke slices only)")
    ev.add_argument("--lane-d-root", default=None)
    ev.add_argument("--out", required=True)
    rp = sub.add_parser("report", help="paired deltas, CIs and the pre-declared decision")
    rp.add_argument("--rows", required=True)
    rp.add_argument("--arms", default="P0,P1,P2,P3")
    rp.add_argument("--rule", required=True)
    rp.add_argument("--out", required=True)
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse(argv)
    if args.command == "extract":
        for centre in args.centres.split(","):
            for market in args.markets.split(","):
                path, info = extract_market(market, centre, args.manifests, args.out)
                print(f"extracted {market} {centre}: {info['days_by_year']} union {info['union_sha256']} -> {path}",
                      flush=True)
        return 0
    out = require_output_outside_repo(args.out)
    if args.command == "evaluate":
        out.mkdir(parents=True, exist_ok=True)
        markets = args.markets.split(",")
        arms = args.arms.split(",")
        hours = [int(h) for h in args.hours.split(",")] if args.hours else None
        val_payloads = [load_records(args.records, m, VALIDATION_CENTRE) for m in markets]
        if hours:
            for p in val_payloads:
                p["records"] = {h: r for h, r in p["records"].items() if h in hours}
        if "R0" in arms:
            r0_rows, parity = [], {}
            for payload in val_payloads:
                rows = score_r0_market(payload)
                r0_rows += rows
                lane = Path(args.lane_d_root or "") / payload["market"] / (
                    f"feature_model_blocked_validation_rows_{payload['market']}.jsonl")
                if args.lane_d_root and lane.is_file() and not hours:
                    parity[payload["market"]] = r0_parity(rows, lane)
                print(f"R0 {payload['market']}: {len(rows)} rows parity {parity.get(payload['market'])}", flush=True)
            _write_jsonl(out / "rows_R0.jsonl", r0_rows)
            (out / "r0_parity.json").write_text(json.dumps(parity, indent=1), encoding="utf-8")
        pooled = [a for a in arms if a in ARMS]
        if pooled:
            centres = sorted({c for a in pooled for c in ARMS[a]["centres"]})
            payloads = list(val_payloads)
            for centre in centres:
                if centre != VALIDATION_CENTRE:
                    payloads += [load_records(args.records, m, centre) for m in markets]
            frame, common = pooled_frame(payloads, station_coordinates(markets))
            print(f"pooled frame {len(frame)} rows, {len(common)} common columns", flush=True)
            for arm in pooled:
                rows = score_pooled_arm(arm, frame, val_payloads, hours=hours)
                _write_jsonl(out / f"rows_{arm}.jsonl", rows)
                print(f"{arm}: {len(rows)} rows", flush=True)
        return 0
    if args.command == "report":
        rows_dir = Path(args.rows)
        arms = args.arms.split(",")
        r0 = _read_jsonl(rows_dir / "rows_R0.jsonl")
        arm_rows = {a: _read_jsonl(rows_dir / f"rows_{a}.jsonl") for a in arms}
        rows = merge_rows(r0, arm_rows)
        text, verdicts, pick = report_markdown(rows, arms, args.rule)
        if out.exists():
            raise PooledModelError(f"refusing to overwrite {out}")
        out.write_text(text, encoding="utf-8")
        print(text)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
