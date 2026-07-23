"""Implementation for the fail-closed H1 ordinal-smoothing research sweep.

This module is deliberately research-only.  It replays a pinned captured-input
corpus from explicitly supplied read-only roots, tunes on a predeclared fleet-
date set, and touches the holdout only after the tune-only selection is fixed.
It has no live-trading, serving-pointer, artifact-promotion, or artifact-write
surface.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import random
import sys
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("ordinal_smoothing_sweep")
SWEEP_WEIGHTS = (0.0, 0.10, 0.25, 0.50, 0.75, 1.0)
SMOOTHING_SIGMA = 0.75
UNIT_FAMILIES = ("C", "F")
DETERMINISM_CANARY_DATE = "2026-06-21"
BOOTSTRAP_SEED = 20260722
BOOTSTRAP_REPLICATES = 10_000
MASS_TOLERANCE = 1e-9
LOG_LOSS_EPSILON = 1e-15
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_CACHE_BYTES = 3 * 1024 * 1024 * 1024

# The raw replay-arm contract did not change in either bounded-memory
# refactor.  Caches written immediately before those orchestration/API-only
# changes therefore remain admissible when their full corpus/config
# fingerprint used one of these exact prior code digests.  This is an explicit,
# narrow allowlist rather than a general fingerprint bypass.
COMPATIBLE_ARM_CODE_DIGESTS = (
    "ab64174850ce76b428f647f2ff815df7a6210582549eaeb20aa347283c26cf33",
    "418fc2b3664e7427c4771d82d9da1f60daea6264169c308dcb6e0e7d24e48665",
)


class ExperimentConfigurationError(ValueError):
    """Raised before replay when the experiment contract is unsafe or unclear."""


def _resolved(path: str | Path, *, strict: bool) -> Path:
    return Path(path).expanduser().resolve(strict=strict)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_path_contract(
    *,
    mirror_data_root: str | Path,
    staged_data_root: str | Path,
    snapshots_root: str | Path,
    corpus_path: str | Path,
    tune_dates_path: str | Path,
    holdout_dates_path: str | Path,
    json_out: str | Path,
    report_out: str | Path,
    cache_root: str | Path,
    lock_path: str | Path,
) -> dict[str, Path]:
    """Resolve and validate all read and write locations before any mutation."""
    paths = {
        "mirror_data_root": _resolved(mirror_data_root, strict=True),
        "staged_data_root": _resolved(staged_data_root, strict=True),
        "snapshots_root": _resolved(snapshots_root, strict=True),
        "corpus_path": _resolved(corpus_path, strict=True),
        "tune_dates_path": _resolved(tune_dates_path, strict=True),
        "holdout_dates_path": _resolved(holdout_dates_path, strict=True),
        "json_out": _resolved(json_out, strict=False),
        "report_out": _resolved(report_out, strict=False),
        "cache_root": _resolved(cache_root, strict=False),
        "lock_path": _resolved(lock_path, strict=False),
    }
    for key in ("mirror_data_root", "staged_data_root", "snapshots_root"):
        if not paths[key].is_dir():
            raise ExperimentConfigurationError(f"{key} is not a directory: {paths[key]}")
    for key in ("corpus_path", "tune_dates_path", "holdout_dates_path"):
        if not paths[key].is_file():
            raise ExperimentConfigurationError(f"{key} is not a file: {paths[key]}")

    mirror_root = paths["mirror_data_root"]
    if not _is_within(paths["snapshots_root"], mirror_root):
        raise ExperimentConfigurationError("snapshots_root must resolve inside mirror_data_root")
    if not _is_within(paths["corpus_path"], mirror_root):
        raise ExperimentConfigurationError("corpus_path must resolve inside mirror_data_root")

    input_roots = (mirror_root, paths["staged_data_root"])
    output_keys = ("json_out", "report_out", "cache_root", "lock_path")
    for key in output_keys:
        for input_root in input_roots:
            if _is_within(paths[key], input_root):
                raise ExperimentConfigurationError(
                    f"{key} must be outside every input data root: {paths[key]} is under {input_root}"
                )
    if len({paths[key] for key in output_keys}) != len(output_keys):
        raise ExperimentConfigurationError("JSON, report, cache, and lock paths must be distinct")
    for key in ("json_out", "report_out", "lock_path"):
        if paths[key].exists() and paths[key].is_dir():
            raise ExperimentConfigurationError(f"{key} must be a file path, not a directory")
    if paths["cache_root"].exists() and not paths["cache_root"].is_dir():
        raise ExperimentConfigurationError("cache_root must be a directory path")
    for config_key in ("tune_dates_path", "holdout_dates_path"):
        if paths[config_key] in {paths[key] for key in output_keys}:
            raise ExperimentConfigurationError(f"an output path aliases {config_key}")

    # Probe explicit file inputs using read-only handles.  Replay opens the
    # pinned tape/replay-input files read-only as well.
    for key in ("corpus_path", "tune_dates_path", "holdout_dates_path"):
        with paths[key].open("rb") as handle:
            handle.read(1)
    return paths


def read_predeclared_dates(path: str | Path) -> tuple[str, ...]:
    """Read one ISO fleet date per line; blank lines and ``#`` comments are allowed."""
    values: list[str] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            value = raw.split("#", 1)[0].strip()
            if not value:
                continue
            try:
                parsed = date.fromisoformat(value)
            except ValueError as exc:
                raise ExperimentConfigurationError(
                    f"invalid ISO date in {path} at line {line_number}: {value!r}"
                ) from exc
            canonical = parsed.isoformat()
            if canonical in values:
                raise ExperimentConfigurationError(f"duplicate date in {path}: {canonical}")
            values.append(canonical)
    if not values:
        raise ExperimentConfigurationError(f"date manifest is empty: {path}")
    if values != sorted(values):
        raise ExperimentConfigurationError(f"date manifest must be sorted ascending: {path}")
    return tuple(values)


def partition_manifest_entries(
    manifest: Mapping[str, Any],
    tune_dates: Iterable[str],
    holdout_dates: Iterable[str],
) -> dict[str, list[dict[str, Any]]]:
    """Require the predeclared tune/holdout sets to exactly partition the corpus."""
    tune = set(tune_dates)
    holdout = set(holdout_dates)
    overlap = sorted(tune & holdout)
    if overlap:
        raise ExperimentConfigurationError(
            "tune and holdout fleet-date sets overlap: " + ", ".join(overlap)
        )
    entries = [dict(entry) for entry in manifest.get("entries") or []]
    if not entries:
        raise ExperimentConfigurationError("promotion corpus has no entries")
    slugs = [str(entry.get("event_slug") or "") for entry in entries]
    if any(not slug for slug in slugs) or len(slugs) != len(set(slugs)):
        raise ExperimentConfigurationError("promotion corpus event slugs must be present and unique")
    corpus_dates = {str(entry.get("target_date") or "") for entry in entries}
    if "" in corpus_dates:
        raise ExperimentConfigurationError("every promotion corpus entry must declare target_date")
    declared = tune | holdout
    if corpus_dates != declared:
        missing = sorted(corpus_dates - declared)
        extra = sorted(declared - corpus_dates)
        details = []
        if missing:
            details.append("unassigned corpus dates=" + ",".join(missing))
        if extra:
            details.append("declared dates absent from corpus=" + ",".join(extra))
        raise ExperimentConfigurationError(
            "date manifests must exactly partition the pinned corpus (" + "; ".join(details) + ")"
        )
    partitions = {
        "tune": [entry for entry in entries if entry["target_date"] in tune],
        "holdout": [entry for entry in entries if entry["target_date"] in holdout],
    }
    if not partitions["tune"] or not partitions["holdout"]:
        raise ExperimentConfigurationError("both tune and holdout partitions need corpus entries")
    return partitions


def folders_for_entries(entries: Iterable[Mapping[str, Any]], snapshots_root: Path) -> list[Path]:
    """Resolve folders only by pinned slug under the explicit mirror snapshot root."""
    folders = []
    for entry in entries:
        slug = str(entry.get("event_slug") or "")
        folder = (snapshots_root / slug).resolve(strict=True)
        if not _is_within(folder, snapshots_root):
            raise ExperimentConfigurationError(f"corpus folder escapes snapshots_root: {slug}")
        if not folder.is_dir():
            raise ExperimentConfigurationError(f"corpus folder is not a directory: {folder}")
        for filename in ("snapshots_long.csv", "replay_inputs.jsonl"):
            input_path = folder / filename
            if not input_path.is_file():
                raise ExperimentConfigurationError(f"missing pinned replay input: {input_path}")
            with input_path.open("rb") as handle:
                handle.read(1)
        folders.append(folder)
    return folders


