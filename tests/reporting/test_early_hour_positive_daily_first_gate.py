import json

from weather.reporting.serving_gates.early_hour_positive_daily_first_gate import (
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
    contract_model_status=None,
    production_readiness_status=None,
    progress_generated_at="2026-06-22T13:00:00+00:00",
    contract_generated_at="2026-06-22T12:00:00+00:00",
    hourly_generated_at="2026-06-22T12:05:00+00:00",
    ten_generated_at="2026-06-22T12:10:00+00:00",
):
    progress = tmp_path / "progress.json"
    contract = tmp_path / "contract.json"
    hourly = tmp_path / "hourly.json"
    ten = tmp_path / "ten.json"
    write_json(
        progress,
        {
            "generated_at_utc": progress_generated_at,
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
            "generated_at_utc": contract_generated_at,
            "status": contract_status,
            "acceptance_passed": contract_status == "PASS",
            "model_served_distribution_status": contract_model_status,
            "model_acceptance_passed": None if contract_model_status is None else contract_model_status == "PASS",
            "production_readiness_status": production_readiness_status,
            "production_readiness_blocker_count": None if production_readiness_status is None else 0 if production_readiness_status == "PASS" else 1,
            "production_readiness_blockers": [
                {
                    "gate": "promotion_refresh_broad_claim",
                    "status": "BLOCK",
                    "detail": "fleet observability must be OK/PASS before location validation counts",
                }
            ] if production_readiness_status == "BLOCK" else [],
            "broad_core_model_claim_allowed": production_readiness_status == "PASS" if production_readiness_status else contract_status == "PASS",
            "blocker_count": 0 if contract_status == "PASS" else 1,
            "first_blocker": {"detail": "contract blocked"},
        },
    )
    write_json(
        hourly,
        {
            "generated_at_utc": hourly_generated_at,
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
            "generated_at_utc": ten_generated_at,
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
    assert "progress_audit_refreshed_after_candidate" in passes
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


def test_gate_blocks_when_accepted_candidate_progress_audit_is_stale(tmp_path):
    progress, contract, hourly, ten = write_inputs(
        tmp_path,
        claim_allowed=True,
        rolling_skill=0.02,
        positive_days=3,
        market_days=90,
        hourly_status="PASS",
        contract_status="PASS",
        progress_generated_at="2026-06-22T12:00:00+00:00",
        ten_generated_at="2026-06-22T12:10:00+00:00",
    )

    payload = build_payload(
        progress_audit=progress,
        served_distribution_contract=contract,
        candidate_hourly=hourly,
        candidate_ten_minute=ten,
    )

    blockers = {gate["gate"]: gate for gate in payload["blockers"]}
    assert payload["status"] == "BLOCK"
    assert "progress_audit_refreshed_after_candidate" in blockers
    assert "progress audit is stale" in blockers["progress_audit_refreshed_after_candidate"]["detail"]


def test_gate_blocks_readiness_and_requires_fresh_progress_after_model_contract_passes(tmp_path):
    progress, contract, hourly, ten = write_inputs(
        tmp_path,
        claim_allowed=True,
        rolling_skill=0.02,
        positive_days=3,
        market_days=90,
        hourly_status="PASS",
        contract_status="BLOCK",
        contract_model_status="PASS",
        production_readiness_status="BLOCK",
        progress_generated_at="2026-06-22T12:00:00+00:00",
        contract_generated_at="2026-06-22T12:20:00+00:00",
    )

    payload = build_payload(
        progress_audit=progress,
        served_distribution_contract=contract,
        candidate_hourly=hourly,
        candidate_ten_minute=ten,
    )

    blockers = {gate["gate"]: gate for gate in payload["blockers"]}
    assert payload["status"] == "BLOCK"
    assert "served_distribution_contract" not in blockers
    assert "production_readiness_gate" in blockers
    assert (
        blockers["production_readiness_gate"]["detail"]
        == "fleet observability must be OK/PASS before location validation counts"
    )
    assert "progress_audit_refreshed_after_candidate" in blockers
