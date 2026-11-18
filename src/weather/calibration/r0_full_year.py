"""Research-only: R0 trained on the full year versus the served target-season window.

R0 (``python -m weather.calibration.feature_model --column-allowlist r0:<market>``)
trains each cutoff-hour HGB on the prior years' +/-7-day window around the
centre date, about 15 days per year. This module asks one question: does the
same model, trained on every 2021-2025 day the PIT corpora cover, plus a
day-of-year seasonal pair, score better on the *same* held-out window days?

It reuses the trainer's own building blocks (record extraction, frame, fold-local
preprocessing, climatology blend, loss), so the windowed arm reproduces the
trainer's per-row blocked validation rows exactly, and the full-year arm differs
only in the HGB's training rows and the two seasonal columns:

* validation rows: the held-out year's in-window target days (holdout_year);
* the climatology prior and its bucket space are the windowed ones in every arm;
* one HGB fit per (hour, held-out year, arm): deterministic, and its training
  set does not depend on the validation row, so it equals the per-row refit.

Several season corpora that share years (Jan-Jul, Aug-Sep, Oct-Dec) are read as
one through ``SeasonCorpusUnion``, which dispatches by date and fails closed on a
date two corpora both plan, an incompatible manifest, or an uncovered date.

Research only. No network. Writes only under ``--output-root``, which may not be
inside the repository's ``data`` or ``artifacts`` trees. Serving, capture and the
served trainer never import it, and an import from anywhere other than this
module's own ``-m`` entry point or pytest raises ``ImportError`` (fail closed).
The seasonal columns are not served features: a promotion would need a
versioned serving feature first.
"""

from __future__ import annotations

import sys

RESEARCH_ENTRY_MODULE = "weather.calibration.r0_full_year"


def _refuse_production_import() -> None:
    """Allow only ``python -m weather.calibration.r0_full_year`` and pytest."""
    if __name__ == "__main__" or "pytest" in sys.modules:
        return
    raise ImportError(
        f"{RESEARCH_ENTRY_MODULE} is research-only; run it with "
        f"'python -m {RESEARCH_ENTRY_MODULE}' (production import refused)"
    )


_refuse_production_import()

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
from collections import defaultdict  # noqa: E402
from collections.abc import Mapping, Sequence  # noqa: E402
from datetime import date, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import numpy as np  # noqa: E402

SEASONAL_COLUMNS = ("doy_sin", "doy_cos")
ARM_WINDOWED = "windowed"
ARM_FULL_YEAR = "full_year"
ARMS = (ARM_WINDOWED, ARM_FULL_YEAR)
WINDOW_HALF_WIDTH_DAYS = 7  # model_constants.HISTORY_WINDOW_DAYS; asserted at run time
CLIMATOLOGY_ALPHA = 0.10
MODEL_WEIGHT = 0.80
HGB_PARAMS = {"max_iter": 50, "max_leaf_nodes": 15, "learning_rate": 0.05, "random_state": 42}
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261024
HEADLINE_HOURS = (7, 8, 9, 10, 11, 12)
ROWS_RECORD = "r0_full_year_validation_row"
SUMMARY_RECORD = "r0_full_year_run_summary"
SCORE_RECORD = "r0_full_year_score"
UNION_COMPATIBILITY_FIELDS = (
    "schema_version",
    "target_year",
    "source_fields",
    "cutoff_hours_local",
    "issue_contract",
    "normalizer_version",
)


class FullYearError(ValueError):
    """The run cannot be honoured exactly; nothing is written."""


def _canonical_sha256(payload: Any) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- dates


def in_window(day: date, centre: date, half_width: int = WINDOW_HALF_WIDTH_DAYS) -> bool:
    """The trainer's target-season test: day-of-year distance in reference year 2000."""
    reference = date(2000, centre.month, centre.day)
    return abs((day.replace(year=2000) - reference).days) <= int(half_width)


def seasonal_features(day: date) -> dict[str, float]:
    angle = 2.0 * math.pi * day.timetuple().tm_yday / 365.25
    return {"doy_sin": math.sin(angle), "doy_cos": math.cos(angle)}


def dates_in_years(years: Sequence[int]) -> list[date]:
    out = []
    for year in sorted({int(y) for y in years}):
        day = date(year, 1, 1)
        while day.year == year:
            out.append(day)
            day += timedelta(days=1)
    return out


# ---------------------------------------------------------------- corpora