def _daily_summary_path(staged_data_root: Path, market_id: str) -> Path:
    from weather.market.market_registry import spec_for_id

    spec = spec_for_id(market_id)
    return staged_data_root / "wunderground" / spec.icao.lower() / "daily" / "daily_summary.csv"


def validate_staged_daily_inputs(
    entries: Iterable[Mapping[str, Any]], staged_data_root: Path
) -> dict[str, Path]:
    market_ids = sorted({str(entry.get("market_id") or "") for entry in entries})
    if any(not market_id for market_id in market_ids):
        raise ExperimentConfigurationError("every corpus entry must declare market_id")
    paths = {}
    for market_id in market_ids:
        summary_path = _daily_summary_path(staged_data_root, market_id).resolve(strict=True)
        if not _is_within(summary_path, staged_data_root):
            raise ExperimentConfigurationError(
                f"daily summary escapes staged_data_root for {market_id}: {summary_path}"
            )
        if not summary_path.is_file():
            raise ExperimentConfigurationError(f"missing staged daily summary: {summary_path}")
        with summary_path.open("rb") as handle:
            handle.read(1)
        hourly_root = summary_path.parents[1] / "hourly"
        hourly_sample = next(
            hourly_root.glob("year=*/month=*/observations.jsonl"),
            None,
        )
        if hourly_sample is None or not hourly_sample.is_file():
            raise ExperimentConfigurationError(
                "staged model inputs are incomplete for "
                f"{market_id}: historical_target_cache also requires "
                f"{hourly_root / 'year=*/month=*/observations.jsonl'}"
            )
        with hourly_sample.open("rb") as handle:
            handle.read(1)
        paths[market_id] = summary_path
    return paths


def _configure_staged_data_root(staged_data_root: Path) -> None:
    """Point process-local read paths at staged inputs before lazy model imports."""
    import weather.paths as weather_paths

    weather_paths.DATA_ROOT = staged_data_root
    from weather.model.toronto_model import TorontoHighTempModel

    TorontoHighTempModel._historical_target_cache.clear()


def ordinal_smoothing_config(weight: float, cutoff_hour: Any) -> dict[str, Any]:
    """Return the fixed H1 arm config for one effective printed cutoff."""
    if weight not in SWEEP_WEIGHTS:
        raise ExperimentConfigurationError(f"weight is outside the fixed H1 grid: {weight}")
    # The effective printed cutoff can already be 7 during local predawn
    # hours.  Historical H1 semantics smooth whenever the feature path is
    # present; local-time scope is measured from replay outputs, not imposed
    # here as a second model variable.
    del cutoff_hour
    enabled = bool(weight > 0.0)
    return {
        "enabled": enabled,
        "sigma": SMOOTHING_SIGMA if enabled else 0.0,
        "blend_weight": float(weight) if enabled else 0.0,
        "source": "research_h1_fixed_sweep",
    }


def make_ordinal_model_factory(weight: float) -> Callable[[str], Any]:
    """Build an arm-specific model; blend weight is the sole swept variable."""
    # Validate before importing/constructing the model so an invalid arm fails
    # without touching model data or artifacts.
    ordinal_smoothing_config(weight, 0)
    from weather.model.toronto_model import TorontoHighTempModel

    class ResearchOrdinalSmoothingModel(TorontoHighTempModel):
        def feature_ordinal_smoothing_config(self, cutoff_hour):
            return ordinal_smoothing_config(weight, cutoff_hour)

    return lambda market_id: ResearchOrdinalSmoothingModel(market_id=market_id)


def _unit_for_market(market_id: str) -> str:
    from weather.market.market_registry import spec_for_id

    return str(spec_for_id(market_id).display_unit).upper()


