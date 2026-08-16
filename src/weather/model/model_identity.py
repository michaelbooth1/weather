"""Deterministic replay identity for model distributions.

The human model version string is useful for release notes, but it is not
specific enough for replay fidelity: retraining artifacts can change while the
version label stays the same. The replay canary needs the exact distribution
identity that produced a snapshot.

Binding rules (``v0.3``)
------------------------

Under ``v0.1`` the code fingerprint was read **from disk at capture time**, while
the recorded ``git_commit`` was ``HEAD``. Neither describes the bytes a
long-running loop actually loaded, and a roll-free commit advances ``HEAD``
without restarting the loop, so three states could disagree at once. The
measured consequence: only 114 of 358 decision snapshots reproduced their own
recorded output, and 0 of 63 captured identities could be rebuilt from Git.

``v0.2`` attempted to bind identity to the process, but its raw marshalled code
objects retained ``co_filename`` and therefore hashed identical code
differently across worktree paths.  It also omitted nested behavior constants
and continued to hash artifact files from disk at capture time.

``v0.3`` binds the identity to the process instead of to the filesystem:

* Diagnostic ``code_hash`` is snapshotted **once, at import**, the way
  ``snapshot_store.PROCESS_RUNTIME_IDENTITY`` already does. It describes the
  tree the process started from, not the tree at capture time, and does not
  feed the authoritative identity hash.
* ``loaded_code_hash`` hashes a path-normalized representation of the **code
  objects held in memory** plus canonical nested behavior constants.
* ``loaded_artifact_hash`` hashes the estimator and postprocessor state held by
  the model.  The legacy disk artifact hash remains observable but cannot
  relabel a process after its artifacts were deserialized.
* ``code_disk_drift`` reports, at every capture, whether disk has since moved
  away from what this process loaded. It is observed, not hashed into the
  identity, so an unrelated edit no longer changes the identity of what ran.

Nothing here writes to disk: capture must not gain a new write path.
"""
from __future__ import annotations

import hashlib
import json
import marshal
import sys
import types
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from importlib.metadata import PackageNotFoundError, version as distribution_version
from pathlib import Path

from weather.artifacts import resolve_artifact_path
from weather.paths import SRC_ROOT, relative_to_repo


IDENTITY_SCHEMA_VERSION = "weather_model_replay_identity_v0.3"

# Files that can alter estimate_distribution for a fixed captured sources dict.
# Keep this list focused on pure distribution/feature/calibration code; the
# identity helper itself is intentionally excluded so report-only edits do not
# invalidate otherwise faithful captures.
DISTRIBUTION_CODE_FILES = (
    Path("weather/model/toronto_model.py"),
    Path("weather/model/model_base.py"),
    Path("weather/model/model_climatology.py"),
    Path("weather/model/model_constants.py"),
    Path("weather/model/model_contracts.py"),
    Path("weather/model/model_distribution.py"),
    Path("weather/model/model_distribution_constants.py"),
    Path("weather/model/model_distribution_signals.py"),
    Path("weather/model/model_features.py"),
    Path("weather/model/model_sources.py"),
    Path("weather/model/feature_store.py"),
    Path("weather/model/calibration_runtime.py"),
    Path("weather/model/continuous_density.py"),
    Path("weather/market/market_config.py"),
    Path("weather/market/market_registry.py"),
    Path("weather/scoring/metrics.py"),
    Path("weather/sources/daily_summary.py"),
    Path("weather/sources/eccc_gridded.py"),
    Path("weather/sources/forecast_history.py"),
    Path("weather/sources/marine_context.py"),
    Path("weather/sources/mrms_precip.py"),
    Path("weather/sources/nbm_probabilistic_tmax.py"),
    Path("weather/sources/reanalysis_synoptic.py"),
    Path("weather/units.py"),
)

DISTRIBUTION_ARTIFACT_TEMPLATES = (
    "calibrated_weights{suffix}.json",
    "feature_model_coefs{suffix}.json",
    "feature_model_hgb{suffix}.pkl",
    "late_day_model_coefs{suffix}.json",
    "probability_calibration{suffix}.json",
    "forecast_error_model{suffix}.json",
    "settlement_lag_model{suffix}.json",
)

