"""Reachability-based retention and exact-file cleanup for replay caches.

Planning is always read-only.  Apply requires an externally approved, hash-
pinned cleanup manifest and re-verifies every source and candidate immediately
before unlinking that one exact file.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

import pandas as pd

from weather.backtesting import replay_cache
from weather.backtesting.replay import (
    RECONSTRUCTED_FILENAME,
    REPLAY_INPUTS_FILENAME,
    index_records_by_snapshot,
    load_replay_records,
)
from weather.calibration.pooled_candidate_scoring import (
    artifact_hash_for_path,
    load_artifact,
)
from weather.calibration.pooled_candidate_replay import (
    _compute_pooled_candidate_day,
    _verified_production_static_context,
)
from weather.io import sha256_file, write_json_atomic, write_text_atomic
from weather.operations.cleanup_preflight import (
    CLEANUP_MANIFEST_SCHEMA_VERSION,
    build_cleanup_preflight,
)
from weather.operations.storage_classes import classification_payload
from weather.operations.replay_cache_retention_report import (
    render_apply_receipt,
    render_plan,
    render_rebuild_one,
)
from weather.operations.replay_cache_retention_parity import cache_payload_parity_checks as _cache_payload_parity_checks
from weather.model.toronto_model import TorontoHighTempModel
from weather.release_artifacts import DEFAULT_ACTIVE_RELEASE_POINTER, DEFAULT_RELEASES_ROOT
from weather.operations.replay_cache_retention_serving import (
    cache_data_path as _cache_data_path,
    load_pinned_serving_bundle as _load_pinned_serving_bundle,
    load_serving_rebuild_context as _load_serving_rebuild_context,
    serving_binding_identity as _serving_binding_identity,
    validated_standalone_output_root as _validated_standalone_output_root,
    verify_serving_market_coverage as _verify_serving_market_coverage,
)
from weather.reporting.candidate_lifecycle.variant_registry import (
    SCHEMA_VERSION as VARIANT_REGISTRY_SCHEMA_VERSION,
    resolve_registry_path,
    variant_export_contract,
)
from weather.reporting.promotion.promotion_corpus import (
    load_manifest,
    verify_entry_inputs,
)
from weather.schema_registry import schema_version


DEFAULT_QUOTA_BYTES = 10 * 1024**3
DEFAULT_CONSUMER = "pooled_candidate_replay"
DEFAULT_CLOB_MAX_AGE_SECONDS = 180.0
MAX_CORPUS_BYTES = 64 * 1024**2
TOOL_SCHEMA_VERSION = schema_version("replay_cache_retention")
RECEIPT_FORMAT = schema_version("replay_cache_retention_receipt")
FIXTURE_PARITY_SCHEMA_VERSION = schema_version("replay_cache_rebuild_one_parity")
CACHE_OFF_PARITY_SCHEMA_VERSION = schema_version("replay_cache_cache_off_rebuild_parity")
PLAN_KIND = "replay_cache_reachability_cleanup"
FULL_KEY_FIELDS = (
    "event_slug",
    "consumer",
    "inputs_fp",
    "model_fp",
    "config_fp",
    "schema_version",
)
OPTIONAL_EVENT_REBUILD_INPUTS = (
    "features_long.csv",
    RECONSTRUCTED_FILENAME,
    "settlement.json",
    "order_books_summary.csv",
    "price_history.csv",
    "market_ws_events.csv",
    "market_ws.jsonl",
)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _identity_digest(value: Any) -> str:
    return replay_cache.fingerprint(value)


def _strict_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)

    def reject_duplicates(pairs):
        output = {}
        for key, value in pairs:
            if key in output:
                raise ValueError(f"duplicate JSON key {key!r}")
            output[key] = value
        return output

    def reject_non_finite(value):
        raise ValueError(f"non-finite JSON constant {value!r}")

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_non_finite,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON {path}: {type(exc).__name__}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _stable_source(path: str | Path, *, kind: str) -> tuple[dict[str, Any], str]:
    lexical_path = _assert_no_reparse_components(path, label=kind)
    if not lexical_path.exists() or not lexical_path.is_file():
        raise ValueError(f"{kind} is missing or not a file: {lexical_path}")
    path = lexical_path.resolve(strict=True)
    before = path.lstat()
    digest = sha256_file(path)
    after = path.lstat()
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ino != after.st_ino
        or before.st_dev != after.st_dev
    ):
        raise ValueError(f"{kind} changed while hashed: {path}")
    return (
        {
            "kind": kind,
            "path": str(path),
            "bytes": int(after.st_size),
            "sha256": digest,
            "file_identity": _file_identity(after),
        },
        digest,
    )


def _absent_source(path: str | Path, *, kind: str) -> dict[str, Any]:
    """Record an optional dependency's exact absence without following links."""

    lexical_path = _assert_no_reparse_components(path, label=kind)
    try:
        lexical_path.lstat()
    except FileNotFoundError:
        return {
            "kind": kind,
            "path": str(lexical_path),
            "absent": True,
        }
    except OSError as exc:
        raise ValueError(
            f"cannot prove optional rebuild input absence {lexical_path}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    raise ValueError(
        f"optional rebuild input expected absent but exists: {lexical_path}"
    )


def _file_identity(stat_result: os.stat_result) -> dict[str, int]:
    return {
        "device": int(stat_result.st_dev),
        "inode": int(stat_result.st_ino),
        "mtime_ns": int(stat_result.st_mtime_ns),
        "ctime_ns": int(stat_result.st_ctime_ns),
    }


def _full_key(metadata: dict[str, Any]) -> dict[str, str]:
    return {field: str(metadata.get(field) or "") for field in FULL_KEY_FIELDS}


def _key_tuple(metadata: dict[str, Any]) -> tuple[str, ...]:
    key = _full_key(metadata)
    return tuple(key[field] for field in FULL_KEY_FIELDS)


def _key_from_tuple(values: tuple[str, ...]) -> dict[str, str]:
    return dict(zip(FULL_KEY_FIELDS, values))


def _key_object(metadata: dict[str, Any]) -> replay_cache.ReplayCacheKey:
    key = _full_key(metadata)
    return replay_cache.ReplayCacheKey(
        event_slug=key["event_slug"],
        consumer=key["consumer"],
        inputs_fp=key["inputs_fp"],
        model_fp=key["model_fp"],
        config_fp=key["config_fp"],
        schema_version=key["schema_version"],
    )


def _is_reparse_point(stat_result: os.stat_result) -> bool:
    return bool(int(getattr(stat_result, "st_file_attributes", 0)) & 0x400)


def _path_is_link(path: Path) -> bool:
    try:
        return path.is_symlink() or _is_reparse_point(path.lstat())
    except OSError:
        return True


def _lexical_absolute(path: str | Path) -> Path:
    """Return an absolute path without resolving links or reparse points."""

    return Path(os.path.abspath(os.fspath(path)))


