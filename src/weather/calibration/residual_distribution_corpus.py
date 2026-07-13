"""Point-in-time corpus materialization for ``ResidualDistributionV1``.

The legacy pooled trainers rebuild historical feature rows from daily files.
That path cannot prove which provider payload was available at prediction time
and fills several missing values with healthy-looking defaults.  This module
instead consumes the captured ``replay_inputs.jsonl`` payload, selects exactly
one declared checkpoint per market/date/cutoff, and joins settlement only after
the point-in-time feature context has been built.

The materializer is deliberately independent of model fitting.  A caller may
inject a feature builder for tests; the default builder runs the same pure
``ResidualDistributionV1`` canonicalizer used by live shadow inference.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from weather.io import sha256_file
from weather.experiment_contract import canonical_json, finalize_self_hash
from weather.backtesting.settled_days import discover_settled_folders, folder_market_id
from weather.market.market_registry import REGISTRY
from weather.model.continuous_density import native_to_f
from weather.model.feature_store import FEATURE_SCHEMA_VERSION
from weather.model.model_constants import INTRADAY_CUTOFF_HOURS
from weather.model.residual_distribution_v1 import (
    residual_band_key,
    validate_market_band_partition,
)
from weather.operations.closed_market_day_archive import DEFAULT_SNAPSHOTS_ROOT
from weather.operations.event_day_manifest import (
    REQUIRED_EVENT_DAY_ARTIFACT_FAMILY_NAMES,
    manifest_hash_valid as event_day_manifest_hash_valid,
    read_event_day_manifest,
    validate_event_day_manifest,
)
from weather.paths import data_path


CORPUS_SCHEMA_VERSION = "residual_distribution_training_corpus_v2"
MANIFEST_SCHEMA_VERSION = "residual_distribution_training_corpus_manifest_v2"
DEFAULT_MAX_CHECKPOINT_LATENESS_MINUTES = 15
REPLAY_INPUT_FILENAME = "replay_inputs.jsonl"
SETTLEMENT_FILENAME = "settlement.json"
SNAPSHOTS_LONG_FILENAME = "snapshots_long.csv"
VARIANT_PREDICTIONS_FILENAME = "variant_predictions.jsonl"
COMPARATOR_VARIANT_IDS = {
    "item50": "item50_pooled_forecast_v3_candidate",
    "dynamic_source": "pooled_f_dynamic_source_state_v0_1",
}
VERIFIED_RELEASE_IDENTITY_STATUSES = frozenset({
    "verified_inactive_shadow_bundle",
    "verified_serving_binding",
    "verified_variant_serving_bundle",
})
QUALIFICATION_INPUT_FILENAMES = (
    "event_day_manifest.json",
    REPLAY_INPUT_FILENAME,
    SETTLEMENT_FILENAME,
    SNAPSHOTS_LONG_FILENAME,
    VARIANT_PREDICTIONS_FILENAME,
    "forecast_payloads.jsonl",
    "observation_payloads.jsonl",
    "clob_capture_status.jsonl",
)
FORBIDDEN_FEATURE_TOKENS = (
    "settlement",
    "winning_band",
    "outcome",
    "label",
    "final_high",
    "final_bucket",
    "market_yes",
    "market_no",
    "edge",
)


class ResidualCorpusError(ValueError):
    """A source row cannot enter the point-in-time training corpus."""


def _parse_timestamp(value: Any, field: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ResidualCorpusError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ResidualCorpusError(f"{field} must include a timezone")
    return parsed


def _parse_date(value: Any, field: str = "target_date") -> date:
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError as exc:
        raise ResidualCorpusError(f"{field} must be an ISO date") from exc


def _finite(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _json_safe(value: Any) -> Any:
    """Replace model-native NaN/Inf sentinels with explicit JSON nulls."""

    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _folder_input_lineage(folder: Path) -> dict[str, Any]:
    files = {
        filename: {
            "exists": (folder / filename).is_file(),
            "sha256": sha256_file(folder / filename) if (folder / filename).is_file() else None,
            "bytes": (folder / filename).stat().st_size if (folder / filename).is_file() else None,
        }
        for filename in QUALIFICATION_INPUT_FILENAMES
    }
    missing = [filename for filename, row in files.items() if not row["exists"]]
    manifest_path = folder / "event_day_manifest.json"
    manifest = read_event_day_manifest(manifest_path)
    semantic_validation: dict[str, Any] | None = None
    semantic_error: str | None = None
    if manifest is not None:
        try:
            semantic_validation = validate_event_day_manifest(
                manifest,
                folder,
                snapshots_root=folder.parent,
                check_hashes=True,
                check_row_counts=True,
                fail_on_extra=True,
            )
        except (OSError, TypeError, ValueError) as exc:
            semantic_error = f"{type(exc).__name__}: {exc}"

    records = [
        {
            **dict(record),
            "_manifest_family": str(family.get("artifact_family") or ""),
        }
        for family in (manifest or {}).get("artifact_families") or []
        if isinstance(family, Mapping)
        for record in family.get("files") or []
        if isinstance(record, Mapping)
    ]
    records_by_path: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        records_by_path[str(record.get("path") or "")].append(record)
    exact_file_proofs: dict[str, dict[str, Any]] = {}
    for filename in QUALIFICATION_INPUT_FILENAMES:
        if filename == "event_day_manifest.json":
            exact_file_proofs[filename] = {
                "record_count": 1 if manifest is not None else 0,
                "manifest_record_sha256": (
                    str((manifest or {}).get("manifest_hash") or "") or None
                ),
                "actual_sha256": files[filename]["sha256"],
                "status": (
                    "PASS"
                    if manifest is not None
                    and files[filename]["exists"]
                    and event_day_manifest_hash_valid(manifest)
                    else "BLOCK"
                ),
            }
            continue
        matches = records_by_path.get(filename) or []
        declared_hash = str(matches[0].get("sha256") or "") if len(matches) == 1 else ""
        exact_file_proofs[filename] = {
            "record_count": len(matches),
            "manifest_record_sha256": declared_hash or None,
            "actual_sha256": files[filename]["sha256"],
            "status": (
                "PASS"
                if len(matches) == 1
                and bool(files[filename]["exists"])
                and declared_hash == files[filename]["sha256"]
                else "BLOCK"
            ),
        }

    required_family_check = next(
        (
            check
            for check in (semantic_validation or {}).get("checks") or []
            if check.get("check") == "required_families"
        ),
        {},
    )
    identity = (manifest or {}).get("release_runtime_identity") or {}
    release_rows = identity.get("release_identities") or []
    runtime_rows = identity.get("runtime_identities") or []
    expected_release_id = (
        str(release_rows[0].get("release_id") or "")
        if len(release_rows) == 1 and isinstance(release_rows[0], Mapping)
        else ""
    )
    expected_runtime_identity = (
        dict(runtime_rows[0])
        if len(runtime_rows) == 1 and isinstance(runtime_rows[0], Mapping)
        else {}
    )
    manifest_bound_hashes = _manifest_bound_identity_hashes(folder, records)
    embedded_status = str(
        (((manifest or {}).get("validation") or {}).get("status") or "MISSING")
    )
    semantic_criteria = {
        "manifest_readable": manifest is not None,
        "manifest_self_hash_valid": bool(
            manifest is not None and event_day_manifest_hash_valid(manifest)
        ),
        "embedded_manifest_status_accepted": embedded_status in {"PASS", "WARN"},
        "operational_semantic_validation_pass": (
            (semantic_validation or {}).get("status") == "PASS"
        ),
        "mandatory_family_exact_evidence_pass": (
            required_family_check.get("status") == "PASS"
            and required_family_check.get("required_families")
            == list(REQUIRED_EVENT_DAY_ARTIFACT_FAMILY_NAMES)
        ),
        "qualification_files_exactly_manifest_proven": bool(exact_file_proofs)
        and all(row["status"] == "PASS" for row in exact_file_proofs.values()),
        "release_identity_singular": (
            identity.get("release_identity_status") == "SINGLE"
            and identity.get("release_identity_count") == 1
            and bool(expected_release_id)
        ),
        "runtime_identity_singular_and_complete": (
            identity.get("runtime_identity_status") == "SINGLE"
            and identity.get("runtime_identity_count") == 1
            and bool(expected_runtime_identity.get("git_commit"))
            and bool(expected_runtime_identity.get("source_fingerprint"))
        ),
        "proof_grade_identity_pass": identity.get("proof_grade_status") == "PASS",
    }
    semantic_manifest = {
        "path": str(manifest_path),
        "file_sha256": files["event_day_manifest.json"]["sha256"],
        "schema_version": (manifest or {}).get("schema_version"),
        "manifest_hash": (manifest or {}).get("manifest_hash"),
        "embedded_validation_status": embedded_status,
        "operational_validation_status": (semantic_validation or {}).get("status")
        or "BLOCK",
        "operational_validation_blockers": [
            str(check.get("check") or "unknown")
            for check in (semantic_validation or {}).get("checks") or []
            if check.get("status") == "BLOCK"
        ],
        "semantic_error": semantic_error,
        "required_families": list(REQUIRED_EVENT_DAY_ARTIFACT_FAMILY_NAMES),
        "exact_file_proofs": exact_file_proofs,
        "expected_release_id": expected_release_id or None,
        "expected_runtime_identity": expected_runtime_identity,
        "manifest_bound_release_manifest_sha256s": manifest_bound_hashes[
            "release_manifest_sha256s"
        ],
        "manifest_bound_configuration_sha256s": manifest_bound_hashes[
            "configuration_sha256s"
        ],
        "expected_release_manifest_sha256": manifest_bound_hashes[
            "expected_release_manifest_sha256"
        ],
        "expected_configuration_sha256": manifest_bound_hashes[
            "expected_configuration_sha256"
        ],
        "criteria": semantic_criteria,
        "status": "PASS" if all(semantic_criteria.values()) else "BLOCK",
    }
    lineage = {
        "folder": str(folder),
        "files": files,
        "missing_required_files": missing,
        "semantic_event_day_manifest": semantic_manifest,
        "status": (
            "PASS"
            if not missing and semantic_manifest["status"] == "PASS"
            else "BLOCK"
        ),
    }
    lineage["lineage_sha256"] = hashlib.sha256(
        canonical_json(lineage).encode("utf-8")
    ).hexdigest()
    return lineage


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _unwrapped_runtime_identity(value: Any) -> dict[str, Any]:
    identity = _mapping(value)
    for key in ("current_identity", "process_identity"):
        nested = identity.get(key)
        if isinstance(nested, Mapping):
            identity = nested
    return dict(identity)


def _identity_values(
    containers: Sequence[Mapping[str, Any]],
    aliases: Sequence[str],
) -> list[str]:
    return sorted({
        str(container.get(alias)).strip()
        for container in containers
        for alias in aliases
        if container.get(alias) not in (None, "")
    })


def _manifest_bound_identity_hashes(
    folder: Path,
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Extract singular hash identities only from exact manifest-bound records.

    The operational manifest's current aggregate identity summary retains the
    release ID and runtime fingerprint but not every release/config hash alias.
    The underlying file records do bind their exact bytes.  Read only the
    identity-bearing canonical tapes whose current hash equals the declared
    record, and treat every declared value as a candidate so disagreement is a
    hard blocker rather than a first-value-wins fallback.
    """

    release_manifest_hashes: set[str] = set()
    configuration_hashes: set[str] = set()
    identity_families = {
        "snapshots",
        "replay_inputs",
        "variant_predictions",
        "snapshot_explanations",
        "forecast_payloads",
        "source_status",
    }

    def collect(container: Mapping[str, Any]) -> None:
        release_manifest_hashes.update(
            _identity_values([container], ("release_manifest_sha256",))
        )
        configuration_hashes.update(
            _identity_values(
                [container],
                ("configuration_sha256", "config_sha256", "release_config_sha256"),
            )
        )

    for record in records:
        if record.get("_manifest_family") not in identity_families:
            continue
        relative_path = str(record.get("path") or "")
        path = folder / relative_path
        if (
            not relative_path
            or path.suffix.lower() not in {".json", ".jsonl"}
            or not path.is_file()
            or record.get("validation_status") != "PASS"
            or sha256_file(path) != record.get("sha256")
        ):
            continue
        for declared_identity in record.get("release_identities") or []:
            if isinstance(declared_identity, Mapping):
                collect(declared_identity)
                configuration_hashes.update(
                    _identity_values([declared_identity], ("configuration_hash",))
                )
        try:
            payloads = read_jsonl(path) if path.suffix.lower() == ".jsonl" else [
                json.loads(path.read_text(encoding="utf-8"))
            ]
            for payload in payloads:
                if not isinstance(payload, Mapping):
                    continue
                collect(payload)
                for key in (
                    "release_identity",
                    "release_lineage",
                    "runtime_identity",
                    "runtime_guard",
                    "model_identity",
                    "config_identity",
                ):
                    nested = payload.get(key)
                    if isinstance(nested, Mapping):
                        collect(nested)
        except (OSError, json.JSONDecodeError, ResidualCorpusError):
            # The operational semantic validator records structured-file
            # failures separately; absence here simply withholds identity PASS.
            continue

    release_rows = sorted(release_manifest_hashes)
    configuration_rows = sorted(configuration_hashes)
    return {
        "release_manifest_sha256s": release_rows,
        "configuration_sha256s": configuration_rows,
        "expected_release_manifest_sha256": (
            release_rows[0]
            if len(release_rows) == 1 and _is_sha256(release_rows[0])
            else None
        ),
        "expected_configuration_sha256": (
            configuration_rows[0]
            if len(configuration_rows) == 1 and _is_sha256(configuration_rows[0])
            else None
        ),
    }


