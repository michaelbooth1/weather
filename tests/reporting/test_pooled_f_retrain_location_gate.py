import json
import pickle

from weather.model.feature_store import FEATURE_SCHEMA_VERSION
from weather.reporting.pooled_f_retrain_location_gate import (
    SCHEMA_VERSION,
    build_payload,
    write_outputs,
)


def write_artifact(path, *, feature_schema, validation_ok=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(
            {
                "schema_version": "pooled_feature_band_hgb_v0.3",
                "feature_schema_version": feature_schema,
                "trained_at": "2026-06-22T00:00:00",
                "family_unit": "F",
                "objective": "binary_market_band_brier_source_reliability",
                "prediction_mode": "band_binary",
                "models": {"7": {"feature_names": ["current_temp"]}},
                "blocked_validation": {"schema_version": "blocked_validation_v0.1", "ok": validation_ok},
            },
            handle,
        )


def write_training_report(path):
    path.write_text(
        "# F-Family Pooled Band Model\n\n## Blocked Validation Audit\n\n| Hour | Audit |\n| :--- | :--- |\n| 07:00 | PASS |\n",
        encoding="utf-8",
    )


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_pass_inputs(tmp_path):
    artifact = tmp_path / "artifact.pkl"
    report = tmp_path / "training.md"
    replay = tmp_path / "replay.json"
    promotion = tmp_path / "promotion.json"
    predawn = tmp_path / "predawn.json"
    bottom = tmp_path / "bottom.json"
    exact = tmp_path / "exact.json"

    write_artifact(artifact, feature_schema=FEATURE_SCHEMA_VERSION)
    write_training_report(report)
    write_json(
        replay,
        {
            "verdict": "PASS",
            "candidate_market_verdict": "PASS",
            "cutover_decision": "READY_FOR_CUTOVER",
            "artifact": {"feature_schema_version": FEATURE_SCHEMA_VERSION, "artifact_hash": "abc"},
            "blocked_validation": {"verdict": "PASS", "reasons": []},
            "aggregate": {"delta_vs_current": -0.01, "delta_vs_market": -0.02},
            "daily_first": {"delta_vs_current": -0.01, "delta_vs_market": -0.02},
        },
    )
    write_json(
        promotion,
        {
            "readiness": {"status": "PASS", "blockers": []},
            "model_skill_claims": {
                "weather_only_core_model": {
                    "broad_market_skill_claim_allowed": True,
                    "daily_first_passed": True,
                    "delta_vs_market": -0.02,
                    "reason": "clear",
                }
            },
            "early_hour_promotion_blocker": {
                "status": "PASS",
                "promotion_allowed": True,
                "blocker_count": 0,
            },
            "source_missingness_location_gate": {"status": "PASS", "blockers": []},
            "decisions": {"action_counts": {"PROMOTE_CANDIDATE": 1}, "promote_markets": ["nyc"]},
        },
    )
    write_json(predawn, {"schema_version": "predawn_weak_slot_repair_v0.1", "status": "PASS", "blocker_count": 0})
    write_json(bottom, {"schema_version": "bottom_location_winner_centering_v0.1", "status": "PASS", "blocker_count": 0})
    write_json(exact, {"schema_version": "exact_band_distance_zero_calibration_v0.1", "status": "PASS", "blocker_count": 0})
    return artifact, report, replay, promotion, predawn, bottom, exact


def test_gate_blocks_stale_schema_and_failed_downstream_evidence(tmp_path):
    artifact, report, replay, promotion, predawn, bottom, exact = write_pass_inputs(tmp_path)
    write_artifact(artifact, feature_schema="toronto_feature_store_v1.13")
    write_json(
        replay,
        {
            "verdict": "BLOCK",
            "cutover_decision": "DO_NOT_CUT_OVER",
            "artifact": {"feature_schema_version": "toronto_feature_store_v1.13"},
            "blocked_validation": {"verdict": "BLOCK", "reasons": ["daily-first candidate is not within market tolerance"]},
            "aggregate": {"delta_vs_current": -0.001, "delta_vs_market": 0.008},
        },
    )
    write_json(
        promotion,
        {
            "readiness": {
                "status": "OPEN",
                "blockers": [{"category": "candidate_market_skill", "detail": "aggregate trails market"}],
            },
            "model_skill_claims": {
                "weather_only_core_model": {
                    "broad_market_skill_claim_allowed": False,
                    "reason": "core candidate still needs aggregate delta_vs_market <= 0",
                }
            },
            "early_hour_promotion_blocker": {
                "status": "BLOCK",
                "promotion_allowed": False,
                "blocker_count": 1,
                "blockers": [{"detail": "candidate ten-minute gate is BLOCK"}],
            },
            "source_missingness_location_gate": {
                "status": "BLOCK",
                "blockers": [{"detail": "miami all-fresh candidate trails market"}],
            },
        },
    )
    write_json(bottom, {"status": "BLOCK", "blocker_count": 1, "first_blocker": {"detail": "bottom market blocked"}})

    payload = build_payload(
        artifact_path=artifact,
        training_report=report,
        candidate_replay=replay,
        promotion_refresh=promotion,
        predawn_repair=predawn,
        bottom_location=bottom,
        exact_distance=exact,
    )
    _, report_out = write_outputs(payload, tmp_path / "out.json", tmp_path / "out.md")

    blocker_names = {gate["gate"] for gate in payload["blockers"]}
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "BLOCK"
    assert payload["broad_core_model_claim_allowed"] is False
    assert "artifact_runtime_schema" in blocker_names
    assert "paired_candidate_replay" in blocker_names
    assert "promotion_refresh_broad_claim" in blocker_names
    assert "bottom_location_gate" in blocker_names
    assert "Pooled F Retrain/Re-Export Location Gate" in report_out.read_text(encoding="utf-8")


def test_gate_passes_when_artifact_and_all_required_reports_clear(tmp_path):
    artifact, report, replay, promotion, predawn, bottom, exact = write_pass_inputs(tmp_path)

    payload = build_payload(
        artifact_path=artifact,
        training_report=report,
        candidate_replay=replay,
        promotion_refresh=promotion,
        predawn_repair=predawn,
        bottom_location=bottom,
        exact_distance=exact,
    )

    assert payload["status"] == "PASS"
    assert payload["broad_core_model_claim_allowed"] is True
    assert payload["model_location_gate_status"] == "PASS"
    assert payload["production_readiness_status"] == "PASS"
    assert payload["blocker_count"] == 0


def test_gate_reports_readiness_blocker_when_broad_claim_passes(tmp_path):
    artifact, report, replay, promotion, predawn, bottom, exact = write_pass_inputs(tmp_path)
    write_json(
        promotion,
        {
            "readiness": {
                "status": "OPEN",
                "blockers": [{"detail": "fleet observability must pass"}],
            },
            "model_skill_claims": {
                "weather_only_core_model": {
                    "broad_market_skill_claim_allowed": True,
                    "daily_first_passed": True,
                    "delta_vs_market": -0.02,
                    "reason": "core candidate clears aggregate and daily-first market-skill gates",
                }
            },
            "early_hour_promotion_blocker": {
                "status": "PASS",
                "promotion_allowed": True,
                "blocker_count": 0,
            },
            "source_missingness_location_gate": {"status": "PASS", "blockers": []},
        },
    )

    payload = build_payload(
        artifact_path=artifact,
        training_report=report,
        candidate_replay=replay,
        promotion_refresh=promotion,
        predawn_repair=predawn,
        bottom_location=bottom,
        exact_distance=exact,
    )

    gate = next(row for row in payload["gates"] if row["gate"] == "promotion_refresh_broad_claim")
    assert payload["status"] == "BLOCK"
    assert gate["detail"] == "fleet observability must pass"
    assert payload["broad_core_model_claim_allowed"] is False
    assert payload["model_location_gate_status"] == "PASS"
    assert payload["model_location_blocker_count"] == 0
    assert payload["production_readiness_status"] == "BLOCK"
    assert payload["production_readiness_blocker_count"] == 1


def test_gate_treats_current_code_soak_as_readiness_when_candidate_weak_slots_clear(tmp_path):
    artifact, report, replay, promotion, predawn, bottom, exact = write_pass_inputs(tmp_path)
    lineage = {
        "gate_status": "PASS",
        "variant_match": True,
        "corpus_match": True,
        "freshness": {"status": "PASS"},
    }
    write_json(
        promotion,
        {
            "readiness": {
                "status": "PASS",
                "blockers": [],
            },
            "model_skill_claims": {
                "weather_only_core_model": {
                    "broad_market_skill_claim_allowed": True,
                    "daily_first_passed": True,
                    "delta_vs_market": -0.02,
                    "reason": "core candidate clears aggregate and daily-first market-skill gates",
                }
            },
            "early_hour_promotion_blocker": {
                "status": "BLOCK",
                "promotion_allowed": False,
                "blocker_count": 1,
                "blockers": [
                    {
                        "category": "current_code_soak",
                        "detail": "current-code soak remains a production-readiness blocker, status=BLOCK",
                    }
                ],
                "candidate_gates": {
                    "hourly": lineage,
                    "ten_minute": lineage,
                },
                "broad_replay": {
                    "active_registry_contract_present": True,
                    "within_market_tolerance": True,
                },
            },
            "source_missingness_location_gate": {"status": "PASS", "blockers": []},
        },
    )

    payload = build_payload(
        artifact_path=artifact,
        training_report=report,
        candidate_replay=replay,
        promotion_refresh=promotion,
        predawn_repair=predawn,
        bottom_location=bottom,
        exact_distance=exact,
    )

    gate = next(row for row in payload["gates"] if row["gate"] == "hourly_ten_minute_weak_slot_gate")
    assert payload["status"] == "BLOCK"
    assert gate["detail"] == "current-code soak remains a production-readiness blocker, status=BLOCK"
    assert payload["model_location_gate_status"] == "PASS"
    assert payload["model_location_blocker_count"] == 0
    assert payload["production_readiness_status"] == "BLOCK"
    assert payload["production_readiness_blocker_count"] == 1
