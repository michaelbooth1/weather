import json
from pathlib import Path

from weather.reporting.research.item48_promotion_readiness_acceptance import build_payload, render_report


def write_json(path: Path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def market_row(
    market_id="atlanta",
    *,
    action="PROMOTE_CANDIDATE",
    delta_vs_current=-0.010,
    delta_vs_market=-0.004,
    permission=True,
    serving=True,
    blocked_validation=True,
):
    return {
        "market_id": market_id,
        "action": action,
        "serving_behavior": "candidate" if serving else "shadow",
        "permission_behavior": "candidate_candidate_only" if permission else "current_or_harvest_only",
        "candidate_permission_allowed": permission,
        "candidate_serving_allowed": serving,
        "metrics": {
            "candidate_brier": 0.030,
            "current_brier": 0.040,
            "market_brier": 0.034,
            "delta_vs_current": delta_vs_current,
            "delta_vs_market": delta_vs_market,
        },
        "blocked_validation": {
            "passed": blocked_validation,
            "verdict": "PASS" if blocked_validation else "BLOCK",
        },
    }


def promotion_payload(
    *,
    markets=None,
    candidate_verdict="PASS",
    blocked_validation=True,
    source_status="PASS",
    hourly_applied=True,
    ten_minute_applied=True,
    uses_market_features=False,
    core_claim=True,
):
    return {
        "family_unit": "F",
        "candidate": {
            "verdict": candidate_verdict,
            "cutover_decision": "PER_MARKET_ONLY",
            "aggregate": {
                "rows": 100,
                "candidate_brier": 0.030,
                "current_brier": 0.041,
                "market_brier": 0.035,
                "delta_vs_current": -0.011,
                "delta_vs_market": -0.005,
            },
            "blocked_validation": {
                "passed": blocked_validation,
                "verdict": "PASS" if blocked_validation else "BLOCK",
            },
            "candidate_shadow_variants": {
                "variant_id": "item224_active_timesplit_logistic_repair_v0_1",
                "uses_market_features": uses_market_features,
                "active_registry_contract": {
                    "variant_id": "item224_active_timesplit_logistic_repair_v0_1",
                },
            },
        },
        "model_skill_claims": {
            "weather_only_core_model": {
                "broad_market_skill_claim_allowed": core_claim,
                "reason": "candidate excludes market inputs",
            }
        },
        "source_missingness_location_gate": {
            "status": source_status,
            "blocker_count": 0 if source_status == "PASS" else 1,
            "blockers": [],
        },
        "readiness": {
            "hourly_performance_mitigation": {
                "applied": hourly_applied,
                "candidate_hourly_status": "PASS" if hourly_applied else "BLOCK",
                "candidate_variant_id": "item224_active_timesplit_logistic_repair_v0_1",
            },
            "ten_minute_performance_mitigation": {
                "applied": ten_minute_applied,
                "candidate_ten_minute_status": "PASS" if ten_minute_applied else "BLOCK",
                "candidate_variant_id": "item224_active_timesplit_logistic_repair_v0_1",
            },
            "blockers": [
                {
                    "category": "live_forward_slo",
                    "severity": "block",
                    "detail": "live-forward SLO remains blocked",
                }
            ],
        },
        "promotion_allowlist": {
            "candidate_id": "item224_active_timesplit_logistic_repair_v0_1",
            "markets": markets
            if markets is not None
            else [
                market_row("atlanta"),
                market_row("austin"),
            ],
        },
    }


def proof_payload(markets=("atlanta", "austin")):
    return {
        "gates": [
            {
                "gate": "live_forward_evidence_state",
                "status": "BLOCK",
                "detail": "live-forward evidence is not ready",
            }
        ],
        "market_dispositions": [
            {
                "market_id": market,
                "promotion_refresh_action": "PROMOTE_CANDIDATE",
                "disposition": "SHADOW",
            }
            for market in markets
        ],
    }


def test_acceptance_passes_all_promote_active_candidate_and_preserves_external_blockers(tmp_path):
    promotion = write_json(tmp_path / "promotion.json", promotion_payload())
    proof = write_json(tmp_path / "proof.json", proof_payload())

    payload = build_payload(promotion, proof)
    report = render_report(payload)

    assert payload["schema_version"] == "item48_promotion_readiness_acceptance_v0.1"
    assert payload["status"] == "PASS"
    assert payload["item48_acceptance_passed"] is True
    assert payload["serving_parity_status"] == "PASS"
    assert payload["production_cutover_status"] == "BLOCK"
    assert payload["external_production_blocker_count"] == 2
    assert payload["summary"]["all_markets_promoted"] is True
    assert payload["summary"]["proof_packet_actions"]["promotion_refresh_action_counts"] == {"PROMOTE_CANDIDATE": 2}
    assert "External Production Blockers" in report


def test_acceptance_blocks_shadow_or_blocked_market(tmp_path):
    promotion = write_json(
        tmp_path / "promotion.json",
        promotion_payload(
            markets=[
                market_row("atlanta"),
                market_row("austin", action="KEEP_SHADOW"),
            ]
        ),
    )
    proof = write_json(tmp_path / "proof.json", proof_payload())

    payload = build_payload(promotion, proof)

    assert payload["status"] == "BLOCK"
    assert payload["serving_parity_status"] == "BLOCK"
    assert payload["first_blocker"]["category"] == "market_action"
    assert "austin action is KEEP_SHADOW" in payload["first_blocker"]["detail"]


def test_acceptance_blocks_when_candidate_mitigation_missing(tmp_path):
    promotion = write_json(
        tmp_path / "promotion.json",
        promotion_payload(hourly_applied=False),
    )
    proof = write_json(tmp_path / "proof.json", proof_payload())

    payload = build_payload(promotion, proof)

    assert payload["status"] == "BLOCK"
    assert payload["first_blocker"]["category"] == "candidate_hourly_mitigation"
    assert payload["summary"]["all_markets_promoted"] is True
