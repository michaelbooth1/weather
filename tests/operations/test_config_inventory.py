import json
from datetime import datetime, timezone

from weather.operations.config_inventory import build_config_inventory, render_report


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_config_inventory_classifies_stale_location_events_and_deprecated_market_shell(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    write_json(
        config / "locations.json",
        {
            "schema_version": "location_registry_v0.1",
            "status": "durable_location_registry",
            "locations": [],
        },
    )
    write_json(
        config / "location_market_events.json",
        {
            "schema_version": "location_market_events_v0.1",
            "generated_at_utc": "2026-06-01T00:00:00+00:00",
            "locations": [],
        },
    )
    write_json(
        config / "markets.json",
        {
            "schema_version": "market_registry_v0.1",
            "status": "deprecated_compatibility_shell",
            "markets": [],
        },
    )
    write_json(
        config / "model_variant_registry.json",
        {"schema_version": "model_variant_registry_v0.1", "variants": []},
    )
    write_json(
        config / "supplemental_stations.json",
        {"schema_version": "supplemental_station_registry_v0.1", "sources": []},
    )
    write_json(
        config / "no_market_extra_locations.json",
        {"schema_version": "no_market_extra_location_registry_v0.1", "locations": []},
    )

    payload = build_config_inventory(
        config,
        now=datetime(2026, 6, 20, tzinfo=timezone.utc),
        generated_at_utc="2026-06-20T00:00:00+00:00",
    )

    rows = {row["path"].replace("\\", "/").split("/")[-1]: row for row in payload["configs"]}
    assert payload["schema_version"] == "config_inventory_v0.1"
    assert rows["locations.json"]["classification"] == "durable_location_registry"
    assert rows["locations.json"]["freshness"] == "NOT_REQUIRED"
    assert rows["location_market_events.json"]["classification"] == "generated_snapshot"
    assert rows["location_market_events.json"]["freshness"] == "STALE"
    assert rows["markets.json"]["classification"] == "deprecated_compatibility_shell"
    assert rows["markets.json"]["status"] == "PASS"
    assert payload["status"] == "WARN"


def test_config_inventory_flags_active_variant_data_artifact_path(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    for name, payload in {
        "locations.json": {"schema_version": "location_registry_v0.1", "locations": []},
        "location_market_events.json": {
            "schema_version": "location_market_events_v0.1",
            "generated_at_utc": "2026-06-20T00:00:00+00:00",
            "locations": [],
        },
        "markets.json": {"schema_version": "market_registry_v0.1", "status": "deprecated_compatibility_shell", "markets": []},
        "supplemental_stations.json": {"schema_version": "supplemental_station_registry_v0.1", "sources": []},
        "no_market_extra_locations.json": {"schema_version": "no_market_extra_location_registry_v0.1", "locations": []},
    }.items():
        write_json(config / name, payload)
    write_json(
        config / "model_variant_registry.json",
        {
            "schema_version": "model_variant_registry_v0.1",
            "variants": [
                {
                    "variant_id": "bad",
                    "lifecycle": "active",
                    "roles": ["candidate"],
                    "artifact_path": "data/backtest/model.pkl",
                }
            ],
        },
    )

    payload = build_config_inventory(
        config,
        now=datetime(2026, 6, 20, tzinfo=timezone.utc),
        generated_at_utc="2026-06-20T00:00:00+00:00",
    )
    report = render_report(payload)

    variant = next(row for row in payload["configs"] if row["path"].endswith("model_variant_registry.json"))
    assert variant["status"] == "WARN"
    assert "active variant artifact_path" in variant["issues"][0]["issue"]
    assert "Config Inventory" in report


def test_config_inventory_accepts_archived_no_market_extra_locations(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    for name, payload in {
        "locations.json": {"schema_version": "location_registry_v0.1", "locations": []},
        "location_market_events.json": {
            "schema_version": "location_market_events_v0.1",
            "generated_at_utc": "2026-06-20T00:00:00+00:00",
            "locations": [],
        },
        "markets.json": {"schema_version": "market_registry_v0.1", "status": "deprecated_compatibility_shell", "markets": []},
        "model_variant_registry.json": {"schema_version": "model_variant_registry_v0.1", "variants": []},
        "supplemental_stations.json": {"schema_version": "supplemental_station_registry_v0.1", "sources": []},
    }.items():
        write_json(config / name, payload)
    write_json(
        config / "no_market_extra_locations.json",
        {
            "schema_version": "no_market_extra_location_registry_v0.1",
            "locations": [
                {
                    "location_id": "phoenix-sky-harbor",
                    "diagnostic_only": True,
                    "archive_reason": "No backfilled evidence yet; retained only in archived_locations.",
                }
            ],
        },
    )

    payload = build_config_inventory(
        config,
        now=datetime(2026, 6, 20, tzinfo=timezone.utc),
        generated_at_utc="2026-06-20T00:00:00+00:00",
    )

    no_market = next(row for row in payload["configs"] if row["path"].endswith("no_market_extra_locations.json"))
    assert no_market["status"] == "PASS"
