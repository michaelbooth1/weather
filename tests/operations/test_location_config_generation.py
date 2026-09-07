"""Interrupted refreshes cannot expose mixed registry/event generations."""

from pathlib import Path

import pytest

from weather.market.location_config import (
    GENERATION_BOUND, GENERATION_FIELD, LEGACY_UNBOUND, LocationConfigError,
    json_bytes, read_location_config_pair,
)
from weather.operations import location_config_refresh as refresh
from weather.operations.config_inventory import build_config_inventory, render_report


def _inputs(tmp_path):
    locations = tmp_path / "locations.json"
    metadata = tmp_path / "location_market_events.json"
    raw = '\ufeff{\r\n "locations": [{"id":"fixture-city","city":"Québec","polymarket": {"event_slug_prefix":"highest-temperature-in-fixture-city-on"}}]\r\n}\r\n'.encode("utf-8")
    locations.write_bytes(raw)
    metadata.write_bytes(b'{"locations":[],"marker":"legacy"}')
    return locations, metadata, raw


def _prepare(locations, metadata, *, marker="1", metadata_only=False):
    return refresh.prepare_refresh(
        locations_path=locations, event_metadata_path=metadata,
        events=[{"id": marker, "slug": "highest-temperature-in-fixture-city-on-january-1-2026",
                 "markets": []}],
        generated_at_utc="2026-01-01T00:00:00+00:00",
        metadata_only=metadata_only,
    )


@pytest.mark.parametrize("metadata_only", [False, True])
def test_commit_binds_exact_output_and_metadata_only_preserves_input(tmp_path, metadata_only):
    locations, metadata, original = _inputs(tmp_path)
    prepared = _prepare(locations, metadata, metadata_only=metadata_only)
    assert locations.read_bytes() == original  # Preparation has no file side effects.
    pair = refresh.publish_refresh(prepared)
    observed = read_location_config_pair(locations, metadata)
    assert observed == pair
    assert locations.read_bytes() == pair.registry_bytes
    assert pair.binding_status == GENERATION_BOUND
    if metadata_only:
        assert pair.registry_bytes == original
    else:
        assert pair.registry_bytes != original
        assert pair.locations_payload["event_metadata"]["path"] == "location_market_events.json"
        assert str(tmp_path) not in pair.registry_bytes.decode("utf-8")
    assert pair.event_metadata_payload["schema_version"] == "location_market_events_v0.1"
    assert pair.event_metadata_payload["locations"][0]["active_events"][0]["event_id"] == "1"


@pytest.mark.parametrize("had_generation", [False, True])
def test_metadata_replace_failure_retains_the_previous_complete_pair(tmp_path, monkeypatch, had_generation):
    locations, metadata, _ = _inputs(tmp_path)
    if had_generation:
        refresh.publish_refresh(_prepare(locations, metadata, marker="previous", metadata_only=True))
    previous_registry, previous_metadata = locations.read_bytes(), metadata.read_bytes()
    prepared = _prepare(locations, metadata)
    original_replace = Path.replace

    def interrupted(path, destination):
        if Path(destination) == metadata:
            raise OSError("fixture metadata publication interrupted")
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", interrupted)
    with pytest.raises(OSError, match="metadata publication interrupted"):
        refresh.publish_refresh(prepared)
    assert locations.read_bytes() == previous_registry
    assert metadata.read_bytes() == previous_metadata
    previous = read_location_config_pair(locations, metadata)
    assert previous.binding_status == (GENERATION_BOUND if had_generation else LEGACY_UNBOUND)
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize("had_generation", [False, True])
def test_projection_failure_keeps_new_complete_generation_even_on_first_migration(
    tmp_path, monkeypatch, had_generation,
):
    locations, metadata, original = _inputs(tmp_path)
    if had_generation:
        refresh.publish_refresh(_prepare(locations, metadata, marker="previous", metadata_only=True))
    prepared = _prepare(locations, metadata, marker="new")
    original_replace = Path.replace

    def interrupted(path, destination):
        if Path(destination) == locations:
            raise OSError("fixture projection publication interrupted")
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", interrupted)
    with pytest.raises(OSError, match="projection publication interrupted"):
        refresh.publish_refresh(prepared)
    assert locations.read_bytes() == original
    pair = read_location_config_pair(locations, metadata)
    assert pair == prepared.pair
    assert pair.registry_bytes != original
    assert pair.event_metadata_payload["locations"][0]["active_events"][0]["event_id"] == "new"
    inventory = build_config_inventory(tmp_path)
    assert inventory["location_config_pair"]["binding_status"] == GENERATION_BOUND
    assert inventory["location_config_pair"]["projection_status"] == "DRIFT"
    assert inventory["location_config_pair"]["status"] == "WARN"
    assert "DRIFT" in render_report(inventory)
    assert not list(tmp_path.glob(".*.tmp"))


