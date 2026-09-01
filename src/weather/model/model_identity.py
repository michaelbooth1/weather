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
import re
import sys
import types
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import fields, is_dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from importlib.metadata import PackageNotFoundError, version as distribution_version
from pathlib import Path
from zoneinfo import ZoneInfo

from weather.artifacts import resolve_artifact_path
from weather.paths import SRC_ROOT, relative_to_repo


IDENTITY_SCHEMA_VERSION = "weather_model_replay_identity_v0.3"
FINGERPRINT_COMPLETE = "COMPLETE"
FINGERPRINT_INCOMPLETE = "INCOMPLETE"
FINGERPRINT_UNLOADED = "UNLOADED"
FINGERPRINT_ERROR = "FINGERPRINT_ERROR"

# A source hash is authoritative for an opaque estimator only when the loader
# records that it fingerprinted the exact object produced from those bytes.
# Merely copying a release-manifest hash next to an arbitrary object does not
# establish that relationship.
LOADED_SOURCE_BINDING_MARKER = "loaded-object-source-sha256:1"

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

# The identity covers distribution behavior for a fixed captured-sources
# payload. This object only coordinates provider fetch fan-out before that
# payload exists; its mutable lock/cache state cannot change replay output.
# Keep the exclusion named and hashed rather than silently dropping an
# unsupported uppercase object.
EXPLICIT_NON_BEHAVIOR_MODULE_CONSTANTS = {
    (
        "weather.model.model_sources",
        "NBM_NATIONAL_TEXT_FANOUT",
    ): "provider_fetch_coordination_cache_outside_fixed_sources_replay",
    (
        "weather.release_serving",
        "_PROCESS_BUNDLES",
    ): "process_cache_state_bound_separately_by_pointer_and_manifest",
}

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


class _UnboundLoadedSourceHash(ValueError):
    """A claimed source hash was not tied to the materialized object."""


class _InvalidLoadedSourceHash(ValueError):
    """A claimed source hash was not a canonical SHA-256 digest."""


class _UnsupportedLoadedArtifactState(TypeError):
    """Loaded artifact state has no deterministic canonical encoding."""

    def __init__(self, unsupported_entries: list[dict]):
        self.unsupported_entries = unsupported_entries
        super().__init__(
            "unsupported loaded artifact state: "
            f"{_canonical_json(unsupported_entries)}"
        )


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


def runtime_dependency_identity() -> dict:
    """Return the import-time runtime dependency identity defensively.

    Runtime versions are part of the identity of the already-loaded process.
    Callers may serialize or annotate the returned mapping without mutating the
    process-global witness used by :func:`model_replay_identity`.
    """
    return deepcopy(_RUNTIME_DEPENDENCY_IDENTITY)


