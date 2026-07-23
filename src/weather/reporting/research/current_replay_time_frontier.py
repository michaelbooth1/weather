"""Memory-bounded time-frontier analysis for selected H1 replay arms.

This research command intentionally consumes the raw H1 JSON caches as immutable
inputs.  H1 caches are several gigabytes each, so every array is decoded one JSON
object at a time; only a capped scoring-key/projection index plus snapshot-,
market-date-, and fleet-date aggregates are retained.  The holdout cache plan is
derived *only* after the tune-only H1 result has fixed its selected weights;
unselected holdout arms are never discovered or opened by this module.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, MutableMapping, Sequence

import numpy as np

from weather.market.market_registry import REGISTRY
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("workstation_current_replay_time_frontier")
H1_SCHEMA_VERSION = schema_version("ordinal_smoothing_sweep")
BOOTSTRAP_SEED = 20260722
BOOTSTRAP_REPLICATES = 10_000
DEFAULT_CHUNK_CHARS = 256 * 1024
DEFAULT_MAX_ITEM_CHARS = 4 * 1024 * 1024
MAX_CACHE_BYTES = 3 * 1024 * 1024 * 1024
MAX_AGGREGATE_GROUPS = 250_000
MAX_ALIGNMENT_KEYS = 500_000
MAX_H1_RESULT_BYTES = 100 * 1024 * 1024
MAX_DATE_MANIFEST_BYTES = 1024 * 1024
MAX_HISTORICAL_CONTEXT_BYTES = 10 * 1024 * 1024
LOG_LOSS_EPSILON = 1e-15
UNITS = ("C", "F")
METRIC_NAMES = ("brier", "logloss", "winner_probability")
MODEL_NAMES = ("current", "selected", "market")
HOURS = tuple(range(24))
EVENING_HOURS = tuple(range(15, 24))
PREDAWN_HOURS = (3, 4, 5)
_TAIL_METADATA_RE = re.compile(
    rb'\],"sigma":(?P<sigma>-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?),'
    rb'"split":"(?P<split>[^"]+)",'
    rb'"weight":(?P<weight>-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)'
    rb'},"fingerprint":"(?P<fingerprint>[0-9a-f]{64})",'
    rb'"schema_version":"(?P<schema>[^"]+)"}\s*$',
)


class ExperimentConfigurationError(ValueError):
    """Raised when provenance, selection, alignment, or path safety fails."""


@dataclass
class ReaderStats:
    """Observable bounded-reader diagnostics, also asserted by focused tests."""

    field: str
    chunk_chars: int
    max_item_chars: int
    chunks_read: int = 0
    characters_read: int = 0
    items_yielded: int = 0
    maximum_buffer_chars: int = 0
    maximum_item_chars: int = 0

    def observe_buffer(self, size: int) -> None:
        self.maximum_buffer_chars = max(self.maximum_buffer_chars, int(size))
        if size > self.chunk_chars + self.max_item_chars:
            raise ExperimentConfigurationError(
                "streaming JSON buffer exceeded its declared bound: "
                f"{size} > {self.chunk_chars + self.max_item_chars}"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "chunk_chars": self.chunk_chars,
            "max_item_chars": self.max_item_chars,
            "chunks_read": self.chunks_read,
            "characters_read": self.characters_read,
            "items_yielded": self.items_yielded,
            "maximum_buffer_chars": self.maximum_buffer_chars,
            "maximum_item_chars": self.maximum_item_chars,
            "declared_buffer_bound_chars": self.chunk_chars + self.max_item_chars,
        }


@dataclass(frozen=True)
class CacheMetadata:
    path: Path
    size_bytes: int
    mtime_ns: int
    split: str
    weight: float
    sigma: float
    fingerprint: str
    schema_version: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "size_bytes": self.size_bytes,
            "mtime_ns": self.mtime_ns,
            "split": self.split,
            "weight": self.weight,
            "sigma": self.sigma,
            "fingerprint": self.fingerprint,
            "schema_version": self.schema_version,
        }


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _read_text_chunk(handle: Any, size: int, stats: ReaderStats) -> str:
    chunk = handle.read(size)
    if chunk:
        stats.chunks_read += 1
        stats.characters_read += len(chunk)
    return chunk


def iter_cache_array(
    path: str | Path,
    field: str = "rows",
    *,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    max_item_chars: int = DEFAULT_MAX_ITEM_CHARS,
    stats: ReaderStats | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield object members of one known H1 cache array with bounded buffering.

    The H1 writer uses compact, sorted-key JSON.  We require that exact envelope
    prefix and seek the requested array marker with fixed-size text chunks.  Each
    row is then decoded by ``JSONDecoder.raw_decode``; at most one incomplete row
    plus one input chunk remains resident.  A malformed or unexpectedly large
    row fails closed instead of expanding memory without limit.
    """

    cache_path = _resolved(path)
    if field not in {"distribution_rows", "rows"}:
        raise ExperimentConfigurationError(f"unsupported cache array field: {field}")
    if chunk_chars < 32 or max_item_chars < 64:
        raise ExperimentConfigurationError("streaming bounds are implausibly small")
    if not cache_path.is_file():
        raise ExperimentConfigurationError(f"cache file does not exist: {cache_path}")
    initial_stat = cache_path.stat()
    size = initial_stat.st_size
    if size <= 0 or size > MAX_CACHE_BYTES:
        raise ExperimentConfigurationError(
            f"cache size is outside the fail-closed bound: {cache_path} ({size})"
        )
    diagnostics = stats or ReaderStats(field, chunk_chars, max_item_chars)
    if diagnostics.field != field:
        raise ExperimentConfigurationError("reader diagnostics field mismatch")
    if (
        diagnostics.chunk_chars != chunk_chars
        or diagnostics.max_item_chars != max_item_chars
    ):
        raise ExperimentConfigurationError("reader diagnostics bound mismatch")
    marker = f'"{field}":['
    required_prefix = '{"arm":{"distribution_rows":['
    decoder = json.JSONDecoder()

    with cache_path.open("r", encoding="utf-8", newline="") as handle:
        initial = _read_text_chunk(handle, chunk_chars, diagnostics)
        if not initial.startswith(required_prefix):
            raise ExperimentConfigurationError(
                f"cache does not have the canonical compact H1 envelope: {cache_path}"
            )
        buffer = initial
        marker_index = buffer.find(marker)
        overlap = max(1, len(marker) - 1)
        while marker_index < 0:
            carry = buffer[-overlap:]
            chunk = _read_text_chunk(handle, chunk_chars, diagnostics)
            if not chunk:
                raise ExperimentConfigurationError(
                    f"cache array marker {field!r} is missing: {cache_path}"
                )
            buffer = carry + chunk
            diagnostics.observe_buffer(len(buffer))
            marker_index = buffer.find(marker)
        buffer = buffer[marker_index + len(marker) :]
        position = 0
        first = True

        while True:
            if position:
                buffer = buffer[position:]
                position = 0
            while not buffer:
                chunk = _read_text_chunk(handle, chunk_chars, diagnostics)
                if not chunk:
                    raise ExperimentConfigurationError(
                        f"unterminated cache array {field!r}: {cache_path}"
                    )
                buffer = chunk
            diagnostics.observe_buffer(len(buffer))

            while buffer and buffer[0].isspace():
                buffer = buffer[1:]
            if not buffer:
                continue
            if buffer[0] == "]":
                final_stat = cache_path.stat()
                if (
                    final_stat.st_size != initial_stat.st_size
                    or final_stat.st_mtime_ns != initial_stat.st_mtime_ns
                ):
                    raise ExperimentConfigurationError(
                        f"cache changed while array {field!r} was streamed: {cache_path}"
                    )
                return
            if not first:
                if buffer[0] != ",":
                    raise ExperimentConfigurationError(
                        f"malformed separator in cache array {field!r}: {cache_path}"
                    )
                buffer = buffer[1:]
                while True:
                    while buffer and buffer[0].isspace():
                        buffer = buffer[1:]
                    if buffer:
                        break
                    chunk = _read_text_chunk(handle, chunk_chars, diagnostics)
                    if not chunk:
                        raise ExperimentConfigurationError(
                            f"unterminated cache array {field!r}: {cache_path}"
                        )
                    buffer = chunk
                if buffer[0] == "]":
                    raise ExperimentConfigurationError(
                        f"trailing comma in cache array {field!r}: {cache_path}"
                    )
            first = False

            while True:
                diagnostics.observe_buffer(len(buffer))
                try:
                    value, end = decoder.raw_decode(buffer)
                except json.JSONDecodeError as exc:
                    if len(buffer) > max_item_chars:
                        raise ExperimentConfigurationError(
                            f"cache item exceeds {max_item_chars} characters in "
                            f"{field!r}: {cache_path}"
                        ) from exc
                    chunk = _read_text_chunk(handle, chunk_chars, diagnostics)
                    if not chunk:
                        raise ExperimentConfigurationError(
                            f"malformed or truncated cache item in {field!r}: {cache_path}"
                        ) from exc
                    buffer += chunk
                    continue
                item_chars = end
                if item_chars > max_item_chars:
                    raise ExperimentConfigurationError(
                        f"cache item exceeds {max_item_chars} characters in "
                        f"{field!r}: {cache_path}"
                    )
                if not isinstance(value, dict):
                    raise ExperimentConfigurationError(
                        f"cache array {field!r} contains a non-object item: {cache_path}"
                    )
                diagnostics.items_yielded += 1
                diagnostics.maximum_item_chars = max(
                    diagnostics.maximum_item_chars, item_chars
                )
                position = end
                yield value
                break