class SeasonCorpusUnion:
    """Several verified PIT corpora read as one by date, with no fallback.

    Unlike the trainer's year-keyed union, season corpora may share years; each
    date must be planned by exactly one corpus. Every manifest is verified and
    preflighted and must agree on ``UNION_COMPATIBILITY_FIELDS``.
    """

    def __init__(
        self,
        manifest_paths: Sequence[str | Path],
        market_id: str,
        *,
        target_year: int,
        required_cutoff_hours: Sequence[int],
        reader_factory=None,
        preflight=None,
        verify=None,
    ):
        if reader_factory is None or preflight is None or verify is None:
            from weather.calibration.forecast_training_contract import (
                preflight_pit_forecast_training_corpus,
            )
            from weather.sources.forecast_training_corpus import (
                PITForecastTrainingCorpus,
                verify_corpus_manifest,
            )

            reader_factory = reader_factory or PITForecastTrainingCorpus
            preflight = preflight or preflight_pit_forecast_training_corpus
            verify = verify or verify_corpus_manifest
        paths = [Path(path) for path in manifest_paths or ()]
        if not paths:
            raise FullYearError("at least one PIT corpus manifest is required")
        self.market_id = str(market_id)
        self.cutoff_hours = tuple(int(hour) for hour in required_cutoff_hours)
        self._by_date: dict[str, Any] = {}
        self.corpora: list[dict[str, Any]] = []
        reference = None
        seen: set[str] = set()
        for path in paths:
            manifest = verify(path)
            corpus_id = str(manifest["corpus_id"])
            if corpus_id in seen:
                raise FullYearError(f"PIT corpus given twice: {corpus_id}")
            seen.add(corpus_id)
            if self.market_id not in manifest.get("market_ids", []):
                raise FullYearError(f"market {self.market_id} is absent from PIT corpus {corpus_id}")
            compatibility = {field: manifest.get(field) for field in UNION_COMPATIBILITY_FIELDS}
            if reference is None:
                reference = compatibility
            elif compatibility != reference:
                differing = sorted(f for f in UNION_COMPATIBILITY_FIELDS if compatibility[f] != reference[f])
                raise FullYearError(f"PIT corpus {corpus_id} is incompatible with the first: {differing}")
            receipt = preflight(
                path,
                target_year=int(target_year),
                required_market_ids=sorted(manifest["market_ids"]),
                required_cutoff_hours=sorted(self.cutoff_hours),
            )
            planned = self._planned_dates(path)
            reader = reader_factory(path, self.market_id)
            overlap = sorted(set(planned) & set(self._by_date))
            if overlap:
                raise FullYearError(
                    f"PIT corpora overlap on {len(overlap)} dates (first {overlap[0]}) for {self.market_id}"
                )
            for day in planned:
                self._by_date[day] = reader
            self.corpora.append({
                "corpus_id": corpus_id,
                "manifest_sha256": manifest["manifest_sha256"],
                "preflight_sha256": (receipt or {}).get("preflight_sha256"),
                "years": sorted(int(year) for year in manifest["years"]),
                "planned_dates": len(planned),
                "first_date": min(planned) if planned else None,
                "last_date": max(planned) if planned else None,
            })

    @staticmethod
    def _planned_dates(manifest_path: Path) -> list[str]:
        plan_path = Path(manifest_path).parent / "plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        dates = []
        for values in (plan.get("expected_dates_by_year") or {}).values():
            dates.extend(str(value) for value in values)
        if not dates:
            raise FullYearError(f"corpus plan lists no dates: {plan_path}")
        return sorted(set(dates))

    def resolve(self, target_date, cutoff_hour):
        from weather.sources.forecast_training_corpus import CorpusVerificationError

        key = str(target_date)[:10]
        reader = self._by_date.get(key)
        if reader is None:
            raise CorpusVerificationError(
                f"no PIT corpus covers {self.market_id} {key}; ambient fallback is not allowed"
            )
        return reader.resolve(key, cutoff_hour)

    def covers(self, target_date) -> bool:
        """True when every cutoff hour resolves for this date."""
        key = str(target_date)[:10]
        reader = self._by_date.get(key)
        if reader is None:
            return False
        for hour in self.cutoff_hours:
            try:
                reader.resolve(key, hour)
            except Exception:  # CorpusVerificationError or a malformed row
                return False
        return True

    def record(self) -> dict[str, Any]:
        corpora = sorted(self.corpora, key=lambda row: (row["first_date"] or "", row["corpus_id"]))
        return {
            "market_id": self.market_id,
            "corpora": corpora,
            "union_sha256": _canonical_sha256([[r["corpus_id"], r["manifest_sha256"]] for r in corpora]),
        }


