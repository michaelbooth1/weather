import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from weather.operations.production_evidence_ledgers import (
    CLEAN_DAY_SCHEMA_VERSION,
    UNATTENDED_SCHEMA_VERSION,
    ProductionEvidenceLedgerError,
    append_entry,
    build_clean_day_entry,
    build_clean_day_summary,
    build_unattended_cycle_entry,
    build_unattended_summary,
    main,
    verify_chain,
)


RELEASE = "release-fixture"
MANIFEST_HASH = "a" * 64


def _write(path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _clean_fleet(target_date="2026-07-10"):
    return {
        "schema_version": "fleet_observability_fixture",
        "generated_at_utc": "2026-07-11T04:00:00+00:00",
        "evidence_frozen": True,
        "release_id": RELEASE,
        "release_manifest_sha256": MANIFEST_HASH,
        "release_identity_status": "verified",
        "summary": {"market_count": 12, "critical_alerts": 0},
        "live_forward_slo": {
            "status": "PASS",
            "counts_toward_live_forward_gate": True,
            "clob_book_age_p99_seconds": 60.0,
            "near_close_clob_book_age_p99_seconds": 15.0,
        },
        "clean_active_day_countability": {
            "target_date": target_date,
            "status": "PASS",
            "counts_toward_clean_active_day": True,
            "operational_blocker_count": 0,
        },
        "current_code_soak": {
            "status": "PASS",
            "counts_toward_active_day": True,
        },
        "runtime_identity_evidence": {
            "status": "PASS",
            "runtime_identity_count": 1,
            "mixed_runtime_identity": False,
            "reconciliation_applied": False,
        },
        "collection": {
            "snapshot_cadence_proof": {
                "summary": {"status": "PASS", "total_gap_count": 0},
            },
            "source_status_proof": {"summary": {"status": "PASS"}},
            "early_hour_coverage_proof": {
                "summary": {
                    "status": "PASS",
                    "counts_toward_early_hour_evidence": True,
                },
            },
        },
    }


def _cycle_payloads(target_date="2026-07-10"):
    def invocation(task_name):
        return {
            "status": "PASS",
            "mode": "scheduled",
            "scheduler_attested": True,
            "task_name": task_name,
            "task_definition_sha256": "b" * 64,
            "manual_intervention": False,
            "manual_intervention_reasons": [],
            "resume_from_step": "",
            "resumed": False,
            "dry_run": False,
            "contract": {
                "status": "PASS",
                "contract_sha256": "c" * 64,
            },
            "task_run_correlation": {"status": "PASS"},
        }

    def lock_proof():
        return {
            "status": "PASS",
            "instrumented": True,
            "stale_lock_count": 0,
            "stale_lock_repair_count": 0,
            "forced_lock_acquisition_count": 0,
            "forced_lock_repair_count": 0,
        }

    release_identity = {
        "status": "PASS",
        "served_bindings_verified": True,
        "release_id": RELEASE,
        "release_manifest_sha256": MANIFEST_HASH,
    }
    sla = {
        "status": "PASS",
        "predeclared": True,
        "duration_seconds": 120.0,
        "limit_seconds": 3600.0,
        "breach_seconds": 0.0,
    }
    base = {
        "schema_version": "daily_refresh_stage_manifest_fixture",
        "target_date": target_date,
        "release_id": RELEASE,
        "release_manifest_sha256": MANIFEST_HASH,
        "release_identity_status": "verified_serving_binding",
        "release_identity": release_identity,
        "status": "COMPLETED",
        "payload_status": "ok",
        "steps": [{"name": "step", "status": "ok"}],
        "inside_sla": True,
        "sla": sla,
        "invocation": invocation("WeatherDailyRefresh"),
        "lock_proof": lock_proof(),
        "completed_at_utc": "2026-07-11T05:00:00+00:00",
    }
    stage_a = {**json.loads(json.dumps(base)), "stage": "settlement"}
    stage_b = {**json.loads(json.dumps(base)), "stage": "evidence"}
    nightly = {
        "schema_version": "nightly_retrain_fixture",
        "generated_at_utc": "2026-07-11T08:00:00+00:00",
        "status": "shadow",
        "dry_run": False,
        "release_id": RELEASE,
        "release_manifest_sha256": MANIFEST_HASH,
        "release_identity_status": "verified_serving_binding",
        "release_identity": release_identity,
        "settled_day_freshness": {"target_date": target_date},
        "steps": [{"name": "validate", "status": "ok"}],
        "nightly_sla": {"state": "OK", "fresh_for_latest_window": True, "alerts": []},
        "sla": sla,
        "invocation": invocation("WeatherNightlyRetrain"),
        "lock_proof": lock_proof(),
        "daily_learning": {
            "input_consistency_status": "PASS",
            "input_freshness_status": "PASS",
        },
        "candidate_release": {"pointer_changed": False},
    }
    return stage_a, stage_b, nightly


def test_clean_day_builder_requires_closed_exact_release_bound_proof():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(Path(tmp) / "fleet.json", _clean_fleet())
        entry = build_clean_day_entry(
            path,
            now=datetime(2026, 7, 11, 12, tzinfo=timezone.utc),
        )

    assert entry["schema_version"] == CLEAN_DAY_SCHEMA_VERSION
    assert entry["status"] == "PASS"
    assert entry["recordable"] is True
    assert entry["entry_key"] == "clean_day:2026-07-10"
    assert entry["all_market_days_countable"] is True
    assert entry["singular_release_identity"] is True
    assert entry["capture_slos_pass"] is True
    assert entry["source_evidence"][0]["sha256"]


def test_clean_day_builder_blocks_open_day_missing_p99_and_reconciliation_unknown():
    with tempfile.TemporaryDirectory() as tmp:
        payload = _clean_fleet("2026-07-11")
        payload["live_forward_slo"].pop("clob_book_age_p99_seconds")
        payload["runtime_identity_evidence"].pop("reconciliation_applied")
        path = _write(Path(tmp) / "fleet.json", payload)
        entry = build_clean_day_entry(
            path,
            now=datetime(2026, 7, 11, 12, tzinfo=timezone.utc),
        )

    assert entry["status"] == "BLOCK"
    assert entry["recordable"] is False
    codes = {row["code"] for row in entry["blockers"]}
    assert "target_day_not_closed" in codes
    assert "clob_p99_too_old" in codes
    assert "runtime_reconciliation_not_allowed" in codes


def test_clean_day_command_refuses_structurally_incomplete_immutable_append():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload = _clean_fleet("2099-01-01")
        path = _write(root / "fleet.json", payload)
        ledger = root / "ledger.jsonl"
        with pytest.raises(ProductionEvidenceLedgerError, match="not exact PASS"):
            main(
                [
                    "clean-day",
                    "--fleet",
                    str(path),
                    "--ledger",
                    str(ledger),
                    "--out",
                    str(root / "summary.json"),
                    "--report",
                    str(root / "summary.md"),
                ]
            )

    assert not ledger.exists()


def test_clean_day_command_refuses_recordable_non_pass_append():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload = _clean_fleet()
        payload["current_code_soak"] = {
            "status": "BLOCK",
            "counts_toward_active_day": False,
        }
        path = _write(root / "fleet.json", payload)
        ledger = root / "ledger.jsonl"
        with pytest.raises(ProductionEvidenceLedgerError, match="not exact PASS"):
            main(
                [
                    "clean-day",
                    "--fleet",
                    str(path),
                    "--ledger",
                    str(ledger),
                    "--out",
                    str(root / "summary.json"),
                    "--report",
                    str(root / "summary.md"),
                ]
            )

    assert not ledger.exists()


def test_append_is_hash_chained_idempotent_and_rejects_conflicting_key():
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp) / "ledger.jsonl"
        entry = {
            "schema_version": CLEAN_DAY_SCHEMA_VERSION,
            "entry_type": "clean_active_day",
            "entry_key": "clean_day:2026-07-10",
            "target_date": "2026-07-10",
            "status": "PASS",
        }
        first = append_entry(ledger, entry)
        duplicate = append_entry(ledger, entry)
        with pytest.raises(ProductionEvidenceLedgerError, match="conflicting immutable entry_key"):
            append_entry(ledger, {**entry, "status": "BLOCK"})
        rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]

    assert first["appended"] is True
    assert duplicate["appended"] is False
    assert duplicate["idempotent"] is True
    assert len(rows) == 1
    assert rows[0]["sequence"] == 1
    assert rows[0]["previous_entry_sha256"] == ""
    assert verify_chain(rows)["status"] == "PASS"


