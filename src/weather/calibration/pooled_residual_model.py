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
import re
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
               extra_hgb=(), extra_scale=()):
    """Mean model on all training rows plus an inner-LOYO scale model and z set.

    ``simple`` (rung 07-12 baseline B_N): OLS on [1, g, max(g, 0)] only (no HGB residual) and a constant
    scale, so mean = nbm_mean + bias + OLS; z = errors / that constant scale.
    ``extra_scale`` (R-S, rule_rs.md condition 1): columns appended to the scale HGB's input only; the mean model
    is untouched. The fit then also carries ``gs_ratio`` = s_new / s_old on the training rows, where s_old is the
    scale model without the columns on the same OOF errors (guard G-s).
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
        if extra_scale:
            raise PooledModelError("extra_scale needs the HGB scale model (simple=False)")
        scale = ConstantScale(np.nanmean(np.abs(errors)))
        s_train = max(MIN_SCALE, scale.value * math.sqrt(math.pi / 2))
        return {"mean": mean, "scale": scale, "z": errors / s_train}
    X, _, _ = mean.features(train)
    yhat_oof = train["y"].to_numpy(float) - errors
    floor_gap = np.nan_to_num(yhat_oof - train["F"].to_numpy(float), nan=0.0)
    scale = HistGradientBoostingRegressor(**SCALE_HGB_PARAMS)
    if not extra_scale:
        scale.fit(np.column_stack([X, floor_gap]), np.abs(errors))
        s_train = np.maximum(MIN_SCALE, scale.predict(np.column_stack([X, floor_gap])) * math.sqrt(math.pi / 2))
        return {"mean": mean, "scale": scale, "z": errors / s_train}
    base_in = np.column_stack([X, floor_gap])
    s_in = np.column_stack([base_in] + [train[c].to_numpy(float) for c in extra_scale])
    scale.fit(s_in, np.abs(errors))
    s_train = np.maximum(MIN_SCALE, scale.predict(s_in) * math.sqrt(math.pi / 2))
    base = HistGradientBoostingRegressor(**SCALE_HGB_PARAMS).fit(base_in, np.abs(errors))
    s_old = np.maximum(MIN_SCALE, base.predict(base_in) * math.sqrt(math.pi / 2))
    return {"mean": mean, "scale": scale, "z": errors / s_train, "extra_scale": tuple(extra_scale),
            "gs_ratio": s_train / s_old}


def _scale_input(fitted, X, gap, frame):
    """The scale model's input: [X, floor gap] plus any R-S ``extra_scale`` columns of ``frame``."""
    import numpy as np

    extra = fitted.get("extra_scale", ())
    return np.column_stack([X, gap] + [frame[c].to_numpy(float) for c in extra])


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
    """RUNG arm value -> (simple, extra_ols, extra_hgb, extra_scale); a bare bool is the R-A form."""
    if isinstance(spec, bool):
        return spec, (), (), ()
    return (bool(spec["simple"]), tuple(spec.get("extra_ols", ())), tuple(spec.get("extra_hgb", ())),
            tuple(spec.get("extra_scale", ())))


def _rung_entry(train, simple, extra_ols=(), extra_hgb=(), extra_scale=()):
    return {"fit": fit_pooled(train, market_id=False, doy=True, raw_columns=False, simple=simple,
                              extra_ols=extra_ols, extra_hgb=extra_hgb, extra_scale=extra_scale),
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
    s = np.maximum(MIN_SCALE, fitted["scale"].predict(_scale_input(fitted, X, gap, one)) * math.sqrt(math.pi / 2))
    p_clim = fm.smoothed_dist(entry["train_y"][market], buckets[market], alpha=0.10)
    return [predictive_distribution(float(yhat[i]), float(s[i]), float(one["F"].iat[i]), fitted["z"],
                                    buckets[market], p_clim) for i in range(len(one))]


def rung_loyo(frame, buckets, hours=RUNG_HOURS, arms=None, mean_pairs=None, mean_out=None):
    """Blocked leave-one-year-out on the 2021-25 Aug-Sep rows, both rung arms, identical rows.

    ``mean_pairs`` {arm: reference arm} (R-S control C-mean): ``mean_out[arm]`` receives the largest |difference|
    of the two arms' mean predictions over every validation row. It does not change any score.
    """
    import numpy as np

    from weather.calibration import feature_model as fm

    arms = arms or RUNG_ARMS
    rows = []
    for hour in hours:
        at_hour = frame[frame["hour"] == hour]
        for year in sorted(at_hour["year"].unique()):
            train = at_hour[at_hour["year"] != year].reset_index(drop=True)
            val = at_hour[at_hour["year"] == year].reset_index(drop=True)
            out = {}
            entries = {}
            for arm, spec in arms.items():
                entry = entries[arm] = _rung_entry(train, *_arm_spec(spec))
                for market in sorted(val["market"].unique()):
                    part = val[val["market"] == market].reset_index(drop=True)
                    for i, dist in enumerate(_dist_from_fit(entry, part, buckets, market)):
                        actual = int(part.at[i, "y"])
                        out.setdefault((market, str(part.at[i, "target_date"])[:10]), {})[arm] = (
                            fm.brier_score(dist, actual), fm.log_loss(dist, actual))
            for arm, ref in (mean_pairs or {}).items():
                a, _ = entries[arm]["fit"]["mean"].predict(val)
                b, _ = entries[ref]["fit"]["mean"].predict(val)
                mean_out[arm] = max(mean_out.get(arm, 0.0), float(np.max(np.abs(a - b))) if len(val) else 0.0)
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
                  hours=RUNG_HOURS, loyo=True, arms=None, train_hook=None, row_hook=None, snap_columns=(),
                  snap_hook=None, mean_pairs=None, fits=None, serve=None):
    """Rung 07-12: B_N and P3d_N_fix dev distributions plus the blocked LOYO table (rule C:/t/l2/rung0712/rule.md).

    Each layout row uses the latest replay snapshot captured at or before the row's own captured_at_utc.
    ``arms``/``train_hook``/``row_hook`` (R-K, R-L) add arms and extra input columns: ``train_hook(frame)`` returns
    (frame, stats); ``row_hook(market, target, hour, nbm, stats)`` returns the row's extra columns. With the
    defaults the output is R-A's, byte for byte. R-S: ``snap_columns`` are extra layout columns read, and
    ``snap_hook(row, stats)`` returns more extra columns from the layout row itself; ``mean_pairs`` {arm: reference}
    records the largest |mean difference| per pair in ``audit["c_mean"]`` (control C-mean). MG-3 freeze control:
    ``fits`` replaces the in-process fits (nothing is fitted) and ``serve(arm, hour, one, market)`` returns the row's
    distribution instead of ``_dist_from_fit``.
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
    arms = arms or RUNG_ARMS
    paths = {arm: out / f"dev_{arm}.jsonl" for arm in arms}
    for path in list(paths.values()) + [out / "loyo_rows.jsonl"]:
        if path.exists():
            raise PooledModelError(f"refusing to overwrite {path}")
    timezones = {m: spec_for_id(m).timezone for m in markets}
    frame, buckets = dev_training_frame(records_root, markets)
    if frame["year"].max() >= 2026:
        raise PooledModelError("a dev training row is from 2026")
    frame, train_stats = attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff, timezones)
    frame = frame[frame["hour"].isin(hours)].reset_index(drop=True)
    hook_stats = None
    if train_hook is not None:
        frame, hook_stats = train_hook(frame)
    audit = {"arms": list(arms), "hours": list(hours), "training_rows": int(len(frame)), "train_nbm": train_stats,
             "train_years": sorted(int(y) for y in frame["year"].unique()), "markets": {},
             "inputs": {"nbm_train_corpus": hashlib.sha256(Path(nbm_train_corpus).read_bytes()).hexdigest(),
                        "observed_running_max_sha256": hashlib.sha256(
                            Path(observed_running_max.__file__).read_bytes()).hexdigest(),
                        "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    if hook_stats is not None:
        audit["train_hook"] = hook_stats
    if loyo:
        loyo_rows = rung_loyo(frame, buckets, hours)
        _write_jsonl(out / "loyo_rows.jsonl", loyo_rows)
        audit["loyo"] = rung_loyo_summary(loyo_rows)
    fits = rung_fits(frame, hours, arms=arms) if fits is None else fits
    coords = station_coordinates(markets)
    snaps = pd.read_parquet(Path(layout) / "inputs_snapshots.parquet", columns=[
        "snapshot_id", "market", "target_date", "local_hour", "cutoff_hour",
        "v2_mean", "v2_stddev", "v2_available_at", "captured_at_utc", *snap_columns])
    if (pd.to_datetime(snaps.target_date).dt.date > N_DEV_LAST).any():
        raise PooledModelError("layout holds a snapshot after 2026-09-29")
    snaps = snaps.assign(nbm_usable=usable_v2_mean(snaps))
    writers = {arm: open(path, "w", encoding="utf-8") for arm, path in paths.items()}
    c_mean = {}
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
                            "market_code": float(R0_MARKETS.index(market)),
                            **({} if row_hook is None else row_hook(market, target, hour, float(row.nbm_usable),
                                                                    stats)),
                            **({} if snap_hook is None else snap_hook(row, stats))}])
                        for arm, ref in (mean_pairs or {}).items():
                            a, _ = fits[(arm, hour)]["fit"]["mean"].predict(one)
                            b, _ = fits[(ref, hour)]["fit"]["mean"].predict(one)
                            c_mean[arm] = max(c_mean.get(arm, 0.0), abs(float(a[0]) - float(b[0])))
                        for arm in arms:
                            dist = (serve(arm, hour, one, market) if serve is not None
                                    else _dist_from_fit(fits[(arm, hour)], one, buckets, market)[0])
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
    if mean_pairs:
        audit["c_mean"] = c_mean
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


def rk_hrrr_columns(corpus_dir, markets=R0_MARKETS, *, hours=RK_HOURS, point=None, day_filter=None):
    """L13's HRRR point corpus -> {(market, local_date, hour): raw R-K path} plus integrity counts.

    ``hours``: the cutoff hours kept (R-K 13-16; R-R 07-12). ``point``: None reads each message's ``nearest``
    value (R-K); a {icao: block index} map reads ``block3x3[index]`` instead (R-R's RN-1 point rule), and a
    station absent from the map has every row ``k_miss`` = 1 (reason ``no_land_cell``). ``day_filter``: a
    predicate on the selection's local_date string; rows it rejects are not read (R-R splits one corpus into
    its training and dev halves this way).

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
        values = {}
        for icao, cell in (m.get("points") or {}).items():
            if icao not in icao_market:
                continue
            cell = cell or {}
            block = cell.get("block3x3")
            if isinstance(block, list) and len(block) == 9 and block[4] != cell.get("nearest"):
                stats["manifest_nearest_not_block_centre"] += 1
            if point is None:
                values[icao] = cell.get("nearest")
            elif icao in point:
                values[icao] = block[point[icao]] if isinstance(block, list) and len(block) == 9 else None
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
        if hour not in hours or (day_filter is not None and not day_filter(day)):
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
        if point is not None and icao not in point:
            stats["selection_no_land_cell"] += 1
            entry["reason"] = "no_land_cell"
            continue
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


def rk_control(rows, reference_rows, arms=("B_N", "P3d_N_fix"), tol=RK_CONTROL_TOL, hours=RK_HOURS):
    """The reference LOYO rows reproduce: same (hour, year, market, date) keys, same incumbent-arm scores."""
    ref = {(r["hour"], r["year"], r["market"], r["date"]): r for r in reference_rows if r["hour"] in hours}
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


RK_RH_EMIT = RJ_RH_EMIT  # R-H 13-16 B_N / P3d_N_fix dev files (rule_rk.md gate 3 reproduction)


def rung_k_dev_emit(*, records_root, layout, replay_root, nbm_train_corpus, hrrr_corpus, hrrr_dev_corpus,
                    loyo_audit, out_dir, markets=R0_MARKETS):
    """R-K gate 1b (dev half, inputs only) and the h13-16 dev distributions of all four arms (no scoring)."""
    out = require_output_outside_repo(out_dir)
    loyo = json.loads(Path(loyo_audit).read_bytes())
    if loyo.get("rule_sha256") != RK_RULE_SHA256 or loyo.get("stopped_at") or not loyo["gates"]["2_loyo"]["pass"]:
        raise PooledModelError(f"R-K gates 1a-2 did not pass: {loyo.get('stopped_at')}")
    train_hrrr, train_stats = rk_hrrr_columns(hrrr_corpus, markets)
    dev_hrrr, dev_stats = rk_hrrr_columns(hrrr_dev_corpus, markets)
    late = sorted(k for k in dev_hrrr if date.fromisoformat(k[1]) > N_DEV_LAST)
    if late:
        raise PooledModelError(f"dev HRRR corpus holds a date after 2026-09-29: {late[0]}")

    def row_hook(market, target, hour, nbm, stats):
        values = rk_columns(dev_hrrr.get((market, target.isoformat(), int(hour))), nbm)
        stats["hrrr_rows"] += 1
        stats["hrrr_covered"] += values["k_miss"] == 0.0
        return values

    audit = dev_emit_rung(records_root=records_root, layout=layout, replay_root=replay_root,
                          nbm_train_corpus=nbm_train_corpus, out_dir=out, markets=markets, hours=RK_HOURS,
                          loyo=False, arms=RK_ARMS, train_hook=lambda f: rk_training_columns(f, train_hrrr),
                          row_hook=row_hook)
    rows = sum(m.get("hrrr_rows", 0) for m in audit["markets"].values())
    covered = sum(m.get("hrrr_covered", 0) for m in audit["markets"].values())
    gate = rk_parity_training(dev_stats, {"rows": rows, "rows_covered": covered})
    gate["dev_coverage"] = gate.pop("training_coverage")
    gate["checks"]["dev_coverage"] = gate["checks"].pop("training_coverage")
    gate["dev_rows"], gate["dev_rows_covered"] = rows, covered
    rk = {"rule_sha256": RK_RULE_SHA256, "clarification_rk1_sha256": RK_CLARIFICATION_RK1_SHA256,
          "loyo_audit_sha256": hashlib.sha256(Path(loyo_audit).read_bytes()).hexdigest(),
          "inputs": {f"{tag}_{n}": hashlib.sha256((Path(root) / n).read_bytes()).hexdigest()
                     for tag, root in (("hrrr_train", hrrr_corpus), ("hrrr_dev", hrrr_dev_corpus))
                     for n in ("manifest.jsonl", "selections.jsonl", "stations.json")},
          "hrrr_dev_corpus_stats": dev_stats, "hrrr_train_corpus_stats": train_stats,
          "training": audit.get("train_hook"), "gates": {"1_parity_dev": gate}, "files": audit["files"],
          "rh_reproduction": {name: audit["files"].get(name) == sha for name, sha in RK_RH_EMIT.items()}}
    if not gate["pass"]:
        rk["stopped_at"] = "gate 1 parity (dev half; not a kill)"
    (out / "rk_emit_audit.json").write_text(json.dumps(rk, indent=1, sort_keys=True), encoding="utf-8")
    return rk