# ---------------------------------------------------------------- scoring core


def make_hgb(min_samples_leaf: int):
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(min_samples_leaf=int(min_samples_leaf), **HGB_PARAMS)


SERVED_FLOOR_MULTIPLIER = 1e-6  # model_distribution.distribution_hard_floor_stage


def observed_floor(high_so_far):
    """round_half_up of the observed high so far; None when it is missing."""
    from weather.units import round_half_up

    if high_so_far is None or (isinstance(high_so_far, float) and math.isnan(high_so_far)):
        return None
    return round_half_up(high_so_far)


def hard_floor(probs: Mapping[int, float], floor, multiplier: float = SERVED_FLOOR_MULTIPLIER) -> dict[int, float]:
    """Mass below ``floor`` times ``multiplier``, renormalised; all mass on ``floor`` if none remains."""
    if floor is None:
        return dict(probs)
    out = {int(b): float(p) * (multiplier if int(b) < int(floor) else 1.0) for b, p in probs.items()}
    total = sum(out.values())
    if total <= 1e-300:
        out = {b: 0.0 for b in out}
        out[int(floor)] = 1.0
        return out
    return {b: v / total for b, v in out.items()}


def seasonal_allowlist_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """The r0 plan plus the seasonal pair, inserted right after the numeric columns."""
    numeric = list(plan["numeric_feature_names"])
    clash = [c for c in SEASONAL_COLUMNS if c in plan["feature_names"]]
    if clash:
        raise FullYearError(f"seasonal columns already in the allowlist: {clash}")
    rest = [c for c in plan["feature_names"] if c not in numeric]
    out = dict(plan)
    out["numeric_feature_names"] = numeric + list(SEASONAL_COLUMNS)
    out["feature_names"] = numeric + list(SEASONAL_COLUMNS) + rest
    return out


def score_hour(
    records: Sequence[Mapping[str, Any]],
    *,
    arm: str,
    leaf: int,
    centre: date,
    bucket_space: Sequence[int],
    frame_builder,
    plan: Mapping[str, Any],
    fm,
) -> list[dict[str, Any]]:
    """Per-row blocked LOYO losses for one cutoff hour and one arm.

    ``records`` are the hour's full-year records (window rows included). The
    windowed arm keeps only window rows; the full-year arm trains on all rows of
    the other years. Validation rows are the held-out year's window rows.
    """
    if arm not in ARMS:
        raise FullYearError(f"unknown arm {arm!r}")
    if arm == ARM_WINDOWED:
        rows = [r for r in records if in_window(r["target_date"], centre)]
        arm_plan = plan
    else:
        rows = [dict(r, **seasonal_features(r["target_date"])) for r in records]
        arm_plan = seasonal_allowlist_plan(plan)
    if not rows:
        return []
    df, feature_cols = frame_builder(rows, arm_plan)
    n_numeric = len(arm_plan["numeric_feature_names"])
    X = df[feature_cols].copy()
    y = df["final_bucket"].copy()
    window = [in_window(r["target_date"], centre) for r in rows]
    blocked = fm.feature_blocked_validation_plan(rows)
    by_train: dict[tuple[int, ...], list[int]] = defaultdict(list)
    for val_idx, train in sorted(blocked["train_indices_by_validation_index"].items()):
        if window[val_idx]:
            by_train[tuple(train)].append(int(val_idx))
    out = []
    for train, val_list in sorted(by_train.items(), key=lambda item: item[1][0]):
        train = list(train)
        if not train or len(set(y.iloc[train])) < 2:
            continue
        window_train = [i for i in train if window[i]]
        p_clim = fm.smoothed_dist([rows[i]["final_bucket"] for i in window_train], bucket_space, alpha=CLIMATOLOGY_ALPHA)
        fold = fm.fold_local_feature_matrices(X, train, val_list, feature_cols, n_numeric)
        hgb = make_hgb(leaf)
        hgb.fit(fold["hgb_train"], y.iloc[train])
        classes = [int(c) for c in hgb.classes_]
        train_probs = hgb.predict_proba(fold["hgb_train"])
        in_sample = float(np.mean([
            fm.log_loss(fm.blend(p_clim.copy(), dict(zip(classes, map(float, p))), MODEL_WEIGHT), int(a))
            for p, a in zip(train_probs, y.iloc[train])
        ]))
        probs = hgb.predict_proba(fold["hgb_validation"])
        for offset, val_idx in enumerate(val_list):
            dist = {c: float(p) for c, p in zip(classes, probs[offset])}
            blended = fm.blend(p_clim.copy(), dist, MODEL_WEIGHT)
            actual = int(y.iloc[val_idx])
            vdate = rows[val_idx]["target_date"]
            floor = observed_floor(rows[val_idx].get("high_so_far"))
            floored = hard_floor(blended, floor)
            floored0 = hard_floor(blended, floor, 0.0)
            out.append({
                "record": ROWS_RECORD,
                "arm": arm,
                "leaf": int(leaf),
                "validation_date": str(vdate),
                "validation_year": int(str(vdate)[:4]),
                "hgb_log_loss": float(fm.log_loss(blended, actual)),
                "hgb_brier": float(fm.brier_score(blended, actual)),
                "floor": floor,
                "hgb_floor_log_loss": float(fm.log_loss(floored, actual)),
                "hgb_floor_brier": float(fm.brier_score(floored, actual)),
                "hgb_floor0_log_loss": float(fm.log_loss(floored0, actual)),
                "n_train": len(train),
                "n_train_window": len(window_train),
                "n_classes": len(classes),
                "train_in_sample_log_loss": in_sample,
            })
    return out


