from weather.reporting.research.blind_feature_repair import (
    REPORT_SCHEMA_VERSION,
    control_sources,
    crossed_summary,
    render_markdown,
)


def test_control_hides_station_rows_without_changing_floor_evidence():
    sources = {
        "metar": {"ok": True, "data": {
            "temp_native": 86.0,
            "max_since_7am_native": 88.0,
            "rows": [{"time": "14:00", "temp_native": 86.0}],
            "latest": {"time": "14:00", "temp_native": 86.0},
            "raw_payload": [{"temp": 30.0}],
        }},
        "station_observations": {"ok": True, "data": {
            "temp_native": 86.0,
            "max_since_7am_native": 88.0,
            "rows": [{"time": "14:00", "temp_native": 86.0}],
        }},
    }

    control = control_sources(sources)

    assert control["metar"]["data"]["rows"] == []
    assert control["metar"]["data"]["raw_payload"] == {}
    assert control["metar"]["data"]["latest"] is None
    assert control["metar"]["data"]["temp_native"] == 86.0
    assert control["metar"]["data"]["max_since_7am_native"] == 88.0
    assert "rows" not in control["station_observations"]["data"]
    assert sources["metar"]["data"]["rows"]


def test_crossed_summary_is_daily_first_and_reports_support():
    rows = [
        {"target_date": "2026-08-01", "market_id": "a", "delta": 1.0},
        {"target_date": "2026-08-01", "market_id": "a", "delta": 3.0},
        {"target_date": "2026-08-01", "market_id": "b", "delta": 4.0},
        {"target_date": "2026-08-02", "market_id": "a", "delta": 6.0},
        {"target_date": "2026-08-02", "market_id": "b", "delta": 8.0},
    ]

    summary = crossed_summary(rows, "delta", replicates=200, seed=17)

    # Daily-first cells are 2, 4, 6, 8; snapshot duplication in the first
    # market-day cannot inflate its weight.
    assert summary["daily_first_point"] == 5.0
    assert summary["date_clusters"] == 2
    assert summary["market_clusters"] == 2
    assert summary["market_days"] == 4
    assert summary["bootstrap_replicates"] == 200
    assert summary["crossed_95_interval"][0] <= 5.0
    assert summary["crossed_95_interval"][1] >= 5.0


def test_rendered_receipt_keeps_machine_verdict_and_hash():
    report = {
        "status": "PASS",
        "verdict": "paired_replay_valid",
        "support": {
            "feature_completeness_rows": 1,
            "served_output_rows": 1,
            "promotion_countable_market_days": 1,
        },
        "positive_control": {
            "rows": 1,
            "exact_rows": 1,
            "mean_recorded_distribution_l1": 0.0,
            "max_recorded_distribution_l1": 0.0,
            "status": "PASS",
        },
        "feature_completeness_by_market": {},
        "served_output_by_provenance_regime": {},
        "report_sha256": "a" * 64,
    }

    markdown = render_markdown(report)

    assert REPORT_SCHEMA_VERSION == "blind_feature_repair_replay_v0.1"
    assert "**PASS — paired_replay_valid.**" in markdown
    assert "a" * 64 in markdown