def run_arm(
    *,
    split: str,
    weight: float,
    folders: Iterable[Path],
    manifest: Mapping[str, Any],
    staged_data_root: Path,
    cache_root: Path,
) -> dict[str, Any]:
    """Run one captured-input arm without writing through replay_backtest itself."""
    from weather.backtesting.replay_backtest import run_replay_backtest

    results = run_replay_backtest(
        [str(folder) for folder in folders],
        daily_summary_path=None,
        overrides={},
        out_path=str(cache_root / f"unused-{split}-{weight}.md"),
        include_reconstructed=False,
        write=False,
        corpus_manifest=manifest,
        model_factory=make_ordinal_model_factory(weight),
        daily_summary_resolver=lambda market_id: _daily_summary_path(
            staged_data_root, market_id
        ),
        include_distribution_rows=True,
    )
    rows = []
    for source in results.get("all_rows") or []:
        row = dict(source)
        row["unit"] = _unit_for_market(str(row.get("market_id") or ""))
        rows.append(row)
    distributions = []
    for source in results.get("distribution_rows") or []:
        row = dict(source)
        row["unit"] = _unit_for_market(str(row.get("market_id") or ""))
        distributions.append(row)

    replay_blockers = []
    if not results.get("snaps_scored"):
        replay_blockers.append("no snapshots scored")
    if results.get("snaps_scored") != results.get("snaps_in_corpus"):
        replay_blockers.append(
            "not every admitted snapshot produced a replay distribution "
            f"({results.get('snaps_scored')}/{results.get('snaps_in_corpus')})"
        )
    if results.get("corpus_warnings"):
        replay_blockers.extend(
            f"corpus warning: {warning}" for warning in results["corpus_warnings"]
        )
    fidelity = results.get("fidelity") or {}
    if fidelity.get("same_identity_n") and not fidelity.get("same_identity_faithful"):
        replay_blockers.append("same-identity replay fidelity canary failed")
    return {
        "split": split,
        "weight": float(weight),
        "sigma": SMOOTHING_SIGMA,
        "rows": rows,
        "distribution_rows": distributions,
        "replay": {
            "snaps_in_corpus": results.get("snaps_in_corpus"),
            "snaps_scored": results.get("snaps_scored"),
            "total_rows": results.get("total_rows"),
            "replayed_versions": results.get("replayed_versions") or [],
            "fidelity": fidelity,
            "band_semantics": results.get("band_semantics") or {},
            "corpus_warnings": results.get("corpus_warnings") or [],
            "blockers": replay_blockers,
        },
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _code_digest() -> str:
    from weather.backtesting import replay_backtest
    from weather.model import model_distribution, model_features, toronto_model

    digest = hashlib.sha256()
    for path in sorted(
        {
            Path(__file__).resolve(),
            Path(replay_backtest.__file__).resolve(),
            Path(model_distribution.__file__).resolve(),
            Path(model_features.__file__).resolve(),
            Path(toronto_model.__file__).resolve(),
        }
    ):
        digest.update(str(path.name).encode("utf-8"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def cache_fingerprint(
    *,
    split: str,
    weight: float,
    manifest: Mapping[str, Any],
    entries: Iterable[Mapping[str, Any]],
    code_digest: str,
) -> str:
    contract = {
        "schema_version": SCHEMA_VERSION,
        "split": split,
        "weight": float(weight),
        "sigma": SMOOTHING_SIGMA,
        "corpus_hash": manifest.get("corpus_hash"),
        "entries": [
            {
                "event_slug": entry.get("event_slug"),
                "target_date": entry.get("target_date"),
                "market_id": entry.get("market_id"),
                "snapshot_ids": entry.get("snapshot_ids") or [],
            }
            for entry in entries
        ],
        "code_digest": code_digest,
    }
    return hashlib.sha256(_canonical_json(contract).encode("utf-8")).hexdigest()


def _weight_token(weight: float) -> str:
    return f"{weight:.2f}".replace(".", "p")


def _atomic_write_json(
    path: Path, payload: Mapping[str, Any], *, compact: bool = False
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        if compact:
            json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
        else:
            json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def load_or_run_arm(
    *,
    split: str,
    weight: float,
    entries: list[dict[str, Any]],
    folders: list[Path],
    manifest: Mapping[str, Any],
    staged_data_root: Path,
    cache_root: Path,
    code_digest: str,
    resume: bool,
) -> dict[str, Any]:
    cache_path = cache_root / f"{split}-weight-{_weight_token(weight)}.json"
    fingerprint = cache_fingerprint(
        split=split,
        weight=weight,
        manifest=manifest,
        entries=entries,
        code_digest=code_digest,
    )
    compatible_fingerprints = {
        cache_fingerprint(
            split=split,
            weight=weight,
            manifest=manifest,
            entries=entries,
            code_digest=compatible_digest,
        )
        for compatible_digest in COMPATIBLE_ARM_CODE_DIGESTS
    }
    compatible_fingerprints.add(fingerprint)
    if cache_path.exists():
        if not resume:
            raise ExperimentConfigurationError(
                f"cache already exists (use --resume only after reviewing its provenance): {cache_path}"
            )
        if cache_path.stat().st_size > MAX_CACHE_BYTES:
            raise ExperimentConfigurationError(f"cache exceeds safety limit: {cache_path}")
        with cache_path.open("r", encoding="utf-8") as handle:
            envelope = json.load(handle)
        if envelope.get("fingerprint") not in compatible_fingerprints:
            raise ExperimentConfigurationError(f"cache fingerprint mismatch: {cache_path}")
        return dict(envelope.get("arm") or {})
    arm = run_arm(
        split=split,
        weight=weight,
        folders=folders,
        manifest=manifest,
        staged_data_root=staged_data_root,
        cache_root=cache_root,
    )
    _atomic_write_json(
        cache_path,
        {
            "schema_version": SCHEMA_VERSION,
            "fingerprint": fingerprint,
            "arm": arm,
        },
        compact=True,
    )
    return arm


def _row_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("market_id"),
        row.get("target_date"),
        row.get("snapshot_id"),
        row.get("captured_at_local"),
        row.get("band"),
        row.get("bin_type"),
        row.get("bin_value_c"),
        row.get("bin_value_hi"),
    )


def _distribution_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("market_id"),
        row.get("target_date"),
        row.get("snapshot_id"),
        row.get("captured_at_local"),
    )


def _canonical_equal(left: Any, right: Any) -> bool:
    """Compare cached JSON values deterministically, including independent NaNs."""

    return _canonical_json(left) == _canonical_json(right)


def _scoring_rows_equivalent(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> bool:
    """Return whether a duplicate key is identical for every H1 score input."""

    fields = ("replayed_p", "outcome", "market_yes", "unit")
    return _canonical_equal(
        {field: left.get(field) for field in fields},
        {field: right.get(field) for field in fields},
    )


def _unique_index(
    rows: Iterable[Mapping[str, Any]],
    key_fn: Callable[[Mapping[str, Any]], tuple[Any, ...]],
    *,
    duplicate_equivalent: Callable[
        [Mapping[str, Any], Mapping[str, Any]], bool
    ]
    | None = None,
) -> tuple[dict[tuple[Any, ...], Mapping[str, Any]], list[str]]:
    index = {}
    blockers = []
    for row in rows:
        key = key_fn(row)
        if key in index:
            if duplicate_equivalent is None or not duplicate_equivalent(
                index[key], row
            ):
                blockers.append(f"conflicting duplicate comparison key: {key!r}")
            # Keep the first occurrence.  Snapshot-id collisions are admitted
            # only when their complete H1 scoring projection is equivalent, so
            # either occurrence produces the same paired score.
            continue
        index[key] = row
    return index, blockers


def alignment_gate(
    baseline_rows: Iterable[Mapping[str, Any]], candidate_rows: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    baseline, blockers = _unique_index(
        baseline_rows,
        _row_key,
        duplicate_equivalent=_scoring_rows_equivalent,
    )
    candidate, candidate_blockers = _unique_index(
        candidate_rows,
        _row_key,
        duplicate_equivalent=_scoring_rows_equivalent,
    )
    blockers.extend(candidate_blockers)
    missing = sorted(set(baseline) - set(candidate), key=str)
    extra = sorted(set(candidate) - set(baseline), key=str)
    if missing:
        blockers.append(f"candidate is missing {len(missing)} baseline scoring rows")
    if extra:
        blockers.append(f"candidate has {len(extra)} extra scoring rows")
    mismatched_labels = 0
    for key in set(baseline) & set(candidate):
        left = baseline[key]
        right = candidate[key]
        if (
            left.get("outcome") != right.get("outcome")
            or left.get("market_yes") != right.get("market_yes")
            or left.get("unit") != right.get("unit")
        ):
            mismatched_labels += 1
    if mismatched_labels:
        blockers.append(f"{mismatched_labels} paired rows changed label, market, or unit")
    return {
        "status": "PASS" if not blockers else "BLOCK",
        "baseline_rows": len(baseline),
        "candidate_rows": len(candidate),
        "mismatched_labels": mismatched_labels,
        "blockers": blockers,
    }


def scope_effect_audit(
    baseline_rows: Iterable[Mapping[str, Any]], candidate_rows: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Measure exact and L1 distribution effects in fixed local-hour windows."""
    baseline, blockers = _unique_index(baseline_rows, _distribution_key)
    candidate, candidate_blockers = _unique_index(candidate_rows, _distribution_key)
    blockers.extend(candidate_blockers)
    missing = set(baseline) - set(candidate)
    extra = set(candidate) - set(baseline)
    if missing:
        blockers.append(f"candidate is missing {len(missing)} full distributions")
    if extra:
        blockers.append(f"candidate has {len(extra)} extra full distributions")

    windows = {
        "00-06": range(0, 7),
        "07-20": range(7, 21),
        "21-23": range(21, 24),
    }
    effects = {
        label: {
            "distributions": 0,
            "changed_exact": 0,
            "unchanged_exact": 0,
            "mean_l1": None,
            "maximum_l1": None,
        }
        for label in windows
    }
    l1_values = {label: [] for label in windows}
    unknown_hours = 0
    for key in set(baseline) & set(candidate):
        row = baseline[key]
        try:
            hour = int(row.get("cutoff_hour"))
        except (TypeError, ValueError):
            unknown_hours += 1
            continue
        label = next(
            (name for name, hours in windows.items() if hour in hours),
            None,
        )
        if label is None:
            unknown_hours += 1
            continue
        left = {str(bucket): float(value) for bucket, value in (row.get("distribution") or {}).items()}
        right = {
            str(bucket): float(value)
            for bucket, value in (candidate[key].get("distribution") or {}).items()
        }
        bucket_keys = set(left) | set(right)
        l1 = sum(abs(left.get(bucket, 0.0) - right.get(bucket, 0.0)) for bucket in bucket_keys)
        effects[label]["distributions"] += 1
        changed = left != right
        effects[label]["changed_exact" if changed else "unchanged_exact"] += 1
        l1_values[label].append(l1)
    if unknown_hours:
        blockers.append(f"{unknown_hours} distributions lack a classifiable local hour")
    for label, values in l1_values.items():
        effects[label]["mean_l1"] = _mean(values)
        effects[label]["maximum_l1"] = max(values) if values else None
    return {
        "status": "PASS" if not blockers else "BLOCK",
        "distributions_compared": len(set(baseline) & set(candidate)),
        "missing": len(missing),
        "extra": len(extra),
        "unknown_local_hours": unknown_hours,
        "windows": effects,
        "blockers": blockers,
    }


def exact_determinism_gate(
    baseline_arm: Mapping[str, Any], control_arm: Mapping[str, Any]
) -> dict[str, Any]:
    """Require byte-equivalent probabilities on an independent weight-0 canary replay."""
    control_dates = {
        str(row.get("target_date"))
        for row in (control_arm.get("distribution_rows") or [])
    }
    baseline_rows = [
        row for row in (baseline_arm.get("rows") or [])
        if str(row.get("target_date")) in control_dates
    ]
    baseline_distributions = [
        row for row in (baseline_arm.get("distribution_rows") or [])
        if str(row.get("target_date")) in control_dates
    ]
    control_rows = list(control_arm.get("rows") or [])
    control_distributions = list(control_arm.get("distribution_rows") or [])

    baseline_row_index, blockers = _unique_index(
        baseline_rows,
        _row_key,
        duplicate_equivalent=_scoring_rows_equivalent,
    )
    control_row_index, control_blockers = _unique_index(
        control_rows,
        _row_key,
        duplicate_equivalent=_scoring_rows_equivalent,
    )
    blockers.extend(control_blockers)
    baseline_distribution_index, distribution_blockers = _unique_index(
        baseline_distributions, _distribution_key
    )
    blockers.extend(distribution_blockers)
    control_distribution_index, control_distribution_blockers = _unique_index(
        control_distributions, _distribution_key
    )
    blockers.extend(control_distribution_blockers)

    row_keys_match = set(baseline_row_index) == set(control_row_index)
    distribution_keys_match = (
        set(baseline_distribution_index) == set(control_distribution_index)
    )
    row_mismatches = sum(
        not _canonical_equal(baseline_row_index[key], control_row_index[key])
        for key in set(baseline_row_index) & set(control_row_index)
    )
    distribution_mismatches = sum(
        not _canonical_equal(
            baseline_distribution_index[key], control_distribution_index[key]
        )
        for key in set(baseline_distribution_index) & set(control_distribution_index)
    )
    if not control_dates:
        blockers.append("weight-0 determinism canary has no distributions")
    if not row_keys_match:
        blockers.append("weight-0 determinism scoring-row keys differ")
    if not distribution_keys_match:
        blockers.append("weight-0 determinism distribution keys differ")
    if row_mismatches:
        blockers.append(f"{row_mismatches} weight-0 scoring rows differ exactly")
    if distribution_mismatches:
        blockers.append(
            f"{distribution_mismatches} weight-0 full distributions differ exactly"
        )

    def content_hash(rows):
        ordered = [dict(rows[key]) for key in sorted(rows, key=str)]
        return hashlib.sha256(_canonical_json(ordered).encode("utf-8")).hexdigest()

    return {
        "status": "PASS" if not blockers else "BLOCK",
        "dates": sorted(control_dates),
        "markets": sorted(
            {str(row.get("market_id")) for row in control_distributions}
        ),
        "scoring_rows": len(control_row_index),
        "distributions": len(control_distribution_index),
        "row_mismatches": row_mismatches,
        "distribution_mismatches": distribution_mismatches,
        "baseline_row_hash": content_hash(baseline_row_index),
        "control_row_hash": content_hash(control_row_index),
        "baseline_distribution_hash": content_hash(baseline_distribution_index),
        "control_distribution_hash": content_hash(control_distribution_index),
        "blockers": blockers,
    }


def mass_gate(distribution_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(distribution_rows)
    violations = []
    maximum_error = 0.0
    for row in rows:
        values = list((row.get("distribution") or {}).values())
        valid = bool(values)
        probabilities = []
        for value in values:
            try:
                probability = float(value)
            except (TypeError, ValueError):
                valid = False
                continue
            if not math.isfinite(probability) or probability < 0.0 or probability > 1.0:
                valid = False
            probabilities.append(probability)
        total = sum(probabilities)
        error = abs(total - 1.0)
        maximum_error = max(maximum_error, error)
        if not valid or error > MASS_TOLERANCE:
            violations.append(
                {
                    "key": list(_distribution_key(row)),
                    "mass": total,
                    "error": error,
                    "valid_probabilities": valid,
                }
            )
    blockers = []
    if not rows:
        blockers.append("no full distributions are available for the simplex gate")
    if violations:
        blockers.append(f"{len(violations)} distributions violate probability/simplex constraints")
    return {
        "status": "PASS" if not blockers else "BLOCK",
        "distributions": len(rows),
        "violations": len(violations),
        "maximum_mass_error": maximum_error,
        "examples": violations[:10],
        "blockers": blockers,
    }


def _brier(probability: float, outcome: int) -> float:
    return (float(probability) - int(outcome)) ** 2


def _log_loss(probability: float, outcome: int) -> float:
    probability = max(LOG_LOSS_EPSILON, min(1.0 - LOG_LOSS_EPSILON, float(probability)))
    return -(
        int(outcome) * math.log(probability)
        + (1 - int(outcome)) * math.log(1.0 - probability)
    )


def paired_fleet_date_rows(
    baseline_rows: Iterable[Mapping[str, Any]],
    candidate_rows: Iterable[Mapping[str, Any]],
    unit: str,
) -> list[dict[str, Any]]:
    baseline, _ = _unique_index(
        baseline_rows,
        _row_key,
        duplicate_equivalent=_scoring_rows_equivalent,
    )
    candidate, _ = _unique_index(
        candidate_rows,
        _row_key,
        duplicate_equivalent=_scoring_rows_equivalent,
    )
    grouped: dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]] = {}
    for key in set(baseline) & set(candidate):
        left = baseline[key]
        right = candidate[key]
        if str(left.get("unit") or "").upper() != unit:
            continue
        grouped.setdefault(str(left.get("target_date")), []).append((left, right))
    output = []
    for target_date, pairs in sorted(grouped.items()):
        n = len(pairs)
        baseline_brier = sum(
            _brier(left["replayed_p"], left["outcome"]) for left, _ in pairs
        ) / n
        candidate_brier = sum(
            _brier(right["replayed_p"], right["outcome"]) for _, right in pairs
        ) / n
        baseline_logloss = sum(
            _log_loss(left["replayed_p"], left["outcome"]) for left, _ in pairs
        ) / n
        candidate_logloss = sum(
            _log_loss(right["replayed_p"], right["outcome"]) for _, right in pairs
        ) / n
        market_brier = sum(
            _brier(left["market_yes"], left["outcome"]) for left, _ in pairs
        ) / n
        market_logloss = sum(
            _log_loss(left["market_yes"], left["outcome"]) for left, _ in pairs
        ) / n
        output.append(
            {
                "target_date": target_date,
                "rows": n,
                "markets": len({left.get("market_id") for left, _ in pairs}),
                "baseline_brier": baseline_brier,
                "candidate_brier": candidate_brier,
                "brier_delta": candidate_brier - baseline_brier,
                "baseline_logloss": baseline_logloss,
                "candidate_logloss": candidate_logloss,
                "logloss_delta": candidate_logloss - baseline_logloss,
                "market_brier": market_brier,
                "market_logloss": market_logloss,
                "candidate_brier_delta_vs_market": candidate_brier - market_brier,
                "candidate_logloss_delta_vs_market": candidate_logloss - market_logloss,
            }
        )
    return output


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def _percentile(sorted_values: list[float], quantile: float) -> float | None:
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def cluster_bootstrap_ci(
    values: Iterable[float],
    *,
    seed: int,
    replicates: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    """Paired cluster bootstrap over fleet dates (one scalar delta per date)."""
    values = [float(value) for value in values]
    if not values:
        return {"low": None, "high": None, "replicates": replicates, "seed": seed}
    rng = random.Random(int(seed))
    n = len(values)
    estimates = []
    for _ in range(int(replicates)):
        estimates.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    estimates.sort()
    return {
        "low": _percentile(estimates, 0.025),
        "high": _percentile(estimates, 0.975),
        "replicates": int(replicates),
        "seed": int(seed),
    }


def sign_test(values: Iterable[float]) -> dict[str, Any]:
    values = [float(value) for value in values]
    improvements = sum(value < 0.0 for value in values)
    regressions = sum(value > 0.0 for value in values)
    ties = len(values) - improvements - regressions
    n = improvements + regressions
    if n:
        tail = min(improvements, regressions)
        probability = min(
            1.0,
            2.0 * sum(math.comb(n, k) for k in range(tail + 1)) / (2.0**n),
        )
    else:
        probability = 1.0
    return {
        "improvements": improvements,
        "regressions": regressions,
        "ties": ties,
        "non_ties": n,
        "two_sided_p": probability,
    }


def _derived_seed(*parts: Any) -> int:
    digest = hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).digest()
    return BOOTSTRAP_SEED + int.from_bytes(digest[:4], "big")


def paired_summary(
    daily_rows: list[dict[str, Any]], *, split: str, unit: str, weight: float
) -> dict[str, Any]:
    brier_deltas = [row["brier_delta"] for row in daily_rows]
    logloss_deltas = [row["logloss_delta"] for row in daily_rows]
    return {
        "split": split,
        "unit": unit,
        "weight": float(weight),
        "fleet_dates": len(daily_rows),
        "scoring_rows": sum(row["rows"] for row in daily_rows),
        "mean_brier_delta": _mean(brier_deltas),
        "mean_logloss_delta": _mean(logloss_deltas),
        "mean_candidate_brier_delta_vs_market": _mean(
            row["candidate_brier_delta_vs_market"] for row in daily_rows
        ),
        "mean_candidate_logloss_delta_vs_market": _mean(
            row["candidate_logloss_delta_vs_market"] for row in daily_rows
        ),
        "brier_cluster_bootstrap_95ci": cluster_bootstrap_ci(
            brier_deltas, seed=_derived_seed(split, unit, weight, "brier")
        ),
        "logloss_cluster_bootstrap_95ci": cluster_bootstrap_ci(
            logloss_deltas, seed=_derived_seed(split, unit, weight, "logloss")
        ),
        "brier_sign_test": sign_test(brier_deltas),
        "logloss_sign_test": sign_test(logloss_deltas),
        "daily": daily_rows,
    }


def _arm_map(arms: Iterable[Mapping[str, Any]]) -> dict[float, dict[str, Any]]:
    output = {}
    for arm in arms:
        weight = float(arm.get("weight"))
        if weight in output:
            raise ExperimentConfigurationError(f"duplicate arm weight: {weight}")
        output[weight] = dict(arm)
    return output


def analyze_tune_arms(
    arms: Iterable[Mapping[str, Any]],
    tune_dates: Iterable[str],
    *,
    baseline_control: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate all tune arms and select separately for C and F using tune only."""
    arm_map = _arm_map(arms)
    blockers = []
    if set(arm_map) != set(SWEEP_WEIGHTS):
        blockers.append(
            f"tune arms must equal fixed grid {list(SWEEP_WEIGHTS)}; got {sorted(arm_map)}"
        )
    baseline = arm_map.get(0.0) or {"rows": [], "distribution_rows": [], "replay": {}}
    baseline_dates = {str(row.get("target_date")) for row in baseline.get("rows") or []}
    if baseline_dates != set(tune_dates):
        blockers.append("weight-0 scoring rows do not cover exactly the predeclared tune dates")
    control = dict(baseline_control or {})
    control_replay_blockers = list((control.get("replay") or {}).get("blockers") or [])
    control_mass = mass_gate(control.get("distribution_rows") or [])
    determinism = exact_determinism_gate(baseline, control)
    control_blockers = (
        control_replay_blockers + control_mass["blockers"] + determinism["blockers"]
    )
    blockers.extend(f"weight-0 determinism: {reason}" for reason in control_blockers)
    arm_gates = {}
    summaries: dict[str, list[dict[str, Any]]] = {unit: [] for unit in UNIT_FAMILIES}
    for weight in sorted(arm_map):
        arm = arm_map[weight]
        replay_blockers = list((arm.get("replay") or {}).get("blockers") or [])
        mass = mass_gate(arm.get("distribution_rows") or [])
        alignment = alignment_gate(baseline.get("rows") or [], arm.get("rows") or [])
        effect = (
            {
                "status": "BASELINE",
                "distributions_compared": 0,
                "missing": 0,
                "extra": 0,
                "unknown_local_hours": 0,
                "windows": {},
                "blockers": [],
            }
            if weight == 0.0
            else scope_effect_audit(
                baseline.get("distribution_rows") or [], arm.get("distribution_rows") or []
            )
        )
        gate_blockers = replay_blockers + mass["blockers"] + alignment["blockers"] + effect["blockers"]
        arm_gates[str(weight)] = {
            "status": "PASS" if not gate_blockers else "BLOCK",
            "replay": arm.get("replay") or {},
            "mass": mass,
            "alignment": alignment,
            "scope_effect": effect,
            "blockers": gate_blockers,
        }
        blockers.extend(f"weight {weight}: {reason}" for reason in gate_blockers)
        if weight == 0.0:
            continue
        for unit in UNIT_FAMILIES:
            daily = paired_fleet_date_rows(
                baseline.get("rows") or [], arm.get("rows") or [], unit
            )
            summaries[unit].append(
                paired_summary(daily, split="tune", unit=unit, weight=weight)
            )

    selected = {}
    selection_details = {}
    for unit in UNIT_FAMILIES:
        candidates = summaries[unit]
        if not any(row.get("fleet_dates") for row in candidates):
            blockers.append(f"no tune fleet-date scores for {unit} markets")
            selected[unit] = 0.0
            selection_details[unit] = {"selected_weight": 0.0, "eligible_weights": []}
            continue
        eligible = [
            row
            for row in candidates
            if row.get("mean_brier_delta") is not None
            and row.get("mean_logloss_delta") is not None
            and row["mean_brier_delta"] < 0.0
            and row["mean_logloss_delta"] < 0.0
        ]
        eligible.sort(
            key=lambda row: (
                row["mean_brier_delta"],
                row["mean_logloss_delta"],
                row["weight"],
            )
        )
        selected[unit] = float(eligible[0]["weight"]) if eligible else 0.0
        selection_details[unit] = {
            "selected_weight": selected[unit],
            "eligible_weights": [row["weight"] for row in eligible],
            "rule": (
                "require negative tune mean paired Brier and log-loss deltas; "
                "rank by Brier delta, log-loss delta, then smaller weight"
            ),
        }
    return {
        "status": "PASS" if not blockers else "BLOCK",
        "blockers": blockers,
        "arm_gates": arm_gates,
        "weight_zero_determinism": {
            **determinism,
            "mass": control_mass,
            "replay": control.get("replay") or {},
        },
        "paired": summaries,
        "selection": selection_details,
        "selected_weights": selected,
    }


def analyze_holdout_arms(
    arms: Iterable[Mapping[str, Any]],
    holdout_dates: Iterable[str],
    selected_weights: Mapping[str, float],
) -> dict[str, Any]:
    """Evaluate only the tune-selected C/F weights against weight 0."""
    arm_map = _arm_map(arms)
    expected = {0.0} | {float(weight) for weight in selected_weights.values() if weight > 0.0}
    blockers = []
    if set(arm_map) != expected:
        blockers.append(
            f"holdout arms must contain only baseline and tune-selected weights {sorted(expected)}"
        )
    baseline = arm_map.get(0.0) or {"rows": [], "distribution_rows": [], "replay": {}}
    baseline_dates = {str(row.get("target_date")) for row in baseline.get("rows") or []}
    if baseline_dates != set(holdout_dates):
        blockers.append("weight-0 scoring rows do not cover exactly the predeclared holdout dates")
    arm_gates = {}
    for weight, arm in sorted(arm_map.items()):
        replay_blockers = list((arm.get("replay") or {}).get("blockers") or [])
        mass = mass_gate(arm.get("distribution_rows") or [])
        alignment = alignment_gate(baseline.get("rows") or [], arm.get("rows") or [])
        effect = (
            {"status": "BASELINE", "blockers": [], "distributions_compared": 0,
             "missing": 0, "extra": 0, "unknown_local_hours": 0, "windows": {}}
            if weight == 0.0
            else scope_effect_audit(
                baseline.get("distribution_rows") or [], arm.get("distribution_rows") or []
            )
        )
        gate_blockers = replay_blockers + mass["blockers"] + alignment["blockers"] + effect["blockers"]
        arm_gates[str(weight)] = {
            "status": "PASS" if not gate_blockers else "BLOCK",
            "replay": arm.get("replay") or {},
            "mass": mass,
            "alignment": alignment,
            "scope_effect": effect,
            "blockers": gate_blockers,
        }
        blockers.extend(f"weight {weight}: {reason}" for reason in gate_blockers)

    paired = {}
    dispositions = {}
    for unit in UNIT_FAMILIES:
        weight = float(selected_weights.get(unit, 0.0))
        if weight == 0.0:
            paired[unit] = None
            dispositions[unit] = "NO_TUNE_CANDIDATE"
            continue
        arm = arm_map.get(weight) or {"rows": []}
        daily = paired_fleet_date_rows(
            baseline.get("rows") or [], arm.get("rows") or [], unit
        )
        summary = paired_summary(daily, split="holdout", unit=unit, weight=weight)
        paired[unit] = summary
        if not daily:
            blockers.append(f"no holdout fleet-date scores for selected {unit} weight {weight}")
            dispositions[unit] = "BLOCK"
            continue
        brier_ci = summary["brier_cluster_bootstrap_95ci"]
        logloss_ci = summary["logloss_cluster_bootstrap_95ci"]
        if brier_ci["high"] < 0.0 and logloss_ci["high"] < 0.0:
            dispositions[unit] = "SUPPORTED"
        elif summary["mean_brier_delta"] < 0.0 and summary["mean_logloss_delta"] < 0.0:
            dispositions[unit] = "DIRECTIONAL_ONLY"
        else:
            dispositions[unit] = "NOT_SUPPORTED"
    return {
        "status": "PASS" if not blockers else "BLOCK",
        "blockers": blockers,
        "arm_gates": arm_gates,
        "paired": paired,
        "dispositions": dispositions,
    }


def analyze_weight_zero_control(
    baseline_arm: Mapping[str, Any], control_arm: Mapping[str, Any]
) -> dict[str, Any]:
    """Compact the independent weight-zero canary before releasing its raw rows."""

    control_replay = control_arm.get("replay") or {}
    control_replay_blockers = list(control_replay.get("blockers") or [])
    control_mass = mass_gate(control_arm.get("distribution_rows") or [])
    determinism = exact_determinism_gate(baseline_arm, control_arm)
    blockers = control_replay_blockers + control_mass["blockers"] + determinism["blockers"]
    return {
        "evidence": {
            **determinism,
            "mass": control_mass,
            "replay": control_replay,
        },
        "blockers": blockers,
    }


def _baseline_scope_effect() -> dict[str, Any]:
    return {
        "status": "BASELINE",
        "distributions_compared": 0,
        "missing": 0,
        "extra": 0,
        "unknown_local_hours": 0,
        "windows": {},
        "blockers": [],
    }


def _compact_arm_gate(
    baseline_arm: Mapping[str, Any], arm: Mapping[str, Any], weight: float
) -> dict[str, Any]:
    """Compute only compact gate evidence; never retain candidate raw rows."""

    replay = arm.get("replay") or {}
    replay_blockers = list(replay.get("blockers") or [])
    mass = mass_gate(arm.get("distribution_rows") or [])
    alignment = alignment_gate(
        baseline_arm.get("rows") or [], arm.get("rows") or []
    )
    effect = (
        _baseline_scope_effect()
        if float(weight) == 0.0
        else scope_effect_audit(
            baseline_arm.get("distribution_rows") or [],
            arm.get("distribution_rows") or [],
        )
    )
    blockers = (
        replay_blockers
        + mass["blockers"]
        + alignment["blockers"]
        + effect["blockers"]
    )
    return {
        "status": "PASS" if not blockers else "BLOCK",
        "replay": replay,
        "mass": mass,
        "alignment": alignment,
        "scope_effect": effect,
        "blockers": blockers,
    }


def _select_tune_weights(
    summaries: Mapping[str, list[dict[str, Any]]], blockers: list[str]
) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
    selected: dict[str, float] = {}
    selection_details: dict[str, dict[str, Any]] = {}
    for unit in UNIT_FAMILIES:
        candidates = summaries[unit]
        if not any(row.get("fleet_dates") for row in candidates):
            blockers.append(f"no tune fleet-date scores for {unit} markets")
            selected[unit] = 0.0
            selection_details[unit] = {
                "selected_weight": 0.0,
                "eligible_weights": [],
            }
            continue
        eligible = [
            row
            for row in candidates
            if row.get("mean_brier_delta") is not None
            and row.get("mean_logloss_delta") is not None
            and row["mean_brier_delta"] < 0.0
            and row["mean_logloss_delta"] < 0.0
        ]
        eligible.sort(
            key=lambda row: (
                row["mean_brier_delta"],
                row["mean_logloss_delta"],
                row["weight"],
            )
        )
        selected[unit] = float(eligible[0]["weight"]) if eligible else 0.0
        selection_details[unit] = {
            "selected_weight": selected[unit],
            "eligible_weights": [row["weight"] for row in eligible],
            "rule": (
                "require negative tune mean paired Brier and log-loss deltas; "
                "rank by Brier delta, log-loss delta, then smaller weight"
            ),
        }
    return selected, selection_details


def analyze_tune_arms_incremental(
    baseline_arm: Mapping[str, Any],
    tune_dates: Iterable[str],
    *,
    weight_zero_control: Mapping[str, Any],
    candidate_loader: Callable[[float], Mapping[str, Any]],
    candidate_weights: Iterable[float] = SWEEP_WEIGHTS[1:],
    collect_garbage: Callable[[], Any] = gc.collect,
) -> dict[str, Any]:
    """Analyze tune arms sequentially while retaining baseline plus one candidate."""

    weights = tuple(float(weight) for weight in candidate_weights)
    blockers: list[str] = []
    expected = tuple(float(weight) for weight in SWEEP_WEIGHTS[1:])
    if weights != expected:
        blockers.append(
            f"tune candidate weights must equal fixed grid {list(expected)}; got {list(weights)}"
        )
    if float(baseline_arm.get("weight", -1.0)) != 0.0:
        blockers.append("incremental tune baseline must be the weight-0 arm")
    baseline_dates = {
        str(row.get("target_date")) for row in baseline_arm.get("rows") or []
    }
    if baseline_dates != set(tune_dates):
        blockers.append("weight-0 scoring rows do not cover exactly the predeclared tune dates")

    control = dict(weight_zero_control or {})
    blockers.extend(
        f"weight-0 determinism: {reason}"
        for reason in (control.get("blockers") or [])
    )
    arm_gates: dict[str, dict[str, Any]] = {}
    baseline_gate = _compact_arm_gate(baseline_arm, baseline_arm, 0.0)
    arm_gates[str(0.0)] = baseline_gate
    blockers.extend(f"weight 0.0: {reason}" for reason in baseline_gate["blockers"])
    summaries: dict[str, list[dict[str, Any]]] = {
        unit: [] for unit in UNIT_FAMILIES
    }

    for weight in weights:
        candidate: Mapping[str, Any] | None = None
        try:
            candidate = candidate_loader(weight)
            actual_weight = float(candidate.get("weight", -1.0))
            if actual_weight != weight:
                raise ExperimentConfigurationError(
                    f"candidate loader returned weight {actual_weight} for requested {weight}"
                )
            gate = _compact_arm_gate(baseline_arm, candidate, weight)
            arm_gates[str(weight)] = gate
            blockers.extend(f"weight {weight}: {reason}" for reason in gate["blockers"])
            for unit in UNIT_FAMILIES:
                daily = paired_fleet_date_rows(
                    baseline_arm.get("rows") or [], candidate.get("rows") or [], unit
                )
                summaries[unit].append(
                    paired_summary(daily, split="tune", unit=unit, weight=weight)
                )
        finally:
            candidate = None
            collect_garbage()

    selected, selection_details = _select_tune_weights(summaries, blockers)
    return {
        "status": "PASS" if not blockers else "BLOCK",
        "blockers": blockers,
        "arm_gates": arm_gates,
        "weight_zero_determinism": control.get("evidence") or {},
        "paired": summaries,
        "selection": selection_details,
        "selected_weights": selected,
    }


def analyze_holdout_arms_incremental(
    baseline_arm: Mapping[str, Any],
    holdout_dates: Iterable[str],
    selected_weights: Mapping[str, float],
    *,
    candidate_loader: Callable[[float], Mapping[str, Any]],
    collect_garbage: Callable[[], Any] = gc.collect,
) -> dict[str, Any]:
    """Evaluate selected holdout arms sequentially against one retained baseline."""

    blockers: list[str] = []
    if float(baseline_arm.get("weight", -1.0)) != 0.0:
        blockers.append("incremental holdout baseline must be the weight-0 arm")
    baseline_dates = {
        str(row.get("target_date")) for row in baseline_arm.get("rows") or []
    }
    if baseline_dates != set(holdout_dates):
        blockers.append("weight-0 scoring rows do not cover exactly the predeclared holdout dates")

    arm_gates: dict[str, dict[str, Any]] = {}
    baseline_gate = _compact_arm_gate(baseline_arm, baseline_arm, 0.0)
    arm_gates[str(0.0)] = baseline_gate
    blockers.extend(f"weight 0.0: {reason}" for reason in baseline_gate["blockers"])

    paired: dict[str, dict[str, Any] | None] = {
        unit: None for unit in UNIT_FAMILIES
    }
    selected_by_weight: dict[float, list[str]] = {}
    for unit in UNIT_FAMILIES:
        weight = float(selected_weights.get(unit, 0.0))
        if weight > 0.0:
            selected_by_weight.setdefault(weight, []).append(unit)

    for weight, units in sorted(selected_by_weight.items()):
        candidate: Mapping[str, Any] | None = None
        try:
            candidate = candidate_loader(weight)
            actual_weight = float(candidate.get("weight", -1.0))
            if actual_weight != weight:
                raise ExperimentConfigurationError(
                    f"candidate loader returned weight {actual_weight} for requested {weight}"
                )
            gate = _compact_arm_gate(baseline_arm, candidate, weight)
            arm_gates[str(weight)] = gate
            blockers.extend(f"weight {weight}: {reason}" for reason in gate["blockers"])
            for unit in units:
                daily = paired_fleet_date_rows(
                    baseline_arm.get("rows") or [], candidate.get("rows") or [], unit
                )
                paired[unit] = paired_summary(
                    daily, split="holdout", unit=unit, weight=weight
                )
        finally:
            candidate = None
            collect_garbage()

    dispositions: dict[str, str] = {}
    for unit in UNIT_FAMILIES:
        weight = float(selected_weights.get(unit, 0.0))
        if weight == 0.0:
            dispositions[unit] = "NO_TUNE_CANDIDATE"
            continue
        summary = paired[unit] or {}
        if not summary.get("daily"):
            blockers.append(
                f"no holdout fleet-date scores for selected {unit} weight {weight}"
            )
            dispositions[unit] = "BLOCK"
            continue
        brier_ci = summary["brier_cluster_bootstrap_95ci"]
        logloss_ci = summary["logloss_cluster_bootstrap_95ci"]
        if brier_ci["high"] < 0.0 and logloss_ci["high"] < 0.0:
            dispositions[unit] = "SUPPORTED"
        elif summary["mean_brier_delta"] < 0.0 and summary["mean_logloss_delta"] < 0.0:
            dispositions[unit] = "DIRECTIONAL_ONLY"
        else:
            dispositions[unit] = "NOT_SUPPORTED"
    return {
        "status": "PASS" if not blockers else "BLOCK",
        "blockers": blockers,
        "arm_gates": arm_gates,
        "paired": paired,
        "dispositions": dispositions,
    }


def build_payload(
    *,
    paths: Mapping[str, Path],
    manifest: Mapping[str, Any],
    tune_dates: Iterable[str],
    holdout_dates: Iterable[str],
    tune_analysis: Mapping[str, Any],
    holdout_analysis: Mapping[str, Any] | None,
    cache_files: Iterable[Path],
) -> dict[str, Any]:
    technical_blockers = list(tune_analysis.get("blockers") or [])
    if holdout_analysis is not None:
        technical_blockers.extend(holdout_analysis.get("blockers") or [])
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "BLOCK" if technical_blockers else "COMPLETE",
        "research_only": True,
        "promotion_authorized": False,
        "technical_blockers": technical_blockers,
        "experiment": {
            "hypothesis": "H1 serve-stage ordinal smoothing is under-tuned",
            "swept_variable": "ordinal_smoothing_blend_weight",
            "weights": list(SWEEP_WEIGHTS),
            "fixed_sigma": SMOOTHING_SIGMA,
            "sigma_unit": "native_settlement_unit",
            "smoothing_scope": "whenever_feature_probabilities_exist",
            "selection_uses_holdout": False,
            "determinism_canary_date": DETERMINISM_CANARY_DATE,
            "bootstrap_seed_base": BOOTSTRAP_SEED,
            "bootstrap_replicates": BOOTSTRAP_REPLICATES,
            "mass_tolerance": MASS_TOLERANCE,
        },
        "inputs": {
            "mirror_data_root": str(paths["mirror_data_root"]),
            "staged_data_root": str(paths["staged_data_root"]),
            "snapshots_root": str(paths["snapshots_root"]),
            "corpus_path": str(paths["corpus_path"]),
            "corpus_hash": manifest.get("corpus_hash"),
            "tune_dates_path": str(paths["tune_dates_path"]),
            "holdout_dates_path": str(paths["holdout_dates_path"]),
            "opened_read_only": True,
        },
        "outputs": {
            "json_out": str(paths["json_out"]),
            "report_out": str(paths["report_out"]),
            "cache_root": str(paths["cache_root"]),
            "lock_path": str(paths["lock_path"]),
            "cache_files": [str(path) for path in cache_files],
            "outside_input_data_roots": True,
        },
        "split": {
            "tune_dates": list(tune_dates),
            "holdout_dates": list(holdout_dates),
        },
        "tune": dict(tune_analysis),
        "holdout": dict(holdout_analysis) if holdout_analysis is not None else {
            "status": "NOT_TOUCHED",
            "reason": "tune technical gates blocked before candidate selection",
        },
    }


def _summary_rows(payload: Mapping[str, Any]) -> list[list[Any]]:
    rows = []
    tune = payload.get("tune") or {}
    for unit, summaries in (tune.get("paired") or {}).items():
        for summary in summaries or []:
            brier_ci = summary.get("brier_cluster_bootstrap_95ci") or {}
            logloss_ci = summary.get("logloss_cluster_bootstrap_95ci") or {}
            brier_sign = summary.get("brier_sign_test") or {}
            rows.append([
                "tune", unit, summary.get("weight"), summary.get("fleet_dates"),
                fmt_signed(summary.get("mean_brier_delta")),
                f"[{fmt_num(brier_ci.get('low'))}, {fmt_num(brier_ci.get('high'))}]",
                f"{brier_sign.get('improvements')}/{brier_sign.get('regressions')}/{brier_sign.get('ties')}",
                fmt_signed(summary.get("mean_logloss_delta")),
                f"[{fmt_num(logloss_ci.get('low'))}, {fmt_num(logloss_ci.get('high'))}]",
                fmt_signed(summary.get("mean_candidate_brier_delta_vs_market")),
                fmt_signed(summary.get("mean_candidate_logloss_delta_vs_market")),
            ])
    holdout = payload.get("holdout") or {}
    for unit, summary in (holdout.get("paired") or {}).items():
        if not summary:
            continue
        brier_ci = summary.get("brier_cluster_bootstrap_95ci") or {}
        logloss_ci = summary.get("logloss_cluster_bootstrap_95ci") or {}
        brier_sign = summary.get("brier_sign_test") or {}
        rows.append([
            "holdout", unit, summary.get("weight"), summary.get("fleet_dates"),
            fmt_signed(summary.get("mean_brier_delta")),
            f"[{fmt_num(brier_ci.get('low'))}, {fmt_num(brier_ci.get('high'))}]",
            f"{brier_sign.get('improvements')}/{brier_sign.get('regressions')}/{brier_sign.get('ties')}",
            fmt_signed(summary.get("mean_logloss_delta")),
            f"[{fmt_num(logloss_ci.get('low'))}, {fmt_num(logloss_ci.get('high'))}]",
            fmt_signed(summary.get("mean_candidate_brier_delta_vs_market")),
            fmt_signed(summary.get("mean_candidate_logloss_delta_vs_market")),
        ])
    return rows


def _effect_rows(payload: Mapping[str, Any]) -> list[list[Any]]:
    rows = []
    for split in ("tune", "holdout"):
        section = payload.get(split) or {}
        for weight, gate in sorted(
            (section.get("arm_gates") or {}).items(),
            key=lambda item: float(item[0]),
        ):
            if float(weight) == 0.0:
                continue
            effect = gate.get("scope_effect") or {}
            for window in ("00-06", "07-20", "21-23"):
                values = (effect.get("windows") or {}).get(window) or {}
                rows.append([
                    split,
                    weight,
                    window,
                    values.get("distributions", 0),
                    values.get("changed_exact", 0),
                    values.get("unchanged_exact", 0),
                    fmt_num(values.get("mean_l1")),
                    fmt_num(values.get("maximum_l1")),
                ])
    return rows


def render_report(payload: Mapping[str, Any]) -> str:
    tune = payload.get("tune") or {}
    holdout = payload.get("holdout") or {}
    paths = payload.get("inputs") or {}
    selection = tune.get("selected_weights") or {}
    determinism = tune.get("weight_zero_determinism") or {}
    lines = [
        "# H1 Ordinal-Smoothing Sweep",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        "Mode: research-only; this report does not authorize serving or promotion.",
        "",
        "## Fixed Experiment Contract",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Swept variable", "ordinal smoothing blend weight only"],
                ["Weights", ", ".join(map(str, SWEEP_WEIGHTS))],
                ["Sigma", f"{SMOOTHING_SIGMA} native settlement units"],
                ["Smoothing scope", "whenever feature probabilities exist"],
                ["Tune dates", len((payload.get("split") or {}).get("tune_dates") or [])],
                ["Untouched holdout dates", len((payload.get("split") or {}).get("holdout_dates") or [])],
                ["Weight-0 canary date", DETERMINISM_CANARY_DATE],
                ["Weight-0 determinism", determinism.get("status")],
                ["Weight-0 canary distributions", determinism.get("distributions")],
                ["Selected C weight", selection.get("C")],
                ["Selected F weight", selection.get("F")],
            ],
        ),
        "",
        "## Read-Only Provenance and Write Boundary",
        "",
        *markdown_table(
            ["Field", "Path / value"],
            [
                ["Mirror data root", paths.get("mirror_data_root")],
                ["Staged data root", paths.get("staged_data_root")],
                ["Snapshots", paths.get("snapshots_root")],
                ["Pinned corpus", paths.get("corpus_path")],
                ["Corpus hash", paths.get("corpus_hash")],
                ["Inputs opened read-only", paths.get("opened_read_only")],
                ["Outputs outside input roots", (payload.get("outputs") or {}).get("outside_input_data_roots")],
            ],
        ),
        "",
        "## Paired Fleet-Date Results",
        "",
        *markdown_table(
            [
                "Split", "Unit", "Weight", "Dates", "Delta Brier vs W0",
                "Brier 95% CI", "Brier +/-/=", "Delta log loss vs W0",
                "Log-loss 95% CI", "Brier vs market", "Log loss vs market",
            ],
            _summary_rows(payload),
        ),
        "",
        "Negative deltas favor the smoothing arm. Confidence intervals are deterministic paired cluster bootstraps over fleet dates; signs are improvement/regression/tie counts.",
        "",
        "## Distribution Effect by Local Hour",
        "",
        *markdown_table(
            ["Split", "Weight", "Local hour", "N", "Changed", "Unchanged", "Mean L1", "Max L1"],
            _effect_rows(payload),
        ),
        "",
        "This is an effect audit, not a no-change gate: the effective printed cutoff can already select the hour-7 feature model during local predawn hours.",
        "",
        "## Weight-0 Determinism Canary",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Date", ", ".join(determinism.get("dates") or [])],
                ["Markets", len(determinism.get("markets") or [])],
                ["Scoring rows", determinism.get("scoring_rows")],
                ["Distributions", determinism.get("distributions")],
                ["Baseline row hash", determinism.get("baseline_row_hash")],
                ["Control row hash", determinism.get("control_row_hash")],
                ["Baseline distribution hash", determinism.get("baseline_distribution_hash")],
                ["Control distribution hash", determinism.get("control_distribution_hash")],
            ],
        ),
        "",
        "## Holdout Disposition",
        "",
        *markdown_table(
            ["Unit", "Disposition"],
            [[unit, disposition] for unit, disposition in (holdout.get("dispositions") or {}).items()],
        ),
        "",
        "## Technical Blockers",
        "",
        *(f"- {reason}" for reason in (payload.get("technical_blockers") or ["none"])),
        "",
    ]
    return "\n".join(lines)


