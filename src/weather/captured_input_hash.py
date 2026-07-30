"""Canonical self-hashing for persisted captured-input replay records."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from weather.release_artifacts import (
    ReleaseArtifactVerificationError,
    canonical_payload_sha256,
)


CAPTURED_INPUT_HASH_ALGORITHM = (
    "sha256-canonical-json;omit=captured_input_hash"
)
_CANONICAL_INTEGER_KEY = re.compile(r"(?:0|-?[1-9][0-9]*)")


def _restore_round_trip_key_types(value: Any, *, persisted: bool) -> Any:
    """Recover numeric mapping keys when persisted ordering proves their type.

    Captured source payloads can contain other numeric-keyed dictionaries, such
    as local-history bucket counts. ``sort_keys=True`` leaves a durable type
    witness: integer keys are emitted in numeric order, while genuine string
    keys are emitted lexicographically. Convert only when those orders differ
    and the observed order is numeric, then let canonical hashing sort again.
    """

    if isinstance(value, Mapping):
        items = list(value.items())
        keys = [key for key, _child in items]
        restore_integer_keys = bool(
            persisted
            and keys
            and all(
                isinstance(key, str) and _CANONICAL_INTEGER_KEY.fullmatch(key)
                for key in keys
            )
            and keys == sorted(keys, key=int)
            and keys != sorted(keys)
        )
        normalized: dict[Any, Any] = {}
        for raw_key, child in items:
            key = int(raw_key) if restore_integer_keys else raw_key
            if key in normalized:
                raise ReleaseArtifactVerificationError(
                    "captured-input mapping keys collide after canonicalization: "
                    f"{raw_key!r}"
                )
            normalized[key] = _restore_round_trip_key_types(
                child,
                persisted=persisted,
            )
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            _restore_round_trip_key_types(child, persisted=persisted)
            for child in value
        ]
    return value


def _typed_recorded_distribution(value: Any) -> Any:
    """Restore the integer bucket-key type lost in a JSON object round trip.

    ``SnapshotStore`` historically computed the captured-input digest while
    temperature buckets were Python integers. JSON persistence necessarily
    writes object keys as strings. Restoring only the schema-owned
    ``recorded_distribution`` bucket keys makes verification reproduce the
    writer's declared canonical digest without accepting arbitrary insertion
    order or changing unrelated string-keyed source payloads.
    """

    if not isinstance(value, Mapping):
        return value
    normalized: dict[int, Any] = {}
    for raw_key, probability in value.items():
        if isinstance(raw_key, bool):
            raise ReleaseArtifactVerificationError(
                "recorded_distribution contains a boolean bucket key"
            )
        if isinstance(raw_key, int):
            bucket = raw_key
        elif isinstance(raw_key, str) and _CANONICAL_INTEGER_KEY.fullmatch(raw_key):
            bucket = int(raw_key)
        else:
            raise ReleaseArtifactVerificationError(
                "recorded_distribution contains a non-canonical integer bucket key: "
                f"{raw_key!r}"
            )
        if bucket in normalized:
            raise ReleaseArtifactVerificationError(
                "recorded_distribution bucket keys collide after canonicalization: "
                f"{raw_key!r}"
            )
        normalized[bucket] = probability
    return normalized


def captured_input_payload_sha256(
    payload: Mapping[str, Any],
    *,
    persisted: bool,
) -> str:
    """Return the round-trip-stable digest declared by captured-input records."""

    normalized = dict(payload)
    normalized.pop("captured_input_hash", None)
    if "recorded_distribution" in normalized:
        normalized["recorded_distribution"] = _typed_recorded_distribution(
            normalized["recorded_distribution"]
        )
    return canonical_payload_sha256(
        _restore_round_trip_key_types(normalized, persisted=persisted)
    )