def rung_k_score(*, layout, emit_dir, out_path, start="2026-08-01", end="2026-09-29"):
    """R-K gates 3 and 4 on the dev scorecard (rule_rk.md); gate 3 failing is the pre-registered kill."""
    import numpy as np

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas

    out_path = require_output_outside_repo(out_path)
    if out_path.exists():
        raise PooledModelError(f"refusing to overwrite {out_path}")
    emit = Path(emit_dir)
    audit = json.loads((emit / "rk_emit_audit.json").read_bytes())
    if audit.get("rule_sha256") != RK_RULE_SHA256 or audit.get("stopped_at"):
        raise PooledModelError(f"emit is not an R-K emit that passed gate 1b: {audit.get('stopped_at')}")
    if not all(audit["rh_reproduction"].values()):
        raise PooledModelError(f"R-H reproduction failed: {audit['rh_reproduction']}")
    start_d, end_d = data.check_range(start, end)
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    table = sc.Table(lay, scored)
    date_w = l3._date_weights([k[0] for k in table.keys], sc.DRAWS, sc.SEED)
    market_b = table.brier(table.p_market)

    def vec(path):
        return l3._vector(table, l3._candidate_frame(str(path), table, lay, folds, data)[0])

    arms = {arm: vec(emit / f"dev_{arm}.jsonl") for arm in RK_ARMS}
    p_mg1, cov_mg1, _ = l3._vector(table, loss_atlas.mg1_frame(table))
    w0712 = (table.local_hour >= 7) & (table.local_hour <= 12)
    _, e = table.cells(table.brier(p_mg1) - market_b, w0712)
    mg1_excess = float(e.mean())
    if round(mg1_excess, 3) != l3.MG1_CONTROL_0712_EXCESS:
        raise PooledModelError(f"MG-1 positive control failed: {mg1_excess:.5f}")
    briers = {arm: table.brier(v[0]) for arm, v in arms.items()}
    covs = {arm: v[1] for arm, v in arms.items()}
    # gate 4: the composite post-13 half on as-of-capture inputs (P3d_N_fix, else MG-1) vs P3d_H (else MG-1)
    for name, arm in (("composite_post13_asof", "P3d_N_fix"), ("P3d_H_mg1", "P3d_H")):
        briers[name] = table.brier(np.where(covs[arm][table.band_snap], arms[arm][0], p_mg1))
        covs[name] = covs[arm] | cov_mg1
    briers["MG1"], covs["MG1"] = table.brier(p_mg1), cov_mg1
    common = covs["B_N"] & covs["B_H"] & covs["P3d_N_fix"] & covs["P3d_H"]
    groups = [("13-16", 13, 16), ("13-14", 13, 14), ("15-16", 15, 16)] + [(f"h{h}", h, h) for h in RK_HOURS]
    pools = [(sc.ALL_MARKETS, None)] + [(m, {m}) for m in sorted(set(table.markets))]

    def compare(arm, ref, scope=common, absolute=False):
        rows = []
        for market, members in pools:
            in_pool = np.ones(len(table.snaps), bool) if members is None else np.isin(table.markets, sorted(members))
            for group, lo, hi in (groups if members is None else groups[:1]):
                mask = scope & in_pool & (table.local_hour >= lo) & (table.local_hour <= hi)
                if not mask.any():
                    continue
                idx, c = table.cells(briers[arm], mask)
                _, r_ = table.cells(briers[ref], mask)
                _, m = table.cells(market_b, mask)
                row = {"arm": arm, "reference": ref, "market": market, "group": group,
                       "n_market_days": int(len(idx)), "n_snapshots": int(mask.sum()),
                       "R_arm": sc.ratio_interval(table.w[:, idx], c, m),
                       "R_reference": sc.ratio_interval(table.w[:, idx], r_, m),
                       "dR_crossed": sc.ratio_interval(table.w[:, idx], c - r_, m),
                       "dR_date_clustered": sc.ratio_interval(date_w[:, idx], c - r_, m)}
                if absolute:
                    row["brier_diff_w_date"] = sc.ratio_interval(table.w_date[:, idx], c - r_, np.ones(len(idx)))
                rows.append(row)
        return rows

    def pick(rows, group):
        return next(r for r in rows if r["market"] == sc.ALL_MARKETS and r["group"] == group)

    def reading(rows):
        p = pick(rows, "13-16")["dR_date_clustered"]["ci95"]
        lower = [pick(rows, f"h{h}")["dR_date_clustered"]["ci95"][0] for h in RK_HOURS]
        if p[0] > 0:
            return "HARM"
        return "WIN" if p[1] < 0 and not any(lo > 0 for lo in lower) else "NULL"

    in_rk = (table.local_hour >= 13) & (table.local_hour <= 16)
    result = {"rule_sha256": RK_RULE_SHA256, "clarification_rk1_sha256": RK_CLARIFICATION_RK1_SHA256,
              "population": {"n_dates": len(scored), "first_date": scored[0], "last_date": scored[-1],
                             "n_market_days": len(table.keys),
                             "common_covered_snapshots": {g: int((common & (table.local_hour >= lo)
                                                                  & (table.local_hour <= hi)).sum())
                                                          for g, lo, hi in groups}},
              "controls": {"mg1_excess_07_12": mg1_excess, "rh_reproduction": audit["rh_reproduction"],
                           "gate1b": audit["gates"]["1_parity_dev"],
                           "composite_mg1_fallback_snapshots_13_16": int((in_rk & ~covs["P3d_N_fix"]
                                                                          & cov_mg1).sum())},
              "inputs": {"emit_files": audit["files"], "emit_inputs": audit["inputs"],
                         "emit_audit_sha256": hashlib.sha256((emit / "rk_emit_audit.json").read_bytes()).hexdigest(),
                         "layout_manifest_sha256": lay.manifest_sha256, "scorecard_code_sha256": sc.code_sha256(),
                         "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
              "gates": {}, "rows": []}

    def done():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
        return result

    result["rows"] += compare("B_H", "B_N")  # reported only
    rows = compare("P3d_H", "P3d_N_fix")
    result["rows"] += rows
    g3 = pick(rows, "13-16")["dR_date_clustered"]
    result["gates"]["3_P3d_H_vs_P3d_N_fix_13_16"] = {"dR_date_clustered": g3, "pass": g3["ci95"][1] < 0}
    if not result["gates"]["3_P3d_H_vs_P3d_N_fix_13_16"]["pass"]:
        result["stopped_at"] = "gate 3 (KILL: HRRR closed as a 13-16 centre input)"
        return done()
    scope4 = covs["composite_post13_asof"] & covs["P3d_H_mg1"]
    rows = compare("P3d_H_mg1", "composite_post13_asof", scope=scope4)
    result["rows"] += rows
    result["rows"] += compare("P3d_H_mg1", "MG1", scope=scope4, absolute=True)  # MG-2 G2 form, reported
    result["rows"] += compare("composite_post13_asof", "MG1", scope=scope4, absolute=True)  # reported
    result["gates"]["4_vs_composite_post13_asof"] = {"reading": reading(rows),
                                                     "dR_date_clustered": pick(rows, "13-16")["dR_date_clustered"]}
    return done()


# ------------------------------------------------- R-L: NBS TXN as the 07-12 pre-dawn centre input (rule_rl.md)

RL_RULE_SHA256 = "3ce9a6f2403c68b543c13be2ea36d4b92cd711b3e9e544a92e79744db53ca9b8"
RL2_RULE_SHA256 = "a1f95786d439bf619bce793d3958373f8bd0d79cd6aa6c25580546f90b4bf2b3"  # rungl2/rule_rl2.md
RL2_SHA256SUMS = {"train": "2c5fc33a62a72b8d5b7aab7f44c4924571b96c9f4b15e1da5731a452c4867b86",
                  "dev": "dd2b7ac4227ee3b9d3345f1e84b81e0f8fcbe4648688e54f0b09e92e6ade7887"}
RL_VARIANTS = {"R-L": {"rule_sha256": RL_RULE_SHA256, "cycle_rule": "newest", "sums": None},
               "R-L2": {"rule_sha256": RL2_RULE_SHA256, "cycle_rule": "txn_bearing", "sums": RL2_SHA256SUMS}}
RL_HOURS = (7, 8, 9, 10, 11, 12)
RL_POOLS = (("07-12", None),)
RL_FEATURES = ("n_txn", "n_gap", "n_xnd", "n_miss")
RL_ARMS = {
    "B_N": True,
    "B_L": {"simple": True, "extra_ols": ("n_gap", "n_miss")},
    "P3d_N_fix": False,
    "P3d_L": {"simple": False, "extra_hgb": ("n_txn", "n_gap", "n_xnd")},
}
RL_PAIRS = (("B_L", "B_N"), ("P3d_L", "P3d_N_fix"), ("P3d_L", "B_L"), ("P3d_N_fix", "B_N"))
RL_MARGIN_S = 10 * 60
RL_MAX_AGE_S = 12 * 3600
RL_TXN_RANGE_F = (-40.0, 130.0)
RL_COVERAGE_MIN = 0.95
RL_COLUMN_CHECK_MAX_F = 3.0
_RL_HEADER = re.compile(r"^\s*(\S+)\s+NBM\s+\S+\s+NBS GUIDANCE\s+(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{2})00 UTC")


def rl_parse_block(text):
    """One NBS station block -> {"station", "issued" (UTC), "columns": {valid_utc: {element: int|None}}}.

    Columns are 3-character fields right-aligned on the FHR row's tokens; sparse elements (TXN, XND, P12, ...)
    are read at the same positions, so a blank field is None and packed fields such as ``100100`` split cleanly.
    """
    from datetime import datetime, timedelta, timezone

    lines = text.replace("\r", "").split("\n")
    head = _RL_HEADER.match(lines[0]) if lines else None
    if head is None:
        raise PooledModelError("NBS block header not recognised")
    station, month, day, year, hour = head.groups()
    issued = datetime(int(year), int(month), int(day), int(hour), tzinfo=timezone.utc)
    rows = {line[:5].strip(): line for line in lines[1:] if len(line) > 5 and line[:5].strip()}
    if "FHR" not in rows:
        raise PooledModelError("NBS block has no FHR row")
    ends = [m.end() for m in re.finditer(r"\d+", rows["FHR"][5:])]
    fhrs = [int(rows["FHR"][5 + e - 3:5 + e]) for e in ends]
    columns = {}
    for e, fhr in zip(ends, fhrs):
        cell = {}
        for name, line in rows.items():
            field = line[5 + e - 3:5 + e].strip() if len(line) >= 5 + e else ""
            try:
                cell[name] = int(field) if field else None
            except ValueError:
                cell[name] = None
        columns[issued + timedelta(hours=fhr)] = cell
    return {"station": station, "issued": issued, "columns": columns}


class RlNbsCorpus:
    """L12's NBS station blocks, selected point-in-time per (market, local date, cutoff hour). Inputs only."""

    def __init__(self, corpus_dir, markets=R0_MARKETS, cycle_rule="newest"):
        from datetime import datetime, timezone

        from weather.market.market_registry import spec_for_id

        if cycle_rule not in ("newest", "txn_bearing"):
            raise PooledModelError(f"unknown NBS cycle rule {cycle_rule}")
        self.cycle_rule = cycle_rule
        self.root = Path(corpus_dir)
        self.stats = defaultdict(int)
        self.icao = {m: spec_for_id(m).icao for m in markets}
        self.tz = {m: spec_for_id(m).timezone for m in markets}
        wanted = set(self.icao.values())
        self.cycles = defaultdict(list)
        for m in _rk_lines(self.root / "manifest.jsonl", self.stats, "manifest"):
            if m.get("product") != "nbs":
                continue
            self.stats["manifest_nbs"] += 1
            if m.get("status") != "ok" or not m.get("last_modified"):
                self.stats["manifest_not_ok"] += 1
                continue
            day = date.fromisoformat(str(m["utc_date"])[:10])
            cycle = datetime(day.year, day.month, day.day, int(m["cycle"]), tzinfo=timezone.utc)
            avail = datetime.fromisoformat(str(m["last_modified"]).replace("Z", "+00:00"))
            for icao, s in (m.get("stations") or {}).items():
                if icao in wanted and s.get("status") == "ok":
                    self.cycles[icao].append((cycle, avail, m["blocks_file"], int(s["file_offset"]),
                                              int(s["length"]), s["sha256"]))
        for v in self.cycles.values():
            v.sort()
        self._parsed = {}

    def _block(self, blocks_file, offset, length, sha):
        key = (blocks_file, offset)
        if key not in self._parsed:
            with open(self.root / blocks_file, "rb") as handle:
                handle.seek(offset)
                raw = handle.read(length)
            if hashlib.sha256(raw).hexdigest() != sha:
                self._parsed[key] = "sha_mismatch"
            else:
                try:
                    self._parsed[key] = rl_parse_block(raw.decode("ascii"))
                except (PooledModelError, UnicodeDecodeError):
                    self._parsed[key] = "parse_failed"
        return self._parsed[key]

    def raw(self, market, day, hour):
        """-> {"n_txn", "n_xnd", "n_miss", "reason", "cycle_utc", "age_s"} for local date ``day`` at h:00."""
        from datetime import datetime, time, timedelta, timezone
        from zoneinfo import ZoneInfo

        target = date.fromisoformat(str(day)[:10])
        t = datetime.combine(target, time(int(hour), 0), tzinfo=ZoneInfo(self.tz[market]))
        out = {"n_txn": float("nan"), "n_xnd": float("nan"), "n_miss": 1.0, "reason": None, "cycle_utc": None,
               "age_s": None}
        eligible = [c for c in self.cycles.get(self.icao[market], ())
                    if c[1] + timedelta(seconds=RL_MARGIN_S) <= t and c[0] <= t]
        if not eligible or (t - eligible[-1][0]).total_seconds() > RL_MAX_AGE_S:
            out["reason"] = "no_cycle"
            return out
        slot = datetime.combine(target + timedelta(days=1), time(0, 0), tzinfo=timezone.utc)
        out["newest_age_s"] = (t - eligible[-1][0]).total_seconds()
        out["skipped"] = 0
        # R-L: the newest eligible cycle only. R-L2 (rule_rl2.md): walk newest to oldest within the age bound; a
        # block failing verification fails closed; a verified block without the column is skipped.
        walk = eligible[::-1] if self.cycle_rule == "txn_bearing" else eligible[-1:]
        for cycle, _, blocks_file, offset, length, sha in walk:
            if (t - cycle).total_seconds() > RL_MAX_AGE_S:
                break
            out.update(cycle_utc=cycle.isoformat(), age_s=(t - cycle).total_seconds())
            block = self._block(blocks_file, offset, length, sha)
            if isinstance(block, str):
                out["reason"] = block
                return out
            if block["station"] != self.icao[market] or block["issued"] != cycle:
                out["reason"] = "identity_mismatch"
                return out
            cell = block["columns"].get(slot)
            if cell is None or cell.get("TXN") is None or cell.get("XND") is None:
                out["skipped"] += 1
                continue
            break
        else:
            cell = None
        if cell is None or cell.get("TXN") is None or cell.get("XND") is None:
            out["reason"] = "column_absent" if self.cycle_rule == "newest" else "no_txn_cycle"
            out.update(cycle_utc=None, age_s=None)
            return out
        txn = float(cell["TXN"])
        if not RL_TXN_RANGE_F[0] <= txn <= RL_TXN_RANGE_F[1]:
            out["reason"] = "txn_out_of_range"
            return out
        out.update(n_txn=txn, n_xnd=float(cell["XND"]), n_miss=0.0)
        return out


def rl_columns(entry, nbm):
    if entry is None or entry["n_miss"]:
        return {"n_txn": float("nan"), "n_gap": float("nan"), "n_xnd": float("nan"), "n_miss": 1.0}
    gap = entry["n_txn"] - float(nbm) if nbm is not None and math.isfinite(float(nbm)) else float("nan")
    return {"n_txn": entry["n_txn"], "n_gap": gap, "n_xnd": entry["n_xnd"], "n_miss": 0.0}


class RlStaleness:
    """Reported-only staleness per cutoff hour (rule_rl2.md): selected-cycle age, UTC hour, skipped newest cycles."""

    def __init__(self):
        self.ages, self.newest, self.hours, self.skipped, self.rows = (defaultdict(list), defaultdict(list),
                                                                       defaultdict(lambda: defaultdict(int)),
                                                                       defaultdict(int), defaultdict(int))

    def add(self, hour, entry):
        h = f"h{int(hour):02d}"
        self.rows[h] += 1
        if entry.get("newest_age_s") is not None:
            self.newest[h].append(entry["newest_age_s"] / 3600)
        if entry["n_miss"] == 0.0:
            self.ages[h].append(entry["age_s"] / 3600)
            self.hours[h][entry["cycle_utc"][11:13] + "Z"] += 1
            self.skipped[h] += entry.get("skipped", 0) > 0

    def report(self):
        import numpy as np

        def q(v):
            return [float(x) for x in np.percentile(v, [10, 50, 90])] if v else None

        return {h: {"rows": n, "selected_age_h_p10_50_90": q(self.ages[h]),
                    "newest_eligible_age_h_p10_50_90": q(self.newest[h]),
                    "selected_cycle_utc_hour": dict(sorted(self.hours[h].items())),
                    "share_newest_skipped": self.skipped[h] / max(len(self.ages[h]), 1)}
                for h, n in sorted(self.rows.items())}


def rl_training_columns(frame, corpus):
    """Attach R-L columns to training rows keyed (market, target_date, cutoff hour); ``fh`` is the NBM anchor."""
    import numpy as np

    cols, stats, gaps = defaultdict(list), defaultdict(int), []
    stale = RlStaleness()
    for market, day, hour, fh in zip(frame["market"], frame["target_date"], frame["hour"], frame["fh"]):
        entry = corpus.raw(market, str(day)[:10], int(hour))
        stale.add(hour, entry)
        stats["rows"] += 1
        stats[f"reason_{entry['reason'] or 'covered'}"] += 1
        values = rl_columns(entry, fh)
        stats["rows_covered"] += values["n_miss"] == 0.0
        if math.isfinite(values["n_gap"]):
            gaps.append(abs(values["n_gap"]))
        for k, v in values.items():
            cols[k].append(v)
    out = frame.copy()
    for k in RL_FEATURES:
        out[k] = cols[k]
    stats = dict(stats)
    stats["median_abs_gap_f"] = float(np.median(gaps)) if gaps else float("nan")
    stats["staleness"] = stale.report()
    return out, stats


def rl_parity(stats):
    """Gate 1 (either half): coverage, block integrity and the daytime-maximum column check. Inputs only."""
    coverage = stats.get("rows_covered", 0) / max(stats.get("rows", 0), 1)
    checks = {"coverage": coverage >= RL_COVERAGE_MIN,
              "sha_mismatch": stats.get("reason_sha_mismatch", 0) == 0,
              "identity_mismatch": stats.get("reason_identity_mismatch", 0) == 0,
              "parse_failed": stats.get("reason_parse_failed", 0) == 0,
              "txn_out_of_range": stats.get("reason_txn_out_of_range", 0) == 0,
              "column_check": stats.get("median_abs_gap_f", float("inf")) <= RL_COLUMN_CHECK_MAX_F}
    return {"coverage": coverage, "median_abs_gap_f": stats.get("median_abs_gap_f"), "checks": checks,
            "pass": all(checks.values())}


def _rl_sums(corpus_dir, variant, half):
    sha = hashlib.sha256((Path(corpus_dir) / "SHA256SUMS").read_bytes()).hexdigest()
    pinned = RL_VARIANTS[variant]["sums"]
    if pinned is not None and sha != pinned[half]:
        raise PooledModelError(f"{variant} {half} corpus SHA256SUMS {sha} != {pinned[half]}")
    return sha


def rung_l_loyo(*, records_root, nbm_train_corpus, nbs_corpus, ra_loyo_rows, out_dir, markets=R0_MARKETS,
                variant="R-L"):
    """R-L / R-L2 gate 1a (training half) and gate 2 (LOYO 2021-25, B_L - B_N at 07-12). No dev row is read."""
    from weather.calibration import ols_floor_ladder as l9
    from weather.market.market_registry import spec_for_id

    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise PooledModelError(f"refusing to write into a non-empty {out}")
    corpus_dir = Path(nbs_corpus)
    v = RL_VARIANTS[variant]
    sums = _rl_sums(corpus_dir, variant, "train")
    ra_sha = hashlib.sha256(Path(ra_loyo_rows).read_bytes()).hexdigest()
    if variant != "R-L" and ra_sha != RR_RA_LOYO_ROWS_SHA256:
        raise PooledModelError(f"R-A loyo rows sha {ra_sha} != {RR_RA_LOYO_ROWS_SHA256}")
    audit = {"rule_sha256": v["rule_sha256"], "variant": variant, "cycle_rule": v["cycle_rule"],
             "arms": list(RL_ARMS), "hours": list(RL_HOURS), "gates": {},
             "inputs": {"nbm_train_corpus": hashlib.sha256(Path(nbm_train_corpus).read_bytes()).hexdigest(),
                        "ra_loyo_rows": hashlib.sha256(Path(ra_loyo_rows).read_bytes()).hexdigest(),
                        "nbs_corpus": str(corpus_dir),
                        "nbs_manifest": hashlib.sha256((corpus_dir / "manifest.jsonl").read_bytes()).hexdigest(),
                        "nbs_sha256sums": hashlib.sha256((corpus_dir / "SHA256SUMS").read_bytes()).hexdigest(),
                        "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}

    def finish():
        (out / "rl_loyo_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True), encoding="utf-8")
        return audit

    timezones = {m: spec_for_id(m).timezone for m in markets}
    corpus = RlNbsCorpus(corpus_dir, markets, cycle_rule=v["cycle_rule"])
    audit["inputs"]["nbs_sha256sums_pinned"] = sums
    frame, buckets = dev_training_frame(records_root, markets)
    if frame["year"].max() >= 2026:
        raise PooledModelError("a training row is from 2026")
    frame, audit["train_nbm"] = attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff, timezones)
    frame = frame[frame["hour"].isin(RL_HOURS)].reset_index(drop=True)
    frame, audit["training"] = rl_training_columns(frame, corpus)
    audit["nbs_corpus_stats"] = dict(corpus.stats)
    audit["gates"]["1_parity_training"] = rl_parity(audit["training"])
    if not audit["gates"]["1_parity_training"]["pass"]:
        audit["stopped_at"] = "gate 1 parity (training half; not a kill)"
        return finish()
    rows = rung_loyo(frame, buckets, RL_HOURS, arms=RL_ARMS)
    _write_jsonl(out / "loyo_rows.jsonl", rows)
    audit["control_ra_reproduction"] = rk_control(rows, _read_jsonl(ra_loyo_rows), hours=RL_HOURS)
    if not audit["control_ra_reproduction"]["pass"]:
        audit["stopped_at"] = "control: R-A LOYO reproduction failed (refused, not a gate)"
        return finish()
    audit["gates"]["2_loyo"] = rg_loyo_summary(rows, pairs=RL_PAIRS, pooled=RL_POOLS)
    primary = audit["gates"]["2_loyo"]["B_L-B_N|07-12|brier"]
    audit["gates"]["2_loyo"]["pass"] = primary["ci95"][1] < 0
    if not audit["gates"]["2_loyo"]["pass"]:
        audit["stopped_at"] = "gate 2 LOYO (KILL: NBS TXN closed as a 07-12 centre input)"
    return finish()


RL_RA_EMIT = {"dev_B_N.jsonl": "83cf9bbe9cd8f3173b98dd4cea47880457cf0c5648fe2cca4d50b4550cd8c43c",
              "dev_P3d_N_fix.jsonl": "cd0034b9faec0b687e1184187feeaa39ab151c5f9f8d1c905d3a49a0e7089542"}


def rung_l_dev_emit(*, records_root, layout, replay_root, nbm_train_corpus, nbs_corpus, nbs_dev_corpus,
                    loyo_audit, out_dir, markets=R0_MARKETS, variant="R-L"):
    """R-L gate 1b (dev half, inputs only) and the h07-12 dev distributions of all four arms (no scoring)."""
    out = require_output_outside_repo(out_dir)
    loyo = json.loads(Path(loyo_audit).read_bytes())
    v = RL_VARIANTS[variant]
    if loyo.get("rule_sha256") != v["rule_sha256"] or loyo.get("stopped_at") or not loyo["gates"]["2_loyo"]["pass"]:
        raise PooledModelError(f"{variant} gates 1a-2 did not pass: {loyo.get('stopped_at')}")
    _rl_sums(nbs_corpus, variant, "train")
    _rl_sums(nbs_dev_corpus, variant, "dev")
    train = RlNbsCorpus(nbs_corpus, markets, cycle_rule=v["cycle_rule"])
    dev = RlNbsCorpus(nbs_dev_corpus, markets, cycle_rule=v["cycle_rule"])
    stale = RlStaleness()
    late = [c for v in dev.cycles.values() for c in v if c[0].date() > N_DEV_LAST]
    if late:
        raise PooledModelError(f"dev NBS corpus holds a cycle after 2026-09-29: {late[0][0]}")
    dev_stats, gaps = defaultdict(int), []

    def row_hook(market, target, hour, nbm, stats):
        entry = dev.raw(market, target.isoformat(), int(hour))
        stale.add(hour, entry)
        values = rl_columns(entry, nbm)
        stats["nbs_rows"] += 1
        stats["nbs_covered"] += values["n_miss"] == 0.0
        dev_stats["rows"] += 1
        dev_stats[f"reason_{entry['reason'] or 'covered'}"] += 1
        dev_stats["rows_covered"] += values["n_miss"] == 0.0
        if math.isfinite(values["n_gap"]):
            gaps.append(abs(values["n_gap"]))
        return values

    audit = dev_emit_rung(records_root=records_root, layout=layout, replay_root=replay_root,
                          nbm_train_corpus=nbm_train_corpus, out_dir=out, markets=markets, hours=RL_HOURS,
                          loyo=False, arms=RL_ARMS, train_hook=lambda f: rl_training_columns(f, train),
                          row_hook=row_hook)
    dev_stats = dict(dev_stats)
    dev_stats["median_abs_gap_f"] = sorted(gaps)[len(gaps) // 2] if gaps else float("nan")
    dev_stats["staleness"] = stale.report()
    rl = {"rule_sha256": v["rule_sha256"], "variant": variant,
          "loyo_audit_sha256": hashlib.sha256(Path(loyo_audit).read_bytes()).hexdigest(),
          "inputs": {f"{tag}_{n}": hashlib.sha256((Path(root) / n).read_bytes()).hexdigest()
                     for tag, root in (("nbs_train", nbs_corpus), ("nbs_dev", nbs_dev_corpus))
                     for n in ("manifest.jsonl", "SHA256SUMS")},
          "nbs_dev_corpus_stats": dict(dev.stats), "dev": dev_stats, "training": audit.get("train_hook"),
          "gates": {"1_parity_dev": rl_parity(dev_stats)}, "files": audit["files"],
          "ra_reproduction": {name: audit["files"].get(name) == sha for name, sha in RL_RA_EMIT.items()}}
    if not rl["gates"]["1_parity_dev"]["pass"]:
        rl["stopped_at"] = "gate 1 parity (dev half; not a kill)"
    (out / "rl_emit_audit.json").write_text(json.dumps(rl, indent=1, sort_keys=True), encoding="utf-8")
    return rl


def rung_l_score(*, layout, emit_dir, coefficients, nowcasts, out_path, start="2026-08-01", end="2026-09-29",
                 variant="R-L"):
    """R-L gates 3 and 4 on the dev scorecard (rule_rl.md); gate 3 failing is the pre-registered kill."""
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
    audit = json.loads((emit / "rl_emit_audit.json").read_bytes())
    if audit.get("rule_sha256") != RL_VARIANTS[variant]["rule_sha256"] or audit.get("stopped_at"):
        raise PooledModelError(f"emit is not an R-L emit that passed gate 1b: {audit.get('stopped_at')}")
    if not all(audit["ra_reproduction"].values()):
        raise PooledModelError(f"R-A reproduction failed: {audit['ra_reproduction']}")
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
    table = sc.Table(lay, scored)
    date_w = l3._date_weights([k[0] for k in table.keys], sc.DRAWS, sc.SEED)
    market_b = table.brier(table.p_market)

    def vec(path):
        return l3._vector(table, l3._candidate_frame(str(path), table, lay, folds, data)[0])

    arms = {arm: vec(emit / f"dev_{arm}.jsonl") for arm in RL_ARMS}
    p_mg1, cov_mg1, _ = l3._vector(table, loss_atlas.mg1_frame(table))
    p_l6, cov_l6, _ = l6_vector(table, state, l3)
    w0712 = (table.local_hour >= 7) & (table.local_hour <= 12)
    _, e = table.cells(table.brier(p_mg1) - market_b, w0712)
    mg1_excess = float(e.mean())
    if round(mg1_excess, 3) != l3.MG1_CONTROL_0712_EXCESS:
        raise PooledModelError(f"MG-1 positive control failed: {mg1_excess:.5f}")
    briers = {arm: table.brier(v[0]) for arm, v in arms.items()}
    covs = {arm: v[1] for arm, v in arms.items()}
    briers["l6"], covs["l6"] = table.brier(p_l6), cov_l6
    common = covs["B_N"] & covs["B_L"] & covs["P3d_N_fix"] & covs["P3d_L"]
    groups = [("07-12", 7, 12)] + [(f"h{h:02d}", h, h) for h in RL_HOURS]
    pools = [(sc.ALL_MARKETS, None)] + [(m, {m}) for m in sorted(set(table.markets))]

    def compare(arm, ref, scope):
        rows = []
        for market, members in pools:
            in_pool = np.ones(len(table.snaps), bool) if members is None else np.isin(table.markets, sorted(members))
            for group, lo, hi in (groups if members is None else groups[:1]):
                mask = scope & in_pool & (table.local_hour >= lo) & (table.local_hour <= hi)
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
        p = pick(rows, "07-12")["dR_date_clustered"]["ci95"]
        lower = [pick(rows, f"h{h:02d}")["dR_date_clustered"]["ci95"][0] for h in RL_HOURS]
        if p[0] > 0:
            return "HARM"
        return "WIN" if p[1] < 0 and not any(lo > 0 for lo in lower) else "NULL"

    result = {"rule_sha256": RL_VARIANTS[variant]["rule_sha256"], "variant": variant,
              "population": {"n_dates": len(scored), "first_date": scored[0], "last_date": scored[-1],
                             "n_market_days": len(table.keys), "common_covered_snapshots_07_12": int((common & w0712).sum())},
              "controls": {"mg1_excess_07_12": mg1_excess, "ra_reproduction": audit["ra_reproduction"],
                           "l6_part_sha256": part_sha, "l6_nowcast_sha256": now_sha,
                           "gate1b": audit["gates"]["1_parity_dev"]},
              "inputs": {"emit_files": audit["files"], "emit_inputs": audit["inputs"],
                         "emit_audit_sha256": hashlib.sha256((emit / "rl_emit_audit.json").read_bytes()).hexdigest(),
                         "layout_manifest_sha256": lay.manifest_sha256, "scorecard_code_sha256": sc.code_sha256(),
                         "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
              "gates": {}, "rows": []}

    def done():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
        return result

    result["rows"] += compare("B_L", "B_N", common)  # reported only
    rows = compare("P3d_L", "P3d_N_fix", common)
    result["rows"] += rows
    g3 = pick(rows, "07-12")["dR_date_clustered"]
    result["gates"]["3_P3d_L_vs_P3d_N_fix_07_12"] = {"dR_date_clustered": g3, "pass": g3["ci95"][1] < 0}
    if not result["gates"]["3_P3d_L_vs_P3d_N_fix_07_12"]["pass"]:
        result["stopped_at"] = "gate 3 (KILL: NBS TXN closed as a 07-12 centre input)"
        return done()
    rows = compare("P3d_L", "l6", common & cov_l6)
    result["rows"] += rows
    result["gates"]["4_vs_l6"] = {"reading": reading(rows), "dR_date_clustered": pick(rows, "07-12")["dR_date_clustered"]}
    return done()


# ---------------------------------------------------------------- R-L2 anchor diagnostic (inputs only, no rule)

RL_DIAG_TRAIN_YEARS = (2021, 2022, 2023, 2024, 2025)
RL_DIAG_TRAIN_MONTHS = (8, 9)


def _rl_diag_summary(values):
    import numpy as np

    arr = np.asarray(values, dtype=float)
    if not len(arr):
        return {"n": 0}
    a = np.abs(arr)
    return {"n": int(len(arr)), "median_abs_f": float(np.median(a)), "mean_abs_f": float(a.mean()),
            "mean_signed_f": float(arr.mean()), "p90_abs_f": float(np.quantile(a, .9)),
            "share_exact_0": float((a == 0).mean()), "share_le_1f": float((a <= 1).mean())}


def rl_anchor_diag(*, nbs_corpus, nbs_dev_corpus, nbm_train_corpus, nbm_dev_corpus, out_path,
                   markets=R0_MARKETS, dev_first="2026-07-30", dev_last="2026-09-29"):
    """Coordinator diagnostic (10-26, no rule): |n_txn - L9 nbm_at_cutoff| at h07-12, training years vs dev.

    Inputs only: NBS station blocks (R-L2's txn_bearing cycle rule) and the L9 PIT NBM corpora. No label,
    outcome, price or market row is read. Grouped by half x year x hour, by the anchor's NBM product version
    and cycle, by the selected NBS cycle's UTC hour, and by whether both come from the same issuance hour.
    """
    from weather.calibration import ols_floor_ladder as l9
    from weather.market.market_registry import spec_for_id

    out_path = require_output_outside_repo(out_path)
    if out_path.exists():
        raise PooledModelError(f"refusing to overwrite {out_path}")
    _rl_sums(nbs_corpus, "R-L2", "train")
    _rl_sums(nbs_dev_corpus, "R-L2", "dev")
    halves = {"train": (RlNbsCorpus(nbs_corpus, markets, cycle_rule="txn_bearing"), Path(nbm_train_corpus)),
              "dev": (RlNbsCorpus(nbs_dev_corpus, markets, cycle_rule="txn_bearing"), Path(nbm_dev_corpus))}
    late = [c for v in halves["dev"][0].cycles.values() for c in v if c[0].date() > N_DEV_LAST]
    if late:
        raise PooledModelError(f"dev NBS corpus holds a cycle after 2026-09-29: {late[0][0]}")
    versions = {}
    for half, (_, path) in halves.items():
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("available") and r.get("mean") is not None:
                versions[(half, r["market_id"], r["target_date"], r["cycle"])] = str(r.get("product_version"))
    groups, counts = defaultdict(list), defaultdict(lambda: defaultdict(int))
    tz = {m: spec_for_id(m).timezone for m in markets}
    for half, (nbs, path) in halves.items():
        table = l9.load_nbm(path)
        for (market, day) in sorted(table):
            if market not in tz:
                continue
            d = date.fromisoformat(day)
            if half == "train":
                if d.year not in RL_DIAG_TRAIN_YEARS or d.month not in RL_DIAG_TRAIN_MONTHS:
                    continue
            elif not (date.fromisoformat(dev_first) <= d <= min(date.fromisoformat(dev_last), N_DEV_LAST)):
                continue
            for hour in RL_HOURS:
                c = counts[half]
                c["rows"] += 1
                anchor, cycle = l9.nbm_at_cutoff(table, market, day, int(hour), tz[market])
                if anchor is None:
                    c["no_anchor"] += 1
                    continue
                entry = nbs.raw(market, day, int(hour))
                if entry["n_miss"]:
                    c[f"nbs_{entry['reason']}"] += 1
                    continue
                c["paired"] += 1
                c["anchor_non_integer"] += float(anchor) != round(float(anchor))
                gap = entry["n_txn"] - float(anchor)
                nbs_hour = entry["cycle_utc"][11:13]
                version = versions.get((half, market, day, cycle), "unknown")
                keys = [("half_year_hour", half, str(d.year), f"h{int(hour):02d}"),
                        ("half_hour", half, f"h{int(hour):02d}"),
                        ("half", half),
                        ("half_version", half, version),
                        ("half_year_version", half, str(d.year), version),
                        ("half_anchor_cycle", half, f"{cycle}Z"),
                        ("half_nbs_cycle", half, f"{nbs_hour}Z"),
                        ("half_same_issuance_hour", half, str(nbs_hour == cycle)),
                        ("half_market", half, market)]
                for k in keys:
                    groups[k].append(gap)
    report = {"evidence_class": "diagnostic, inputs only, no rule (coordinator 2026-10-26)",
              "ruling": "R-L3 dropped; R-L2 kill stands; any follow-up rung needs a fresh ruling",
              "inputs": {"nbs_train_SHA256SUMS": _rl_sums(nbs_corpus, "R-L2", "train"),
                         "nbs_dev_SHA256SUMS": _rl_sums(nbs_dev_corpus, "R-L2", "dev"),
                         "nbm_train_corpus": hashlib.sha256(Path(nbm_train_corpus).read_bytes()).hexdigest(),
                         "nbm_dev_corpus": hashlib.sha256(Path(nbm_dev_corpus).read_bytes()).hexdigest(),
                         "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
              "cycle_rule": "txn_bearing (R-L2)", "hours": list(RL_HOURS),
              "train_years": list(RL_DIAG_TRAIN_YEARS), "train_months": list(RL_DIAG_TRAIN_MONTHS),
              "dev_dates": [dev_first, dev_last],
              "counts": {h: {"rows": 0, **counts[h]} for h in halves},
              "groups": {"|".join(k): _rl_diag_summary(v) for k, v in sorted(groups.items())}}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    return report


# ------------------------------------------------- R-R: the HRRR hourly path as a 07-12 centre input (rule_rr.md)

RR_RULE_SHA256 = "e3d92e1aa779957db90c9627f3ccdc9052d7f9f2d6f7ae50843ebadbd0f5bb22"
RR_LAND_SHA256 = "22069beebb5609755b35621bac05e91a1b35e434670c993a93a8aca9434fd7d6"
RR_LAND_MSG_SHA256 = "10c7fb85ac10616ca3f45295d945002ab5da437054736748f6746dd01b0e7c29"
RR_LAND_KEY = "hrrr.20250801/conus/hrrr.t00z.wrfsfcf00.grib2"
RR_CORPUS_SHA256 = {"manifest.jsonl": "fef6c307a411e6373af05830b55c4dff8cb23d08f46e18f07949821f08fe88e6",
                    "selections.jsonl": "31bd3d3a7c6456df657e8f99b763a06a80bc41772881f67dc7eeaf5dee1f4e67",
                    "days.jsonl": "34af53b0e276c541605e3e93a57018619ddf0895f92f07add5c835901fd3515e",
                    "stations.json": "52e8bb5f22513828cb5edbfc16b77afb293cfcb9df62a92abd4db30ab7a0abe3"}
RR_RA_LOYO_ROWS_SHA256 = "21cacdaabcf50165da084a748b42a0b862c36c9e1f4b8d4bdb506c07c927f54d"
RR_HOURS = (7, 8, 9, 10, 11, 12)
RR_POOLS = (("07-12", None), ("07-09", (7, 8, 9)), ("10-12", (10, 11, 12)))
RR_ARMS = RK_ARMS
RR_PAIRS = RK_PAIRS
RR_RA_EMIT = RL_RA_EMIT  # R-F's B_N / P3d_N_fix 07-12 dev inputs (rule_rr.md gate 3 reproduction)
RR_EXPECTED_INDEX = {"KSFO": 3}  # the coordinator's reading of RN-1; every other station is the centre cell (4)
RR_TRAIN_LAST = "2025-12-31"
RR_DEV_FIRST = "2026-07-30"
RR_DEV_LAST = "2026-09-29"


def _rr_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rr_verify_corpus(corpus_dir):
    """Every corpus file's sha256 equals the coordinator's pin, or the run is refused."""
    got = {n: _rr_sha(Path(corpus_dir) / n) for n in RR_CORPUS_SHA256}
    bad = {n: s for n, s in got.items() if s != RR_CORPUS_SHA256[n]}
    if bad:
        raise PooledModelError(f"R-R corpus sha mismatch: {bad}")
    return got


def rr_point_rule(land_path, corpus_dir, markets=R0_MARKETS, expected=None):
    """RN-1's land-aware point rule (rule_rr.md, Point rule) -> {icao: block index}, refused on any mismatch.

    The chosen index is recomputed from the station's (fi, fj) and the stored LAND block (row-major, south to
    north, west to east: index = 3 * (dj + 1) + (di + 1)); it must equal ``rn1_chosen_index`` in the land file
    and the coordinator's reading (KSFO 3, every other station the centre cell 4). ``expected`` replaces the
    pinned land sha and that reading (tests only).
    """
    land_sha = _rr_sha(land_path)
    pinned = RR_LAND_SHA256 if expected is None else expected.get("land_sha256")
    if land_sha != pinned:
        raise PooledModelError(f"land file sha {land_sha} != {pinned}")
    land = json.loads(Path(land_path).read_bytes())
    stations_sha = _rr_sha(Path(corpus_dir) / "stations.json")
    if land.get("stations_json_sha256") != stations_sha:
        raise PooledModelError(f"land stations_json_sha256 {land.get('stations_json_sha256')} != {stations_sha}")
    if expected is None and (land.get("msg_sha256") != RR_LAND_MSG_SHA256 or land.get("key") != RR_LAND_KEY):
        raise PooledModelError("land file is not the registered LAND:surface message")
    reading = RR_EXPECTED_INDEX if expected is None else expected.get("index", {})
    stations = json.loads((Path(corpus_dir) / "stations.json").read_bytes())
    point, report = {}, {}
    for icao, s in sorted(stations.items()):
        if s.get("market") not in markets:
            continue
        cell = land["stations"][icao]
        if (cell["i"], cell["j"], cell["fi"], cell["fj"]) != (s["i"], s["j"], s["fi"], s["fj"]):
            raise PooledModelError(f"{icao}: land grid position differs from stations.json")
        mask = cell["land_block3x3"]
        dist = []
        for k in range(9):
            dj, di = divmod(k, 3)
            dist.append(math.hypot(s["i"] + di - 1 - s["fi"], s["j"] + dj - 1 - s["fj"]))
        if max(abs(a - b) for a, b in zip(dist, cell["dist_grid_units"])) > 1e-9:
            raise PooledModelError(f"{icao}: block ordering does not reproduce the stored distances")
        land_cells = [k for k in range(9) if mask[k] == 1]
        chosen = min(land_cells, key=lambda k: (dist[k], k)) if land_cells else None
        if chosen != cell.get("rn1_chosen_index"):
            raise PooledModelError(f"{icao}: recomputed RN-1 index {chosen} != {cell.get('rn1_chosen_index')}")
        if chosen != reading.get(icao, 4):
            raise PooledModelError(f"{icao}: RN-1 index {chosen} differs from the coordinator's reading")
        if chosen is not None:
            point[icao] = chosen
        report[icao] = {"market": s["market"], "chosen_index": chosen, "n_land": len(land_cells),
                        "chosen_dist_grid": None if chosen is None else dist[chosen]}
    return point, {"land_sha256": land_sha, "stations_json_sha256": stations_sha, "stations": report}


def _rr_train_day(day):
    return day <= RR_TRAIN_LAST


def _rr_dev_day(day):
    return RR_DEV_FIRST <= day <= RR_DEV_LAST


def rr_corpus_dates(corpus_dir):
    """The corpus' local dates and cycles (inputs only); nothing may be dated after 2026-09-29."""
    days, cycles = set(), set()
    with open(Path(corpus_dir) / "selections.jsonl", "rb") as handle:
        for line in handle:
            if line.strip():
                s = json.loads(line)
                days.add(s["local_date"])
                if s.get("cycle_utc"):
                    cycles.add(s["cycle_utc"][:10])
    if max(days) > RR_DEV_LAST or (cycles and max(cycles) > RR_DEV_LAST):
        raise PooledModelError(f"R-R corpus holds a date after {RR_DEV_LAST}")
    train = sorted(d for d in days if _rr_train_day(d))
    dev = sorted(d for d in days if _rr_dev_day(d))
    other = sorted(days - set(train) - set(dev))
    return {"n_days": len(days), "train_days": len(train), "dev_days": len(dev), "other_days": other,
            "first": min(days), "last": max(days)}


def rr_parity(corpus_stats, rows, covered, tag):
    """Gate 1 (rule_rr.md, RK-1 section 1 with h07-12): inputs only."""
    gate = rk_parity_training(corpus_stats, {"rows": rows, "rows_covered": covered})
    gate[f"{tag}_coverage"] = gate.pop("training_coverage")
    gate["checks"][f"{tag}_coverage"] = gate["checks"].pop("training_coverage")
    gate["checks"]["nearest_is_block_centre"] = corpus_stats.get("manifest_nearest_not_block_centre", 0) == 0
    gate["no_land_cell_rows"] = corpus_stats.get("selection_no_land_cell", 0)  # reported, not a failure
    gate["rows"], gate["rows_covered"] = rows, covered
    gate["pass"] = all(gate["checks"].values())
    return gate


def rung_r_loyo(*, records_root, nbm_train_corpus, hrrr_corpus, land, ra_loyo_rows, out_dir, markets=R0_MARKETS):
    """R-R gate 1a (training half) and gate 2 (LOYO 2021-25, B_H - B_N at 07-12). No dev row is read."""
    from weather.calibration import ols_floor_ladder as l9
    from weather.market.market_registry import spec_for_id

    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise PooledModelError(f"refusing to write into a non-empty {out}")
    corpus = Path(hrrr_corpus)
    shas = rr_verify_corpus(corpus)
    ra_sha = _rr_sha(ra_loyo_rows)
    if ra_sha != RR_RA_LOYO_ROWS_SHA256:
        raise PooledModelError(f"R-A loyo rows sha {ra_sha} != {RR_RA_LOYO_ROWS_SHA256}")
    point, point_report = rr_point_rule(land, corpus, markets)
    audit = {"rule_sha256": RR_RULE_SHA256, "arms": list(RR_ARMS), "hours": list(RR_HOURS), "gates": {},
             "point_rule": point_report, "corpus_dates": rr_corpus_dates(corpus),
             "inputs": {"nbm_train_corpus": _rr_sha(nbm_train_corpus), "ra_loyo_rows": ra_sha,
                        "hrrr_corpus": str(corpus), **{f"hrrr_{n}": s for n, s in shas.items()},
                        "module_sha256": _rr_sha(__file__)}}

    def finish():
        (out / "rr_loyo_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True), encoding="utf-8")
        return audit

    timezones = {m: spec_for_id(m).timezone for m in markets}
    hrrr, audit["hrrr_corpus_stats"] = rk_hrrr_columns(corpus, markets, hours=RR_HOURS, point=point,
                                                       day_filter=_rr_train_day)
    frame, buckets = dev_training_frame(records_root, markets)
    if frame["year"].max() >= 2026:
        raise PooledModelError("a training row is from 2026")
    frame, audit["train_nbm"] = attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff, timezones)
    frame = frame[frame["hour"].isin(RR_HOURS)].reset_index(drop=True)
    frame, audit["training"] = rk_training_columns(frame, hrrr)
    reasons = defaultdict(int)
    for market, day, hour in zip(frame["market"], frame["target_date"], frame["hour"]):
        entry = hrrr.get((market, str(day)[:10], int(hour)))
        reasons["no_selection" if entry is None else (entry["reason"] or "covered")] += 1
    audit["training_reasons"] = dict(reasons)
    audit["gates"]["1a_parity_training"] = rr_parity(audit["hrrr_corpus_stats"], audit["training"]["rows"],
                                                     audit["training"]["rows_covered"], "training")
    if not audit["gates"]["1a_parity_training"]["pass"]:
        audit["stopped_at"] = "gate 1a parity (training half; not a kill)"
        return finish()
    rows = rung_loyo(frame, buckets, RR_HOURS, arms=RR_ARMS)
    _write_jsonl(out / "loyo_rows.jsonl", rows)
    audit["control_ra_reproduction"] = rk_control(rows, _read_jsonl(ra_loyo_rows), hours=RR_HOURS)
    if not audit["control_ra_reproduction"]["pass"]:
        audit["stopped_at"] = "control: R-A 07-12 LOYO reproduction failed (refused, not a gate)"
        return finish()
    audit["gates"]["2_loyo"] = rg_loyo_summary(rows, pairs=RR_PAIRS, pooled=RR_POOLS)
    primary = audit["gates"]["2_loyo"]["B_H-B_N|07-12|brier"]
    audit["gates"]["2_loyo"]["pass"] = primary["ci95"][1] < 0
    if not audit["gates"]["2_loyo"]["pass"]:
        audit["stopped_at"] = "gate 2 LOYO (KILL: HRRR closed as a 07-12 centre input)"
    return finish()


def rung_r_dev_emit(*, records_root, layout, replay_root, nbm_train_corpus, hrrr_corpus, land, loyo_audit, out_dir,
                    markets=R0_MARKETS):
    """R-R gate 1b (dev half, inputs only) and the h07-12 dev distributions of all four arms (no scoring)."""
    out = require_output_outside_repo(out_dir)
    loyo = json.loads(Path(loyo_audit).read_bytes())
    if loyo.get("rule_sha256") != RR_RULE_SHA256 or loyo.get("stopped_at") or not loyo["gates"]["2_loyo"]["pass"]:
        raise PooledModelError(f"R-R gates 1a-2 did not pass: {loyo.get('stopped_at')}")
    corpus = Path(hrrr_corpus)
    shas = rr_verify_corpus(corpus)
    point, point_report = rr_point_rule(land, corpus, markets)
    dates = rr_corpus_dates(corpus)
    train_hrrr, train_stats = rk_hrrr_columns(corpus, markets, hours=RR_HOURS, point=point, day_filter=_rr_train_day)
    dev_hrrr, dev_stats = rk_hrrr_columns(corpus, markets, hours=RR_HOURS, point=point, day_filter=_rr_dev_day)
    reasons = defaultdict(int)

    def row_hook(market, target, hour, nbm, stats):
        entry = dev_hrrr.get((market, target.isoformat(), int(hour)))
        reasons["no_selection" if entry is None else (entry["reason"] or "covered")] += 1
        values = rk_columns(entry, nbm)
        stats["hrrr_rows"] += 1
        stats["hrrr_covered"] += values["k_miss"] == 0.0
        return values

    audit = dev_emit_rung(records_root=records_root, layout=layout, replay_root=replay_root,
                          nbm_train_corpus=nbm_train_corpus, out_dir=out, markets=markets, hours=RR_HOURS,
                          loyo=False, arms=RR_ARMS, train_hook=lambda f: rk_training_columns(f, train_hrrr),
                          row_hook=row_hook)
    rows = sum(m.get("hrrr_rows", 0) for m in audit["markets"].values())
    covered = sum(m.get("hrrr_covered", 0) for m in audit["markets"].values())
    rr = {"rule_sha256": RR_RULE_SHA256, "loyo_audit_sha256": _rr_sha(loyo_audit), "point_rule": point_report,
          "corpus_dates": dates, "inputs": {f"hrrr_{n}": s for n, s in shas.items()},
          "hrrr_dev_corpus_stats": dev_stats, "hrrr_train_corpus_stats": train_stats, "dev_reasons": dict(reasons),
          "training": audit.get("train_hook"), "gates": {"1b_parity_dev": rr_parity(dev_stats, rows, covered, "dev")},
          "files": audit["files"],
          "ra_reproduction": {name: audit["files"].get(name) == sha for name, sha in RR_RA_EMIT.items()}}
    if not rr["gates"]["1b_parity_dev"]["pass"]:
        rr["stopped_at"] = "gate 1b parity (dev half; not a kill)"
    (out / "rr_emit_audit.json").write_text(json.dumps(rr, indent=1, sort_keys=True), encoding="utf-8")
    return rr


def rung_r_score(*, layout, emit_dir, coefficients, nowcasts, rf_result, out_path, start="2026-08-01",
                 end="2026-09-29"):
    """R-R gates 3 and 4 (and gate 5, reported) on the dev scorecard (rule_rr.md); gate 3 failing is the kill."""
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
    audit = json.loads((emit / "rr_emit_audit.json").read_bytes())
    if audit.get("rule_sha256") != RR_RULE_SHA256 or audit.get("stopped_at"):
        raise PooledModelError(f"emit is not an R-R emit that passed gate 1b: {audit.get('stopped_at')}")
    if not all(audit["ra_reproduction"].values()):
        raise PooledModelError(f"R-F input reproduction failed: {audit['ra_reproduction']}")
    now_sha = _rr_sha(nowcasts)
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

    def arm_vec(table, arm):
        return l3._vector(table, l3._candidate_frame(str(emit / f"dev_{arm}.jsonl"), table, lay, folds, data)[0])

    full = sc.Table(lay, fit_dates)
    fdates = full.snaps.date.astype(str).to_numpy()
    pl, cl, _ = l6_vector(full, state, l3)
    weights = {}
    for name, cand in (("blend_l6_H", "P3d_H"), ("blend_l6", "P3d_N_fix")):
        pa, ca, _ = arm_vec(full, cand)
        A, B = blend_weight(pa, pl, full.y, full.offsets, full.n)
        weights[name] = walk_forward_weights(fdates, full.local_hour, ca & cl, A, B, scored)

    table = sc.Table(lay, scored)
    date_w = l3._date_weights([k[0] for k in table.keys], sc.DRAWS, sc.SEED)
    market_b = table.brier(table.p_market)
    vec = {arm: arm_vec(table, arm) for arm in RR_ARMS}
    p_mg1, cov_mg1, _ = l3._vector(table, loss_atlas.mg1_frame(table))
    p_l6, cov_l6, _ = l6_vector(table, state, l3)
    w0712 = (table.local_hour >= 7) & (table.local_hour <= 12)
    _, e = table.cells(table.brier(p_mg1) - market_b, w0712)
    mg1_excess = float(e.mean())
    if round(mg1_excess, 3) != l3.MG1_CONTROL_0712_EXCESS:
        raise PooledModelError(f"MG-1 positive control failed: {mg1_excess:.5f}")
    # R-F's mg1.predict identity and L6 controls (rung_rf), refused otherwise
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
                   "mg1_identity_max_abs_diff": mg1_identity}
    if l6_controls["differing_outside_07_12"] or l6_controls["differing_without_nowcast"]:
        raise PooledModelError(f"L6 control failed: {l6_controls}")
    if not l6_controls["snapshots_differing_from_mg1"]:
        raise PooledModelError("L6 never differs from MG-1: nowcast keys do not join")
    dates = table.snaps.date.astype(str).to_numpy()
    briers = {arm: table.brier(v[0]) for arm, v in vec.items()}
    covs = {arm: v[1] for arm, v in vec.items()}
    everything = np.ones(len(table.snaps), dtype=bool)
    briers.update(l6=table.brier(p_l6), mg1=table.brier(p_mg1))
    covs.update(l6=cov_l6, mg1=cov_mg1)
    for name, cand in (("blend_l6_H", "P3d_H"), ("blend_l6", "P3d_N_fix")):
        w_snap = np.array([weights[name].get((int(h), d), 0.0) for h, d in zip(table.local_hour, dates)])
        wb = np.where(covs[cand] & cov_l6, w_snap, 0.0)[table.band_snap]
        briers[name] = table.brier(wb * vec[cand][0] + (1.0 - wb) * p_l6)
        covs[name] = cov_l6
    briers["P3d_H_l6"] = table.brier(np.where(covs["P3d_H"][table.band_snap], vec["P3d_H"][0], p_l6))
    covs["P3d_H_l6"] = covs["P3d_H"] | cov_l6
    four = covs["B_N"] & covs["B_H"] & covs["P3d_N_fix"] & covs["P3d_H"]
    scope4 = covs["P3d_H"] & cov_l6  # R-F's covered scope with P3d_H in place of P3d_N_fix
    pools = [(sc.ALL_MARKETS, None), (l3.PRIMARY_POOL, set(l3.PRIMARY_MARKETS))] + [
        (m, {m}) for m in sorted(set(table.markets))]
    groups = [("07-12", 7, 12), ("07-09", 7, 9), ("10-12", 10, 12)] + [(f"h{h:02d}", h, h) for h in RR_HOURS]

    def compare(arm, ref, scope, label, absolute=False):
        rows = []
        for market, members in pools:
            in_pool = everything if members is None else np.isin(table.markets, sorted(members))
            for group, lo, hi in groups:
                mask = scope & in_pool & (table.local_hour >= lo) & (table.local_hour <= hi)
                if not mask.any():
                    continue
                idx, c = table.cells(briers[arm], mask)
                _, r_ = table.cells(briers[ref], mask)
                _, m = table.cells(market_b, mask)
                row = {"arm": arm, "reference": ref, "scope": label, "market": market, "group": group,
                       "n_market_days": int(len(idx)), "n_snapshots": int(mask.sum()),
                       "R_arm": sc.ratio_interval(table.w[:, idx], c, m),
                       "R_reference": sc.ratio_interval(table.w[:, idx], r_, m),
                       "R_arm_date_clustered": sc.ratio_interval(date_w[:, idx], c, m),
                       "dR_crossed": sc.ratio_interval(table.w[:, idx], c - r_, m),
                       "dR_date_clustered": sc.ratio_interval(date_w[:, idx], c - r_, m)}
                if absolute:
                    row["brier_diff_w_date"] = sc.ratio_interval(table.w_date[:, idx], c - r_, np.ones(len(idx)))
                rows.append(row)
        return rows

    def pick(rows, group="07-12"):
        return next(r for r in rows if r["market"] == sc.ALL_MARKETS and r["group"] == group)

    def reading(rows):
        p = pick(rows)["dR_date_clustered"]["ci95"]
        lower = [pick(rows, f"h{h:02d}")["dR_date_clustered"]["ci95"][0] for h in RR_HOURS]
        if p[0] > 0:
            return "HARM"
        return "WIN" if p[1] < 0 and not any(lo > 0 for lo in lower) else "NULL"

    # R-F's blend_l6 vs L6 estimate, reported (not a gate): R-F's construction re-run on R-F's inputs
    rf = json.loads(Path(rf_result).read_bytes())
    rf_row = next(r for r in rf["rows"] if r["arm"] == "blend_l6" and r["reference"] == "l6"
                  and r["scope"] == "covered" and r["market"] == sc.ALL_MARKETS and r["group"] == "07-12")
    rf_now = pick(compare("blend_l6", "l6", covs["P3d_N_fix"] & cov_l6, "covered"))["dR_date_clustered"]["estimate"]
    result = {"rule_sha256": RR_RULE_SHA256,
              "population": {"n_dates": len(scored), "first_date": scored[0], "last_date": scored[-1],
                             "n_market_days": len(table.keys),
                             "four_arm_covered_snapshots": {g: int((four & (table.local_hour >= lo)
                                                                    & (table.local_hour <= hi)).sum())
                                                            for g, lo, hi in groups},
                             "gate4_scope_snapshots_07_12": int((scope4 & w0712).sum()),
                             "gate4_scope_equals_four_arm_and_l6": bool(
                                 ((scope4 & w0712) == (four & cov_l6 & w0712)).all())},
              "controls": {"mg1_excess_07_12": mg1_excess, "ra_reproduction": audit["ra_reproduction"],
                           "l6_part_sha256": part_sha, "l6_nowcast_sha256": now_sha, **l6_controls,
                           "rf_blend_l6_vs_l6_estimate": rf_now,
                           "rf_blend_l6_vs_l6_reported": rf_row["dR_date_clustered"]["estimate"],
                           "rf_reproduced": abs(rf_now - rf_row["dR_date_clustered"]["estimate"]) <= 1e-9,
                           "gate1b": audit["gates"]["1b_parity_dev"]},
              "inputs": {"emit_files": audit["files"], "emit_inputs": audit["inputs"],
                         "emit_audit_sha256": _rr_sha(emit / "rr_emit_audit.json"), "rf_result": _rr_sha(rf_result),
                         "layout_manifest_sha256": lay.manifest_sha256, "scorecard_code_sha256": sc.code_sha256(),
                         "module_sha256": _rr_sha(__file__)},
              "gates": {}, "rows": []}

    def done():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
        return result

    result["rows"] += compare("B_H", "B_N", four, "four_arm")  # reported only
    rows = compare("P3d_H", "P3d_N_fix", four, "four_arm")
    result["rows"] += rows
    g3 = pick(rows)["dR_date_clustered"]
    result["gates"]["3_P3d_H_vs_P3d_N_fix_07_12"] = {"dR_date_clustered": g3, "pass": g3["ci95"][1] < 0}
    if not result["gates"]["3_P3d_H_vs_P3d_N_fix_07_12"]["pass"]:
        result["stopped_at"] = "gate 3 (KILL: HRRR closed as a 07-12 centre input)"
        return done()
    rows = compare("blend_l6_H", "l6", scope4, "covered")
    result["rows"] += rows
    result["gates"]["4_blend_l6_H_vs_l6"] = {
        "reading": reading(rows), "dR_date_clustered": pick(rows)["dR_date_clustered"],
        "hours": {f"h{h:02d}": pick(rows, f"h{h:02d}")["dR_date_clustered"] for h in RR_HOURS}}
    result["rows"] += compare("blend_l6_H", "l6", everything, "blended")
    result["rows"] += compare("P3d_H_l6", "l6", scope4, "covered")
    result["rows"] += compare("P3d_H_l6", "l6", everything, "blended")
    result["rows"] += compare("blend_l6_H", "blend_l6", scope4, "covered")
    result["rows"] += compare("blend_l6_H", "mg1", scope4, "covered", absolute=True)
    result["rows"] += compare("l6", "mg1", scope4, "covered", absolute=True)
    result["weights"] = {name: {f"h{h:02d}": {"mean": float(np.mean([w[(h, d)] for d in scored])),
                                              "first": w[(h, scored[0])], "last": w[(h, scored[-1])]}
                                for h in RR_HOURS} for name, w in weights.items()}
    result["gate5_vs_market_reported"] = {
        arm: {r["group"]: r["R_arm_date_clustered"] for r in compare(arm, "l6", scope4, "covered")
              if r["market"] == sc.ALL_MARKETS}
        for arm in ("P3d_H", "blend_l6_H", "l6")}
    return done()


# ------------------------------------------------- R-S: NBM's own spread as a scale-model input (rule_rs.md)

RS_RULE_SHA256 = "5fb593f4dbfac01fd0c9984ccb29522dbee979f54d27852baadccadcb21d13a2"
RS_COLUMNS = ("nbm_sd", "nbm_qw")
RS_PD_SHA256 = "ae029eda4e4f563dfeaaf21b3d014f19c05116b2697f7d6d4d0dba8a62112fbb"  # predictive_distribution source
RS_SCORECARD_SHA256 = "f69071ac5612f022ade56ada764f813c28da79cd0265848c58041115439005c5"
RS_PINNED = {"FLOOR_MIX_CLIM": 0.02, "MIN_SCALE": 0.5, "KERNEL_BANDWIDTH": 0.25,
             "SCALE_HGB_PARAMS": {"max_iter": 100, "learning_rate": 0.05, "max_leaf_nodes": 7,
                                  "min_samples_leaf": 40, "early_stopping": False, "random_state": 42}}
RS_TRAIN_CORPUS_SHA256 = "1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd"
RS_DEV_CORPUS_SHA256 = "85746b7a560116f632436b24f268938a0a4ec47bf6d748aacba6e0abef257727"
RS_COVERAGE_MIN = 0.95
RS_SD_RANGE = (0.0, 30.0)
RS_QW_RANGE = (0.0, 60.0)
RS_PARITY_MIN = 0.98
RS_PARITY_TOL = 1e-6
RS_GS_BAND = (0.95, 1.05)
RS_ADDENDUM1_SHA256 = "1b930b8ea0db6d2be61237d5fc3c4ab5e7bca6a6abb8db9988bb26445aa5d566"  # guard G-v
RS_GV_BAND = (0.8, 1.25)
RS_S_SPEC = {"simple": False, "extra_scale": RS_COLUMNS}
RS_WINDOWS = {
    "07-12": {
        "hours": RR_HOURS, "primary": ("P3d_H_S", "P3d_H"),
        "arms": {"P3d_N_fix": False, "P3d_H": RK_ARMS["P3d_H"], "P3d_N_fix_S": RS_S_SPEC,
                 "P3d_H_S": {**RK_ARMS["P3d_H"], "extra_scale": RS_COLUMNS}},
        "pairs": {"P3d_H_S": "P3d_H", "P3d_N_fix_S": "P3d_N_fix"},
        "reference_loyo_sha256": "170c61e36d0b4559a91389e01138d622bbccdc00d2091b8a80a21b8eaf7e383e",  # R-R
        "control_arms": ("P3d_N_fix", "P3d_H"),
        "base_dev": {"dev_P3d_H.jsonl": "a2dc30e2b0790ad4cf4ed167c329c00a6c87d4245fb1d6a55d0f80ffdfc14f3d"}},
    "13-16": {
        "hours": RK_HOURS, "primary": ("P3d_N_fix_S", "P3d_N_fix"),
        "arms": {"P3d_N_fix": False, "P3d_N_fix_S": RS_S_SPEC},
        "pairs": {"P3d_N_fix_S": "P3d_N_fix"},
        "reference_loyo_sha256": "bb0bf4943b7105b3f0ded1ec327c80bbdc54d9cbcc657cd10bf50d49eb761ee3",  # R-K
        "control_arms": ("P3d_N_fix",),
        "base_dev": {"dev_P3d_N_fix.jsonl": "abc4350724fe42a5d2423dcf5dd3f1c1b06dcea4799cb0d297bd6de465096109"}},
}


def _rs_finite(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return out if math.isfinite(out) else float("nan")


def rs_pinned_check(with_scorecard=False):
    """Condition 4: the floor censoring / 2% climatology code and the scale constants are byte-identical; refuse."""
    import ast

    src = Path(__file__).read_text(encoding="utf-8")
    node = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == "predictive_distribution")
    got = {"predictive_distribution_sha256": hashlib.sha256(ast.get_source_segment(src, node).encode()).hexdigest(),
           "FLOOR_MIX_CLIM": FLOOR_MIX_CLIM, "MIN_SCALE": MIN_SCALE, "KERNEL_BANDWIDTH": KERNEL_BANDWIDTH,
           "SCALE_HGB_PARAMS": dict(SCALE_HGB_PARAMS)}
    want = {"predictive_distribution_sha256": RS_PD_SHA256, **RS_PINNED}
    if with_scorecard:
        from weather.reporting.scorecards import dev_scorecard as sc

        got["scorecard_code_sha256"] = sc.code_sha256()
        want["scorecard_code_sha256"] = RS_SCORECARD_SHA256
    if got != want:
        raise PooledModelError(f"R-S pinned code differs: {got} != {want}")
    return got


def rs_spread_table(path):
    """{(market, target_date, cycle): (sd, p10, p90, version)} from an NBP PIT corpus (last row per key)."""
    table = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if not r.get("available") or r.get("mean") is None:
            continue
        table[(r["market_id"], r["target_date"], r["cycle"])] = (
            _rs_finite(r.get("sd")), _rs_finite(r.get("p10")), _rs_finite(r.get("p90")),
            str(r.get("product_version")))
    return table


def rs_training_columns(frame, nbm_table, spread, nbm_at_cutoff, timezones):
    """``nbm_sd`` and ``nbm_qw`` = p90 - p10 of the L9 row ``nbm_at_cutoff`` selects (NaN without an anchor)."""
    sd, qw, versions, stats = [], [], [], defaultdict(int)
    for market, day, hour in zip(frame["market"], frame["target_date"], frame["hour"]):
        stats["rows"] += 1
        value, cycle = nbm_at_cutoff(nbm_table, market, str(day)[:10], int(hour), timezones[market])
        if value is None:
            stats["no_anchor"] += 1
            sd.append(float("nan"))
            qw.append(float("nan"))
            versions.append(None)
            continue
        stats["anchor_rows"] += 1
        s_, p10, p90, *rest = spread.get((market, str(day)[:10], cycle), (float("nan"),) * 3)
        versions.append(rest[0] if rest else None)
        q = p90 - p10 if math.isfinite(p10) and math.isfinite(p90) else float("nan")
        for name, v, (lo, hi) in (("sd", s_, RS_SD_RANGE), ("qw", q, RS_QW_RANGE)):
            if math.isfinite(v):
                stats[f"{name}_present"] += 1
                stats[f"{name}_out_of_range"] += not lo <= v <= hi
        sd.append(s_)
        qw.append(q)
    out = frame.copy()
    out["nbm_sd"] = sd
    out["nbm_qw"] = qw
    out["nbm_version"] = versions
    return out, dict(stats)


def rs_parity_training(stats):
    """Gate 1a: coverage >= 0.95 of anchored rows for both columns, and every present value in range."""
    anchored = max(stats.get("anchor_rows", 0), 1)
    coverage = {n: stats.get(f"{n}_present", 0) / anchored for n in ("sd", "qw")}
    checks = {"sd_coverage": coverage["sd"] >= RS_COVERAGE_MIN, "qw_coverage": coverage["qw"] >= RS_COVERAGE_MIN,
              "sd_in_range": stats.get("sd_out_of_range", 0) == 0, "qw_in_range": stats.get("qw_out_of_range", 0) == 0}
    return {"coverage": coverage, "threshold": RS_COVERAGE_MIN, "checks": checks, "pass": all(checks.values())}


def _rs_cycle(key):
    """'nbm-nbp:20260801T01Z' -> '2026-08-01T01' (the issuance hour), else None."""
    text = str(key or "")
    if not text.startswith("nbm-nbp:") or len(text) != len("nbm-nbp:20260801T01Z"):
        return None
    d = text[len("nbm-nbp:"):]
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]}T{d[9:11]}"


def rs_dev_population(layout, hours, markets=R0_MARKETS):
    """Gate 1b / G-v dev rows: window cutoff hours, local_hour >= cutoff, usable captured v2 mean, 07-30..09-29."""
    import numpy as np
    import pandas as pd

    from weather.calibration.r0_ols_floor_devfit import usable_v2_mean

    snaps = pd.read_parquet(Path(layout) / "inputs_snapshots.parquet", columns=[
        "market", "target_date", "local_hour", "cutoff_hour", "v2_mean", "v2_stddev", "v2_available_at",
        "captured_at_utc", "v2_p10", "v2_p90", "v2_cycle_key"])
    if (pd.to_datetime(snaps.target_date).dt.date > N_DEV_LAST).any():
        raise PooledModelError("layout holds a snapshot after 2026-09-29")
    usable = usable_v2_mean(snaps)
    hour = pd.to_numeric(snaps.cutoff_hour, errors="coerce").to_numpy(float)
    day = pd.to_datetime(snaps.target_date).dt.date
    keep = (np.isfinite(usable) & np.isin(hour, list(hours)) & (snaps.local_hour.to_numpy(float) >= hour)
            & snaps.market.isin(list(markets)).to_numpy() & (day >= N_DEV_FIRST).to_numpy()
            & (day <= N_DEV_LAST).to_numpy())
    return snaps[keep].reset_index(drop=True)


def _rs_describe(values):
    import numpy as np

    arr = np.asarray([v for v in values if v is not None and math.isfinite(float(v))], dtype=float)
    if not len(arr):
        return {"n": 0}
    q = np.quantile(arr, [0.1, 0.25, 0.5, 0.75, 0.9])
    return {"n": int(len(arr)), "mean": float(arr.mean()), "p10": float(q[0]), "p25": float(q[1]),
            "median": float(q[2]), "p75": float(q[3]), "p90": float(q[4])}


def rs_era_guard(frame, dev, window):
    """Guard G-v (addendum 1): nbm_sd / nbm_qw by NBM version and year vs dev 2026; median ratios in [0.8, 1.25]."""
    import numpy as np

    cfg = _rs_window(window)
    anchored = frame[frame["nbm_version"].notna()]
    dev_cols = {"nbm_sd": dev["v2_stddev"].to_numpy(float),
                "nbm_qw": dev["v2_p90"].to_numpy(float) - dev["v2_p10"].to_numpy(float)}
    dev_hour = np.array([int(float(h)) for h in dev["cutoff_hour"]]) if len(dev) else np.array([], int)
    out = {"addendum1_sha256": RS_ADDENDUM1_SHA256, "band": list(RS_GV_BAND), "columns": {}}
    ok = True
    for col in RS_COLUMNS:
        cells = {"train_all": _rs_describe(anchored[col]), "dev_2026": _rs_describe(dev_cols[col])}
        for (year, version), part in anchored.groupby([anchored["year"], anchored["nbm_version"]]):
            cells[f"train_{int(year)}_v{version}"] = _rs_describe(part[col])
        for h in cfg["hours"]:
            cells[f"train_all|h{h:02d}"] = _rs_describe(anchored.loc[anchored["hour"] == h, col])
            cells[f"dev_2026|h{h:02d}"] = _rs_describe(dev_cols[col][dev_hour == h])
        t_med = cells["train_all"].get("median")
        d_med = cells["dev_2026"].get("median")
        ratio = d_med / t_med if t_med and d_med is not None else None
        in_band = ratio is not None and RS_GV_BAND[0] <= ratio <= RS_GV_BAND[1]
        ok = ok and in_band
        out["columns"][col] = {"cells": cells, "ratio_dev_over_train_median": ratio, "in_band": in_band}
    out["pass"] = ok
    return out


def rs_parity_dev(layout, nbm_dev_corpus, hours, markets=R0_MARKETS):
    """Gate 1b (outcome-free): captured v2_stddev / v2_p10 / v2_p90 vs the dev NBP row of the captured cycle."""
    sha = _rr_sha(nbm_dev_corpus)
    if sha != RS_DEV_CORPUS_SHA256:
        raise PooledModelError(f"dev NBP corpus sha {sha} != {RS_DEV_CORPUS_SHA256}")
    corpus = {}
    for line in Path(nbm_dev_corpus).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if not r.get("available") or r.get("mean") is None or r["target_date"] > N_DEV_LAST.isoformat():
            continue
        corpus[(r["market_id"], r["target_date"], str(r["issued_at"])[:13])] = r
    counts = defaultdict(int)
    per_hour = defaultdict(lambda: defaultdict(int))
    for row in rs_dev_population(layout, hours, markets).itertuples(index=False):
        h = f"h{int(float(row.cutoff_hour)):02d}"
        counts["rows"] += 1
        per_hour[h]["rows"] += 1
        cycle = _rs_cycle(row.v2_cycle_key)
        ref = None if cycle is None else corpus.get((row.market, str(row.target_date)[:10], cycle))
        if ref is None:
            counts["no_corpus_row"] += 1
            per_hour[h]["no_corpus_row"] += 1
            continue
        for name, captured, corp in (("sd", row.v2_stddev, ref.get("sd")), ("p10", row.v2_p10, ref.get("p10")),
                                     ("p90", row.v2_p90, ref.get("p90"))):
            a, b = _rs_finite(captured), _rs_finite(corp)
            ok = math.isfinite(a) and math.isfinite(b) and abs(a - b) <= RS_PARITY_TOL
            counts[f"{name}_match"] += ok
            per_hour[h][f"{name}_match"] += ok
    share = {n: counts.get(f"{n}_match", 0) / max(counts["rows"], 1) for n in ("sd", "p10", "p90")}
    return {"rows": counts["rows"], "counts": dict(counts), "share": share, "threshold": RS_PARITY_MIN,
            "tolerance_f": RS_PARITY_TOL, "per_hour": {h: dict(v) for h, v in sorted(per_hour.items())},
            "nbm_dev_corpus_sha256": sha,
            "pass": counts["rows"] > 0 and all(v >= RS_PARITY_MIN for v in share.values())}


def _rs_window(window):
    if window not in RS_WINDOWS:
        raise PooledModelError(f"unknown R-S window {window}")
    return RS_WINDOWS[window]


def _rs_training_frame(window, records_root, nbm_train_corpus, hrrr_corpus, land, markets, audit):
    """The base rung's own training frame (R-R at 07-12, R-K at 13-16) plus the two R-S columns."""
    from weather.calibration import ols_floor_ladder as l9
    from weather.market.market_registry import spec_for_id

    cfg = _rs_window(window)
    sha = _rr_sha(nbm_train_corpus)
    if sha != RS_TRAIN_CORPUS_SHA256:
        raise PooledModelError(f"L9 training corpus sha {sha} != {RS_TRAIN_CORPUS_SHA256}")
    timezones = {m: spec_for_id(m).timezone for m in markets}
    frame, buckets = dev_training_frame(records_root, markets)
    if frame["year"].max() >= 2026:
        raise PooledModelError("a training row is from 2026")
    table = l9.load_nbm(nbm_train_corpus)
    frame, audit["train_nbm"] = attach_training_nbm(frame, table, l9.nbm_at_cutoff, timezones)
    frame = frame[frame["hour"].isin(cfg["hours"])].reset_index(drop=True)
    if window == "07-12":
        corpus = Path(hrrr_corpus)
        audit["inputs"].update({f"hrrr_{n}": s for n, s in rr_verify_corpus(corpus).items()})
        point, audit["point_rule"] = rr_point_rule(land, corpus, markets)
        hrrr, audit["hrrr_corpus_stats"] = rk_hrrr_columns(corpus, markets, hours=RR_HOURS, point=point,
                                                           day_filter=_rr_train_day)
        frame, audit["training_hrrr"] = rk_training_columns(frame, hrrr)
    frame, audit["training_spread"] = rs_training_columns(frame, table, rs_spread_table(nbm_train_corpus),
                                                          l9.nbm_at_cutoff, timezones)
    return frame, buckets


def rs_guard(frame, window):
    """Guard G-s: s_new / s_old on each S arm's full-training OOF rows, pooled over the window's hours."""
    import numpy as np

    cfg = _rs_window(window)
    out = {}
    for arm in cfg["pairs"]:
        ratios = np.concatenate([
            _rung_entry(frame[frame["hour"] == h].reset_index(drop=True), *_arm_spec(cfg["arms"][arm]))
            ["fit"]["gs_ratio"] for h in cfg["hours"]])
        out[arm] = {"median": float(np.median(ratios)), "mean": float(np.mean(ratios)),
                    "p10": float(np.quantile(ratios, 0.1)), "p90": float(np.quantile(ratios, 0.9)),
                    "n": int(len(ratios)), "band": list(RS_GS_BAND),
                    "in_band": bool(RS_GS_BAND[0] <= float(np.median(ratios)) <= RS_GS_BAND[1])}
    primary = cfg["primary"][0]
    return {"arms": out, "primary": primary, "pass": out[primary]["in_band"]}


def rung_s_loyo(*, window, records_root, nbm_train_corpus, reference_loyo_rows, layout, out_dir, hrrr_corpus=None,
                land=None, markets=R0_MARKETS):
    """R-S gate 1a, guard G-v (addendum 1), guard G-s, control C-mean, the base-rung LOYO control and gate 2.

    ``layout`` is read for inputs only (captured v2 spread, G-v); no label, outcome or price is read here.
    """
    cfg = _rs_window(window)
    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise PooledModelError(f"refusing to write into a non-empty {out}")
    ref_sha = _rr_sha(reference_loyo_rows)
    if ref_sha != cfg["reference_loyo_sha256"]:
        raise PooledModelError(f"reference loyo rows sha {ref_sha} != {cfg['reference_loyo_sha256']}")
    audit = {"rule_sha256": RS_RULE_SHA256, "addendum1_sha256": RS_ADDENDUM1_SHA256, "window": window,
             "arms": list(cfg["arms"]),
             "primary": list(cfg["primary"]), "hours": list(cfg["hours"]), "gates": {},
             "pinned": rs_pinned_check(),
             "inputs": {"nbm_train_corpus": _rr_sha(nbm_train_corpus), "reference_loyo_rows": ref_sha,
                        "module_sha256": _rr_sha(__file__)}}

    def finish():
        (out / "rs_loyo_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True), encoding="utf-8")
        return audit

    frame, buckets = _rs_training_frame(window, records_root, nbm_train_corpus, hrrr_corpus, land, markets, audit)
    audit["gates"]["1a_parity_training"] = rs_parity_training(audit["training_spread"])
    if not audit["gates"]["1a_parity_training"]["pass"]:
        audit["stopped_at"] = "gate 1a parity (training half; not a kill)"
        return finish()
    audit["guard_gv"] = rs_era_guard(frame, rs_dev_population(layout, cfg["hours"], markets), window)
    if not audit["guard_gv"]["pass"]:
        audit["stopped_at"] = "era shift (G-v; addendum 1, not a kill)"
        return finish()
    audit["guard_gs"] = rs_guard(frame, window)
    if not audit["guard_gs"]["pass"]:
        audit["stopped_at"] = "guard G-s: global width shift (not a kill)"
        return finish()
    c_mean = {}
    rows = rung_loyo(frame, buckets, cfg["hours"], arms=cfg["arms"], mean_pairs=cfg["pairs"], mean_out=c_mean)
    _write_jsonl(out / "loyo_rows.jsonl", rows)
    audit["control_c_mean"] = {"max_abs_diff": c_mean, "pass": bool(c_mean) and all(v == 0.0 for v in c_mean.values())}
    audit["control_base_reproduction"] = rk_control(rows, _read_jsonl(reference_loyo_rows), arms=cfg["control_arms"],
                                                    hours=cfg["hours"])
    if not audit["control_c_mean"]["pass"]:
        audit["stopped_at"] = "control C-mean failed (refused, not a gate)"
        return finish()
    if not audit["control_base_reproduction"]["pass"]:
        audit["stopped_at"] = "control: base-rung LOYO reproduction failed (refused, not a gate)"
        return finish()
    audit["gates"]["2_loyo"] = rg_loyo_summary(rows, pairs=tuple(cfg["pairs"].items()), pooled=((window, None),))
    s_arm, base = cfg["primary"]
    primary = audit["gates"]["2_loyo"][f"{s_arm}-{base}|{window}|brier"]
    audit["gates"]["2_loyo"]["pass"] = primary["ci95"][1] < 0
    if not audit["gates"]["2_loyo"]["pass"]:
        audit["stopped_at"] = f"gate 2 LOYO (KILL: NBM spread closed as a {window} scale input)"
    return finish()


def rung_s_dev_emit(*, window, records_root, layout, replay_root, nbm_train_corpus, nbm_dev_corpus, loyo_audit,
                    out_dir, hrrr_corpus=None, land=None, markets=R0_MARKETS):
    """R-S gate 1b (outcome-free, before any dev fit) and the window's dev distributions (no scoring)."""
    cfg = _rs_window(window)
    out = require_output_outside_repo(out_dir)
    loyo = json.loads(Path(loyo_audit).read_bytes())
    if (loyo.get("rule_sha256") != RS_RULE_SHA256 or loyo.get("addendum1_sha256") != RS_ADDENDUM1_SHA256
            or loyo.get("window") != window or loyo.get("stopped_at") or not loyo["guard_gv"]["pass"]
            or not loyo["gates"]["2_loyo"]["pass"]):
        raise PooledModelError(f"R-S gates 1a-2 did not pass for {window}: {loyo.get('stopped_at')}")
    rs = {"rule_sha256": RS_RULE_SHA256, "window": window, "loyo_audit_sha256": _rr_sha(loyo_audit),
          "pinned": rs_pinned_check(), "gates": {}, "inputs": {}}
    out.mkdir(parents=True, exist_ok=True)

    def finish():
        (out / "rs_emit_audit.json").write_text(json.dumps(rs, indent=1, sort_keys=True), encoding="utf-8")
        return rs

    rs["gates"]["1b_parity_dev"] = rs_parity_dev(layout, nbm_dev_corpus, cfg["hours"], markets)
    if not rs["gates"]["1b_parity_dev"]["pass"]:
        rs["stopped_at"] = "gate 1b parity (dev half; not a kill)"
        return finish()
    from weather.calibration import ols_floor_ladder as l9
    from weather.market.market_registry import spec_for_id

    sha = _rr_sha(nbm_train_corpus)
    if sha != RS_TRAIN_CORPUS_SHA256:
        raise PooledModelError(f"L9 training corpus sha {sha} != {RS_TRAIN_CORPUS_SHA256}")
    rs["inputs"]["nbm_train_corpus"] = sha
    timezones = {m: spec_for_id(m).timezone for m in markets}
    table = l9.load_nbm(nbm_train_corpus)
    spread = rs_spread_table(nbm_train_corpus)
    train_hrrr = None
    row_hook = None
    if window == "07-12":
        corpus = Path(hrrr_corpus)
        rs["inputs"].update({f"hrrr_{n}": s for n, s in rr_verify_corpus(corpus).items()})
        point, rs["point_rule"] = rr_point_rule(land, corpus, markets)
        train_hrrr, rs["hrrr_train_corpus_stats"] = rk_hrrr_columns(corpus, markets, hours=RR_HOURS, point=point,
                                                                    day_filter=_rr_train_day)
        dev_hrrr, rs["hrrr_dev_corpus_stats"] = rk_hrrr_columns(corpus, markets, hours=RR_HOURS, point=point,
                                                                day_filter=_rr_dev_day)

        def row_hook(market, target, hour, nbm, stats):
            values = rk_columns(dev_hrrr.get((market, target.isoformat(), int(hour))), nbm)
            stats["hrrr_rows"] += 1
            stats["hrrr_covered"] += values["k_miss"] == 0.0
            return values

    def snap_hook(row, stats):
        sd = _rs_finite(row.v2_stddev)
        qw = _rs_finite(row.v2_p90) - _rs_finite(row.v2_p10)
        stats["spread_rows"] += 1
        stats["spread_sd_present"] += math.isfinite(sd)
        stats["spread_qw_present"] += math.isfinite(qw)
        stats["spread_sd_lt_1f"] += math.isfinite(sd) and sd < 1.0
        return {"nbm_sd": sd, "nbm_qw": qw}

    def train_hook(f):
        stats = {}
        if train_hrrr is not None:
            f, stats["hrrr"] = rk_training_columns(f, train_hrrr)
        f, stats["spread"] = rs_training_columns(f, table, spread, l9.nbm_at_cutoff, timezones)
        stats["gate_1a_on_emit_frame"] = rs_parity_training(stats["spread"])
        return f, stats

    audit = dev_emit_rung(records_root=records_root, layout=layout, replay_root=replay_root,
                          nbm_train_corpus=nbm_train_corpus, out_dir=out, markets=markets, hours=cfg["hours"],
                          loyo=False, arms=cfg["arms"], train_hook=train_hook,
                          row_hook=row_hook, snap_columns=("v2_p10", "v2_p90"), snap_hook=snap_hook,
                          mean_pairs=cfg["pairs"])
    rs["training"] = audit.get("train_hook")
    rs["files"] = audit["files"]
    rs["markets"] = audit["markets"]
    rs["base_reproduction"] = {name: audit["files"].get(name) == sha for name, sha in cfg["base_dev"].items()}
    rs["control_c_mean"] = {"max_abs_diff": audit.get("c_mean", {}),
                            "pass": bool(audit.get("c_mean")) and all(v == 0.0 for v in audit["c_mean"].values())}
    if not all(rs["base_reproduction"].values()):
        rs["stopped_at"] = "control: base dev files do not reproduce (refused, not a gate)"
    elif not rs["control_c_mean"]["pass"]:
        rs["stopped_at"] = "control C-mean failed on dev (refused, not a gate)"
    return finish()


def _rs_band_pit(table, p, keep_snap):
    """Band-midpoint PIT of the winning band per snapshot (bands in index order), for snapshots in ``keep_snap``."""
    import numpy as np

    csum = np.cumsum(p)
    start = np.repeat(csum[table.offsets] - p[table.offsets], table.n)
    hi = csum - start
    mid = hi - p / 2.0
    win = table.y > 0
    snap = table.band_snap[win]
    return mid[win][keep_snap[snap]]


def _rs_sharpness(path):
    """Mean predictive SD (deg) over an emitted distribution file."""
    import numpy as np

    sds = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        dist = json.loads(line)["distribution"]
        t = np.array([float(k) for k in dist])
        w = np.array(list(dist.values()), dtype=float)
        w = w / w.sum()
        m = float((t * w).sum())
        sds.append(math.sqrt(float(((t - m) ** 2 * w).sum())))
    return {"mean_sd": float(np.mean(sds)) if sds else None, "n": len(sds)}


def rung_s_score(*, layout, emit_dirs, coefficients=None, nowcasts=None, out_path, start="2026-08-01",
                 end="2026-09-29"):
    """R-S gate 3 (kill) and gate 4 (drafts only) per window on the dev scorecard; ``emit_dirs`` {window: dir}."""
    import os

    import numpy as np

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas

    out_path = require_output_outside_repo(out_path)
    if out_path.exists():
        raise PooledModelError(f"refusing to overwrite {out_path}")
    pinned = rs_pinned_check(with_scorecard=True)
    start_d, end_d = data.check_range(start, end)
    if end_d > N_DEV_LAST:
        raise PooledModelError("R-S dev labels end at 2026-09-29")
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    table = sc.Table(lay, scored)
    date_w = l3._date_weights([k[0] for k in table.keys], sc.DRAWS, sc.SEED)
    market_b = table.brier(table.p_market)
    p_mg1, cov_mg1, _ = l3._vector(table, loss_atlas.mg1_frame(table))
    w0712 = (table.local_hour >= 7) & (table.local_hour <= 12)
    _, e = table.cells(table.brier(p_mg1) - market_b, w0712)
    mg1_excess = float(e.mean())
    if round(mg1_excess, 3) != l3.MG1_CONTROL_0712_EXCESS:
        raise PooledModelError(f"MG-1 positive control failed: {mg1_excess:.5f}")
    everything = np.ones(len(table.snaps), dtype=bool)
    pools = [(sc.ALL_MARKETS, None)] + [(m, {m}) for m in sorted(set(table.markets))]
    result = {"rule_sha256": RS_RULE_SHA256, "pinned": pinned,
              "population": {"n_dates": len(scored), "first_date": scored[0], "last_date": scored[-1],
                             "n_market_days": len(table.keys)},
              "controls": {"mg1_excess_07_12": mg1_excess},
              "inputs": {"layout_manifest_sha256": lay.manifest_sha256, "scorecard_code_sha256": sc.code_sha256(),
                         "module_sha256": _rr_sha(__file__)},
              "windows": {}}
    briers, covs, probs = {"mg1": table.brier(p_mg1)}, {"mg1": cov_mg1}, {}

    def compare(arm, ref, scope, window, hours, absolute=False):
        groups = [(window, hours[0], hours[-1])] + [(f"h{h:02d}", h, h) for h in hours]
        rows = []
        for market, members in pools:
            in_pool = everything if members is None else np.isin(table.markets, sorted(members))
            for group, lo, hi in (groups if members is None else groups[:1]):
                mask = scope & in_pool & (table.local_hour >= lo) & (table.local_hour <= hi)
                if not mask.any():
                    continue
                idx, c = table.cells(briers[arm], mask)
                _, r_ = table.cells(briers[ref], mask)
                _, m = table.cells(market_b, mask)
                row = {"arm": arm, "reference": ref, "market": market, "group": group,
                       "n_market_days": int(len(idx)), "n_snapshots": int(mask.sum()),
                       "R_arm": sc.ratio_interval(table.w[:, idx], c, m),
                       "R_reference": sc.ratio_interval(table.w[:, idx], r_, m),
                       "dR_crossed": sc.ratio_interval(table.w[:, idx], c - r_, m),
                       "dR_date_clustered": sc.ratio_interval(date_w[:, idx], c - r_, m)}
                if absolute:
                    row["brier_diff_w_date"] = sc.ratio_interval(table.w_date[:, idx], c - r_, np.ones(len(idx)))
                rows.append(row)
        return rows

    def pick(rows, group):
        return next(r for r in rows if r["market"] == sc.ALL_MARKETS and r["group"] == group)

    def reading(rows, window, hours):
        p = pick(rows, window)["dR_date_clustered"]["ci95"]
        lower = [pick(rows, f"h{h:02d}")["dR_date_clustered"]["ci95"][0] for h in hours]
        if p[0] > 0:
            return "HARM"
        return "WIN" if p[1] < 0 and not any(lo > 0 for lo in lower) else "NULL"

    for window, emit_dir in sorted(emit_dirs.items()):
        cfg = _rs_window(window)
        hours = cfg["hours"]
        emit = Path(emit_dir)
        audit = json.loads((emit / "rs_emit_audit.json").read_bytes())
        if audit.get("rule_sha256") != RS_RULE_SHA256 or audit.get("window") != window or audit.get("stopped_at"):
            raise PooledModelError(f"{window}: not an R-S emit that passed gate 1b and controls: "
                                   f"{audit.get('stopped_at')}")
        if not all(audit["base_reproduction"].values()) or not audit["control_c_mean"]["pass"]:
            raise PooledModelError(f"{window}: base reproduction or C-mean failed")
        res = {"emit_audit_sha256": _rr_sha(emit / "rs_emit_audit.json"), "emit_files": audit["files"],
               "controls": {"base_reproduction": audit["base_reproduction"], "c_mean": audit["control_c_mean"],
                            "gate1b": audit["gates"]["1b_parity_dev"]["share"]},
               "gates": {}, "rows": [], "reported": {}}
        result["windows"][window] = res
        for arm in cfg["arms"]:
            p, c, _ = l3._vector(table, l3._candidate_frame(str(emit / f"dev_{arm}.jsonl"), table, lay, folds,
                                                            data)[0])
            name = f"{window}:{arm}"
            briers[name], covs[name], probs[name] = table.brier(p), c, p
        in_w = (table.local_hour >= hours[0]) & (table.local_hour <= hours[-1])
        s_arm, base = cfg["primary"]
        for arm, ref in cfg["pairs"].items():
            a, b = f"{window}:{arm}", f"{window}:{ref}"
            rows = compare(a, b, covs[a] & covs[b], window, hours)
            res["rows"] += rows
            if arm == s_arm:
                g3 = pick(rows, window)["dR_date_clustered"]
                res["gates"]["3_dev"] = {"pair": f"{arm}-{ref}", "dR_date_clustered": g3, "pass": g3["ci95"][1] < 0}
            else:
                res["reported"][f"secondary_{arm}-{ref}"] = pick(rows, window)["dR_date_clustered"]
        for arm in cfg["arms"]:
            name = f"{window}:{arm}"
            pit = _rs_band_pit(table, probs[name], covs[name] & in_w)
            res["reported"][f"calibration_{arm}"] = {
                "n": int(len(pit)), "pit_mean": float(np.mean(pit)) if len(pit) else None,
                **{f"central_{int(x * 100)}_coverage": float(np.mean(np.abs(pit - 0.5) <= x / 2)) if len(pit)
                   else None for x in (0.5, 0.8, 0.9)}}
            res["reported"][f"sharpness_{arm}"] = _rs_sharpness(emit / f"dev_{arm}.jsonl")
        spread = defaultdict(int)
        for stats in audit["markets"].values():
            for k in ("spread_rows", "spread_sd_lt_1f", "spread_sd_present", "spread_qw_present"):
                spread[k] += stats.get(k, 0)
        res["reported"]["nbm_sd_lt_1f_share"] = spread["spread_sd_lt_1f"] / max(spread["spread_rows"], 1)
        res["reported"]["spread_counts"] = dict(spread)
        if not res["gates"]["3_dev"]["pass"]:
            res["stopped_at"] = f"gate 3 (KILL: NBM spread closed as a {window} scale input)"
            continue
        if window == "07-12":
            if coefficients is None or nowcasts is None:
                raise PooledModelError("07-12 gate 4 needs the frozen L6 coefficients and nowcasts")
            now_sha = _rr_sha(nowcasts)
            if now_sha != L6_NOWCAST_SHA256:
                raise PooledModelError(f"L6 nowcast sha {now_sha} != {L6_NOWCAST_SHA256}")
            os.environ["L6_NOWCASTS"] = str(nowcasts)
            from weather.reporting.scorecards.free_source_candidates import l6_stack

            l6_stack._CACHE.clear()
            state, part_sha = l6_frozen_state(coefficients)
            fit_dates = sorted(d for d in {str(x) for x in lay.dates} if BLEND_FIT_FIRST <= d <= end)
            full = sc.Table(lay, fit_dates)
            fdates = full.snaps.date.astype(str).to_numpy()
            pl, cl, _ = l6_vector(full, state, l3)
            p_l6, cov_l6, _ = l6_vector(table, state, l3)
            briers["l6"], covs["l6"] = table.brier(p_l6), cov_l6
            dates = table.snaps.date.astype(str).to_numpy()
            weights = {}
            for name, cand in (("blend_l6_HS", "P3d_H_S"), ("blend_l6_H", "P3d_H")):
                pa, ca, _ = l3._vector(full, l3._candidate_frame(str(emit / f"dev_{cand}.jsonl"), full, lay, folds,
                                                                 data)[0])
                A, B = blend_weight(pa, pl, full.y, full.offsets, full.n)
                weights[name] = walk_forward_weights(fdates, full.local_hour, ca & cl, A, B, scored)
                c = covs[f"{window}:{cand}"]
                w_snap = np.array([weights[name].get((int(h), d), 0.0) for h, d in zip(table.local_hour, dates)])
                wb = np.where(c & cov_l6, w_snap, 0.0)[table.band_snap]
                briers[name] = table.brier(wb * probs[f"{window}:{cand}"] + (1.0 - wb) * p_l6)
                covs[name] = cov_l6
            scope4 = covs["07-12:P3d_H_S"] & covs["07-12:P3d_H"] & cov_l6
            rows = compare("blend_l6_HS", "l6", scope4, window, hours)
            res["rows"] += rows
            res["gates"]["4_blend_l6_HS_vs_l6"] = {
                "reading": reading(rows, window, hours), "dR_date_clustered": pick(rows, window)["dR_date_clustered"],
                "hours": {f"h{h:02d}": pick(rows, f"h{h:02d}")["dR_date_clustered"] for h in hours}}
            inc = compare("blend_l6_HS", "blend_l6_H", scope4, window, hours)
            res["rows"] += inc
            res["reported"]["blend_l6_HS-blend_l6_H"] = pick(inc, window)["dR_date_clustered"]
            res["controls"].update(l6_part_sha256=part_sha, l6_nowcast_sha256=now_sha)
            res["weights"] = {name: {f"h{h:02d}": float(np.mean([w[(h, d)] for d in scored])) for h in hours}
                              for name, w in weights.items()}
        else:
            for name, arm in (("composite_post13_asof", "13-16:P3d_N_fix"), ("P3d_N_fix_S_mg1", "13-16:P3d_N_fix_S")):
                briers[name] = table.brier(np.where(covs[arm][table.band_snap], probs[arm], p_mg1))
                covs[name] = covs[arm] | cov_mg1
            scope4 = covs["composite_post13_asof"] & covs["P3d_N_fix_S_mg1"]
            rows = compare("P3d_N_fix_S_mg1", "composite_post13_asof", scope4, window, hours)
            res["rows"] += rows
            res["gates"]["4_vs_composite_post13_asof"] = {
                "reading": reading(rows, window, hours), "dR_date_clustered": pick(rows, window)["dR_date_clustered"]}
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


# ------------------------------------------------- MG-3 freeze prep (1a): frozen P3d_H states and blend weights

MG3_STATE_RULE_SHA256 = "9e63899ddcfcbd795f10f0437c7bd9f9b6fc9740767b8d824818ef0f7f95cc5d"  # rule_mg3_p3dh_state.md
MG3_WEIGHTS_RULE_SHA256 = "4fb02a2cec9a6c5c4fc06e811bd69d3ba35721d0650475c8584de313765ef6e8"  # rule_mg3_blend_weights.md
MG3_STATE_SCHEMA = "mg3_p3d_h_state/1"
MG3_ARM = "P3d_H"
MG3_CONTROL_TOL = 1e-12
MG3_EXPORT_TOL = 1e-9
MG3_BLOCKS = {
    "07-12": {"hours": RR_HOURS, "rule_sha256": RR_RULE_SHA256, "point": "rn1",
              "reference_sha256": "a2dc30e2b0790ad4cf4ed167c329c00a6c87d4245fb1d6a55d0f80ffdfc14f3d"},
    "13-16": {"hours": RK_HOURS, "rule_sha256": RK_RULE_SHA256, "point": "nearest",
              "reference_sha256": "e5195945cd8a24db178cd8b85e0af8914c95321b581a65897e8cac59eb451da1"},
}
MG3_RR_SCORE_SHA256 = "577b689b6285d6125357b4f658351deaf1c47171352753f6956d29b278261dab"
MG3_RR_EMIT = {"dev_P3d_H.jsonl": MG3_BLOCKS["07-12"]["reference_sha256"], "dev_P3d_N_fix.jsonl": RI_FIX_SHA256}


def _mg3_hrrr(block, hrrr_corpus, hrrr_dev_corpus, land, markets):
    """The block's training and dev HRRR columns, built exactly as its rung's dev emit built them."""
    if block == "07-12":
        if land is None:
            raise PooledModelError("the 07-12 block needs the RN-1 land file")
        corpus = Path(hrrr_corpus)
        shas = rr_verify_corpus(corpus)
        point, point_report = rr_point_rule(land, corpus, markets)
        train, train_stats = rk_hrrr_columns(corpus, markets, hours=RR_HOURS, point=point, day_filter=_rr_train_day)
        dev, dev_stats = rk_hrrr_columns(corpus, markets, hours=RR_HOURS, point=point, day_filter=_rr_dev_day)
        inputs = {f"hrrr_{n}": s for n, s in shas.items()}
        point_rule = {"rule": "RN-1 nearest land cell (rr_point_rule)", "land_sha256": _rr_sha(land),
                      "report": point_report}
    elif block == "13-16":
        if hrrr_dev_corpus is None:
            raise PooledModelError("the 13-16 block needs the 2026 dev HRRR corpus")
        train, train_stats = rk_hrrr_columns(hrrr_corpus, markets)
        dev, dev_stats = rk_hrrr_columns(hrrr_dev_corpus, markets)
        inputs = {f"{tag}_{n}": _rr_sha(Path(root) / n)
                  for tag, root in (("hrrr_train", hrrr_corpus), ("hrrr_dev", hrrr_dev_corpus))
                  for n in ("manifest.jsonl", "selections.jsonl", "stations.json")}
        point_rule = {"rule": "nearest cell (R-K as fitted)", "land_sha256": None, "report": None}
    else:
        raise PooledModelError(f"unknown MG-3 block {block}")
    late = sorted(k for k in dev if date.fromisoformat(k[1]) > N_DEV_LAST)
    if late:
        raise PooledModelError(f"dev HRRR holds a date after 2026-09-29: {late[0]}")
    return train, dev, {"inputs": inputs, "point_rule": point_rule, "train_stats": train_stats,
                        "dev_stats": dev_stats}


def mg3_hour_entry(entry):
    """One hour of the frozen state from a ``_rung_entry`` fit: mean (plus its extra columns), scale, z, train_y."""
    import numpy as np

    model = entry["fit"]["mean"]
    mean = state_mean_dict(model)
    mean["extra_hgb"] = list(model.extra_hgb)
    mean["extra_ols"] = list(model.extra_ols)
    return {"mean": mean, "scale": entry["fit"]["scale"], "z": np.asarray(entry["fit"]["z"], dtype=np.float64),
            "train_y": {m: list(v) for m, v in entry["train_y"].items()}}


def mg3_state_X(state, hour, *, market, target_date, high_so_far, current_temp, nbm_mean, extra):
    """The frozen state's X row: ``state_features`` plus the ``extra_hgb`` columns in order. -> (X, mu0, g, F)."""
    import numpy as np

    X, mu0, g, floor = state_features(state, hour, market=market, target_date=target_date, high_so_far=high_so_far,
                                      current_temp=current_temp, nbm_mean=nbm_mean)
    tail = np.asarray([[float(extra[c]) for c in state["extra_hgb"]]], dtype=float)
    return np.column_stack([X, tail]), mu0, g, floor


def mg3_state_distribution(state, hour, *, market, target_date, high_so_far, current_temp, nbm_mean, extra):
    """Serve math from a frozen ``mg3_p3d_h_state/1`` state only (rule_mg3_p3dh_state.md section 2)."""
    import numpy as np

    from weather.calibration import feature_model as fm

    X, mu0, g, floor = mg3_state_X(state, hour, market=market, target_date=target_date, high_so_far=high_so_far,
                                   current_temp=current_temp, nbm_mean=nbm_mean, extra=extra)
    entry = state["hours"][int(hour)]
    mean = entry["mean"]
    if mean.get("extra_ols"):
        raise PooledModelError("an MG-3 P3d_H state has no extra OLS columns")
    yhat = float((mu0 + np.array([[1.0, g, max(g, 0.0)]]) @ mean["ols"] + mean["hgb"].predict(X))[0])
    c = state["constants"]
    s = max(c["min_scale"],
            float(entry["scale"].predict(np.column_stack([X, [yhat - floor]]))[0]) * math.sqrt(math.pi / 2))
    p_clim = fm.smoothed_dist(entry["train_y"][market], state["buckets"][market], alpha=c["clim_alpha"])
    return predictive_distribution(yhat, s, floor, entry["z"], state["buckets"][market], p_clim)


def mg3_load_state(path, expected_sha256):
    """Research-side control load: unpickle only after the file sha256 equals the bound value."""
    import pickle as _pickle

    blob = Path(path).read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    if digest != expected_sha256:
        raise PooledModelError(f"MG-3 state {path}: sha256 {digest} != bound {expected_sha256}")
    state = _pickle.loads(blob)
    if state.get("schema") != MG3_STATE_SCHEMA or state.get("arm") != MG3_ARM:
        raise PooledModelError(f"MG-3 state {path}: schema or arm mismatch")
    return state


def _mg3_compare_jsonl(path, reference):
    """Line-by-line: same keys and max |p - p_ref| over the union of bands. -> report dict."""
    got = Path(path).read_text(encoding="utf-8").splitlines()
    ref = Path(reference).read_text(encoding="utf-8").splitlines()
    worst, first_bad, key_mismatch = 0.0, None, 0
    for i, (a, b) in enumerate(zip(got, ref)):
        ra, rb = json.loads(a), json.loads(b)
        if (ra["market"], ra["snapshot_id"], ra["target_date"]) != (rb["market"], rb["snapshot_id"], rb["target_date"]):
            key_mismatch += 1
            first_bad = first_bad if first_bad is not None else i
            continue
        da, db = ra["distribution"], rb["distribution"]
        diff = max(abs(float(da.get(k, 0.0)) - float(db.get(k, 0.0))) for k in set(da) | set(db))
        if diff > worst:
            worst = diff
        if diff > MG3_CONTROL_TOL and first_bad is None:
            first_bad = i
    return {"rows": len(got), "reference_rows": len(ref), "key_mismatch": key_mismatch, "max_abs_dp": worst,
            "first_bad_line": first_bad, "file_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            "reference_sha256": hashlib.sha256(Path(reference).read_bytes()).hexdigest(),
            "byte_identical": Path(path).read_bytes() == Path(reference).read_bytes(),
            "pass": len(got) == len(ref) and key_mismatch == 0 and worst <= MG3_CONTROL_TOL}


def mg3_freeze_state(*, block, records_root, layout, replay_root, nbm_train_corpus, hrrr_corpus, reference,
                     out_dir, commit, hrrr_dev_corpus=None, land=None, rule_path=None, markets=R0_MARKETS):
    """rule_mg3_p3dh_state.md: fit the block's P3d_H once on Aug-Sep 2021-25, freeze it, then the identity control."""
    import platform
    import pickle as _pickle

    import numpy as np
    import pandas as pd
    import scipy
    import sklearn

    from weather.calibration import ols_floor_ladder as l9
    from weather.market.market_registry import spec_for_id

    spec = MG3_BLOCKS[block]
    if rule_path is not None and _rr_sha(rule_path) != MG3_STATE_RULE_SHA256:
        raise PooledModelError(f"rule {rule_path} is not {MG3_STATE_RULE_SHA256}")
    if _rr_sha(reference) != spec["reference_sha256"]:
        raise PooledModelError(f"reference {reference} is not {spec['reference_sha256']}")
    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pkl, side, parity_path = out / "p3d_h_state.pkl", out / "p3d_h_state.json", out / "export_parity.json"
    control_dir = out / "control"
    for path in (pkl, side, parity_path, out / "control.json", control_dir):
        if path.exists():
            raise PooledModelError(f"refusing to overwrite {path}")
    hours = spec["hours"]
    train_hrrr, dev_hrrr, hrrr_meta = _mg3_hrrr(block, hrrr_corpus, hrrr_dev_corpus, land, markets)
    # Training rows: exactly dev_emit_rung's frame, then the block's HRRR training hook.
    timezones = {m: spec_for_id(m).timezone for m in markets}
    frame, buckets = dev_training_frame(records_root, markets)
    if frame["year"].max() >= 2026:
        raise PooledModelError("an MG-3 training row is from 2026")
    frame, train_nbm = attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff, timezones)
    frame = frame[frame["hour"].isin(hours)].reset_index(drop=True)
    frame, hook_stats = rk_training_columns(frame, train_hrrr)
    simple, extra_ols, extra_hgb, extra_scale = _arm_spec(RK_ARMS[MG3_ARM])
    if simple or extra_ols or extra_scale or tuple(extra_hgb) != ("k_max", "k_gap", "k_tcdc"):
        raise PooledModelError(f"the P3d_H arm spec changed: {RK_ARMS[MG3_ARM]}")
    fits, entries = {}, {}
    for hour in hours:
        train = frame[frame["hour"] == hour].reset_index(drop=True)
        entry = _rung_entry(train, simple, extra_ols, extra_hgb, extra_scale)
        fits[hour] = entry
        entries[hour] = mg3_hour_entry(entry)
        print(f"mg3 {block} fit hour {hour}: {len(train)} rows", flush=True)
    levels = [name for name in LEVEL_COLUMNS if f"x_{name}" in frame.columns]
    state = {
        "schema": MG3_STATE_SCHEMA, "arm": MG3_ARM, "block": block, "markets": list(markets),
        "centres": list(AUG_SEP_CENTRES),
        "season_of": {f"{m:02d}": season_of(f"2026-{m:02d}-01") for m in range(1, 13)},
        "coords": {m: [float(v) for v in station_coordinates([m])[m]] for m in markets},
        "buckets": {m: list(buckets[m]) for m in markets},  # as fitted: same values, same order
        "constants": {"floor_mix_clim": FLOOR_MIX_CLIM, "kernel_bandwidth": KERNEL_BANDWIDTH,
                      "min_scale": MIN_SCALE, "clim_alpha": 0.10, "levels": levels},
        "conversion": {"enabled": False, "rule_id": None,
                       "rule": "none: the dev arms read raw high_so_far and current_temp, as fitted"},
        "extra_hgb": list(extra_hgb), "point_rule": hrrr_meta["point_rule"], "hours": entries,
        "provenance": {
            "commit": commit, "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "rule_sha256": MG3_STATE_RULE_SHA256, "rung_rule_sha256": spec["rule_sha256"],
            "training_rows": int(len(frame)), "train_years": sorted(int(y) for y in frame["year"].unique()),
            "train_nbm": train_nbm, "train_hrrr": hook_stats, "hrrr_train_corpus_stats": hrrr_meta["train_stats"],
            "inputs": dict(hrrr_meta["inputs"], nbm_train_corpus=_rr_sha(nbm_train_corpus)),
            "versions": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
                         "sklearn": sklearn.__version__, "pandas": pd.__version__}},
    }
    blob = _pickle.dumps(state, protocol=4)
    pkl.write_bytes(blob)
    digest = hashlib.sha256(blob).hexdigest()
    side.write_text(json.dumps(dict(state["provenance"], state_sha256=digest, block=block), indent=1,
                               sort_keys=True, default=str), encoding="utf-8")
    # Control 1: export parity on sampled training rows (state serve math vs the in-process mean model).
    worst, checked = 0.0, 0
    for hour in hours:
        train = frame[frame["hour"] == hour].reset_index(drop=True)
        model = fits[hour]["fit"]["mean"]
        sample = train.sample(n=min(200, len(train)), random_state=hour)
        pred, X_ref = model.predict(sample)
        for j, (_, row) in enumerate(sample.iterrows()):
            if not (math.isfinite(float(row["F"])) and math.isfinite(float(row["x_current_temp"]))):
                continue
            X, mu0, g, _ = mg3_state_X(
                state, hour, market=row["market"], target_date=date.fromisoformat(row["target_date"]),
                high_so_far=float(row["F"]), current_temp=float(row["x_current_temp"]), nbm_mean=float(row["fh"]),
                extra={c: row[c] for c in extra_hgb})
            yhat = float((mu0 + np.array([[1.0, g, max(g, 0.0)]]) @ entries[hour]["mean"]["ols"]
                          + entries[hour]["mean"]["hgb"].predict(X))[0])
            nan_split = (np.isnan(X[0]) != np.isnan(X_ref[j])).any()
            gap = float(np.inf) if nan_split else float(np.nanmax(np.abs(X - X_ref[j])))
            worst = max(worst, gap, abs(yhat - float(pred[j])))
            checked += 1
    export = {"rows": checked, "max_abs_diff": worst, "tolerance": MG3_EXPORT_TOL, "pass": worst <= MG3_EXPORT_TOL}
    parity_path.write_text(json.dumps(export, indent=1), encoding="utf-8")
    print(f"mg3 {block} export parity: {export}", flush=True)
    control = {"rule_sha256": MG3_STATE_RULE_SHA256, "block": block, "state_sha256": digest, "export_parity": export}
    if not export["pass"]:
        control["pass"] = False
        control["stopped_at"] = "export parity"
        (out / "control.json").write_text(json.dumps(control, indent=1, sort_keys=True), encoding="utf-8")
        return control
    # Control 2: re-emit the dev rows from the frozen state (reloaded by its sha) through the serve math.
    frozen = mg3_load_state(pkl, digest)

    def row_hook(market, target, hour, nbm, stats):
        values = rk_columns(dev_hrrr.get((market, target.isoformat(), int(hour))), nbm)
        stats["hrrr_rows"] += 1
        stats["hrrr_covered"] += values["k_miss"] == 0.0
        return values

    def serve(arm, hour, one, market):
        r = one.iloc[0]
        return mg3_state_distribution(
            frozen, hour, market=market, target_date=date.fromisoformat(r["target_date"]),
            high_so_far=float(r["F"]), current_temp=float(r["x_current_temp"]), nbm_mean=float(r["fh"]),
            extra={c: r[c] for c in frozen["extra_hgb"]})

    audit = dev_emit_rung(records_root=records_root, layout=layout, replay_root=replay_root,
                          nbm_train_corpus=nbm_train_corpus, out_dir=control_dir, markets=markets, hours=hours,
                          loyo=False, arms={MG3_ARM: RK_ARMS[MG3_ARM]}, row_hook=row_hook, fits={}, serve=serve)
    control["reemit"] = _mg3_compare_jsonl(control_dir / f"dev_{MG3_ARM}.jsonl", reference)
    control["emit_markets"] = audit["markets"]
    control["pass"] = bool(control["reemit"]["pass"])
    (out / "control.json").write_text(json.dumps(control, indent=1, sort_keys=True, default=str), encoding="utf-8")
    return control


def mg3_freeze_weights(*, layout, emit_dir, coefficients, nowcasts, rr_score, out_dir, commit, rule_path=None,
                       start=BLEND_FIT_FIRST, end="2026-09-29"):
    """rule_mg3_blend_weights.md: R-R's walk-forward weights reproduced (control), then w*(h) on all fit dates."""
    import os

    import numpy as np

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data

    if rule_path is not None and _rr_sha(rule_path) != MG3_WEIGHTS_RULE_SHA256:
        raise PooledModelError(f"rule {rule_path} is not {MG3_WEIGHTS_RULE_SHA256}")
    if _rr_sha(rr_score) != MG3_RR_SCORE_SHA256:
        raise PooledModelError(f"rr_score {rr_score} is not {MG3_RR_SCORE_SHA256}")
    emit = Path(emit_dir)
    for name, sha in MG3_RR_EMIT.items():
        if _rr_sha(emit / name) != sha:
            raise PooledModelError(f"{emit / name} is not {sha}")
    now_sha = _rr_sha(nowcasts)
    if now_sha != L6_NOWCAST_SHA256:
        raise PooledModelError(f"L6 nowcast sha {now_sha} != {L6_NOWCAST_SHA256}")
    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "blend_l6_H_weights.json"
    if path.exists():
        raise PooledModelError(f"refusing to overwrite {path}")
    os.environ["L6_NOWCASTS"] = str(nowcasts)
    from weather.reporting.scorecards.free_source_candidates import l6_stack

    l6_stack._CACHE.clear()
    state, part_sha = l6_frozen_state(coefficients)
    start_d, end_d = data.check_range(start, end)
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    fit_dates = sorted(d for d in {str(x) for x in lay.dates} if BLEND_FIT_FIRST <= d <= end)
    full = sc.Table(lay, fit_dates)
    fdates = full.snaps.date.astype(str).to_numpy()
    if max(fdates) > "2026-09-29":
        raise PooledModelError("a fit date is after 2026-09-29")
    pl, cl, _ = l6_vector(full, state, l3)
    reference = json.loads(Path(rr_score).read_bytes())["weights"]
    result = {"rule_sha256": MG3_WEIGHTS_RULE_SHA256, "commit": commit,
              "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "inputs": {"rr_score": MG3_RR_SCORE_SHA256, "l6_part": part_sha, "nowcasts": now_sha,
                         **{name: sha for name, sha in MG3_RR_EMIT.items()}},
              "fit_dates": [fit_dates[0], fit_dates[-1], len(fit_dates)], "control": {}, "weights": {},
              "reported": {}}
    worst = 0.0
    keep = {}
    for name, cand in (("blend_l6_H", "P3d_H"), ("blend_l6", "P3d_N_fix")):
        frame_, _ = l3._candidate_frame(str(emit / f"dev_{cand}.jsonl"), full, lay, folds, data)
        pa, ca, _ = l3._vector(full, frame_)
        A, B = blend_weight(pa, pl, full.y, full.offsets, full.n)
        w = walk_forward_weights(fdates, full.local_hour, ca & cl, A, B, scored)
        for h in RR_HOURS:
            got = {"mean": float(np.mean([w[(h, d)] for d in scored])), "first": w[(h, scored[0])],
                   "last": w[(h, scored[-1])]}
            for k, v in got.items():
                worst = max(worst, abs(float(v) - float(reference[name][f"h{h:02d}"][k])))
        keep[name] = (A, B, ca & cl, w)
    result["control"] = {"max_abs_diff": worst, "tolerance": MG3_CONTROL_TOL, "pass": worst <= MG3_CONTROL_TOL}
    if result["control"]["pass"]:
        A, B, covered, w = keep["blend_l6_H"]
        for h in RR_HOURS:
            sel = covered & (full.local_hour == h)
            result["weights"][f"h{h:02d}"] = solve_weight(A[sel], B[sel])
            result["reported"][f"h{h:02d}"] = {
                "covered_snapshots": int(sel.sum()),
                "walk_forward_mean": float(np.mean([w[(h, d)] for d in scored])),
                "walk_forward_last": w[(h, scored[-1])],
                "abs_frozen_minus_last": abs(result["weights"][f"h{h:02d}"] - w[(h, scored[-1])])}
    else:
        result["stopped_at"] = "positive control (R-R walk-forward weights not reproduced)"
    path.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    Path(str(path) + ".sha256").write_text(f"{_rr_sha(path)}  {path.name}\n", encoding="utf-8")
    return result


MG3_RF1_NOTE_SHA256 = "b13f2e035cb797efc04ed936af523aa5c269dc693fd6eec766b0bb212ed8efa9"  # mg3/refit_note_rf1.md
MG3_RF1_FROZEN_WEIGHTS_SHA256 = "c7b8ebc08d31ca30e5289d453ec2260bcc6659b32b379410f58b0d2b9b03530a"
MG3_RF1_PARTNER_SHA256 = "2366d67c5cdd6eb26b98064807210ade1c657829b7fa8e683535b94a9a2faa76"
MG3_RF1_SEASON_NOWCASTS_SHA256 = "714fa14e04c416da922803514fea1de8fe64459a0ea543878ddddfd6bc34896a"
MG3_RF1_IDENTITY_TOL = 1e-9
MG3_RF1_COVERAGE_MIN = 0.95


def mg3_refit_weights_rf1(*, layout, emit_dir, coefficients, nowcasts, season_nowcasts, partner_vectors, rr_score,
                          frozen_weights, out_dir, commit, note_path=None, start=BLEND_FIT_FIRST, end="2026-09-29"):
    """refit_note_rf1.md: the 4fb02a2c weights refitted once with the season-matched L6 dev vectors as partner.

    Checks (each refuses): (1) control - R-R walk-forward reproduced and the old-partner w* equal the frozen table;
    (2) vector identity - the parquet equals ``l6_vector`` under the season nowcasts; (3) coverage."""
    import os

    import numpy as np
    import pandas as pd

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data

    if note_path is not None and _rr_sha(note_path) != MG3_RF1_NOTE_SHA256:
        raise PooledModelError(f"note {note_path} is not {MG3_RF1_NOTE_SHA256}")
    expected = {"rr_score": (rr_score, MG3_RR_SCORE_SHA256), "nowcasts": (nowcasts, L6_NOWCAST_SHA256),
                "season_nowcasts": (season_nowcasts, MG3_RF1_SEASON_NOWCASTS_SHA256),
                "partner_vectors": (partner_vectors, MG3_RF1_PARTNER_SHA256),
                "frozen_weights": (frozen_weights, MG3_RF1_FROZEN_WEIGHTS_SHA256)}
    for name, (path_, sha) in expected.items():
        if _rr_sha(path_) != sha:
            raise PooledModelError(f"{name} {path_} is not {sha}")
    emit = Path(emit_dir)
    for name, sha in MG3_RR_EMIT.items():
        if _rr_sha(emit / name) != sha:
            raise PooledModelError(f"{emit / name} is not {sha}")
    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "blend_l6_H_weights.json"
    if path.exists():
        raise PooledModelError(f"refusing to overwrite {path}")
    from weather.reporting.scorecards.free_source_candidates import l6_stack

    state, part_sha = l6_frozen_state(coefficients)
    start_d, end_d = data.check_range(start, end)
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    fit_dates = sorted(d for d in {str(x) for x in lay.dates} if BLEND_FIT_FIRST <= d <= end)
    full = sc.Table(lay, fit_dates)
    fdates = full.snaps.date.astype(str).to_numpy()
    if max(fdates) > "2026-09-29":
        raise PooledModelError("a fit date is after 2026-09-29")

    def partner_from_nowcasts(nowcast_path):
        os.environ["L6_NOWCASTS"] = str(nowcast_path)
        l6_stack._CACHE.clear()
        p, c, _ = l6_vector(full, state, l3)
        return p, c

    pl_old, cl_old = partner_from_nowcasts(nowcasts)
    reference = json.loads(Path(rr_score).read_bytes())["weights"]
    frozen = json.loads(Path(frozen_weights).read_bytes())["weights"]
    result = {"note_sha256": MG3_RF1_NOTE_SHA256, "rule_sha256": MG3_WEIGHTS_RULE_SHA256, "commit": commit,
              "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "inputs": {"l6_part": part_sha, **{k: v[1] for k, v in expected.items()},
                         **{name: sha for name, sha in MG3_RR_EMIT.items()}},
              "fit_dates": [fit_dates[0], fit_dates[-1], len(fit_dates)], "checks": {}, "weights": {},
              "reported": {}}

    def finish():
        path.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
        Path(str(path) + ".sha256").write_text(f"{_rr_sha(path)}  {path.name}\n", encoding="utf-8")
        return result

    # check 1: control with the old partner
    worst_wf, keep = 0.0, {}
    for name, cand in (("blend_l6_H", "P3d_H"), ("blend_l6", "P3d_N_fix")):
        frame_, _ = l3._candidate_frame(str(emit / f"dev_{cand}.jsonl"), full, lay, folds, data)
        pa, ca, _ = l3._vector(full, frame_)
        A, B = blend_weight(pa, pl_old, full.y, full.offsets, full.n)
        w = walk_forward_weights(fdates, full.local_hour, ca & cl_old, A, B, scored)
        for h in RR_HOURS:
            got = {"mean": float(np.mean([w[(h, d)] for d in scored])), "first": w[(h, scored[0])],
                   "last": w[(h, scored[-1])]}
            for k, v in got.items():
                worst_wf = max(worst_wf, abs(float(v) - float(reference[name][f"h{h:02d}"][k])))
        keep[name] = (pa, ca, A, B)
    pa, ca, A_old, B_old = keep["blend_l6_H"]
    old_w = {f"h{h:02d}": solve_weight(A_old[ca & cl_old & (full.local_hour == h)],
                                       B_old[ca & cl_old & (full.local_hour == h)]) for h in RR_HOURS}
    worst_w = max(abs(old_w[k] - float(frozen[k])) for k in old_w)
    result["checks"]["1_control"] = {"walk_forward_max_abs_diff": worst_wf, "frozen_w_max_abs_diff": worst_w,
                                     "tolerance": MG3_CONTROL_TOL,
                                     "pass": worst_wf <= MG3_CONTROL_TOL and worst_w <= MG3_CONTROL_TOL}
    if not result["checks"]["1_control"]["pass"]:
        result["stopped_at"] = "check 1 control (refit refused)"
        return finish()

    # check 2: the SM-L6 parquet equals l6_vector under the season nowcasts
    vec = pd.read_parquet(partner_vectors, columns=["row_key", "band_index", "p"])
    duplicates = int(vec.duplicated(["row_key", "band_index"]).sum())
    pn, cn, _ = l3._vector(full, vec)
    pr, cr = partner_from_nowcasts(season_nowcasts)
    on = cn[full.band_snap]
    diff = float(np.max(np.abs(pn[on] - pr[on]))) if on.any() else float("inf")
    result["checks"]["2_identity"] = {"duplicates": duplicates, "same_coverage": bool(np.array_equal(cn, cr)),
                                      "max_abs_diff": diff, "tolerance": MG3_RF1_IDENTITY_TOL,
                                      "pass": duplicates == 0 and bool(np.array_equal(cn, cr))
                                      and diff <= MG3_RF1_IDENTITY_TOL}
    if not result["checks"]["2_identity"]["pass"]:
        result["stopped_at"] = "check 2 vector identity (refit refused)"
        return finish()

    # check 3: coverage
    lost = int((cl_old & ~cn).sum())
    share = {f"h{h:02d}": float((ca & cn & (full.local_hour == h)).sum() / max((ca & (full.local_hour == h)).sum(), 1))
             for h in RR_HOURS}
    result["checks"]["3_coverage"] = {"old_covered_not_new": lost, "share_per_hour": share,
                                      "threshold": MG3_RF1_COVERAGE_MIN,
                                      "pass": lost == 0 and min(share.values()) >= MG3_RF1_COVERAGE_MIN}
    if not result["checks"]["3_coverage"]["pass"]:
        result["stopped_at"] = "check 3 coverage (refit refused)"
        return finish()

    A, B = blend_weight(pa, pn, full.y, full.offsets, full.n)
    for h in RR_HOURS:
        sel = ca & cn & (full.local_hour == h)
        key = f"h{h:02d}"
        result["weights"][key] = solve_weight(A[sel], B[sel])
        result["reported"][key] = {"covered_snapshots": int(sel.sum()), "old_w": old_w[key],
                                   "abs_new_minus_old": abs(result["weights"][key] - old_w[key])}
    return finish()


