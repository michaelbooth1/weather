import datetime
import pandas as pd
from unittest import mock
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

import pytest
import overview_helpers
from overview_helpers import check_snapshot_status, format_status_table, format_edge_table

@mock.patch("overview_helpers.all_specs")
@mock.patch("overview_helpers.SnapshotStore")
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
        {"market_id": "a", "city_label": "A", "range_label": ">=20", "edge_percent": 0.15, "model_prob": 0.5, "market_price": 0.35, "trust_score": 90, "settled_days": 10}
    ]
    df = format_edge_table(edges)
    assert not df.empty
    assert "Edge" in df.columns
    assert df.iloc[0]["Edge"] == "+15.0%"

@mock.patch("overview_helpers.all_specs")
@mock.patch("overview_helpers.config_for_date")
@mock.patch("overview_helpers.SnapshotStore")
@mock.patch("overview_helpers.score_market")
@mock.patch("pandas.read_csv")
def test_compute_biggest_edges(mock_read_csv, mock_score_market, mock_store_cls, mock_config, mock_all_specs):
    # Mock a single market spec
    mock_spec = mock.Mock()
    mock_spec.id = "test-market"
    mock_spec.city_label = "Test City"
    mock_all_specs.return_value = [mock_spec]
    
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
        {"snapshot_id": "snap1", "range_label": "20+", "edge": 0.05, "model_probability": 0.5, "market_yes": 0.45, "captured_at_local": "2024-01-01"},
        {"snapshot_id": "snap1", "range_label": "30+", "edge": -0.15, "model_probability": 0.2, "market_yes": 0.35, "captured_at_local": "2024-01-01"},
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
