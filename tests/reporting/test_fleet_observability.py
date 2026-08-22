import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from weather.collection.collection_health import (  # noqa: E402
    early_hour_coverage_summary,
    fleet_collection_health,
    fleet_source_family_degradation_summary,
    source_family_degradation,
)
from weather.market.market_registry import all_specs  # noqa: E402
from weather.operations.market_making_daily_roll import MARKET_MAKING_DAILY_ROLL_SUPERVISOR
from weather.operations.supervisor import SupervisorSpec
from weather.operations.taker_bot_daily_roll import TAKER_DAILY_ROLL_SUPERVISOR
from weather.reporting.fleet.fleet_observability import (  # noqa: E402
    _build_trust_readiness,
    _build_runtime_identity_observability,
    _build_trading_observability,
    artifact_metadata,
    audit_alerts,
    classify_loop_diagnostic_event,
    clob_alerts,
    cleanup_deletion_gate_summary,
    current_code_soak_summary,
    daily_refresh_resource_summary,
    load_daily_refresh_resource_rows,
    clean_active_day_countability,
    live_forward_slo_gate,
    loop_integrity_alerts,
    mm_evidence_starvation_summary,
    mm_paper_evidence_summary,
    observation_alerts,
    overall_status,
    parquet_incremental_alerts,
    parquet_incremental_status,
    runtime_identity_alerts,
    runtime_identity_target_date,
    settled_day_freshness_alerts,
    trust_readiness,
    write_json,
    write_markdown,
)
from weather.reporting.fleet import fleet_observability_loops


