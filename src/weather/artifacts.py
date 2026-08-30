"""Artifact path policy with compatibility for the pre-package layout."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pickle
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import ARTIFACTS_ROOT, REPO_ROOT, SRC_ROOT, config_path, relative_to_repo
from weather.release_artifacts import (
    ReleaseArtifactVerificationError as ReleaseArtifactVerificationError,
    resolve_verified_active_release as resolve_verified_active_release,
)
from weather.schema_registry import schema_version


ARTIFACT_REGISTRY_SCHEMA_VERSION = schema_version("model_artifact_registry")
ARTIFACT_SIZE_AUDIT_SCHEMA_VERSION = schema_version("model_artifact_size_audit")
ARTIFACT_EXTERNALIZATION_SCHEMA_VERSION = schema_version("model_artifact_externalization")
ARTIFACT_PROMOTION_PREFLIGHT_SCHEMA_VERSION = schema_version("model_artifact_promotion_preflight")
ARTIFACT_SCHEMA_FORWARD_MIGRATION_SCHEMA_VERSION = schema_version("artifact_schema_forward_migration")
DEFAULT_ARTIFACT_REGISTRY_PATH = ARTIFACTS_ROOT / "manifests" / "model_artifact_registry.json"
DEFAULT_ARTIFACT_SIZE_AUDIT_PATH = ARTIFACTS_ROOT / "manifests" / "model_artifact_size_audit.json"
DEFAULT_ARTIFACT_EXTERNALIZATION_PATH = ARTIFACTS_ROOT / "manifests" / "model_artifact_externalization.json"
DEFAULT_ARTIFACT_PROMOTION_PREFLIGHT_PATH = ARTIFACTS_ROOT / "manifests" / "model_artifact_promotion_preflight.json"
DEFAULT_VARIANT_REGISTRY_PATH = config_path() / "model_variant_registry.json"
DEFAULT_CANDIDATE_ARTIFACT_ROOT = ARTIFACTS_ROOT / "candidates"
DEFAULT_IMMUTABLE_RELEASE_ROOT = ARTIFACTS_ROOT / "releases"
DEFAULT_ACTIVE_RELEASE_POINTER = DEFAULT_IMMUTABLE_RELEASE_ROOT / "current_release.json"

MIB = 1024 * 1024
DEFAULT_INDIVIDUAL_ARTIFACT_WARNING_BYTES = 90 * MIB
DEFAULT_INDIVIDUAL_ARTIFACT_FAILURE_BYTES = 100 * MIB
DEFAULT_TOTAL_ARTIFACT_WARNING_BYTES = 350 * MIB
DEFAULT_TOTAL_ARTIFACT_FAILURE_BYTES = 500 * MIB
EXTERNALIZED_BACKENDS = {"git_lfs", "external_artifact_store"}
VARIANT_CONTRACT_FIELDS = (
    "artifact_path",
    "artifact_required",
    "prediction_function",
    "prediction_mode",
    "export_family",
    "default_export_path",
    "postprocess_config_hash",
    "live_runtime",
)
FEATURE_SCHEMA_RE = re.compile(r"^(?P<family>.+)_v(?P<major>\d+)(?:\.(?P<minor>\d+))?$")
GIT_LFS_POINTER_MAX_BYTES = 512
GIT_LFS_POINTER_RE = re.compile(
    rb"\Aversion https://git-lfs\.github\.com/spec/v1\n"
    rb"oid sha256:([0-9a-f]{64})\n"
    rb"size (0|[1-9][0-9]*)\n\Z"
)


class CandidateArtifactPathError(ValueError):
    """A training output violates the candidate-only artifact path policy."""


def assert_candidate_artifact_output(
    output_path: str | Path,
    *,
    candidates_root: str | Path = DEFAULT_CANDIDATE_ARTIFACT_ROOT,
    releases_root: str | Path = DEFAULT_IMMUTABLE_RELEASE_ROOT,
    active_pointer: str | Path = DEFAULT_ACTIVE_RELEASE_POINTER,
) -> Path:
    """Allow a training write only below a disjoint candidate artifact root."""

    output = Path(output_path).resolve()
    candidates = Path(candidates_root).resolve()
    releases = Path(releases_root).resolve()
    pointer = Path(active_pointer).resolve()
    if candidates == releases or candidates.is_relative_to(releases) or releases.is_relative_to(candidates):
        raise CandidateArtifactPathError("candidate and release roots must be disjoint")
    if output == candidates:
        raise CandidateArtifactPathError("candidate output must name a child path, not the candidate root")
    if not output.is_relative_to(candidates):
        raise CandidateArtifactPathError(f"candidate-only guard rejected output outside candidate root: {output}")
    if output == pointer or output.is_relative_to(releases):
        raise CandidateArtifactPathError(f"candidate-only guard rejected active/immutable release output: {output}")
    return output


def training_artifact_output_policy(
    output_path: str | Path,
    *,
    candidates_root: str | Path = DEFAULT_CANDIDATE_ARTIFACT_ROOT,
    releases_root: str | Path = DEFAULT_IMMUTABLE_RELEASE_ROOT,
    active_pointer: str | Path = DEFAULT_ACTIVE_RELEASE_POINTER,
    allow_legacy_serving_output: bool = False,
) -> dict[str, Any]:
    """Guard trainer output while quarantining an explicit legacy escape hatch."""

    output = Path(output_path).resolve()
    releases = Path(releases_root).resolve()
    pointer = Path(active_pointer).resolve()
    if output == pointer or output == releases or output.is_relative_to(releases):
        raise CandidateArtifactPathError(
            f"trainer output cannot target immutable/active release state: {output}"
        )
    try:
        guarded = assert_candidate_artifact_output(
            output,
            candidates_root=candidates_root,
            releases_root=releases,
            active_pointer=pointer,
        )
    except CandidateArtifactPathError:
        if not allow_legacy_serving_output:
            raise
        return {
            "status": "QUARANTINED_LEGACY_OUTPUT",
            "path": str(output),
            "release_eligible": False,
        }
    return {
        "status": "CANDIDATE_ONLY",
        "path": str(guarded),
        "release_eligible": True,
    }


def parse_feature_schema_version(version: str | None) -> dict[str, Any] | None:
    if not version:
        return None
    match = FEATURE_SCHEMA_RE.match(str(version))
    if not match:
        return None
    return {
        "family": match.group("family"),
        "major": int(match.group("major")),
        "minor": int(match.group("minor") or 0),
    }


def same_feature_schema_family(source: str | None, target: str | None) -> bool:
    source_parts = parse_feature_schema_version(source)
    target_parts = parse_feature_schema_version(target)
    return bool(
        source_parts
        and target_parts
        and source_parts["family"] == target_parts["family"]
        and source_parts["major"] == target_parts["major"]
    )


def _schema_order(source: str | None, target: str | None) -> int | None:
    source_parts = parse_feature_schema_version(source)
    target_parts = parse_feature_schema_version(target)
    if not source_parts or not target_parts:
        return None
    if source_parts["family"] != target_parts["family"]:
        return None
    if source_parts["major"] != target_parts["major"]:
        return source_parts["major"] - target_parts["major"]
    return source_parts["minor"] - target_parts["minor"]


def _schema_migration_plan(
    *,
    source_feature_schema_version: str | None,
    target_feature_schema_version: str | None,
    migration_status: str,
    classification: str,
    action: str,
    reason: str,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": ARTIFACT_SCHEMA_FORWARD_MIGRATION_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        "source_feature_schema_version": source_feature_schema_version,
        "target_feature_schema_version": target_feature_schema_version,
        "effective_feature_schema_version": (
            target_feature_schema_version
            if migration_status in {"current", "migrated"}
            else source_feature_schema_version
        ),
        "migration_status": migration_status,
        "classification": classification,
        "action": action,
        "reason": reason,
    }


def feature_schema_migration_plan(
    source_feature_schema_version: str | None,
    target_feature_schema_version: str | None,
    *,
    stable_feature_names: bool | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    if source_feature_schema_version == target_feature_schema_version and target_feature_schema_version:
        return _schema_migration_plan(
            source_feature_schema_version=source_feature_schema_version,
            target_feature_schema_version=target_feature_schema_version,
            migration_status="current",
            classification="current",
            action="none",
            reason="artifact already uses the active feature schema",
            generated_at_utc=generated_at_utc,
        )
    if not source_feature_schema_version:
        return _schema_migration_plan(
            source_feature_schema_version=source_feature_schema_version,
            target_feature_schema_version=target_feature_schema_version,
            migration_status="unrecoverable",
            classification="unrecoverable",
            action="quarantine",
            reason="artifact feature schema is missing",
            generated_at_utc=generated_at_utc,
        )
    if not target_feature_schema_version:
        return _schema_migration_plan(
            source_feature_schema_version=source_feature_schema_version,
            target_feature_schema_version=target_feature_schema_version,
            migration_status="unrecoverable",
            classification="unrecoverable",
            action="quarantine",
            reason="active feature schema is missing",
            generated_at_utc=generated_at_utc,
        )
    order = _schema_order(source_feature_schema_version, target_feature_schema_version)
    if order is None:
        return _schema_migration_plan(
            source_feature_schema_version=source_feature_schema_version,
            target_feature_schema_version=target_feature_schema_version,
            migration_status="unrecoverable",
            classification="unrecoverable",
            action="quarantine",
            reason="artifact feature schema is not in the active feature family",
            generated_at_utc=generated_at_utc,
        )
    if order > 0:
        return _schema_migration_plan(
            source_feature_schema_version=source_feature_schema_version,
            target_feature_schema_version=target_feature_schema_version,
            migration_status="unrecoverable",
            classification="unrecoverable",
            action="quarantine",
            reason="artifact feature schema is newer than the runtime schema",
            generated_at_utc=generated_at_utc,
        )
    if not same_feature_schema_family(source_feature_schema_version, target_feature_schema_version):
        return _schema_migration_plan(
            source_feature_schema_version=source_feature_schema_version,
            target_feature_schema_version=target_feature_schema_version,
            migration_status="unrecoverable",
            classification="unrecoverable",
            action="quarantine",
            reason="artifact feature schema major version predates the active feature family",
            generated_at_utc=generated_at_utc,
        )
    if stable_feature_names is False:
        return _schema_migration_plan(
            source_feature_schema_version=source_feature_schema_version,
            target_feature_schema_version=target_feature_schema_version,
            migration_status="unrecoverable",
            classification="unrecoverable",
            action="quarantine",
            reason="artifact does not expose stable trained feature names for migration",
            generated_at_utc=generated_at_utc,
        )
    return _schema_migration_plan(
        source_feature_schema_version=source_feature_schema_version,
        target_feature_schema_version=target_feature_schema_version,
        migration_status="migrated",
        classification="migratable",
        action="metadata_forward_migration",
        reason=(
            "same-family feature schema bump migrated by preserving trained "
            "feature_names and updating artifact schema metadata"
        ),
        generated_at_utc=generated_at_utc,
    )


def _model_bundles(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    models = artifact.get("models")
    if isinstance(models, dict):
        return [bundle for bundle in models.values() if isinstance(bundle, dict)]
    return [
        value
        for key, value in artifact.items()
        if str(key).isdigit() and isinstance(value, dict)
    ]


def artifact_has_stable_feature_names(artifact: dict[str, Any] | None) -> bool:
    if not isinstance(artifact, dict):
        return False
    top_level = artifact.get("feature_names")
    if isinstance(top_level, list) and top_level:
        return True
    bundles = _model_bundles(artifact)
    return bool(bundles) and all(bool(bundle.get("feature_names")) for bundle in bundles)


def migrate_artifact_payload(
    artifact: dict[str, Any],
    *,
    target_feature_schema_version: str,
    generated_at_utc: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = feature_schema_migration_plan(
        artifact.get("feature_schema_version"),
        target_feature_schema_version,
        stable_feature_names=artifact_has_stable_feature_names(artifact),
        generated_at_utc=generated_at_utc,
    )
    if plan.get("migration_status") != "migrated":
        return artifact, plan

    migrated = copy.deepcopy(artifact)
    migrated["feature_schema_version"] = target_feature_schema_version
    for bundle in _model_bundles(migrated):
        bundle["feature_schema_version"] = target_feature_schema_version
    history = list(migrated.get("schema_migration_history") or [])
    history.append(plan)
    migrated["schema_migration_history"] = history
    return migrated, plan


def write_migrated_pickle_artifact(
    source_path: str | Path,
    output_path: str | Path,
    *,
    target_feature_schema_version: str,
) -> tuple[Path, dict[str, Any]]:
    source = Path(source_path)
    with source.open("rb") as handle:
        artifact = pickle.load(handle)
    if not isinstance(artifact, dict):
        raise ValueError(f"artifact at {source} is not a dict payload")
    migrated, plan = migrate_artifact_payload(
        artifact,
        target_feature_schema_version=target_feature_schema_version,
    )
    if plan.get("migration_status") != "migrated":
        raise ValueError(f"artifact at {source} is not migratable: {plan.get('reason')}")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        pickle.dump(migrated, handle)
    return output, plan


def _artifact_dir(filename: str) -> Path:
    name = Path(filename).name
    if name.startswith("feature_model_hgb") and name.endswith(".pkl"):
        return ARTIFACTS_ROOT / "models" / "hgb"
    if (
        name.startswith("feature_model_coefs")
        or name.startswith("late_day_model_coefs")
    ) and name.endswith(".json"):
        return ARTIFACTS_ROOT / "models" / "coefs"
    if name == "f_family_secondary_artifacts.json":
        return ARTIFACTS_ROOT / "manifests"
    if (
        name.startswith("calibrated_weights")
        or name.startswith("probability_calibration")
        or name.startswith("forecast_error_model")
        or name.startswith("settlement_lag_model")
    ) and name.endswith(".json"):
        return ARTIFACTS_ROOT / "calibration"
    return ARTIFACTS_ROOT / "misc"


def artifact_path(filename: str | Path) -> Path:
    path = Path(filename)
    if path.is_absolute() or path.parent != Path("."):
        return path
    return _artifact_dir(path.name) / path.name


def legacy_artifact_path(filename: str | Path) -> Path:
    return SRC_ROOT / Path(filename).name


def artifact_candidates(filename: str | Path) -> tuple[Path, ...]:
    path = Path(filename)
    if path.is_absolute() or path.parent != Path("."):
        return (path,)
    return artifact_path(path.name), legacy_artifact_path(path.name)


def resolve_artifact_path(filename: str | Path, *, for_write: bool = False) -> Path:
    path = Path(filename)
    if path.is_absolute() or path.parent != Path("."):
        return path
    new_path = artifact_path(path.name)
    if for_write:
        return new_path
    if new_path.exists():
        return new_path
    old_path = legacy_artifact_path(path.name)
    if old_path.exists():
        return old_path
    return new_path


def writable_artifact_path(filename: str | Path) -> Path:
    path = resolve_artifact_path(filename, for_write=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def artifact_metadata_path(filename: str | Path) -> dict:
    path = resolve_artifact_path(filename)
    return {
        "path": relative_to_repo(path),
        "legacy_path": relative_to_repo(legacy_artifact_path(filename)),
        "exists": path.exists(),
        "is_legacy": path == legacy_artifact_path(filename),
    }


def sha256_file(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _git_lfs_pointer_identity(path: Path) -> tuple[int, str] | None:
    """Return the logical object identity for one canonical LFS pointer.

    Materialized LFS objects return ``None`` and retain the ordinary byte/hash
    path. Pointer-like content is rejected unless it is the exact three-line
    Git LFS v1 form used by this repository.
    """

    with path.open("rb") as handle:
        candidate = handle.read(GIT_LFS_POINTER_MAX_BYTES + 1)
    if len(candidate) <= GIT_LFS_POINTER_MAX_BYTES:
        match = GIT_LFS_POINTER_RE.fullmatch(candidate)
        if match is not None:
            return int(match.group(2)), match.group(1).decode("ascii")
    pointer_like = (
        b"git-lfs.github.com/spec/" in candidate
        or candidate.startswith(b"oid sha256:")
        or (
            candidate.startswith(b"version ")
            and b"\noid " in candidate
            and b"\nsize " in candidate
        )
    )
    if pointer_like:
        raise ValueError(f"malformed Git LFS pointer: {path}")
    return None


def artifact_kind(path: str | Path) -> str:
    path = Path(path)
    name = path.name
    parts = {part.lower() for part in path.parts}
    if "hgb" in parts or (name.startswith("feature_model_hgb") and name.endswith(".pkl")):
        return "hgb_model"
    if "coefs" in parts or name.startswith(("feature_model_coefs", "late_day_model_coefs")):
        return "coefs_model"
    if "calibration" in parts:
        return "calibration"
    if "manifests" in parts:
        return "manifest"
    return "misc"


def _repo_relative_path(path: str | Path) -> str | None:
    path = Path(path)
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return None


def _repo_relative_value(value: str | Path | None) -> str | None:
    if value in (None, ""):
        return None
    value = str(value).replace("\\", "/")
    if "://" in value:
        return None
    path = Path(value)
    if path.is_absolute():
        return _repo_relative_path(path)
    return value


def _variant_contract(variant: dict) -> dict:
    contract = dict(variant.get("export_contract") or {})
    for key in VARIANT_CONTRACT_FIELDS:
        if key in variant and key not in contract:
            contract[key] = variant.get(key)
    contract.setdefault("artifact_required", True)
    contract.setdefault("variant_id", variant.get("variant_id"))
    contract.setdefault("variant_family", variant.get("variant_family"))
    contract.setdefault("track", variant.get("track"))
    return contract


def _shadow_only_variant(variant: dict) -> bool:
    roles = {str(role) for role in variant.get("roles") or []}
    return variant.get("lifecycle") == "shadow" or "shadow-only" in roles


def _git_lfs_attribute_map(paths: list[Path]) -> dict[str, bool]:
    rel_paths = []
    for path in paths:
        rel = _repo_relative_path(path)
        if rel:
            rel_paths.append(rel)
    if not rel_paths:
        return {}
    try:
        result = subprocess.run(
            ["git", "check-attr", "filter", "--", *rel_paths],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    output: dict[str, bool] = {rel: False for rel in rel_paths}
    if result.returncode != 0:
        return output
    for line in result.stdout.splitlines():
        try:
            path_text, _attribute, value = line.split(": ", 2)
        except ValueError:
            continue
        normalized = path_text.strip('"').replace("\\", "/")
        output[normalized] = value.strip() == "lfs"
    return output


def variant_artifact_references(registry_path: str | Path | None = DEFAULT_VARIANT_REGISTRY_PATH) -> dict[str, list[dict]]:
    if registry_path in (None, ""):
        return {}
    path = Path(registry_path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    refs: dict[str, list[dict]] = {}
    for variant in payload.get("variants") or []:
        if not isinstance(variant, dict):
            continue
        contract = _variant_contract(variant)
        artifact_path = contract.get("artifact_path")
        rel = _repo_relative_value(artifact_path)
        if not rel:
            continue
        roles = [str(role) for role in variant.get("roles") or []]
        refs.setdefault(rel, []).append({
            "variant_id": variant.get("variant_id"),
            "variant_family": variant.get("variant_family"),
            "lifecycle": variant.get("lifecycle"),
            "roles": roles,
            "active_for_headline": bool(variant.get("active_for_headline", True)),
            "shadow_only": _shadow_only_variant(variant),
            "artifact_required": bool(contract.get("artifact_required", True)),
            "artifact_path": artifact_path,
            "prediction_mode": contract.get("prediction_mode"),
            "export_family": contract.get("export_family"),
        })
    return refs


def _registry_use(refs: list[dict], path: Path) -> str:
    if refs:
        promoted = [
            ref for ref in refs
            if ref.get("lifecycle") == "active"
            and ref.get("active_for_headline")
            and not ref.get("shadow_only")
        ]
        if promoted:
            return "active_promoted"
        if any(ref.get("lifecycle") == "active" for ref in refs):
            return "active_shadow"
        if any(ref.get("shadow_only") for ref in refs):
            return "shadow_only"
        if any("smoke" in set(ref.get("roles") or []) for ref in refs):
            return "smoke_only"
        if any(ref.get("lifecycle") == "archived" for ref in refs):
            return "historical"
    name = path.name.lower()
    if "smoke" in name:
        return "smoke_only"
    if artifact_kind(path) in {"hgb_model", "coefs_model", "calibration"}:
        return "unregistered_runtime_artifact"
    return "unreferenced"


def _reproducibility_requirement(registry_use: str, kind: str) -> str:
    if registry_use == "active_promoted":
        return "promotion_restore_required"
    if registry_use == "active_shadow":
        return "shadow_replay_restore_required"
    if registry_use == "shadow_only":
        return "shadow_only_rebuildable"
    if registry_use == "smoke_only":
        return "smoke_rebuildable"
    if registry_use == "historical":
        return "historical_replay_restore_required"
    if kind in {"hgb_model", "coefs_model", "calibration"}:
        return "runtime_restore_required"
    return "manifest_only"


def _storage_backend(path: Path, *, git_lfs_tracked: bool) -> str:
    if git_lfs_tracked:
        return "git_lfs"
    return "git"


def _restore_instruction(path: str, storage_backend: str) -> str:
    if storage_backend == "git_lfs":
        return f'git lfs pull --include="{path}"'
    if storage_backend == "external_artifact_store":
        return f"fetch external artifact using the manifest entry for {path}"
    return f"git checkout -- {path}"


def json_artifact_versions(path: str | Path) -> dict:
    path = Path(path)
    if path.suffix.lower() != ".json":
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    versions = {}
    for key in ("schema_version", "feature_schema_version", "model_schema_version"):
        if payload.get(key):
            versions[key] = payload.get(key)
    if not versions and isinstance(payload, dict):
        first = next(iter(payload.values()), None)
        if isinstance(first, dict):
            for key in ("schema_version", "feature_schema_version", "model_schema_version"):
                if first.get(key):
                    versions[key] = first.get(key)
    return versions


def discover_artifact_files(root: str | Path = ARTIFACTS_ROOT):
    root = Path(root)
    if not root.exists():
        return []
    return sorted(
        path for path in root.rglob("*")
        if path.is_file()
        and path.name != DEFAULT_ARTIFACT_REGISTRY_PATH.name
        and path.name != DEFAULT_ARTIFACT_SIZE_AUDIT_PATH.name
        and path.name != DEFAULT_ARTIFACT_EXTERNALIZATION_PATH.name
        and path.name != DEFAULT_ARTIFACT_PROMOTION_PREFLIGHT_PATH.name
        and path.suffix.lower() in {".json", ".pkl", ".parquet"}
    )


def artifact_record(
    path: str | Path,
    root: str | Path = ARTIFACTS_ROOT,
    *,
    variant_refs: dict[str, list[dict]] | None = None,
    git_lfs_tracked: bool = False,
) -> dict:
    path = Path(path)
    root = Path(root)
    stat = path.stat()
    lfs_pointer_identity = (
        _git_lfs_pointer_identity(path) if git_lfs_tracked else None
    )
    try:
        artifact_id = path.relative_to(root).as_posix()
    except ValueError:
        artifact_id = relative_to_repo(path)
    versions = json_artifact_versions(path)
    repo_path = relative_to_repo(path)
    refs = (variant_refs or {}).get(repo_path, [])
    kind = artifact_kind(path)
    registry_use = _registry_use(refs, path)
    storage_backend = _storage_backend(path, git_lfs_tracked=git_lfs_tracked)
    storage_managed = storage_backend in EXTERNALIZED_BACKENDS
    if lfs_pointer_identity is None:
        bytes_value = int(stat.st_size)
        sha256 = sha256_file(path)
    else:
        bytes_value, sha256 = lfs_pointer_identity
    return {
        "artifact_id": artifact_id,
        "path": repo_path,
        "kind": kind,
        "suffix": path.suffix.lower(),
        "bytes": bytes_value,
        "unmanaged_git_bytes": 0 if storage_managed else bytes_value,
        "managed_external_bytes": bytes_value if storage_managed else 0,
        "storage_backend": storage_backend,
        "storage_managed": storage_managed,
        "restore_instruction": _restore_instruction(repo_path, storage_backend),
        "registry_use": registry_use,
        "reproducibility_requirement": _reproducibility_requirement(registry_use, kind),
        "variant_refs": refs,
        "sha256": sha256,
        "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "schema_version": versions.get("schema_version"),
        "feature_schema_version": versions.get("feature_schema_version"),
        "model_schema_version": versions.get("model_schema_version"),
    }


def build_artifact_registry(
    root: str | Path = ARTIFACTS_ROOT,
    generated_at=None,
    *,
    variant_registry_path: str | Path | None = DEFAULT_VARIANT_REGISTRY_PATH,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    files = discover_artifact_files(root)
    lfs_attrs = _git_lfs_attribute_map(files)
    refs = variant_artifact_references(variant_registry_path)
    rows = [
        artifact_record(
            path,
            root=root,
            variant_refs=refs,
            git_lfs_tracked=lfs_attrs.get(relative_to_repo(path), False),
        )
        for path in files
    ]
    counts = Counter(row["kind"] for row in rows)
    storage_counts = Counter(row["storage_backend"] for row in rows)
    registry_use_counts = Counter(row["registry_use"] for row in rows)
    return {
        "schema_version": ARTIFACT_REGISTRY_SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "artifact_root": relative_to_repo(root),
        "artifact_count": len(rows),
        "kind_counts": dict(sorted(counts.items())),
        "storage_backend_counts": dict(sorted(storage_counts.items())),
        "registry_use_counts": dict(sorted(registry_use_counts.items())),
        "working_tree_bytes": sum(row["bytes"] for row in rows),
        "unmanaged_git_bytes": sum(row["unmanaged_git_bytes"] for row in rows),
        "managed_external_bytes": sum(row["managed_external_bytes"] for row in rows),
        "artifacts": rows,
    }


def write_artifact_registry(
    path: str | Path = DEFAULT_ARTIFACT_REGISTRY_PATH,
    root: str | Path = ARTIFACTS_ROOT,
    *,
    variant_registry_path: str | Path | None = DEFAULT_VARIANT_REGISTRY_PATH,
) -> Path:
    payload = build_artifact_registry(root=root, variant_registry_path=variant_registry_path)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _size_status(rows):
    if any(row["status"] == "FAIL" for row in rows):
        return "FAIL"
    if any(row["status"] == "WARN" for row in rows):
        return "WARN"
    return "PASS"


def _threshold_row(kind, status, bytes_value, threshold_bytes, artifact=None):
    row = {
        "kind": kind,
        "status": status,
        "bytes": int(bytes_value),
        "threshold_bytes": int(threshold_bytes),
    }
    if artifact is not None:
        row["artifact_id"] = artifact.get("artifact_id")
        row["path"] = artifact.get("path")
        row["suffix"] = artifact.get("suffix")
        row["artifact_kind"] = artifact.get("kind")
        row["storage_backend"] = artifact.get("storage_backend")
        row["registry_use"] = artifact.get("registry_use")
    return row


def build_artifact_size_audit(
    root: str | Path = ARTIFACTS_ROOT,
    *,
    generated_at=None,
    individual_warning_bytes=DEFAULT_INDIVIDUAL_ARTIFACT_WARNING_BYTES,
    individual_failure_bytes=DEFAULT_INDIVIDUAL_ARTIFACT_FAILURE_BYTES,
    total_warning_bytes=DEFAULT_TOTAL_ARTIFACT_WARNING_BYTES,
    total_failure_bytes=DEFAULT_TOTAL_ARTIFACT_FAILURE_BYTES,
    largest_limit=10,
    variant_registry_path: str | Path | None = DEFAULT_VARIANT_REGISTRY_PATH,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    registry = build_artifact_registry(
        root=root,
        generated_at=generated_at,
        variant_registry_path=variant_registry_path,
    )
    artifacts = registry["artifacts"]
    total_bytes = sum(row["bytes"] for row in artifacts)
    unmanaged_git_bytes = sum(row.get("unmanaged_git_bytes", row["bytes"]) for row in artifacts)
    managed_external_bytes = sum(row.get("managed_external_bytes", 0) for row in artifacts)
    checks = []
    for row in artifacts:
        measured_bytes = row.get("unmanaged_git_bytes", row["bytes"])
        if measured_bytes >= individual_failure_bytes:
            checks.append(_threshold_row("individual_artifact", "FAIL", measured_bytes, individual_failure_bytes, row))
        elif measured_bytes >= individual_warning_bytes:
            checks.append(_threshold_row("individual_artifact", "WARN", measured_bytes, individual_warning_bytes, row))
    if unmanaged_git_bytes >= total_failure_bytes:
        checks.append(_threshold_row("total_artifacts", "FAIL", unmanaged_git_bytes, total_failure_bytes))
    elif unmanaged_git_bytes >= total_warning_bytes:
        checks.append(_threshold_row("total_artifacts", "WARN", unmanaged_git_bytes, total_warning_bytes))

    largest = sorted(artifacts, key=lambda row: row["bytes"], reverse=True)[:largest_limit]
    thresholds = {
        "individual_warning_bytes": int(individual_warning_bytes),
        "individual_failure_bytes": int(individual_failure_bytes),
        "total_warning_bytes": int(total_warning_bytes),
        "total_failure_bytes": int(total_failure_bytes),
        "policy": (
            "Track small JSON calibration artifacts and manifests in Git. "
            "Move binary model artifacts that reach the warning threshold to Git LFS "
            "or an external artifact store before promotion. Size thresholds apply "
            "to unmanaged Git payload; LFS/externalized artifacts remain counted in "
            "working_tree_bytes and managed_external_bytes for restore planning."
        ),
    }
    return {
        "schema_version": ARTIFACT_SIZE_AUDIT_SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "artifact_root": registry["artifact_root"],
        "status": _size_status(checks),
        "artifact_count": registry["artifact_count"],
        "total_bytes": total_bytes,
        "working_tree_bytes": total_bytes,
        "unmanaged_git_bytes": unmanaged_git_bytes,
        "managed_external_bytes": managed_external_bytes,
        "kind_counts": registry["kind_counts"],
        "storage_backend_counts": registry["storage_backend_counts"],
        "registry_use_counts": registry["registry_use_counts"],
        "thresholds": thresholds,
        "largest_artifacts": largest,
        "checks": checks,
    }


def write_artifact_size_audit(
    path: str | Path = DEFAULT_ARTIFACT_SIZE_AUDIT_PATH,
    root: str | Path = ARTIFACTS_ROOT,
    **kwargs,
) -> Path:
    payload = build_artifact_size_audit(root=root, **kwargs)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def build_artifact_externalization_manifest(
    root: str | Path = ARTIFACTS_ROOT,
    *,
    generated_at=None,
    variant_registry_path: str | Path | None = DEFAULT_VARIANT_REGISTRY_PATH,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    registry = build_artifact_registry(
        root=root,
        generated_at=generated_at,
        variant_registry_path=variant_registry_path,
    )
    managed = [
        row for row in registry["artifacts"]
        if row.get("storage_managed")
    ]
    backend_counts = Counter(row.get("storage_backend") for row in managed)
    return {
        "schema_version": ARTIFACT_EXTERNALIZATION_SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "artifact_root": registry["artifact_root"],
        "managed_artifact_count": len(managed),
        "managed_external_bytes": sum(row["bytes"] for row in managed),
        "storage_backend_counts": dict(sorted(backend_counts.items())),
        "restore_instructions": {
            "git_lfs": (
                "Install Git LFS, then run "
                '`git lfs pull --include="artifacts/models/hgb/*.pkl"` '
                "from the repository root after checkout."
            ),
            "external_artifact_store": (
                "Fetch each artifact from the URI named by its manifest entry "
                "and verify SHA-256 before promotion."
            ),
        },
        "artifacts": [
            {
                "artifact_id": row["artifact_id"],
                "path": row["path"],
                "kind": row["kind"],
                "bytes": row["bytes"],
                "sha256": row["sha256"],
                "storage_backend": row["storage_backend"],
                "restore_instruction": row["restore_instruction"],
                "registry_use": row["registry_use"],
                "reproducibility_requirement": row["reproducibility_requirement"],
                "variant_refs": row.get("variant_refs") or [],
            }
            for row in managed
        ],
    }


def write_artifact_externalization_manifest(
    path: str | Path = DEFAULT_ARTIFACT_EXTERNALIZATION_PATH,
    root: str | Path = ARTIFACTS_ROOT,
    **kwargs,
) -> Path:
    payload = build_artifact_externalization_manifest(root=root, **kwargs)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _preflight_check(severity, category, detail, *, artifact_id=None, path=None, variant_id=None):
    row = {
        "severity": severity,
        "category": category,
        "detail": detail,
    }
    if artifact_id is not None:
        row["artifact_id"] = artifact_id
    if path is not None:
        row["path"] = str(path)
    if variant_id is not None:
        row["variant_id"] = variant_id
    return row


def _artifact_registry_identity(payload: dict) -> dict:
    """Project a registry to checkout-stable artifact identity fields."""

    return {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at_utc", "artifacts"}
    } | {
        "artifacts": [
            {
                key: value
                for key, value in row.items()
                if key != "modified_at_utc"
            }
            for row in (payload.get("artifacts") or [])
        ]
    }


def _artifact_externalization_identity(payload: dict) -> dict:
    return {
        key: value
        for key, value in payload.items()
        if key != "generated_at_utc"
    }


def _identity_sha256(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_tracked_artifact_manifest(path: Path, *, label: str) -> dict:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def tracked_artifact_manifest_checks(
    *,
    root: str | Path = ARTIFACTS_ROOT,
    variant_registry_path: str | Path | None = DEFAULT_VARIANT_REGISTRY_PATH,
    registry_manifest_path: str | Path = DEFAULT_ARTIFACT_REGISTRY_PATH,
    externalization_manifest_path: str | Path = DEFAULT_ARTIFACT_EXTERNALIZATION_PATH,
) -> list[dict]:
    """Compare tracked manifest identity with the current artifact tree.

    Generation timestamps and checkout-dependent mtimes are diagnostic and are
    deliberately excluded. Artifact bytes, hashes, classification, restore
    policy, variant bindings, counts, and storage totals must match exactly.
    """

    current_registry = build_artifact_registry(
        root=root,
        generated_at="1970-01-01T00:00:00+00:00",
        variant_registry_path=variant_registry_path,
    )
    current_externalization = build_artifact_externalization_manifest(
        root=root,
        generated_at="1970-01-01T00:00:00+00:00",
        variant_registry_path=variant_registry_path,
    )
    specs = (
        (
            "artifact_registry_identity_mismatch",
            Path(registry_manifest_path),
            "artifact registry",
            _artifact_registry_identity,
            current_registry,
        ),
        (
            "artifact_externalization_identity_mismatch",
            Path(externalization_manifest_path),
            "artifact externalization manifest",
            _artifact_externalization_identity,
            current_externalization,
        ),
    )
    checks = []
    for category, path, label, projector, current in specs:
        try:
            tracked = _load_tracked_artifact_manifest(path, label=label)
            tracked_identity = projector(tracked)
            current_identity = projector(current)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            checks.append(
                _preflight_check(
                    "error",
                    category,
                    f"{label} is missing or unreadable: {exc}",
                    path=path,
                )
            )
            continue
        tracked_sha = _identity_sha256(tracked_identity)
        current_sha = _identity_sha256(current_identity)
        if tracked_sha != current_sha:
            checks.append(
                _preflight_check(
                    "error",
                    category,
                    (
                        f"{label} does not match current artifact identity; "
                        f"tracked={tracked_sha}, current={current_sha}; regenerate "
                        "all artifact manifests with their canonical producers"
                    ),
                    path=path,
                )
            )
    return checks


def _variant_local_path_checks(registry_path: str | Path | None) -> list[dict]:
    if registry_path in (None, ""):
        return []
    path = Path(registry_path)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return [
            _preflight_check(
                "error",
                "variant_registry_unreadable",
                "variant registry could not be read as JSON",
                path=path,
            )
        ]
    checks = []
    for variant in payload.get("variants") or []:
        if not isinstance(variant, dict) or variant.get("lifecycle") != "active":
            continue
        contract = _variant_contract(variant)
        artifact_path = contract.get("artifact_path")
        rel = _repo_relative_value(artifact_path)
        if not rel or not rel.startswith("data/"):
            continue
        severity = "warning" if _shadow_only_variant(variant) else "error"
        category = (
            "shadow_local_candidate_artifact_path"
            if severity == "warning"
            else "active_local_artifact_path"
        )
        checks.append(_preflight_check(
            severity,
            category,
            (
                "active registry artifacts must live under artifacts/ with "
                "Git LFS or external manifest coverage unless explicitly "
                "marked shadow-only"
            ),
            path=artifact_path,
            variant_id=variant.get("variant_id"),
        ))
    return checks


def build_artifact_promotion_preflight(
    root: str | Path = ARTIFACTS_ROOT,
    *,
    generated_at=None,
    variant_registry_path: str | Path | None = DEFAULT_VARIANT_REGISTRY_PATH,
    individual_warning_bytes=DEFAULT_INDIVIDUAL_ARTIFACT_WARNING_BYTES,
    individual_failure_bytes=DEFAULT_INDIVIDUAL_ARTIFACT_FAILURE_BYTES,
    total_warning_bytes=DEFAULT_TOTAL_ARTIFACT_WARNING_BYTES,
    total_failure_bytes=DEFAULT_TOTAL_ARTIFACT_FAILURE_BYTES,
    verify_tracked_manifests: bool = False,
    registry_manifest_path: str | Path = DEFAULT_ARTIFACT_REGISTRY_PATH,
    externalization_manifest_path: str | Path = DEFAULT_ARTIFACT_EXTERNALIZATION_PATH,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    size_audit = build_artifact_size_audit(
        root=root,
        generated_at=generated_at,
        variant_registry_path=variant_registry_path,
        individual_warning_bytes=individual_warning_bytes,
        individual_failure_bytes=individual_failure_bytes,
        total_warning_bytes=total_warning_bytes,
        total_failure_bytes=total_failure_bytes,
    )
    checks = list(size_audit.get("checks") or [])
    checks.extend(_variant_local_path_checks(variant_registry_path))
    if verify_tracked_manifests:
        checks.extend(
            tracked_artifact_manifest_checks(
                root=root,
                variant_registry_path=variant_registry_path,
                registry_manifest_path=registry_manifest_path,
                externalization_manifest_path=externalization_manifest_path,
            )
        )
    error_count = sum(1 for row in checks if row.get("severity") == "error" or row.get("status") == "FAIL")
    warning_count = sum(1 for row in checks if row.get("severity") == "warning" or row.get("status") == "WARN")
    status = "FAIL" if error_count else ("WARN" if warning_count else "PASS")
    return {
        "schema_version": ARTIFACT_PROMOTION_PREFLIGHT_SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "status": status,
        "artifact_root": size_audit.get("artifact_root"),
        "variant_registry_path": (
            _repo_relative_value(variant_registry_path)
            or str(variant_registry_path)
            if variant_registry_path
            else None
        ),
        "summary": {
            "artifact_count": size_audit.get("artifact_count"),
            "working_tree_bytes": size_audit.get("working_tree_bytes"),
            "unmanaged_git_bytes": size_audit.get("unmanaged_git_bytes"),
            "managed_external_bytes": size_audit.get("managed_external_bytes"),
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "size_audit": size_audit,
        "checks": checks,
        "tracked_manifest_verification": {
            "required": bool(verify_tracked_manifests),
            "status": (
                "PASS"
                if verify_tracked_manifests
                and not any(
                    row.get("category")
                    in {
                        "artifact_registry_identity_mismatch",
                        "artifact_externalization_identity_mismatch",
                    }
                    for row in checks
                )
                else "BLOCK"
                if verify_tracked_manifests
                else "NOT_RUN"
            ),
            "registry_manifest_path": _repo_relative_value(registry_manifest_path)
            or str(registry_manifest_path),
            "externalization_manifest_path": _repo_relative_value(
                externalization_manifest_path
            )
            or str(externalization_manifest_path),
        },
    }


def write_artifact_promotion_preflight(
    path: str | Path = DEFAULT_ARTIFACT_PROMOTION_PREFLIGHT_PATH,
    root: str | Path = ARTIFACTS_ROOT,
    **kwargs,
) -> Path:
    payload = build_artifact_promotion_preflight(root=root, **kwargs)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def cmd_registry(args):
    out = write_artifact_registry(args.out, root=args.root, variant_registry_path=args.variant_registry)
    payload = json.loads(Path(out).read_text(encoding="utf-8"))
    print(f"Wrote artifact registry to {out}")
    print(f"artifacts={payload.get('artifact_count')} kinds={payload.get('kind_counts')}")


def cmd_size_audit(args):
    out = write_artifact_size_audit(
        args.out,
        root=args.root,
        individual_warning_bytes=args.individual_warning_bytes,
        individual_failure_bytes=args.individual_failure_bytes,
        total_warning_bytes=args.total_warning_bytes,
        total_failure_bytes=args.total_failure_bytes,
        variant_registry_path=args.variant_registry,
    )
    payload = json.loads(Path(out).read_text(encoding="utf-8"))
    print(f"Wrote artifact size audit to {out}")
    print(
        "status={status} artifacts={count} unmanaged_mib={unmanaged:.2f} managed_mib={managed:.2f}".format(
            status=payload.get("status"),
            count=payload.get("artifact_count"),
            unmanaged=(payload.get("unmanaged_git_bytes") or 0) / MIB,
            managed=(payload.get("managed_external_bytes") or 0) / MIB,
        )
    )
    for row in payload.get("checks") or []:
        artifact = row.get("artifact_id") or row.get("kind")
        print(
            "{status}: {artifact} {size:.2f} MiB threshold={threshold:.2f} MiB".format(
                status=row.get("status"),
                artifact=artifact,
                size=(row.get("bytes") or 0) / MIB,
                threshold=(row.get("threshold_bytes") or 0) / MIB,
            )
        )
    if payload.get("status") == "FAIL" or (args.fail_on_warn and payload.get("status") == "WARN"):
        raise SystemExit(1)


def cmd_externalization_manifest(args):
    out = write_artifact_externalization_manifest(
        args.out,
        root=args.root,
        variant_registry_path=args.variant_registry,
    )
    payload = json.loads(Path(out).read_text(encoding="utf-8"))
    print(f"Wrote artifact externalization manifest to {out}")
    print(
        "managed_artifacts={count} managed_mib={managed:.2f}".format(
            count=payload.get("managed_artifact_count"),
            managed=(payload.get("managed_external_bytes") or 0) / MIB,
        )
    )


def cmd_promotion_preflight(args):
    out = write_artifact_promotion_preflight(
        args.out,
        root=args.root,
        variant_registry_path=args.variant_registry,
        individual_warning_bytes=args.individual_warning_bytes,
        individual_failure_bytes=args.individual_failure_bytes,
        total_warning_bytes=args.total_warning_bytes,
        total_failure_bytes=args.total_failure_bytes,
        verify_tracked_manifests=not args.skip_tracked_manifest_verification,
        registry_manifest_path=args.registry_manifest,
        externalization_manifest_path=args.externalization_manifest,
    )
    payload = json.loads(Path(out).read_text(encoding="utf-8"))
    summary = payload.get("summary") or {}
    print(f"Wrote artifact promotion preflight to {out}")
    print(
        "status={status} unmanaged_mib={unmanaged:.2f} managed_mib={managed:.2f} errors={errors} warnings={warnings}".format(
            status=payload.get("status"),
            unmanaged=(summary.get("unmanaged_git_bytes") or 0) / MIB,
            managed=(summary.get("managed_external_bytes") or 0) / MIB,
            errors=summary.get("error_count"),
            warnings=summary.get("warning_count"),
        )
    )
    if payload.get("status") == "FAIL" or (args.fail_on_warn and payload.get("status") == "WARN"):
        raise SystemExit(1)


def build_parser():
    parser = argparse.ArgumentParser(description="Artifact path and registry utilities.")
    sub = parser.add_subparsers(dest="command", required=True)
    registry = sub.add_parser("registry")
    registry.add_argument("--root", default=str(ARTIFACTS_ROOT))
    registry.add_argument("--out", default=str(DEFAULT_ARTIFACT_REGISTRY_PATH))
    registry.add_argument("--variant-registry", default=str(DEFAULT_VARIANT_REGISTRY_PATH))
    registry.set_defaults(func=cmd_registry)
    size_audit = sub.add_parser("size-audit")
    size_audit.add_argument("--root", default=str(ARTIFACTS_ROOT))
    size_audit.add_argument("--out", default=str(DEFAULT_ARTIFACT_SIZE_AUDIT_PATH))
    size_audit.add_argument("--variant-registry", default=str(DEFAULT_VARIANT_REGISTRY_PATH))
    size_audit.add_argument("--individual-warning-bytes", type=int, default=DEFAULT_INDIVIDUAL_ARTIFACT_WARNING_BYTES)
    size_audit.add_argument("--individual-failure-bytes", type=int, default=DEFAULT_INDIVIDUAL_ARTIFACT_FAILURE_BYTES)
    size_audit.add_argument("--total-warning-bytes", type=int, default=DEFAULT_TOTAL_ARTIFACT_WARNING_BYTES)
    size_audit.add_argument("--total-failure-bytes", type=int, default=DEFAULT_TOTAL_ARTIFACT_FAILURE_BYTES)
    size_audit.add_argument("--fail-on-warn", action="store_true")
    size_audit.set_defaults(func=cmd_size_audit)
    externalization = sub.add_parser("externalization-manifest")
    externalization.add_argument("--root", default=str(ARTIFACTS_ROOT))
    externalization.add_argument("--out", default=str(DEFAULT_ARTIFACT_EXTERNALIZATION_PATH))
    externalization.add_argument("--variant-registry", default=str(DEFAULT_VARIANT_REGISTRY_PATH))
    externalization.set_defaults(func=cmd_externalization_manifest)
    preflight = sub.add_parser("promotion-preflight")
    preflight.add_argument("--root", default=str(ARTIFACTS_ROOT))
    preflight.add_argument("--out", default=str(DEFAULT_ARTIFACT_PROMOTION_PREFLIGHT_PATH))
    preflight.add_argument("--variant-registry", default=str(DEFAULT_VARIANT_REGISTRY_PATH))
    preflight.add_argument("--individual-warning-bytes", type=int, default=DEFAULT_INDIVIDUAL_ARTIFACT_WARNING_BYTES)
    preflight.add_argument("--individual-failure-bytes", type=int, default=DEFAULT_INDIVIDUAL_ARTIFACT_FAILURE_BYTES)
    preflight.add_argument("--total-warning-bytes", type=int, default=DEFAULT_TOTAL_ARTIFACT_WARNING_BYTES)
    preflight.add_argument("--total-failure-bytes", type=int, default=DEFAULT_TOTAL_ARTIFACT_FAILURE_BYTES)
    preflight.add_argument("--registry-manifest", default=str(DEFAULT_ARTIFACT_REGISTRY_PATH))
    preflight.add_argument("--externalization-manifest", default=str(DEFAULT_ARTIFACT_EXTERNALIZATION_PATH))
    preflight.add_argument(
        "--skip-tracked-manifest-verification",
        action="store_true",
        help="Custom-root diagnostics only: do not compare tracked manifest identity.",
    )
    preflight.add_argument("--fail-on-warn", action="store_true")
    preflight.set_defaults(func=cmd_promotion_preflight)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
