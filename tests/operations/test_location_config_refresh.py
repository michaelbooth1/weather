import json
import hashlib
import io

import pytest

from weather.operations.location_config_refresh import (
    build_location_market_events,
    durable_locations_payload,
    main,
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
        event_metadata_path="config/location_market_events.json",
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
    assert durable["event_metadata"]["last_refreshed_at_utc"] == generated_at
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


def test_full_final_page_cannot_publish_a_truncated_inventory(monkeypatch):
    from weather.operations import location_config_refresh as refresh
    monkeypatch.setattr(refresh.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(b'[{}]'))
    with pytest.raises(ValueError, match="pagination is incomplete"):
        refresh.fetch_gamma_events(limit=1, max_pages=2)


def test_short_terminal_page_proves_pagination_complete(monkeypatch):
    from weather.operations import location_config_refresh as refresh
    pages = iter([b'[{"id":"1"}]', b'[]'])
    monkeypatch.setattr(refresh.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(next(pages)))
    assert refresh.fetch_gamma_events(limit=1, max_pages=2) == ([{"id": "1"}], [0, 1])


def test_resolution_descriptions_retain_exact_bytes_and_separate_market_source():
    from weather.operations.location_config_refresh import normalized_event
    description = "Resolve using station X.\nRevisions accepted through 18:00.  "
    result = normalized_event({"description": description, "resolutionSource": "https://event.test", "markets": [
        {"description": "Market-specific rules", "resolutionSource": "https://market.test"}]})
    assert result["description"] == description
    assert result["description_sha256"] == hashlib.sha256(description.encode()).hexdigest()
    assert result["markets"][0]["description"] == "Market-specific rules"
    assert result["markets"][0]["resolution_source_url"] == "https://market.test"


def test_failed_atomic_replace_preserves_the_previous_config(tmp_path, monkeypatch):
    from weather.operations.location_config_refresh import write_json
    path = tmp_path / "config.json"
    path.write_text('{"previous":true}')
    def interrupted(*args):
        raise OSError("fixture interrupted before publication")
    monkeypatch.setattr(type(path), "replace", interrupted)
    with pytest.raises(OSError, match="fixture interrupted"):
        write_json(path, {"new": True})
    assert json.loads(path.read_text()) == {"previous": True}
