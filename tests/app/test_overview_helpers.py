import datetime
import pandas as pd
from unittest import mock
import sys
import os
import pytest
import weather.reporting.overview_helpers as overview_helpers
from weather.reporting.overview_helpers import check_snapshot_status, format_status_table, format_edge_table

@mock.patch("weather.reporting.overview_helpers.all_specs")
@mock.patch("weather.reporting.overview_helpers.SnapshotStore")
def test_check_snapshot_status_missing(mock_store_cls, mock_all_specs):
    # Mock a single spec
    mock_spec = mock.Mock()
    mock_spec.id = "test-market"
    mock_spec.city_label = "Test City"
    mock_all_specs.return_value = [mock_spec]
    
    # Mock SnapshotStore missing long path
    mock_store = mock.Mock()
    mock_store.long_path.exists.return_value = False
    mock_store_cls.return_value = mock_store
    
    status = check_snapshot_status()
    assert len(status) == 1
    assert status[0]["city_label"] == "Test City"
    assert status[0]["status_icon"] == "🔴"

def test_format_status_table():
    status = [
        {"city_label": "A", "last_snapshot": "2024-01-01", "minutes_ago": 10, "status_icon": "🟢"},
        {"city_label": "B", "last_snapshot": "2024-01-01", "minutes_ago": -1, "status_icon": "🔴"}
    ]
    df = format_status_table(status)
    assert not df.empty
    assert "Status" in df.columns
    assert "Market" in df.columns
    assert "Age" in df.columns
    assert df.iloc[0]["Age"] == "10 mins ago"
    assert df.iloc[1]["Age"] == "No data"

def test_format_edge_table():
    edges = [
        {"market_id": "a", "city_label": "A", "range_label": ">=20", "edge_percent": 0.15, "model_prob": 0.5, "market_price": 0.35, "trust_score": 90, "settled_days": 10, "audit_saved": True}
    ]
    df = format_edge_table(edges)
    assert not df.empty
    assert "Edge" in df.columns
    assert "Audit Saved" in df.columns
    assert df.iloc[0]["Edge"] == "+15.0%"
    assert bool(df.iloc[0]["Audit Saved"]) is True

@mock.patch("weather.reporting.overview_helpers.all_specs")
@mock.patch("weather.reporting.overview_helpers.config_for_date")
@mock.patch("weather.reporting.overview_helpers.SnapshotStore")
@mock.patch("weather.reporting.overview_helpers.score_market")
@mock.patch("weather.reporting.overview_helpers.load_audit_index")
@mock.patch("pandas.read_csv")
def test_compute_biggest_edges(mock_read_csv, mock_load_audit_index, mock_score_market, mock_store_cls, mock_config, mock_all_specs):
    # Mock a single market spec
    mock_spec = mock.Mock()
    mock_spec.id = "test-market"
    mock_spec.city_label = "Test City"
    mock_all_specs.return_value = [mock_spec]
    mock_load_audit_index.return_value = {}
    
    # Mock config_for_date
    mock_cfg = mock.Mock()
    mock_cfg.event_slug = "test-slug"
    mock_config.return_value = mock_cfg

    # Mock SnapshotStore
    mock_store = mock.Mock()
    mock_store.long_path.exists.return_value = True
    mock_store_cls.return_value = mock_store

    # Mock read_csv
    mock_df = pd.DataFrame([
        {"snapshot_id": "snap1", "range_label": "20+", "edge": 0.05, "model_probability": 0.5, "market_yes": 0.45, "captured_at_local": "2024-01-01", "event_slug": "test-slug", "bin_kind": "gte", "bin_value_c": 20},
        {"snapshot_id": "snap1", "range_label": "30+", "edge": -0.15, "model_probability": 0.2, "market_yes": 0.35, "captured_at_local": "2024-01-01", "event_slug": "test-slug", "bin_kind": "gte", "bin_value_c": 30},
    ])
    mock_read_csv.return_value = mock_df

    # Mock score_market
    mock_score_market.return_value = {"trust_score": 85, "settled_days": 20}

    edges = overview_helpers.compute_biggest_edges(n=10)
    
    assert len(edges) == 1
    edge = edges[0]
    assert edge["market_id"] == "test-market"
    assert edge["city_label"] == "Test City"
    assert edge["range_label"] == "30+"  # -0.15 has highest absolute edge
    assert edge["abs_edge"] == 0.15
    assert edge["trust_score"] == 85
    assert edge["settled_days"] == 20
    assert edge["audit_saved"] is False

@mock.patch("weather.reporting.overview_helpers.all_specs")
@mock.patch("weather.reporting.overview_helpers.config_for_date")
@mock.patch("weather.reporting.overview_helpers.SnapshotStore")
@mock.patch("weather.reporting.overview_helpers.score_market")
@mock.patch("weather.reporting.overview_helpers.ensure_audit_record_saved")
@mock.patch("weather.reporting.overview_helpers.load_audit_index")
@mock.patch("pandas.read_csv")
def test_compute_biggest_edges_marks_auto_saved_audit(mock_read_csv, mock_load_audit_index, mock_ensure_audit, mock_score_market, mock_store_cls, mock_config, mock_all_specs):
    if hasattr(overview_helpers.compute_biggest_edges, "clear"):
        overview_helpers.compute_biggest_edges.clear()

    mock_spec = mock.Mock()
    mock_spec.id = "nyc"
    mock_spec.city_label = "NYC"
    mock_all_specs.return_value = [mock_spec]
    mock_load_audit_index.return_value = {}

    mock_cfg = mock.Mock()
    mock_cfg.event_slug = "highest-temperature-in-nyc-on-june-23-2099"
    mock_config.return_value = mock_cfg

    mock_store = mock.Mock()
    mock_store.long_path.exists.return_value = True
    mock_store.event_slug = mock_cfg.event_slug
    mock_store.root = "data/snapshots/highest-temperature-in-nyc-on-june-23-2099"
    mock_store_cls.return_value = mock_store

    mock_read_csv.return_value = pd.DataFrame([
        {
            "snapshot_id": "snap1",
            "range_label": "70-71 F",
            "edge": -0.71,
            "model_probability": 0.11,
            "market_yes": 0.82,
            "captured_at_local": "2099-06-23T10:00:00-04:00",
            "event_slug": mock_cfg.event_slug,
            "bin_kind": "eq",
            "bin_value_c": 70,
            "bin_value_hi_c": 71,
        },
    ])
    mock_score_market.return_value = {"trust_score": 85, "settled_days": 20}
    mock_ensure_audit.return_value = {"triggered": True, "saved": True, "written": True}

    edges = overview_helpers.compute_biggest_edges(n=10)

    assert len(edges) == 1
    assert edges[0]["audit_saved"] is True
    assert edges[0]["audit_triggered"] is True
    assert edges[0]["audit_written"] is True
    mock_ensure_audit.assert_called_once()