# Runtime attributes that are capable of changing the served distribution.
# The object held by the model is fingerprinted; the path visible on disk at a
# later capture is only diagnostic.  Keep this list aligned with
# RELEASE_BOUND_BASE_MODEL_LOADER_BOUNDARIES in weather.release_serving.
LOADED_ARTIFACT_COMPONENTS = (
    ("calibrated_weights", "calibrated_weights"),
    ("feature_lr_coefficients", "_feature_model_coefs"),
    ("feature_hgb", "_feature_model_hgb"),
    ("late_day_lr_coefficients", "_late_day_model_coefs"),
    ("probability_calibration", "probability_calibration"),
    ("forecast_error_model", "forecast_error_model"),
    ("settlement_lag_model", "settlement_lag_model"),
    ("afternoon_residual_centering", "afternoon_residual_centering"),
    ("family_secondary_artifacts", "family_secondary_artifacts"),
)

RUNTIME_DEPENDENCY_DISTRIBUTIONS = ("numpy", "scipy", "scikit-learn")

_MISSING = object()
_UNSUPPORTED = object()


def _runtime_dependency_identity() -> dict:
    packages = {}
    for distribution in RUNTIME_DEPENDENCY_DISTRIBUTIONS:
        try:
            packages[distribution] = distribution_version(distribution)
        except PackageNotFoundError:
            packages[distribution] = None
    payload = {
        "python_version": sys.version.split()[0],
        "implementation_cache_tag": sys.implementation.cache_tag,
        "marshal_version": marshal.version,
        "packages": packages,
    }
    return {**payload, "runtime_dependency_hash": _hash_payload(payload)}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_payload(payload) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(encoded)


_RUNTIME_DEPENDENCY_IDENTITY = _runtime_dependency_identity()