# ------------------------------------------------- MG-3 freeze prep (1b): RN-1 point rule bound into the release

MG3_BINDING_SCHEMA = "mg3_release_binding/1"
MG3_PENDING = "PENDING"
MG3_RN1 = {  # RN-1 (clarification 1 of R-R): the 07-12 HRRR point rule, as fitted and scored
    "rule_sha256": "e4869491a8480f302c0bb4c33b0d55d4110ef98551f0db26e59d3441e204004b",
    "land_sha256": RR_LAND_SHA256,
    "land_msg_sha256": RR_LAND_MSG_SHA256,
    "land_key": RR_LAND_KEY,
    "stations_json_sha256": RR_CORPUS_SHA256["stations.json"],
    "index": dict(RR_EXPECTED_INDEX),
    "default_index": 4,
    "block_order": "row-major, south to north, west to east: index = 3 * (dj + 1) + (di + 1)",
    "choice": "the land cell (LAND:surface == 1) nearest (fi, fj) in grid units; ties to the lower index",
}
MG3_POINT_RULES = {"07-12": "rn1", "13-16": "nearest"}
MG3_RELEASE_FILES = (  # every repository file the MG-3 freeze, its controls and the R-R/R-K arms execute
    "src/weather/calibration/pooled_residual_model.py",
    "src/weather/calibration/feature_model.py",
    "src/weather/calibration/ols_floor_ladder.py",
    "src/weather/calibration/r0_ols_floor_devfit.py",
    "src/weather/calibration/r0_ols_floor_challenger.py",
    "src/weather/model/observed_running_max.py",
    "src/weather/reporting/scorecards/dev_scorecard.py",
    "src/weather/reporting/scorecards/dev_scorecard_data.py",
    "src/weather/reporting/scorecards/free_source_candidates/l6_stack.py",
    "src/weather/units.py",
)


