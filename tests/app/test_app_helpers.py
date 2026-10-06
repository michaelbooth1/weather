"""Killing assertions for small app helpers (test-suite review K, role 19, A09).

Covers the Arrow-safe table normaliser, the Control Room timestamp label and the router's query-parameter
normalisation. The router is driven through AppTest from a path anchored on this file, not the CWD.

Guards: app UI contracts (app/AGENTS.md) - Control Room times are UTC labels (a naive time is UTC, never
  host-local), Arrow-safe tables, router query-parameter normalisation; review K role 6 mutants.
"""
import time
from pathlib import Path
from unittest import mock

import pytest
from streamlit.testing.v1 import AppTest

from app.table_utils import arrow_safe_dataframe


ROUTER = Path(__file__).resolve().parents[2] / "app" / "streamlit_app.py"


def test_arrow_safe_dataframe_stringifies_mixed_and_forced_columns_only():
    assert arrow_safe_dataframe([{"a": 1}, {"a": "x"}])["a"].tolist() == ["1", "x"]
    # A blank cell does not make a numeric column mixed.
    assert arrow_safe_dataframe([{"a": 1}, {"a": ""}])["a"].tolist() == [1, ""]
    assert arrow_safe_dataframe([{"Value": 5}])["Value"].tolist() == ["5"]


@pytest.fixture
def non_utc_local_zone(monkeypatch):
    """Run under a non-UTC local zone so a naive timestamp read as local time would show.

    POSIX only: Windows has no ``time.tzset``, and there the host zone applies.
    """
    if not hasattr(time, "tzset"):
        yield
        return
    monkeypatch.setenv("TZ", "Asia/Kolkata")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _control_room_page():
    # Runs as an AppTest script: imports stay inside. Every timestamp the page labels is set here.
    from unittest import mock as page_mock

    from app.views import control_room

    control = {
        "run": {"available": True, "path": "run", "recorded_at": None, "payload": {}},
        "readiness": {
            "available": True,
            "path": "readiness.json",
            "recorded_at": "2026-08-15T14:05:00",
            "payload": {"generated_at_utc": "2026-08-15T14:05:00+02:00"},
        },
        "platform_verification": {"available": True, "path": "pv.json", "recorded_at": "", "payload": {}},
    }
    with page_mock.patch.object(control_room, "_load_control_room_snapshot", return_value=(control, {})):
        control_room.render_control_room_page()


def test_control_room_timestamp_labels_are_utc(non_utc_local_zone):
    app_test = AppTest.from_function(_control_room_page, default_timeout=30)
    app_test.run()
    assert not app_test.exception
    tables = [frame.value.to_dict("records") for frame in app_test.dataframe]
    generated = [row["Value"] for table in tables for row in table if row.get("Metric") == "Generated"]
    recorded = {row["Artifact"]: row["Recorded"] for table in tables for row in table if "Artifact" in row}
    # An offset timestamp is converted to UTC.
    assert generated == ["2026-08-15 12:05 UTC"]
    # A naive timestamp is already UTC; it must not be shifted by the host's local zone.
    assert recorded["readiness"] == "2026-08-15 14:05 UTC"
    # Missing and empty timestamps both read "not recorded".
    assert recorded["run"] == "not recorded"
    assert recorded["platform_verification"] == "not recorded"


def _run_router(params):
    with mock.patch("app.views.cockpit._load_cockpit_snapshot", side_effect=RuntimeError("fixture")), \
         mock.patch("app.views.control_room._load_control_room_snapshot", side_effect=RuntimeError("fixture")), \
         mock.patch("weather.reporting.roadmap.roadmap_backlog.summarize_roadmap_status",
                    side_effect=RuntimeError("fixture")):
        app_test = AppTest.from_file(str(ROUTER), default_timeout=30)
        for key, value in params.items():
            app_test.query_params[key] = value
        app_test.run()
    return {key: list(value) if isinstance(value, (list, tuple)) else [value]
            for key, value in app_test.query_params.items()}


def test_router_normalises_query_params_per_page():
    # Cockpit: any extra parameter is dropped (the bare ``cockpit`` key has an empty value).
    assert _run_router({"cockpit": "1", "foo": "1"}) == {}
    # Roadmap: a stray market parameter is dropped.
    assert _run_router({"roadmap": "1", "market": "control"}) == {}
    # Retired market routes fall back to the Control Room and say so in the URL.
    assert _run_router({"market": "overview"}) == {"market": ["control"]}
