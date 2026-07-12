import hashlib
import json
import shutil
from pathlib import Path

import pytest

from weather.experiment_contract import finalize_self_hash
from weather.model_stage_retirement import (
    ABLATION_HASH_FIELD,
    ABLATION_SCHEMA_VERSION,
    INCUMBENT_STAGES,
    REGISTER_HASH_FIELD,
    REQUIRED_CALIBRATION_ARMS,
    REQUIRED_EXPERIMENT_TYPES,
    REQUIRED_REQUALIFICATION_CRITERIA,
    REQUIRED_SAFETY_INVARIANTS,
    StageRetirementGateError,
    audit_residual_distribution_v1_graph,
    build_stage_retirement_register,
    verify_stage_retirement_register,
    write_stage_retirement_register,
)
from weather.paths import REPO_ROOT


CANDIDATE_ID = "residual_distribution_v1"
GENERATED_AT = "2026-07-12T18:00:00+00:00"


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _receipt(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    report = {
        "status": "OFFLINE_PASS",
        "candidate_id": CANDIDATE_ID,
        "qualification": {
            "status": "OFFLINE_PASS",
            "offline_status": "PASS",
            "forward_status": "BLOCK",
            "criteria": {key: True for key in REQUIRED_REQUALIFICATION_CRITERIA},
        },
        "candidate_artifact": {
            "sha256": "a" * 64,
            "qualification_status": "OFFLINE_PASS",
            "offline_qualification_status": "PASS",
            "forward_qualification_status": "BLOCK",
            "promotion_eligible": False,
        },
    }
    report_path = _write_json(tmp_path / "requalification.json", report)
    paired_hash = _receipt("paired-whole-fleet-dates-2026-06-01-through-2026-06-14")
    calibration = {
        "literal_served_transform_executed": True,
        "comparator_arm": "literal_current_served_transform",
        "arms_evaluated": sorted(REQUIRED_CALIBRATION_ARMS),
        "selected_arm": "simplex_temperature",
        "paired_unit": "fleet_target_date",
        "paired_date_count": 14,
        "paired_dates_sha256": paired_hash,
        "embargo_days_evaluated": [3, 5, 7],
        "seed_count": 5,
        "evaluation_receipt_sha256": _receipt("calibration-receipt"),
        "delta_brier": {"mean": -0.002, "ci95_upper": -0.0001},
        "delta_log_loss": {"mean": -0.006, "ci95_upper": -0.0001},
        "ece_delta": 0.002,
        "ece_delta_ci95_upper": 0.008,
        "max_market_brier_delta": 0.006,
        "simplex_invariants": {
            "partition_sum_one": "PASS",
            "probabilities_finite": "PASS",
            "probabilities_nonnegative": "PASS",
            "served_transform_parity": "PASS",
        },
        "parity_vectors": {"status": "PASS", "max_abs_delta": 0.0},
    }
    stages = []
    for descriptor in INCUMBENT_STAGES:
        stage_id = descriptor["stage_id"]
        stages.append(
            {
                "stage_id": stage_id,
                "category": descriptor["category"],
                "experiment_types": sorted(REQUIRED_EXPERIMENT_TYPES),
                "paired_unit": "fleet_target_date",
                "paired_date_count": 14,
                "paired_dates_sha256": paired_hash,
                "evaluation_receipt_sha256": _receipt(f"stage:{stage_id}"),
                "delta_brier": {"mean": 0.0002, "ci95_upper": 0.0008},
                "delta_log_loss": {"mean": 0.001, "ci95_upper": 0.004},
                "max_market_brier_delta": 0.008,
                "safety_invariants": {
                    key: "PASS" for key in REQUIRED_SAFETY_INVARIANTS
                },
            }
        )
    evidence = finalize_self_hash(
        {
            "schema_version": ABLATION_SCHEMA_VERSION,
            "artifact_type": "served_calibration_stage_ablation",
            "status": "PASS",
            "candidate_id": CANDIDATE_ID,
            "generated_at_utc": "2026-07-12T17:00:00+00:00",
            "requalification_report_sha256": _sha256(report_path),
            "candidate_artifact_sha256": "a" * 64,
            "independent_unit": "fleet_target_date",
            "cluster_unit": "fleet_target_date",
            "paired_date_count": 14,
            "paired_dates_sha256": paired_hash,
            "frozen_full_stack_id": "incumbent-release-frozen",
            "candidate_graph_id": CANDIDATE_ID,
            "calibration": calibration,
            "stage_ablations": stages,
        },
        hash_field=ABLATION_HASH_FIELD,
    )
    evidence_path = _write_json(tmp_path / "served_ablation.json", evidence)
    return report_path, evidence_path


def _rewrite_evidence(path: Path, mutate) -> None:
    evidence = json.loads(path.read_text(encoding="utf-8"))
    mutate(evidence)
    evidence = finalize_self_hash(
        {key: value for key, value in evidence.items() if key != ABLATION_HASH_FIELD},
        hash_field=ABLATION_HASH_FIELD,
    )
    _write_json(path, evidence)


def test_exact_e3_e4_evidence_retires_every_incumbent_stage(tmp_path):
    report, evidence = _fixture(tmp_path)

    register = build_stage_retirement_register(
        report,
        evidence,
        generated_at_utc=GENERATED_AT,
    )
    verified = verify_stage_retirement_register(register, report, evidence)
    output = write_stage_retirement_register(register, tmp_path / "retirement-register.json")

    assert verified["status"] == "PASS"
    assert verified["retirement_permission"] == "AUTHORIZED_BY_EVIDENCE_REGISTER"
    assert verified["mutation_performed"] is False
    assert verified["summary"]["incumbent_stage_count"] == len(INCUMBENT_STAGES)
    assert verified["summary"]["retire_count"] == len(INCUMBENT_STAGES)
    assert verified["summary"]["block_count"] == 0
    assert verified["summary"]["quarantine_count"] == 0
    assert {row["decision"] for row in verified["stages"]} == {"RETIRE"}
    assert verified["calibration"]["disposition"] == "SUPERSEDE_LEGACY_CALIBRATION"
    assert verified["v1_graph_audit"]["status"] == "PASS"
    assert verified["summary"]["binary_selector_call_count"] == 0
    assert verified["summary"]["legacy_postprocess_call_count"] == 0
    assert verified["summary"]["router_or_fallback_call_count"] == 0
    assert verified[REGISTER_HASH_FIELD]
    assert output.exists()


def test_missing_stage_evidence_blocks_retirement(tmp_path):
    report, evidence = _fixture(tmp_path)
    missing_stage = INCUMBENT_STAGES[-1]["stage_id"]
    _rewrite_evidence(
        evidence,
        lambda payload: payload["stage_ablations"].pop(),
    )

    register = build_stage_retirement_register(
        report,
        evidence,
        generated_at_utc=GENERATED_AT,
    )
    verified = verify_stage_retirement_register(register, report, evidence)

    assert verified["status"] == "BLOCK"
    assert verified["retirement_permission"] == "FORBIDDEN"
    assert "stage_ablation_incomplete" in verified["blockers"]
    row = next(item for item in verified["stages"] if item["stage_id"] == missing_stage)
    assert row["decision"] == "BLOCK"
    assert row["blockers"] == ["stage evidence is missing"]


def test_complete_but_inferior_removal_is_quarantined_not_retired(tmp_path):
    report, evidence = _fixture(tmp_path)
    stage_id = INCUMBENT_STAGES[0]["stage_id"]

    def make_inferior(payload):
        payload["stage_ablations"][0]["delta_brier"]["ci95_upper"] = 0.002

    _rewrite_evidence(evidence, make_inferior)
    register = build_stage_retirement_register(
        report,
        evidence,
        generated_at_utc=GENERATED_AT,
    )

    assert register["status"] == "QUARANTINE"
    assert register["retirement_permission"] == "FORBIDDEN"
    row = next(item for item in register["stages"] if item["stage_id"] == stage_id)
    assert row["decision"] == "QUARANTINE"
    assert "brier_ci_noninferior" in row["quarantine_reasons"]


@pytest.mark.parametrize("recompute_hash", [False, True])
def test_register_tampering_is_rejected_even_if_attacker_rehashes(
    tmp_path,
    recompute_hash,
):
    report, evidence = _fixture(tmp_path)
    register = build_stage_retirement_register(
        report,
        evidence,
        generated_at_utc=GENERATED_AT,
    )
    register["stages"][0]["decision"] = "QUARANTINE"
    if recompute_hash:
        register = finalize_self_hash(
            {key: value for key, value in register.items() if key != REGISTER_HASH_FIELD},
            hash_field=REGISTER_HASH_FIELD,
        )

    with pytest.raises(StageRetirementGateError, match="self-hash|does not match"):
        verify_stage_retirement_register(register, report, evidence)


def test_v1_graph_audit_detects_injected_legacy_postprocess_call(tmp_path):
    for relative in {
        Path("src/weather/model/residual_distribution_v1.py"),
        Path("src/weather/collection/live_variant_predictions.py"),
        Path("src/weather/calibration/pooled_candidate_replay.py"),
    }:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, destination)
    live_path = tmp_path / "src/weather/collection/live_variant_predictions.py"
    source = live_path.read_text(encoding="utf-8")
    source = source.replace(
        '    runtime = "residual_distribution_v1"',
        '    runtime = "residual_distribution_v1"\n    apply_band_postprocessing()',
        1,
    )
    live_path.write_text(source, encoding="utf-8")

    audit = audit_residual_distribution_v1_graph(tmp_path)

    assert audit["status"] == "BLOCK"
    assert audit["legacy_postprocess_call_count"] == 1
    assert audit["criteria"]["no_legacy_postprocess_calls"] is False
