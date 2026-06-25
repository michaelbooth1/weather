from unittest import mock

from streamlit.testing.v1 import AppTest


@mock.patch("weather.reporting.roadmap.roadmap_backlog.summarize_roadmap_status")
def test_app_roadmap_query_param_rendering(mock_summary):
    mock_summary.return_value = {
        "generated_at_utc": "2026-06-22T00:00:00+00:00",
        "closed_item_count": 205,
        "open_item_count": 2,
        "open_blocked_item_count": 1,
        "open_unblocked_item_count": 1,
        "lint_error_count": 0,
        "open_items": [
            {
                "number": 1,
                "title": "Blocked Item",
                "date": "2026-06-22",
                "disposition": "BLOCKED",
                "blocked": True,
            },
            {
                "number": 2,
                "title": "Unblocked Item",
                "date": "2026-06-22",
                "disposition": "READY",
                "blocked": False,
            },
        ],
    }

    at = AppTest.from_file("app/streamlit_app.py")
    at.query_params["roadmap"] = ""
    at.run()

    assert not at.exception
    assert mock_summary.called
    assert len(at.metric) == 4
    assert len(at.dataframe) == 1