def test_stale_competing_producer_cannot_overwrite_a_committed_generation(tmp_path):
    locations, metadata, _ = _inputs(tmp_path)
    first = _prepare(locations, metadata, marker="first", metadata_only=True)
    stale = _prepare(locations, metadata, marker="stale", metadata_only=True)
    refresh.publish_refresh(first)
    with pytest.raises(ValueError, match="metadata changed"):
        refresh.publish_refresh(stale)
    assert read_location_config_pair(locations, metadata) == first.pair


def test_source_edit_during_fetch_is_not_lost(tmp_path, monkeypatch):
    locations, metadata, _ = _inputs(tmp_path)
    previous_metadata = metadata.read_bytes()
    edited = b'{"locations":[{"id":"manual-edit"}]}'

    def fetch():
        locations.write_bytes(edited)
        return [], []

    monkeypatch.setattr(refresh, "fetch_gamma_events", fetch)
    prepared = refresh.prepare_refresh(locations_path=locations, event_metadata_path=metadata)
    with pytest.raises(ValueError, match="source registry changed"):
        refresh.publish_refresh(prepared)
    assert locations.read_bytes() == edited
    assert metadata.read_bytes() == previous_metadata


def test_commit_rechecks_inputs_and_replaces_files_only_inside_transaction(tmp_path, monkeypatch):
    from contextlib import contextmanager

    locations, metadata, _ = _inputs(tmp_path)
    prepared = _prepare(locations, metadata)
    held = False
    observed = []
    original_lock, original_read, original_write = (
        refresh.lock_path_transaction, Path.read_bytes, refresh._write_bytes_atomic,
    )

    @contextmanager
    def locked(path):
        nonlocal held
        with original_lock(path):
            held = True
            try:
                yield
            finally:
                held = False

    def read(path):
        assert held
        observed.append(("read", path))
        return original_read(path)

    def write(path, raw):
        assert held
        observed.append(("write", path))
        return original_write(path, raw)

    monkeypatch.setattr(refresh, "lock_path_transaction", locked)
    monkeypatch.setattr(Path, "read_bytes", read)
    monkeypatch.setattr(refresh, "_write_bytes_atomic", write)
    refresh.publish_refresh(prepared)
    assert observed == [
        ("read", locations), ("read", metadata),
        ("write", metadata), ("read", locations), ("write", locations),
    ]


def test_flush_failure_cleans_temporary_file_and_preserves_previous_metadata(tmp_path, monkeypatch):
    locations, metadata, _ = _inputs(tmp_path)
    prepared = _prepare(locations, metadata)
    previous = metadata.read_bytes()

    def interrupted(_descriptor):
        raise OSError("fixture fsync failed")

    monkeypatch.setattr(refresh.os, "fsync", interrupted)
    with pytest.raises(OSError, match="fsync failed"):
        refresh.publish_refresh(prepared)
    assert metadata.read_bytes() == previous
    assert not list(tmp_path.glob(".*.tmp"))


def test_invalid_generation_reports_inventory_warning_and_paired_consumers_refuse(tmp_path):
    from weather.operations.event_metadata_validation import build_validation_payload
    from weather.reporting.source_gates.source_family_inventory import market_expansion_scorecard

    locations, metadata, _ = _inputs(tmp_path)
    prepared = _prepare(locations, metadata)
    damaged = prepared.pair.event_metadata_payload
    damaged[GENERATION_FIELD].pop("registry_sha256")
    metadata.write_bytes(json_bytes(damaged))
    inventory = build_config_inventory(tmp_path)
    assert inventory["location_config_pair"]["binding_status"] == "INVALID"
    assert inventory["status"] == "WARN"
    assert "invalid" in render_report(inventory)
    with pytest.raises(LocationConfigError, match="incomplete"):
        market_expansion_scorecard(locations, metadata)
    validation = build_validation_payload(
        locations_path=locations, event_metadata_path=metadata,
        markets=["nyc"], target_date="2026-01-01", fetch_live=False,
    )
    assert validation["status"] == "BLOCK"
    assert validation["location_config_pair"]["binding_status"] == "INVALID"
    assert validation["market_rows"][0]["first_issue"]["code"] == "location_config_generation_invalid"


def test_paired_consumers_use_embedded_registry_when_projection_drifts(tmp_path):
    from weather.operations.event_metadata_validation import build_validation_payload
    from weather.reporting.source_gates.source_family_inventory import market_expansion_scorecard

    locations, metadata, _ = _inputs(tmp_path)
    pair = refresh.publish_refresh(_prepare(locations, metadata, metadata_only=True))
    locations.write_bytes(b'{"locations":[{"id":"wrong-projection"}]}')
    scorecard = market_expansion_scorecard(locations, metadata)
    assert [row["location_id"] for row in scorecard["rows"]] == ["fixture-city"]
    assert scorecard["rows"][0]["checks"]["active_or_recent_event"]
    assert scorecard["location_config_pair"] == pair.identity()
    validation = build_validation_payload(
        locations_path=locations, event_metadata_path=metadata,
        markets=["nyc"], target_date="2026-01-01", fetch_live=False,
    )
    assert validation["location_config_pair"] == pair.identity()
    assert validation["status"] == "BLOCK"  # Config binding grants no event qualification.


