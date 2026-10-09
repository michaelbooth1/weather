"""Read a location registry and event metadata as one immutable generation.

The metadata envelope is the publication point. A separate registry file is a
compatibility projection and may lag a committed envelope after interruption.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from weather.schema_registry import schema_version


GENERATION_FIELD = "location_config_generation"
GENERATION_ID_FIELD = "generation_id"
GENERATION_SCHEMA_VERSION = schema_version("location_config_generation")
GENERATION_BOUND = "GENERATION_BOUND"
LEGACY_UNBOUND = "LEGACY_UNBOUND"
_GENERATION_KEYS = {
    "schema_version", "generation_id", "registry_source_identity",
    "source_input_registry_sha256", "registry_sha256", "registry_bytes_base64",
    "event_metadata_sha256",
}


class LocationConfigError(ValueError):
    """A declared generation is incomplete, corrupt or bound to another input."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False,
                       allow_nan=False) + "\n").encode("utf-8")


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LocationConfigError(f"duplicate location-config JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise LocationConfigError(f"non-finite location-config JSON value: {value}")


def _finite_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise LocationConfigError(f"non-finite location-config JSON value: {value}")
    return parsed


def parse_json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                             parse_constant=_invalid_constant, parse_float=_finite_float)
    except (UnicodeError, ValueError) as exc:
        raise LocationConfigError(f"{label} is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise LocationConfigError(f"{label} must be a JSON object")
    return payload


def registry_source_identity(locations_path: str | Path,
                             event_metadata_path: str | Path) -> str:
    """Record a portable relative identity; readers never follow this value."""
    try:
        relative = os.path.relpath(Path(locations_path).resolve(),
                                   Path(event_metadata_path).resolve().parent)
    except ValueError as exc:
        raise LocationConfigError("registry and metadata must share a path volume") from exc
    return relative.replace("\\", "/")


def _is_sha256(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def _valid_source_identity(value) -> bool:
    return (isinstance(value, str) and bool(value) and "\\" not in value
            and not PurePosixPath(value).is_absolute()
            and not PureWindowsPath(value).drive
            and value not in {".", ".."}
            and PurePosixPath(value).as_posix() == value)


def _event_payload(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items()
            if key not in {GENERATION_FIELD, GENERATION_ID_FIELD}}


@dataclass(frozen=True)
class LocationConfigPair:
    registry_bytes: bytes
    metadata_bytes: bytes
    binding_status: str
    generation_id: str | None = None
    registry_source_identity: str | None = None

    @property
    def locations_payload(self) -> dict[str, Any]:
        return parse_json_object(self.registry_bytes, label="location registry")

    @property
    def event_metadata_payload(self) -> dict[str, Any]:
        return parse_json_object(self.metadata_bytes, label="event metadata")

    def identity(self) -> dict[str, Any]:
        return {
            "binding_status": self.binding_status,
            "generation_id": self.generation_id,
            "registry_source_identity": self.registry_source_identity,
            "registry_sha256": sha256_bytes(self.registry_bytes),
            "event_metadata_file_sha256": sha256_bytes(self.metadata_bytes),
        }


def _pair_from_metadata(metadata_bytes: bytes, *,
                        expected_source_identity: str | None = None) -> LocationConfigPair | None:
    metadata = parse_json_object(metadata_bytes, label="event metadata")
    if GENERATION_FIELD not in metadata and GENERATION_ID_FIELD not in metadata:
        return None
    generation = metadata.get(GENERATION_FIELD)
    if not isinstance(generation, dict) or set(generation) != _GENERATION_KEYS:
        raise LocationConfigError("location config generation is incomplete")
    if generation.get("schema_version") != GENERATION_SCHEMA_VERSION:
        raise LocationConfigError("location config generation schema is unsupported")
    source = generation.get("registry_source_identity")
    if not _valid_source_identity(source):
        raise LocationConfigError("location config registry source identity is invalid")
    if expected_source_identity is not None and source != expected_source_identity:
        raise LocationConfigError("location config registry source identity mismatch")
    for field in ("generation_id", "registry_sha256", "source_input_registry_sha256",
                  "event_metadata_sha256"):
        if not _is_sha256(generation.get(field)):
            raise LocationConfigError(f"location config generation has invalid {field}")
    try:
        registry_bytes = base64.b64decode(generation["registry_bytes_base64"], validate=True)
    except (ValueError, TypeError) as exc:
        raise LocationConfigError("location config embedded registry bytes are invalid") from exc
    parse_json_object(registry_bytes, label="embedded location registry")
    if sha256_bytes(registry_bytes) != generation["registry_sha256"]:
        raise LocationConfigError("location config registry hash mismatch")
    if sha256_bytes(_canonical_bytes(_event_payload(metadata))) != generation["event_metadata_sha256"]:
        raise LocationConfigError("location config event metadata hash mismatch")
    expected_id = sha256_bytes(_canonical_bytes({
        key: value for key, value in generation.items() if key != GENERATION_ID_FIELD
    }))
    if generation["generation_id"] != expected_id or metadata.get(GENERATION_ID_FIELD) != expected_id:
        raise LocationConfigError("location config generation identity mismatch")
    return LocationConfigPair(registry_bytes, metadata_bytes, GENERATION_BOUND, expected_id, source)


def validate_generation_metadata_bytes(
    metadata_bytes: bytes, *, expected_source_identity: str | None = None,
) -> LocationConfigPair | None:
    """Validate one captured envelope without opening its registry source path."""
    return _pair_from_metadata(
        metadata_bytes, expected_source_identity=expected_source_identity,
    )


def build_generation_metadata(registry_bytes: bytes, event_payload: Mapping[str, Any], *,
                              source_input_registry_bytes: bytes,
                              source_identity: str) -> dict[str, Any]:
    parse_json_object(registry_bytes, label="location registry")
    parse_json_object(source_input_registry_bytes, label="source location registry")
    if not _valid_source_identity(source_identity):
        raise LocationConfigError("location config registry source identity is invalid")
    if GENERATION_FIELD in event_payload or GENERATION_ID_FIELD in event_payload:
        raise LocationConfigError("new event payload already declares a generation")
    generation = {
        "schema_version": GENERATION_SCHEMA_VERSION,
        "registry_source_identity": source_identity,
        "source_input_registry_sha256": sha256_bytes(source_input_registry_bytes),
        "registry_sha256": sha256_bytes(registry_bytes),
        "registry_bytes_base64": base64.b64encode(registry_bytes).decode("ascii"),
        "event_metadata_sha256": sha256_bytes(_canonical_bytes(event_payload)),
    }
    generation["generation_id"] = sha256_bytes(_canonical_bytes(generation))
    return {**event_payload, GENERATION_ID_FIELD: generation["generation_id"],
            GENERATION_FIELD: generation}


def validate_pair_bytes(registry_bytes: bytes, metadata_bytes: bytes, *,
                        expected_source_identity: str | None = None) -> LocationConfigPair:
    """Verify captured/frozen buffers without reopening or following source paths."""
    parse_json_object(registry_bytes, label="location registry")
    bound = _pair_from_metadata(metadata_bytes, expected_source_identity=expected_source_identity)
    if bound is None:
        return LocationConfigPair(registry_bytes, metadata_bytes, LEGACY_UNBOUND)
    if registry_bytes != bound.registry_bytes:
        raise LocationConfigError("location config frozen registry differs from embedded generation")
    return bound


def read_location_config_pair(locations_path: str | Path, event_metadata_path: str | Path, *,
                              allow_missing_legacy: bool = False) -> LocationConfigPair:
    """Bound reads use one buffer; legacy reads recheck metadata across migration."""
    metadata_path = Path(event_metadata_path)
    try:
        metadata_bytes = metadata_path.read_bytes()
    except FileNotFoundError:
        if not allow_missing_legacy:
            raise
        metadata_bytes = None
    source_identity = registry_source_identity(locations_path, metadata_path)
    bound = _pair_from_metadata(
        metadata_bytes if metadata_bytes is not None else b"{}",
        expected_source_identity=source_identity,
    )
    if bound is not None:
        return bound
    try:
        registry_bytes = Path(locations_path).read_bytes()
    except FileNotFoundError:
        if not allow_missing_legacy:
            raise
        registry_bytes = b"{}"
    try:
        latest_metadata_bytes = metadata_path.read_bytes()
    except FileNotFoundError:
        latest_metadata_bytes = None
    if latest_metadata_bytes != metadata_bytes:
        if latest_metadata_bytes is not None:
            latest_bound = _pair_from_metadata(
                latest_metadata_bytes, expected_source_identity=source_identity,
            )
            if latest_bound is not None:
                return latest_bound
        raise LocationConfigError("location config legacy metadata changed during read")
    return validate_pair_bytes(
        registry_bytes, metadata_bytes if metadata_bytes is not None else b"{}",
    )


def verify_frozen_config_pair(root: Path, roles: Mapping[str, Mapping[str, Any]]) -> LocationConfigPair:
    """Rehash the exact buffers against trusted outer roles before cross-binding."""
    captured = {}
    for role in ("locations_config", "location_market_events_config"):
        row = roles[role]
        path = root / str(row["path"])
        if path.is_symlink():
            raise LocationConfigError(f"frozen location config role is a symlink: {role}")
        raw = path.read_bytes()
        if sha256_bytes(raw) != row.get("sha256") or len(raw) != row.get("bytes"):
            raise LocationConfigError(f"frozen location config role hash mismatch: {role}")
        captured[role] = raw
    return validate_pair_bytes(captured["locations_config"],
                               captured["location_market_events_config"])