# ---------------------------------------------------------------- SM-H (rule_sm_h.md): season-matched P3d_H 13-15

SM_H_RULE_SHA256 = "fca2bb1179b601ac4fe142fa17855fea095e10850e1501eb1a478f4a9b655e4d"  # mg3/rule_sm_h.md
SM_H_CENTRES = ("2026-10-10", "2026-10-25", "2026-11-09", "2026-11-24", "2026-12-09")
SM_H_HOURS = (13, 14, 15)
SM_H_MONTHS = ("10", "11", "12")
SM_H_ARMS = {"SM_H": RK_ARMS["P3d_H"], "SM_N": False}
SM_H_PAIRS = (("SM_H", "P3d_N"), ("SM_N", "P3d_N"), ("SM_H", "SM_N"))
SM_H_POOLS = (("13-15", None),)
SM_H_P3D_N_STATE_SHA256 = "dff5d7975fa7a18278f8e500e4e0bcdd768c5d05dc4caf8b8e08332dad1a6574"  # MG-2 frozen P3d_N
SM_H_PART1A_SHA256 = "98d80635666fafca107072b8fae2026b8924a6a8500c2968c599807e246166b7"  # CS-1 part1a.json
SM_H_NBM_SHA256 = "1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd"
SM_H_HRRR_SHA256 = {"manifest.jsonl": "409f6f917f2bca2999ebf39c52440c673760356295aaa291f572bfe624269935",
                    "selections.jsonl": "055add5a4a2aa25483f70ee6c355562d4730e8b01daa1f8b56adb5788512ec75",
                    "stations.json": "52e8bb5f22513828cb5edbfc16b77afb293cfcb9df62a92abd4db30ab7a0abe3"}