# ---------------------------------------------------------------- run


def _guard_output_root(output_root: Path) -> Path:
    from weather.paths import ARTIFACTS_ROOT, DATA_ROOT

    root = Path(output_root).resolve()
    for protected in (DATA_ROOT.resolve(), ARTIFACTS_ROOT.resolve()):
        if root == protected or protected in root.parents:
            raise FullYearError(f"--output-root may not be inside {protected}")
    return root


def run_market(
    market_id: str,
    *,
    centre: date,
    manifests: Sequence[str | Path],
    training_years: Sequence[int],
    leaves: Sequence[int],
    arms: Sequence[str],
    output_root: Path,
) -> dict[str, Any]:
    from weather.calibration import feature_model as fm
    from weather.calibration.feature_model_training_inputs import require_market_history
    from weather.calibration.r0_scope import require_r0_market
    from weather.model.model_constants import HISTORY_WINDOW_DAYS
    from weather.model.toronto_model import INTRADAY_CUTOFF_HOURS, TorontoHighTempModel

    if HISTORY_WINDOW_DAYS != WINDOW_HALF_WIDTH_DAYS:
        raise FullYearError(f"trainer window is {HISTORY_WINDOW_DAYS} days, this module assumes {WINDOW_HALF_WIDTH_DAYS}")
    require_r0_market(market_id)
    root = _guard_output_root(output_root)
    years = sorted({int(y) for y in training_years})
    if not years or max(years) >= centre.year:
        raise FullYearError(f"training years must be earlier than the centre year: {years}")
    model = TorontoHighTempModel(market_id=market_id, target_date=centre)
    spec = model.spec
    require_market_history(spec)
    plan = fm.resolve_column_allowlist(
        f"r0:{market_id}", market_spec=spec,
        known_wind_groups=fm.WIND_GROUPS, known_cloud_groups=fm.CLOUD_GROUPS,
    )
    union = SeasonCorpusUnion(manifests, spec.id, target_year=centre.year, required_cutoff_hours=INTRADAY_CUTOFF_HOURS)
    window_cache = model.historical_target_cache()
    bucket_space = list(window_cache["bucket_space"])
    full_cache = model.historical_target_cache(coverage_target_dates=dates_in_years(years))
    labelled = {d: row for d, row in full_cache["daily"].items() if d.year in years}
    covered = {d: row for d, row in labelled.items() if union.covers(d)}
    window_days = sorted(d for d in window_cache["daily"] if d.year in years)
    missing_window = [d for d in window_days if d not in covered]
    if missing_window:
        raise FullYearError(f"window days without PIT coverage: {[str(d) for d in missing_window[:5]]}")
    raw = fm.build_feature_records_for_model(
        model, covered, full_cache["by_date"], None, None,
        marine_water_contrast_index={}, reanalysis_synoptic_index={}, forecast_resolver=union,
    )

    def frame_builder(rows, arm_plan):
        return fm.feature_model_frame(rows, fm.WIND_GROUPS, fm.CLOUD_GROUPS, market_spec=spec, column_allowlist=arm_plan)

    out_dir = root / market_id
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_path = out_dir / f"r0_full_year_rows_{market_id}.jsonl"
    tmp = rows_path.with_suffix(".jsonl.tmp")
    count = 0
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        for hour in INTRADAY_CUTOFF_HOURS:
            records = raw.get(hour) or []
            for arm in arms:
                for leaf in leaves:
                    for row in score_hour(records, arm=arm, leaf=leaf, centre=centre, bucket_space=bucket_space,
                                          frame_builder=frame_builder, plan=plan, fm=fm):
                        row.update({"market": market_id, "hour": int(hour)})
                        handle.write(json.dumps(row, sort_keys=True) + "\n")
                        count += 1
            print(f"{market_id} hour {hour:02d}: {len(records)} records", flush=True)
    tmp.replace(rows_path)
    by_year = defaultdict(int)
    for d in covered:
        by_year[str(d.year)] += 1
    summary = {
        "record": SUMMARY_RECORD,
        "market": market_id,
        "centre_date": centre.isoformat(),
        "training_years": years,
        "leaves": [int(x) for x in leaves],
        "arms": list(arms),
        "labelled_days": len(labelled),
        "covered_days": len(covered),
        "covered_days_by_year": dict(sorted(by_year.items())),
        "window_days": len(window_days),
        "bucket_space": bucket_space,
        "allowlist_sha256": plan.get("sha256"),
        "feature_names": list(plan["feature_names"]),
        "seasonal_columns": list(SEASONAL_COLUMNS),
        "hgb_params": dict(HGB_PARAMS),
        "pit_forecast_corpus": union.record(),
        "rows": count,
        "rows_file": rows_path.name,
    }
    (out_dir / f"r0_full_year_summary_{market_id}.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


# ---------------------------------------------------------------- score


def load_rows(paths: Sequence[Path]) -> list[dict[str, Any]]:
    rows = []
    for path in paths:
        with Path(path).open("r", encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())
    return rows


def paired_deltas(rows, baseline: tuple[str, int], candidate: tuple[str, int]):
    """{(market, hour, date): candidate - baseline}; also the unpaired count."""
    def index(arm, leaf):
        return {(r["market"], int(r["hour"]), r["validation_date"]): float(r["hgb_log_loss"])
                for r in rows if r["arm"] == arm and int(r["leaf"]) == int(leaf)}

    base, cand = index(*baseline), index(*candidate)
    keys = sorted(set(base) & set(cand))
    unpaired = len(set(base) ^ set(cand))
    return {k: cand[k] - base[k] for k in keys}, unpaired


def market_mean_delta(deltas: Mapping[tuple, float], hours: Sequence[int], weights=None):
    """Equal-weight mean over markets of each market's mean delta over its rows at ``hours``.

    ``weights`` maps a validation date to its bootstrap multiplicity.
    """
    hours = {int(h) for h in hours}
    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, float] = defaultdict(float)
    for (market, hour, day), value in deltas.items():
        if hour not in hours:
            continue
        w = 1.0 if weights is None else weights.get(day, 0.0)
        if w:
            sums[market] += w * value
            counts[market] += w
    means = [sums[m] / counts[m] for m in sums if counts[m] > 0]
    return float(np.mean(means)) if means else float("nan")


