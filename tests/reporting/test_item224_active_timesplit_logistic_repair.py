from weather.reporting.research import item224_active_timesplit_logistic_repair as repair


def _row(**overrides):
    row = {
        "variant_id": "item224_active_source_route_composite_v0_1",
        "variant_family": "item224_active_source_route_composite",
        "uses_market_features": "false",
        "is_control": "false",
        "claim_lane": "weather_only_core_model",
        "counts_toward_weather_model_promotion": "true",
        "quote_risk_eligible": "false",
        "quote_risk_gate_reason": "weather_only_core_model",
        "market_id": "nyc",
        "target_date": "2026-06-12",
        "snapshot_id": "20260612T040000-0400",
        "band_key": "eq:96.0-97.0",
        "probability": "0.17",
        "current_probability": "0.02",
        "recorded_probability": "0.17",
        "market_yes": "0.04",
        "outcome": "0",
        "artifact_hash": "source-artifact",
        "postprocess_config_hash": "source-config",
        "experiment_start_date": "2026-06-21",
        "route_source_path": "data/backtest/item50_pooled_candidate_shadow_variants.csv",
        "route_source_variant_family": "pooled_f_candidate",
        "route_source_variant_id": "item50_pooled_forecast_v3_candidate",
        "captured_at_local": "2026-06-12T04:00:00-04:00",
        "range_label": "",
        "bin_type": "eq",
        "bin_value": "96.0",
        "cutoff_hour": "7",
        "cutoff_regime": "early",
        "source_freshness_state": "all_fresh",
        "settlement_distance_bucket": "2",
        "forecast_source_count_bucket": "two_sources",
        "forecast_disagreement_bucket": "high_disagreement",
        "forecast_bucket_pressure": "near_forecast",
        "feature_missingness_hash": "hash",
    }
    row.update(overrides)
    return row


def test_early_adjacent_low_current_gap_cap_uses_current_probability():
    row = _row(current_probability="0.02", settlement_distance_bucket="2")

    probability, guardrails = repair.repaired_probability(row, 0.13)

    assert probability == 0.02
    assert guardrails == ["early_adjacent_low_current_gap_cap_v0_1"]


def test_early_adjacent_cap_ignores_non_adjacent_distance_bucket():
    row = _row(current_probability="0.02", settlement_distance_bucket="3")

    probability, guardrails = repair.repaired_probability(row, 0.13)

    assert probability == 0.13
    assert guardrails == []


def test_decorated_rows_are_countable_active_contract_rows():
    rows, summary = repair.decorate_eval_rows(
        [_row()],
        [0.13],
        training_dates=("2026-06-07", "2026-06-08"),
        eval_dates=("2026-06-12", "2026-06-13"),
    )

    row = rows[0]
    assert row["variant_id"] == repair.VARIANT_ID
    assert row["variant_family"] == repair.VARIANT_FAMILY
    assert row["counts_toward_weather_model_promotion"] == "true"
    assert row["uses_market_features"] == "false"
    assert row["quote_risk_eligible"] == "false"
    assert row["probability"] == "0.02"
    assert row["recorded_probability"] == "0.02"
    assert row["item224_active_timesplit_logistic_raw_probability"] == "0.13"
    assert row["active_timesplit_source_variant_id"] == "item50_pooled_forecast_v3_candidate"
    assert summary["guardrail_counts"]["early_adjacent_low_current_gap_cap_v0_1"] == 1
    assert summary["active_source_lineage_counts"] == {
        "item50_pooled_forecast_v3_candidate": 1,
    }


def test_feature_policy_excludes_labels_market_price_and_eval_identity_fields():
    excluded = set(repair.EXCLUDED_LABEL_MARKET_OR_IDENTITY_FIELDS)

    assert {"outcome", "market_yes", "target_date", "snapshot_id", "captured_at_local"} <= excluded
    assert "market_yes" not in repair.NUMERIC_FEATURES
    assert "outcome" not in repair.NUMERIC_FEATURES
    assert "target_date" not in repair.CATEGORICAL_FEATURES