SM_H_CONTROL_TOL = 1e-9


def sm_h_brier(dist, actual):
    """CS-1's Brier: sum_k p_k^2 - 2 p_y + 1 (the label need not be in the support)."""
    return sum(p * p for p in dist.values()) - 2.0 * dist.get(int(actual), 0.0) + 1.0


def sm_h_day_filter(day):
    """Rule section 2: HRRR selections on local dates in 2021-2025, months 10-12 only."""
    return "2021" <= day[:4] <= "2025" and day[5:7] in SM_H_MONTHS


def _sm_h_bound(path, expected, what):
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if digest != expected:
        raise PooledModelError(f"{what} {path}: sha256 {digest} != bound {expected}")
    return digest


def sm_h_frame(records_root, markets=R0_MARKETS, centres=SM_H_CENTRES, hours=SM_H_HOURS):
    """Oct-Dec 2021-25 P3d training rows at 13-15 and the per-market union of the Oct-Dec bucket spaces."""
    missing = [f"{m}_{c}" for c in centres for m in markets if not records_path(records_root, m, c).exists()]
    if missing:
        raise PooledModelError(f"SM-H records missing: {missing}")
    payloads = [load_records(records_root, m, c) for c in centres for m in markets]
    frame, _ = pooled_frame(payloads, station_coordinates(markets))
    drop = [c for c in frame.columns if c.startswith("x_") and c not in DEV_KEEP_X]
    frame = frame.drop(columns=drop)
    days = frame["target_date"].astype(str)
    if (days < "2021-01-01").any() or (days > "2025-12-31").any() or not days.str[5:7].isin(SM_H_MONTHS).all():
        raise PooledModelError("an SM-H record is outside 2021-25 Oct-Dec")
    buckets = {m: sorted({int(b) for p in payloads if p["market"] == m for b in p["bucket_space"]}) for m in markets}
    return frame[frame["hour"].isin(hours)].reset_index(drop=True), buckets


def sm_h_frozen_dist(state, row):
    """MG-2's frozen P3d_N serve math on one training row (CS-1 part1a's inputs)."""
    return state_distribution(state, int(row["hour"]), market=row["market"],
                              target_date=date.fromisoformat(str(row["target_date"])[:10]),
                              high_so_far=float(row["F"]), current_temp=float(row["x_current_temp"]),
                              nbm_mean=float(row["fh"]))


def sm_h_rows(frame, buckets, state, hours=SM_H_HOURS, arms=None):
    """Blocked LOYO per hour on the Oct-Dec rows (SM_H, SM_N) plus the frozen P3d_N, identical rows.

    Rows without a finite high_so_far or current_temp are excluded from every arm. -> (rows, excluded)."""
    import numpy as np

    from weather.calibration import feature_model as fm

    arms = SM_H_ARMS if arms is None else arms
    rows, excluded = [], 0
    for hour in hours:
        at_hour = frame[frame["hour"] == hour]
        for year in sorted(at_hour["year"].unique()):
            train = at_hour[at_hour["year"] != year].reset_index(drop=True)
            val = at_hour[at_hour["year"] == year].reset_index(drop=True)
            ok = np.isfinite(val["F"].to_numpy(float)) & np.isfinite(val["x_current_temp"].to_numpy(float))
            excluded += int((~ok).sum())
            val = val[ok].reset_index(drop=True)
            entries = {arm: _rung_entry(train, *_arm_spec(spec)) for arm, spec in arms.items()}
            for market in sorted(val["market"].unique()):
                part = val[val["market"] == market].reset_index(drop=True)
                dists = {arm: _dist_from_fit(e, part, buckets, market) for arm, e in entries.items()}
                for i in range(len(part)):
                    actual = int(part.at[i, "y"])
                    row = {"hour": int(hour), "year": int(year), "market": market,
                           "date": str(part.at[i, "target_date"])[:10], "y": actual}
                    dists_i = {a: d[i] for a, d in dists.items()}
                    dists_i["P3d_N"] = sm_h_frozen_dist(state, part.iloc[i])
                    for arm, dist in dists_i.items():
                        row[f"{arm}_brier"] = sm_h_brier(dist, actual)
                        row[f"{arm}_log"] = fm.log_loss(dist, actual)
                    rows.append(row)
        print(f"sm-h loyo hour {hour}: {sum(1 for r in rows if r['hour'] == hour)} rows", flush=True)
    return rows, excluded


def sm_h_control(rows, part1a, hours=SM_H_HOURS, tol=SM_H_CONTROL_TOL):
    """Rule section 5.2: frozen P3d_N per-hour mean Brier and row count equal CS-1 part1a Oct-Dec."""
    out, ok = {}, True
    for hour in hours:
        ref = part1a["p3d_n_1316"]["periods"]["oct_dec"]["by"][f"h{hour:02d}"]
        got = [r["P3d_N_brier"] for r in rows if r["hour"] == hour]
        mean = sum(got) / len(got) if got else float("nan")
        diff = abs(mean - float(ref["brier_part"]))
        passed = len(got) == int(ref["n_rows"]) and diff <= tol
        ok = ok and passed
        out[f"h{hour:02d}"] = {"mean": mean, "reference": float(ref["brier_part"]), "abs_diff": diff,
                               "n": len(got), "reference_n": int(ref["n_rows"]), "pass": passed}
    out["pass"] = bool(ok)
    return out


def sm_h_counts(frame):
    by_year = frame.groupby("year").agg(rows=("y", "size"), dates=("target_date", "nunique"))
    return {str(y): {"rows": int(r.rows), "dates": int(r.dates)} for y, r in by_year.iterrows()}


