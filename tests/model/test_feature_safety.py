from weather.model.feature_safety import (
    audit_recursive_model_inputs,
    forbidden_model_input_reason,
)


def test_recursive_audit_rejects_aliases_hidden_in_feature_family_hash_manifests():
    payload = {
        "guardrail": {
            "feature_hash_inputs": {
                "families": [
                    "forecast_profile",
                    "settlement-distance-bucket",
                    "retrospective/casebook",
                    "post event winner",
                ]
            }
        }
    }

    audit = audit_recursive_model_inputs({"candidate": payload})

    assert audit["status"] == "BLOCK"
    assert {row["value"] for row in audit["rejections"]} == {
        "settlement-distance-bucket",
        "retrospective/casebook",
        "post event winner",
    }
    assert forbidden_model_input_reason("label-gate-state") is not None


def test_recursive_audit_does_not_treat_evaluation_only_labels_as_model_inputs():
    payload = {
        "corpus_lineage": {
            "model_input_fields": ["forecast_high", "band_mid_minus_forecast"],
            "evaluation_only_label_fields": [
                "outcome",
                "settlement_distance_bucket",
                "winning_band",
            ],
        }
    }

    audit = audit_recursive_model_inputs({"corpus": payload})

    assert audit["status"] == "PASS"
    assert audit["rejections"] == []
