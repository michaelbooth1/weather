from unittest import mock

from streamlit.testing.v1 import AppTest


def _snapshot():
    return {
        "generated_at_utc": "2026-10-02T15:00:00+00:00",
        "money": {"available": True, "status": "INCOMPLETE", "cash_pusd": "283.95", "pnl_pusd": None,
                  "pnl_reason": "INCOMPLETE: unredeemed_terminal_value_unknown", "bleed_limit_reached": False,
                  "position_count": 0, "open_order_count": 0, "unredeemed_count": 0, "errors": [],
                  "captured_at_utc": "2026-10-02T14:59:00+00:00",
                  "rewards": {"available": True, "date": "2026-10-01", "total_pusd": "8.25", "payment_verified": False}},
        "work": {"available": True, "record_count": 4, "open_count": 3, "by_status": {"proposed": 2, "queued": 1},
                 "by_owner": {"production": 3}, "overdue_owner_count": 1, "ready_to_land": ["W-0003"],
                 "check_issues": ["W-0001: needs_owner older than 3 days: Approve 5f deletes"],
                 "waiting_on_owner": [{"id": "W-0001", "title": "t", "question": "Approve 5f deletes",
                                       "since": "2026-09-28", "age_days": 4.6, "overdue": True}]},
        "health": {
            "host": {"available": False, "reason": "missing host_health_latest.json"},
            "disk": {"available": True, "free_gib": 91.0, "slope_gib_per_day": -4.8, "slope_reason": "a to b",
                     "days_to": {"50": 8.5, "40": 10.6}},
            "maker_evidence": {"available": True, "status": {"state": "RUNNING"}, "closed_dates": ["2026-09-30"],
                               "unsealed_past_dates": []},
        },
        "exam": {"available": True, "embargo": "No policy P&L or policy comparison is shown for panel dates.",
                 "exams": [{"candidate": "maker-replay-2026-10-15-v1", "phase": "panel day 3 of 14",
                            "look": "2026-10-15", "days_to_look": 13, "panel": ["2026-09-30", "2026-10-13"],
                            "panel_days_closed": 1, "panel_days_total": 14, "source": "DECISION_LOG 2026-09-27"}]},
    }


def _visible_text(app_test):
    elements = [*app_test.title, *app_test.subheader, *app_test.markdown, *app_test.caption,
                *app_test.info, *app_test.warning, *app_test.error, *app_test.success]
    return "\n".join(str(element.value) for element in elements)


@mock.patch("app.views.cockpit._load_cockpit_snapshot")
def test_cockpit_is_the_default_read_only_page(mock_load):
    mock_load.return_value = _snapshot()
    app_test = AppTest.from_file("app/streamlit_app.py")
    app_test.run()

    assert not app_test.exception
    assert app_test.selectbox[0].value == "Cockpit"
    assert app_test.title[0].value == "Owner Cockpit"
    assert [header.value for header in app_test.subheader] == ["Money", "Work", "Health", "Exam"]
    metrics = {metric.label: metric.value for metric in app_test.metric}
    assert metrics["Campaign P&L (pUSD)"] == "INCOMPLETE"
    assert metrics["Free disk (GiB)"] == "91.0"
    text = _visible_text(app_test)
    assert "Unavailable: missing host_health_latest.json" in text
    assert "W-0001: Approve 5f deletes (4.6 d)" in text
    assert "No policy P&L" in text
    assert len(app_test.button) == 0 and len(app_test.number_input) == 0 and len(app_test.text_input) == 0


@mock.patch("app.views.cockpit._load_cockpit_snapshot")
def test_cockpit_fails_closed_on_any_exception(mock_load):
    broken = _snapshot()
    del broken["work"]["waiting_on_owner"]  # a render-time KeyError after Money has rendered
    mock_load.return_value = broken
    app_test = AppTest.from_file("app/streamlit_app.py")
    app_test.query_params["cockpit"] = ""
    app_test.run()

    assert not app_test.exception
    assert [error.value for error in app_test.error] == ["Cockpit failed safely: KeyError: 'waiting_on_owner'"]
    assert len(app_test.metric) == 0  # the partial render was dropped


@mock.patch("app.views.cockpit._load_cockpit_snapshot", side_effect=OSError("disk gone"))
def test_cockpit_fails_closed_when_the_snapshot_cannot_load(mock_load):
    app_test = AppTest.from_file("app/streamlit_app.py")
    app_test.run()

    assert not app_test.exception
    assert "Cockpit failed safely: OSError: disk gone" in _visible_text(app_test)


@mock.patch("app.views.control_room._load_control_room_snapshot", side_effect=RuntimeError("fixture"))
def test_retired_market_routes_still_fall_back_to_control_room(mock_load):
    app_test = AppTest.from_file("app/streamlit_app.py")
    app_test.query_params["market"] = "overview"
    app_test.run()

    assert not app_test.exception
    assert app_test.selectbox[0].value == "Control Room"