def test_chain_verification_detects_tampering():
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp) / "ledger.jsonl"
        append_entry(
            ledger,
            {
                "schema_version": CLEAN_DAY_SCHEMA_VERSION,
                "entry_type": "clean_active_day",
                "entry_key": "clean_day:2026-07-10",
                "target_date": "2026-07-10",
                "status": "PASS",
            },
        )
        rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        rows[0]["status"] = "BLOCK"

    verification = verify_chain(rows)
    assert verification["status"] == "BLOCK"
    assert {row["code"] for row in verification["errors"]} >= {
        "record_hash_mismatch",
        "entry_hash_mismatch",
    }


def test_clean_day_summary_requires_latest_consecutive_suffix_under_one_release():
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp) / "clean.jsonl"
        for target in ("2026-07-08", "2026-07-09", "2026-07-10"):
            append_entry(
                ledger,
                {
                    "schema_version": CLEAN_DAY_SCHEMA_VERSION,
                    "entry_type": "clean_active_day",
                    "entry_key": f"clean_day:{target}",
                    "target_date": target,
                    "status": "PASS",
                    "release_id": RELEASE,
                    "release_manifest_sha256": MANIFEST_HASH,
                    "market_count": 12,
                    "all_market_days_countable": True,
                    "singular_release_identity": True,
                    "capture_slos_pass": True,
                },
            )
        passed = build_clean_day_summary(ledger)
        append_entry(
            ledger,
            {
                "schema_version": CLEAN_DAY_SCHEMA_VERSION,
                "entry_type": "clean_active_day",
                "entry_key": "clean_day:2026-07-11",
                "target_date": "2026-07-11",
                "status": "BLOCK",
                "release_id": RELEASE,
                "release_manifest_sha256": MANIFEST_HASH,
                "market_count": 12,
            },
        )
        blocked = build_clean_day_summary(ledger)

    assert passed["status"] == "PASS"
    assert passed["summary"]["consecutive_clean_active_days"] == 3
    assert passed["summary"]["ledger_integrity_status"] == "PASS"
    assert passed["summary"]["entry_chain_sha256"]
    assert blocked["status"] == "BLOCK"
    assert blocked["summary"]["consecutive_clean_active_days"] == 0


