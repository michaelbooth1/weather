import json

from weather.reporting.research.item160_candidate_viability_audit import (
    SCHEMA_VERSION,
    build_payload,
    write_outputs,
)


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_candidate(
    root,
    name,
    *,
    validation_evidence="active_replay_contract",
    registry_contract=True,
    replay_delta=-0.002,
    blocked_passed=True,
    hourly_status="PASS",
    ten_status="PASS",
    probe_status=None,
    served_status=None,
    served_blocking_gate="broad_claim_gate",
    positive_status=None,
):
    replay = root / f"{name}_replay.json"
    hourly = root / f"{name}_hourly.json"
    ten = root / f"{name}_ten.json"
    probe = root / f"{name}_probe.json"
    served = root / f"{name}_served.json"
    positive = root / f"{name}_positive.json"
    write_json(
        replay,
        {
            "validation_evidence": validation_evidence,
            "verdict": "PASS" if blocked_passed else "BLOCK",
            "cutover_decision": "READY_FOR_CUTOVER" if blocked_passed else "DO_NOT_CUT_OVER",
            "row_export_metric_passed": replay_delta <= 0.003,
            "aggregate": {"delta_vs_current": -0.004, "delta_vs_market": replay_delta},
            "blocked_validation": {
                "passed": blocked_passed,
                "metric_passed": replay_delta <= 0.003,
                "reasons": [] if blocked_passed else ["candidate is not within market tolerance"],
            },
            "candidate_shadow_variants": {
                "variant_id": name,
                "registry_contract": registry_contract,
            },
            "market_rows": [],
        },
    )
    write_json(
        hourly,
        {
            "candidate_hourly_gate": {
                "status": hourly_status,
                "blocker_count": 0 if hourly_status == "PASS" else 1,
                "first_blocker": {"detail": "early-hour candidate Brier trails market"},
                "early_morning": {"delta_vs_market": -0.001 if hourly_status == "PASS" else 0.006},
            }
        },
    )
    write_json(
        ten,
        {
            "candidate_ten_minute_gate": {
                "status": ten_status,
                "blocker_count": 0 if ten_status == "PASS" else 1,
                "first_blocker": {"detail": "candidate weak-slot Brier trails market"},
                "weak_slot_overlap": {"delta_vs_market": -0.002 if ten_status == "PASS" else 0.01},
            }
        },
    )
    if probe_status:
        write_json(probe, {"status": probe_status, "exception": "source lineage rejected"})
    if served_status:
        write_json(
            served,
            {
                "status": served_status,
                "acceptance_passed": served_status == "PASS",
                "blocker_count": 0 if served_status == "PASS" else 1,
                "first_blocker": {"detail": "fleet observability must pass"},
                "gates": [
                    {
                        "gate": served_blocking_gate,
                        "status": "BLOCK" if served_status != "PASS" else "PASS",
                        "detail": "fleet observability must pass",
                    }
                ],
            },
        )
    if positive_status:
        write_json(
            positive,
            {
                "status": positive_status,
                "acceptance_passed": positive_status == "PASS",
                "blocker_count": 0 if positive_status == "PASS" else 1,
                "first_blocker": {"detail": "rolling daily-first skill is negative"},
                "gates": [
                    {
                        "gate": "rolling_daily_first_non_negative",
                        "status": "BLOCK" if positive_status != "PASS" else "PASS",
                        "detail": "rolling daily-first skill is negative",
                    }
                ],
            },
        )
    return {
        "candidate_id": name,
        "variant_id": name,
        "replay": replay,
        "hourly": hourly,
        "ten_minute": ten,
        "countability_probe": probe if probe_status else None,
        "served_distribution": served if served_status else None,
        "positive_gate": positive if positive_status else None,
        "basis": "test",
    }


def test_audit_classifies_ready_countability_and_performance_candidates(tmp_path):
    ready = write_candidate(tmp_path, "ready")
    countability = write_candidate(
        tmp_path,
        "surrogate_metric",
        validation_evidence="row_export_surrogate",
        registry_contract=False,
        probe_status="EXPECTED_REJECTED",
    )
    performance = write_candidate(
        tmp_path,
        "active_bad_hourly",
        blocked_passed=False,
        hourly_status="BLOCK",
        replay_delta=0.007,
    )

    payload = build_payload([ready, countability, performance])
    _, report = write_outputs(payload, tmp_path / "audit.json", tmp_path / "audit.md")

    by_id = {row["candidate_id"]: row for row in payload["candidates"]}
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "PASS"
    assert payload["promotion_ready_candidate_count"] == 1
    assert payload["model_ready_candidate_count"] == 1
    assert by_id["ready"]["status"] == "PROMOTION_READY_CANDIDATE"
    assert by_id["surrogate_metric"]["status"] == "COUNTABILITY_BLOCKED"
    assert by_id["active_bad_hourly"]["status"] == "PERFORMANCE_BLOCKED"
    assert "Item 160 Candidate Viability Audit" in report.read_text(encoding="utf-8")


def test_audit_blocks_when_no_candidate_is_promotion_ready(tmp_path):
    candidate = write_candidate(
        tmp_path,
        "surrogate_metric",
        validation_evidence="row_export_surrogate",
        registry_contract=False,
    )

    payload = build_payload([candidate])

    assert payload["status"] == "BLOCK"
    assert payload["promotion_ready_candidate_count"] == 0
    assert payload["best_metric_candidate"] == "surrogate_metric"


def test_audit_keeps_model_ready_candidate_blocked_by_readiness(tmp_path):
    candidate = write_candidate(
        tmp_path,
        "active_ready_but_fleet_blocked",
        served_status="BLOCK",
        served_blocking_gate="broad_claim_gate",
        positive_status="BLOCK",
    )

    payload = build_payload([candidate])
    row = payload["candidates"][0]

    assert payload["status"] == "BLOCK"
    assert payload["promotion_ready_candidate_count"] == 0
    assert payload["model_ready_candidate_count"] == 1
    assert payload["best_model_ready_candidate"] == "active_ready_but_fleet_blocked"
    assert row["status"] == "PRODUCTION_READINESS_BLOCKED"
    assert row["next_action"] == "fleet observability must pass"
