from datetime import datetime
from zoneinfo import ZoneInfo

from weather.model.source_adapters import fetch_source_group


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
