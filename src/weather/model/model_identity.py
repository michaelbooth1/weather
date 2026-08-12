"""Deterministic replay identity for model distributions.

The human model version string is useful for release notes, but it is not
specific enough for replay fidelity: retraining artifacts can change while the
version label stays the same. The replay canary needs the exact distribution
identity that produced a snapshot.

Binding rules (``v0.2``, established by ``-09-75a``/``-09-76a``)
---------------------------------------------------------------

Under ``v0.1`` the code fingerprint was read **from disk at capture time**, while
the recorded ``git_commit`` was ``HEAD``. Neither describes the bytes a
long-running loop actually loaded, and a roll-free commit advances ``HEAD``
without restarting the loop, so three states could disagree at once. The
measured consequence: only 114 of 358 decision snapshots reproduced their own
recorded output, and 0 of 63 captured identities could be rebuilt from Git.

``v0.2`` binds the identity to the process instead of to the filesystem:

* ``code_hash`` is snapshotted **once, at import**, the way
  ``snapshot_store.PROCESS_RUNTIME_IDENTITY`` already does. It describes the
  tree the process started from, not the tree at capture time.
* ``loaded_code_hash`` hashes the **code objects held in memory**, never the
  filesystem, so it stays correct even if the files are edited or deleted after
  import. This is the only field that cannot drift.
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
from datetime import datetime, timezone
from pathlib import Path

from weather.artifacts import resolve_artifact_path
from weather.paths import SRC_ROOT, relative_to_repo


IDENTITY_SCHEMA_VERSION = "weather_model_replay_identity_v0.2"

# Files that can alter estimate_distribution for a fixed captured sources dict.
# Keep this list focused on pure distribution/feature/calibration code; the
# identity helper itself is intentionally excluded so report-only edits do not
# invalidate otherwise faithful captures.
DISTRIBUTION_CODE_FILES = (
    Path("weather/model/model_base.py"),
    Path("weather/model/model_climatology.py"),
    Path("weather/model/model_constants.py"),
    Path("weather/model/model_distribution.py"),
    Path("weather/model/model_features.py"),
    Path("weather/model/feature_store.py"),
    Path("weather/calibration/forecast_error_model.py"),
    Path("weather/calibration/family_secondary_artifacts.py"),
    Path("weather/calibration/probability_calibration.py"),
    Path("weather/calibration/settlement_lag_model.py"),
    Path("weather/market/market_registry.py"),
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


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_payload(payload) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(encoded)


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


def _code_objects(namespace, module_name: str, seen: set[int]) -> list[tuple[str, object]]:
    """Every code object this module defines, in a stable order.

    Only objects whose ``__module__`` is this module are included, so a
    re-exported helper is fingerprinted once, by its owner.
    """
    found: list[tuple[str, object]] = []
    for name in sorted(namespace):
        obj = namespace[name]
        if isinstance(obj, (staticmethod, classmethod)):
            obj = obj.__func__
        if isinstance(obj, property):
            for suffix, accessor in (("fget", obj.fget), ("fset", obj.fset), ("fdel", obj.fdel)):
                if isinstance(accessor, types.FunctionType):
                    found.append((f"{name}.{suffix}", accessor.__code__))
            continue
        if isinstance(obj, types.FunctionType):
            if getattr(obj, "__module__", None) == module_name:
                found.append((name, obj.__code__))
            continue
        if isinstance(obj, type):
            if getattr(obj, "__module__", None) != module_name or id(obj) in seen:
                continue
            seen.add(id(obj))
            for sub_name, code in _code_objects(dict(vars(obj)), module_name, seen):
                found.append((f"{name}.{sub_name}", code))
    return found


# Module-level values worth binding. Anything else (imported modules, arrays,
# fitted estimators) is skipped: it is either not content or already covered by
# the artifact fingerprints.
_CONSTANT_TYPES = (bool, int, float, str, bytes, type(None))


def _module_constants(namespace: dict) -> list[tuple[str, str]]:
    """Module-level primitives, so a changed threshold is not invisible.

    ``model_constants.py`` defines no functions at all, so a bytecode-only
    witness would report an empty fingerprint for it and a changed constant
    would move nothing. Dunders are excluded deliberately: ``__file__`` and
    ``__cached__`` are path-dependent, and folding them in would make the same
    code fingerprint differently in a worktree than in production.
    """
    found: list[tuple[str, str]] = []
    for name in sorted(namespace):
        if name.startswith("__") and name.endswith("__"):
            continue
        value = namespace[name]
        if isinstance(value, _CONSTANT_TYPES):
            found.append((name, repr(value)))
        elif isinstance(value, (tuple, frozenset)) and all(
            isinstance(item, _CONSTANT_TYPES) for item in value
        ):
            found.append((name, repr(value)))
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
    for name, code in _code_objects(namespace, module_name, set()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(marshal.dumps(code))
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
    these modules import lazily -- at the first capture only 7 of 11 are in
    ``sys.modules`` -- so a module still missing is retried on each call until
    it appears. Caching the whole set on the first call would freeze those four
    as "never loaded" for the life of the process.
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
    code_hash = _combined_hash(code_files)
    disk_code_hash = _combined_hash(disk_code_files)

    payload = {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "model_version": model_version,
        "market_id": market_id,
        "active_model_kind": getattr(model, "active_model_kind", None),
        "code_hash": code_hash,
        "artifact_hash": _combined_hash(artifact_files),
        "loaded_code_hash": loaded_code["loaded_code_hash"],
    }
    identity_hash = _hash_payload(payload)
    return {
        **payload,
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
        },
    }


def identity_hash(identity) -> str | None:
    if not isinstance(identity, dict):
        return None
    value = identity.get("identity_hash")
    return str(value) if value else None
