import json

from weather.reporting.research.item147_winner_centering_disposition import (
    SCHEMA_VERSION,
    build_payload,
    write_outputs,
)


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_inputs(tmp_path, *, all_pass=False):
    replay = tmp_path / "replay.json"
    hourly = tmp_path / "hourly.json"
    exact = tmp_path / "exact.json"
    repair = tmp_path / "repair.json"
    positive = tmp_path / "positive.json"
    no_go = tmp_path / "no_go.json"

    write_json(
        replay,
        {
            "verdict": "PASS" if all_pass else "PARTIAL_PASS",
            "cutover_decision": "READY_FOR_CUTOVER" if all_pass else "PER_MARKET_ONLY",
            "aggregate": {"delta_vs_current": -0.003, "delta_vs_market": 0.002},
            "daily_first": {"delta_vs_current": -0.003, "delta_vs_market": 0.002},
            "candidate_shadow_variants": {"uses_market_features": False, "variant_id": "item147"},
            "market_rows": (
                [{"market_id": "atlanta", "verdict": "PASS"}]
                if all_pass
                else [
                    {"market_id": "atlanta", "verdict": "PASS"},
                    {"market_id": "austin", "verdict": "BLOCK"},
                    {"market_id": "seattle", "verdict": "BLOCK"},
                ]
            ),
        },
    )
    write_json(
        hourly,
        {
            "candidate_hourly_gate": {
                "status": "PASS",
                "blocker_count": 0,
                "early_morning": {
                    "delta_vs_current": -0.004,
                    "delta_vs_market": -0.001,
                    "winner_variant_probability": 0.43,
                    "winner_market_probability": 0.43,
                },
            }
        },
    )
    write_json(
        exact,
        {
            "status": "PASS" if all_pass else "BLOCK",
            "blocker_count": 0 if all_pass else 1,
            "first_blocker": {"detail": "settlement-distance-0 market gap"},
        },
    )
    write_json(
        repair,
        {
            "status": "PASS" if all_pass else "BLOCK",
            "blocker_count": 0 if all_pass else 1,
            "summary": {"blocked_markets": [] if all_pass else ["seattle"]},
        },
    )
    write_json(
        positive,
        {
            "status": "PASS" if all_pass else "BLOCK",
            "blocker_count": 0 if all_pass else 1,
            "first_blocker": {"detail": "rolling daily-first skill is negative"},
            "acceptance_passed": all_pass,
        },
    )
    write_json(no_go, {"status": "NO_GO", "blocked_market_count": 2})
    return replay, hourly, exact, repair, positive, no_go


def test_disposition_keeps_item147_shadow_when_newer_gates_block(tmp_path):
    replay, hourly, exact, repair, positive, no_go = write_inputs(tmp_path)

    payload = build_payload(
        replay=replay,
        hourly=hourly,
        exact_distance=exact,
        market_repair=repair,
        positive_daily_first=positive,
        no_go=no_go,
    )
    _, report = write_outputs(payload, tmp_path / "out.json", tmp_path / "out.md")

    blockers = {gate["gate"] for gate in payload["blockers"]}
    passes = {gate["gate"] for gate in payload["gates"] if gate["status"] == "PASS"}
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "BLOCK"
    assert payload["disposition"] == "KEEP_SHADOW_DIAGNOSTIC"
    assert "early_hour_candidate_gate" in passes
    assert "aggregate_daily_first_market_tolerance" in passes
    assert "blocked_variant_basket_no_go" in passes
    assert "per_market_promotion_gate" in blockers
    assert "exact_band_distance_zero_gate" in blockers
    assert "market_residual_repair_gate" in blockers
    assert "positive_daily_first_gate" in blockers
    assert "Item 147 Winner-Centering Disposition" in report.read_text(encoding="utf-8")


def test_disposition_can_pass_when_all_gates_clear(tmp_path):
    replay, hourly, exact, repair, positive, no_go = write_inputs(tmp_path, all_pass=True)

    payload = build_payload(
        replay=replay,
        hourly=hourly,
        exact_distance=exact,
        market_repair=repair,
        positive_daily_first=positive,
        no_go=no_go,
    )

    assert payload["status"] == "PASS"
    assert payload["disposition"] == "PROMOTION_READY"
    assert payload["promotion_allowed"] is True
    assert payload["blocker_count"] == 0
