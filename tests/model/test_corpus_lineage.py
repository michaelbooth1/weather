from weather.model.corpus_lineage import build_pooled_corpus_lineage


def test_corpus_lineage_hashes_selection_evaluation_and_final_refit_with_bounds():
    rows = [
        {
            "target_date": "2024-07-01",
            "year": 2024,
            "market_id": "nyc",
            "forecast_high": 88.0,
            "final_bucket": 89,
        },
        {
            "target_date": "2025-07-02",
            "year": 2025,
            "market_id": "nyc",
            "forecast_high": 90.0,
            "final_bucket": 91,
        },
    ]

    payload = build_pooled_corpus_lineage(
        rows,
        holdout_year=2025,
        model_input_fields=["forecast_high"],
    )

    assert payload["selection_training"]["row_count"] == 1
    assert payload["selection_training"]["target_date_min"] == "2024-07-01"
    assert payload["evaluation"]["row_count"] == 1
    assert payload["evaluation"]["target_date_max"] == "2025-07-02"
    assert payload["final_refit"]["row_count"] == 2
    assert len(payload["final_refit"]["sha256"]) == 64
    assert payload["model_input_fields"] == ["forecast_high"]
    assert payload["evaluation_only_label_fields"] == ["final_bucket"]