def _canonical_json(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _constant_payload(value, seen: set[int] | None = None):
    """Return a path-stable JSON value for behavior-bearing Python state.

    Unsupported objects return ``_UNSUPPORTED`` rather than falling back to
    ``repr``: reprs commonly contain memory addresses or checkout paths and
    would recreate the exact false identity this module is meant to prevent.
    """
    seen = set() if seen is None else seen
    value_type = type(value)
    if value is None:
        return ["none"]
    if value_type is bool:
        return ["bool", value]
    if value_type is int:
        return ["int", str(value)]
    if value_type is float:
        return ["float", value.hex()]
    if value_type is str:
        return ["str", value]
    if value_type is bytes:
        return ["bytes", value.hex()]
    if isinstance(value, Enum):
        child = _constant_payload(value.value, seen)
        if child is _UNSUPPORTED:
            return _UNSUPPORTED
        return ["enum", f"{value_type.__module__}.{value_type.__qualname__}", child]
    if isinstance(value, Path):
        relative = relative_to_repo(value)
        return (
            ["repo_path", relative]
            if relative and not Path(relative).is_absolute()
            else _UNSUPPORTED
        )

    object_id = id(value)
    if object_id in seen:
        return _UNSUPPORTED
    seen.add(object_id)
    try:
        if isinstance(value, Mapping):
            pairs = []
            for key, child_value in value.items():
                key_payload = _constant_payload(key, seen)
                value_payload = _constant_payload(child_value, seen)
                if key_payload is _UNSUPPORTED or value_payload is _UNSUPPORTED:
                    return _UNSUPPORTED
                pairs.append([key_payload, value_payload])
            pairs.sort(key=lambda pair: _canonical_json(pair[0]))
            return ["mapping", pairs]
        if value_type in {tuple, list}:
            children = []
            for child_value in value:
                child = _constant_payload(child_value, seen)
                if child is _UNSUPPORTED:
                    return _UNSUPPORTED
                children.append(child)
            return [value_type.__name__, children]
        if value_type in {set, frozenset}:
            children = []
            for child_value in value:
                child = _constant_payload(child_value, seen)
                if child is _UNSUPPORTED:
                    return _UNSUPPORTED
                children.append(child)
            children.sort(key=_canonical_json)
            return [value_type.__name__, children]
        if is_dataclass(value) and not isinstance(value, type):
            children = []
            for field in fields(value):
                child = _constant_payload(getattr(value, field.name), seen)
                if child is _UNSUPPORTED:
                    return _UNSUPPORTED
                children.append([field.name, child])
            return ["dataclass", f"{value_type.__module__}.{value_type.__qualname__}", children]
        return _UNSUPPORTED
    finally:
        seen.remove(object_id)


def _function_state(function: types.FunctionType):
    closure_values = []
    for cell in function.__closure__ or ():
        try:
            closure_values.append(cell.cell_contents)
        except ValueError:
            closure_values.append(["empty_closure_cell"])
    state = {
        "defaults": function.__defaults__,
        "kwdefaults": function.__kwdefaults__,
        "closure": tuple(closure_values),
    }
    payload = _constant_payload(state)
    if payload is not _UNSUPPORTED:
        return payload
    partial = {}
    for key, value in state.items():
        child = _constant_payload(value)
        partial[key] = (
            child
            if child is not _UNSUPPORTED
            else ["unsupported", type(value).__module__, type(value).__qualname__]
        )
    return [
        "partially_unsupported_function_state",
        partial,
    ]


def _normalized_code_object(code: types.CodeType) -> types.CodeType:
    """Remove checkout paths from a code object, including nested bodies."""
    constants = tuple(
        _normalized_code_object(value) if isinstance(value, types.CodeType) else value
        for value in code.co_consts
    )
    return code.replace(co_consts=constants, co_filename="<loaded-weather-code>")


def file_fingerprint(path: Path) -> dict:
    """Stable metadata for one file path, including absence.

    Missing files matter because many US markets intentionally have no
    per-market calibration artifacts yet. If one appears later, the replay
    identity must change.
    """
    path = Path(path)
    rel = relative_to_repo(path)
    if not path.exists():
        return {"path": rel, "exists": False, "size": None, "sha256": None}
    data = path.read_bytes()
    return {
        "path": rel,
        "exists": True,
        "size": len(data),
        "sha256": _sha256_bytes(data),
    }


def _combined_hash(items: list[dict]) -> str:
    reduced = [
        {
            "path": item.get("path"),
            "exists": item.get("exists"),
            "sha256": item.get("sha256"),
        }
        for item in items
    ]
    return _hash_payload(reduced)


def _module_name_for(relative_path: Path) -> str:
    """``weather/model/model_base.py`` -> ``weather.model.model_base``."""
    return ".".join(Path(relative_path).with_suffix("").parts)


def _code_objects(
    namespace, module_name: str, seen: set[int]
) -> list[tuple[str, types.CodeType, object]]:
    """Every code object this module defines, in a stable order.

    Only objects whose ``__module__`` is this module are included, so a
    re-exported helper is fingerprinted once, by its owner.
    """
    found: list[tuple[str, types.CodeType, object]] = []
    for name in sorted(namespace):
        obj = namespace[name]
        if isinstance(obj, (staticmethod, classmethod)):
            obj = obj.__func__
        if isinstance(obj, property):
            for suffix, accessor in (("fget", obj.fget), ("fset", obj.fset), ("fdel", obj.fdel)):
                if isinstance(accessor, types.FunctionType):
                    found.append(
                        (f"{name}.{suffix}", accessor.__code__, _function_state(accessor))
                    )
            continue
        if isinstance(obj, types.FunctionType):
            if getattr(obj, "__module__", None) == module_name:
                found.append((name, obj.__code__, _function_state(obj)))
            continue
        if isinstance(obj, type):
            if getattr(obj, "__module__", None) != module_name or id(obj) in seen:
                continue
            seen.add(id(obj))
            for sub_name, code, state in _code_objects(dict(vars(obj)), module_name, seen):
                found.append((f"{name}.{sub_name}", code, state))
    return found


def _module_constants(namespace: dict) -> list[tuple[str, str]]:
    """Canonical module-level behavior constants.

    ``model_constants.py`` defines no functions at all, so a bytecode-only
    witness would report an empty fingerprint for it and a changed constant
    would move nothing.  Containers are admitted only for conventional
    uppercase constants; this captures TTL maps, feature contracts and market
    registries without binding mutable runtime caches.  Dunders are excluded
    deliberately because their values are process/path metadata.
    """
    found: list[tuple[str, str]] = []
    for name in sorted(namespace):
        if name.startswith("__") and name.endswith("__"):
            continue
        value = namespace[name]
        is_scalar = type(value) in {bool, int, float, str, bytes, type(None)}
        if not is_scalar and name.upper() != name:
            continue
        payload = _constant_payload(value)
        if payload is not _UNSUPPORTED:
            found.append((name, _canonical_json(payload)))
    return found


def loaded_code_fingerprint(module_name: str) -> dict:
    """Fingerprint one module from the code objects held in memory.

    This never touches the filesystem, so it remains correct after the source
    file is edited, moved or deleted -- which is exactly the failure ``v0.1``
    could not see.
    """
    module = sys.modules.get(module_name)
    if module is None:
        return {
            "module": module_name,
            "loaded": False,
            "file": None,
            "code_units": None,
            "constants": None,
            "sha256": None,
        }
    namespace = dict(vars(module))
    digest = hashlib.sha256()
    units = 0
    for name, code, function_state in _code_objects(namespace, module_name, set()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(marshal.dumps(_normalized_code_object(code)))
        digest.update(b"\2")
        digest.update(_canonical_json(function_state).encode("utf-8"))
        digest.update(b"\0")
        units += 1
    constants = _module_constants(namespace)
    for name, value in constants:
        digest.update(name.encode("utf-8"))
        digest.update(b"\1")
        digest.update(value.encode("utf-8"))
        digest.update(b"\1")
    return {
        "module": module_name,
        "loaded": True,
        "file": relative_to_repo(Path(getattr(module, "__file__", "") or "")) or None,
        "code_units": units,
        "constants": len(constants),
        "sha256": digest.hexdigest(),
    }


def _runtime_state_fingerprint(value) -> tuple[str, bytes]:
    """Serialize already-loaded state without consulting its source file."""
    payload = _constant_payload(value)
    if payload is _UNSUPPORTED:
        raise TypeError(f"unsupported loaded artifact state: {type(value).__qualname__}")
    return "canonical-json-1", _canonical_json(payload).encode("utf-8")


def _loaded_artifact_source_hashes(model) -> dict[str, dict]:
    """Exact source hashes captured at load or verified by a serving release."""
    sources = dict(getattr(model, "_loaded_artifact_source_hashes", {}) or {})
    bundle = getattr(model, "serving_bundle", None)
    graph = getattr(bundle, "base_model_graph", None)
    market_id = getattr(model, "market_id", None)
    if not isinstance(graph, Mapping) or not market_id:
        return sources
    market = (graph.get("markets") or {}).get(market_id)
    components = market.get("components") if isinstance(market, Mapping) else None
    if isinstance(components, Mapping):
        for role, descriptor in components.items():
            if isinstance(descriptor, Mapping) and descriptor.get("sha256"):
                sources.setdefault(
                    str(role),
                    {"sha256": str(descriptor["sha256"]), "size": None},
                )
    shared = graph.get("shared_components")
    if isinstance(shared, Mapping):
        for role, descriptor in shared.items():
            if isinstance(descriptor, Mapping) and descriptor.get("sha256"):
                sources.setdefault(
                    str(role),
                    {"sha256": str(descriptor["sha256"]), "size": None},
                )
    return sources


def loaded_artifact_identity(model) -> dict:
    """Fingerprint estimator/postprocessor state held by ``model``.

    The fingerprint is cached for the current component-object identity. Model
    artifacts are immutable after loading; lazy loading or a target/market
    switch changes the object signature and recomputes the witness.  The cache
    stores IDs and hashes only, so it does not retain an obsolete estimator
    graph after a daily market switch.
    """
    from weather.model.model_constants import _UNLOADED  # local: avoid an import cycle

    values = []
    source_hashes = _loaded_artifact_source_hashes(model)
    for role, attribute in LOADED_ARTIFACT_COMPONENTS:
        value = getattr(model, attribute, _MISSING)
        state = "unloaded" if value is _MISSING or value is _UNLOADED else "loaded"
        values.append((role, attribute, value, state))
    signature = tuple(
        (
            role,
            attribute,
            state,
            None if state == "unloaded" else id(value),
            source_hashes.get(role, {}).get("sha256"),
            source_hashes.get(role, {}).get("size"),
        )
        for role, attribute, value, state in values
    )
    cached = getattr(model, "_model_replay_loaded_artifact_identity", None)
    if isinstance(cached, dict) and cached.get("signature") == signature:
        return cached["identity"]

    records = []
    for role, attribute, value, state in values:
        if state == "unloaded":
            records.append(
                {
                    "role": role,
                    "attribute": attribute,
                    "state": state,
                    "encoding": None,
                    "serialized_size": None,
                    "sha256": None,
                }
            )
            continue
        try:
            source = source_hashes.get(role)
            if isinstance(source, Mapping) and source.get("sha256"):
                record = {
                    "role": role,
                    "attribute": attribute,
                    "state": state,
                    "encoding": "loaded-source-sha256-1",
                    "serialized_size": source.get("size"),
                    "sha256": str(source["sha256"]),
                }
            else:
                encoding, encoded = _runtime_state_fingerprint(value)
                record = {
                    "role": role,
                    "attribute": attribute,
                    "state": state,
                    "encoding": encoding,
                    "serialized_size": len(encoded),
                    "sha256": _sha256_bytes(encoded),
                }
        except Exception as exc:  # noqa: BLE001 - identity must not break capture
            record = {
                "role": role,
                "attribute": attribute,
                "state": "fingerprint_error",
                "encoding": None,
                "serialized_size": None,
                "sha256": None,
                "error_type": type(exc).__name__,
            }
        records.append(record)
    identity = {
        "components": records,
        "loaded_artifact_hash": _hash_payload(
            [
                {
                    "role": item["role"],
                    "state": item["state"],
                    "encoding": item["encoding"],
                    "sha256": item["sha256"],
                }
                for item in records
            ]
        ),
        "components_loaded": sum(item["state"] == "loaded" for item in records),
        "components_expected": len(records),
        "components_unloaded": [
            item["role"] for item in records if item["state"] == "unloaded"
        ],
        "components_failed": [
            item["role"] for item in records if item["state"] == "fingerprint_error"
        ],
    }
    try:
        setattr(
            model,
            "_model_replay_loaded_artifact_identity",
            {"signature": signature, "identity": identity},
        )
    except Exception:  # noqa: BLE001 - immutable test doubles may reject caching
        pass
    return identity


def _import_time_code_files() -> list[dict] | None:
    """Snapshot the distribution code as this process starts.

    Mirrors ``snapshot_store.PROCESS_RUNTIME_IDENTITY``, which already binds its
    fingerprint at import rather than at use. Identity must never break capture,
    so a failure here degrades to the live read rather than raising.
    """
    try:
        return [file_fingerprint(SRC_ROOT / name) for name in DISTRIBUTION_CODE_FILES]
    except Exception:  # noqa: BLE001 - identity should not break capture
        return None


_IMPORT_TIME_UTC = datetime.now(timezone.utc).isoformat()
_IMPORT_TIME_CODE_FILES = _import_time_code_files()
_LOADED_MODULE_CACHE: dict[str, dict] = {}


def _unloaded_record(module_name: str) -> dict:
    return {
        "module": module_name,
        "loaded": False,
        "file": None,
        "code_units": None,
        "constants": None,
        "sha256": None,
    }


def loaded_code_identity() -> dict:
    """In-memory code identity for the distribution modules.

    Cached **per module**, not per process. Loaded code cannot change without a
    restart, so a module already fingerprinted is never re-read. But several of
    these modules import lazily, so a module still missing is retried on each
    call until it appears. Caching the whole set on the first call would freeze
    it as "never loaded" for the life of the process.
    """
    modules = []
    for relative in DISTRIBUTION_CODE_FILES:
        module_name = _module_name_for(relative)
        record = _LOADED_MODULE_CACHE.get(module_name)
        if record is None or not record["loaded"]:
            try:
                record = loaded_code_fingerprint(module_name)
            except Exception:  # noqa: BLE001 - identity should not break capture
                record = _unloaded_record(module_name)
            _LOADED_MODULE_CACHE[module_name] = record
        modules.append(record)
    return {
        "modules": modules,
        "loaded_code_hash": _hash_payload(
            [{"module": item["module"], "sha256": item["sha256"]} for item in modules]
        ),
        "modules_loaded": sum(1 for item in modules if item["loaded"]),
        "modules_expected": len(modules),
        "modules_not_loaded": [item["module"] for item in modules if not item["loaded"]],
        "marshal_version": marshal.version,
        "python_version": sys.version.split()[0],
    }


def model_replay_identity(model) -> dict:
    """Return the deterministic identity of the model's current distribution.

    Call this after ``estimate_distribution`` so ``active_model_kind`` reflects
    the path that actually served the snapshot.
    """
    spec = getattr(model, "spec", None)
    market_id = getattr(model, "market_id", None) or getattr(spec, "id", None)
    suffix = getattr(spec, "artifact_suffix", "")

    disk_code_files = [file_fingerprint(SRC_ROOT / name) for name in DISTRIBUTION_CODE_FILES]
    if _IMPORT_TIME_CODE_FILES is None:
        code_files, code_files_origin = disk_code_files, "live_fallback"
    else:
        code_files, code_files_origin = _IMPORT_TIME_CODE_FILES, "import_time"

    artifact_files = [
        file_fingerprint(resolve_artifact_path(template.format(suffix=suffix)))
        for template in DISTRIBUTION_ARTIFACT_TEMPLATES
    ]
    if getattr(spec, "display_unit", None) == "F":
        artifact_files.append(file_fingerprint(resolve_artifact_path("f_family_secondary_artifacts.json")))

    try:
        model_version = model.get_model_version_string()
    except Exception:  # noqa: BLE001 - identity should not break capture
        model_version = None

    loaded_code = loaded_code_identity()
    loaded_artifacts = loaded_artifact_identity(model)
    code_hash = _combined_hash(code_files)
    disk_code_hash = _combined_hash(disk_code_files)
    disk_artifact_hash = _combined_hash(artifact_files)

    # Only process-held state feeds identity_hash.  code_hash and artifact_hash
    # remain top-level observations for migration/debugging, but hashing either
    # would let a later filesystem edit relabel an unchanged process.
    identity_payload = {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "model_version": model_version,
        "market_id": market_id,
        "active_model_kind": getattr(model, "active_model_kind", None),
        "loaded_code_hash": loaded_code["loaded_code_hash"],
        "loaded_artifact_hash": loaded_artifacts["loaded_artifact_hash"],
        "runtime_dependency_hash": _RUNTIME_DEPENDENCY_IDENTITY[
            "runtime_dependency_hash"
        ],
    }
    identity_hash = _hash_payload(identity_payload)
    return {
        **identity_payload,
        # Legacy diagnostic names: these describe the import-time/disk trees,
        # not the authoritative process identity under v0.3.
        "code_hash": code_hash,
        "artifact_hash": disk_artifact_hash,
        "identity_hash": identity_hash,
        "code_files": code_files,
        "artifact_files": artifact_files,
        # Observed, never hashed: an edit on disk describes the filesystem, not
        # the process, and must not change the identity of what actually ran.
        "runtime_binding": {
            "code_files_origin": code_files_origin,
            "import_time_utc": _IMPORT_TIME_UTC,
            "disk_code_hash": disk_code_hash,
            "code_disk_drift": bool(disk_code_hash != code_hash),
            "loaded_modules": loaded_code["modules"],
            "modules_loaded": loaded_code["modules_loaded"],
            "modules_expected": loaded_code["modules_expected"],
            "modules_not_loaded": loaded_code["modules_not_loaded"],
            "marshal_version": loaded_code["marshal_version"],
            "python_version": loaded_code["python_version"],
            "loaded_artifacts": loaded_artifacts["components"],
            "artifact_components_loaded": loaded_artifacts["components_loaded"],
            "artifact_components_expected": loaded_artifacts["components_expected"],
            "artifact_components_unloaded": loaded_artifacts["components_unloaded"],
            "artifact_components_failed": loaded_artifacts["components_failed"],
            "disk_artifact_hash": disk_artifact_hash,
            "runtime_dependencies": _RUNTIME_DEPENDENCY_IDENTITY,
        },
    }


def identity_hash(identity) -> str | None:
    if not isinstance(identity, dict):
        return None
    value = identity.get("identity_hash")
    return str(value) if value else None
