import pytest
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from streamlit.testing.v1 import AppTest
from unittest import mock

@mock.patch("overview_helpers.compute_biggest_edges")
@mock.patch("overview_helpers.check_snapshot_status")
def test_app_overview_rendering(mock_status, mock_edges):
    # Mock data to avoid hitting actual files/APIs during UI test
    mock_edges.return_value = [
        {"market_id": "test-market", "city_label": "Test City", "range_label": "20+", "edge_percent": 0.20, "abs_edge": 0.20, "model_prob": 0.50, "market_price": 0.30, "trust_score": 80, "settled_days": 10, "captured_at": "2024-01-01"}
    ]
    mock_status.return_value = [
        {"market_id": "test-market", "city_label": "Test City", "last_snapshot": "2024-01-01", "minutes_ago": 5, "status_icon": "🟢"}
    ]
    
    # Run the app
    at = AppTest.from_file("app.py").run()
    
    # Assert there are no exceptions
    assert not at.exception
    
    # By default, it might load "overview" since it's the first in the selectbox now
    # We can ensure it by setting query params or checking the selectbox value
    # Let's check the title to ensure we're on the overview page
    markdown_texts = [m.value for m in at.markdown]
    assert any("🗺️ Market Overview" in text for text in markdown_texts)
    
    # Check that headers are rendered
    markdown_texts = [m.value for m in at.markdown]
    has_edges = any("Biggest Edges" in text for text in markdown_texts)
    has_health = any("Capture-Tape Health" in text for text in markdown_texts)
    
    assert has_edges, "Biggest Edges section missing"
    assert has_health, "Capture-Tape Health section missing"
    
    # Check dataframes are present
    assert len(at.dataframe) >= 2