def write_outputs(payload: Mapping[str, Any], json_out: Path, report_out: Path) -> None:
    for path in (json_out, report_out):
        if path.exists():
            raise ExperimentConfigurationError(f"refusing to overwrite existing output: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(json_out, payload)
    temporary = report_out.with_name(report_out.name + f".tmp-{os.getpid()}")
    temporary.write_text(render_report(payload), encoding="utf-8")
    os.replace(temporary, report_out)


@contextmanager
def exclusive_research_lock(path: Path):
    """Acquire one explicit fail-closed lock and remove only the lock we created."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ExperimentConfigurationError(f"research lock already exists: {path}") from exc
    try:
        payload = {
            "pid": os.getpid(),
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "schema_version": SCHEMA_VERSION,
        }
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def run_experiment(args: argparse.Namespace) -> dict[str, Any]:
    paths = validate_path_contract(
        mirror_data_root=args.mirror_data_root,
        staged_data_root=args.staged_data_root,
        snapshots_root=args.snapshots_root,
        corpus_path=args.corpus,
        tune_dates_path=args.tune_dates_file,
        holdout_dates_path=args.holdout_dates_file,
        json_out=args.json_out,
        report_out=args.report_out,
        cache_root=args.cache_root,
        lock_path=args.lock_path,
    )
    tune_dates = read_predeclared_dates(paths["tune_dates_path"])
    holdout_dates = read_predeclared_dates(paths["holdout_dates_path"])

    from weather.reporting.promotion.promotion_corpus import load_manifest

    manifest = load_manifest(paths["corpus_path"], max_bytes=MAX_MANIFEST_BYTES)
    partitions = partition_manifest_entries(manifest, tune_dates, holdout_dates)
    if DETERMINISM_CANARY_DATE not in set(tune_dates):
        raise ExperimentConfigurationError(
            f"the predeclared tune set must include determinism canary date {DETERMINISM_CANARY_DATE}"
        )
    canary_entries = [
        entry
        for entry in partitions["tune"]
        if entry.get("target_date") == DETERMINISM_CANARY_DATE
    ]
    from weather.market.market_registry import REGISTRY

    canary_markets = {str(entry.get("market_id") or "") for entry in canary_entries}
    if canary_markets != set(REGISTRY) or len(canary_entries) != len(REGISTRY):
        missing = sorted(set(REGISTRY) - canary_markets)
        extra = sorted(canary_markets - set(REGISTRY))
        raise ExperimentConfigurationError(
            "weight-0 determinism canary must cover the full configured fleet on "
            f"{DETERMINISM_CANARY_DATE} exactly once per market; "
            f"entries={len(canary_entries)}, expected={len(REGISTRY)}, "
            f"missing={missing}, extra={extra}"
        )
    all_entries = partitions["tune"] + partitions["holdout"]
    _configure_staged_data_root(paths["staged_data_root"])
    validate_staged_daily_inputs(all_entries, paths["staged_data_root"])
    # Resolve and probe only tune tapes before selection.  Holdout tape files
    # remain unopened until the tune-only arm ranking is final.
    tune_folders = folders_for_entries(partitions["tune"], paths["snapshots_root"])
    canary_folders = folders_for_entries(canary_entries, paths["snapshots_root"])

    with exclusive_research_lock(paths["lock_path"]):
        paths["cache_root"].mkdir(parents=True, exist_ok=True)
        digest = _code_digest()
        print("H1 tune replay: weight=0.00", flush=True)
        tune_baseline = load_or_run_arm(
            split="tune",
            weight=0.0,
            entries=partitions["tune"],
            folders=tune_folders,
            manifest=manifest,
            staged_data_root=paths["staged_data_root"],
            cache_root=paths["cache_root"],
            code_digest=digest,
            resume=args.resume,
        )
        try:
            print(
                f"H1 weight-0 determinism canary: fleet_date={DETERMINISM_CANARY_DATE}",
                flush=True,
            )
            baseline_control = load_or_run_arm(
                split="tune-determinism-control",
                weight=0.0,
                entries=canary_entries,
                folders=canary_folders,
                manifest=manifest,
                staged_data_root=paths["staged_data_root"],
                cache_root=paths["cache_root"],
                code_digest=digest,
                resume=args.resume,
            )
            try:
                weight_zero_control = analyze_weight_zero_control(
                    tune_baseline, baseline_control
                )
            finally:
                baseline_control = None
                gc.collect()

            def load_tune_candidate(weight: float) -> Mapping[str, Any]:
                print(f"H1 tune replay: weight={weight:.2f}", flush=True)
                return load_or_run_arm(
                    split="tune",
                    weight=weight,
                    entries=partitions["tune"],
                    folders=tune_folders,
                    manifest=manifest,
                    staged_data_root=paths["staged_data_root"],
                    cache_root=paths["cache_root"],
                    code_digest=digest,
                    resume=args.resume,
                )

            tune_analysis = analyze_tune_arms_incremental(
                tune_baseline,
                tune_dates,
                weight_zero_control=weight_zero_control,
                candidate_loader=load_tune_candidate,
            )
        finally:
            tune_baseline = None
            gc.collect()

        holdout_analysis = None
        if tune_analysis["status"] == "PASS":
            selected = tune_analysis["selected_weights"]
            holdout_folders = folders_for_entries(
                partitions["holdout"], paths["snapshots_root"]
            )
            print("H1 holdout replay: weight=0.00", flush=True)
            holdout_baseline = load_or_run_arm(
                split="holdout",
                weight=0.0,
                entries=partitions["holdout"],
                folders=holdout_folders,
                manifest=manifest,
                staged_data_root=paths["staged_data_root"],
                cache_root=paths["cache_root"],
                code_digest=digest,
                resume=args.resume,
            )
            try:
                def load_holdout_candidate(weight: float) -> Mapping[str, Any]:
                    print(f"H1 holdout replay: weight={weight:.2f}", flush=True)
                    return load_or_run_arm(
                        split="holdout",
                        weight=weight,
                        entries=partitions["holdout"],
                        folders=holdout_folders,
                        manifest=manifest,
                        staged_data_root=paths["staged_data_root"],
                        cache_root=paths["cache_root"],
                        code_digest=digest,
                        resume=args.resume,
                    )

                holdout_analysis = analyze_holdout_arms_incremental(
                    holdout_baseline,
                    holdout_dates,
                    selected,
                    candidate_loader=load_holdout_candidate,
                )
            finally:
                holdout_baseline = None
                gc.collect()
        cache_files = sorted(paths["cache_root"].glob("*.json"))
        payload = build_payload(
            paths=paths,
            manifest=manifest,
            tune_dates=tune_dates,
            holdout_dates=holdout_dates,
            tune_analysis=tune_analysis,
            holdout_analysis=holdout_analysis,
            cache_files=cache_files,
        )
        write_outputs(payload, paths["json_out"], paths["report_out"])
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Research-only H1 ordinal-smoothing sweep over a pinned captured-input corpus. "
            "All data and write locations are required and validated fail-closed."
        )
    )
    parser.add_argument("--mirror-data-root", required=True)
    parser.add_argument("--staged-data-root", required=True)
    parser.add_argument("--snapshots-root", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--tune-dates-file", required=True)
    parser.add_argument("--holdout-dates-file", required=True)
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--report-out", required=True)
    parser.add_argument("--cache-root", required=True)
    parser.add_argument("--lock-path", required=True)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse only cache arms whose corpus/config/code fingerprint matches exactly.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = run_experiment(args)
    except (ExperimentConfigurationError, OSError, ValueError) as exc:
        print(f"H1 ordinal-smoothing sweep blocked: {exc}", file=sys.stderr)
        return 2
    print(
        "H1 ordinal-smoothing sweep "
        f"status={payload.get('status')} "
        f"C={payload.get('tune', {}).get('selected_weights', {}).get('C')} "
        f"F={payload.get('tune', {}).get('selected_weights', {}).get('F')}"
    )
    print(f"JSON written to {args.json_out}")
    print(f"Report written to {args.report_out}")
    return 1 if payload.get("status") == "BLOCK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