def bootstrap_weights(dates: Sequence[str], *, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED) -> np.ndarray:
    """(draws, len(dates)) multiplicities; each draw resamples the dates with replacement."""
    rng = np.random.default_rng(seed)
    n = len(dates)
    picks = rng.integers(0, n, size=(int(draws), n))
    return np.stack([np.bincount(row, minlength=n) for row in picks]).astype(float)


def bootstrap_ci(deltas, hours, *, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED):
    """Percentile 95% CI by resampling validation dates (all markets and hours together).

    Vectorised form of ``market_mean_delta`` under each draw's date weights.
    """
    dates = sorted({k[2] for k in deltas})
    position = {d: i for i, d in enumerate(dates)}
    weights = bootstrap_weights(dates, draws=draws, seed=seed)
    hours = {int(h) for h in hours}
    by_market: dict[str, tuple[list[int], list[float]]] = defaultdict(lambda: ([], []))
    for (market, hour, day), value in deltas.items():
        if hour in hours:
            by_market[market][0].append(position[day])
            by_market[market][1].append(value)
    if not by_market:
        return float("nan"), float("nan")
    per_market = []
    for idx, values in by_market.values():
        w = weights[:, idx]
        total = w.sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            per_market.append((w @ np.asarray(values)) / total)
    stats = np.nanmean(np.vstack(per_market), axis=0)
    stats = stats[~np.isnan(stats)]
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