def _assert_no_reparse_components(path: str | Path, *, label: str) -> Path:
    """Reject every existing link/reparse component before resolving a path."""

    lexical = _lexical_absolute(path)
    current = Path(lexical.anchor) if lexical.anchor else Path()
    parts = lexical.parts[1:] if lexical.anchor else lexical.parts
    for part in parts:
        current = current / part
        try:
            stat_result = current.lstat()
        except FileNotFoundError:
            # Once an ancestor is absent, no deeper lexical component exists.
            break
        except OSError as exc:
            raise ValueError(
                f"cannot inspect {label} path component {current}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if current.is_symlink() or _is_reparse_point(stat_result):
            raise ValueError(f"{label} contains a link or reparse point: {current}")
    return lexical


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _paths_overlap(left: Path, right: Path) -> bool:
    left = left.resolve()
    right = right.resolve()
    return _within(left, right) or _within(right, left)


def _validated_output_root(
    cache_root: str | Path,
    output_root: str | Path,
    protected_roots: Iterable[str | Path],
) -> tuple[Path, list[Path]]:
    cache_lexical = _assert_no_reparse_components(cache_root, label="cache root")
    output_lexical = _assert_no_reparse_components(output_root, label="output root")
    normalized_roots = sorted(
        {
            _assert_no_reparse_components(root, label="protected root").resolve()
            for root in protected_roots
        },
        key=lambda path: os.path.normcase(str(path)),
    )
    if not normalized_roots:
        raise ValueError("at least one explicit protected data/mirror root is required")
    cache_resolved = cache_lexical.resolve()
    if not any(
        cache_resolved == root or _within(cache_resolved, root)
        for root in normalized_roots
    ):
        raise ValueError("cache root is not contained by an explicit protected root")
    for protected_root in normalized_roots:
        if _paths_overlap(protected_root, output_lexical):
            raise ValueError(
                "output root must not overlap an explicit protected data/mirror "
                f"root ({protected_root})"
            )
    return output_lexical.resolve(), normalized_roots


def _artifact_family_config(
    artifact: dict[str, Any],
    corpus: dict[str, Any],
    *,
    registry_postprocess_config_hash: str | None,
    clob_max_age_seconds: float,
) -> dict[str, Any]:
    prediction_mode = artifact.get("prediction_mode") or "bucket_distribution"
    family_unit = artifact.get("family_unit") or (
        "all" if prediction_mode == "residual_distribution_v1" else "F"
    )
    postprocess = artifact.get("postprocess") or {}
    density_postprocess = artifact.get("density_postprocess") or {}
    return {
        "consumer_row_contract": "pooled_candidate_replay_day_rows_v0.1",
        "prediction_mode": prediction_mode,
        "family_unit": family_unit,
        "artifact_schema_version": artifact.get("schema_version"),
        "artifact_feature_schema_version": artifact.get("feature_schema_version"),
        "include_reconstructed": bool(corpus.get("include_reconstructed")),
        "clob_max_age_seconds": float(clob_max_age_seconds),
        "postprocess_schema_version": postprocess.get("schema_version"),
        "density_postprocess_schema_version": density_postprocess.get("schema_version"),
        "registry_postprocess_config_hash": registry_postprocess_config_hash,
        "replay_cache_schema_version": replay_cache.REPLAY_CACHE_SCHEMA_VERSION,
    }


def _verify_corpus_rebuild_inputs(
    manifest: dict[str, Any],
    *,
    protected_roots: Iterable[Path],
) -> list[dict[str, Any]]:
    """Pin every captured tape/replay file needed by the corpus entries."""

    raw_snapshots_root = str(manifest.get("snapshots_root") or "")
    if not raw_snapshots_root:
        raise ValueError("promotion corpus snapshots_root is missing")
    snapshots_lexical = _assert_no_reparse_components(
        raw_snapshots_root,
        label="promotion corpus snapshots root",
    )
    if not snapshots_lexical.exists() or not snapshots_lexical.is_dir():
        raise ValueError(
            f"promotion corpus snapshots root is missing: {snapshots_lexical}"
        )
    snapshots_root = snapshots_lexical.resolve(strict=True)
    if not any(
        snapshots_root == root or _within(snapshots_root, root)
        for root in protected_roots
    ):
        raise ValueError(
            "promotion corpus snapshots root is outside every explicit protected root"
        )

    sources_by_path: dict[str, dict[str, Any]] = {}
    entries = manifest.get("entries") or []
    if not entries:
        raise ValueError("promotion corpus contains no entries")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("promotion corpus contains a non-object entry")
        event_slug = str(entry.get("event_slug") or "")
        relative_text = str(
            entry.get("folder_relative_to_snapshots_root")
            or entry.get("folder_name")
            or event_slug
        )
        relative = Path(relative_text)
        if (
            not event_slug
            or relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise ValueError(
                f"promotion corpus entry has an unsafe folder path: {relative_text!r}"
            )
        folder_lexical = _assert_no_reparse_components(
            snapshots_root / relative,
            label=f"promotion corpus event folder {event_slug}",
        )
        if not folder_lexical.exists() or not folder_lexical.is_dir():
            raise ValueError(
                f"promotion corpus event folder is missing: {folder_lexical}"
            )
        folder = folder_lexical.resolve(strict=True)
        if not _within(folder, snapshots_root) or folder.name != event_slug:
            raise ValueError(
                f"promotion corpus event folder identity is invalid: {folder}"
            )

        pinned_id_list = [
            str(value) for value in entry.get("snapshot_ids") or []
        ]
        pinned_ids = set(pinned_id_list)
        if not pinned_ids or len(pinned_ids) != len(pinned_id_list):
            raise ValueError(
                f"{event_slug}: pinned snapshot IDs are empty or duplicated"
            )
        if int(entry.get("snapshot_count") or -1) != len(pinned_ids):
            raise ValueError(f"{event_slug}: snapshot_count does not match pinned IDs")
        if set(map(str, (entry.get("tape_row_hashes") or {}).keys())) != pinned_ids:
            raise ValueError(f"{event_slug}: tape row hashes do not cover pinned IDs")
        if (
            set(map(str, (entry.get("replay_record_hashes") or {}).keys()))
            != pinned_ids
        ):
            raise ValueError(
                f"{event_slug}: replay record hashes do not cover pinned IDs"
            )
        for field in ("tape_row_hashes", "replay_record_hashes"):
            if any(
                not re.fullmatch(r"[0-9a-f]{64}", str(value or ""))
                for value in (entry.get(field) or {}).values()
            ):
                raise ValueError(
                    f"{event_slug}: {field} contains a non-SHA-256 value"
                )

        tape_path = folder / "snapshots_long.csv"
        replay_path = folder / REPLAY_INPUTS_FILENAME
        tape_source, tape_hash = _stable_source(
            tape_path,
            kind="promotion_snapshot_tape",
        )
        replay_source, replay_hash = _stable_source(
            replay_path,
            kind="promotion_replay_inputs",
        )
        input_sources = [tape_source, replay_source]
        for filename in OPTIONAL_EVENT_REBUILD_INPUTS:
            optional_path = folder / filename
            kind = f"promotion_optional_rebuild_input:{filename}"
            if optional_path.exists():
                optional_source, _ = _stable_source(
                    optional_path,
                    kind=kind,
                )
                input_sources.append(optional_source)
            else:
                input_sources.append(
                    _absent_source(optional_path, kind=kind)
                )

        frame = pd.read_csv(tape_path)
        records = index_records_by_snapshot(load_replay_records(folder))
        if "snapshot_id" not in frame:
            raise ValueError(f"{event_slug}: snapshot tape lacks snapshot_id")
        pinned_row_count = int(
            frame["snapshot_id"].astype(str).isin(pinned_ids).sum()
        )
        if int(entry.get("row_count") or -1) != pinned_row_count:
            raise ValueError(
                f"{event_slug}: pinned snapshot tape row count changed"
            )
        warnings = verify_entry_inputs(entry, folder, frame, records)
        if warnings:
            raise ValueError("; ".join(map(str, warnings)))
        if sha256_file(tape_path) != tape_hash:
            raise ValueError(f"{event_slug}: snapshot tape changed while verified")
        if sha256_file(replay_path) != replay_hash:
            raise ValueError(f"{event_slug}: replay input tape changed while verified")
        for source in input_sources:
            sources_by_path[source["path"]] = source

    return sorted(
        sources_by_path.values(),
        key=lambda row: (row["kind"], row["path"]),
    )


def _load_corpora(
    paths: Iterable[str | Path],
    *,
    protected_roots: Iterable[Path],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    roots: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for raw_path in paths:
        path = _assert_no_reparse_components(raw_path, label="promotion corpus")
        source, before_hash = _stable_source(path, kind="promotion_corpus")
        path = path.resolve(strict=True)
        manifest = load_manifest(path, max_bytes=MAX_CORPUS_BYTES)
        after_hash = sha256_file(path)
        if after_hash != before_hash:
            raise ValueError(f"promotion corpus changed while parsed: {path}")
        input_sources = _verify_corpus_rebuild_inputs(
            manifest,
            protected_roots=protected_roots,
        )
        roots.append(
            {
                "path": path,
                "manifest": manifest,
                "source": source,
                "input_sources": input_sources,
                "rebuild_input_sources_sha256": _identity_digest(
                    [
                        {
                            "kind": row["kind"],
                            "path": row["path"],
                            "absent": bool(row.get("absent")),
                            "bytes": row.get("bytes"),
                            "sha256": row.get("sha256"),
                        }
                        for row in input_sources
                    ]
                ),
            }
        )
        sources.extend([source, *input_sources])
    if not roots:
        raise ValueError("at least one explicit promotion corpus is required")
    return roots, sources


def _load_registry(path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _assert_no_reparse_components(path, label="model variant registry")
    source, before_hash = _stable_source(path, kind="model_variant_registry")
    path = path.resolve(strict=True)
    registry = _strict_json(path)
    after_hash = sha256_file(path)
    if after_hash != before_hash:
        raise ValueError(f"model variant registry changed while parsed: {path}")
    if registry.get("schema_version") != VARIANT_REGISTRY_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported model variant registry schema {registry.get('schema_version')!r}"
        )
    return registry, source


def _artifact_roots(
    registry: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    roots: list[dict[str, Any]] = []
    sources_by_path: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for variant in registry.get("variants") or []:
        if not isinstance(variant, dict):
            errors.append("variant registry contains a non-object row")
            continue
        contract = variant_export_contract(variant)
        if str(contract.get("live_runtime") or "") != "pooled_candidate_replay":
            continue
        raw_artifact_path = contract.get("artifact_path")
        if not raw_artifact_path:
            if variant.get("lifecycle") in {"active", "shadow"}:
                errors.append(f"{variant.get('variant_id')}: pooled replay artifact path is missing")
            continue
        artifact_path = resolve_registry_path(raw_artifact_path)
        if artifact_path is None:
            if variant.get("lifecycle") in {"active", "shadow"}:
                errors.append(f"{variant.get('variant_id')}: pooled replay artifact path is not local")
            continue
        artifact_path = _assert_no_reparse_components(
            artifact_path,
            label="replay model artifact",
        )
        try:
            source, before_hash = _stable_source(artifact_path, kind="replay_model_artifact")
            artifact = load_artifact(artifact_path)
            after_hash = sha256_file(artifact_path)
            if after_hash != before_hash:
                raise ValueError(f"artifact changed while loaded: {artifact_path}")
            model_fp = str(artifact.get("artifact_hash") or artifact_hash_for_path(artifact_path))
            if not model_fp:
                raise ValueError("artifact model fingerprint is empty")
            try:
                production_static_context = _verified_production_static_context(
                    artifact
                )
                rebuildable = production_static_context is not None
                rebuild_blocker = (
                    None
                    if rebuildable
                    else "artifact_has_no_verified_production_static_context"
                )
            except ValueError as exc:
                production_static_context = None
                rebuildable = False
                rebuild_blocker = (
                    "artifact_production_static_context_invalid:"
                    f"{type(exc).__name__}:{exc}"
                )
        except Exception as exc:  # noqa: BLE001 - converted to a fail-closed root error.
            if variant.get("lifecycle") in {"active", "shadow"}:
                errors.append(
                    f"{variant.get('variant_id')}: cannot load active pooled artifact: "
                    f"{type(exc).__name__}: {exc}"
                )
            continue
        source_key = str(artifact_path)
        sources_by_path[source_key] = source
        roots.append(
            {
                "variant_id": str(variant.get("variant_id") or ""),
                "lifecycle": str(variant.get("lifecycle") or ""),
                "active": variant.get("lifecycle") in {"active", "shadow"},
                "path": artifact_path,
                "source": source,
                "artifact": artifact,
                "model_fp": model_fp,
                "postprocess_config_hash": contract.get("postprocess_config_hash"),
                "rebuildable": rebuildable,
                "rebuild_blocker": rebuild_blocker,
                "production_static_context_sha256": (
                    production_static_context.get("context_sha256")
                    if production_static_context is not None
                    else None
                ),
                "production_static_context_markets": sorted(
                    map(
                        str,
                        (
                            (production_static_context or {}).get("markets")
                            or {}
                        ),
                    )
                ),
            }
        )
    if errors:
        raise ValueError("; ".join(errors))
    active_roots = [root for root in roots if root["active"]]
    if not active_roots:
        raise ValueError("variant registry has no active/shadow pooled replay artifact roots")
    return roots, list(sources_by_path.values())


def _build_key_maps(
    corpora: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    *,
    consumers: Iterable[str],
    clob_max_age_seconds: float,
) -> tuple[set[tuple[str, ...]], dict[tuple[str, ...], list[dict[str, Any]]]]:
    reachable: set[tuple[str, ...]] = set()
    rebuildable: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    normalized_consumers = tuple(sorted({str(value) for value in consumers if str(value)}))
    if not normalized_consumers:
        raise ValueError("at least one replay-cache consumer is required")
    for corpus_root in corpora:
        manifest = corpus_root["manifest"]
        for artifact_root in artifacts:
            # The direct promotion path historically had no headline registry
            # contract.  Include both that exact config and the registry-bound
            # config; over-retention is intentional.
            postprocess_hashes = {
                None,
                artifact_root.get("postprocess_config_hash"),
            }
            for postprocess_hash in postprocess_hashes:
                config = _artifact_family_config(
                    artifact_root["artifact"],
                    manifest,
                    registry_postprocess_config_hash=postprocess_hash,
                    clob_max_age_seconds=clob_max_age_seconds,
                )
                config_fp = replay_cache.config_fingerprint(config)
                for entry in manifest.get("entries") or []:
                    entry_market_id = str(entry.get("market_id") or "")
                    for consumer in normalized_consumers:
                        key = replay_cache.key_for_entry(
                            entry,
                            consumer=consumer,
                            model_fp=artifact_root["model_fp"],
                            config_fp=config_fp,
                        )
                        key_tuple = _key_tuple(key.metadata())
                        source_row = {
                            "corpus_path": str(corpus_root["path"]),
                            "corpus_sha256": corpus_root["source"]["sha256"],
                            "corpus_hash": str(manifest.get("corpus_hash") or ""),
                            "rebuild_input_sources_sha256": corpus_root[
                                "rebuild_input_sources_sha256"
                            ],
                            "rebuild_input_source_count": len(
                                corpus_root["input_sources"]
                            ),
                            "artifact_path": str(artifact_root["path"]),
                            "artifact_sha256": artifact_root["source"]["sha256"],
                            "variant_id": artifact_root["variant_id"],
                            "config_fp": config_fp,
                            "production_static_context_sha256": artifact_root[
                                "production_static_context_sha256"
                            ],
                        }
                        context_markets = artifact_root[
                            "production_static_context_markets"
                        ]
                        if artifact_root["rebuildable"] and entry_market_id in context_markets:
                            sources = rebuildable.setdefault(key_tuple, [])
                            if source_row not in sources:
                                sources.append(source_row)
                        if artifact_root["active"]:
                            reachable.add(key_tuple)
    return reachable, rebuildable


def _iter_cache_files(cache_root: Path) -> tuple[list[Path], list[dict[str, Any]]]:
    files: list[Path] = []
    ambiguities: list[dict[str, Any]] = []

    def onerror(exc: OSError) -> None:
        ambiguities.append(
            {
                "path": str(getattr(exc, "filename", None) or cache_root),
                "reason": (
                    "unreadable_cache_subtree:"
                    f"{type(exc).__name__}:{getattr(exc, 'strerror', None) or exc}"
                ),
            }
        )

    for dirpath, dirnames, filenames in os.walk(
        cache_root,
        followlinks=False,
        onerror=onerror,
    ):
        base = Path(dirpath)
        retained_dirs = []
        for dirname in sorted(dirnames):
            path = base / dirname
            if _path_is_link(path):
                ambiguities.append(
                    {"path": str(path), "reason": "linked_or_reparse_directory"}
                )
            else:
                retained_dirs.append(dirname)
        dirnames[:] = retained_dirs
        for filename in sorted(filenames):
            files.append(base / filename)
    return sorted(files, key=lambda path: path.as_posix()), ambiguities


def _cache_file_row(
    path: Path,
    *,
    cache_root: Path,
    reachable: set[tuple[str, ...]],
    rebuildable: dict[tuple[str, ...], list[dict[str, Any]]],
) -> tuple[str, dict[str, Any]]:
    if _path_is_link(path):
        return "ambiguous", {"path": str(path), "reason": "linked_or_reparse_file"}
    try:
        relative = path.resolve().relative_to(cache_root)
    except (OSError, ValueError):
        return "ambiguous", {"path": str(path), "reason": "path_escape"}
    if path.suffix.lower() != ".json":
        return "ambiguous", {
            "path": relative.as_posix(),
            "reason": "unexpected_non_json_cache_file",
        }
    before = path.lstat()
    try:
        payload = _strict_json(path)
        digest = sha256_file(path)
    except (OSError, ValueError) as exc:
        return "ambiguous", {
            "path": relative.as_posix(),
            "reason": f"unreadable_cache_entry:{type(exc).__name__}:{exc}",
        }
    after = path.lstat()
    if _file_identity(before) != _file_identity(after) or before.st_size != after.st_size:
        return "ambiguous", {
            "path": relative.as_posix(),
            "reason": "cache_entry_changed_while_scanned",
        }
    if payload.get("schema_version") != replay_cache.REPLAY_CACHE_SCHEMA_VERSION:
        return "ambiguous", {
            "path": relative.as_posix(),
            "reason": "unsupported_replay_cache_schema",
        }
    raw_key = payload.get("key")
    if not isinstance(raw_key, dict):
        return "ambiguous", {
            "path": relative.as_posix(),
            "reason": "missing_full_cache_key",
        }
    full_key = _full_key(raw_key)
    if any(not full_key[field] for field in FULL_KEY_FIELDS):
        return "ambiguous", {
            "path": relative.as_posix(),
            "reason": "incomplete_full_cache_key",
            "full_key": full_key,
        }
    key = _key_object(full_key)
    expected = replay_cache.cache_path(cache_root, key).resolve()
    if expected != path.resolve():
        return "ambiguous", {
            "path": relative.as_posix(),
            "reason": "cache_path_does_not_match_full_key",
            "expected_path": expected.relative_to(cache_root).as_posix()
            if _within(expected, cache_root)
            else str(expected),
            "full_key": full_key,
        }
    key_tuple = _key_tuple(full_key)
    base = {
        "path": relative.as_posix(),
        "data_path": _cache_data_path(cache_root, relative),
        "bytes": int(after.st_size),
        "sha256": digest,
        "file_identity": _file_identity(after),
        "full_key": full_key,
        "identity": _identity_digest(full_key),
        "storage_class": "operator_cache",
        "artifact_family": "replay_cache",
        "retention_class": "reachability_bounded_rebuildable_replay_cache",
        "rebuild_source": (
            "exact pinned promotion corpus, retained replay/snapshot/settlement "
            "inputs, exact candidate artifact with frozen production static "
            "context, exact retained serving-release graph, and row-affecting "
            "replay config"
        ),
        "deletion_reason": "full replay-cache key is unreachable from every explicit active root",
    }
    if key_tuple in reachable:
        base["reason"] = "reachable_full_key"
        return "reachable", base
    if key_tuple not in rebuildable:
        base["reason"] = "unreachable_but_rebuild_identity_is_not_proven"
        return "ambiguous", base
    base["reason"] = "unreachable_full_key"
    base["rebuild_sources"] = rebuildable[key_tuple]
    return "candidate", base


def build_retention_plan(
    *,
    cache_root: str | Path,
    corpora: Iterable[str | Path],
    registry_path: str | Path,
    output_root: str | Path,
    protected_roots: Iterable[str | Path],
    quota_bytes: int = DEFAULT_QUOTA_BYTES,
    consumers: Iterable[str] = (DEFAULT_CONSUMER,),
    clob_max_age_seconds: float = DEFAULT_CLOB_MAX_AGE_SECONDS,
    active_release_pointer: str | Path = DEFAULT_ACTIVE_RELEASE_POINTER,
    releases_root: str | Path = DEFAULT_RELEASES_ROOT,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build a non-mutating exact-file cleanup manifest."""

    cache_root = _lexical_absolute(cache_root)
    output_root = _lexical_absolute(output_root)
    registry_path = _lexical_absolute(registry_path)
    active_release_pointer = _lexical_absolute(active_release_pointer)
    releases_root = _lexical_absolute(releases_root)
    corpus_paths = [_lexical_absolute(path) for path in corpora]
    blockers: list[str] = []
    ambiguities: list[dict[str, Any]] = []
    reachable_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    reachable_keys: set[tuple[str, ...]] = set()
    serving_binding: dict[str, Any] = {}

    if int(quota_bytes) <= 0:
        blockers.append("quota_bytes_must_be_positive")
    try:
        _assert_no_reparse_components(cache_root, label="cache root")
    except ValueError as exc:
        blockers.append(f"cache_root_path_unsafe:{exc}")
    if not cache_root.exists() or not cache_root.is_dir():
        blockers.append("cache_root_missing_or_not_directory")
    elif _path_is_link(cache_root):
        blockers.append("cache_root_is_link_or_reparse_point")
    try:
        output_root, normalized_protected_roots = _validated_output_root(
            cache_root,
            output_root,
            protected_roots,
        )
    except ValueError as exc:
        normalized_protected_roots = []
        blockers.append(f"output_root_unsafe:{exc}")

    rebuildable: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    try:
        corpus_roots, corpus_sources = _load_corpora(
            corpus_paths,
            protected_roots=normalized_protected_roots,
        )
        registry, registry_source = _load_registry(registry_path)
        artifact_roots, artifact_sources = _artifact_roots(registry)
        serving_binding, serving_sources = _load_serving_rebuild_context(
            active_release_pointer,
            releases_root,
        )
        _verify_serving_market_coverage(corpus_roots, serving_binding)
        reachable_keys, rebuildable = _build_key_maps(
            corpus_roots,
            artifact_roots,
            consumers=consumers,
            clob_max_age_seconds=clob_max_age_seconds,
        )
        sources = [
            registry_source,
            *corpus_sources,
            *artifact_sources,
            *serving_sources,
        ]
    except Exception as exc:  # noqa: BLE001 - root ambiguity blocks all selection.
        blockers.append(f"reachability_incomplete:{type(exc).__name__}:{exc}")

    if cache_root.exists() and cache_root.is_dir() and not _path_is_link(cache_root):
        files, walk_ambiguities = _iter_cache_files(cache_root)
        ambiguities.extend(walk_ambiguities)
        if not blockers:
            for path in files:
                disposition, row = _cache_file_row(
                    path,
                    cache_root=cache_root,
                    reachable=reachable_keys,
                    rebuildable=rebuildable,
                )
                if disposition == "reachable":
                    reachable_rows.append(row)
                elif disposition == "candidate":
                    candidate_rows.append(row)
                else:
                    ambiguities.append(row)
        elif files:
            ambiguities.append(
                {
                    "path": ".",
                    "reason": "cache_files_not_classified_because_reachability_is_incomplete",
                    "file_count": len(files),
                }
            )

    if ambiguities:
        blockers.append("ambiguous_cache_or_reachability_state")
    reachable_bytes = sum(int(row["bytes"]) for row in reachable_rows)
    candidate_bytes = sum(int(row["bytes"]) for row in candidate_rows)
    if reachable_bytes > int(quota_bytes):
        blockers.append("reachable_cache_bytes_exceed_quota")

    # Ambiguous reachability retains everything.  Keep the provisional rows in
    # diagnostics, but expose no cleanup candidates to preflight/apply.
    selected = [] if ambiguities or any(item.startswith("reachability_incomplete") for item in blockers) else candidate_rows
    status = "PASS" if not blockers else "BLOCK"
    reachability_key_payload = [
        _key_from_tuple(key) for key in sorted(reachable_keys)
    ]
    return {
        "schema_version": CLEANUP_MANIFEST_SCHEMA_VERSION,
        "tool_schema_version": TOOL_SCHEMA_VERSION,
        "kind": PLAN_KIND,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "mode": "dry_run",
        "status": status,
        "apply_required": True,
        "root": str(cache_root),
        "protected_roots": [str(path) for path in normalized_protected_roots],
        "output_root": str(output_root),
        "registry_path": str(registry_path),
        "corpus_paths": [str(path) for path in corpus_paths],
        "serving_rebuild": serving_binding,
        "operator_review": {
            "approved": False,
            "approved_by": "",
            "approved_at_utc": "",
            "note": "",
        },
        "reachability": {
            "status": "COMPLETE" if not any(
                item.startswith("reachability_incomplete") for item in blockers
            ) else "INCOMPLETE",
            "consumer_roots": sorted({str(value) for value in consumers}),
            "clob_max_age_seconds": float(clob_max_age_seconds),
            "source_files": sorted(sources, key=lambda row: (row["kind"], row["path"])),
            "reachable_key_count": len(reachable_keys),
            "reachable_keys_sha256": _identity_digest(reachability_key_payload),
            "algorithm": "exact_full_key_membership_no_age_or_lru",
        },
        "quota": {
            "bytes": int(quota_bytes),
            "reachable_bytes": reachable_bytes,
            "reachable_exceeds_quota": reachable_bytes > int(quota_bytes),
            "selection_policy": "diagnostic_only_never_select_reachable",
        },
        "summary": {
            "reachable_count": len(reachable_rows),
            "reachable_bytes": reachable_bytes,
            "provisional_candidate_count": len(candidate_rows),
            "provisional_candidate_bytes": candidate_bytes,
            "selected_count": len(selected),
            "selected_bytes": sum(int(row["bytes"]) for row in selected),
            "ambiguity_count": len(ambiguities),
        },
        "blockers": blockers,
        "reachable": reachable_rows,
        "provisional_candidates": candidate_rows,
        "ambiguities": ambiguities,
        "candidates": selected,
    }


def write_plan_outputs(
    payload: dict[str, Any],
    output_root: str | Path,
) -> tuple[Path, Path]:
    output_root, protected_roots = _validated_output_root(
        Path(payload["root"]),
        output_root,
        payload.get("protected_roots") or [],
    )
    expected_protected_roots = sorted(
        (
            Path(str(path)).resolve()
            for path in payload.get("protected_roots") or []
        ),
        key=lambda path: os.path.normcase(str(path)),
    )
    if expected_protected_roots != protected_roots:
        raise ValueError(
            "plan protected roots do not match the explicit output boundary"
        )
    json_path = output_root / "replay_cache_retention_manifest.json"
    report_path = output_root / "replay_cache_retention_report.md"
    write_json_atomic(json_path, payload, trailing_newline=True)
    write_text_atomic(report_path, render_plan(payload))
    return json_path, report_path


def _verify_source_files(source_files: Iterable[dict[str, Any]]) -> None:
    for source in source_files:
        lexical_path = _assert_no_reparse_components(
            str(source.get("path") or ""),
            label="reachability source",
        )
        if source.get("absent") is True:
            try:
                lexical_path.lstat()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise ValueError(
                    "cannot reverify optional rebuild input absence "
                    f"{lexical_path}: {type(exc).__name__}: {exc}"
                ) from exc
            raise ValueError(
                f"optional rebuild input appeared: {lexical_path}"
            )
        if not lexical_path.exists() or not lexical_path.is_file():
            raise ValueError(
                f"reachability source is missing or not a file: {lexical_path}"
            )
        path = lexical_path.resolve(strict=True)
        if _path_is_link(path):
            raise ValueError(f"reachability source is missing or linked: {path}")
        before = path.lstat()
        expected_identity = _expected_file_identity(source.get("file_identity"))
        if _file_identity(before) != expected_identity:
            raise ValueError(f"reachability source file identity changed: {path}")
        if int(source.get("bytes") or -1) != int(before.st_size):
            raise ValueError(f"reachability source bytes changed: {path}")
        if str(source.get("sha256") or "") != sha256_file(path):
            raise ValueError(f"reachability source SHA-256 changed: {path}")
        after = path.lstat()
        if (
            _file_identity(after) != _file_identity(before)
            or after.st_size != before.st_size
        ):
            raise ValueError(f"reachability source changed while re-verified: {path}")


def _expected_file_identity(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("file identity must be an object")
    keys = ("device", "inode", "mtime_ns", "ctime_ns")
    if any(key not in value or isinstance(value[key], bool) for key in keys):
        raise ValueError("file identity is incomplete")
    try:
        return {key: int(value[key]) for key in keys}
    except (TypeError, ValueError) as exc:
        raise ValueError("file identity contains a non-integer value") from exc


def _source_contract(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        path = _lexical_absolute(str(row.get("path") or ""))
        if row.get("absent") is True:
            output.append(
                {
                    "kind": str(row.get("kind") or ""),
                    "path": str(path),
                    "absent": True,
                }
            )
            continue
        output.append(
            {
                "kind": str(row.get("kind") or ""),
                "path": str(path.resolve()),
                "absent": False,
                "bytes": int(row.get("bytes") or -1),
                "sha256": str(row.get("sha256") or ""),
                "file_identity": _expected_file_identity(
                    row.get("file_identity")
                ),
            }
        )
    return sorted(output, key=lambda row: (row["kind"], row["path"]))


def _recompute_candidate_eligibility(
    candidate: dict[str, Any],
    *,
    corpus_paths: Iterable[Path],
    registry_path: Path,
    consumers: Iterable[str],
    clob_max_age_seconds: float,
    expected_sources: Iterable[dict[str, Any]],
    protected_roots: Iterable[Path],
    active_release_pointer: Path,
    releases_root: Path,
    expected_serving_binding: dict[str, Any],
) -> None:
    """Rebuild live reachability and fail if the exact key is no longer deletable."""

    _verify_source_files(expected_sources)
    corpus_roots, corpus_sources = _load_corpora(
        corpus_paths,
        protected_roots=protected_roots,
    )
    registry, registry_source = _load_registry(registry_path)
    artifact_roots, artifact_sources = _artifact_roots(registry)
    serving_binding, serving_sources = _load_serving_rebuild_context(
        active_release_pointer,
        releases_root,
    )
    _verify_serving_market_coverage(corpus_roots, serving_binding)
    if _serving_binding_identity(serving_binding) != _serving_binding_identity(
        expected_serving_binding
    ):
        raise ValueError("serving rebuild binding changed")
    actual_sources = [
        registry_source,
        *corpus_sources,
        *artifact_sources,
        *serving_sources,
    ]
    if _source_contract(actual_sources) != _source_contract(expected_sources):
        raise ValueError("reachability source set or exact source identity changed")
    reachable, rebuildable = _build_key_maps(
        corpus_roots,
        artifact_roots,
        consumers=consumers,
        clob_max_age_seconds=clob_max_age_seconds,
    )
    key_tuple = _key_tuple(candidate.get("full_key") or {})
    if key_tuple in reachable:
        raise ValueError("candidate full cache key is now reachable")
    if key_tuple not in rebuildable:
        raise ValueError("candidate full cache key is no longer proven rebuildable")


def _verify_apply_candidate(
    candidate: dict[str, Any],
    *,
    cache_root: Path,
) -> Path:
    relative = Path(str(candidate.get("path") or ""))
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError(f"candidate path must be normalized and relative: {relative}")
    lexical_path = _assert_no_reparse_components(
        cache_root / relative,
        label="candidate path",
    )
    path = lexical_path.resolve()
    path.relative_to(cache_root)
    if _path_is_link(path) or not path.exists() or not path.is_file():
        raise ValueError(f"candidate missing, linked, or not a file: {path}")
    before = path.lstat()
    expected_identity = _expected_file_identity(candidate.get("file_identity"))
    if _file_identity(before) != expected_identity:
        raise ValueError(f"candidate file identity changed: {path}")
    if int(candidate.get("bytes") or -1) != int(before.st_size):
        raise ValueError(f"candidate bytes changed: {path}")
    if str(candidate.get("sha256") or "") != sha256_file(path):
        raise ValueError(f"candidate SHA-256 changed: {path}")
    payload = _strict_json(path)
    actual_key = _full_key(payload.get("key") or {})
    if actual_key != _full_key(candidate.get("full_key") or {}):
        raise ValueError(f"candidate full cache key changed: {path}")
    if payload.get("schema_version") != replay_cache.REPLAY_CACHE_SCHEMA_VERSION:
        raise ValueError(f"candidate replay-cache schema changed: {path}")
    expected_path = replay_cache.cache_path(cache_root, _key_object(actual_key)).resolve()
    if expected_path != path:
        raise ValueError(f"candidate path no longer matches full cache key: {path}")
    after = path.lstat()
    if _file_identity(after) != _file_identity(before) or after.st_size != before.st_size:
        raise ValueError(f"candidate changed during immediate re-verification: {path}")
    return path


def _write_apply_receipt(
    receipt: dict[str, Any],
    *,
    json_path: Path,
    report_path: Path,
) -> None:
    receipt["updated_at_utc"] = utc_iso()
    _write_text_durable_atomic(
        json_path,
        json.dumps(receipt, indent=2, sort_keys=True, default=str) + "\n",
    )
    _write_text_durable_atomic(report_path, render_apply_receipt(receipt))


def _write_text_durable_atomic(path: Path, text: str) -> None:
    """Replace one receipt file only after its bytes are fsync-durable."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    try:
        with temporary.open("x", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        # Re-open the final name so a successful return proves the replaced
        # file itself can be flushed before an exact candidate unlink.
        with path.open("r+b") as handle:
            os.fsync(handle.fileno())
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temporary.exists() and not _path_is_link(temporary):
            temporary.unlink()


def apply_retention_manifest(
    manifest_path: str | Path,
    *,
    expected_manifest_sha256: str,
    cache_root: str | Path,
    corpora: Iterable[str | Path],
    registry_path: str | Path,
    output_root: str | Path,
    protected_roots: Iterable[str | Path],
    active_release_pointer: str | Path = DEFAULT_ACTIVE_RELEASE_POINTER,
    releases_root: str | Path = DEFAULT_RELEASES_ROOT,
) -> dict[str, Any]:
    """Apply one externally reviewed exact-path manifest, stopping on failure."""

    manifest_path = _assert_no_reparse_components(
        manifest_path,
        label="approved cleanup manifest",
    ).resolve(strict=True)
    cache_root = _assert_no_reparse_components(
        cache_root,
        label="cache root",
    ).resolve(strict=True)
    output_root, normalized_protected_roots = _validated_output_root(
        cache_root,
        output_root,
        protected_roots,
    )
    corpus_paths = sorted(
        _assert_no_reparse_components(
            path,
            label="promotion corpus",
        ).resolve(strict=True)
        for path in corpora
    )
    registry_path = _assert_no_reparse_components(
        registry_path,
        label="model variant registry",
    ).resolve(strict=True)
    active_release_pointer = _assert_no_reparse_components(
        active_release_pointer,
        label="active release pointer",
    ).resolve()
    releases_root = _assert_no_reparse_components(
        releases_root,
        label="releases root",
    ).resolve()
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected_manifest_sha256).lower()):
        raise ValueError("expected manifest SHA-256 must be 64 lowercase hex characters")
    manifest_before = manifest_path.lstat()
    before_hash = sha256_file(manifest_path)
    if before_hash != str(expected_manifest_sha256).lower():
        raise ValueError("cleanup manifest SHA-256 does not match expected identity")
    manifest = _strict_json(manifest_path)
    after_hash = sha256_file(manifest_path)
    manifest_after = manifest_path.lstat()
    if (
        after_hash != before_hash
        or _file_identity(manifest_after) != _file_identity(manifest_before)
        or manifest_after.st_size != manifest_before.st_size
    ):
        raise ValueError("cleanup manifest changed while loaded")
    if manifest.get("schema_version") != CLEANUP_MANIFEST_SCHEMA_VERSION:
        raise ValueError("unsupported cleanup manifest schema")
    if manifest.get("tool_schema_version") != TOOL_SCHEMA_VERSION:
        raise ValueError("unsupported replay-cache retention tool schema")
    if manifest.get("kind") != PLAN_KIND:
        raise ValueError("manifest is not a replay-cache reachability cleanup plan")
    if Path(str(manifest.get("root") or "")).resolve() != cache_root:
        raise ValueError("explicit cache root does not match manifest")
    if Path(str(manifest.get("output_root") or "")).resolve() != output_root:
        raise ValueError("explicit output root does not match manifest")
    manifest_protected_roots = sorted(
        (
            _assert_no_reparse_components(
                path,
                label="manifest protected root",
            ).resolve()
            for path in manifest.get("protected_roots") or []
        ),
        key=lambda path: os.path.normcase(str(path)),
    )
    if manifest_protected_roots != normalized_protected_roots:
        raise ValueError(
            "explicit protected data/mirror roots do not match the manifest"
        )
    if Path(str(manifest.get("registry_path") or "")).resolve() != registry_path:
        raise ValueError("explicit registry path does not match manifest")
    if (
        sorted(
            Path(str(path)).resolve()
            for path in manifest.get("corpus_paths") or []
        )
        != corpus_paths
    ):
        raise ValueError("explicit promotion corpora do not match manifest")
    serving_binding = manifest.get("serving_rebuild")
    _serving_binding_identity(serving_binding)
    if (
        Path(str(serving_binding.get("active_pointer_path") or "")).resolve()
        != active_release_pointer
        or Path(str(serving_binding.get("releases_root") or "")).resolve()
        != releases_root
    ):
        raise ValueError(
            "explicit serving release inputs do not match the manifest"
        )
    if manifest.get("status") != "PASS":
        raise ValueError("blocked replay-cache manifest cannot be applied")
    if (manifest.get("reachability") or {}).get("status") != "COMPLETE":
        raise ValueError("incomplete reachability cannot be applied")
    if manifest.get("ambiguities"):
        raise ValueError("ambiguous replay-cache manifest cannot be applied")
    if (manifest.get("quota") or {}).get("reachable_exceeds_quota"):
        raise ValueError("reachable cache bytes exceed quota")
    review = manifest.get("operator_review") or {}
    if (
        review.get("approved") is not True
        or not str(review.get("approved_by") or "").strip()
        or not str(review.get("approved_at_utc") or "").strip()
        or not str(review.get("note") or "").strip()
    ):
        raise ValueError(
            "cleanup manifest lacks explicit operator approval identity, "
            "timestamp, or note"
        )
    reachability = manifest.get("reachability") or {}
    consumers = reachability.get("consumer_roots") or []
    if not isinstance(consumers, list) or not consumers or any(
        not isinstance(value, str) or not value for value in consumers
    ):
        raise ValueError("manifest replay-cache consumer roots are invalid")
    try:
        clob_max_age_seconds = float(reachability.get("clob_max_age_seconds"))
    except (TypeError, ValueError) as exc:
        raise ValueError("manifest CLOB max age is invalid") from exc
    if not math.isfinite(clob_max_age_seconds) or clob_max_age_seconds <= 0:
        raise ValueError("manifest CLOB max age must be positive and finite")
    candidates = manifest.get("candidates") or []
    candidate_paths = [str(row.get("path") or "") for row in candidates]
    if len(candidate_paths) != len(set(candidate_paths)):
        raise ValueError("cleanup manifest contains duplicate candidate paths")

    preflight = build_cleanup_preflight(manifest, root=cache_root)
    actions = [
        {
            "path": row.get("path"),
            "bytes": int(row.get("bytes") or 0),
            "sha256": row.get("sha256"),
            "identity": row.get("identity"),
            "reason": row.get("reason"),
            "file_identity": row.get("file_identity"),
            "status": "PLANNED",
        }
        for row in candidates
    ]
    receipt = {
        "receipt_format": RECEIPT_FORMAT,
        "generated_at_utc": utc_iso(),
        "status": "APPLYING",
        "manifest_path": str(manifest_path),
        "manifest_sha256": before_hash,
        "manifest_bytes": int(manifest_after.st_size),
        "manifest_file_identity": _file_identity(manifest_after),
        "root": str(cache_root),
        "protected_roots": [str(path) for path in normalized_protected_roots],
        "output_root": str(output_root),
        "cleanup_preflight": preflight,
        "actions": actions,
        "deleted_count": 0,
        "deleted_bytes": 0,
        "stop_on_first_failure": True,
        "directory_removal_permitted": False,
    }
    json_path = output_root / "replay_cache_retention_apply_receipt.json"
    report_path = output_root / "replay_cache_retention_apply_receipt.md"
    _write_apply_receipt(receipt, json_path=json_path, report_path=report_path)
    if preflight.get("status") != "PASS":
        receipt["status"] = "BLOCKED_BY_CLEANUP_PREFLIGHT"
        for row in actions:
            row["status"] = "UNATTEMPTED"
        _write_apply_receipt(receipt, json_path=json_path, report_path=report_path)
        return receipt

    for index, candidate in enumerate(candidates):
        action = actions[index]
        try:
            # Source identities and the exact candidate are checked inside the
            # smallest practical window before this one unlink.
            source_files = reachability.get("source_files") or []
            _recompute_candidate_eligibility(
                candidate,
                corpus_paths=corpus_paths,
                registry_path=registry_path,
                consumers=consumers,
                clob_max_age_seconds=clob_max_age_seconds,
                expected_sources=source_files,
                protected_roots=normalized_protected_roots,
                active_release_pointer=active_release_pointer,
                releases_root=releases_root,
                expected_serving_binding=serving_binding,
            )
            path = _verify_apply_candidate(candidate, cache_root=cache_root)
            parity = _cache_off_rebuild_candidate(
                candidate,
                cache_root=cache_root,
                corpus_paths=corpus_paths,
                registry_path=registry_path,
                consumers=consumers,
                clob_max_age_seconds=clob_max_age_seconds,
                expected_sources=source_files,
                protected_roots=normalized_protected_roots,
                active_release_pointer=active_release_pointer,
                releases_root=releases_root,
                expected_serving_binding=serving_binding,
            )
            action["cache_off_rebuild_parity"] = parity
            if parity["status"] != "PASS":
                raise ValueError("cache-off rebuild parity blocked candidate unlink")
            action["status"] = "PRE_UNLINK"
            action["pre_unlink_at_utc"] = utc_iso()
            action["pre_unlink_file_identity"] = _file_identity(path.lstat())
            _write_apply_receipt(receipt, json_path=json_path, report_path=report_path)
            # A crash after this durable write-ahead record leaves an explicit
            # uncertain PRE_UNLINK state. Recompute again after persisting it,
            # then pin the exact candidate immediately before unlink.
            _recompute_candidate_eligibility(
                candidate,
                corpus_paths=corpus_paths,
                registry_path=registry_path,
                consumers=consumers,
                clob_max_age_seconds=clob_max_age_seconds,
                expected_sources=source_files,
                protected_roots=normalized_protected_roots,
                active_release_pointer=active_release_pointer,
                releases_root=releases_root,
                expected_serving_binding=serving_binding,
            )
            path = _verify_apply_candidate(candidate, cache_root=cache_root)
            immediate_parity = _cache_off_rebuild_candidate(
                candidate,
                cache_root=cache_root,
                corpus_paths=corpus_paths,
                registry_path=registry_path,
                consumers=consumers,
                clob_max_age_seconds=clob_max_age_seconds,
                expected_sources=source_files,
                protected_roots=normalized_protected_roots,
                active_release_pointer=active_release_pointer,
                releases_root=releases_root,
                expected_serving_binding=serving_binding,
            )
            action["immediate_pre_unlink_cache_off_rebuild_parity"] = (
                immediate_parity
            )
            if immediate_parity["status"] != "PASS":
                raise ValueError(
                    "immediate pre-unlink cache-off rebuild parity blocked "
                    "candidate unlink"
                )
            # Persist the second proof before pinning and unlinking the exact
            # cache entry. A failed durable receipt write retains the file.
            _write_apply_receipt(
                receipt,
                json_path=json_path,
                report_path=report_path,
            )
            # Receipt I/O is outside the protected roots and can take
            # non-trivial time on a slow volume. Recompute live reachability
            # and every pinned source identity again afterward so the next
            # operation is the exact candidate verification and unlink.
            _recompute_candidate_eligibility(
                candidate,
                corpus_paths=corpus_paths,
                registry_path=registry_path,
                consumers=consumers,
                clob_max_age_seconds=clob_max_age_seconds,
                expected_sources=source_files,
                protected_roots=normalized_protected_roots,
                active_release_pointer=active_release_pointer,
                releases_root=releases_root,
                expected_serving_binding=serving_binding,
            )
            path = _verify_apply_candidate(candidate, cache_root=cache_root)
            path.unlink()
            if path.exists():
                raise OSError(f"candidate still exists after unlink: {path}")
            action["status"] = "DELETED"
            action["deleted_at_utc"] = utc_iso()
            receipt["deleted_count"] += 1
            receipt["deleted_bytes"] += int(action["bytes"])
            _write_apply_receipt(receipt, json_path=json_path, report_path=report_path)
        except Exception as exc:  # noqa: BLE001 - persist exact first failure.
            action["status"] = "FAILED"
            action["error"] = f"{type(exc).__name__}: {exc}"
            for remaining in actions[index + 1 :]:
                remaining["status"] = "UNATTEMPTED"
            receipt["status"] = "FAILED"
            receipt["first_failure_index"] = index
            _write_apply_receipt(receipt, json_path=json_path, report_path=report_path)
            return receipt

    receipt["status"] = "APPLIED"
    receipt["completed_at_utc"] = utc_iso()
    _write_apply_receipt(receipt, json_path=json_path, report_path=report_path)
    return receipt


def _cache_off_rebuild_candidate(
    candidate: dict[str, Any],
    *,
    cache_root: Path,
    corpus_paths: Iterable[Path],
    registry_path: Path,
    consumers: Iterable[str],
    clob_max_age_seconds: float,
    expected_sources: Iterable[dict[str, Any]],
    protected_roots: Iterable[Path],
    active_release_pointer: Path,
    releases_root: Path,
    expected_serving_binding: dict[str, Any],
    abs_tolerance: float = replay_cache.SENTINEL_NUMERIC_ABS_TOLERANCE,
) -> dict[str, Any]:
    """Recompute one exact cache entry without consulting the cache.

    Every available corpus/artifact binding that produces the candidate's full
    key must independently reproduce every field consumed on a cache hit.
    Source identities and the cache entry are pinned before and after compute.
    """

    path = _verify_apply_candidate(candidate, cache_root=cache_root)
    cached = _strict_json(path)
    cached_key = _full_key(cached.get("key") or {})
    key_tuple = _key_tuple(cached_key)
    if not all(cached_key.values()):
        raise ValueError("candidate cache entry has an incomplete full key")

    _verify_source_files(expected_sources)
    corpus_roots, corpus_sources = _load_corpora(
        corpus_paths,
        protected_roots=protected_roots,
    )
    registry, registry_source = _load_registry(registry_path)
    artifact_roots, artifact_sources = _artifact_roots(registry)
    serving_binding, serving_sources = _load_serving_rebuild_context(
        active_release_pointer,
        releases_root,
    )
    _verify_serving_market_coverage(corpus_roots, serving_binding)
    if _serving_binding_identity(serving_binding) != _serving_binding_identity(
        expected_serving_binding
    ):
        raise ValueError("serving rebuild binding changed")
    actual_sources = [
        registry_source,
        *corpus_sources,
        *artifact_sources,
        *serving_sources,
    ]
    if _source_contract(actual_sources) != _source_contract(expected_sources):
        raise ValueError("rebuild source set or exact source identity changed")
    reachable, rebuildable = _build_key_maps(
        corpus_roots,
        artifact_roots,
        consumers=consumers,
        clob_max_age_seconds=clob_max_age_seconds,
    )
    if key_tuple in reachable:
        raise ValueError("candidate full cache key is now reachable")
    source_rows = rebuildable.get(key_tuple) or []
    if not source_rows:
        raise ValueError("candidate full cache key has no rebuild source")
    serving_bundle = _load_pinned_serving_bundle(expected_serving_binding)

    corpus_by_path = {
        str(root["path"]): root
        for root in corpus_roots
    }
    artifact_by_path = {
        str(root["path"]): root
        for root in artifact_roots
    }
    bindings = []
    for source_row in sorted(
        source_rows,
        key=lambda row: (
            str(row.get("corpus_path") or ""),
            str(row.get("artifact_path") or ""),
            str(row.get("config_fp") or ""),
            str(row.get("variant_id") or ""),
        ),
    ):
        corpus_root = corpus_by_path.get(str(source_row.get("corpus_path") or ""))
        artifact_root = artifact_by_path.get(str(source_row.get("artifact_path") or ""))
        if corpus_root is None or artifact_root is None:
            raise ValueError("rebuild binding no longer resolves to its source roots")
        if str(source_row.get("config_fp") or "") != cached_key["config_fp"]:
            raise ValueError("rebuild binding config fingerprint changed")
        matching_entries = []
        for entry in corpus_root["manifest"].get("entries") or []:
            expected_key = replay_cache.key_for_entry(
                entry,
                consumer=cached_key["consumer"],
                model_fp=artifact_root["model_fp"],
                config_fp=str(source_row["config_fp"]),
            )
            if _key_tuple(expected_key.metadata()) == key_tuple:
                matching_entries.append((entry, expected_key))
        if len(matching_entries) != 1:
            raise ValueError(
                "rebuild binding must resolve exactly one manifest entry for "
                f"{cached_key['event_slug']}: found {len(matching_entries)}"
            )
        entry, expected_key = matching_entries[0]
        manifest = corpus_root["manifest"]
        snapshots_root = _assert_no_reparse_components(
            str(manifest.get("snapshots_root") or ""),
            label="rebuild snapshots root",
        ).resolve(strict=True)
        relative = Path(
            str(
                entry.get("folder_relative_to_snapshots_root")
                or entry.get("folder_name")
                or entry.get("event_slug")
                or ""
            )
        )
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise ValueError(f"rebuild folder path is unsafe: {relative}")
        folder = _assert_no_reparse_components(
            snapshots_root / relative,
            label="rebuild event folder",
        ).resolve(strict=True)
        if (
            not folder.is_dir()
            or not _within(folder, snapshots_root)
            or folder.name != cached_key["event_slug"]
        ):
            raise ValueError(f"rebuild event folder identity is invalid: {folder}")
        # Sanitize host-specific folder aliases to the verified snapshots root.
        compute_entries = []
        for manifest_entry in manifest.get("entries") or []:
            manifest_relative = Path(
                str(
                    manifest_entry.get("folder_relative_to_snapshots_root")
                    or manifest_entry.get("folder_name")
                    or manifest_entry.get("event_slug")
                    or ""
                )
            )
            if (
                manifest_relative.is_absolute()
                or not manifest_relative.parts
                or any(
                    part in {"", ".", ".."}
                    for part in manifest_relative.parts
                )
            ):
                raise ValueError(
                    "rebuild manifest contains an unsafe folder alias"
                )
            canonical_folder = _assert_no_reparse_components(
                snapshots_root / manifest_relative,
                label="rebuild manifest event folder",
            ).resolve(strict=True)
            if (
                not canonical_folder.is_dir()
                or not _within(canonical_folder, snapshots_root)
                or canonical_folder.name
                != str(manifest_entry.get("event_slug") or "")
            ):
                raise ValueError(
                    "rebuild manifest folder alias does not resolve to its "
                    "verified event folder"
                )
            compute_entry = dict(manifest_entry)
            compute_entry["folder"] = str(canonical_folder)
            compute_entry["folder_name"] = canonical_folder.name
            compute_entry["folder_relative_to_snapshots_root"] = (
                manifest_relative.as_posix()
            )
            compute_entries.append(compute_entry)
        compute_manifest = dict(manifest)
        compute_manifest["snapshots_root"] = str(snapshots_root)
        compute_manifest["entries"] = compute_entries

        TorontoHighTempModel.clear_historical_cache()
        artifact = artifact_root["artifact"]
        prediction_mode = artifact.get("prediction_mode") or "bucket_distribution"
        family_unit = artifact.get("family_unit") or (
            "all" if prediction_mode == "residual_distribution_v1" else "F"
        )
        computed = _compute_pooled_candidate_day(
            SimpleNamespace(
                snapshots_root=str(snapshots_root),
                clob_max_age_seconds=float(clob_max_age_seconds),
                long_job_guard_info=None,
            ),
            compute_manifest,
            folder,
            artifact,
            family_unit=family_unit,
            prediction_mode=prediction_mode,
            defer_settlement_join=False,
            serving_bundle=serving_bundle,
        )
        warnings = (
            (computed.get("replay_results") or {}).get("corpus_warnings") or []
        )
        if warnings:
            raise ValueError(
                "cache-off rebuild reported corpus warnings: "
                + "; ".join(map(str, warnings))
            )
        rebuilt = {
            "key": expected_key.metadata(),
            "rows": computed.get("candidate_rows"),
            "replay_results": computed.get("replay_results"),
            "coverage": computed.get("coverage"),
            "diagnostics": computed.get("diagnostics"),
        }
        checks = _cache_payload_parity_checks(
            cached,
            rebuilt,
            abs_tolerance=abs_tolerance,
        )
        bindings.append(
            {
                "status": (
                    "PASS"
                    if all(row["status"] == "PASS" for row in checks)
                    else "BLOCK"
                ),
                "corpus_path": str(corpus_root["path"]),
                "corpus_sha256": corpus_root["source"]["sha256"],
                "corpus_hash": str(manifest.get("corpus_hash") or ""),
                "artifact_path": str(artifact_root["path"]),
                "artifact_sha256": artifact_root["source"]["sha256"],
                "variant_id": artifact_root["variant_id"],
                "full_key": expected_key.metadata(),
                "checks": checks,
            }
        )

    _verify_source_files(expected_sources)
    path = _verify_apply_candidate(candidate, cache_root=cache_root)
    status = (
        "PASS"
        if bindings and all(row["status"] == "PASS" for row in bindings)
        else "BLOCK"
    )
    return {
        "receipt_format": CACHE_OFF_PARITY_SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": status,
        "mode": "cache_off_compute",
        "compute_callable": (
            "weather.calibration.pooled_candidate_replay."
            "_compute_pooled_candidate_day"
        ),
        "cache_entry": {
            "path": str(path),
            "bytes": int(path.stat().st_size),
            "sha256": sha256_file(path),
            "file_identity": _file_identity(path.lstat()),
            "full_key": cached_key,
            "identity": _identity_digest(cached_key),
        },
        "source_contract": _source_contract(expected_sources),
        "abs_tolerance": float(abs_tolerance),
        "bindings": bindings,
        "proof_scope": (
            "real cache-off recomputation of all cache-hit consumed fields for "
            "every exact corpus/artifact binding of one full cache key"
        ),
    }


def rebuild_one_parity(
    cache_entry_path: str | Path,
    rebuilt_payload_path: str | Path,
    *,
    abs_tolerance: float = replay_cache.SENTINEL_NUMERIC_ABS_TOLERANCE,
) -> dict[str, Any]:
    """Compare all fields consumed on a cache hit against one rebuilt fixture."""

    cache_entry_source, _ = _stable_source(
        cache_entry_path,
        kind="rebuild_one_cache_entry",
    )
    rebuilt_payload_source, _ = _stable_source(
        rebuilt_payload_path,
        kind="rebuild_one_payload",
    )
    cache_entry_path = Path(cache_entry_source["path"])
    rebuilt_payload_path = Path(rebuilt_payload_source["path"])
    cached = _strict_json(cache_entry_path)
    rebuilt = _strict_json(rebuilt_payload_path)
    checks = _cache_payload_parity_checks(
        cached,
        rebuilt,
        abs_tolerance=abs_tolerance,
    )
    cached_key = _full_key(cached.get("key") or {})
    rebuilt_key = _full_key(rebuilt.get("key") or {})
    _verify_source_files([cache_entry_source, rebuilt_payload_source])
    return {
        "receipt_format": FIXTURE_PARITY_SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": "PASS" if all(row["status"] == "PASS" for row in checks) else "BLOCK",
        "cache_entry": {
            **cache_entry_source,
            "full_key": cached_key,
            "identity": _identity_digest(cached_key),
        },
        "rebuilt_payload": {
            **rebuilt_payload_source,
            "full_key": rebuilt_key,
        },
        "proof_scope": (
            "comparison of two operator-supplied payload files only; this is "
            "a fixture diagnostic and does not prove retained inputs or an "
            "actual cache-off rebuild"
        ),
        "abs_tolerance": float(abs_tolerance),
        "checks": checks,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dry-run-first reachability cleanup for replay-cache entries."
    )
    parser.add_argument("--cache-root", default="")
    parser.add_argument("--corpus", action="append", default=[])
    parser.add_argument("--registry", default="")
    parser.add_argument("--output-root", required=True)
    parser.add_argument(
        "--protected-root",
        action="append",
        required=True,
        help=(
            "Explicit data or mirror root protected from output writes; repeat "
            "for every source/mirror boundary. One root must contain cache-root."
        ),
    )
    parser.add_argument("--quota-bytes", type=int, default=DEFAULT_QUOTA_BYTES)
    parser.add_argument("--consumer", action="append", default=[])
    parser.add_argument("--clob-max-age-seconds", type=float, default=DEFAULT_CLOB_MAX_AGE_SECONDS)
    parser.add_argument(
        "--active-release-pointer",
        default=str(DEFAULT_ACTIVE_RELEASE_POINTER),
    )
    parser.add_argument(
        "--releases-root",
        default=str(DEFAULT_RELEASES_ROOT),
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--expected-manifest-sha256", default="")
    parser.add_argument("--rebuild-one-cache-entry", default="")
    parser.add_argument("--rebuild-one-payload", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    consumers = args.consumer or [DEFAULT_CONSUMER]
    if args.rebuild_one_cache_entry or args.rebuild_one_payload:
        if not args.rebuild_one_cache_entry or not args.rebuild_one_payload:
            raise ValueError("rebuild-one requires both cache entry and rebuilt payload")
        output_root = _validated_standalone_output_root(
            args.output_root,
            args.protected_root,
        )
        payload = rebuild_one_parity(
            args.rebuild_one_cache_entry,
            args.rebuild_one_payload,
        )
        write_json_atomic(
            output_root / "replay_cache_rebuild_one_parity.json",
            payload,
            trailing_newline=True,
        )
        write_text_atomic(
            output_root / "replay_cache_rebuild_one_parity.md",
            render_rebuild_one(payload),
        )
        print(f"Replay-cache rebuild-one parity: {payload['status']}")
        return 0 if payload["status"] == "PASS" else 2
    if not args.cache_root or not args.corpus or not args.registry:
        raise ValueError(
            "plan/apply requires --cache-root, at least one --corpus, and "
            "--registry"
        )
    output_root, _protected_root = _validated_output_root(
        args.cache_root,
        args.output_root,
        args.protected_root,
    )
    if args.apply:
        if not args.manifest or not args.expected_manifest_sha256:
            raise ValueError("apply requires --manifest and --expected-manifest-sha256")
        receipt = apply_retention_manifest(
            args.manifest,
            expected_manifest_sha256=args.expected_manifest_sha256,
            cache_root=args.cache_root,
            corpora=args.corpus,
            registry_path=args.registry,
            output_root=output_root,
            protected_roots=args.protected_root,
            active_release_pointer=args.active_release_pointer,
            releases_root=args.releases_root,
        )
        print(f"Replay-cache retention apply: {receipt['status']}")
        return 0 if receipt["status"] == "APPLIED" else 2
    payload = build_retention_plan(
        cache_root=args.cache_root,
        corpora=args.corpus,
        registry_path=args.registry,
        output_root=output_root,
        protected_roots=args.protected_root,
        quota_bytes=args.quota_bytes,
        consumers=consumers,
        clob_max_age_seconds=args.clob_max_age_seconds,
        active_release_pointer=args.active_release_pointer,
        releases_root=args.releases_root,
    )
    json_path, report_path = write_plan_outputs(payload, output_root)
    print(f"Replay-cache retention dry run: {payload['status']}")
    print(f"Manifest written to {json_path}")
    print(f"Report written to {report_path}")
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
