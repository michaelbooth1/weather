"""Bounded compact projections for large taker strategy bakeoff artifacts.

The full bakeoff remains the canonical artifact.  This module publishes a
small, content-bound sibling containing only the fields needed by settlement
finalization and the champion/challenger ledger.  Readers validate the sibling
against the canonical file without deserializing that file.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, BinaryIO

from weather.io import read_json, sha256_file, write_json_streaming_atomic
from weather.schema_registry import schema_version


BAKEOFF_LEDGER_PROJECTION_FILENAME = "strategy_bakeoff_ledger_projection.json"
BAKEOFF_LEDGER_PROJECTION_SCHEMA_VERSION = (
    schema_version("taker_strategy_bakeoff_ledger_projection")
)
DEFAULT_SCHEMA_LINE_MAX_BYTES = 64 * 1024
DEFAULT_PROJECTION_MAX_BYTES = 16 * 1024 * 1024
SETTLED_FINALIZATION_PROJECTION_FILENAME = "settled_finalization_projection.json"
SETTLED_FINALIZATION_PROJECTION_SCHEMA_VERSION = (
    schema_version("taker_settled_finalization_projection")
)

_SOURCE_BINDING_FIELDS = frozenset(
    {"filename", "size_bytes", "mtime_ns", "sha256"}
)
_PROJECTION_FIELDS = frozenset(
    {
        "projection_schema_version",
        "source_artifact_binding",
        "schema_version",
        "run_id",
        "source_run_id",
        "target_date",
        "exchange_economics_gate",
        "label_summary",
        "blockers",
        "promotion_gates",
        "pnl",
        "profitability_artifact_verification",
    }
)
_LEDGER_STRATEGY_FIELDS = frozenset(
    {
        "strategy_id",
        "strategy_family",
        "filled_order_count",
        "settled_order_count",
        "settled_market_count",
        "unsettled_order_count",
        "unscored_order_count",
        "spent_usdc",
        "settlement_pnl_usdc",
        "net_pnl_usdc",
        "low_price_tail_fill_count",
    }
)
_TOP_LEVEL_SCHEMA_LINE = re.compile(
    r'^  "schema_version"\s*:\s*'
    r'(?P<value>"(?:\\.|[^"\\])*")\s*,?\s*$'
)
_FINALIZATION_STRATEGY_FIELDS = frozenset(
    {
        "strategy_id",
        "strategy_family",
        "filled_order_count",
        "after_fee_pnl_scored",
        "after_slippage_pnl_scored",
        "live_profitability_evidence_basis",
        "market_benchmark_status",
        "market_smarter_slice_count",
        "market_benchmark_no_trade_net_pnl_usdc",
        "market_benchmark_avoided_loss_usdc",
        "market_benchmark_missed_gain_usdc",
        "exchange_economics_snapshot_id",
        "exchange_economics_hash",
        "exchange_economics_evidence_basis",
    }
)

__all__ = [
    "BAKEOFF_LEDGER_PROJECTION_FILENAME",
    "BAKEOFF_LEDGER_PROJECTION_SCHEMA_VERSION",
    "DEFAULT_PROJECTION_MAX_BYTES",
    "DEFAULT_SCHEMA_LINE_MAX_BYTES",
    "SETTLED_FINALIZATION_PROJECTION_FILENAME",
    "SETTLED_FINALIZATION_PROJECTION_SCHEMA_VERSION",
    "bakeoff_ledger_projection_path",
    "build_bakeoff_ledger_projection",
    "build_settled_finalization_projection",
    "load_bakeoff_ledger_projection",
    "load_settled_finalization_projection",
    "read_pretty_json_top_level_schema_version",
    "settled_finalization_projection_path",
    "write_bakeoff_ledger_projection",
    "write_settled_finalization_projection",
]


def bakeoff_ledger_projection_path(bakeoff_path: str | Path) -> Path:
    """Return the fixed compact sibling path for a canonical bakeoff."""

    return Path(bakeoff_path).with_name(BAKEOFF_LEDGER_PROJECTION_FILENAME)


def settled_finalization_projection_path(settled_path: str | Path) -> Path:
    return Path(settled_path).with_name(SETTLED_FINALIZATION_PROJECTION_FILENAME)


def build_settled_finalization_projection(
    payload: Mapping[str, Any],
    *,
    source_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Select the fixed finalization state needed by bounded readers."""

    pnl = payload.get("pnl") if isinstance(payload, Mapping) else {}
    strategy_summary = payload.get("strategy_summary") if isinstance(payload, Mapping) else {}
    strategies = (
        strategy_summary.get("strategies")
        if isinstance(strategy_summary, Mapping)
        else []
    )
    return {
        "projection_schema_version": SETTLED_FINALIZATION_PROJECTION_SCHEMA_VERSION,
        "source_artifact_binding": dict(source_binding),
        "schema_version": payload.get("schema_version"),
        "run_id": payload.get("run_id"),
        "target_date": payload.get("target_date"),
        "exchange_economics_gate": payload.get("exchange_economics_gate") or {},
        **{
            key: payload.get(key)
            for key in (
                "exchange_economics_status",
                "exchange_economics_evidence_basis",
                "exchange_economics_snapshot_id",
                "exchange_economics_hash",
                "exchange_economics_source_hash",
                "exchange_economics_verified_at_utc",
                "exchange_economics_effective_date",
                "exchange_economics_platform",
            )
        },
        "summary": dict(pnl.get("summary") or {}) if isinstance(pnl, Mapping) else {},
        "strategies": [
            {
                key: value
                for key, value in row.items()
                if key in _FINALIZATION_STRATEGY_FIELDS
            }
            for row in (strategies or [])
            if isinstance(row, Mapping)
        ],
    }