def _canonical_json(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _type_name(value) -> str:
    value_type = type(value)
    return f"{value_type.__module__}.{value_type.__qualname__}"


def _record_unsupported(
    unsupported: list[dict] | None,
    *,
    path: str,
    value,
    reason: str = "unsupported_type",
) -> None:
    if unsupported is not None:
        unsupported.append(
            {
                "path": path,
                "reason": reason,
                "type": _type_name(value),
            }
        )


def _normalized_unsupported(entries: list[dict]) -> list[dict]:
    unique = {_canonical_json(entry): entry for entry in entries}
    return [unique[key] for key in sorted(unique)]


def _constant_payload(
    value,
    seen: set[int] | None = None,
    *,
    unsupported: list[dict] | None = None,
    path: str = "$",
):
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
    if isinstance(value, ZoneInfo):
        return ["zoneinfo", value.key]
    if value_type is datetime:
        tz_payload = _constant_payload(
            value.tzinfo,
            seen,
            unsupported=unsupported,
            path=f"{path}.tzinfo",
        )
        if tz_payload is _UNSUPPORTED:
            return _UNSUPPORTED
        return [
            "datetime",
            value.replace(tzinfo=None).isoformat(timespec="microseconds"),
            value.fold,
            tz_payload,
        ]
    if value_type is date:
        return ["date", value.isoformat()]
    if value_type is time:
        tz_payload = _constant_payload(
            value.tzinfo,
            seen,
            unsupported=unsupported,
            path=f"{path}.tzinfo",
        )
        if tz_payload is _UNSUPPORTED:
            return _UNSUPPORTED
        return [
            "time",
            value.replace(tzinfo=None).isoformat(timespec="microseconds"),
            value.fold,
            tz_payload,
        ]
    if value_type is timedelta:
        return ["timedelta", value.days, value.seconds, value.microseconds]
    if value_type is timezone:
        offset = value.utcoffset(None)
        return [
            "timezone",
            None
            if offset is None
            else [offset.days, offset.seconds, offset.microseconds],
            value.tzname(None),
        ]
    if isinstance(value, re.Pattern):
        pattern = _constant_payload(
            value.pattern,
            seen,
            unsupported=unsupported,
            path=f"{path}.pattern",
        )
        if pattern is _UNSUPPORTED:
            return _UNSUPPORTED
        return ["compiled_regex", pattern, value.flags]
    # Dataclass-generated __init__ functions close over these documented
    # singleton sentinels. Their stable type names describe the sentinel; an
    # arbitrary object() remains unsupported unless a module-level name binds
    # it explicitly below.
    if _type_name(value) in {
        "dataclasses._HAS_DEFAULT_FACTORY_CLASS",
        "dataclasses._MISSING_TYPE",
    }:
        return ["named_type_sentinel", _type_name(value)]
    if isinstance(value, type):
        reference = f"{value.__module__}.{value.__qualname__}"
        if value.__module__ == "builtins":
            return ["builtin_reference", reference]
        if is_dataclass(value):
            # Frozen dataclass methods close over their own class. The class's
            # generated and authored methods are fingerprinted independently.
            return ["dataclass_type_reference", reference]
        if reference == "dataclasses.FrozenInstanceError":
            return ["stdlib_type_reference", reference]
    if isinstance(value, (types.BuiltinFunctionType, types.BuiltinMethodType)):
        return [
            "builtin_reference",
            f"{value.__module__}.{value.__qualname__}",
        ]
    if isinstance(value, types.ModuleType):
        return ["module_reference", value.__name__]
    if isinstance(value, Enum):
        child = _constant_payload(
            value.value,
            seen,
            unsupported=unsupported,
            path=f"{path}.value",
        )
        if child is _UNSUPPORTED:
            return _UNSUPPORTED
        return ["enum", f"{value_type.__module__}.{value_type.__qualname__}", child]
    if isinstance(value, Path):
        relative = relative_to_repo(value)
        if relative and not Path(relative).is_absolute():
            return ["repo_path", relative]
        _record_unsupported(
            unsupported,
            path=path,
            value=value,
            reason="path_outside_repository",
        )
        return _UNSUPPORTED

    object_id = id(value)
    if object_id in seen:
        _record_unsupported(
            unsupported,
            path=path,
            value=value,
            reason="recursive_reference",
        )
        return _UNSUPPORTED
    seen.add(object_id)
    try:
        if isinstance(value, types.FunctionType):
            closure_values = []
            for cell in value.__closure__ or ():
                try:
                    closure_values.append(cell.cell_contents)
                except ValueError:
                    closure_values.append(["empty_closure_cell"])
            state_payload = _constant_payload(
                {
                    "defaults": value.__defaults__,
                    "kwdefaults": value.__kwdefaults__,
                    "closure": tuple(closure_values),
                },
                seen,
                unsupported=unsupported,
                path=f"{path}.function_state",
            )
            if state_payload is _UNSUPPORTED:
                return _UNSUPPORTED
            code_hash = _sha256_bytes(
                marshal.dumps(_normalized_code_object(value.__code__))
            )
            return [
                "python_function",
                value.__module__,
                value.__qualname__,
                code_hash,
                state_payload,
            ]
        if isinstance(value, Mapping):
            pairs = []
            complete = True
            for key, child_value in value.items():
                key_payload = _constant_payload(
                    key,
                    seen,
                    unsupported=unsupported,
                    path=f"{path}.<key>",
                )
                key_label = (
                    _canonical_json(key_payload)
                    if key_payload is not _UNSUPPORTED
                    else "<unsupported-key>"
                )
                value_payload = _constant_payload(
                    child_value,
                    seen,
                    unsupported=unsupported,
                    path=f"{path}[{key_label}]",
                )
                if key_payload is _UNSUPPORTED or value_payload is _UNSUPPORTED:
                    complete = False
                else:
                    pairs.append([key_payload, value_payload])
            if not complete:
                return _UNSUPPORTED
            pairs.sort(key=lambda pair: _canonical_json(pair[0]))
            return ["mapping", pairs]
        if value_type in {tuple, list}:
            children = []
            complete = True
            for index, child_value in enumerate(value):
                child = _constant_payload(
                    child_value,
                    seen,
                    unsupported=unsupported,
                    path=f"{path}[{index}]",
                )
                if child is _UNSUPPORTED:
                    complete = False
                else:
                    children.append(child)
            if not complete:
                return _UNSUPPORTED
            return [value_type.__name__, children]
        if value_type in {set, frozenset}:
            children = []
            complete = True
            for child_value in value:
                child = _constant_payload(
                    child_value,
                    seen,
                    unsupported=unsupported,
                    path=f"{path}.<member>",
                )
                if child is _UNSUPPORTED:
                    complete = False
                else:
                    children.append(child)
            if not complete:
                return _UNSUPPORTED
            children.sort(key=_canonical_json)
            return [value_type.__name__, children]
        if is_dataclass(value) and not isinstance(value, type):
            children = []
            complete = True
            for field in fields(value):
                child = _constant_payload(
                    getattr(value, field.name),
                    seen,
                    unsupported=unsupported,
                    path=f"{path}.{field.name}",
                )
                if child is _UNSUPPORTED:
                    complete = False
                else:
                    children.append([field.name, child])
            if not complete:
                return _UNSUPPORTED
            return ["dataclass", f"{value_type.__module__}.{value_type.__qualname__}", children]
        _record_unsupported(unsupported, path=path, value=value)
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
    parts = {}
    all_unsupported = []
    for key, value in state.items():
        unsupported = []
        child = _constant_payload(
            value,
            unsupported=unsupported,
            path=f"function_state.{key}",
        )
        normalized = _normalized_unsupported(unsupported)
        all_unsupported.extend(normalized)
        parts[key] = (
            child
            if child is not _UNSUPPORTED
            else ["unsupported_function_state", normalized]
        )
    return {
        "payload": ["function_state", parts],
        "unsupported_entries": _normalized_unsupported(all_unsupported),
    }


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


def _module_constants(
    namespace: dict,
    module_name: str,
) -> tuple[list[tuple[str, str]], list[dict], list[dict]]:
    """Canonical module-level behavior constants.

    ``model_constants.py`` defines no functions at all, so a bytecode-only
    witness would report an empty fingerprint for it and a changed constant
    would move nothing.  Containers are admitted only for conventional
    uppercase constants; this captures TTL maps, feature contracts and market
    registries without binding mutable runtime caches.  Dunders are excluded
    deliberately because their values are process/path metadata.
    """
    found: list[tuple[str, str]] = []
    unsupported_entries: list[dict] = []
    excluded_entries: list[dict] = []
    for name in sorted(namespace):
        if name.startswith("__") and name.endswith("__"):
            continue
        value = namespace[name]
        is_scalar = type(value) in {bool, int, float, str, bytes, type(None)}
        if not is_scalar and name.upper() != name:
            continue
        exclusion_reason = EXPLICIT_NON_BEHAVIOR_MODULE_CONSTANTS.get(
            (module_name, name)
        )
        if exclusion_reason:
            found.append(
                (
                    name,
                    _canonical_json(
                        ["explicit_non_behavior_constant", exclusion_reason]
                    ),
                )
            )
            excluded_entries.append(
                {
                    "owner": f"constant:{name}",
                    "reason": exclusion_reason,
                    "type": _type_name(value),
                }
            )
            continue
        if type(value) is object:
            payload = ["named_object_sentinel", name]
            unsupported = []
        else:
            unsupported = []
            payload = _constant_payload(
                value,
                unsupported=unsupported,
                path=f"module_constant.{name}",
            )
        normalized = _normalized_unsupported(unsupported)
        if payload is _UNSUPPORTED:
            marker = ["unsupported_module_constant", normalized]
            found.append((name, _canonical_json(marker)))
            unsupported_entries.extend(
                {"owner": f"constant:{name}", **entry} for entry in normalized
            )
        else:
            found.append((name, _canonical_json(payload)))
    return (
        found,
        _normalized_unsupported(unsupported_entries),
        _normalized_unsupported(excluded_entries),
    )


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
            "status": FINGERPRINT_UNLOADED,
            "file": None,
            "code_units": None,
            "constants": None,
            "sha256": None,
            "unsupported_entries": [],
            "excluded_entries": [],
            "error_type": None,
        }
    namespace = dict(vars(module))
    digest = hashlib.sha256()
    units = 0
    unsupported_entries = []
    for name, code, function_state in _code_objects(namespace, module_name, set()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(marshal.dumps(_normalized_code_object(code)))
        digest.update(b"\2")
        digest.update(_canonical_json(function_state).encode("utf-8"))
        digest.update(b"\0")
        unsupported_entries.extend(
            {"owner": f"function:{name}", **entry}
            for entry in function_state["unsupported_entries"]
        )
        units += 1
    constants, constant_unsupported, excluded_entries = _module_constants(
        namespace,
        module_name,
    )
    unsupported_entries.extend(constant_unsupported)
    unsupported_entries = _normalized_unsupported(unsupported_entries)
    for name, value in constants:
        digest.update(name.encode("utf-8"))
        digest.update(b"\1")
        digest.update(value.encode("utf-8"))
        digest.update(b"\1")
    return {
        "module": module_name,
        "loaded": True,
        "status": (
            FINGERPRINT_INCOMPLETE
            if unsupported_entries
            else FINGERPRINT_COMPLETE
        ),
        "file": relative_to_repo(Path(getattr(module, "__file__", "") or "")) or None,
        "code_units": units,
        "constants": len(constants),
        "sha256": digest.hexdigest(),
        "unsupported_entries": unsupported_entries,
        "excluded_entries": excluded_entries,
        "error_type": None,
    }


def _runtime_state_fingerprint(value) -> tuple[str, bytes]:
    """Serialize already-loaded state without consulting its source file."""
    unsupported = []
    payload = _constant_payload(
        value,
        unsupported=unsupported,
        path="loaded_artifact",
    )
    if payload is _UNSUPPORTED:
        raise _UnsupportedLoadedArtifactState(
            _normalized_unsupported(unsupported)
        )
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
                    {
                        "sha256": str(descriptor["sha256"]),
                        "size": None,
                        "binding": "release_graph_unbound",
                    },
                )
    shared = graph.get("shared_components")
    if isinstance(shared, Mapping):
        for role, descriptor in shared.items():
            if isinstance(descriptor, Mapping) and descriptor.get("sha256"):
                sources.setdefault(
                    str(role),
                    {
                        "sha256": str(descriptor["sha256"]),
                        "size": None,
                        "binding": "release_graph_unbound",
                    },
                )
    return sources