def sm_h_loyo(*, records_root, nbm_train_corpus, hrrr_corpus, p3d_n_state, part1a, out_dir, markets=R0_MARKETS):
    """SM-H (rule_sm_h.md): one look. History only; no 2026 row and no dev row is read."""
    from weather.calibration import ols_floor_ladder as l9
    from weather.market.market_registry import spec_for_id

    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise PooledModelError(f"refusing to write into a non-empty {out}")
    corpus = Path(hrrr_corpus)
    audit = {"rule_sha256": SM_H_RULE_SHA256, "arms": list(SM_H_ARMS) + ["P3d_N"], "hours": list(SM_H_HOURS),
             "centres": list(SM_H_CENTRES), "checks": {},
             "inputs": {"nbm_train_corpus": _sm_h_bound(nbm_train_corpus, SM_H_NBM_SHA256, "NBM corpus"),
                        "p3d_n_state": _sm_h_bound(p3d_n_state, SM_H_P3D_N_STATE_SHA256, "P3d_N state"),
                        "part1a": _sm_h_bound(part1a, SM_H_PART1A_SHA256, "CS-1 part1a"),
                        **{f"hrrr_{n}": _sm_h_bound(corpus / n, sha, f"HRRR {n}")
                           for n, sha in SM_H_HRRR_SHA256.items()},
                        "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}

    def finish():
        (out / "sm_h_loyo_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True), encoding="utf-8")
        return audit

    state = pickle.loads(Path(p3d_n_state).read_bytes())
    reference = json.loads(Path(part1a).read_text(encoding="utf-8"))
    timezones = {m: spec_for_id(m).timezone for m in markets}
    hrrr, audit["hrrr_corpus_stats"] = rk_hrrr_columns(corpus, markets, hours=SM_H_HOURS,
                                                       day_filter=sm_h_day_filter)
    frame, buckets = sm_h_frame(records_root, markets)
    frame, audit["train_nbm"] = attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff,
                                                    timezones)
    frame, audit["training"] = rk_training_columns(frame, hrrr)
    audit["counts_by_year"] = sm_h_counts(frame)
    audit["covered_by_year"] = {str(y): int((g["k_miss"] == 0.0).sum()) for y, g in frame.groupby("year")}
    audit["checks"]["1_inputs"] = rk_parity_training(audit["hrrr_corpus_stats"], audit["training"])
    if not audit["checks"]["1_inputs"]["pass"]:
        audit["stopped_at"] = "check 1 inputs (not a kill)"
        return finish()
    rows, audit["rows_excluded_no_obs"] = sm_h_rows(frame, buckets, state)
    _write_jsonl(out / "loyo_rows.jsonl", rows)
    audit["checks"]["2_comparator_control"] = sm_h_control(rows, reference)
    if not audit["checks"]["2_comparator_control"]["pass"]:
        audit["stopped_at"] = "check 2 comparator control (refused, not a kill)"
        return finish()
    audit["summary"] = rg_loyo_summary(rows, pairs=SM_H_PAIRS, pooled=SM_H_POOLS)
    primary = audit["summary"]["SM_H-P3d_N|13-15|brier"]
    audit["decision"] = {"pair": "SM_H-P3d_N|13-15|brier", "estimate": primary["estimate"],
                         "ci95": primary["ci95"], "selected": "SM_H" if primary["ci95"][1] < 0 else "P3d_N"}
    return finish()


# ---------------------------------------------------------------- C10-sel and SM-H SMH-1: comparator = served P3d_N

C10_RULE_SHA256 = "8c59c1b6ea2708c319189d89e8efd531cdaa04593803f92b1e620c5100252391"  # c10/rule_c10_sel.md
SM_H_CLARIFICATION_1_SHA256 = "b30078031375b3ab77db791124ec24e6568035c25f1696c3c7d54d98cc67e891"  # SMH-1
C10_HOURS = (13, 14, 15, 16)
C10_FWD_STATE_SHA256 = "c6cc39f7b57f668557415d28ec37ac291694f4b429e572a3c178fb74e5a9c780"  # MG-2 served P3d_N
C10_FWD_TRAINING_ROWS = 103609
C10_SMH_ROWS_SHA256 = "f6f96cbceb3d3435431847470008300725161b5c39215e11a65ef696fb392fd5"  # SM-H loyo_rows.jsonl
C10_PAIRS = (("SM_N", "P3d_N_fwd"), ("SM_N", "P3d_N_dev"), ("P3d_N_fwd", "P3d_N_dev"))
C10_POOLS = (("13-16", None),)
C10_PARITY_TOL = 1e-9
C10_TOL = 1e-12
SMH1_PAIRS = (("SM_H", "P3d_N_fwd"),)
SMH1_POOLS = (("13-15", None),)
SMH1_HOURS = (13, 14, 15)


def fwd_hour_entry(train, markets=R0_MARKETS):
    """One ``hours[h]`` entry built exactly as :func:`forward_fit` builds it (same fit_pooled call)."""
    import numpy as np

    fitted = fit_pooled(train, market_id=False, doy=True, raw_columns=False, bias_by="season")
    return {"mean": state_mean_dict(fitted["mean"]), "scale": fitted["scale"],
            "z": np.asarray(fitted["z"], dtype=np.float64),
            "train_y": {m: [int(v) for v in train.loc[train["market"] == m, "y"]] for m in markets}}


def fwd_shell(state, entries):
    """The served state with ``hours[h]`` replaced by ``entries`` (C10-sel section 3); every other field kept."""
    return dict(state, hours={**state["hours"], **entries})


def dist_max_abs(a, b):
    return max(abs(float(a.get(k, 0.0)) - float(b.get(k, 0.0))) for k in set(a) | set(b))


def row_key(r):
    return (int(r["hour"]), int(r["year"]), str(r["market"]), str(r["date"]))


def c10_rows(oct_frame, fwd_frame, buckets, fwd_state, dev_state, hours=C10_HOURS, markets=R0_MARKETS,
             serve=None):
    """SM_N (Oct-Dec LOYO), P3d_N_fwd (Aug-Dec LOYO in the served shell) and P3d_N_dev on identical rows.

    Also tier-2 parity: the all-years refit in the shell vs the served state on every scored row.
    ``serve`` (state, row) -> distribution defaults to the served math. -> (rows, excluded, parity)."""
    import numpy as np

    from weather.calibration import feature_model as fm

    serve = serve or sm_h_frozen_dist
    rows, excluded, parity = [], 0, {}
    for hour in hours:
        at_hour = oct_frame[oct_frame["hour"] == hour]
        fwd_hour = fwd_frame[fwd_frame["hour"] == hour].reset_index(drop=True)
        full = fwd_shell(fwd_state, {int(hour): fwd_hour_entry(fwd_hour, markets)})
        worst, checked = 0.0, 0
        for year in sorted(at_hour["year"].unique()):
            train = at_hour[at_hour["year"] != year].reset_index(drop=True)
            val = at_hour[at_hour["year"] == year].reset_index(drop=True)
            ok = np.isfinite(val["F"].to_numpy(float)) & np.isfinite(val["x_current_temp"].to_numpy(float))
            excluded += int((~ok).sum())
            val = val[ok].reset_index(drop=True)
            sm_n = _rung_entry(train, False)
            fold = fwd_shell(fwd_state, {int(hour): fwd_hour_entry(
                fwd_hour[fwd_hour["year"] != year].reset_index(drop=True), markets)})
            for market in sorted(val["market"].unique()):
                part = val[val["market"] == market].reset_index(drop=True)
                sm = _dist_from_fit(sm_n, part, buckets, market)
                for i in range(len(part)):
                    one = part.iloc[i]
                    actual = int(part.at[i, "y"])
                    ref = serve(fwd_state, one)
                    worst = max(worst, dist_max_abs(serve(full, one), ref))
                    checked += 1
                    row = {"hour": int(hour), "year": int(year), "market": market,
                           "date": str(part.at[i, "target_date"])[:10], "y": actual}
                    for arm, dist in (("SM_N", sm[i]), ("P3d_N_fwd", serve(fold, one)),
                                      ("P3d_N_dev", serve(dev_state, one))):
                        row[f"{arm}_brier"] = sm_h_brier(dist, actual)
                        row[f"{arm}_log"] = fm.log_loss(dist, actual)
                    rows.append(row)
        parity[f"h{hour:02d}"] = {"rows": checked, "max_abs": worst}
        print(f"c10 hour {hour}: {sum(1 for r in rows if r['hour'] == hour)} rows, parity {worst:.3g}", flush=True)
    parity["max_abs"] = max(v["max_abs"] for v in parity.values())
    parity["rows"] = sum(v["rows"] for k, v in parity.items() if k.startswith("h"))
    parity["tolerance"] = C10_PARITY_TOL
    parity["pass"] = parity["max_abs"] <= C10_PARITY_TOL and parity["rows"] == len(rows)
    return rows, excluded, parity


def c10_sm_n_reproduction(rows, smh_rows, hours=SMH1_HOURS, tol=C10_TOL):
    """C10-sel checks 1 (scored keys at 13-15 = the SM-H rows) and 5 (SM_N reproduces SM-H's SM_N)."""
    got = {row_key(r): r for r in rows if r["hour"] in hours}
    ref = {row_key(r): r for r in smh_rows if r["hour"] in hours}
    worst = max((abs(got[k]["SM_N_brier"] - ref[k]["SM_N_brier"]) for k in set(got) & set(ref)), default=0.0)
    same = set(got) == set(ref) and len(got) == sum(1 for r in rows if r["hour"] in hours)
    return {"same_keys": same, "rows": len(got), "reference_rows": len(ref), "max_abs": worst,
            "pass": bool(same and worst <= tol)}


def c10_sel(*, records_root, nbm_train_corpus, fwd_state, dev_state, part1a, smh_rows, out_dir, markets=R0_MARKETS):
    """C10-sel (rule_c10_sel.md): one look. History only; no 2026 row and no dev row is read."""
    from weather.calibration import ols_floor_ladder as l9
    from weather.market.market_registry import spec_for_id

    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise PooledModelError(f"refusing to write into a non-empty {out}")
    audit = {"rule_sha256": C10_RULE_SHA256, "hours": list(C10_HOURS), "checks": {},
             "inputs": {"nbm_train_corpus": _sm_h_bound(nbm_train_corpus, SM_H_NBM_SHA256, "NBM corpus"),
                        "fwd_state": _sm_h_bound(fwd_state, C10_FWD_STATE_SHA256, "served P3d_N state"),
                        "dev_state": _sm_h_bound(dev_state, SM_H_P3D_N_STATE_SHA256, "dev P3d_N state"),
                        "part1a": _sm_h_bound(part1a, SM_H_PART1A_SHA256, "CS-1 part1a"),
                        "smh_rows": _sm_h_bound(smh_rows, C10_SMH_ROWS_SHA256, "SM-H rows"),
                        "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}

    def finish():
        (out / "c10_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True), encoding="utf-8")
        return audit

    served = pickle.loads(Path(fwd_state).read_bytes())
    dev = pickle.loads(Path(dev_state).read_bytes())
    reference = json.loads(Path(part1a).read_text(encoding="utf-8"))
    timezones = {m: spec_for_id(m).timezone for m in markets}
    nbm = l9.load_nbm(nbm_train_corpus)
    oct_frame, buckets = sm_h_frame(records_root, markets, hours=C10_HOURS)
    oct_frame, audit["oct_nbm"] = attach_training_nbm(oct_frame, nbm, l9.nbm_at_cutoff, timezones)
    missing = [f"{m}_{c}" for c in FORWARD_CENTRES for m in markets if not records_path(records_root, m, c).exists()]
    if missing:
        raise PooledModelError(f"C10 forward records missing: {missing}")
    fwd_frame, _ = forward_training_frame(records_root, markets)
    audit["fwd_frame_rows"] = int(len(fwd_frame))
    years_ok = set(int(y) for y in fwd_frame["year"].unique()) <= set(FORWARD_YEARS)
    fwd_frame = fwd_frame[fwd_frame["hour"].isin(C10_HOURS)].reset_index(drop=True)
    fwd_frame, audit["fwd_nbm"] = attach_training_nbm(fwd_frame, nbm, l9.nbm_at_cutoff, timezones)
    audit["counts_by_year"] = sm_h_counts(oct_frame)
    audit["checks"]["1_inputs"] = {"fwd_frame_rows": audit["fwd_frame_rows"], "expected": C10_FWD_TRAINING_ROWS,
                                   "years_2021_25": years_ok,
                                   "pass": audit["fwd_frame_rows"] == C10_FWD_TRAINING_ROWS and years_ok}
    if not audit["checks"]["1_inputs"]["pass"]:
        audit["stopped_at"] = "check 1 inputs (VOID)"
        return finish()
    audit["checks"]["2_tier1_bytes"] = {"attainable": False, "binding": False,
                                        "reason": "provenance embeds module 52c497a9 / commit 73675b78; a "
                                                  "re-pickled loaded state does not reproduce its bytes"}
    rows, audit["rows_excluded_no_obs"], parity = c10_rows(oct_frame, fwd_frame, buckets, served, dev,
                                                           markets=markets)
    audit["checks"]["3_tier2_parity"] = parity
    audit["checks"]["4_row_identity"] = sm_h_control(
        [{"hour": r["hour"], "P3d_N_brier": r["P3d_N_dev_brier"]} for r in rows], reference, hours=C10_HOURS,
        tol=C10_TOL)
    audit["checks"]["1_inputs"]["scored_keys_and_5_sm_n"] = c10_sm_n_reproduction(rows, _read_jsonl(smh_rows))
    audit["checks"]["5_sm_n_reproduction"] = audit["checks"]["1_inputs"].pop("scored_keys_and_5_sm_n")
    _write_jsonl(out / "loyo_rows.jsonl", rows)
    fwd_path = out / "fwd_rows.jsonl"
    _write_jsonl(fwd_path, [{"hour": r["hour"], "year": r["year"], "market": r["market"], "date": r["date"],
                             "y": r["y"], "P3d_N_fwd_brier": r["P3d_N_fwd_brier"],
                             "P3d_N_fwd_log": r["P3d_N_fwd_log"]} for r in rows])
    audit["outputs"] = {"loyo_rows": _rr_sha(out / "loyo_rows.jsonl"), "fwd_rows": _rr_sha(fwd_path)}
    failed = [k for k in ("3_tier2_parity", "4_row_identity", "5_sm_n_reproduction") if not audit["checks"][k]["pass"]]
    if failed:
        audit["stopped_at"] = f"checks {failed} (VOID; no score read)"
        return finish()
    audit["summary"] = rg_loyo_summary(rows, pairs=C10_PAIRS, pooled=C10_POOLS)
    pooled = audit["summary"]["SM_N-P3d_N_fwd|13-16|brier"]
    h16 = audit["summary"]["SM_N-P3d_N_fwd|h16|brier"]
    adopt = pooled["ci95"][1] < 0 and h16["estimate"] <= 0
    audit["decision"] = {"pair": "SM_N-P3d_N_fwd", "pooled_13_16": pooled, "h16": h16,
                         "selected": "SM_N" if adopt else "P3d_N"}
    return finish()


def sm_h_redecide(*, smh_rows, c10_audit, out_dir, expected_smh_rows=C10_SMH_ROWS_SHA256):
    """SM-H clarification SMH-1: SM_H (existing rows) vs P3d_N_fwd (C10's fwd_rows) at 13-15, one look."""
    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "smh1_audit.json"
    if any(out.iterdir()):
        raise PooledModelError(f"refusing to write into a non-empty {out}")
    c10 = json.loads(Path(c10_audit).read_text(encoding="utf-8"))
    fwd_path = Path(c10_audit).parent / "fwd_rows.jsonl"
    audit = {"clarification_sha256": SM_H_CLARIFICATION_1_SHA256, "rule_sha256": SM_H_RULE_SHA256,
             "inputs": {"smh_rows": _sm_h_bound(smh_rows, expected_smh_rows, "SM-H rows"),
                        "c10_audit": _rr_sha(c10_audit),
                        "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}

    def finish():
        target.write_text(json.dumps(audit, indent=1, sort_keys=True), encoding="utf-8")
        return audit

    checks_ok = (not c10.get("stopped_at") and c10.get("rule_sha256") == C10_RULE_SHA256
                 and all(c10["checks"][k]["pass"] for k in ("1_inputs", "3_tier2_parity", "4_row_identity",
                                                            "5_sm_n_reproduction")))
    if not checks_ok:
        audit["stopped_at"] = "C10 run VOID or incomplete (SMH-1 VOID)"
        return finish()
    audit["inputs"]["fwd_rows"] = _sm_h_bound(fwd_path, c10["outputs"]["fwd_rows"], "C10 fwd rows")
    sm = {row_key(r): r for r in _read_jsonl(smh_rows) if r["hour"] in SMH1_HOURS}
    fwd = {row_key(r): r for r in _read_jsonl(fwd_path) if r["hour"] in SMH1_HOURS}
    audit["join"] = {"smh_rows": len(sm), "fwd_rows": len(fwd), "same_keys": set(sm) == set(fwd)}
    if set(sm) != set(fwd):
        audit["stopped_at"] = "keys differ (SMH-1 VOID)"
        return finish()
    rows = [{"hour": k[0], "year": k[1], "market": k[2], "date": k[3],
             "SM_H_brier": sm[k]["SM_H_brier"], "SM_H_log": sm[k]["SM_H_log"],
             "P3d_N_fwd_brier": fwd[k]["P3d_N_fwd_brier"], "P3d_N_fwd_log": fwd[k]["P3d_N_fwd_log"]}
            for k in sorted(sm)]
    audit["summary"] = rg_loyo_summary(rows, pairs=SMH1_PAIRS, pooled=SMH1_POOLS)
    pooled = audit["summary"]["SM_H-P3d_N_fwd|13-15|brier"]
    audit["decision"] = {"pair": "SM_H-P3d_N_fwd|13-15|brier", "estimate": pooled["estimate"],
                         "ci95": pooled["ci95"], "selected": "SM_H" if pooled["ci95"][1] < 0 else "P3d_N"}
    return finish()


# ---------------------------------------------------------------- SM-H served state (binding note, rule_sm_h s7)

SM_H_BINDING_SHA256 = "6507946e185fb4ba1a76e1c5022f14a38d981a3904fd8aaf16ac65837df74cab"  # mg3/binding_sm_h_state.md
SM_H_LOYO_AUDIT_SHA256 = "5a39218f55fac01eaad6913032e462287d9d234eaa662fb010b2afb00161e541"  # SM-H run audit
SM_H_STATE_BLOCK = "SM-H 13-15"
SM_H_STATE_TOL = 1e-9
SM_H_STATE_SHA256 = "b6bc242a8c2b679069a4090b8912eea3b80af160b6bc228424c846fb3b87a477"  # row 52, control 5a106a0d
SM_H_EXCLUDED_MARKETS = ("san-francisco",)  # MG3-DC-1 s2.1: SF 13-16 stays on MG-2's bound arm


def sm_h_load_state(path, expected_sha256=SM_H_STATE_SHA256):
    """Verified load of the served SM-H state: bytes at the bound sha, then schema, block, hours, centres, rules."""
    state = mg3_load_state(path, expected_sha256)
    prov = state.get("provenance") or {}
    problems = [name for name, ok in (
        ("block", state.get("block") == SM_H_STATE_BLOCK),
        ("hours", sorted(state.get("hours") or {}) == list(SM_H_HOURS)),
        ("centres", state.get("centres") == list(SM_H_CENTRES)),
        ("conversion", not (state.get("conversion") or {}).get("enabled")),
        ("point_rule", (state.get("point_rule") or {}).get("land_sha256") is None),
        ("extra_hgb", state.get("extra_hgb") == ["k_max", "k_gap", "k_tcdc"]),
        ("note_sha256", prov.get("note_sha256") == SM_H_BINDING_SHA256),
        ("rule_sha256", prov.get("rule_sha256") == SM_H_RULE_SHA256),
        ("clarification_sha256", prov.get("clarification_sha256") == SM_H_CLARIFICATION_1_SHA256)) if not ok]
    if problems:
        raise PooledModelError(f"SM-H state {path}: {problems} differ from the binding note")
    return state


def sm_h_build_state(frame, buckets, *, hours=SM_H_HOURS, markets=R0_MARKETS, provenance=None):
    """The SM_H spec fitted once per hour on ``frame`` and frozen as ``mg3_p3d_h_state/1``. -> (state, fits)."""
    simple, extra_ols, extra_hgb, extra_scale = _arm_spec(SM_H_ARMS["SM_H"])
    if simple or extra_ols or extra_scale or tuple(extra_hgb) != ("k_max", "k_gap", "k_tcdc"):
        raise PooledModelError(f"the SM_H arm spec changed: {SM_H_ARMS['SM_H']}")
    days = frame["target_date"].astype(str)
    if (days < "2021-01-01").any() or (days > "2025-12-31").any() or not days.str[5:7].isin(SM_H_MONTHS).all():
        raise PooledModelError("an SM-H state training row is outside 2021-25 Oct-Dec")
    fits, entries = {}, {}
    for hour in hours:
        train = frame[frame["hour"] == hour].reset_index(drop=True)
        fits[hour] = _rung_entry(train, simple, extra_ols, extra_hgb, extra_scale)
        entries[hour] = mg3_hour_entry(fits[hour])
    levels = [name for name in LEVEL_COLUMNS if f"x_{name}" in frame.columns]
    state = {
        "schema": MG3_STATE_SCHEMA, "arm": MG3_ARM, "block": SM_H_STATE_BLOCK, "markets": list(markets),
        "centres": list(SM_H_CENTRES),
        "season_of": {f"{m:02d}": season_of(f"2026-{m:02d}-01") for m in range(1, 13)},
        "coords": {m: [float(v) for v in station_coordinates([m])[m]] for m in markets},
        "buckets": {m: list(buckets[m]) for m in markets},
        "constants": {"floor_mix_clim": FLOOR_MIX_CLIM, "kernel_bandwidth": KERNEL_BANDWIDTH,
                      "min_scale": MIN_SCALE, "clim_alpha": 0.10, "levels": levels},
        "conversion": {"enabled": False, "rule_id": None,
                       "rule": "none: SM-H read raw high_so_far and current_temp, as fitted"},
        "extra_hgb": list(extra_hgb), "point_rule": {"rule": "nearest cell (R-K as fitted)", "land_sha256": None},
        "hours": entries, "provenance": dict(provenance or {}),
    }
    return state, fits


def _sm_h_serve_rows(state, part, hour):
    """Frozen-state serve math on each row of one market's frame slice."""
    out = []
    for _, r in part.iterrows():
        out.append(mg3_state_distribution(
            state, hour, market=r["market"], target_date=date.fromisoformat(str(r["target_date"])[:10]),
            high_so_far=float(r["F"]), current_temp=float(r["x_current_temp"]), nbm_mean=float(r["fh"]),
            extra={c: r[c] for c in state["extra_hgb"]}))
    return out


def _sm_h_finite(part):
    import numpy as np

    ok = np.isfinite(part["F"].to_numpy(float)) & np.isfinite(part["x_current_temp"].to_numpy(float))
    return part[ok].reset_index(drop=True)


def sm_h_export_parity(state, fits, frame, buckets, hours=SM_H_HOURS, tol=SM_H_STATE_TOL):
    """Note s3.2: on every finite training row, the frozen serve math equals the in-process fit's distribution."""
    worst, n, first_bad = 0.0, 0, None
    for hour in hours:
        at_hour = _sm_h_finite(frame[frame["hour"] == hour])
        for market in sorted(at_hour["market"].unique()):
            part = at_hour[at_hour["market"] == market].reset_index(drop=True)
            ref = _dist_from_fit(fits[hour], part, buckets, market)
            got = _sm_h_serve_rows(state, part, hour)
            for i, (a, b) in enumerate(zip(got, ref)):
                d = dist_max_abs(a, b)
                if d > tol and first_bad is None:
                    first_bad = {"hour": hour, "market": market, "date": str(part.at[i, "target_date"])[:10],
                                 "abs_diff": d}
                worst = max(worst, d)
                n += 1
    return {"rows": n, "max_abs_dp": worst, "tolerance": tol, "first_bad": first_bad,
            "pass": first_bad is None and n > 0}


def sm_h_fold_control(frame, buckets, smh_rows, hours=SM_H_HOURS, markets=R0_MARKETS, tol=SM_H_STATE_TOL):
    """Note s3.3: per (hour, held-out year), a fold state from the same builder reproduces SM_H_brier per row."""
    reference = {row_key(r): float(r["SM_H_brier"]) for r in smh_rows if int(r["hour"]) in hours}
    got = {}
    for hour in hours:
        at_hour = frame[frame["hour"] == hour]
        for year in sorted(at_hour["year"].unique()):
            fold, _ = sm_h_build_state(at_hour[at_hour["year"] != year], buckets, hours=(hour,), markets=markets)
            val = _sm_h_finite(at_hour[at_hour["year"] == year])
            for market in sorted(val["market"].unique()):
                part = val[val["market"] == market].reset_index(drop=True)
                for i, dist in enumerate(_sm_h_serve_rows(fold, part, hour)):
                    key = (int(hour), int(year), str(market), str(part.at[i, "target_date"])[:10])
                    got[key] = sm_h_brier(dist, int(part.at[i, "y"]))
        print(f"sm-h freeze fold control hour {hour}: {sum(1 for k in got if k[0] == hour)} rows", flush=True)
    same = set(got) == set(reference)
    diffs = [abs(got[k] - reference[k]) for k in sorted(set(got) & set(reference))]
    worst = max(diffs) if diffs else float("inf")
    first_bad = next((list(k) for k in sorted(set(got) & set(reference)) if abs(got[k] - reference[k]) > tol), None)
    return {"rows": len(got), "reference_rows": len(reference), "same_keys": same,
            "missing": len(set(reference) - set(got)), "extra": len(set(got) - set(reference)),
            "max_abs_brier_diff": worst, "tolerance": tol, "first_bad": first_bad,
            "pass": bool(same and diffs and worst <= tol)}


def sm_h_freeze_state(*, records_root, nbm_train_corpus, hrrr_corpus, smh_audit, smh_rows, out_dir, commit,
                      note_path=None, markets=R0_MARKETS):
    """binding_sm_h_state.md: fit SM_H once on all Oct-Dec 2021-25 rows, freeze, then the identity control."""
    import pickle as _pickle
    import platform

    import numpy as np
    import pandas as pd
    import scipy
    import sklearn

    from weather.calibration import ols_floor_ladder as l9
    from weather.market.market_registry import spec_for_id

    if note_path is not None and _rr_sha(note_path) != SM_H_BINDING_SHA256:
        raise PooledModelError(f"note {note_path} is not {SM_H_BINDING_SHA256}")
    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise PooledModelError(f"refusing to write into a non-empty {out}")
    corpus = Path(hrrr_corpus)
    control = {"note_sha256": SM_H_BINDING_SHA256, "rule_sha256": SM_H_RULE_SHA256,
               "clarification_sha256": SM_H_CLARIFICATION_1_SHA256, "block": SM_H_STATE_BLOCK, "checks": {},
               "inputs": {"nbm_train_corpus": _sm_h_bound(nbm_train_corpus, SM_H_NBM_SHA256, "NBM corpus"),
                          "smh_audit": _sm_h_bound(smh_audit, SM_H_LOYO_AUDIT_SHA256, "SM-H audit"),
                          "smh_rows": _sm_h_bound(smh_rows, C10_SMH_ROWS_SHA256, "SM-H rows"),
                          **{f"hrrr_{n}": _sm_h_bound(corpus / n, sha, f"HRRR {n}")
                             for n, sha in SM_H_HRRR_SHA256.items()},
                          "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}

    def finish(stopped=None):
        if stopped:
            control["stopped_at"] = stopped
        control["pass"] = stopped is None
        (out / "control.json").write_text(json.dumps(control, indent=1, sort_keys=True, default=str),
                                          encoding="utf-8")
        return control

    reference = json.loads(Path(smh_audit).read_text(encoding="utf-8"))
    timezones = {m: spec_for_id(m).timezone for m in markets}
    hrrr, hrrr_stats = rk_hrrr_columns(corpus, markets, hours=SM_H_HOURS, day_filter=sm_h_day_filter)
    frame, buckets = sm_h_frame(records_root, markets)
    frame, train_nbm = attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff, timezones)
    frame, training = rk_training_columns(frame, hrrr)
    counts = sm_h_counts(frame)
    covered = {str(y): int((g["k_miss"] == 0.0).sum()) for y, g in frame.groupby("year")}
    parity = rk_parity_training(hrrr_stats, training)
    control["checks"]["1_inputs"] = {
        "counts_by_year": counts, "covered_by_year": covered, "hrrr_training": parity,
        "counts_match": counts == reference["counts_by_year"],
        "covered_match": covered == reference["covered_by_year"],
        "pass": bool(parity["pass"] and counts == reference["counts_by_year"]
                     and covered == reference["covered_by_year"])}
    if not control["checks"]["1_inputs"]["pass"]:
        return finish("check 1 inputs")
    provenance = {
        "commit": commit, "module_sha256": control["inputs"]["module_sha256"], "note_sha256": SM_H_BINDING_SHA256,
        "rule_sha256": SM_H_RULE_SHA256, "clarification_sha256": SM_H_CLARIFICATION_1_SHA256,
        "training_rows": int(len(frame)), "train_years": sorted(int(y) for y in frame["year"].unique()),
        "train_nbm": train_nbm, "train_hrrr": training, "hrrr_train_corpus_stats": hrrr_stats,
        "inputs": {k: v for k, v in control["inputs"].items() if k != "module_sha256"},
        "versions": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
                     "sklearn": sklearn.__version__, "pandas": pd.__version__}}
    state, fits = sm_h_build_state(frame, buckets, markets=markets, provenance=provenance)
    pkl = out / "p3d_h_state.pkl"
    blob = _pickle.dumps(state, protocol=4)
    pkl.write_bytes(blob)
    digest = hashlib.sha256(blob).hexdigest()
    (out / "p3d_h_state.json").write_text(json.dumps(dict(provenance, state_sha256=digest, block=SM_H_STATE_BLOCK),
                                                     indent=1, sort_keys=True, default=str), encoding="utf-8")
    control["state_sha256"] = digest
    print(f"sm-h freeze: state {digest} from {len(frame)} rows", flush=True)
    frozen = mg3_load_state(pkl, digest)
    export = sm_h_export_parity(frozen, fits, frame, buckets)
    (out / "export_parity.json").write_text(json.dumps(export, indent=1), encoding="utf-8")
    control["checks"]["2_export_parity"] = export
    print(f"sm-h freeze export parity: {export}", flush=True)
    if not export["pass"]:
        return finish("check 2 export parity")
    fold = sm_h_fold_control(frame, buckets, _read_jsonl(smh_rows), markets=markets)
    (out / "fold_control.json").write_text(json.dumps(fold, indent=1), encoding="utf-8")
    control["checks"]["3_fold_reproduction"] = fold
    if not fold["pass"]:
        return finish("check 3 fold reproduction")
    return finish()


def mg3_release_files(root=None):
    root = Path(root or REPO_ROOT)
    return {rel: _rr_sha(root / rel) for rel in MG3_RELEASE_FILES}


def mg3_release_binding(*, land, corpus_dir, states=None, weights=None, root=None, markets=R0_MARKETS):
    """The MG-3 ``release-binding.json`` content (research side): rules, RN-1, data files, code files, states.

    RN-1 is recomputed by ``rr_point_rule`` from the land file and ``stations.json`` (refused on any mismatch with
    the pinned shas or the KSFO 3 / centre-4 reading) and bound as constants plus the recomputed indices. States and
    the weight table are bound by sha256 once frozen; until then they read ``PENDING``.
    The served SM-H 13-15 state (key ``SM_H_STATE_BLOCK``) is bound only from a verified load at
    ``SM_H_STATE_SHA256`` (``sm_h_load_state``); the recorded sha is that of the bytes the load verified. It
    replaces the 13-16 state at 13-15, except the ``excluded_markets`` (MG3-DC-1 s2.1).
    """
    point, report = rr_point_rule(land, corpus_dir, markets)
    stations = report["stations"]
    states = dict(states or {})
    unknown = set(states) - set(MG3_BLOCKS) - {SM_H_STATE_BLOCK}
    if unknown:
        raise PooledModelError(f"unknown MG-3 state blocks {sorted(unknown)}")
    smh_path = states.pop(SM_H_STATE_BLOCK, None)
    bound_states = {}
    for block in sorted(MG3_BLOCKS):
        path = states.get(block)
        if path is None:
            bound_states[block] = {"sha256": MG3_PENDING, "point_rule": MG3_POINT_RULES[block]}
            continue
        state = mg3_load_state(path, _rr_sha(path))
        if state.get("block") != block:
            raise PooledModelError(f"state {path} is block {state.get('block')}, not {block}")
        land_sha = (state.get("point_rule") or {}).get("land_sha256")
        if (land_sha == MG3_RN1["land_sha256"]) != (MG3_POINT_RULES[block] == "rn1"):
            raise PooledModelError(f"state {path}: point rule land sha {land_sha} does not fit block {block}")
        bound_states[block] = {"sha256": _rr_sha(path), "point_rule": MG3_POINT_RULES[block]}
    smh = {"sha256": MG3_PENDING, "point_rule": "nearest", "hours": list(SM_H_HOURS), "replaces": "13-16",
           "excluded_markets": list(SM_H_EXCLUDED_MARKETS)}
    if smh_path is not None:
        sm_h_load_state(smh_path, SM_H_STATE_SHA256)
        verified = _rr_sha(smh_path)
        if verified != SM_H_STATE_SHA256:  # the file changed between the verified load and this read
            raise PooledModelError(f"SM-H state {smh_path} changed while binding")
        smh["sha256"] = verified
    bound_states[SM_H_STATE_BLOCK] = smh
    return {
        "schema": MG3_BINDING_SCHEMA,
        "rules": {"mg3_state": MG3_STATE_RULE_SHA256, "mg3_weights": MG3_WEIGHTS_RULE_SHA256,
                  "rr": RR_RULE_SHA256, "rk": RK_RULE_SHA256, "rk1": RK_CLARIFICATION_RK1_SHA256,
                  "rn1": MG3_RN1["rule_sha256"], "sm_h": SM_H_RULE_SHA256, "smh1": SM_H_CLARIFICATION_1_SHA256,
                  "sm_h_binding": SM_H_BINDING_SHA256},
        "rn1": dict(MG3_RN1, recomputed={icao: stations[icao]["chosen_index"] for icao in sorted(stations)}),
        "point_rules": dict(MG3_POINT_RULES),
        "data_files": {"land_3x3.json": report["land_sha256"], "stations.json": report["stations_json_sha256"]},
        "files": mg3_release_files(root),
        "states": bound_states,
        "weights_sha256": _rr_sha(weights) if weights is not None else MG3_PENDING,
    }


def mg3_verify_release(path, *, land, corpus_dir, states=None, weights=None, root=None, markets=R0_MARKETS):
    """Recompute the binding from the running files and inputs; any field that differs refuses."""
    bound = json.loads(Path(path).read_text(encoding="utf-8"))
    running = mg3_release_binding(land=land, corpus_dir=corpus_dir, states=states, weights=weights, root=root,
                                  markets=markets)
    problems = [key for key in running if key != "files" and bound.get(key) != running[key]]
    problems += [rel for rel, sha in running["files"].items() if bound.get("files", {}).get(rel) != sha]
    problems += [rel for rel in bound.get("files", {}) if rel not in running["files"]]
    if problems:
        raise PooledModelError(f"MG-3 release binding mismatch: {problems}")
    return bound


# ------------------------------------------------- MG-3 freeze prep (1c): forward HRRR parity scorer

MG3_PARITY_RULE_SHA256 = "2c6e6045dca379854c281195e0a51a61f0de400bc517ed7faa444b2900a6593e"
MG3_PARITY_FP1_SHA256 = "533f6f3818389b5ec81f0ed4392ea022a3878d6a00dc8b1dd81c76b6bff039a7"  # rule_mg3_forward_parity.md
MG3_PARITY_TOL = 1e-9
MG3_PARITY_SHARE = 0.99
MG3_LATENCY_S = 600
MG3_RECORDER_ROW_SCHEMA = 2
MG3_STAMP = {"07-12": ("k_max_f", "k_tcdc"), "13-16": ("k_max_f_nearest_cell", None)}


def _mg3_utc(value):
    from datetime import datetime

    return None if value is None else datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _mg3_complete_lines(path):
    """JSON lines up to the last newline (a live recorder may be mid-append) -> (rows, the bytes kept)."""
    blob = Path(path).read_bytes()
    blob = blob[:blob.rfind(b"\n") + 1]
    return [json.loads(line) for line in blob.splitlines() if line.strip()], blob


def _mg3_message_index(messages):
    """{(key, variable): message} for TMP / TCDC records; the first record of a key wins."""
    out = {}
    for m in messages:
        record = str(m.get("idx_record", ""))
        var = next((v for v, prefix in RK_VARIABLES.items() if record.startswith(prefix + ":")), None)
        if var is not None:
            out.setdefault((m["key"], var), m)
    return out


def _mg3_block_of(hour):
    return next((b for b, spec in MG3_BLOCKS.items() if int(hour) in spec["hours"]), None)


def _mg3_share(ok, n):
    return {"n": int(n), "ok": int(ok), "share": (ok / n) if n else None}


def mg3_recorder_corpus(recorder_dir, out_dir, *, through, markets=R0_MARKETS):
    """Freeze a consistent copy of the recorder (complete lines only) as a training-format corpus.

    ``manifest.jsonl`` = the recorder's messages; ``selections.jsonl`` = one selection per counted row (row_schema
    2, R0 stations, local_date <= ``through``) carrying the row's own cycle and fhs, with ``latest_available_utc`` =
    max over its fhs and both variables of max(grib, idx LastModified), the training rule's availability.
    Returns (rows, messages, input shas).
    """
    src, out = Path(recorder_dir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=False)
    stations_blob = (src / "stations.json").read_bytes()
    stations = json.loads(stations_blob)
    keep = {icao for icao, s in stations.items() if s.get("market") in markets}
    snaps, snaps_blob = _mg3_complete_lines(src / "snapshots.jsonl")
    messages, msg_blob = _mg3_complete_lines(src / "messages.jsonl")
    rows = [r for r in snaps if r.get("row_schema") == MG3_RECORDER_ROW_SCHEMA and r.get("station") in keep
            and str(r["local_date"]) <= str(through) and _mg3_block_of(r["hour_local"]) is not None]
    index = _mg3_message_index(messages)
    selections = []
    for r in rows:
        latest = None
        if r.get("cycle_utc") and r.get("fhs"):
            cycle = _mg3_utc(r["cycle_utc"])
            stamps = []
            for fh in r["fhs"]:
                for var in RK_VARIABLES:
                    m = index.get((rk_message_key(cycle, fh), var))
                    stamps.append(None if m is None else max(_mg3_utc(m["grib_last_modified"]),
                                                             _mg3_utc(m["idx_last_modified"])))
            latest = None if any(s is None for s in stamps) else max(stamps).isoformat()
        selections.append({"station": r["station"], "local_date": r["local_date"], "hour_local": r["hour_local"],
                           "snapshot_utc": r["snapshot_utc"], "cycle_utc": r.get("cycle_utc"),
                           "fhs": list(r.get("fhs") or []), "latest_available_utc": latest})
    (out / "stations.json").write_bytes(stations_blob)
    (out / "manifest.jsonl").write_bytes(msg_blob)
    _write_jsonl(out / "selections.jsonl", selections)
    shas = {"recorder_snapshots_complete_lines": hashlib.sha256(snaps_blob).hexdigest(),
            "recorder_messages_complete_lines": hashlib.sha256(msg_blob).hexdigest(),
            "recorder_stations": hashlib.sha256(stations_blob).hexdigest(),
            "recorder_meta": _rr_sha(src / "meta.json")}
    return rows, messages, shas


def _mg3_archive(archive_dir, land, point, icao_market, markets):
    archive_point, _ = rr_point_rule(land, archive_dir, markets)
    if archive_point != point:
        raise PooledModelError("archive RN-1 indices differ from the recorder's")
    sel = {}
    for s in _rk_lines(Path(archive_dir) / "selections.jsonl", defaultdict(int), "selections"):
        if s.get("station") in icao_market:
            sel.setdefault((icao_market[s["station"]], str(s["local_date"]), int(s["hour_local"])), s)
    index = _mg3_message_index(_rk_lines(Path(archive_dir) / "manifest.jsonl", defaultdict(int), "manifest"))
    shas = {f"archive_{n}": _rr_sha(Path(archive_dir) / n) for n in ("manifest.jsonl", "selections.jsonl",
                                                                      "stations.json")}
    return {"selections": sel, "index": index, "shas": shas}


def mg3_forward_parity(*, recorder_dir, land, out_dir, through, commit, archive_dir=None, rule_path=None,
                       markets=R0_MARKETS):
    """rule_mg3_forward_parity.md: F0-F2 and F4 on the recorder rows, F3 against an archive corpus when given."""
    if rule_path is not None and _rr_sha(rule_path) != MG3_PARITY_RULE_SHA256:
        raise PooledModelError(f"rule {rule_path} is not {MG3_PARITY_RULE_SHA256}")
    out = require_output_outside_repo(out_dir)
    if out.exists():
        raise PooledModelError(f"refusing to overwrite {out}")
    corpus = out / "recorder_corpus"
    rows, messages, shas = mg3_recorder_corpus(recorder_dir, corpus, through=through, markets=markets)
    if not rows:
        raise PooledModelError("no counted recorder row (row_schema 2) up to --through")
    first = min(str(r["local_date"]) for r in rows)
    meta_path = Path(recorder_dir) / "meta.json"
    if not meta_path.exists():
        raise PooledModelError(f"{meta_path} is missing (FP-1 needs first_started_utc)")
    first_started = _mg3_utc(json.loads(meta_path.read_bytes()).get("first_started_utc"))
    if first_started is None:
        raise PooledModelError("meta.json has no first_started_utc (FP-1)")

    def in_window(day):
        return first <= day <= str(through)

    point, point_report = rr_point_rule(land, corpus, markets)
    stations = json.loads((corpus / "stations.json").read_bytes())
    icao_market = {icao: s["market"] for icao, s in stations.items() if s.get("market") in markets}
    index = _mg3_message_index(messages)
    archive = None if archive_dir is None else _mg3_archive(archive_dir, land, point, icao_market, markets)
    result = {"rule_sha256": MG3_PARITY_RULE_SHA256, "clarification_fp1_sha256": MG3_PARITY_FP1_SHA256,
              "first_started_utc": first_started.isoformat(), "commit": commit, "through": str(through), "first": first,
              "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "inputs": dict(shas, land_sha256=_rr_sha(land), **(archive["shas"] if archive else {})),
              "point_rule": point_report, "blocks": {}}
    passes = []
    for block, spec in sorted(MG3_BLOCKS.items()):
        block_point = point if spec["point"] == "rn1" else None
        feats, feat_stats = rk_hrrr_columns(corpus, markets, hours=spec["hours"], point=block_point,
                                            day_filter=in_window)
        block_rows = [r for r in rows if int(r["hour_local"]) in spec["hours"]]
        k_name, t_name = MG3_STAMP[block]
        f0 = {"rows": len(block_rows), "k_miss_differs": 0, "max_dk_max": 0.0, "max_dk_tcdc": 0.0,
              "msg_sha_missing": 0, "first_bad": None}
        f1 = {"equal": 0, "older": 0, "newer": 0, "n": 0}
        f3 = {"both_cycle": 0, "selection_equal": 0, "recorder_newer": 0, "values_compared": 0, "max_dk_max": 0.0,
              "max_dk_tcdc": 0.0, "bytes_checked": 0, "bytes_differ": 0, "bytes_absent": 0, "rows_no_archive": 0}
        used, cover, paused = {}, defaultdict(lambda: [0, 0]), 0
        for r in block_rows:
            market, day, hour = icao_market[r["station"]], str(r["local_date"]), int(r["hour_local"])
            e = feats[(market, day, hour)]
            paused += bool(r.get("paused_at_snapshot"))
            cover[market][0] += r.get("k_miss") == 0
            cover[market][1] += 1
            bad = False
            if float(e["k_miss"]) != float(r.get("k_miss", 1)):
                f0["k_miss_differs"] += 1
                bad = True
            elif e["k_miss"] == 0.0:
                dk = abs(e["k_max"] - float(r[k_name]))
                f0["max_dk_max"] = max(f0["max_dk_max"], dk)
                bad = bad or dk > MG3_PARITY_TOL
                if t_name is not None:
                    dt_ = abs(e["k_tcdc"] - float(r[t_name]))
                    f0["max_dk_tcdc"] = max(f0["max_dk_tcdc"], dt_)
                    bad = bad or dt_ > MG3_PARITY_TOL
            cycle = _mg3_utc(r.get("cycle_utc"))
            if cycle is not None:
                for var, row_shas in (r.get("hrrr_msg_sha256") or {}).items():
                    for fh, sha in zip(r["fhs"], row_shas):
                        m = index.get((rk_message_key(cycle, fh), var))
                        if m is None or m.get("msg_sha256") != sha:
                            f0["msg_sha_missing"] += 1
                            bad = True
                        else:
                            used[(m["key"], var)] = m
            if bad and f0["first_bad"] is None:
                f0["first_bad"] = {"station": r["station"], "local_date": day, "hour_local": hour}
            train = _mg3_utc(r.get("training_rule_cycle_utc"))
            f1["n"] += 1
            if cycle == train:
                f1["equal"] += 1
            elif cycle is None or (train is not None and cycle < train):
                f1["older"] += 1
            else:
                f1["newer"] += 1
            if archive is None:
                continue
            s = archive["selections"].get((market, day, hour))
            if s is None:
                f3["rows_no_archive"] += 1
                continue
            a_cycle = _mg3_utc(s.get("cycle_utc"))
            if cycle is None or a_cycle is None:
                f3["recorder_newer"] += cycle is not None  # a cycle the training rule did not have
                continue
            f3["both_cycle"] += 1
            if cycle != a_cycle or list(r["fhs"]) != list(s.get("fhs") or []):
                f3["recorder_newer"] += cycle > a_cycle
                continue
            f3["selection_equal"] += 1
            for fh in r["fhs"]:
                for var in RK_VARIABLES:
                    key = (rk_message_key(cycle, fh), var)
                    a, m = archive["index"].get(key), index.get(key)
                    f3["bytes_checked"] += 1
                    if a is None or m is None:
                        f3["bytes_absent"] += 1
                    elif a.get("msg_sha256") != m.get("msg_sha256"):
                        f3["bytes_differ"] += 1
        published = [(m, max(_mg3_utc(m["grib_last_modified"]), _mg3_utc(m["idx_last_modified"])))
                     for m in used.values()]
        # Clarification FP-1: messages S3 published before the recorder's FIRST start are excluded from F2 only.
        latency = sorted((_mg3_utc(m["captured_at_utc"]) - pub).total_seconds()
                         for m, pub in published if first_started is None or pub >= first_started)
        excluded_prestart = len(published) - len(latency)
        f0["pass"] = (f0["k_miss_differs"] == 0 and f0["msg_sha_missing"] == 0
                      and f0["max_dk_max"] <= MG3_PARITY_TOL and f0["max_dk_tcdc"] <= MG3_PARITY_TOL)
        f1["share_equal"] = f1["equal"] / f1["n"] if f1["n"] else None
        f1["pass"] = bool(f1["n"]) and f1["newer"] == 0 and f1["share_equal"] >= MG3_PARITY_SHARE
        f2 = dict(_mg3_share(sum(x <= MG3_LATENCY_S for x in latency), len(latency)),
                  excluded_prestart=excluded_prestart,
                  max_s=latency[-1] if latency else None,
                  p99_s=latency[max(0, math.ceil(0.99 * len(latency)) - 1)] if latency else None)
        f2["pass"] = bool(latency) and f2["share"] >= MG3_PARITY_SHARE
        f4 = {m: _mg3_share(c[0], c[1]) for m, c in sorted(cover.items())}
        for v in f4.values():
            v["pass"] = v["share"] is not None and v["share"] >= RK_COVERAGE_MIN
        f4_pass = len(f4) == len(markets) and all(v["pass"] for v in f4.values())
        entry = {"rows": len(block_rows), "paused_rows": paused, "recorder_feature_stats": feat_stats,
                 "F0": f0, "F1": f1, "F2": f2, "F4": {"markets": f4, "pass": f4_pass}}
        archive_pass = None
        if archive is not None:
            a_feats, f3["archive_stats"] = rk_hrrr_columns(archive_dir, markets, hours=spec["hours"],
                                                           point=block_point, day_filter=in_window)
            for r in block_rows:
                key = (icao_market[r["station"]], str(r["local_date"]), int(r["hour_local"]))
                e, a = feats[key], a_feats.get(key)
                if a is None or e["k_miss"] or a["k_miss"] or e["cycle_utc"] != a["cycle_utc"] or e["fhs"] != a["fhs"]:
                    continue
                f3["values_compared"] += 1
                f3["max_dk_max"] = max(f3["max_dk_max"], abs(e["k_max"] - a["k_max"]))
                f3["max_dk_tcdc"] = max(f3["max_dk_tcdc"], abs(e["k_tcdc"] - a["k_tcdc"]))
            f3["F3a_pass"] = (f3["both_cycle"] > 0 and f3["recorder_newer"] == 0
                              and f3["selection_equal"] / f3["both_cycle"] >= MG3_PARITY_SHARE)
            f3["F3b_pass"] = (f3["values_compared"] > 0 and f3["max_dk_max"] <= MG3_PARITY_TOL
                              and f3["max_dk_tcdc"] <= MG3_PARITY_TOL)
            f3["F3c_pass"] = f3["bytes_checked"] > 0 and f3["bytes_absent"] == 0 and f3["bytes_differ"] == 0
            f3["pass"] = f3["F3a_pass"] and f3["F3b_pass"] and f3["F3c_pass"]
            entry["F3"] = f3
            archive_pass = f3["pass"]
        result["blocks"][block] = entry
        passes.append((f0["pass"] and f1["pass"] and f2["pass"] and f4_pass, archive_pass))
    local_ok = all(p[0] for p in passes)
    if archive is None:
        result["verdict"] = "PARTIAL (archive pending)" if local_ok else "FAIL"
    else:
        result["verdict"] = "PASS" if local_ok and all(p[1] for p in passes) else "FAIL"
    (out / "forward_parity.json").write_text(json.dumps(result, indent=1, sort_keys=True, default=str),
                                             encoding="utf-8")
    return result


# ------------------------------------------------- R-U (rule_ru.md 9441cc94): HRRR spread anomaly vs P3d_H 13-16 error

RU_RULE_SHA256 = "9441cc9404f8f4da25520e6b97678d1609e9073f630828a0329209fd68730c36"
RU_STATE_SHA256 = "e891d884e06164a6925f6b2bbf1c7756529cb35222ab0c8c863552cfa7457db7"
RU_HRRR_PINS = ("409f6f917f2bca2999ebf39c52440c673760356295aaa291f572bfe624269935",
                "055add5a4a2aa25483f70ee6c355562d4730e8b01daa1f8b56adb5788512ec75")
RU_HOURS = (13, 14, 15, 16)


def ru_p0_stats(frame, z_col="z", e_col="e", years=None):
    """R-Z P0 statistics on a frame with year, market, hour, z, e (and optional rise): L3's thresholds unchanged."""
    import numpy as np

    from weather.calibration import rz_hrrr_spread as rz

    years = tuple(years or rz.LOYO_YEARS)
    year = frame["year"].to_numpy(int)
    z, e = frame[z_col].to_numpy(float), frame[e_col].to_numpy(float)
    rows = np.isfinite(z) & np.isfinite(e)
    za = np.full(len(frame), np.nan)
    for Y in years:
        te = year == Y
        table = frame[rows & ~te].groupby(["market", "hour"])[z_col].mean().to_dict()
        zb = np.array([table.get((m, h), np.nan) for m, h in zip(frame["market"], frame["hour"])], float)
        za[te] = z[te] - zb[te]
    rows &= np.isfinite(za)
    hours, markets = frame["hour"].to_numpy(int), frame["market"].astype(str).to_numpy()

    def rho(mask):
        m = rows & mask
        return {"rho": rz._spearman(za[m], e[m]), "n": int(m.sum())}

    pooled = rho(np.ones(len(frame), bool))
    per_year = {str(Y): rho(year == Y) for Y in years}
    sign = 1.0 if (pooled["rho"] or 0.0) >= 0 else -1.0
    flips = [y for y, r in per_year.items() if r["rho"] is not None and r["rho"] * sign < 0]
    closed = bool(pooled["rho"] is None or pooled["rho"] < rz.P0_RHO_MIN or len(flips) > rz.P0_FLIP_MAX)
    out = {"pooled": pooled, "per_year": per_year,
           "per_hour": {f"h{h:02d}": rho(hours == h) for h in sorted(set(hours.tolist()))},
           "per_market_reported_only": {m: rho(markets == m) for m in sorted(set(markets))},
           "opposite_sign_years": flips, "closed": closed}
    if "rise" in frame.columns:
        rise = frame["rise"].to_numpy(bool)
        out["rise_reported_only"] = {"pooled": rho(rise), **{f"h{h:02d}": rho(rise & (hours == h))
                                                               for h in sorted(set(hours.tolist()))}}
    return out


def ru_p0(*, records_root, nbm_train_corpus, hrrr_corpus, state_path, out_dir, commit, rule_path=None,
          markets=R0_MARKETS):
    """rule_ru.md: P0 of the HRRR 3x3 spread anomaly against |dmax - mu| of P3d_H 13-16, LOYO mu (history only)."""
    import numpy as np

    from weather.calibration import ols_floor_ladder as l9
    from weather.calibration import rz_hrrr_spread as rz
    from weather.market.market_registry import spec_for_id

    if rule_path is not None and _rr_sha(rule_path) != RU_RULE_SHA256:
        raise PooledModelError(f"rule {rule_path} is not {RU_RULE_SHA256}")
    out = require_output_outside_repo(out_dir)
    if out.exists():
        raise PooledModelError(f"refusing to overwrite {out}")
    state = mg3_load_state(state_path, RU_STATE_SHA256)
    if state["block"] != "13-16":
        raise PooledModelError("R-U needs the 13-16 state")
    # The P3d_H 13-16 training frame, built exactly as mg3_freeze_state built it.
    timezones = {m: spec_for_id(m).timezone for m in markets}
    frame, _buckets = dev_training_frame(records_root, markets)
    if frame["year"].max() >= 2026:
        raise PooledModelError("an R-U row is from 2026")
    frame, _ = attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff, timezones)
    frame = frame[frame["hour"].isin(RU_HOURS)].reset_index(drop=True)
    train_hrrr, _ = rk_hrrr_columns(hrrr_corpus, markets)
    frame, _ = rk_training_columns(frame, train_hrrr)
    extra = list(state["extra_hgb"])
    # Secondary mu (reported only): the frozen state's pre-floor mean, in-sample on every history row.
    mu = np.full(len(frame), np.nan)
    for i, r in enumerate(frame.to_dict("records")):
        if not (math.isfinite(float(r["F"])) and math.isfinite(float(r["x_current_temp"]))):
            continue
        X, mu0, g, _ = mg3_state_X(state, int(r["hour"]), market=r["market"],
                                   target_date=date.fromisoformat(r["target_date"]), high_so_far=float(r["F"]),
                                   current_temp=float(r["x_current_temp"]), nbm_mean=float(r["fh"]),
                                   extra={c: r[c] for c in extra})
        mean = state["hours"][int(r["hour"])]["mean"]
        mu[i] = float((mu0 + np.array([[1.0, g, max(g, 0.0)]]) @ mean["ols"] + mean["hgb"].predict(X))[0])
    frame["mu_frozen"] = mu
    # Decision mu: leave-one-year-out P3d_H refits (the R-K LOYO code path), so mu and zbar are both out of year.
    simple, extra_ols, extra_hgb, extra_scale = _arm_spec(RK_ARMS[MG3_ARM])
    mu_l = np.full(len(frame), np.nan)
    for Y in sorted(int(y) for y in frame["year"].unique()):
        for h in RU_HOURS:
            te_mask = ((frame["year"] == Y) & (frame["hour"] == h)).to_numpy()
            if not te_mask.any():
                continue
            tr = frame[(frame["year"] != Y) & (frame["hour"] == h)].reset_index(drop=True)
            fit = _rung_entry(tr, simple, extra_ols, extra_hgb, extra_scale)["fit"]
            yhat, _ = fit["mean"].predict(frame[te_mask].reset_index(drop=True))
            mu_l[te_mask] = np.asarray(yhat, float)
            print(f"ru loyo {Y} h{h}: {int(te_mask.sum())} rows", flush=True)
    frame["mu"] = mu_l
    frame["e"] = (frame["y"].astype(float) - frame["mu"]).abs()
    frame["rise"] = frame["y"].astype(float) > np.floor(frame["F"].astype(float) + 0.5)
    # z: L3's R-Z code, unchanged; ICAO -> market by the corpus's stations.json.
    spread, spread_stats, pins = rz.hrrr_spread(hrrr_corpus, *RU_HRRR_PINS)
    stations = json.loads((Path(hrrr_corpus) / "stations.json").read_bytes())
    spread["market"] = [stations.get(s, {}).get("market") for s in spread["station"]]
    z = spread.set_index(["market", "local_date", "hour"])["z"].to_dict()
    sd9 = spread.set_index(["market", "local_date", "hour"])["sd9"].to_dict()
    keys = list(zip(frame["market"], frame["target_date"], frame["hour"].astype(int)))
    frame["z"] = [z.get(k, np.nan) for k in keys]
    frame["sd9"] = [sd9.get(k, np.nan) for k in keys]
    coverage = float(np.isfinite(frame["z"].to_numpy(float)).mean())
    result = {"rule_sha256": RU_RULE_SHA256, "commit": commit, "state_sha256": RU_STATE_SHA256,
              "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "rz_module_sha256": hashlib.sha256(Path(rz.__file__).read_bytes()).hexdigest(),
              "inputs": dict(pins, nbm_train_corpus=_rr_sha(nbm_train_corpus)), "spread_stats": spread_stats,
              "rows": int(len(frame)), "years": sorted(int(y) for y in frame["year"].unique()),
              "z_coverage": coverage, "coverage_min": rz.COVERAGE_MIN,
              "thresholds": {"rho_min": rz.P0_RHO_MIN, "flip_max": rz.P0_FLIP_MAX}}
    usable = frame[np.isfinite(frame["mu"].to_numpy(float))].reset_index(drop=True)
    result["p0"] = ru_p0_stats(usable)
    result["precondition_coverage_ok"] = coverage >= rz.COVERAGE_MIN
    result["verdict"] = ("STOPPED (coverage)" if not result["precondition_coverage_ok"]
                         else "CLOSED" if result["p0"]["closed"] else "SURVIVES")
    # Reported only: the high_so_far structure by hour.
    half = np.floor(usable["F"].astype(float) + 0.5)
    result["high_so_far_reported_only"] = {
        f"h{h:02d}": {"rows": int((usable["hour"] == h).sum()),
                      "median_e": float(usable.loc[usable["hour"] == h, "e"].median()),
                      "share_dmax_eq_halfup_F": float((usable["y"].astype(float) == half)[usable["hour"] == h].mean()),
                      "median_sd9": float(usable.loc[usable["hour"] == h, "sd9"].median())}
        for h in RU_HOURS}
    # Secondary, reported only: the same P0 with the frozen (in-sample) mu.
    fz = frame.assign(e=(frame["y"].astype(float) - frame["mu_frozen"]).abs())
    result["frozen_mu_reported_only"] = ru_p0_stats(
        fz[np.isfinite(fz["mu_frozen"].to_numpy(float))].reset_index(drop=True))
    out.mkdir(parents=True)
    (out / "ru_p0.json").write_text(json.dumps(result, indent=1, sort_keys=True, default=str), encoding="utf-8")
    print(f"R-U P0: {result['verdict']} pooled {result['p0']['pooled']}", flush=True)
    return result


# ------------------------------------------------- R-V (rule_rv.md): MOS/NBE day-max as one 13-16 centre column

RV_RULE_SHA256 = "b0cf2a03224d2581f96c77b801dd5244353ca1f2025ab0802940dcf65e88e818"  # rv/rule_rv.md
RV_HOURS = (13, 14, 15, 16)
RV_POOLS = (("13-16", None), ("13-14", (13, 14)), ("15-16", (15, 16)))
RV_SOURCES = {  # IEM model -> (day-max field, candidate run hours of UTC day D (latest first), availability lag)
    "GFS": ("n_x", (6, 0), 4 * 3600 + 1800),
    "NAM": ("n_x", (0,), 4 * 3600),
    "NBE": ("txn", (1, 0), 2 * 3600),  # the early D-bearing cycle: 01Z in 2021-25, 00Z in 2026 (rule deviation)
}
RV_RANGE_F = (-40.0, 130.0)
RV_MIN_SOURCES = 2
RV_COVERAGE_MIN = 0.95
RV_SHIFT_MAX_F = 1.5
RV_CONTROL_TOL = 1e-12
RV_DUMMY_MARKETS = tuple(m for m in R0_MARKETS if m != "atlanta")
RV_DUMMIES = tuple(f"mi_{m}" for m in RV_DUMMY_MARKETS)
RV_ARMS = {
    "B_N": True,
    "P3d_N_fix": False,
    "P3d_V": {"simple": False, "extra_hgb": ("v_gap",)},
    "P3d_I": {"simple": False, "extra_ols": RV_DUMMIES},
}
RV_PAIRS = (("P3d_V", "P3d_N_fix"), ("P3d_V", "P3d_I"), ("P3d_I", "P3d_N_fix"), ("P3d_N_fix", "B_N"))
RV_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py"
RV_FETCH_SPACING_S = 8.0


def rv_fetch_windows(years):
    """(year, sts, ets) per year: runtimes 07-31 00Z .. 09-30 23:59Z, 2026 clipped to 09-29 23:59Z."""
    out = []
    for year in years:
        if int(year) > 2026:
            raise PooledModelError("R-V reads nothing after 2026-09-29")
        end = "09-29T23:59Z" if int(year) == 2026 else "09-30T23:59Z"
        out.append((int(year), f"{year}-07-31T00:00Z", f"{year}-{end}"))
    return out


RV_C1_SHA256 = "db11d8d2e1443143816302cbe16b1f065401ca4b8aa3d8ca61122ba1aaef3ba5"  # rv/clarification_rv_c1.md


def rv_c1_fetch_windows(years):
    """RV-C1 section 2: runtimes 09-30 00Z .. 12-31 23:59Z, history 2021-25 only."""
    out = []
    for year in years:
        if not 2021 <= int(year) <= 2025:
            raise PooledModelError("RV-C1 fetches history 2021-25 only")
        out.append((int(year), f"{year}-09-30T00:00Z", f"{year}-12-31T23:59Z"))
    return out


def rv_fetch(*, out_dir, years, markets=R0_MARKETS, spacing=RV_FETCH_SPACING_S, opener=None, sleep=None,
             windows=None):
    """Fetch the IEM MOS CSVs R-V needs (one connection, >= ``spacing`` s apart, back off on throttling).

    Writes ``<ICAO>_<MODEL>_<year>.csv`` plus ``manifest.json`` (sha256 per file). Rows with a runtime on or after
    2026-09-30 are dropped before writing. Existing complete files are kept (resumable)."""
    import time
    import urllib.parse
    import urllib.request

    from weather.market.market_registry import spec_for_id

    sleep = sleep or time.sleep
    opener = opener or (lambda url: urllib.request.urlopen(url, timeout=300).read().decode("utf-8", "replace"))
    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    last = [0.0]

    def get(params):
        backoff = 60
        while True:
            wait = spacing - (time.time() - last[0])
            if wait > 0:
                sleep(wait)
            last[0] = time.time()
            try:
                body = opener(RV_URL + "?" + urllib.parse.urlencode(params))
            except Exception as exc:  # noqa: BLE001 - network errors back off and retry
                print(f"rv-fetch {params} error {exc!r}; sleep {backoff}", flush=True)
                sleep(backoff)
                backoff = min(backoff * 2, 960)
                continue
            if "Too many requests" in body[:500]:
                print(f"rv-fetch {params} throttled; sleep {backoff}", flush=True)
                sleep(backoff)
                backoff = min(backoff * 2, 960)
                continue
            if not body.startswith("runtime"):
                raise PooledModelError(f"IEM returned no CSV for {params}: {body[:120]!r}")
            return body

    for market in markets:
        icao = spec_for_id(market).icao
        for model in RV_SOURCES:
            for year, sts, ets in (windows or rv_fetch_windows)(years):
                path = out / f"{icao}_{model}_{year}.csv"
                if path.exists():
                    continue
                body = get({"station": icao, "model": model, "sts": sts, "ets": ets, "format": "csv"})
                lines = body.splitlines(keepends=True)
                kept = [lines[0]] + [ln for ln in lines[1:] if ln[:10] < "2026-09-30"]
                tmp = path.with_suffix(".part")
                tmp.write_text("".join(kept), encoding="utf-8", newline="")
                tmp.replace(path)
                print(f"rv-fetch {path.name} rows={len(kept) - 1}", flush=True)
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob("*.csv"))}
    manifest = {"rule_sha256": RV_RULE_SHA256, "url": RV_URL, "years": sorted(int(y) for y in years),
                "windows": [list(w) for w in (windows or rv_fetch_windows)(years)],
                "markets": list(markets), "models": list(RV_SOURCES), "files": files}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


def rv_load(corpus_dir, years):
    """{(icao, model): {(runtime, ftime): value}} from an rv-fetch directory, sha-checked against its manifest."""
    import csv
    from datetime import datetime, timezone

    root = Path(corpus_dir)
    manifest = json.loads((root / "manifest.json").read_bytes())
    table = {}
    for name, sha in sorted(manifest["files"].items()):
        icao, model, year = name[:-4].split("_")
        if int(year) not in set(int(y) for y in years):
            continue
        data = (root / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != sha:
            raise PooledModelError(f"{name} does not match the manifest")
        field = RV_SOURCES[model][0]
        values = table.setdefault((icao, model), {})
        for rec in csv.DictReader(data.decode("utf-8").splitlines()):
            runtime = datetime.fromisoformat(rec["runtime"]).replace(tzinfo=timezone.utc)
            if runtime.date() > N_DEV_LAST:
                raise PooledModelError(f"{name} holds a runtime after 2026-09-29")
            ftime = datetime.fromisoformat(rec["ftime"]).replace(tzinfo=timezone.utc)
            values[(runtime, ftime)] = _num(rec.get(field))
    return table, hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()


def rv_source_value(values, model, day, instant):
    """One source's D-max at ``instant`` per rule_rv.md: (value, runtime) or (nan, None)."""
    from datetime import datetime, timedelta, timezone

    _, hours, lag = RV_SOURCES[model]
    ftime = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(days=1)
    for hour in hours:
        runtime = datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)
        if runtime + timedelta(seconds=lag) > instant:
            continue
        value = values.get((runtime, ftime), float("nan"))
        if math.isfinite(value) and RV_RANGE_F[0] <= value <= RV_RANGE_F[1]:
            return value, runtime
    return float("nan"), None


def rv_entry(table, icao, day, hour, tz):
    """``mos_x`` and per-source values for (station, local target date, cutoff hour)."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz) if isinstance(tz, str) else tz  # the registry gives IANA names
    instant = datetime(day.year, day.month, day.day, int(hour), tzinfo=tz).astimezone(timezone.utc)
    src = {m: rv_source_value(table.get((icao, m), {}), m, day, instant)[0] for m in RV_SOURCES}
    found = [v for v in src.values() if math.isfinite(v)]
    mos_x = sum(found) / len(found) if len(found) >= RV_MIN_SOURCES else float("nan")
    return {"mos_x": mos_x, **{f"src_{m}": v for m, v in src.items()}}


def rv_columns(entry, anchor):
    anchor = float(anchor) if anchor is not None else float("nan")
    gap = entry["mos_x"] - anchor if math.isfinite(entry["mos_x"]) and math.isfinite(anchor) else float("nan")
    return {"v_gap": gap}


def rv_training_columns(frame, table, timezones, icaos):
    """Attach ``v_gap``, ``mos_x``, the per-source values and the market dummies to training rows."""
    cols, stats = defaultdict(list), defaultdict(int)
    for market, day, hour, fh in zip(frame["market"], frame["target_date"], frame["hour"], frame["fh"]):
        day = date.fromisoformat(str(day)[:10])
        entry = rv_entry(table, icaos[market], day, hour, timezones[market])
        values = {**entry, **rv_columns(entry, fh)}
        year = str(day.year)
        stats["rows"] += 1
        stats["rows_covered"] += math.isfinite(entry["mos_x"])
        stats[f"rows_{year}"] += 1
        for m in RV_SOURCES:
            stats[f"{m}_{year}"] += math.isfinite(entry[f"src_{m}"])
        for k, v in values.items():
            cols[k].append(v)
    out = frame.copy()
    for k, v in cols.items():
        out[k] = v
    for m, name in zip(RV_DUMMY_MARKETS, RV_DUMMIES):
        out[name] = (out["market"] == m).astype(float)
    return out, dict(stats)


def rv_gate_1a(stats):
    coverage = stats.get("rows_covered", 0) / max(stats.get("rows", 0), 1)
    years = sorted({k.split("_")[1] for k in stats if k.startswith("rows_") and k[5:].isdigit()})
    per = {m: {y: stats.get(f"{m}_{y}", 0) / max(stats[f"rows_{y}"], 1) for y in years} for m in RV_SOURCES}
    return {"coverage": coverage, "threshold": RV_COVERAGE_MIN, "per_source_year": per,
            "pass": coverage >= RV_COVERAGE_MIN}


def rv_gate_1b(frame):
    """Per-year mean/sd of each source minus ``fh`` and of ``v_gap``; pass if no year's v_gap mean is off by > 1.5 F."""
    import numpy as np

    out = {"per_year": {}}
    pooled = float(np.nanmean(frame["v_gap"].to_numpy(float)))
    worst = 0.0
    for year, part in frame.groupby(frame["target_date"].astype(str).str[:4]):
        fh = part["fh"].to_numpy(float)
        row = {}
        for col in [f"src_{m}" for m in RV_SOURCES] + ["v_gap"]:
            d = part[col].to_numpy(float) - (fh if col != "v_gap" else 0.0)
            row[col] = {"mean": float(np.nanmean(d)), "sd": float(np.nanstd(d)), "n": int(np.isfinite(d).sum())}
        out["per_year"][year] = row
        worst = max(worst, abs(row["v_gap"]["mean"] - pooled))
    out.update(pooled_v_gap_mean=pooled, worst_year_shift=worst, threshold=RV_SHIFT_MAX_F,
               **{"pass": worst <= RV_SHIFT_MAX_F})
    return out


def rung_v_loyo(*, records_root, nbm_train_corpus, mos_corpus, rj_loyo_rows, out_dir, markets=R0_MARKETS):
    """R-V gates 1a, 1b and 1 (nested LOYO 2021-25, h13-16). No dev row is read."""
    from weather.calibration import ols_floor_ladder as l9
    from weather.market.market_registry import spec_for_id

    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise PooledModelError(f"refusing to write into a non-empty {out}")
    table, manifest_sha = rv_load(mos_corpus, years=range(2021, 2026))
    audit = {"rule_sha256": RV_RULE_SHA256, "arms": {k: str(v) for k, v in RV_ARMS.items()},
             "hours": list(RV_HOURS), "gates": {},
             "inputs": {"nbm_train_corpus": hashlib.sha256(Path(nbm_train_corpus).read_bytes()).hexdigest(),
                        "rj_loyo_rows": hashlib.sha256(Path(rj_loyo_rows).read_bytes()).hexdigest(),
                        "mos_manifest": manifest_sha,
                        "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}

    def finish():
        (out / "rv_loyo_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True), encoding="utf-8")
        return audit

    specs = {m: spec_for_id(m) for m in markets}
    timezones = {m: s.timezone for m, s in specs.items()}
    icaos = {m: s.icao for m, s in specs.items()}
    frame, buckets = dev_training_frame(records_root, markets)
    if frame["year"].max() >= 2026:
        raise PooledModelError("a training row is from 2026")
    frame, audit["train_nbm"] = attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff, timezones)
    frame = frame[frame["hour"].isin(RV_HOURS)].reset_index(drop=True)
    frame, audit["training"] = rv_training_columns(frame, table, timezones, icaos)
    audit["gates"]["1a_coverage"] = rv_gate_1a(audit["training"])
    if not audit["gates"]["1a_coverage"]["pass"]:
        audit["stopped_at"] = "gate 1a coverage (STOPPED, not a kill)"
        return finish()
    audit["gates"]["1b_version_shift"] = rv_gate_1b(frame)
    if not audit["gates"]["1b_version_shift"]["pass"]:
        audit["stopped_at"] = "gate 1b version shift (STOPPED, not a kill)"
        return finish()
    rows = rung_loyo(frame, buckets, RV_HOURS, arms=RV_ARMS)
    _write_jsonl(out / "loyo_rows.jsonl", rows)
    audit["control_rj_reproduction"] = rk_control(rows, _read_jsonl(rj_loyo_rows), tol=RV_CONTROL_TOL,
                                                  hours=RV_HOURS)
    if not audit["control_rj_reproduction"]["pass"]:
        audit["stopped_at"] = "control: R-J LOYO reproduction failed (refused, not a gate)"
        return finish()
    summary = rg_loyo_summary(rows, pairs=RV_PAIRS, pooled=RV_POOLS)
    by_market = {}
    for market in sorted({r["market"] for r in rows}):
        part = [r for r in rows if r["market"] == market]
        by_market[market] = rg_loyo_summary(part, pairs=RV_PAIRS[:2], pooled=(("13-16", None),))
    vs_fix = summary["P3d_V-P3d_N_fix|13-16|brier"]
    vs_int = summary["P3d_V-P3d_I|13-16|brier"]
    audit["gates"]["1_loyo"] = {"summary": summary, "by_market": by_market,
                                "P3d_V-P3d_N_fix": vs_fix, "P3d_V-P3d_I": vs_int,
                                "pass": vs_fix["ci95"][1] < 0 and vs_int["ci95"][1] < 0}
    if not audit["gates"]["1_loyo"]["pass"]:
        audit["stopped_at"] = "gate 1 LOYO (KILL: MOS/NBE day-max closed as a 13-16 centre input on P3d_N_fix)"
    return finish()


# ---------------------------------------------------------------- R-V clarification RV-C1 (served arms)

RV_C1_MOS_AUGSEP_SHA256 = "1e6e6b3d75a1e5bef688f4e0136c37cf42c650b7e8add13b1544187adbba3c50"  # rv/mos manifest
RV_C1_OCT_KEYS_SHA256 = "2c555bdadb853d2da9d4269294fb255c4f982acceab0a7886c34629f366b4745"  # C10 loyo_rows
RV_C1_AUG_KEYS_SHA256 = "2a91bb80e7e1d82b885ae9e07b97b35a936864f57c629c7cdd6a02e5de4d37dd"  # R-V gate-1 rows
RV_C1_C10_FWD_ROWS_SHA256 = "c69b1351e0a48cdb18abc24453364941615ece3fc873c54f331854d620aefe47"
RV_C1_V = ("v_gap",)
RV_C1_SMHV_EXTRA = ("k_max", "k_gap", "k_tcdc", "v_gap")
RV_C1_PARITY_TOL = 1e-9
RV_C1_TOL = 1e-12
RV_C1_PAIRS_A = (("P3d_V_fwd", "P3d_N_fwd"),)
RV_C1_POOLS_A = (("13-16", None), ("13-14", (13, 14)), ("15-16", (15, 16)))
RV_C1_PAIRS_B = (("SM_HV", "SM_H"),)
RV_C1_POOLS_B = (("13-15", None),)


def rv_c1_merge_tables(first, second):
    """Union of two ``rv_load`` tables on (station, model, runtime, ftime). -> (table, conflicts)."""
    table = {k: dict(v) for k, v in first.items()}
    conflicts = []
    for key, values in second.items():
        into = table.setdefault(key, {})
        for when, value in values.items():
            if when in into:
                old = into[when]
                same = old == value or (not math.isfinite(old) and not math.isfinite(value))
                if not same:
                    conflicts.append([key[0], key[1], when[0].isoformat(), when[1].isoformat(), old, value])
                continue
            into[when] = value
    return table, conflicts


def rv_c1_v_entry(train, extra):
    """One shell ``hours[h]`` entry for the forward spec plus ``extra`` HGB columns (mg3_hour_entry layout)."""
    return mg3_hour_entry(_rung_entry(train, False, (), tuple(extra)))


def rv_c1_v_shell(state, hour, entry, extra):
    return dict(fwd_shell(state, {int(hour): entry}), extra_hgb=list(extra))


def rv_c1_serve(shell, row):
    """The candidate's serving path: ``state_features`` (shell conversion included) plus the shell's extras."""
    return mg3_state_distribution(
        shell, int(row["hour"]), market=row["market"], target_date=date.fromisoformat(str(row["target_date"])[:10]),
        high_so_far=float(row["F"]), current_temp=float(row["x_current_temp"]), nbm_mean=float(row["fh"]),
        extra={c: row[c] for c in shell["extra_hgb"]})


def _rv_c1_finite(part):
    import numpy as np

    ok = np.isfinite(part["F"].to_numpy(float)) & np.isfinite(part["x_current_temp"].to_numpy(float))
    return part[ok].reset_index(drop=True), int((~ok).sum())


def rv_c1_rows_a(scored, fwd_frame, fwd_state, hours=RV_HOURS, markets=R0_MARKETS, serve_n=None, serve_v=None):
    """RV-C1 (a): P3d_N_fwd and P3d_V_fwd fold rows on each scored set, plus tier-2 and V-off parity.

    ``scored`` {name: frame}. Each fold for held-out year y drops year y's Aug-Dec rows of ``fwd_frame``.
    -> ({name: rows}, {name: excluded}, parity)."""
    from weather.calibration import feature_model as fm

    serve_n = serve_n or sm_h_frozen_dist
    serve_v = serve_v or rv_c1_serve
    rows = {name: [] for name in scored}
    excluded = {name: 0 for name in scored}
    tier2, v_off, checked = 0.0, 0.0, 0
    for hour in hours:
        fwd_hour = fwd_frame[fwd_frame["hour"] == hour].reset_index(drop=True)
        full_n = fwd_shell(fwd_state, {int(hour): fwd_hour_entry(fwd_hour, markets)})
        full_off = rv_c1_v_shell(fwd_state, hour, rv_c1_v_entry(fwd_hour, ()), ())
        years = sorted(set().union(*(set(f.loc[f["hour"] == hour, "year"].unique()) for f in scored.values())))
        for year in years:
            train = fwd_hour[fwd_hour["year"] != year].reset_index(drop=True)
            fold_n = fwd_shell(fwd_state, {int(hour): fwd_hour_entry(train, markets)})
            fold_v = rv_c1_v_shell(fwd_state, hour, rv_c1_v_entry(train, RV_C1_V), RV_C1_V)
            for name, frame in scored.items():
                val, dropped = _rv_c1_finite(frame[(frame["hour"] == hour) & (frame["year"] == year)])
                excluded[name] += dropped
                for i in range(len(val)):
                    one = val.iloc[i]
                    ref = serve_n(fwd_state, one)
                    tier2 = max(tier2, dist_max_abs(serve_n(full_n, one), ref))
                    v_off = max(v_off, dist_max_abs(serve_v(full_off, one), ref))
                    checked += 1
                    actual = int(one["y"])
                    row = {"hour": int(hour), "year": int(year), "market": str(one["market"]),
                           "date": str(one["target_date"])[:10], "y": actual}
                    for arm, dist in (("P3d_N_fwd", serve_n(fold_n, one)), ("P3d_V_fwd", serve_v(fold_v, one))):
                        row[f"{arm}_brier"] = sm_h_brier(dist, actual)
                        row[f"{arm}_log"] = fm.log_loss(dist, actual)
                    rows[name].append(row)
        print(f"rv-c1 (a) hour {hour}: tier2 {tier2:.3g} v_off {v_off:.3g}", flush=True)
    total = sum(len(r) for r in rows.values())
    parity = {"rows": checked, "tolerance": RV_C1_PARITY_TOL,
              "tier2": {"max_abs": tier2, "pass": tier2 <= RV_C1_PARITY_TOL and checked == total},
              "v_off": {"max_abs": v_off, "pass": v_off <= RV_C1_PARITY_TOL and checked == total}}
    return rows, excluded, parity


def rv_c1_rows_b(frame, buckets, hours=SM_H_HOURS):
    """RV-C1 (b): SM_H and SM_HV blocked LOYO on the Oct-Dec rows, as ``sm_h_rows``. -> (rows, excluded)."""
    from weather.calibration import feature_model as fm

    arms = {"SM_H": _arm_spec(RK_ARMS["P3d_H"]), "SM_HV": (False, (), RV_C1_SMHV_EXTRA, ())}
    rows, excluded = [], 0
    for hour in hours:
        at_hour = frame[frame["hour"] == hour]
        for year in sorted(at_hour["year"].unique()):
            train = at_hour[at_hour["year"] != year].reset_index(drop=True)
            val, dropped = _rv_c1_finite(at_hour[at_hour["year"] == year])
            excluded += dropped
            entries = {arm: _rung_entry(train, *spec) for arm, spec in arms.items()}
            for market in sorted(val["market"].unique()):
                part = val[val["market"] == market].reset_index(drop=True)
                dists = {arm: _dist_from_fit(e, part, buckets, market) for arm, e in entries.items()}
                for i in range(len(part)):
                    actual = int(part.at[i, "y"])
                    row = {"hour": int(hour), "year": int(year), "market": market,
                           "date": str(part.at[i, "target_date"])[:10], "y": actual}
                    for arm, d in dists.items():
                        row[f"{arm}_brier"] = sm_h_brier(d[i], actual)
                        row[f"{arm}_log"] = fm.log_loss(d[i], actual)
                    rows.append(row)
        print(f"rv-c1 (b) hour {hour}: {sum(1 for r in rows if r['hour'] == hour)} rows", flush=True)
    return rows, excluded


def rv_c1_reproduce(rows, reference, arm, ref_field, tol=RV_C1_TOL):
    """Identical keys and |rows[arm] - reference[ref_field]| <= tol on every row."""
    got = {row_key(r): r[f"{arm}_brier"] for r in rows}
    ref = {row_key(r): float(r[ref_field]) for r in reference}
    common = set(got) & set(ref)
    worst = max((abs(got[k] - ref[k]) for k in common), default=float("inf"))
    same = set(got) == set(ref) and len(got) == len(rows)
    return {"rows": len(got), "reference_rows": len(ref), "same_keys": same, "missing": len(set(ref) - set(got)),
            "extra": len(set(got) - set(ref)), "max_abs": worst, "tolerance": tol, "pass": bool(same and worst <= tol)}


def rv_c1_keys(rows, reference):
    got, ref = {row_key(r) for r in rows}, {row_key(r) for r in reference}
    return {"rows": len(rows), "reference_rows": len(ref), "missing": len(ref - got), "extra": len(got - ref),
            "pass": got == ref and len(got) == len(rows)}


def _rv_c1_by_market(rows, pairs, pooled):
    return {m: rg_loyo_summary([r for r in rows if r["market"] == m], pairs=pairs, pooled=pooled)
            for m in sorted({r["market"] for r in rows})}


def rv_c1(*, records_root, nbm_train_corpus, hrrr_corpus, mos_augsep, mos_octdec, fwd_state, c10_rows_path,
          c10_fwd_rows, smh_rows, rv_rows, out_dir, markets=R0_MARKETS):
    """RV-C1 (clarification_rv_c1.md): reads (a) and (b) in one run. History only; no dev row is read."""
    from weather.calibration import ols_floor_ladder as l9
    from weather.market.market_registry import spec_for_id

    out = require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise PooledModelError(f"refusing to write into a non-empty {out}")
    corpus = Path(hrrr_corpus)
    audit = {"clarification_sha256": RV_C1_SHA256, "rule_sha256": RV_RULE_SHA256, "checks": {}, "gates": {},
             "inputs": {"nbm_train_corpus": _sm_h_bound(nbm_train_corpus, SM_H_NBM_SHA256, "NBM corpus"),
                        "fwd_state": _sm_h_bound(fwd_state, C10_FWD_STATE_SHA256, "served P3d_N state"),
                        "mos_augsep_manifest": _sm_h_bound(Path(mos_augsep) / "manifest.json",
                                                           RV_C1_MOS_AUGSEP_SHA256, "Aug-Sep MOS manifest"),
                        "mos_octdec_manifest": _rr_sha(Path(mos_octdec) / "manifest.json"),
                        "c10_rows": _sm_h_bound(c10_rows_path, RV_C1_OCT_KEYS_SHA256, "C10 rows"),
                        "c10_fwd_rows": _sm_h_bound(c10_fwd_rows, RV_C1_C10_FWD_ROWS_SHA256, "C10 fwd rows"),
                        "smh_rows": _sm_h_bound(smh_rows, C10_SMH_ROWS_SHA256, "SM-H rows"),
                        "rv_rows": _sm_h_bound(rv_rows, RV_C1_AUG_KEYS_SHA256, "R-V gate-1 rows"),
                        **{f"hrrr_{n}": _sm_h_bound(corpus / n, sha, f"HRRR {n}")
                           for n, sha in SM_H_HRRR_SHA256.items()},
                        "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}

    def finish(stopped=None):
        if stopped:
            audit["stopped_at"] = stopped
        (out / "rvc1_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True, default=str),
                                             encoding="utf-8")
        return audit

    years = range(2021, 2026)
    aug_table, _ = rv_load(mos_augsep, years)
    oct_table, _ = rv_load(mos_octdec, years)
    table, conflicts = rv_c1_merge_tables(aug_table, oct_table)
    specs = {m: spec_for_id(m) for m in markets}
    timezones = {m: s.timezone for m, s in specs.items()}
    icaos = {m: s.icao for m, s in specs.items()}
    nbm = l9.load_nbm(nbm_train_corpus)
    # scored Oct-Dec 13-16 (C10's rows), with v_gap: gates 1a/1b first (STOP, not VOID)
    oct_frame, buckets = sm_h_frame(records_root, markets, hours=RV_HOURS)
    oct_frame, audit["oct_nbm"] = attach_training_nbm(oct_frame, nbm, l9.nbm_at_cutoff, timezones)
    oct_frame, oct_stats = rv_training_columns(oct_frame, table, timezones, icaos)
    audit["gates"]["1a_octdec"] = rv_gate_1a(oct_stats)
    audit["gates"]["1b_octdec"] = rv_gate_1b(oct_frame)
    if not audit["gates"]["1a_octdec"]["pass"]:
        return finish("gate 1a on Oct-Dec rows (STOPPED, not a kill)")
    if not audit["gates"]["1b_octdec"]["pass"]:
        return finish("gate 1b on Oct-Dec rows (STOPPED, not a kill)")
    # forward training frame (a) and the Aug-Sep scored rows
    fwd_frame, _ = forward_training_frame(records_root, markets)
    fwd_rows_all = int(len(fwd_frame))
    years_ok = set(int(y) for y in fwd_frame["year"].unique()) <= set(FORWARD_YEARS)
    fwd_frame = fwd_frame[fwd_frame["hour"].isin(RV_HOURS)].reset_index(drop=True)
    fwd_frame, audit["fwd_nbm"] = attach_training_nbm(fwd_frame, nbm, l9.nbm_at_cutoff, timezones)
    fwd_frame, fwd_stats = rv_training_columns(fwd_frame, table, timezones, icaos)
    audit["gates"]["fwd_frame_reported"] = {"1a": rv_gate_1a(fwd_stats), "1b": rv_gate_1b(fwd_frame)}
    aug_frame, _ = dev_training_frame(records_root, markets)
    aug_frame, _ = attach_training_nbm(aug_frame, nbm, l9.nbm_at_cutoff, timezones)
    aug_frame = aug_frame[aug_frame["hour"].isin(RV_HOURS)].reset_index(drop=True)
    aug_frame, _ = rv_training_columns(aug_frame, table, timezones, icaos)
    # (b) frame: the SM-H frame plus v_gap
    hrrr, audit["hrrr_corpus_stats"] = rk_hrrr_columns(corpus, markets, hours=SM_H_HOURS, day_filter=sm_h_day_filter)
    b_frame, b_buckets = sm_h_frame(records_root, markets)
    b_frame, _ = attach_training_nbm(b_frame, nbm, l9.nbm_at_cutoff, timezones)
    b_frame, audit["b_training_hrrr"] = rk_training_columns(b_frame, hrrr)
    b_frame, _ = rv_training_columns(b_frame, table, timezones, icaos)
    audit["checks"]["1_inputs"] = {"fwd_frame_rows": fwd_rows_all, "expected": C10_FWD_TRAINING_ROWS,
                                   "years_2021_25": years_ok, "merge_conflicts": conflicts[:20],
                                   "n_conflicts": len(conflicts),
                                   "hrrr": rk_parity_training(audit["hrrr_corpus_stats"], audit["b_training_hrrr"]),
                                   "pass": (fwd_rows_all == C10_FWD_TRAINING_ROWS and years_ok and not conflicts)}
    audit["checks"]["1_inputs"]["pass"] = bool(audit["checks"]["1_inputs"]["pass"]
                                               and audit["checks"]["1_inputs"]["hrrr"]["pass"])
    if not audit["checks"]["1_inputs"]["pass"]:
        return finish("check 1 inputs (VOID)")
    served = pickle.loads(Path(fwd_state).read_bytes())
    rows_a, audit["rows_excluded_a"], parity = rv_c1_rows_a({"octdec": oct_frame, "augsep": aug_frame}, fwd_frame,
                                                           served, markets=markets)
    rows_b, audit["rows_excluded_b"] = rv_c1_rows_b(b_frame, b_buckets)
    _write_jsonl(out / "rows_a_octdec.jsonl", rows_a["octdec"])
    _write_jsonl(out / "rows_a_augsep.jsonl", rows_a["augsep"])
    _write_jsonl(out / "rows_b.jsonl", rows_b)
    audit["outputs"] = {n: _rr_sha(out / n) for n in ("rows_a_octdec.jsonl", "rows_a_augsep.jsonl", "rows_b.jsonl")}
    audit["checks"]["2_keys"] = {"a_octdec": rv_c1_keys(rows_a["octdec"], _read_jsonl(c10_rows_path)),
                                 "a_augsep": rv_c1_keys(rows_a["augsep"], _read_jsonl(rv_rows)),
                                 "b": rv_c1_keys(rows_b, _read_jsonl(smh_rows))}
    audit["checks"]["2_keys"]["pass"] = all(v["pass"] for v in audit["checks"]["2_keys"].values())
    audit["checks"]["3_tier2"] = parity["tier2"]
    audit["checks"]["4_v_off_a"] = parity["v_off"]
    audit["checks"]["5_c10_fwd_reproduction"] = rv_c1_reproduce(rows_a["octdec"], _read_jsonl(c10_fwd_rows),
                                                                "P3d_N_fwd", "P3d_N_fwd_brier")
    audit["checks"]["6_v_off_b"] = rv_c1_reproduce(rows_b, _read_jsonl(smh_rows), "SM_H", "SM_H_brier")
    failed = [k for k, v in audit["checks"].items() if not v["pass"]]
    if failed:
        return finish(f"checks {failed} (VOID; no score read)")
    sa = rg_loyo_summary(rows_a["octdec"], pairs=RV_C1_PAIRS_A, pooled=RV_C1_POOLS_A)
    sa_aug = rg_loyo_summary(rows_a["augsep"], pairs=RV_C1_PAIRS_A, pooled=RV_C1_POOLS_A)
    sb = rg_loyo_summary(rows_b, pairs=RV_C1_PAIRS_B, pooled=RV_C1_POOLS_B)
    audit["summary"] = {"a_octdec": sa, "a_augsep_reported": sa_aug, "b": sb,
                        "a_by_market": _rv_c1_by_market(rows_a["octdec"], RV_C1_PAIRS_A, (("13-16", None),)),
                        "b_by_market": _rv_c1_by_market(rows_b, RV_C1_PAIRS_B, (("13-15", None),))}
    a = sa["P3d_V_fwd-P3d_N_fwd|13-16|brier"]
    b = sb["SM_HV-SM_H|13-15|brier"]
    audit["decision"] = {
        "a": {"pair": "P3d_V_fwd-P3d_N_fwd|13-16|brier (Oct-Dec keys)", "estimate": a["estimate"],
              "ci95": a["ci95"], "adopt_candidate": a["ci95"][1] < 0},
        "b": {"pair": "SM_HV-SM_H|13-15|brier", "estimate": b["estimate"], "ci95": b["ci95"],
              "adopt_candidate": b["ci95"][1] < 0}}
    audit["decision"]["r_v"] = ("gate 2 re-registered against the passing arm(s)"
                                if a["ci95"][1] < 0 or b["ci95"][1] < 0 else "R-V CLOSES; gate 2 never runs")
    return finish()


# -------------------------------------------------------------------------- CLI


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
    ll = sub.add_parser("rung-l-loyo", help="R-L gate 1 (training half) and gate 2 LOYO (heavy)")
    ll.add_argument("--records", required=True)
    ll.add_argument("--nbm-train-corpus", required=True)
    ll.add_argument("--nbs", required=True, help="L12 NBS/NBH corpus directory (2021-25)")
    ll.add_argument("--ra-loyo-rows", required=True, help="R-A loyo_rows.jsonl (incumbent-arm control)")
    ll.add_argument("--out", required=True)
    ll.add_argument("--variant", choices=sorted(RL_VARIANTS), default="R-L")
    kd = sub.add_parser("rung-k-dev-emit", help="R-K gate 1b and h13-16 dev distributions (heavy)")
    kd.add_argument("--records", required=True)
    kd.add_argument("--layout", required=True)
    kd.add_argument("--replay-root", required=True)
    kd.add_argument("--nbm-train-corpus", required=True)
    kd.add_argument("--hrrr", required=True, help="L13 HRRR corpus 2021-25 (training columns)")
    kd.add_argument("--hrrr-dev", required=True, help="L13 HRRR corpus 2026-07-30..09-29 (dev columns)")
    kd.add_argument("--loyo-audit", required=True, help="rk_loyo_audit.json (gates 1a-2 must have passed)")
    kd.add_argument("--out", required=True)
    ks = sub.add_parser("rung-k-score", help="R-K gates 3-4 on the dev scorecard (heavy)")
    ks.add_argument("--layout", required=True)
    ks.add_argument("--emit", required=True)
    ks.add_argument("--out", required=True)
    ld = sub.add_parser("rung-l-dev-emit", help="R-L gate 1b and h07-12 dev distributions (heavy)")
    ld.add_argument("--records", required=True)
    ld.add_argument("--layout", required=True)
    ld.add_argument("--replay-root", required=True)
    ld.add_argument("--nbm-train-corpus", required=True)
    ld.add_argument("--nbs", required=True, help="L12 NBS corpus 2021-25 (training columns)")
    ld.add_argument("--nbs-dev", required=True, help="L12 NBS corpus 2026-07-30..09-29 (dev columns)")
    ld.add_argument("--loyo-audit", required=True, help="rl_loyo_audit.json (gates 1a-2 must have passed)")
    ld.add_argument("--out", required=True)
    ld.add_argument("--variant", choices=sorted(RL_VARIANTS), default="R-L")
    ls_ = sub.add_parser("rung-l-score", help="R-L gates 3-4 on the dev scorecard (heavy)")
    ls_.add_argument("--layout", required=True)
    ls_.add_argument("--emit", required=True)
    ls_.add_argument("--coefficients", required=True)
    ls_.add_argument("--nowcasts", required=True)
    ls_.add_argument("--out", required=True)
    ls_.add_argument("--variant", choices=sorted(RL_VARIANTS), default="R-L")
    ad = sub.add_parser("rung-l-anchor-diag", help="R-L2 anchor diagnostic: |n_txn - L9 NBM| (inputs only)")
    ad.add_argument("--nbs", required=True)
    ad.add_argument("--nbs-dev", required=True)
    ad.add_argument("--nbm-train-corpus", required=True)
    ad.add_argument("--nbm-dev-corpus", required=True)
    ad.add_argument("--out", required=True)
    rl_ = sub.add_parser("rung-r-loyo", help="R-R gate 1a (training half) and gate 2 LOYO (heavy)")
    rl_.add_argument("--records", required=True)
    rl_.add_argument("--nbm-train-corpus", required=True)
    rl_.add_argument("--hrrr", required=True, help="L13 HRRR 07-12 corpus (2021-25 and 2026 dev in one)")
    rl_.add_argument("--land", required=True, help="L13 land_3x3.json (RN-1 point rule)")
    rl_.add_argument("--ra-loyo-rows", required=True, help="R-A loyo_rows.jsonl (incumbent-arm control)")
    rl_.add_argument("--out", required=True)
    rd_ = sub.add_parser("rung-r-dev-emit", help="R-R gate 1b and h07-12 dev distributions (heavy)")
    rd_.add_argument("--records", required=True)
    rd_.add_argument("--layout", required=True)
    rd_.add_argument("--replay-root", required=True)
    rd_.add_argument("--nbm-train-corpus", required=True)
    rd_.add_argument("--hrrr", required=True)
    rd_.add_argument("--land", required=True)
    rd_.add_argument("--loyo-audit", required=True, help="rr_loyo_audit.json (gates 1a-2 must have passed)")
    rd_.add_argument("--out", required=True)
    rs_ = sub.add_parser("rung-r-score", help="R-R gates 3-5 on the dev scorecard (heavy)")
    rs_.add_argument("--layout", required=True)
    rs_.add_argument("--emit", required=True)
    rs_.add_argument("--coefficients", required=True)
    rs_.add_argument("--nowcasts", required=True)
    rs_.add_argument("--rf-result", required=True)
    rs_.add_argument("--out", required=True)
    sl_ = sub.add_parser("rung-s-loyo", help="R-S gate 1a, guard G-s, controls and gate 2 LOYO for a window (heavy)")
    sl_.add_argument("--window", required=True, choices=sorted(RS_WINDOWS))
    sl_.add_argument("--records", required=True)
    sl_.add_argument("--nbm-train-corpus", required=True)
    sl_.add_argument("--reference-loyo-rows", required=True, help="R-R (07-12) or R-K (13-16) loyo_rows.jsonl")
    sl_.add_argument("--layout", required=True, help="dev layout (inputs only: captured v2 spread for G-v)")
    sl_.add_argument("--hrrr", help="07-12 only: L13 HRRR corpus (R-R's)")
    sl_.add_argument("--land", help="07-12 only: L13 land_3x3.json (R-R's)")
    sl_.add_argument("--out", required=True)
    se_ = sub.add_parser("rung-s-dev-emit", help="R-S gate 1b and dev distributions for a window (heavy)")
    se_.add_argument("--window", required=True, choices=sorted(RS_WINDOWS))
    se_.add_argument("--records", required=True)
    se_.add_argument("--layout", required=True)
    se_.add_argument("--replay-root", required=True)
    se_.add_argument("--nbm-train-corpus", required=True)
    se_.add_argument("--nbm-dev-corpus", required=True)
    se_.add_argument("--loyo-audit", required=True, help="rs_loyo_audit.json (gates 1a-2 must have passed)")
    se_.add_argument("--hrrr")
    se_.add_argument("--land")
    se_.add_argument("--out", required=True)
    ss_ = sub.add_parser("rung-s-score", help="R-S gates 3-4 on the dev scorecard (heavy)")
    ss_.add_argument("--layout", required=True)
    ss_.add_argument("--emit", action="append", required=True, help="WINDOW=DIR, repeatable")
    ss_.add_argument("--coefficients")
    ss_.add_argument("--nowcasts")
    ss_.add_argument("--out", required=True)
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
    ms = sub.add_parser("mg3-freeze-state", help="MG-3 (1a-i): frozen P3d_H state for one block + controls (heavy)")
    ms.add_argument("--block", required=True, choices=sorted(MG3_BLOCKS))
    ms.add_argument("--records", required=True)
    ms.add_argument("--layout", required=True)
    ms.add_argument("--replay-root", required=True)
    ms.add_argument("--nbm-train-corpus", required=True)
    ms.add_argument("--hrrr-corpus", required=True)
    ms.add_argument("--hrrr-dev-corpus", default=None, help="13-16 only: the 2026 dev HRRR corpus")
    ms.add_argument("--land", default=None, help="07-12 only: the RN-1 land file")
    ms.add_argument("--reference", required=True, help="the block's dev_P3d_H.jsonl (identity control)")
    ms.add_argument("--rule", required=True)
    ms.add_argument("--commit", required=True)
    ms.add_argument("--out", required=True)
    mw = sub.add_parser("mg3-freeze-weights", help="MG-3 (1a-ii): frozen blend_l6_H weights + control (heavy)")
    mw.add_argument("--layout", required=True)
    mw.add_argument("--emit-dir", required=True)
    mw.add_argument("--coefficients", required=True)
    mw.add_argument("--nowcasts", required=True)
    mw.add_argument("--rr-score", required=True)
    mw.add_argument("--rule", required=True)
    mw.add_argument("--commit", required=True)
    mw.add_argument("--out", required=True)
    rf = sub.add_parser("mg3-refit-weights-rf1", help="MG-3 RF-1: 07-12 blend weights refitted once vs SM-L6 (heavy)")
    for opt in ("--layout", "--emit", "--coefficients", "--nowcasts", "--season-nowcasts", "--partner-vectors",
                "--rr-score", "--frozen-weights", "--out", "--commit"):
        rf.add_argument(opt, required=True)
    rf.add_argument("--note", default=None)
    sh = sub.add_parser("sm-h-loyo", help="SM-H: season-matched P3d_H 13-15 LOYO vs frozen P3d_N (heavy)")
    for opt in ("--records", "--nbm-train-corpus", "--hrrr", "--p3d-n-state", "--part1a", "--out"):
        sh.add_argument(opt, required=True)
    c10 = sub.add_parser("c10-sel", help="C10-sel: SM-N vs served P3d_N_fwd at 13-16, history LOYO (heavy)")
    for opt in ("--records", "--nbm-train-corpus", "--fwd-state", "--dev-state", "--part1a", "--smh-rows", "--out"):
        c10.add_argument(opt, required=True)
    rd = sub.add_parser("sm-h-redecide", help="SM-H SMH-1: SM_H vs P3d_N_fwd at 13-15 from the C10 rows")
    for opt in ("--smh-rows", "--c10-audit", "--out"):
        rd.add_argument(opt, required=True)
    sf = sub.add_parser("sm-h-freeze", help="SM-H binding note: served SM-H 13-15 state + identity control (heavy)")
    for opt in ("--records", "--nbm-train-corpus", "--hrrr", "--smh-audit", "--smh-rows", "--out", "--commit"):
        sf.add_argument(opt, required=True)
    sf.add_argument("--note", default=None)
    mb = sub.add_parser("mg3-release-binding", help="MG-3 (1b): release-binding.json content incl. RN-1")
    mb.add_argument("--land", required=True)
    mb.add_argument("--corpus", required=True, help="the 07-12 HRRR corpus holding stations.json")
    mb.add_argument("--state-0712", default=None)
    mb.add_argument("--state-1316", default=None)
    mb.add_argument("--state-smh", default=None, help="the served SM-H 13-15 state (binding note, row 52)")
    mb.add_argument("--weights", default=None)
    mb.add_argument("--out", required=True)
    ru = sub.add_parser("ru-p0", help="R-U P0 (rule_ru.md): HRRR 3x3 spread anomaly vs P3d_H 13-16 error, history")
    ru.add_argument("--records", required=True)
    ru.add_argument("--nbm-train-corpus", required=True)
    ru.add_argument("--hrrr", required=True)
    ru.add_argument("--state", required=True)
    ru.add_argument("--rule", required=True)
    ru.add_argument("--commit", required=True)
    ru.add_argument("--out", required=True)
    vf = sub.add_parser("rv-fetch", help="R-V: fetch IEM MOS/NBE CSVs for the 11 US stations (network, light)")
    vf.add_argument("--years", required=True, help="comma list, e.g. 2021,2022,2023,2024,2025 or 2026")
    vf.add_argument("--out", required=True)
    vf.add_argument("--octdec", action="store_true", help="RV-C1: runtimes 09-30..12-31, 2021-25 only")
    vc = sub.add_parser("rv-c1", help="R-V RV-C1: P3d_V_fwd vs served P3d_N_fwd 13-16 and SM_HV vs SM-H 13-15 (heavy)")
    for opt in ("--records", "--nbm-train-corpus", "--hrrr", "--mos-augsep", "--mos-octdec", "--fwd-state",
                "--c10-rows", "--c10-fwd-rows", "--smh-rows", "--rv-rows", "--out"):
        vc.add_argument(opt, required=True)
    vl = sub.add_parser("rung-v-loyo", help="R-V gates 1a, 1b and 1 (nested LOYO 2021-25 h13-16) (heavy)")
    vl.add_argument("--records", required=True)
    vl.add_argument("--nbm-train-corpus", required=True)
    vl.add_argument("--mos", required=True, help="rv-fetch directory holding 2021-25")
    vl.add_argument("--rj-loyo-rows", required=True, help="R-J loyo_rows.jsonl (incumbent-arm control)")
    vl.add_argument("--out", required=True)
    mp = sub.add_parser("mg3-forward-parity", help="MG-3 (1c): forward HRRR parity F0-F4 (inputs only)")
    mp.add_argument("--recorder", required=True)
    mp.add_argument("--land", required=True)
    mp.add_argument("--through", required=True, help="last local date counted (inclusive)")
    mp.add_argument("--archive", default=None, help="an L13 archive corpus for the same forward dates (F3)")
    mp.add_argument("--rule", required=True)
    mp.add_argument("--commit", required=True)
    mp.add_argument("--out", required=True)
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
    if args.command == "rung-l-loyo":
        audit = rung_l_loyo(records_root=args.records, nbm_train_corpus=args.nbm_train_corpus, nbs_corpus=args.nbs,
                            ra_loyo_rows=args.ra_loyo_rows, out_dir=args.out, variant=args.variant)
        print(json.dumps({"gates": {k: v.get("pass") for k, v in audit["gates"].items()},
                          "stopped_at": audit.get("stopped_at"),
                          "control": audit.get("control_ra_reproduction")}, indent=1))
        return 0
    if args.command == "rung-k-dev-emit":
        audit = rung_k_dev_emit(records_root=args.records, layout=args.layout, replay_root=args.replay_root,
                                nbm_train_corpus=args.nbm_train_corpus, hrrr_corpus=args.hrrr,
                                hrrr_dev_corpus=args.hrrr_dev, loyo_audit=args.loyo_audit, out_dir=args.out)
        print(json.dumps({"gates": audit["gates"], "stopped_at": audit.get("stopped_at"),
                          "rh_reproduction": audit["rh_reproduction"]}, indent=1))
        return 0
    if args.command == "rung-k-score":
        result = rung_k_score(layout=args.layout, emit_dir=args.emit, out_path=Path(args.out))
        print(json.dumps({"gates": result["gates"], "stopped_at": result.get("stopped_at")}, indent=1))
        return 0
    if args.command == "rung-l-dev-emit":
        audit = rung_l_dev_emit(records_root=args.records, layout=args.layout, replay_root=args.replay_root,
                                nbm_train_corpus=args.nbm_train_corpus, nbs_corpus=args.nbs,
                                nbs_dev_corpus=args.nbs_dev, loyo_audit=args.loyo_audit, out_dir=args.out,
                                variant=args.variant)
        print(json.dumps({"gates": audit["gates"], "stopped_at": audit.get("stopped_at"),
                          "ra_reproduction": audit["ra_reproduction"]}, indent=1, default=float))
        return 0
    if args.command == "rung-l-score":
        result = rung_l_score(layout=args.layout, emit_dir=args.emit, coefficients=args.coefficients,
                              nowcasts=args.nowcasts, out_path=Path(args.out), variant=args.variant)
        print(json.dumps({"gates": result["gates"], "stopped_at": result.get("stopped_at")}, indent=1))
        return 0
    if args.command == "rung-l-anchor-diag":
        report = rl_anchor_diag(nbs_corpus=args.nbs, nbs_dev_corpus=args.nbs_dev,
                                nbm_train_corpus=args.nbm_train_corpus, nbm_dev_corpus=args.nbm_dev_corpus,
                                out_path=Path(args.out))
        print(json.dumps({"counts": report["counts"]}, indent=1))
        return 0
    if args.command == "rung-r-loyo":
        audit = rung_r_loyo(records_root=args.records, nbm_train_corpus=args.nbm_train_corpus, hrrr_corpus=args.hrrr,
                            land=args.land, ra_loyo_rows=args.ra_loyo_rows, out_dir=args.out)
        print(json.dumps({"gates": {k: v.get("pass") for k, v in audit["gates"].items()},
                          "stopped_at": audit.get("stopped_at"),
                          "control": audit.get("control_ra_reproduction")}, indent=1))
        return 0
    if args.command == "rung-r-dev-emit":
        audit = rung_r_dev_emit(records_root=args.records, layout=args.layout, replay_root=args.replay_root,
                                nbm_train_corpus=args.nbm_train_corpus, hrrr_corpus=args.hrrr, land=args.land,
                                loyo_audit=args.loyo_audit, out_dir=args.out)
        print(json.dumps({"gates": audit["gates"], "stopped_at": audit.get("stopped_at"),
                          "ra_reproduction": audit["ra_reproduction"]}, indent=1, default=float))
        return 0
    if args.command == "rung-r-score":
        result = rung_r_score(layout=args.layout, emit_dir=args.emit, coefficients=args.coefficients,
                              nowcasts=args.nowcasts, rf_result=args.rf_result, out_path=Path(args.out))
        print(json.dumps({"gates": result["gates"], "stopped_at": result.get("stopped_at")}, indent=1))
        return 0
    if args.command == "rung-s-loyo":
        audit = rung_s_loyo(window=args.window, records_root=args.records, nbm_train_corpus=args.nbm_train_corpus,
                            reference_loyo_rows=args.reference_loyo_rows, layout=args.layout, out_dir=args.out,
                            hrrr_corpus=args.hrrr, land=args.land)
        gv = audit.get("guard_gv") or {}
        print(json.dumps({"gates": {k: v.get("pass") for k, v in audit["gates"].items()},
                          "guard_gv": {c: v["ratio_dev_over_train_median"] for c, v in gv.get("columns", {}).items()},
                          "guard_gs": audit.get("guard_gs"), "stopped_at": audit.get("stopped_at")}, indent=1))
        return 0
    if args.command == "rung-s-dev-emit":
        audit = rung_s_dev_emit(window=args.window, records_root=args.records, layout=args.layout,
                                replay_root=args.replay_root, nbm_train_corpus=args.nbm_train_corpus,
                                nbm_dev_corpus=args.nbm_dev_corpus, loyo_audit=args.loyo_audit, out_dir=args.out,
                                hrrr_corpus=args.hrrr, land=args.land)
        print(json.dumps({"gates": {k: v.get("pass") for k, v in audit["gates"].items()},
                          "stopped_at": audit.get("stopped_at"),
                          "base_reproduction": audit.get("base_reproduction")}, indent=1))
        return 0
    if args.command == "rung-s-score":
        emit_dirs = dict(item.split("=", 1) for item in args.emit)
        result = rung_s_score(layout=args.layout, emit_dirs=emit_dirs, coefficients=args.coefficients,
                              nowcasts=args.nowcasts, out_path=Path(args.out))
        print(json.dumps({w: {"gates": r["gates"], "stopped_at": r.get("stopped_at")}
                          for w, r in result["windows"].items()}, indent=1, default=float))
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
    if args.command == "mg3-freeze-state":
        control = mg3_freeze_state(
            block=args.block, records_root=args.records, layout=args.layout, replay_root=args.replay_root,
            nbm_train_corpus=args.nbm_train_corpus, hrrr_corpus=args.hrrr_corpus,
            hrrr_dev_corpus=args.hrrr_dev_corpus, land=args.land, reference=args.reference, out_dir=args.out,
            commit=args.commit, rule_path=args.rule)
        print(json.dumps(control, indent=1, sort_keys=True, default=str))
        return 0 if control["pass"] else 1
    if args.command == "mg3-freeze-weights":
        result = mg3_freeze_weights(layout=args.layout, emit_dir=args.emit_dir, coefficients=args.coefficients,
                                    nowcasts=args.nowcasts, rr_score=args.rr_score, out_dir=args.out,
                                    commit=args.commit, rule_path=args.rule)
        print(json.dumps({k: result[k] for k in ("control", "weights", "reported")}, indent=1, sort_keys=True))
        return 0 if result["control"]["pass"] else 1
    if args.command == "mg3-refit-weights-rf1":
        result = mg3_refit_weights_rf1(layout=args.layout, emit_dir=args.emit, coefficients=args.coefficients,
                                       nowcasts=args.nowcasts, season_nowcasts=args.season_nowcasts,
                                       partner_vectors=args.partner_vectors, rr_score=args.rr_score,
                                       frozen_weights=args.frozen_weights, out_dir=args.out, commit=args.commit,
                                       note_path=args.note)
        print(json.dumps({"checks": {k: v["pass"] for k, v in result["checks"].items()},
                          "stopped_at": result.get("stopped_at"), "weights": result["weights"]}, indent=1))
        return 0 if not result.get("stopped_at") else 1
    if args.command == "sm-h-loyo":
        audit = sm_h_loyo(records_root=args.records, nbm_train_corpus=args.nbm_train_corpus, hrrr_corpus=args.hrrr,
                          p3d_n_state=args.p3d_n_state, part1a=args.part1a, out_dir=args.out)
        print(json.dumps({"checks": {k: v.get("pass") for k, v in audit["checks"].items()},
                          "stopped_at": audit.get("stopped_at"), "decision": audit.get("decision")}, indent=1))
        return 0 if not audit.get("stopped_at") else 1
    if args.command == "c10-sel":
        audit = c10_sel(records_root=args.records, nbm_train_corpus=args.nbm_train_corpus, fwd_state=args.fwd_state,
                        dev_state=args.dev_state, part1a=args.part1a, smh_rows=args.smh_rows, out_dir=args.out)
        print(json.dumps({"checks": {k: v.get("pass") for k, v in audit["checks"].items()},
                          "stopped_at": audit.get("stopped_at"),
                          "selected": (audit.get("decision") or {}).get("selected")}, indent=1))
        return 0 if not audit.get("stopped_at") else 1
    if args.command == "sm-h-redecide":
        audit = sm_h_redecide(smh_rows=args.smh_rows, c10_audit=args.c10_audit, out_dir=args.out)
        print(json.dumps({"stopped_at": audit.get("stopped_at"), "decision": audit.get("decision")}, indent=1))
        return 0 if not audit.get("stopped_at") else 1
    if args.command == "sm-h-freeze":
        control = sm_h_freeze_state(records_root=args.records, nbm_train_corpus=args.nbm_train_corpus,
                                    hrrr_corpus=args.hrrr, smh_audit=args.smh_audit, smh_rows=args.smh_rows,
                                    out_dir=args.out, commit=args.commit, note_path=args.note)
        print(json.dumps({"state_sha256": control.get("state_sha256"), "stopped_at": control.get("stopped_at"),
                          "checks": {k: v.get("pass") for k, v in control["checks"].items()}}, indent=1))
        return 0 if control["pass"] else 1
    if args.command == "mg3-release-binding":
        if out.exists():
            raise PooledModelError(f"refusing to overwrite {out}")
        states = {b: s for b, s in (("07-12", args.state_0712), ("13-16", args.state_1316),
                                    (SM_H_STATE_BLOCK, args.state_smh)) if s}
        binding = mg3_release_binding(land=args.land, corpus_dir=args.corpus, states=states, weights=args.weights)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(binding, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"sha256": _rr_sha(out), "states": binding["states"],
                          "rn1": binding["rn1"]["recomputed"]}, indent=1, sort_keys=True))
        return 0
    if args.command == "ru-p0":
        result = ru_p0(records_root=args.records, nbm_train_corpus=args.nbm_train_corpus, hrrr_corpus=args.hrrr,
                       state_path=args.state, out_dir=args.out, commit=args.commit, rule_path=args.rule)
        return 0 if result["verdict"] != "STOPPED (coverage)" else 3
    if args.command == "rv-fetch":
        manifest = rv_fetch(out_dir=args.out, years=[int(y) for y in args.years.split(",")],
                            windows=rv_c1_fetch_windows if args.octdec else None)
        print(json.dumps({"files": len(manifest["files"])}, indent=1))
        return 0
    if args.command == "rv-c1":
        audit = rv_c1(records_root=args.records, nbm_train_corpus=args.nbm_train_corpus, hrrr_corpus=args.hrrr,
                      mos_augsep=args.mos_augsep, mos_octdec=args.mos_octdec, fwd_state=args.fwd_state,
                      c10_rows_path=args.c10_rows, c10_fwd_rows=args.c10_fwd_rows, smh_rows=args.smh_rows,
                      rv_rows=args.rv_rows, out_dir=args.out)
        print(json.dumps({"stopped_at": audit.get("stopped_at"),
                          "checks": {k: v.get("pass") for k, v in audit["checks"].items()},
                          "decision": audit.get("decision")}, indent=1, default=str))
        return 0 if not audit.get("stopped_at") else 1
    if args.command == "rung-v-loyo":
        audit = rung_v_loyo(records_root=args.records, nbm_train_corpus=args.nbm_train_corpus, mos_corpus=args.mos,
                            rj_loyo_rows=args.rj_loyo_rows, out_dir=args.out)
        print(json.dumps({"gates": {k: v.get("pass") for k, v in audit["gates"].items()},
                          "stopped_at": audit.get("stopped_at"),
                          "control": audit.get("control_rj_reproduction")}, indent=1))
        return 0
    if args.command == "mg3-forward-parity":
        result = mg3_forward_parity(recorder_dir=args.recorder, land=args.land, out_dir=args.out,
                                    through=args.through, commit=args.commit, archive_dir=args.archive,
                                    rule_path=args.rule)
        summary = {b: {k: v["pass"] for k, v in e.items() if k.startswith("F")} for b, e in result["blocks"].items()}
        print(json.dumps({"verdict": result["verdict"], "blocks": summary}, indent=1, sort_keys=True))
        return 0 if result["verdict"] != "FAIL" else 1
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
