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
``dev-emit`` / ``dev-emit-n``
    Dev-window candidate vectors: P3d/U0d (amendment 3) and P3d_N (amendment 5: anchored on the
    captured NBM 07Z mean, METAR-only running max) in the dev scorecard's candidate format.
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
import os
from pathlib import Path

# Master ruling 10-24: fits use at most 10 OpenMP threads (32 logical cores / 3 slots).
for _threads_var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_threads_var, "10")

from weather.paths import CONFIG_ROOT, REPO_ROOT  # noqa: E402


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
JAN_JUL_CENTRES = (
    "2026-01-08", "2026-01-23", "2026-02-07", "2026-02-22", "2026-03-09", "2026-03-24", "2026-04-08",
    "2026-04-23", "2026-05-08", "2026-05-23", "2026-06-07", "2026-06-22", "2026-07-07", "2026-07-22",
)
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
DECISION_ARMS = ("P0", "P1", "P2", "P3")  # the original rule's Bonferroni family (fixed)
# Amendment 2: the P0 design fitted per market (the pooling control).
EXTRA_ARMS = {
    "U0": {"centres": (VALIDATION_CENTRE,), "market_id": False, "doy": False, "per_market": True},
    # Amendment 4: full year (L1's corpus), bias and normal per (market, cutoff, centre).
    "P3F": {"centres": JAN_JUL_CENTRES + AUG_SEP_CENTRES + OCT_DEC_CENTRES, "market_id": False, "doy": True,
            "bias_by": "centre"},
}
ALL_POOLED_ARMS = {**ARMS, **EXTRA_ARMS}
# Amendment 2 comparators from lane L3 (171717d5f): our column prefix -> L3 arm name.
L3_COMPARATORS = {
    "a": "ols_floor",
    "e": "r0_baseline_floor",
    "f": "bias_corrected_forecast_floor",
    "r0floor": "r0_floor",
    "l3r0": "r0_repro",
}
HEADLINE_REFS = ("a", "f")
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
    month = str(centre)[5:7]
    if month in ("08", "09"):
        return "aug_sep"
    return "oct_dec" if month in ("10", "11", "12") else "jan_jul"


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


def window_days(centre, year, half_width=7):
    from datetime import timedelta

    c = date.fromisoformat(str(centre))
    mid = date(int(year), c.month, c.day)
    return [mid + timedelta(days=k) for k in range(-half_width, half_width + 1)]