def write_settled_finalization_projection(
    settled_path: str | Path,
    payload: Mapping[str, Any],
) -> Path:
    """Publish a compact, stat-bound sibling after the canonical payload."""

    source_path = Path(settled_path)
    before = source_path.stat()
    binding = {
        "filename": source_path.name,
        "size_bytes": int(before.st_size),
        "mtime_ns": int(before.st_mtime_ns),
    }
    projection_path = settled_finalization_projection_path(source_path)
    projection = build_settled_finalization_projection(
        payload,
        source_binding=binding,
    )
    write_json_streaming_atomic(projection_path, projection)
    after = source_path.stat()
    if not _same_file_version(before, after):
        projection_path.unlink(missing_ok=True)
        raise RuntimeError(
            "canonical finalization changed while its projection was published: "
            f"{source_path}"
        )
    return projection_path


def load_settled_finalization_projection(
    settled_path: str | Path,
    *,
    max_projection_bytes: int = DEFAULT_PROJECTION_MAX_BYTES,
) -> dict[str, Any] | None:
    """Load a small finalization projection bound by source size and mtime."""

    source_path = Path(settled_path)
    projection_path = settled_finalization_projection_path(source_path)
    try:
        before = projection_path.stat()
    except OSError:
        return None
    if before.st_size > max_projection_bytes:
        return None
    projection = read_json(projection_path, None)
    try:
        after = projection_path.stat()
    except OSError:
        return None
    if not _same_file_version(before, after) or not isinstance(projection, dict):
        return None
    if (
        projection.get("projection_schema_version")
        != SETTLED_FINALIZATION_PROJECTION_SCHEMA_VERSION
    ):
        return None
    binding = projection.get("source_artifact_binding") or {}
    try:
        source_stat = source_path.stat()
    except OSError:
        return None
    if not (
        binding.get("filename") == source_path.name
        and type(binding.get("size_bytes")) is int
        and binding.get("size_bytes") == source_stat.st_size
        and type(binding.get("mtime_ns")) is int
        and binding.get("mtime_ns") == source_stat.st_mtime_ns
        and isinstance(projection.get("summary"), dict)
        and isinstance(projection.get("strategies"), list)
        and all(isinstance(row, dict) for row in projection.get("strategies"))
        and isinstance(projection.get("exchange_economics_gate"), dict)
    ):
        return None
    return projection