def _release_identity_proof(
    replay_row: Mapping[str, Any],
    *,
    input_lineage: Mapping[str, Any],
    replay_file_sha256: str,
    settlement_sha256: str,
) -> dict[str, Any]:
    model_identity = _mapping(replay_row.get("model_identity"))
    runtime_guard = _mapping(replay_row.get("runtime_guard"))
    runtime_identity = _unwrapped_runtime_identity(replay_row.get("runtime_identity"))
    containers = [
        replay_row,
        _mapping(replay_row.get("release_identity")),
        _mapping(replay_row.get("release_lineage")),
        model_identity,
        runtime_guard,
        runtime_identity,
    ]
    release_ids = _identity_values(
        containers,
        ("release_id", "serving_release_id", "model_release_id"),
    )
    release_manifest_hashes = _identity_values(
        containers,
        ("release_manifest_sha256",),
    )
    configuration_hashes = _identity_values(
        containers,
        ("configuration_sha256", "config_sha256", "release_config_sha256"),
    )
    semantic_manifest = _mapping(
        input_lineage.get("semantic_event_day_manifest")
    )
    expected_runtime = _mapping(semantic_manifest.get("expected_runtime_identity"))
    expected_release_id = str(semantic_manifest.get("expected_release_id") or "")
    expected_release_manifest_sha256 = str(
        semantic_manifest.get("expected_release_manifest_sha256") or ""
    )
    expected_configuration_sha256 = str(
        semantic_manifest.get("expected_configuration_sha256") or ""
    )
    runtime_candidates = [runtime_identity]
    for key in ("process_identity", "current_identity"):
        candidate = runtime_guard.get(key)
        if isinstance(candidate, Mapping):
            runtime_candidates.append(_unwrapped_runtime_identity(candidate))
    runtime_pairs = {
        (
            str(candidate.get("git_commit") or ""),
            str(candidate.get("source_fingerprint") or ""),
        )
        for candidate in runtime_candidates
        if candidate
    }
    exact_proofs = _mapping(semantic_manifest.get("exact_file_proofs"))
    replay_proof = _mapping(exact_proofs.get(REPLAY_INPUT_FILENAME))
    settlement_proof = _mapping(exact_proofs.get(SETTLEMENT_FILENAME))
    release_status = str(replay_row.get("release_identity_status") or "")
    criteria = {
        "semantic_event_manifest_pass": semantic_manifest.get("status") == "PASS",
        "qualification_lineage_pass": input_lineage.get("status") == "PASS",
        "replay_file_exact_manifest_hash_match": (
            replay_proof.get("status") == "PASS"
            and replay_proof.get("actual_sha256") == replay_file_sha256
        ),
        "settlement_file_exact_manifest_hash_match": (
            settlement_proof.get("status") == "PASS"
            and settlement_proof.get("actual_sha256") == settlement_sha256
        ),
        "verified_release_binding": release_status in VERIFIED_RELEASE_IDENTITY_STATUSES,
        "base_model_release_bound": replay_row.get("base_model_release_bound") is True,
        "release_id_singular_and_complete": len(release_ids) == 1,
        "release_id_matches_event_manifest": (
            len(release_ids) == 1
            and bool(expected_release_id)
            and release_ids[0] == expected_release_id
        ),
        "release_manifest_sha256_singular_and_valid": (
            len(release_manifest_hashes) == 1
            and _is_sha256(release_manifest_hashes[0])
        ),
        "release_manifest_sha256_matches_manifest_bound_identity": (
            len(release_manifest_hashes) == 1
            and bool(expected_release_manifest_sha256)
            and release_manifest_hashes[0] == expected_release_manifest_sha256
        ),
        "configuration_sha256_singular_and_valid": (
            len(configuration_hashes) == 1
            and _is_sha256(configuration_hashes[0])
        ),
        "configuration_sha256_matches_manifest_bound_identity": (
            len(configuration_hashes) == 1
            and bool(expected_configuration_sha256)
            and configuration_hashes[0] == expected_configuration_sha256
        ),
        "runtime_identity_complete": (
            bool(runtime_identity.get("git_commit"))
            and bool(runtime_identity.get("source_fingerprint"))
        ),
        "runtime_identity_consistent": len(runtime_pairs) == 1,
        "runtime_identity_matches_event_manifest": (
            bool(runtime_identity.get("git_commit"))
            and bool(runtime_identity.get("source_fingerprint"))
            and runtime_identity.get("git_commit") == expected_runtime.get("git_commit")
            and runtime_identity.get("source_fingerprint")
            == expected_runtime.get("source_fingerprint")
        ),
    }
    return {
        "status": "PASS" if all(criteria.values()) else "BLOCK",
        "criteria": criteria,
        "blockers": sorted(name for name, passed in criteria.items() if not passed),
        "qualification_input_lineage_sha256": input_lineage.get("lineage_sha256"),
        "event_day_manifest_sha256": semantic_manifest.get("file_sha256"),
        "event_day_manifest_hash": semantic_manifest.get("manifest_hash"),
        "release_identity_status": release_status or None,
        "observed_release_ids": release_ids,
        "expected_release_id": expected_release_id or None,
        "observed_release_manifest_sha256s": release_manifest_hashes,
        "expected_release_manifest_sha256": expected_release_manifest_sha256 or None,
        "observed_configuration_sha256s": configuration_hashes,
        "expected_configuration_sha256": expected_configuration_sha256 or None,
        "runtime_identity_sha256": _runtime_identity_sha256(runtime_identity),
        "runtime_git_commit": runtime_identity.get("git_commit"),
        "runtime_source_fingerprint": runtime_identity.get("source_fingerprint"),
        "expected_runtime_git_commit": expected_runtime.get("git_commit"),
        "expected_runtime_source_fingerprint": expected_runtime.get("source_fingerprint"),
    }