class TestFleetObservability(unittest.TestCase):
    def test_scheduled_bounded_mode_omits_full_trust_replay(self):
        with patch(
            "weather.reporting.fleet.fleet_observability_payload.score_all_markets",
            side_effect=AssertionError("full trust replay must not run"),
        ):
            trust, execution = _build_trust_readiness(
                Path("unused"),
                include_trust_replay=False,
            )

        self.assertEqual(trust, {})
        self.assertEqual(execution["status"], "SKIPPED")
        self.assertTrue(execution["trust_readiness_omitted"])
        self.assertFalse(execution["score_all_markets_called"])

    def test_scheduled_bounded_mode_omits_runtime_identity_tape_replay(self):
        with patch(
            "weather.reporting.fleet.fleet_observability_payload.build_runtime_identity_evidence",
            side_effect=AssertionError("snapshot tapes must not be opened"),
        ):
            evidence, execution = _build_runtime_identity_observability(
                snapshots_root=Path("unused"),
                target_date="2026-08-20",
                mm_runs_root=Path("unused-mm"),
                taker_runs_root=Path("unused-taker"),
                reconciliation_path=Path("unused-reconciliation.json"),
                include_runtime_identity_replay=False,
            )

        self.assertEqual(evidence, {})
        self.assertEqual(execution["status"], "SKIPPED")
        self.assertTrue(execution["runtime_identity_evidence_omitted"])
        self.assertFalse(execution["build_runtime_identity_evidence_called"])

    def test_scheduled_bounded_mode_omits_duplicate_mm_taker_replay(self):
        with patch(
            "weather.reporting.fleet.fleet_observability_payload.mm_evidence_starvation_summary",
            side_effect=AssertionError("MM runs must not be enumerated"),
        ), patch(
            "weather.reporting.fleet.fleet_observability_payload.build_trading_evidence_summary",
            side_effect=AssertionError("MM/taker runs must not be enumerated"),
        ):
            starvation, evidence, execution = _build_trading_observability(
                Path("unused-mm"),
                Path("unused-taker"),
                include_trading_replay=False,
            )

        self.assertEqual(starvation, {})
        self.assertEqual(evidence, {})
        self.assertEqual(execution["status"], "SKIPPED")
        self.assertTrue(execution["trading_evidence_omitted"])
        self.assertFalse(execution["mm_evidence_starvation_summary_called"])
        self.assertFalse(execution["build_trading_evidence_summary_called"])

    def test_json_writer_publishes_complete_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "fleet.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"old": true}\n', encoding="utf-8")

            result = write_json(path, {"status": "PASS", "markets": 12})

            self.assertEqual(result, path)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"markets": 12, "status": "PASS"},
            )
            self.assertEqual(list(path.parent.glob("fleet.json.*.tmp")), [])

    def test_daily_refresh_resource_peaks_and_budget_decisions_surface(self):
        summary = daily_refresh_resource_summary([
            {
                "step": "maker_paper_score",
                "status": "ok",
                "child_pid": 123,
                "budget": {
                    "private_memory_max_bytes": 4096,
                    "working_set_max_bytes": 3072,
                    "timeout_seconds": 60,
                },
                "admission_before": {"decision": "ADMIT"},
                "admission_after": {"decision": "ADMIT"},
                "subprocess": {
                    "duration_seconds": 3.5,
                    "resource_peaks": {
                        "private_memory_peak_bytes": 2048,
                        "working_set_peak_bytes": 1024,
                    },
                    "resource_io": {"read_bytes": 8192, "write_bytes": 2048},
                },
                "result_metrics": {"input_row_count": 12},
            }
        ])

        self.assertEqual(summary["status"], "OK")
        self.assertEqual(summary["private_memory_peak_bytes"], 2048)
        self.assertEqual(summary["working_set_peak_bytes"], 1024)
        self.assertEqual(summary["budget_decisions"][0]["before"], "ADMIT")
        self.assertEqual(summary["budget_decisions"][0]["read_bytes"], 8192)
        self.assertEqual(summary["budget_decisions"][0]["result_metric_count"], 1)
        postcheck = daily_refresh_resource_summary([{
            "step": "maker_paper_score",
            "status": "ok_postcheck_deferred",
            "post_step_failure_reason": "post_step_capture_or_physical_check_failed",
        }])
        self.assertEqual(postcheck["status"], "DEFERRED")
        self.assertEqual(
            postcheck["budget_decisions"][0]["failure_reason"],
            "post_step_capture_or_physical_check_failed",
        )

    def test_daily_refresh_resources_survive_standalone_fleet_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = Path(tmp) / "daily_refresh_status.json"
            status.write_text(
                json.dumps({
                    "status": "interrupted",
                    "resource_steps": [{
                        "step": "maker_paper_score",
                        "status": "error",
                        "failure_reason": "resource_budget_exceeded",
                    }],
                }),
                encoding="utf-8",
            )

            rows = load_daily_refresh_resource_rows(status)
            summary = daily_refresh_resource_summary(rows)

        self.assertEqual(summary["status"], "ERROR")
        self.assertEqual(summary["budget_decisions"][0]["step"], "maker_paper_score")

    def test_fleet_collection_health_returns_one_row_per_registered_market(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-toronto-on-june-7-2026"
            folder.mkdir(parents=True)
            start = datetime(2026, 6, 7, 11, 0)
            pd.DataFrame([
                {
                    "snapshot_id": f"s{i}",
                    "captured_at_local": (start + timedelta(minutes=10 * i)).isoformat(),
                }
                for i in range(49)
            ]).to_csv(folder / "snapshots_long.csv", index=False)
            pd.DataFrame([
                {
                    "snapshot_id": "s48",
                    "captured_at_utc": "2026-06-07T23:00:00+00:00",
                    "captured_at_local": (start + timedelta(minutes=480)).isoformat(),
                    "source": "open_meteo",
                    "ok": True,
                    "stale": True,
                    "status": "rate_limited_cache",
                    "source_family": "open_meteo",
                    "degradation_state": "rate_limited_fallback",
                },
                {
                    "snapshot_id": "s48",
                    "captured_at_utc": "2026-06-07T23:00:00+00:00",
                    "captured_at_local": (start + timedelta(minutes=480)).isoformat(),
                    "source": "weather_forecast",
                    "ok": True,
                    "stale": False,
                    "status": "fresh",
                    "source_family": "weather_forecast",
                    "degradation_state": "healthy",
                },
            ]).to_csv(folder / "source_status_long.csv", index=False)

            payload = fleet_collection_health(
                snapshots_root=root,
                live=True,
                as_of=datetime(2026, 6, 7, 19, 0),
            )

        self.assertEqual(payload["summary"]["market_count"], 12)
        by_market = {row["market_id"]: row for row in payload["markets"]}
        self.assertEqual(by_market["toronto"]["state"], "CLEAN")
        self.assertEqual(by_market["nyc"]["state"], "MISSING")
        toronto_sources = by_market["toronto"]["source_family_degradation"]
        self.assertEqual(toronto_sources["affected_family_count"], 1)
        self.assertEqual(toronto_sources["fallback_source_count"], 1)
        self.assertEqual(toronto_sources["families"]["open_meteo"]["fallback_sources"], ["open_meteo"])
        self.assertFalse(toronto_sources["trading_evidence_allowed"])
        self.assertTrue(toronto_sources["model_review_allowed"])
        toronto_cadence = by_market["toronto"]["snapshot_cadence_proof"]
        self.assertEqual(toronto_cadence["status"], "PASS")
        self.assertEqual(toronto_cadence["latest_snapshot_id"], "s48")
        self.assertEqual(toronto_cadence["gap_count"], 0)
        fleet_sources = payload["summary"]["source_family_degradation"]
        self.assertEqual(payload["source_status_proof"]["schema_version"], "source_status_proof_v0.2")
        self.assertEqual(payload["source_status_proof"]["status"], "BLOCK")
        self.assertEqual(payload["source_status_proof"]["root_cause_class"], "missing_source_status")
        self.assertEqual(fleet_sources["status"], "BLOCK")
        self.assertEqual(fleet_sources["root_cause_class"], "missing_source_status")
        self.assertEqual(fleet_sources["affected_market_count"], 1)
        self.assertEqual(fleet_sources["fallback_source_count"], 1)
        self.assertEqual(
            payload["snapshot_cadence_proof"]["summary"]["blocked_market_count"],
            11,
        )

    def test_early_hour_coverage_counts_midnight_to_eight_snapshots(self):
        target_date = datetime(2026, 6, 26).date()
        start = datetime(2026, 6, 26, 0, 0)
        times = [start + timedelta(minutes=10 * idx) for idx in range(49)]

        proof = early_hour_coverage_summary(
            times,
            10.0,
            target_date=target_date,
            as_of=datetime(2026, 6, 26, 12, 0),
        )

        self.assertEqual(proof["status"], "PASS")
        self.assertTrue(proof["counts_toward_early_hour_evidence"])
        self.assertEqual(proof["snapshot_count"], 49)
        self.assertEqual(proof["minimum_snapshot_count"], 48)
        self.assertEqual(proof["gap_count"], 0)

    def test_clean_active_day_countability_requires_early_hour_coverage(self):
        collection = {
            "markets": [{"market_id": "toronto", "target_date": "2026-06-26"}],
            "source_status_proof": {
                "summary": {
                    "promotion_readiness_allowed": True,
                    "promotion_readiness_blocked_market_count": 0,
                },
            },
            "early_hour_coverage_proof": {
                "summary": {
                    "status": "PASS",
                    "counts_toward_early_hour_evidence": True,
                    "countable_market_count": 1,
                    "total_snapshot_count": 49,
                },
            },
        }
        clob = {"books": {"ok": True, "markets": [{"market_id": "toronto", "ok": True}]}}
        live_slo = {
            "status": "PASS",
            "ok": True,
            "counts_toward_live_forward_gate": True,
            "snapshot_cadence_proof": {
                "summary": {
                    "status": "PASS",
                    "snapshot_coverage_gap_blocked_market_count": 0,
                },
            },
        }
        current_soak = {"status": "PASS", "counts_toward_active_day": True}

        proof = clean_active_day_countability(collection, clob, live_slo, current_soak)
        collection["early_hour_coverage_proof"]["summary"] = {
            "status": "BLOCK",
            "counts_toward_early_hour_evidence": False,
            "reason": "12/48 minimum early-hour snapshots",
        }
        blocked = clean_active_day_countability(collection, clob, live_slo, current_soak)

        self.assertEqual(proof["status"], "PASS")
        self.assertTrue(proof["counts_toward_early_hour_evidence"])
        self.assertEqual(blocked["status"], "BLOCK")
        self.assertEqual(blocked["first_blocker"]["name"], "early_hour_coverage")

    def test_source_family_provider_cooldown_is_nonblocking_with_fresh_family_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            pd.DataFrame([
                {
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-19T22:00:00+00:00",
                    "captured_at_local": "2026-06-19T18:00:00-04:00",
                    "source": "global_ensemble",
                    "ok": True,
                    "stale": False,
                    "status": "fresh_cache",
                    "cache_status": "fresh_cache",
                    "source_family": "open_meteo",
                    "degradation_state": "healthy",
                },
                {
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-19T22:00:00+00:00",
                    "captured_at_local": "2026-06-19T18:00:00-04:00",
                    "source": "open_meteo",
                    "ok": False,
                    "stale": False,
                    "status": "rate_limited",
                    "cache_status": "provider_cooldown",
                    "source_family": "open_meteo",
                    "degradation_state": "rate_limited",
                    "retry_after_seconds": "60.0",
                    "age_minutes": "0.5",
                },
            ]).to_csv(folder / "source_status_long.csv", index=False)

            payload = source_family_degradation(folder)

        open_meteo = payload["families"]["open_meteo"]
        self.assertEqual(payload["affected_family_count"], 1)
        self.assertEqual(payload["blocking_family_count"], 0)
        self.assertTrue(payload["trading_evidence_allowed"])
        self.assertTrue(payload["claim_lane_allowance"]["model_review"])
        self.assertTrue(payload["claim_lane_allowance"]["paper_trading"])
        self.assertFalse(payload["claim_lane_allowance"]["live_trade_permission"])
        self.assertFalse(payload["claim_lane_allowance"]["promotion_readiness"])
        self.assertEqual(payload["provider_cooldown_source_count"], 1)
        self.assertEqual(open_meteo["status"], "rate_limited_with_fresh_family_coverage")
        self.assertFalse(open_meteo["trading_blocking"])
        self.assertEqual(open_meteo["provider_cooldown_sources"], ["open_meteo"])
        self.assertEqual(open_meteo["max_retry_after_seconds"], 60.0)
        self.assertEqual(open_meteo["top_cache_states"]["provider_cooldown"], 1)
        self.assertEqual(
            open_meteo["claim_lane_allowance"],
            {
                "model_review": True,
                "paper_trading": True,
                "live_trade_permission": False,
                "promotion_readiness": False,
            },
        )

    def test_source_family_degradation_flags_multi_market_settlement_auth_outage(self):
        markets = []
        for market_id in ("atlanta", "nyc"):
            with tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                pd.DataFrame([
                    {
                        "snapshot_id": "s1",
                        "captured_at_utc": "2026-06-19T22:00:00+00:00",
                        "captured_at_local": "2026-06-19T18:00:00-04:00",
                        "source": "wu_history",
                        "ok": False,
                        "stale": False,
                        "status": "settlement_source_auth_failure",
                        "cache_status": "auth_failure",
                        "source_family": "wu_history",
                        "degradation_state": "settlement_source_auth_failure",
                        "http_status": "403",
                    },
                ]).to_csv(folder / "source_status_long.csv", index=False)
                markets.append({
                    "market_id": market_id,
                    "source_family_degradation": source_family_degradation(folder),
                })
        summary = fleet_source_family_degradation_summary(markets)

        first = markets[0]["source_family_degradation"]["families"]["wu_history"]

        self.assertEqual(first["status"], "settlement_source_auth_failure")
        self.assertTrue(first["trading_blocking"])
        self.assertEqual(first["settlement_auth_failure_sources"], ["wu_history"])
        self.assertFalse(
            any("credential" in key for key in markets[0]["source_family_degradation"])
        )
        self.assertEqual(summary["settlement_source_auth_failure_market_count"], 2)
        self.assertTrue(summary["settlement_source_auth_failure_fleet_blocker"])
        self.assertEqual(summary["settlement_auth_failure_source_count"], 2)
        self.assertEqual(summary["status"], "BLOCK")
        self.assertEqual(summary["root_cause_class"], "settlement_source_auth_failure")
        self.assertFalse(any("credential" in key for key in summary))

    def test_source_family_direct_rate_limit_is_nonblocking_with_fresh_family_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            pd.DataFrame([
                {
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-19T22:00:00+00:00",
                    "captured_at_local": "2026-06-19T18:00:00-04:00",
                    "source": "global_ensemble",
                    "ok": True,
                    "stale": False,
                    "status": "fresh_cache",
                    "cache_status": "fresh_cache",
                    "source_family": "open_meteo",
                    "degradation_state": "healthy",
                },
                {
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-19T22:00:00+00:00",
                    "captured_at_local": "2026-06-19T18:00:00-04:00",
                    "source": "open_meteo",
                    "ok": False,
                    "stale": False,
                    "status": "rate_limited",
                    "cache_status": "miss",
                    "source_family": "open_meteo",
                    "degradation_state": "rate_limited",
                },
            ]).to_csv(folder / "source_status_long.csv", index=False)

            payload = source_family_degradation(folder)

        open_meteo = payload["families"]["open_meteo"]
        self.assertEqual(payload["affected_family_count"], 1)
        self.assertEqual(payload["blocking_family_count"], 0)
        self.assertTrue(payload["trading_evidence_allowed"])
        self.assertFalse(payload["live_trade_permission_allowed"])
        self.assertEqual(open_meteo["status"], "rate_limited_with_fresh_family_coverage")
        self.assertFalse(open_meteo["trading_blocking"])

    def test_source_family_provider_cooldown_blocks_without_fresh_family_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            pd.DataFrame([
                {
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-19T22:00:00+00:00",
                    "captured_at_local": "2026-06-19T18:00:00-04:00",
                    "source": "open_meteo",
                    "ok": False,
                    "stale": False,
                    "status": "rate_limited",
                    "cache_status": "provider_cooldown",
                    "source_family": "open_meteo",
                    "degradation_state": "rate_limited",
                },
            ]).to_csv(folder / "source_status_long.csv", index=False)

            payload = source_family_degradation(folder)

        open_meteo = payload["families"]["open_meteo"]
        self.assertEqual(payload["affected_family_count"], 1)
        self.assertEqual(payload["blocking_family_count"], 1)
        self.assertFalse(payload["trading_evidence_allowed"])
        self.assertFalse(payload["claim_lane_allowance"]["paper_trading"])
        self.assertFalse(payload["claim_lane_allowance"]["live_trade_permission"])
        self.assertEqual(open_meteo["status"], "degraded")
        self.assertTrue(open_meteo["trading_blocking"])

    def test_artifact_metadata_records_schema_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.json"
            path.write_text(
                json.dumps({"schema_version": "demo_v1", "generated_at_utc": "2026-06-12T00:00:00Z"}),
                encoding="utf-8",
            )

            meta = artifact_metadata(path, kind="demo")

        self.assertTrue(meta["exists"])
        self.assertEqual(meta["schema_version"], "demo_v1")
        self.assertEqual(meta["schema_status"], "ok")
        self.assertIsNotNone(meta["sha256"])

    def test_artifact_metadata_recognizes_legacy_per_hour_feature_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feature_model_coefs.json"
            path.write_text(
                json.dumps({"12": {"feature_schema_version": "feature_store_v1"}}),
                encoding="utf-8",
            )

            meta = artifact_metadata(path, kind="feature_model_coefs")

        self.assertEqual(meta["schema_status"], "ok")
        self.assertEqual(meta["schema_version"], "feature_model_coefs_v0.1")
        self.assertEqual(meta["feature_schema_version"], "feature_store_v1")

    def test_audit_alerts_ignore_wu_gaps_covered_by_redundant_sources(self):
        alerts = audit_alerts(
            {
                "nyc": {
                    "missing_days": ["2000-06-07"],
                    "sparse_days": [["2000-06-08", 1]],
                    "duplicate_timestamps": [],
                    "impossible_values": [],
                }
            },
            gap_coverage={
                "markets": {
                    "nyc": {
                        "unresolved_missing_days": [],
                        "unresolved_sparse_days": [],
                    }
                }
            },
        )

        self.assertEqual(alerts, [])

    def test_audit_alerts_warn_on_uncovered_historical_gaps(self):
        alerts = audit_alerts(
            {
                "nyc": {
                    "missing_days": ["2000-06-07"],
                    "sparse_days": [],
                    "duplicate_timestamps": [],
                    "impossible_values": [],
                }
            },
            gap_coverage={
                "markets": {
                    "nyc": {
                        "unresolved_missing_days": ["2000-06-07"],
                        "unresolved_sparse_days": [],
                    }
                }
            },
        )

        self.assertEqual(len(alerts), 1)
        self.assertIn("uncovered", alerts[0]["message"])

    def test_overall_status_uses_highest_alert_severity(self):
        self.assertEqual(overall_status([]), "OK")
        self.assertEqual(overall_status([{"severity": "warning"}]), "WARN")
        self.assertEqual(overall_status([{"severity": "warning"}, {"severity": "critical"}]), "CRITICAL")

    def test_cleanup_deletion_gate_requires_review_manifest(self):
        gate = cleanup_deletion_gate_summary()

        self.assertEqual(gate["status"], "REVIEW_REQUIRED")
        self.assertEqual(gate["delete_permission"], "allowed_only_with_reviewed_cleanup_manifest")

    def test_runtime_identity_alerts_warn_on_mixed_runtime_blocker(self):
        collection = {
            "markets": [
                {"market_id": "toronto", "target_date": "2026-06-21"},
                {"market_id": "atlanta", "target_date": "2026-06-21"},
                {"market_id": "nyc", "target_date": "2026-06-20"},
            ]
        }
        evidence = {
            "status": "BLOCK",
            "target_date": "2026-06-21",
            "blocking_reason": "mixed_runtime_identity_unsegmented",
            "runtime_identity_count": 2,
            "snapshot_row_count": 2446,
            "reconciliation_status": "missing",
        }

        alerts = runtime_identity_alerts(evidence)

        self.assertEqual(runtime_identity_target_date(collection), "2026-06-21")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "warning")
        self.assertEqual(alerts[0]["category"], "runtime_identity")
        self.assertIn("mixed runtime identities", alerts[0]["message"])
        self.assertEqual(alerts[0]["detail"]["runtime_identity_count"], 2)

    def test_trust_readiness_reports_gate_gaps(self):
        rows = trust_readiness([{"market": "nyc", "trust_score": 15, "settled_days": 1}])

        self.assertEqual(rows["nyc"]["trust_gap"], 10)
        self.assertEqual(rows["nyc"]["settled_day_gap"], 1)

    def test_clob_alerts_healthy_fleet_is_quiet(self):
        alerts = clob_alerts({
            "loop": {"state": "RUNNING", "heartbeat_age_seconds": 12.0},
            "books": {"markets": [
                {"market_id": "toronto", "ok": True, "captures": 500},
                {"market_id": "nyc", "ok": True, "captures": 480},
            ]},
        })

        self.assertEqual(alerts, [])

    def test_clob_alerts_dead_loop_is_critical_without_per_market_noise(self):
        alerts = clob_alerts({
            "loop": {"state": "DEAD", "pid": 123, "heartbeat_age_seconds": 999.0},
            "books": {"markets": [
                {"market_id": "toronto", "ok": False, "captures": 0, "reason": "no book captures"},
            ]},
        })

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "critical")
        self.assertEqual(alerts[0]["category"], "clob")
        self.assertIn("DEAD", alerts[0]["message"])

    def test_clob_alerts_tape_gap_is_critical_while_loop_runs(self):
        alerts = clob_alerts({
            "loop": {"state": "RUNNING"},
            "books": {"markets": [
                {
                    "market_id": "denver",
                    "ok": False,
                    "captures": 200,
                    "max_gap_seconds": 432.0,
                    "gaps_over_threshold": 2,
                    "reason": "2 gaps over 120s (max 432.0s)",
                },
                {"market_id": "toronto", "ok": True, "captures": 500},
            ]},
        })

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "critical")
        self.assertEqual(alerts[0]["market_id"], "denver")
        self.assertIn("gaps over", alerts[0]["message"])

    def test_clob_alerts_paused_loop_warns(self):
        alerts = clob_alerts({
            "loop": {"state": "PAUSED"},
            "books": {"markets": []},
        })

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "warning")

    def test_observation_alerts_dead_watcher_is_critical(self):
        alerts = observation_alerts({
            "state": "DEAD",
            "heartbeat_age_seconds": 999.0,
            "consecutive_errors": 0,
        })

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "critical")
        self.assertEqual(alerts[0]["category"], "observation_trigger")

    def test_live_forward_slo_passes_only_when_all_capture_loops_are_clean(self):
        collection = {"markets": [{"market_id": "toronto", "action_required": False}]}
        clob = {
            "loop": {"state": "RUNNING", "heartbeat_age_seconds": 10.0},
            "books": {"markets": [{"market_id": "toronto", "ok": True, "captures": 100}]},
        }
        observation = {"state": "RUNNING", "heartbeat_age_seconds": 10.0}

        gate = live_forward_slo_gate(collection, clob, observation)

        self.assertTrue(gate["ok"])
        self.assertTrue(gate["counts_toward_live_forward_gate"])
        self.assertEqual(gate["status"], "PASS")

    def test_live_forward_slo_blocks_on_event_metadata_validation(self):
        collection = {"markets": [{"market_id": "atlanta", "action_required": False}]}
        clob = {
            "loop": {"state": "RUNNING", "heartbeat_age_seconds": 10.0},
            "books": {"markets": [{"market_id": "atlanta", "ok": True, "captures": 100}]},
        }
        observation = {"state": "RUNNING", "heartbeat_age_seconds": 10.0}
        event_metadata = {
            "exists": True,
            "status": "BLOCK",
            "target_date": "2026-06-24",
            "validation_hash": "hash-1",
            "summary": {
                "issue_count": 1,
                "first_blocker": {
                    "market_id": "atlanta",
                    "event_slug": "highest-temperature-in-atlanta-on-june-24-2026",
                    "target_date": "2026-06-24",
                    "reason": "target event missing",
                    "first_issue": {"code": "target_event_missing"},
                    "remediation_command": "python -m weather.operations.location_config_refresh",
                    "recoverable_same_day": True,
                },
            },
        }

        gate = live_forward_slo_gate(collection, clob, observation, event_metadata)

        self.assertFalse(gate["ok"])
        self.assertEqual(gate["status"], "BLOCK")
        self.assertEqual(gate["first_blocker"]["gate"], "event_metadata_validation")
        self.assertEqual(gate["summary"]["first_blocking_owner"], "weather.operations.event_metadata_validation")

    def test_optional_market_event_stream_warning_does_not_block_live_forward_slo(self):
        collection = {"markets": [{"market_id": "toronto", "action_required": False}]}
        clob = {
            "loop": {
                "state": "RUNNING",
                "heartbeat_age_seconds": 10.0,
                "include_price_history": True,
                "include_ws_events": True,
                "last_market_results": {
                    "toronto": {
                        "books": 4,
                        "price_history_rows": 0,
                        "ws_messages": 0,
                        "ws_event_rows": 0,
                        "ws_error": "RuntimeError: websocket unavailable",
                    }
                },
            },
            "books": {"markets": [{"market_id": "toronto", "ok": True, "captures": 100}]},
        }
        observation = {"state": "RUNNING", "heartbeat_age_seconds": 10.0}

        gate = live_forward_slo_gate(collection, clob, observation)

        self.assertTrue(gate["ok"])
        self.assertEqual(gate["status"], "PASS")
        self.assertTrue(gate["counts_toward_live_forward_gate"])
        optional = gate["optional_market_event_streams"]
        self.assertEqual(optional["status"], "WARN")
        self.assertFalse(optional["blocks_core_model_review"])
        self.assertEqual(optional["issue_count"], 2)

    def test_optional_stream_gate_reads_separate_enrichment_not_raw_loop(self):
        collection = {"markets": [{"market_id": "toronto", "action_required": False}]}
        clob = {
            "loop": {
                "state": "RUNNING",
                "heartbeat_age_seconds": 5.0,
                "include_price_history": False,
                "include_ws_events": False,
                "critical_loop_enrichment_isolated": True,
                "last_market_results": {"toronto": {"books": 4}},
            },
            "enrichment": {
                "state": "RUNNING",
                "include_price_history": True,
                "include_ws_events": True,
                "last_market_results": {
                    "toronto": {
                        "price_history_rows": 10,
                        "ws_messages": 1,
                        "ws_event_rows": 1,
                    }
                },
            },
            "books": {"markets": [{"market_id": "toronto", "ok": True, "captures": 100}]},
        }
        observation = {"state": "RUNNING", "heartbeat_age_seconds": 5.0}

        gate = live_forward_slo_gate(collection, clob, observation)

        optional = gate["optional_market_event_streams"]
        self.assertEqual(optional["status"], "PASS")
        self.assertEqual(optional["capture_mode"], "separate_enrichment")
        self.assertEqual(optional["enrichment_state"], "RUNNING")
        self.assertTrue(gate["counts_toward_live_forward_gate"])

    def test_parquet_incremental_status_reads_backlog_and_alerts_on_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "closed_market_day_parquet_incremental.json"
            path.write_text(
                json.dumps({
                    "schema_version": "closed_market_day_parquet_incremental_v0.1",
                    "generated_at_utc": "2026-06-23T00:00:00+00:00",
                    "status": "BLOCK",
                    "mode": "apply",
                    "summary": {
                        "scanned": 2,
                        "converted": 1,
                        "blocked": 0,
                        "failed": 1,
                        "remaining_scan_backlog": 3,
                    },
                    "blocker_counts": {"active_writer_lock": 1},
                    "family_status_counts": {"parquet": 5},
                    "backlog_by_market": [{"market_id": "austin", "failed": 1}],
                }),
                encoding="utf-8",
            )

            status = parquet_incremental_status(path)
            alerts = parquet_incremental_alerts(status)

        self.assertTrue(status["exists"])
        self.assertEqual(status["status"], "BLOCK")
        self.assertEqual(status["failed"], 1)
        self.assertEqual(status["remaining_scan_backlog"], 3)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["category"], "closed_day_parquet_incremental")

    def test_live_forward_slo_blocks_on_snapshot_gap_clob_gap_or_watcher_failure(self):
        collection = {
            "markets": [{
                "market_id": "toronto",
                "action_required": True,
                "state": "AT_RISK",
                "reason": (
                    "2 gap(s), max 33 min; afternoon window not fully covered "
                    "(captured 00:02-13:52); latest capture is 40 min old"
                ),
                "latest_age_minutes": 40.0,
                "snapshots": 42,
                "source_family_degradation": {
                    "available": True,
                    "trading_evidence_allowed": False,
                    "affected_family_count": 1,
                    "failed_source_count": 1,
                    "families": {"nws_hourly": {"status": "degraded"}},
                },
            }]
        }
        clob = {
            "loop": {"state": "RUNNING"},
            "books": {"markets": [{
                "market_id": "toronto",
                "ok": False,
                "captures": 100,
                "trailing_age_seconds": 180.0,
                "reason": "last book capture is 180s old",
            }]},
        }
        observation = {"state": "DEAD", "heartbeat_age_seconds": 999.0}

        gate = live_forward_slo_gate(collection, clob, observation)

        self.assertFalse(gate["ok"])
        self.assertFalse(gate["counts_toward_live_forward_gate"])
        self.assertEqual(gate["status"], "BLOCK")
        self.assertEqual(
            {row["name"] for row in gate["gates"] if not row["ok"]},
            {"snapshot_collection", "clob_book_capture", "observation_trigger"},
        )
        concrete = {row["name"] for row in gate["concrete_gates"] if not row["ok"]}
        self.assertIn("snapshot_coverage_gap", concrete)
        self.assertIn("afternoon_window_coverage", concrete)
        self.assertIn("latest_model_row_freshness", concrete)
        self.assertIn("source_status_freshness", concrete)
        self.assertIn("clob_book_freshness", concrete)
        self.assertIn("observation_trigger_health", concrete)
        self.assertEqual(gate["first_blocker"]["market_id"], "toronto")
        self.assertEqual(gate["first_blocker"]["owner"], "weather snapshot/model loop")
        self.assertIn("snapshot_tracker --restart", gate["first_blocker"]["repair_command"])
        self.assertIn("fleet_observability report", gate["first_blocker"]["verification_command"])
        cadence = gate["snapshot_cadence_proof"]
        self.assertEqual(cadence["summary"]["blocked_market_count"], 1)
        self.assertEqual(cadence["summary"]["snapshot_coverage_gap_blocked_market_count"], 1)
        self.assertIn("snapshot_tracker --status", cadence["status_command"])
        self.assertIn("snapshot_tracker --restart", cadence["repair_command"])
        self.assertGreaterEqual(len(gate["recovery_checklist"]), 6)

    def test_live_forward_slo_surfaces_june19_all_market_snapshot_gap_shape(self):
        market_ids = [spec.id for spec in all_specs()]
        collection = {
            "markets": [
                {
                    "market_id": market_id,
                    "action_required": True,
                    "snapshot_action_required": True,
                    "state": "PARTIAL",
                    "reason": "2 gap(s), max 34 min",
                    "snapshots": 42,
                    "max_gap_minutes": 34.0,
                    "snapshot_cadence_proof": {
                        "status": "BLOCK",
                        "snapshot_count": 42,
                        "gap_count": 2,
                        "max_gap_minutes": 34.0,
                        "root_cause": "unknown_snapshot_gap",
                        "recoverable_same_day": False,
                        "gap_windows": [
                            {
                                "after": "2026-06-19T12:00:00-04:00",
                                "before": "2026-06-19T12:34:00-04:00",
                                "gap_minutes": 34.0,
                            }
                        ],
                    },
                }
                for market_id in market_ids
            ]
        }
        clob = {
            "loop": {"state": "RUNNING", "heartbeat_age_seconds": 5.0},
            "books": {"markets": [{"market_id": market_id, "ok": True} for market_id in market_ids]},
        }
        observation = {"state": "RUNNING", "heartbeat_age_seconds": 5.0}

        gate = live_forward_slo_gate(collection, clob, observation)
        concrete = {row["name"]: row for row in gate["concrete_gates"]}
        cadence = gate["snapshot_cadence_proof"]

        self.assertEqual(gate["status"], "BLOCK")
        self.assertEqual(
            {row["name"] for row in gate["gates"] if not row["ok"]},
            {"snapshot_collection"},
        )
        self.assertFalse(concrete["snapshot_coverage_gap"]["ok"])
        self.assertEqual(concrete["snapshot_coverage_gap"]["blocked_market_count"], 12)
        self.assertFalse(gate["first_blocker"]["recoverable_same_day"])
        self.assertEqual(cadence["summary"]["blocked_market_count"], 12)
        self.assertEqual(cadence["summary"]["snapshot_coverage_gap_blocked_market_count"], 12)
        self.assertEqual(cadence["summary"]["total_gap_count"], 24)
        self.assertEqual(cadence["summary"]["recoverable_same_day_market_count"], 0)
        self.assertEqual(cadence["summary"]["nonrecoverable_active_day_blocked_market_count"], 12)
        self.assertTrue(cadence["summary"]["clean_active_day_required"])
        self.assertIn("collect next active day", cadence["summary"]["next_unblock_action"])
        self.assertTrue(all(row["gap_windows"] for row in cadence["markets"]))
        self.assertIn("snapshot_tracker --restart", cadence["repair_command"])

    def test_snapshot_cadence_next_unblock_prioritizes_any_nonrecoverable_gap(self):
        collection = {
            "markets": [
                {
                    "market_id": "toronto",
                    "action_required": True,
                    "snapshot_action_required": True,
                    "state": "AT_RISK",
                    "reason": "1 gap(s), max 214 min",
                    "snapshots": 64,
                    "snapshot_cadence_proof": {
                        "status": "BLOCK",
                        "active_day_countable": False,
                        "recoverable_same_day": False,
                        "gap_count": 1,
                        "gap_windows": [{"gap_minutes": 214.0}],
                    },
                },
                {
                    "market_id": "nyc",
                    "action_required": True,
                    "snapshot_action_required": True,
                    "state": "AT_RISK",
                    "reason": "latest capture is 20 min old",
                    "snapshots": 80,
                    "snapshot_cadence_proof": {
                        "status": "BLOCK",
                        "active_day_countable": True,
                        "recoverable_same_day": True,
                        "gap_count": 0,
                    },
                },
            ]
        }
        clob = {"loop": {"state": "RUNNING"}, "books": {"markets": []}}
        observation = {"state": "RUNNING", "heartbeat_age_seconds": 5.0}

        cadence = live_forward_slo_gate(collection, clob, observation)["snapshot_cadence_proof"]

        self.assertEqual(cadence["summary"]["recoverable_same_day_market_count"], 1)
        self.assertEqual(cadence["summary"]["nonrecoverable_active_day_blocked_market_count"], 1)
        self.assertTrue(cadence["summary"]["clean_active_day_required"])
        self.assertIn("collect next active day", cadence["summary"]["next_unblock_action"])

    def test_live_forward_slo_source_status_settlement_auth_has_source_status_repair(self):
        collection = {
            "markets": [{
                "market_id": "toronto",
                "action_required": False,
                "state": "CLEAN",
                "reason": "ok",
                "snapshots": 49,
                "source_family_degradation": {
                    "available": True,
                    "trading_evidence_allowed": False,
                    "affected_family_count": 1,
                    "failed_source_count": 0,
                    "fallback_source_count": 0,
                    "settlement_auth_failure_source_count": 1,
                    "repair_command": (
                        "python -m weather.collection.snapshot_tracker --backfill-source-status "
                        "--overwrite-source-status --source-status-folder data/snapshots/toronto"
                    ),
                    "families": {
                        "wu_history": {
                            "status": "settlement_source_auth_failure",
                            "failed_source_count": 0,
                            "fallback_source_count": 0,
                            "rate_limited_source_count": 0,
                            "settlement_auth_failure_source_count": 1,
                            "settlement_auth_failure_sources": ["wu_history"],
                        },
                    },
                },
            }]
        }
        clob = {"loop": {"state": "RUNNING"}, "books": {"markets": []}}
        observation = {"state": "RUNNING", "heartbeat_age_seconds": 10.0}

        gate = live_forward_slo_gate(collection, clob, observation)

        self.assertFalse(gate["ok"])
        self.assertEqual(gate["first_blocker"]["component"], "source_status")
        self.assertEqual(
            gate["first_blocker"]["root_cause"],
            "settlement_source_auth_failure",
        )
        self.assertEqual(
            gate["first_blocker"]["owner"],
            "snapshot source-status writer / optional provider source",
        )
        self.assertFalse(gate["first_blocker"]["recoverable_same_day"])
        self.assertIn("--backfill-source-status", gate["first_blocker"]["repair_command"])
        self.assertNotIn("secret", json.dumps(gate["first_blocker"]).lower())

    def test_live_forward_slo_source_status_provider_fallback_has_specific_repair(self):
        collection = {
            "markets": [{
                "market_id": "toronto",
                "action_required": False,
                "state": "CLEAN",
                "reason": "ok",
                "snapshots": 49,
                "source_family_degradation": {
                    "available": True,
                    "trading_evidence_allowed": False,
                    "affected_family_count": 1,
                    "failed_source_count": 0,
                    "fallback_source_count": 2,
                    "repair_command": (
                        "python -m weather.collection.snapshot_tracker --backfill-source-status "
                        "--overwrite-source-status --source-status-folder data/snapshots/toronto"
                    ),
                    "families": {
                        "open_meteo": {
                            "status": "degraded",
                            "failed_source_count": 0,
                            "fallback_source_count": 2,
                            "rate_limited_source_count": 0,
                            "fallback_sources": ["open_meteo", "eccc_gem"],
                        },
                        "weather_forecast": {"status": "healthy"},
                    },
                },
            }]
        }
        clob = {"loop": {"state": "RUNNING"}, "books": {"markets": []}}
        observation = {"state": "RUNNING", "heartbeat_age_seconds": 10.0}

        gate = live_forward_slo_gate(collection, clob, observation)

        self.assertFalse(gate["ok"])
        self.assertEqual(gate["first_blocker"]["component"], "source_status")
        self.assertEqual(gate["first_blocker"]["root_cause"], "open_meteo_provider_fallback")
        self.assertEqual(gate["first_blocker"]["owner"], "Open-Meteo quota / forecast source collector")
        self.assertFalse(gate["first_blocker"]["recoverable_same_day"])
        self.assertIn("--backfill-source-status", gate["first_blocker"]["repair_command"])
        self.assertIn("--source-status-folder data/snapshots/toronto", gate["first_blocker"]["repair_command"])
        self.assertIn("fallback_sources=open_meteo,eccc_gem", gate["first_blocker"]["detail"])

    def test_live_forward_slo_source_status_rate_limit_has_provider_owner(self):
        collection = {
            "markets": [{
                "market_id": "toronto",
                "action_required": False,
                "state": "CLEAN",
                "reason": "ok",
                "snapshots": 49,
                "source_family_degradation": {
                    "available": True,
                    "trading_evidence_allowed": False,
                    "affected_family_count": 1,
                    "failed_source_count": 0,
                    "fallback_source_count": 0,
                    "rate_limited_source_count": 2,
                    "repair_command": (
                        "python -m weather.collection.snapshot_tracker --backfill-source-status "
                        "--overwrite-source-status --source-status-folder data/snapshots/toronto"
                    ),
                    "families": {
                        "open_meteo": {
                            "status": "degraded",
                            "failed_source_count": 0,
                            "fallback_source_count": 0,
                            "rate_limited_source_count": 2,
                            "rate_limited_sources": ["open_meteo", "eccc_gem"],
                        },
                        "weather_forecast": {"status": "healthy"},
                    },
                },
            }]
        }
        clob = {"loop": {"state": "RUNNING"}, "books": {"markets": []}}
        observation = {"state": "RUNNING", "heartbeat_age_seconds": 10.0}

        gate = live_forward_slo_gate(collection, clob, observation)

        self.assertFalse(gate["ok"])
        self.assertEqual(gate["first_blocker"]["component"], "source_status")
        self.assertEqual(gate["first_blocker"]["root_cause"], "open_meteo_provider_rate_limited")
        self.assertEqual(gate["first_blocker"]["owner"], "Open-Meteo quota / forecast source collector")
        self.assertIn("--backfill-source-status", gate["first_blocker"]["repair_command"])
        self.assertIn("--source-status-folder data/snapshots/toronto", gate["first_blocker"]["repair_command"])
        self.assertIn("rate_limited_sources=open_meteo,eccc_gem", gate["first_blocker"]["detail"])

    def test_live_forward_slo_has_dedicated_variant_prediction_freshness_gate(self):
        collection = {
            "markets": [{
                "market_id": "toronto",
                "action_required": True,
                "snapshot_action_required": False,
                "state": "CLEAN",
                "reason": "capture cadence healthy",
                "snapshots": 49,
                "variant_prediction_tape": {
                    "action_required": True,
                    "state": "MISSING",
                    "reason": "variant_predictions_long.csv missing or empty",
                    "snapshot_id": "s48",
                    "active_variant_count": 1,
                    "latest_rows": 0,
                    "expected_latest_rows": 1,
                },
            }]
        }
        clob = {"loop": {"state": "RUNNING"}, "books": {"markets": []}}
        observation = {"state": "RUNNING", "heartbeat_age_seconds": 10.0}

        gate = live_forward_slo_gate(collection, clob, observation)
        concrete = {row["name"]: row for row in gate["concrete_gates"]}

        self.assertFalse(gate["ok"])
        self.assertFalse(concrete["variant_prediction_freshness"]["ok"])
        self.assertNotIn("snapshot_collection", {row["gate"] for row in gate["recovery_checklist"]})
        self.assertEqual(gate["first_blocker"]["component"], "variant_prediction_tape")

    def test_markdown_surfaces_cleanup_deletion_gate(self):
        payload = {
            "generated_at_utc": "2026-06-15T00:00:00+00:00",
            "status": "CRITICAL",
            "summary": {"critical_alerts": 1, "warning_alerts": 0},
            "collection": {
                "markets": [],
                "source_status_proof": {
                    "summary": {
                        "source_status_blocked_market_count": 1,
                        "live_trade_permission_blocked_market_count": 1,
                        "promotion_readiness_blocked_market_count": 1,
                        "top_degraded_family": "open_meteo",
                        "provider_cooldown_source_count": 1,
                        "settlement_auth_failure_source_count": 1,
                    },
                    "repair_command": (
                        "python -m weather.collection.snapshot_tracker "
                        "--backfill-source-status --overwrite-source-status"
                    ),
                    "verification_command": "python -m weather.collection.snapshot_tracker --status",
                    "markets": [
                        {
                            "market_id": "nyc",
                            "snapshot_id": "s48",
                            "model_review_allowed": True,
                            "paper_trading_allowed": True,
                            "live_trade_permission_allowed": False,
                            "promotion_readiness_allowed": False,
                            "affected_family_count": 1,
                            "blocking_family_count": 0,
                            "provider_cooldown_source_count": 1,
                            "top_degraded_family": "open_meteo",
                            "affected_families": [
                                {
                                    "family": "open_meteo",
                                    "status": "rate_limited_with_fresh_family_coverage",
                                    "failed_source_count": 0,
                                    "fallback_source_count": 0,
                                    "rate_limited_source_count": 1,
                                    "provider_cooldown_source_count": 1,
                                    "top_cache_states": {"provider_cooldown": 1},
                                    "max_retry_after_seconds": 60.0,
                                    "max_cache_age_minutes": 0.5,
                                }
                            ],
                            "repair_command": (
                                "python -m weather.collection.snapshot_tracker --backfill-source-status "
                                "--overwrite-source-status --source-status-folder data/snapshots/nyc"
                            ),
                        }
                    ],
                },
            },
            "historical_audits": {},
            "historical_audit_execution": {
                "status": "SKIPPED",
                "reason": "scheduled_bounded_mode",
                "historical_audits_omitted": True,
            },
            "historical_gap_coverage": {"markets": {}},
            "artifact_provenance": {"markets": {}},
            "trust_readiness": {},
            "trust_readiness_execution": {
                "status": "SKIPPED",
                "reason": "scheduled_bounded_mode",
                "trust_readiness_omitted": True,
            },
            "runtime_identity_execution": {
                "status": "SKIPPED",
                "reason": "scheduled_bounded_mode",
                "runtime_identity_evidence_omitted": True,
            },
            "trading_replay_execution": {
                "status": "SKIPPED",
                "reason": "scheduled_bounded_mode",
                "trading_evidence_omitted": True,
            },
            "clob": {"loop": {}, "books": {"markets": []}},
            "observation_trigger": {},
            "loop_integrity": {
                "summary": {"malformed_lines": 2, "duplicate_writer_count": 0},
                "rows": [
                    {
                        "name": "clob_capture",
                        "ok": False,
                        "malformed_lines": 2,
                        "duplicate_writer": False,
                        "writer_lock": {"pid": 123},
                        "status_writer": {"pid": 123},
                        "repair_command": "python -m weather.operations.loop_jsonl_repair repair data/logs/clob.jsonl",
                        "malformed_samples": [
                            {
                                "source": "console",
                                "path": "data/logs/clob.jsonl",
                                "line": 9,
                                "classification": "console_text",
                                "text": "Traceback sample",
                            }
                        ],
                    }
                ],
            },
            "current_code_soak": {
                "schema_version": "loop_current_code_soak_v0.1",
                "status": "BLOCK",
                "counts_toward_active_day": False,
                "window_days": 7,
                "cadence_slo_status": "BLOCK",
                "cadence_slo_reason": "clob_book_freshness blocks broad live-forward SLO for nyc",
                "current_identity": {"git_branch": "master", "git_commit": "abc123", "source_fingerprint": "current"},
                "verification_command": "python -m weather.reporting.fleet.fleet_observability report",
                "summary": {
                    "diagnostic_class_counts": {"stale_code": 3, "duplicate_writer_blocked_benign": 2},
                    "restart_class_counts": {"stale_code": 3},
                },
                "loops": [
                    {
                        "name": "snapshot_capture",
                        "status": "BLOCK",
                        "state": "STALE_CODE",
                        "runtime_code_state": "stale_code",
                        "single_writer": True,
                        "restart_count": 3,
                        "restart_budget": 6,
                        "duplicate_writer_incidents": 0,
                        "benign_duplicate_writer_blocks": 2,
                        "malformed_lines": 0,
                        "consecutive_errors": 0,
                        "blocking_reasons": ["runtime_code_state=stale_code"],
                    }
                ],
            },
            "live_forward_slo": {
                "status": "BLOCK",
                "counts_toward_live_forward_gate": False,
                "reason": "clob_book_freshness blocks broad live-forward SLO for nyc",
                "gates": [],
                "concrete_gates": [
                    {
                        "name": "clob_book_freshness",
                        "ok": False,
                        "blocked_market_count": 1,
                        "owner": "CLOB book supervisor",
                        "repair_command": "python -m weather.market.market_microstructure ensure",
                        "messages": [
                            "last book capture is 180s old",
                            "last book capture is 180s old",
                            "second market missing book",
                        ],
                    }
                ],
                "first_blocker": {
                    "market_id": "nyc",
                    "component": "clob_book_capture",
                    "gate": "clob_book_freshness",
                    "owner": "CLOB book supervisor",
                    "repair_command": "python -m weather.market.market_microstructure ensure",
                },
                "recovery_checklist": [
                    {
                        "market_id": "nyc",
                        "component": "clob_book_capture",
                        "gate": "clob_book_freshness",
                        "owner": "CLOB book supervisor",
                        "before": "trailing_age_seconds=180.0",
                        "repair_command": "python -m weather.market.market_microstructure ensure",
                        "verification_command": "python -m weather.reporting.fleet.fleet_observability report",
                        "after": "rerun broad live-forward SLO",
                    }
                ],
                "snapshot_cadence_proof": {
                    "summary": {
                        "status": "BLOCK",
                        "blocked_market_count": 1,
                        "snapshot_coverage_gap_blocked_market_count": 1,
                        "total_gap_count": 1,
                        "max_gap_minutes": 34.0,
                    },
                    "status_command": "python -m weather.collection.snapshot_tracker --status",
                    "repair_command": "python -m weather.collection.snapshot_tracker --restart",
                    "verification_command": "python -m weather.reporting.fleet.fleet_observability report",
                    "markets": [
                        {
                            "market_id": "nyc",
                            "status": "BLOCK",
                            "blocking_gates": ["snapshot_coverage_gap"],
                            "snapshot_count": 42,
                            "gap_count": 1,
                            "max_gap_minutes": 34.0,
                            "latest_age_minutes": 40.0,
                            "root_cause": "unknown_snapshot_gap",
                            "recoverable_same_day": False,
                            "gap_windows": [
                                {
                                    "after": "2026-06-19T12:00:00-04:00",
                                    "before": "2026-06-19T12:34:00-04:00",
                                    "gap_minutes": 34.0,
                                }
                            ],
                        }
                    ],
                },
                "rerun_command": "python -m weather.reporting.fleet.fleet_observability report",
            },
            "mm_paper_evidence": {
                "exists": True,
                "path": "data/backtest/mm_paper_report.json",
                "by_class": {
                    "model_review_evidence": {
                        "countable_market_count": 11,
                        "blocked_market_count": 1,
                        "all_selected_markets_count": False,
                        "first_blocked_market": "nyc",
                        "first_blocked_owner": "model-refresh",
                    }
                },
            },
            "cleanup_deletion_gate": {
                "status": "REVIEW_REQUIRED",
                "canonical_evidence": {
                    "delete_permission": "allowed_only_with_reviewed_cleanup_manifest",
                    "detail": "canonical evidence cleanup requires an explicit reviewed cleanup manifest",
                },
            },
            "runtime_identity_evidence": {
                "status": "BLOCK",
                "target_date": "2026-06-21",
                "mixed_runtime_identity": True,
                "runtime_identity_count": 2,
                "snapshot_row_count": 2446,
                "blocking_reason": "mixed_runtime_identity_unsegmented",
                "reconciliation_status": "missing",
                "snapshots": {
                    "segments": [
                        {
                            "runtime_git_commit": "5b6f5af2d396",
                            "row_count": 1337,
                            "snapshot_count": 48,
                            "market_count": 6,
                            "runtime_source_fingerprint": "source-a",
                            "runtime_code_states": {"current": 1337},
                        },
                        {
                            "runtime_git_commit": "2e3672d99680",
                            "row_count": 1109,
                            "snapshot_count": 41,
                            "market_count": 6,
                            "runtime_source_fingerprint": "source-b",
                            "runtime_code_states": {"current": 1109},
                        },
                    ]
                },
            },
            "alerts": [],
        }

        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "fleet.md"
            write_markdown(report, payload)
            text = report.read_text(encoding="utf-8")

        self.assertIn("## Cleanup Deletion Gate", text)
        self.assertIn("Trust replay: **SKIPPED**", text)
        self.assertIn("Historical audit: **SKIPPED**", text)
        self.assertIn("scheduled_bounded_mode", text)
        self.assertIn("Runtime-identity replay: **SKIPPED**", text)
        self.assertIn("MM/taker replay: **SKIPPED**", text)
        self.assertIn("REVIEW_REQUIRED", text)
        self.assertIn("allowed_only_with_reviewed_cleanup_manifest", text)
        self.assertIn("## Loop Artifact Integrity", text)
        self.assertIn("clob_capture", text)
        self.assertIn("loop_jsonl_repair repair", text)
        self.assertIn("Traceback sample", text)
        self.assertIn("## Current-Code Soak Proof", text)
        self.assertIn("runtime_code_state=stale_code", text)
        self.assertIn("duplicate_writer_blocked_benign", text)
        self.assertIn("## Per-Market MM Paper Evidence", text)
        self.assertIn("model_review_evidence", text)
        self.assertIn("nyc", text)
        self.assertIn("### Broad Recovery Checklist", text)
        self.assertIn("clob_book_freshness", text)
        self.assertIn("last book capture is 180s old (x2)", text)
        self.assertIn("second market missing book", text)
        self.assertEqual(text.count("last book capture is 180s old"), 1)
        self.assertIn("weather.market.market_microstructure ensure", text)
        self.assertIn("### Snapshot Cadence Proof", text)
        self.assertIn("unknown_snapshot_gap", text)
        self.assertIn("12:00->12:34", text)
        self.assertIn("weather.collection.snapshot_tracker --restart", text)
        self.assertIn("## Source Status Proof", text)
        self.assertNotIn("credential present", text.lower())
        self.assertIn("open_meteo:rate_limited_with_fresh_family_coverage", text)
        self.assertIn("--source-status-folder data/snapshots/nyc", text)
        self.assertIn("## Runtime Identity Evidence", text)
        self.assertIn("mixed_runtime_identity_unsegmented", text)
        self.assertIn("5b6f5af2d396", text)

    def test_mm_paper_evidence_summary_reads_per_market_credit_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mm_paper_report.json"
            path.write_text(
                json.dumps(
                    {
                        "generated_at_utc": "2026-06-17T17:00:00+00:00",
                        "summary": {
                            "per_market_live_forward_evidence": {
                                "model_review_evidence": {
                                    "countable_market_count": 11,
                                    "blocked_market_count": 1,
                                },
                                "live_trade_permission_evidence": {
                                    "countable_market_count": 0,
                                    "blocked_market_count": 12,
                                },
                            }
                        },
                        "per_market_evidence_credits": [
                            {
                                "market_id": "nyc",
                                "evidence_class": "model_review_evidence",
                                "counts": False,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            summary = mm_paper_evidence_summary(path)

        self.assertTrue(summary["exists"])
        self.assertEqual(summary["by_class"]["model_review_evidence"]["countable_market_count"], 11)
        self.assertEqual(summary["by_class"]["live_trade_permission_evidence"]["countable_market_count"], 0)
        self.assertEqual(summary["credit_rows"][0]["market_id"], "nyc")

    def test_mm_evidence_starvation_summary_flags_june20_all_stale_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_folder = Path(tmp) / "mm_runs" / "2026-06-20" / "20260620T233005288278Z"
            run_folder.mkdir(parents=True)
            markets = []
            for index in range(12):
                markets.append({
                    "market_id": f"m{index}",
                    "status": "STALE",
                    "model_age_seconds": 11399.0,
                    "book_audit": {"trailing_age_seconds": 10260.1},
                    "gates": [
                        {
                            "name": "model_freshness",
                            "ok": False,
                            "severity": "stale",
                            "detail": "current model snapshot is stale or timestamp is missing",
                        },
                        {
                            "name": "clob_freshness",
                            "ok": False,
                            "severity": "stale",
                            "detail": "last book capture is 10260s old",
                        },
                        {
                            "name": "observation_trigger",
                            "ok": False,
                            "severity": "stale",
                            "detail": "stale or erroring observation watcher",
                        },
                    ],
                })
            (run_folder / "run_summary.json").write_text(
                json.dumps({
                    "run_id": "20260620T233005288278Z",
                    "target_date": "2026-06-20",
                    "run_folder": str(run_folder),
                    "evidence_mode": "active_day_live_forward",
                    "counts_toward_live_forward_gate": False,
                    "preflight_status": "STALE",
                    "cumulative": {"blocked_by_preflight_count": 66},
                    "preflight": {"status": "STALE", "markets": markets},
                    "live_forward_gate": {
                        "summary": {"market_count": 12, "blocked_market_count": 12},
                        "evidence": {
                            "paper_trading_evidence": {
                                "market_count": 12,
                                "countable_market_count": 0,
                                "blocked_market_count": 12,
                            },
                            "live_trade_permission_evidence": {
                                "market_count": 12,
                                "countable_market_count": 0,
                                "blocked_market_count": 12,
                            },
                        },
                    },
                    "preflight_remediation": {
                        "owner_counts": {
                            "weather snapshot/model loop": 12,
                            "CLOB book supervisor": 12,
                            "observation-trigger supervisor": 12,
                        },
                        "root_cause_counts": {
                            "stale_model_row": 12,
                            "stale_clob_book_tape": 12,
                            "watcher_stale": 12,
                        },
                    },
                }),
                encoding="utf-8",
            )

            summary = mm_evidence_starvation_summary(Path(tmp) / "mm_runs")

        latest = summary["latest"]
        self.assertEqual(summary["status"], "CRITICAL")
        self.assertEqual(summary["starved_active_day_streak"], 1)
        self.assertEqual(summary["countable_paper_market_day_count"], 0)
        self.assertTrue(latest["starved_active_day"])
        self.assertEqual(latest["preflight_blocked_market_fraction"], 1.0)
        self.assertEqual(latest["blocked_by_preflight_count"], 66)
        self.assertIn("161", latest["recovery_owner_items"])
        self.assertIn("157", latest["recovery_owner_items"])
        self.assertEqual(latest["max_stale_input_age_seconds"], 11399.0)
        self.assertIn("owners=161,157", summary["critical_alert"]["message"])

    def test_mm_evidence_starvation_summary_marks_june21_toronto_atlanta_closeout_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_folder = Path(tmp) / "mm_runs" / "2026-06-21" / "20260621T153607128252Z"
            run_folder.mkdir(parents=True)
            markets = [
                {
                    "market_id": "toronto",
                    "status": "STALE",
                    "model_age_seconds": 7200.0,
                    "gates": [
                        {
                            "name": "model_freshness",
                            "ok": False,
                            "severity": "stale",
                            "detail": "current model snapshot is stale or timestamp is missing",
                        }
                    ],
                },
                {
                    "market_id": "atlanta",
                    "status": "STALE",
                    "book_audit": {"trailing_age_seconds": 3570.0},
                    "gates": [
                        {
                            "name": "clob_freshness",
                            "ok": False,
                            "severity": "stale",
                            "detail": "last book capture is 3570s old",
                        }
                    ],
                },
            ]
            (run_folder / "run_summary.json").write_text(
                json.dumps({
                    "run_id": "20260621T153607128252Z",
                    "target_date": "2026-06-21",
                    "run_folder": str(run_folder),
                    "evidence_mode": "active_day_live_forward",
                    "counts_toward_live_forward_gate": False,
                    "preflight_status": "WARN",
                    "quote_permission_rows": 0,
                    "live_trade_permission_rows": 0,
                    "markets": markets,
                    "live_forward_gate": {
                        "summary": {"market_count": 2, "blocked_market_count": 2},
                        "evidence": {
                            "paper_trading_evidence": {
                                "market_count": 2,
                                "countable_market_count": 0,
                                "blocked_market_count": 2,
                            },
                            "live_trade_permission_evidence": {
                                "market_count": 2,
                                "countable_market_count": 0,
                                "blocked_market_count": 2,
                            },
                        },
                    },
                    "preflight_remediation": {
                        "owner_counts": {
                            "weather snapshot/model loop": 1,
                            "CLOB book supervisor": 1,
                        },
                        "root_cause_counts": {
                            "stale_model_row": 1,
                            "stale_clob_book_tape": 1,
                        },
                    },
                }),
                encoding="utf-8",
            )
            (run_folder / "preflight_recovery_closeout.json").write_text(
                json.dumps({
                    "schema_version": "mm_preflight_recovery_closeout_v0.1",
                    "status": "RECOVERED",
                    "recovered": True,
                    "unrecovered": False,
                    "incident_count": 2,
                    "command_results": [
                        {
                            "suggested_command": "python -m weather.collection.snapshot_tracker --status",
                            "action": "skipped",
                            "status": "SKIPPED",
                            "skip_reason": "dry run",
                        },
                        {
                            "suggested_command": "python -m weather.market.market_microstructure ensure",
                            "action": "skipped",
                            "status": "SKIPPED",
                            "skip_reason": "dry run",
                        },
                    ],
                    "post_repair_preflight_artifact_path": str(run_folder / "post_repair_preflight.json"),
                    "post_repair_run": {
                        "run_id": "20260621T153607128252Z-postrepair",
                        "preflight_status": "PASS",
                        "counts_toward_live_forward_gate": True,
                    },
                }),
                encoding="utf-8",
            )

            summary = mm_evidence_starvation_summary(Path(tmp) / "mm_runs")

        latest = summary["latest"]
        self.assertEqual(summary["status"], "RECOVERED")
        self.assertEqual(summary["starved_active_day_count"], 1)
        self.assertEqual(summary["recovered_starved_active_day_count"], 1)
        self.assertEqual(summary["unrecovered_starved_active_day_count"], 0)
        self.assertEqual(summary["critical_alert"], {})
        self.assertTrue(latest["starved_active_day"])
        self.assertEqual(latest["status"], "RECOVERED")
        self.assertEqual(latest["preflight_recovery_closeout_status"], "RECOVERED")
        self.assertTrue(latest["preflight_recovery_recovered"])
        self.assertEqual(latest["post_repair_preflight_status"], "PASS")
        self.assertIn("python -m weather.collection.snapshot_tracker --status", latest["recovery_command"])
        self.assertIn("python -m weather.market.market_microstructure ensure", latest["recovery_command"])

    def test_loop_integrity_alerts_warn_on_malformed_jsonl_and_critical_on_duplicate_writer(self):
        alerts = loop_integrity_alerts({
            "rows": [
                {
                    "name": "snapshot_capture",
                    "malformed_lines": 1,
                    "duplicate_writer": False,
                    "diagnostics_integrity": {"malformed_lines": 1},
                    "console_integrity": {"malformed_lines": 0},
                    "malformed_samples": [{"path": "diag.jsonl", "line": 2, "classification": "partial_json"}],
                    "repair_command": "python -m weather.operations.loop_jsonl_repair repair diag.jsonl",
                },
                {
                    "name": "clob_capture",
                    "malformed_lines": 0,
                    "duplicate_writer": True,
                    "status_writer": {"pid": 1},
                    "writer_lock": {"pid": 2},
                },
            ]
        })

        self.assertEqual([row["severity"] for row in alerts], ["warning", "critical"])
        self.assertEqual({row["category"] for row in alerts}, {"loop_integrity"})
        self.assertIn("loop_jsonl_repair repair", alerts[0]["detail"]["repair_command"])

    def test_loop_restart_taxonomy_separates_stale_code_and_benign_duplicate_writer(self):
        self.assertEqual(
            classify_loop_diagnostic_event({
                "status": "stale_code",
                "detail": "process code identity differs from current source tree",
            }),
            "stale_code",
        )
        self.assertEqual(
            classify_loop_diagnostic_event({
                "status": "duplicate_writer_blocked",
                "existing_writer": {"exists": False},
            }),
            "duplicate_writer_blocked_benign",
        )
        self.assertEqual(
            classify_loop_diagnostic_event({
                "status": "duplicate_writer_blocked",
                "existing_writer": {"exists": True, "pid": 123},
            }),
            "duplicate_writer_incident",
        )

    def test_current_code_soak_blocks_stale_code_restarts_and_counts_benign_duplicates(self):
        now = datetime(2026, 6, 20, 12, 0, tzinfo=datetime.now().astimezone().tzinfo)
        current_identity = {
            "git_branch": "master",
            "git_commit": "abc123",
            "source_fingerprint": "current",
        }
        stale_identity = {
            "git_branch": "master",
            "git_commit": "abc123",
            "source_fingerprint": "stale",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "loop_status.json"
            diagnostics_path = root / "diagnostics.jsonl"
            console_path = root / "console.log"
            status_path.write_text(
                json.dumps(
                    {
                        "pid": 123,
                        "started_at": now.isoformat(),
                        "last_heartbeat": now.isoformat(),
                        "last_snapshot_written_at": now.isoformat(),
                        "interval_minutes": 10.0,
                        "consecutive_errors": 0,
                        "runtime_identity": stale_identity,
                        "status_writer": {"pid": 123},
                    }
                ),
                encoding="utf-8",
            )
            (root / "loop_supervisor_status.json").write_text(
                json.dumps({
                    "schema_version": "loop_supervisor_status_v0.1",
                    "action": "backoff",
                    "ensure_status": "BLOCKED",
                    "exit_code": 1,
                    "reason": "restart_backoff_active=30.0s",
                    "recovery_guard": {
                        "retry_at_utc": (now + timedelta(seconds=30)).isoformat(),
                        "retry_after_seconds": 30.0,
                    },
                }),
                encoding="utf-8",
            )
            diagnostics_path.write_text(
                "\n".join(
                    [
                        json.dumps({
                            "time": (now - timedelta(minutes=5)).isoformat(),
                            "status": "stale_code",
                            "detail": "code identity differs from current source tree",
                        }),
                        json.dumps({
                            "time": (now - timedelta(minutes=4)).isoformat(),
                            "status": "duplicate_writer_blocked",
                            "existing_writer": {"exists": False},
                        }),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            console_path.write_text("", encoding="utf-8")
            spec = SupervisorSpec(
                name="snapshot_capture",
                module="weather.collection.snapshot_tracker",
                status_path=status_path,
                diagnostics_path=diagnostics_path,
                console_log_path=console_path,
            )

            with patch("weather.collection.snapshot_tracker.pid_is_python", return_value=True):
                soak = current_code_soak_summary(
                    {
                        "rows": [
                            {
                                "name": "snapshot_capture",
                                "writer_lock": {"exists": False},
                                "status_writer": {"pid": 123},
                                "duplicate_writer": False,
                                "malformed_lines": 0,
                            }
                        ]
                    },
                    {"status": "PASS", "counts_toward_live_forward_gate": True},
                    now=now,
                    current_identity=current_identity,
                    specs=(spec,),
                )

        row = soak["loops"][0]
        self.assertEqual(soak["status"], "BLOCK")
        self.assertEqual(row["runtime_code_state"], "stale_code")
        self.assertEqual(row["restart_class_counts"]["stale_code"], 1)
        self.assertEqual(row["benign_duplicate_writer_blocks"], 1)
        self.assertEqual(row["duplicate_writer_incidents"], 0)
        self.assertEqual(row["supervisor_action"], "backoff")
        self.assertEqual(row["supervisor_ensure_status"], "BLOCKED")
        self.assertEqual(row["supervisor_exit_code"], 1)
        self.assertEqual(row["supervisor_retry_after_seconds"], 30.0)
        self.assertIn("runtime_code_state=stale_code", row["blocking_reasons"])

    def test_current_code_soak_keeps_historical_duplicate_writer_context_without_blocking_clean_window(self):
        now = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
        current_identity = {
            "git_branch": "master",
            "git_commit": "abc123",
            "source_fingerprint": "current",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "loop_status.json"
            diagnostics_path = root / "diagnostics.jsonl"
            console_path = root / "console.log"
            status_path.write_text(
                json.dumps(
                    {
                        "pid": 123,
                        "started_at": now.isoformat(),
                        "last_heartbeat": now.isoformat(),
                        "last_snapshot_written_at": now.isoformat(),
                        "interval_minutes": 10.0,
                        "consecutive_errors": 0,
                        "runtime_identity": current_identity,
                        "status_writer": {"pid": 123},
                    }
                ),
                encoding="utf-8",
            )
            diagnostics_path.write_text(
                json.dumps({
                    "time": (now - timedelta(days=2)).isoformat(),
                    "status": "duplicate_writer_blocked",
                    "existing_writer": {"exists": True, "pid": 456},
                })
                + "\n",
                encoding="utf-8",
            )
            console_path.write_text("", encoding="utf-8")
            spec = SupervisorSpec(
                name="snapshot_capture",
                module="weather.collection.snapshot_tracker",
                status_path=status_path,
                diagnostics_path=diagnostics_path,
                console_log_path=console_path,
            )

            with patch("weather.collection.snapshot_tracker.pid_is_python", return_value=True):
                soak = current_code_soak_summary(
                    {
                        "rows": [
                            {
                                "name": "snapshot_capture",
                                "writer_lock": {"exists": False},
                                "status_writer": {"pid": 123},
                                "duplicate_writer": False,
                                "malformed_lines": 0,
                            }
                        ]
                    },
                    {"status": "PASS", "counts_toward_live_forward_gate": True},
                    now=now,
                    current_identity=current_identity,
                    specs=(spec,),
                )

        row = soak["loops"][0]
        self.assertEqual(soak["status"], "PASS")
        self.assertEqual(row["duplicate_writer_incidents"], 0)
        self.assertEqual(row["diagnostic_duplicate_writer_incidents"], 1)
        self.assertEqual(soak["summary"]["diagnostic_duplicate_writer_incident_count"], 1)
        self.assertEqual(soak["summary"]["duplicate_writer_incident_count"], 0)

    def test_current_code_soak_includes_bot_daily_roll_supervisors(self):
        now = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
        current_identity = {
            "git_branch": "master",
            "git_commit": "abc123",
            "source_fingerprint": "current",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            taker_status = root / "taker_status.json"
            taker_diag = root / "taker_diagnostics.jsonl"
            taker_console = root / "taker_console.log"
            maker_status = root / "maker_status.json"
            maker_diag = root / "maker_diagnostics.jsonl"
            maker_console = root / "maker_console.log"
            for path, runner in (
                (taker_status, "taker_bot_daily_roll"),
                (maker_status, "market_making_daily_roll"),
            ):
                path.write_text(
                    json.dumps({
                        "runner": runner,
                        "status": "already_running",
                        "pid": 123,
                        "target_date": "2026-06-20",
                        "started_at_utc": now.isoformat(),
                        "runtime_identity": current_identity,
                        "artifact_liveness": {"status": "PASS", "ok": True},
                        "resource_diagnostics": {
                            "status": "PASS",
                            "private_bytes": 512 * 1024**2,
                        },
                        "incremental_persistence": {
                            "status": "PASS",
                            "mode": "append_checkpoint",
                        },
                        "status_writer": {"pid": 123},
                    }),
                    encoding="utf-8",
                )
            taker_diag.write_text(
                json.dumps({
                    "time": (now - timedelta(minutes=5)).isoformat(),
                    "supervisor": "ensure",
                    "action": "restart",
                    "state": "STALE_CODE",
                    "restart_cause": "superseded_code",
                    "runtime_identity_matches_current": False,
                })
                + "\n",
                encoding="utf-8",
            )
            maker_diag.write_text("", encoding="utf-8")
            taker_console.write_text("plain child console output\n", encoding="utf-8")
            maker_console.write_text("plain child console output\n", encoding="utf-8")
            taker_spec = TAKER_DAILY_ROLL_SUPERVISOR.with_paths(
                status_path=taker_status,
                diagnostics_path=taker_diag,
                console_log_path=taker_console,
            )
            maker_spec = MARKET_MAKING_DAILY_ROLL_SUPERVISOR.with_paths(
                status_path=maker_status,
                diagnostics_path=maker_diag,
                console_log_path=maker_console,
            )
            integrity = {
                "rows": [
                    {
                        "name": taker_spec.name,
                        "writer_lock": {"exists": False},
                        "status_writer": {"pid": 123},
                        "duplicate_writer": False,
                        "malformed_lines": 0,
                    },
                    {
                        "name": maker_spec.name,
                        "writer_lock": {"exists": False},
                        "status_writer": {"pid": 123},
                        "duplicate_writer": False,
                        "malformed_lines": 0,
                    },
                ]
            }

            with patch("weather.operations.taker_bot_daily_roll.pid_matches_taker_bot", return_value=True), \
                    patch("weather.operations.market_making_daily_roll.pid_matches_market_making_run", return_value=True):
                soak = current_code_soak_summary(
                    integrity,
                    {"status": "PASS", "counts_toward_live_forward_gate": True},
                    now=now,
                    current_identity=current_identity,
                    specs=(taker_spec, maker_spec),
                )

        rows = {row["name"]: row for row in soak["loops"]}
        self.assertEqual(soak["status"], "PASS")
        self.assertEqual(soak["summary"]["loop_count"], 2)
        self.assertIn("taker_bot_daily_roll", rows)
        self.assertIn("market_making_daily_roll", rows)
        self.assertEqual(rows["taker_bot_daily_roll"]["restart_class_counts"]["stale_code"], 1)
        self.assertEqual(rows["taker_bot_daily_roll"]["resource_diagnostics"]["status"], "PASS")
        self.assertEqual(
            rows["taker_bot_daily_roll"]["incremental_persistence"]["mode"],
            "append_checkpoint",
        )
        self.assertIn("start --force", " ".join(rows["taker_bot_daily_roll"]["restart_command"]))
        self.assertIn("ensure", " ".join(rows["market_making_daily_roll"]["ensure_command"]))

    def test_bot_daily_roll_plain_console_is_not_loop_integrity_malformed_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "taker_status.json"
            diagnostics_path = root / "taker_diagnostics.jsonl"
            console_path = root / "taker_console.log"
            status_path.write_text(json.dumps({"status_writer": {"pid": 123}}), encoding="utf-8")
            diagnostics_path.write_text(json.dumps({"time": "2026-06-20T12:00:00+00:00", "status": "ok"}) + "\n", encoding="utf-8")
            console_path.write_text("plain bot output\nTraceback text stays outside JSONL integrity\n", encoding="utf-8")
            spec = TAKER_DAILY_ROLL_SUPERVISOR.with_paths(
                status_path=status_path,
                diagnostics_path=diagnostics_path,
                console_log_path=console_path,
            )

            with patch.object(fleet_observability_loops, "SUPERVISED_LOOP_SPECS", (spec,)):
                integrity = fleet_observability_loops.loop_artifact_integrity()

        row = integrity["rows"][0]
        self.assertEqual(row["name"], "taker_bot_daily_roll")
        self.assertEqual(row["console_integrity"]["malformed_lines"], 0)
        self.assertEqual(row["console_integrity"]["skipped_reason"], "plain_text_daily_roll_console")
        self.assertTrue(row["ok"])

    def test_settled_day_freshness_alert_names_repair_commands(self):
        alerts = settled_day_freshness_alerts({
            "exists": True,
            "status": "FAIL",
            "target_date": "2026-06-17",
            "path": "data/backtest/settled_day_freshness.json",
            "summary": {"incomplete_market_count": 12},
            "repair_command": "python -m weather.operations.settled_day_freshness repair",
            "replay_status_repair_command": "python -m weather.operations.replay_status_backfill",
        })

        self.assertEqual(alerts[0]["severity"], "critical")
        self.assertEqual(alerts[0]["category"], "settled_day_freshness")
        self.assertIn("2026-06-17", alerts[0]["message"])
        self.assertEqual(len(alerts[0]["detail"]["repair_commands"]), 2)


if __name__ == "__main__":
    unittest.main()