def read_cache_metadata(path: str | Path) -> CacheMetadata:
    """Read only the bounded prefix/tail needed to validate an H1 cache."""

    cache_path = _resolved(path)
    if not cache_path.is_file():
        raise ExperimentConfigurationError(f"cache file does not exist: {cache_path}")
    initial_stat = cache_path.stat()
    size = initial_stat.st_size
    if size <= 0 or size > MAX_CACHE_BYTES:
        raise ExperimentConfigurationError(
            f"cache size is outside the fail-closed bound: {cache_path} ({size})"
        )
    with cache_path.open("rb") as handle:
        prefix = handle.read(128)
        if not prefix.startswith(b'{"arm":{"distribution_rows":['):
            raise ExperimentConfigurationError(
                f"cache does not have the canonical compact H1 envelope: {cache_path}"
            )
        tail_bytes = min(size, 256 * 1024)
        handle.seek(size - tail_bytes)
        tail = handle.read(tail_bytes)
    match = _TAIL_METADATA_RE.search(tail)
    if not match:
        raise ExperimentConfigurationError(
            f"cache tail metadata is missing or noncanonical: {cache_path}"
        )
    final_stat = cache_path.stat()
    if (
        final_stat.st_size != initial_stat.st_size
        or final_stat.st_mtime_ns != initial_stat.st_mtime_ns
    ):
        raise ExperimentConfigurationError(
            f"cache changed while bounded metadata was read: {cache_path}"
        )
    metadata = CacheMetadata(
        path=cache_path,
        size_bytes=size,
        mtime_ns=initial_stat.st_mtime_ns,
        split=match.group("split").decode("utf-8"),
        weight=float(match.group("weight")),
        sigma=float(match.group("sigma")),
        fingerprint=match.group("fingerprint").decode("ascii"),
        schema_version=match.group("schema").decode("utf-8"),
    )
    if metadata.schema_version != H1_SCHEMA_VERSION:
        raise ExperimentConfigurationError(
            f"unexpected H1 cache schema {metadata.schema_version!r}: {cache_path}"
        )
    return metadata