def test_unattended_builder_requires_scheduled_no_repair_consistent_sla_cycle():
    with tempfile.TemporaryDirectory() as tmp:
        stage_a, stage_b, nightly = _cycle_payloads()
        a = _write(Path(tmp) / "a.json", stage_a)
        b = _write(Path(tmp) / "b.json", stage_b)
        n = _write(Path(tmp) / "n.json", nightly)
        entry = build_unattended_cycle_entry(a, b, n)

    assert entry["schema_version"] == UNATTENDED_SCHEMA_VERSION
    assert entry["status"] == "PASS"
    assert entry["recordable"] is True
    assert entry["daily_refresh_pass"] is True
    assert entry["nightly_pass"] is True
    assert entry["inside_sla"] is True
    assert entry["manual_repair"] is False
    assert entry["stale_lock"] is False
    assert entry["inconsistent_input_count"] == 0


def test_unattended_builder_blocks_unknown_provenance_stale_inputs_and_mixed_date():
    with tempfile.TemporaryDirectory() as tmp:
        stage_a, stage_b, nightly = _cycle_payloads()
        stage_a.pop("invocation")
        stage_b["lock_proof"]["stale_lock_count"] = 1
        nightly["settled_day_freshness"]["target_date"] = "2026-07-09"
        nightly["daily_learning"]["input_consistency_status"] = "FAIL"
        a = _write(Path(tmp) / "a.json", stage_a)
        b = _write(Path(tmp) / "b.json", stage_b)
        n = _write(Path(tmp) / "n.json", nightly)
        entry = build_unattended_cycle_entry(a, b, n)

    assert entry["status"] == "BLOCK"
    assert entry["recordable"] is False
    codes = {row["code"] for row in entry["blockers"]}
    assert "mixed_target_dates" in codes
    assert "invocation_not_proven_scheduled" in codes
    assert "stale_or_forced_lock_repair" in codes
    assert "nightly_inputs_inconsistent_or_stale" in codes


