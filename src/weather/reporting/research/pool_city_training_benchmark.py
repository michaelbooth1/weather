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
The historical season window requires an explicit calendar anchor so reruns do
not silently move when the workstation date changes.

The CLI is research-only and defaults to ``plan`` mode.  Full execution
requires ``--mode run --confirm-research-only``.  All writes are constrained to
an explicit repository ``scratch`` directory, while the mirrored data root is
opened through a read-only tracing guard.
"""

from __future__ import annotations

import argparse
import builtins
import hashlib
import json
import math
import os
import platform
import random
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from weather.io import (
    write_csv_rows_atomic as _write_csv_rows_atomic,
    write_json_atomic as _write_json_file_atomic,
    write_text_atomic,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("pool_city_training_benchmark")
CHECKPOINT_SCHEMA_VERSION = schema_version("pool_city_task_checkpoint")
CHECKPOINT_STATUS_SCHEMA_VERSION = schema_version("pool_city_checkpoint_status")
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
CHECKPOINT_DIGEST_FIELD = "checkpoint_sha256"
CHECKPOINT_STATUS_DIGEST_FIELD = "status_sha256"
PREDICTION_NUMERIC_FIELDS = (
    "mean_f",
    "target_f",
    "sigma_f",
    "density_logloss",
    "winning_bucket_brier",
    "mean_absolute_error_f",
    "market_band_rows",
    "market_band_weight",
    "market_band_brier_sum",
    "market_band_logloss_sum",
)


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


def self_digest(payload: Mapping[str, Any], *, digest_field: str) -> str:
    return payload_sha256({
        key: value for key, value in payload.items() if key != digest_field
    })


def require_sha256(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} is not a lowercase SHA-256 digest")
    return value


def _reject_duplicate_json_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"duplicate JSON object key: {key}")
        output[key] = value
    return output


def _reject_nonfinite_json_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {value}")


def _reject_nested_nonfinite_json(value: Any, *, path: str = "$") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite JSON number at {path}")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_nested_nonfinite_json(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_nested_nonfinite_json(item, path=f"{path}[{index}]")


def load_json_mapping_strict(path: str | Path, *, label: str) -> dict[str, Any]:
    artifact_path = Path(path)
    try:
        payload = json.loads(
            artifact_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_json_constant,
        )
        _reject_nested_nonfinite_json(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid {label} {artifact_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"invalid {label} {artifact_path}: root must be an object")
    return payload


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
    opened_identity: dict[Path, tuple[int, int, int, int]]


def _file_identity(stat_result) -> tuple[int, int, int, int]:
    return (
        int(getattr(stat_result, "st_dev", 0)),
        int(getattr(stat_result, "st_ino", 0)),
        int(stat_result.st_size),
        int(stat_result.st_mtime_ns),
    )


@contextmanager
def read_only_path_trace(data_root: str | Path):
    """Trace data-root reads and reject any attempted mirror write."""

    supplied_data_root = Path(data_root).expanduser()
    lexical_data_root = Path(os.path.abspath(os.fspath(supplied_data_root)))
    data_root = supplied_data_root.resolve()
    lexical_data_roots = tuple({lexical_data_root, data_root})
    original_path_open = Path.open
    original_exists = Path.exists
    original_builtin_open = builtins.open
    original_os_open = os.open
    path_mutator_names = tuple(
        name
        for name in (
            "unlink",
            "rename",
            "replace",
            "mkdir",
            "rmdir",
            "touch",
            "write_text",
            "write_bytes",
            "chmod",
            "symlink_to",
            "hardlink_to",
        )
        if hasattr(Path, name)
    )
    original_path_mutators = {
        name: getattr(Path, name) for name in path_mutator_names
    }
    os_single_mutator_names = tuple(
        name
        for name in (
            "remove",
            "unlink",
            "mkdir",
            "makedirs",
            "rmdir",
            "removedirs",
            "chmod",
            "utime",
            "truncate",
        )
        if hasattr(os, name)
    )
    original_os_single_mutators = {
        name: getattr(os, name) for name in os_single_mutator_names
    }
    os_pair_mutator_names = tuple(
        name for name in ("rename", "replace", "link") if hasattr(os, name)
    )
    original_os_pair_mutators = {
        name: getattr(os, name) for name in os_pair_mutator_names
    }
    original_os_symlink = getattr(os, "symlink", None)
    shutil_destination_mutator_names = tuple(
        name
        for name in (
            "copy",
            "copy2",
            "copyfile",
            "copytree",
            "copymode",
            "copystat",
        )
        if hasattr(shutil, name)
    )
    original_shutil_destination_mutators = {
        name: getattr(shutil, name)
        for name in shutil_destination_mutator_names
    }
    original_shutil_move = shutil.move
    original_shutil_rmtree = shutil.rmtree
    trace = ReadTrace(opened=set(), checked=set(), opened_identity={})

    def resolved_path(raw_path: Any) -> Path | None:
        if isinstance(raw_path, int):
            return None
        try:
            path = Path(os.fsdecode(raw_path)).resolve(strict=False)
        except (OSError, TypeError, ValueError):
            return None
        return path

    def relevant(raw_path: Any) -> Path | None:
        resolved = resolved_path(raw_path)
        if resolved is None or not _is_relative_to(resolved, data_root):
            return None
        return resolved

    def deny_mutation(
        raw_path: Any,
        *,
        operation: str,
        dir_fd: int | None = None,
    ) -> None:
        if isinstance(raw_path, int):
            raise PermissionError(
                f"descriptor-based {operation} cannot prove read-only mirror provenance"
            )
        if dir_fd is not None:
            try:
                relative = not os.path.isabs(os.fsdecode(raw_path))
            except (TypeError, ValueError):
                relative = True
            if relative:
                raise PermissionError(
                    f"relative {operation} with dir_fd cannot prove read-only mirror provenance"
                )
        try:
            lexical = Path(
                os.path.abspath(os.fsdecode(raw_path))
            )
        except (OSError, TypeError, ValueError):
            lexical = None
        resolved = relevant(raw_path)
        lexical_inside = lexical is not None and any(
            _is_relative_to(lexical, root) for root in lexical_data_roots
        )
        if resolved is not None or lexical_inside:
            blocked = resolved or lexical
            if blocked is not None:
                trace.checked.add(blocked)
            raise PermissionError(
                f"research input mirror is read-only: {operation}: {blocked}"
            )

    def record_opened(resolved: Path, identity: tuple[int, int, int, int] | None) -> None:
        trace.checked.add(resolved)
        previous = trace.opened_identity.get(resolved)
        if previous is not None and identity is not None and previous != identity:
            raise RuntimeError(f"research input changed between reads: {resolved}")
        if identity is not None:
            trace.opened_identity[resolved] = identity
        trace.opened.add(resolved)

    def identity_for_handle(handle: Any, resolved: Path) -> tuple[int, int, int, int] | None:
        try:
            return _file_identity(os.fstat(handle.fileno()))
        except (AttributeError, OSError, ValueError):
            try:
                return _file_identity(resolved.stat())
            except OSError:
                return None

    def identity_for_fd(fd: int, resolved: Path) -> tuple[int, int, int, int] | None:
        try:
            return _file_identity(os.fstat(fd))
        except OSError:
            try:
                return _file_identity(resolved.stat())
            except OSError:
                return None

    def traced_open(self: Path, mode="r", *args, **kwargs):
        resolved = relevant(self)
        if resolved is not None:
            trace.checked.add(resolved)
            if any(flag in str(mode) for flag in ("w", "a", "x", "+")):
                raise PermissionError(f"research input mirror is read-only: {resolved}")
        handle = original_path_open(self, mode, *args, **kwargs)
        if resolved is not None:
            try:
                record_opened(resolved, identity_for_handle(handle, resolved))
            except Exception:
                handle.close()
                raise
        return handle

    def traced_builtin_open(file, mode="r", *args, **kwargs):
        if isinstance(file, int):
            raise PermissionError(
                "descriptor-based builtins.open cannot prove read-only mirror provenance"
            )
        resolved = relevant(file)
        if resolved is not None:
            trace.checked.add(resolved)
            if any(flag in str(mode) for flag in ("w", "a", "x", "+")):
                raise PermissionError(f"research input mirror is read-only: {resolved}")
            if kwargs.get("opener") is not None:
                raise PermissionError(
                    f"custom opener is forbidden for research mirror input: {resolved}"
                )
        handle = original_builtin_open(file, mode, *args, **kwargs)
        if resolved is not None:
            try:
                record_opened(resolved, identity_for_handle(handle, resolved))
            except Exception:
                handle.close()
                raise
        return handle

    write_flags = (
        os.O_WRONLY
        | os.O_RDWR
        | os.O_APPEND
        | os.O_CREAT
        | os.O_TRUNC
        | os.O_EXCL
        | int(getattr(os, "O_TEMPORARY", 0))
    )

    def traced_os_open(path, flags, mode=0o777, *, dir_fd=None):
        if dir_fd is not None and not os.path.isabs(path):
            raise PermissionError(
                "relative os.open with dir_fd cannot prove read-only mirror provenance"
            )
        resolved = relevant(path)
        if resolved is not None:
            trace.checked.add(resolved)
            if int(flags) & write_flags:
                raise PermissionError(f"research input mirror is read-only: {resolved}")
        if dir_fd is None:
            fd = original_os_open(path, flags, mode)
        else:
            fd = original_os_open(path, flags, mode, dir_fd=dir_fd)
        if resolved is not None:
            try:
                record_opened(resolved, identity_for_fd(fd, resolved))
            except Exception:
                os.close(fd)
                raise
        return fd

    def traced_exists(self: Path):
        resolved = relevant(self)
        if resolved is not None:
            trace.checked.add(resolved)
        return original_exists(self)

    def guarded_path_mutator(name: str):
        original = original_path_mutators[name]

        def guarded(self: Path, *args, **kwargs):
            deny_mutation(self, operation=f"Path.{name}")
            target = args[0] if args else kwargs.get("target")
            if name in {"rename", "replace"} and target is not None:
                deny_mutation(
                    target,
                    operation=f"Path.{name} destination",
                )
            return original(self, *args, **kwargs)

        return guarded

    def guarded_os_single_mutator(name: str):
        original = original_os_single_mutators[name]

        def guarded(path, *args, **kwargs):
            deny_mutation(
                path,
                operation=f"os.{name}",
                dir_fd=kwargs.get("dir_fd"),
            )
            return original(path, *args, **kwargs)

        return guarded

    def guarded_os_pair_mutator(name: str):
        original = original_os_pair_mutators[name]

        def guarded(source, destination, *args, **kwargs):
            deny_mutation(
                source,
                operation=f"os.{name} source",
                dir_fd=kwargs.get("src_dir_fd"),
            )
            deny_mutation(
                destination,
                operation=f"os.{name} destination",
                dir_fd=kwargs.get("dst_dir_fd"),
            )
            return original(source, destination, *args, **kwargs)

        return guarded

    def guarded_os_symlink(source, destination, *args, **kwargs):
        # Creating a link mutates its destination directory. The source may be
        # a deliberately relative link target, so only the link path is gated.
        deny_mutation(
            destination,
            operation="os.symlink destination",
            dir_fd=kwargs.get("dir_fd"),
        )
        return original_os_symlink(source, destination, *args, **kwargs)

    def guarded_shutil_destination_mutator(name: str):
        original = original_shutil_destination_mutators[name]

        def guarded(source, destination, *args, **kwargs):
            deny_mutation(
                destination,
                operation=f"shutil.{name} destination",
            )
            return original(source, destination, *args, **kwargs)

        return guarded

    def guarded_shutil_move(source, destination, *args, **kwargs):
        deny_mutation(source, operation="shutil.move source")
        deny_mutation(destination, operation="shutil.move destination")
        return original_shutil_move(source, destination, *args, **kwargs)

    def guarded_shutil_rmtree(path, *args, **kwargs):
        deny_mutation(path, operation="shutil.rmtree")
        return original_shutil_rmtree(path, *args, **kwargs)

    Path.open = traced_open
    Path.exists = traced_exists
    for name in path_mutator_names:
        setattr(Path, name, guarded_path_mutator(name))
    builtins.open = traced_builtin_open
    os.open = traced_os_open
    for name in os_single_mutator_names:
        setattr(os, name, guarded_os_single_mutator(name))
    for name in os_pair_mutator_names:
        setattr(os, name, guarded_os_pair_mutator(name))
    if original_os_symlink is not None:
        os.symlink = guarded_os_symlink
    for name in shutil_destination_mutator_names:
        setattr(shutil, name, guarded_shutil_destination_mutator(name))
    shutil.move = guarded_shutil_move
    shutil.rmtree = guarded_shutil_rmtree
    try:
        yield trace
    finally:
        shutil.rmtree = original_shutil_rmtree
        shutil.move = original_shutil_move
        for name, original in original_shutil_destination_mutators.items():
            setattr(shutil, name, original)
        if original_os_symlink is not None:
            os.symlink = original_os_symlink
        for name, original in original_os_pair_mutators.items():
            setattr(os, name, original)
        for name, original in original_os_single_mutators.items():
            setattr(os, name, original)
        Path.open = original_path_open
        Path.exists = original_exists
        for name, original in original_path_mutators.items():
            setattr(Path, name, original)
        builtins.open = original_builtin_open
        os.open = original_os_open


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
    seen_keys: set[tuple[str, str, int]] = set()
    for row in rows:
        target_date = record_date(row)
        year = int(target_date[:4])
        if int(start_year) <= year <= int(end_year):
            cell = (str(row.get("market_id")), int(row.get("cutoff_hour")))
            if cell not in required:
                continue
            key = (cell[0], target_date, cell[1])
            if key in seen_keys:
                raise ValueError(
                    "balanced panel contains duplicate market/date/hour key: "
                    f"{key}"
                )
            seen_keys.add(key)
            cells[target_date].append(cell)
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
        keys = [record_key(row) for row in output[split]]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{split} panel contains duplicate market/date/hour keys")
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
        before_identity = _file_identity(stat)
        captured_identity = trace.opened_identity.get(path)
        if captured_identity is not None and before_identity != captured_identity:
            raise RuntimeError(
                f"research input changed between corpus load and manifest hash: {path}"
            )
        digest = file_sha256(path)
        after = path.stat()
        after_identity = _file_identity(after)
        if before_identity != after_identity:
            raise RuntimeError(f"research input changed during manifest hash: {path}")
        rows.append({
            "path": relative,
            "status": "read" if path in trace.opened else "checked_present",
            "size_bytes": int(after.st_size),
            "mtime_utc": datetime.fromtimestamp(after.st_mtime, timezone.utc).isoformat(),
            "sha256": digest,
        })
    manifest = {
        "schema_version": "pool_city_input_manifest_v0.1",
        "data_root": str(data_root),
        "read_only_guard": True,
        "read_only_guard_contract": (
            "python_open_and_common_pathname_mutation_v0.2"
        ),
        "read_only_guard_scope": (
            "corpus-load Python APIs; raw pre-opened descriptors and direct "
            "native calls are outside scope and are unused by audited loaders"
        ),
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
    season_anchor_date: date,
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
            historical_window_target_date=season_anchor_date,
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
        native_keys = [record_key(row) for row in native[split]]
        canonical_keys = [record_key(row) for row in canonical[split]]
        if len(native_keys) != len(set(native_keys)):
            raise ValueError(f"{split} native panel contains duplicate keys")
        if len(canonical_keys) != len(set(canonical_keys)):
            raise ValueError(f"{split} canonical panel contains duplicate keys")
        if set(native_keys) != set(canonical_keys):
            raise ValueError(
                f"{split} native/canonical panel key sets differ"
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
        "season_anchor_date": season_anchor_date.isoformat(),
        "season_anchor_policy": (
            "explicit CLI-bound calendar anchor for the historical target-season window"
        ),
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


def _git_value(repo_root: Path, *arguments: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _closure_file_entry(path: Path, repo_root: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    if not _is_relative_to(resolved, repo_root):
        raise ValueError(f"execution closure file escapes repository: {path}")
    before = resolved.stat()
    before_identity = _file_identity(before)
    digest = file_sha256(resolved)
    after = resolved.stat()
    if before_identity != _file_identity(after):
        raise RuntimeError(f"execution closure file changed while hashing: {resolved}")
    return {
        "path": resolved.relative_to(repo_root).as_posix(),
        "sha256": digest,
        "size_bytes": int(after.st_size),
    }


def _repository_execution_files(repo_root: Path) -> list[Path]:
    """Return an over-complete deterministic repository code/config closure."""

    candidates: set[Path] = set()
    for root, suffixes in (
        (repo_root / "src" / "weather", {".py"}),
        (repo_root / "weather", {".py"}),
        (repo_root / "config", None),
    ):
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if suffixes is not None and path.suffix.lower() not in suffixes:
                continue
            if path.suffix.lower() in {".pyc", ".pyo"}:
                continue
            resolved = path.resolve(strict=True)
            if not _is_relative_to(resolved, repo_root):
                raise ValueError(f"execution closure path escapes repository: {path}")
            candidates.add(resolved)
    for name in (
        "pyproject.toml",
        "requirements.txt",
        "pytest.ini",
        "sitecustomize.py",
    ):
        path = repo_root / name
        if path.is_file():
            candidates.add(path.resolve(strict=True))
    return sorted(candidates, key=lambda path: path.relative_to(repo_root).as_posix())


def source_provenance(dependencies: Mapping[str, Any]) -> dict[str, Any]:
    """Seal the full repository code/config tree and execution environment."""

    own_file = Path(__file__).resolve()
    repo_root = own_file.parents[4]
    closure_paths = _repository_execution_files(repo_root)
    source_files = [
        _closure_file_entry(path, repo_root)
        for path in closure_paths
    ]
    verification_files = [
        _closure_file_entry(path, repo_root)
        for path in closure_paths
    ]
    if verification_files != source_files:
        raise RuntimeError(
            "repository execution closure changed during two-pass hashing"
        )
    dependency_modules = sorted({
        str(getattr(value, "__module__", ""))
        for value in dependencies.values()
        if callable(value) and getattr(value, "__module__", None)
    })
    git_status = _git_value(
        repo_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    )
    head_commit = _git_value(repo_root, "rev-parse", "HEAD")
    head_tree = _git_value(repo_root, "rev-parse", "HEAD^{tree}")
    if git_status is None or not head_commit or not head_tree:
        raise RuntimeError("cannot seal exact Git identity for benchmark execution")
    git_identity = {
        "head_commit": head_commit,
        "head_tree": head_tree,
        "tracked_worktree_status_sha256": hashlib.sha256(
            git_status.encode("utf-8")
        ).hexdigest(),
        "tracked_worktree_dirty": bool(git_status),
    }
    distributions = {}
    for distribution in ("numpy", "pandas", "scipy", "scikit-learn"):
        try:
            distributions[distribution] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            distributions[distribution] = None
    contract = {
        "contract_version": "pool_city_execution_source_closure_v0.2",
        "closure_policy": (
            "all src/weather and bootstrap Python; all repository config files; "
            "root build/runtime pins; callable owner modules; exact Git identity"
        ),
        "git_identity": git_identity,
        "source_files": source_files,
        "source_tree_sha256": payload_sha256(source_files),
        "dependency_callable_modules": dependency_modules,
        "runtime": {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "distributions": distributions,
            "platform": platform.platform(),
        },
    }
    return {
        **contract,
        "git_commit": git_identity["head_commit"],
        "source_contract_sha256": payload_sha256(contract),
    }


def verify_source_provenance_unchanged(
    initial: Mapping[str, Any],
    current: Mapping[str, Any],
) -> dict[str, Any]:
    """Fail before COMPLETE if code/config/Git/runtime changed during the run."""

    if not isinstance(initial, Mapping) or not isinstance(current, Mapping):
        raise RuntimeError("benchmark source closure verification is malformed")
    if dict(initial) != dict(current):
        changed = [
            key
            for key in sorted(set(initial) | set(current))
            if initial.get(key) != current.get(key)
        ]
        raise RuntimeError(
            "benchmark code/config/Git/runtime closure changed during execution: "
            + ", ".join(changed)
        )
    return {
        "status": "PASS",
        "verified_at_utc": utc_iso(),
        "source_contract_sha256": initial.get("source_contract_sha256"),
        "source_tree_sha256": initial.get("source_tree_sha256"),
        "git_identity": initial.get("git_identity"),
        "exact_initial_completion_match": True,
    }


def benchmark_run_id(
    *,
    corpus: Mapping[str, Any],
    contracts: Mapping[int, Mapping[str, Any]],
    grid_f: Sequence[float],
    configuration: Mapping[str, Any],
    sources: Mapping[str, Any],
    task_contracts: Mapping[str, Mapping[str, Any]],
) -> str:
    return payload_sha256({
        "corpus_contract_sha256": corpus["corpus_contract_sha256"],
        "input_manifest_sha256": corpus["input_manifest_sha256"],
        "feature_contracts": {str(hour): row["sha256"] for hour, row in sorted(contracts.items())},
        "grid_f": list(grid_f),
        "configuration": configuration,
        "source_contract_sha256": sources["source_contract_sha256"],
        "git_identity": sources["git_identity"],
        "task_contracts_sha256": payload_sha256(task_contracts),
    })


def _checkpoint_path(root: Path, task: Mapping[str, Any]) -> Path:
    return root / "models" / str(task["regime"]) / f"{task['task_id']}.json"


def _normalized_task(task: Mapping[str, Any]) -> dict[str, Any]:
    regime = str(task.get("regime") or "")
    if regime not in REGIMES:
        raise ValueError(f"invalid checkpoint task regime: {regime!r}")
    task_id = str(task.get("task_id") or "")
    if not task_id:
        raise ValueError("checkpoint task_id is empty")
    raw_hour = task.get("hour")
    if isinstance(raw_hour, bool) or not isinstance(raw_hour, (int, np.integer)):
        raise ValueError(f"invalid checkpoint task hour: {raw_hour!r}")
    hour = int(raw_hour)
    if hour < 0 or hour > 23:
        raise ValueError(f"invalid checkpoint task hour: {hour}")
    market_id = task.get("market_id")
    if regime == "pooled":
        if market_id is not None:
            raise ValueError("pooled checkpoint task must have market_id=None")
    else:
        market_id = str(market_id or "")
        if not market_id:
            raise ValueError(f"{regime} checkpoint task must name a market")
    expected_task_id = (
        f"pooled__all__h{hour:02d}"
        if regime == "pooled"
        else f"{regime}__{market_id}__h{hour:02d}"
    )
    if task_id != expected_task_id:
        raise ValueError(
            f"checkpoint task_id does not match task fields: "
            f"expected={expected_task_id}, actual={task_id}"
        )
    return {
        "task_id": task_id,
        "regime": regime,
        "market_id": market_id,
        "hour": hour,
    }


def _strict_prediction_key(row: Mapping[str, Any]) -> tuple[str, str, str, int]:
    if not isinstance(row, Mapping):
        raise ValueError("checkpoint scored_rows entries must be objects")
    raw_date = row.get("target_date")
    if not isinstance(raw_date, str):
        raise ValueError(f"malformed prediction target_date: {raw_date!r}")
    try:
        target_date = date.fromisoformat(raw_date).isoformat()
    except ValueError as exc:
        raise ValueError(f"malformed prediction target_date: {raw_date!r}") from exc
    if target_date != raw_date:
        raise ValueError(f"prediction target_date is not canonical ISO date: {raw_date!r}")
    market_id = row.get("market_id")
    if not isinstance(market_id, str) or not market_id:
        raise ValueError(f"malformed prediction market_id: {market_id!r}")
    raw_hour = row.get("cutoff_hour")
    if isinstance(raw_hour, bool) or not isinstance(raw_hour, int):
        raise ValueError(f"malformed prediction cutoff_hour: {raw_hour!r}")
    if raw_hour < 0 or raw_hour > 23:
        raise ValueError(f"malformed prediction cutoff_hour: {raw_hour!r}")
    split = row.get("split")
    if not isinstance(split, str) or split not in SPLITS:
        raise ValueError(f"checkpoint prediction split is invalid: {split!r}")
    return split, market_id, target_date, raw_hour


def _prediction_key_contract(
    keys: Iterable[tuple[str, str, str, int]],
) -> tuple[list[tuple[str, str, str, int]], str]:
    ordered = sorted(keys)
    if len(ordered) != len(set(ordered)):
        raise ValueError("expected task prediction keys contain duplicates")
    return ordered, payload_sha256([
        {
            "split": split,
            "market_id": market_id,
            "target_date": target_date,
            "cutoff_hour": hour,
        }
        for split, market_id, target_date, hour in ordered
    ])


def expected_task_prediction_keys(
    task: Mapping[str, Any],
    rows_by_split: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[tuple[str, str, str, int]]:
    normalized = _normalized_task(task)
    scopes = task_row_scopes(normalized, rows_by_split)
    keys = []
    for split in SPLITS:
        keys.extend(
            (
                split,
                str(row.get("market_id")),
                record_date(row),
                int(row.get("cutoff_hour")),
            )
            for row in scopes[split]
        )
    return _prediction_key_contract(keys)[0]


def expected_task_prediction_keys_from_corpus(
    task: Mapping[str, Any],
    corpus: Mapping[str, Any],
) -> list[tuple[str, str, str, int]]:
    normalized = _normalized_task(task)
    markets = [str(value) for value in (corpus.get("markets") or ())]
    if not markets or len(markets) != len(set(markets)):
        raise ValueError("corpus markets are empty or duplicated")
    target_markets = (
        markets if normalized["regime"] == "pooled"
        else [str(normalized["market_id"])]
    )
    if any(market not in markets for market in target_markets):
        raise ValueError(f"task market is absent from corpus: {normalized['market_id']}")
    split_dates = corpus.get("split_dates")
    if not isinstance(split_dates, Mapping):
        raise ValueError("corpus split_dates is missing")
    keys = []
    for split in SPLITS:
        dates = split_dates.get(split)
        if not isinstance(dates, list) or not dates:
            raise ValueError(f"corpus {split} dates are missing")
        canonical_dates = []
        for raw_date in dates:
            if not isinstance(raw_date, str):
                raise ValueError(f"corpus {split} contains a non-string date")
            parsed = date.fromisoformat(raw_date).isoformat()
            if parsed != raw_date:
                raise ValueError(f"corpus {split} date is not canonical: {raw_date!r}")
            canonical_dates.append(parsed)
        if len(canonical_dates) != len(set(canonical_dates)):
            raise ValueError(f"corpus {split} dates contain duplicates")
        for target_date in canonical_dates:
            for market_id in target_markets:
                keys.append((
                    split,
                    market_id,
                    target_date,
                    int(normalized["hour"]),
                ))
    return _prediction_key_contract(keys)[0]


def build_task_contract(
    task: Mapping[str, Any],
    *,
    feature_contract_sha256: str,
    expected_prediction_keys: Sequence[tuple[str, str, str, int]],
) -> dict[str, Any]:
    normalized = _normalized_task(task)
    ordered, prediction_digest = _prediction_key_contract(expected_prediction_keys)
    contract = {
        "contract_version": "pool_city_task_contract_v0.2",
        "task": normalized,
        "feature_contract_sha256": str(feature_contract_sha256),
        "expected_prediction_rows": len(ordered),
        "expected_prediction_keys_sha256": prediction_digest,
    }
    return {**contract, "task_contract_sha256": payload_sha256(contract)}


def build_checkpoint_run_contract(
    *,
    run_id: str,
    corpus: Mapping[str, Any],
    contracts: Mapping[int, Mapping[str, Any]],
    grid_f: Sequence[float],
    configuration: Mapping[str, Any],
    sources: Mapping[str, Any],
    task_contracts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    task_ids = list(task_contracts)
    contract = {
        "contract_version": "pool_city_checkpoint_run_contract_v0.2",
        "run_id": str(run_id),
        "corpus_contract_sha256": str(corpus["corpus_contract_sha256"]),
        "input_manifest_sha256": str(corpus["input_manifest_sha256"]),
        "native_corpus_sha256": corpus["native_corpus_sha256"],
        "canonical_corpus_sha256": corpus["canonical_corpus_sha256"],
        "feature_contracts": {
            str(hour): str(row["sha256"])
            for hour, row in sorted(contracts.items())
        },
        "grid_f_sha256": payload_sha256(list(grid_f)),
        "grid_points": len(grid_f),
        "configuration_sha256": payload_sha256(configuration),
        "source_contract_sha256": str(sources["source_contract_sha256"]),
        "source_tree_sha256": str(sources["source_tree_sha256"]),
        "git_identity": sources["git_identity"],
        "task_ids": task_ids,
        "task_contracts_sha256": payload_sha256(task_contracts),
    }
    return {**contract, "run_contract_sha256": payload_sha256(contract)}


def _validate_prediction_rows(
    rows: Any,
    *,
    task: Mapping[str, Any],
    expected_prediction_keys: Sequence[tuple[str, str, str, int]],
) -> None:
    if not isinstance(rows, list):
        raise ValueError("checkpoint scored_rows must be a list")
    normalized = _normalized_task(task)
    expected, expected_digest = _prediction_key_contract(expected_prediction_keys)
    actual = []
    for row in rows:
        key = _strict_prediction_key(row)
        actual.append(key)
        if row.get("task_id") != normalized["task_id"]:
            raise ValueError("checkpoint prediction task_id mismatch")
        if row.get("regime") != normalized["regime"]:
            raise ValueError("checkpoint prediction regime mismatch")
        expected_scored_market = (
            "all" if normalized["regime"] == "pooled"
            else normalized["market_id"]
        )
        if row.get("scored_market_id") != expected_scored_market:
            raise ValueError("checkpoint prediction scored_market_id mismatch")
        if key[3] != normalized["hour"]:
            raise ValueError("checkpoint prediction cutoff hour mismatches task")
        if row.get("unit") not in {"C", "F"}:
            raise ValueError(f"checkpoint prediction unit is invalid: {row.get('unit')!r}")
        for field in PREDICTION_NUMERIC_FIELDS:
            value = row.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"checkpoint prediction {field} is not numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"checkpoint prediction {field} is not finite")
        if not isinstance(row.get("market_band_rows"), int):
            raise ValueError("checkpoint prediction market_band_rows is not integral")
        if int(row["market_band_rows"]) <= 0 or float(row["market_band_weight"]) <= 0:
            raise ValueError("checkpoint prediction has no scored market bands")
        if not isinstance(row.get("density_shape_id"), str) or not row["density_shape_id"]:
            raise ValueError("checkpoint prediction density_shape_id is missing")
    actual_ordered, actual_digest = _prediction_key_contract(actual)
    if actual_ordered != expected or actual_digest != expected_digest:
        raise ValueError(
            "checkpoint prediction key set mismatch: "
            f"expected={len(expected)}, actual={len(actual_ordered)}"
        )


def validate_checkpoint_run_contract(run_contract: Mapping[str, Any]) -> None:
    if not isinstance(run_contract, Mapping):
        raise ValueError("checkpoint run contract is not an object")
    if run_contract.get("contract_version") != "pool_city_checkpoint_run_contract_v0.2":
        raise ValueError("checkpoint run contract version mismatch")
    claimed = run_contract.get("run_contract_sha256")
    require_sha256(claimed, label="checkpoint run contract self-digest")
    if claimed != self_digest(
        run_contract,
        digest_field="run_contract_sha256",
    ):
        raise ValueError("checkpoint run contract self-digest mismatch")
    require_sha256(run_contract.get("run_id"), label="checkpoint run_id")
    for field in (
        "corpus_contract_sha256",
        "input_manifest_sha256",
        "grid_f_sha256",
        "configuration_sha256",
        "source_contract_sha256",
        "source_tree_sha256",
        "task_contracts_sha256",
    ):
        require_sha256(
            run_contract.get(field),
            label=f"checkpoint run contract {field}",
        )
    for field in ("native_corpus_sha256", "canonical_corpus_sha256"):
        split_hashes = run_contract.get(field)
        if not isinstance(split_hashes, Mapping) or set(split_hashes) != {
            "train",
            *SPLITS,
        }:
            raise ValueError(f"checkpoint run contract {field} is malformed")
        for split, digest in split_hashes.items():
            require_sha256(
                digest,
                label=f"checkpoint run contract {field}.{split}",
            )
    feature_contracts = run_contract.get("feature_contracts")
    if not isinstance(feature_contracts, Mapping) or not feature_contracts:
        raise ValueError("checkpoint run feature contracts are missing")
    for hour, digest in feature_contracts.items():
        try:
            parsed_hour = int(hour)
        except (TypeError, ValueError) as exc:
            raise ValueError("checkpoint run feature contract hour is invalid") from exc
        if str(parsed_hour) != str(hour) or parsed_hour < 0 or parsed_hour > 23:
            raise ValueError("checkpoint run feature contract hour is invalid")
        require_sha256(
            digest,
            label=f"checkpoint run feature contract hour {hour}",
        )
    grid_points = run_contract.get("grid_points")
    if isinstance(grid_points, bool) or not isinstance(grid_points, int) or grid_points <= 0:
        raise ValueError("checkpoint run grid point count is invalid")
    git_identity = run_contract.get("git_identity")
    if not isinstance(git_identity, Mapping):
        raise ValueError("checkpoint run Git identity is missing")
    for field in ("head_commit", "head_tree"):
        value = git_identity.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"checkpoint run Git {field} is missing")
    require_sha256(
        git_identity.get("tracked_worktree_status_sha256"),
        label="checkpoint run Git worktree status digest",
    )
    if not isinstance(git_identity.get("tracked_worktree_dirty"), bool):
        raise ValueError("checkpoint run Git dirty marker is malformed")
    task_ids = run_contract.get("task_ids")
    if (
        not isinstance(task_ids, list)
        or any(not isinstance(value, str) or not value for value in task_ids)
        or len(task_ids) != len(set(task_ids))
    ):
        raise ValueError("checkpoint run contract task inventory is malformed")


def validate_task_contract(task_contract: Mapping[str, Any]) -> None:
    if not isinstance(task_contract, Mapping):
        raise ValueError("checkpoint task contract is not an object")
    if task_contract.get("contract_version") != "pool_city_task_contract_v0.2":
        raise ValueError("checkpoint task contract version mismatch")
    claimed = task_contract.get("task_contract_sha256")
    require_sha256(claimed, label="checkpoint task contract self-digest")
    if claimed != self_digest(
        task_contract,
        digest_field="task_contract_sha256",
    ):
        raise ValueError("checkpoint task contract self-digest mismatch")
    _normalized_task(task_contract.get("task") or {})
    require_sha256(
        task_contract.get("feature_contract_sha256"),
        label="checkpoint task feature contract",
    )
    require_sha256(
        task_contract.get("expected_prediction_keys_sha256"),
        label="checkpoint task prediction-key contract",
    )
    rows = task_contract.get("expected_prediction_rows")
    if isinstance(rows, bool) or not isinstance(rows, int) or rows <= 0:
        raise ValueError("checkpoint task contract prediction count is invalid")


def load_checkpoint(
    path: Path,
    *,
    run_contract: Mapping[str, Any],
    task_contract: Mapping[str, Any],
    expected_prediction_keys: Sequence[tuple[str, str, str, int]],
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    validate_checkpoint_run_contract(run_contract)
    validate_task_contract(task_contract)
    expected_ordered, expected_digest = _prediction_key_contract(
        expected_prediction_keys
    )
    if (
        task_contract.get("expected_prediction_rows") != len(expected_ordered)
        or task_contract.get("expected_prediction_keys_sha256") != expected_digest
    ):
        raise ValueError("checkpoint task contract prediction-key binding mismatch")
    payload = load_json_mapping_strict(path, label="checkpoint")
    if payload.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        raise ValueError(
            f"checkpoint schema mismatch: expected={CHECKPOINT_SCHEMA_VERSION}, "
            f"actual={payload.get('schema_version')}"
        )
    claimed_digest = payload.get(CHECKPOINT_DIGEST_FIELD)
    require_sha256(claimed_digest, label="checkpoint self-digest")
    if claimed_digest != self_digest(
        payload,
        digest_field=CHECKPOINT_DIGEST_FIELD,
    ):
        raise ValueError(f"checkpoint self-digest mismatch: {path}")
    expected_task = task_contract["task"]
    if (
        payload.get("run_id") != run_contract.get("run_id")
        or payload.get("run_contract_sha256") != run_contract.get("run_contract_sha256")
        or payload.get("task_id") != expected_task.get("task_id")
        or payload.get("task_contract_sha256") != task_contract.get("task_contract_sha256")
    ):
        raise ValueError(f"checkpoint identity mismatch: {path}")
    for field in ("regime", "market_id", "hour", "feature_contract_sha256"):
        expected = (
            task_contract.get("feature_contract_sha256")
            if field == "feature_contract_sha256"
            else expected_task.get(field)
        )
        if payload.get(field) != expected:
            raise ValueError(f"checkpoint {field} mismatch: {path}")
    _validate_prediction_rows(
        payload.get("scored_rows"),
        task=expected_task,
        expected_prediction_keys=expected_prediction_keys,
    )
    return payload


def load_authoritative_checkpoint_status(
    path: str | Path,
    *,
    run_contract: Mapping[str, Any],
    expected_task_ids: Sequence[str],
) -> dict[str, Any]:
    """Load and validate the task ledger that owns resume accounting."""

    status_path = Path(path)
    validate_checkpoint_run_contract(run_contract)
    status = load_json_mapping_strict(status_path, label="checkpoint status")
    if status.get("schema_version") != CHECKPOINT_STATUS_SCHEMA_VERSION:
        raise ValueError(
            f"checkpoint status schema mismatch: expected={CHECKPOINT_STATUS_SCHEMA_VERSION}, "
            f"actual={status.get('schema_version')}"
        )
    claimed_digest = status.get(CHECKPOINT_STATUS_DIGEST_FIELD)
    require_sha256(claimed_digest, label="checkpoint status self-digest")
    if claimed_digest != self_digest(
        status,
        digest_field=CHECKPOINT_STATUS_DIGEST_FIELD,
    ):
        raise ValueError(f"checkpoint status self-digest mismatch: {status_path}")
    run_id = str(run_contract.get("run_id") or "")
    if (
        status.get("run_id") != run_id
        or status.get("run_contract_sha256") != run_contract.get("run_contract_sha256")
    ):
        raise ValueError(
            "checkpoint status run identity mismatch: "
            f"expected={run_id}, actual={status.get('run_id')}"
        )
    expected_ids = [str(value) for value in expected_task_ids]
    if len(expected_ids) != len(set(expected_ids)):
        raise ValueError("expected checkpoint task inventory contains duplicates")
    recorded_ids = status.get("completed_task_ids")
    if not isinstance(recorded_ids, list) or any(
        not isinstance(value, str) for value in recorded_ids
    ):
        raise ValueError("checkpoint status completed_task_ids is malformed")
    if len(recorded_ids) != len(set(recorded_ids)):
        raise ValueError("checkpoint status completed_task_ids contains duplicates")
    if recorded_ids != expected_ids:
        raise ValueError("checkpoint status task inventory mismatch")
    checkpoint_digests = status.get("checkpoint_sha256_by_task")
    if (
        not isinstance(checkpoint_digests, Mapping)
        or set(checkpoint_digests) != set(expected_ids)
    ):
        raise ValueError("checkpoint status checkpoint digest inventory is malformed")
    for task_id, digest in checkpoint_digests.items():
        require_sha256(digest, label=f"checkpoint status digest for {task_id}")
    for field in ("completed_tasks", "total_tasks", "resumed_tasks"):
        value = status.get(field)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"checkpoint status {field} is malformed")
    completed = status["completed_tasks"]
    total = status["total_tasks"]
    resumed = status["resumed_tasks"]
    if completed != len(expected_ids) or total != len(expected_ids):
        raise ValueError(
            "checkpoint status is not complete: "
            f"completed={completed}, total={total}, expected={len(expected_ids)}"
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
    run_contract: Mapping[str, Any],
    task_contracts: Mapping[str, Mapping[str, Any]],
    status_path: Path,
) -> list[dict[str, Any]]:
    validate_checkpoint_run_contract(run_contract)
    normalized_tasks = [_normalized_task(task) for task in tasks]
    task_ids = [task["task_id"] for task in normalized_tasks]
    if task_ids != list(run_contract["task_ids"]):
        raise ValueError("execution task inventory does not match checkpoint run contract")
    if set(task_contracts) != set(task_ids):
        raise ValueError("execution task contracts do not match task inventory")
    results = []
    started = time.perf_counter()
    resumed = 0
    completed_task_ids = []
    checkpoint_digests: dict[str, str] = {}
    for index, task in enumerate(normalized_tasks, start=1):
        task_id = str(task["task_id"])
        task_contract = task_contracts[task_id]
        expected_keys = expected_task_prediction_keys(task, rows_by_split)
        checkpoint_path = _checkpoint_path(checkpoint_root, task)
        checkpoint = load_checkpoint(
            checkpoint_path,
            run_contract=run_contract,
            task_contract=task_contract,
            expected_prediction_keys=expected_keys,
        )
        if checkpoint is None:
            result = fit_task(
                task,
                rows_by_split=rows_by_split,
                feature_contract=contracts[int(task["hour"])],
                grid_f=grid_f,
                dependencies=dependencies,
            )
            checkpoint = {
                "schema_version": CHECKPOINT_SCHEMA_VERSION,
                "run_id": run_contract["run_id"],
                "run_contract_sha256": run_contract["run_contract_sha256"],
                "task_contract_sha256": task_contract["task_contract_sha256"],
                "completed_at_utc": utc_iso(),
                **result,
            }
            _validate_prediction_rows(
                checkpoint.get("scored_rows"),
                task=task,
                expected_prediction_keys=expected_keys,
            )
            checkpoint[CHECKPOINT_DIGEST_FIELD] = self_digest(
                checkpoint,
                digest_field=CHECKPOINT_DIGEST_FIELD,
            )
            write_json_atomic(checkpoint_path, checkpoint)
            checkpoint = load_checkpoint(
                checkpoint_path,
                run_contract=run_contract,
                task_contract=task_contract,
                expected_prediction_keys=expected_keys,
            )
            if checkpoint is None:
                raise ValueError(f"checkpoint disappeared after publication: {checkpoint_path}")
        else:
            resumed += 1
        results.append(checkpoint)
        completed_task_ids.append(task_id)
        checkpoint_digests[task_id] = str(checkpoint[CHECKPOINT_DIGEST_FIELD])
        status = {
            "schema_version": CHECKPOINT_STATUS_SCHEMA_VERSION,
            "run_id": run_contract["run_id"],
            "run_contract_sha256": run_contract["run_contract_sha256"],
            "updated_at_utc": utc_iso(),
            "completed_tasks": index,
            "total_tasks": len(tasks),
            "resumed_tasks": resumed,
            "completed_task_ids": list(completed_task_ids),
            "checkpoint_sha256_by_task": dict(checkpoint_digests),
            "last_task_id": task_id,
            "elapsed_seconds": time.perf_counter() - started,
        }
        status[CHECKPOINT_STATUS_DIGEST_FIELD] = self_digest(
            status,
            digest_field=CHECKPOINT_STATUS_DIGEST_FIELD,
        )
        write_json_atomic(status_path, status)
    authoritative_status = load_authoritative_checkpoint_status(
        status_path,
        run_contract=run_contract,
        expected_task_ids=task_ids,
    )
    validate_task_results(
        results,
        tasks=normalized_tasks,
        rows_by_split=rows_by_split,
        task_contracts=task_contracts,
        run_contract=run_contract,
        checkpoint_digests=authoritative_status["checkpoint_sha256_by_task"],
    )
    return results


def validate_exact_regime_panels(
    scored_rows: Sequence[Mapping[str, Any]],
) -> None:
    """Require one exact prediction panel shared by all geographic regimes."""

    if not scored_rows:
        raise ValueError("benchmark has no scored rows")
    seen: set[tuple[str, str, str, str, int]] = set()
    panels: dict[
        tuple[str, str],
        dict[tuple[str, str, int], tuple[str, float, int, float]],
    ] = {}
    for row in scored_rows:
        split, market_id, target_date, hour = _strict_prediction_key(row)
        regime = row.get("regime")
        if not isinstance(regime, str) or regime not in REGIMES:
            raise ValueError(f"prediction regime is invalid: {regime!r}")
        full_key = (split, regime, market_id, target_date, hour)
        if full_key in seen:
            raise ValueError(f"duplicate scored panel key: {full_key}")
        seen.add(full_key)
        unit = row.get("unit")
        if unit not in {"C", "F"}:
            raise ValueError(f"prediction unit is invalid: {unit!r}")
        try:
            immutable_score_contract = (
                str(unit),
                float(row["target_f"]),
                int(row["market_band_rows"]),
                float(row["market_band_weight"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("prediction outcome contract is malformed") from exc
        if not all(
            math.isfinite(value)
            for value in (
                immutable_score_contract[1],
                immutable_score_contract[3],
            )
        ):
            raise ValueError("prediction outcome contract is non-finite")
        panels.setdefault((split, regime), {})[
            (market_id, target_date, hour)
        ] = immutable_score_contract
    for split in SPLITS:
        regime_maps = {regime: panels.get((split, regime)) for regime in REGIMES}
        if any(value is None for value in regime_maps.values()):
            raise ValueError(f"{split} scored panel is missing a geographic regime")
        baseline = regime_maps["pooled"] or {}
        for regime in ("per_city", "loco"):
            candidate = regime_maps[regime] or {}
            if set(candidate) != set(baseline):
                raise ValueError(
                    f"{split} {regime}/pooled prediction key sets differ"
                )
            if candidate != baseline:
                raise ValueError(
                    f"{split} {regime}/pooled prediction outcome contracts differ"
                )


def validate_task_results(
    results: Sequence[Mapping[str, Any]],
    *,
    tasks: Sequence[Mapping[str, Any]],
    rows_by_split: Mapping[str, Sequence[Mapping[str, Any]]] | None,
    task_contracts: Mapping[str, Mapping[str, Any]],
    run_contract: Mapping[str, Any],
    checkpoint_digests: Mapping[str, str] | None = None,
    corpus: Mapping[str, Any] | None = None,
) -> None:
    validate_checkpoint_run_contract(run_contract)
    normalized_tasks = [_normalized_task(task) for task in tasks]
    expected_ids = [task["task_id"] for task in normalized_tasks]
    actual_ids = [str(result.get("task_id") or "") for result in results]
    if len(actual_ids) != len(set(actual_ids)):
        raise ValueError("completed task results contain duplicate task IDs")
    if actual_ids != expected_ids:
        raise ValueError("completed task result inventory or order is invalid")
    all_rows = []
    for task, result in zip(normalized_tasks, results):
        task_id = task["task_id"]
        task_contract = task_contracts.get(task_id)
        if task_contract is None:
            raise ValueError(f"task contract is missing for {task_id}")
        expected_keys = (
            expected_task_prediction_keys(task, rows_by_split)
            if rows_by_split is not None
            else expected_task_prediction_keys_from_corpus(task, corpus or {})
        )
        _validate_prediction_rows(
            result.get("scored_rows"),
            task=task,
            expected_prediction_keys=expected_keys,
        )
        if (
            result.get("run_id") != run_contract["run_id"]
            or result.get("run_contract_sha256") != run_contract["run_contract_sha256"]
            or result.get("task_contract_sha256") != task_contract["task_contract_sha256"]
        ):
            raise ValueError(f"completed task result contract mismatch: {task_id}")
        if checkpoint_digests is not None and (
            result.get(CHECKPOINT_DIGEST_FIELD) != checkpoint_digests.get(task_id)
        ):
            raise ValueError(f"checkpoint ledger digest mismatch: {task_id}")
        all_rows.extend(result["scored_rows"])
    validate_exact_regime_panels(all_rows)


def _aggregate_group(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = aggregate_source_scores(rows) or {}
    return {**metrics}


def aggregate_benchmark(scored_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    validate_exact_regime_panels(scored_rows)
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
    left_dates = set(left)
    right_dates = set(right)
    if left_dates != right_dates:
        raise ValueError(
            "paired comparison key sets differ: "
            f"left_only={len(left_dates - right_dates)}, "
            f"right_only={len(right_dates - left_dates)}"
        )
    dates = sorted(left_dates)
    deltas = []
    for value in dates:
        left_value = float(left[value])
        right_value = float(right[value])
        if not math.isfinite(left_value) or not math.isfinite(right_value):
            raise ValueError(f"paired comparison contains non-finite value for {value}")
        deltas.append(left_value - right_value)
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
    validate_exact_regime_panels(scored_rows)
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


def publish_benchmark_outputs(
    out_dir: Path,
    payload: Mapping[str, Any],
    *,
    scored_rows: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    """Publish dependent leaves first and the COMPLETE marker last."""

    artifact_path = out_dir / "pool_city_training_benchmark.json"
    report_path = out_dir / "pool_city_training_benchmark.md"
    if payload.get("status") == "COMPLETE":
        if scored_rows is None:
            raise ValueError("complete benchmark publication requires prediction rows")
        if artifact_path.exists():
            write_json_atomic(artifact_path, {
                "schema_version": SCHEMA_VERSION,
                "status": "FINALIZING",
                "research_only": True,
                "promotion_permission": "forbidden",
                "run_id": payload.get("run_id"),
                "serving_or_release_authorization": False,
            })
        write_csv_atomic(out_dir / "predictions.csv", scored_rows)
    write_text_atomic(report_path, render_report(payload))
    # This is the generation's only positive completion marker.
    write_json_atomic(artifact_path, payload)


def finalize_completed_checkpoint_run(
    *,
    data_root: str | Path,
    out_dir: str | Path,
) -> dict[str, Any]:
    """Regenerate aggregate artifacts from one already-complete checkpoint set."""

    out_dir = ensure_scratch_output(out_dir, data_root=data_root)
    artifact_path = out_dir / "pool_city_training_benchmark.json"
    payload = load_json_mapping_strict(
        artifact_path,
        label="completed benchmark artifact",
    )
    if payload.get("status") != "COMPLETE":
        raise ValueError(f"benchmark artifact is not complete: status={payload.get('status')}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"benchmark artifact schema mismatch: {payload.get('schema_version')}"
        )
    run_id = str(payload.get("run_id") or "")
    if not run_id:
        raise ValueError("completed benchmark artifact has no run_id")
    configuration = payload.get("configuration") or {}
    corpus = payload.get("corpus") or {}
    if (
        not isinstance(corpus, Mapping)
        or corpus.get("corpus_contract_sha256") != corpus_contract_sha256(corpus)
    ):
        raise ValueError("completed benchmark corpus contract self-digest mismatch")
    input_manifest = load_json_mapping_strict(
        out_dir / "input_manifest.json",
        label="pool/city input manifest",
    )
    if input_manifest.get("schema_version") != schema_version("pool_city_input_manifest"):
        raise ValueError("completed benchmark input manifest schema mismatch")
    if input_manifest.get("manifest_sha256") != self_digest(
        input_manifest,
        digest_field="manifest_sha256",
    ):
        raise ValueError("completed benchmark input manifest self-digest mismatch")
    try:
        manifest_data_root = Path(str(input_manifest.get("data_root"))).resolve(
            strict=False
        )
    except (OSError, RuntimeError) as exc:
        raise ValueError("completed benchmark input manifest data root is invalid") from exc
    if manifest_data_root != Path(data_root).resolve(strict=False):
        raise ValueError("completed benchmark input manifest data root mismatch")
    if (
        corpus.get("input_manifest_sha256") != input_manifest.get("manifest_sha256")
        or payload.get("input_manifest")
        != {key: value for key, value in input_manifest.items() if key != "files"}
    ):
        raise ValueError("completed benchmark input manifest binding mismatch")
    tasks = task_specs(corpus.get("markets") or (), configuration.get("hours") or ())
    if not tasks:
        raise ValueError("completed benchmark artifact has no task inventory")
    checkpoint_contract = payload.get("checkpoint_contract")
    if not isinstance(checkpoint_contract, Mapping):
        raise ValueError(
            "completed benchmark uses legacy unauthenticated checkpoints"
        )
    run_contract = checkpoint_contract.get("run_contract")
    embedded_task_contracts = checkpoint_contract.get("task_contracts")
    if not isinstance(run_contract, Mapping) or not isinstance(
        embedded_task_contracts,
        Mapping,
    ):
        raise ValueError(
            "completed benchmark checkpoint execution closure is missing"
        )
    validate_checkpoint_run_contract(run_contract)
    if run_contract.get("run_id") != run_id:
        raise ValueError("completed benchmark run contract run_id mismatch")

    dependencies = _dependencies()
    current_sources = source_provenance(dependencies)
    payload_sources = payload.get("source_provenance")
    if not isinstance(payload_sources, Mapping):
        raise ValueError("completed benchmark source provenance is missing")
    if (
        run_contract.get("source_contract_sha256")
        != payload_sources.get("source_contract_sha256")
        or run_contract.get("source_contract_sha256")
        != current_sources.get("source_contract_sha256")
        or run_contract.get("source_tree_sha256")
        != current_sources.get("source_tree_sha256")
        or run_contract.get("git_identity") != current_sources.get("git_identity")
    ):
        raise ValueError(
            "completed benchmark code/config/Git closure does not match current execution"
        )

    trainer_contract = payload.get("trainer_contract")
    if not isinstance(trainer_contract, Mapping):
        raise ValueError("completed benchmark trainer contract is missing")
    feature_rows = trainer_contract.get("feature_contracts")
    if not isinstance(feature_rows, Mapping):
        raise ValueError("completed benchmark feature contracts are missing")
    contracts: dict[int, dict[str, Any]] = {}
    for raw_hour in configuration.get("hours") or ():
        hour = int(raw_hour)
        row = feature_rows.get(str(hour))
        if not isinstance(row, Mapping) or not isinstance(row.get("sha256"), str):
            raise ValueError(f"feature contract is missing for hour {hour}")
        contracts[hour] = {"sha256": row["sha256"]}
    try:
        grid_f = dependencies["canonical_grid_f"](
            float(trainer_contract["grid_low_f"]),
            float(trainer_contract["grid_high_f"]),
            float(trainer_contract["grid_step_f"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("completed benchmark grid contract is malformed") from exc
    if len(grid_f) != int(trainer_contract.get("grid_points", -1)):
        raise ValueError("completed benchmark grid point count mismatch")

    recomputed_task_contracts = {}
    for task in tasks:
        expected_keys = expected_task_prediction_keys_from_corpus(task, corpus)
        task_contract = build_task_contract(
            task,
            feature_contract_sha256=contracts[int(task["hour"])]["sha256"],
            expected_prediction_keys=expected_keys,
        )
        task_id = str(task["task_id"])
        validate_task_contract(task_contract)
        if embedded_task_contracts.get(task_id) != task_contract:
            raise ValueError(f"completed benchmark task contract mismatch: {task_id}")
        recomputed_task_contracts[task_id] = task_contract
    contract_configuration = {
        key: value for key, value in configuration.items() if key != "mode"
    }
    recomputed_run_id = benchmark_run_id(
        corpus=corpus,
        contracts=contracts,
        grid_f=grid_f,
        configuration=contract_configuration,
        sources=current_sources,
        task_contracts=recomputed_task_contracts,
    )
    if recomputed_run_id != run_id:
        raise ValueError("completed benchmark run_id cannot be reproduced")
    recomputed_run_contract = build_checkpoint_run_contract(
        run_id=run_id,
        corpus=corpus,
        contracts=contracts,
        grid_f=grid_f,
        configuration=contract_configuration,
        sources=current_sources,
        task_contracts=recomputed_task_contracts,
    )
    if dict(run_contract) != recomputed_run_contract:
        raise ValueError("completed benchmark run contract cannot be reproduced")

    status_path = out_dir / "checkpoint_status.json"
    checkpoint_status = load_authoritative_checkpoint_status(
        status_path,
        run_contract=run_contract,
        expected_task_ids=[str(task["task_id"]) for task in tasks],
    )
    task_results = []
    for task in tasks:
        task_id = str(task["task_id"])
        checkpoint = load_checkpoint(
            _checkpoint_path(out_dir / "checkpoints", task),
            run_contract=run_contract,
            task_contract=recomputed_task_contracts[task_id],
            expected_prediction_keys=expected_task_prediction_keys_from_corpus(
                task,
                corpus,
            ),
        )
        if checkpoint is None:
            raise ValueError(f"missing completed checkpoint for {task['task_id']}")
        task_results.append(checkpoint)
    validate_task_results(
        task_results,
        tasks=tasks,
        rows_by_split=None,
        task_contracts=recomputed_task_contracts,
        run_contract=run_contract,
        checkpoint_digests=checkpoint_status["checkpoint_sha256_by_task"],
        corpus=corpus,
    )

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
    publish_benchmark_outputs(
        out_dir,
        corrected,
        scored_rows=scored_rows,
    )
    return corrected


def run_benchmark(
    *,
    data_root: str | Path,
    out_dir: str | Path,
    season_anchor_date: date | str | None = None,
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
    if str(mode) not in {"plan", "run", "finalize"}:
        raise ValueError("mode must be plan, run, or finalize")
    if mode in {"run", "finalize"} and not confirm_research_only:
        raise ValueError(f"{mode} execution requires confirm_research_only=True")
    if mode != "finalize":
        if season_anchor_date is None:
            raise ValueError(
                "plan/run requires an explicit season_anchor_date so the "
                "historical panel cannot move with wall-clock date"
            )
        try:
            season_anchor_date = (
                season_anchor_date.date()
                if isinstance(season_anchor_date, datetime)
                else season_anchor_date
                if isinstance(season_anchor_date, date)
                else date.fromisoformat(str(season_anchor_date))
            )
        except ValueError as exc:
            raise ValueError("season_anchor_date must be an ISO calendar date") from exc
        if season_anchor_date.year <= int(confirmation_year):
            raise ValueError(
                "season_anchor_date year must be later than confirmation_year"
            )
    out_dir = ensure_scratch_output(out_dir, data_root=data_root)
    if mode == "finalize":
        return finalize_completed_checkpoint_run(data_root=data_root, out_dir=out_dir)

    total_started = time.perf_counter()
    rows_by_split, corpus, loaded = load_corpus(
        data_root=data_root,
        season_anchor_date=season_anchor_date,
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
        "season_anchor_date": season_anchor_date.isoformat(),
        "grid_step_f": 0.1,
        "bootstrap_replicates": int(bootstrap_replicates),
        "bootstrap_seed": int(bootstrap_seed),
        "geographic_regimes": list(REGIMES),
        "development_use": "sigma_and_density_shape_selection_only",
        "confirmation_use": "scoring_only",
        "loco_contract": "held_out_market_excluded_from_training_and_development_tuning",
    }
    contract_configuration = {
        key: value for key, value in configuration.items() if key != "mode"
    }
    task_contracts = {}
    for task in tasks:
        expected_from_rows = expected_task_prediction_keys(task, rows_by_split)
        expected_from_corpus = expected_task_prediction_keys_from_corpus(task, corpus)
        if expected_from_rows != expected_from_corpus:
            raise ValueError(
                f"task prediction closure differs from corpus metadata: {task['task_id']}"
            )
        task_contracts[str(task["task_id"])] = build_task_contract(
            task,
            feature_contract_sha256=contracts[int(task["hour"])]["sha256"],
            expected_prediction_keys=expected_from_rows,
        )
    run_id = benchmark_run_id(
        corpus=corpus,
        contracts=contracts,
        grid_f=grid_f,
        configuration=contract_configuration,
        sources=sources,
        task_contracts=task_contracts,
    )
    run_contract = build_checkpoint_run_contract(
        run_id=run_id,
        corpus=corpus,
        contracts=contracts,
        grid_f=grid_f,
        configuration=contract_configuration,
        sources=sources,
        task_contracts=task_contracts,
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
        "checkpoint_contract": {
            "directory": str((out_dir / "checkpoints").resolve()),
            "task_count": len(tasks),
            "identity": (
                "self-digest + exact run/code/config/git/corpus/manifest/"
                "feature/grid/task/prediction-key contracts"
            ),
            "atomic": True,
            "run_contract": run_contract,
            "task_contracts": task_contracts,
        },
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
        publish_benchmark_outputs(out_dir, payload)
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
        publish_benchmark_outputs(out_dir, payload)
        return payload

    task_results = execute_tasks(
        tasks=tasks,
        rows_by_split=rows_by_split,
        contracts=contracts,
        grid_f=grid_f,
        dependencies=dependencies,
        checkpoint_root=out_dir / "checkpoints",
        run_contract=run_contract,
        task_contracts=task_contracts,
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
    completion_source_verification = verify_source_provenance_unchanged(
        sources,
        source_provenance(dependencies),
    )
    runtime.update({
        "completed_tasks": len(task_results),
        "actual_total_seconds": time.perf_counter() - total_started,
        "resumed_tasks": load_authoritative_checkpoint_status(
            out_dir / "checkpoint_status.json",
            run_contract=run_contract,
            expected_task_ids=[str(task["task_id"]) for task in tasks],
        )["resumed_tasks"],
        "resumed_tasks_source": "checkpoint_status.json",
        "completion_source_verification": completion_source_verification,
    })
    payload = {
        **base_payload,
        "status": "COMPLETE",
        "completed_at_utc": utc_iso(),
        "runtime": runtime,
        "results": results,
        "paired_evidence": comparisons,
    }
    publish_benchmark_outputs(
        out_dir,
        payload,
        scored_rows=scored_rows,
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
    parser.add_argument(
        "--season-anchor-date",
        help=(
            "Required for plan/run: explicit ISO date whose month/day anchors "
            "the historical target-season window."
        ),
    )
    parser.add_argument("--bootstrap-replicates", type=int, default=DEFAULT_BOOTSTRAP_REPLICATES)
    parser.add_argument("--bootstrap-seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    parser.add_argument("--max-runtime-hours", type=float, default=DEFAULT_MAX_RUNTIME_HOURS)
    parser.add_argument("--memory-budget-bytes", type=int, default=DEFAULT_MEMORY_BUDGET_BYTES)
    args = parser.parse_args()
    payload = run_benchmark(
        data_root=args.data_root,
        out_dir=args.out_dir,
        season_anchor_date=args.season_anchor_date,
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