def sha256_file(path: str | Path, *, chunk_bytes: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with _resolved(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_bytes), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_stable_file(
    path: str | Path,
    *,
    chunk_bytes: int = 4 * 1024 * 1024,
    expected_size_bytes: int | None = None,
    expected_mtime_ns: int | None = None,
) -> str:
    """Hash an immutable input and reject a size/mtime change during the pass."""

    resolved = _resolved(path)
    before = resolved.stat()
    if expected_size_bytes is not None and before.st_size != expected_size_bytes:
        raise ExperimentConfigurationError(
            f"input size changed before hashing: {resolved}"
        )
    if expected_mtime_ns is not None and before.st_mtime_ns != expected_mtime_ns:
        raise ExperimentConfigurationError(
            f"input mtime changed before hashing: {resolved}"
        )
    digest = sha256_file(resolved, chunk_bytes=chunk_bytes)
    after = resolved.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise ExperimentConfigurationError(f"input changed while being hashed: {resolved}")
    return digest


def read_dates(path: str | Path) -> tuple[str, ...]:
    date_path = _resolved(path)
    if not date_path.is_file():
        raise ExperimentConfigurationError(f"date manifest is missing: {date_path}")
    if date_path.stat().st_size > MAX_DATE_MANIFEST_BYTES:
        raise ExperimentConfigurationError(f"date manifest exceeds size bound: {date_path}")
    dates = tuple(
        line.strip()
        for line in date_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    if not dates or len(dates) != len(set(dates)):
        raise ExperimentConfigurationError(
            f"date manifest must contain unique nonempty dates: {date_path}"
        )
    parsed = []
    for value in dates:
        try:
            parsed.append(datetime.strptime(value, "%Y-%m-%d").date())
        except ValueError as exc:
            raise ExperimentConfigurationError(
                f"invalid date {value!r} in {date_path}"
            ) from exc
    if parsed != sorted(parsed):
        raise ExperimentConfigurationError(f"dates are not sorted: {date_path}")
    return dates


def _weight_token(weight: float) -> str:
    return f"{float(weight):.2f}".replace(".", "p")


def load_h1_selection(
    path: str | Path,
    *,
    tune_dates: Sequence[str],
    holdout_dates: Sequence[str],
    allow_blocked_tune_only: bool = False,
) -> dict[str, Any]:
    """Validate H1 selection before constructing any cache path.

    The normal mode requires a completely passed H1 result and its exact
    selected/incumbent holdout-arm gate.  ``allow_blocked_tune_only`` is a
    deliberately narrower research mode: H1 must be BLOCK, tune must be BLOCK,
    and holdout must be NOT_TOUCHED with no holdout arm gates.  That mode can
    consume finalized tune caches only and can never be upgraded into holdout
    evidence by the caller.
    """

    result_path = _resolved(path)
    if not result_path.is_file():
        raise ExperimentConfigurationError(f"H1 result is missing: {result_path}")
    initial_result_stat = result_path.stat()
    if initial_result_stat.st_size > MAX_H1_RESULT_BYTES:
        raise ExperimentConfigurationError(f"H1 result exceeds size bound: {result_path}")
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentConfigurationError(f"cannot read H1 result: {result_path}") from exc
    blockers = []
    if payload.get("schema_version") != H1_SCHEMA_VERSION:
        blockers.append(f"schema is {payload.get('schema_version')!r}, not {H1_SCHEMA_VERSION!r}")
    expected_h1_status = "BLOCK" if allow_blocked_tune_only else "COMPLETE"
    if payload.get("status") != expected_h1_status:
        blockers.append(
            f"H1 status is {payload.get('status')!r}, not {expected_h1_status}"
        )
    experiment = payload.get("experiment") or {}
    if experiment.get("selection_uses_holdout") is not False:
        blockers.append("H1 does not attest tune-only selection")
    tune = payload.get("tune") or {}
    holdout = payload.get("holdout") or {}
    expected_tune_status = "BLOCK" if allow_blocked_tune_only else "PASS"
    expected_holdout_status = "NOT_TOUCHED" if allow_blocked_tune_only else "PASS"
    if tune.get("status") != expected_tune_status:
        blockers.append(
            f"H1 tune status is {tune.get('status')!r}, not {expected_tune_status}"
        )
    if holdout.get("status") != expected_holdout_status:
        blockers.append(
            "H1 holdout status is "
            f"{holdout.get('status')!r}, not {expected_holdout_status}"
        )
    split = payload.get("split") or {}
    if tuple(split.get("tune_dates") or ()) != tuple(tune_dates):
        blockers.append("H1 tune dates do not exactly match the predeclared manifest")
    if tuple(split.get("holdout_dates") or ()) != tuple(holdout_dates):
        blockers.append("H1 holdout dates do not exactly match the predeclared manifest")
    overlap = sorted(set(tune_dates) & set(holdout_dates))
    if overlap:
        blockers.append(f"tune and holdout date manifests overlap: {overlap}")
    selected_raw = tune.get("selected_weights") or {}
    selected: dict[str, float] = {}
    allowed_weights = {0.0, 0.10, 0.25, 0.50, 0.75, 1.0}
    for unit in UNITS:
        try:
            weight = float(selected_raw[unit])
        except (KeyError, TypeError, ValueError):
            blockers.append(f"H1 has no valid selected weight for {unit}")
            continue
        if weight not in allowed_weights:
            blockers.append(f"H1 selected weight {weight} for {unit} is outside the fixed grid")
        selected[unit] = weight
    selection_details = tune.get("selection") or {}
    if not isinstance(selection_details, Mapping):
        blockers.append("H1 tune selection is not an object")
        selection_details = {}
    for unit, weight in selected.items():
        detail = selection_details.get(unit)
        try:
            detail_weight = float(detail["selected_weight"])
        except (KeyError, TypeError, ValueError):
            blockers.append(f"H1 tune selection has no valid selected weight for {unit}")
            continue
        if detail_weight != weight:
            blockers.append(
                f"H1 selected-weight records disagree for {unit}: "
                f"summary={weight}, selection={detail_weight}"
            )
    expected_holdout_weights = (
        set()
        if allow_blocked_tune_only
        else {0.0} | {weight for weight in selected.values() if weight > 0.0}
    )
    holdout_gates = holdout.get("arm_gates") or {}
    if not isinstance(holdout_gates, Mapping):
        blockers.append("H1 holdout arm_gates is not an object")
        holdout_gates = {}
    holdout_gate_by_weight: dict[float, Any] = {}
    for value, gate in holdout_gates.items():
        try:
            weight = float(value)
        except (TypeError, ValueError):
            blockers.append(f"H1 holdout arm gate has a nonnumeric weight: {value!r}")
            continue
        if weight in holdout_gate_by_weight:
            blockers.append(f"H1 holdout has duplicate numeric arm gate {weight}")
        holdout_gate_by_weight[weight] = gate
    actual_holdout_weights = set(holdout_gate_by_weight)
    if actual_holdout_weights != expected_holdout_weights:
        blockers.append(
            "H1 holdout arm set does not match the permitted evidence mode: "
            f"expected={sorted(expected_holdout_weights)}, "
            f"actual={sorted(actual_holdout_weights)}"
        )
    if not allow_blocked_tune_only:
        for weight in sorted(expected_holdout_weights):
            gate = holdout_gate_by_weight.get(weight)
            if not isinstance(gate, Mapping) or gate.get("status") != "PASS":
                blockers.append(
                    f"H1 holdout arm gate {weight} is not individually PASS"
                )

        tune_gates = tune.get("arm_gates") or {}
        if not isinstance(tune_gates, Mapping):
            blockers.append("H1 tune arm_gates is not an object")
            tune_gates = {}
        tune_gate_by_weight: dict[float, Any] = {}
        for value, gate in tune_gates.items():
            try:
                weight = float(value)
            except (TypeError, ValueError):
                blockers.append(
                    f"H1 tune arm gate has a nonnumeric weight: {value!r}"
                )
                continue
            if weight in tune_gate_by_weight:
                blockers.append(f"H1 tune has duplicate numeric arm gate {weight}")
            tune_gate_by_weight[weight] = gate
        selected_tune_weights = {0.0} | set(selected.values())
        for weight in sorted(selected_tune_weights):
            gate = tune_gate_by_weight.get(weight)
            if not isinstance(gate, Mapping) or gate.get("status") != "PASS":
                blockers.append(
                    f"H1 tune arm gate {weight} is not individually PASS"
                )
    technical_blockers = list(payload.get("technical_blockers") or tune.get("blockers") or [])
    if allow_blocked_tune_only and not technical_blockers:
        blockers.append("blocked tune-only mode requires recorded H1 technical blockers")
    if not allow_blocked_tune_only and technical_blockers:
        blockers.append(
            f"complete H1 result still records {len(technical_blockers)} technical blockers"
        )
    if blockers:
        raise ExperimentConfigurationError("; ".join(blockers))
    return {
        "path": str(result_path),
        "sha256": sha256_stable_file(
            result_path,
            expected_size_bytes=initial_result_stat.st_size,
            expected_mtime_ns=initial_result_stat.st_mtime_ns,
        ),
        "payload": payload,
        "selected_weights": selected,
        "evidence_mode": (
            "BLOCKED_TUNE_ONLY" if allow_blocked_tune_only else "COMPLETE_HOLDOUT"
        ),
        "technical_blockers": technical_blockers,
    }


def validate_path_contract(
    *,
    h1_result: str | Path,
    cache_root: str | Path,
    tune_dates_file: str | Path,
    holdout_dates_file: str | Path,
    output_root: str | Path,
    report_out: str | Path,
    historical_hourly_json: str | Path | None = None,
    read_only_roots: Iterable[str | Path] = (),
) -> dict[str, Path]:
    """Resolve paths and prohibit every output below cache/data inputs."""

    read_only_root_values = tuple(read_only_roots)
    if not read_only_root_values:
        raise ExperimentConfigurationError(
            "at least one explicit read-only data root is required"
        )

    paths = {
        "h1_result": _resolved(h1_result),
        "cache_root": _resolved(cache_root),
        "tune_dates_file": _resolved(tune_dates_file),
        "holdout_dates_file": _resolved(holdout_dates_file),
        "output_root": _resolved(output_root),
        "report_out": _resolved(report_out),
    }
    if historical_hourly_json:
        paths["historical_hourly_json"] = _resolved(historical_hourly_json)
    for key in ("h1_result", "tune_dates_file", "holdout_dates_file"):
        if not paths[key].is_file():
            raise ExperimentConfigurationError(f"required input {key} is missing: {paths[key]}")
    if "historical_hourly_json" in paths and not paths["historical_hourly_json"].is_file():
        raise ExperimentConfigurationError(
            f"historical hourly input is missing: {paths['historical_hourly_json']}"
        )
    if not paths["cache_root"].is_dir():
        raise ExperimentConfigurationError(f"cache root is missing: {paths['cache_root']}")
    protected = {paths["cache_root"]}
    resolved_read_only_roots = {
        _resolved(root) for root in read_only_root_values
    }
    for root in resolved_read_only_roots:
        if not root.is_dir():
            raise ExperimentConfigurationError(
                f"read-only data root is missing: {root}"
            )
    protected.update(resolved_read_only_roots)
    for output_key in ("output_root", "report_out"):
        output = paths[output_key]
        for root in protected:
            if _is_within(output, root):
                raise ExperimentConfigurationError(
                    f"{output_key} must be outside read-only/cache root {root}: {output}"
                )
    if _is_within(paths["report_out"], paths["output_root"]):
        raise ExperimentConfigurationError(
            "tracked report must be outside the untracked analysis output root"
        )
    if paths["output_root"].exists():
        if not paths["output_root"].is_dir() or any(paths["output_root"].iterdir()):
            raise ExperimentConfigurationError(
                f"refusing to reuse nonempty/non-directory output root: {paths['output_root']}"
            )
    if paths["report_out"].exists():
        raise ExperimentConfigurationError(
            f"refusing to overwrite tracked report: {paths['report_out']}"
        )
    return paths


def load_historical_hourly_context(path: str | Path) -> dict[str, Any]:
    from weather.reporting.research.current_replay_time_frontier_history import (
        load_historical_hourly_context as implementation,
    )

    return implementation(path)


def build_cache_plan(
    *,
    cache_root: str | Path,
    selected_weights: Mapping[str, float],
    splits: Sequence[str] = ("tune", "holdout"),
) -> dict[str, dict[str, Path]]:
    """Construct, without directory discovery, only the allowed cache paths."""

    root = _resolved(cache_root)
    plan: dict[str, dict[str, Path]] = {}
    requested_splits = tuple(splits)
    if not requested_splits or len(set(requested_splits)) != len(requested_splits):
        raise ExperimentConfigurationError("cache plan splits must be unique and nonempty")
    if not set(requested_splits) <= {"tune", "holdout"}:
        raise ExperimentConfigurationError(
            f"cache plan contains an unsupported split: {requested_splits}"
        )
    for split in requested_splits:
        split_plan: dict[str, Path] = {
            "0.0": root / f"{split}-weight-{_weight_token(0.0)}.json"
        }
        for weight in sorted({float(value) for value in selected_weights.values()}):
            if weight > 0.0:
                split_plan[str(weight)] = root / (
                    f"{split}-weight-{_weight_token(weight)}.json"
                )
        for path in split_plan.values():
            resolved = path.resolve()
            if not _is_within(resolved, root):
                raise ExperimentConfigurationError(f"cache escaped root: {resolved}")
            if not resolved.is_file():
                raise ExperimentConfigurationError(f"selected cache is missing: {resolved}")
        plan[split] = split_plan
    return plan


def validate_cache_plan(
    plan: Mapping[str, Mapping[str, Path]],
) -> dict[str, CacheMetadata]:
    metadata: dict[str, CacheMetadata] = {}
    if not plan:
        raise ExperimentConfigurationError("cache plan is empty")
    for split, split_plan in plan.items():
        if split not in {"tune", "holdout"}:
            raise ExperimentConfigurationError(f"unsupported cache-plan split: {split}")
        for weight_key, path in split_plan.items():
            weight = float(weight_key)
            item = read_cache_metadata(path)
            if item.split != split or item.weight != weight:
                raise ExperimentConfigurationError(
                    f"cache metadata mismatch for {path}: "
                    f"split={item.split}, weight={item.weight}"
                )
            identity = f"{split}:{weight}"
            metadata[identity] = item
    fingerprints = [item.fingerprint for item in metadata.values()]
    if len(fingerprints) != len(set(fingerprints)):
        raise ExperimentConfigurationError("selected cache fingerprints are not unique")
    return metadata


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


def _snapshot_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("market_id"),
        row.get("target_date"),
        row.get("snapshot_id"),
        row.get("captured_at_local"),
    )


def _float_field(row: Mapping[str, Any], field: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise ExperimentConfigurationError(
            f"missing/non-numeric replay field {field!r} for key {_row_key(row)!r}"
        ) from exc
    if not math.isfinite(value):
        raise ExperimentConfigurationError(
            f"non-finite replay field {field!r} for key {_row_key(row)!r}"
        )
    return value


def _outcome(row: Mapping[str, Any]) -> int:
    value = _float_field(row, "outcome")
    if value not in (0.0, 1.0):
        raise ExperimentConfigurationError(f"outcome is not binary for {_row_key(row)!r}")
    return int(value)


def _brier(probability: float, outcome: int) -> float:
    return (probability - outcome) ** 2


def _logloss(probability: float, outcome: int) -> float:
    probability = max(LOG_LOSS_EPSILON, min(1.0 - LOG_LOSS_EPSILON, probability))
    return -(
        outcome * math.log(probability)
        + (1 - outcome) * math.log(1.0 - probability)
    )


def _capture_minute_of_day(row: Mapping[str, Any]) -> int:
    minute = row.get("capture_minute")
    if minute is not None:
        try:
            value = int(minute)
        except (TypeError, ValueError) as exc:
            raise ExperimentConfigurationError(
                f"invalid capture_minute for {_row_key(row)!r}"
            ) from exc
        if 0 <= value < 24 * 60:
            return value
    captured = str(row.get("captured_at_local") or "")
    try:
        parsed = datetime.fromisoformat(captured.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExperimentConfigurationError(
            f"invalid captured_at_local for {_row_key(row)!r}: {captured!r}"
        ) from exc
    return parsed.hour * 60 + parsed.minute


def _capture_hour(row: Mapping[str, Any]) -> int:
    return _capture_minute_of_day(row) // 60


def _unit_rows(rows: Iterable[Mapping[str, Any]], unit: str) -> Iterator[dict[str, Any]]:
    for row in rows:
        if str(row.get("unit") or "").upper() == unit:
            yield dict(row)


def _canonical_equal(left: Any, right: Any) -> bool:
    """NaN-safe equality matching the sealed H1 scoring contract."""

    return json.dumps(
        left, sort_keys=True, separators=(",", ":"), default=str
    ) == json.dumps(right, sort_keys=True, separators=(",", ":"), default=str)


def _scoring_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: row.get(field)
        for field in ("replayed_p", "outcome", "market_yes", "unit")
    }


def aligned_row_pairs(
    current_rows: Iterable[Mapping[str, Any]],
    selected_rows: Iterable[Mapping[str, Any]] | None,
) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """Merge identical-order H1 rows and fail closed on any misalignment."""

    if selected_rows is None:
        for row in current_rows:
            item = dict(row)
            yield item, item
        return
    sentinel = object()
    for left, right in zip_longest(current_rows, selected_rows, fillvalue=sentinel):
        if left is sentinel or right is sentinel:
            raise ExperimentConfigurationError("selected/current cache row counts differ")
        left_row = dict(left)
        right_row = dict(right)
        left_key = _row_key(left_row)
        right_key = _row_key(right_row)
        if left_key != right_key:
            raise ExperimentConfigurationError(
                f"selected/current cache alignment mismatch: {left_key!r} != {right_key!r}"
            )
        for field in ("unit", "outcome", "market_yes"):
            if left_row.get(field) != right_row.get(field):
                raise ExperimentConfigurationError(
                    f"selected/current immutable field {field!r} differs at {left_key!r}"
                )
        yield left_row, right_row


def aligned_selected_row_pairs(
    current_rows: Iterable[Mapping[str, Any]],
    candidate_rows_by_weight: Mapping[float, Iterable[Mapping[str, Any]]],
    selected_weights: Mapping[str, float],
    diagnostics: MutableMapping[str, Any] | None = None,
) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """Align every distinct selected arm once and route its row by native unit.

    All H1 arms replay the same corpus.  Advancing their iterators in lockstep
    avoids rescanning the multi-gigabyte incumbent separately for C and F while
    preserving an exact fail-closed identity comparison for every row.
    """

    weights = sorted(float(weight) for weight in candidate_rows_by_weight)
    streams = [iter(current_rows)] + [iter(candidate_rows_by_weight[weight]) for weight in weights]
    sentinel = object()
    first_scoring_projection: dict[
        tuple[Any, ...], tuple[dict[str, Any], ...]
    ] = {}
    raw_rows = 0
    duplicate_rows = 0
    duplicate_market_dates: set[tuple[str, str]] = set()
    for values in zip_longest(*streams, fillvalue=sentinel):
        raw_rows += 1
        if any(value is sentinel for value in values):
            raise ExperimentConfigurationError(
                "selected/current cache row counts differ in multi-arm alignment"
            )
        current = dict(values[0])
        current_key = _row_key(current)
        candidates: dict[float, dict[str, Any]] = {}
        for weight, source in zip(weights, values[1:]):
            candidate = dict(source)
            candidate_key = _row_key(candidate)
            if candidate_key != current_key:
                raise ExperimentConfigurationError(
                    "selected/current cache alignment mismatch for weight "
                    f"{weight}: {current_key!r} != {candidate_key!r}"
                )
            for field in ("unit", "outcome", "market_yes"):
                if not _canonical_equal(current.get(field), candidate.get(field)):
                    raise ExperimentConfigurationError(
                        f"selected/current immutable field {field!r} differs at "
                        f"{current_key!r} for weight {weight}"
                    )
            candidates[weight] = candidate
        projections = tuple(
            [_scoring_projection(current)]
            + [_scoring_projection(candidates[weight]) for weight in weights]
        )
        if current_key in first_scoring_projection:
            duplicate_rows += 1
            duplicate_market_dates.add(
                (str(current.get("market_id") or ""), str(current.get("target_date") or ""))
            )
            if not _canonical_equal(first_scoring_projection[current_key], projections):
                raise ExperimentConfigurationError(
                    f"conflicting duplicate comparison key: {current_key!r}"
                )
            # The H1 contract keeps the first occurrence when every score input
            # is canonically identical. Non-scoring fields such as recorded_p
            # are intentionally irrelevant to current-code replay scoring.
            continue
        if len(first_scoring_projection) >= MAX_ALIGNMENT_KEYS:
            raise ExperimentConfigurationError(
                f"alignment key count exceeds bound {MAX_ALIGNMENT_KEYS}"
            )
        first_scoring_projection[current_key] = projections
        unit = str(current.get("unit") or "").upper()
        if unit not in selected_weights:
            raise ExperimentConfigurationError(
                f"cache row has an unsupported native unit {unit!r}: {current_key!r}"
            )
        selected_weight = float(selected_weights[unit])
        selected = current if selected_weight == 0.0 else candidates.get(selected_weight)
        if selected is None:
            raise ExperimentConfigurationError(
                f"selected cache weight {selected_weight} was not opened for unit {unit}"
            )
        yield current, selected
    if diagnostics is not None:
        diagnostics.update(
            {
                "raw_rows": raw_rows,
                "unique_rows": len(first_scoring_projection),
                "equivalent_duplicate_rows_collapsed": duplicate_rows,
                "duplicate_market_dates": [
                    {"market_id": market_id, "target_date": target_date}
                    for market_id, target_date in sorted(duplicate_market_dates)
                ],
                "key_bound": MAX_ALIGNMENT_KEYS,
                "key_fields": [
                    "market_id",
                    "target_date",
                    "snapshot_id",
                    "captured_at_local",
                    "band",
                    "bin_type",
                    "bin_value_c",
                    "bin_value_hi",
                ],
                "duplicate_equivalence_fields": [
                    "replayed_p",
                    "outcome",
                    "market_yes",
                    "unit",
                ],
                "non_scoring_fields_ignored": ["recorded_p"],
                "policy": "KEEP_FIRST_ONLY_IF_CANONICALLY_SCORE_EQUIVALENT",
            }
        )


def iter_snapshot_scores(
    row_pairs: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]]
) -> Iterator[dict[str, Any]]:
    """Collapse aligned band rows to one equal-weight scoring observation."""

    current_key: tuple[Any, ...] | None = None
    state: dict[str, Any] | None = None

    def finish(snapshot: MutableMapping[str, Any]) -> dict[str, Any]:
        bands = int(snapshot["band_rows"])
        if bands <= 0 or snapshot["winner_rows"] != 1:
            raise ExperimentConfigurationError(
                f"snapshot must have exactly one winning band: {snapshot['snapshot_key']!r}"
            )
        for model in MODEL_NAMES:
            mass = snapshot[f"{model}_probability_mass"]
            if model != "market" and abs(mass - 1.0) > 1e-6:
                raise ExperimentConfigurationError(
                    f"{model} probability mass {mass} is not one for "
                    f"{snapshot['snapshot_key']!r}"
                )
            snapshot[f"{model}_brier"] /= bands
            snapshot[f"{model}_logloss"] /= bands
        return dict(snapshot)

    for current, selected in row_pairs:
        key = _snapshot_key(current)
        if current_key != key:
            if state is not None:
                yield finish(state)
            current_key = key
            state = {
                "snapshot_key": key,
                "market_id": str(current.get("market_id") or ""),
                "unit": str(current.get("unit") or "").upper(),
                "target_date": str(current.get("target_date") or ""),
                "snapshot_id": str(current.get("snapshot_id") or ""),
                "captured_at_local": str(current.get("captured_at_local") or ""),
                "hour": _capture_hour(current),
                "capture_minute": _capture_minute_of_day(current),
                "band_rows": 0,
                "winner_rows": 0,
            }
            for model in MODEL_NAMES:
                state[f"{model}_brier"] = 0.0
                state[f"{model}_logloss"] = 0.0
                state[f"{model}_winner_probability"] = 0.0
                state[f"{model}_probability_mass"] = 0.0
        assert state is not None
        outcome = _outcome(current)
        probabilities = {
            "current": _float_field(current, "replayed_p"),
            "selected": _float_field(selected, "replayed_p"),
            "market": _float_field(current, "market_yes"),
        }
        for model, probability in probabilities.items():
            if not 0.0 <= probability <= 1.0:
                raise ExperimentConfigurationError(
                    f"{model} probability is outside [0,1] at {_row_key(current)!r}"
                )
            state[f"{model}_brier"] += _brier(probability, outcome)
            state[f"{model}_logloss"] += _logloss(probability, outcome)
            state[f"{model}_probability_mass"] += probability
            if outcome:
                state[f"{model}_winner_probability"] = probability
        state["band_rows"] += 1
        state["winner_rows"] += outcome
    if state is not None:
        yield finish(state)