def _build_cycle_entry(tmp, stage_a, stage_b, nightly):
    root = Path(tmp)
    return build_unattended_cycle_entry(
        _write(root / "a.json", stage_a),
        _write(root / "b.json", stage_b),
        _write(root / "n.json", nightly),
    )


def test_unattended_builder_blocks_spoofed_manual_or_resumed_invocation():
    with tempfile.TemporaryDirectory() as tmp:
        stage_a, stage_b, nightly = _cycle_payloads()
        stage_a["invocation"].update({
            "status": "BLOCK",
            "scheduler_attested": False,
            "mode": "manual_or_unverified",
            "manual_intervention": True,
            "manual_intervention_reasons": ["scheduler_not_attested"],
            "contract": {"status": "PASS", "contract_sha256": "c" * 64},
            "task_run_correlation": {"status": "BLOCK"},
        })
        stage_b["invocation"].update({
            "resume_from_step": "promotion_refresh",
            "resumed": True,
            "manual_intervention": True,
        })
        entry = _build_cycle_entry(tmp, stage_a, stage_b, nightly)

    codes = {row["code"] for row in entry["blockers"]}
    assert entry["status"] == "BLOCK"
    assert entry["recordable"] is False
    assert "scheduler_attestation_failed" in codes
    assert "manual_intervention_or_resume" in codes


def test_unattended_builder_blocks_task_contract_mismatch_or_disabled_task():
    with tempfile.TemporaryDirectory() as tmp:
        stage_a, stage_b, nightly = _cycle_payloads()
        stage_b["invocation"].update({
            "status": "BLOCK",
            "scheduler_attested": False,
            "task_definition_sha256": "",
            "contract": {"status": "BLOCK", "contract_sha256": ""},
            "task_run_correlation": {"status": "BLOCK"},
            "blockers": [{"code": "scheduler_task_disabled"}],
        })
        entry = _build_cycle_entry(tmp, stage_a, stage_b, nightly)

    codes = {row["code"] for row in entry["blockers"]}
    assert entry["status"] == "BLOCK"
    assert "invocation_not_proven_scheduled" in codes
    assert "scheduler_attestation_failed" in codes


def test_unattended_builder_blocks_exact_stale_and_forced_lock_outcomes():
    with tempfile.TemporaryDirectory() as tmp:
        stage_a, stage_b, nightly = _cycle_payloads()
        stage_a["lock_proof"].update({
            "status": "BLOCK",
            "stale_lock_count": 1,
            "stale_lock_repair_count": 1,
        })
        nightly["lock_proof"].update({
            "status": "BLOCK",
            "forced_lock_acquisition_count": 1,
            "forced_lock_repair_count": 0,
        })
        entry = _build_cycle_entry(tmp, stage_a, stage_b, nightly)

    assert entry["status"] == "BLOCK"
    assert entry["stale_lock"] is True
    assert "stale_or_forced_lock_repair" in {row["code"] for row in entry["blockers"]}


def test_unattended_builder_blocks_predeclared_sla_breach():
    with tempfile.TemporaryDirectory() as tmp:
        stage_a, stage_b, nightly = _cycle_payloads()
        stage_b["sla"].update({
            "status": "BLOCK",
            "duration_seconds": 3700.0,
            "limit_seconds": 3600.0,
            "breach_seconds": 100.0,
        })
        entry = _build_cycle_entry(tmp, stage_a, stage_b, nightly)

    assert entry["status"] == "BLOCK"
    assert entry["inside_sla"] is False
    assert "stage_b_outside_sla" in {row["code"] for row in entry["blockers"]}


