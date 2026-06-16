import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.abspath("src"))

from collection_health import fleet_collection_health  # noqa: E402
from fleet_observability import (  # noqa: E402
    artifact_metadata,
    audit_alerts,
    clob_alerts,
    live_forward_slo_gate,
    observation_alerts,
    overall_status,
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

            payload = fleet_collection_health(
                snapshots_root=root,
                live=True,
                as_of=datetime(2026, 6, 7, 19, 0),
            )

        self.assertEqual(payload["summary"]["market_count"], 12)
        by_market = {row["market_id"]: row for row in payload["markets"]}
        self.assertEqual(by_market["toronto"]["state"], "CLEAN")
        self.assertEqual(by_market["nyc"]["state"], "MISSING")

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
                "reason": "latest capture is 40 min old",
            }]
        }
        clob = {
            "loop": {"state": "RUNNING"},
            "books": {"markets": [{
                "market_id": "toronto",
                "ok": False,
                "captures": 100,
                "reason": "book tape gap",
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
            "live_forward_slo": {"gates": []},
            "tape_backup": {
                "status": "MISSING_CRITICAL_CLASS",
                "backup_root": "Z:/weather-tapes",
                "age_hours": 1.5,
                "file_count": 10,
                "missing_critical_classes": ["clob_tapes"],
                "checksum_failures": [{"path": "x", "reason": "sha256_mismatch"}],
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


if __name__ == "__main__":
    unittest.main()
