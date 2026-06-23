import pytest
import sys
import os
from streamlit.testing.v1 import AppTest
from unittest import mock

@mock.patch("weather.reporting.overview_helpers.compute_biggest_edges")
@mock.patch("weather.reporting.overview_helpers.check_snapshot_status")
@mock.patch("weather.reporting.overview_helpers.load_audit_analysis_dashboard")
def test_app_overview_rendering(mock_analysis, mock_status, mock_edges):
    # Mock data to avoid hitting actual files/APIs during UI test
    mock_edges.return_value = [
        {"market_id": "test-market", "city_label": "Test City", "range_label": "20+", "edge_percent": 0.20, "abs_edge": 0.20, "model_prob": 0.50, "market_price": 0.30, "trust_score": 80, "settled_days": 10, "captured_at": "2024-01-01"}
    ]
    mock_status.return_value = [
        {"market_id": "test-market", "city_label": "Test City", "last_snapshot": "2024-01-01", "minutes_ago": 5, "status_icon": "🟢"}
    ]
    
    mock_analysis.return_value = {
        "payload": {
            "summary": {
                "recommendation_count": 1,
                "ready_for_operator_review_count": 1,
                "pending_count": 0,
                "market_closer_count": 1,
                "model_closer_count": 0,
            },
            "recommendations": [
                {
                    "priority": "P1",
                    "category": "model_repair_candidate",
                    "market_id": "nyc",
                    "range_label": "70-71 F",
                    "direction": "market_higher_than_model",
                    "evidence": {
                        "case_count": 1,
                        "resolved_count": 1,
                        "pending_count": 0,
                        "market_closer_count": 1,
                    },
                    "route": {
                        "repair_lane": "exact-band/winner-centering",
                        "roadmap_owner": "Items 70, 147, 230",
                        "counts_toward_repair_evidence": True,
                        "automatic_model_or_trading_change_allowed": False,
                    },
                    "action": "Replay the saved snapshots.",
                }
            ],
            "pending_watchlist": [],
            "groups": {"by_market_direction": []},
            "operator_review_queue": {"rows": []},
        },
        "status": {
            "analysis_artifact_status": "OK",
            "analysis_artifact_detail": "analysis artifact is fresh",
            "generated_at_utc": "2099-06-23T18:00:00+00:00",
            "analysis_age_minutes": 0,
            "audit_log_status": "OK",
            "audit_log_detail": "audit log has recent qualifying snapshots",
            "latest_audit_at_utc": "2099-06-23T17:59:00+00:00",
            "audit_log_age_minutes": 1,
        },
    }

    # Run the app
    at = AppTest.from_file("app/streamlit_app.py").run()
    
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
    has_audit = any("Audit Analysis" in text for text in markdown_texts)
    has_health = any("Capture-Tape Health" in text for text in markdown_texts)
    
    assert has_edges, "Biggest Edges section missing"
    assert has_audit, "Audit Analysis section missing"
    assert has_health, "Capture-Tape Health section missing"
    
    # Check dataframes are present
    assert len(at.dataframe) >= 2
