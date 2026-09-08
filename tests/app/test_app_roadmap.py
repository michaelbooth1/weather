from unittest import mock

from streamlit.testing.v1 import AppTest

from app.views.roadmap import _active_rows, _completion


@mock.patch("app.views.roadmap.cached_project", return_value={"workstreams": [], "next_steps": []})
@mock.patch("weather.reporting.roadmap.roadmap_backlog.summarize_roadmap_status")
def test_app_roadmap_query_param_rendering(mock_summary, _project):
    mock_summary.return_value = {
        "generated_at_utc": "2026-06-22T00:00:00+00:00",
        "status": "OK",
        "total_item_count": 207,
        "closed_item_count": 205,
        "active_item_count": 2,
        "partial_item_count": 1,
        "open_item_count": 1,
        "active_blocked_item_count": 1,
        "active_unblocked_item_count": 1,
        "lint_error_count": 0,
        "active_items": [
            {
                "number": 1,
                "title": "Blocked Item",
                "status": "OPEN",
                "date": "2026-06-22",
                "disposition": "BLOCKED",
                "blocked": True,
                "checked_checklist_count": 2,
                "open_checklist_count": 1,
            },
            {
                "number": 2,
                "title": "Unblocked Item",
                "status": "PARTIAL",
                "date": "2026-06-22",
                "disposition": "READY",
                "blocked": False,
                "checked_checklist_count": 3,
                "open_checklist_count": 2,
            },
        ],
    }

    at = AppTest.from_file("app/streamlit_app.py")
    at.query_params["roadmap"] = ""
    at.run()

    assert not at.exception
    assert mock_summary.called
    assert at.selectbox[0].value == "Roadmap"
    assert at.title[0].value == "Roadmap"
    assert len(at.metric) == 4
    assert [metric.label for metric in at.metric] == [
        "Active work",
        "Clear path",
        "Dependency held",
        "Roadmap integrity",
    ]
    assert len(at.tabs) == 3
    assert len(at.dataframe) == 3
    assert len(at.button) == 0


def test_roadmap_helpers_include_partial_work_and_bounded_completion():
    summary = {"closed_item_count": 8, "total_item_count": 10}
    rows = _active_rows([
        {
            "number": 7,
            "title": "Pilot proof",
            "status": "PARTIAL",
            "blocked": False,
            "checked_checklist_count": 4,
            "open_checklist_count": 2,
        }
    ])

    assert _completion(summary) == 0.8
    assert rows[0]["Status"] == "In progress"
    assert rows[0]["Dependency marker"] == "CLEAR"
    assert rows[0]["Checklist"] == "4 done / 2 open"
