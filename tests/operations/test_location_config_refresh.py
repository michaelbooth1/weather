import json

from weather.operations.location_config_refresh import (
    bootstrap_legacy_event_snapshot,
    build_location_market_events,
    durable_locations_payload,
    main,
    write_event_snapshot,
)


def test_location_config_refresh_splits_volatile_market_events_from_durable_locations():
    locations = {
        "schema_version": 1,
        "source": {"generated_at_utc": "2026-06-07T00:00:00+00:00"},
        "locations": [
            {
                "id": "atlanta",
                "city": "Atlanta",
                "polymarket": {
                    "series_slug": "atlanta-daily-weather",
                    "event_slug_prefix": "highest-temperature-in-atlanta-on",
                    "latest_event_slug": "old",
                    "active_events": [{"event_slug": "old"}],
                },
            }
        ],
    }
    events = [
        {
            "id": "123",
            "slug": "highest-temperature-in-atlanta-on-june-20-2026",
            "title": "Highest temperature in Atlanta on June 20?",
            "endDate": "2026-06-20T12:00:00Z",
            "resolutionSource": "https://example.test/KATL",
            "markets": [
                {
                    "id": "m1",
                    "conditionId": "condition-1",
                    "groupItemTitle": "80-81",
                    "outcomes": json.dumps(["Yes", "No"]),
                    "clobTokenIds": json.dumps(["yes-token", "no-token"]),
                    "enableOrderBook": True,
                    "active": True,
                    "closed": False,
                },
                {},
            ],
        }
    ]

    generated_at = "2026-06-20T20:00:00+00:00"
    event_payload = build_location_market_events(
        locations,
        events,
        generated_at_utc=generated_at,
        offsets=[0],
    )
    durable = durable_locations_payload(
        locations,
        event_metadata_path="data/location_market_events.json",
        generated_at_utc=generated_at,
    )

    event_row = event_payload["locations"][0]
    assert event_payload["schema_version"] == "location_market_events_v0.1"
    assert event_row["latest_event_slug"] == "highest-temperature-in-atlanta-on-june-20-2026"
    assert event_row["source_event_dates"] == ["2026-06-20"]
    assert event_row["active_events"][0]["market_count"] == 2
    market = event_row["active_events"][0]["markets"][0]
    assert market["condition_id"] == "condition-1"
    assert market["outcome_tokens"] == {"Yes": "yes-token", "No": "no-token"}
    assert durable["schema_version"] == "location_registry_v0.1"
    assert durable["event_metadata"]["path"] == "data/location_market_events.json"
    assert "last_refreshed_at_utc" not in durable["event_metadata"]
    assert "latest_event_slug" not in durable["locations"][0]["polymarket"]
    assert "active_events" not in durable["locations"][0]["polymarket"]


def test_location_config_refresh_payload_is_json_serializable():
    payload = build_location_market_events({"locations": []}, [], generated_at_utc="2026-06-20T00:00:00+00:00")
    json.dumps(payload)


def test_metadata_only_cli_leaves_location_registry_unchanged(tmp_path):
    locations_path = tmp_path / "locations.json"
    event_metadata_path = tmp_path / "events-out.json"
    events_path = tmp_path / "events-in.json"
    locations_path.write_text(
        json.dumps({
            "schema_version": "location_registry_v0.1",
            "locations": [{
                "id": "atlanta",
                "polymarket": {
                    "event_slug_prefix": "highest-temperature-in-atlanta-on",
                },
            }],
        }, indent=3),
        encoding="utf-8",
    )
    events_path.write_text(
        json.dumps({
            "events": [{
                "id": "123",
                "slug": "highest-temperature-in-atlanta-on-august-14-2026",
                "markets": [],
            }],
        }),
        encoding="utf-8",
    )
    before = locations_path.read_bytes()

    main([
        "--locations", str(locations_path),
        "--event-metadata", str(event_metadata_path),
        "--events-json", str(events_path),
        "--metadata-only",
    ])

    assert locations_path.read_bytes() == before
    payload = json.loads(event_metadata_path.read_text(encoding="utf-8"))
    assert payload["locations"][0]["active_events"][0]["event_date"] == "2026-08-14"


def test_legacy_snapshot_bootstrap_preserves_exact_bytes_and_archives(tmp_path):
    source = tmp_path / "config" / "location_market_events.json"
    target = tmp_path / "data" / "location_market_events.json"
    archive = tmp_path / "data" / "archive"
    source.parent.mkdir(parents=True)
    raw = b'{\r\n  "generated_at_utc": "2026-09-01T00:00:00Z",\r\n  "locations": []\r\n}\r\n'
    source.write_bytes(raw)

    result = bootstrap_legacy_event_snapshot(source, target, archive_dir=archive)

    assert result == target
    assert target.read_bytes() == raw
    archived = list(archive.glob("*.json"))
    assert len(archived) == 1
    assert archived[0].read_bytes() == raw


def test_event_snapshot_writer_archives_previous_and_writes_lf_atomically(tmp_path):
    target = tmp_path / "data" / "events.json"
    archive = tmp_path / "archive"
    old = b'{\r\n  "generated_at_utc": "2026-09-01T00:00:00Z",\r\n  "locations": []\r\n}\r\n'
    target.parent.mkdir(parents=True)
    target.write_bytes(old)

    write_event_snapshot(
        target,
        {"generated_at_utc": "2026-09-02T00:00:00Z", "locations": []},
        archive_dir=archive,
    )

    assert [path.read_bytes() for path in archive.glob("*.json")] == [old]
    current = target.read_bytes()
    assert b"\r\n" not in current
    assert current.endswith(b"\n")
    assert current.startswith(b"{\n")