def _scope_ids(hour: int, capture_minute: int | None = None) -> tuple[str, ...]:
    scopes = ["all_hours", f"hour_{hour:02d}"]
    if hour in PREDAWN_HOURS:
        scopes.append("predawn_03_05")
        if capture_minute is not None:
            slot_minute = (capture_minute // 10) * 10
            scopes.append(
                f"ten_minute_{slot_minute // 60:02d}{slot_minute % 60:02d}"
            )
    if hour in EVENING_HOURS:
        scopes.append("evening_15_23")
    return tuple(scopes)


def _metric_fields() -> tuple[str, ...]:
    return tuple(f"{model}_{metric}" for model in MODEL_NAMES for metric in METRIC_NAMES)


SCORE_FIELDS = _metric_fields()


def aggregate_market_dates(
    snapshots: Iterable[Mapping[str, Any]], *, split: str, selected_weight: float
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Average snapshots within market-date/scope, never across raw row density."""

    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    observed_dates: set[str] = set()
    maximum_bands = 0
    snapshot_count = 0
    band_rows = 0
    maximum_current_mass_error = 0.0
    maximum_selected_mass_error = 0.0
    market_mass_minimum = math.inf
    market_mass_maximum = -math.inf
    market_mass_total = 0.0
    for snapshot in snapshots:
        market_id = str(snapshot["market_id"])
        target_date = str(snapshot["target_date"])
        observed_dates.add(target_date)
        snapshot_count += 1
        band_rows += int(snapshot["band_rows"])
        maximum_bands = max(maximum_bands, int(snapshot["band_rows"]))
        maximum_current_mass_error = max(
            maximum_current_mass_error,
            abs(float(snapshot.get("current_probability_mass", 1.0)) - 1.0),
        )
        maximum_selected_mass_error = max(
            maximum_selected_mass_error,
            abs(float(snapshot.get("selected_probability_mass", 1.0)) - 1.0),
        )
        market_mass = float(snapshot.get("market_probability_mass", 1.0))
        market_mass_minimum = min(market_mass_minimum, market_mass)
        market_mass_maximum = max(market_mass_maximum, market_mass)
        market_mass_total += market_mass
        capture_minute = snapshot.get("capture_minute")
        for scope in _scope_ids(
            int(snapshot["hour"]),
            int(capture_minute) if capture_minute is not None else None,
        ):
            key = (str(snapshot["unit"]), market_id, target_date, scope)
            group = groups.get(key)
            if group is None:
                if len(groups) >= MAX_AGGREGATE_GROUPS:
                    raise ExperimentConfigurationError(
                        f"market-date aggregation exceeds {MAX_AGGREGATE_GROUPS} groups"
                    )
                group = {
                    "schema_version": SCHEMA_VERSION,
                    "split": split,
                    "unit": snapshot["unit"],
                    "market_id": market_id,
                    "target_date": target_date,
                    "scope": scope,
                    "selected_weight": float(selected_weight),
                    "snapshots": 0,
                    "band_rows": 0,
                }
                for field in SCORE_FIELDS:
                    group[field] = 0.0
                groups[key] = group
            group["snapshots"] += 1
            group["band_rows"] += int(snapshot["band_rows"])
            for field in SCORE_FIELDS:
                group[field] += float(snapshot[field])
    rows = []
    for key in sorted(groups):
        group = groups[key]
        n = int(group["snapshots"])
        for field in SCORE_FIELDS:
            group[field] /= n
        rows.append(group)
    diagnostics = {
        "observed_dates": sorted(observed_dates),
        "snapshots": snapshot_count,
        "band_rows": band_rows,
        "market_date_scope_rows": len(rows),
        "maximum_bands_per_snapshot": maximum_bands,
        "probability_mass": {
            "maximum_current_error": maximum_current_mass_error,
            "maximum_selected_error": maximum_selected_mass_error,
            "market_mass_minimum": market_mass_minimum if snapshot_count else None,
            "market_mass_mean": market_mass_total / snapshot_count if snapshot_count else None,
            "market_mass_maximum": market_mass_maximum if snapshot_count else None,
            "market_mass_was_normalized": False,
        },
    }
    return rows, diagnostics


def build_fleet_date_rows(market_date_rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Average market-date metrics across markets, then expose one fleet-date row."""

    groups: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in market_date_rows:
        key = (
            str(row["split"]),
            str(row["unit"]),
            str(row["target_date"]),
            str(row["scope"]),
        )
        if key not in groups and len(groups) >= MAX_AGGREGATE_GROUPS:
            raise ExperimentConfigurationError(
                f"fleet-date aggregation exceeds {MAX_AGGREGATE_GROUPS} groups"
            )
        groups[key].append(row)
    output = []
    for key in sorted(groups):
        split, unit, target_date, scope = key
        rows = groups[key]
        result = {
            "schema_version": SCHEMA_VERSION,
            "split": split,
            "unit": unit,
            "market_id": "__fleet__",
            "target_date": target_date,
            "scope": scope,
            "selected_weight": rows[0]["selected_weight"],
            "markets": len(rows),
            "snapshots": sum(int(row["snapshots"]) for row in rows),
            "band_rows": sum(int(row["band_rows"]) for row in rows),
        }
        for field in SCORE_FIELDS:
            result[field] = sum(float(row[field]) for row in rows) / len(rows)
        output.append(result)
    return output


def configured_markets_by_unit(
    registry: Mapping[str, Any] = REGISTRY,
) -> dict[str, tuple[str, ...]]:
    """Freeze the configured 12-market panel by native settlement unit."""

    output: dict[str, list[str]] = {unit: [] for unit in UNITS}
    for market_id, spec in registry.items():
        unit = str(getattr(spec, "display_unit", "")).upper()
        if unit not in output:
            raise ExperimentConfigurationError(
                f"configured market {market_id!r} has unsupported unit {unit!r}"
            )
        output[unit].append(str(market_id))
    frozen = {unit: tuple(sorted(markets)) for unit, markets in output.items()}
    if any(not markets for markets in frozen.values()):
        raise ExperimentConfigurationError(
            f"configured native-unit panel is empty for a unit: {frozen}"
        )
    if sum(len(markets) for markets in frozen.values()) != 12:
        raise ExperimentConfigurationError(
            "time-frontier strict sensitivity requires the configured 12-market "
            f"registry, got {frozen}"
        )
    return frozen


def build_complete_panel_fleet_date_rows(
    market_date_rows: Sequence[Mapping[str, Any]],
    *,
    configured: Mapping[str, Sequence[str]],
    splits: Sequence[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep only date/slot groups containing every configured market for its unit.

    This is an explicit coverage sensitivity.  It never imputes a missing city,
    carries a partial panel forward, or replaces the available-case primary.
    """

    expected = {
        unit: tuple(sorted(str(value) for value in configured.get(unit, ())))
        for unit in UNITS
    }
    if any(not values for values in expected.values()):
        raise ExperimentConfigurationError(
            f"complete-panel sensitivity has an empty native-unit panel: {expected}"
        )
    scope_ids = (
        "all_hours",
        "predawn_03_05",
        "evening_15_23",
        *(f"hour_{hour:02d}" for hour in HOURS),
        *(
            f"ten_minute_{hour:02d}{minute:02d}"
            for hour in PREDAWN_HOURS
            for minute in range(0, 60, 10)
        ),
    )
    observed_splits = tuple(
        sorted(set(str(row["split"]) for row in market_date_rows))
    )
    requested_splits = tuple(splits) if splits is not None else observed_splits
    diagnostic_index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for split in requested_splits:
        for unit in UNITS:
            for scope in scope_ids:
                diagnostic_index[(split, unit, scope)] = {
                    "schema_version": SCHEMA_VERSION,
                    "split": split,
                    "unit": unit,
                    "scope": scope,
                    "configured_markets": list(expected[unit]),
                    "configured_market_count": len(expected[unit]),
                    "available_case_fleet_dates": 0,
                    "complete_panel_fleet_dates": 0,
                    "dropped_incomplete_fleet_dates": 0,
                    "complete_target_dates": [],
                    "incomplete_target_dates": [],
                    "imputation_used": False,
                }

    groups: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in market_date_rows:
        key = (
            str(row["split"]),
            str(row["unit"]),
            str(row["target_date"]),
            str(row["scope"]),
        )
        groups[key].append(row)

    complete_market_rows: list[Mapping[str, Any]] = []
    for (split, unit, target_date, scope), rows in sorted(groups.items()):
        if unit not in expected:
            raise ExperimentConfigurationError(
                f"complete-panel row has unsupported unit {unit!r}"
            )
        diagnostic = diagnostic_index.get((split, unit, scope))
        if diagnostic is None:
            raise ExperimentConfigurationError(
                f"complete-panel row has undeclared split/scope: {split}/{unit}/{scope}"
            )
        by_market = {str(row["market_id"]): row for row in rows}
        if len(by_market) != len(rows):
            raise ExperimentConfigurationError(
                f"duplicate market-date row in complete-panel group: "
                f"{split}/{unit}/{target_date}/{scope}"
            )
        observed = set(by_market)
        expected_set = set(expected[unit])
        extra = sorted(observed - expected_set)
        if extra:
            raise ExperimentConfigurationError(
                f"unconfigured markets in {split}/{unit}/{target_date}/{scope}: {extra}"
            )
        diagnostic["available_case_fleet_dates"] += 1
        if observed == expected_set:
            diagnostic["complete_panel_fleet_dates"] += 1
            diagnostic["complete_target_dates"].append(target_date)
            complete_market_rows.extend(rows)
        else:
            diagnostic["dropped_incomplete_fleet_dates"] += 1
            diagnostic["incomplete_target_dates"].append(
                {
                    "target_date": target_date,
                    "observed_market_count": len(observed),
                    "observed_markets": sorted(observed),
                    "missing_markets": sorted(expected_set - observed),
                }
            )

    fleet_rows = build_fleet_date_rows(complete_market_rows)
    for row in fleet_rows:
        row["panel_scope"] = "COMPLETE_CONFIGURED_NATIVE_UNIT_PANEL"
        row["configured_markets"] = list(expected[str(row["unit"])])
        row["configured_market_count"] = len(expected[str(row["unit"])])
    diagnostics = [diagnostic_index[key] for key in sorted(diagnostic_index)]
    return fleet_rows, diagnostics


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def _derived_seed(*parts: Any) -> int:
    digest = hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).digest()
    return BOOTSTRAP_SEED + int.from_bytes(digest[:4], "big")


def cluster_bootstrap_ci(
    values: Iterable[float],
    *,
    seed: int,
    replicates: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    """Paired bootstrap over fleet dates with a small bounded vectorized fast path."""

    observations = [float(value) for value in values]
    if not observations:
        return {"low": None, "high": None, "replicates": replicates, "seed": seed}
    if all(value == observations[0] for value in observations):
        return {
            "low": observations[0],
            "high": observations[0],
            "replicates": int(replicates),
            "seed": int(seed),
        }
    array = np.asarray(observations, dtype=float)
    rng = np.random.default_rng(int(seed))
    indices = rng.integers(0, len(array), size=(int(replicates), len(array)))
    estimates = array[indices].mean(axis=1)
    low, high = np.quantile(estimates, [0.025, 0.975], method="linear")
    return {
        "low": float(low),
        "high": float(high),
        "replicates": int(replicates),
        "seed": int(seed),
    }


def paired_sign_test(values: Iterable[float], *, lower_is_better: bool) -> dict[str, Any]:
    values = [float(value) for value in values]
    favorable = sum(value < 0.0 if lower_is_better else value > 0.0 for value in values)
    unfavorable = sum(value > 0.0 if lower_is_better else value < 0.0 for value in values)
    ties = len(values) - favorable - unfavorable
    n = favorable + unfavorable
    if n:
        tail = min(favorable, unfavorable)
        p_value = min(1.0, 2.0 * sum(math.comb(n, k) for k in range(tail + 1)) / (2.0**n))
    else:
        p_value = 1.0
    return {
        "favorable": favorable,
        "unfavorable": unfavorable,
        "ties": ties,
        "non_ties": n,
        "two_sided_p": p_value,
        "favorable_direction": "negative" if lower_is_better else "positive",
    }


def summarize_equal_weight_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    split: str,
    unit: str,
    market_id: str,
    scope: str,
    selected_weight: float,
) -> dict[str, Any]:
    rows = list(rows)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "split": split,
        "evidence_role": "EXPLORATORY_SELECTION_CONTEXT" if split == "tune" else "UNTOUCHED_HOLDOUT",
        "unit": unit,
        "market_id": market_id,
        "scope": scope,
        "panel_scope": (
            str(rows[0].get("panel_scope"))
            if rows and rows[0].get("panel_scope")
            else (
                "AVAILABLE_CASE_EQUAL_MARKET_FLEET"
                if market_id == "__fleet__"
                else "PER_MARKET"
            )
        ),
        "selected_weight": float(selected_weight),
        "fleet_dates": len(rows),
        "markets": len({str(row.get("market_id")) for row in rows if row.get("market_id") != "__fleet__"})
        if market_id != "__fleet__"
        else max((int(row.get("markets", 0)) for row in rows), default=0),
        "snapshots": sum(int(row.get("snapshots", 0)) for row in rows),
        "band_rows": sum(int(row.get("band_rows", 0)) for row in rows),
        "market_coverage_per_fleet_date": {
            "minimum": min(
                (int(row.get("markets", 1)) for row in rows), default=0
            )
            if market_id == "__fleet__"
            else 1,
            "mean": _mean(
                int(row.get("markets", 1)) for row in rows
            )
            if market_id == "__fleet__"
            else 1.0,
            "maximum": max(
                (int(row.get("markets", 1)) for row in rows), default=0
            )
            if market_id == "__fleet__"
            else 1,
        },
        "snapshots_per_fleet_date": {
            "minimum": min((int(row.get("snapshots", 0)) for row in rows), default=0),
            "mean": _mean(int(row.get("snapshots", 0)) for row in rows),
            "maximum": max((int(row.get("snapshots", 0)) for row in rows), default=0),
        },
        "metrics": {},
        "selected_vs_current": {},
    }
    for model in MODEL_NAMES:
        result["metrics"][model] = {
            metric: _mean(float(row[f"{model}_{metric}"]) for row in rows)
            for metric in METRIC_NAMES
        }
    for metric in METRIC_NAMES:
        deltas = [
            float(row[f"selected_{metric}"]) - float(row[f"current_{metric}"])
            for row in rows
        ]
        lower_is_better = metric != "winner_probability"
        result["selected_vs_current"][metric] = {
            "mean_delta": _mean(deltas),
            "paired_fleet_date_bootstrap_95ci": cluster_bootstrap_ci(
                deltas,
                seed=_derived_seed(split, unit, market_id, scope, selected_weight, metric),
            ),
            "paired_fleet_date_sign_test": paired_sign_test(
                deltas, lower_is_better=lower_is_better
            ),
        }
    if float(selected_weight) == 0.0:
        result["selected_effect_disposition"] = "NO_SELECTED_CHANGE"
    else:
        brier = result["selected_vs_current"]["brier"]
        logloss = result["selected_vs_current"]["logloss"]
        winner = result["selected_vs_current"]["winner_probability"]
        brier_ci = brier["paired_fleet_date_bootstrap_95ci"]
        logloss_ci = logloss["paired_fleet_date_bootstrap_95ci"]
        winner_ci = winner["paired_fleet_date_bootstrap_95ci"]
        if (
            brier_ci["high"] is not None
            and brier_ci["high"] < 0.0
            and logloss_ci["high"] is not None
            and logloss_ci["high"] < 0.0
            and winner_ci["low"] is not None
            and winner_ci["low"] > 0.0
        ):
            result["selected_effect_disposition"] = "SUPPORTED_ALL_THREE"
        elif (
            brier["mean_delta"] is not None
            and brier["mean_delta"] < 0.0
            and logloss["mean_delta"] is not None
            and logloss["mean_delta"] < 0.0
            and winner["mean_delta"] is not None
            and winner["mean_delta"] > 0.0
        ):
            result["selected_effect_disposition"] = "DIRECTIONAL_ALL_THREE"
        else:
            result["selected_effect_disposition"] = "MIXED_OR_NOT_SUPPORTED"
    for model in ("current", "selected"):
        result[f"{model}_vs_market"] = {
            metric: result["metrics"][model][metric] - result["metrics"]["market"][metric]
            for metric in METRIC_NAMES
        }
        result[f"{model}_vs_market_inference"] = {}
        for metric in METRIC_NAMES:
            deltas = [
                float(row[f"{model}_{metric}"]) - float(row[f"market_{metric}"])
                for row in rows
            ]
            lower_is_better = metric != "winner_probability"
            result[f"{model}_vs_market_inference"][metric] = {
                "mean_delta": _mean(deltas),
                "paired_fleet_date_bootstrap_95ci": cluster_bootstrap_ci(
                    deltas,
                    seed=_derived_seed(
                        split, unit, market_id, scope, model, "market", metric
                    ),
                ),
                "paired_fleet_date_sign_test": paired_sign_test(
                    deltas, lower_is_better=lower_is_better
                ),
            }
    return result


def build_summaries(
    market_date_rows: Sequence[Mapping[str, Any]],
    fleet_date_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    summaries = []
    market_groups: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in market_date_rows:
        market_groups[(str(row["split"]), str(row["unit"]), str(row["market_id"]), str(row["scope"]))].append(row)
    for key in sorted(market_groups):
        split, unit, market_id, scope = key
        rows = market_groups[key]
        summaries.append(
            summarize_equal_weight_rows(
                rows,
                split=split,
                unit=unit,
                market_id=market_id,
                scope=scope,
                selected_weight=float(rows[0]["selected_weight"]),
            )
        )
    fleet_groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in fleet_date_rows:
        fleet_groups[(str(row["split"]), str(row["unit"]), str(row["scope"]))].append(row)
    for key in sorted(fleet_groups):
        split, unit, scope = key
        rows = fleet_groups[key]
        summaries.append(
            summarize_equal_weight_rows(
                rows,
                split=split,
                unit=unit,
                market_id="__fleet__",
                scope=scope,
                selected_weight=float(rows[0]["selected_weight"]),
            )
        )
    return summaries


def _hour_from_scope(scope: str) -> int | None:
    match = re.fullmatch(r"hour_(\d{2})", scope)
    return int(match.group(1)) if match else None


def _first_sustained(hours: Sequence[int], predicate: Mapping[int, bool]) -> int | None:
    for index, hour in enumerate(hours):
        if predicate.get(hour) and all(predicate.get(later, False) for later in hours[index:]):
            return hour
    return None


def derive_breakpoints(summaries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Derive explicit evening crossovers; do not infer unsupported hours."""

    index: dict[tuple[str, str, str], dict[int, Mapping[str, Any]]] = defaultdict(dict)
    for row in summaries:
        hour = _hour_from_scope(str(row.get("scope") or ""))
        if hour is not None and hour in EVENING_HOURS:
            index[(str(row["split"]), str(row["unit"]), str(row["market_id"]))][hour] = row
    output = []
    for key in sorted(index):
        split, unit, market_id = key
        hourly = index[key]
        observed = sorted(hourly)
        for model in ("current", "selected"):
            joint_edge: dict[int, bool] = {}
            market_caught: dict[int, bool] = {}
            supported_joint_edge: dict[int, bool] = {}
            supported_market_caught: dict[int, bool] = {}
            threshold_crossings: dict[str, int | None] = {}
            per_hour = []
            for hour in observed:
                metrics = hourly[hour]["metrics"]
                brier_advantage = metrics["market"]["brier"] - metrics[model]["brier"]
                logloss_advantage = metrics["market"]["logloss"] - metrics[model]["logloss"]
                winner_advantage = metrics[model]["winner_probability"] - metrics["market"]["winner_probability"]
                joint_edge[hour] = brier_advantage > 0 and logloss_advantage > 0 and winner_advantage > 0
                market_caught[hour] = brier_advantage <= 0 and logloss_advantage <= 0 and winner_advantage <= 0
                inference = hourly[hour].get(f"{model}_vs_market_inference") or {}
                brier_ci = (inference.get("brier") or {}).get(
                    "paired_fleet_date_bootstrap_95ci"
                ) or {}
                logloss_ci = (inference.get("logloss") or {}).get(
                    "paired_fleet_date_bootstrap_95ci"
                ) or {}
                winner_ci = (inference.get("winner_probability") or {}).get(
                    "paired_fleet_date_bootstrap_95ci"
                ) or {}
                supported_joint_edge[hour] = (
                    brier_ci.get("high") is not None
                    and brier_ci["high"] < 0.0
                    and logloss_ci.get("high") is not None
                    and logloss_ci["high"] < 0.0
                    and winner_ci.get("low") is not None
                    and winner_ci["low"] > 0.0
                )
                supported_market_caught[hour] = (
                    brier_ci.get("low") is not None
                    and brier_ci["low"] >= 0.0
                    and logloss_ci.get("low") is not None
                    and logloss_ci["low"] >= 0.0
                    and winner_ci.get("high") is not None
                    and winner_ci["high"] <= 0.0
                )
                per_hour.append(
                    {
                        "hour": hour,
                        "fleet_dates": hourly[hour]["fleet_dates"],
                        "brier_advantage_vs_market": brier_advantage,
                        "logloss_advantage_vs_market": logloss_advantage,
                        "winner_probability_advantage_vs_market": winner_advantage,
                        "joint_model_edge": joint_edge[hour],
                        "market_caught_up_on_all_three_metrics": market_caught[hour],
                        "confidence_supported_joint_model_edge": supported_joint_edge[hour],
                        "confidence_supported_market_catchup": supported_market_caught[hour],
                    }
                )
            for threshold in (0.40, 0.50, 0.80, 0.90):
                model_predicate = {
                    hour: hourly[hour]["metrics"][model]["winner_probability"] >= threshold
                    for hour in observed
                }
                market_predicate = {
                    hour: hourly[hour]["metrics"]["market"]["winner_probability"] >= threshold
                    for hour in observed
                }
                token = str(threshold).replace(".", "p")
                threshold_crossings[f"{model}_sustained_winner_probability_ge_{token}"] = _first_sustained(observed, model_predicate)
                threshold_crossings[f"market_sustained_winner_probability_ge_{token}"] = _first_sustained(observed, market_predicate)
            ever_positive = False
            first_failure_after_positive = None
            for hour in observed:
                if joint_edge[hour]:
                    ever_positive = True
                elif ever_positive and first_failure_after_positive is None:
                    first_failure_after_positive = hour
            sustained_collapse = None
            if ever_positive:
                no_joint_edge = {hour: not joint_edge[hour] for hour in observed}
                sustained_collapse = _first_sustained(observed, no_joint_edge)
            output.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "split": split,
                    "evidence_role": "EXPLORATORY_SELECTION_CONTEXT" if split == "tune" else "UNTOUCHED_HOLDOUT",
                    "unit": unit,
                    "market_id": market_id,
                    "model": model,
                    "observed_evening_hours": observed,
                    "joint_edge_definition": "model Brier and binary log-loss below market, and winner probability above market",
                    "market_catchup_definition": "market is at least as good on Brier, binary log-loss, and winner probability",
                    "joint_edge_hours": [hour for hour in observed if joint_edge[hour]],
                    "market_catchup_hours": [hour for hour in observed if market_caught[hour]],
                    "confidence_supported_joint_edge_hours": [
                        hour for hour in observed if supported_joint_edge[hour]
                    ],
                    "confidence_supported_market_catchup_hours": [
                        hour for hour in observed if supported_market_caught[hour]
                    ],
                    "first_joint_edge_failure_after_positive_hour": first_failure_after_positive,
                    "sustained_joint_edge_collapse_hour": sustained_collapse,
                    "first_market_catchup_hour": next((hour for hour in observed if market_caught[hour]), None),
                    "sustained_market_catchup_hour": _first_sustained(observed, market_caught),
                    "first_confidence_supported_joint_edge_hour": next(
                        (hour for hour in observed if supported_joint_edge[hour]), None
                    ),
                    "first_confidence_supported_market_catchup_hour": next(
                        (hour for hour in observed if supported_market_caught[hour]), None
                    ),
                    "sustained_confidence_supported_market_catchup_hour": _first_sustained(
                        observed, supported_market_caught
                    ),
                    "threshold_crossings": threshold_crossings,
                    "hourly": per_hour,
                }
            )
    return output


def compare_historical_pattern(
    historical: Mapping[str, Any] | None,
    summaries: Sequence[Mapping[str, Any]],
    breakpoints: Sequence[Mapping[str, Any]],
    *,
    evidence_split: str = "holdout",
) -> list[dict[str, Any]]:
    from weather.reporting.research.current_replay_time_frontier_history import (
        compare_historical_pattern as implementation,
    )

    return implementation(
        historical,
        summaries,
        breakpoints,
        evidence_split=evidence_split,
    )


def analyze_split_unit(
    *,
    split: str,
    unit: str,
    current_cache: Path,
    selected_cache: Path,
    selected_weight: float,
    expected_dates: Sequence[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    current_stats = ReaderStats("rows", DEFAULT_CHUNK_CHARS, DEFAULT_MAX_ITEM_CHARS)
    current = _unit_rows(iter_cache_array(current_cache, stats=current_stats), unit)
    selected_stats = None
    if selected_cache.resolve() == current_cache.resolve():
        selected = None
    else:
        selected_stats = ReaderStats("rows", DEFAULT_CHUNK_CHARS, DEFAULT_MAX_ITEM_CHARS)
        selected = _unit_rows(iter_cache_array(selected_cache, stats=selected_stats), unit)
    snapshots = iter_snapshot_scores(aligned_row_pairs(current, selected))
    rows, diagnostics = aggregate_market_dates(
        snapshots, split=split, selected_weight=selected_weight
    )
    if tuple(diagnostics["observed_dates"]) != tuple(expected_dates):
        raise ExperimentConfigurationError(
            f"{split}/{unit} cache dates do not exactly match manifest: "
            f"expected={list(expected_dates)}, observed={diagnostics['observed_dates']}"
        )
    diagnostics["current_reader"] = current_stats.as_dict()
    diagnostics["selected_reader"] = (
        selected_stats.as_dict() if selected_stats else {"same_as_current": True}
    )
    diagnostics["current_cache"] = str(current_cache)
    diagnostics["selected_cache"] = str(selected_cache)
    diagnostics["selected_weight"] = float(selected_weight)
    return rows, diagnostics


def analyze_split_units(
    *,
    split: str,
    current_cache: Path,
    selected_caches_by_weight: Mapping[float, Path],
    selected_weights: Mapping[str, float],
    expected_dates: Sequence[str],
    failure_diagnostics: MutableMapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Analyze both unit families while scanning each unique cache exactly once."""

    current_stats = ReaderStats("rows", DEFAULT_CHUNK_CHARS, DEFAULT_MAX_ITEM_CHARS)
    current_rows = iter_cache_array(current_cache, stats=current_stats)
    candidate_stats: dict[float, ReaderStats] = {}
    candidate_rows: dict[float, Iterator[dict[str, Any]]] = {}
    for weight, path in sorted(selected_caches_by_weight.items()):
        if float(weight) <= 0.0:
            raise ExperimentConfigurationError(
                "multi-arm selected cache map must contain only positive weights"
            )
        stats = ReaderStats("rows", DEFAULT_CHUNK_CHARS, DEFAULT_MAX_ITEM_CHARS)
        candidate_stats[float(weight)] = stats
        candidate_rows[float(weight)] = iter_cache_array(path, stats=stats)
    alignment_diagnostics: dict[str, Any] = {}
    snapshots = iter_snapshot_scores(
        aligned_selected_row_pairs(
            current_rows,
            candidate_rows,
            selected_weights,
            diagnostics=alignment_diagnostics,
        )
    )
    try:
        rows, aggregate_diagnostics = aggregate_market_dates(
            snapshots, split=split, selected_weight=-1.0
        )
    except ExperimentConfigurationError:
        if failure_diagnostics is not None:
            failure_diagnostics.update(
                {
                    "status": "BLOCK",
                    "current_cache": str(current_cache),
                    "current_reader": current_stats.as_dict(),
                    "selected_caches": {
                        str(weight): {
                            "path": str(selected_caches_by_weight[weight]),
                            "reader": candidate_stats[weight].as_dict(),
                        }
                        for weight in sorted(candidate_stats)
                    },
                    "unique_cache_scans": 1 + len(candidate_rows),
                    "alignment": alignment_diagnostics,
                }
            )
        raise
    # The mixed-unit streaming pass uses the unit-selected weight on every
    # snapshot; stamp it after partitioning rather than pretending one shared arm.
    for row in rows:
        row["selected_weight"] = float(selected_weights[str(row["unit"])])
    observed_split_dates = sorted(
        {
            str(row["target_date"])
            for row in rows
            if row["scope"] == "all_hours"
        }
    )
    if tuple(observed_split_dates) != tuple(expected_dates):
        raise ExperimentConfigurationError(
            f"{split} cache dates do not exactly match manifest: "
            f"expected={list(expected_dates)}, observed={observed_split_dates}"
        )
    unit_diagnostics: dict[str, Any] = {}
    for unit in UNITS:
        observed_dates = sorted(
            {
                str(row["target_date"])
                for row in rows
                if row["unit"] == unit and row["scope"] == "all_hours"
            }
        )
        if not observed_dates:
            raise ExperimentConfigurationError(
                f"{split}/{unit} cache contains no scoring dates"
            )
        unit_rows = [row for row in rows if row["unit"] == unit]
        unit_diagnostics[unit] = {
            "observed_dates": observed_dates,
            "missing_split_dates": sorted(set(expected_dates) - set(observed_dates)),
            "market_date_scope_rows": len(unit_rows),
            "markets": sorted({str(row["market_id"]) for row in unit_rows}),
            "selected_weight": float(selected_weights[unit]),
        }
    diagnostics = {
        **aggregate_diagnostics,
        "observed_split_dates": observed_split_dates,
        "current_cache": str(current_cache),
        "current_reader": current_stats.as_dict(),
        "selected_caches": {
            str(weight): {
                "path": str(selected_caches_by_weight[weight]),
                "reader": candidate_stats[weight].as_dict(),
            }
            for weight in sorted(candidate_stats)
        },
        "units": unit_diagnostics,
        "alignment": alignment_diagnostics,
        "unique_cache_scans": 1 + len(candidate_rows),
    }
    return rows, diagnostics


def run_experiment(args: argparse.Namespace) -> dict[str, Any]:
    """Preserve the public API while loading orchestration lazily."""

    from weather.reporting.research.current_replay_time_frontier_runner import (
        run_experiment as implementation,
    )

    return implementation(args)


def build_parser() -> argparse.ArgumentParser:
    from weather.reporting.research.current_replay_time_frontier_runner import (
        build_parser as implementation,
    )

    return implementation()


def main(argv: Sequence[str] | None = None) -> int:
    from weather.reporting.research.current_replay_time_frontier_runner import (
        main as implementation,
    )

    return implementation(argv)


if __name__ == "__main__":
    raise SystemExit(main())
