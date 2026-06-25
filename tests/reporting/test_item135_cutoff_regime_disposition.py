import json

from weather.reporting.research.item135_cutoff_regime_disposition import (
    SCHEMA_VERSION,
    build_payload,
    write_outputs,
)


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def threshold(regime, *, status="pass", delta_market=0.001):
    return {
        "regime": regime,
        "status": status,
        "reasons": [] if status == "pass" else [f"{regime} market gap"],
        "daily_first": {
            "n": 100,
            "n_days": 3,
            "delta_vs_current": -0.001,
            "delta_vs_market": delta_market,
        },
    }


def weighting_payload(*, all_pass=False):
    blocked = [] if all_pass else ["early", "midday", "late"]
    return {
        "schema_version": "cutoff_regime_weighting_v0.1",
        "variant": {
            "variant_id": "item135_regime_weighted_forecast_observation_v0_1",
            "variant_family": "cutoff_regime_forecast_observation_weighting",
            "rows": 1000,
            "uses_market_features": False,
        },
        "aggregate": {"delta_vs_current": -0.001, "delta_vs_market": 0.002},
        "daily_first": {"delta_vs_current": -0.001, "delta_vs_market": 0.002},
        "no_leakage_audit": {
            "status": "PASS",
            "market_days": 3,
            "rows": 1000,
            "duplicate_observation_keys": 0,
        },
        "regime_thresholds": [
            threshold("early", status="pass" if all_pass else "blocked", delta_market=0.001 if all_pass else 0.004),
            threshold("midday", status="pass" if all_pass else "blocked", delta_market=0.001 if all_pass else 0.012),
            threshold("late", status="pass" if all_pass else "blocked", delta_market=0.001 if all_pass else 0.007),
            threshold("final_lock_in"),
        ],
        "acceptance": {
            "status": "pass" if all_pass else "blocked",
            "blocked_regimes": blocked,
            "reasons": [f"{regime}: market gap" for regime in blocked],
        },
    }


def write_inputs(tmp_path, *, all_pass=False):
    weighting = tmp_path / "weighting.json"
    item134 = tmp_path / "item134.json"
    served = tmp_path / "served.json"
    positive = tmp_path / "positive.json"
    write_json(weighting, weighting_payload(all_pass=all_pass))
    write_json(
        item134,
        {
            "status": "PASS" if all_pass else "BLOCK",
            "disposition": "PROMOTION_READY" if all_pass else "KEEP_SHADOW_DIAGNOSTIC",
            "first_blocker": {"detail": "item134 still blocks"},
        },
    )
    write_json(
        served,
        {
            "status": "PASS" if all_pass else "BLOCK",
            "first_blocker": {"detail": "served distribution still blocks"},
        },
    )
    write_json(
        positive,
        {
            "status": "PASS" if all_pass else "BLOCK",
            "first_blocker": {"detail": "positive daily-first still blocks"},
        },
    )
    return weighting, item134, served, positive


def test_cutoff_regime_disposition_blocks_when_regime_and_upstream_gates_block(tmp_path):
    weighting, item134, served, positive = write_inputs(tmp_path)

    payload = build_payload(
        weighting=weighting,
        item134=item134,
        served_distribution=served,
        positive_daily_first=positive,
    )
    _, report = write_outputs(payload, tmp_path / "out.json", tmp_path / "out.md")

    blockers = {gate["gate"] for gate in payload["blockers"]}
    passes = {gate["gate"] for gate in payload["gates"] if gate["status"] == "PASS"}
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "BLOCK"
    assert payload["disposition"] == "KEEP_SHADOW_DIAGNOSTIC"
    assert "all_hour_regime_replay_coverage" in passes
    assert "current_replay_lift_guardrail" in passes
    assert "final_lock_in_threshold" in passes
    assert "lane_separation" in passes
    assert "regime_thresholds" in blockers
    assert "upstream_forecast_profile_disposition" in blockers
    assert "served_distribution_contract" in blockers
    assert "positive_daily_first_gate" in blockers
    assert "Item 135 Cutoff-Regime Disposition" in report.read_text(encoding="utf-8")


def test_cutoff_regime_disposition_can_pass_when_all_gates_clear(tmp_path):
    weighting, item134, served, positive = write_inputs(tmp_path, all_pass=True)

    payload = build_payload(
        weighting=weighting,
        item134=item134,
        served_distribution=served,
        positive_daily_first=positive,
    )

    assert payload["status"] == "PASS"
    assert payload["disposition"] == "PROMOTION_READY"
    assert payload["promotion_allowed"] is True
    assert payload["blocker_count"] == 0
