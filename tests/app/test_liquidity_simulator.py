from unittest.mock import patch

from streamlit.testing.v1 import AppTest


def _app():
    at = AppTest.from_file("app/streamlit_app.py", default_timeout=30)
    at.query_params["market"] = "simulator"
    return at


def test_simulator_route_runs_without_monitor_or_network_and_exports_scenario():
    with patch("app.monitor_data.load_control_snapshot", side_effect=AssertionError("monitor accessed")), patch("socket.create_connection", side_effect=AssertionError("network accessed")):
        at = _app().run()
    assert not at.exception
    assert at.title[0].value == "Liquidity reward simulator"
    assert next(item for item in at.selectbox if item.label == "Page").value == "Reward Simulator"
    assert at.query_params["market"] == ["simulator"]
    assert len(at.metric) == 3
    assert len(at.dataframe) == 1
    assert "After costs (pUSD)" in at.dataframe[0].value.columns


def test_user_competition_change_updates_reward_and_partial_fill_erases_it():
    at = _app().run()
    other = next(item for item in at.number_input if item.label == "Other makers' combined Q-min")
    other.set_value(20.0).run()
    assert not at.exception
    before = at.dataframe[0].value
    assert before.iloc[-1]["After costs (pUSD)"] > 0
    remaining = next(item for item in at.slider if item.label == "YES shares remaining after fills")
    remaining.set_value(.99).run()
    assert not at.exception
    after = at.dataframe[0].value
    assert after.iloc[-1]["Gross reward (tokens)"] == 0
    assert after.iloc[-1]["After costs (pUSD)"] < 0


def test_two_sided_plan_displays_order_cap_failure():
    at = _app().run()
    next(item for item in at.selectbox if item.label == "Buy plan").set_value("BOTH").run()
    assert not at.exception
    assert any("capital:order_cap" in str(item.value) for item in at.warning)