def _runtime_identity_sha256(identity: Any) -> str | None:
    if not isinstance(identity, Mapping) or not identity:
        return None
    stable_keys = (
        "source_fingerprint",
        "runtime_id",
        "git_commit",
        "config_sha256",
        "release_manifest_sha256",
        "release_id",
    )
    stable = {
        key: identity.get(key)
        for key in stable_keys
        if identity.get(key) not in (None, "")
    } or dict(identity)
    return hashlib.sha256(canonical_json(stable).encode("utf-8")).hexdigest()


def replay_input_sha256(row: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(_json_safe(dict(row))).encode("utf-8")).hexdigest()


def checkpoint_lateness_minutes(
    row: Mapping[str, Any],
    *,
    target_date: str | date,
    cutoff_hour: int,
) -> float:
    """Return minutes from the declared cutoff to the captured prediction.

    Checkpoints are the first capture at or after the wall-clock cutoff.  A
    negative value is therefore a pre-cutoff row and is never eligible.
    """

    captured = _parse_timestamp(
        row.get("captured_at_local") or row.get("built_at"),
        "captured_at_local",
    )
    expected_date = target_date if isinstance(target_date, date) else _parse_date(target_date)
    if captured.date() != expected_date:
        raise ResidualCorpusError(
            f"captured date {captured.date().isoformat()} does not match target date "
            f"{expected_date.isoformat()}"
        )
    cutoff = captured.replace(
        hour=int(cutoff_hour),
        minute=0,
        second=0,
        microsecond=0,
    )
    return (captured - cutoff).total_seconds() / 60.0


