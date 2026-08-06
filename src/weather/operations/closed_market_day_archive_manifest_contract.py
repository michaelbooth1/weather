"""Dependency-safe shape and self-hash contract for closed-day archives."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from weather.schema_registry import schema_version


MANIFEST_SCHEMA_VERSION = schema_version("closed_market_day_archive_manifest")
ARCHIVE_ROOT_VERSION = "v0.1"
MARKET_DAY_PARTITION_KEYS = ("local_date", "market_id", "event_slug")
COUNTABLE_QUALITY_GRADES = ("complete", "manual_override")
ELIGIBLE_FINALIZATION_STATES = (
    "settled_countable",
    "settled_non_countable",
    "closed_unlabeled",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ARTIFACT_FAMILY_NAMES = frozenset(
    {
        "snapshots_long",
        "features_long",
        "components_long",
        "forecasts_long",
        "forecast_payloads_long",
        "observation_payloads_long",
        "source_status_long",
        "replay_inputs",
        "replay_input_status",
        "clob_capture_status",
        "clob_tokens",
        "order_books_summary",
        "order_books_long",
        "price_history",
        "market_ws_events",
        "maker_execution_tape",
        "clob_features_long",
        "variant_predictions_long",
    }
)


def _integer(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def manifest_content_hash(manifest: dict[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("manifest_hash", None)
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def manifest_hash_valid(manifest: dict[str, Any]) -> bool:
    return bool(manifest.get("manifest_hash")) and manifest.get(
        "manifest_hash"
    ) == manifest_content_hash(manifest)


def validate_manifest_shape(manifest: dict[str, Any]) -> list[str]:
    """Validate the complete v0.1 manifest shape without opening Parquet."""

    errors: list[str] = []
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        errors.append("schema_version must be closed_market_day_archive_manifest_v0.1")
    if manifest.get("archive_root_version") != ARCHIVE_ROOT_VERSION:
        errors.append(f"archive_root_version must be {ARCHIVE_ROOT_VERSION}")
    for key in (
        "generated_at_utc",
        "writer",
        "writer_version",
        "source_folder",
        "manifest_hash",
    ):
        if not manifest.get(key):
            errors.append(f"{key} is required")

    partition = manifest.get("partition")
    if not isinstance(partition, dict):
        errors.append("partition must be an object")
    else:
        for key in MARKET_DAY_PARTITION_KEYS:
            if not partition.get(key):
                errors.append(f"partition.{key} is required")

    finalization = manifest.get("finalization")
    if not isinstance(finalization, dict):
        errors.append("finalization must be an object")
    else:
        state = finalization.get("state")
        if state not in ELIGIBLE_FINALIZATION_STATES:
            errors.append(
                "finalization.state must be one of "
                + ", ".join(ELIGIBLE_FINALIZATION_STATES)
            )
        if "countable" not in finalization:
            errors.append("finalization.countable is required")
        if (
            state == "settled_countable"
            and finalization.get("quality_grade") not in COUNTABLE_QUALITY_GRADES
        ):
            errors.append(
                "settled_countable finalization requires a countable quality_grade"
            )

    validation = manifest.get("validation")
    if not isinstance(validation, dict):
        errors.append("validation must be an object")
    elif validation.get("status") not in {"PASS", "WARN", "BLOCK"}:
        errors.append("validation.status must be PASS, WARN, or BLOCK")

    event_manifest = manifest.get("event_day_manifest")
    if not isinstance(event_manifest, dict):
        errors.append("event_day_manifest must be an object")
    else:
        if event_manifest.get("status") != "PASS":
            errors.append("event_day_manifest.status must be PASS")
        if not event_manifest.get("path"):
            errors.append("event_day_manifest.path is required")
        if not SHA256_RE.fullmatch(str(event_manifest.get("manifest_hash") or "")):
            errors.append("event_day_manifest.manifest_hash must be SHA-256")

    release_runtime_identity = manifest.get("release_runtime_identity")
    if not isinstance(release_runtime_identity, dict):
        errors.append("release_runtime_identity must be an object")
    else:
        if (
            release_runtime_identity.get("release_identity_status") != "SINGLE"
            or _integer(release_runtime_identity.get("release_identity_count")) != 1
        ):
            errors.append("release_runtime_identity must contain one release identity")
        release_rows = release_runtime_identity.get("release_identities")
        if (
            not isinstance(release_rows, list)
            or len(release_rows) != 1
            or not isinstance(release_rows[0], dict)
            or not str(release_rows[0].get("release_id") or "").strip()
        ):
            errors.append("release_runtime_identity.release_identities must name one release")
        if (
            release_runtime_identity.get("runtime_identity_status") != "SINGLE"
            or _integer(release_runtime_identity.get("runtime_identity_count")) != 1
            or release_runtime_identity.get("mixed_runtime_identity") is not False
        ):
            errors.append("release_runtime_identity must contain one runtime identity")
        runtime_rows = release_runtime_identity.get("runtime_identities")
        if (
            not isinstance(runtime_rows, list)
            or len(runtime_rows) != 1
            or not isinstance(runtime_rows[0], dict)
            or not str(runtime_rows[0].get("runtime_key") or "").strip()
        ):
            errors.append("release_runtime_identity.runtime_identities must name one runtime")
        if release_runtime_identity.get("proof_grade_status") != "PASS":
            errors.append("release_runtime_identity.proof_grade_status must be PASS")

    families = manifest.get("artifact_families")
    if not isinstance(families, list) or not families:
        errors.append("artifact_families must be a non-empty list")
        return errors
    for index, family in enumerate(families):
        if not isinstance(family, dict):
            errors.append(f"artifact_families[{index}] must be an object")
            continue
        name = family.get("artifact_family")
        if name not in ARTIFACT_FAMILY_NAMES:
            errors.append(f"artifact_families[{index}].artifact_family is unknown")
        status = family.get("status")
        if status not in {"parquet", "raw_reference_only", "missing_source", "skipped"}:
            errors.append(f"artifact_families[{index}].status is invalid")
        if status in {"parquet", "raw_reference_only"} and not family.get(
            "source_files"
        ):
            errors.append(f"artifact_families[{index}].source_files is required")
        for source_index, source in enumerate(family.get("source_files") or []):
            if not isinstance(source, dict):
                errors.append(
                    f"artifact_families[{index}].source_files[{source_index}] must be an object"
                )
                continue
            for key in ("path", "bytes", "sha256", "role"):
                if key not in source:
                    errors.append(
                        f"artifact_families[{index}].source_files[{source_index}].{key} is required"
                    )
        if status == "parquet":
            parquet = family.get("parquet")
            if not isinstance(parquet, dict):
                errors.append(f"artifact_families[{index}].parquet is required")
            else:
                for key in (
                    "path",
                    "bytes",
                    "sha256",
                    "row_count",
                    "codec",
                    "schema_fingerprint",
                ):
                    if key not in parquet:
                        errors.append(f"artifact_families[{index}].parquet.{key} is required")
    return errors


__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "ARCHIVE_ROOT_VERSION",
    "MARKET_DAY_PARTITION_KEYS",
    "COUNTABLE_QUALITY_GRADES",
    "ELIGIBLE_FINALIZATION_STATES",
    "manifest_content_hash",
    "manifest_hash_valid",
    "validate_manifest_shape",
]
