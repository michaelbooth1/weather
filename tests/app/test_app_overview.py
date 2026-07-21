from unittest import mock

from streamlit.testing.v1 import AppTest


def _visible_text(app_test):
    elements = [
        *app_test.title,
        *app_test.markdown,
        *app_test.caption,
        *app_test.info,
        *app_test.warning,
        *app_test.error,
    ]
    return "\n".join(str(element.value) for element in elements)


def _ready_payload():
    return {
        "status": "READY",
        "status_message": "Three candidates pass every gate.",
        "as_of_utc": "2026-07-21T17:02:00+00:00",
        "paper_only": True,
        "recommendations": [
            {
                "market_id": "nyc-high-2026-07-21",
                "market_label": "New York City",
                "target_date": "2026-07-21",
                "range_label": "72-73 F",
                "side_label": "BUY YES",
                "executable_price": 0.94,
                "conservative_probability": 0.94,
                "calibrated_probability": 0.97,
                "after_cost_ev_per_share": 0.018,
                "expected_return_on_cost": 0.019,
                "paper_stake_usdc": 4.70,
                "max_loss_usdc": 4.70,
                "profit_if_right_usdc": 0.30,
                "expected_profit_usdc": 0.09,
                "independent_target_days": 12,
                "settled_sample_size": 41,
                "after_fee_skill": 0.08,
                "model_age_seconds": 32,
                "book_age_seconds": 11,
                "strategy_name": "settlement-scored",
                "strategy_status": "control",
                "market_url": "/?market=nyc-high-2026-07-21",
            }
        ],
        "candidate_count": 1,
        "fund": {
            "budget_usdc": 100,
            "spent_usdc": 4.70,
            "remaining_usdc": 95.30,
            "net_pnl_usdc": 0,
            "filled_order_count": 1,
            "unsettled_order_count": 1,
        },
        "blocker_counts": {"stale_book": 2, "permission_denied": 5},
        "provenance": {
            "run_id": "paper-20260721T170200Z",
            "release_id": "research-unbound",
            "permission_map_generated_at_utc": "2026-07-20T07:00:00+00:00",
        },
        "warnings": ["Research-unbound evidence remains diagnostic only."],
    }


@mock.patch("weather.reporting.market.safe_bets.load_safe_bets_payload")
def test_home_renders_high_probability_paper_recommendation(mock_load):
    mock_load.return_value = _ready_payload()

    app_test = AppTest.from_file("app/streamlit_app.py").run()

    assert not app_test.exception
    assert mock_load.called
    assert app_test.selectbox[0].value == "Home"
    assert app_test.title[0].value == "Safest bets right now"
    text = _visible_text(app_test)
    assert "Paper-only, settlement-scored shortlist" in text
    assert "No outcome is guaranteed" in text
    assert "New York City" in text
    assert "72-73 F" in text
    assert "BUY YES" in text
    assert "94.0%" in text
    assert text.count("94.0%") >= 2
    assert "$4.70" in text
    assert "Paper arm: settlement-scored / control" in text
    assert "Open market evidence" in text
    assert "Permission Denied" in text
    assert "Data provenance and safety gates" in [expander.label for expander in app_test.expander]
    assert [metric.label for metric in app_test.metric] == [
        "Test budget",
        "Paper spent",
        "Remaining",
        "Paper net P&L",
        "Passing bets",
    ]
    assert len(app_test.button) == 0
    assert len(app_test.number_input) == 0
    assert "Place order" not in text


@mock.patch("weather.reporting.market.safe_bets.load_safe_bets_payload")
def test_home_fails_closed_when_run_is_blocked(mock_load):
    payload = _ready_payload()
    payload.update(
        {
            "status": "BLOCKED",
            "status_message": "Exchange economics gate is blocked.",
        }
    )
    payload["recommendations"][0]["range_label"] = "SHOULD-NOT-RENDER"
    mock_load.return_value = payload

    app_test = AppTest.from_file("app/streamlit_app.py").run()

    assert not app_test.exception
    text = _visible_text(app_test)
    assert "Exchange economics gate is blocked." in text
    assert "SHOULD-NOT-RENDER" not in text
    assert app_test.metric[-1].value == "0"


@mock.patch("weather.reporting.market.safe_bets.load_safe_bets_payload")
def test_home_handles_partial_sync_without_old_recommendations(mock_load):
    mock_load.side_effect = ValueError("partial JSON")

    app_test = AppTest.from_file("app/streamlit_app.py").run()

    assert not app_test.exception
    text = _visible_text(app_test)
    assert 'Gate status: <strong class="safe-status-warn">LOADING</strong>' in text
    assert "Waiting for sync to finish" in text
    assert app_test.metric[-1].value == "0"
