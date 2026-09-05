from unittest import mock
from datetime import datetime, timezone

import pytest

from streamlit.testing.v1 import AppTest


TARGET_DATE = datetime.now(timezone.utc).date().isoformat()


def _artifact(payload, name):
    return {
        "available": True,
        "path": f"fixture://{name}.json",
        "recorded_at": "2026-08-15T14:05:00+00:00",
        "payload": {**payload, "generated_at_utc": datetime.now(timezone.utc).isoformat()},
    }


def _control_fixture():
    return {
        "target_date": TARGET_DATE,
        "run": _artifact(
            {
                "run_id": "pilot-1",
                "target_date": TARGET_DATE,
                "mode": "live-pilot",
                "selected_market_count": 1,
                "run_budget_usdc": 100,
                "quote_permission_rows": 1,
                "live_trade_permission_rows": 1,
                "order_lifecycle": {
                    "current_open_order_count": 0,
                    "current_reserved_usdc": 0,
                },
            },
            "run",
        ),
        "readiness": _artifact(
            {
                "generated_at_utc": "2026-08-15T14:05:00+00:00",
                "target_date": TARGET_DATE,
                "status": "PASS",
                "live_capital_permission": True,
                "requires_explicit_operator_approval": True,
                "blocker_count": 0,
                "summary": {"evidence_mode": "active_day_live_forward"},
                "next_actions": [],
            },
            "readiness",
        ),
        "platform_verification": _artifact(
            {
                "platform": "polymarket_global",
                "status": "PASS",
                "verified_for_target_date": TARGET_DATE,
            },
            "platform",
        ),
        "economics_snapshot": _artifact(
            {
                "platform": "polymarket_global",
                "target_date": TARGET_DATE,
            },
            "economics-current",
        ),
        "economics_drift": _artifact(
            {
                "platform": "polymarket_global",
                "target_date": TARGET_DATE,
                "status": "PASS",
            },
            "economics-drift",
        ),
        "economics_accepted": _artifact(
            {"platform": "polymarket_global", "target_date": TARGET_DATE},
            "economics-accepted",
        ),
    }


def _operations_fixture():
    return {
        "host_status": {
            "available": True,
            "path": "fixture://status.ps1",
            "payload": {
                "ts": datetime.now(timezone.utc).isoformat(),
                "verdict": "OK",
                "flags": [],
                "warns": [],
                "streak": {"today": "ON_TRACK (100 caps, 0.0min max gap)"},
                "execution_tape": {
                    "process_healthy": True,
                    "capture_state": "CONNECTED",
                    "evidence_integrity": "PASS",
                    "price_path_usable": True,
                },
            },
        }
    }


def _visible_text(app_test):
    elements = [
        *app_test.title,
        *app_test.subheader,
        *app_test.markdown,
        *app_test.caption,
        *app_test.info,
        *app_test.warning,
        *app_test.error,
        *app_test.success,
    ]
    return "\n".join(str(element.value) for element in elements)


@pytest.fixture(autouse=True)
def local_monitor_data_only():
    with mock.patch("app.views.control_room._load_monitor_extras", return_value={
        "project": {"objective": "Prepare the attended lifecycle test", "next_steps": ["Finish the next stage"]},
        "session": {"configured": False}, "portable": {"status": "UNAVAILABLE"},
        "trading": {"available": False},
    }):
        yield


@mock.patch("app.views.control_room._load_control_room_snapshot")
def test_control_room_route_is_read_only_and_decision_first(mock_load):
    mock_load.return_value = (_control_fixture(), _operations_fixture())
    app_test = AppTest.from_file("app/streamlit_app.py")
    app_test.query_params["market"] = "control"
    app_test.run()

    assert not app_test.exception
    assert mock_load.called
    assert app_test.selectbox[0].value == "Control Room"
    assert app_test.title[0].value == "Control Room"
    text = _visible_text(app_test)
    assert "INTERNATIONAL POLYMARKET" in text
    assert "READY FOR EXPLICIT APPROVAL" in text
    assert "never grants trading authority" not in text.lower()
    assert "not trading authority" in text
    assert [metric.label for metric in app_test.metric] == [
        "Capture host",
        "Execution tape",
        "Portable executor",
    ]
    assert len(app_test.button) == 0
    assert len(app_test.number_input) == 0
    assert "Place order" not in text
    assert "Cancel order" not in text


@mock.patch("app.views.control_room._load_control_room_snapshot")
def test_control_room_route_fails_closed_without_current_readiness(mock_load):
    control = _control_fixture()
    control["readiness"] = {
        "available": False,
        "path": "fixture://backtest",
        "error": "no readiness receipt for target date 2026-08-15",
    }
    mock_load.return_value = (control, _operations_fixture())
    app_test = AppTest.from_file("app/streamlit_app.py")
    app_test.query_params["market"] = "control"
    app_test.run()

    assert not app_test.exception
    assert "HOLD" in _visible_text(app_test)
    assert "No portable attempt connected" in _visible_text(app_test)
    assert "Accounting" not in [metric.label for metric in app_test.metric]
    assert len(app_test.button) == 0


@mock.patch("app.views.control_room._load_control_room_snapshot")
def test_control_room_populates_results_and_flags_unresolved_session(mock_load):
    mock_load.return_value = (_control_fixture(), _operations_fixture())
    extras = {
        "project": {"objective": "Observe the project"},
        "session": {"configured": True, "attempt": "fixture-attempt", "stages": [
            {"label": "Stage 1", "state": "OUTCOME UNKNOWN", "detail": "Review cleanup evidence."}
        ]},
        "portable": {"status": "STALE", "recorded_status": "PASS"},
        "trading": {"available": True, "run_id": "run-1", "mode": "live-pilot",
                    "reconciliation": {"status": "STALE"}, "amounts": {
                        "Net reconciled P&L": None, "Paid maker rebates": 0,
                        "Paid liquidity rewards": None, "Actual fees": 0.01,
                    }},
    }
    with mock.patch("app.views.control_room._load_monitor_extras", return_value=extras):
        at = AppTest.from_file("app/streamlit_app.py").run()
    assert not at.exception
    text = _visible_text(at)
    assert "OUTCOME UNKNOWN" in text
    assert "Current orders and exposure are unknown" in text
    values = {metric.label: metric.value for metric in at.metric}
    assert values["Net reconciled P&L"] == "—"
    assert values["Paid maker rebates"] == "0.000000"
    assert len(at.button) == 0


@mock.patch("app.views.control_room._load_control_room_snapshot")
def test_retired_route_still_falls_back_to_control_room(mock_load):
    mock_load.return_value = (_control_fixture(), _operations_fixture())
    at = AppTest.from_file("app/streamlit_app.py")
    at.query_params["market"] = "legacy-city"
    at.run()
    assert not at.exception
    assert at.title[0].value == "Control Room"
