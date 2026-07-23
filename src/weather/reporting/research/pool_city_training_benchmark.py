"""Leakage-safe pooled, per-city, and leave-one-city-out density benchmark.

This research harness deliberately reuses the canonical continuous-density
trainer and feature frame.  It changes only the geographic fit scope:

* ``pooled`` fits all markets with the normal city/context features;
* ``per_city`` fits one model for the market being scored; and
* ``loco`` fits every market except the market being scored.

Temperature-like inputs and targets are converted by the canonical density
adapter to Fahrenheit inside the model, then projected back onto native C/F
market bands for scoring.  The development year may select density width and
shape; the later confirmation year is never used by fitting or selection.

The CLI is research-only and defaults to ``plan`` mode.  Full execution
requires ``--mode run --confirm-research-only``.  All writes are constrained to
an explicit repository ``scratch`` directory, while the mirrored data root is
opened through a read-only tracing guard.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import platform
import random
import subprocess
import sys
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import sklearn

from weather.io import (
    write_csv_rows_atomic as _write_csv_rows_atomic,
    write_json_atomic as _write_json_file_atomic,
    write_text_atomic,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("pool_city_training_benchmark")
DEFAULT_HOURS = tuple(range(7, 21))
DEFAULT_PANEL_START_YEAR = 2015
DEFAULT_DEVELOPMENT_YEAR = 2024
DEFAULT_CONFIRMATION_YEAR = 2025
DEFAULT_BOOTSTRAP_REPLICATES = 10_000
DEFAULT_BOOTSTRAP_SEED = 20_260_722
DEFAULT_MAX_RUNTIME_HOURS = 12.0
DEFAULT_MEMORY_BUDGET_BYTES = 4 * 1024**3
REGIMES = ("pooled", "per_city", "loco")
SPLITS = ("development", "confirmation")
NON_CONTRACTUAL_CORPUS_FIELDS = frozenset({"non_contractual_runtime"})


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_json_value(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True)) if isinstance(value, (set, frozenset)) else items
    return str(value)


def canonical_json(payload: Any) -> str:
    return json.dumps(
        _json_value(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def payload_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def corpus_contract_sha256(corpus: Mapping[str, Any]) -> str:
    """Hash reproducible corpus identity while retaining diagnostic timings."""

    return payload_sha256({
        key: value
        for key, value in corpus.items()
        if key not in NON_CONTRACTUAL_CORPUS_FIELDS
        and key != "corpus_contract_sha256"
    })


def file_sha256(path: str | Path, chunk_bytes: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(int(chunk_bytes)):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: str | Path, payload: Any) -> Path:
    return _write_json_file_atomic(
        path,
        _json_value(payload),
        trailing_newline=True,
    )


def write_csv_atomic(path: str | Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    fields = sorted({str(key) for row in rows for key in row})
    normalized = (
        {key: _json_value(row.get(key)) for key in fields}
        for row in rows
    )
    return _write_csv_rows_atomic(path, fields, normalized)


@dataclass
class ReadTrace:
    opened: set[Path]
    checked: set[Path]


@contextmanager
def read_only_path_trace(data_root: str | Path):
    """Trace data-root reads and reject any attempted mirror write."""

    data_root = Path(data_root).resolve()
    original_open = Path.open
    original_exists = Path.exists
    trace = ReadTrace(opened=set(), checked=set())

    def relevant(path: Path) -> bool:
        try:
            resolved = path.resolve(strict=False)
        except OSError:
            return False
        return _is_relative_to(resolved, data_root)

    def traced_open(self: Path, mode="r", *args, **kwargs):
        path = Path(self)
        if relevant(path):
            resolved = path.resolve(strict=False)
            trace.checked.add(resolved)
            if any(flag in str(mode) for flag in ("w", "a", "x", "+")):
                raise PermissionError(f"research input mirror is read-only: {resolved}")
            trace.opened.add(resolved)
        return original_open(self, mode, *args, **kwargs)

    def traced_exists(self: Path):
        path = Path(self)
        if relevant(path):
            trace.checked.add(path.resolve(strict=False))
        return original_exists(self)

    Path.open = traced_open
    Path.exists = traced_exists
    try:
        yield trace
    finally:
        Path.open = original_open
        Path.exists = original_exists


def configure_data_root(data_root: str | Path) -> Path:
    """Point repository-owned data helpers at one explicit read-only mirror."""

    import weather.paths as weather_paths

    resolved = Path(data_root).resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"data root not found: {resolved}")
    weather_paths.DATA_ROOT = resolved

    # Some source modules bind path constants at import time.  A fresh CLI
    # process imports them after this function.  Refuse an ambiguous embedded
    # call instead of silently mixing roots.
    stale_modules = []
    for module_name in (
        "weather.sources.wu_history",
        "weather.sources.forecast_history",
        "weather.sources.reanalysis_history",
        "weather.reporting.source_gates.source_redundancy",
    ):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        candidates = []
        for attribute in ("DEFAULT_DATA_ROOT", "DATA_ROOT", "DEFAULT_ROOT"):
            value = getattr(module, attribute, None)
            if isinstance(value, Path):
                candidates.append(value.resolve(strict=False))
        if candidates and not all(_is_relative_to(path, resolved) for path in candidates):
            stale_modules.append(module_name)
    if stale_modules:
        raise RuntimeError(
            "data root must be configured before importing data-bound source modules: "
            + ", ".join(stale_modules)
        )
    return resolved


def _dependencies() -> dict[str, Any]:
    """Load canonical model dependencies only after the data root is bound."""

    from weather.calibration.pooled_feature_model import (
        DENSITY_DEFAULT_SHAPE,
        DENSITY_SHAPE_TUNING_CANDIDATES,
        build_family_dataset,
        canonical_density_records,
        density_shape_config,
        density_shape_id,
        density_sigma_candidates,
        density_synthetic_market_band_rows,
        density_support_f,
        density_weight_matrix,
        feature_frame,
        predict_density_means,
        residual_sigma_f,
        train_density_hour_model,
    )
    from weather.market.market_registry import all_specs
    from weather.model.continuous_density import (
        bucket_interval_native,
        canonical_grid_f,
        native_interval_to_f,
    )
    from weather.model.feature_store import FEATURE_SCHEMA_VERSION
    from weather.model.variant_prediction_runtime import native_value_to_f, record_unit

    return {
        "DENSITY_DEFAULT_SHAPE": DENSITY_DEFAULT_SHAPE,
        "DENSITY_SHAPE_TUNING_CANDIDATES": DENSITY_SHAPE_TUNING_CANDIDATES,
        "FEATURE_SCHEMA_VERSION": FEATURE_SCHEMA_VERSION,
        "all_specs": all_specs,
        "bucket_interval_native": bucket_interval_native,
        "build_family_dataset": build_family_dataset,
        "canonical_density_records": canonical_density_records,
        "canonical_grid_f": canonical_grid_f,
        "density_shape_config": density_shape_config,
        "density_shape_id": density_shape_id,
        "density_sigma_candidates": density_sigma_candidates,
        "density_synthetic_market_band_rows": density_synthetic_market_band_rows,
        "density_support_f": density_support_f,
        "density_weight_matrix": density_weight_matrix,
        "feature_frame": feature_frame,
        "native_interval_to_f": native_interval_to_f,
        "native_value_to_f": native_value_to_f,
        "predict_density_means": predict_density_means,
        "record_unit": record_unit,
        "residual_sigma_f": residual_sigma_f,
        "train_density_hour_model": train_density_hour_model,
    }


def record_date(row: Mapping[str, Any]) -> str:
    value = row.get("target_date", row.get("date"))
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value)[:10]).isoformat()


def record_key(row: Mapping[str, Any]) -> tuple[str, str, int]:
    return str(row.get("market_id")), record_date(row), int(row.get("cutoff_hour"))


def corpus_hash(rows: Iterable[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in sorted(rows, key=record_key):
        digest.update(canonical_json(row).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def complete_panel_dates(
    rows: Sequence[Mapping[str, Any]],
    *,
    markets: Sequence[str],
    hours: Sequence[int],
    start_year: int,
    end_year: int,
) -> list[str]:
    """Return dates with exactly one row for every market/hour cell."""

    required = {(str(market), int(hour)) for market in markets for hour in hours}
    cells: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for row in rows:
        target_date = record_date(row)
        year = int(target_date[:4])
        if int(start_year) <= year <= int(end_year):
            cells[target_date].append((str(row.get("market_id")), int(row.get("cutoff_hour"))))
    output = []
    for target_date, observed in sorted(cells.items()):
        if len(observed) == len(required) and set(observed) == required:
            output.append(target_date)
    return output


def chronological_splits(
    panel_dates: Sequence[str],
    *,
    development_year: int,
    confirmation_year: int,
) -> dict[str, list[str]]:
    dates = sorted({date.fromisoformat(str(value)).isoformat() for value in panel_dates})
    train = [value for value in dates if int(value[:4]) < int(development_year)]
    development = [value for value in dates if int(value[:4]) == int(development_year)]
    confirmation = [value for value in dates if int(value[:4]) == int(confirmation_year)]
    if not train or not development or not confirmation:
        raise ValueError("chronological panel requires nonempty train, development, and confirmation dates")
    if not (max(train) < min(development) <= max(development) < min(confirmation)):
        raise ValueError("chronological split ordering is invalid")
    return {
        "train": train,
        "development": development,
        "confirmation": confirmation,
    }


def filter_panel_rows(
    rows: Sequence[Mapping[str, Any]],
    splits: Mapping[str, Sequence[str]],
) -> dict[str, list[dict[str, Any]]]:
    date_to_split = {
        target_date: split
        for split, dates in splits.items()
        for target_date in dates
    }
    output = {split: [] for split in splits}
    for raw in rows:
        target_date = record_date(raw)
        split = date_to_split.get(target_date)
        if split is None:
            continue
        row = dict(raw)
        row["target_date"] = target_date
        output[split].append(row)
    for split in output:
        output[split].sort(key=record_key)
    return output


def build_input_manifest(
    data_root: str | Path,
    trace: ReadTrace,
) -> dict[str, Any]:
    data_root = Path(data_root).resolve()
    paths = sorted(trace.checked | trace.opened)
    rows = []
    for path in paths:
        if not _is_relative_to(path, data_root):
            continue
        relative = path.relative_to(data_root).as_posix()
        if not path.exists():
            rows.append({"path": relative, "status": "missing"})
            continue
        if not path.is_file():
            rows.append({"path": relative, "status": "non_file"})
            continue
        stat = path.stat()
        rows.append({
            "path": relative,
            "status": "read" if path in trace.opened else "checked_present",
            "size_bytes": int(stat.st_size),
            "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "sha256": file_sha256(path),
        })
    manifest = {
        "schema_version": "pool_city_input_manifest_v0.1",
        "data_root": str(data_root),
        "read_only_guard": True,
        "files": rows,
        "opened_file_count": sum(1 for row in rows if row.get("status") == "read"),
        "missing_checked_path_count": sum(1 for row in rows if row.get("status") == "missing"),
        "total_read_bytes": sum(int(row.get("size_bytes") or 0) for row in rows if row.get("status") == "read"),
    }
    manifest["manifest_sha256"] = payload_sha256(manifest)
    return manifest


def load_corpus(
    *,
    data_root: str | Path,
    hours: Sequence[int] = DEFAULT_HOURS,
    panel_start_year: int = DEFAULT_PANEL_START_YEAR,
    development_year: int = DEFAULT_DEVELOPMENT_YEAR,
    confirmation_year: int = DEFAULT_CONFIRMATION_YEAR,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], dict[str, Any]]:
    """Load one balanced market/date/hour panel with train-frozen context."""

    resolved_root = configure_data_root(data_root)
    dependencies = _dependencies()
    specs = tuple(dependencies["all_specs"]())
    markets = tuple(sorted(spec.id for spec in specs))
    units = {spec.id: spec.display_unit for spec in specs}
    context_cutoff = f"{int(development_year):04d}-01-01"
    started = time.perf_counter()
    with read_only_path_trace(resolved_root) as trace:
        raw_rows, raw_counts = dependencies["build_family_dataset"](
            unit="all",
            cutoff_hours=tuple(int(hour) for hour in hours),
            prior_as_of_exclusive=context_cutoff,
        )
    load_seconds = time.perf_counter() - started
    panel_dates = complete_panel_dates(
        raw_rows,
        markets=markets,
        hours=hours,
        start_year=panel_start_year,
        end_year=confirmation_year,
    )
    splits = chronological_splits(
        panel_dates,
        development_year=development_year,
        confirmation_year=confirmation_year,
    )
    native = filter_panel_rows(raw_rows, splits)
    canonical = {
        split: dependencies["canonical_density_records"](rows)
        for split, rows in native.items()
    }
    expected_per_date = len(markets) * len(tuple(hours))
    for split, dates in splits.items():
        expected = len(dates) * expected_per_date
        if len(native[split]) != expected or len(canonical[split]) != expected:
            raise ValueError(
                f"{split} panel lost rows during native/canonical assembly: "
                f"expected={expected}, native={len(native[split])}, canonical={len(canonical[split])}"
            )

    manifest = build_input_manifest(resolved_root, trace)
    corpus = {
        "panel_contract": "balanced_market_date_hour_panel_v1",
        "markets": list(markets),
        "units_by_market": units,
        "hours": [int(hour) for hour in hours],
        "panel_start_year": int(panel_start_year),
        "development_year": int(development_year),
        "confirmation_year": int(confirmation_year),
        "feature_context_as_of_exclusive": context_cutoff,
        "feature_context_policy": (
            "climate and static source-reliability context exclude development "
            "and confirmation years before any feature row is assembled"
        ),
        "raw_source_rows_before_panel": len(raw_rows),
        "raw_counts_before_panel": raw_counts,
        "balanced_panel_dates": len(panel_dates),
        "split_dates": splits,
        "split_rows": {split: len(rows) for split, rows in canonical.items()},
        "native_corpus_sha256": {
            split: corpus_hash(rows) for split, rows in native.items()
        },
        "canonical_corpus_sha256": {
            split: corpus_hash(rows) for split, rows in canonical.items()
        },
        "input_manifest_sha256": manifest["manifest_sha256"],
        "corpus_contract_excludes": sorted(NON_CONTRACTUAL_CORPUS_FIELDS),
        "non_contractual_runtime": {
            "load_seconds": round(load_seconds, 6),
        },
    }
    corpus["corpus_contract_sha256"] = corpus_contract_sha256(corpus)
    return canonical, corpus, {"manifest": manifest, "dependencies": dependencies}


def feature_contracts(
    train_rows: Sequence[Mapping[str, Any]],
    hours: Sequence[int],
    dependencies: Mapping[str, Any],
) -> dict[int, dict[str, Any]]:
    contracts = {}
    for hour in hours:
        hour_rows = [row for row in train_rows if int(row["cutoff_hour"]) == int(hour)]
        frame = dependencies["feature_frame"](hour_rows)
        names = list(frame.columns)
        if not names:
            raise ValueError(f"no canonical density features for hour {hour}")
        market_columns = sorted(name for name in names if name.startswith("market_id_"))
        contracts[int(hour)] = {
            "feature_names": names,
            "feature_count": len(names),
            "market_feature_columns": market_columns,
            "city_context_columns": [
                name for name in ("latitude", "longitude", "coastal", "climate_normal", "climate_std", "high_so_far_anomaly", "forecast_anomaly")
                if name in names
            ],
            "sha256": payload_sha256(names),
        }
    return contracts


def _rows_for(
    rows: Sequence[Mapping[str, Any]],
    *,
    hour: int,
    include_markets: set[str] | None = None,
    exclude_market: str | None = None,
) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if int(row.get("cutoff_hour")) == int(hour)
        and (include_markets is None or str(row.get("market_id")) in include_markets)
        and (exclude_market is None or str(row.get("market_id")) != str(exclude_market))
    ]


def task_specs(markets: Sequence[str], hours: Sequence[int]) -> list[dict[str, Any]]:
    tasks = []
    for hour in sorted(int(value) for value in hours):
        tasks.append({"task_id": f"pooled__all__h{hour:02d}", "regime": "pooled", "market_id": None, "hour": hour})
        for market_id in sorted(markets):
            tasks.append({"task_id": f"per_city__{market_id}__h{hour:02d}", "regime": "per_city", "market_id": market_id, "hour": hour})
        for market_id in sorted(markets):
            tasks.append({"task_id": f"loco__{market_id}__h{hour:02d}", "regime": "loco", "market_id": market_id, "hour": hour})
    return tasks


def task_row_scopes(
    task: Mapping[str, Any],
    rows_by_split: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    regime = str(task["regime"])
    market_id = task.get("market_id")
    hour = int(task["hour"])
    if regime == "pooled":
        return {
            "train": _rows_for(rows_by_split["train"], hour=hour),
            "tune": _rows_for(rows_by_split["development"], hour=hour),
            "development": _rows_for(rows_by_split["development"], hour=hour),
            "confirmation": _rows_for(rows_by_split["confirmation"], hour=hour),
        }
    if regime == "per_city":
        included = {str(market_id)}
        return {
            "train": _rows_for(rows_by_split["train"], hour=hour, include_markets=included),
            "tune": _rows_for(rows_by_split["development"], hour=hour, include_markets=included),
            "development": _rows_for(rows_by_split["development"], hour=hour, include_markets=included),
            "confirmation": _rows_for(rows_by_split["confirmation"], hour=hour, include_markets=included),
        }
    if regime == "loco":
        included = {str(market_id)}
        return {
            "train": _rows_for(rows_by_split["train"], hour=hour, exclude_market=str(market_id)),
            "tune": _rows_for(rows_by_split["development"], hour=hour, exclude_market=str(market_id)),
            "development": _rows_for(rows_by_split["development"], hour=hour, include_markets=included),
            "confirmation": _rows_for(rows_by_split["confirmation"], hour=hour, include_markets=included),
        }
    raise ValueError(f"unknown benchmark regime: {regime}")


def _interval_probability(
    grid: np.ndarray,
    cumulative: np.ndarray,
    total: float,
    low_f: float | None,
    high_f: float | None,
) -> float:
    low_index = 0 if low_f is None or not math.isfinite(float(low_f)) else int(np.searchsorted(grid, float(low_f), side="left"))
    high_index = len(grid) if high_f is None or not math.isfinite(float(high_f)) else int(np.searchsorted(grid, float(high_f), side="left"))
    mass = float(cumulative[high_index] - cumulative[low_index])
    return mass / total if total > 0 else 0.0


def score_source_row(
    row: Mapping[str, Any],
    mean_f: float,
    *,
    grid_f: Sequence[float],
    sigma_f: float,
    shape_config: Mapping[str, Any],
    dependencies: Mapping[str, Any],
) -> dict[str, Any]:
    """Return exact canonical density-score sufficient statistics for one row."""

    grid = np.asarray(grid_f, dtype=float)
    weights = dependencies["density_weight_matrix"](
        [row],
        np.asarray([float(mean_f)], dtype=float),
        grid,
        float(sigma_f),
        shape_config=shape_config,
    )[0]
    cumulative = np.concatenate(([0.0], np.cumsum(weights, dtype=float)))
    total = float(cumulative[-1])
    unit = dependencies["record_unit"](row)
    final_bucket = float(row["final_bucket"])
    winner_low = dependencies["native_value_to_f"](final_bucket - 0.5, unit)
    winner_high = dependencies["native_value_to_f"](final_bucket + 0.5, unit)
    winner_p = max(1e-15, min(1.0, _interval_probability(grid, cumulative, total, winner_low, winner_high)))
    target_f = dependencies["native_value_to_f"](final_bucket, unit)

    band_weight = 0.0
    band_brier_sum = 0.0
    band_logloss_sum = 0.0
    band_count = 0
    for band in dependencies["density_synthetic_market_band_rows"](row):
        low_native, high_native = dependencies["bucket_interval_native"](
            band["kind"], band["value"], band.get("value_hi")
        )
        low_f, high_f = dependencies["native_interval_to_f"](
            low_native, high_native, band["unit"]
        )
        probability = _interval_probability(grid, cumulative, total, low_f, high_f)
        probability = max(1e-15, min(1.0 - 1e-15, probability))
        outcome = float(band["outcome"])
        sample_weight = float(band.get("_sample_weight", 1.0))
        binary_loss = -(
            outcome * math.log(probability)
            + (1.0 - outcome) * math.log(1.0 - probability)
        )
        band_weight += sample_weight
        band_brier_sum += sample_weight * ((probability - outcome) ** 2)
        band_logloss_sum += sample_weight * binary_loss
        band_count += 1

    return {
        "target_date": record_date(row),
        "market_id": str(row.get("market_id")),
        "unit": str(unit),
        "cutoff_hour": int(row.get("cutoff_hour")),
        "mean_f": float(mean_f),
        "target_f": float(target_f),
        "sigma_f": float(sigma_f),
        "density_logloss": -math.log(winner_p),
        "winning_bucket_brier": (winner_p - 1.0) ** 2,
        "mean_absolute_error_f": abs(float(mean_f) - float(target_f)),
        "market_band_rows": int(band_count),
        "market_band_weight": float(band_weight),
        "market_band_brier_sum": float(band_brier_sum),
        "market_band_logloss_sum": float(band_logloss_sum),
    }


def aggregate_source_scores(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    source_n = len(rows)
    band_weight = sum(float(row["market_band_weight"]) for row in rows)
    return {
        "n": source_n,
        "density_logloss": sum(float(row["density_logloss"]) for row in rows) / source_n,
        "winning_bucket_brier": sum(float(row["winning_bucket_brier"]) for row in rows) / source_n,
        "mean_absolute_error_f": sum(float(row["mean_absolute_error_f"]) for row in rows) / source_n,
        "market_band_rows": sum(int(row["market_band_rows"]) for row in rows),
        "market_band_weight": band_weight,
        "market_band_brier": (
            sum(float(row["market_band_brier_sum"]) for row in rows) / band_weight
            if band_weight > 0 else None
        ),
        "market_band_logloss": (
            sum(float(row["market_band_logloss_sum"]) for row in rows) / band_weight
            if band_weight > 0 else None
        ),
    }


def score_rows(
    rows: Sequence[Mapping[str, Any]],
    means: Sequence[float],
    *,
    grid_f: Sequence[float],
    sigma_f: float,
    shape_config: Mapping[str, Any],
    dependencies: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    scored = [
        score_source_row(
            row,
            mean,
            grid_f=grid_f,
            sigma_f=sigma_f,
            shape_config=shape_config,
            dependencies=dependencies,
        )
        for row, mean in zip(rows, means)
    ]
    return aggregate_source_scores(scored), scored


def tune_density_shape_fast(
    rows: Sequence[Mapping[str, Any]],
    means: Sequence[float],
    *,
    grid_f: Sequence[float],
    base_sigma_f: float,
    dependencies: Mapping[str, Any],
) -> dict[str, Any]:
    """Mirror canonical sigma/shape selection without an expanded N x grid matrix."""

    candidates = []
    for sigma_f in dependencies["density_sigma_candidates"](base_sigma_f):
        for raw_shape in dependencies["DENSITY_SHAPE_TUNING_CANDIDATES"]:
            shape = dependencies["density_shape_config"](raw_shape)
            score, _ = score_rows(
                rows,
                means,
                grid_f=grid_f,
                sigma_f=sigma_f,
                shape_config=shape,
                dependencies=dependencies,
            )
            if score is None:
                continue
            candidates.append({
                "sigma_f": float(sigma_f),
                "density_shape_id": shape["id"],
                "density_shape": shape,
                **score,
            })
    if not candidates:
        raise ValueError("density shape tuning produced no candidates")
    base_shape_id = dependencies["density_shape_id"](dependencies["DENSITY_DEFAULT_SHAPE"])
    candidates.sort(key=lambda row: (
        float(row.get("market_band_brier", float("inf"))),
        float(row.get("winning_bucket_brier", float("inf"))),
        float(row.get("density_logloss", float("inf"))),
        0 if row.get("density_shape_id") == base_shape_id else 1,
        abs(float(row["sigma_f"]) - float(base_sigma_f)),
    ))
    selected = candidates[0]
    return {
        "selected_sigma_f": selected["sigma_f"],
        "selected_density_shape_id": selected["density_shape_id"],
        "selected_density_shape": selected["density_shape"],
        "selected_score": selected,
        "base_sigma_f": float(base_sigma_f),
        "base_density_shape_id": base_shape_id,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def fit_task(
    task: Mapping[str, Any],
    *,
    rows_by_split: Mapping[str, Sequence[Mapping[str, Any]]],
    feature_contract: Mapping[str, Any],
    grid_f: Sequence[float],
    dependencies: Mapping[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    scopes = task_row_scopes(task, rows_by_split)
    if not scopes["train"] or not scopes["tune"]:
        raise ValueError(f"task {task['task_id']} has an empty train/tune scope")
    model, imputer, feature_names, residuals, training_metrics = dependencies["train_density_hour_model"](
        scopes["train"],
        feature_names=list(feature_contract["feature_names"]),
    )
    if list(feature_names) != list(feature_contract["feature_names"]):
        raise ValueError(f"task {task['task_id']} changed the declared feature contract")
    base_sigma_f = dependencies["residual_sigma_f"](residuals)
    tune_means = dependencies["predict_density_means"](
        model, imputer, feature_names, scopes["tune"]
    )
    tuning = tune_density_shape_fast(
        scopes["tune"],
        tune_means,
        grid_f=grid_f,
        base_sigma_f=base_sigma_f,
        dependencies=dependencies,
    )
    selected_sigma = float(tuning["selected_sigma_f"])
    selected_shape = dict(tuning["selected_density_shape"])
    scored_rows = []
    split_metrics = {}
    for split in SPLITS:
        means = dependencies["predict_density_means"](
            model, imputer, feature_names, scopes[split]
        )
        metrics, rows = score_rows(
            scopes[split],
            means,
            grid_f=grid_f,
            sigma_f=selected_sigma,
            shape_config=selected_shape,
            dependencies=dependencies,
        )
        split_metrics[split] = metrics
        for row in rows:
            row.update({
                "regime": task["regime"],
                "scored_market_id": task.get("market_id") or "all",
                "split": split,
                "density_shape_id": selected_shape["id"],
                "task_id": task["task_id"],
            })
            scored_rows.append(row)
    training_markets = sorted({str(row["market_id"]) for row in scopes["train"]})
    tuning_markets = sorted({str(row["market_id"]) for row in scopes["tune"]})
    model_parameters = {
        key: model.get_params().get(key)
        for key in ("max_iter", "max_leaf_nodes", "learning_rate", "random_state")
    }
    return {
        **dict(task),
        "feature_contract_sha256": feature_contract["sha256"],
        "feature_count": feature_contract["feature_count"],
        "training_markets": training_markets,
        "tuning_markets": tuning_markets,
        "train_rows": len(scopes["train"]),
        "tune_rows": len(scopes["tune"]),
        "development_score_rows": len(scopes["development"]),
        "confirmation_score_rows": len(scopes["confirmation"]),
        "trainer": {
            "callable": "weather.calibration.pooled_feature_model.train_density_hour_model",
            "estimator": type(model).__name__,
            "parameters": model_parameters,
            "imputer": {
                "class": type(imputer).__name__,
                "strategy": getattr(imputer, "strategy", None),
                "keep_empty_features": getattr(imputer, "keep_empty_features", None),
            },
        },
        "training_metrics": training_metrics,
        "base_sigma_f": float(base_sigma_f),
        "selected_sigma_f": selected_sigma,
        "selected_density_shape_id": selected_shape["id"],
        "selected_density_shape": selected_shape,
        "tuning_candidate_count": tuning["candidate_count"],
        "tuning_selected_score": tuning["selected_score"],
        "split_metrics": split_metrics,
        "scored_rows": scored_rows,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
    }


def source_provenance(dependencies: Mapping[str, Any]) -> dict[str, Any]:
    callables = (
        dependencies["train_density_hour_model"],
        dependencies["feature_frame"],
        dependencies["canonical_density_records"],
        dependencies["predict_density_means"],
        dependencies["density_weight_matrix"],
    )
    files = sorted({Path(inspect.getsourcefile(value) or "").resolve() for value in callables})
    own_file = Path(__file__).resolve()
    files.append(own_file)
    source_files = []
    for path in sorted(set(files)):
        if path.is_file():
            source_files.append({"path": str(path), "sha256": file_sha256(path), "size_bytes": path.stat().st_size})
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=own_file.parents[4],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return {
        "git_commit": commit,
        "source_files": source_files,
        "source_contract_sha256": payload_sha256(source_files),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "sklearn_version": sklearn.__version__,
        "platform": platform.platform(),
    }


def benchmark_run_id(
    *,
    corpus: Mapping[str, Any],
    contracts: Mapping[int, Mapping[str, Any]],
    grid_f: Sequence[float],
    configuration: Mapping[str, Any],
    sources: Mapping[str, Any],
) -> str:
    return payload_sha256({
        "corpus_contract_sha256": corpus["corpus_contract_sha256"],
        "feature_contracts": {str(hour): row["sha256"] for hour, row in sorted(contracts.items())},
        "grid_f": list(grid_f),
        "configuration": configuration,
        "source_contract_sha256": sources["source_contract_sha256"],
    })


def _checkpoint_path(root: Path, task: Mapping[str, Any]) -> Path:
    return root / "models" / str(task["regime"]) / f"{task['task_id']}.json"


def load_checkpoint(path: Path, *, run_id: str, task_id: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid checkpoint {path}: {exc}") from exc
    if payload.get("run_id") != run_id or payload.get("task_id") != task_id:
        raise ValueError(f"checkpoint identity mismatch: {path}")
    return payload


def load_authoritative_checkpoint_status(
    path: str | Path,
    *,
    run_id: str,
    expected_tasks: int,
) -> dict[str, Any]:
    """Load and validate the task ledger that owns resume accounting."""

    status_path = Path(path)
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid checkpoint status {status_path}: {exc}") from exc
    expected_schema = schema_version("pool_city_checkpoint_status")
    if status.get("schema_version") != expected_schema:
        raise ValueError(
            f"checkpoint status schema mismatch: expected={expected_schema}, "
            f"actual={status.get('schema_version')}"
        )
    if status.get("run_id") != run_id:
        raise ValueError(
            f"checkpoint status run_id mismatch: expected={run_id}, actual={status.get('run_id')}"
        )
    completed = int(status.get("completed_tasks", -1))
    total = int(status.get("total_tasks", -1))
    resumed = int(status.get("resumed_tasks", -1))
    if completed != int(expected_tasks) or total != int(expected_tasks):
        raise ValueError(
            "checkpoint status is not complete: "
            f"completed={completed}, total={total}, expected={expected_tasks}"
        )
    if resumed < 0 or resumed > completed:
        raise ValueError(
            f"checkpoint status has invalid resumed_tasks={resumed} for completed_tasks={completed}"
        )
    return status


def estimate_private_memory_bytes(
    rows_by_split: Mapping[str, Sequence[Mapping[str, Any]]],
    contracts: Mapping[int, Mapping[str, Any]],
    grid_f: Sequence[float],
) -> int:
    max_hour_rows = max(
        sum(1 for row in rows_by_split["train"] if int(row["cutoff_hour"]) == int(hour))
        for hour in contracts
    )
    max_features = max(int(contract["feature_count"]) for contract in contracts.values())
    # Conservative factor covers DataFrame, imputed matrix, HGB working state,
    # and one-row grid/shape scoring buffers.
    matrix_bytes = max_hour_rows * max_features * 8 * 12
    scoring_bytes = len(grid_f) * 8 * 64
    return int(matrix_bytes + scoring_bytes + 64 * 1024**2)


def run_pilot(
    *,
    markets: Sequence[str],
    hours: Sequence[int],
    rows_by_split: Mapping[str, Sequence[Mapping[str, Any]]],
    contracts: Mapping[int, Mapping[str, Any]],
    grid_f: Sequence[float],
    dependencies: Mapping[str, Any],
) -> dict[str, Any]:
    representative_hour = sorted(int(hour) for hour in hours)[len(hours) // 2]
    representative_market = next((market for market in sorted(markets) if market != "toronto"), sorted(markets)[0])
    tasks = [
        {"task_id": f"pilot_pooled__all__h{representative_hour:02d}", "regime": "pooled", "market_id": None, "hour": representative_hour},
        {"task_id": f"pilot_per_city__{representative_market}__h{representative_hour:02d}", "regime": "per_city", "market_id": representative_market, "hour": representative_hour},
        {"task_id": f"pilot_loco__{representative_market}__h{representative_hour:02d}", "regime": "loco", "market_id": representative_market, "hour": representative_hour},
    ]
    timings = {}
    details = []
    for task in tasks:
        result = fit_task(
            task,
            rows_by_split=rows_by_split,
            feature_contract=contracts[representative_hour],
            grid_f=grid_f,
            dependencies=dependencies,
        )
        timings[task["regime"]] = float(result["elapsed_seconds"])
        details.append({
            "regime": task["regime"],
            "market_id": task.get("market_id"),
            "hour": representative_hour,
            "elapsed_seconds": result["elapsed_seconds"],
            "train_rows": result["train_rows"],
            "tune_rows": result["tune_rows"],
        })
    model_seconds = len(hours) * (
        timings["pooled"]
        + len(markets) * timings["per_city"]
        + len(markets) * timings["loco"]
    )
    estimate_seconds = model_seconds * 1.20
    return {
        "schema_version": "pool_city_runtime_plan_v0.1",
        "generated_at_utc": utc_iso(),
        "representative_hour": representative_hour,
        "representative_market": representative_market,
        "pilot_tasks": details,
        "task_count": len(hours) * (1 + 2 * len(markets)),
        "estimate_method": "measured_regime_scope_seconds_x_exact_task_counts_plus_20pct",
        "estimated_model_seconds": model_seconds,
        "estimated_total_seconds": estimate_seconds,
        "estimated_total_hours": estimate_seconds / 3600.0,
    }


def execute_tasks(
    *,
    tasks: Sequence[Mapping[str, Any]],
    rows_by_split: Mapping[str, Sequence[Mapping[str, Any]]],
    contracts: Mapping[int, Mapping[str, Any]],
    grid_f: Sequence[float],
    dependencies: Mapping[str, Any],
    checkpoint_root: Path,
    run_id: str,
    status_path: Path,
) -> list[dict[str, Any]]:
    results = []
    started = time.perf_counter()
    resumed = 0
    for index, task in enumerate(tasks, start=1):
        checkpoint_path = _checkpoint_path(checkpoint_root, task)
        checkpoint = load_checkpoint(
            checkpoint_path,
            run_id=run_id,
            task_id=str(task["task_id"]),
        )
        if checkpoint is None:
            result = fit_task(
                task,
                rows_by_split=rows_by_split,
                feature_contract=contracts[int(task["hour"])],
                grid_f=grid_f,
                dependencies=dependencies,
            )
            checkpoint = {"run_id": run_id, "completed_at_utc": utc_iso(), **result}
            write_json_atomic(checkpoint_path, checkpoint)
        else:
            resumed += 1
        results.append(checkpoint)
        write_json_atomic(status_path, {
            "schema_version": "pool_city_checkpoint_status_v0.1",
            "run_id": run_id,
            "updated_at_utc": utc_iso(),
            "completed_tasks": index,
            "total_tasks": len(tasks),
            "resumed_tasks": resumed,
            "last_task_id": task["task_id"],
            "elapsed_seconds": time.perf_counter() - started,
        })
    return results


def _aggregate_group(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = aggregate_source_scores(rows) or {}
    return {**metrics}


def aggregate_benchmark(scored_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_market: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in scored_rows:
        by_market[(str(row["split"]), str(row["regime"]), str(row["market_id"]))].append(row)
    market_rows = []
    for (split, regime, market_id), rows in sorted(by_market.items()):
        market_rows.append({
            "split": split,
            "regime": regime,
            "market_id": market_id,
            "unit": str(rows[0]["unit"]),
            **_aggregate_group(rows),
        })

    family_rows = []
    for split in SPLITS:
        for regime in REGIMES:
            regime_markets = [row for row in market_rows if row["split"] == split and row["regime"] == regime]
            for family in ("ALL", "C", "F"):
                members = [row for row in regime_markets if family == "ALL" or row["unit"] == family]
                raw = [row for row in scored_rows if row["split"] == split and row["regime"] == regime and (family == "ALL" or row["unit"] == family)]
                if not members or not raw:
                    continue
                micro = _aggregate_group(raw)
                family_rows.append({
                    "split": split,
                    "regime": regime,
                    "unit_family": family,
                    "market_count": len(members),
                    "micro": micro,
                    "equal_city_macro": {
                        metric: sum(float(row[metric]) for row in members) / len(members)
                        for metric in (
                            "density_logloss",
                            "winning_bucket_brier",
                            "mean_absolute_error_f",
                            "market_band_brier",
                            "market_band_logloss",
                        )
                    },
                })
    return {"per_market": market_rows, "family": family_rows}


def exact_sign_p_value(negative: int, positive: int) -> float | None:
    n = int(negative) + int(positive)
    if n <= 0:
        return None
    smaller = min(int(negative), int(positive))
    tail = sum(math.comb(n, k) for k in range(smaller + 1)) / (2**n)
    return min(1.0, 2.0 * tail)


def paired_cluster_summary(
    left: Mapping[str, float],
    right: Mapping[str, float],
    *,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    dates = sorted(set(left) & set(right))
    deltas = [float(left[value]) - float(right[value]) for value in dates]
    if not deltas:
        return {"paired_dates": 0, "status": "INSUFFICIENT"}
    negative = sum(delta < -1e-15 for delta in deltas)
    positive = sum(delta > 1e-15 for delta in deltas)
    ties = len(deltas) - negative - positive
    rng = random.Random(int(seed))
    bootstrap = []
    for _ in range(max(1, int(bootstrap_replicates))):
        sample = [deltas[rng.randrange(len(deltas))] for _ in deltas]
        bootstrap.append(sum(sample) / len(sample))
    low, high = np.quantile(np.asarray(bootstrap), [0.025, 0.975])
    ordered = sorted(deltas)
    median = (
        ordered[len(ordered) // 2]
        if len(ordered) % 2 else
        (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2.0
    )
    return {
        "paired_dates": len(dates),
        "delta_definition": "left_market_band_brier_minus_right_market_band_brier; negative favors left",
        "mean_delta": sum(deltas) / len(deltas),
        "median_delta": median,
        "bootstrap_ci95": [float(low), float(high)],
        "bootstrap_replicates": int(bootstrap_replicates),
        "bootstrap_seed": int(seed),
        "left_better_dates": negative,
        "right_better_dates": positive,
        "ties": ties,
        "two_sided_exact_sign_p": exact_sign_p_value(negative, positive),
        "date_deltas": [
            {"target_date": target_date, "delta": delta}
            for target_date, delta in zip(dates, deltas)
        ],
    }


def paired_evidence(
    scored_rows: Sequence[Mapping[str, Any]],
    *,
    split: str = "confirmation",
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> list[dict[str, Any]]:
    rows = [row for row in scored_rows if row["split"] == split]
    date_scores: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        for family in ("ALL", str(row["unit"])):
            date_scores[(str(row["regime"]), family, str(row["target_date"]))].append(row)
    maps = {}
    for (regime, family, target_date), members in date_scores.items():
        maps.setdefault((regime, family), {})[target_date] = _aggregate_group(members)["market_band_brier"]
    comparisons = []
    pairs = (("pooled", "per_city"), ("pooled", "loco"), ("per_city", "loco"))
    for family in ("ALL", "C", "F"):
        for pair_index, (left, right) in enumerate(pairs):
            comparison = paired_cluster_summary(
                maps.get((left, family), {}),
                maps.get((right, family), {}),
                bootstrap_replicates=bootstrap_replicates,
                seed=int(seed) + pair_index + {"ALL": 0, "C": 100, "F": 200}[family],
            )
            comparisons.append({
                "split": split,
                "unit_family": family,
                "left_regime": left,
                "right_regime": right,
                **comparison,
            })
    return comparisons


def _format_number(value: Any, digits: int = 6) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return lines


def render_report(payload: Mapping[str, Any]) -> str:
    runtime = payload.get("runtime") or {}
    corpus = payload.get("corpus") or {}
    results = payload.get("results") or {}
    lines = [
        "# Pool vs Per-City vs Leave-One-City-Out Density Benchmark",
        "",
        f"Status: **{payload.get('status')}**",
        "",
        "Research-only result. It does not authorize serving changes, artifact promotion, or live trading.",
        "",
        "## Design",
        "",
        "All regimes use the same canonical continuous-density HGB trainer, hourly feature contract, hyperparameters, canonical-F grid, and native-band scorer. Only geographic training scope changes. Static climate/source context is frozen before 2024; 2024 selects density width/shape, and 2025 is untouched confirmation.",
        "",
        f"Balanced panel: `{corpus.get('balanced_panel_dates')}` fleet dates; train/dev/confirm rows `{corpus.get('split_rows')}`.",
        f"Corpus contract SHA-256: `{corpus.get('corpus_contract_sha256')}`.",
        f"Input manifest SHA-256: `{corpus.get('input_manifest_sha256')}`.",
        "",
        "## Runtime and bounds",
        "",
        f"Task count: `{runtime.get('task_count')}`; completed: `{runtime.get('completed_tasks', 0)}`.",
        f"Pilot estimate: `{_format_number(runtime.get('estimated_total_hours'), 3)}` hours; overnight boundary: `{_format_number(runtime.get('max_runtime_hours'), 1)}` hours.",
        f"Estimated private-memory ceiling: `{runtime.get('estimated_private_memory_bytes')}` bytes; configured budget: `{runtime.get('memory_budget_bytes')}` bytes.",
        "",
    ]
    if payload.get("status") != "COMPLETE":
        lines += [
            "## Pending execution",
            "",
            str(payload.get("next_action") or "Run mode has not been authorized."),
            "",
        ]
        return "\n".join(lines) + "\n"

    correction = payload.get("reporting_correction") or {}
    if correction:
        lines += [
            "## Reporting correction",
            "",
            (
                "The completed model checkpoints and run ID were preserved. Final aggregation was regenerated "
                f"from `{correction.get('finalization_reused_checkpoints')}` completed checkpoints after "
                "correcting resume accounting to use the authoritative checkpoint-status ledger."
            ),
            "",
            (
                "`runtime.resumed_tasks` was corrected from "
                f"`{correction.get('runtime_resumed_tasks_before')}` to "
                f"`{correction.get('runtime_resumed_tasks_after')}`; this reporting-only correction did not "
                "retrain or alter any model checkpoint."
            ),
            "",
        ]

    lines += ["## Confirmation metrics", ""]
    family_rows = [row for row in results.get("family", []) if row.get("split") == "confirmation"]
    lines += _markdown_table(
        ["Unit", "Regime", "Markets", "Macro band Brier", "Macro band logloss", "Macro winner Brier", "Macro MAE F"],
        [
            [
                row["unit_family"], row["regime"], row["market_count"],
                _format_number(row["equal_city_macro"]["market_band_brier"]),
                _format_number(row["equal_city_macro"]["market_band_logloss"]),
                _format_number(row["equal_city_macro"]["winning_bucket_brier"]),
                _format_number(row["equal_city_macro"]["mean_absolute_error_f"], 4),
            ]
            for row in family_rows
        ],
    )
    lines += ["", "## Per-market confirmation", ""]
    market_rows = [row for row in results.get("per_market", []) if row.get("split") == "confirmation"]
    lines += _markdown_table(
        ["Market", "Unit", "Regime", "Rows", "Band Brier", "Band logloss", "Winner Brier", "MAE F"],
        [
            [
                row["market_id"], row["unit"], row["regime"], row["n"],
                _format_number(row["market_band_brier"]),
                _format_number(row["market_band_logloss"]),
                _format_number(row["winning_bucket_brier"]),
                _format_number(row["mean_absolute_error_f"], 4),
            ]
            for row in market_rows
        ],
    )
    lines += ["", "## Paired confirmation evidence", ""]
    lines += _markdown_table(
        ["Unit", "Left", "Right", "Dates", "Mean delta", "95% bootstrap CI", "Left/Right/Tie", "Sign p"],
        [
            [
                row["unit_family"], row["left_regime"], row["right_regime"], row.get("paired_dates"),
                _format_number(row.get("mean_delta")),
                (
                    f"[{_format_number((row.get('bootstrap_ci95') or [None, None])[0])}, "
                    f"{_format_number((row.get('bootstrap_ci95') or [None, None])[1])}]"
                ),
                f"{row.get('left_better_dates', 0)}/{row.get('right_better_dates', 0)}/{row.get('ties', 0)}",
                _format_number(row.get("two_sided_exact_sign_p"), 4),
            ]
            for row in payload.get("paired_evidence", [])
        ],
    )
    lines += [
        "",
        "Delta is left minus right market-band Brier, so negative favors the left regime. Bootstrap resampling and the exact sign test cluster by fleet date.",
        "",
    ]
    return "\n".join(lines) + "\n"


def ensure_scratch_output(
    path: str | Path,
    *,
    data_root: str | Path,
) -> Path:
    from weather.paths import REPO_ROOT

    try:
        resolved = Path(path).expanduser().resolve(strict=False)
        resolved_data_root = Path(data_root).expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"cannot resolve benchmark output/data path: {exc}") from exc
    if _is_relative_to(resolved, resolved_data_root):
        raise ValueError(
            "benchmark output resolves inside the supplied read-only data root: "
            f"output={resolved}, data_root={resolved_data_root}"
        )
    if not _is_relative_to(resolved, REPO_ROOT.resolve()) or "scratch" not in {part.lower() for part in resolved.parts}:
        raise ValueError(f"benchmark outputs must stay below repository scratch/: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def finalize_completed_checkpoint_run(
    *,
    data_root: str | Path,
    out_dir: str | Path,
) -> dict[str, Any]:
    """Regenerate aggregate artifacts from one already-complete checkpoint set."""

    out_dir = ensure_scratch_output(out_dir, data_root=data_root)
    artifact_path = out_dir / "pool_city_training_benchmark.json"
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load completed benchmark artifact {artifact_path}: {exc}") from exc
    if payload.get("status") != "COMPLETE":
        raise ValueError(f"benchmark artifact is not complete: status={payload.get('status')}")
    run_id = str(payload.get("run_id") or "")
    if not run_id:
        raise ValueError("completed benchmark artifact has no run_id")
    configuration = payload.get("configuration") or {}
    corpus = payload.get("corpus") or {}
    tasks = task_specs(corpus.get("markets") or (), configuration.get("hours") or ())
    if not tasks:
        raise ValueError("completed benchmark artifact has no task inventory")
    status_path = out_dir / "checkpoint_status.json"
    checkpoint_status = load_authoritative_checkpoint_status(
        status_path,
        run_id=run_id,
        expected_tasks=len(tasks),
    )
    task_results = []
    for task in tasks:
        checkpoint = load_checkpoint(
            _checkpoint_path(out_dir / "checkpoints", task),
            run_id=run_id,
            task_id=str(task["task_id"]),
        )
        if checkpoint is None:
            raise ValueError(f"missing completed checkpoint for {task['task_id']}")
        task_results.append(checkpoint)

    scored_rows = [row for result in task_results for row in result["scored_rows"]]
    results = aggregate_benchmark(scored_rows)
    comparisons = paired_evidence(
        scored_rows,
        split="confirmation",
        bootstrap_replicates=int(configuration.get("bootstrap_replicates", DEFAULT_BOOTSTRAP_REPLICATES)),
        seed=int(configuration.get("bootstrap_seed", DEFAULT_BOOTSTRAP_SEED)),
    )
    existing_correction = payload.get("reporting_correction") or {}
    previous_resumed = existing_correction.get(
        "runtime_resumed_tasks_before",
        (payload.get("runtime") or {}).get("resumed_tasks"),
    )
    corrected_at = str(existing_correction.get("corrected_at_utc") or utc_iso())
    correction = {
        **existing_correction,
        "status": "APPLIED",
        "kind": "reporting_only_checkpoint_refinalization",
        "reason": (
            "The original final assembly counted the presence of completed_at_utc on every task result "
            "instead of reading resumed_tasks from the checkpoint-status ledger."
        ),
        "artifact_sha256_before_correction": existing_correction.get(
            "artifact_sha256_before_correction"
        ) or file_sha256(artifact_path),
        "checkpoint_status_sha256": file_sha256(status_path),
        "corrected_at_utc": corrected_at,
        "model_run_id": run_id,
        "model_run_id_preserved": True,
        "model_source_contract_sha256": (payload.get("source_provenance") or {}).get(
            "source_contract_sha256"
        ),
        "runtime_resumed_tasks_before": previous_resumed,
        "runtime_resumed_tasks_after": int(checkpoint_status["resumed_tasks"]),
        "authoritative_resumed_tasks_source": "checkpoint_status.json",
        "finalization_reused_checkpoints": len(task_results),
        "model_checkpoints_retrained": 0,
        "trainer_callable_label_correction": {
            "checkpoint_recorded": "weather.calibration.pooled_band_training.train_density_hour_model",
            "actual_imported_callable": "weather.calibration.pooled_feature_model.train_density_hour_model",
        },
    }
    runtime = {
        **(payload.get("runtime") or {}),
        "completed_tasks": len(task_results),
        "resumed_tasks": int(checkpoint_status["resumed_tasks"]),
        "resumed_tasks_source": "checkpoint_status.json",
        "finalization_reused_checkpoints": len(task_results),
    }
    corrected = {
        **payload,
        "runtime": runtime,
        "results": results,
        "paired_evidence": comparisons,
        "reporting_corrected_at_utc": corrected_at,
        "reporting_correction": correction,
    }
    write_csv_atomic(out_dir / "predictions.csv", scored_rows)
    write_json_atomic(artifact_path, corrected)
    write_text_atomic(
        out_dir / "pool_city_training_benchmark.md",
        render_report(corrected),
    )
    return corrected


def run_benchmark(
    *,
    data_root: str | Path,
    out_dir: str | Path,
    mode: str = "plan",
    confirm_research_only: bool = False,
    hours: Sequence[int] = DEFAULT_HOURS,
    panel_start_year: int = DEFAULT_PANEL_START_YEAR,
    development_year: int = DEFAULT_DEVELOPMENT_YEAR,
    confirmation_year: int = DEFAULT_CONFIRMATION_YEAR,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    max_runtime_hours: float = DEFAULT_MAX_RUNTIME_HOURS,
    memory_budget_bytes: int = DEFAULT_MEMORY_BUDGET_BYTES,
) -> dict[str, Any]:
    out_dir = ensure_scratch_output(out_dir, data_root=data_root)
    if str(mode) not in {"plan", "run", "finalize"}:
        raise ValueError("mode must be plan, run, or finalize")
    if mode in {"run", "finalize"} and not confirm_research_only:
        raise ValueError(f"{mode} execution requires confirm_research_only=True")
    if mode == "finalize":
        return finalize_completed_checkpoint_run(data_root=data_root, out_dir=out_dir)

    total_started = time.perf_counter()
    rows_by_split, corpus, loaded = load_corpus(
        data_root=data_root,
        hours=hours,
        panel_start_year=panel_start_year,
        development_year=development_year,
        confirmation_year=confirmation_year,
    )
    dependencies = loaded["dependencies"]
    manifest = loaded["manifest"]
    contracts = feature_contracts(rows_by_split["train"], hours, dependencies)
    low_f, high_f = dependencies["density_support_f"](rows_by_split["train"])
    grid_f = dependencies["canonical_grid_f"](low_f, high_f, 0.1)
    markets = list(corpus["markets"])
    tasks = task_specs(markets, hours)
    sources = source_provenance(dependencies)
    configuration = {
        "mode": mode,
        "hours": [int(hour) for hour in hours],
        "panel_start_year": int(panel_start_year),
        "development_year": int(development_year),
        "confirmation_year": int(confirmation_year),
        "grid_step_f": 0.1,
        "bootstrap_replicates": int(bootstrap_replicates),
        "bootstrap_seed": int(bootstrap_seed),
        "geographic_regimes": list(REGIMES),
        "development_use": "sigma_and_density_shape_selection_only",
        "confirmation_use": "scoring_only",
        "loco_contract": "held_out_market_excluded_from_training_and_development_tuning",
    }
    run_id = benchmark_run_id(
        corpus=corpus,
        contracts=contracts,
        grid_f=grid_f,
        configuration={key: value for key, value in configuration.items() if key != "mode"},
        sources=sources,
    )
    private_memory = estimate_private_memory_bytes(rows_by_split, contracts, grid_f)
    if private_memory > int(memory_budget_bytes):
        raise MemoryError(
            f"projected private memory {private_memory} exceeds budget {memory_budget_bytes}"
        )
    pilot = run_pilot(
        markets=markets,
        hours=hours,
        rows_by_split=rows_by_split,
        contracts=contracts,
        grid_f=grid_f,
        dependencies=dependencies,
    )
    runtime = {
        **pilot,
        "run_id": run_id,
        "max_runtime_hours": float(max_runtime_hours),
        "memory_budget_bytes": int(memory_budget_bytes),
        "estimated_private_memory_bytes": private_memory,
        "completed_tasks": 0,
    }
    write_json_atomic(out_dir / "input_manifest.json", manifest)
    write_json_atomic(out_dir / "runtime_plan.json", runtime)

    base_payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "research_only": True,
        "promotion_permission": "forbidden",
        "run_id": run_id,
        "configuration": configuration,
        "corpus": corpus,
        "input_manifest": {
            key: value for key, value in manifest.items() if key != "files"
        },
        "source_provenance": sources,
        "trainer_contract": {
            "canonical_model_family": "pooled_continuous_density_hgb_v0.7",
            "feature_schema_version": dependencies["FEATURE_SCHEMA_VERSION"],
            "feature_contracts": {
                str(hour): {key: value for key, value in contract.items() if key != "feature_names"}
                for hour, contract in contracts.items()
            },
            "feature_names_by_hour": {
                str(hour): contract["feature_names"] for hour, contract in contracts.items()
            },
            "grid_low_f": low_f,
            "grid_high_f": high_f,
            "grid_step_f": 0.1,
            "grid_points": len(grid_f),
        },
        "runtime": runtime,
    }
    if float(pilot["estimated_total_hours"]) > float(max_runtime_hours):
        payload = {
            **base_payload,
            "status": "BLOCKED_RUNTIME_BOUNDARY",
            "next_action": "Operator approval is required because the pilot projects beyond the configured overnight boundary.",
        }
        write_json_atomic(out_dir / "pool_city_training_benchmark.json", payload)
        write_text_atomic(
            out_dir / "pool_city_training_benchmark.md",
            render_report(payload),
        )
        return payload
    if mode == "plan":
        payload = {
            **base_payload,
            "status": "READY_FOR_EXPLICIT_RUN",
            "next_action": (
                "Resource-safe plan complete. Re-run with --mode run "
                "--confirm-research-only after explicit coordination approval."
            ),
        }
        write_json_atomic(out_dir / "pool_city_training_benchmark.json", payload)
        write_text_atomic(
            out_dir / "pool_city_training_benchmark.md",
            render_report(payload),
        )
        return payload

    task_results = execute_tasks(
        tasks=tasks,
        rows_by_split=rows_by_split,
        contracts=contracts,
        grid_f=grid_f,
        dependencies=dependencies,
        checkpoint_root=out_dir / "checkpoints",
        run_id=run_id,
        status_path=out_dir / "checkpoint_status.json",
    )
    scored_rows = [row for result in task_results for row in result["scored_rows"]]
    results = aggregate_benchmark(scored_rows)
    comparisons = paired_evidence(
        scored_rows,
        split="confirmation",
        bootstrap_replicates=bootstrap_replicates,
        seed=bootstrap_seed,
    )
    runtime.update({
        "completed_tasks": len(task_results),
        "actual_total_seconds": time.perf_counter() - total_started,
        "resumed_tasks": load_authoritative_checkpoint_status(
            out_dir / "checkpoint_status.json",
            run_id=run_id,
            expected_tasks=len(tasks),
        )["resumed_tasks"],
        "resumed_tasks_source": "checkpoint_status.json",
    })
    payload = {
        **base_payload,
        "status": "COMPLETE",
        "completed_at_utc": utc_iso(),
        "runtime": runtime,
        "results": results,
        "paired_evidence": comparisons,
        "checkpoint_contract": {
            "directory": str((out_dir / "checkpoints").resolve()),
            "task_count": len(tasks),
            "identity": "run_id + task_id",
            "atomic": True,
        },
    }
    write_csv_atomic(out_dir / "predictions.csv", scored_rows)
    write_json_atomic(out_dir / "pool_city_training_benchmark.json", payload)
    write_text_atomic(
        out_dir / "pool_city_training_benchmark.md",
        render_report(payload),
    )
    return payload


def parse_hours(value: str) -> tuple[int, ...]:
    hours = tuple(sorted({int(item.strip()) for item in str(value).split(",") if item.strip()}))
    if not hours or any(hour < 0 or hour > 23 for hour in hours):
        raise ValueError("hours must be a comma-separated set from 0 through 23")
    return hours


def main() -> None:
    from weather.paths import repo_path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, help="Explicit read-only mirror root.")
    parser.add_argument(
        "--out-dir",
        default=str(repo_path("scratch", "workstation-research-output", "workstream_b", "pool_city")),
    )
    parser.add_argument("--mode", choices=("plan", "run", "finalize"), default="plan")
    parser.add_argument("--confirm-research-only", action="store_true")
    parser.add_argument("--hours", default=",".join(str(hour) for hour in DEFAULT_HOURS))
    parser.add_argument("--panel-start-year", type=int, default=DEFAULT_PANEL_START_YEAR)
    parser.add_argument("--development-year", type=int, default=DEFAULT_DEVELOPMENT_YEAR)
    parser.add_argument("--confirmation-year", type=int, default=DEFAULT_CONFIRMATION_YEAR)
    parser.add_argument("--bootstrap-replicates", type=int, default=DEFAULT_BOOTSTRAP_REPLICATES)
    parser.add_argument("--bootstrap-seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    parser.add_argument("--max-runtime-hours", type=float, default=DEFAULT_MAX_RUNTIME_HOURS)
    parser.add_argument("--memory-budget-bytes", type=int, default=DEFAULT_MEMORY_BUDGET_BYTES)
    args = parser.parse_args()
    payload = run_benchmark(
        data_root=args.data_root,
        out_dir=args.out_dir,
        mode=args.mode,
        confirm_research_only=args.confirm_research_only,
        hours=parse_hours(args.hours),
        panel_start_year=args.panel_start_year,
        development_year=args.development_year,
        confirmation_year=args.confirmation_year,
        bootstrap_replicates=args.bootstrap_replicates,
        bootstrap_seed=args.bootstrap_seed,
        max_runtime_hours=args.max_runtime_hours,
        memory_budget_bytes=args.memory_budget_bytes,
    )
    print(json.dumps({
        "status": payload["status"],
        "run_id": payload["run_id"],
        "out_dir": str(Path(args.out_dir).resolve()),
        "estimated_total_hours": payload["runtime"].get("estimated_total_hours"),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
