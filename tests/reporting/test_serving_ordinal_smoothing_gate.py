import json
import pickle

from weather.reporting.serving_ordinal_smoothing_gate import (
    SCHEMA_VERSION,
    build_payload,
    write_outputs,
)


def write_artifact(path, *, ordinal_smoothing=None):
    payload = {
        "schema_version": "pooled_feature_band_hgb_v0.3",
        "feature_schema_version": "toronto_feature_store_v1.13",
        "trained_at": "2026-06-22T00:00:00",
        "models": {"7": {"feature_names": ["current_temp"]}},
    }
    if ordinal_smoothing is not None:
        payload["ordinal_smoothing"] = ordinal_smoothing
    with path.open("wb") as handle:
        pickle.dump(payload, handle)


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_inputs(tmp_path, *, hourly_status="BLOCK", replay_status="BLOCK", retrain_status="BLOCK"):
    artifact = tmp_path / "artifact.pkl"
    predawn = tmp_path / "predawn.json"
    hourly = tmp_path / "hourly.json"
    ten = tmp_path / "ten.json"
    replay = tmp_path / "replay.json"
    retrain = tmp_path / "retrain_location.json"

    write_artifact(artifact)
    write_json(
        predawn,
        {
            "status": "PASS",
            "blocker_count": 0,
            "guardrails": [
                {"regime": "ramp_midday", "status": "PASS", "delta_vs_current": 0.0},
                {"regime": "late_day", "status": "PASS", "delta_vs_current": 0.0},
                {"regime": "lock_in", "status": "PASS", "delta_vs_current": 0.0},
            ],
            "weak_slot_summary": {"delta_vs_current": -0.02},
        },
    )
    write_json(
        hourly,
        {
            "candidate_hourly_gate": {
                "status": hourly_status,
                "blocker_count": 0 if hourly_status == "PASS" else 1,
                "first_blocker": {"detail": "early-hour candidate Brier trails market"},
                "early_morning": {
                    "delta_vs_current": -0.004,
                    "delta_vs_market": -0.001 if hourly_status == "PASS" else 0.0048,
                    "logloss_delta_vs_market": 0.0 if hourly_status == "PASS" else 0.025,
                },
            }
        },
    )
    write_json(
        ten,
        {
            "candidate_ten_minute_gate": {
                "status": "PASS",
                "blocker_count": 0,
                "weak_slot_overlap": {
                    "delta_vs_current": -0.029,
                    "delta_vs_market": -0.009,
                    "winner_variant_probability": 0.47,
                    "winner_market_probability": 0.35,
                },
            }
        },
    )
    write_json(
        replay,
        {
            "verdict": replay_status,
            "cutover_decision": "READY_FOR_CUTOVER" if replay_status == "PASS" else "DO_NOT_CUT_OVER",
            "aggregate": {"delta_vs_current": -0.001, "delta_vs_market": -0.002 if replay_status == "PASS" else 0.009},
            "source": {"validation_mode": "active_replay" if replay_status == "PASS" else "row_export_surrogate"},
        },
    )
    write_json(
        retrain,
        {
            "status": retrain_status,
            "broad_core_model_claim_allowed": retrain_status == "PASS",
            "blocker_count": 0 if retrain_status == "PASS" else 1,
            "first_blocker": {"detail": "pooled F retrain/location gate blocked"},
        },
    )
    return artifact, predawn, hourly, ten, replay, retrain


def test_gate_separates_fixed_smoothing_policy_from_remaining_validation_blockers(tmp_path):
    artifact, predawn, hourly, ten, replay, retrain = write_inputs(tmp_path)

    payload = build_payload(
        artifact_path=artifact,
        predawn_repair=predawn,
        candidate_hourly=hourly,
        candidate_ten_minute=ten,
        replay=replay,
        retrain_location_gate=retrain,
    )
    _, report = write_outputs(payload, tmp_path / "out.json", tmp_path / "out.md")

    blockers = {gate["gate"] for gate in payload["blockers"]}
    passes = {gate["gate"] for gate in payload["gates"] if gate["status"] == "PASS"}
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "BLOCK"
    assert payload["ordinal_smoothing_train_serve_skew_fixed"] is True
    assert "artifact_smoothing_policy" in passes
    assert "predawn_weak_slot_repair" in passes
    assert "ramp_late_guardrails" in passes
    assert "candidate_hourly_early_gate" in blockers
    assert "active_replay_contract" in blockers
    assert "broad_retrain_location_gate" in blockers
    assert "Serving Ordinal Smoothing Gate" in report.read_text(encoding="utf-8")


def test_gate_passes_when_hourly_replay_and_location_gate_clear(tmp_path):
    artifact, predawn, hourly, ten, replay, retrain = write_inputs(
        tmp_path,
        hourly_status="PASS",
        replay_status="PASS",
        retrain_status="PASS",
    )

    payload = build_payload(
        artifact_path=artifact,
        predawn_repair=predawn,
        candidate_hourly=hourly,
        candidate_ten_minute=ten,
        replay=replay,
        retrain_location_gate=retrain,
    )

    assert payload["status"] == "PASS"
    assert payload["acceptance_passed"] is True
    assert payload["blocker_count"] == 0


def test_gate_blocks_unsafe_enabled_smoothing_config(tmp_path):
    artifact, predawn, hourly, ten, replay, retrain = write_inputs(
        tmp_path,
        hourly_status="PASS",
        replay_status="PASS",
        retrain_status="PASS",
    )
    write_artifact(artifact, ordinal_smoothing={"enabled": True})

    payload = build_payload(
        artifact_path=artifact,
        predawn_repair=predawn,
        candidate_hourly=hourly,
        candidate_ten_minute=ten,
        replay=replay,
        retrain_location_gate=retrain,
    )

    assert payload["status"] == "BLOCK"
    assert payload["blockers"][0]["gate"] == "artifact_smoothing_policy"