def evaluate_arm(deltas, hours_all: Sequence[int]) -> dict[str, Any]:
    per_hour = {}
    for hour in hours_all:
        mean = market_mean_delta(deltas, [hour])
        lo, hi = bootstrap_ci(deltas, [hour])
        per_hour[int(hour)] = {"delta": mean, "ci": [lo, hi], "win": bool(mean < 0 and hi < 0), "worse": bool(lo > 0)}
    mean = market_mean_delta(deltas, HEADLINE_HOURS)
    lo, hi = bootstrap_ci(deltas, HEADLINE_HOURS)
    headline = {"delta": mean, "ci": [lo, hi], "win": bool(mean < 0 and hi < 0)}
    adoptable = headline["win"] and not any(v["worse"] for v in per_hour.values())
    return {"headline_07_12": headline, "per_hour": per_hour, "adoptable": bool(adoptable)}


def per_market_table(deltas, markets, hours_all):
    table = {}
    for market in markets:
        sub = {k: v for k, v in deltas.items() if k[0] == market}
        if not sub:
            continue
        row = {}
        for label, hours in [("07-12", HEADLINE_HOURS)] + [(f"{h:02d}", [h]) for h in hours_all]:
            mean = market_mean_delta(sub, hours)
            lo, hi = bootstrap_ci(sub, hours)
            row[label] = {"delta": mean, "ci": [lo, hi]}
        table[market] = row
    return table


def pick(arms_result: Mapping[str, Mapping[str, Any]]) -> str | None:
    """Lowest 07-12 headline among the adoptable arms; exact tie -> larger leaf."""
    adoptable = [(v["headline_07_12"]["delta"], -int(k.split(":")[1]), k) for k, v in arms_result.items() if v["adoptable"]]
    return min(adoptable)[2] if adoptable else None


def reproduction_check(rows, reference_rows, market: str, arm=ARM_WINDOWED, leaf=20) -> dict[str, Any]:
    ours = {(int(r["hour"]), r["validation_date"]): float(r["hgb_log_loss"])
            for r in rows if r["market"] == market and r["arm"] == arm and int(r["leaf"]) == leaf}
    ref = {(int(r["hour"]), r["validation_date"]): float(r["hgb_log_loss"]) for r in reference_rows}
    keys = set(ours) & set(ref)
    max_diff = max((abs(ours[k] - ref[k]) for k in keys), default=float("nan"))
    return {"market": market, "paired": len(keys), "ours_only": len(set(ours) - set(ref)),
            "reference_only": len(set(ref) - set(ours)), "max_abs_diff": max_diff,
            "pass": bool(keys and not (set(ours) ^ set(ref)) and max_diff <= 1e-9)}


def score(rows_root: Path, markets: Sequence[str], *, reference_root: Path | None = None,
          candidates=((ARM_FULL_YEAR, 20), (ARM_FULL_YEAR, 10), (ARM_FULL_YEAR, 5)),
          descriptive=((ARM_WINDOWED, 10), (ARM_WINDOWED, 5)), baseline=(ARM_WINDOWED, 20)) -> dict[str, Any]:
    from weather.model.toronto_model import INTRADAY_CUTOFF_HOURS

    hours_all = [int(h) for h in INTRADAY_CUTOFF_HOURS]
    paths = [Path(rows_root) / m / f"r0_full_year_rows_{m}.jsonl" for m in markets]
    rows = load_rows([p for p in paths if p.exists()])
    present = sorted({r["market"] for r in rows})
    result: dict[str, Any] = {"record": SCORE_RECORD, "markets": present, "baseline": f"{baseline[0]}:{baseline[1]}",
                              "draws": BOOTSTRAP_DRAWS, "seed": BOOTSTRAP_SEED, "arms": {}, "descriptive": {},
                              "per_market": {}, "reproduction": [], "in_sample": {}}
    if reference_root is not None:
        for market in present:
            ref_path = Path(reference_root) / market / f"feature_model_blocked_validation_rows_{market}.jsonl"
            if ref_path.exists():
                result["reproduction"].append(reproduction_check(rows, load_rows([ref_path]), market))
    for group, arms in (("arms", candidates), ("descriptive", descriptive)):
        for arm in arms:
            deltas, unpaired = paired_deltas(rows, baseline, arm)
            if not deltas:
                continue
            key = f"{arm[0]}:{arm[1]}"
            verdict = evaluate_arm(deltas, hours_all)
            verdict["paired_rows"] = len(deltas)
            verdict["unpaired_rows"] = unpaired
            result[group][key] = verdict
            result["per_market"][key] = per_market_table(deltas, present, hours_all)
    for arm in (baseline, *candidates, *descriptive):
        sub = [r for r in rows if r["arm"] == arm[0] and int(r["leaf"]) == arm[1]]
        if sub:
            result["in_sample"][f"{arm[0]}:{arm[1]}"] = {
                "validation_mean": float(np.mean([r["hgb_log_loss"] for r in sub])),
                "train_in_sample_mean": float(np.mean([r["train_in_sample_log_loss"] for r in sub])),
                "mean_n_train": float(np.mean([r["n_train"] for r in sub])),
            }
    result["pick"] = pick(result["arms"])
    result["reproduction_pass"] = bool(result["reproduction"]) and all(r["pass"] for r in result["reproduction"])
    return result


