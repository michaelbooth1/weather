import csv
import json
from collections import defaultdict

import pytest

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
        "current_probability": "0.20",
        "recorded_probability": "0.17",
        "market_yes": "0.04",
        "outcome": "1",
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
        "settlement_distance_bucket": "0",
        "forecast_source_count_bucket": "two_sources",
        "forecast_disagreement_bucket": "high_disagreement",
        "forecast_bucket_pressure": "near_forecast",
        "used_extra_location_labels": "true",
        "target_local_labels_present": "true",
        "extra_location_gate_status": "PASS",
        "extra_location_gate_reason": "retrospective_label_gate",
        "extra_location_weight": "0.4",
        "casebook_taxonomy": "market_lead",
        "casebook_case_id": "post-settlement-case",
        "casebook_result": "model_win",
        "casebook_slice_type": "known_edge_candidate",
        "feature_schema_version": "attribution_with_settlement",
        "feature_family_hash": "settlement-inclusive-family-hash",
        "feature_missingness_hash": "settlement-inclusive-missingness-hash",
        "micro_gate_taxonomy": "market_lead",
        "micro_gate_reason": "allowed retrospective taxonomy",
    }
    row.update(overrides)
    return row


def _two_band_snapshot(**overrides):
    first = _row(**overrides)
    second = _row(
        **{
            **overrides,
            "band_key": "eq:98.0-99.0",
            "bin_value": "98.0",
            "current_probability": "0.80",
            "outcome": "0",
            "settlement_distance_bucket": "2",
        }
    )
    return [first, second]


def _partition_sums(rows, field):
    grouped = defaultdict(float)
    for row in rows:
        key = (row["market_id"], row["target_date"], row["snapshot_id"])
        grouped[key] += float(row[field])
    return grouped


def test_settlement_and_outcome_fields_do_not_affect_guardrail():
    leaked = _row(
        current_probability="0.02",
        settlement_distance_bucket="2",
        outcome="1",
        casebook_result="model_win",
    )
    changed_labels = _row(
        current_probability="0.02",
        settlement_distance_bucket="99",
        outcome="0",
        casebook_result="model_loss",
    )

    leaked_probability, leaked_guardrails = repair.repaired_probability(leaked, 0.13)
    changed_probability, changed_guardrails = repair.repaired_probability(changed_labels, 0.13)

    assert leaked_probability == pytest.approx(0.13)
    assert changed_probability == pytest.approx(0.13)
    assert leaked_guardrails == []
    assert changed_guardrails == []


def test_feature_contract_excludes_and_rejects_prohibited_fields():
    contract = repair.validate_feature_contract()
    selected = set(contract["numeric_features"] + contract["categorical_features"])
    excluded = set(repair.EXCLUDED_LABEL_MARKET_OR_IDENTITY_FIELDS)

    assert set(repair.SETTLEMENT_OR_OUTCOME_DERIVED_FIELDS) <= excluded
    assert selected.isdisjoint(repair.PROHIBITED_FEATURE_FIELDS)
    assert set(repair.GUARDRAIL_FEATURES).isdisjoint(repair.PROHIBITED_FEATURE_FIELDS)
    assert set(repair.row_features(_row())) == selected
    assert "settlement_distance_bucket" not in selected
    assert "feature_missingness_hash" not in selected

    with pytest.raises(ValueError, match="prohibited model fields: settlement_distance_bucket"):
        repair.validate_feature_contract(
            categorical_features=(*repair.CATEGORICAL_FEATURES, "settlement_distance_bucket")
        )
    with pytest.raises(ValueError, match="prohibited guardrail fields: casebook_result"):
        repair.validate_feature_contract(
            guardrail_features=(*repair.GUARDRAIL_FEATURES, "casebook_result")
        )


def test_decorated_and_exported_probabilities_are_snapshot_partitions(tmp_path):
    first_snapshot = _two_band_snapshot()
    second_snapshot = _two_band_snapshot(
        snapshot_id="20260612T050000-0400",
        current_probability="0.45",
    )
    second_snapshot[1]["current_probability"] = "0.55"
    source_rows = [*first_snapshot, *second_snapshot]

    rows, summary = repair.decorate_eval_rows(
        source_rows,
        [2.0, 1.0, 9.0, 1.0],
        training_dates=("2026-06-07", "2026-06-08"),
        eval_dates=("2026-06-12", "2026-06-13"),
    )
    rows_out = tmp_path / "rows.csv"
    repair.write_rows(rows_out, list(rows[0]), rows)
    exported = list(csv.DictReader(rows_out.open("r", encoding="utf-8", newline="")))

    assert all(total == pytest.approx(1.0) for total in _partition_sums(rows, "probability").values())
    assert all(
        total == pytest.approx(1.0)
        for total in _partition_sums(
            rows,
            "item224_active_timesplit_logistic_raw_probability",
        ).values()
    )
    assert all(total == pytest.approx(1.0) for total in _partition_sums(exported, "probability").values())
    assert {row["counts_toward_weather_model_promotion"] for row in rows} == {"false"}
    assert {row["claim_lane"] for row in rows} == {"quarantined_label_leak_repair"}
    assert summary["raw_partition_normalization"]["snapshot_partitions"] == 2
    assert summary["final_partition_normalization"]["max_abs_partition_sum_error"] <= 1e-12
    assert summary["active_source_lineage_counts"] == {
        "item50_pooled_forecast_v3_candidate": 4,
    }


def test_probability_normalization_falls_back_to_current_then_uniform():
    rows = _two_band_snapshot(current_probability="0.75")
    rows[1]["current_probability"] = "0.25"

    normalized, methods, summary = repair.normalize_snapshot_probabilities(
        rows,
        [float("nan"), -1.0],
    )

    assert normalized == pytest.approx([0.75, 0.25])
    assert set(methods) == {"current_partition_fallback"}
    assert summary["normalization_method_counts"] == {"current_partition_fallback": 1}

    rows[0]["current_probability"] = "nan"
    rows[1]["current_probability"] = "-1"
    normalized, methods, summary = repair.normalize_snapshot_probabilities(
        rows,
        [float("nan"), -1.0],
    )

    assert normalized == pytest.approx([0.5, 0.5])
    assert set(methods) == {"uniform_partition_fallback"}
    assert summary["normalization_method_counts"] == {"uniform_partition_fallback": 1}


def test_partition_validation_rejects_unnormalized_probabilities():
    rows = _two_band_snapshot()
    rows[0]["probability"] = "0.2"
    rows[1]["probability"] = "0.2"

    with pytest.raises(ValueError, match="partition sums to 0.4"):
        repair.validate_probability_partitions(rows)


def test_variant_contract_and_static_registry_are_quarantined():
    contract = repair.quarantined_contract("data/backtest/item224_rows.csv")
    registry = json.loads(repair.DEFAULT_BASE_REGISTRY.read_text(encoding="utf-8"))
    entry = next(
        row for row in registry["variants"] if row["variant_id"] == repair.VARIANT_ID
    )

    for item in (contract, entry):
        assert item["lifecycle"] != "active"
        assert item["active_for_headline"] is False
        assert item["counts_toward_weather_model_promotion"] is False
        assert item["promotion_status"] == "blocked"
        assert "label-leak-quarantined" in item["roles"]
