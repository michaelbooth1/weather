from weather.operations.python_runtime_audit import streamlit_route_smoke


def test_single_market_route_smoke_renders_history_without_pandas_shadowing():
    payload = streamlit_route_smoke()

    assert payload["status"] == "PASS"
    assert payload["route"] == "single_market"
    assert payload["exception_count"] == 0