# ---------------------------------------------------------------- fair comparators (lane L3 rows)

L3_COMPARATORS = {
    "e_r0_baseline_floor": "r0_baseline_floor_log_loss",
    "f_bias_corrected_forecast_floor": "bias_corrected_forecast_floor_log_loss",
    "ols_floor": "ols_floor_log_loss",
}
DECISIVE_COMPARATORS = ("f_bias_corrected_forecast_floor", "ols_floor")
PRIMARY_MARKETS = ("atlanta", "austin", "chicago", "dallas", "denver")


def l3_parity(ours, l3_rows, market: str) -> dict[str, Any]:
    """Row sets must match one to one and L3's r0_repro must equal our windowed leaf-20 loss."""
    mine = {(int(r["hour"]), r["validation_date"]): float(r["hgb_log_loss"])
            for r in ours if r["market"] == market and r["arm"] == ARM_WINDOWED and int(r["leaf"]) == 20}
    theirs = {(int(r["hour"]), r["validation_date"]): float(r["r0_repro_log_loss"])
              for r in l3_rows if r["market_id"] == market}
    keys = set(mine) & set(theirs)
    max_diff = max((abs(mine[k] - theirs[k]) for k in keys), default=float("nan"))
    return {"market": market, "paired": len(keys), "ours_only": len(set(mine) - set(theirs)),
            "l3_only": len(set(theirs) - set(mine)), "max_abs_diff": max_diff,
            "pass": bool(keys and not (set(mine) ^ set(theirs)) and max_diff <= 1e-9)}


def compare_fair(rows_root: Path, l3_root: Path, markets: Sequence[str] = PRIMARY_MARKETS) -> dict[str, Any]:
    """Full-year leaf 20 + served floor (FYF) against the fair comparators on identical rows."""
    hours_all = list(range(7, 21))
    result: dict[str, Any] = {"record": SCORE_RECORD + "_fair", "draws": BOOTSTRAP_DRAWS, "seed": BOOTSTRAP_SEED,
                              "parity": [], "markets_scored": [], "comparisons": {}, "per_market": {},
                              "mean_loss_07_12": {}}
    losses: dict[str, dict[tuple, float]] = defaultdict(dict)
    for market in markets:
        path = Path(rows_root) / market / f"r0_full_year_rows_{market}.jsonl"
        l3_path = Path(l3_root) / f"challenger_rows_{market}.jsonl"
        if not path.exists() or not l3_path.exists():
            result["parity"].append({"market": market, "pass": False, "missing": True})
            continue
        ours, l3 = load_rows([path]), load_rows([l3_path])
        fy = [r for r in ours if r["arm"] == ARM_FULL_YEAR and int(r["leaf"]) == 20 and "hgb_floor_log_loss" in r]
        gate = l3_parity(ours, l3, market)
        gate["full_year_floor_rows"] = len(fy)
        if not fy:
            gate["pass"] = False
        result["parity"].append(gate)
        if not gate["pass"]:
            continue
        result["markets_scored"].append(market)
        for r in fy:
            k = (market, int(r["hour"]), r["validation_date"])
            losses["FYF"][k] = float(r["hgb_floor_log_loss"])
            losses["FYF0"][k] = float(r["hgb_floor0_log_loss"])
            losses["FY_raw"][k] = float(r["hgb_log_loss"])
        for r in ours:
            if r["arm"] == ARM_WINDOWED and int(r["leaf"]) == 20:
                losses["R0_raw"][(market, int(r["hour"]), r["validation_date"])] = float(r["hgb_log_loss"])
        for r in l3:
            k = (market, int(r["hour"]), r["validation_date"])
            for name, column in L3_COMPARATORS.items():
                losses[name][k] = float(r[column])
    for target in list(L3_COMPARATORS) + ["R0_raw", "FY_raw"]:
        keys = sorted(set(losses["FYF"]) & set(losses[target]))
        deltas = {k: losses["FYF"][k] - losses[target][k] for k in keys}
        if not deltas:
            continue
        verdict = evaluate_arm(deltas, hours_all)
        verdict["beats"] = verdict.pop("adoptable")
        verdict["paired_rows"] = len(deltas)
        result["comparisons"][f"FYF_vs_{target}"] = verdict
        result["per_market"][f"FYF_vs_{target}"] = per_market_table(deltas, result["markets_scored"], hours_all)
    for arm, table in losses.items():
        per = defaultdict(list)
        for (market, hour, _), value in table.items():
            if hour in HEADLINE_HOURS:
                per[market].append(value)
        result["mean_loss_07_12"][arm] = {m: float(np.mean(v)) for m, v in sorted(per.items())}
    complete = sorted(result["markets_scored"]) == sorted(markets)
    beats = {t: result["comparisons"].get(f"FYF_vs_{t}", {}).get("beats", False) for t in DECISIVE_COMPARATORS}
    result["status"] = "FINAL" if complete else "PROVISIONAL"
    result["beats_decisive"] = beats
    result["adopt_full_year"] = bool(complete and all(beats.values()))
    return result