def collapse_to_predeclared_checkpoints(
    rows: Iterable[Mapping[str, Any]],
    *,
    target_date: str | date,
    cutoff_hours: Sequence[int] = INTRADAY_CUTOFF_HOURS,
    max_lateness_minutes: int = DEFAULT_MAX_CHECKPOINT_LATENESS_MINUTES,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Select one earliest nonnegative capture for every declared cutoff."""

    max_lateness = int(max_lateness_minutes)
    if max_lateness < 0:
        raise ValueError("max_lateness_minutes must be non-negative")
    materialized = [dict(row) for row in rows]
    selected: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for raw_hour in cutoff_hours:
        hour = int(raw_hour)
        eligible: list[tuple[float, str, dict[str, Any]]] = []
        invalid_count = 0
        for row in materialized:
            try:
                lateness = checkpoint_lateness_minutes(
                    row,
                    target_date=target_date,
                    cutoff_hour=hour,
                )
            except ResidualCorpusError:
                invalid_count += 1
                continue
            if 0.0 <= lateness <= max_lateness:
                eligible.append((lateness, str(row.get("snapshot_id") or ""), row))
        if not eligible:
            exclusions.append({
                "cutoff_hour": hour,
                "reason": "checkpoint_missing",
                "max_lateness_minutes": max_lateness,
                "invalid_timestamp_rows": invalid_count,
            })
            continue
        lateness, _snapshot_id, chosen = min(eligible, key=lambda item: (item[0], item[1]))
        chosen = dict(chosen)
        chosen["_captured_replay_input_sha256"] = replay_input_sha256(chosen)
        chosen["cutoff_hour"] = hour
        chosen["checkpoint_lateness_minutes"] = round(float(lateness), 6)
        selected.append(chosen)
    return selected, exclusions


def read_jsonl(path: str | Path) -> Iterable[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ResidualCorpusError(
                    f"{path}:{line_number} contains invalid JSON"
                ) from exc
            if not isinstance(payload, dict):
                raise ResidualCorpusError(f"{path}:{line_number} must be a JSON object")
            yield payload


def _status_from_source_item(item: Mapping[str, Any]) -> str:
    status = str(item.get("status") or "").strip().lower()
    if status:
        return status
    if bool(item.get("stale")):
        return "stale_cache"
    if bool(item.get("ok")):
        return "fresh"
    return "unknown"


def source_diagnostics_from_replay(
    sources: Mapping[str, Any] | None,
    *,
    captured_at: datetime,
) -> list[dict[str, Any]]:
    """Canonicalize raw replay source envelopes without inventing freshness."""

    diagnostics: list[dict[str, Any]] = []
    for name, raw_item in sorted((sources or {}).items()):
        item = raw_item if isinstance(raw_item, Mapping) else {}
        raw_age = item.get("cache_age_minutes")
        if raw_age is None:
            raw_age = item.get("age_minutes")
        age = _finite(raw_age)
        if age is None and item.get("fetched_at"):
            try:
                fetched = _parse_timestamp(item.get("fetched_at"), f"sources.{name}.fetched_at")
                age = max(
                    0.0,
                    (captured_at.astimezone(timezone.utc) - fetched.astimezone(timezone.utc)).total_seconds()
                    / 60.0,
                )
            except ResidualCorpusError:
                age = None
        diagnostics.append({
            "source": str(name),
            "source_family": item.get("source_family") or str(name),
            "status": _status_from_source_item(item),
            "age_minutes": age,
            "ttl_minutes": _finite(item.get("ttl_minutes")),
            "degradation_state": item.get("degradation_state"),
            "cache_status": item.get("cache_status"),
            "physical_validity_status": item.get("physical_validity_status"),
        })
    return diagnostics


def complete_band_definition(path: str | Path, *, unit: str = "F") -> list[dict[str, Any]]:
    """Read one ordered, complete market partition from a snapshot tape."""

    path = Path(path)
    if not path.exists():
        raise ResidualCorpusError(f"market band tape is missing: {path}")
    first_snapshot: str | None = None
    bands: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            snapshot_id = str(row.get("snapshot_id") or "")
            if first_snapshot is None:
                first_snapshot = snapshot_id
            if snapshot_id != first_snapshot:
                break
            value = _finite(row.get("bin_value_c"))
            value_hi = _finite(row.get("bin_value_hi_c"))
            if value is None:
                continue
            bands.append({
                "kind": str(row.get("bin_kind") or "eq"),
                "value": value,
                "value_hi": value if value_hi is None else value_hi,
                "label": str(row.get("range_label") or ""),
            })
    if not bands:
        raise ResidualCorpusError(f"market band tape has no usable partition: {path}")
    try:
        return validate_market_band_partition(bands, unit=unit)
    except ValueError as exc:
        raise ResidualCorpusError(
            f"market band tape is not a complete settlement partition: {path}: {exc}"
        ) from exc


def captured_comparator_probabilities(
    path: str | Path,
    *,
    snapshot_ids: Sequence[str],
    bands: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, dict[str, float]]]:
    """Load exact served and named challenger simplexes for selected captures."""

    source = Path(path)
    selected = {str(value) for value in snapshot_ids if str(value)}
    if not source.is_file() or not selected:
        return {}
    band_keys = [residual_band_key(band) for band in bands]
    values: dict[str, dict[str, dict[str, list[float]]]] = {
        snapshot_id: defaultdict(lambda: defaultdict(list))
        for snapshot_id in selected
    }
    variant_to_comparator = {
        variant_id: comparator_id
        for comparator_id, variant_id in COMPARATOR_VARIANT_IDS.items()
    }
    for row in read_jsonl(source):
        snapshot_id = str(row.get("snapshot_id") or "")
        if snapshot_id not in selected or row.get("prediction_status") != "predicted":
            continue
        band_key = str(row.get("band_key") or "")
        if band_key not in band_keys:
            continue
        served = _finite(row.get("serving_model_probability"))
        if served is not None:
            values[snapshot_id]["frozen_current_release"][band_key].append(served)
        comparator_id = variant_to_comparator.get(str(row.get("variant_id") or ""))
        variant_probability = _finite(row.get("variant_probability"))
        if comparator_id and variant_probability is not None:
            values[snapshot_id][comparator_id][band_key].append(variant_probability)

    output: dict[str, dict[str, dict[str, float]]] = {}
    for snapshot_id, comparators in values.items():
        complete: dict[str, dict[str, float]] = {}
        for comparator_id, by_band in comparators.items():
            simplex: dict[str, float] = {}
            valid = True
            for band_key in band_keys:
                candidates = by_band.get(band_key) or []
                if not candidates or any(
                    not math.isclose(candidates[0], value, rel_tol=0.0, abs_tol=1e-12)
                    for value in candidates[1:]
                ):
                    valid = False
                    break
                simplex[band_key] = float(candidates[0])
            if (
                valid
                and all(value >= 0.0 for value in simplex.values())
                and math.isclose(math.fsum(simplex.values()), 1.0, rel_tol=0.0, abs_tol=1e-6)
            ):
                complete[comparator_id] = simplex
        output[snapshot_id] = complete
    return output


def _default_feature_builder(
    replay_row: Mapping[str, Any],
    *,
    market_id: str,
    unit: str,
    cutoff_hour: int,
) -> dict[str, Any]:
    """Rebuild the shared V1 context from the captured source envelope."""

    from weather.model.residual_distribution_v1 import (
        SOURCE_STATES,
        canonical_candidate_features,
        default_feature_contract,
    )
    from weather.model.toronto_model import TorontoHighTempModel

    captured = _parse_timestamp(
        replay_row.get("captured_at_local") or replay_row.get("built_at"),
        "captured_at_local",
    )
    model = TorontoHighTempModel(
        market_id=market_id,
        target_date=_parse_date(replay_row.get("target_date")),
    )
    sources = replay_row.get("sources") or {}
    vector = model.extract_live_features(sources, int(cutoff_hour), now=captured)
    diagnostics = model.source_diagnostics(sources)
    feature_schema_version = str(vector.get("feature_schema_version") or "").strip()
    # Materialization preserves degraded rows for research and fault-slice
    # analysis.  Promotion qualification separately requires every row to
    # satisfy the fitted artifact's serving permission (currently fresh-only),
    # so this cannot turn stale/unknown evidence into a release PASS.
    contract = default_feature_contract(
        feature_schema_version,
        allowed_source_states=tuple(sorted(SOURCE_STATES)),
    )
    context = canonical_candidate_features(
        artifact=contract,
        feature_vector=vector,
        source_diagnostics=diagnostics,
        market_id=market_id,
        unit=unit,
    )
    if isinstance(context, Mapping) and context.get("status") in {"skipped", "failed"}:
        raise ResidualCorpusError(
            f"feature builder rejected checkpoint: {context.get('failure_reason')}: "
            f"{context.get('failure_detail')}"
        )
    output = _json_safe(dict(context))
    output["_feature_schema_version"] = feature_schema_version
    return output


def _feature_anchor_f(features: Mapping[str, Any]) -> float | None:
    for key in ("forecast_high_f", "nwp_anchor_f", "anchor_f", "forecast_high"):
        value = _finite(features.get(key))
        if value is not None:
            return value
    return None


def validate_residual_training_row(row: Mapping[str, Any]) -> dict[str, Any]:
    required_text = (
        "target_date",
        "market_id",
        "snapshot_id",
        "captured_at_utc",
        "captured_at_local",
        "native_unit",
        "feature_schema_version",
        "replay_input_sha256",
        "settlement_sha256",
        "feature_sha256",
    )
    for field in required_text:
        if not str(row.get(field) or "").strip():
            raise ResidualCorpusError(f"training row is missing {field}")
    _parse_date(row.get("target_date"))
    _parse_timestamp(row.get("captured_at_utc"), "captured_at_utc")
    _parse_timestamp(row.get("captured_at_local"), "captured_at_local")
    if int(row.get("cutoff_hour")) not in range(0, 24):
        raise ResidualCorpusError("cutoff_hour must be between 0 and 23")
    for field in ("settlement_high_f", "forecast_anchor_f", "residual_target_f"):
        if _finite(row.get(field)) is None:
            raise ResidualCorpusError(f"training row has non-finite {field}")
    features = row.get("features")
    if not isinstance(features, Mapping) or not features:
        raise ResidualCorpusError("training row features must be a non-empty object")
    forbidden = [
        name
        for name in features
        if any(token in str(name).lower() for token in FORBIDDEN_FEATURE_TOKENS)
    ]
    if forbidden:
        raise ResidualCorpusError(
            "training features contain outcome/market-derived fields: " + ", ".join(sorted(forbidden))
        )
    expected_feature_hash = hashlib.sha256(
        canonical_json(dict(features)).encode("utf-8")
    ).hexdigest()
    if row.get("feature_sha256") != expected_feature_hash:
        raise ResidualCorpusError("feature_sha256 does not match the feature payload")
    bands = row.get("market_bands")
    if not isinstance(bands, list) or len(bands) < 2:
        raise ResidualCorpusError("training row requires a complete market-band partition")
    proof = row.get("release_identity_proof")
    if not isinstance(proof, Mapping):
        raise ResidualCorpusError("training row requires a release_identity_proof")
    evidence_class = str(row.get("training_evidence_class") or "")
    if evidence_class not in {"release_bound", "research_only"}:
        raise ResidualCorpusError("training_evidence_class must be release_bound or research_only")
    proof_pass = proof.get("status") == "PASS"
    if (evidence_class == "release_bound") != proof_pass:
        raise ResidualCorpusError(
            "training_evidence_class does not match release_identity_proof status"
        )
    if bool(row.get("promotion_training_countable")):
        if not bool(row.get("settlement_countable")) or not proof_pass:
            raise ResidualCorpusError(
                "promotion_training_countable requires countable settlement and identity proof"
            )
        if not str(row.get("release_id") or ""):
            raise ResidualCorpusError("promotion-countable row requires release_id")
        for field in ("release_manifest_sha256", "configuration_sha256"):
            if not _is_sha256(row.get(field)):
                raise ResidualCorpusError(f"promotion-countable row requires valid {field}")
        runtime_hash = _runtime_identity_sha256(row.get("runtime_identity"))
        if not runtime_hash or proof.get("runtime_identity_sha256") != runtime_hash:
            raise ResidualCorpusError(
                "promotion-countable row runtime identity does not match its proof"
            )
    return dict(row)


def materialize_market_day_rows(
    folder: str | Path,
    *,
    cutoff_hours: Sequence[int] = INTRADAY_CUTOFF_HOURS,
    max_lateness_minutes: int = DEFAULT_MAX_CHECKPOINT_LATENESS_MINUTES,
    require_countable_settlement: bool = True,
    feature_builder: Callable[..., Mapping[str, Any]] | None = None,
    qualification_input_lineage: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    folder = Path(folder)
    input_lineage = dict(qualification_input_lineage or _folder_input_lineage(folder))
    settlement_path = folder / SETTLEMENT_FILENAME
    replay_path = folder / REPLAY_INPUT_FILENAME
    if not settlement_path.exists() or not replay_path.exists():
        return [], [{
            "folder": str(folder),
            "reason": "missing_settlement_or_replay_input",
        }]
    settlement = json.loads(settlement_path.read_text(encoding="utf-8"))
    if require_countable_settlement and not bool(settlement.get("promotion_countable")):
        return [], [{
            "folder": str(folder),
            "reason": "settlement_not_promotion_countable",
        }]
    market_id = str(settlement.get("market_id") or "").strip()
    spec = REGISTRY.get(market_id)
    if spec is None:
        return [], [{"folder": str(folder), "reason": "unknown_market"}]
    unit = str(settlement.get("settlement_unit") or spec.display_unit).upper()
    if unit != str(spec.display_unit).upper():
        return [], [{"folder": str(folder), "reason": "settlement_unit_mismatch"}]
    target_date = str(settlement.get("target_date") or "")
    settlement_high_native = _finite(settlement.get("settlement_high"))
    if not target_date or settlement_high_native is None:
        return [], [{"folder": str(folder), "reason": "missing_settlement_target"}]
    settlement_high_f = native_to_f(settlement_high_native, unit)
    try:
        bands = complete_band_definition(folder / SNAPSHOTS_LONG_FILENAME, unit=unit)
    except ResidualCorpusError as exc:
        return [], [{
            "folder": str(folder),
            "market_id": market_id,
            "target_date": target_date,
            "reason": "invalid_market_band_partition",
            "detail": str(exc),
        }]
    selected, exclusions = collapse_to_predeclared_checkpoints(
        read_jsonl(replay_path),
        target_date=target_date,
        cutoff_hours=cutoff_hours,
        max_lateness_minutes=max_lateness_minutes,
    )
    output: list[dict[str, Any]] = []
    comparators_by_snapshot = captured_comparator_probabilities(
        folder / VARIANT_PREDICTIONS_FILENAME,
        snapshot_ids=[str(row.get("snapshot_id") or "") for row in selected],
        bands=bands,
    )
    builder = feature_builder or _default_feature_builder
    settlement_hash = sha256_file(settlement_path)
    replay_file_hash = sha256_file(replay_path)
    for selected_row in selected:
        cutoff_hour = int(selected_row["cutoff_hour"])
        try:
            features = _json_safe(dict(builder(
                selected_row,
                market_id=market_id,
                unit=unit,
                cutoff_hour=cutoff_hour,
            )))
            feature_schema_version = str(
                features.pop("_feature_schema_version", None)
                or selected_row.get("feature_schema_version")
                or FEATURE_SCHEMA_VERSION
            )
            anchor_f = _feature_anchor_f(features)
            if anchor_f is None:
                raise ResidualCorpusError("canonical feature context has no forecast anchor")
            feature_hash = hashlib.sha256(
                canonical_json(features).encode("utf-8")
            ).hexdigest()
            identity_proof = _release_identity_proof(
                selected_row,
                input_lineage=input_lineage,
                replay_file_sha256=replay_file_hash,
                settlement_sha256=settlement_hash,
            )
            release_ids = identity_proof["observed_release_ids"]
            release_manifest_hashes = identity_proof[
                "observed_release_manifest_sha256s"
            ]
            configuration_hashes = identity_proof["observed_configuration_sha256s"]
            row = {
                "schema_version": CORPUS_SCHEMA_VERSION,
                "target_date": target_date,
                "market_id": market_id,
                "snapshot_id": str(selected_row.get("snapshot_id") or ""),
                "cutoff_hour": cutoff_hour,
                "checkpoint_lateness_minutes": selected_row["checkpoint_lateness_minutes"],
                "captured_at_utc": str(selected_row.get("captured_at_utc") or ""),
                "captured_at_local": str(selected_row.get("captured_at_local") or ""),
                "built_at": str(selected_row.get("built_at") or ""),
                "native_unit": unit,
                "feature_schema_version": feature_schema_version,
                "settlement_high_f": float(settlement_high_f),
                "forecast_anchor_f": float(anchor_f),
                "residual_target_f": float(settlement_high_f - anchor_f),
                "features": features,
                "feature_sha256": feature_hash,
                "source_health": source_diagnostics_from_replay(
                    selected_row.get("sources") or {},
                    captured_at=_parse_timestamp(
                        selected_row.get("captured_at_local") or selected_row.get("built_at"),
                        "captured_at_local",
                    ),
                ),
                "market_bands": bands,
                "winning_band": {
                    "kind": settlement.get("winning_band_kind"),
                    "value": settlement.get("winning_band_value"),
                    "value_hi": settlement.get("winning_band_value_hi"),
                },
                "settlement_quality": settlement.get("quality_grade"),
                "settlement_countable": bool(settlement.get("promotion_countable")),
                "release_id": release_ids[0] if len(release_ids) == 1 else "",
                "release_manifest_sha256": (
                    release_manifest_hashes[0]
                    if len(release_manifest_hashes) == 1
                    else ""
                ),
                "configuration_sha256": (
                    configuration_hashes[0]
                    if len(configuration_hashes) == 1
                    else ""
                ),
                "replay_input_sha256": selected_row["_captured_replay_input_sha256"],
                "replay_file_sha256": replay_file_hash,
                "settlement_sha256": settlement_hash,
                "runtime_identity": _unwrapped_runtime_identity(
                    selected_row.get("runtime_identity")
                ),
                "model_identity": selected_row.get("model_identity") or {},
                "release_identity_proof": identity_proof,
                "comparator_probabilities": _json_safe(
                    selected_row.get("comparator_probabilities")
                    or selected_row.get("variant_probabilities")
                    or selected_row.get("recorded_band_probabilities")
                    or comparators_by_snapshot.get(str(selected_row.get("snapshot_id") or ""))
                    or {}
                ),
            }
            row["training_evidence_class"] = (
                "release_bound"
                if identity_proof["status"] == "PASS"
                else "research_only"
            )
            row["promotion_training_countable"] = bool(
                row["settlement_countable"] and identity_proof["status"] == "PASS"
            )
            output.append(validate_residual_training_row(_json_safe(row)))
        except (ResidualCorpusError, TypeError, ValueError) as exc:
            exclusions.append({
                "folder": str(folder),
                "market_id": market_id,
                "target_date": target_date,
                "cutoff_hour": cutoff_hour,
                "snapshot_id": selected_row.get("snapshot_id"),
                "reason": "checkpoint_rejected",
                "detail": str(exc),
            })
    for exclusion in exclusions:
        exclusion.setdefault("folder", str(folder))
        exclusion.setdefault("market_id", market_id)
        exclusion.setdefault("target_date", target_date)
    return output, exclusions


def materialize_residual_training_corpus(
    folders: Iterable[str | Path],
    *,
    cutoff_hours: Sequence[int] = INTRADAY_CUTOFF_HOURS,
    max_lateness_minutes: int = DEFAULT_MAX_CHECKPOINT_LATENESS_MINUTES,
    require_countable_settlement: bool = True,
    feature_builder: Callable[..., Mapping[str, Any]] | None = None,
    corpus_out: str | Path | None = None,
    manifest_out: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Materialize a self-hashed, one-row-per-checkpoint training corpus."""

    rows: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    inputs: list[dict[str, Any]] = []
    for raw_folder in sorted({str(Path(value).resolve()) for value in folders}):
        folder = Path(raw_folder)
        input_lineage = _folder_input_lineage(folder)
        market_rows, market_exclusions = materialize_market_day_rows(
            folder,
            cutoff_hours=cutoff_hours,
            max_lateness_minutes=max_lateness_minutes,
            require_countable_settlement=require_countable_settlement,
            feature_builder=feature_builder,
            qualification_input_lineage=input_lineage,
        )
        rows.extend(market_rows)
        exclusions.extend(market_exclusions)
        inputs.append(input_lineage)
    rows.sort(key=lambda row: (
        row["target_date"],
        row["market_id"],
        int(row["cutoff_hour"]),
    ))
    identities = [
        (row["target_date"], row["market_id"], int(row["cutoff_hour"]))
        for row in rows
    ]
    if len(identities) != len(set(identities)):
        raise ResidualCorpusError("corpus contains duplicate market/date/cutoff rows")
    corpus_hash = hashlib.sha256(
        canonical_json(rows).encode("utf-8")
    ).hexdigest()
    release_ids = sorted({str(row.get("release_id") or "") for row in rows})
    runtime_identities = sorted({
        token
        for row in rows
        for token in [_runtime_identity_sha256(row.get("runtime_identity"))]
        if token
    })
    all_release_bound = bool(rows) and all(
        row.get("training_evidence_class") == "release_bound"
        and bool(row.get("promotion_training_countable"))
        and _mapping(row.get("release_identity_proof")).get("status") == "PASS"
        for row in rows
    )
    input_lineage_complete = bool(inputs) and all(row["status"] == "PASS" for row in inputs)
    required_files_hashed = bool(inputs) and all(
        all(
            _mapping(_mapping(input_row.get("files")).get(filename)).get("exists") is True
            and _is_sha256(
                _mapping(_mapping(input_row.get("files")).get(filename)).get("sha256")
            )
            for filename in QUALIFICATION_INPUT_FILENAMES
        )
        for input_row in inputs
    )
    identity_criteria = {
        "all_rows_release_bound_and_countable": all_release_bound,
        "singular_nonmissing_release_id": len(release_ids) == 1 and release_ids != [""],
        "singular_nonmissing_runtime_identity": (
            len(runtime_identities) == 1
            and all(bool(row.get("runtime_identity")) for row in rows)
        ),
        "per_input_folder_semantic_manifest_verified": input_lineage_complete,
        "all_required_files_present_and_hashed": required_files_hashed,
        "all_row_identity_proofs_pass": bool(rows) and all(
            _mapping(row.get("release_identity_proof")).get("status") == "PASS"
            for row in rows
        ),
    }
    manifest = finalize_self_hash({
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "artifact_type": "residual_distribution_training_corpus_manifest",
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        "corpus_schema_version": CORPUS_SCHEMA_VERSION,
        "corpus_sha256": corpus_hash,
        "selection_policy": {
            "checkpoint": "earliest_capture_at_or_after_cutoff",
            "cutoff_hours": [int(hour) for hour in cutoff_hours],
            "max_lateness_minutes": int(max_lateness_minutes),
            "substitution_allowed": False,
        },
        "label_policy": {
            "require_countable_settlement": bool(require_countable_settlement),
            "join_after_feature_construction": True,
        },
        "qualification_input_contract": {
            "required_files": list(QUALIFICATION_INPUT_FILENAMES),
            "all_required_files_are_hashed": required_files_hashed,
            "semantic_event_manifest_verification_required": True,
            "per_input_folder_semantic_verification_required": True,
            "operational_validator": "weather.operations.event_day_manifest.validate_event_day_manifest",
            "criteria": identity_criteria,
            "status": "PASS" if all(identity_criteria.values()) else "BLOCK",
            "release_ids": release_ids,
            "runtime_identity_sha256s": runtime_identities,
        },
        "counts": {
            "input_market_days": len(inputs),
            "accepted_rows": len(rows),
            "excluded_rows": len(exclusions),
            "fleet_dates": len({row["target_date"] for row in rows}),
            "market_days": len({(row["target_date"], row["market_id"]) for row in rows}),
            "release_bound_rows": sum(
                1 for row in rows if row.get("training_evidence_class") == "release_bound"
            ),
            "research_only_rows": sum(
                1 for row in rows if row.get("training_evidence_class") == "research_only"
            ),
            "semantic_manifest_pass_market_days": sum(
                1 for row in inputs if row.get("status") == "PASS"
            ),
            "semantic_manifest_block_market_days": sum(
                1 for row in inputs if row.get("status") != "PASS"
            ),
        },
        "inputs": inputs,
        "exclusions": exclusions,
    }, hash_field="manifest_sha256")
    if corpus_out is not None:
        _atomic_write_jsonl(corpus_out, rows)
    if manifest_out is not None:
        _atomic_write_json(manifest_out, manifest)
    return rows, manifest


def verify_residual_corpus_manifest(
    rows: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ResidualCorpusError("residual corpus manifest schema mismatch")
    expected_manifest = finalize_self_hash(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"},
        hash_field="manifest_sha256",
    )
    if manifest.get("manifest_sha256") != expected_manifest.get("manifest_sha256"):
        raise ResidualCorpusError("residual corpus manifest self-hash mismatch")
    validated = [validate_residual_training_row(row) for row in rows]
    corpus_hash = hashlib.sha256(canonical_json(validated).encode("utf-8")).hexdigest()
    if manifest.get("corpus_sha256") != corpus_hash:
        raise ResidualCorpusError("residual corpus hash mismatch")
    contract = manifest.get("qualification_input_contract")
    if not isinstance(contract, Mapping):
        raise ResidualCorpusError("qualification_input_contract is missing")
    if contract.get("required_files") != list(QUALIFICATION_INPUT_FILENAMES):
        raise ResidualCorpusError("qualification input required-files contract mismatch")
    if contract.get("semantic_event_manifest_verification_required") is not True:
        raise ResidualCorpusError("semantic event-manifest verification is not required")
    if contract.get("per_input_folder_semantic_verification_required") is not True:
        raise ResidualCorpusError("per-folder semantic verification is not required")

    recorded_inputs = manifest.get("inputs")
    if not isinstance(recorded_inputs, list):
        raise ResidualCorpusError("residual corpus inputs must be a list")
    current_inputs: list[dict[str, Any]] = []
    for input_row in recorded_inputs:
        if not isinstance(input_row, Mapping) or not str(input_row.get("folder") or ""):
            raise ResidualCorpusError("residual corpus input lineage is malformed")
        recorded_payload = {
            key: value for key, value in input_row.items() if key != "lineage_sha256"
        }
        expected_lineage_hash = hashlib.sha256(
            canonical_json(recorded_payload).encode("utf-8")
        ).hexdigest()
        if input_row.get("lineage_sha256") != expected_lineage_hash:
            raise ResidualCorpusError("residual corpus input lineage self-hash mismatch")
        current = _folder_input_lineage(Path(str(input_row["folder"])))
        if (
            current.get("lineage_sha256") != input_row.get("lineage_sha256")
            or current.get("status") != input_row.get("status")
        ):
            raise ResidualCorpusError(
                "residual corpus input no longer matches semantic event-manifest proof"
            )
        current_inputs.append(current)

    release_ids = sorted({str(row.get("release_id") or "") for row in validated})
    runtime_identities = sorted({
        token
        for row in validated
        for token in [_runtime_identity_sha256(row.get("runtime_identity"))]
        if token
    })
    all_release_bound = bool(validated) and all(
        row.get("training_evidence_class") == "release_bound"
        and bool(row.get("promotion_training_countable"))
        and _mapping(row.get("release_identity_proof")).get("status") == "PASS"
        for row in validated
    )
    required_files_hashed = bool(current_inputs) and all(
        all(
            _mapping(_mapping(input_row.get("files")).get(filename)).get("exists") is True
            and _is_sha256(
                _mapping(_mapping(input_row.get("files")).get(filename)).get("sha256")
            )
            for filename in QUALIFICATION_INPUT_FILENAMES
        )
        for input_row in current_inputs
    )
    expected_criteria = {
        "all_rows_release_bound_and_countable": all_release_bound,
        "singular_nonmissing_release_id": len(release_ids) == 1 and release_ids != [""],
        "singular_nonmissing_runtime_identity": (
            len(runtime_identities) == 1
            and all(bool(row.get("runtime_identity")) for row in validated)
        ),
        "per_input_folder_semantic_manifest_verified": bool(current_inputs)
        and all(row.get("status") == "PASS" for row in current_inputs),
        "all_required_files_present_and_hashed": required_files_hashed,
        "all_row_identity_proofs_pass": bool(validated)
        and all(
            _mapping(row.get("release_identity_proof")).get("status") == "PASS"
            for row in validated
        ),
    }
    if contract.get("criteria") != expected_criteria:
        raise ResidualCorpusError("qualification input criteria do not match corpus evidence")
    expected_contract_status = "PASS" if all(expected_criteria.values()) else "BLOCK"
    if contract.get("status") != expected_contract_status:
        raise ResidualCorpusError("qualification input contract status is inconsistent")
    if contract.get("all_required_files_are_hashed") is not required_files_hashed:
        raise ResidualCorpusError("qualification input hash status is inconsistent")
    if contract.get("release_ids") != release_ids:
        raise ResidualCorpusError("qualification input release IDs are inconsistent")
    if contract.get("runtime_identity_sha256s") != runtime_identities:
        raise ResidualCorpusError("qualification runtime identities are inconsistent")
    return dict(manifest)


def _atomic_write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _atomic_write_jsonl(path: str | Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(canonical_json(dict(row)) + "\n")
    os.replace(temporary, path)


def _parse_cutoff_hours(value: str) -> tuple[int, ...]:
    hours = tuple(int(item.strip()) for item in str(value).split(",") if item.strip())
    if not hours or any(hour not in range(24) for hour in hours) or len(set(hours)) != len(hours):
        raise argparse.ArgumentTypeError("cutoff hours must be unique integers from 0 through 23")
    return hours


def _newest_per_market(folders: Sequence[Path], limit: int) -> list[Path]:
    if int(limit) <= 0:
        return list(folders)
    by_market: dict[str, list[Path]] = {}
    for folder in folders:
        by_market.setdefault(str(folder_market_id(folder) or "unknown"), []).append(folder)
    return sorted(
        folder
        for market_folders in by_market.values()
        for folder in market_folders[-int(limit):]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize a hash-linked ResidualDistributionV1 PIT training corpus."
    )
    parser.add_argument("--folder", action="append", default=[])
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--as-of", default="")
    parser.add_argument("--market-id", default="")
    parser.add_argument(
        "--cutoff-hours",
        type=_parse_cutoff_hours,
        default=tuple(INTRADAY_CUTOFF_HOURS),
    )
    parser.add_argument(
        "--max-market-days-per-market",
        type=int,
        default=0,
        help="Bounded research/smoke cap; zero consumes every discovered settled day.",
    )
    parser.add_argument(
        "--max-lateness-minutes",
        type=int,
        default=DEFAULT_MAX_CHECKPOINT_LATENESS_MINUTES,
    )
    parser.add_argument(
        "--allow-noncountable-settlement",
        action="store_true",
        help="Research-only: retain labels that are not promotion-countable.",
    )
    parser.add_argument(
        "--out",
        default=str(data_path("backtest", "residual_distribution_v1_training_corpus.jsonl")),
    )
    parser.add_argument(
        "--manifest-out",
        default=str(data_path("backtest", "residual_distribution_v1_training_corpus_manifest.json")),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    folders = [Path(value) for value in args.folder]
    if not folders:
        folders = discover_settled_folders(
            root=args.snapshots_root,
            as_of=args.as_of or None,
            required_file=REPLAY_INPUT_FILENAME,
            market_id=args.market_id or None,
        )
    folders = _newest_per_market(folders, args.max_market_days_per_market)
    rows, manifest = materialize_residual_training_corpus(
        folders,
        cutoff_hours=args.cutoff_hours,
        max_lateness_minutes=args.max_lateness_minutes,
        require_countable_settlement=not args.allow_noncountable_settlement,
        corpus_out=args.out,
        manifest_out=args.manifest_out,
    )
    print(
        "ResidualDistributionV1 corpus: "
        f"rows={len(rows)} excluded={manifest['counts']['excluded_rows']} "
        f"fleet_dates={manifest['counts']['fleet_dates']} out={args.out}"
    )


__all__ = [name for name in globals() if not name.startswith("_")]


if __name__ == "__main__":
    main()
