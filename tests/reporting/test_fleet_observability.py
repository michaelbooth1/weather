import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from weather.collection.collection_health import fleet_collection_health, source_family_degradation  # noqa: E402
from weather.reporting.fleet_observability import (  # noqa: E402
    artifact_metadata,
    audit_alerts,
    clob_alerts,
    live_forward_slo_gate,
    loop_integrity_alerts,
    mm_paper_evidence_summary,
    observation_alerts,
    overall_status,
    settled_day_freshness_alerts,
    trust_readiness,
    write_markdown,
)


class TestFleetObservability(unittest.TestCase):
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
        fleet_sources = payload["summary"]["source_family_degradation"]
        self.assertEqual(fleet_sources["affected_market_count"], 1)
        self.assertEqual(fleet_sources["fallback_source_count"], 1)

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
                },
            ]).to_csv(folder / "source_status_long.csv", index=False)

            payload = source_family_degradation(folder)

        open_meteo = payload["families"]["open_meteo"]
        self.assertEqual(payload["affected_family_count"], 1)
        self.assertEqual(payload["blocking_family_count"], 0)
        self.assertTrue(payload["trading_evidence_allowed"])
        self.assertEqual(payload["provider_cooldown_source_count"], 1)
        self.assertEqual(open_meteo["status"], "rate_limited_with_fresh_family_coverage")
        self.assertFalse(open_meteo["trading_blocking"])
        self.assertEqual(open_meteo["provider_cooldown_sources"], ["open_meteo"])

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
        self.assertIn("snapshot_tracker --status", gate["first_blocker"]["repair_command"])
        self.assertIn("fleet_observability report", gate["first_blocker"]["verification_command"])
        self.assertGreaterEqual(len(gate["recovery_checklist"]), 6)

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
        self.assertIn("snapshot_tracker --status", gate["first_blocker"]["repair_command"])
        self.assertNotIn("backfill-source-status", gate["first_blocker"]["repair_command"])
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
        self.assertIn("snapshot_tracker --status", gate["first_blocker"]["repair_command"])
        self.assertNotIn("backfill-source-status", gate["first_blocker"]["repair_command"])
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

    def test_markdown_surfaces_tape_backup_status(self):
        payload = {
            "generated_at_utc": "2026-06-15T00:00:00+00:00",
            "status": "CRITICAL",
            "summary": {"critical_alerts": 1, "warning_alerts": 0},
            "collection": {"markets": []},
            "historical_audits": {},
            "historical_gap_coverage": {"markets": {}},
            "artifact_provenance": {"markets": {}},
            "trust_readiness": {},
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
                        "messages": ["last book capture is 180s old"],
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
                        "verification_command": "python -m weather.reporting.fleet_observability report",
                        "after": "rerun broad live-forward SLO",
                    }
                ],
                "rerun_command": "python -m weather.reporting.fleet_observability report",
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
            "tape_backup": {
                "status": "MISSING_CRITICAL_CLASS",
                "backup_root": "Z:/weather-tapes",
                "age_hours": 1.5,
                "file_count": 10,
                "missing_critical_classes": ["clob_tapes"],
                "checksum_failures": [{"path": "x", "reason": "sha256_mismatch"}],
                "restore_drill_sla_status": "OK",
                "restore_drill_sla_detail": "restore drill evidence is current",
                "last_restore_drill": {"status": "PASS", "generated_at_utc": "2026-06-15T01:00:00+00:00"},
            },
            "alerts": [],
        }

        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "fleet.md"
            write_markdown(report, payload)
            text = report.read_text(encoding="utf-8")

        self.assertIn("## Tape Backup And Restore", text)
        self.assertIn("MISSING_CRITICAL_CLASS", text)
        self.assertIn("clob_tapes", text)
        self.assertIn("Restore SLA", text)
        self.assertIn("restore drill evidence is current", text)
        self.assertIn("## Loop Artifact Integrity", text)
        self.assertIn("clob_capture", text)
        self.assertIn("loop_jsonl_repair repair", text)
        self.assertIn("Traceback sample", text)
        self.assertIn("## Per-Market MM Paper Evidence", text)
        self.assertIn("model_review_evidence", text)
        self.assertIn("nyc", text)
        self.assertIn("### Broad Recovery Checklist", text)
        self.assertIn("clob_book_freshness", text)
        self.assertIn("weather.market.market_microstructure ensure", text)

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
