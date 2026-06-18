from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from weather.model.source_adapters import FETCH_META_KEY, fetch_source_group


def test_fetch_source_group_runs_without_model_facade():
    tz = ZoneInfo("UTC")

    def fail():
        raise RuntimeError("boom")

    result = fetch_source_group(
        {
            "ok_source": lambda: {"value": 3},
            "bad_source": fail,
        },
        timezone=tz,
        now_fn=lambda: datetime(2026, 6, 16, 12, 0, tzinfo=tz),
        max_workers=1,
    )

    assert result["ok_source"]["ok"] is True
    assert result["ok_source"]["data"] == {"value": 3}
    assert result["ok_source"]["fetched_at"] == "2026-06-16T12:00:00+00:00"
    assert result["bad_source"]["ok"] is False
    assert "boom" in result["bad_source"]["error"]
    assert result["bad_source"]["fetched_at"] == "2026-06-16T12:00:00+00:00"


def test_fetch_source_group_strips_success_metadata():
    tz = ZoneInfo("UTC")
    result = fetch_source_group(
        {
            "open_meteo": lambda: {
                "rows": [],
                FETCH_META_KEY: {
                    "status": "fresh_cache",
                    "source_family": "open_meteo",
                    "cache_status": "fresh_cache",
                },
            },
        },
        timezone=tz,
        now_fn=lambda: datetime(2026, 6, 16, 12, 0, tzinfo=tz),
        max_workers=1,
    )

    assert result["open_meteo"]["ok"] is True
    assert result["open_meteo"]["status"] == "fresh_cache"
    assert result["open_meteo"]["source_family"] == "open_meteo"
    assert result["open_meteo"]["data"] == {"rows": []}


def test_fetch_source_group_surfaces_http_429_metadata():
    tz = ZoneInfo("UTC")

    class Response:
        status_code = 429
        headers = {"Retry-After": "7"}

    def fail():
        exc = requests.HTTPError("too many requests")
        exc.response = Response()
        raise exc

    result = fetch_source_group(
        {"open_meteo": fail},
        timezone=tz,
        now_fn=lambda: datetime(2026, 6, 16, 12, 0, tzinfo=tz),
        max_workers=1,
    )

    assert result["open_meteo"]["ok"] is False
    assert result["open_meteo"]["status"] == "rate_limited"
    assert result["open_meteo"]["http_status"] == 429
    assert result["open_meteo"]["retry_after_seconds"] == 7.0
