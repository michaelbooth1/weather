import json

from weather.operations.location_config_refresh import (
    build_location_market_events,
    durable_locations_payload,
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
