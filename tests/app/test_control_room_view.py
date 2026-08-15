from unittest import mock

from streamlit.testing.v1 import AppTest


TARGET_DATE = "2026-08-15"


def _artifact(payload, name):
    return {
        "available": True,
        "path": f"fixture://{name}.json",
        "recorded_at": "2026-08-15T14:05:00+00:00",
        "payload": payload,
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


@mock.patch("app.views.control_room._load_control_room_snapshot")
def test_control_room_route_is_read_only_and_decision_first(mock_load):
    mock_load.return_value = (_control_fixture(), _operations_fixture())
    app_test = AppTest.from_file("app/streamlit_app.py")
    app_test.query_params["market"] = "control"
    app_test.run()

    assert not app_test.exception
    assert mock_load.called
    assert app_test.selectbox[0].value == "Control Room"
    assert app_test.title[0].value == "Operator Control Room"
    text = _visible_text(app_test)
    assert "International Polymarket / read-only operations" in text
    assert "READY FOR EXPLICIT APPROVAL" in text
    assert "never grants trading authority" not in text.lower()
    assert "not trading authority" in text
    assert [metric.label for metric in app_test.metric] == [
        "Capture",
        "Host",
        "International",
        "Live readiness",
        "Execution tape",
        "Economics",
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
    metrics = {metric.label: metric.value for metric in app_test.metric}
    assert metrics["Live readiness"] == "BLOCK"
    assert len(app_test.button) == 0
