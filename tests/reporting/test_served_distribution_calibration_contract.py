import json

from weather.reporting.served_distribution_calibration_contract import (
    SCHEMA_VERSION,
    build_payload,
    write_outputs,
)


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_inputs(
    tmp_path,
    *,
    active_replay=False,
    hourly_status="BLOCK",
    exact_status="BLOCK",
    bottom_status="BLOCK",
    broad_status="BLOCK",
    model_location_status=None,
    production_readiness_status=None,
):
    serving = tmp_path / "serving.json"
    retrain = tmp_path / "retrain.json"
    replay = tmp_path / "replay.json"
    hourly = tmp_path / "hourly.json"
    ten = tmp_path / "ten.json"
    exact = tmp_path / "exact.json"
    bottom = tmp_path / "bottom.json"
    promotion = tmp_path / "promotion.json"

    write_json(
        serving,
        {
            "status": "BLOCK",
            "ordinal_smoothing_train_serve_skew_fixed": True,
            "acceptance_passed": False,
            "blocker_count": 1,
        },
    )
    write_json(
        retrain,
        {
            "status": broad_status,
            "broad_core_model_claim_allowed": broad_status == "PASS",
            "model_location_gate_status": model_location_status,
            "model_location_claim_evidence_allowed": None if model_location_status is None else model_location_status == "PASS",
            "model_location_blocker_count": None if model_location_status is None else 0 if model_location_status == "PASS" else 1,
            "production_readiness_status": production_readiness_status,
            "production_readiness_blocker_count": None if production_readiness_status is None else 0 if production_readiness_status == "PASS" else 1,
            "blocker_count": 0 if broad_status == "PASS" else 1,
            "first_blocker": {"detail": "runtime schema mismatch"},
            "blockers": [
                {
                    "gate": "promotion_refresh_broad_claim",
                    "status": "BLOCK",
                    "detail": "fleet observability must be OK/PASS before location validation counts",
                }
            ] if production_readiness_status == "BLOCK" else [],
        },
    )
    write_json(
        replay,
        {
            "verdict": "PASS" if active_replay else "BLOCK",
            "cutover_decision": "READY_FOR_CUTOVER" if active_replay else "DO_NOT_CUT_OVER",
            "validation_evidence": "active_replay_contract" if active_replay else "row_export_surrogate",
            "blocked_validation": {
                "verdict": "PASS" if active_replay else "BLOCK",
                "passed": active_replay,
                "reasons": [] if active_replay else ["row-export summary is not active replay/export contract evidence"],
            },
            "candidate_shadow_variants": {
                "uses_market_features": False,
                "registry_contract": active_replay,
                "variant_id": "candidate",
            },
            "aggregate": {
                "delta_vs_current": -0.01,
                "delta_vs_market": -0.01 if active_replay else 0.009,
            },
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
                    "delta_vs_market": -0.002 if hourly_status == "PASS" else 0.0048,
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
                "weak_slot_overlap": {"delta_vs_current": -0.029, "delta_vs_market": -0.009},
            }
        },
    )
    write_json(
        exact,
        {
            "status": exact_status,
            "blocker_count": 0 if exact_status == "PASS" else 1,
            "first_blocker": {"detail": "exact-band early market gap"},
        },
    )
    write_json(
        bottom,
        {
            "status": bottom_status,
            "blocker_count": 0 if bottom_status == "PASS" else 1,
            "first_blocker": {"detail": "bottom-location current regression"},
        },
    )
    write_json(
        promotion,
        {
            "model_skill_claims": {
                "weather_only_core_model": {"broad_market_skill_claim_allowed": broad_status == "PASS"},
                "market_informed_quote_risk": {"counts_toward_core_skill_claim": False},
            }
        },
    )
    return serving, retrain, replay, hourly, ten, exact, bottom, promotion


def test_contract_blocks_row_export_and_uncleared_served_distribution_gates(tmp_path):
    serving, retrain, replay, hourly, ten, exact, bottom, promotion = write_inputs(tmp_path)

    payload = build_payload(
        serving_ordinal_gate=serving,
        retrain_location_gate=retrain,
        replay=replay,
        candidate_hourly=hourly,
        candidate_ten_minute=ten,
        exact_distance=exact,
        bottom_location=bottom,
        promotion_refresh=promotion,
    )
    _, report = write_outputs(payload, tmp_path / "out.json", tmp_path / "out.md")

    blockers = {gate["gate"] for gate in payload["blockers"]}
    passes = {gate["gate"] for gate in payload["gates"] if gate["status"] == "PASS"}
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "BLOCK"
    assert payload["served_distribution_contract_specified"] is True
    assert "contract_schema" in passes
    assert "serving_parity_prerequisite" in passes
    assert "weak_slot_ten_minute_gate" in passes
    assert "lane_separation" in passes
    assert "active_replay_contract" in blockers
    assert "early_hour_hourly_gate" in blockers
    assert "exact_band_distance_zero_gate" in blockers
    assert "bottom_location_gate" in blockers
    assert "broad_claim_gate" in blockers
    assert "Served-Distribution Calibration Contract" in report.read_text(encoding="utf-8")


def test_contract_passes_when_active_replay_and_all_required_gates_clear(tmp_path):
    serving, retrain, replay, hourly, ten, exact, bottom, promotion = write_inputs(
        tmp_path,
        active_replay=True,
        hourly_status="PASS",
        exact_status="PASS",
        bottom_status="PASS",
        broad_status="PASS",
    )

    payload = build_payload(
        serving_ordinal_gate=serving,
        retrain_location_gate=retrain,
        replay=replay,
        candidate_hourly=hourly,
        candidate_ten_minute=ten,
        exact_distance=exact,
        bottom_location=bottom,
        promotion_refresh=promotion,
    )

    assert payload["status"] == "PASS"
    assert payload["acceptance_passed"] is True
    assert payload["blocker_count"] == 0


def test_contract_accepts_model_location_pass_while_broad_claim_readiness_blocks(tmp_path):
    serving, retrain, replay, hourly, ten, exact, bottom, promotion = write_inputs(
        tmp_path,
        active_replay=True,
        hourly_status="PASS",
        exact_status="PASS",
        bottom_status="PASS",
        broad_status="BLOCK",
        model_location_status="PASS",
        production_readiness_status="BLOCK",
    )

    payload = build_payload(
        serving_ordinal_gate=serving,
        retrain_location_gate=retrain,
        replay=replay,
        candidate_hourly=hourly,
        candidate_ten_minute=ten,
        exact_distance=exact,
        bottom_location=bottom,
        promotion_refresh=promotion,
    )

    gates = {gate["gate"]: gate for gate in payload["gates"]}
    assert payload["status"] == "PASS"
    assert payload["acceptance_passed"] is True
    assert payload["model_served_distribution_status"] == "PASS"
    assert payload["broad_core_model_claim_allowed"] is False
    assert payload["production_readiness_status"] == "BLOCK"
    assert payload["production_readiness_blockers"][0]["gate"] == "promotion_refresh_broad_claim"
    assert gates["broad_claim_gate"]["status"] == "PASS"
    assert "broad claim remains readiness-blocked" in gates["broad_claim_gate"]["detail"]
