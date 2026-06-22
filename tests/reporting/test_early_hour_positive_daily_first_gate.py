import json

from weather.reporting.early_hour_positive_daily_first_gate import (
    SCHEMA_VERSION,
    build_payload,
    write_outputs,
)


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_inputs(
    tmp_path,
    *,
    claim_allowed=False,
    rolling_skill=-0.2,
    positive_days=1,
    market_days=36,
    hourly_status="BLOCK",
    contract_status="BLOCK",
):
    progress = tmp_path / "progress.json"
    contract = tmp_path / "contract.json"
    hourly = tmp_path / "hourly.json"
    ten = tmp_path / "ten.json"
    write_json(
        progress,
        {
            "core_model_trend_claim": {
                "status": "PROVEN" if claim_allowed else "DIRECTIONAL",
                "claim_allowed": claim_allowed,
                "threshold_failures": [] if claim_allowed else ["rolling daily-first skill is negative"],
                "summary": {
                    "positive_daily_first_days": positive_days,
                    "positive_skill_days": positive_days,
                    "rolling_daily_first_brier_skill": rolling_skill,
                    "promotion_grade_market_days": market_days,
                },
            },
            "daily_progress_ledger_latest": {
                "broad_improvement_claim_allowed": claim_allowed,
            },
        },
    )
    write_json(
        contract,
        {
            "status": contract_status,
            "acceptance_passed": contract_status == "PASS",
            "blocker_count": 0 if contract_status == "PASS" else 1,
            "first_blocker": {"detail": "contract blocked"},
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
    return progress, contract, hourly, ten


def test_gate_blocks_until_hourly_contract_and_daily_first_progress_clear(tmp_path):
    progress, contract, hourly, ten = write_inputs(tmp_path)

    payload = build_payload(
        progress_audit=progress,
        served_distribution_contract=contract,
        candidate_hourly=hourly,
        candidate_ten_minute=ten,
    )
    _, report = write_outputs(payload, tmp_path / "out.json", tmp_path / "out.md")

    blockers = {gate["gate"] for gate in payload["blockers"]}
    passes = {gate["gate"] for gate in payload["gates"] if gate["status"] == "PASS"}
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "BLOCK"
    assert "candidate_weak_slot_ten_minute_gate" in passes
    assert "candidate_hourly_early_gate" in blockers
    assert "served_distribution_contract" in blockers
    assert "rolling_daily_first_non_negative" in blockers
    assert "positive_daily_first_days" in blockers
    assert "promotion_grade_market_days" in blockers
    assert "progress_claim_allowed" in blockers
    assert "Early-Hour Positive Daily-First Gate" in report.read_text(encoding="utf-8")


def test_gate_passes_with_positive_daily_first_and_accepted_candidate(tmp_path):
    progress, contract, hourly, ten = write_inputs(
        tmp_path,
        claim_allowed=True,
        rolling_skill=0.02,
        positive_days=3,
        market_days=90,
        hourly_status="PASS",
        contract_status="PASS",
    )

    payload = build_payload(
        progress_audit=progress,
        served_distribution_contract=contract,
        candidate_hourly=hourly,
        candidate_ten_minute=ten,
    )

    assert payload["status"] == "PASS"
    assert payload["acceptance_passed"] is True
    assert payload["blocker_count"] == 0