def _bound_source_fingerprint(source: Mapping, value) -> tuple[str, int | None]:
    sha256 = str(source.get("sha256") or "").lower()
    if re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
        raise _InvalidLoadedSourceHash("source claim is not a SHA-256 digest")
    if (
        source.get("binding") != LOADED_SOURCE_BINDING_MARKER
        or source.get("object_id") != id(value)
    ):
        raise _UnboundLoadedSourceHash(
            "source hash is not bound to the exact materialized object"
        )
    size = source.get("size")
    if size is not None and (type(size) is not int or size < 0):
        raise _InvalidLoadedSourceHash("source size is not a non-negative integer")
    return sha256, size


def loaded_artifact_identity(model) -> dict:
    """Fingerprint estimator/postprocessor state held by ``model``.

    Canonical state is re-read on every call. Object identity is not a content
    witness: a dict or dataclass can mutate in place without changing ``id``.
    Opaque estimators may use a loader-provided source hash only when that
    record binds the exact materialized object.
    """
    from weather.model.model_constants import _UNLOADED  # local: avoid an import cycle

    values = []
    source_hashes = _loaded_artifact_source_hashes(model)
    for role, attribute in LOADED_ARTIFACT_COMPONENTS:
        value = getattr(model, attribute, _MISSING)
        state = "unloaded" if value is _MISSING or value is _UNLOADED else "loaded"
        values.append((role, attribute, value, state))
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
                    "source_claim_sha256": None,
                    "unsupported_entries": [],
                }
            )
            continue
        source = source_hashes.get(role)
        source_claim_sha256 = (
            str(source.get("sha256"))
            if isinstance(source, Mapping) and source.get("sha256")
            else None
        )
        try:
            try:
                encoding, encoded = _runtime_state_fingerprint(value)
                record = {
                    "role": role,
                    "attribute": attribute,
                    "state": state,
                    "encoding": encoding,
                    "serialized_size": len(encoded),
                    "sha256": _sha256_bytes(encoded),
                    "source_claim_sha256": source_claim_sha256,
                    "unsupported_entries": [],
                }
            except TypeError:
                if not isinstance(source, Mapping) or not source.get("sha256"):
                    raise
                sha256, size = _bound_source_fingerprint(source, value)
                record = {
                    "role": role,
                    "attribute": attribute,
                    "state": state,
                    "encoding": "loaded-source-sha256-1",
                    "serialized_size": size,
                    "sha256": sha256,
                    "source_claim_sha256": source_claim_sha256,
                    "unsupported_entries": [],
                }
        except Exception as exc:  # noqa: BLE001 - identity must not break capture
            record = {
                "role": role,
                "attribute": attribute,
                "state": "fingerprint_error",
                "encoding": None,
                "serialized_size": None,
                "sha256": None,
                "source_claim_sha256": source_claim_sha256,
                "error_type": type(exc).__name__,
                "unsupported_entries": getattr(exc, "unsupported_entries", []),
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
                    "source_claim_sha256": (
                        item.get("source_claim_sha256")
                        if item["state"] == "fingerprint_error"
                        else None
                    ),
                    "error_type": item.get("error_type"),
                    "unsupported_entries": item.get("unsupported_entries") or [],
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
    identity["status"] = (
        FINGERPRINT_INCOMPLETE
        if identity["components_failed"]
        else FINGERPRINT_COMPLETE
    )
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
        "status": FINGERPRINT_UNLOADED,
        "file": None,
        "code_units": None,
        "constants": None,
        "sha256": None,
        "unsupported_entries": [],
        "excluded_entries": [],
        "error_type": None,
    }