# ---------------------------------------------------------------- CLI


def _int_list(value: str) -> list[int]:
    return [int(x) for x in str(value).split(",") if x.strip()]


def parse_years(value: str) -> list[int]:
    years: set[int] = set()
    for token in str(value).split(","):
        token = token.strip()
        if "-" in token:
            a, b = (int(x) for x in token.split("-", 1))
            if b < a:
                raise FullYearError(f"reversed year range {token!r}")
            years.update(range(a, b + 1))
        elif token:
            years.add(int(token))
    return sorted(years)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Research-only R0 full-year vs windowed blocked validation.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Fit and score one market (heavy; use the workstation wrapper).")
    run.add_argument("--market", required=True)
    run.add_argument("--centre-date", required=True)
    run.add_argument("--pit-forecast-corpus-manifest", action="append", required=True, dest="manifests")
    run.add_argument("--training-years", default="2021-2025")
    run.add_argument("--leaves", default="20,10,5")
    run.add_argument("--arms", default=",".join(ARMS))
    run.add_argument("--output-root", required=True)
    sc = sub.add_parser("score", help="Apply the pre-declared rule to written rows (light).")
    sc.add_argument("--rows-root", required=True)
    sc.add_argument("--markets", required=True)
    sc.add_argument("--reference-root", default=None)
    sc.add_argument("--out", required=True)
    fc = sub.add_parser("compare-fair", help="FYF vs lane L3's floored comparators on identical rows (light).")
    fc.add_argument("--rows-root", required=True)
    fc.add_argument("--l3-root", required=True)
    fc.add_argument("--markets", default=",".join(PRIMARY_MARKETS))
    fc.add_argument("--out", required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        arms = [a.strip() for a in args.arms.split(",") if a.strip()]
        unknown = sorted(set(arms) - set(ARMS))
        if unknown:
            raise FullYearError(f"unknown arms {unknown}")
        summary = run_market(
            args.market, centre=date.fromisoformat(args.centre_date), manifests=args.manifests,
            training_years=parse_years(args.training_years), leaves=_int_list(args.leaves), arms=arms,
            output_root=Path(args.output_root),
        )
        print(json.dumps({k: summary[k] for k in ("market", "covered_days", "covered_days_by_year", "rows")}, sort_keys=True))
        return 0
    if args.command == "compare-fair":
        result = compare_fair(Path(args.rows_root), Path(args.l3_root),
                              [m.strip() for m in args.markets.split(",") if m.strip()])
        out = _guard_output_root(Path(args.out).parent) / Path(args.out).name
        out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": result["status"], "adopt_full_year": result["adopt_full_year"],
                          "beats_decisive": result["beats_decisive"],
                          "headline": {k: v["headline_07_12"] for k, v in result["comparisons"].items()}},
                         sort_keys=True))
        return 0
    result = score(Path(args.rows_root), [m.strip() for m in args.markets.split(",") if m.strip()],
                   reference_root=Path(args.reference_root) if args.reference_root else None)
    out = _guard_output_root(Path(args.out).parent) / Path(args.out).name
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"pick": result["pick"], "reproduction_pass": result["reproduction_pass"],
                      "headline": {k: v["headline_07_12"] for k, v in result["arms"].items()}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