def covered_years(centre, manifests, markets=R0_MARKETS, hours=range(7, 21)):
    """Amendment 4: years whose corpus has a complete row at every cutoff for every market and window day."""
    complete = set()
    years = set()
    for manifest in manifests:
        root = Path(manifest).parent
        years.update(int(y) for y in json.loads(Path(manifest).read_text(encoding="utf-8"))["years"])
        with open(root / "coverage.jsonl", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if row.get("status") == "complete" and row.get("market_id") in markets:
                    complete.add((row["market_id"], str(row["target_date"])[:10], int(row["cutoff_hour_local"])))
    return sorted(
        y for y in years
        if all((m, d.isoformat(), h) in complete for m in markets for d in window_days(centre, y) for h in hours)
    )


def extract_market(market, centre, manifests, out_root, training_years=None):
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
        cache["daily"], training_years=training_years, forecast_years=union.years, target_date=centre_date,
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


def extract_many(markets, centres, manifests, out_root, coverage_years=False):
    """Extract every (market, centre); a fail-closed corpus gap skips that pair, never relaxes it.

    ``coverage_years`` (amendment 4) restricts each centre to the years its corpora fully cover.
    """
    from weather.sources.forecast_training_corpus import CorpusVerificationError

    failed = []
    for centre in centres:
        years = covered_years(centre, manifests) if coverage_years else None
        if coverage_years:
            print(f"centre {centre}: covered years {years}", flush=True)
            if not years:
                failed += [(m, centre, "no covered year") for m in markets]
                continue
        for market in markets:
            if records_path(out_root, market, centre).exists():
                print(f"present {market} {centre}", flush=True)
                continue
            try:
                path, info = extract_market(market, centre, manifests, out_root, training_years=years)
            except CorpusVerificationError as exc:
                failed.append((market, centre, str(exc)))
                print(f"FAILED_CLOSED {market} {centre}: {exc}", flush=True)
                continue
            print(f"extracted {market} {centre}: {info['days_by_year']} union {info['union_sha256']} -> {path}",
                  flush=True)
    return failed


def complete_centres(root, markets, centres):
    """Centres with a records file for every market; the rest are dropped whole (rule amendment)."""
    kept, dropped = [], []
    for centre in centres:
        (kept if all(records_path(root, m, centre).exists() for m in markets) else dropped).append(centre)
    return kept, dropped


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

    def __init__(self, *, market_id, doy, raw_columns=True, bias_by="season", use_hgb=True, extra_ols=(),
                 extra_hgb=()):
        self.use_hgb = use_hgb
        self.extra_ols = tuple(extra_ols)  # rung R-G: columns added to the OLS design (NaN -> 0)
        self.extra_hgb = tuple(extra_hgb)  # rung R-G: columns added to the HGB residual / scale inputs
        self.market_id = market_id
        self.doy = doy
        self.raw_columns = raw_columns
        if bias_by not in ("season", "centre"):
            raise PooledModelError(f"unknown bias key {bias_by}")
        self.bias_by = bias_by

    def _anchors(self, frame):
        import numpy as np

        keys_b = list(zip(frame["market"], frame[self.bias_by]))
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
        cols += [frame[c].to_numpy(float) for c in getattr(self, "extra_hgb", ())]
        if self.market_id:
            cols.append(frame["market_code"].to_numpy(float))
        return np.column_stack(cols), mu0, g

    def _design(self, frame, g):
        import numpy as np

        extra = [np.nan_to_num(frame[c].to_numpy(float), nan=0.0) for c in getattr(self, "extra_ols", ())]
        return np.column_stack([np.ones_like(g), g, np.maximum(g, 0.0)] + extra)

    def fit(self, frame):
        import numpy as np
        from sklearn.ensemble import HistGradientBoostingRegressor

        has_fh = frame["fh"].notna()
        diff = (frame["y"] - frame["fh"])[has_fh]
        self.bias = diff.groupby([frame["market"][has_fh], frame[self.bias_by][has_fh]]).mean().to_dict()
        self.bias_global = float(diff.mean()) if len(diff) else 0.0
        self.normal = frame.groupby(["market", "centre"])["y"].mean().to_dict()
        self.normal_by_market = frame.groupby("market")["y"].mean().to_dict()
        self.normal_global = float(frame["y"].mean())
        self.x_columns = [c for c in frame.columns if c.startswith("x_")] if self.raw_columns else []
        X, mu0, g = self.features(frame)
        r = frame["y"].to_numpy(float) - mu0
        design = self._design(frame, g)
        self.ols, *_ = np.linalg.lstsq(design, r, rcond=None)
        resid = r - design @ self.ols
        if not getattr(self, "use_hgb", True):
            self.hgb = None
            return self
        cat = [X.shape[1] - 1] if self.market_id else None
        self.hgb = HistGradientBoostingRegressor(categorical_features=cat, **MEAN_HGB_PARAMS)
        self.hgb.fit(X, resid)
        return self

    def predict(self, frame):
        import numpy as np

        X, mu0, g = self.features(frame)
        design = self._design(frame, g)
        resid = self.hgb.predict(X) if self.hgb is not None else 0.0
        return mu0 + design @ self.ols + resid, X


class ConstantScale:
    """Rung 07-12 baseline B_N: one scale per fit (mean absolute inner-LOYO error), no model."""

    def __init__(self, value):
        self.value = float(value)

    def predict(self, X):
        import numpy as np

        return np.full(len(X), self.value)


def fit_pooled(train, *, market_id, doy, raw_columns=True, bias_by="season", simple=False, extra_ols=(),
               extra_hgb=()):
    """Mean model on all training rows plus an inner-LOYO scale model and z set.

    ``simple`` (rung 07-12 baseline B_N): OLS on [1, g, max(g, 0)] only (no HGB residual) and a constant
    scale, so mean = nbm_mean + bias + OLS; z = errors / that constant scale.
    """
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingRegressor

    errors = np.full(len(train), np.nan)
    years = sorted(train["year"].unique())
    if len(years) < 2:
        raise PooledModelError("the scale model needs at least two training years")
    for year in years:
        inner = (train["year"] != year).to_numpy()
        model = MeanModel(market_id=market_id, doy=doy, raw_columns=raw_columns, bias_by=bias_by,
                          use_hgb=not simple, extra_ols=extra_ols, extra_hgb=extra_hgb).fit(train[inner])
        pred, _ = model.predict(train[~inner])
        errors[~inner] = train["y"].to_numpy(float)[~inner] - pred
    mean = MeanModel(market_id=market_id, doy=doy, raw_columns=raw_columns, bias_by=bias_by,
                     use_hgb=not simple, extra_ols=extra_ols, extra_hgb=extra_hgb).fit(train)
    if simple:
        scale = ConstantScale(np.nanmean(np.abs(errors)))
        s_train = max(MIN_SCALE, scale.value * math.sqrt(math.pi / 2))
        return {"mean": mean, "scale": scale, "z": errors / s_train}
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

    spec = ALL_POOLED_ARMS[arm]
    usable = frame[frame["centre"].isin(spec["centres"])]
    val_all = frame[frame["centre"] == VALIDATION_CENTRE]
    buckets = {p["market"]: p["bucket_space"] for p in validation_payloads}
    rows = []
    for hour in sorted(set(val_all["hour"]) if hours is None else hours):
        at_hour = usable[usable["hour"] == hour]
        val_hour = val_all[val_all["hour"] == hour]
        for year in sorted(val_hour["year"].unique()):
            train_all = at_hour[at_hour["year"] != year]
            val_all_year = val_hour[val_hour["year"] == year]
            groups = (
                [(m, train_all[train_all["market"] == m], val_all_year[val_all_year["market"] == m])
                 for m in sorted(val_all_year["market"].unique())]
                if spec.get("per_market") else [(None, train_all, val_all_year)]
            )
            for _, train, val in groups:
                rows += _score_fold(arm, spec, train.reset_index(drop=True), val.reset_index(drop=True),
                                    buckets, hour, year)
    return rows


def _score_fold(arm, spec, train, val, buckets, hour, year):
    import numpy as np
    from weather.calibration import feature_model as fm

    rows = []
    fitted = fit_pooled(train, market_id=spec["market_id"], doy=spec["doy"], bias_by=spec.get("bias_by", "season"))
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


def score_l3_comparators(markets, manifests, target_date=VALIDATION_CENTRE):
    """Lane L3's arms on the trainer's rows, via its own ``score_market`` (imported, not forked)."""
    from weather.calibration import r0_ols_floor_challenger as l3

    rows, metas = [], {}
    for market in markets:
        l3_rows, meta = l3.score_market(market, date.fromisoformat(str(target_date)), list(manifests))
        metas[market] = meta
        for r in l3_rows:
            out = {"market": market, "hour": int(r["hour"]), "validation_date": str(r["validation_date"]),
                   "validation_year": int(r["validation_year"])}
            for ours, theirs in L3_COMPARATORS.items():
                out[f"{ours}_log_loss"] = float(r[f"{theirs}_log_loss"])
                out[f"{ours}_brier"] = float(r[f"{theirs}_brier"])
            rows.append(out)
        print(f"L3 comparators {market}: {len(l3_rows)} rows", flush=True)
    return rows, metas


def l3_parity(r0_rows, l3_rows, tolerance=1e-9):
    """Amendment 2 row gate: identical keys and L3's R0 reproduction equal to ours per row."""
    key = lambda r: (r["market"], r["hour"], r["validation_date"])  # noqa: E731
    ours = {key(r): r["R0_log_loss"] for r in r0_rows}
    theirs = {key(r): r["l3r0_log_loss"] for r in l3_rows}
    if set(ours) != set(theirs):
        return {"keys_match": False, "ours": len(ours), "theirs": len(theirs), "max_abs_diff": None, "ok": False}
    diff = max(abs(ours[k] - theirs[k]) for k in ours) if ours else 0.0
    return {"keys_match": True, "rows": len(ours), "max_abs_diff": diff, "ok": diff <= tolerance}


# ----------------------------------------------------------------------- report


def bootstrap_deltas(rows, arm, *, hours=WINDOW_HOURS, metric="log_loss", draws=BOOTSTRAP_DRAWS,
                     seed=BOOTSTRAP_SEED, crossed=False, ref="R0"):
    """Fleet and per-market paired deltas (arm - ref) with date-cluster bootstrap draws."""
    import numpy as np

    sel = [r for r in rows if r["hour"] in hours]
    markets = sorted({r["market"] for r in sel})
    dates = sorted({r["validation_date"] for r in sel})
    d_idx = {d: i for i, d in enumerate(dates)}
    m_idx = {m: i for i, m in enumerate(markets)}
    sums = np.zeros((len(markets), len(dates)))
    counts = np.zeros((len(markets), len(dates)))
    for r in sel:
        delta = r[f"{arm}_{metric}"] - r[f"{ref}_{metric}"]
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
    level_fleet = 1.0 - 0.05 / len(DECISION_ARMS)
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


def attach_lane_d_floor(rows, root):
    """Descriptive: lane D's floored R0 rows as ``dfloor_*`` where its file exists."""
    for market in sorted({r["market"] for r in rows}):
        path = Path(root) / market / f"feature_model_blocked_validation_rows_{market}.jsonl"
        if not path.is_file():
            continue
        theirs = {(int(x["hour"]), str(x["validation_date"])): x for x in _read_jsonl(path)}
        for r in rows:
            x = theirs.get((r["hour"], r["validation_date"])) if r["market"] == market else None
            if x is not None and "hgb_floored_log_loss" in x:
                r["dfloor_log_loss"] = float(x["hgb_floored_log_loss"])
                if "hgb_floored_brier" in x:
                    r["dfloor_brier"] = float(x["hgb_floored_brier"])


def headline_rows(row_dirs, lane_d_floor_root=None, arm="P3", extra=("U0",)):
    """Merge R0, P3, U0 and L3 rows; the amendment 2 row gate must hold."""
    def find(name):
        for d in row_dirs:
            if (Path(d) / name).is_file():
                return Path(d) / name
        raise PooledModelError(f"{name} not found in {row_dirs}")

    r0 = _read_jsonl(find("rows_R0.jsonl"))
    l3_rows = _read_jsonl(find("rows_L3.jsonl"))
    gate = l3_parity(r0, l3_rows)
    if not gate["ok"]:
        raise PooledModelError(f"amendment 2 row gate failed: {gate}")
    names = [arm, *extra] if arm == "P3" else [arm, "P3", *extra]
    rows = merge_rows(r0, {a: _read_jsonl(find(f"rows_{a}.jsonl")) for a in dict.fromkeys(names)})
    by_key = {(r["market"], r["hour"], r["validation_date"]): r for r in l3_rows}
    for r in rows:
        extra = by_key[(r["market"], r["hour"], r["validation_date"])]
        r.update({k: v for k, v in extra.items() if k.endswith(("_log_loss", "_brier")) and not k.startswith("R0_")})
    if lane_d_floor_root:
        attach_lane_d_floor(rows, lane_d_floor_root)
    return rows, gate


def headline_verdict(rows, arm="P3", ref="a", n_refs=len(HEADLINE_REFS)):
    """Amendment 2: fleet (1 - 0.05/n_refs) interval below 0 and no market 95% interval above 0."""
    boot = bootstrap_deltas(rows, arm, ref=ref)
    fleet_ci = percentile_ci(boot["fleet_draws"], 1.0 - 0.05 / n_refs)
    market_ci = {m: percentile_ci(boot["market_draws"][:, j], 0.95) for j, m in enumerate(boot["markets"])}
    worse = [m for m, ci in market_ci.items() if ci[0] > 0]
    if fleet_ci[1] < 0 and not worse:
        word = "beats"
    elif fleet_ci[0] > 0:
        word = "is worse than"
    else:
        word = "does not beat"
    return {"fleet": boot["fleet"], "fleet_ci": fleet_ci, "per_market": boot["per_market"],
            "market_ci": market_ci, "markets_worse": worse, "verdict": f"{arm} {word} {ref}",
            "dates": boot["dates"], "rows": boot["rows"]}


def headline_markdown(rows, rule_path, gate, head="P3"):
    third = ("U0", "P3") if head == "P3" else (head, "P3")
    rule_sha = hashlib.sha256(Path(rule_path).read_bytes()).hexdigest()
    lines = [f"# L2 amendment 2/4: {head} vs fair comparators (centre 2026-11-24, US 11)", "",
             f"Rule: {rule_path} sha256 {rule_sha}", "",
             f"Row gate (L3 rows == R0 rows, L3 r0_repro == L2 R0): {json.dumps(gate)}", "",
             "Refs: a = L3 ols_floor, e = r0_baseline_floor, f = bias_corrected_forecast_floor, "
             "r0floor = R0 + hard floor, dfloor = lane D floored R0 (where present), R0 = raw R0.", "",
             f"## Headline (07-12, log loss, {head} - ref; 97.5% Bonferroni fleet interval)", "",
             "| Comparison | fleet delta | 97.5% CI | markets CI-worse | verdict |", "| --- | --- | --- | --- | --- |"]
    v = None
    for ref in HEADLINE_REFS:
        v = headline_verdict(rows, head, ref)
        lines.append(f"| {head} - {ref} | {v['fleet']:+.4f} | [{v['fleet_ci'][0]:+.4f}, {v['fleet_ci'][1]:+.4f}] | "
                     f"{', '.join(v['markets_worse']) or 'none'} | {v['verdict']} |")
        crossed = bootstrap_deltas(rows, head, ref=ref, crossed=True)
        ci = percentile_ci(crossed["fleet_draws"], 0.95)
        lines.append(f"| (crossed date x market 95%) | | [{ci[0]:+.4f}, {ci[1]:+.4f}] | | |")
    lines += ["", f"Date clusters {v['dates']}, rows {v['rows']}.", ""]
    pairs = [(head, r) for r in ("a", "f", "e", "r0floor", "R0")] + (
        [("U0", "P3"), ("U0", "a"), ("U0", "f")] if head == "P3" else [(head, "P3")])
    if any("dfloor_log_loss" in r for r in rows):
        pairs.append((head, "dfloor"))
    lines += ["## Descriptive 07-12 fleet deltas (95% date-clustered)", "", "| Comparison | log loss | Brier |",
              "| --- | --- | --- |"]
    for arm, ref in pairs:
        sub = [r for r in rows if f"{ref}_log_loss" in r]
        cells = []
        for metric in ("log_loss", "brier"):
            if not all(f"{ref}_{metric}" in r for r in sub):
                cells.append("n/a")
                continue
            b = bootstrap_deltas(sub, arm, ref=ref, metric=metric)
            lo, hi = percentile_ci(b["fleet_draws"], 0.95)
            cells.append(f"{b['fleet']:+.4f} [{lo:+.4f}, {hi:+.4f}]")
        lines.append(f"| {arm} - {ref} ({len({r['market'] for r in sub})} mkts) | {cells[0]} | {cells[1]} |")
    lines += ["", "## Per market 07-12 log loss delta (95%)", "",
              f"| Market | {head} - a | {head} - f | {third[0]} - {third[1]} |", "| --- | --- | --- | --- |"]
    vs = {k: headline_verdict(rows, arm, ref) for k, (arm, ref) in
          {"a": (head, "a"), "f": (head, "f"), "u": third}.items()}
    for m in vs["a"]["per_market"]:
        cells = [f"{vs[k]['per_market'][m]:+.3f} [{vs[k]['market_ci'][m][0]:+.3f}, {vs[k]['market_ci'][m][1]:+.3f}]"
                 for k in ("a", "f", "u")]
        lines.append(f"| {m} | " + " | ".join(cells) + " |")
    lines += ["", "## Per hour, fleet log loss (levels) and deltas (95%); hour 12 called out", "",
              f"| Hour | {head} | a | f | e | {head} - a | {head} - f | {third[0]} - {third[1]} |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for hour in sorted({r["hour"] for r in rows}):
        hr = [r for r in rows if r["hour"] == hour]
        lv = [sum(r[f"{k}_log_loss"] for r in hr) / len(hr) for k in (head, "a", "f", "e")]
        cells = []
        for arm, ref in ((head, "a"), (head, "f"), third):
            b = bootstrap_deltas(rows, arm, ref=ref, hours=(hour,))
            lo, hi = percentile_ci(b["fleet_draws"], 0.95)
            cells.append(f"{b['fleet']:+.3f} [{lo:+.3f}, {hi:+.3f}]")
        tag = " **(12)**" if hour == 12 else (" (07-12)" if hour in WINDOW_HOURS else "")
        lines.append(f"| {hour:02d}{tag} | " + " | ".join(f"{x:.3f}" for x in lv) + " | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------- amendment 3: dev window

DEV_ARMS = {"P3d": False, "U0d": True}  # arm -> per market
DEV_KEEP_X = ("x_high_so_far", "x_current_temp")  # the serve-time inputs with parity (L3's main variant)


def nearest_centre(target_date, centres=AUG_SEP_CENTRES):
    """The Aug-Sep centre whose month-day is closest to ``target_date``'s (for the normal)."""
    d = date.fromisoformat(str(target_date)[:10])
    ref = date(2001, d.month, d.day)
    return min(centres, key=lambda c: abs((date(2001, int(c[5:7]), int(c[8:10])) - ref).days))


def dev_training_frame(records_root, markets=R0_MARKETS):
    """Every Aug-Sep 2021-25 record, reduced to the serve-parity inputs."""
    payloads = [load_records(records_root, m, c) for c in AUG_SEP_CENTRES for m in markets]
    frame, _ = pooled_frame(payloads, station_coordinates(markets))
    drop = [c for c in frame.columns if c.startswith("x_") and c not in DEV_KEEP_X]
    buckets = {p["market"]: p["bucket_space"] for p in payloads if p["centre"] == "2026-09-07"}
    return frame.drop(columns=drop), buckets


def dev_fits(frame, arm):
    """One fit per cutoff (P3d) or per (market, cutoff) (U0d), on all five training years."""
    per_market = DEV_ARMS[arm]
    fits = {}
    for hour in sorted(frame["hour"].unique()):
        at_hour = frame[frame["hour"] == hour]
        groups = [(m, at_hour[at_hour["market"] == m]) for m in sorted(at_hour["market"].unique())] \
            if per_market else [(None, at_hour)]
        for market, train in groups:
            train = train.reset_index(drop=True)
            fits[(int(hour), market)] = {
                "fit": fit_pooled(train, market_id=False, doy=True, raw_columns=False),
                "train_y": {m: [int(v) for v in train.loc[train["market"] == m, "y"]]
                            for m in train["market"].unique()},
            }
    return fits


def dev_emit_distributions(*, records_root, layout, replay_root, dev_manifest, out_dir, markets=R0_MARKETS):
    """Emit P3d and U0d distributions for the dev snapshots on lane L3's inputs (its helpers, unchanged)."""
    import numpy as np
    import pandas as pd
    from zoneinfo import ZoneInfo

    from weather.calibration import feature_model as fm
    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.calibration.feature_model_training_inputs import PITForecastCorpusUnion
    from weather.market.market_registry import spec_for_id
    from weather.model.toronto_model import INTRADAY_CUTOFF_HOURS

    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frame, buckets = dev_training_frame(records_root, markets)
    if frame["year"].max() >= 2026:
        raise PooledModelError("a dev training row is from 2026")
    fits = {arm: dev_fits(frame, arm) for arm in DEV_ARMS}
    coords = station_coordinates(markets)
    snaps = pd.read_parquet(Path(layout) / "inputs_snapshots.parquet", columns=[
        "snapshot_id", "market", "target_date", "local_hour", "cutoff_hour"])
    if (pd.to_datetime(snaps.target_date).dt.date > l3.DEV_LAST).any():
        raise PooledModelError("layout holds a snapshot after 2026-09-29")
    hours = {int(h) for h in INTRADAY_CUTOFF_HOURS}
    paths = {arm: out / f"dev_{arm}.jsonl" for arm in DEV_ARMS}
    for path in paths.values():
        if path.exists():
            raise PooledModelError(f"refusing to overwrite {path}")
    writers = {arm: open(path, "w", encoding="utf-8") for arm, path in paths.items()}
    audit = {"markets": {}, "training_rows": int(len(frame)), "train_years": sorted(int(y) for y in frame["year"].unique())}
    try:
        for market in markets:
            spec = spec_for_id(market)
            tz = ZoneInfo(spec.timezone)
            dev_union = PITForecastCorpusUnion([dev_manifest], spec.id, target_year=2027,
                                               required_cutoff_hours=INTRADAY_CUTOFF_HOURS)
            obs = {}
            for slug, target, folder in l3._event_folders(replay_root):
                if not (l3.DEV_FIRST <= target <= l3.DEV_LAST) or slug != market:
                    continue
                for hour, rec in l3.scan_replay_observations(folder, market, target, tz, hours).items():
                    obs[(target.isoformat(), hour)] = rec
            stats = defaultdict(int)
            lat, lon, elev = coords[market]
            for row in snaps[snaps.market == market].itertuples(index=False):
                try:
                    hour = int(str(row.cutoff_hour))
                except ValueError:
                    hour = None
                if hour not in hours:
                    stats["outside_cutoff_hours"] += 1
                    continue
                if int(row.local_hour) < hour:
                    stats["local_hour_before_cutoff"] += 1
                    continue
                key = (str(row.target_date)[:10], hour)
                rec = obs.get(key)
                if rec is None or rec["high_so_far"] is None:
                    stats["no_replay_observation"] += 1
                    continue
                fc = dev_union.resolve(key[0], hour)["forecast_high"]
                tdate = date.fromisoformat(key[0])
                doy = tdate.timetuple().tm_yday
                one = pd.DataFrame([{
                    "market": market, "centre": nearest_centre(key[0]), "season": "aug_sep", "hour": hour,
                    "target_date": key[0], "year": tdate.year, "y": float("nan"),
                    "F": _num(rec["high_so_far"]), "fh": _num(fc), "lat": lat, "lon": lon, "elev": elev,
                    "doy_sin": math.sin(2 * math.pi * doy / 365.25), "doy_cos": math.cos(2 * math.pi * doy / 365.25),
                    "x_high_so_far": _num(rec["high_so_far"]), "x_current_temp": _num(rec["current_temp"]),
                    "market_code": float(R0_MARKETS.index(market)),
                }])
                for arm, per_market in DEV_ARMS.items():
                    entry = fits[arm][(hour, market if per_market else None)]
                    fitted = entry["fit"]
                    yhat, X = fitted["mean"].predict(one)
                    gap = np.nan_to_num(yhat - one["F"].to_numpy(float), nan=0.0)
                    s = max(MIN_SCALE, float(fitted["scale"].predict(np.column_stack([X, gap]))[0]) * math.sqrt(math.pi / 2))
                    p_clim = fm.smoothed_dist(entry["train_y"][market], buckets[market], alpha=0.10)
                    dist = predictive_distribution(float(yhat[0]), s, float(one.at[0, "F"]), fitted["z"],
                                                   buckets[market], p_clim)
                    writers[arm].write(json.dumps({
                        "market": market, "snapshot_id": row.snapshot_id, "target_date": key[0],
                        "distribution": {str(b): p for b, p in dist.items() if p > 0}}, sort_keys=True) + "\n")
                stats["emitted"] += 1
            audit["markets"][market] = dict(stats, replay_hours=len(obs))
            print(f"dev {market}: {dict(stats)}", flush=True)
    finally:
        for handle in writers.values():
            handle.close()
    audit["files"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths.values()}
    (out / "dev_emit_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True), encoding="utf-8")
    return audit


# ------------------------------------------------------------- amendment 5: P3d_N (MG-2 pick, option N)

N_ARM = "P3d_N"
N_DEV_FIRST = date(2026, 7, 30)
N_DEV_LAST = date(2026, 9, 29)


def attach_training_nbm(frame, nbm_table, nbm_at_cutoff, timezones):
    """Amendment 5: replace the anchor column ``fh`` with L9's PIT NBM mean at each record's cutoff.

    A record without an NBM value keeps its forecast_high (L9 IMPUTE "fc"). Returns (frame, counts).
    """
    import numpy as np

    values, stats = [], defaultdict(int)
    for market, day, hour, fh in zip(frame["market"], frame["target_date"], frame["hour"], frame["fh"]):
        value, cycle = nbm_at_cutoff(nbm_table, market, str(day)[:10], int(hour), timezones[market])
        if value is None:
            stats["train_nbm_imputed_forecast"] += 1
            value = fh
        else:
            stats[f"train_nbm_cycle_{cycle}"] += 1
        values.append(np.nan if value is None else float(value))
    out = frame.copy()
    out["fh"] = np.asarray(values, dtype=float)
    return out, dict(stats)


def _require_metar_only(func):
    import inspect

    if "metar_only" not in inspect.signature(func).parameters:
        raise PooledModelError("observed_running_max lacks the metar_only switch (pick rule C1); refusing")
    return func


def scan_replay_n(folder, market_id, target_date, tz, hours, unit, running_max, observations_at_cutoff):
    """Per cutoff hour, inputs from the last replay snapshot captured in [h:00, h+1:00).

    high_so_far: ``running_max(station={}, metar=sources.metar.data, ..., metar_only=True)``;
    current_temp: the latest captured METAR row observed at or before h:00 (L3's helper);
    ``main_high_so_far``: that helper's running max, for the cross-check only.
    """
    import re
    from datetime import datetime

    pattern = re.compile(r'"captured_at_local":\s*"([^"]+)"')
    path = Path(folder) / "replay_inputs.jsonl"
    chosen = {}
    with open(path, "rb") as handle:
        offset = 0
        for line in handle:
            match = pattern.search(line[:4096].decode("utf-8", "replace"))
            if match:
                local = datetime.fromisoformat(match.group(1)).astimezone(tz)
                if local.date() == target_date and local.hour in hours:
                    chosen[local.hour] = (local, offset, len(line))
            offset += len(line)
        out = {}
        for hour, (local, start, size) in sorted(chosen.items()):
            handle.seek(start)
            snapshot = json.loads(handle.read(size))
            metar = (((snapshot.get("sources") or {}).get("metar") or {}).get("data")) or {}
            current, main_high, n = observations_at_cutoff(metar.get("rows"), target_date, hour, tz)
            high, _ = running_max({}, metar, target_date=target_date, tz=tz, unit=unit, cutoff_hour=hour,
                                  now=local, metar_only=True)
            out[hour] = {"replay_snapshot_id": snapshot.get("snapshot_id"), "replay_captured_at_local": local.isoformat(),
                         "current_temp": current, "high_so_far": high, "main_high_so_far": main_high, "n_rows": n}
    return out


def dev_emit_n_distributions(*, records_root, layout, replay_root, nbm_train_corpus, nbm_dev_corpus, out_dir,
                             markets=R0_MARKETS):
    """Amendment 5: P3d_N dev distributions on A_N's rows (captured NBM mean, METAR-only running max)."""
    import numpy as np
    import pandas as pd
    from zoneinfo import ZoneInfo

    from weather.calibration import feature_model as fm
    from weather.calibration import ols_floor_ladder as l9
    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.calibration.r0_ols_floor_devfit import usable_v2_mean
    from weather.market.market_registry import spec_for_id
    from weather.model import observed_running_max
    from weather.model.toronto_model import INTRADAY_CUTOFF_HOURS
    from weather.units import round_half_up

    running_max = _require_metar_only(observed_running_max.running_max_since_midnight)
    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"dev_{N_ARM}.jsonl"
    if path.exists():
        raise PooledModelError(f"refusing to overwrite {path}")
    timezones = {m: spec_for_id(m).timezone for m in markets}
    frame, buckets = dev_training_frame(records_root, markets)
    if frame["year"].max() >= 2026:
        raise PooledModelError("a dev training row is from 2026")
    frame, train_stats = attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff, timezones)
    fits = dev_fits(frame, "P3d")
    dev_table = l9.load_nbm(nbm_dev_corpus)
    coords = station_coordinates(markets)
    snaps = pd.read_parquet(Path(layout) / "inputs_snapshots.parquet", columns=[
        "snapshot_id", "market", "target_date", "local_hour", "cutoff_hour",
        "v2_mean", "v2_stddev", "v2_available_at", "captured_at_utc"])
    if (pd.to_datetime(snaps.target_date).dt.date > N_DEV_LAST).any():
        raise PooledModelError("layout holds a snapshot after 2026-09-29")
    snaps = snaps.assign(nbm_usable=usable_v2_mean(snaps))
    hours = {int(h) for h in INTRADAY_CUTOFF_HOURS}
    audit = {"arm": N_ARM, "markets": {}, "training_rows": int(len(frame)), "train_nbm": train_stats,
             "train_years": sorted(int(y) for y in frame["year"].unique()),
             "inputs": {"nbm_train_corpus": hashlib.sha256(Path(nbm_train_corpus).read_bytes()).hexdigest(),
                        "nbm_dev_corpus": hashlib.sha256(Path(nbm_dev_corpus).read_bytes()).hexdigest(),
                        "observed_running_max_sha256": hashlib.sha256(
                            Path(observed_running_max.__file__).read_bytes()).hexdigest(),
                        "ols_floor_ladder_sha256": hashlib.sha256(Path(l9.__file__).read_bytes()).hexdigest()}}
    match_by_hour = defaultdict(lambda: defaultdict(int))
    with open(path, "w", encoding="utf-8") as writer:
        for market in markets:
            spec = spec_for_id(market)
            tz = ZoneInfo(spec.timezone)
            obs = {}
            for slug, target, folder in l3._event_folders(replay_root):
                if slug != market or not (N_DEV_FIRST <= target <= N_DEV_LAST):
                    continue
                for hour, rec in scan_replay_n(folder, market, target, tz, hours, spec.display_unit, running_max,
                                               l3.observations_at_cutoff).items():
                    obs[(target.isoformat(), hour)] = rec
            stats = defaultdict(int)
            lat, lon, elev = coords[market]
            for row in snaps[snaps.market == market].itertuples(index=False):
                try:
                    hour = int(str(row.cutoff_hour))
                except ValueError:
                    hour = None
                if hour not in hours:
                    stats["outside_cutoff_hours"] += 1
                    continue
                if int(row.local_hour) < hour:
                    stats["local_hour_before_cutoff"] += 1
                    continue
                key = (str(row.target_date)[:10], hour)
                nbm = float(row.nbm_usable)
                if not math.isfinite(nbm):
                    stats["no_usable_nbm"] += 1
                    continue
                corpus_value, _ = l9.nbm_at_cutoff(dev_table, market, key[0], hour, spec.timezone)
                match_by_hour[hour]["exact" if corpus_value is not None and float(corpus_value) == nbm
                                    else "differs_or_missing"] += 1
                rec = obs.get(key)
                if rec is None:
                    stats["no_replay_observation"] += 1
                    continue
                if rec["high_so_far"] is None or rec["current_temp"] is None:
                    stats["missing_metar_feature"] += 1
                    continue
                if rec["main_high_so_far"] is None or int(round_half_up(rec["main_high_so_far"])) != int(
                        round_half_up(rec["high_so_far"])):
                    stats["floor_differs_from_p3d_main"] += 1
                tdate = date.fromisoformat(key[0])
                doy = tdate.timetuple().tm_yday
                one = pd.DataFrame([{
                    "market": market, "centre": nearest_centre(key[0]), "season": "aug_sep", "hour": hour,
                    "target_date": key[0], "year": tdate.year, "y": float("nan"),
                    "F": float(rec["high_so_far"]), "fh": nbm, "lat": lat, "lon": lon, "elev": elev,
                    "doy_sin": math.sin(2 * math.pi * doy / 365.25), "doy_cos": math.cos(2 * math.pi * doy / 365.25),
                    "x_high_so_far": float(rec["high_so_far"]), "x_current_temp": float(rec["current_temp"]),
                    "market_code": float(R0_MARKETS.index(market)),
                }])
                entry = fits.get((hour, None))
                if entry is None:
                    stats["no_fit_for_hour"] += 1
                    continue
                fitted = entry["fit"]
                yhat, X = fitted["mean"].predict(one)
                gap = np.nan_to_num(yhat - one["F"].to_numpy(float), nan=0.0)
                s = max(MIN_SCALE, float(fitted["scale"].predict(np.column_stack([X, gap]))[0]) * math.sqrt(math.pi / 2))
                p_clim = fm.smoothed_dist(entry["train_y"][market], buckets[market], alpha=0.10)
                dist = predictive_distribution(float(yhat[0]), s, float(one.at[0, "F"]), fitted["z"],
                                               buckets[market], p_clim)
                writer.write(json.dumps({
                    "market": market, "snapshot_id": row.snapshot_id, "target_date": key[0],
                    "distribution": {str(b): p for b, p in dist.items() if p > 0}}, sort_keys=True) + "\n")
                stats["emitted"] += 1
            audit["markets"][market] = dict(stats, replay_hours=len(obs))
            print(f"{N_ARM} {market}: {dict(stats)}", flush=True)
    audit["dev_corpus_vs_captured_nbm_by_hour"] = {str(h): dict(v) for h, v in sorted(match_by_hour.items())}
    audit["files"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()}
    (out / "dev_emit_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True), encoding="utf-8")
    return audit


# ------------------------------------------------- rung 07-12 (2026-10-25): B_N and P3d_N_fix

RUNG_ARMS = {"B_N": True, "P3d_N_fix": False}  # arm -> simple (pooled OLS baseline)
RUNG_HOURS = (7, 8, 9, 10, 11, 12)


def replay_index(handle, target_date, tz):
    """Every replay snapshot captured on the target local date: sorted [(captured_local, offset, size)]."""
    import re
    from datetime import datetime

    pattern = re.compile(r'"captured_at_local":\s*"([^"]+)"')
    index, offset = [], 0
    handle.seek(0)
    for line in handle:
        match = pattern.search(line[:4096].decode("utf-8", "replace"))
        if match:
            local = datetime.fromisoformat(match.group(1)).astimezone(tz)
            if local.date() == target_date:
                index.append((local, offset, len(line)))
        offset += len(line)
    index.sort()
    return index


def latest_at_or_before(index, instant):
    """The latest indexed snapshot captured at or before ``instant`` (L11 audit fix), else None."""
    import bisect

    keys = [e[0] for e in index]
    i = bisect.bisect_right(keys, instant)
    return index[i - 1] if i else None


def rung_inputs(snapshot, target_date, tz, hour, unit, captured_local, running_max, observations_at_cutoff,
                rounding="half_up"):
    """high_so_far / current_temp at cutoff ``hour`` from one snapshot, METAR-only, WU whole F (clarification 3 c)."""
    metar = (((snapshot.get("sources") or {}).get("metar") or {}).get("data")) or {}
    current, _, n = observations_at_cutoff(metar.get("rows"), target_date, hour, tz)
    high, _ = running_max({}, metar, target_date=target_date, tz=tz, unit=unit, cutoff_hour=hour,
                          now=captured_local, metar_only=True)
    if rounding:
        high, current = wu_whole_f(high, rounding), wu_whole_f(current, rounding)
    return {"high_so_far": high, "current_temp": current, "n_rows": n}


def _arm_spec(spec):
    """RUNG arm value -> (simple, extra_ols, extra_hgb); a bare bool is the R-A form."""
    if isinstance(spec, bool):
        return spec, (), ()
    return bool(spec["simple"]), tuple(spec.get("extra_ols", ())), tuple(spec.get("extra_hgb", ()))


def _rung_entry(train, simple, extra_ols=(), extra_hgb=()):
    return {"fit": fit_pooled(train, market_id=False, doy=True, raw_columns=False, simple=simple,
                              extra_ols=extra_ols, extra_hgb=extra_hgb),
            "train_y": {m: [int(v) for v in train.loc[train["market"] == m, "y"]] for m in train["market"].unique()}}


def rung_fits(frame, hours=RUNG_HOURS, arms=None):
    fits = {}
    for arm, spec in (arms or RUNG_ARMS).items():
        for hour in hours:
            fits[(arm, hour)] = _rung_entry(frame[frame["hour"] == hour].reset_index(drop=True), *_arm_spec(spec))
    return fits


def _dist_from_fit(entry, one, buckets, market):
    import numpy as np
    from weather.calibration import feature_model as fm

    fitted = entry["fit"]
    yhat, X = fitted["mean"].predict(one)
    gap = np.nan_to_num(yhat - one["F"].to_numpy(float), nan=0.0)
    s = np.maximum(MIN_SCALE, fitted["scale"].predict(np.column_stack([X, gap])) * math.sqrt(math.pi / 2))
    p_clim = fm.smoothed_dist(entry["train_y"][market], buckets[market], alpha=0.10)
    return [predictive_distribution(float(yhat[i]), float(s[i]), float(one["F"].iat[i]), fitted["z"],
                                    buckets[market], p_clim) for i in range(len(one))]


def rung_loyo(frame, buckets, hours=RUNG_HOURS, arms=None):
    """Blocked leave-one-year-out on the 2021-25 Aug-Sep rows, both rung arms, identical rows."""
    from weather.calibration import feature_model as fm

    arms = arms or RUNG_ARMS
    rows = []
    for hour in hours:
        at_hour = frame[frame["hour"] == hour]
        for year in sorted(at_hour["year"].unique()):
            train = at_hour[at_hour["year"] != year].reset_index(drop=True)
            val = at_hour[at_hour["year"] == year].reset_index(drop=True)
            out = {}
            for arm, spec in arms.items():
                entry = _rung_entry(train, *_arm_spec(spec))
                for market in sorted(val["market"].unique()):
                    part = val[val["market"] == market].reset_index(drop=True)
                    for i, dist in enumerate(_dist_from_fit(entry, part, buckets, market)):
                        actual = int(part.at[i, "y"])
                        out.setdefault((market, str(part.at[i, "target_date"])[:10]), {})[arm] = (
                            fm.brier_score(dist, actual), fm.log_loss(dist, actual))
            for (market, day), v in out.items():
                rows.append({"hour": int(hour), "year": int(year), "market": market, "date": day,
                             **{f"{a}_brier": v[a][0] for a in arms}, **{f"{a}_log": v[a][1] for a in arms}})
        print(f"rung loyo hour {hour}: {sum(1 for r in rows if r['hour'] == hour)} rows", flush=True)
    return rows


def rung_loyo_summary(rows, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED):
    """P3d_N_fix - B_N per hour and pooled 07-12 (mean per row), date-clustered bootstrap."""
    import numpy as np

    out = {}
    groups = {f"h{h:02d}": [r for r in rows if r["hour"] == h] for h in sorted({r["hour"] for r in rows})}
    groups["07-12"] = rows
    rng = np.random.default_rng(seed)
    for name, rs in groups.items():
        for metric in ("brier", "log"):
            by_date = defaultdict(list)
            for r in rs:
                by_date[r["date"]].append(r[f"P3d_N_fix_{metric}"] - r[f"B_N_{metric}"])
            dates = sorted(by_date)
            sums = np.array([sum(by_date[d]) for d in dates])
            counts = np.array([len(by_date[d]) for d in dates])
            idx = rng.integers(0, len(dates), size=(draws, len(dates)))
            boot = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
            out[f"{name}|{metric}"] = {
                "P3d_N_fix_minus_B_N": float(sums.sum() / counts.sum()),
                "ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
                "B_N_mean": float(np.mean([r[f"B_N_{metric}"] for r in rs])), "n": len(rs), "n_dates": len(dates)}
    return out


def dev_emit_rung(*, records_root, layout, replay_root, nbm_train_corpus, out_dir, markets=R0_MARKETS,
                  hours=RUNG_HOURS, loyo=True):
    """Rung 07-12: B_N and P3d_N_fix dev distributions plus the blocked LOYO table (rule C:/t/l2/rung0712/rule.md).

    Each layout row uses the latest replay snapshot captured at or before the row's own captured_at_utc.
    """
    import pandas as pd
    from zoneinfo import ZoneInfo

    from weather.calibration import ols_floor_ladder as l9
    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.calibration.r0_ols_floor_devfit import usable_v2_mean
    from weather.market.market_registry import spec_for_id
    from weather.model import observed_running_max

    running_max = _require_metar_only(observed_running_max.running_max_since_midnight)
    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {arm: out / f"dev_{arm}.jsonl" for arm in RUNG_ARMS}
    for path in list(paths.values()) + [out / "loyo_rows.jsonl"]:
        if path.exists():
            raise PooledModelError(f"refusing to overwrite {path}")
    timezones = {m: spec_for_id(m).timezone for m in markets}
    frame, buckets = dev_training_frame(records_root, markets)
    if frame["year"].max() >= 2026:
        raise PooledModelError("a dev training row is from 2026")
    frame, train_stats = attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff, timezones)
    frame = frame[frame["hour"].isin(hours)].reset_index(drop=True)
    audit = {"arms": list(RUNG_ARMS), "hours": list(hours), "training_rows": int(len(frame)), "train_nbm": train_stats,
             "train_years": sorted(int(y) for y in frame["year"].unique()), "markets": {},
             "inputs": {"nbm_train_corpus": hashlib.sha256(Path(nbm_train_corpus).read_bytes()).hexdigest(),
                        "observed_running_max_sha256": hashlib.sha256(
                            Path(observed_running_max.__file__).read_bytes()).hexdigest(),
                        "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    if loyo:
        loyo_rows = rung_loyo(frame, buckets, hours)
        _write_jsonl(out / "loyo_rows.jsonl", loyo_rows)
        audit["loyo"] = rung_loyo_summary(loyo_rows)
    fits = rung_fits(frame, hours)
    coords = station_coordinates(markets)
    snaps = pd.read_parquet(Path(layout) / "inputs_snapshots.parquet", columns=[
        "snapshot_id", "market", "target_date", "local_hour", "cutoff_hour",
        "v2_mean", "v2_stddev", "v2_available_at", "captured_at_utc"])
    if (pd.to_datetime(snaps.target_date).dt.date > N_DEV_LAST).any():
        raise PooledModelError("layout holds a snapshot after 2026-09-29")
    snaps = snaps.assign(nbm_usable=usable_v2_mean(snaps))
    writers = {arm: open(path, "w", encoding="utf-8") for arm, path in paths.items()}
    try:
        for market in markets:
            spec = spec_for_id(market)
            tz = ZoneInfo(spec.timezone)
            folders = {target: folder for slug, target, folder in l3._event_folders(replay_root)
                       if slug == market and N_DEV_FIRST <= target <= N_DEV_LAST}
            stats, ahead = defaultdict(int), []
            lat, lon, elev = coords[market]
            rows = snaps[snaps.market == market].copy()
            rows["target"] = pd.to_datetime(rows.target_date).dt.date
            for target, group in rows.groupby("target"):
                folder = folders.get(target)
                eligible = []
                for row in group.itertuples(index=False):
                    try:
                        hour = int(str(row.cutoff_hour))
                    except ValueError:
                        hour = None
                    if hour not in hours:
                        stats["outside_cutoff_hours"] += 1
                    elif int(row.local_hour) < hour:
                        stats["local_hour_before_cutoff"] += 1
                    elif not math.isfinite(float(row.nbm_usable)):
                        stats["no_usable_nbm"] += 1
                    elif folder is None:
                        stats["no_replay_folder"] += 1
                    else:
                        eligible.append((row, hour))
                if not eligible:
                    continue
                with open(Path(folder) / "replay_inputs.jsonl", "rb") as handle:
                    index = replay_index(handle, target, tz)
                    cache, parsed = {}, {}
                    for row, hour in eligible:
                        captured = pd.Timestamp(row.captured_at_utc)
                        captured = (captured.tz_localize("UTC") if captured.tzinfo is None else captured)
                        entry = latest_at_or_before(index, captured.to_pydatetime())
                        if entry is None:
                            stats["no_replay_snapshot_at_or_before_capture"] += 1
                            continue
                        ahead.append((captured.to_pydatetime() - entry[0]).total_seconds() / 60)
                        key = (entry[1], hour)
                        if key not in cache:
                            if entry[1] not in parsed:
                                handle.seek(entry[1])
                                try:
                                    parsed = {entry[1]: json.loads(handle.read(entry[2]))}
                                except json.JSONDecodeError:
                                    parsed = {entry[1]: None}
                            snap = parsed[entry[1]]
                            cache[key] = None if snap is None else rung_inputs(
                                snap, target, tz, hour, spec.display_unit, entry[0], running_max,
                                l3.observations_at_cutoff)
                        rec = cache[key]
                        if rec is None:
                            stats["corrupt_replay_line"] += 1
                            continue
                        if rec["high_so_far"] is None or rec["current_temp"] is None:
                            stats["missing_metar_feature"] += 1
                            continue
                        doy = target.timetuple().tm_yday
                        one = pd.DataFrame([{
                            "market": market, "centre": nearest_centre(target.isoformat()), "season": "aug_sep",
                            "hour": hour, "target_date": target.isoformat(), "year": target.year, "y": float("nan"),
                            "F": float(rec["high_so_far"]), "fh": float(row.nbm_usable), "lat": lat, "lon": lon,
                            "elev": elev, "doy_sin": math.sin(2 * math.pi * doy / 365.25),
                            "doy_cos": math.cos(2 * math.pi * doy / 365.25),
                            "x_high_so_far": float(rec["high_so_far"]), "x_current_temp": float(rec["current_temp"]),
                            "market_code": float(R0_MARKETS.index(market))}])
                        for arm in RUNG_ARMS:
                            dist = _dist_from_fit(fits[(arm, hour)], one, buckets, market)[0]
                            writers[arm].write(json.dumps({
                                "market": market, "snapshot_id": row.snapshot_id, "target_date": target.isoformat(),
                                "distribution": {str(b): p for b, p in dist.items() if p > 0}}, sort_keys=True) + "\n")
                        stats["emitted"] += 1
            ahead.sort()
            audit["markets"][market] = dict(stats, median_minutes_capture_after_replay=(
                ahead[len(ahead) // 2] if ahead else None))
            print(f"rung {market}: {dict(stats)}", flush=True)
    finally:
        for w in writers.values():
            w.close()
    audit["files"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths.values()}
    (out / "dev_emit_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True), encoding="utf-8")
    return audit


# ------------------------------------------------- rung 07-12 R-D (walk-forward MG-1 blend) and R-E (descriptive)

BLEND_FIT_FIRST = "2026-08-01"
POSITION_CLASSES = ("<=-3", "-2", "-1", "0", "+1", "+2", ">=+3")


def blend_weight(a, b, y, offsets, n):
    """Per-snapshot A and B for the exact Brier minimiser of w*a + (1-w)*b over [0, 1]."""
    import numpy as np

    d = a - b
    A = np.add.reduceat(d * d, offsets) / n
    B = np.add.reduceat(d * (b - y), offsets) / n
    return A, B


def solve_weight(A, B):
    total_a = float(A.sum())
    if total_a <= 0:
        return 0.0
    return min(1.0, max(0.0, -float(B.sum()) / total_a))


def walk_forward_weights(dates, hours, covered, A, B, scored_dates, hour_set=RUNG_HOURS):
    """w(h, d) fitted on covered snapshots at hour h with date strictly before d (dates ISO strings)."""
    import numpy as np

    out = {}
    for h in hour_set:
        at = covered & (hours == h)
        for d in scored_dates:
            sel = at & (dates < d)
            out[(h, d)] = solve_weight(A[sel], B[sel]) if sel.any() else 0.0
    return out


def position_classes(table):
    """Per band: class index of band_index - winning band_index (POSITION_CLASSES)."""
    import numpy as np

    band_index = table.bands.band_index.to_numpy(int)
    winner_flat = np.add.reduceat(table.y * band_index, table.offsets)
    has_winner = np.add.reduceat(table.y, table.offsets) > 0
    pos = band_index - np.repeat(winner_flat, table.n).astype(int)
    cls = np.clip(pos, -3, 3) + 3
    return cls, np.repeat(has_winner, table.n)


def rung_blend(*, layout, fix_jsonl, bn_jsonl, out_path, start="2026-08-01", end="2026-09-29"):
    """R-D and R-E under C:/t/l2/rung0712/rule_rd.md."""
    import numpy as np

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas

    out_path = require_output_outside_repo(out_path)
    if out_path.exists():
        raise PooledModelError(f"refusing to overwrite {out_path}")
    start_d, end_d = data.check_range(start, end)
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)

    # fitting table: every dev date from BLEND_FIT_FIRST (weights use only dates strictly before each scored date)
    fit_dates = sorted(d for d in {str(x) for x in lay.dates} if BLEND_FIT_FIRST <= d <= end)
    full = sc.Table(lay, fit_dates)
    pa, cov_a, _ = l3._vector(full, l3._candidate_frame(str(fix_jsonl), full, lay, folds, data)[0])
    pb, cov_b, _ = l3._vector(full, loss_atlas.mg1_frame(full))
    A, B = blend_weight(pa, pb, full.y, full.offsets, full.n)
    weights = walk_forward_weights(full.snaps.date.astype(str).to_numpy(), full.local_hour, cov_a & cov_b, A, B,
                                   scored)

    table = sc.Table(lay, scored)
    date_w = l3._date_weights([k[0] for k in table.keys], sc.DRAWS, sc.SEED)
    market_b = table.brier(table.p_market)
    p_fix, cov_fix, reasons_fix = l3._vector(table, l3._candidate_frame(str(fix_jsonl), table, lay, folds, data)[0])
    p_bn, cov_bn, reasons_bn = l3._vector(table, l3._candidate_frame(str(bn_jsonl), table, lay, folds, data)[0])
    p_mg1, cov_mg1, reasons_mg1 = l3._vector(table, loss_atlas.mg1_frame(table))
    _, e = table.cells(table.brier(p_mg1) - market_b, (table.local_hour >= 7) & (table.local_hour <= 12))
    mg1_excess = float(e.mean())
    if round(mg1_excess, 3) != l3.MG1_CONTROL_0712_EXCESS:
        raise PooledModelError(f"MG-1 positive control failed: {mg1_excess:.5f}")
    dates = table.snaps.date.astype(str).to_numpy()
    w_snap = np.array([weights.get((int(h), d), 0.0) for h, d in zip(table.local_hour, dates)])
    both = cov_fix & cov_mg1
    w_band = np.where(both, w_snap, 0.0)[table.band_snap]
    p_blend = w_band * p_fix + (1.0 - w_band) * p_mg1
    blend_b = table.brier(p_blend)
    everything = np.ones(len(table.snaps), dtype=bool)
    refs = {"mg1": (table.brier(p_mg1), cov_mg1), "p3d_n_fix": (table.brier(p_fix), cov_fix),
            "b_n": (table.brier(p_bn), cov_bn), "served": (table.brier(table.p_served), everything)}
    pools = [(sc.ALL_MARKETS, None), (l3.PRIMARY_POOL, set(l3.PRIMARY_MARKETS))] + [
        (m, {m}) for m in sorted(set(table.markets))]
    groups = [("07-12", 7, 12)] + [(f"h{h:02d}", h, h) for h in RUNG_HOURS]
    rows = []
    for ref_name, (ref_b, ref_cov) in refs.items():
        for scope in ("covered", "blended"):
            base = (both & ref_cov) if scope == "covered" else everything
            for market, members in pools:
                in_pool = everything if members is None else np.isin(table.markets, sorted(members))
                for group, lo, hi in groups:
                    mask = base & in_pool & (table.local_hour >= lo) & (table.local_hour <= hi)
                    if not mask.any():
                        continue
                    idx, c = table.cells(blend_b, mask)
                    _, r_ = table.cells(ref_b, mask)
                    _, m = table.cells(market_b, mask)
                    rows.append({"reference": ref_name, "scope": scope, "market": market, "group": group,
                                 "n_market_days": int(len(idx)), "n_snapshots": int(mask.sum()),
                                 "R_blend": sc.ratio_interval(table.w[:, idx], c, m),
                                 "R_reference": sc.ratio_interval(table.w[:, idx], r_, m),
                                 "dR_crossed": sc.ratio_interval(table.w[:, idx], c - r_, m),
                                 "dR_date_clustered": sc.ratio_interval(date_w[:, idx], c - r_, m)})
    weight_report = {}
    for h in RUNG_HOURS:
        ws = [weights[(h, d)] for d in scored]
        weight_report[f"h{h:02d}"] = {"mean": float(np.mean(ws)), "first": ws[0], "last": ws[-1],
                                      "min": float(min(ws)), "max": float(max(ws))}

    # R-E: exact band-position decomposition of P3d_N_fix - MG-1
    cls, has_winner = position_classes(table)
    diff_band = ((p_fix - table.y) ** 2 - (p_mg1 - table.y) ** 2) / np.repeat(table.n, table.n)
    decomposition = {}
    win_a = np.add.reduceat(p_fix * table.y, table.offsets)
    win_b = np.add.reduceat(p_mg1 * table.y, table.offsets)
    for market, members in [(sc.ALL_MARKETS, None)] + [(m, {m}) for m in sorted(set(table.markets))]:
        in_pool = everything if members is None else np.isin(table.markets, sorted(members))
        for group, lo, hi in (groups if members is None else groups[:1]):
            mask = both & in_pool & (table.local_hour >= lo) & (table.local_hour <= hi)
            if not mask.any():
                continue
            idx, mden = table.cells(market_b, mask)
            entry = {"n_snapshots": int(mask.sum()),
                     "mean_p_winner": {"P3d_N_fix": float(win_a[mask].mean()), "MG1": float(win_b[mask].mean())}}
            total = np.zeros(len(table.snaps))
            for k, name in enumerate(POSITION_CLASSES):
                per_snap = np.bincount(table.band_snap, weights=np.where(cls == k, diff_band, 0.0),
                                       minlength=len(table.snaps))
                total += per_snap
                _, cnum = table.cells(per_snap, mask)
                entry[name] = sc.ratio_interval(date_w[:, idx], cnum, mden)
            _, ctot = table.cells(total, mask)
            entry["total_dR"] = sc.ratio_interval(date_w[:, idx], ctot, mden)
            decomposition[f"{market}|{group}"] = entry
    result = {"rule": "C:/t/l2/rung0712/rule_rd.md",
              "population": {"n_dates": len(scored), "first_date": scored[0], "last_date": scored[-1],
                             "n_market_days": len(table.keys)},
              "fit_dates": [fit_dates[0], fit_dates[-1], len(fit_dates)],
              "mg1_control_excess_07_12": mg1_excess,
              "inputs": {"P3d_N_fix": hashlib.sha256(Path(fix_jsonl).read_bytes()).hexdigest(),
                         "B_N": hashlib.sha256(Path(bn_jsonl).read_bytes()).hexdigest(),
                         "layout_manifest_sha256": lay.manifest_sha256,
                         "scorecard_code_sha256": sc.code_sha256(),
                         "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
              "coverage": {"P3d_N_fix": reasons_fix, "B_N": reasons_bn, "MG1": reasons_mg1,
                           "both": int(both.sum())},
              "weights": weight_report,
              "weights_by_date": {f"h{h:02d}": [weights[(h, d)] for d in scored] for h in RUNG_HOURS},
              "rows": rows, "decomposition": decomposition}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


# ------------------------------------------------- rung 07-12 R-F (blends vs the MG-2 pre-13 arm, MG-1 + L6)

L6_PART_SHA256 = "07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9"
L6_NOWCAST_SHA256 = "3806687cd6ad8d38571fd5d17efa5405856300d2f0029ae644e3ad08db4a31f3"


def l6_frozen_state(coefficients_path, expected=L6_PART_SHA256):
    payload = json.loads(Path(coefficients_path).read_bytes())
    part = payload["l6_stack"]
    sha = hashlib.sha256(json.dumps(part, sort_keys=True, separators=(",", ":"), allow_nan=False)
                         .encode("utf-8")).hexdigest()
    if sha != expected:
        raise PooledModelError(f"L6 coefficients part sha {sha} != {expected}")
    return {"coef": {int(h): tuple(v) for h, v in part["coef"].items()}, "column": part["column"]}, sha


def _with_floor(snaps):
    from weather.reporting.scorecards import dev_scorecard_data as data
    import pandas as pd

    if "floor" in snaps.columns:
        return snaps
    return snaps.assign(floor=snaps[list(data.FLOOR_FIELDS)].apply(pd.to_numeric, errors="coerce").max(axis=1))


def l6_vector(table, state, l3):
    from weather.reporting.scorecards.free_source_candidates import l6_stack

    return l3._vector(table, l6_stack.predict(state, _with_floor(table.snaps), table.bands))


def rung_rf(*, layout, fix_jsonl, bn_jsonl, coefficients, nowcasts, rd_result, out_path,
            start="2026-08-01", end="2026-09-29"):
    """R-F under C:/t/l2/rung0712/rule_rf.md."""
    import os

    import numpy as np

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas

    out_path = require_output_outside_repo(out_path)
    if out_path.exists():
        raise PooledModelError(f"refusing to overwrite {out_path}")
    now_sha = hashlib.sha256(Path(nowcasts).read_bytes()).hexdigest()
    if now_sha != L6_NOWCAST_SHA256:
        raise PooledModelError(f"L6 nowcast sha {now_sha} != {L6_NOWCAST_SHA256}")
    os.environ["L6_NOWCASTS"] = str(nowcasts)
    from weather.reporting.scorecards.free_source_candidates import l6_stack, mg1

    l6_stack._CACHE.clear()
    state, part_sha = l6_frozen_state(coefficients)
    start_d, end_d = data.check_range(start, end)
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    fit_dates = sorted(d for d in {str(x) for x in lay.dates} if BLEND_FIT_FIRST <= d <= end)

    def vectors(table):
        fix = l3._vector(table, l3._candidate_frame(str(fix_jsonl), table, lay, folds, data)[0])
        mg = l3._vector(table, loss_atlas.mg1_frame(table))
        l6 = l6_vector(table, state, l3)
        return fix, mg, l6

    full = sc.Table(lay, fit_dates)
    (fa, fcov, _), (ma, mcov, _), (la, lcov, _) = vectors(full)
    fdates = full.snaps.date.astype(str).to_numpy()
    weights = {}
    for name, (base, bcov) in {"blend_mg1": (ma, mcov), "blend_l6": (la, lcov)}.items():
        A, B = blend_weight(fa, base, full.y, full.offsets, full.n)
        weights[name] = walk_forward_weights(fdates, full.local_hour, fcov & bcov, A, B, scored)

    table = sc.Table(lay, scored)
    date_w = l3._date_weights([k[0] for k in table.keys], sc.DRAWS, sc.SEED)
    market_b = table.brier(table.p_market)
    (p_fix, cov_fix, r_fix), (p_mg1, cov_mg1, r_mg1), (p_l6, cov_l6, r_l6) = vectors(table)
    p_bn, cov_bn, r_bn = l3._vector(table, l3._candidate_frame(str(bn_jsonl), table, lay, folds, data)[0])
    w0712 = (table.local_hour >= 7) & (table.local_hour <= 12)
    _, e = table.cells(table.brier(p_mg1) - market_b, w0712)
    mg1_excess = float(e.mean())
    if round(mg1_excess, 3) != l3.MG1_CONTROL_0712_EXCESS:
        raise PooledModelError(f"MG-1 positive control failed: {mg1_excess:.5f}")
    p_mg1_module, _, _ = l3._vector(table, mg1.predict(_with_floor(table.snaps), table.bands, None))
    mg1_identity = float(np.max(np.abs(p_mg1_module - p_mg1)))
    if mg1_identity > 1e-12:
        raise PooledModelError(f"mg1.predict differs from loss_atlas.mg1_frame by {mg1_identity}")
    differs = np.add.reduceat(np.abs(p_l6 - p_mg1), table.offsets) > 1e-12
    has_now = np.isfinite(l6_stack.nowcasts()[0][state["column"]].reindex(
        table.snaps.row_key.to_numpy()).to_numpy(float))
    l6_controls = {"snapshots_differing_from_mg1": int(differs.sum()),
                   "differing_outside_07_12": int((differs & ~w0712).sum()),
                   "differing_without_nowcast": int((differs & ~has_now).sum()),
                   "snapshots_07_12_with_nowcast": int((w0712 & has_now).sum()),
                   "covered_differ_07_12": int((differs & w0712 & cov_l6).sum()),
                   "mg1_identity_max_abs_diff": mg1_identity}
    if l6_controls["differing_outside_07_12"] or l6_controls["differing_without_nowcast"]:
        raise PooledModelError(f"L6 control failed: {l6_controls}")
    if not l6_controls["snapshots_differing_from_mg1"]:
        raise PooledModelError("L6 never differs from MG-1: nowcast keys do not join")
    dates = table.snaps.date.astype(str).to_numpy()
    arms = {}
    for name, (base, bcov) in {"blend_mg1": (p_mg1, cov_mg1), "blend_l6": (p_l6, cov_l6)}.items():
        w_snap = np.array([weights[name].get((int(h), d), 0.0) for h, d in zip(table.local_hour, dates)])
        both = cov_fix & bcov
        wb = np.where(both, w_snap, 0.0)[table.band_snap]
        arms[name] = table.brier(wb * p_fix + (1.0 - wb) * base)
    arms["l6"] = table.brier(p_l6)
    everything = np.ones(len(table.snaps), dtype=bool)
    refs = {"l6": (table.brier(p_l6), cov_l6), "mg1": (table.brier(p_mg1), cov_mg1),
            "p3d_n_fix": (table.brier(p_fix), cov_fix), "b_n": (table.brier(p_bn), cov_bn),
            "served": (table.brier(table.p_served), everything), "blend_mg1": (arms["blend_mg1"], cov_mg1)}
    common = cov_fix & cov_l6
    pools = [(sc.ALL_MARKETS, None), (l3.PRIMARY_POOL, set(l3.PRIMARY_MARKETS))] + [
        (m, {m}) for m in sorted(set(table.markets))]
    groups = [("07-12", 7, 12)] + [(f"h{h:02d}", h, h) for h in RUNG_HOURS]
    rows = []
    for arm, arm_b in arms.items():
        for ref_name, (ref_b, ref_cov) in refs.items():
            if ref_name == arm:
                continue
            for scope in ("covered", "blended"):
                base_mask = (common & ref_cov) if scope == "covered" else everything
                for market, members in pools:
                    in_pool = everything if members is None else np.isin(table.markets, sorted(members))
                    for group, lo, hi in groups:
                        mask = base_mask & in_pool & (table.local_hour >= lo) & (table.local_hour <= hi)
                        if not mask.any():
                            continue
                        idx, c = table.cells(arm_b, mask)
                        _, r_ = table.cells(ref_b, mask)
                        _, m = table.cells(market_b, mask)
                        rows.append({"arm": arm, "reference": ref_name, "scope": scope, "market": market,
                                     "group": group, "n_market_days": int(len(idx)), "n_snapshots": int(mask.sum()),
                                     "R_arm": sc.ratio_interval(table.w[:, idx], c, m),
                                     "R_reference": sc.ratio_interval(table.w[:, idx], r_, m),
                                     "dR_crossed": sc.ratio_interval(table.w[:, idx], c - r_, m),
                                     "dR_date_clustered": sc.ratio_interval(date_w[:, idx], c - r_, m)})
    # positive control: R-D reproduced (blend_mg1 vs MG-1, ALL, covered by blend's components, 07-12)
    rd = json.loads(Path(rd_result).read_bytes())
    rd_row = next(r for r in rd["rows"] if r["reference"] == "mg1" and r["scope"] == "covered"
                  and r["market"] == sc.ALL_MARKETS and r["group"] == "07-12")
    mask = cov_fix & cov_mg1 & w0712
    idx, c = table.cells(arms["blend_mg1"], mask)
    _, r_ = table.cells(refs["mg1"][0], mask)
    _, m = table.cells(market_b, mask)
    rd_now = float((c - r_).sum() / m.sum())
    if abs(rd_now - rd_row["dR_date_clustered"]["estimate"]) > 1e-9:
        raise PooledModelError(f"R-D control failed: {rd_now} != {rd_row['dR_date_clustered']['estimate']}")
    weight_report = {name: {f"h{h:02d}": {"mean": float(np.mean([w[(h, d)] for d in scored])),
                                         "first": w[(h, scored[0])], "last": w[(h, scored[-1])]}
                            for h in RUNG_HOURS} for name, w in weights.items()}
    result = {"rule": "C:/t/l2/rung0712/rule_rf.md",
              "population": {"n_dates": len(scored), "first_date": scored[0], "last_date": scored[-1],
                             "n_market_days": len(table.keys), "common_covered_snapshots_07_12": int(
                                 (common & w0712).sum())},
              "controls": {"mg1_excess_07_12": mg1_excess, "rd_reproduced": rd_now, **l6_controls},
              "inputs": {"l6_part_sha256": part_sha, "l6_nowcast_sha256": now_sha,
                         "P3d_N_fix": hashlib.sha256(Path(fix_jsonl).read_bytes()).hexdigest(),
                         "B_N": hashlib.sha256(Path(bn_jsonl).read_bytes()).hexdigest(),
                         "l6_stack_sha256": hashlib.sha256(Path(l6_stack.__file__).read_bytes()).hexdigest(),
                         "layout_manifest_sha256": lay.manifest_sha256, "scorecard_code_sha256": sc.code_sha256(),
                         "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
              "coverage": {"P3d_N_fix": r_fix, "MG1": r_mg1, "L6": r_l6, "B_N": r_bn},
              "weights": weight_report, "rows": rows}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


# ------------------------------------------------- rung 07-12 R-G (trajectory and floor features, rule a8cf6564)

RG_RULE_SHA256 = "a8cf65640625605acdd0acad391bb267357957a5fd0bd9bd7e6e7a62dafe9b29"
RG_OBS_SHA256 = "37d97195828d9f58d510f078e3029d53ed051fe471c4a94333bb0cc51f6d28f2"
RG_FEATURES = ("t_trend3", "t_trend3_miss", "t_amp", "t_path_gap")
RG_ARMS = {
    "B_N": True,
    "B_G": {"simple": True, "extra_ols": RG_FEATURES},
    "P3d_N_fix": False,
    "P3d_G": {"simple": False, "extra_hgb": ("t_trend3", "t_amp", "t_path_gap")},
}
RG_TREND_CLIP = 10.0
RG_TREND_WINDOW_S = 3 * 3600
RG_PARITY_MIN = {"overnight_min_exact": 0.95, "trend3_within_1": 0.90, "training_iem_coverage": 0.95}
RG_TRAIN_YEARS = (2021, 2022, 2023, 2024, 2025)


def trajectory_features(instants, temps, local_days, capture, target_day):
    """R-G features at ``capture`` (epoch seconds) from METAR reports (sorted epoch seconds, F, local-day ordinal).

    trend3: OLS slope (F/h) of the last 3 reports at or before capture, all within 3 h, clipped to +-10, else None.
    overnight_min: WU whole F (half_up) of the minimum report of the target local day at or before capture.
    n_3h: reports in the 3 h before capture.
    """
    import bisect

    k = bisect.bisect_right(instants, capture)
    day_start = bisect.bisect_left(local_days, target_day, 0, k)  # local days are non-decreasing in time
    same = temps[day_start:k] if (day_start < k and local_days[day_start] == target_day) else []
    overnight = wu_whole_f(min(same), "half_up") if len(same) else None
    n_3h = k - bisect.bisect_left(instants, capture - RG_TREND_WINDOW_S, 0, k)
    trend = None
    if k >= 3 and instants[k - 3] >= capture - RG_TREND_WINDOW_S:
        xs = [(instants[i] - instants[k - 1]) / 3600.0 for i in range(k - 3, k)]
        ys = [float(temps[i]) for i in range(k - 3, k)]
        mx, my = sum(xs) / 3, sum(ys) / 3
        sxx = sum((x - mx) ** 2 for x in xs)
        if sxx > 0:
            slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
            trend = max(-RG_TREND_CLIP, min(RG_TREND_CLIP, slope))
    return {"trend3": trend, "overnight_min": overnight, "n_3h": n_3h}


def _report_arrays(pairs, tz):
    """[(aware datetime, temp F)] -> sorted, de-duplicated (last wins) arrays of epoch s, temp, local-day ordinal."""
    kept = {}
    for instant, temp in pairs:
        if instant is None or temp is None:
            continue
        try:
            value = float(temp)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            kept[instant] = value
    keys = sorted(kept)
    return ([k.timestamp() for k in keys], [kept[k] for k in keys], [k.astimezone(tz).date().toordinal() for k in keys])


def rg_iem_reports(obs_parquet, markets, timezones, last_local=N_DEV_LAST):
    """IEM market-station reports per market (T-group F when present, else tmpf; corrections last), local <= last."""
    import pandas as pd
    from zoneinfo import ZoneInfo

    sha = hashlib.sha256(Path(obs_parquet).read_bytes()).hexdigest()
    if sha != RG_OBS_SHA256:
        raise PooledModelError(f"IEM obs parquet sha {sha} != {RG_OBS_SHA256}")
    obs = pd.read_parquet(obs_parquet, columns=["market", "valid_utc", "tmpf", "tgroup_f", "is_cor", "role"],
                          filters=[("role", "==", "market")])
    out = {}
    for market in markets:
        tz = ZoneInfo(timezones[market])
        part = obs[obs.market == market].sort_values(["valid_utc", "is_cor"], kind="mergesort")
        temp = part.tgroup_f.where(part.tgroup_f.notna(), part.tmpf)
        local = part.valid_utc.dt.tz_convert(tz)
        keep = (local.dt.date <= last_local).to_numpy() & temp.notna().to_numpy()
        pairs = zip(part.valid_utc[keep].dt.to_pydatetime(), temp[keep].to_numpy(float))
        out[market] = _report_arrays(pairs, tz)
    return out, sha


def rg_diurnal_fraction(reports, tz, years=RG_TRAIN_YEARS):
    """s(month, hour): mean (T_H - Tmin) / (Tmax - Tmin) over training-year local days with Tmax - Tmin >= 2 F,
    T_H the latest report at or before H:00 local of that day."""
    import bisect
    from datetime import datetime, time

    instants, temps, days = reports
    by_day = defaultdict(list)
    for i, d in enumerate(days):
        by_day[d].append(i)
    sums, counts = defaultdict(float), defaultdict(int)
    for d, idx in by_day.items():
        day = date.fromordinal(d)
        if day.year not in years:
            continue
        values = [temps[i] for i in idx]
        lo, hi = min(values), max(values)
        if hi - lo < 2:
            continue
        sub = [instants[i] for i in idx]
        for hour in range(24):
            at = datetime.combine(day, time(hour, 0), tzinfo=tz).timestamp()
            j = bisect.bisect_right(sub, at)
            if j == 0:
                continue
            sums[(day.month, hour)] += (values[j - 1] - lo) / (hi - lo)
            counts[(day.month, hour)] += 1
    return {k: sums[k] / counts[k] for k in sums}


def rg_columns(feats, F, nbm, month, hour, frac):
    """Model columns from the raw features: trend3 (+ missing indicator), amp, path_gap."""
    trend, low = feats["trend3"], feats["overnight_min"]
    amp = (nbm - low) if (low is not None and nbm is not None and math.isfinite(nbm)) else float("nan")
    s = frac.get((month, hour))
    path_gap = (F - (low + amp * s)) if (math.isfinite(amp) and s is not None and math.isfinite(F)) else float("nan")
    return {"t_trend3": float("nan") if trend is None else float(trend), "t_trend3_miss": 1.0 if trend is None else 0.0,
            "t_amp": float(amp), "t_path_gap": float(path_gap)}


def rg_training_columns(frame, iem, fracs, timezones):
    """Attach R-G columns to the 2021-25 training frame (IEM reports at each record's own h:00 cutoff)."""
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

    cols, stats = defaultdict(list), defaultdict(int)
    for market, day, hour, F, fh in zip(frame["market"], frame["target_date"], frame["hour"], frame["F"], frame["fh"]):
        tz = ZoneInfo(timezones[market])
        target = date.fromisoformat(str(day)[:10])
        cutoff = datetime.combine(target, time(int(hour), 0), tzinfo=tz).timestamp()
        feats = trajectory_features(*iem[market], cutoff, target.toordinal())
        stats["rows"] += 1
        stats["iem_3_reports_in_3h"] += feats["n_3h"] >= 3
        stats["overnight_min_missing"] += feats["overnight_min"] is None
        stats["trend3_missing"] += feats["trend3"] is None
        for k, v in rg_columns(feats, float(F), float(fh), target.month, int(hour), fracs[market]).items():
            cols[k].append(v)
    out = frame.copy()
    for k in RG_FEATURES:
        out[k] = cols[k]
    return out, dict(stats)


def _captured_reports(snapshot, tz, observation_instant):
    metar = (((snapshot.get("sources") or {}).get("metar") or {}).get("data")) or {}
    pairs = [(observation_instant(row, tz)[0], row.get("temp_native")) for row in metar.get("rows") or []]
    return _report_arrays(pairs, tz)


def rg_parity_verdict(stats):
    n = max(stats.get("parity_rows", 0), 1)
    fractions = {"overnight_min_exact": stats.get("overnight_min_exact", 0) / n,
                 "trend3_within_1": stats.get("trend3_within_1", 0) / n,
                 "training_iem_coverage": stats.get("training_iem_3_reports_in_3h", 0) / max(stats.get(
                     "training_rows", 0), 1)}
    return fractions, all(fractions[k] >= RG_PARITY_MIN[k] for k in RG_PARITY_MIN)


def rung_g_emit(*, records_root, layout, replay_root, nbm_train_corpus, obs_parquet, ra_emit_dir, out_dir,
                markets=R0_MARKETS, hours=RUNG_HOURS, gate=("07-12", None), report_pools=(), rule_sha=None):
    """R-G gates 1 (parity) and 2 (LOYO), then the dev distributions of all four arms (rule_rg.md, a8cf6564).

    Gate order is binding: parity is measured on inputs only and, if it fails, nothing is fitted or scored;
    LOYO is scored only after parity passes; dev rows are emitted only after LOYO passes.
    """
    import pandas as pd
    from zoneinfo import ZoneInfo

    from weather.calibration import ols_floor_ladder as l9
    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.calibration.r0_ols_floor_devfit import usable_v2_mean
    from weather.market.market_registry import spec_for_id
    from weather.model import observed_running_max

    running_max = _require_metar_only(observed_running_max.running_max_since_midnight)
    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise PooledModelError(f"refusing to write into a non-empty {out}")
    timezones = {m: spec_for_id(m).timezone for m in markets}
    gate_label, gate_hours = gate
    gate_hours = tuple(hours) if gate_hours is None else tuple(gate_hours)
    pools = ((gate_label, None if gate_hours == tuple(hours) else gate_hours),) + tuple(report_pools)
    audit = {"rule_sha256": rule_sha or RG_RULE_SHA256, "arms": list(RG_ARMS), "hours": list(hours),
             "gate_pool": [gate_label, list(gate_hours)], "gates": {},
             "inputs": {"nbm_train_corpus": hashlib.sha256(Path(nbm_train_corpus).read_bytes()).hexdigest(),
                        "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}

    def finish():
        (out / "rg_emit_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True), encoding="utf-8")
        return audit

    iem, audit["inputs"]["obs_parquet"] = rg_iem_reports(obs_parquet, markets, timezones)
    fracs = {m: rg_diurnal_fraction(iem[m], ZoneInfo(timezones[m])) for m in markets}
    frame, buckets = dev_training_frame(records_root, markets)
    if frame["year"].max() >= 2026:
        raise PooledModelError("a dev training row is from 2026")
    frame, audit["train_nbm"] = attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff, timezones)
    frame = frame[frame["hour"].isin(hours)].reset_index(drop=True)
    frame, train_stats = rg_training_columns(frame, iem, fracs, timezones)
    audit["training"] = train_stats
    if gate_hours != tuple(hours):
        _, gate_train = rg_training_columns(frame[frame["hour"].isin(gate_hours)].reset_index(drop=True), iem, fracs,
                                            timezones)
        audit["training_gate_hours"] = gate_train
    else:
        gate_train = train_stats
    hour_stats = defaultdict(lambda: defaultdict(int))

    # ---- dev rows: captured features plus the IEM features at the same capture time (gate 1, inputs only)
    snaps = pd.read_parquet(Path(layout) / "inputs_snapshots.parquet", columns=[
        "snapshot_id", "market", "target_date", "local_hour", "cutoff_hour",
        "v2_mean", "v2_stddev", "v2_available_at", "captured_at_utc"])
    if (pd.to_datetime(snaps.target_date).dt.date > N_DEV_LAST).any():
        raise PooledModelError("layout holds a snapshot after 2026-09-29")
    snaps = snaps.assign(nbm_usable=usable_v2_mean(snaps))
    coords = station_coordinates(markets)
    stats = defaultdict(int, training_rows=gate_train["rows"],
                        training_iem_3_reports_in_3h=gate_train["iem_3_reports_in_3h"])
    dev_rows = []
    for market in markets:
        spec = spec_for_id(market)
        tz = ZoneInfo(spec.timezone)
        folders = {target: folder for slug, target, folder in l3._event_folders(replay_root)
                   if slug == market and N_DEV_FIRST <= target <= N_DEV_LAST}
        rows = snaps[snaps.market == market].copy()
        rows["target"] = pd.to_datetime(rows.target_date).dt.date
        lat, lon, elev = coords[market]
        for target, group in rows.groupby("target"):
            folder = folders.get(target)
            eligible = []
            for row in group.itertuples(index=False):
                try:
                    hour = int(str(row.cutoff_hour))
                except ValueError:
                    hour = None
                if hour in hours and int(row.local_hour) >= hour and math.isfinite(float(row.nbm_usable)) \
                        and folder is not None:
                    eligible.append((row, hour))
            if not eligible:
                continue
            with open(Path(folder) / "replay_inputs.jsonl", "rb") as handle:
                index = replay_index(handle, target, tz)
                parsed = {}
                for row, hour in eligible:
                    captured = pd.Timestamp(row.captured_at_utc)
                    captured = (captured.tz_localize("UTC") if captured.tzinfo is None else captured)
                    entry = latest_at_or_before(index, captured.to_pydatetime())
                    if entry is None:
                        continue
                    if entry[1] not in parsed:
                        handle.seek(entry[1])
                        try:
                            snap = json.loads(handle.read(entry[2]))
                        except json.JSONDecodeError:
                            snap = None
                        parsed = {entry[1]: None if snap is None else (
                            snap, _captured_reports(snap, tz, l3.metar_observation_instant))}
                    item = parsed[entry[1]]
                    if item is None:
                        continue
                    snap, reports = item
                    rec = rung_inputs(snap, target, tz, hour, spec.display_unit, entry[0], running_max,
                                      l3.observations_at_cutoff)
                    if rec["high_so_far"] is None or rec["current_temp"] is None:
                        continue
                    at = entry[0].timestamp()
                    cap = trajectory_features(*reports, at, target.toordinal())
                    ref = trajectory_features(*iem[market], at, target.toordinal())
                    for target_stats in ([stats] if hour in gate_hours else []) + [hour_stats[hour]]:
                        target_stats["parity_rows"] += 1
                        target_stats["overnight_min_exact"] += (cap["overnight_min"] is not None
                                                                and cap["overnight_min"] == ref["overnight_min"])
                        target_stats["trend3_within_1"] += ((cap["trend3"] is None and ref["trend3"] is None) or (
                            cap["trend3"] is not None and ref["trend3"] is not None
                            and abs(cap["trend3"] - ref["trend3"]) <= 1.0))
                        target_stats["captured_trend3_missing"] += cap["trend3"] is None
                        target_stats["captured_overnight_min_missing"] += cap["overnight_min"] is None
                    F, nbm = float(rec["high_so_far"]), float(row.nbm_usable)
                    doy = target.timetuple().tm_yday
                    dev_rows.append({
                        "snapshot_id": row.snapshot_id, "market": market, "centre": nearest_centre(target.isoformat()),
                        "season": "aug_sep", "hour": hour, "target_date": target.isoformat(), "year": target.year,
                        "y": float("nan"), "F": F, "fh": nbm, "lat": lat, "lon": lon, "elev": elev,
                        "doy_sin": math.sin(2 * math.pi * doy / 365.25), "doy_cos": math.cos(2 * math.pi * doy / 365.25),
                        "x_high_so_far": F, "x_current_temp": float(rec["current_temp"]),
                        "market_code": float(R0_MARKETS.index(market)),
                        **rg_columns(cap, F, nbm, target.month, entry[0].astimezone(tz).hour, fracs[market])})
        print(f"rg parity {market}: {dict(stats)}", flush=True)
    fractions, passed = rg_parity_verdict(stats)
    audit["gates"]["1_parity"] = {"counts": dict(stats), "fractions": fractions, "thresholds": RG_PARITY_MIN,
                                  "pass": passed}
    if gate_hours != tuple(hours):
        audit["gates"]["1_parity"]["per_hour"] = {f"h{h:02d}": {k: v / max(c["parity_rows"], 1) for k, v in c.items()
                                                                if k != "parity_rows"} | {"rows": c["parity_rows"]}
                                                  for h, c in sorted(hour_stats.items())}
    if not passed:
        audit["stopped_at"] = "gate 1 parity"
        return finish()

    # ---- gate 2: blocked LOYO on 2021-25, B_G - B_N (all four arms on identical rows)
    loyo_rows = rung_loyo(frame, buckets, hours, arms=RG_ARMS)
    _write_jsonl(out / "loyo_rows.jsonl", loyo_rows)
    audit["gates"]["2_loyo"] = rg_loyo_summary(loyo_rows, pooled=pools)
    primary = audit["gates"]["2_loyo"][f"B_G-B_N|{gate_label}|brier"]
    audit["gates"]["2_loyo"]["pass"] = primary["ci95"][1] < 0
    if not audit["gates"]["2_loyo"]["pass"]:
        audit["stopped_at"] = "gate 2 LOYO"
        return finish()

    # ---- dev distributions, all four arms (B_N and P3d_N_fix must reproduce R-A's files byte for byte)
    fits = rung_fits(frame, hours, arms=RG_ARMS)
    dev = pd.DataFrame(dev_rows)
    files = {}
    for arm in RG_ARMS:
        path = out / f"dev_{arm}.jsonl"
        with open(path, "w", encoding="utf-8") as w:
            for i in range(len(dev)):
                one = dev.iloc[[i]].reset_index(drop=True)
                dist = _dist_from_fit(fits[(arm, int(one.at[0, "hour"]))], one, buckets, one.at[0, "market"])[0]
                w.write(json.dumps({"market": one.at[0, "market"], "snapshot_id": one.at[0, "snapshot_id"],
                                    "target_date": one.at[0, "target_date"],
                                    "distribution": {str(b): p for b, p in dist.items() if p > 0}},
                                   sort_keys=True) + "\n")
        files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"rg emitted {arm}", flush=True)
    audit["files"] = files
    audit["ra_reproduction"] = {
        arm: files[f"dev_{arm}.jsonl"] == hashlib.sha256((Path(ra_emit_dir) / f"dev_{arm}.jsonl").read_bytes()).hexdigest()
        for arm in ("B_N", "P3d_N_fix")}
    return finish()


def rg_loyo_summary(rows, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED,
                    pairs=(("B_G", "B_N"), ("P3d_G", "P3d_N_fix"), ("P3d_G", "B_G"), ("P3d_N_fix", "B_N")),
                    pooled=(("07-12", None),)):
    """Pairwise mean differences per hour and pooled groups, date-clustered bootstrap (R-A's construction).

    ``pooled``: (label, hours or None = every row); the default is R-G's single 07-12 pool."""
    import numpy as np

    out = {}
    groups = {f"h{h:02d}": [r for r in rows if r["hour"] == h] for h in sorted({r["hour"] for r in rows})}
    for label, members in pooled:
        groups[label] = rows if members is None else [r for r in rows if r["hour"] in members]
    for a, b in pairs:
        rng = np.random.default_rng(seed)
        for name, rs in groups.items():
            for metric in ("brier", "log"):
                by_date = defaultdict(list)
                for r in rs:
                    by_date[r["date"]].append(r[f"{a}_{metric}"] - r[f"{b}_{metric}"])
                dates = sorted(by_date)
                sums = np.array([sum(by_date[d]) for d in dates])
                counts = np.array([len(by_date[d]) for d in dates])
                idx = rng.integers(0, len(dates), size=(draws, len(dates)))
                boot = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
                out[f"{a}-{b}|{name}|{metric}"] = {
                    "estimate": float(sums.sum() / counts.sum()),
                    "ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
                    "n": len(rs), "n_dates": len(dates)}
    return out


def rung_g_score(*, layout, emit_dir, coefficients, nowcasts, rf_result, out_path, start="2026-08-01",
                 end="2026-09-29"):
    """R-G gates 3 and 4 on the dev scorecard (rule_rg.md); each gate stops the read if it fails."""
    import os

    import numpy as np

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas

    out_path = require_output_outside_repo(out_path)
    if out_path.exists():
        raise PooledModelError(f"refusing to overwrite {out_path}")
    emit = Path(emit_dir)
    audit = json.loads((emit / "rg_emit_audit.json").read_bytes())
    if audit.get("stopped_at") or not all(audit.get("ra_reproduction", {}).values()):
        raise PooledModelError(f"emit did not pass gates 1-2 or R-A reproduction: {audit.get('stopped_at')}")
    now_sha = hashlib.sha256(Path(nowcasts).read_bytes()).hexdigest()
    if now_sha != L6_NOWCAST_SHA256:
        raise PooledModelError(f"L6 nowcast sha {now_sha} != {L6_NOWCAST_SHA256}")
    os.environ["L6_NOWCASTS"] = str(nowcasts)
    from weather.reporting.scorecards.free_source_candidates import l6_stack

    l6_stack._CACHE.clear()
    state, part_sha = l6_frozen_state(coefficients)
    start_d, end_d = data.check_range(start, end)
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    fit_dates = sorted(d for d in {str(x) for x in lay.dates} if BLEND_FIT_FIRST <= d <= end)

    def arm_vec(table, arm):
        return l3._vector(table, l3._candidate_frame(str(emit / f"dev_{arm}.jsonl"), table, lay, folds, data)[0])

    full = sc.Table(lay, fit_dates)
    fdates = full.snaps.date.astype(str).to_numpy()
    weights = {}
    for name, cand in (("blend_l6_G", "P3d_G"), ("blend_l6", "P3d_N_fix")):
        pa, ca, _ = arm_vec(full, cand)
        pl, cl, _ = l6_vector(full, state, l3)
        A, B = blend_weight(pa, pl, full.y, full.offsets, full.n)
        weights[name] = walk_forward_weights(fdates, full.local_hour, ca & cl, A, B, scored)

    table = sc.Table(lay, scored)
    date_w = l3._date_weights([k[0] for k in table.keys], sc.DRAWS, sc.SEED)
    market_b = table.brier(table.p_market)
    vec = {arm: arm_vec(table, arm) for arm in RG_ARMS}
    p_mg1, cov_mg1, _ = l3._vector(table, loss_atlas.mg1_frame(table))
    p_l6, cov_l6, _ = l6_vector(table, state, l3)
    w0712 = (table.local_hour >= 7) & (table.local_hour <= 12)
    _, e = table.cells(table.brier(p_mg1) - market_b, w0712)
    mg1_excess = float(e.mean())
    if round(mg1_excess, 3) != l3.MG1_CONTROL_0712_EXCESS:
        raise PooledModelError(f"MG-1 positive control failed: {mg1_excess:.5f}")
    dates = table.snaps.date.astype(str).to_numpy()
    briers = {arm: table.brier(v[0]) for arm, v in vec.items()}
    covs = {arm: v[1] for arm, v in vec.items()}
    briers.update(l6=table.brier(p_l6), mg1=table.brier(p_mg1), served=table.brier(table.p_served))
    covs.update(l6=cov_l6, mg1=cov_mg1, served=np.ones(len(table.snaps), dtype=bool))
    for name, cand in (("blend_l6_G", "P3d_G"), ("blend_l6", "P3d_N_fix")):
        w_snap = np.array([weights[name].get((int(h), d), 0.0) for h, d in zip(table.local_hour, dates)])
        wb = np.where(covs[cand] & cov_l6, w_snap, 0.0)[table.band_snap]
        briers[name] = table.brier(wb * vec[cand][0] + (1.0 - wb) * p_l6)
        covs[name] = cov_l6
    common = covs["B_N"] & covs["B_G"] & covs["P3d_N_fix"] & covs["P3d_G"] & cov_l6
    everything = np.ones(len(table.snaps), dtype=bool)
    pools = [(sc.ALL_MARKETS, None), (l3.PRIMARY_POOL, set(l3.PRIMARY_MARKETS))] + [
        (m, {m}) for m in sorted(set(table.markets))]
    groups = [("07-12", 7, 12)] + [(f"h{h:02d}", h, h) for h in RUNG_HOURS]

    def compare(arm, ref):
        rows = []
        for scope in ("covered", "blended"):
            base = (common & covs[ref]) if scope == "covered" else everything
            for market, members in pools:
                in_pool = everything if members is None else np.isin(table.markets, sorted(members))
                for group, lo, hi in groups:
                    mask = base & in_pool & (table.local_hour >= lo) & (table.local_hour <= hi)
                    if not mask.any():
                        continue
                    idx, c = table.cells(briers[arm], mask)
                    _, r_ = table.cells(briers[ref], mask)
                    _, m = table.cells(market_b, mask)
                    rows.append({"arm": arm, "reference": ref, "scope": scope, "market": market, "group": group,
                                 "n_market_days": int(len(idx)), "n_snapshots": int(mask.sum()),
                                 "R_arm": sc.ratio_interval(table.w[:, idx], c, m),
                                 "R_reference": sc.ratio_interval(table.w[:, idx], r_, m),
                                 "dR_crossed": sc.ratio_interval(table.w[:, idx], c - r_, m),
                                 "dR_date_clustered": sc.ratio_interval(date_w[:, idx], c - r_, m)})
        return rows

    def primary(rows):
        return next(r for r in rows if r["scope"] == "covered" and r["market"] == sc.ALL_MARKETS
                    and r["group"] == "07-12")

    def reading(rows):
        p = primary(rows)["dR_date_clustered"]["ci95"]
        hours_lower = [r["dR_date_clustered"]["ci95"][0] for r in rows if r["scope"] == "covered"
                       and r["market"] == sc.ALL_MARKETS and r["group"] != "07-12"]
        if p[0] > 0:
            return "HARM"
        return "WIN" if p[1] < 0 and not any(lo > 0 for lo in hours_lower) else "NULL"

    # R-F reproduced (blend_l6 vs L6) as a positive control
    rf = json.loads(Path(rf_result).read_bytes())
    rf_row = next(r for r in rf["rows"] if r["arm"] == "blend_l6" and r["reference"] == "l6" and r["scope"] == "covered"
                  and r["market"] == sc.ALL_MARKETS and r["group"] == "07-12")
    rf_now = primary(compare("blend_l6", "l6"))["dR_date_clustered"]["estimate"]
    if abs(rf_now - rf_row["dR_date_clustered"]["estimate"]) > 1e-9:
        raise PooledModelError(f"R-F control failed: {rf_now} != {rf_row['dR_date_clustered']['estimate']}")
    result = {"rule": "C:/t/l2/rung0712/rule_rg.md", "rule_sha256": RG_RULE_SHA256,
              "population": {"n_dates": len(scored), "first_date": scored[0], "last_date": scored[-1],
                             "n_market_days": len(table.keys), "common_covered_snapshots_07_12": int((common & w0712).sum())},
              "controls": {"mg1_excess_07_12": mg1_excess, "rf_reproduced": rf_now, "l6_part_sha256": part_sha,
                           "l6_nowcast_sha256": now_sha, "ra_reproduction": audit["ra_reproduction"]},
              "inputs": {"emit_files": audit["files"], "layout_manifest_sha256": lay.manifest_sha256,
                         "scorecard_code_sha256": sc.code_sha256(),
                         "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
              "gates": {}, "rows": []}

    def done():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
        return result

    rows = compare("B_G", "B_N")
    result["rows"] += rows
    g3 = primary(rows)["dR_date_clustered"]
    result["gates"]["3a_B_G_vs_B_N"] = {"dR_date_clustered": g3, "pass": g3["ci95"][1] < 0}
    if not result["gates"]["3a_B_G_vs_B_N"]["pass"]:
        result["stopped_at"] = "gate 3 (B_G - B_N)"
        return done()
    for ref in ("P3d_N_fix", "B_G"):
        result["rows"] += compare("P3d_G", ref)
    g3b = primary([r for r in result["rows"] if r["arm"] == "P3d_G" and r["reference"] == "P3d_N_fix"])
    result["gates"]["3b_P3d_G_vs_P3d_N_fix"] = {"dR_date_clustered": g3b["dR_date_clustered"],
                                               "pass": g3b["dR_date_clustered"]["ci95"][1] < 0}
    if not result["gates"]["3b_P3d_G_vs_P3d_N_fix"]["pass"]:
        result["stopped_at"] = "gate 3 (P3d_G - P3d_N_fix)"
        return done()
    readings = {}
    for arm in ("P3d_G", "blend_l6_G"):
        rows = compare(arm, "l6")
        result["rows"] += rows
        readings[arm] = reading(rows)
    for arm, ref in (("blend_l6_G", "blend_l6"), ("P3d_G", "mg1"), ("blend_l6_G", "mg1")):
        result["rows"] += compare(arm, ref)
    result["gates"]["4_incumbent"] = readings
    result["weights"] = {name: {f"h{h:02d}": float(np.mean([w[(h, d)] for d in scored])) for h in RUNG_HOURS}
                         for name, w in weights.items()}
    return done()


# ------------------------------------------------- R-H: market-relative loss atlas (descriptive, selection evidence)

RH_LABEL = ("SELECTION EVIDENCE - descriptive dev-window atlas (2026-08-01..09-29 layout dates), reference = captured "
            "capture-time market p_market_yes; not pre-registered; no edge claim")
RH_WINDOWS = (("07-12", 7, 12), ("13-16", 13, 16))
RH_SMALL_N = 15
# onshore sectors (degrees true, METAR wind direction) for the coastal markets; speed >= 4 kt
RH_ONSHORE = {"los-angeles": (200, 290), "san-francisco": (240, 320), "seattle": (190, 300), "miami": (45, 150),
              "houston": (90, 200), "nyc": (30, 170)}
RH_TAGS = ("front", "cloud", "onshore", "obs_vs_nbm_path", "nbm_error_ex_post", "hrrr_minus_nbm", "nws_minus_nbm")


def _metar_obs(snapshot, tz, observation_instant):
    """Captured METAR rows -> sorted [(epoch s, row)] (corrections last)."""
    metar = (((snapshot.get("sources") or {}).get("metar") or {}).get("data")) or {}
    kept = {}
    for row in metar.get("rows") or []:
        instant = observation_instant(row, tz)[0]
        if instant is not None:
            kept[instant.timestamp()] = row
    return sorted(kept.items())


def _f(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def rh_obs_tags(obs, capture, market):
    """front / cloud / onshore from captured METAR rows observed at or before ``capture`` (epoch s)."""
    import bisect

    keys = [t for t, _ in obs]
    k = bisect.bisect_right(keys, capture)
    if k == 0:
        return {"front": "unknown", "cloud": "unknown", "onshore": "n/a" if market not in RH_ONSHORE else "unknown"}
    t_last, last = obs[k - 1]
    j = bisect.bisect_left(keys, t_last - 3 * 3600 - 1200, 0, k)
    then = obs[j][1] if j < k - 1 and t_last - obs[j][0] >= 2 * 3600 else None
    front = "unknown"
    if then is not None:
        p1, p0 = _f(last.get("pressure_hpa")), _f(then.get("pressure_hpa"))
        d1, d0 = _f(last.get("wind_dir")), _f(then.get("wind_dir"))
        s1, s0 = _f(last.get("wind_speed")), _f(then.get("wind_speed"))
        dp = abs(p1 - p0) >= 2.0 if (p1 is not None and p0 is not None) else False
        shift = False
        if None not in (d1, d0, s1, s0) and s1 >= 6 and s0 >= 6:
            diff = abs(d1 - d0) % 360
            shift = min(diff, 360 - diff) >= 90
        front = "front" if (dp or shift) else "no_front"
    cover = str(last.get("cover") or "").upper()
    cloud = ("overcast" if cover in ("OVC", "VV") else "broken" if cover == "BKN"
             else "clear_few_sct" if cover in ("CLR", "SKC", "FEW", "SCT", "CAVOK", "NSC", "NCD") else "unknown")
    if market not in RH_ONSHORE:
        onshore = "n/a"
    else:
        d, s = _f(last.get("wind_dir")), _f(last.get("wind_speed"))
        lo, hi = RH_ONSHORE[market]
        onshore = "unknown" if d is None or s is None else (
            "onshore" if (s >= 4 and lo <= d <= hi) else "not_onshore")
    return {"front": front, "cloud": cloud, "onshore": onshore}


def _bin(value, lo, hi, names=("cold", "near", "warm")):
    if value is None or not math.isfinite(value):
        return "unknown"
    return names[0] if value <= lo else names[2] if value >= hi else names[1]


def rh_tags(*, layout, replay_root, obs_parquet, out_path, markets=R0_MARKETS, hours=range(7, 17)):
    """Per-snapshot regime tags from captured obs and forecasts only (descriptive; R-H)."""
    import pandas as pd
    from zoneinfo import ZoneInfo

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.calibration.r0_ols_floor_devfit import usable_v2_mean
    from weather.market.market_registry import spec_for_id
    from weather.model import observed_running_max

    running_max = _require_metar_only(observed_running_max.running_max_since_midnight)
    out_path = require_output_outside_repo(out_path)
    if out_path.exists():
        raise PooledModelError(f"refusing to overwrite {out_path}")
    timezones = {m: spec_for_id(m).timezone for m in markets}
    iem, iem_sha = rg_iem_reports(obs_parquet, markets, timezones)
    fracs = {m: rg_diurnal_fraction(iem[m], ZoneInfo(timezones[m])) for m in markets}  # 2021-25 only
    del iem
    snaps = pd.read_parquet(Path(layout) / "inputs_snapshots.parquet", columns=[
        "snapshot_id", "row_key", "market", "target_date", "local_hour", "cutoff_hour", "v2_mean", "v2_stddev", "v2_available_at",
        "captured_at_utc", "hrrr_high", "nws_grid_high"])
    if (pd.to_datetime(snaps.target_date).dt.date > N_DEV_LAST).any():
        raise PooledModelError("layout holds a snapshot after 2026-09-29")
    snaps = snaps[snaps.local_hour.isin(list(hours)) & snaps.market.isin(markets)].copy()
    snaps["nbm_usable"] = usable_v2_mean(snaps)
    out, stats = [], defaultdict(int)
    for market in markets:
        spec = spec_for_id(market)
        tz = ZoneInfo(spec.timezone)
        folders = {target: folder for slug, target, folder in l3._event_folders(replay_root)
                   if slug == market and N_DEV_FIRST <= target <= N_DEV_LAST}
        rows = snaps[snaps.market == market].copy()
        rows["target"] = pd.to_datetime(rows.target_date).dt.date
        for target, group in rows.groupby("target"):
            folder = folders.get(target)
            if folder is None:
                stats["no_replay_folder"] += len(group)
                continue
            with open(Path(folder) / "replay_inputs.jsonl", "rb") as handle:
                index = replay_index(handle, target, tz)
                if not index:
                    stats["no_replay_snapshot"] += len(group)
                    continue

                def load(entry):
                    handle.seek(entry[1])
                    try:
                        return json.loads(handle.read(entry[2]))
                    except json.JSONDecodeError:
                        return None

                last = load(index[-1])
                final = None
                if last is not None:
                    reports = _captured_reports(last, tz, l3.metar_observation_instant)
                    same = [t for t, d in zip(reports[1], reports[2]) if d == target.toordinal()]
                    final = wu_whole_f(max(same), "half_up") if same else None
                parsed = {}
                for row in group.itertuples(index=False):
                    captured = pd.Timestamp(row.captured_at_utc)
                    captured = (captured.tz_localize("UTC") if captured.tzinfo is None else captured)
                    entry = latest_at_or_before(index, captured.to_pydatetime())
                    if entry is None:
                        stats["no_snapshot_at_or_before"] += 1
                        continue
                    if entry[1] not in parsed:
                        snap = load(entry)
                        parsed = {entry[1]: None if snap is None else (snap, _metar_obs(
                            snap, tz, l3.metar_observation_instant))}
                    item = parsed[entry[1]]
                    if item is None:
                        stats["corrupt_line"] += 1
                        continue
                    snap, obs = item
                    at = entry[0].timestamp()
                    tags = rh_obs_tags(obs, at, market)
                    nbm = _f(row.nbm_usable)
                    hour_now = entry[0].astimezone(tz).hour
                    gap = float("nan")
                    try:
                        cutoff = int(str(row.cutoff_hour))
                    except ValueError:
                        cutoff = None
                    if nbm is not None and cutoff is not None and int(row.local_hour) >= cutoff:
                        rec = rung_inputs(snap, target, tz, cutoff, spec.display_unit, entry[0], running_max,
                                          l3.observations_at_cutoff)
                        if rec["high_so_far"] is not None:
                            feats = trajectory_features(*_captured_reports(snap, tz, l3.metar_observation_instant),
                                                        at, target.toordinal())
                            gap = rg_columns(feats, float(rec["high_so_far"]), nbm, target.month, hour_now,
                                             fracs[market])["t_path_gap"]
                    hr, nws = _f(row.hrrr_high), _f(row.nws_grid_high)
                    out.append({"row_key": row.row_key, "snapshot_id": row.snapshot_id, **tags,
                                "obs_vs_nbm_path": _bin(gap, -1.0, 1.0),
                                "nbm_error_ex_post": _bin(None if (final is None or nbm is None) else final - nbm,
                                                          -2.0, 2.0),
                                "hrrr_minus_nbm": _bin(None if (hr is None or nbm is None) else hr - nbm, -2.0, 2.0),
                                "nws_minus_nbm": _bin(None if (nws is None or nbm is None) else nws - nbm, -2.0, 2.0)})
                    stats["tagged"] += 1
        print(f"rh tags {market}: {dict(stats)}", flush=True)
    frame = pd.DataFrame(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out_path, index=False)
    audit = {"label": RH_LABEL, "counts": dict(stats), "obs_parquet_sha256": iem_sha,
             "distribution": {t: frame[t].value_counts().to_dict() for t in RH_TAGS},
             "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             "file_sha256": hashlib.sha256(out_path.read_bytes()).hexdigest()}
    out_path.with_suffix(".audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True), encoding="utf-8")
    return audit


def rh_atlas(*, layout, p3d_files, coefficients, nowcasts, tags_path, out_path, start="2026-08-01",
             end="2026-09-29"):
    """R-H market-relative loss atlas: excess Brier (arm - capture-time market) by market, hour, bucket position and
    capture-time regime, date-clustered 95% intervals, for L6 and P3d_N_fix at 07-12 and 13-16."""
    import os

    import numpy as np
    import pandas as pd

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas

    out_path = require_output_outside_repo(out_path)
    if out_path.exists():
        raise PooledModelError(f"refusing to overwrite {out_path}")
    now_sha = hashlib.sha256(Path(nowcasts).read_bytes()).hexdigest()
    if now_sha != L6_NOWCAST_SHA256:
        raise PooledModelError(f"L6 nowcast sha {now_sha} != {L6_NOWCAST_SHA256}")
    os.environ["L6_NOWCASTS"] = str(nowcasts)
    from weather.reporting.scorecards.free_source_candidates import l6_stack

    l6_stack._CACHE.clear()
    state, part_sha = l6_frozen_state(coefficients)
    combined = out_path.parent / "dev_P3d_N_fix_07_16.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(combined, "wb") as w:
        for f in p3d_files:
            w.write(Path(f).read_bytes())
    start_d, end_d = data.check_range(start, end)
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    dates = sorted(d for d in {str(x) for x in lay.dates} if start <= d <= end)

    # positive control on the standard scored population
    ctl = sc.Table(lay, scored)
    p_mg1c, _, _ = l3._vector(ctl, loss_atlas.mg1_frame(ctl))
    _, e = ctl.cells(ctl.brier(p_mg1c) - ctl.brier(ctl.p_market), (ctl.local_hour >= 7) & (ctl.local_hour <= 12))
    mg1_excess = float(e.mean())
    if round(mg1_excess, 3) != l3.MG1_CONTROL_0712_EXCESS:
        raise PooledModelError(f"MG-1 positive control failed: {mg1_excess:.5f}")
    del ctl

    table = sc.Table(lay, dates)
    date_w = l3._date_weights([k[0] for k in table.keys], sc.DRAWS, sc.SEED)
    p_fix, cov_fix, r_fix = l3._vector(table, l3._candidate_frame(str(combined), table, lay, folds, data)[0])
    p_l6, cov_l6, r_l6 = l6_vector(table, state, l3)
    p_mkt = table.p_market
    b_mkt = table.brier(p_mkt)
    arms = {"L6": (p_l6, cov_l6), "P3d_N_fix": (p_fix, cov_fix)}
    tags = pd.read_parquet(tags_path).set_index("row_key").reindex(table.snaps.row_key)
    tag_cols = {t: tags[t].fillna("untagged").astype(str).to_numpy() for t in RH_TAGS}
    common = cov_fix & cov_l6
    hours = table.local_hour
    markets = table.markets

    def cell(arm, mask, total_sum):
        p, _ = arms[arm]
        b = table.brier(p)
        if not mask.any():
            return None
        idx, c = table.cells(b, mask)
        _, m = table.cells(b_mkt, mask)
        n_dates = len({table.keys[i][0] for i in idx})
        ex = sc.ratio_interval(date_w[:, idx], c - m, np.ones_like(c))
        return {"n_market_days": int(len(idx)), "n_dates": int(n_dates), "n_snapshots": int(mask.sum()),
                "small_n": bool(len(idx) < RH_SMALL_N), "brier_arm": float(c.mean()), "brier_market": float(m.mean()),
                "excess": ex, "R": sc.ratio_interval(date_w[:, idx], c, m),
                "share_of_window_excess": float((b - b_mkt)[mask].sum() / total_sum) if total_sum else None}

    cls, has_winner = position_classes(table)
    result = {"label": RH_LABEL, "controls": {"mg1_excess_07_12_scored": mg1_excess, "l6_part_sha256": part_sha,
                                              "l6_nowcast_sha256": now_sha},
              "population": {"dates": [dates[0], dates[-1], len(dates)], "n_market_days": len(table.keys),
                             "common_covered_snapshots": {w: int((common & (hours >= lo) & (hours <= hi)).sum())
                                                          for w, lo, hi in RH_WINDOWS}},
              "coverage": {"P3d_N_fix": r_fix, "L6": r_l6},
              "inputs": {"p3d_files": {str(f): hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in p3d_files},
                         "tags_sha256": hashlib.sha256(Path(tags_path).read_bytes()).hexdigest(),
                         "layout_manifest_sha256": lay.manifest_sha256, "scorecard_code_sha256": sc.code_sha256(),
                         "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
              "cells": [], "positions": [], "tag_crosstab": {}}
    for window, lo, hi in RH_WINDOWS:
        in_w = common & (hours >= lo) & (hours <= hi)
        for arm in arms:
            b = table.brier(arms[arm][0])
            total = float((b - b_mkt)[in_w].sum())

            def add(dim, value, mask):
                c = cell(arm, mask, total)
                if c is not None:
                    result["cells"].append({"window": window, "arm": arm, "dim": dim, "value": value, **c})

            add("all", "all", in_w)
            for m in sorted(set(markets)):
                add("market", m, in_w & (markets == m))
            for h in range(lo, hi + 1):
                add("hour", f"h{h:02d}", in_w & (hours == h))
            for t, values in tag_cols.items():
                for v in sorted(set(values[in_w])):
                    add(t, v, in_w & (values == v))
            for m in sorted(RH_ONSHORE):
                for v in ("onshore", "not_onshore"):
                    add("market_x_onshore", f"{m}|{v}", in_w & (markets == m) & (tag_cols["onshore"] == v))
            # bucket position: exact decomposition of the window's excess, and where each side puts its mass
            p = arms[arm][0]
            diff_band = ((p - table.y) ** 2 - (p_mkt - table.y) ** 2) / np.repeat(table.n, table.n)
            idx, mden = table.cells(np.ones(len(table.snaps)), in_w)
            for k, name in enumerate(POSITION_CLASSES):
                sel = cls == k
                per_snap = np.bincount(table.band_snap, weights=np.where(sel, diff_band, 0.0),
                                       minlength=len(table.snaps))
                mass_arm = np.bincount(table.band_snap, weights=np.where(sel, p, 0.0), minlength=len(table.snaps))
                mass_mkt = np.bincount(table.band_snap, weights=np.where(sel, p_mkt, 0.0), minlength=len(table.snaps))
                _, cnum = table.cells(per_snap, in_w)
                result["positions"].append({
                    "window": window, "arm": arm, "position": name,
                    "excess_contribution": sc.ratio_interval(date_w[:, idx], cnum, mden),
                    "mean_mass_arm": float(mass_arm[in_w].mean()), "mean_mass_market": float(mass_mkt[in_w].mean())})
        for t, values in tag_cols.items():
            result["tag_crosstab"][f"{window}|{t}"] = pd.Series(values[in_w]).value_counts().to_dict()
    out_path.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


# ------------------------------------------------- R-I: per-hour temperature on the 07-12 arms (rule_ri.md)

RI_RULE_SHA256 = "b8a3d79ca13111db2bd667dc16e7a8418ddfe27bfaecbfaea23b099037341730"
RI_FIX_SHA256 = "cd0034b9faec0b687e1184187feeaa39ab151c5f9f8d1c905d3a49a0e7089542"  # R-A 07-12 vectors
RI_TAU_GRID = tuple(round(0.50 + 0.01 * i, 2) for i in range(251))  # 0.50 .. 3.00, contains 1.00
RI_LABEL_ALT = ("SELECTION EVIDENCE - alternative reading: arm re-centred on the capture-time market-implied median "
                "band; consumes the market benchmark; never a gate, never an arm, never booked as improvement")


def ri_pick_tau(loss_by_tau, grid=RI_TAU_GRID):
    """Grid minimiser; ties go to the tau closest to 1.00."""
    import numpy as np

    loss = np.asarray(loss_by_tau, dtype=float)
    best = np.flatnonzero(loss <= loss.min() + 1e-15)
    return float(min((grid[i] for i in best), key=lambda t: (abs(t - 1.0), t)))


def ri_temper(p, offsets, n, tau_band):
    """q_b proportional to p_b ** tau within each snapshot; zero bands stay zero; an all-zero snapshot is unchanged."""
    import numpy as np

    p = np.asarray(p, dtype=float)
    q = np.where(p > 0, np.power(np.where(p > 0, p, 1.0), tau_band), 0.0)
    s = np.add.reduceat(q, offsets)
    s_band = np.repeat(s, n)
    return np.where(s_band > 0, q / np.where(s_band > 0, s_band, 1.0), p)


def _ri_dict_losses(probs, actual_index, grid=RI_TAU_GRID):
    """Multi-category Brier (sum over buckets, fm.brier_score form) of one distribution at every grid tau."""
    import numpy as np

    p = np.asarray(probs, dtype=float)
    onehot = np.zeros(len(p))
    if actual_index is not None:
        onehot[actual_index] = 1.0
    taus = np.asarray(grid)[:, None]
    q = np.where(p > 0, np.power(np.where(p > 0, p, 1.0)[None, :], taus), 0.0)
    s = q.sum(axis=1, keepdims=True)
    q = np.where(s > 0, q / np.where(s > 0, s, 1.0), p[None, :])
    return ((q - onehot[None, :]) ** 2).sum(axis=1)


def ri_loyo(frame, buckets, hours=RUNG_HOURS):
    """Gate 1: strictly nested LOYO of the per-hour temperature on P3d_N_fix (2021-25 Aug-Sep rows)."""
    import numpy as np

    rows, taus = [], {}
    for hour in hours:
        at_hour = frame[frame["hour"] == hour]
        years = sorted(int(y) for y in at_hour["year"].unique())

        def predict(train_years, target_year):
            train = at_hour[at_hour["year"].isin(train_years)].reset_index(drop=True)
            val = at_hour[at_hour["year"] == target_year].reset_index(drop=True)
            entry = _rung_entry(train, *_arm_spec(RUNG_ARMS["P3d_N_fix"]))
            out = []
            for market in sorted(val["market"].unique()):
                part = val[val["market"] == market].reset_index(drop=True)
                for i, dist in enumerate(_dist_from_fit(entry, part, buckets, market)):
                    keys = list(dist)
                    actual = int(part.at[i, "y"])
                    out.append((market, str(part.at[i, "target_date"])[:10], [dist[k] for k in keys],
                                keys.index(actual) if actual in keys else None))
            return out

        for held in years:
            inner = np.zeros(len(RI_TAU_GRID))
            for x in years:
                if x == held:
                    continue
                for _, _, probs, a in predict([y for y in years if y not in (x, held)], x):
                    inner += _ri_dict_losses(probs, a)
            tau = ri_pick_tau(inner)
            one = RI_TAU_GRID.index(1.0)
            taus[(hour, held)] = {"tau": tau, "inner_brier_uncal": float(inner[one]),
                                  "inner_brier_cal": float(inner[RI_TAU_GRID.index(tau)]),
                                  "training_score_not_worse": bool(inner[RI_TAU_GRID.index(tau)] <= inner[one] + 1e-12)}
            for market, day, probs, a in predict([y for y in years if y != held], held):
                losses = _ri_dict_losses(probs, a, grid=(1.0, tau))
                rows.append({"hour": int(hour), "year": int(held), "market": market, "date": day,
                             "tau": tau, "P3d_N_fix_brier": float(losses[0]), "P3d_N_fix_cal_brier": float(losses[1])})
            print(f"ri loyo h{hour:02d} held {held}: tau {tau}", flush=True)
    return rows, taus


def ri_loyo_summary(rows, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED):
    import numpy as np

    out = {}
    groups = {f"h{h:02d}": [r for r in rows if r["hour"] == h] for h in sorted({r["hour"] for r in rows})}
    groups["07-12"] = rows
    rng = np.random.default_rng(seed)
    for name, rs in groups.items():
        by_date = defaultdict(list)
        for r in rs:
            by_date[r["date"]].append(r["P3d_N_fix_cal_brier"] - r["P3d_N_fix_brier"])
        dates = sorted(by_date)
        sums = np.array([sum(by_date[d]) for d in dates])
        counts = np.array([len(by_date[d]) for d in dates])
        idx = rng.integers(0, len(dates), size=(draws, len(dates)))
        boot = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
        out[name] = {"cal_minus_uncal": float(sums.sum() / counts.sum()),
                     "ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
                     "uncal_mean": float(np.mean([r["P3d_N_fix_brier"] for r in rs])), "n": len(rs),
                     "n_dates": len(dates)}
    return out


def rung_i_loyo(*, records_root, nbm_train_corpus, ra_loyo_rows, out_dir, markets=R0_MARKETS, hours=RUNG_HOURS):
    """R-I gate 1 (rule_ri.md): nested LOYO, with R-A's uncalibrated LOYO Brier reproduced as a positive control."""
    from weather.calibration import ols_floor_ladder as l9
    from weather.market.market_registry import spec_for_id

    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name in ("ri_loyo.json", "ri_loyo_rows.jsonl"):
        if (out / name).exists():
            raise PooledModelError(f"refusing to overwrite {out / name}")
    timezones = {m: spec_for_id(m).timezone for m in markets}
    frame, buckets = dev_training_frame(records_root, markets)
    if frame["year"].max() >= 2026:
        raise PooledModelError("a dev training row is from 2026")
    frame, train_stats = attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff, timezones)
    frame = frame[frame["hour"].isin(hours)].reset_index(drop=True)
    rows, taus = ri_loyo(frame, buckets, hours)
    ra = {}
    with open(ra_loyo_rows, encoding="utf-8") as handle:
        for line in handle:
            r = json.loads(line)
            ra[(r["hour"], r["market"], r["date"])] = r["P3d_N_fix_brier"]
    worst = max(abs(r["P3d_N_fix_brier"] - ra[(r["hour"], r["market"], r["date"])]) for r in rows)
    if len(ra) != len(rows) or worst > 1e-9:
        raise PooledModelError(f"R-A LOYO control failed: rows {len(rows)} vs {len(ra)}, max diff {worst}")
    _write_jsonl(out / "ri_loyo_rows.jsonl", rows)
    summary = ri_loyo_summary(rows)
    result = {"rule_sha256": RI_RULE_SHA256, "train_nbm": train_stats,
              "controls": {"ra_loyo_rows": len(ra), "ra_max_abs_diff": worst,
                           "training_score_not_worse_all": all(v["training_score_not_worse"] for v in taus.values())},
              "taus": {f"h{h:02d}|{y}": v for (h, y), v in sorted(taus.items())}, "summary": summary,
              "gate1_pass": summary["07-12"]["ci95"][1] < 0,
              "inputs": {"nbm_train_corpus": hashlib.sha256(Path(nbm_train_corpus).read_bytes()).hexdigest(),
                         "ra_loyo_rows": hashlib.sha256(Path(ra_loyo_rows).read_bytes()).hexdigest(),
                         "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    if not result["controls"]["training_score_not_worse_all"]:
        raise PooledModelError("a fitted tau worsened its own training score")
    (out / "ri_loyo.json").write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


def ri_walk_forward_taus(briers_by_tau, dates, hours, covered, scored_dates, hour_set=RUNG_HOURS):
    """tau(h, d) = grid minimiser of the summed per-snapshot Brier on covered snapshots at hour h dated before d."""
    import numpy as np

    out = {}
    for h in hour_set:
        at = covered & (hours == h)
        for d in scored_dates:
            sel = at & (dates < d)
            out[(h, d)] = ri_pick_tau(briers_by_tau[sel].sum(axis=0)) if sel.any() else 1.0
    return out


def ri_recentre(p, ref, offsets, n, impossible):
    """Shift each snapshot's distribution so its median band equals the reference's median band (R-I alt reading)."""
    import numpy as np

    out = np.array(p, dtype=float, copy=True)
    for o, k in zip(offsets, n):
        a, r = out[o:o + k], np.asarray(ref[o:o + k], dtype=float)
        if a.sum() <= 0 or r.sum() <= 0:
            continue
        shift = int(np.argmax(np.cumsum(r) / r.sum() >= 0.5)) - int(np.argmax(np.cumsum(a) / a.sum() >= 0.5))
        if shift == 0:
            continue
        moved = np.zeros(k)
        np.add.at(moved, np.clip(np.arange(k) + shift, 0, k - 1), a)
        moved[np.asarray(impossible[o:o + k], dtype=bool)] = 0.0
        if moved.sum() > 0:
            out[o:o + k] = moved / moved.sum()
    return out


def rung_i_score(*, layout, fix_jsonl, coefficients, nowcasts, loyo_result, out_path, start="2026-08-01",
                 end="2026-09-29"):
    """R-I gates 2 and 3, the reported comparisons and the alternative reading (rule_ri.md)."""
    import os

    import numpy as np

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas

    out_path = require_output_outside_repo(out_path)
    if out_path.exists():
        raise PooledModelError(f"refusing to overwrite {out_path}")
    loyo = json.loads(Path(loyo_result).read_bytes())
    if loyo.get("rule_sha256") != RI_RULE_SHA256 or not loyo.get("gate1_pass"):
        raise PooledModelError("gate 1 has not passed under this rule; gate 2 may not run (KILL applies)")
    now_sha = hashlib.sha256(Path(nowcasts).read_bytes()).hexdigest()
    if now_sha != L6_NOWCAST_SHA256:
        raise PooledModelError(f"L6 nowcast sha {now_sha} != {L6_NOWCAST_SHA256}")
    fix_sha = hashlib.sha256(Path(fix_jsonl).read_bytes()).hexdigest()
    if fix_sha != RI_FIX_SHA256:
        raise PooledModelError(f"P3d_N_fix vectors sha {fix_sha} != {RI_FIX_SHA256}")
    os.environ["L6_NOWCASTS"] = str(nowcasts)
    from weather.reporting.scorecards.free_source_candidates import l6_stack

    l6_stack._CACHE.clear()
    state, part_sha = l6_frozen_state(coefficients)
    start_d, end_d = data.check_range(start, end)
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    fit_dates = sorted(d for d in {str(x) for x in lay.dates} if BLEND_FIT_FIRST <= d <= end)

    def vectors(table):
        fix = l3._vector(table, l3._candidate_frame(str(fix_jsonl), table, lay, folds, data)[0])
        return fix, l6_vector(table, state, l3)

    def tau_band(table, taus, covered):
        dates = table.snaps.date.astype(str).to_numpy()
        t = np.array([taus.get((int(h), d), 1.0) if c else 1.0
                      for h, d, c in zip(table.local_hour, dates, covered)])
        return t[table.band_snap], t

    # walk-forward taus on the fitting table (every dev date from 2026-08-01, dates strictly before each scored date)
    full = sc.Table(lay, fit_dates)
    (fa, fcov, _), (la, lcov, _) = vectors(full)
    fdates = full.snaps.date.astype(str).to_numpy()
    in_hours = (full.local_hour >= 7) & (full.local_hour <= 12)
    taus = {}
    for name, (p, cov) in {"P3d_N_fix": (fa, fcov & lcov), "L6": (la, fcov & lcov)}.items():
        sel = cov & in_hours
        grid = np.zeros((len(full.snaps), len(RI_TAU_GRID)))
        for j, tau in enumerate(RI_TAU_GRID):
            grid[sel, j] = full.brier(ri_temper(p, full.offsets, full.n, np.full(len(p), tau)))[sel]
        taus[name] = ri_walk_forward_taus(grid, fdates, full.local_hour, sel, scored)
        del grid
    del full, fa, la

    table = sc.Table(lay, scored)
    date_w = l3._date_weights([k[0] for k in table.keys], sc.DRAWS, sc.SEED)
    market_b = table.brier(table.p_market)
    (p_fix, cov_fix, r_fix), (p_l6, cov_l6, r_l6) = vectors(table)
    p_mg1, _, _ = l3._vector(table, loss_atlas.mg1_frame(table))
    w0712 = (table.local_hour >= 7) & (table.local_hour <= 12)
    _, e = table.cells(table.brier(p_mg1) - market_b, w0712)
    mg1_excess = float(e.mean())
    if round(mg1_excess, 3) != l3.MG1_CONTROL_0712_EXCESS:
        raise PooledModelError(f"MG-1 positive control failed: {mg1_excess:.5f}")
    common = cov_fix & cov_l6
    tb_fix, _ = tau_band(table, taus["P3d_N_fix"], common)
    tb_l6, _ = tau_band(table, taus["L6"], common)
    probs = {"P3d_N_fix": p_fix, "L6": p_l6,
             "P3d_N_fix_cal": ri_temper(p_fix, table.offsets, table.n, tb_fix),
             "L6_cal": ri_temper(p_l6, table.offsets, table.n, tb_l6)}
    for name in list(probs):
        mass = np.add.reduceat(probs[name], table.offsets)
        if np.any(np.abs(mass[common] - 1.0) > 1e-9):
            raise PooledModelError(f"{name}: probability mass not preserved")
    if np.any(probs["P3d_N_fix_cal"][(p_fix == 0) & common[table.band_snap]] != 0):
        raise PooledModelError("tempering moved mass into a zero band")
    briers = {k: table.brier(v) for k, v in probs.items()}
    groups = [("07-12", 7, 12)] + [(f"h{h:02d}", h, h) for h in RUNG_HOURS]
    pools = [(sc.ALL_MARKETS, None)] + [(m, {m}) for m in sorted(set(table.markets))]

    def compare(arm, ref, b=briers):
        rows = []
        for market, members in pools:
            in_pool = np.ones(len(table.snaps), bool) if members is None else np.isin(table.markets, sorted(members))
            for group, lo, hi in groups if members is None else groups[:1]:
                mask = common & in_pool & (table.local_hour >= lo) & (table.local_hour <= hi)
                if not mask.any():
                    continue
                idx, c = table.cells(b[arm], mask)
                _, r_ = table.cells(b[ref], mask)
                _, m = table.cells(market_b, mask)
                rows.append({"arm": arm, "reference": ref, "market": market, "group": group,
                             "n_market_days": int(len(idx)), "n_snapshots": int(mask.sum()),
                             "R_arm": sc.ratio_interval(table.w[:, idx], c, m),
                             "R_reference": sc.ratio_interval(table.w[:, idx], r_, m),
                             "dR_crossed": sc.ratio_interval(table.w[:, idx], c - r_, m),
                             "dR_date_clustered": sc.ratio_interval(date_w[:, idx], c - r_, m)})
        return rows

    def primary(rows):
        return next(r for r in rows if r["market"] == sc.ALL_MARKETS and r["group"] == "07-12")

    def hours_lower(rows):
        return [r["dR_date_clustered"]["ci95"][0] for r in rows if r["market"] == sc.ALL_MARKETS
                and r["group"] != "07-12"]

    def reading(rows):
        p = primary(rows)["dR_date_clustered"]["ci95"]
        if p[0] > 0:
            return "HARM"
        return "WIN" if p[1] < 0 and not any(lo > 0 for lo in hours_lower(rows)) else "NULL"

    result = {"rule": "C:/t/l2/rungi/rule_ri.md", "rule_sha256": RI_RULE_SHA256,
              "population": {"n_dates": len(scored), "first_date": scored[0], "last_date": scored[-1],
                             "n_market_days": len(table.keys), "common_covered_snapshots_07_12":
                                 int((common & w0712).sum())},
              "controls": {"mg1_excess_07_12": mg1_excess, "l6_part_sha256": part_sha, "l6_nowcast_sha256": now_sha,
                           "gate1": loyo["summary"]["07-12"]},
              "coverage": {"P3d_N_fix": r_fix, "L6": r_l6},
              "inputs": {"fix_jsonl": fix_sha, "loyo_result": hashlib.sha256(Path(loyo_result).read_bytes()).hexdigest(),
                         "layout_manifest_sha256": lay.manifest_sha256, "scorecard_code_sha256": sc.code_sha256(),
                         "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
              "taus": {arm: {f"h{h:02d}": {"mean": float(np.mean([t[(h, d)] for d in scored])),
                                           "first": t[(h, scored[0])], "last": t[(h, scored[-1])]}
                             for h in RUNG_HOURS} for arm, t in taus.items()},
              "gates": {}, "rows": [], "reported": {}}

    def done():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
        return result

    result["rows"] += compare("P3d_N_fix", "L6")  # R-F incumbent control (reported)
    rows = compare("P3d_N_fix_cal", "P3d_N_fix")
    result["rows"] += rows
    g2 = primary(rows)["dR_date_clustered"]
    result["gates"]["2_dev_vs_uncal"] = {"dR_date_clustered": g2, "hours_lower": hours_lower(rows),
                                         "pass": g2["ci95"][1] < 0 and not any(lo > 0 for lo in hours_lower(rows))}
    if not result["gates"]["2_dev_vs_uncal"]["pass"]:
        result["stopped_at"] = "gate 2 (KILL: width lever closed again for the NBM family)"
    else:
        rows = compare("P3d_N_fix_cal", "L6")
        result["rows"] += rows
        result["gates"]["3_vs_L6"] = {"reading": reading(rows), "dR_date_clustered": primary(rows)["dR_date_clustered"]}
    result["rows"] += compare("L6_cal", "L6")

    # bucket-position decomposition, P3d_N_fix_cal - P3d_N_fix (reported)
    cls, _ = position_classes(table)
    mask = common & w0712
    idx, mden = table.cells(np.ones(len(table.snaps)), mask)
    diff_band = ((probs["P3d_N_fix_cal"] - table.y) ** 2 - (p_fix - table.y) ** 2) / np.repeat(table.n, table.n)
    pos = {}
    for k, name in enumerate(POSITION_CLASSES):
        sel = cls == k
        per = np.bincount(table.band_snap, weights=np.where(sel, diff_band, 0.0), minlength=len(table.snaps))
        _, cnum = table.cells(per, mask)
        pos[name] = {"contribution": sc.ratio_interval(date_w[:, idx], cnum, mden),
                     **{f"mass_{a}": float(np.bincount(table.band_snap, weights=np.where(sel, probs[a], 0.0),
                                                       minlength=len(table.snaps))[mask].mean())
                        for a in ("P3d_N_fix", "P3d_N_fix_cal", "L6", "L6_cal")},
                     "mass_market": float(np.bincount(table.band_snap, weights=np.where(sel, table.p_market, 0.0),
                                                      minlength=len(table.snaps))[mask].mean())}
    result["reported"]["positions_07_12"] = pos

    # alternative reading (selection evidence): re-centre on the capture-time market-implied median band
    alt = {"label": RI_LABEL_ALT}
    for arm in ("P3d_N_fix", "L6"):
        rc_u = table.brier(ri_recentre(probs[arm], table.p_market, table.offsets, table.n, table.impossible))
        rc_c = table.brier(ri_recentre(probs[f"{arm}_cal"], table.p_market, table.offsets, table.n, table.impossible))
        _, cu = table.cells(briers[arm], mask)
        _, cc = table.cells(briers[f"{arm}_cal"], mask)
        _, ru = table.cells(rc_u, mask)
        _, rc = table.cells(rc_c, mask)
        _, m = table.cells(market_b, mask)
        alt[arm] = {"excess_uncal": sc.ratio_interval(date_w[:, idx], cu - m, mden),
                    "excess_cal": sc.ratio_interval(date_w[:, idx], cc - m, mden),
                    "excess_recentred_uncal": sc.ratio_interval(date_w[:, idx], ru - m, mden),
                    "excess_recentred_cal": sc.ratio_interval(date_w[:, idx], rc - m, mden),
                    "gain_cal": sc.ratio_interval(date_w[:, idx], cu - cc, mden),
                    "gain_cal_after_recentring": sc.ratio_interval(date_w[:, idx], ru - rc, mden),
                    "surviving_share": sc.ratio_interval(date_w[:, idx], ru - rc, cu - cc)}
    result["reported"]["alternative_reading"] = alt
    return done()


# ------------------------------------------------- R-J: R-G trajectory columns in the afternoon (rule_rj.md)

RJ_RULE_SHA256 = "e948c0a288f6e4a1cf4f3f143b8246cb11bc48e21cc67238187c180f58dfe171"
RJ_HOURS = (13, 14, 15, 16)
RJ_GATE = ("13-14", (13, 14))
RJ_SECONDARY = ("15-16", (15, 16))
RJ_P3D_N_SHA256 = "721ae2cd24283115f68c4b6a1b38d84d34a81921e41468d360b587599fd031ec"  # composite post-13 dev arm
RJ_RH_EMIT = {"dev_P3d_N_fix.jsonl": "abc4350724fe42a5d2423dcf5dd3f1c1b06dcea4799cb0d297bd6de465096109",
              "dev_B_N.jsonl": "bab9cac728a5b363888278ad66b12e73807b5e0ae0849bcb13f12f5e8139f186"}


def rung_j_score(*, layout, emit_dir, p3d_n_jsonl, out_path, start="2026-08-01", end="2026-09-29"):
    """R-J gates 3 and 4 on the dev scorecard (rule_rj.md); gate 3 failing is the pre-registered kill."""
    import numpy as np

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas

    out_path = require_output_outside_repo(out_path)
    if out_path.exists():
        raise PooledModelError(f"refusing to overwrite {out_path}")
    emit = Path(emit_dir)
    audit = json.loads((emit / "rg_emit_audit.json").read_bytes())
    if audit.get("rule_sha256") != RJ_RULE_SHA256 or audit.get("stopped_at"):
        raise PooledModelError(f"emit is not an R-J emit that passed gates 1-2: {audit.get('stopped_at')}")
    for name, sha in RJ_RH_EMIT.items():
        if audit["files"].get(name) != sha:
            raise PooledModelError(f"R-H reproduction failed for {name}: {audit['files'].get(name)} != {sha}")
    n_sha = hashlib.sha256(Path(p3d_n_jsonl).read_bytes()).hexdigest()
    if n_sha != RJ_P3D_N_SHA256:
        raise PooledModelError(f"P3d_N dev sha {n_sha} != {RJ_P3D_N_SHA256}")
    start_d, end_d = data.check_range(start, end)
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    table = sc.Table(lay, scored)
    date_w = l3._date_weights([k[0] for k in table.keys], sc.DRAWS, sc.SEED)
    market_b = table.brier(table.p_market)

    def vec(path):
        return l3._vector(table, l3._candidate_frame(str(path), table, lay, folds, data)[0])

    arms = {arm: vec(emit / f"dev_{arm}.jsonl") for arm in RG_ARMS}
    p_mg1, cov_mg1, _ = l3._vector(table, loss_atlas.mg1_frame(table))
    p_n, cov_n, r_n = vec(p3d_n_jsonl)
    w0712 = (table.local_hour >= 7) & (table.local_hour <= 12)
    _, e = table.cells(table.brier(p_mg1) - market_b, w0712)
    mg1_excess = float(e.mean())
    if round(mg1_excess, 3) != l3.MG1_CONTROL_0712_EXCESS:
        raise PooledModelError(f"MG-1 positive control failed: {mg1_excess:.5f}")
    # composite post-13 half: P3d_N where the scorecard uses it, else MG-1 (mg2_composite.compose)
    p_comp = np.where(cov_n[table.band_snap], p_n, p_mg1)
    cov_comp = cov_n | cov_mg1
    briers = {arm: table.brier(v[0]) for arm, v in arms.items()}
    covs = {arm: v[1] for arm, v in arms.items()}
    briers["composite_post13"], covs["composite_post13"] = table.brier(p_comp), cov_comp
    common = covs["B_N"] & covs["B_G"] & covs["P3d_N_fix"] & covs["P3d_G"] & cov_comp
    in_rj = (table.local_hour >= 13) & (table.local_hour <= 16)
    groups = [(RJ_GATE[0], 13, 14), ("h13", 13, 13), ("h14", 14, 14), (RJ_SECONDARY[0], 15, 16), ("h15", 15, 15),
              ("h16", 16, 16)]
    pools = [(sc.ALL_MARKETS, None)] + [(m, {m}) for m in sorted(set(table.markets))]

    def compare(arm, ref):
        rows = []
        for market, members in pools:
            in_pool = np.ones(len(table.snaps), bool) if members is None else np.isin(table.markets, sorted(members))
            for group, lo, hi in (groups if members is None else [groups[0], groups[3]]):
                mask = common & in_pool & (table.local_hour >= lo) & (table.local_hour <= hi)
                if not mask.any():
                    continue
                idx, c = table.cells(briers[arm], mask)
                _, r_ = table.cells(briers[ref], mask)
                _, m = table.cells(market_b, mask)
                rows.append({"arm": arm, "reference": ref, "market": market, "group": group,
                             "n_market_days": int(len(idx)), "n_snapshots": int(mask.sum()),
                             "R_arm": sc.ratio_interval(table.w[:, idx], c, m),
                             "R_reference": sc.ratio_interval(table.w[:, idx], r_, m),
                             "dR_crossed": sc.ratio_interval(table.w[:, idx], c - r_, m),
                             "dR_date_clustered": sc.ratio_interval(date_w[:, idx], c - r_, m)})
        return rows

    def pick(rows, group):
        return next(r for r in rows if r["market"] == sc.ALL_MARKETS and r["group"] == group)

    def reading(rows):
        p = pick(rows, RJ_GATE[0])["dR_date_clustered"]["ci95"]
        lower = [pick(rows, g)["dR_date_clustered"]["ci95"][0] for g in ("h13", "h14")]
        if p[0] > 0:
            return "HARM"
        return "WIN" if p[1] < 0 and not any(lo > 0 for lo in lower) else "NULL"

    result = {"rule": "C:/t/l2/rungj/rule_rj.md", "rule_sha256": RJ_RULE_SHA256,
              "population": {"n_dates": len(scored), "first_date": scored[0], "last_date": scored[-1],
                             "n_market_days": len(table.keys),
                             "common_covered_snapshots": {g: int((common & (table.local_hour >= lo)
                                                                  & (table.local_hour <= hi)).sum())
                                                          for g, lo, hi in groups}},
              "controls": {"mg1_excess_07_12": mg1_excess, "rh_reproduction": RJ_RH_EMIT,
                           "composite_post13_mg1_fallback_snapshots_13_16": int((in_rj & ~cov_n & cov_mg1).sum()),
                           "composite_post13_p3d_n_snapshots_13_16": int((in_rj & cov_n).sum()),
                           "gate1": audit["gates"]["1_parity"], "gate2_pass": audit["gates"]["2_loyo"].get("pass")},
              "coverage": {"P3d_N": r_n},
              "inputs": {"emit_files": audit["files"], "p3d_n_sha256": n_sha,
                         "emit_audit_sha256": hashlib.sha256((emit / "rg_emit_audit.json").read_bytes()).hexdigest(),
                         "layout_manifest_sha256": lay.manifest_sha256, "scorecard_code_sha256": sc.code_sha256(),
                         "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
              "gates": {}, "rows": []}

    def done():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
        return result

    result["rows"] += compare("B_G", "B_N")  # reported only
    result["rows"] += compare("P3d_N_fix", "composite_post13")  # reported only (incumbent sizing)
    rows = compare("P3d_G", "P3d_N_fix")
    result["rows"] += rows
    g3 = pick(rows, RJ_GATE[0])["dR_date_clustered"]
    result["gates"]["3_P3d_G_vs_P3d_N_fix_13_14"] = {"dR_date_clustered": g3, "pass": g3["ci95"][1] < 0}
    if not result["gates"]["3_P3d_G_vs_P3d_N_fix_13_14"]["pass"]:
        result["stopped_at"] = "gate 3 (KILL: trajectory family closed for the afternoon)"
        return done()
    rows = compare("P3d_G", "composite_post13")
    result["rows"] += rows
    result["gates"]["4_vs_composite_post13"] = {"reading": reading(rows),
                                                "dR_date_clustered": pick(rows, RJ_GATE[0])["dR_date_clustered"]}
    return done()


# ------------------------------------------------- P3d_N vs P3d_N_fix diagnostic (2026-10-25, descriptive, no rule)

DIAG_LABEL = ("DESCRIPTIVE DIAGNOSTIC - P3d_N (721ae2cd, last_in_hour, raw METAR F) vs P3d_N_fix (as-of-capture, "
              "WU whole F); dev rows <= 2026-09-29 only; selection evidence, no arm, no gate of its own")
DIAG_HOURS = (13, 14, 15, 16)
# variant -> (selection of high_so_far, rounding of high_so_far, selection of current_temp, rounding of current_temp)
DIAG_VARIANTS = {
    "fix": ("fix", True, "fix", True),
    "orig": ("orig", False, "orig", False),
    "swap_high": ("orig", False, "fix", True),   # column group high_so_far (F, x_high_so_far) from P3d_N
    "swap_current": ("fix", True, "orig", False),  # column group current_temp (x_current_temp) from P3d_N
    "mech_selection": ("orig", True, "orig", True),  # P3d_N's snapshot, WU whole F (selection effect only)
    "mech_rounding": ("fix", False, "fix", False),  # as-of-capture snapshot, raw F (rounding effect only)
}
DIAG_RH_FIX_SHA256 = "abc4350724fe42a5d2423dcf5dd3f1c1b06dcea4799cb0d297bd6de465096109"  # R-H P3d_N_fix 13-16
DIAG_A_N_SHA256 = "066ac73b41557711707451377eb34cf9aff81581bc8e7c171b14a9149cb6b3cb"  # MG-2 pick arm A (A_N)
DIAG_ARM_A_SHA256 = "14cc74207e8fff7e121bb811f3356a2b98b6064f94974d4e64f0c6ce0d7a24d1"  # MG-2 dev_composite arm A
DIAG_V3_SHA256 = "8f3e58953922863c55b126287f3d8109d238be0c168a0fc58073f2dd9752e942"  # MG-2 control_v3 vectors
DIAG_PICK = {"seed": 20261025, "p3d_n_minus_a_n": -0.1550986238704583, "a_n_minus_mg1": -0.3915437386366088,
             "n_rows": 13958}
DIAG_COMPOSITE_ARM_A_13_16 = -0.01037  # MG-2 dev_composite.json 13-16 Brier - MG-1 (arm A design)


def _diag_obs(snapshot, target, tz, hour, unit, local, running_max, l3):
    """Raw (unrounded) inputs plus the latest observation instant used and the snapshot's capture time."""
    rec = rung_inputs(snapshot, target, tz, hour, unit, local, running_max, l3.observations_at_cutoff, rounding=None)
    from datetime import datetime, time

    cutoff = datetime.combine(target, time(int(hour), 0), tzinfo=tz)
    metar = (((snapshot.get("sources") or {}).get("metar") or {}).get("data")) or {}
    latest = None
    for row in metar.get("rows") or []:
        if row.get("temp_native") is None:
            continue
        instant, _ = l3.metar_observation_instant(row, tz)
        if instant is not None and instant.date() == target and instant <= cutoff:
            latest = instant if latest is None or instant > latest else latest
    rec.update(captured_local=local.isoformat(), latest_obs_local=None if latest is None else latest.isoformat())
    return rec


def p3dn_diag_emit(*, records_root, layout, replay_root, nbm_train_corpus, out_dir, rh_fix_jsonl, p3d_n_jsonl,
                   markets=R0_MARKETS, hours=DIAG_HOURS):
    """Per-snapshot input diff (P3d_N's inputs vs P3d_N_fix's) and one P3d_N_fix-model emission per input variant."""
    import numpy as np
    import pandas as pd
    from zoneinfo import ZoneInfo

    from weather.calibration import ols_floor_ladder as l9
    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.calibration.r0_ols_floor_devfit import usable_v2_mean
    from weather.market.market_registry import spec_for_id
    from weather.model import observed_running_max

    for path, sha in ((rh_fix_jsonl, DIAG_RH_FIX_SHA256), (p3d_n_jsonl, RJ_P3D_N_SHA256)):
        got = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if got != sha:
            raise PooledModelError(f"{path} sha {got} != {sha}")
    running_max = _require_metar_only(observed_running_max.running_max_since_midnight)
    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {v: out / f"dev_{v}.jsonl" for v in DIAG_VARIANTS}
    for path in list(paths.values()) + [out / "diag_inputs.jsonl"]:
        if path.exists():
            raise PooledModelError(f"refusing to overwrite {path}")
    timezones = {m: spec_for_id(m).timezone for m in markets}
    frame, buckets = dev_training_frame(records_root, markets)
    if frame["year"].max() >= 2026:
        raise PooledModelError("a dev training row is from 2026")
    frame, _ = attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff, timezones)
    frame = frame[frame["hour"].isin(hours)].reset_index(drop=True)
    fits = rung_fits(frame, hours, arms={"P3d_N_fix": RUNG_ARMS["P3d_N_fix"]})
    coords = station_coordinates(markets)
    snaps = pd.read_parquet(Path(layout) / "inputs_snapshots.parquet", columns=[
        "snapshot_id", "market", "target_date", "local_hour", "cutoff_hour",
        "v2_mean", "v2_stddev", "v2_available_at", "captured_at_utc"])
    if (pd.to_datetime(snaps.target_date).dt.date > N_DEV_LAST).any():
        raise PooledModelError("layout holds a snapshot after 2026-09-29")
    snaps = snaps.assign(nbm_usable=usable_v2_mean(snaps))
    writers = {v: open(p, "w", encoding="utf-8") for v, p in paths.items()}
    diff_rows, stats = [], defaultdict(int)
    try:
        for market in markets:
            spec = spec_for_id(market)
            tz = ZoneInfo(spec.timezone)
            folders = {target: folder for slug, target, folder in l3._event_folders(replay_root)
                       if slug == market and N_DEV_FIRST <= target <= N_DEV_LAST}
            lat, lon, elev = coords[market]
            rows = snaps[snaps.market == market].copy()
            rows["target"] = pd.to_datetime(rows.target_date).dt.date
            for target, group in rows.groupby("target"):
                folder = folders.get(target)
                eligible = []
                for row in group.itertuples(index=False):
                    try:
                        hour = int(str(row.cutoff_hour))
                    except ValueError:
                        continue
                    if hour in hours and int(row.local_hour) >= hour and math.isfinite(float(row.nbm_usable)) \
                            and folder is not None:
                        eligible.append((row, hour))
                if not eligible:
                    continue
                with open(Path(folder) / "replay_inputs.jsonl", "rb") as handle:
                    index = replay_index(handle, target, tz)
                    # P3d_N (scan_replay_n): the last snapshot in FILE order captured in [h:00, h+1:00)
                    last_in_hour = {}
                    for e in sorted(index, key=lambda e: e[1]):
                        if e[0].hour in hours:
                            last_in_hour[e[0].hour] = e
                    parsed, cache = {}, {}

                    def inputs(entry, hour):
                        key = (entry[1], hour)
                        if key not in cache:
                            if entry[1] not in parsed:
                                handle.seek(entry[1])
                                parsed.clear()
                                try:
                                    parsed[entry[1]] = json.loads(handle.read(entry[2]))
                                except json.JSONDecodeError:
                                    parsed[entry[1]] = None
                            snap = parsed[entry[1]]
                            cache[key] = None if snap is None else _diag_obs(
                                snap, target, tz, hour, spec.display_unit, entry[0], running_max, l3)
                        return cache[key]

                    for row, hour in eligible:
                        captured = pd.Timestamp(row.captured_at_utc)
                        captured = (captured.tz_localize("UTC") if captured.tzinfo is None else captured)
                        cap = captured.to_pydatetime()
                        e_fix = latest_at_or_before(index, cap)
                        e_orig = last_in_hour.get(hour)
                        if e_fix is None or e_orig is None:
                            stats["missing_fix" if e_fix is None else "missing_orig"] += 1
                            continue
                        rec = {"fix": inputs(e_fix, hour), "orig": inputs(e_orig, hour)}
                        if rec["fix"] is None or rec["orig"] is None:
                            stats["corrupt_replay_line_" + ("fix" if rec["fix"] is None else "orig")] += 1
                            continue
                        if any(rec[s][k] is None for s in rec for k in ("high_so_far", "current_temp")):
                            stats["missing_metar_feature"] += 1
                            continue
                        doy = target.timetuple().tm_yday
                        base = {"market": market, "centre": nearest_centre(target.isoformat()), "season": "aug_sep",
                                "hour": hour, "target_date": target.isoformat(), "year": target.year,
                                "y": float("nan"), "fh": float(row.nbm_usable), "lat": lat, "lon": lon,
                                "elev": elev, "doy_sin": math.sin(2 * math.pi * doy / 365.25),
                                "doy_cos": math.cos(2 * math.pi * doy / 365.25),
                                "market_code": float(R0_MARKETS.index(market))}
                        frames = {}
                        for v, (sel_h, rnd_h, sel_c, rnd_c) in DIAG_VARIANTS.items():
                            h_ = rec[sel_h]["high_so_far"]
                            c_ = rec[sel_c]["current_temp"]
                            h_ = wu_whole_f(h_) if rnd_h else float(h_)
                            c_ = wu_whole_f(c_) if rnd_c else float(c_)
                            frames[v] = dict(base, F=float(h_), x_high_so_far=float(h_), x_current_temp=float(c_))
                            dist = _dist_from_fit(fits[("P3d_N_fix", hour)], pd.DataFrame([frames[v]]), buckets,
                                                  market)[0]
                            writers[v].write(json.dumps({
                                "market": market, "snapshot_id": row.snapshot_id, "target_date": target.isoformat(),
                                "distribution": {str(b): p for b, p in dist.items() if p > 0}}, sort_keys=True) + "\n")
                        differing = sorted(k for k in frames["fix"] if not (
                            frames["fix"][k] == frames["orig"][k]
                            or (isinstance(frames["fix"][k], float) and isinstance(frames["orig"][k], float)
                                and np.isnan(frames["fix"][k]) and np.isnan(frames["orig"][k]))))
                        diff_rows.append({
                            "market": market, "snapshot_id": row.snapshot_id, "target_date": target.isoformat(),
                            "hour": hour, "local_hour": int(row.local_hour), "captured_utc": captured.isoformat(),
                            "differing_columns": differing,
                            "orig_snapshot_local": rec["orig"]["captured_local"],
                            "fix_snapshot_local": rec["fix"]["captured_local"],
                            "orig_snapshot_after_capture": bool(e_orig[0] > cap),
                            "orig_latest_obs_local": rec["orig"]["latest_obs_local"],
                            "fix_latest_obs_local": rec["fix"]["latest_obs_local"],
                            "orig_obs_after_capture": bool(rec["orig"]["latest_obs_local"] is not None and
                                                           datetime_fromiso(rec["orig"]["latest_obs_local"]) > cap),
                            "orig_n_rows": rec["orig"]["n_rows"], "fix_n_rows": rec["fix"]["n_rows"],
                            **{f"{v}_{k}": frames[v][k] for v in ("orig", "fix")
                               for k in ("F", "x_current_temp")},
                            "fix_raw_high": float(rec["fix"]["high_so_far"]),
                            "fix_raw_current": float(rec["fix"]["current_temp"])})
                        stats["emitted"] += 1
            print(f"diag {market}: {dict(stats)}", flush=True)
    finally:
        for w in writers.values():
            w.close()
    _write_jsonl(out / "diag_inputs.jsonl", diff_rows)

    def load(path):
        d = {}
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    r = json.loads(line)
                    d[(r["market"], r["snapshot_id"])] = r["distribution"]
        return d

    def max_dp(a, b):
        keys = set(a) & set(b)
        worst = 0.0
        for k in keys:
            da, db = a[k], b[k]
            for bucket in set(da) | set(db):
                worst = max(worst, abs(da.get(bucket, 0.0) - db.get(bucket, 0.0)))
        return {"common": len(keys), "only_diag": len(set(a) - set(b)), "only_reference": len(set(b) - set(a)),
                "max_abs_dp": worst}

    ref_n = {k: v for k, v in load(p3d_n_jsonl).items()}
    diag = {v: load(p) for v, p in paths.items()}
    ref_n = {k: ref_n[k] for k in ref_n if k in diag["orig"] or k in diag["fix"]}
    audit = {"label": DIAG_LABEL, "hours": list(hours), "stats": dict(stats), "variants": DIAG_VARIANTS,
             "controls": {"fix_vs_rh_P3d_N_fix": max_dp(diag["fix"], load(rh_fix_jsonl)),
                          "orig_vs_721ae2cd": max_dp(diag["orig"], ref_n)},
             "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in list(paths.values()) + [out / "diag_inputs.jsonl"]},
             "inputs": {"rh_fix_sha256": DIAG_RH_FIX_SHA256, "p3d_n_sha256": RJ_P3D_N_SHA256,
                        "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
             "input_diff": p3dn_input_summary(diff_rows)}
    (out / "diag_emit_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True), encoding="utf-8")
    return audit


def datetime_fromiso(text):
    from datetime import datetime

    return datetime.fromisoformat(text)


def p3dn_input_summary(rows):
    """Per hour: rows, rows with each column differing, magnitudes, and the look-ahead flags."""
    import numpy as np

    out = {}
    for label, hs in (("13-14", (13, 14)), ("13", (13,)), ("14", (14,)), ("15-16", (15, 16)), ("15", (15,)),
                      ("16", (16,))):
        rs = [r for r in rows if r["hour"] in hs]
        if not rs:
            continue
        cols = sorted({c for r in rs for c in r["differing_columns"]})
        entry = {"rows": len(rs), "rows_any_differing": sum(1 for r in rs if r["differing_columns"]),
                 "orig_snapshot_after_capture": sum(r["orig_snapshot_after_capture"] for r in rs),
                 "orig_observation_after_capture": sum(r["orig_obs_after_capture"] for r in rs),
                 "same_snapshot": sum(r["orig_snapshot_local"] == r["fix_snapshot_local"] for r in rs),
                 "orig_more_rows": sum(r["orig_n_rows"] > r["fix_n_rows"] for r in rs),
                 "orig_newer_latest_obs": sum((r["orig_latest_obs_local"] or "") > (r["fix_latest_obs_local"] or "")
                                              for r in rs),
                 "columns": {}}
        lead = [(datetime_fromiso(r["orig_snapshot_local"]) - datetime_fromiso(r["captured_utc"])).total_seconds()
                / 60 for r in rs if r["orig_snapshot_after_capture"]]
        entry["orig_snapshot_minutes_after_capture"] = (
            {"median": float(np.median(lead)), "p90": float(np.quantile(lead, .9)), "max": float(max(lead))}
            if lead else None)
        for col, key in (("F", "F"), ("x_high_so_far", "F"), ("x_current_temp", "x_current_temp")):
            d = np.array([r[f"orig_{key}"] - r[f"fix_{key}"] for r in rs])
            nz = d[d != 0]
            sel = np.array([r[f"orig_{key}"] - (r["fix_raw_high"] if key == "F" else r["fix_raw_current"])
                            for r in rs])
            entry["columns"][col] = {
                "rows_differing": int((d != 0).sum()),
                "rows_differing_by_snapshot_selection": int((sel != 0).sum()),
                "mean_orig_minus_fix": float(d.mean()), "mean_abs_where_differing": float(np.abs(nz).mean())
                if len(nz) else 0.0, "median_abs_where_differing": float(np.median(np.abs(nz))) if len(nz) else 0.0,
                "p90_abs_where_differing": float(np.quantile(np.abs(nz), .9)) if len(nz) else 0.0,
                "max_abs": float(np.abs(d).max()),
                "share_orig_above_fix": float((d > 0).mean()), "share_orig_below_fix": float((d < 0).mean())}
        entry["other_columns_differing"] = [c for c in cols if c not in ("F", "x_high_so_far", "x_current_temp")]
        out[label] = entry
    return out


def _share_interval(w, a, b):
    """sum(w a) / sum(w b) per draw over all draws (denominator sign kept), percentile 95%."""
    import numpy as np

    num, den = w @ a, w @ b
    with np.errstate(divide="ignore", invalid="ignore"):
        boot = num / den
    fin = boot[np.isfinite(boot)]
    return {"estimate": float(a.sum() / b.sum()) if b.sum() != 0 else None,
            "ci95": np.quantile(fin, [.025, .975]).tolist() if len(fin) else [None, None],
            "draws_denominator_le_0": int((den <= 0).sum())}


def p3dn_diag_score(*, layout, diag_dir, p3d_n_jsonl, v3_vectors, a_n_jsonl, arm_a_jsonl, coefficients, nowcasts,
                    out_path, start="2026-08-01", end="2026-09-29"):
    """Attribution of P3d_N_fix - P3d_N, the composite re-score with the fix, and the pick re-score vs A_N."""
    import os

    import numpy as np
    import pandas as pd

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas

    out_path = require_output_outside_repo(out_path)
    if out_path.exists():
        raise PooledModelError(f"refusing to overwrite {out_path}")
    diag = Path(diag_dir)
    audit = json.loads((diag / "diag_emit_audit.json").read_bytes())
    shas = {}
    for name, path, sha in (("p3d_n", p3d_n_jsonl, RJ_P3D_N_SHA256), ("v3_vectors", v3_vectors, DIAG_V3_SHA256),
                            ("a_n", a_n_jsonl, DIAG_A_N_SHA256), ("arm_a", arm_a_jsonl, DIAG_ARM_A_SHA256)):
        shas[name] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if shas[name] != sha:
            raise PooledModelError(f"{name} sha {shas[name]} != {sha}")
    for v in DIAG_VARIANTS:
        got = hashlib.sha256((diag / f"dev_{v}.jsonl").read_bytes()).hexdigest()
        if got != audit["files"][f"dev_{v}.jsonl"]:
            raise PooledModelError(f"dev_{v}.jsonl changed since the emit")
    os.environ["L6_NOWCASTS"] = str(nowcasts)
    if hashlib.sha256(Path(nowcasts).read_bytes()).hexdigest() != L6_NOWCAST_SHA256:
        raise PooledModelError("L6 nowcasts sha mismatch")
    start_d, end_d = data.check_range(start, end)
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    table = sc.Table(lay, scored)
    w_rj = l3._date_weights([k[0] for k in table.keys], sc.DRAWS, sc.SEED)
    w_pick = l3._date_weights([k[0] for k in table.keys], sc.DRAWS, DIAG_PICK["seed"])
    market_b = table.brier(table.p_market)

    def vec(path):
        return l3._vector(table, l3._candidate_frame(str(path), table, lay, folds, data)[0])

    var = {v: vec(diag / f"dev_{v}.jsonl") for v in DIAG_VARIANTS}
    p_n, cov_n, r_n = vec(p3d_n_jsonl)
    p_mg1, cov_mg1, _ = l3._vector(table, loss_atlas.mg1_frame(table))
    from weather.reporting.scorecards.free_source_candidates import l6_stack

    l6_stack._CACHE.clear()
    state, _ = l6_frozen_state(coefficients)
    p_l6, cov_l6, _ = l6_vector(table, state, l3)
    w0712 = (table.local_hour >= 7) & (table.local_hour <= 12)
    _, e = table.cells(table.brier(p_mg1) - market_b, w0712)
    mg1_excess = float(e.mean())
    if round(mg1_excess, 3) != l3.MG1_CONTROL_0712_EXCESS:
        raise PooledModelError(f"MG-1 positive control failed: {mg1_excess:.5f}")
    hour = table.local_hour
    groups = [("13-14", 13, 14), ("h13", 13, 13), ("h14", 14, 14), ("15-16", 15, 16), ("h15", 15, 15),
              ("h16", 16, 16), ("13-16", 13, 16)]
    result = {"label": DIAG_LABEL, "population": {"n_dates": len(scored), "first": scored[0], "last": scored[-1],
                                                  "n_market_days": len(table.keys)},
              "controls": {"mg1_excess_07_12": mg1_excess, "emit": audit["controls"]},
              "inputs": {**shas, "diag_files": audit["files"], "layout_manifest_sha256": lay.manifest_sha256,
                         "scorecard_code_sha256": sc.code_sha256(),
                         "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}

    # ---- 2. attribution of P3d_N_fix - P3d_N (dR, R-J's date weights) on identical covered snapshots
    common = cov_n.copy()
    for _, cov, _ in var.values():
        common &= cov
    briers = {v: table.brier(p) for v, (p, _, _) in var.items()}
    briers["P3d_N_721ae2cd"] = table.brier(p_n)
    orig_equal = float(np.abs(var["orig"][0] - p_n)[common[table.band_snap]].max())
    result["controls"]["orig_variant_equals_721ae2cd_max_abs_on_common"] = orig_equal
    attribution = {}
    for g, lo, hi in groups:
        mask = common & (hour >= lo) & (hour <= hi)
        idx, c_fix = table.cells(briers["fix"], mask)
        _, c_orig = table.cells(briers["orig"], mask)
        _, c_n = table.cells(briers["P3d_N_721ae2cd"], mask)
        _, m = table.cells(market_b, mask)
        gap = c_fix - c_orig
        entry = {"n_snapshots": int(mask.sum()), "n_market_days": int(len(idx)),
                 "dR_fix_minus_721ae2cd": sc.ratio_interval(w_rj[:, idx], c_fix - c_n, m),
                 "dR_fix_minus_orig": sc.ratio_interval(w_rj[:, idx], gap, m),
                 "dR_fix_minus_orig_crossed": sc.ratio_interval(table.w[:, idx], gap, m), "variants": {}}
        for v in DIAG_VARIANTS:
            if v in ("fix", "orig"):
                continue
            _, c_v = table.cells(briers[v], mask)
            entry["variants"][v] = {"dR_fix_minus_variant": sc.ratio_interval(w_rj[:, idx], c_fix - c_v, m),
                                    "share_of_gap": _share_interval(w_rj[:, idx], c_fix - c_v, gap)}
        _, c_h = table.cells(briers["swap_high"], mask)
        _, c_c = table.cells(briers["swap_current"], mask)
        entry["interaction_share"] = _share_interval(w_rj[:, idx], gap - (c_fix - c_h) - (c_fix - c_c), gap)
        attribution[g] = entry
    result["attribution"] = attribution

    # ---- 3. the composite (pre-13 L6 stack, post-13 P3d_N, MG-1 elsewhere) vs MG-1, with and without the fix
    band_hour = hour[table.band_snap]
    p_v3, cov_v3, _ = l3._vector(table, pd.read_parquet(v3_vectors))
    pre = np.where(cov_l6[table.band_snap], p_l6, p_mg1)
    comp_orig = np.where(band_hour < 13, pre, np.where(cov_n[table.band_snap], p_n, p_mg1))
    in16 = band_hour <= 16
    result["controls"]["rebuilt_composite_equals_mg2_control_v3_max_abs_00_16"] = float(
        np.abs(comp_orig - p_v3)[in16].max())
    result["controls"]["mg2_control_v3_covers_all"] = bool(cov_v3.all())
    p_fix, cov_fix = var["fix"][0], var["fix"][1]
    post = (band_hour >= 13) & (band_hour <= 16)
    comp_fix = np.where(post, np.where(cov_fix[table.band_snap], p_fix, p_mg1), p_v3)
    p_arm_a, cov_arm_a, _ = vec(arm_a_jsonl)
    comp_arm_a = np.where(band_hour < 13, pre, np.where(cov_arm_a[table.band_snap], p_arm_a, p_mg1))
    snap_post = (hour >= 13) & (hour <= 16)
    result["composite_post_sources_13_16"] = {
        "orig_p3d_n": int((snap_post & cov_n).sum()), "orig_mg1": int((snap_post & ~cov_n).sum()),
        "fix_p3d_n_fix": int((snap_post & cov_fix).sum()), "fix_mg1": int((snap_post & ~cov_fix).sum()),
        "p3d_n_covered_fix_not": int((snap_post & cov_n & ~cov_fix).sum()),
        "fix_covered_p3d_n_not": int((snap_post & cov_fix & ~cov_n).sum())}
    blocks = [("00-16", 0, 16), ("00-12", 0, 12), ("07-12", 7, 12), ("13-16", 13, 16), ("13-14", 13, 14),
              ("15-16", 15, 16), ("h13", 13, 13), ("h14", 14, 14), ("h15", 15, 15), ("h16", 16, 16)]
    b_mg1 = table.brier(p_mg1)

    def vs_mg1(p):
        b = table.brier(p)
        rows = {}
        for name, lo, hi in blocks:
            mask = (hour >= lo) & (hour <= hi)
            idx, c = table.cells(b, mask)
            _, k = table.cells(b_mg1, mask)
            _, m = table.cells(market_b, mask)
            ones = np.ones(len(idx))
            rows[name] = {"n_cells": int(len(idx)),
                          "brier_minus_mg1_date_clustered": sc.ratio_interval(table.w_date[:, idx], c - k, ones),
                          "brier_minus_mg1_crossed": sc.ratio_interval(table.w[:, idx], c - k, ones),
                          "dR_vs_mg1_date_clustered": sc.ratio_interval(table.w_date[:, idx], c - k, m)}
        g1 = rows["00-16"]["brier_minus_mg1_date_clustered"]["ci95"][1]
        g2 = rows["13-16"]["brier_minus_mg1_date_clustered"]["ci95"][1]
        rows["gate_reading_dev_only"] = {"G1_00_16_upper_lt_0.0010": bool(g1 < 0.0010), "G2_13_16_upper_lt_0": bool(
            g2 < 0), "dev_stop_13_16_upper_ge_0": bool(g2 >= 0)}
        return rows

    result["composite"] = {"mg2_control_v3_as_emitted": vs_mg1(p_v3), "orig_rebuilt": vs_mg1(comp_orig),
                           "fix": vs_mg1(comp_fix), "arm_a_control": vs_mg1(comp_arm_a)}
    result["controls"]["arm_a_composite_13_16"] = {
        "got": result["composite"]["arm_a_control"]["13-16"]["brier_minus_mg1_date_clustered"]["estimate"],
        "expected": DIAG_COMPOSITE_ARM_A_13_16}
    b_cf, b_co = table.brier(comp_fix), table.brier(p_v3)
    diff = {}
    for name, lo, hi in blocks:
        mask = (hour >= lo) & (hour <= hi)
        idx, cf = table.cells(b_cf, mask)
        _, co = table.cells(b_co, mask)
        diff[name] = sc.ratio_interval(table.w_date[:, idx], cf - co, np.ones(len(idx)))
    result["composite"]["fix_minus_orig_brier"] = diff

    # ---- 4. the MG-2 afternoon pick re-scored: P3d_N_fix vs A_N on the pick rows (r0_ols_floor_challenger.dev_pick)
    p_an, cov_an, r_an = vec(a_n_jsonl)
    in_hours = np.isin(hour, DIAG_HOURS)
    rows_pick = in_hours & cov_an & cov_n
    rows_fix = rows_pick & cov_fix
    primary = np.isin(table.markets, sorted(l3.PRIMARY_MARKETS))
    b_an = table.brier(p_an)

    def both(a, b, mask):
        idx, c = table.cells(a, mask)
        _, r_ = table.cells(b, mask)
        _, m = table.cells(market_b, mask)
        return {"crossed": sc.ratio_interval(table.w[:, idx], c - r_, m),
                "date_clustered": sc.ratio_interval(w_pick[:, idx], c - r_, m)}

    def challenger(b, rows):
        pooled = both(b, b_an, rows)
        hrs = {f"h{h:02d}": both(b, b_an, rows & (hour == h)) for h in DIAG_HOURS}
        prim = both(b, b_an, rows & primary)
        return {"dR_vs_a_n": pooled, "by_hour": hrs, "primary5": prim, "dR_vs_mg1": both(b, b_mg1, rows),
                "conditions": {
                    "2_upper_below_0_both": all(pooled[k]["ci95"][1] < 0 for k in pooled),
                    "3_no_ci_worse_hour": not any(v["date_clustered"]["ci95"][0] > 0 for v in hrs.values()),
                    "4_primary5_point_below_0": prim["date_clustered"]["estimate"] < 0,
                    "tie_rule_interval_excludes_0": pooled["date_clustered"]["ci95"][1] < 0}}

    pick = {"rows": {"pick_rows": int(rows_pick.sum()), "pick_rows_fix_covered": int(rows_fix.sum()),
                     "expected_pick_rows": DIAG_PICK["n_rows"]},
            "a_n_coverage": r_an,
            "control_a_n_minus_mg1": both(b_an, b_mg1, rows_pick),
            "control_p3d_n": challenger(table.brier(p_n), rows_pick),
            "p3d_n_on_fix_rows": challenger(table.brier(p_n), rows_fix),
            "p3d_n_fix": challenger(briers["fix"], rows_fix),
            "p3d_n_fix_minus_p3d_n": both(briers["fix"], table.brier(p_n), rows_fix),
            "a_n_minus_mg1_on_fix_rows": both(b_an, b_mg1, rows_fix)}
    pick["controls"] = {
        "p3d_n_minus_a_n": {"got": pick["control_p3d_n"]["dR_vs_a_n"]["date_clustered"]["estimate"],
                            "expected": DIAG_PICK["p3d_n_minus_a_n"]},
        "a_n_minus_mg1": {"got": pick["control_a_n_minus_mg1"]["date_clustered"]["estimate"],
                          "expected": DIAG_PICK["a_n_minus_mg1"]}}
    result["pick"] = pick
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=1, sort_keys=True, default=float), encoding="utf-8")
    return result


# ------------------------------------------------- R-K: HRRR 13-16 hourly path as a centre input (rule_rk.md)

RK_RULE_SHA256 = "21b5dfe1870c03bcab143903b8fccc37a446c49de97b3889377039c7c8327221"
RK_CLARIFICATION_RK1_SHA256 = "c825b2771ca8f8d4e02fbc736f820f0b581d4be8c7a69b0c71a729f9101432c7"
RK_HOURS = (13, 14, 15, 16)
RK_POOLS = (("13-16", None), ("13-14", (13, 14)), ("15-16", (15, 16)))
RK_FEATURES = ("k_max", "k_gap", "k_tcdc", "k_miss")
RK_ARMS = {
    "B_N": True,
    "B_H": {"simple": True, "extra_ols": ("k_gap", "k_tcdc", "k_miss")},
    "P3d_N_fix": False,
    "P3d_H": {"simple": False, "extra_hgb": ("k_max", "k_gap", "k_tcdc")},
}
RK_PAIRS = (("B_H", "B_N"), ("P3d_H", "P3d_N_fix"), ("P3d_H", "B_H"), ("P3d_N_fix", "B_N"))
RK_VARIABLES = {"TMP": "TMP:2 m above ground", "TCDC": "TCDC:entire atmosphere"}
RK_VALID_END_LOCAL = 17
RK_MARGIN_S = 10 * 60
RK_TMP_RANGE_F = (-60.0, 130.0)
RK_COVERAGE_MIN = 0.95
RK_CONTROL_TOL = 1e-12


def rk_message_key(cycle, fh):
    """The AWS object key of one HRRR surface file (L13 manifest ``key``)."""
    return f"hrrr.{cycle:%Y%m%d}/conus/hrrr.t{cycle:%H}z.wrfsfcf{int(fh):02d}.grib2"


def rk_kelvin_to_f(kelvin):
    return (float(kelvin) - 273.15) * 9.0 / 5.0 + 32.0


def _rk_lines(path, stats, name):
    """JSON lines; a torn or corrupt line (a corpus still being appended) is counted and skipped."""
    with open(path, "rb") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                stats[f"{name}_corrupt_line"] += 1


def rk_hrrr_columns(corpus_dir, markets=R0_MARKETS):
    """L13's HRRR point corpus -> {(market, local_date, hour): raw R-K path} plus integrity counts.

    Inputs only: no outcome, label, price or layout row is read. Per selection (rule_rk.md, feature family):
    ``k_max`` = max TMP (nearest point, K -> F) over the selection's fhs, ``k_tcdc`` = mean TCDC (%) over the
    same fhs, ``k_miss`` = 1 when there is no cycle, a needed message is absent or fails its identity check, or
    a value is not finite. ``k_gap`` needs the row's own NBM anchor and is added by :func:`rk_columns`.
    """
    from datetime import datetime, timedelta, time
    from zoneinfo import ZoneInfo

    corpus = Path(corpus_dir)
    stats = defaultdict(int)
    stations = json.loads((corpus / "stations.json").read_bytes())
    icao_market = {icao: s["market"] for icao, s in stations.items() if s.get("market") in markets}
    missing = sorted(set(markets) - set(icao_market.values()))
    if missing:
        raise PooledModelError(f"HRRR corpus has no station for {missing}")
    tzs = {icao: ZoneInfo(stations[icao]["tz"]) for icao in icao_market}
    messages, mismatched = {}, set()
    for m in _rk_lines(corpus / "manifest.jsonl", stats, "manifest"):
        record = str(m.get("idx_record") or "")
        var = next((v for v, prefix in RK_VARIABLES.items() if record.startswith(prefix + ":")), None)
        if var is None:
            stats["manifest_other_variable"] += 1
            continue
        cycle, fh = datetime.fromisoformat(m["cycle_utc"]), int(m["fh"])
        key = (cycle, fh, var)
        if m.get("key") != rk_message_key(cycle, fh) or record != f"{RK_VARIABLES[var]}:{fh} hour fcst:":
            stats["manifest_identity_mismatch"] += 1
            mismatched.add(key)
            continue
        values = {icao: (point or {}).get("nearest") for icao, point in (m.get("points") or {}).items()
                  if icao in icao_market}
        if key in messages:
            stats["manifest_duplicate"] += 1
            if messages[key] != values:
                stats["manifest_duplicate_conflict"] += 1
                mismatched.add(key)
            continue
        messages[key] = values
        stats[f"manifest_{var}"] += 1
    out = {}
    for s in _rk_lines(corpus / "selections.jsonl", stats, "selections"):
        icao = s.get("station")
        if icao not in icao_market:
            continue
        market, day, hour = icao_market[icao], str(s["local_date"]), int(s["hour_local"])
        if hour not in RK_HOURS:
            continue
        key = (market, day, hour)
        stats["selections"] += 1
        if key in out:
            stats["selection_duplicate"] += 1
            continue
        tz = tzs[icao]
        target = date.fromisoformat(day)
        snapshot = datetime.combine(target, time(hour, 0), tzinfo=tz)
        window_end = datetime.combine(target, time(RK_VALID_END_LOCAL, 0), tzinfo=tz)
        entry = {"cycle_utc": s.get("cycle_utc"), "fhs": list(s.get("fhs") or []), "k_max": float("nan"),
                 "k_tcdc": float("nan"), "k_miss": 1.0, "reason": None}
        out[key] = entry
        if datetime.fromisoformat(s["snapshot_utc"]) != snapshot:
            stats["selection_snapshot_mismatch"] += 1
            entry["reason"] = "snapshot_mismatch"
            continue
        if s.get("cycle_utc") is None or not entry["fhs"]:
            stats["selection_no_cycle"] += 1
            entry["reason"] = "no_cycle"
            continue
        cycle = datetime.fromisoformat(s["cycle_utc"])
        latest = s.get("latest_available_utc")
        if latest is None or datetime.fromisoformat(latest) + timedelta(seconds=RK_MARGIN_S) > snapshot:
            stats["selection_pit_violation"] += 1
            entry["reason"] = "pit_violation"
            continue
        valid = [cycle + timedelta(hours=int(fh)) for fh in entry["fhs"]]
        if min(valid) < snapshot or max(valid) > window_end:
            stats["selection_window_violation"] += 1
            entry["reason"] = "window_violation"
            continue
        tmp, tcdc = [], []
        for fh in entry["fhs"]:
            for var, sink in (("TMP", tmp), ("TCDC", tcdc)):
                k = (cycle, int(fh), var)
                if k in mismatched:
                    entry["reason"] = "identity_mismatch"
                v = messages.get(k, {}).get(icao)
                sink.append(float("nan") if v is None else float(v))
        if entry["reason"] == "identity_mismatch":
            stats["selection_identity_mismatch_used"] += 1
            continue
        if not all(math.isfinite(v) for v in tmp + tcdc):
            stats["selection_message_absent"] += 1
            entry["reason"] = "message_absent"
            continue
        tmp_f = [rk_kelvin_to_f(v) for v in tmp]
        if min(tmp_f) < RK_TMP_RANGE_F[0] or max(tmp_f) > RK_TMP_RANGE_F[1]:
            stats["selection_tmp_out_of_range"] += 1
            entry["reason"] = "tmp_out_of_range"
            continue
        entry.update(k_max=max(tmp_f), k_tcdc=sum(tcdc) / len(tcdc), k_miss=0.0)
        stats["selection_covered"] += 1
    return out, dict(stats)


def rk_columns(entry, nbm):
    """Model columns for one row: the raw path plus ``k_gap`` against the row's own NBM anchor."""
    if entry is None or entry["k_miss"]:
        return {"k_max": float("nan"), "k_gap": float("nan"), "k_tcdc": float("nan"), "k_miss": 1.0}
    gap = entry["k_max"] - float(nbm) if nbm is not None and math.isfinite(float(nbm)) else float("nan")
    return {"k_max": entry["k_max"], "k_gap": gap, "k_tcdc": entry["k_tcdc"], "k_miss": 0.0}


def rk_training_columns(frame, hrrr):
    """Attach R-K columns to training rows keyed (market, target_date, cutoff hour); ``fh`` is the NBM anchor."""
    cols, stats = defaultdict(list), defaultdict(int)
    for market, day, hour, fh in zip(frame["market"], frame["target_date"], frame["hour"], frame["fh"]):
        entry = hrrr.get((market, str(day)[:10], int(hour)))
        stats["rows"] += 1
        stats["rows_no_selection"] += entry is None
        values = rk_columns(entry, fh)
        stats["rows_covered"] += values["k_miss"] == 0.0
        for k, v in values.items():
            cols[k].append(v)
    out = frame.copy()
    for k in RK_FEATURES:
        out[k] = cols[k]
    return out, dict(stats)


def rk_parity_training(corpus_stats, train_stats):
    """Gate 1, training half (rule_rk.md gate 1 and clarification RK-1): inputs only."""
    coverage = train_stats.get("rows_covered", 0) / max(train_stats.get("rows", 0), 1)
    checks = {"training_coverage": coverage >= RK_COVERAGE_MIN,
              "identity_mismatch_used": corpus_stats.get("selection_identity_mismatch_used", 0) == 0,
              "tmp_out_of_range": corpus_stats.get("selection_tmp_out_of_range", 0) == 0,
              "pit_violation": corpus_stats.get("selection_pit_violation", 0) == 0,
              "window_violation": corpus_stats.get("selection_window_violation", 0) == 0,
              "snapshot_mismatch": corpus_stats.get("selection_snapshot_mismatch", 0) == 0}
    return {"training_coverage": coverage, "threshold": RK_COVERAGE_MIN, "checks": checks,
            "pass": all(checks.values())}


def rk_control(rows, reference_rows, arms=("B_N", "P3d_N_fix"), tol=RK_CONTROL_TOL):
    """R-J's LOYO rows reproduce: same (hour, year, market, date) keys, same incumbent-arm scores."""
    ref = {(r["hour"], r["year"], r["market"], r["date"]): r for r in reference_rows if r["hour"] in RK_HOURS}
    got = {(r["hour"], r["year"], r["market"], r["date"]): r for r in rows}
    worst = 0.0
    for k in set(ref) & set(got):
        for arm in arms:
            for metric in ("brier", "log"):
                worst = max(worst, abs(got[k][f"{arm}_{metric}"] - ref[k][f"{arm}_{metric}"]))
    same_keys = set(ref) == set(got)
    return {"same_keys": same_keys, "n_rows": len(got), "n_reference": len(ref), "max_abs_diff": worst,
            "pass": same_keys and worst <= tol}


def rung_k_loyo(*, records_root, nbm_train_corpus, hrrr_corpus, rj_loyo_rows, out_dir, markets=R0_MARKETS):
    """R-K gate 1 (training half) and gate 2 (LOYO 2021-25, B_H - B_N at 13-16). No dev row is read."""
    from weather.calibration import ols_floor_ladder as l9
    from weather.market.market_registry import spec_for_id

    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise PooledModelError(f"refusing to write into a non-empty {out}")
    corpus = Path(hrrr_corpus)
    audit = {"rule_sha256": RK_RULE_SHA256, "clarification_rk1_sha256": RK_CLARIFICATION_RK1_SHA256,
             "arms": list(RK_ARMS), "hours": list(RK_HOURS), "gates": {},
             "inputs": {"nbm_train_corpus": hashlib.sha256(Path(nbm_train_corpus).read_bytes()).hexdigest(),
                        "rj_loyo_rows": hashlib.sha256(Path(rj_loyo_rows).read_bytes()).hexdigest(),
                        "hrrr_corpus": str(corpus),
                        **{f"hrrr_{n}": hashlib.sha256((corpus / n).read_bytes()).hexdigest()
                           for n in ("manifest.jsonl", "selections.jsonl", "stations.json")},
                        "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}

    def finish():
        (out / "rk_loyo_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True), encoding="utf-8")
        return audit

    timezones = {m: spec_for_id(m).timezone for m in markets}
    hrrr, audit["hrrr_corpus_stats"] = rk_hrrr_columns(corpus, markets)
    frame, buckets = dev_training_frame(records_root, markets)
    if frame["year"].max() >= 2026:
        raise PooledModelError("a training row is from 2026")
    frame, audit["train_nbm"] = attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff, timezones)
    frame = frame[frame["hour"].isin(RK_HOURS)].reset_index(drop=True)
    frame, audit["training"] = rk_training_columns(frame, hrrr)
    audit["gates"]["1_parity_training"] = rk_parity_training(audit["hrrr_corpus_stats"], audit["training"])
    if not audit["gates"]["1_parity_training"]["pass"]:
        audit["stopped_at"] = "gate 1 parity (training half; not a kill)"
        return finish()
    rows = rung_loyo(frame, buckets, RK_HOURS, arms=RK_ARMS)
    _write_jsonl(out / "loyo_rows.jsonl", rows)
    audit["control_rj_reproduction"] = rk_control(rows, _read_jsonl(rj_loyo_rows))
    if not audit["control_rj_reproduction"]["pass"]:
        audit["stopped_at"] = "control: R-J LOYO reproduction failed (refused, not a gate)"
        return finish()
    audit["gates"]["2_loyo"] = rg_loyo_summary(rows, pairs=RK_PAIRS, pooled=RK_POOLS)
    primary = audit["gates"]["2_loyo"]["B_H-B_N|13-16|brier"]
    audit["gates"]["2_loyo"]["pass"] = primary["ci95"][1] < 0
    if not audit["gates"]["2_loyo"]["pass"]:
        audit["stopped_at"] = "gate 2 LOYO (KILL: HRRR closed as a 13-16 centre input)"
    return finish()


def rk_hrrr_audit(*, hrrr_corpus, out_path, markets=R0_MARKETS):
    """Schema and coverage audit of an HRRR corpus (inputs only; no outcome or layout row is read)."""
    out_path = require_output_outside_repo(out_path)
    if out_path.exists():
        raise PooledModelError(f"refusing to overwrite {out_path}")
    hrrr, stats = rk_hrrr_columns(hrrr_corpus, markets)
    per_hour = defaultdict(lambda: [0, 0])
    reasons = defaultdict(int)
    for (_, _, hour), entry in hrrr.items():
        per_hour[hour][0] += 1
        per_hour[hour][1] += entry["k_miss"] == 0.0
        reasons[entry["reason"] or "covered"] += 1
    result = {"rule_sha256": RK_RULE_SHA256, "stats": stats, "reasons": dict(reasons),
              "per_hour": {f"h{h:02d}": {"selections": n, "covered": c, "coverage": c / max(n, 1)}
                           for h, (n, c) in sorted(per_hour.items())},
              "years": sorted({k[1][:4] for k in hrrr})}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


# ------------------------------------------------- clarification 3: forward refit and frozen state (MG-2)

FORWARD_CENTRES = AUG_SEP_CENTRES + ("2026-10-10", "2026-10-25", "2026-11-09", "2026-11-24", "2026-12-09")
FORWARD_YEARS = (2021, 2022, 2023, 2024, 2025)
STATE_SCHEMA = "mg2_p3d_n_state/1"
WU_ROUNDING_CANDIDATES = ("half_up", "half_even", "half_down", "floor", "ceil")


def exact_tgroup_f(value_f):
    """The exact Fahrenheit value of a T-group reading given as a float in degrees F.

    The T-group carries tenths of a degree C; 32 + 9 * tenths / 50 is recovered without float error.
    """
    from fractions import Fraction

    tenths = round((float(value_f) - 32.0) * 50.0 / 9.0)
    return Fraction(32) + Fraction(9 * tenths, 50)


def round_candidate(exact, rule):
    """Whole degrees from an exact Fraction under one rounding rule."""
    import math as _m

    lo = _m.floor(exact)
    frac = exact - lo
    if rule == "floor":
        return int(lo)
    if rule == "ceil":
        return int(_m.ceil(exact))
    if frac * 2 != 1:
        return int(lo + (1 if frac * 2 > 1 else 0))
    if rule == "half_up":
        return int(lo + 1)
    if rule == "half_down":
        return int(lo)
    if rule == "half_even":
        return int(lo if lo % 2 == 0 else lo + 1)
    raise PooledModelError(f"unknown rounding rule {rule}")


def wu_whole_f(value_f, rule="half_up"):
    """Serve-time conversion of a METAR T-group Fahrenheit value to WU's whole-degree representation."""
    if value_f is None:
        return None
    try:
        if not math.isfinite(float(value_f)):
            return None
    except (TypeError, ValueError):
        return None
    return float(round_candidate(exact_tgroup_f(value_f), rule))


def wu_rounding_parity(*, obs_parquet, wu_root, markets=R0_MARKETS, years=FORWARD_YEARS, months=(8, 9, 10, 11, 12)):
    """Historical WU whole-degree F vs the same reports' T-group F (IEM), per candidate rounding rule."""
    import pandas as pd

    from weather.market.market_registry import spec_for_id

    obs = pd.read_parquet(obs_parquet, columns=["station", "role", "market", "valid_utc", "tmpf", "tgroup_f", "is_cor"])
    obs = obs[(obs.role == "market") & obs.market.isin(markets)]
    obs = obs[obs.valid_utc.dt.year.isin(years) & obs.valid_utc.dt.month.isin(months)]
    if (obs.valid_utc.dt.year >= 2026).any():
        raise PooledModelError("a 2026 row reached the rounding check")
    out = {"markets": {}, "years": list(years), "months": list(months)}
    totals = defaultdict(lambda: defaultdict(int))
    for market in markets:
        icao = spec_for_id(market).icao.lower()
        wu = []
        for year in years:
            for month in months:
                path = Path(wu_root) / icao / "hourly" / f"year={year}" / f"month={month:02d}" / "observations.jsonl"
                if not path.is_file():
                    continue
                for line in path.read_text(encoding="utf-8").splitlines():
                    row = json.loads(line)
                    if row.get("temp_native") is None:
                        continue
                    wu.append((pd.Timestamp(row["valid_time_utc"]).tz_convert("UTC"), float(row["temp_native"])))
        wu = pd.DataFrame(wu, columns=["valid_utc", "wu_f"]).drop_duplicates("valid_utc", keep="last")
        mobs = obs[obs.market == market].drop_duplicates("valid_utc", keep="last")
        joined = mobs.merge(wu, on="valid_utc", how="inner")
        joined = joined[joined.tgroup_f.notna()]
        stats = defaultdict(int)
        for tg, wu_f in zip(joined.tgroup_f, joined.wu_f):
            exact = exact_tgroup_f(tg)
            tie = (exact - math.floor(exact)) * 2 == 1
            stats["rows"] += 1
            stats["ties"] += int(tie)
            for rule in WU_ROUNDING_CANDIDATES:
                hit = round_candidate(exact, rule) == wu_f
                stats[f"{rule}_match"] += int(hit)
                if tie:
                    stats[f"{rule}_tie_match"] += int(hit)
        stats["wu_rows"] = int(len(wu))
        stats["iem_rows"] = int(len(mobs))
        out["markets"][market] = dict(stats)
        for k, v in stats.items():
            totals["ALL"][k] += v
    out["ALL"] = dict(totals["ALL"])
    return out


def receipt_grace_check(*, replay_root, markets=R0_MARKETS, hours=range(7, 21), graces=(0, 5, 10, 15, 20)):
    """Capture-only: do the METAR rows observed by h:00 in the latest snapshot captured by h:00 + g equal the
    rows in the last snapshot of the hour (the eventually-received set the trainer's WU history matches)?"""
    import re
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.market.market_registry import spec_for_id

    pattern = re.compile(r'"captured_at_local":\s*"([^"]+)"')
    hours = set(hours)
    out = {"graces": list(graces), "markets": {}}
    for market in markets:
        tz = ZoneInfo(spec_for_id(market).timezone)
        stats = defaultdict(int)
        gaps = []
        for slug, target, folder in l3._event_folders(replay_root):
            if slug != market or not (N_DEV_FIRST <= target <= N_DEV_LAST):
                continue
            index = []
            with open(Path(folder) / "replay_inputs.jsonl", "rb") as handle:
                offset = 0
                for line in handle:
                    match = pattern.search(line[:4096].decode("utf-8", "replace"))
                    if match:
                        local = datetime.fromisoformat(match.group(1)).astimezone(tz)
                        if local.date() == target:
                            index.append((local, offset, len(line)))
                    offset += len(line)
                index.sort()
                gaps += [(b[0] - a[0]).total_seconds() / 60 for a, b in zip(index, index[1:])]
                cache = {}

                def features(entry, hour):
                    key = (entry[1], hour)
                    if key not in cache:
                        handle.seek(entry[1])
                        try:
                            snap = json.loads(handle.read(entry[2]))
                        except json.JSONDecodeError:  # truncated capture line
                            cache[key] = None
                            return None
                        rows = ((((snap.get("sources") or {}).get("metar") or {}).get("data")) or {}).get("rows")
                        cache[key] = l3.observations_at_cutoff(rows, target, hour, tz)
                    return cache[key]

                for hour in sorted(hours):
                    cutoff = datetime(target.year, target.month, target.day, hour, tzinfo=tz)
                    in_hour = [e for e in index if cutoff <= e[0] < cutoff + timedelta(hours=1)]
                    if not in_hour:
                        stats["no_snapshot_in_hour"] += 1
                        continue
                    ref = features(in_hour[-1], hour)
                    if ref is None:
                        stats["corrupt_reference"] += 1
                        continue
                    stats["hours"] += 1
                    final = features(index[-1], hour)  # last same-day snapshot: eventually-received proxy
                    if final is not None:
                        stats["last_in_hour_vs_final_hours"] += 1
                        stats["last_in_hour_same_final_rows"] += int(final[2] == ref[2])
                        stats["last_in_hour_same_final_features"] += int(final[0] == ref[0] and final[1] == ref[1])
                    for g in graces:
                        before = [e for e in index if e[0] <= cutoff + timedelta(minutes=g)]
                        if not before:
                            stats[f"g{g}_no_snapshot"] += 1
                            continue
                        got = features(before[-1], hour)
                        if got is None:
                            stats[f"g{g}_corrupt"] += 1
                            continue
                        stats[f"g{g}_same_rows"] += int(got[2] == ref[2])
                        stats[f"g{g}_same_features"] += int(got[0] == ref[0] and got[1] == ref[1])
        gaps.sort()
        stats["median_gap_min"] = gaps[len(gaps) // 2] if gaps else None
        out["markets"][market] = dict(stats)
    total = defaultdict(int)
    for s in out["markets"].values():
        for k, v in s.items():
            if k != "median_gap_min" and v is not None:
                total[k] += v
    out["ALL"] = dict(total)
    return out


def _plain(value):
    """numpy scalars to Python floats/ints for the frozen state."""
    import numpy as np

    if isinstance(value, dict):
        return {(tuple(_plain(k) for k in key) if isinstance(key, tuple) else _plain(key)): _plain(v)
                for key, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def forward_training_frame(records_root, markets=R0_MARKETS, centres=FORWARD_CENTRES):
    payloads = [load_records(records_root, m, c) for c in centres for m in markets]
    frame, _ = pooled_frame(payloads, station_coordinates(markets))
    drop = [c for c in frame.columns if c.startswith("x_") and c not in DEV_KEEP_X]
    frame = frame.drop(columns=drop)
    buckets = {}
    for market in markets:
        union = set()
        for p in payloads:
            if p["market"] == market:
                union |= {int(b) for b in p["bucket_space"]}
        buckets[market] = sorted(union)
    return frame, buckets


def availability_counts(frame):
    counts = frame.groupby(["market", frame["target_date"].str[5:7], "year"]).agg(
        days=("target_date", "nunique"), rows=("y", "size"))
    return {f"{m}|{mo}|{y}": {"days": int(r.days), "rows": int(r.rows)} for (m, mo, y), r in counts.iterrows()}


def state_mean_dict(model):
    import numpy as np

    return {
        "bias": _plain(dict(model.bias)), "bias_by": model.bias_by, "bias_global": float(model.bias_global),
        "normal": _plain(dict(model.normal)), "normal_by_market": _plain(dict(model.normal_by_market)),
        "normal_global": float(model.normal_global), "x_columns": list(model.x_columns),
        "ols": np.asarray(model.ols, dtype=np.float64).reshape(3), "hgb": model.hgb,
        "doy": bool(model.doy), "market_id": bool(model.market_id),
    }


def state_features(state, hour, *, market, target_date, high_so_far, current_temp, nbm_mean):
    """Serve math from the frozen state only (reference for L8): (X row, mu0, g, F)."""
    import numpy as np

    mean = state["hours"][int(hour)]["mean"]
    centre = min(state["centres"], key=lambda c: abs((date(2001, int(c[5:7]), int(c[8:10]))
                                                      - date(2001, target_date.month, target_date.day)).days))
    season = state["season_of"][centre[5:7]]
    bias = mean["bias"].get((market, season), mean["bias_global"])
    normal = mean["normal"].get((market, centre), mean["normal_by_market"].get(market, mean["normal_global"]))
    if state["conversion"]["enabled"]:
        high_so_far = wu_whole_f(high_so_far, state["conversion"]["rule_id"].split(":")[-1])
        current_temp = wu_whole_f(current_temp, state["conversion"]["rule_id"].split(":")[-1])
    mu0 = nbm_mean + bias if nbm_mean is not None and math.isfinite(nbm_mean) else normal
    g = high_so_far - mu0
    lat, lon, elev = state["coords"][market]
    doy = target_date.timetuple().tm_yday
    levels = {"high_so_far": high_so_far, "current_temp": current_temp}
    cols = [levels[name] - mu0 for name in state["constants"]["levels"]]
    cols += [g, max(g, 0.0), mu0 - normal, lat, lon, elev, normal, bias]
    if mean["doy"]:
        cols += [math.sin(2 * math.pi * doy / 365.25), math.cos(2 * math.pi * doy / 365.25)]
    return np.asarray([cols], dtype=float), mu0, g, high_so_far


def state_distribution(state, hour, **inputs):
    import numpy as np

    from weather.calibration import feature_model as fm

    X, mu0, g, floor = state_features(state, hour, **inputs)
    entry = state["hours"][int(hour)]
    mean = entry["mean"]
    design = np.array([[1.0, g, max(g, 0.0)]])
    yhat = float((mu0 + design @ mean["ols"] + mean["hgb"].predict(X))[0])
    c = state["constants"]
    s = max(c["min_scale"], float(entry["scale"].predict(np.column_stack([X, [yhat - floor]]))[0]) * math.sqrt(math.pi / 2))
    market = inputs["market"]
    p_clim = fm.smoothed_dist(entry["train_y"][market], state["buckets"][market], alpha=c["clim_alpha"])
    return predictive_distribution(yhat, s, floor, entry["z"], state["buckets"][market], p_clim)


def forward_fit(*, records_root, nbm_train_corpus, out_dir, rounding_rule, late_report, commit,
                markets=R0_MARKETS, input_shas=None):
    """Clarification 3: the Aug-Dec 2021-25 P3d_N refit, exported as the frozen L8 state (no 2026 row)."""
    import platform
    import pickle as _pickle

    import numpy as np
    import pandas as pd
    import scipy
    import sklearn

    from weather.calibration import ols_floor_ladder as l9
    from weather.market.market_registry import spec_for_id

    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pkl, side = out / "p3d_n_state.pkl", out / "p3d_n_state.json"
    for path in (pkl, side):
        if path.exists():
            raise PooledModelError(f"refusing to overwrite {path}")
    frame, buckets = forward_training_frame(records_root, markets)
    if frame["year"].max() >= 2026 or not set(frame["year"].unique()) <= set(FORWARD_YEARS):
        raise PooledModelError("a forward training row is outside 2021-25")
    nonint = int(sum((~np.isclose(frame[c].dropna() % 1, 0)).sum() for c in DEV_KEEP_X))
    timezones = {m: spec_for_id(m).timezone for m in markets}
    frame, train_nbm = attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff, timezones)
    hours = {}
    for hour in sorted(int(h) for h in frame["hour"].unique()):
        train = frame[frame["hour"] == hour].reset_index(drop=True)
        fitted = fit_pooled(train, market_id=False, doy=True, raw_columns=False, bias_by="season")
        hours[hour] = {
            "mean": state_mean_dict(fitted["mean"]), "scale": fitted["scale"],
            "z": np.asarray(fitted["z"], dtype=np.float64),
            "train_y": {m: [int(v) for v in train.loc[train["market"] == m, "y"]] for m in markets},
        }
        print(f"forward fit hour {hour}: {len(train)} rows", flush=True)
    levels = [name for name in LEVEL_COLUMNS if f"x_{name}" in frame.columns]
    module_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    state = {
        "schema": STATE_SCHEMA, "arm": N_ARM, "fit_kind": "forward", "markets": list(R0_MARKETS),
        "centres": list(FORWARD_CENTRES),
        "season_of": {f"{m:02d}": season_of(f"2026-{m:02d}-01") for m in range(1, 13)},
        "coords": {m: [float(v) for v in station_coordinates([m])[m]] for m in markets},
        "buckets": {m: [int(b) for b in buckets[m]] for m in markets},
        "constants": {"floor_mix_clim": FLOOR_MIX_CLIM, "kernel_bandwidth": KERNEL_BANDWIDTH,
                      "min_scale": MIN_SCALE, "clim_alpha": 0.10, "levels": levels},
        "conversion": {"enabled": True, "rule_id": f"wu_whole_f_tgroup:{rounding_rule}",
                       "rule": (f"exact F = 32 + 9*t/50 with t = the T-group tenths of a degree C recovered from the "
                                f"METAR temp_native; WU whole F = {rounding_rule} rounding of that exact value"
                                " (applied to high_so_far and current_temp before g, the floor and the features)")},
        "late_report": dict(late_report),
        "hours": hours,
        "provenance": {
            "commit": commit, "module_sha256": module_sha, "training_rows": int(len(frame)),
            "train_years": sorted(int(y) for y in frame["year"].unique()),
            "train_window": {"centres": list(FORWARD_CENTRES), "first_date_md": frame["target_date"].str[5:].min(),
                             "last_date_md": frame["target_date"].str[5:].max()},
            "train_nbm": train_nbm, "non_integer_training_obs": nonint,
            "availability": availability_counts(frame),
            "inputs": dict(input_shas or {}),
            "versions": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
                         "sklearn": sklearn.__version__, "pandas": pd.__version__},
        },
    }
    blob = _pickle.dumps(state, protocol=4)
    pkl.write_bytes(blob)
    digest = hashlib.sha256(blob).hexdigest()
    side.write_text(json.dumps(dict(state["provenance"], state_sha256=digest), indent=1, sort_keys=True),
                    encoding="utf-8")
    # Export parity: the frozen state reproduces the in-process mean model on sampled training rows.
    probe = dict(state, conversion={"enabled": False, "rule_id": None, "rule": None})
    worst = 0.0
    checked = 0
    for hour, entry in hours.items():
        train = frame[frame["hour"] == hour].reset_index(drop=True)
        ref = MeanModel(market_id=False, doy=True, raw_columns=False, bias_by="season")
        for key, value in entry["mean"].items():
            setattr(ref, key, value)
        sample = train.sample(n=min(200, len(train)), random_state=hour)
        pred, X_ref = ref.predict(sample)
        for j, (_, row) in enumerate(sample.iterrows()):
            if not (math.isfinite(float(row["F"])) and math.isfinite(float(row["x_current_temp"]))):
                continue
            X, mu0, g, _ = state_features(
                probe, hour, market=row["market"], target_date=date.fromisoformat(row["target_date"]),
                high_so_far=float(row["F"]), current_temp=float(row["x_current_temp"]), nbm_mean=float(row["fh"]))
            yhat = float((mu0 + np.array([[1.0, g, max(g, 0.0)]]) @ entry["mean"]["ols"]
                          + entry["mean"]["hgb"].predict(X))[0])
            worst = max(worst, float(np.max(np.abs(X - X_ref[j]))), abs(yhat - float(pred[j])))
            checked += 1
    if worst > 1e-9:
        raise PooledModelError(f"frozen state does not reproduce the fitted model (max abs diff {worst})")
    print(f"export parity: {checked} training rows, max abs diff {worst:.3g}", flush=True)
    return state, digest


def dev_verdict_markdown(scores, rule_path, arms=tuple(DEV_ARMS)):
    """Amendment 3: L3's dev verdict applied to P3d (decisive) and U0d, with the reported groups."""
    from weather.calibration import r0_ols_floor_challenger as l3

    verdict = l3.dev_verdict(scores, arms=arms)
    rule_sha = hashlib.sha256(Path(rule_path).read_bytes()).hexdigest()
    pop = scores.get("population", {})
    lines = ["# L2 amendment 3: dev window vs served (dev_scorecard via L3 dev-score)", "",
             f"Rule: {rule_path} sha256 {rule_sha}", "",
             f"Population: {json.dumps(pop)}; layout manifest {scores.get('layout_manifest_sha256')}; "
             f"scorecard code {scores.get('scorecard_code_sha256')}", "",
             "## Verdict (pooled 07-12 dR = R_candidate - R_served; negative = better than served)", "",
             "| Arm | interval | dR | 95% CI | blocks worse | beats served |", "| --- | --- | --- | --- | --- | --- |"]
    for arm in arms:
        for kind in ("dR_date_clustered", "dR_crossed"):
            v = verdict[arm][kind]
            lines.append(f"| {arm} | {kind} | {v['estimate']:+.4f} | [{v['ci95'][0]:+.4f}, {v['ci95'][1]:+.4f}] | "
                         f"{', '.join(v['blocks_worse']) or 'none'} | {v['beats_served']} |")
    groups = ["00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all", "07-12", "12-16"] + [
        f"h{h:02d}" for h in range(7, 21)]
    for arm in arms:
        rows = {(r["market"], r["group"]): r for r in scores["candidates"][arm]["rows"]}
        lines += ["", f"## {arm}: pooled groups (R, dR date-clustered 95%)", "",
                  "| Group | n market-days | R_candidate | R_served | dR | 95% CI |", "| --- | --- | --- | --- | --- | --- |"]
        for g in groups:
            r = rows.get(("ALL", g))
            if r is None:
                continue
            d = r["dR_date_clustered"]
            tag = " **(12)**" if g == "h12" else ""
            lines.append(f"| {g}{tag} | {r['n_market_days']} | {r['R_candidate']['estimate']:.3f} | "
                         f"{r['R_served']['estimate']:.3f} | {d['estimate']:+.4f} | [{d['ci95'][0]:+.4f}, {d['ci95'][1]:+.4f}] |")
        lines += ["", f"## {arm}: per market 07-12", "", "| Market | dR | 95% CI |", "| --- | --- | --- |"]
        for (m, g), r in sorted(rows.items()):
            if g == "07-12" and m != "ALL":
                d = r["dR_date_clustered"]
                lines.append(f"| {m} | {d['estimate']:+.4f} | [{d['ci95'][0]:+.4f}, {d['ci95'][1]:+.4f}] |")
    return "\n".join(lines) + "\n", verdict


# -------------------------------------------------------------------------- CLI




# ------------------------------------------------- R-M: per-market centre bias at 07-12 (lane L11, rule_rm.md)

RM_RULE_SHA256 = "91e25610bf7c56193a040289e16ea21ed5aea53de2d20f7a4ed23033cb4a225b"
RM_GRID = tuple(round(-4.0 + 0.1 * i, 1) for i in range(81))  # -4.0 .. +4.0 F, contains 0.0
RM_ZERO = RM_GRID.index(0.0)
RM_RA_LOYO_SHA256 = "21cacdaabcf50165da084a748b42a0b862c36c9e1f4b8d4bdb506c07c927f54d"
RM_NBM_TRAIN_SHA256 = "1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd"
RM_THREE = ("dallas", "austin", "seattle")  # R-H finding 4: called out, never re-selected


def rm_pick(loss, grid=RM_GRID):
    """Grid minimiser; ties go to the shift closest to 0."""
    import numpy as np

    loss = np.asarray(loss, dtype=float)
    best = np.flatnonzero(loss <= loss.min() + 1e-15)
    return float(min((grid[i] for i in best), key=lambda s: (abs(s), s)))


def rm_cdf(keys, probs):
    """Piecewise-uniform integer pmf -> (edges at k +- 0.5, CDF at the edges)."""
    import numpy as np

    keys = np.asarray(keys, dtype=int)
    lo, hi = int(keys.min()), int(keys.max())
    dense = np.zeros(hi - lo + 1)
    np.add.at(dense, keys - lo, np.asarray(probs, dtype=float))
    edges = np.arange(lo - 0.5, hi + 1.0, 1.0)
    return edges, np.concatenate([[0.0], np.cumsum(dense)])


def rm_shifted_cdf(edges, cdf, x, shifts):
    """G_s(x) = F(x - s): rows = shifts, columns = x (left of the support 0, right of it the total mass)."""
    import numpy as np

    s = np.asarray(shifts, dtype=float)[:, None]
    return np.interp((np.asarray(x, dtype=float)[None, :] - s).ravel(), edges, cdf, left=0.0,
                     right=float(cdf[-1])).reshape(len(s), -1)


def rm_shift_dict(keys, probs, shifts):
    """Translate an integer pmf by each shift and rebin to integers: (ks, Q[shift, k])."""
    import numpy as np

    edges, cdf = rm_cdf(keys, probs)
    pad = int(math.ceil(max(abs(float(v)) for v in shifts))) + 1
    ks = np.arange(int(edges[0] + 0.5) - pad, int(edges[-1] - 0.5) + pad + 1)
    g = rm_shifted_cdf(edges, cdf, np.append(ks - 0.5, ks[-1] + 0.5), shifts)
    return ks, np.diff(g, axis=1)


def rm_loyo_losses(dist, actual, floor, shifts=RM_GRID):
    """fm.brier_score (integer keys) of the shifted pmf at every shift, under the LOYO rule-4 mask."""
    import numpy as np

    from weather.units import round_half_up

    keys = list(dist)
    ks, q = rm_shift_dict(keys, [dist[k] for k in keys], shifts)
    q0 = q[list(shifts).index(0.0)] if 0.0 in shifts else None
    if floor is not None and math.isfinite(floor):
        q = np.where((ks < int(round_half_up(floor)))[None, :], 0.0, q)
    tot = q.sum(axis=1, keepdims=True)
    if q0 is not None:
        q = np.where(tot > 0, q / np.where(tot > 0, tot, 1.0), q0[None, :])
    else:
        q = q / np.where(tot > 0, tot, 1.0)
    onehot = (ks == int(actual)).astype(float)
    loss = ((q - onehot[None, :]) ** 2).sum(axis=1)
    if not (ks[0] <= int(actual) <= ks[-1]):
        loss = loss + 1.0
    return loss


def rm_loyo(frame, buckets, hours=RUNG_HOURS):
    """Gate 1: strictly nested LOYO of one shift per market (07-12 block) on P3d_N_fix (2021-25 Aug-Sep rows)."""
    import numpy as np

    from weather.calibration import feature_model as fm

    inner = defaultdict(lambda: np.zeros(len(RM_GRID)))
    outer = []
    for hour in hours:
        at_hour = frame[frame["hour"] == hour]
        years = sorted(int(y) for y in at_hour["year"].unique())

        def predict(train_years, target_year):
            train = at_hour[at_hour["year"].isin(train_years)].reset_index(drop=True)
            val = at_hour[at_hour["year"] == target_year].reset_index(drop=True)
            entry = _rung_entry(train, *_arm_spec(RUNG_ARMS["P3d_N_fix"]))
            out = []
            for market in sorted(val["market"].unique()):
                part = val[val["market"] == market].reset_index(drop=True)
                for i, dist in enumerate(_dist_from_fit(entry, part, buckets, market)):
                    out.append((market, str(part.at[i, "target_date"])[:10], dist, int(part.at[i, "y"]),
                                float(part.at[i, "F"])))
            return out

        for held in years:
            for x in years:
                if x == held:
                    continue
                for market, _, dist, a, floor in predict([y for y in years if y not in (x, held)], x):
                    inner[(held, market)] += rm_loyo_losses(dist, a, floor)
            for market, day, dist, a, floor in predict([y for y in years if y != held], held):
                outer.append({"hour": int(hour), "year": int(held), "market": market, "date": day,
                              "raw_brier": float(fm.brier_score(dist, a)), "loss": rm_loyo_losses(dist, a, floor),
                              "actual_in_keys": a in dist})
        print(f"rm loyo h{hour:02d}: {sum(1 for r in outer if r['hour'] == hour)} rows", flush=True)
    shifts = {}
    for (held, market), loss in sorted(inner.items()):
        s = rm_pick(loss)
        i = RM_GRID.index(s)
        shifts[(held, market)] = {"shift": s, "inner_brier_noshift": float(loss[RM_ZERO]),
                                  "inner_brier_shift": float(loss[i]),
                                  "training_score_not_worse": bool(loss[i] <= loss[RM_ZERO] + 1e-12)}
    rows = []
    for r in outer:
        s = shifts[(r["year"], r["market"])]["shift"]
        rows.append({"hour": r["hour"], "year": r["year"], "market": r["market"], "date": r["date"], "shift": s,
                     "P3d_N_fix_brier": r["raw_brier"], "noshift_brier": float(r["loss"][RM_ZERO]),
                     "shift_brier": float(r["loss"][RM_GRID.index(s)]), "actual_in_keys": r["actual_in_keys"]})
    return rows, shifts


def rm_loyo_summary(rows, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED):
    import numpy as np

    out = {}
    groups = {"07-12": rows}
    groups.update({f"h{h:02d}": [r for r in rows if r["hour"] == h] for h in sorted({r["hour"] for r in rows})})
    groups.update({m: [r for r in rows if r["market"] == m] for m in sorted({r["market"] for r in rows})})
    rng = np.random.default_rng(seed)
    for name, rs in groups.items():
        by_date = defaultdict(list)
        for r in rs:
            by_date[r["date"]].append(r["shift_brier"] - r["noshift_brier"])
        dates = sorted(by_date)
        sums = np.array([sum(by_date[d]) for d in dates])
        counts = np.array([len(by_date[d]) for d in dates])
        idx = rng.integers(0, len(dates), size=(draws, len(dates)))
        boot = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
        out[name] = {"shift_minus_noshift": float(sums.sum() / counts.sum()),
                     "ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
                     "noshift_mean": float(np.mean([r["noshift_brier"] for r in rs])), "n": len(rs),
                     "n_dates": len(dates)}
    return out


def rung_m_loyo(*, records_root, nbm_train_corpus, ra_loyo_rows, out_dir, markets=R0_MARKETS, hours=RUNG_HOURS):
    """R-M gate 1 (rule_rm.md): nested LOYO, with R-A's LOYO Brier reproduced as a positive control."""
    from weather.calibration import ols_floor_ladder as l9
    from weather.market.market_registry import spec_for_id

    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name in ("rm_loyo.json", "rm_loyo_rows.jsonl"):
        if (out / name).exists():
            raise PooledModelError(f"refusing to overwrite {out / name}")
    for path, want in ((nbm_train_corpus, RM_NBM_TRAIN_SHA256), (ra_loyo_rows, RM_RA_LOYO_SHA256)):
        got = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if got != want:
            raise PooledModelError(f"{path} sha {got} != {want}")
    timezones = {m: spec_for_id(m).timezone for m in markets}
    frame, buckets = dev_training_frame(records_root, markets)
    if frame["year"].max() >= 2026:
        raise PooledModelError("a dev training row is from 2026")
    frame, train_stats = attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff, timezones)
    frame = frame[frame["hour"].isin(hours)].reset_index(drop=True)
    rows, shifts = rm_loyo(frame, buckets, hours)
    ra = {}
    with open(ra_loyo_rows, encoding="utf-8") as handle:
        for line in handle:
            r = json.loads(line)
            ra[(r["hour"], r["market"], r["date"])] = r["P3d_N_fix_brier"]
    worst = max(abs(r["P3d_N_fix_brier"] - ra[(r["hour"], r["market"], r["date"])]) for r in rows)
    if len(ra) != len(rows) or worst > 1e-9:
        raise PooledModelError(f"R-A LOYO control failed: rows {len(rows)} vs {len(ra)}, max diff {worst}")
    if not all(v["training_score_not_worse"] for v in shifts.values()):
        raise PooledModelError("a fitted shift worsened its own training score")
    _write_jsonl(out / "rm_loyo_rows.jsonl", rows)
    summary = rm_loyo_summary(rows)
    mask_effect = [r["noshift_brier"] - r["P3d_N_fix_brier"] for r in rows]
    result = {"rule_sha256": RM_RULE_SHA256, "train_nbm": train_stats, "grid": [RM_GRID[0], RM_GRID[-1], 0.1],
              "controls": {"ra_loyo_rows": len(ra), "ra_max_abs_diff": worst,
                           "loyo_mask_effect_noshift_minus_raw": {"mean": float(sum(mask_effect) / len(rows)),
                                                                  "max_abs": float(max(map(abs, mask_effect)))},
                           "training_score_not_worse_all": True,
                           "rows_actual_not_a_pmf_key": int(sum(not r["actual_in_keys"] for r in rows))},
              "shifts": {f"{m}|{y}": v for (y, m), v in sorted(shifts.items(), key=lambda kv: (kv[0][1], kv[0][0]))},
              "summary": summary, "gate1_pass": summary["07-12"]["ci95"][1] < 0,
              "inputs": {"nbm_train_corpus": RM_NBM_TRAIN_SHA256, "ra_loyo_rows": RM_RA_LOYO_SHA256,
                         "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    (out / "rm_loyo.json").write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


def rm_fix_prepare(dists, bands):
    """Per snapshot with a P3d_N_fix pmf: its CDF and band edges, built once."""
    import numpy as np

    prep = []
    for rk, g in bands[bands.row_key.isin(set(dists))].groupby("row_key", sort=False):
        d = dists[rk]
        keys = list(d)
        edges, cdf = rm_cdf(keys, [d[k] for k in keys])
        kind = g.kind.to_numpy()
        up = np.where(kind == "gte", np.inf, g.high.to_numpy(float) + 0.5)
        lo = np.where(kind == "lte", -np.inf, g.low.to_numpy(float) - 0.5)
        prep.append((rk, g.band_index.to_numpy(int), edges, cdf, up, lo))
    return prep


def rm_fix_band_probs(prep, shift_of):
    """P3d_N_fix integer pmfs translated by shift_of(row_key) and mapped onto the bands (lte/eq/gte)."""
    import numpy as np
    import pandas as pd

    rk_out, bi_out, p_out = [], [], []
    for rk, bi, edges, cdf, up, lo in prep:
        s = float(shift_of(rk))
        gu = np.where(np.isinf(up), cdf[-1], np.interp(np.where(np.isinf(up), 0.0, up) - s, edges, cdf, left=0.0,
                                                      right=float(cdf[-1])))
        gl = np.where(np.isinf(lo), 0.0, np.interp(np.where(np.isinf(lo), 0.0, lo) - s, edges, cdf, left=0.0,
                                                   right=float(cdf[-1])))
        rk_out.extend([rk] * len(bi))
        bi_out.append(bi)
        p_out.append(np.clip(gu - gl, 0.0, None))
    return pd.DataFrame({"row_key": rk_out, "band_index": np.concatenate(bi_out) if bi_out else np.zeros(0, int),
                         "p": np.concatenate(p_out) if p_out else np.zeros(0)})


def rm_l6_band_probs(state, snaps, bands, shift):
    """L6 (l6_stack.predict) with its centre moved by ``shift`` (array per snapshot), vectorised over bands."""
    import numpy as np
    import pandas as pd

    from weather.reporting.scorecards.free_source_candidates import l6_stack, mg1

    s = _with_floor(snaps).reset_index(drop=True)
    table, _ = l6_stack.nowcasts()
    n = table[state["column"]].reindex(s.row_key).to_numpy(float)
    v2 = pd.to_numeric(s.v2_mean, errors="coerce").to_numpy(float)
    hours = s.local_hour.to_numpy(int)
    mu = v2.copy()
    for h, (a, b, _) in state["coef"].items():
        sel = (hours == h) & np.isfinite(n) & np.isfinite(v2)
        mu[sel] = v2[sel] + a + b * (n[sel] - v2[sel])
    mu = mu + np.asarray(shift, dtype=float)
    avail = pd.to_datetime(s.v2_available_at, utc=True, errors="coerce")
    t = pd.to_datetime(s.captured_at_utc, utc=True)
    sd = pd.to_numeric(s.v2_stddev, errors="coerce").to_numpy(float)
    ok = np.isfinite(mu) & np.isfinite(sd) & avail.notna().to_numpy() & (avail <= t).fillna(False).to_numpy()
    floor = pd.to_numeric(s["floor"], errors="coerce").to_numpy(float)
    B = np.where(np.isfinite(floor), np.floor(floor + 0.5), -np.inf)
    pos = pd.Series(np.arange(len(s)), index=s.row_key.to_numpy())
    b = bands[bands.row_key.isin(set(s.row_key[ok]))]
    i = pos.reindex(b.row_key.to_numpy()).to_numpy(int)
    p = mg1.band_probs(b.kind.to_numpy(), b.low.to_numpy(), b.high.to_numpy(), B[i], mu[i], np.maximum(sd[i], 1.0))
    return pd.DataFrame({"row_key": b.row_key.to_numpy(), "band_index": b.band_index.to_numpy(int),
                         "p": np.asarray(p, float)})


def rm_walk_forward(briers, dates, markets, sel, scored_dates):
    """s(m, d) = grid minimiser of the summed Brier on selected snapshots of market m dated before d."""
    out = {}
    for m in sorted(set(markets[sel])):
        at = sel & (markets == m)
        for d in scored_dates:
            use = at & (dates < d)
            out[(m, d)] = rm_pick(briers[use].sum(axis=0)) if use.any() else 0.0
    return out


def rung_m_score(*, layout, fix_jsonl, coefficients, nowcasts, loyo_result, out_path, start="2026-08-01",
                 end="2026-09-29"):
    """R-M gates 2 and 3 (rule_rm.md)."""
    import os

    import numpy as np

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas

    out_path = require_output_outside_repo(out_path)
    if out_path.exists():
        raise PooledModelError(f"refusing to overwrite {out_path}")
    loyo = json.loads(Path(loyo_result).read_bytes())
    if loyo.get("rule_sha256") != RM_RULE_SHA256 or not loyo.get("gate1_pass"):
        raise PooledModelError("gate 1 has not passed under this rule; gate 2 may not run (KILL applies)")
    now_sha = hashlib.sha256(Path(nowcasts).read_bytes()).hexdigest()
    if now_sha != L6_NOWCAST_SHA256:
        raise PooledModelError(f"L6 nowcast sha {now_sha} != {L6_NOWCAST_SHA256}")
    fix_sha = hashlib.sha256(Path(fix_jsonl).read_bytes()).hexdigest()
    if fix_sha != RI_FIX_SHA256:
        raise PooledModelError(f"P3d_N_fix vectors sha {fix_sha} != {RI_FIX_SHA256}")
    os.environ["L6_NOWCASTS"] = str(nowcasts)
    from weather.reporting.scorecards.free_source_candidates import l6_stack

    l6_stack._CACHE.clear()
    state, part_sha = l6_frozen_state(coefficients)
    start_d, end_d = data.check_range(start, end)
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    fit_dates = sorted(d for d in {str(x) for x in lay.dates} if BLEND_FIT_FIRST <= d <= end)
    dists = {}
    with open(fix_jsonl, encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if str(row.get("target_date", ""))[:10] > end:
                raise PooledModelError("P3d_N_fix vectors hold rows after the window")
            dists[f"{row['market']}|{row['snapshot_id']}"] = {int(float(k)): float(v)
                                                             for k, v in row["distribution"].items()}

    preps = {}

    def arm_vectors(table, shift_fix, shift_l6):
        """(p_fix, p_l6) on ``table`` with per-snapshot shifts (arrays aligned to table.snaps)."""
        pos = dict(zip(table.snaps.row_key, range(len(table.snaps))))
        if id(table) not in preps:
            preps.clear()
            preps[id(table)] = rm_fix_prepare(dists, table.bands)
        fx = rm_fix_band_probs(preps[id(table)], lambda rk: shift_fix[pos[rk]] if rk in pos else 0.0)
        p_fix, _ = table.candidate_vector(fx)
        p_l6, _ = table.candidate_vector(rm_l6_band_probs(state, table.snaps, table.bands, shift_l6))
        return p_fix, p_l6

    # coverage and controls on the fitting table
    full = sc.Table(lay, fit_dates)
    fix0, fcov, _ = l3._vector(full, l3._candidate_frame(str(fix_jsonl), full, lay, folds, data)[0])
    l60, lcov, _ = l6_vector(full, state, l3)
    zero = np.zeros(len(full.snaps))
    a_fix, a_l6 = arm_vectors(full, zero, zero)
    common_f = fcov & lcov
    band_common = common_f[full.band_snap]
    controls = {"fix_s0_max_abs_diff": float(np.max(np.abs(a_fix - fix0)[band_common])),
                "l6_s0_max_abs_diff": float(np.max(np.abs(a_l6 - l60)[band_common]))}
    if controls["fix_s0_max_abs_diff"] > 1e-9 or controls["l6_s0_max_abs_diff"] > 1e-9:
        raise PooledModelError(f"s = 0 does not reproduce the registered arms: {controls}")
    fdates = full.snaps.date.astype(str).to_numpy()
    sel = common_f & (full.local_hour >= 7) & (full.local_hour <= 12)
    grids = {"P3d_N_fix": np.zeros((len(full.snaps), len(RM_GRID))), "L6": np.zeros((len(full.snaps), len(RM_GRID)))}
    for j, s in enumerate(RM_GRID):
        sh = np.full(len(full.snaps), s)
        pf, pl = arm_vectors(full, sh, sh)
        grids["P3d_N_fix"][sel, j] = full.brier(pf)[sel]
        grids["L6"][sel, j] = full.brier(pl)[sel]
        print(f"rm grid {s:+.1f}", flush=True)
    shifts = {arm: rm_walk_forward(g, fdates, full.markets, sel, scored) for arm, g in grids.items()}
    del grids, full
    preps.clear()

    table = sc.Table(lay, scored)
    date_w = l3._date_weights([k[0] for k in table.keys], sc.DRAWS, sc.SEED)
    market_b = table.brier(table.p_market)
    p_fix, cov_fix, r_fix = l3._vector(table, l3._candidate_frame(str(fix_jsonl), table, lay, folds, data)[0])
    p_l6, cov_l6, r_l6 = l6_vector(table, state, l3)
    p_mg1, _, _ = l3._vector(table, loss_atlas.mg1_frame(table))
    w0712 = (table.local_hour >= 7) & (table.local_hour <= 12)
    _, e = table.cells(table.brier(p_mg1) - market_b, w0712)
    mg1_excess = float(e.mean())
    if round(mg1_excess, 3) != l3.MG1_CONTROL_0712_EXCESS:
        raise PooledModelError(f"MG-1 positive control failed: {mg1_excess:.5f}")
    common = cov_fix & cov_l6
    tdates = table.snaps.date.astype(str).to_numpy()
    in_scope = common & w0712

    def per_snap(arm):
        return np.array([shifts[arm].get((m, d), 0.0) if c else 0.0
                         for m, d, c in zip(table.markets, tdates, in_scope)])

    s_fix, s_l6 = per_snap("P3d_N_fix"), per_snap("L6")
    p_fix_s, _ = arm_vectors(table, s_fix, np.zeros(len(table.snaps)))
    _, p_l6_s = arm_vectors(table, np.zeros(len(table.snaps)), s_l6)
    probs = {"P3d_N_fix": p_fix, "L6": p_l6, "P3d_N_fix_shift": np.where(in_scope[table.band_snap], p_fix_s, p_fix),
             "L6_shift": np.where(in_scope[table.band_snap], p_l6_s, p_l6)}
    for name, v in probs.items():
        mass = np.add.reduceat(v, table.offsets)
        if np.any(np.abs(mass[common] - 1.0) > 1e-9):
            raise PooledModelError(f"{name}: probability mass not preserved")
    briers = {k: table.brier(v) for k, v in probs.items()}
    groups = [("07-12", 7, 12)] + [(f"h{h:02d}", h, h) for h in RUNG_HOURS]
    pools = [(sc.ALL_MARKETS, None)] + [(m, {m}) for m in sorted(set(table.markets))]

    def compare(arm, ref):
        rows = []
        for market, members in pools:
            in_pool = np.ones(len(table.snaps), bool) if members is None else np.isin(table.markets, sorted(members))
            for group, lo, hi in groups if members is None else groups[:1]:
                mask = common & in_pool & (table.local_hour >= lo) & (table.local_hour <= hi)
                if not mask.any():
                    continue
                idx, c = table.cells(briers[arm], mask)
                _, r_ = table.cells(briers[ref], mask)
                _, m = table.cells(market_b, mask)
                rows.append({"arm": arm, "reference": ref, "market": market, "group": group,
                             "n_market_days": int(len(idx)), "n_snapshots": int(mask.sum()),
                             "R_arm": sc.ratio_interval(table.w[:, idx], c, m),
                             "R_reference": sc.ratio_interval(table.w[:, idx], r_, m),
                             "dR_crossed": sc.ratio_interval(table.w[:, idx], c - r_, m),
                             "dR_date_clustered": sc.ratio_interval(date_w[:, idx], c - r_, m)})
        return rows

    def primary(rows):
        return next(r for r in rows if r["market"] == sc.ALL_MARKETS and r["group"] == "07-12")

    def hours_lower(rows):
        return [r["dR_date_clustered"]["ci95"][0] for r in rows if r["market"] == sc.ALL_MARKETS
                and r["group"] != "07-12"]

    def passes(rows):
        p = primary(rows)["dR_date_clustered"]["ci95"]
        return p[1] < 0 and not any(lo > 0 for lo in hours_lower(rows))

    def reading(rows):
        if primary(rows)["dR_date_clustered"]["ci95"][0] > 0:
            return "HARM"
        return "WIN" if passes(rows) else "NULL"

    result = {"rule": "C:/t/l11pb/rule_rm.md", "rule_sha256": RM_RULE_SHA256,
              "population": {"n_dates": len(scored), "first_date": scored[0], "last_date": scored[-1],
                             "n_market_days": len(table.keys), "common_covered_snapshots_07_12": int(in_scope.sum())},
              "controls": dict(controls, mg1_excess_07_12=mg1_excess, l6_part_sha256=part_sha,
                               l6_nowcast_sha256=now_sha, gate1=loyo["summary"]["07-12"]),
              "coverage": {"P3d_N_fix": r_fix, "L6": r_l6},
              "inputs": {"fix_jsonl": fix_sha, "loyo_result": hashlib.sha256(Path(loyo_result).read_bytes()).hexdigest(),
                         "layout_manifest_sha256": lay.manifest_sha256, "scorecard_code_sha256": sc.code_sha256(),
                         "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
              "shifts": {arm: {m: {"mean": float(np.mean([t[(m, d)] for d in scored])), "first": t[(m, scored[0])],
                                   "last": t[(m, scored[-1])]} for m in sorted({k[0] for k in t})}
                         for arm, t in shifts.items()},
              "gates": {}, "rows": []}
    result["rows"] += compare("L6", "P3d_N_fix")  # R-F incumbent control (reported)
    for arm in ("P3d_N_fix", "L6"):
        rows = compare(f"{arm}_shift", arm)
        result["rows"] += rows
        result["gates"][f"2_{arm}"] = {"dR_date_clustered": primary(rows)["dR_date_clustered"],
                                       "hours_lower": hours_lower(rows), "pass": passes(rows)}
    if result["gates"]["2_P3d_N_fix"]["pass"]:
        rows = compare("P3d_N_fix_shift", "L6")
        result["rows"] += rows
        result["gates"]["3_P3d_N_fix_shift_vs_L6"] = {"reading": reading(rows),
                                                      "dR_date_clustered": primary(rows)["dR_date_clustered"]}
    if result["gates"]["2_L6"]["pass"]:
        result["gates"]["3_L6_shift_vs_L6"] = {"reading": reading(compare("L6_shift", "L6")),
                                               "dR_date_clustered": result["gates"]["2_L6"]["dR_date_clustered"]}
    n_pass = sum(result["gates"][f"2_{a}"]["pass"] for a in ("P3d_N_fix", "L6"))
    result["kill"] = ("closed for NBM-anchored arms (gate 2 failed for both arms)" if n_pass == 0 else
                      "closed for " + ", ".join(a for a in ("P3d_N_fix", "L6") if not result["gates"][f"2_{a}"]["pass"])
                      if n_pass == 1 else "none")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


# ---------------------------------------------------------------- R-O (lane L11): GEFS member-mean centre input
# Rule: docs/research/gefs-members-l11-2026-10-26/rule_rn.md (file name kept; rung R-O, NAMING.md).
RO_RULE_SHA256 = "a9ca45f063a39b8ad2408414aab4658d5f4f96c855a51d11b34236b8045fa18c"
RO_A = tuple(round(-3.0 + 0.1 * i, 1) for i in range(61))  # -3.0 .. +3.0 F
RO_B = tuple(round(0.05 * i, 2) for i in range(21))  # 0.00 .. 1.00, so b is clipped to [0, 1] by construction
RO_PAIRS = tuple((a, b) for a in RO_A for b in RO_B)
RO_ZERO = RO_PAIRS.index((0.0, 0.0))
RO_MIN_MEMBERS = 25
RO_PERTURBED = tuple(f"gep{k:02d}" for k in range(1, 31))


def ro_pick(loss, pairs=RO_PAIRS):
    """Grid minimiser; ties -> smallest |a| + b, then smaller b, then smaller |a| (then smaller a)."""
    import numpy as np

    loss = np.asarray(loss, dtype=float)
    best = np.flatnonzero(loss <= loss.min() + 1e-15)
    return min((pairs[i] for i in best), key=lambda p: (abs(p[0]) + p[1], p[1], abs(p[0]), p[0]))


def ro_kelvin_to_f(k):
    return (float(k) - 273.15) * 9.0 / 5.0 + 32.0


def ro_load_gefs(corpus_dir):
    """{(market, YYYY-MM-DD cycle date): [(member, valid_utc, available_utc, value_F)]} from the R-O corpus rows."""
    from datetime import datetime

    table = defaultdict(list)
    path = Path(corpus_dir) / "gefs_member_rows.jsonl"
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            r = json.loads(line)
            if r.get("kind") != "message" or r.get("status") != "ok":
                continue
            valid = datetime.fromisoformat(r["valid_utc"])
            avail = datetime.fromisoformat(r["available_utc"])
            for market, p in r["points"].items():
                table[(market, r["date"])].append((r["member"], valid, avail, ro_kelvin_to_f(p["bilinear_k"])))
    return table


def ro_gefs_value(table, market, day, hour, tz):
    """Rule R-O feature G at (market, local date ``day``, cutoff ``hour``): the 30-member mean of each member's max
    over the 06Z f006..f024 nodes whose valid local date is ``day``, using only messages available by h:00 local.
    A member counts only if every such node is present and available; None below 25 members."""
    from datetime import date as _date, datetime, timezone as _tz
    from zoneinfo import ZoneInfo

    d = _date.fromisoformat(str(day)[:10])
    cutoff = datetime(d.year, d.month, d.day, int(hour), tzinfo=ZoneInfo(tz)).astimezone(_tz.utc)
    highs = [v for m, v in ro_member_highs(table, market, d, cutoff, tz).items() if m in RO_PERTURBED]
    if len(highs) < RO_MIN_MEMBERS:
        return None
    return float(sum(highs) / len(highs))


def ro_member_highs(table, market, day, cutoff_utc, tz):
    """{member: max over the 06Z f006..f024 nodes valid on local date ``day``}, for members (gec00 included) whose
    every such node is present with available_utc <= ``cutoff_utc``."""
    from datetime import date as _date, datetime, timedelta, timezone as _tz
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(tz)
    d = day if isinstance(day, _date) else _date.fromisoformat(str(day)[:10])
    cycle = datetime(d.year, d.month, d.day, 6, tzinfo=_tz.utc)
    want = {cycle + timedelta(hours=fh) for fh in (6, 9, 12, 15, 18, 21, 24)}
    want = {v for v in want if v.astimezone(zone).date() == d}
    if not want:
        return {}
    by_member = defaultdict(dict)
    for member, valid, avail, value in table.get((market, d.isoformat()), []):
        if valid in want and avail <= cutoff_utc:
            by_member[member][valid] = value
    return {m: max(v.values()) for m, v in by_member.items() if set(v) == want}


RO_PARITY_FIRST, RO_PARITY_LAST = "2026-07-30", "2026-09-29"
_RO_SLUG = None


def ro_slug_date(slug):
    """(city part, target date) from a 'highest-temperature-in-<city>-on-<month>-<day>-<year>' slug, else None."""
    import re
    from datetime import date as _date

    global _RO_SLUG
    if _RO_SLUG is None:
        _RO_SLUG = re.compile(r"^highest-temperature-in-(.+)-on-([a-z]+)-(\d{1,2})-(\d{4})$")
    m = _RO_SLUG.match(slug)
    months = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
              "november", "december")
    if not m or m.group(2) not in months:
        return None
    return m.group(1), _date(int(m.group(4)), months.index(m.group(2)) + 1, int(m.group(3)))


def ro_parity_stats(pairs):
    """mean diff, median |diff| and Pearson r over (market, date) means, for (market, date, corpus, captured)."""
    import numpy as np

    pairs = [p for p in pairs if p[2] is not None and p[3] is not None]
    if len(pairs) < 3:
        return {"n": len(pairs), "pass": False}
    diff = np.array([p[2] - p[3] for p in pairs])
    cell = defaultdict(list)
    for market, day, ours, theirs in pairs:
        cell[(market, day)].append((ours, theirs))
    xs = np.array([np.mean([o for o, _ in v]) for v in cell.values()])
    ys = np.array([np.mean([t for _, t in v]) for v in cell.values()])
    r = float(np.corrcoef(xs, ys)[0, 1]) if len(cell) >= 3 else float("nan")
    res = {"n": len(pairs), "n_cells": len(cell), "mean_diff": float(diff.mean()),
           "median_abs_diff": float(np.median(np.abs(diff))), "pearson_r_cell_means": r}
    res["pass"] = bool(abs(res["mean_diff"]) <= 1.0 and res["median_abs_diff"] <= 1.0 and r >= 0.95)
    return res


def rung_o_parity(*, inputs_root, gefs_corpus, out_dir, markets=R0_MARKETS, hours=RUNG_HOURS):
    """R-O precondition P: corpus p10/p90 of member highs and control high vs the captured global_ensemble values.

    Reads only ``sources.global_ensemble`` (plus the snapshot's id and capture time) of snapshots whose event target
    date is in 2026-07-30..2026-09-29 and whose local capture hour is in ``hours``; nothing else is decoded."""
    import re
    from datetime import date as _date, datetime

    from weather.market.market_registry import spec_for_id
    from weather.model.model_sources import percentile

    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if (out / "rn_parity.json").exists():
        raise PooledModelError(f"refusing to overwrite {out / 'rn_parity.json'}")
    first, last = _date.fromisoformat(RO_PARITY_FIRST), _date.fromisoformat(RO_PARITY_LAST)
    timezones = {m: spec_for_id(m).timezone for m in markets}
    table = ro_load_gefs(gefs_corpus)
    local_re = re.compile(r'"captured_at_local":\s*"([^"]+)"')
    stats = defaultdict(list)
    counts = defaultdict(int)
    cities = defaultdict(int)
    for folder in sorted(Path(inputs_root).iterdir()):
        parsed = ro_slug_date(folder.name)
        if parsed is None:
            counts["skipped_unparsed_slug"] += 1
            continue
        city, target = parsed
        if not (first <= target <= last):
            counts["skipped_date_outside"] += 1
            continue
        path = folder / "replay_inputs.jsonl"
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                m = local_re.search(line[:4096])
                if not m or datetime.fromisoformat(m.group(1)).hour not in hours:
                    continue
                rec = json.loads(line)
                market = (rec.get("model_identity") or {}).get("market_id")
                if market not in timezones:
                    cities[city] += 1
                    break
                if str(rec.get("target_date"))[:10] != target.isoformat():
                    raise PooledModelError(f"{folder.name}: target_date {rec.get('target_date')} != slug")
                cutoff = datetime.fromisoformat(rec["captured_at_utc"])
                ge = (rec.get("sources") or {}).get("global_ensemble") or {}
                data = ge.get("data") or {}
                counts["snapshots"] += 1
                if not data:
                    counts["snapshots_without_capture"] += 1
                    continue
                highs = ro_member_highs(table, market, target, cutoff, timezones[market])
                members = [v for k, v in highs.items() if k in RO_PERTURBED]
                if len(members) < RO_MIN_MEMBERS:
                    counts["snapshots_without_corpus"] += 1
                    continue
                counts["snapshots_compared"] += 1
                day = target.isoformat()
                stats["p10"].append((market, day, percentile(members, 0.10), data.get("day_member_high_p10")))
                stats["p90"].append((market, day, percentile(members, 0.90), data.get("day_member_high_p90")))
                stats["control"].append((market, day, highs.get("gec00"), data.get("day_max_native")))
    parity = {k: ro_parity_stats(stats[k]) for k in ("p10", "p90", "control")}
    by_market = {k: {m: ro_parity_stats([p for p in stats[k] if p[0] == m]) for m in markets}
                 for k in ("p10", "p90", "control")}
    result = {"rule_sha256": RO_RULE_SHA256, "rung": "R-O", "window": [RO_PARITY_FIRST, RO_PARITY_LAST],
              "hours": list(hours), "counts": dict(counts), "non_us_city_folders_skipped": dict(cities),
              "parity": parity, "by_market": by_market,
              "P_pass": all(v.get("pass") for v in parity.values()),
              "inputs": {"gefs_rows_sha256": hashlib.sha256(
                  (Path(gefs_corpus) / "gefs_member_rows.jsonl").read_bytes()).hexdigest(),
                  "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    (out / "rn_parity.json").write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


RO_RULE_C1_SHA256 = "b25f36cf6e08b4ac69db548163f7f374d5906538224a453f4e5e1f92b075ad24"  # rule_rn.md + Clarification 1
RO_C1_LINK_TOL = 1e-6


def ro_c1_load_capture(capture_csv):
    """{event: {blob: {member: (node_max|None, day_max|None)}}} plus {blob: unit} from the C1 extractor CSV."""
    import csv

    def num(text):
        return float(text) if text not in ("", None) else None

    blobs = defaultdict(lambda: defaultdict(dict))
    units = {}
    with open(capture_csv, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            blobs[row["event"]][row["blob"]][row["member"]] = (num(row["node_max"]), num(row["day_max"]))
            units[row["blob"]] = row["temperature_unit"]
    return blobs, units


def ro_c1_blob_stats(members):
    """(day fingerprint (p10, p90, control), node stats (p10, p90, control) or None) for one blob's member table.

    The day fingerprint mirrors ``model_sources.fetch_global_ensemble``; the node stats mirror P's history side."""
    from weather.model.model_sources import percentile

    perturbed = {k: v for k, v in members.items() if k != "control"}
    day_highs = [v[1] for v in perturbed.values() if v[1] is not None]
    fingerprint = (percentile(day_highs, 0.10), percentile(day_highs, 0.90), (members.get("control") or (None, None))[1])
    node = [v[0] for v in perturbed.values() if v[0] is not None]
    if len(node) < RO_MIN_MEMBERS:
        return fingerprint, None
    return fingerprint, (percentile(node, 0.10), percentile(node, 0.90), (members.get("control") or (None, None))[0])


def _ro_c1_close(a, b):
    return a is not None and b is not None and abs(float(a) - float(b)) <= RO_C1_LINK_TOL


def rung_o_parity_c1(*, inputs_root, gefs_corpus, capture_csv, capture_manifest, out_dir, markets=R0_MARKETS,
                     hours=RUNG_HOURS):
    """R-O precondition P under rule_rn.md Clarification 1: the capture side is recomputed from the capture host's raw
    ensemble payloads (``tools/research/ro_capture_member_extract.py`` CSV) at history's node definition.

    Same snapshot population, window, hours, history side and limits as ``rung_o_parity``. A snapshot's capture value
    comes from the blob(s) of its event that reproduce its captured day p10/p90/control (within 1e-6); unlinked or
    disagreeing snapshots are excluded and counted."""
    import re
    from datetime import date as _date, datetime

    from weather.market.market_registry import spec_for_id
    from weather.model.model_sources import percentile

    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if (out / "rn_parity_c1.json").exists():
        raise PooledModelError(f"refusing to overwrite {out / 'rn_parity_c1.json'}")
    manifest = json.loads(Path(capture_manifest).read_text(encoding="utf-8"))
    csv_sha = hashlib.sha256(Path(capture_csv).read_bytes()).hexdigest()
    if manifest.get("output", {}).get("sha256") != csv_sha:
        raise PooledModelError("capture CSV sha256 does not match its manifest")
    capture, units = ro_c1_load_capture(capture_csv)
    blob_stats = {ev: {b: ro_c1_blob_stats(m) for b, m in blobs.items()} for ev, blobs in capture.items()}
    first, last = _date.fromisoformat(RO_PARITY_FIRST), _date.fromisoformat(RO_PARITY_LAST)
    timezones = {m: spec_for_id(m).timezone for m in markets}
    table = ro_load_gefs(gefs_corpus)
    local_re = re.compile(r'"captured_at_local":\s*"([^"]+)"')
    stats = defaultdict(list)
    counts = defaultdict(int)
    cities = defaultdict(int)
    for folder in sorted(Path(inputs_root).iterdir()):
        parsed = ro_slug_date(folder.name)
        if parsed is None:
            counts["skipped_unparsed_slug"] += 1
            continue
        city, target = parsed
        if not (first <= target <= last):
            counts["skipped_date_outside"] += 1
            continue
        path = folder / "replay_inputs.jsonl"
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                m = local_re.search(line[:4096])
                if not m or datetime.fromisoformat(m.group(1)).hour not in hours:
                    continue
                rec = json.loads(line)
                market = (rec.get("model_identity") or {}).get("market_id")
                if market not in timezones:
                    cities[city] += 1
                    break
                if str(rec.get("target_date"))[:10] != target.isoformat():
                    raise PooledModelError(f"{folder.name}: target_date {rec.get('target_date')} != slug")
                cutoff = datetime.fromisoformat(rec["captured_at_utc"])
                data = (((rec.get("sources") or {}).get("global_ensemble") or {}).get("data")) or {}
                counts["snapshots"] += 1
                if not data:
                    counts["snapshots_without_capture"] += 1
                    continue
                want = (data.get("day_member_high_p10"), data.get("day_member_high_p90"), data.get("day_max_native"))
                linked = [(b, node) for b, (fp, node) in blob_stats.get(folder.name, {}).items()
                          if all(_ro_c1_close(x, y) for x, y in zip(fp, want))]
                if not linked:
                    counts["snapshots_unlinked"] += 1
                    continue
                if any("F" not in str(units.get(b, "")) for b, _ in linked):
                    counts["snapshots_unit_not_fahrenheit"] += 1
                    continue
                nodes = {node for _, node in linked}
                if len(nodes) != 1:
                    counts["snapshots_linked_blobs_disagree"] += 1
                    continue
                node = nodes.pop()
                if node is None:
                    counts["snapshots_capture_below_25_members"] += 1
                    continue
                highs = ro_member_highs(table, market, target, cutoff, timezones[market])
                members = [v for k, v in highs.items() if k in RO_PERTURBED]
                if len(members) < RO_MIN_MEMBERS:
                    counts["snapshots_without_corpus"] += 1
                    continue
                counts["snapshots_compared"] += 1
                counts["linked_blobs_total"] += len(linked)
                day = target.isoformat()
                stats["p10"].append((market, day, percentile(members, 0.10), node[0]))
                stats["p90"].append((market, day, percentile(members, 0.90), node[1]))
                stats["control"].append((market, day, highs.get("gec00"), node[2]))
    parity = {k: ro_parity_stats(stats[k]) for k in ("p10", "p90", "control")}
    by_market = {k: {m: ro_parity_stats([p for p in stats[k] if p[0] == m]) for m in markets}
                 for k in ("p10", "p90", "control")}
    result = {"rule_sha256": RO_RULE_C1_SHA256, "rule_original_sha256": RO_RULE_SHA256, "rung": "R-O",
              "clarification": 1, "window": [RO_PARITY_FIRST, RO_PARITY_LAST], "hours": list(hours),
              "counts": dict(counts), "non_us_city_folders_skipped": dict(cities), "parity": parity,
              "by_market": by_market, "P_pass": all(v.get("pass") for v in parity.values()),
              "inputs": {"gefs_rows_sha256": hashlib.sha256(
                  (Path(gefs_corpus) / "gefs_member_rows.jsonl").read_bytes()).hexdigest(),
                  "capture_csv_sha256": csv_sha,
                  "capture_manifest_sha256": hashlib.sha256(Path(capture_manifest).read_bytes()).hexdigest(),
                  "extractor_script_sha256": manifest.get("script_sha256"),
                  "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    (out / "rn_parity_c1.json").write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


def ro_row_shifts(diff):
    """Shift for every (a, b) pair at one row with d = G - N (all 0 when d is missing)."""
    import numpy as np

    if diff is None or not math.isfinite(diff):
        return np.zeros(len(RO_PAIRS))
    return np.array([a + b * diff for a, b in RO_PAIRS])


def ro_loyo(frame, buckets, gvals, hours=RUNG_HOURS):
    """Gate 1: strictly nested LOYO of (a_h, b_h) pooled over markets per hour, on P3d_N_fix (2021-25 Aug-Sep)."""
    import numpy as np

    from weather.calibration import feature_model as fm

    inner = defaultdict(lambda: np.zeros(len(RO_PAIRS)))
    outer = []
    for hour in hours:
        at_hour = frame[frame["hour"] == hour]
        years = sorted(int(y) for y in at_hour["year"].unique())

        def predict(train_years, target_year):
            train = at_hour[at_hour["year"].isin(train_years)].reset_index(drop=True)
            val = at_hour[at_hour["year"] == target_year].reset_index(drop=True)
            entry = _rung_entry(train, *_arm_spec(RUNG_ARMS["P3d_N_fix"]))
            out = []
            for market in sorted(val["market"].unique()):
                part = val[val["market"] == market].reset_index(drop=True)
                for i, dist in enumerate(_dist_from_fit(entry, part, buckets, market)):
                    day = str(part.at[i, "target_date"])[:10]
                    g = gvals.get((market, day, int(hour)))
                    n = float(part.at[i, "fh"])
                    diff = (g - n) if (g is not None and math.isfinite(n)) else None
                    out.append((market, day, dist, int(part.at[i, "y"]), float(part.at[i, "F"]), diff))
            return out

        for held in years:
            for x in years:
                if x == held:
                    continue
                for market, _, dist, a, floor, diff in predict([y for y in years if y not in (x, held)], x):
                    shifts = ro_row_shifts(diff)
                    inner[(held, hour)] += rm_loyo_losses(dist, a, floor, shifts=tuple([0.0] + list(shifts)))[1:]
            for market, day, dist, a, floor, diff in predict([y for y in years if y != held], held):
                outer.append({"hour": int(hour), "year": int(held), "market": market, "date": day, "dist": dist,
                              "actual": a, "floor": floor, "diff": diff, "raw_brier": float(fm.brier_score(dist, a)),
                              "actual_in_keys": a in dist})
        print(f"ro loyo h{hour:02d}: {sum(1 for r in outer if r['hour'] == hour)} rows", flush=True)
    coefs = {}
    for (held, hour), loss in sorted(inner.items()):
        a, b = ro_pick(loss)
        i = RO_PAIRS.index((a, b))
        coefs[(held, hour)] = {"a": a, "b": b, "inner_brier_noshift": float(loss[RO_ZERO]),
                               "inner_brier_shift": float(loss[i]),
                               "training_score_not_worse": bool(loss[i] <= loss[RO_ZERO] + 1e-12)}
    rows = []
    for r in outer:
        c = coefs[(r["year"], r["hour"])]
        s = 0.0 if r["diff"] is None else c["a"] + c["b"] * r["diff"]
        loss = rm_loyo_losses(r["dist"], r["actual"], r["floor"], shifts=(0.0, s))
        rows.append({"hour": r["hour"], "year": r["year"], "market": r["market"], "date": r["date"], "shift": s,
                     "gefs_minus_anchor": r["diff"], "P3d_N_fix_brier": r["raw_brier"],
                     "noshift_brier": float(loss[0]), "shift_brier": float(loss[1]),
                     "actual_in_keys": r["actual_in_keys"]})
    return rows, coefs


def rung_o_loyo(*, records_root, nbm_train_corpus, ra_loyo_rows, gefs_corpus, out_dir, markets=R0_MARKETS,
                hours=RUNG_HOURS):
    """R-O gate 1 (rule_rn.md, rung R-O): nested LOYO of the GEFS member-mean centre shift, R-A control reproduced."""
    from weather.calibration import ols_floor_ladder as l9
    from weather.market.market_registry import spec_for_id

    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name in ("rn_loyo.json", "rn_loyo_rows.jsonl"):
        if (out / name).exists():
            raise PooledModelError(f"refusing to overwrite {out / name}")
    for path, want in ((nbm_train_corpus, RM_NBM_TRAIN_SHA256), (ra_loyo_rows, RM_RA_LOYO_SHA256)):
        got = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if got != want:
            raise PooledModelError(f"{path} sha {got} != {want}")
    manifest = json.loads((Path(gefs_corpus) / "manifest.json").read_text(encoding="utf-8"))
    rows_sha = hashlib.sha256((Path(gefs_corpus) / "gefs_member_rows.jsonl").read_bytes()).hexdigest()
    if manifest.get("rows_sha256") != rows_sha:
        raise PooledModelError("GEFS corpus rows do not match their manifest")
    timezones = {m: spec_for_id(m).timezone for m in markets}
    frame, buckets = dev_training_frame(records_root, markets)
    if frame["year"].max() >= 2026:
        raise PooledModelError("a dev training row is from 2026")
    frame, train_stats = attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff, timezones)
    frame = frame[frame["hour"].isin(hours)].reset_index(drop=True)
    table = ro_load_gefs(gefs_corpus)
    gvals, cover = {}, defaultdict(int)
    for market, day, hour in zip(frame["market"], frame["target_date"], frame["hour"]):
        key = (market, str(day)[:10], int(hour))
        if key not in gvals:
            gvals[key] = ro_gefs_value(table, market, key[1], key[2], timezones[market])
            cover["with_gefs" if gvals[key] is not None else "without_gefs"] += 1
    rows, coefs = ro_loyo(frame, buckets, gvals, hours)
    ra = {}
    with open(ra_loyo_rows, encoding="utf-8") as handle:
        for line in handle:
            r = json.loads(line)
            ra[(r["hour"], r["market"], r["date"])] = r["P3d_N_fix_brier"]
    worst = max(abs(r["P3d_N_fix_brier"] - ra[(r["hour"], r["market"], r["date"])]) for r in rows)
    if len(ra) != len(rows) or worst > 1e-9:
        raise PooledModelError(f"R-A LOYO control failed: rows {len(rows)} vs {len(ra)}, max diff {worst}")
    if not all(v["training_score_not_worse"] for v in coefs.values()):
        raise PooledModelError("a fitted (a, b) worsened its own training score")
    _write_jsonl(out / "rn_loyo_rows.jsonl", rows)
    summary = rm_loyo_summary(rows)
    diffs = [r["gefs_minus_anchor"] for r in rows if r["gefs_minus_anchor"] is not None]
    result = {"rule_sha256": RO_RULE_SHA256, "rung": "R-O", "train_nbm": train_stats,
              "grid": {"a": [RO_A[0], RO_A[-1], 0.1], "b": [RO_B[0], RO_B[-1], 0.05]},
              "coverage": {"rows": len(rows), "rows_with_gefs": len(diffs), "keys": dict(cover)},
              "gefs_minus_anchor": {"mean": float(sum(diffs) / len(diffs)) if diffs else None,
                                    "mean_abs": float(sum(map(abs, diffs)) / len(diffs)) if diffs else None},
              "controls": {"ra_loyo_rows": len(ra), "ra_max_abs_diff": worst, "training_score_not_worse_all": True,
                           "rows_actual_not_a_pmf_key": int(sum(not r["actual_in_keys"] for r in rows))},
              "coefficients": {f"{y}|h{h:02d}": v for (y, h), v in sorted(coefs.items())},
              "summary": summary, "gate1_pass": summary["07-12"]["ci95"][1] < 0,
              "inputs": {"nbm_train_corpus": RM_NBM_TRAIN_SHA256, "ra_loyo_rows": RM_RA_LOYO_SHA256,
                         "gefs_rows_sha256": rows_sha, "gefs_manifest_module_sha256": manifest.get("module_sha256"),
                         "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    (out / "rn_loyo.json").write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


def _parse(argv=None):
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.pooled_residual_model",
                                     description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract", help="trainer records for markets x centres (heavy)")
    ex.add_argument("--markets", default=",".join(R0_MARKETS))
    ex.add_argument("--centres", default=VALIDATION_CENTRE)
    ex.add_argument("--manifest", action="append", required=True, dest="manifests")
    ex.add_argument("--coverage-years", action="store_true",
                    help="amendment 4: per centre, only the years the corpora fully cover")
    ex.add_argument("--out", required=True)
    ev = sub.add_parser("evaluate", help="R0 and pooled arms on identical rows (heavy)")
    ev.add_argument("--records", required=True)
    ev.add_argument("--arms", default="R0,P0,P1")
    ev.add_argument("--markets", default=",".join(R0_MARKETS))
    ev.add_argument("--hours", default=None, help="comma list (smoke slices only)")
    ev.add_argument("--lane-d-root", default=None)
    ev.add_argument("--extract-augsep-manifest", default=None,
                    help="first extract missing Aug-Sep centres from this manifest (fail-closed gaps skipped)")
    ev.add_argument("--l3-manifest", action="append", default=None, dest="l3_manifests",
                    help="with arm L3: the Oct-Dec manifests for lane L3's score_market")
    ev.add_argument("--out", required=True)
    hl = sub.add_parser("headline", help="amendment 2: P3 vs L3's (a) and (f), U0, fair comparators")
    hl.add_argument("--rows", action="append", required=True, help="row directories (searched in order)")
    hl.add_argument("--lane-d-floor-root", default=None)
    hl.add_argument("--arm", default="P3", choices=("P3", "P3F"))
    hl.add_argument("--rule", required=True)
    hl.add_argument("--out", required=True)
    de = sub.add_parser("dev-emit", help="amendment 3: P3d/U0d dev-window distributions (heavy)")
    de.add_argument("--records", required=True)
    de.add_argument("--layout", required=True)
    de.add_argument("--replay-root", required=True)
    de.add_argument("--dev-manifest", required=True)
    de.add_argument("--markets", default=",".join(R0_MARKETS))
    de.add_argument("--out", required=True)
    dn = sub.add_parser("dev-emit-n", help="amendment 5: P3d_N dev distributions on the captured NBM mean (heavy)")
    dn.add_argument("--records", required=True)
    dn.add_argument("--layout", required=True)
    dn.add_argument("--replay-root", required=True)
    dn.add_argument("--nbm-train-corpus", required=True, help="lane L9's PIT NBM corpus rows (2021-25)")
    dn.add_argument("--nbm-dev-corpus", required=True, help="the 2026 NBM corpus rows (cross-check only)")
    dn.add_argument("--markets", default=",".join(R0_MARKETS))
    dn.add_argument("--out", required=True)
    ru = sub.add_parser("dev-emit-rung", help="rung 07-12: B_N and P3d_N_fix dev distributions + LOYO (heavy)")
    ru.add_argument("--records", required=True)
    ru.add_argument("--layout", required=True)
    ru.add_argument("--replay-root", required=True)
    ru.add_argument("--nbm-train-corpus", required=True)
    ru.add_argument("--markets", default=",".join(R0_MARKETS))
    ru.add_argument("--no-loyo", action="store_true")
    ru.add_argument("--hours", default=",".join(str(h) for h in RUNG_HOURS), help="cutoff hours (R-H: 13,14,15,16)")
    ru.add_argument("--out", required=True)
    rb = sub.add_parser("rung-blend", help="rung 07-12 R-D walk-forward MG-1 blend + R-E decomposition (heavy)")
    rb.add_argument("--layout", required=True)
    rb.add_argument("--fix", required=True, help="dev_P3d_N_fix.jsonl")
    rb.add_argument("--bn", required=True, help="dev_B_N.jsonl")
    rb.add_argument("--out", required=True)
    rf = sub.add_parser("rung-rf", help="rung 07-12 R-F: blends vs the MG-2 pre-13 arm MG-1 + L6 (heavy)")
    rf.add_argument("--layout", required=True)
    rf.add_argument("--fix", required=True, help="dev_P3d_N_fix.jsonl")
    rf.add_argument("--bn", required=True, help="dev_B_N.jsonl")
    rf.add_argument("--coefficients", required=True, help="frozen MG-2 coefficients JSON (part l6_stack)")
    rf.add_argument("--nowcasts", required=True, help="L6 nowcast parquet")
    rf.add_argument("--rd-result", required=True, help="R-D rung_blend.json (positive control)")
    rf.add_argument("--out", required=True)
    ge = sub.add_parser("rung-g-emit", help="rung 07-12 R-G gates 1-2 and dev distributions (heavy)")
    ge.add_argument("--records", required=True)
    ge.add_argument("--layout", required=True)
    ge.add_argument("--replay-root", required=True)
    ge.add_argument("--nbm-train-corpus", required=True)
    ge.add_argument("--obs-parquet", required=True, help="lane L6 IEM market-station parquet")
    ge.add_argument("--ra-emit", required=True, help="R-A emit directory (B_N / P3d_N_fix reproduction)")
    ge.add_argument("--out", required=True)
    gs = sub.add_parser("rung-g-score", help="rung 07-12 R-G gates 3-4 on the dev scorecard (heavy)")
    gs.add_argument("--layout", required=True)
    gs.add_argument("--emit", required=True)
    gs.add_argument("--coefficients", required=True)
    gs.add_argument("--nowcasts", required=True)
    gs.add_argument("--rf-result", required=True)
    gs.add_argument("--out", required=True)
    ht = sub.add_parser("rh-tags", help="R-H regime tags from captured obs and forecasts (heavy)")
    ht.add_argument("--layout", required=True)
    ht.add_argument("--replay-root", required=True)
    ht.add_argument("--obs-parquet", required=True, help="lane L6 IEM parquet (2021-25 diurnal fractions only)")
    ht.add_argument("--out", required=True)
    ha = sub.add_parser("rh-atlas", help="R-H market-relative loss atlas, selection evidence (heavy)")
    ha.add_argument("--layout", required=True)
    ha.add_argument("--p3d", required=True, help="comma-separated dev_P3d_N_fix.jsonl files (07-12, 13-16)")
    ha.add_argument("--coefficients", required=True)
    ha.add_argument("--nowcasts", required=True)
    ha.add_argument("--tags", required=True)
    ha.add_argument("--out", required=True)
    il = sub.add_parser("rung-i-loyo", help="R-I gate 1: nested LOYO per-hour temperature on P3d_N_fix (heavy)")
    il.add_argument("--records", required=True)
    il.add_argument("--nbm-train-corpus", required=True)
    il.add_argument("--ra-loyo-rows", required=True, help="R-A loyo_rows.jsonl (positive control)")
    il.add_argument("--out", required=True)
    isc = sub.add_parser("rung-i-score", help="R-I gates 2-3 and the alternative reading (heavy)")
    isc.add_argument("--layout", required=True)
    isc.add_argument("--fix", required=True)
    isc.add_argument("--coefficients", required=True)
    isc.add_argument("--nowcasts", required=True)
    isc.add_argument("--loyo-result", required=True)
    isc.add_argument("--out", required=True)
    op = sub.add_parser("rung-o-parity", help="R-O precondition P: corpus vs captured GEFS p10/p90/control (heavy)")
    op.add_argument("--inputs", required=True)
    op.add_argument("--gefs-corpus", required=True)
    op.add_argument("--out", required=True)
    oc = sub.add_parser("rung-o-parity-c1",
                        help="R-O precondition P under Clarification 1: corpus vs host-extracted node maxima (heavy)")
    oc.add_argument("--inputs", required=True)
    oc.add_argument("--gefs-corpus", required=True)
    oc.add_argument("--capture-csv", required=True)
    oc.add_argument("--capture-manifest", required=True)
    oc.add_argument("--out", required=True)
    ol = sub.add_parser("rung-o-loyo", help="R-O gate 1: nested LOYO GEFS member-mean centre shift (heavy)")
    ol.add_argument("--records", required=True)
    ol.add_argument("--nbm-train-corpus", required=True)
    ol.add_argument("--ra-loyo-rows", required=True)
    ol.add_argument("--gefs-corpus", required=True)
    ol.add_argument("--out", required=True)
    ml = sub.add_parser("rung-m-loyo", help="R-M gate 1: nested LOYO per-market centre shift (heavy)")
    ml.add_argument("--records", required=True)
    ml.add_argument("--nbm-train-corpus", required=True)
    ml.add_argument("--ra-loyo-rows", required=True)
    ml.add_argument("--out", required=True)
    msc = sub.add_parser("rung-m-score", help="R-M gates 2-3 (heavy)")
    msc.add_argument("--layout", required=True)
    msc.add_argument("--fix", required=True)
    msc.add_argument("--coefficients", required=True)
    msc.add_argument("--nowcasts", required=True)
    msc.add_argument("--loyo-result", required=True)
    msc.add_argument("--out", required=True)
    je = sub.add_parser("rung-j-emit", help="R-J gates 1-2 and h13-16 dev distributions (heavy)")
    je.add_argument("--records", required=True)
    je.add_argument("--layout", required=True)
    je.add_argument("--replay-root", required=True)
    je.add_argument("--nbm-train-corpus", required=True)
    je.add_argument("--obs-parquet", required=True)
    je.add_argument("--rh-emit", required=True, help="R-H 13-16 emit directory (B_N / P3d_N_fix reproduction)")
    je.add_argument("--out", required=True)
    js = sub.add_parser("rung-j-score", help="R-J gates 3-4 on the dev scorecard (heavy)")
    js.add_argument("--layout", required=True)
    js.add_argument("--emit", required=True)
    js.add_argument("--p3d-n", required=True, help="dev_P3d_N.jsonl (composite post-13 dev arm)")
    js.add_argument("--out", required=True)
    ka = sub.add_parser("rk-hrrr-audit", help="R-K: HRRR corpus schema and coverage audit (inputs only)")
    ka.add_argument("--hrrr", required=True, help="L13 HRRR corpus directory")
    ka.add_argument("--out", required=True)
    kl = sub.add_parser("rung-k-loyo", help="R-K gate 1 (training half) and gate 2 LOYO (heavy)")
    kl.add_argument("--records", required=True)
    kl.add_argument("--nbm-train-corpus", required=True)
    kl.add_argument("--hrrr", required=True, help="L13 HRRR corpus directory (2021-25)")
    kl.add_argument("--rj-loyo-rows", required=True, help="R-J loyo_rows.jsonl (incumbent-arm control)")
    kl.add_argument("--out", required=True)
    de = sub.add_parser("p3dn-diag-emit", help="P3d_N vs P3d_N_fix input diff and variant emissions (heavy)")
    de.add_argument("--records", required=True)
    de.add_argument("--layout", required=True)
    de.add_argument("--replay-root", required=True)
    de.add_argument("--nbm-train-corpus", required=True)
    de.add_argument("--rh-fix", required=True, help="R-H dev_P3d_N_fix.jsonl (13-16)")
    de.add_argument("--p3d-n", required=True, help="dev_P3d_N.jsonl (721ae2cd)")
    de.add_argument("--out", required=True)
    ds = sub.add_parser("p3dn-diag-score", help="P3d_N vs P3d_N_fix attribution, composite and pick re-score (heavy)")
    ds.add_argument("--layout", required=True)
    ds.add_argument("--diag", required=True)
    ds.add_argument("--p3d-n", required=True)
    ds.add_argument("--v3-vectors", required=True, help="MG-2 control_v3 mg2_vectors.parquet")
    ds.add_argument("--a-n", required=True, help="MG-2 pick arm A (A_N) dev distributions")
    ds.add_argument("--arm-a", required=True, help="MG-2 dev_composite arm A distributions (control)")
    ds.add_argument("--coefficients", required=True)
    ds.add_argument("--nowcasts", required=True)
    ds.add_argument("--out", required=True)
    wr = sub.add_parser("wu-rounding", help="clarification 3 (c): WU whole F vs T-group F on 2021-25 rows (heavy)")
    wr.add_argument("--obs-parquet", required=True, help="IEM market-station rows with tgroup_f (lane L6)")
    wr.add_argument("--wu-root", required=True)
    wr.add_argument("--out", required=True)
    rg = sub.add_parser("receipt-grace", help="clarification 3 (d): capture-only receipt check per grace (heavy)")
    rg.add_argument("--replay-root", required=True)
    rg.add_argument("--out", required=True)
    ff = sub.add_parser("forward-fit", help="clarification 3: Aug-Dec 2021-25 P3d_N refit, frozen L8 state (heavy)")
    ff.add_argument("--records", required=True)
    ff.add_argument("--nbm-train-corpus", required=True)
    ff.add_argument("--rounding-rule", required=True, choices=WU_ROUNDING_CANDIDATES)
    ff.add_argument("--late-rule", required=True, choices=("last_in_hour", "receipt_by"))
    ff.add_argument("--grace-minutes", type=int, default=None)
    ff.add_argument("--commit", required=True)
    ff.add_argument("--input", action="append", default=[], help="name=sha256 provenance entries")
    ff.add_argument("--out", required=True)
    dv = sub.add_parser("dev-verdict", help="amendment 3: verdict and tables from L3 dev-score output")
    dv.add_argument("--scores", required=True)
    dv.add_argument("--rule", required=True)
    dv.add_argument("--out", required=True)
    rp = sub.add_parser("report", help="paired deltas, CIs and the pre-declared decision")
    rp.add_argument("--rows", required=True)
    rp.add_argument("--arms", default="P0,P1,P2,P3")
    rp.add_argument("--rule", required=True)
    rp.add_argument("--out", required=True)
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse(argv)
    if args.command == "extract":
        failed = extract_many(args.markets.split(","), args.centres.split(","), args.manifests, args.out,
                              coverage_years=args.coverage_years)
        return 1 if failed else 0
    out = require_output_outside_repo(args.out)
    if args.command == "evaluate":
        out.mkdir(parents=True, exist_ok=True)
        markets = args.markets.split(",")
        arms = args.arms.split(",")
        hours = [int(h) for h in args.hours.split(",")] if args.hours else None
        if args.extract_augsep_manifest:
            extract_many(markets, AUG_SEP_CENTRES, [args.extract_augsep_manifest], args.records)
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
        if "L3" in arms:
            if not args.l3_manifests:
                raise PooledModelError("arm L3 needs --l3-manifest")
            l3_rows, metas = score_l3_comparators(markets, args.l3_manifests)
            _write_jsonl(out / "rows_L3.jsonl", l3_rows)
            (out / "l3_meta.json").write_text(json.dumps(metas, indent=1, default=str), encoding="utf-8")
        pooled = [a for a in arms if a in ALL_POOLED_ARMS]
        if pooled:
            wanted = sorted({c for a in pooled for c in ALL_POOLED_ARMS[a]["centres"]})
            centres, dropped = complete_centres(args.records, markets, wanted)
            if VALIDATION_CENTRE not in centres:
                raise PooledModelError("the validation centre is incomplete")
            (out / "centres.json").write_text(json.dumps({"used": centres, "dropped": dropped}), encoding="utf-8")
            print(f"centres used {centres}; dropped (incomplete) {dropped}", flush=True)
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
    if args.command == "dev-emit":
        audit = dev_emit_distributions(records_root=args.records, layout=args.layout, replay_root=args.replay_root,
                                       dev_manifest=args.dev_manifest, out_dir=args.out,
                                       markets=args.markets.split(","))
        print(json.dumps(audit["files"], indent=1))
        return 0
    if args.command == "dev-emit-n":
        audit = dev_emit_n_distributions(records_root=args.records, layout=args.layout, replay_root=args.replay_root,
                                         nbm_train_corpus=args.nbm_train_corpus, nbm_dev_corpus=args.nbm_dev_corpus,
                                         out_dir=args.out, markets=args.markets.split(","))
        print(json.dumps(audit["files"], indent=1))
        return 0
    if args.command == "rung-g-emit":
        audit = rung_g_emit(records_root=args.records, layout=args.layout, replay_root=args.replay_root,
                            nbm_train_corpus=args.nbm_train_corpus, obs_parquet=args.obs_parquet,
                            ra_emit_dir=args.ra_emit, out_dir=args.out)
        print(json.dumps({"gates": {k: v.get("pass") for k, v in audit["gates"].items()},
                          "stopped_at": audit.get("stopped_at"), "ra_reproduction": audit.get("ra_reproduction")}))
        return 0
    if args.command == "rh-tags":
        audit = rh_tags(layout=args.layout, replay_root=args.replay_root, obs_parquet=args.obs_parquet,
                        out_path=Path(args.out))
        print(json.dumps(audit, indent=1, sort_keys=True))
        return 0
    if args.command == "rh-atlas":
        result = rh_atlas(layout=args.layout, p3d_files=[Path(f) for f in args.p3d.split(",")],
                          coefficients=args.coefficients, nowcasts=args.nowcasts, tags_path=args.tags,
                          out_path=Path(args.out))
        print(json.dumps({"controls": result["controls"], "population": result["population"]}, indent=1))
        return 0
    if args.command == "rung-i-loyo":
        result = rung_i_loyo(records_root=args.records, nbm_train_corpus=args.nbm_train_corpus,
                             ra_loyo_rows=args.ra_loyo_rows, out_dir=args.out)
        print(json.dumps({"gate1_pass": result["gate1_pass"], "summary": result["summary"],
                          "controls": result["controls"]}, indent=1))
        return 0
    if args.command == "rung-i-score":
        result = rung_i_score(layout=args.layout, fix_jsonl=args.fix, coefficients=args.coefficients,
                              nowcasts=args.nowcasts, loyo_result=args.loyo_result, out_path=Path(args.out))
        print(json.dumps({"gates": result["gates"], "stopped_at": result.get("stopped_at")}, indent=1))
        return 0
    if args.command == "rung-o-parity":
        result = rung_o_parity(inputs_root=args.inputs, gefs_corpus=args.gefs_corpus, out_dir=args.out)
        print(json.dumps({"P_pass": result["P_pass"], "parity": result["parity"], "counts": result["counts"]}))
        return 0
    if args.command == "rung-o-parity-c1":
        result = rung_o_parity_c1(inputs_root=args.inputs, gefs_corpus=args.gefs_corpus, capture_csv=args.capture_csv,
                                  capture_manifest=args.capture_manifest, out_dir=args.out)
        print(json.dumps({"P_pass": result["P_pass"], "parity": result["parity"], "counts": result["counts"]}))
        return 0
    if args.command == "rung-o-loyo":
        result = rung_o_loyo(records_root=args.records, nbm_train_corpus=args.nbm_train_corpus,
                             ra_loyo_rows=args.ra_loyo_rows, gefs_corpus=args.gefs_corpus, out_dir=args.out)
        print(json.dumps({"gate1_pass": result["gate1_pass"], "07-12": result["summary"]["07-12"]}))
        return 0
    if args.command == "rung-m-loyo":
        result = rung_m_loyo(records_root=args.records, nbm_train_corpus=args.nbm_train_corpus,
                             ra_loyo_rows=args.ra_loyo_rows, out_dir=args.out)
        print(json.dumps({"gate1_pass": result["gate1_pass"], "07-12": result["summary"]["07-12"]}))
        return 0
    if args.command == "rung-m-score":
        result = rung_m_score(layout=args.layout, fix_jsonl=args.fix, coefficients=args.coefficients,
                              nowcasts=args.nowcasts, loyo_result=args.loyo_result, out_path=args.out)
        print(json.dumps({"gates": result["gates"], "kill": result["kill"]}))
        return 0
    if args.command == "rung-j-emit":
        audit = rung_g_emit(records_root=args.records, layout=args.layout, replay_root=args.replay_root,
                            nbm_train_corpus=args.nbm_train_corpus, obs_parquet=args.obs_parquet,
                            ra_emit_dir=args.rh_emit, out_dir=args.out, hours=RJ_HOURS, gate=RJ_GATE,
                            report_pools=(RJ_SECONDARY,), rule_sha=RJ_RULE_SHA256)
        print(json.dumps({"gates": {k: v.get("pass") for k, v in audit["gates"].items()},
                          "stopped_at": audit.get("stopped_at"), "ra_reproduction": audit.get("ra_reproduction")}))
        return 0
    if args.command == "rk-hrrr-audit":
        result = rk_hrrr_audit(hrrr_corpus=args.hrrr, out_path=Path(args.out))
        print(json.dumps({"per_hour": result["per_hour"], "reasons": result["reasons"]}, indent=1))
        return 0
    if args.command == "rung-k-loyo":
        audit = rung_k_loyo(records_root=args.records, nbm_train_corpus=args.nbm_train_corpus, hrrr_corpus=args.hrrr,
                            rj_loyo_rows=args.rj_loyo_rows, out_dir=args.out)
        print(json.dumps({"gates": {k: v.get("pass") for k, v in audit["gates"].items()},
                          "stopped_at": audit.get("stopped_at"),
                          "control": audit.get("control_rj_reproduction")}, indent=1))
        return 0
    if args.command == "p3dn-diag-emit":
        audit = p3dn_diag_emit(records_root=args.records, layout=args.layout, replay_root=args.replay_root,
                               nbm_train_corpus=args.nbm_train_corpus, out_dir=args.out, rh_fix_jsonl=args.rh_fix,
                               p3d_n_jsonl=args.p3d_n)
        print(json.dumps({"controls": audit["controls"], "stats": audit["stats"]}, indent=1))
        return 0
    if args.command == "p3dn-diag-score":
        result = p3dn_diag_score(layout=args.layout, diag_dir=args.diag, p3d_n_jsonl=args.p3d_n,
                                 v3_vectors=args.v3_vectors, a_n_jsonl=args.a_n, arm_a_jsonl=args.arm_a,
                                 coefficients=args.coefficients, nowcasts=args.nowcasts, out_path=Path(args.out))
        print(json.dumps(result["controls"], indent=1, default=float))
        return 0
    if args.command == "rung-j-score":
        result = rung_j_score(layout=args.layout, emit_dir=args.emit, p3d_n_jsonl=args.p3d_n, out_path=Path(args.out))
        print(json.dumps({"gates": result["gates"], "stopped_at": result.get("stopped_at")}, indent=1))
        return 0
    if args.command == "rung-g-score":
        result = rung_g_score(layout=args.layout, emit_dir=args.emit, coefficients=args.coefficients,
                              nowcasts=args.nowcasts, rf_result=args.rf_result, out_path=args.out)
        print(json.dumps({"gates": result["gates"], "stopped_at": result.get("stopped_at")}, indent=1))
        return 0
    if args.command == "rung-rf":
        result = rung_rf(layout=args.layout, fix_jsonl=args.fix, bn_jsonl=args.bn, coefficients=args.coefficients,
                         nowcasts=args.nowcasts, rd_result=args.rd_result, out_path=args.out)
        print(json.dumps({"controls": result["controls"], "weights": result["weights"]}, indent=1))
        return 0
    if args.command == "rung-blend":
        result = rung_blend(layout=args.layout, fix_jsonl=args.fix, bn_jsonl=args.bn, out_path=args.out)
        print(json.dumps(result["weights"], indent=1))
        return 0
    if args.command == "dev-emit-rung":
        audit = dev_emit_rung(records_root=args.records, layout=args.layout, replay_root=args.replay_root,
                              nbm_train_corpus=args.nbm_train_corpus, out_dir=args.out,
                              markets=args.markets.split(","), loyo=not args.no_loyo,
                              hours=tuple(int(h) for h in args.hours.split(",")))
        print(json.dumps({"files": audit["files"], "loyo": audit.get("loyo")}, indent=1))
        return 0
    if args.command in ("wu-rounding", "receipt-grace"):
        if out.exists():
            raise PooledModelError(f"refusing to overwrite {out}")
        if args.command == "wu-rounding":
            result = wu_rounding_parity(obs_parquet=args.obs_parquet, wu_root=args.wu_root)
        else:
            result = receipt_grace_check(replay_root=args.replay_root)
        out.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
        print(json.dumps(result["ALL"], indent=1, sort_keys=True))
        return 0
    if args.command == "forward-fit":
        inputs = dict(item.split("=", 1) for item in args.input)
        _, digest = forward_fit(records_root=args.records, nbm_train_corpus=args.nbm_train_corpus, out_dir=args.out,
                                rounding_rule=args.rounding_rule, commit=args.commit, input_shas=inputs,
                                late_report={"rule": args.late_rule, "grace_minutes": args.grace_minutes})
        print(json.dumps({"state_sha256": digest}))
        return 0
    if args.command == "dev-verdict":
        scores = json.loads(Path(args.scores).read_text(encoding="utf-8"))
        text, _ = dev_verdict_markdown(scores, args.rule)
        if out.exists():
            raise PooledModelError(f"refusing to overwrite {out}")
        out.write_text(text, encoding="utf-8")
        print(text)
        return 0
    if args.command == "headline":
        rows, gate = headline_rows(args.rows, args.lane_d_floor_root, arm=args.arm,
                                   extra=("U0",) if args.arm == "P3" else ())
        text = headline_markdown(rows, args.rule, gate, head=args.arm)
        if out.exists():
            raise PooledModelError(f"refusing to overwrite {out}")
        out.write_text(text, encoding="utf-8")
        print(text)
        return 0
    if args.command == "report":
        rows_dir = Path(args.rows)
        arms = args.arms.split(",")
        r0 = _read_jsonl(rows_dir / "rows_R0.jsonl")
        arm_rows = {a: _read_jsonl(rows_dir / f"rows_{a}.jsonl") for a in arms}
        rows = merge_rows(r0, arm_rows)
        text, verdicts, pick = report_markdown(rows, arms, args.rule)
        centres_file = rows_dir / "centres.json"
        if centres_file.is_file():
            text += f"\nCentres used / dropped (rule amendment): {centres_file.read_text(encoding='utf-8')}\n"
        parity_file = rows_dir / "r0_parity.json"
        if parity_file.is_file():
            text += f"\nR0 parity against lane D rows: {parity_file.read_text(encoding='utf-8')}\n"
        if out.exists():
            raise PooledModelError(f"refusing to overwrite {out}")
        out.write_text(text, encoding="utf-8")
        print(text)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
