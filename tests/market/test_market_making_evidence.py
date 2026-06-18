from datetime import datetime, timezone

import pytest

from weather.market.market_making_evidence import classify_market_making_evidence


def test_active_window_paper_run_counts_as_live_forward_evidence():
    payload = classify_market_making_evidence(
        "2026-06-16",
        now="2026-06-16T23:30:00+00:00",
        timezone_name="America/Toronto",
        run_mode="paper-live-forward",
    )

    assert payload["evidence_mode"] == "active_day_live_forward"
    assert payload["counts_toward_live_forward_gate"]
    assert payload["local_run_date"] == "2026-06-16"


def test_after_window_same_local_target_date_is_post_settlement():
    payload = classify_market_making_evidence(
        "2026-06-16",
        now="2026-06-17T00:31:18+00:00",
        timezone_name="America/Toronto",
        run_mode="paper-live-forward",
    )

    assert payload["evidence_mode"] == "post_settlement_evaluation"
    assert not payload["counts_toward_live_forward_gate"]
    assert "after active-day evidence window" in payload["reason"]


def test_before_window_run_is_operator_drill():
    payload = classify_market_making_evidence(
        "2026-06-16",
        now="2026-06-16T04:01:00+00:00",
        timezone_name="America/Toronto",
        run_mode="paper-live-forward",
    )

    assert payload["evidence_mode"] == "operator_drill"
    assert not payload["counts_toward_live_forward_gate"]
    assert "before active-day evidence window" in payload["reason"]


def test_operator_override_wins_and_datetime_target_is_supported():
    payload = classify_market_making_evidence(
        datetime(2026, 6, 16, tzinfo=timezone.utc),
        now="2026-06-16T23:30:00+00:00",
        timezone_name="America/Toronto",
        requested_mode="operator_drill",
        run_mode="paper-live-forward",
    )

    assert payload["target_date"] == "2026-06-16"
    assert payload["evidence_mode"] == "operator_drill"
    assert payload["reason"] == "operator override"
    assert not payload["counts_toward_live_forward_gate"]


def test_invalid_evidence_mode_is_rejected():
    with pytest.raises(ValueError, match="unsupported evidence mode"):
        classify_market_making_evidence(
            "2026-06-16",
            now="2026-06-16T23:30:00+00:00",
            requested_mode="not-a-mode",
        )
