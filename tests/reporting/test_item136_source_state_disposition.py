import json

from weather.reporting.item136_source_state_disposition import (
    SCHEMA_VERSION,
    build_payload,
    write_outputs,
)


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def reliability_payload(*, all_pass=False):
    return {
        "schema_version": "forecast_source_state_reliability_v0.1",
        "variant": {
            "variant_id": "item136_source_state_reliability_v0_1",
            "rows": 1000,
            "uses_market_features": False,
        },
        "daily_first": {
            "delta_vs_current": -0.001,
            "delta_vs_raw_forecast": -0.001 if all_pass else 0.001,
        },
        "aggregate": {"delta_vs_current": -0.001},
        "by_source_state_slice": [
            {"group": "all_fresh", "n": 800, "delta_vs_raw_forecast": 0.0, "delta_vs_current": -0.001},
            {
                "group": "degraded_source",
                "n": 200,
                "delta_vs_raw_forecast": -0.001 if all_pass else 0.001,
                "delta_vs_current": -0.001,
            },
        ],
        "by_forecast_disagreement": [
            {
                "group": "high_disagreement",
                "n": 400,
                "delta_vs_raw_forecast": -0.001 if all_pass else 0.001,
                "delta_vs_current": -0.001,
            },
        ],
        "quote_risk_reporting": {
            "status": "shadow_only",
            "rows": 1000,
            "risky_rows": 400,
            "reason_field": "source_state_reliability_reason",
            "alpha_field": "source_state_reliability_alpha",
            "risk_bucket_field": "source_state_risk_bucket",
            "top_reasons": [{"reason": "limited forecast source count", "rows": 400}],
        },
        "market_thresholds": [],
        "acceptance": {
            "status": "pass" if all_pass else "blocked",
            "reasons": [] if all_pass else ["degraded-source slice does not improve raw forecast-profile skill"],
            "blocked_markets": [] if all_pass else ["chicago"],
        },
    }


def write_inputs(tmp_path, *, all_pass=False):
    reliability = tmp_path / "reliability.json"
    item134 = tmp_path / "item134.json"
    item135 = tmp_path / "item135.json"
    served = tmp_path / "served.json"
    positive = tmp_path / "positive.json"
    write_json(reliability, reliability_payload(all_pass=all_pass))
    for path, name in [(item134, "item134"), (item135, "item135"), (served, "served"), (positive, "positive")]:
        write_json(
            path,
            {
                "status": "PASS" if all_pass else "BLOCK",
                "disposition": "PROMOTION_READY" if all_pass else "KEEP_SHADOW_DIAGNOSTIC",
                "first_blocker": {"detail": f"{name} still blocks"},
            },
        )
    return reliability, item134, item135, served, positive


def test_source_state_disposition_blocks_when_thresholds_and_upstream_gates_block(tmp_path):
    reliability, item134, item135, served, positive = write_inputs(tmp_path)

    payload = build_payload(
        reliability=reliability,
        item134=item134,
        item135=item135,
        served_distribution=served,
        positive_daily_first=positive,
    )
    _, report = write_outputs(payload, tmp_path / "out.json", tmp_path / "out.md")

    blockers = {gate["gate"] for gate in payload["blockers"]}
    passes = {gate["gate"] for gate in payload["gates"] if gate["status"] == "PASS"}
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "BLOCK"
    assert payload["disposition"] == "KEEP_SHADOW_DIAGNOSTIC"
    assert "all_hour_source_state_replay_coverage" in passes
    assert "explanation_and_quote_risk_reason_surface" in passes
    assert "current_replay_lift_guardrail" in passes
    assert "lane_separation" in passes
    assert "source_state_reliability_thresholds" in blockers
    assert "upstream_forecast_profile_disposition" in blockers
    assert "upstream_cutoff_regime_disposition" in blockers
    assert "served_distribution_contract" in blockers
    assert "positive_daily_first_gate" in blockers
    assert "Item 136 Source-State Reliability Disposition" in report.read_text(encoding="utf-8")


def test_source_state_disposition_can_pass_when_all_gates_clear(tmp_path):
    reliability, item134, item135, served, positive = write_inputs(tmp_path, all_pass=True)

    payload = build_payload(
        reliability=reliability,
        item134=item134,
        item135=item135,
        served_distribution=served,
        positive_daily_first=positive,
    )

    assert payload["status"] == "PASS"
    assert payload["disposition"] == "PROMOTION_READY"
    assert payload["promotion_allowed"] is True
    assert payload["blocker_count"] == 0
