"""Generation readers preserve exact bytes and reject incomplete bindings."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from weather.market.location_config import (
    GENERATION_BOUND, GENERATION_FIELD, LEGACY_UNBOUND, LocationConfigError,
    build_generation_metadata, json_bytes, parse_json_object,
    read_location_config_pair, registry_source_identity, sha256_bytes,
    validate_pair_bytes, verify_frozen_config_pair,
)


def _metadata(raw, *, identity="locations.json", marker="A"):
    return build_generation_metadata(
        raw, {"schema_version": "location_market_events_v0.1",
              "locations": [], "marker": marker},
        source_input_registry_bytes=raw, source_identity=identity,
    )


def test_exact_registry_bytes_and_immutable_captured_payloads(tmp_path):
    raw = '\ufeff{\r\n  "locations": [{"id": "québec"}]\r\n}\r\n'.encode("utf-8")
    metadata = json_bytes(_metadata(raw))
    pair = validate_pair_bytes(raw, metadata)
    assert pair.binding_status == GENERATION_BOUND
    assert pair.registry_bytes == raw
    assert pair.metadata_bytes == metadata
    assert pair.locations_payload["locations"][0]["id"] == "québec"
    mutated = pair.locations_payload
    mutated["locations"].clear()
    assert len(pair.locations_payload["locations"]) == 1
    with pytest.raises(FrozenInstanceError):
        pair.registry_bytes = b"{}"
    assert pair.identity()["registry_sha256"] == sha256_bytes(raw)


def test_legacy_is_explicitly_unbound_and_missing_compatibility_is_opt_in(tmp_path):
    locations, metadata = tmp_path / "locations.json", tmp_path / "events.json"
    with pytest.raises(FileNotFoundError):
        read_location_config_pair(locations, metadata)
    empty = read_location_config_pair(locations, metadata, allow_missing_legacy=True)
    assert empty.binding_status == LEGACY_UNBOUND
    assert empty.locations_payload == empty.event_metadata_payload == {}
    locations.write_bytes(b'{"schema_version":"old","locations":[]}')
    metadata.write_bytes(b'{"schema_version":"also_old","locations":[]}')
    assert read_location_config_pair(locations, metadata).binding_status == LEGACY_UNBOUND


@pytest.mark.parametrize("damage", [
    "missing_envelope", "missing_root_id", "null_envelope", "missing_registry",
    "invalid_base64", "registry_hash", "source_hash", "event_hash",
    "generation_id", "event_payload", "unknown_field", "unsupported_schema",
    "absolute_source", "windows_source", "wrong_source",
])
def test_partial_or_corrupt_generation_never_falls_back_to_legacy(tmp_path, damage):
    raw = b'{"locations":[]}'
    payload = _metadata(raw)
    generation = payload[GENERATION_FIELD]
    if damage == "missing_envelope":
        payload.pop(GENERATION_FIELD)
    elif damage == "missing_root_id":
        payload.pop("generation_id")
    elif damage == "null_envelope":
        payload[GENERATION_FIELD] = None
    elif damage == "missing_registry":
        generation.pop("registry_bytes_base64")
    elif damage == "invalid_base64":
        generation["registry_bytes_base64"] = "!"
    elif damage == "registry_hash":
        generation["registry_sha256"] = "0" * 64
    elif damage == "source_hash":
        generation["source_input_registry_sha256"] = None
    elif damage == "event_hash":
        generation["event_metadata_sha256"] = "0" * 64
    elif damage == "generation_id":
        generation["generation_id"] = "0" * 64
    elif damage == "event_payload":
        payload["marker"] = "changed"
    elif damage == "unknown_field":
        generation["unrecognized"] = True
    elif damage == "unsupported_schema":
        generation["schema_version"] = "unsupported"
    elif damage == "absolute_source":
        generation["registry_source_identity"] = "/host/private/locations.json"
    elif damage == "windows_source":
        generation["registry_source_identity"] = "C:/host/private/locations.json"
    elif damage == "wrong_source":
        payload = _metadata(raw, identity="other.json")
    locations, metadata = tmp_path / "locations.json", tmp_path / "events.json"
    locations.write_bytes(raw)
    metadata.write_bytes(json_bytes(payload))
    with pytest.raises(LocationConfigError):
        read_location_config_pair(locations, metadata, allow_missing_legacy=True)


@pytest.mark.parametrize("raw", [
    b'{"locations":[],"locations":[]}', b'{"value":NaN}', b'{"value":Infinity}',
    b'{"value":1e999}', b"[]", b"{partial",
])
def test_json_decode_refuses_ambiguous_or_invalid_objects(raw):
    with pytest.raises(LocationConfigError):
        parse_json_object(raw, label="fixture")


def test_bound_reader_uses_one_captured_metadata_buffer_during_replacement(tmp_path, monkeypatch):
    locations, metadata = tmp_path / "locations.json", tmp_path / "events.json"
    raw_a, raw_b = b'{"locations":[{"id":"A"}]}', b'{"locations":[{"id":"B"}]}'
    metadata_a = json_bytes(_metadata(raw_a, marker="A"))
    metadata_b = json_bytes(_metadata(raw_b, marker="B"))
    locations.write_bytes(raw_a)
    metadata.write_bytes(metadata_a)
    original = Path.read_bytes
    calls = []

    def interleaved_read(path):
        calls.append(path)
        if path == locations:
            raise AssertionError("bound reader reopened the registry projection")
        captured = original(path)
        if path == metadata:
            metadata.write_bytes(metadata_b)
            locations.write_bytes(raw_b)
        return captured

    monkeypatch.setattr(Path, "read_bytes", interleaved_read)
    pair = read_location_config_pair(locations, metadata)
    assert calls == [metadata]
    assert pair.registry_bytes == raw_a
    assert pair.metadata_bytes == metadata_a
    assert pair.event_metadata_payload["marker"] == "A"


def test_custom_source_identity_is_portable_and_never_followed(tmp_path):
    locations = tmp_path / "registry" / "custom.json"
    metadata = tmp_path / "generated" / "events.json"
    locations.parent.mkdir()
    metadata.parent.mkdir()
    identity = registry_source_identity(locations, metadata)
    assert identity == "../registry/custom.json"
    raw = b'{"locations":[]}'
    metadata.write_bytes(json_bytes(_metadata(raw, identity=identity)))
    # A bound read succeeds without a projection and does not open the embedded path.
    pair = read_location_config_pair(locations, metadata)
    assert pair.registry_bytes == raw
    assert pair.registry_source_identity == identity
    with pytest.raises(LocationConfigError, match="source identity mismatch"):
        read_location_config_pair(tmp_path / "different.json", metadata)


def test_frozen_pair_rehashes_captured_buffers_and_checks_cross_binding(tmp_path):
    raw = b'{"locations":[{"id":"A"}]}'
    metadata = json_bytes(_metadata(raw))
    roles = {}
    for role, name, value in [
        ("locations_config", "locations.json", raw),
        ("location_market_events_config", "events.json", metadata),
    ]:
        (tmp_path / name).write_bytes(value)
        roles[role] = {"path": name, "sha256": sha256_bytes(value), "bytes": len(value)}
    assert verify_frozen_config_pair(tmp_path, roles).binding_status == GENERATION_BOUND
    changed = b'{"locations":[{"id":"B"}]}'
    (tmp_path / "locations.json").write_bytes(changed)
    with pytest.raises(LocationConfigError, match="role hash mismatch"):
        verify_frozen_config_pair(tmp_path, roles)
    roles["locations_config"].update(sha256=sha256_bytes(changed), bytes=len(changed))
    with pytest.raises(LocationConfigError, match="differs from embedded"):
        verify_frozen_config_pair(tmp_path, roles)