def _fingerprint_error_record(module_name: str, exc: Exception) -> dict:
    return {
        "module": module_name,
        "loaded": module_name in sys.modules,
        "status": FINGERPRINT_ERROR,
        "file": None,
        "code_units": None,
        "constants": None,
        "sha256": None,
        "unsupported_entries": [],
        "excluded_entries": [],
        "error_type": type(exc).__name__,
    }


def loaded_module_fingerprints(module_names: Iterable[str]) -> list[dict]:
    """Return deterministic in-memory fingerprints for exact loaded modules.

    Names are normalized to a sorted unique sequence so the returned rows are
    stable for a set of runtime owners.  Missing modules and fingerprint
    failures remain explicit records instead of being confused with a valid
    source hash.  Results are defensive copies and share no mutable state with
    callers or the distribution-identity cache.
    """
    names = list(module_names)
    if any(type(name) is not str or not name for name in names):
        raise ValueError("module names must be non-empty strings")

    records = []
    for module_name in sorted(set(names)):
        try:
            record = loaded_code_fingerprint(module_name)
        except Exception as exc:  # noqa: BLE001 - identity should fail closed
            record = _fingerprint_error_record(module_name, exc)
        records.append(deepcopy(record))
    return records


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
        if record is None or record.get("status") in {
            FINGERPRINT_UNLOADED,
            FINGERPRINT_ERROR,
        }:
            try:
                record = loaded_code_fingerprint(module_name)
            except Exception as exc:  # noqa: BLE001 - identity should not break capture
                record = _fingerprint_error_record(module_name, exc)
            _LOADED_MODULE_CACHE[module_name] = record
        modules.append(record)
    identity = {
        "modules": modules,
        "loaded_code_hash": _hash_payload(
            [
                {
                    "module": item["module"],
                    "status": item["status"],
                    "sha256": item["sha256"],
                    "error_type": item.get("error_type"),
                }
                for item in modules
            ]
        ),
        "modules_loaded": sum(1 for item in modules if item["loaded"]),
        "modules_expected": len(modules),
        "modules_not_loaded": [
            item["module"]
            for item in modules
            if item["status"] == FINGERPRINT_UNLOADED
        ],
        "modules_incomplete": [
            item["module"]
            for item in modules
            if item["status"] == FINGERPRINT_INCOMPLETE
        ],
        "modules_failed": [
            item["module"]
            for item in modules
            if item["status"] == FINGERPRINT_ERROR
        ],
        "marshal_version": marshal.version,
        "python_version": sys.version.split()[0],
    }
    identity["status"] = (
        FINGERPRINT_COMPLETE
        if all(item["status"] == FINGERPRINT_COMPLETE for item in modules)
        else FINGERPRINT_INCOMPLETE
    )
    return identity


