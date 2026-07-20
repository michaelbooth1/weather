"""Compact, source-bound CSV inputs for bounded maker-paper scoring.

Canonical quote-intent tapes remain the provenance record. These sibling CSVs
retain only fields read by :mod:`weather.market.mm_paper` and its scoring
helpers. A small manifest binds both projections to canonical and projection
file size/mtime pairs. Readers use the pair only when the complete run-level
binding validates; otherwise they fail closed to the canonical tapes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from weather.io import (
    iter_csv_rows,
    write_csv_rows_atomic,
    write_json_streaming_atomic,
)
from weather.market.market_making_run_constants import DEFAULT_RUNS_ROOT
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("mm_scoring_projection")
MANIFEST_FILENAME = "mm_scoring_projection_manifest.json"
BASE_PROJECTION_FILENAME = "mm_scoring_projection.csv"
MODEL_VARIANT_PROJECTION_FILENAME = "model_variant_mm_scoring_projection.csv"
BASE_CANONICAL_FILENAME = "quote_intents_long.csv"
MODEL_VARIANT_CANONICAL_FILENAME = "model_variant_quote_intents_long.csv"
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_HEADER_BYTES = 64 * 1024

# Strict current mm_run_v0.2 fields consumed by quote/leg construction and by
# the mm_paper_v0.1 uptime, blocker, event, guardrail, reward, and model-variant
# diagnostics. Reader-only legacy aliases are intentionally absent. Runtime
# identity, release lineage, artifact hashes, and other provenance remain in
# the canonical tapes.
SCORING_COLUMNS = (
    "run_id",
    "target_date",
    "run_mode",
    "generated_at_utc",
    "captured_at_utc",
    "capture_hour_local",
    "policy_hash",
    "live_trade_permission",
    "quote_permission",
    "regime",
    "reason_code",
    "market_id",
    "event_slug",
    "range_label",
    "bin_kind",
    "bin_value",
    "bin_value_hi",
    "clob_token_id",
    "fair_probability",
    "market_mid",
    "market_yes",
    "edge",
    "bid_price",
    "bid_size",
    "ask_price",
    "ask_size",
    "book_spread",
    "book_imbalance_1pct",
    "source_fresh",
    "source_freshness_state",
    "model_version",
    "served_model_version",
    "model_variant_id",
    "model_variant_family",
    "model_variant_role",
    "model_variant_basket_id",
    "model_variant_probability_source",
    "model_variant_counterfactual",
    "promotion_state",
    "known_edge_taxonomy",
    "known_edge_allowed",
    "known_edge_permission",
    "known_edge_reason",
    "known_edge_match_cutoff",
    "known_edge_match_hour_utc",
    "known_edge_match_band_distance_bucket",
    "known_edge_match_band_type",
    "known_edge_match_casebook_taxonomy",
    "known_edge_match_regime",
    "known_edge_match_source_fresh",
    "known_edge_match_source_freshness_state",
    "known_edge_match_book_imbalance_bucket",
    "event_gate_status",
    "event_gate_action",
    "event_gate_reason_code",
    "event_gate_event_class",
    "event_gate_event_id",
    "event_gate_next_event_at_utc",
    "event_gate_exception_id",
    "early_hour_guardrail_status",
    "early_hour_guardrail_reason",
    "early_hour_guardrail_min_edge",
    "early_hour_guardrail_size_multiplier",
    "early_hour_guardrail_quote_widen_buffer",
    "early_hour_guardrail_override_allowed",
    "early_hour_guardrail_market_weight",
    "market_aware_overlay_probability",
    "market_aware_overlay_edge",
    "market_aware_overlay_used_for_risk_only",
)

# The scorer still accepts these historical/fixture aliases, but the canonical
# mm_run_v0.2 writer does not emit them. A source containing any alias must use
# canonical fallback rather than receiving a projection that silently drops a
# scoring-significant value (notably min_order_size).
UNPROJECTED_COMPATIBILITY_COLUMNS = frozenset({
    "asset_id",
    "avoided_toxicity_usdc",
    "band_distance_bucket",
    "band_type",
    "best_ask",
    "best_ask_price",
    "best_bid",
    "best_bid_price",
    "bin_type",
    "bin_value_c",
    "book_best_ask",
    "book_best_bid",
    "book_imbalance_bucket",
    "candidate_p",
    "casebook_taxonomy",
    "clob_best_ask",
    "clob_best_bid",
    "clob_midpoint",
    "cutoff",
    "cutoff_hour",
    "effective_cutoff_hour",
    "event_gate_avoided_toxicity_usdc",
    "fill_time_utc",
    "forecast_count_bucket",
    "forecast_disagreement",
    "forecast_disagreement_bucket",
    "forecast_source_count_bucket",
    "hour_utc",
    "known_edge_source_freshness_state",
    "markout_30m_adverse_usdc",
    "min_order_size",
    "model_probability",
    "policy_id",
    "quote_size",
    "quote_time_utc",
    "source_count_bucket",
    "source_disagreement_bucket",
    "tick_size",
    "utc_hour",
    "winning_band",
    "winning_band_kind",
    "winning_band_value",
    "winning_band_value_hi",
})

_KINDS = ("base", "model_variant")
_CANONICAL_FILENAMES = {
    "base": BASE_CANONICAL_FILENAME,
    "model_variant": MODEL_VARIANT_CANONICAL_FILENAME,
}
_PROJECTION_FILENAMES = {
    "base": BASE_PROJECTION_FILENAME,
    "model_variant": MODEL_VARIANT_PROJECTION_FILENAME,
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paths(run_folder: str | Path) -> dict[str, dict[str, Path]]:
    folder = Path(run_folder)
    return {
        kind: {
            "canonical": folder / _CANONICAL_FILENAMES[kind],
            "projection": folder / _PROJECTION_FILENAMES[kind],
        }
        for kind in _KINDS
    }


def _file_binding(path: Path, *, content_hash: bool = False) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError:
        return {"filename": path.name, "exists": False}
    binding = {
        "filename": path.name,
        "exists": True,
        "size_bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }
    if content_hash:
        try:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            after = path.stat()
        except OSError:
            return {"filename": path.name, "exists": False}
        if (
            stat.st_size != after.st_size
            or stat.st_mtime_ns != after.st_mtime_ns
        ):
            return {"filename": path.name, "exists": False}
        binding["sha256"] = digest.hexdigest()
    return binding


def _same_binding(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    if left.get("filename") != right.get("filename"):
        return False
    if type(left.get("exists")) is not bool or left.get("exists") != right.get("exists"):
        return False
    if not left.get("exists"):
        return set(left) == {"filename", "exists"}
    matches = bool(
        type(left.get("size_bytes")) is int
        and type(left.get("mtime_ns")) is int
        and left.get("size_bytes") == right.get("size_bytes")
        and left.get("mtime_ns") == right.get("mtime_ns")
    )
    if not matches:
        return False
    if "sha256" in left:
        return bool(
            isinstance(left.get("sha256"), str)
            and len(left["sha256"]) == 64
            and left.get("sha256") == right.get("sha256")
        )
    return True


def _read_header(path: Path) -> list[str] | None:
    try:
        before = path.stat()
        with path.open("rb") as handle:
            raw = handle.readline(MAX_HEADER_BYTES + 1)
        after = path.stat()
    except OSError:
        return None
    if (
        not raw
        or len(raw) > MAX_HEADER_BYTES
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        return None
    try:
        line = raw.decode("utf-8-sig")
        return next(csv.reader([line]))
    except (UnicodeDecodeError, csv.Error, StopIteration):
        return None


def _projection_manifest(run_folder: Path) -> dict[str, Any] | None:
    path = run_folder / MANIFEST_FILENAME
    try:
        before = path.stat()
        if before.st_size > MAX_MANIFEST_BYTES:
            return None
        with path.open("rb") as handle:
            raw = handle.read(MAX_MANIFEST_BYTES + 1)
        after = path.stat()
    except OSError:
        return None
    if (
        len(raw) > MAX_MANIFEST_BYTES
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        return None
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _source_header_issue(paths: Mapping[str, Mapping[str, Path]]) -> str | None:
    required = set(SCORING_COLUMNS)
    for kind in _KINDS:
        source = paths[kind]["canonical"]
        if not source.exists():
            continue
        header = _read_header(source)
        if header is None:
            return f"{kind}_canonical_header_invalid"
        missing = sorted(required - set(header))
        if missing:
            return f"{kind}_canonical_columns_missing:{','.join(missing)}"
        aliases = sorted(set(header) & UNPROJECTED_COMPATIBILITY_COLUMNS)
        if aliases:
            return f"{kind}_canonical_compatibility_aliases:{','.join(aliases)}"
    return None


def validate_run_scoring_projection(run_folder: str | Path) -> dict[str, Any]:
    """Validate the complete run-level pair without reading row bodies."""

    folder = Path(run_folder)
    paths = _paths(folder)
    source_header_issue = _source_header_issue(paths)
    if source_header_issue:
        return {"valid": False, "reason": source_header_issue}
    manifest = _projection_manifest(folder)
    if manifest is None:
        return {"valid": False, "reason": "missing_or_invalid_manifest"}
    if manifest.get("schema_version") != SCHEMA_VERSION:
        return {"valid": False, "reason": "projection_schema_mismatch"}
    if manifest.get("columns") != list(SCORING_COLUMNS):
        return {"valid": False, "reason": "projection_columns_mismatch"}
    source_bindings = manifest.get("source_bindings")
    projection_bindings = manifest.get("projection_bindings")
    if not isinstance(source_bindings, dict) or not isinstance(projection_bindings, dict):
        return {"valid": False, "reason": "projection_bindings_missing"}
    for kind in _KINDS:
        source = source_bindings.get(kind)
        projection = projection_bindings.get(kind)
        if not isinstance(source, dict) or not isinstance(projection, dict):
            return {"valid": False, "reason": f"{kind}_binding_missing"}
        if not _same_binding(source, _file_binding(paths[kind]["canonical"])):
            return {"valid": False, "reason": f"{kind}_canonical_binding_mismatch"}
        if not _same_binding(
            projection,
            _file_binding(paths[kind]["projection"], content_hash=True),
        ):
            return {"valid": False, "reason": f"{kind}_projection_binding_mismatch"}
        if _read_header(paths[kind]["projection"]) != list(SCORING_COLUMNS):
            return {"valid": False, "reason": f"{kind}_projection_header_mismatch"}
        if type(projection.get("row_count")) is not int or projection.get("row_count") < 0:
            return {"valid": False, "reason": f"{kind}_projection_row_count_invalid"}
    return {
        "valid": True,
        "reason": None,
        "schema_version": SCHEMA_VERSION,
        "manifest_path": str(folder / MANIFEST_FILENAME),
        "source_bindings": source_bindings,
        "projection_bindings": projection_bindings,
    }


def resolve_run_scoring_inputs(run_folder: str | Path) -> dict[str, Any]:
    """Resolve the projection pair or an all-canonical fail-closed fallback."""

    folder = Path(run_folder)
    paths = _paths(folder)
    validation = validate_run_scoring_projection(folder)
    use_projection = bool(validation.get("valid"))
    input_paths = {
        kind: paths[kind]["projection" if use_projection else "canonical"]
        for kind in _KINDS
    }
    canonical_bytes = sum(
        int(binding.get("size_bytes") or 0)
        for binding in (_file_binding(paths[kind]["canonical"]) for kind in _KINDS)
        if binding.get("exists")
    )
    input_bytes = sum(
        int(binding.get("size_bytes") or 0)
        for binding in (_file_binding(path) for path in input_paths.values())
        if binding.get("exists")
    )
    return {
        "run_folder": str(folder),
        "input_mode": "projection" if use_projection else "canonical_fallback",
        "projection_valid": use_projection,
        "projection_reason": validation.get("reason"),
        "manifest_path": validation.get("manifest_path"),
        "input_paths": {kind: str(path) for kind, path in input_paths.items()},
        "canonical_paths": {
            kind: str(paths[kind]["canonical"])
            for kind in _KINDS
        },
        "input_bindings": (
            validation.get("projection_bindings")
            if use_projection
            else {kind: _file_binding(path) for kind, path in input_paths.items()}
        ),
        "input_bytes": input_bytes,
        "canonical_bytes": canonical_bytes,
        "projected_vs_canonical_byte_ratio": (
            input_bytes / canonical_bytes if canonical_bytes else None
        ),
    }


def _project_rows(rows: Iterable[Mapping[str, Any]]) -> Iterator[dict[str, Any]]:
    for row in rows:
        yield {column: row.get(column, "") for column in SCORING_COLUMNS}


def _canonical_rows(path: Path) -> Iterable[Mapping[str, Any]]:
    if not path.exists():
        return ()
    return iter_csv_rows(path, attach_diagnostics=True)


def _write_counted_projection(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0

    def counted() -> Iterator[dict[str, Any]]:
        nonlocal count
        for row in _project_rows(rows):
            count += 1
            yield row

    write_csv_rows_atomic(path, SCORING_COLUMNS, counted())
    return count


def _manifest_payload(run_folder: Path, row_counts: Mapping[str, int]) -> dict[str, Any]:
    paths = _paths(run_folder)
    source_bindings = {
        kind: _file_binding(paths[kind]["canonical"])
        for kind in _KINDS
    }
    projection_bindings = {}
    for kind in _KINDS:
        binding = _file_binding(paths[kind]["projection"], content_hash=True)
        binding["row_count"] = int(row_counts[kind])
        projection_bindings[kind] = binding
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "columns": list(SCORING_COLUMNS),
        "source_bindings": source_bindings,
        "projection_bindings": projection_bindings,
    }


def _publish_manifest(run_folder: Path, row_counts: Mapping[str, int]) -> dict[str, Any]:
    manifest_path = run_folder / MANIFEST_FILENAME
    payload = _manifest_payload(run_folder, row_counts)
    write_json_streaming_atomic(manifest_path, payload, trailing_newline=True)
    paths = _paths(run_folder)
    stable = all(
        _same_binding(
            payload["source_bindings"][kind],
            _file_binding(paths[kind]["canonical"]),
        )
        and _same_binding(
            payload["projection_bindings"][kind],
            _file_binding(paths[kind]["projection"], content_hash=True),
        )
        for kind in _KINDS
    )
    if not stable:
        manifest_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"maker canonical/projection inputs changed during projection publish: {run_folder}"
        )
    validation = validate_run_scoring_projection(run_folder)
    if not validation.get("valid"):
        manifest_path.unlink(missing_ok=True)
        raise RuntimeError(
            "published maker scoring projection did not validate: "
            f"{validation.get('reason')}"
        )
    return resolve_run_scoring_inputs(run_folder)


def write_run_scoring_projections(run_folder: str | Path) -> dict[str, Any]:
    """Atomically derive both projections from canonical tapes in one pass."""

    folder = Path(run_folder)
    paths = _paths(folder)
    if not paths["base"]["canonical"].exists():
        raise FileNotFoundError(paths["base"]["canonical"])
    source_header_issue = _source_header_issue(paths)
    if source_header_issue:
        raise ValueError(source_header_issue)
    (folder / MANIFEST_FILENAME).unlink(missing_ok=True)
    before = {
        kind: _file_binding(paths[kind]["canonical"])
        for kind in _KINDS
    }
    row_counts = {
        kind: _write_counted_projection(
            paths[kind]["projection"],
            _canonical_rows(paths[kind]["canonical"]),
        )
        for kind in _KINDS
    }
    after = {
        kind: _file_binding(paths[kind]["canonical"])
        for kind in _KINDS
    }
    if any(not _same_binding(before[kind], after[kind]) for kind in _KINDS):
        raise RuntimeError(
            f"maker canonical tape changed while its projection was derived: {folder}"
        )
    return _publish_manifest(folder, row_counts)


def discover_run_folders(runs_root: str | Path) -> list[Path]:
    root = Path(runs_root)
    return sorted(
        path.parent
        for path in root.glob(f"*/*/{BASE_CANONICAL_FILENAME}")
        if path.is_file()
    )


def backfill_run_scoring_projections(
    run_folders: Iterable[str | Path],
    *,
    skip_existing: bool = True,
) -> dict[str, Any]:
    rows = []
    for item in run_folders:
        folder = Path(item)
        existing = validate_run_scoring_projection(folder)
        if skip_existing and existing.get("valid"):
            receipt = resolve_run_scoring_inputs(folder)
            rows.append({"status": "SKIPPED_VALID", **receipt})
            continue
        try:
            receipt = write_run_scoring_projections(folder)
        except Exception as exc:
            rows.append({
                "run_folder": str(folder),
                "status": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue
        rows.append({"status": "WROTE", **receipt})
    return {
        "schema_version": SCHEMA_VERSION,
        "run_count": len(rows),
        "written_run_count": sum(row.get("status") == "WROTE" for row in rows),
        "skipped_run_count": sum(row.get("status") == "SKIPPED_VALID" for row in rows),
        "error_run_count": sum(row.get("status") == "ERROR" for row in rows),
        "runs": rows,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build compact source-bound maker-paper scoring projections."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    backfill = sub.add_parser("backfill")
    backfill.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    backfill.add_argument("--run-folder", action="append", default=[])
    backfill.add_argument(
        "--force",
        action="store_true",
        help="Rebuild valid projections instead of the default skip-existing behavior.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "backfill":
        raise AssertionError(args.command)
    folders = [Path(path) for path in args.run_folder]
    if not folders:
        folders = discover_run_folders(args.runs_root)
    payload = backfill_run_scoring_projections(
        folders,
        skip_existing=not args.force,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if payload["error_run_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BASE_CANONICAL_FILENAME",
    "BASE_PROJECTION_FILENAME",
    "MANIFEST_FILENAME",
    "MODEL_VARIANT_CANONICAL_FILENAME",
    "MODEL_VARIANT_PROJECTION_FILENAME",
    "SCHEMA_VERSION",
    "SCORING_COLUMNS",
    "backfill_run_scoring_projections",
    "discover_run_folders",
    "resolve_run_scoring_inputs",
    "validate_run_scoring_projection",
    "write_run_scoring_projections",
]
