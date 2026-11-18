from weather.calibration.probability_calibration_report import write_report


def test_report_separates_candidate_score_and_emitted_behavior_for_tail_only_data(tmp_path):
    selected = dict(method="isotonic", param=None, brier=0.04, logloss=0.2)
    artifact = {
        "generated_at_utc": "2000-01-01T00:00:00+00:00",
        "selected_deployable_candidate": selected,
        "candidate_scores": [selected],
        "training": {
            "rows": 6, "target_dates": ["2000-01-01"], "baseline_brier": 0.09,
            "baseline_logloss": 0.3, "market_brier": 0.1, "market_logloss": 0.4,
            "baseline_brier_skill_vs_market": 0.1, "selected_brier_skill_vs_market": 0.6,
            "artifact_replay_brier": 0.09, "artifact_replay_logloss": 0.3,
            "artifact_replay_brier_skill_vs_market": 0.1,
        },
        "market_bin": {
            "method": "isotonic", "preserve_distribution_coherence": True,
            "contexts": {}, "min_context_n": 40,
        },
        "exact_distribution": {
            "enabled": True, "method": "temperature", "temperature": 1.0,
            "temperature_by_hour": {}, "prior_weight": 0.0,
        },
    }
    report = tmp_path / "calibration.md"
    write_report(report, artifact)
    text = report.read_text(encoding="utf-8")
    assert "Highest-ranked weather-only binary candidate" in text
    assert "applies hard support and otherwise returns the band probability" in text
    assert "Market-bin replay Brier on training rows: 0.0900" in text
    assert "Exact-row count: 0" in text
    assert "Selected Deployable Calibrator" not in text
    artifact["market_bin"]["preserve_distribution_coherence"] = False
    write_report(report, artifact)
    assert "prior_shrink (default branch)" in report.read_text(encoding="utf-8")