def _identity_blockers(loaded_code: dict, loaded_artifacts: dict) -> list[dict]:
    blockers = []
    for record in loaded_code["modules"]:
        if record["status"] == FINGERPRINT_COMPLETE:
            continue
        blockers.append(
            {
                "scope": "loaded_code",
                "component": record["module"],
                "status": record["status"],
                "error_type": record.get("error_type"),
                "unsupported_entries": record.get("unsupported_entries") or [],
            }
        )
    for record in loaded_artifacts["components"]:
        if record["state"] != "fingerprint_error":
            continue
        blockers.append(
            {
                "scope": "loaded_artifact",
                "component": record["role"],
                "status": FINGERPRINT_ERROR,
                "error_type": record.get("error_type"),
                "unsupported_entries": record.get("unsupported_entries") or [],
            }
        )
    return sorted(blockers, key=_canonical_json)


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
    status = (
        FINGERPRINT_COMPLETE
        if loaded_code["status"] == FINGERPRINT_COMPLETE
        and loaded_artifacts["status"] == FINGERPRINT_COMPLETE
        else FINGERPRINT_INCOMPLETE
    )
    identity_blockers = _identity_blockers(loaded_code, loaded_artifacts)
    identity_payload = {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "status": status,
        "model_version": model_version,
        "market_id": market_id,
        "active_model_kind": getattr(model, "active_model_kind", None),
        "loaded_code_hash": loaded_code["loaded_code_hash"],
        "loaded_artifact_hash": loaded_artifacts["loaded_artifact_hash"],
        "runtime_dependency_hash": _RUNTIME_DEPENDENCY_IDENTITY[
            "runtime_dependency_hash"
        ],
    }
    diagnostic_identity_hash = _hash_payload(
        {**identity_payload, "identity_blockers": identity_blockers}
    )
    authoritative_identity_hash = (
        _hash_payload(identity_payload)
        if status == FINGERPRINT_COMPLETE
        else None
    )
    return {
        **identity_payload,
        # Legacy diagnostic names: these describe the import-time/disk trees,
        # not the authoritative process identity under v0.3.
        "code_hash": code_hash,
        "artifact_hash": disk_artifact_hash,
        "identity_hash": authoritative_identity_hash,
        "diagnostic_identity_hash": diagnostic_identity_hash,
        "identity_blockers": identity_blockers,
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
            "modules_incomplete": loaded_code["modules_incomplete"],
            "modules_failed": loaded_code["modules_failed"],
            "loaded_code_status": loaded_code["status"],
            "marshal_version": loaded_code["marshal_version"],
            "python_version": loaded_code["python_version"],
            "loaded_artifacts": loaded_artifacts["components"],
            "artifact_components_loaded": loaded_artifacts["components_loaded"],
            "artifact_components_expected": loaded_artifacts["components_expected"],
            "artifact_components_unloaded": loaded_artifacts["components_unloaded"],
            "artifact_components_failed": loaded_artifacts["components_failed"],
            "loaded_artifact_status": loaded_artifacts["status"],
            "disk_artifact_hash": disk_artifact_hash,
            "runtime_dependencies": _RUNTIME_DEPENDENCY_IDENTITY,
        },
    }


def identity_hash(identity) -> str | None:
    if not isinstance(identity, dict):
        return None
    if (
        identity.get("schema_version") == IDENTITY_SCHEMA_VERSION
        and identity.get("status") != FINGERPRINT_COMPLETE
    ):
        return None
    value = identity.get("identity_hash")
    return str(value) if value else None