def build_bakeoff_ledger_projection(
    payload: Mapping[str, Any],
    *,
    source_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Select only the bakeoff fields used by bounded downstream readers."""

    if not isinstance(payload, Mapping):
        raise TypeError("bakeoff payload must be a mapping")
    if not isinstance(source_binding, Mapping):
        raise TypeError("source artifact binding must be a mapping")
    pnl = payload.get("pnl")
    by_strategy = pnl.get("by_strategy") if isinstance(pnl, Mapping) else None
    compact_strategies = [
        {
            key: value
            for key, value in row.items()
            if key in _LEDGER_STRATEGY_FIELDS
        }
        for row in (by_strategy or [])
        if isinstance(row, Mapping)
    ]
    return {
        "projection_schema_version": BAKEOFF_LEDGER_PROJECTION_SCHEMA_VERSION,
        "source_artifact_binding": dict(source_binding),
        "schema_version": payload.get("schema_version"),
        "run_id": payload.get("run_id"),
        "source_run_id": payload.get("source_run_id"),
        "target_date": payload.get("target_date"),
        "exchange_economics_gate": payload.get("exchange_economics_gate") or {},
        "label_summary": payload.get("label_summary") or {},
        "blockers": payload.get("blockers") or [],
        "promotion_gates": payload.get("promotion_gates") or [],
        "pnl": {"by_strategy": compact_strategies},
        "profitability_artifact_verification": (
            payload.get("profitability_artifact_verification") or {}
        ),
    }


def _same_file_version(left, right) -> bool:
    return bool(
        left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
    )


def _stable_source_binding(path: Path) -> dict[str, Any]:
    before = path.stat()
    digest = sha256_file(path)
    after = path.stat()
    if not _same_file_version(before, after):
        raise RuntimeError(
            f"canonical bakeoff changed while its projection was being bound: {path}"
        )
    return {
        "filename": path.name,
        "size_bytes": int(after.st_size),
        "mtime_ns": int(after.st_mtime_ns),
        "sha256": digest,
    }


def write_bakeoff_ledger_projection(
    bakeoff_path: str | Path,
    payload: Mapping[str, Any],
) -> Path:
    """Atomically publish the compact sibling after the canonical bakeoff."""

    source_path = Path(bakeoff_path)
    projection_path = bakeoff_ledger_projection_path(source_path)
    source_binding = _stable_source_binding(source_path)
    projection = build_bakeoff_ledger_projection(
        payload,
        source_binding=source_binding,
    )
    write_json_streaming_atomic(projection_path, projection)
    try:
        after_publish = source_path.stat()
    except OSError:
        projection_path.unlink(missing_ok=True)
        raise
    if (
        after_publish.st_size != source_binding["size_bytes"]
        or after_publish.st_mtime_ns != source_binding["mtime_ns"]
    ):
        projection_path.unlink(missing_ok=True)
        raise RuntimeError(
            "canonical bakeoff changed while its projection was being published: "
            f"{source_path}"
        )
    return projection_path


def _valid_sha256(value: Any) -> bool:
    text = str(value or "")
    return bool(
        len(text) == 64
        and text == text.lower()
        and all(character in "0123456789abcdef" for character in text)
    )


def _valid_projection_shape(
    projection: Any,
    *,
    expected_bakeoff_schema_version: str | None,
) -> bool:
    if not isinstance(projection, dict) or set(projection) != _PROJECTION_FIELDS:
        return False
    if (
        projection.get("projection_schema_version")
        != BAKEOFF_LEDGER_PROJECTION_SCHEMA_VERSION
    ):
        return False
    schema_version = projection.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version:
        return False
    if (
        expected_bakeoff_schema_version is not None
        and schema_version != expected_bakeoff_schema_version
    ):
        return False
    if not all(
        isinstance(projection.get(field), str) and projection.get(field)
        for field in ("run_id", "source_run_id", "target_date")
    ):
        return False
    if not isinstance(projection.get("label_summary"), dict):
        return False
    if not isinstance(projection.get("exchange_economics_gate"), dict):
        return False
    blockers = projection.get("blockers")
    if not isinstance(blockers, list) or not all(
        isinstance(row, dict) for row in blockers
    ):
        return False
    promotion_gates = projection.get("promotion_gates")
    if not isinstance(promotion_gates, list) or not all(
        isinstance(row, dict) for row in promotion_gates
    ):
        return False
    pnl = projection.get("pnl")
    if not isinstance(pnl, dict) or set(pnl) != {"by_strategy"}:
        return False
    by_strategy = pnl.get("by_strategy")
    if not isinstance(by_strategy, list) or not all(
        isinstance(row, dict) for row in by_strategy
    ):
        return False
    if not isinstance(projection.get("profitability_artifact_verification"), dict):
        return False
    binding = projection.get("source_artifact_binding")
    return bool(
        isinstance(binding, dict)
        and set(binding) == _SOURCE_BINDING_FIELDS
        and isinstance(binding.get("filename"), str)
        and binding.get("filename")
        and type(binding.get("size_bytes")) is int
        and binding.get("size_bytes") >= 0
        and type(binding.get("mtime_ns")) is int
        and binding.get("mtime_ns") >= 0
        and _valid_sha256(binding.get("sha256"))
    )


def load_bakeoff_ledger_projection(
    bakeoff_path: str | Path,
    *,
    expected_bakeoff_schema_version: str | None = None,
    max_projection_bytes: int = DEFAULT_PROJECTION_MAX_BYTES,
) -> dict[str, Any] | None:
    """Load a valid compact sibling without deserializing the main artifact."""

    source_path = Path(bakeoff_path)
    projection_path = bakeoff_ledger_projection_path(source_path)
    if max_projection_bytes <= 0:
        raise ValueError("max_projection_bytes must be positive")
    try:
        projection_before = projection_path.stat()
    except OSError:
        return None
    if projection_before.st_size > max_projection_bytes:
        return None
    projection = read_json(projection_path, None)
    try:
        projection_after = projection_path.stat()
    except OSError:
        return None
    if not _same_file_version(projection_before, projection_after):
        return None
    if not _valid_projection_shape(
        projection,
        expected_bakeoff_schema_version=expected_bakeoff_schema_version,
    ):
        return None
    binding = projection["source_artifact_binding"]
    if binding["filename"] != source_path.name:
        return None
    try:
        before = source_path.stat()
        if (
            before.st_size != binding["size_bytes"]
            or before.st_mtime_ns != binding["mtime_ns"]
        ):
            return None
        digest = sha256_file(source_path)
        after = source_path.stat()
    except OSError:
        return None
    if not _same_file_version(before, after):
        return None
    if (
        after.st_size != binding["size_bytes"]
        or after.st_mtime_ns != binding["mtime_ns"]
        or digest != binding["sha256"]
    ):
        return None
    return projection


def _discard_oversized_line(handle: BinaryIO, fragment: bytes, limit: int) -> None:
    while fragment and not fragment.endswith((b"\n", b"\r")):
        fragment = handle.readline(limit + 1)


def read_pretty_json_top_level_schema_version(
    path: str | Path,
    *,
    max_line_bytes: int = DEFAULT_SCHEMA_LINE_MAX_BYTES,
) -> str | None:
    """Read a pretty JSON root schema with fixed memory per physical line.

    Nested ``schema_version`` keys are ignored because canonical pretty JSON
    indents root-object fields by exactly two spaces.  Oversized physical lines
    are consumed in bounded fragments and cannot become schema candidates.
    """

    if max_line_bytes <= 0:
        raise ValueError("max_line_bytes must be positive")
    try:
        with Path(path).open("rb") as handle:
            while True:
                raw_line = handle.readline(max_line_bytes + 1)
                if not raw_line:
                    return None
                if len(raw_line) > max_line_bytes:
                    _discard_oversized_line(handle, raw_line, max_line_bytes)
                    continue
                if not raw_line.startswith(b'  "schema_version"'):
                    continue
                try:
                    line = raw_line.decode("utf-8").rstrip("\r\n")
                except UnicodeDecodeError:
                    return None
                match = _TOP_LEVEL_SCHEMA_LINE.fullmatch(line)
                if not match:
                    continue
                try:
                    value = json.loads(match.group("value"))
                except json.JSONDecodeError:
                    return None
                return value if isinstance(value, str) and value else None
    except OSError:
        return None