def test_unattended_builder_blocks_missing_verified_serving_release():
    with tempfile.TemporaryDirectory() as tmp:
        stage_a, stage_b, nightly = _cycle_payloads()
        nightly["release_id"] = ""
        nightly["release_manifest_sha256"] = ""
        nightly["release_identity"] = {
            "status": "BLOCK",
            "served_bindings_verified": False,
            "release_id": "",
            "release_manifest_sha256": "",
        }
        nightly["release_identity_status"] = "unverified"
        entry = _build_cycle_entry(tmp, stage_a, stage_b, nightly)

    codes = {row["code"] for row in entry["blockers"]}
    assert entry["status"] == "BLOCK"
    assert entry["recordable"] is False
    assert "release_id_mismatch_or_missing" in codes
    assert "release_binding_proof_missing" in codes


def test_unattended_command_refuses_non_pass_producer_proof_append():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        stage_a, stage_b, nightly = _cycle_payloads()
        nightly["dry_run"] = True
        nightly["invocation"]["dry_run"] = True
        nightly["invocation"]["manual_intervention"] = True
        nightly["invocation"]["manual_intervention_reasons"] = ["dry_run"]
        a = _write(root / "a.json", stage_a)
        b = _write(root / "b.json", stage_b)
        n = _write(root / "n.json", nightly)
        ledger = root / "cycles.jsonl"
        with pytest.raises(ProductionEvidenceLedgerError, match="not exact PASS"):
            main([
                "unattended-cycle",
                "--stage-a", str(a),
                "--stage-b", str(b),
                "--nightly", str(n),
                "--ledger", str(ledger),
                "--out", str(root / "summary.json"),
                "--report", str(root / "summary.md"),
            ])

    assert not ledger.exists()


def test_unattended_summary_requires_seven_consecutive_cycles_and_zero_exceptions():
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp) / "cycles.jsonl"
        for day in range(1, 8):
            target = f"2026-07-{day:02d}"
            append_entry(
                ledger,
                {
                    "schema_version": UNATTENDED_SCHEMA_VERSION,
                    "entry_type": "unattended_daily_nightly_cycle",
                    "entry_key": f"unattended_cycle:{target}",
                    "target_date": target,
                    "status": "PASS",
                    "release_id": RELEASE,
                    "release_manifest_sha256": MANIFEST_HASH,
                    "daily_refresh_pass": True,
                    "nightly_pass": True,
                    "inside_sla": True,
                    "manual_repair": False,
                    "stale_lock": False,
                    "mixed_target_date": False,
                    "unreviewed_promotion": False,
                    "inconsistent_input_count": 0,
                },
            )
        summary = build_unattended_summary(ledger)

    assert summary["status"] == "PASS"
    assert summary["summary"]["consecutive_unattended_cycles"] == 7
    assert summary["summary"]["daily_refresh_pass_count"] == 7
    assert summary["summary"]["nightly_pass_count"] == 7
    assert summary["summary"]["inside_sla_count"] == 7
    assert summary["summary"]["manual_repair_count"] == 0
    assert summary["summary"]["stale_lock_count"] == 0
    assert summary["summary"]["mixed_target_date_count"] == 0
    assert summary["summary"]["unreviewed_promotion_count"] == 0
    assert summary["summary"]["inconsistent_input_count"] == 0


def test_empty_ledgers_are_integrity_valid_but_gate_blocked():
    clean = build_clean_day_summary([])
    unattended = build_unattended_summary([])

    assert clean["status"] == "BLOCK"
    assert clean["summary"]["ledger_integrity_status"] == "PASS"
    assert clean["summary"]["entry_count"] == 0
    assert unattended["status"] == "BLOCK"
    assert unattended["summary"]["ledger_integrity_status"] == "PASS"
    assert unattended["summary"]["entry_count"] == 0