def test_in_memory_legacy_validation_does_not_read_default_paths(monkeypatch):
    from weather.operations.event_metadata_validation import build_validation_payload

    def forbidden(_path):
        raise AssertionError("in-memory validation opened a config file")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    payload = build_validation_payload(
        locations_payload={"locations": []}, event_metadata_payload={"locations": []},
        markets=["nyc"], target_date="2026-01-01", fetch_live=False,
    )
    assert payload["location_config_pair"]["binding_status"] == LEGACY_UNBOUND


@pytest.mark.parametrize("exhausted", [False, True])
def test_windows_permission_retry_reuses_staged_bytes_and_cleans_exhaustion(
    tmp_path, monkeypatch, exhausted,
):
    locations, metadata, original_registry = _inputs(tmp_path)
    previous_metadata = metadata.read_bytes()
    prepared = _prepare(locations, metadata, metadata_only=True)
    original_replace = Path.replace
    attempts, sleeps = [], []

    def sharing_conflict(path, destination):
        attempts.append((path, Path(destination), path.read_bytes()))
        if exhausted or len(attempts) < 3:
            raise PermissionError("fixture Windows sharing conflict")
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", sharing_conflict)
    monkeypatch.setattr(refresh.time, "sleep", sleeps.append)
    if exhausted:
        with pytest.raises(PermissionError, match="sharing conflict"):
            refresh.publish_refresh(prepared)
        assert len(attempts) == refresh.ATOMIC_REPLACE_ATTEMPTS
        assert metadata.read_bytes() == previous_metadata
    else:
        refresh.publish_refresh(prepared)
        assert len(attempts) == 3
        assert read_location_config_pair(locations, metadata) == prepared.pair
    assert sleeps == [refresh.ATOMIC_REPLACE_RETRY_SECONDS] * (len(attempts) - 1)
    assert len({row[0] for row in attempts}) == 1
    assert all(row[1] == metadata and row[2] == prepared.pair.metadata_bytes for row in attempts)
    assert locations.read_bytes() == original_registry
    assert not list(tmp_path.glob(".*.tmp"))


def test_metadata_only_capture_and_economics_readers_accept_additive_envelope(tmp_path):
    from weather.market.execution_tape_capture import load_market_day_seeds
    from weather.market.exchange_economics import _event_rows_for_global_snapshot
    from weather.market.location_config import build_generation_metadata
    from weather.market.market_config import config_for_date

    target = "2026-01-01"
    slug = config_for_date(target, "nyc").event_slug
    event_payload = {
        "schema_version": "location_market_events_v0.1",
        "generated_at_utc": "2026-01-01T18:00:00+00:00",
        "locations": [{
            "location_id": "nyc", "active_events": [{
                "event_date": target, "event_slug": slug,
                "markets": [{
                    "condition_id": f"0x{1:064x}", "active": True, "closed": False,
                    "outcomes": [
                        {"name": "Yes", "token_id": "101"},
                        {"name": "No", "token_id": "102"},
                    ],
                }],
            }],
        }],
    }
    raw = b'{"locations":[{"id":"nyc"}]}'
    bound = build_generation_metadata(
        raw, event_payload, source_input_registry_bytes=raw,
        source_identity="locations.json",
    )
    path = tmp_path / "events.json"
    path.write_bytes(json_bytes(bound))
    seeds = load_market_day_seeds(
        path, markets="nyc", target_date=target, now="2026-01-01T19:00:00+00:00",
    )
    assert len(seeds) == 1
    assert seeds[0].event_slug == slug
    assert seeds[0].asset_ids == ("101", "102")
    baseline = _event_rows_for_global_snapshot(event_payload, target)
    assert baseline[0]
    assert _event_rows_for_global_snapshot(bound, target) == baseline


def test_registry_edit_after_envelope_commit_is_preserved(tmp_path, monkeypatch):
    locations, metadata, _ = _inputs(tmp_path)
    prepared = _prepare(locations, metadata)
    edited = b'{"locations":[{"id":"operator-edit-after-commit"}]}'
    original_write = refresh._write_bytes_atomic
    writes = []

    def write_then_edit(path, raw):
        writes.append(path)
        result = original_write(path, raw)
        if path == metadata:
            locations.write_bytes(edited)
        return result

    monkeypatch.setattr(refresh, "_write_bytes_atomic", write_then_edit)
    with pytest.raises(ValueError, match="changed after metadata publication"):
        refresh.publish_refresh(prepared)
    assert writes == [metadata]
    assert locations.read_bytes() == edited
    assert read_location_config_pair(locations, metadata) == prepared.pair
