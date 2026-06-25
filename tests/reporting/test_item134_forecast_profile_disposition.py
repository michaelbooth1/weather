import json

from weather.reporting.research.item134_forecast_profile_disposition import (
    SCHEMA_VERSION,
    build_payload,
    write_outputs,
)


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def replay_payload(*, all_pass=False):
    return {
        "verdict": "PASS" if all_pass else "BLOCK",
        "candidate_market_verdict": "PASS" if all_pass else "PARTIAL_PASS",
        "cutover_decision": "READY_FOR_CUTOVER" if all_pass else "DO_NOT_CUT_OVER",
        "artifact": {
            "schema_version": "pooled_feature_band_hgb_forecast_profile_v0.1",
            "feature_schema_version": "toronto_feature_store_v1.6",
            "feature_subset": "forecast_profile",
            "hour_models": list(range(7, 21)),
        },
        "coverage": {
            "candidate_rows": 1000,
            "family_rows": 1000,
            "missing_candidate_rows": 0,
        },
        "aggregate": {"delta_vs_current": -0.002, "delta_vs_market": 0.002},
        "daily_first": {
            "delta_vs_current": -0.002,
            "delta_vs_market": 0.002 if all_pass else 0.004,
        },
        "blocked_validation": {
            "passed": all_pass,
            "verdict": "PASS" if all_pass else "BLOCK",
            "reasons": [] if all_pass else ["daily-first candidate is not within market tolerance"],
            "daily_first": {"delta_vs_market": 0.002 if all_pass else 0.004},
        },
        "by_cutoff_regime": [
            {"group": "early", "n": 400, "delta_vs_current": -0.001, "delta_vs_market": 0.002},
            {"group": "midday", "n": 300, "delta_vs_current": -0.001, "delta_vs_market": 0.002},
            {"group": "late", "n": 300, "delta_vs_current": -0.001, "delta_vs_market": 0.002},
        ],
        "by_forecast_disagreement": [
            {"group": "high_disagreement", "n": 500, "delta_vs_current": -0.001, "delta_vs_market": 0.002},
        ],
        "candidate_shadow_variants": {
            "variant_id": "item134_forecast_profile_v0_1",
            "variant_family": "forecast_profile_calibration",
            "uses_market_features": False,
        },
        "forecast_profile_guardrails": {
            "schema_version": "forecast_profile_guardrails_v0.1",
            "blocked_markets": [] if all_pass else ["austin", "seattle"],
            "rows": [],
        },
        "market_rows": (
            [{"market_id": "atlanta", "verdict": "PASS"}]
            if all_pass
            else [
                {"market_id": "atlanta", "verdict": "PASS"},
                {"market_id": "austin", "verdict": "BLOCK"},
                {"market_id": "miami", "verdict": "SHADOW"},
            ]
        ),
    }


def write_inputs(tmp_path, *, all_pass=False):
    replay = tmp_path / "replay.json"
    served = tmp_path / "served.json"
    positive = tmp_path / "positive.json"
    write_json(replay, replay_payload(all_pass=all_pass))
    write_json(
        served,
        {
            "status": "PASS" if all_pass else "BLOCK",
            "blocker_count": 0 if all_pass else 1,
            "first_blocker": {"detail": "served distribution still blocks"},
        },
    )
    write_json(
        positive,
        {
            "status": "PASS" if all_pass else "BLOCK",
            "blocker_count": 0 if all_pass else 1,
            "first_blocker": {"detail": "positive daily-first evidence still blocks"},
        },
    )
    return replay, served, positive


def test_forecast_profile_disposition_keeps_lane_shadow_when_promotion_gates_block(tmp_path):
    replay, served, positive = write_inputs(tmp_path)

    payload = build_payload(
        replay=replay,
        served_distribution=served,
        positive_daily_first=positive,
    )
    _, report = write_outputs(payload, tmp_path / "out.json", tmp_path / "out.md")

    blockers = {gate["gate"] for gate in payload["blockers"]}
    passes = {gate["gate"] for gate in payload["gates"] if gate["status"] == "PASS"}
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "BLOCK"
    assert payload["disposition"] == "KEEP_SHADOW_DIAGNOSTIC"
    assert payload["promotion_allowed"] is False
    assert "forecast_profile_subset_contract" in passes
    assert "all_hour_replay_coverage" in passes
    assert "current_replay_lift_guardrail" in passes
    assert "lane_separation" in passes
    assert "daily_first_market_tolerance" in blockers
    assert "high_disagreement_guardrail" in blockers
    assert "per_market_promotion_gate" in blockers
    assert "served_distribution_contract" in blockers
    assert "positive_daily_first_gate" in blockers
    assert "Item 134 Forecast-Profile Disposition" in report.read_text(encoding="utf-8")


def test_forecast_profile_disposition_can_pass_when_all_gates_clear(tmp_path):
    replay, served, positive = write_inputs(tmp_path, all_pass=True)

    payload = build_payload(
        replay=replay,
        served_distribution=served,
        positive_daily_first=positive,
    )

    assert payload["status"] == "PASS"
    assert payload["disposition"] == "PROMOTION_READY"
    assert payload["promotion_allowed"] is True
    assert payload["blocker_count"] == 0
