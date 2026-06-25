import json

from weather.reporting.research.item138_weak_input_family_gate import (
    SCHEMA_VERSION,
    build_payload,
    write_outputs,
)


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def weak_payload(*, all_pass=False):
    warnings = [] if all_pass else [
        {
            "family": "surface_weather",
            "disposition": "diagnostic_only",
            "feature_count": 2,
            "reasons": ["family disposition is diagnostic_only"],
        }
    ]
    return {
        "schema_version": "weak_input_family_disposition_v0.1",
        "summary": {
            "status": "PASS" if all_pass else "WARN",
            "family_count": 4,
            "training_preflight_status": "PASS" if all_pass else "WARN",
        },
        "training_preflight": {
            "schema_version": "weak_input_family_disposition_v0.1",
            "status": "PASS" if all_pass else "WARN",
            "diagnostic_only_families": [] if all_pass else ["surface_weather"],
            "warnings": warnings,
        },
        "families": [
            {"family": "observed_temp_path", "disposition": "served", "backfill_plan": None},
            {"family": "surface_weather", "disposition": "diagnostic_only", "backfill_plan": None},
            {
                "family": "marine_microclimate",
                "disposition": "regime_backfill",
                "backfill_plan": {"regimes": ["marine_layer"]},
            },
            {"family": "time_context", "disposition": "served", "backfill_plan": None},
        ],
    }


def write_inputs(tmp_path, *, all_pass=False):
    weak = tmp_path / "weak.json"
    item136 = tmp_path / "item136.json"
    write_json(weak, weak_payload(all_pass=all_pass))
    write_json(
        item136,
        {
            "status": "PASS" if all_pass else "BLOCK",
            "first_blocker": {"detail": "source-state still blocks"},
        },
    )
    return weak, item136


def test_weak_input_gate_blocks_when_active_artifact_preflight_warns(tmp_path):
    weak, item136 = write_inputs(tmp_path)

    payload = build_payload(weak_input=weak, item136=item136)
    _, report = write_outputs(payload, tmp_path / "out.json", tmp_path / "out.md")

    blockers = {gate["gate"] for gate in payload["blockers"]}
    passes = {gate["gate"] for gate in payload["gates"] if gate["status"] == "PASS"}
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "BLOCK"
    assert payload["disposition"] == "KEEP_POLICY_SHADOW_PRUNE_ON_RETRAIN"
    assert "family_disposition_inventory" in passes
    assert "regime_backfill_plan_inventory" in passes
    assert "model_explanation_diagnostic_surface" in passes
    assert "active_artifact_pruning_preflight" in blockers
    assert "upstream_source_state_disposition" in blockers
    assert "Item 138 Weak Input-Family Gate" in report.read_text(encoding="utf-8")


def test_weak_input_gate_can_pass_when_preflight_and_upstream_clear(tmp_path):
    weak, item136 = write_inputs(tmp_path, all_pass=True)

    payload = build_payload(weak_input=weak, item136=item136)

    assert payload["status"] == "PASS"
    assert payload["disposition"] == "PRUNING_READY"
    assert payload["promotion_allowed"] is True
    assert payload["blocker_count"] == 0
