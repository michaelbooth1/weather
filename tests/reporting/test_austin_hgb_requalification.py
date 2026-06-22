import json
from pathlib import Path

from weather.reporting.austin_hgb_requalification import build_payload, render_report


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def promotion_payload(*, delta_market=0.001, candidate_verdict="BLOCK", cutover="DO_NOT_CUT_OVER", allow=True):
    return {
        "candidate": {
            "verdict": candidate_verdict,
            "cutover_decision": cutover,
        },
        "decisions": {
            "markets": [
                {
                    "market_id": "austin",
                    "city": "Austin",
                    "action": "PROMOTE_CANDIDATE",
                    "verdict": "PASS",
                    "reason": "beats current replay",
                    "metrics": {
                        "candidate_brier": 0.030,
                        "current_brier": 0.034,
                        "market_brier": 0.029 if delta_market > 0 else 0.031,
                        "delta_vs_current": -0.004,
                        "delta_vs_market": delta_market,
                    },
                    "blocked_validation": {"passed": True, "verdict": "PASS"},
                }
            ]
        },
        "promotion_allowlist": {
            "markets": [
                {
                    "market_id": "austin",
                    "action": "PROMOTE_CANDIDATE",
                    "verdict": "PASS",
                    "candidate_permission_allowed": allow,
                    "candidate_serving_allowed": allow,
                    "serving_behavior": "candidate" if allow else "current_or_shadow",
                    "permission_behavior": "candidate_candidate_only" if allow else "current_or_harvest_only",
                }
            ]
        },
    }


def proof_payload(disposition="SHADOW"):
    return {
        "market_dispositions": [
            {
                "market_id": "austin",
                "disposition": disposition,
                "promotion_refresh_action": "PROMOTE_CANDIDATE",
            }
        ]
    }


def exact_payload(status="BLOCK"):
    return {
        "schema_version": "exact_band_distance_zero_calibration_v0.1",
        "status": status,
        "first_blocker": {"detail": "target Brier trails market"},
    }


def quarantine_payload():
    return {
        "artifacts": [
            {
                "market_id": "austin",
                "artifact_kind": "hgb_model",
                "disposition": "historical_only",
                "active_candidate": False,
                "promotable": False,
            }
        ]
    }


def test_austin_hgb_packet_passes_when_serving_is_fail_closed(tmp_path):
    promotion = write_json(tmp_path / "promotion.json", promotion_payload())
    proof = write_json(tmp_path / "proof.json", proof_payload("SHADOW"))
    exact = write_json(tmp_path / "exact.json", exact_payload("BLOCK"))
    quarantine = write_json(tmp_path / "quarantine.json", quarantine_payload())

    payload = build_payload(
        promotion_refresh=promotion,
        proof_packet=proof,
        exact_distance=exact,
        per_location_quarantine=quarantine,
        generated_at_utc="2026-06-22T00:00:00+00:00",
    )
    report = render_report(payload)

    assert payload["status"] == "PASS"
    assert payload["requalification_verdict"] == "BLOCK"
    assert payload["serving_disposition"] == "SHADOW"
    assert payload["summary"]["hard_slice_id"] == "austin_2026_06_22_high_disagreement"
    assert payload["promotion_allowlist"]["effective_promotion_state"] == "SHADOW"
    assert "Austin HGB Requalification" in report
    assert "exact_band_distance_zero_replay" in report


def test_austin_hgb_packet_allows_live_candidate_only_when_all_local_gates_pass(tmp_path):
    promotion = write_json(
        tmp_path / "promotion.json",
        promotion_payload(delta_market=-0.001, candidate_verdict="PASS", cutover="PER_MARKET_ONLY", allow=True),
    )
    proof = write_json(tmp_path / "proof.json", proof_payload("PROMOTE"))
    exact = write_json(tmp_path / "exact.json", exact_payload("PASS"))
    quarantine = write_json(tmp_path / "quarantine.json", quarantine_payload())

    payload = build_payload(
        promotion_refresh=promotion,
        proof_packet=proof,
        exact_distance=exact,
        per_location_quarantine=quarantine,
        generated_at_utc="2026-06-22T00:00:00+00:00",
    )

    assert payload["status"] == "PASS"
    assert payload["requalification_verdict"] == "PASS"
    assert payload["serving_disposition"] == "LIVE_CANDIDATE"
    assert not payload["requalification_blockers"]
