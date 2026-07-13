import hashlib
import json
import tempfile
import unittest
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from weather.operations.storage_classes import ANALYSIS_PROJECTION, CANONICAL_EVIDENCE, OPERATOR_CACHE
from weather.reporting.data_quality.data_retention_inventory import (
    HEADROOM_PROBE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    build_headroom_probe,
    build_payload,
    main,
    render_report,
)


PROBE_NOW = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)


def _write_full_inventory(
    path: Path,
    root: Path,
    *,
    generated_at: datetime = PROBE_NOW - timedelta(hours=1),
    recent_bytes: int = 1_000,
    lookback_hours: float = 24.0,
    daily_recent_bytes: int | None = None,
) -> dict:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at.isoformat(),
        "mode": "full_inventory",
        "status": "PASS",
        "root": str(root),
        "root_exists": True,
        "lookback_hours": lookback_hours,
        "min_free_bytes": 0,
        "disk": {
            "daily_recent_bytes": (
                daily_recent_bytes
                if daily_recent_bytes is not None
                else int(recent_bytes * 24.0 / lookback_hours)
            )
        },
        "summary": {"file_count": 1, "recent_bytes": recent_bytes},
        "policy_summaries": [],
        "storage_class_summaries": [],
    }
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return payload


class TestDataRetentionInventory(unittest.TestCase):
    def test_classifies_data_owners_and_marks_review_required_classes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "snapshots" / "market-day" / "snapshots_long.csv"
            snapshot.parent.mkdir(parents=True)
            snapshot.write_text("x" * 32, encoding="utf-8")
            cache = root / "cache" / "provider.json"
            cache.parent.mkdir()
            cache.write_text("{}", encoding="utf-8")

            payload = build_payload(
                root,
                min_free_bytes=0,
                lookback_hours=48,
                top_n=5,
            )

        by_policy = {row["policy"]: row for row in payload["policy_summaries"]}
        by_storage_class = {row["storage_class"]: row for row in payload["storage_class_summaries"]}
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(by_policy["snapshots"]["owner"], "collection/model/market")
        self.assertEqual(by_policy["snapshots"]["delete_gate"]["status"], "REVIEW_REQUIRED")
        self.assertIn(ANALYSIS_PROJECTION, by_storage_class)
        self.assertIn(OPERATOR_CACHE, by_storage_class)
        self.assertEqual(by_storage_class[ANALYSIS_PROJECTION]["delete_gate"]["status"], "REVIEW_REQUIRED")
        self.assertIn("snapshot_csv_long_tables", by_storage_class[ANALYSIS_PROJECTION]["artifact_families"])
        self.assertEqual(
            by_policy["snapshots"]["delete_gate"]["delete_permission"],
            "allowed_only_with_reviewed_manifest",
        )
        self.assertEqual(by_policy["provider_caches"]["delete_gate"]["status"], "NOT_REQUIRED")

    def test_canonical_evidence_delete_gate_requires_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mm = root / "mm_runs" / "run1" / "order_lifecycle.jsonl"
            mm.parent.mkdir(parents=True)
            mm.write_text("{}\n", encoding="utf-8")

            payload = build_payload(root, min_free_bytes=0)
            report = render_report(payload)

        by_policy = {row["policy"]: row for row in payload["policy_summaries"]}
        by_storage_class = {row["storage_class"]: row for row in payload["storage_class_summaries"]}
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(by_policy["mm_runs"]["delete_gate"]["status"], "REVIEW_REQUIRED")
        self.assertEqual(by_storage_class[CANONICAL_EVIDENCE]["delete_gate"]["status"], "REVIEW_REQUIRED")
        self.assertIn("Ownership And Retention", report)
        self.assertIn("Storage Class Summary", report)
        self.assertIn("Operator Procedure", report)

    def test_shared_forecast_cas_policy_reports_deletion_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            digest = "a" * 64
            blob = (
                root
                / "forecast_payload_cas"
                / "sha256"
                / digest[:2]
                / f"{digest}.blob"
            )
            blob.parent.mkdir(parents=True)
            blob.write_bytes(b"shared bytes")

            payload = build_payload(root, min_free_bytes=0)

        by_policy = {row["policy"]: row for row in payload["policy_summaries"]}
        shared_policy = by_policy["shared_forecast_payload_cas"]
        self.assertEqual(shared_policy["file_count"], 1)
        gate = shared_policy["delete_gate"]
        self.assertEqual(gate["status"], "BLOCK")
        self.assertEqual(gate["delete_permission"], "disabled")

    def test_reports_largest_and_recent_growth(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "backtest" / "old_report.md"
            old.parent.mkdir(parents=True)
            old.write_text("old", encoding="utf-8")
            large = root / "backtest" / "active_variant_shadow_long.csv"
            large.write_text("x" * 64, encoding="utf-8")

            payload = build_payload(root, min_free_bytes=0, lookback_hours=24, top_n=3)

        self.assertEqual(payload["largest_files"][0]["path"], "backtest/active_variant_shadow_long.csv")
        recent_dirs = {row["path"]: row for row in payload["recent_directories"]}
        self.assertIn("backtest", recent_dirs)
        self.assertGreaterEqual(recent_dirs["backtest"]["bytes"], 64)

    def test_blocks_when_recent_write_rate_exhausts_growth_headroom(self):
        disk_usage = namedtuple("disk_usage", "total used free")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recent = root / "backtest" / "large.csv"
            recent.parent.mkdir(parents=True)
            recent.write_text("x" * 200, encoding="utf-8")

            with patch(
                "weather.reporting.data_quality.data_retention_inventory.shutil.disk_usage",
                return_value=disk_usage(total=10_000, used=9_000, free=1_000),
            ):
                payload = build_payload(
                    root,
                    min_free_bytes=0,
                    min_growth_headroom_days=10,
                    lookback_hours=24,
                )

        self.assertEqual(payload["status"], "BLOCK")
        self.assertAlmostEqual(payload["disk"]["growth_headroom_days"], 5.0)
        self.assertAlmostEqual(payload["disk"]["growth_headroom_shortfall_days"], 5.0)
        self.assertIn("Growth headroom", render_report(payload))

    def test_bounded_headroom_probe_passes_without_walking_the_data_tree(self):
        disk_usage = namedtuple("disk_usage", "total used free")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "prior_full_inventory.json"
            _write_full_inventory(source, root)
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

            with (
                patch(
                    "weather.reporting.data_quality.data_retention_inventory.shutil.disk_usage",
                    return_value=disk_usage(total=200_000, used=100_000, free=100_000),
                ),
                patch(
                    "weather.reporting.data_quality.data_retention_inventory.os.walk",
                    side_effect=AssertionError("bounded probe must not walk the data tree"),
                ),
            ):
                payload = build_headroom_probe(
                    source,
                    root=root,
                    min_free_bytes=0,
                    now=PROBE_NOW,
                )

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["schema_version"], HEADROOM_PROBE_SCHEMA_VERSION)
        self.assertEqual(payload["source_inventory_sha256"], source_hash)
        self.assertTrue(payload["source_inventory"]["trustworthy"])
        self.assertFalse(payload["summary"]["filesystem_walk_performed"])
        self.assertEqual(payload["disk"]["daily_recent_bytes"], 1_000)
        self.assertAlmostEqual(payload["disk"]["growth_headroom_days"], 100.0)
        self.assertEqual(payload["disk"]["required_headroom_bytes"], 30_000)
        self.assertIn("Bounded Storage Headroom Probe", render_report(payload))

    def test_bounded_headroom_probe_blocks_below_thirty_days(self):
        disk_usage = namedtuple("disk_usage", "total used free")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "prior_full_inventory.json"
            _write_full_inventory(source, root)
            with patch(
                "weather.reporting.data_quality.data_retention_inventory.shutil.disk_usage",
                return_value=disk_usage(total=100_000, used=80_000, free=20_000),
            ):
                payload = build_headroom_probe(
                    source,
                    root=root,
                    min_free_bytes=0,
                    now=PROBE_NOW,
                )

        self.assertEqual(payload["status"], "BLOCK")
        self.assertAlmostEqual(payload["disk"]["growth_headroom_days"], 20.0)
        self.assertAlmostEqual(payload["disk"]["growth_headroom_shortfall_days"], 10.0)
        self.assertIn(
            "growth_headroom_below_minimum",
            {row["code"] for row in payload["blockers"]},
        )

    def test_bounded_headroom_probe_derives_rate_for_legacy_full_inventory(self):
        disk_usage = namedtuple("disk_usage", "total used free")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "prior_full_inventory.json"
            payload = _write_full_inventory(source, root, recent_bytes=2_000)
            payload["mode"] = "legacy_full_inventory"
            payload["disk"].pop("daily_recent_bytes")
            source.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            with patch(
                "weather.reporting.data_quality.data_retention_inventory.shutil.disk_usage",
                return_value=disk_usage(total=200_000, used=100_000, free=100_000),
            ):
                probe = build_headroom_probe(
                    source,
                    root=root,
                    min_free_bytes=0,
                    now=PROBE_NOW,
                )

        self.assertEqual(probe["status"], "PASS")
        self.assertEqual(probe["disk"]["daily_recent_bytes"], 2_000)

    def test_bounded_headroom_probe_fails_closed_on_stale_source(self):
        disk_usage = namedtuple("disk_usage", "total used free")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "prior_full_inventory.json"
            _write_full_inventory(
                source,
                root,
                generated_at=PROBE_NOW - timedelta(hours=169),
            )
            with patch(
                "weather.reporting.data_quality.data_retention_inventory.shutil.disk_usage",
                return_value=disk_usage(total=200_000, used=100_000, free=100_000),
            ):
                payload = build_headroom_probe(source, root=root, now=PROBE_NOW)

        self.assertEqual(payload["status"], "BLOCK")
        self.assertAlmostEqual(payload["source_inventory"]["age_hours"], 169.0)
        self.assertFalse(payload["source_inventory"]["trustworthy"])
        self.assertIn(
            "source_inventory_stale",
            payload["source_inventory"]["blocker_codes"],
        )

    def test_bounded_headroom_probe_fails_closed_on_malformed_or_zero_rate_source(self):
        disk_usage = namedtuple("disk_usage", "total used free")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            malformed = root / "malformed.json"
            malformed.write_text("{not-json", encoding="utf-8")
            zero_rate = root / "zero_rate.json"
            _write_full_inventory(
                zero_rate,
                root,
                recent_bytes=0,
                daily_recent_bytes=0,
            )
            with patch(
                "weather.reporting.data_quality.data_retention_inventory.shutil.disk_usage",
                return_value=disk_usage(total=200_000, used=100_000, free=100_000),
            ):
                malformed_payload = build_headroom_probe(
                    malformed,
                    root=root,
                    min_free_bytes=0,
                    now=PROBE_NOW,
                )
                zero_payload = build_headroom_probe(
                    zero_rate,
                    root=root,
                    min_free_bytes=0,
                    now=PROBE_NOW,
                )

        self.assertEqual(malformed_payload["status"], "BLOCK")
        self.assertIn(
            "source_inventory_malformed",
            malformed_payload["source_inventory"]["blocker_codes"],
        )
        self.assertEqual(zero_payload["status"], "BLOCK")
        self.assertEqual(zero_payload["disk"]["daily_recent_bytes"], 0)
        self.assertIsNone(zero_payload["disk"]["growth_headroom_days"])
        self.assertIn(
            "source_recent_write_rate_nonpositive",
            zero_payload["source_inventory"]["blocker_codes"],
        )

    def test_bounded_headroom_probe_pins_exact_source_bytes(self):
        disk_usage = namedtuple("disk_usage", "total used free")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "prior_full_inventory.json"
            _write_full_inventory(source, root)
            pinned_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            source.write_bytes(source.read_bytes() + b" ")
            mutated_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            with patch(
                "weather.reporting.data_quality.data_retention_inventory.shutil.disk_usage",
                return_value=disk_usage(total=200_000, used=100_000, free=100_000),
            ):
                payload = build_headroom_probe(
                    source,
                    root=root,
                    min_free_bytes=0,
                    expected_source_sha256=pinned_hash,
                    now=PROBE_NOW,
                )

        self.assertEqual(payload["status"], "BLOCK")
        self.assertEqual(payload["source_inventory_sha256"], mutated_hash)
        self.assertFalse(payload["source_inventory"]["hash_matches_expected"])
        self.assertIn(
            "source_inventory_hash_mismatch",
            payload["source_inventory"]["blocker_codes"],
        )

    def test_headroom_probe_cli_preserves_legacy_inventory_invocation(self):
        disk_usage = namedtuple("disk_usage", "total used free")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recent = root / "recent.csv"
            recent.write_text("x" * 1_000, encoding="utf-8")
            inventory_out = root / "inventory.json"
            inventory_report = root / "inventory.md"
            with patch("builtins.print"):
                legacy_exit = main(
                    [
                        "--root",
                        str(root),
                        "--out",
                        str(inventory_out),
                        "--report",
                        str(inventory_report),
                        "--min-free-bytes",
                        "0",
                    ]
                )
            self.assertEqual(legacy_exit, 0)
            self.assertEqual(
                json.loads(inventory_out.read_text(encoding="utf-8"))["mode"],
                "full_inventory",
            )

            probe_out = root / "probe.json"
            probe_report = root / "probe.md"
            with (
                patch(
                    "weather.reporting.data_quality.data_retention_inventory.shutil.disk_usage",
                    return_value=disk_usage(total=200_000, used=100_000, free=100_000),
                ),
                patch("builtins.print"),
            ):
                probe_exit = main(
                    [
                        "headroom-probe",
                        "--source-inventory",
                        str(inventory_out),
                        "--root",
                        str(root),
                        "--out",
                        str(probe_out),
                        "--report",
                        str(probe_report),
                        "--min-free-bytes",
                        "0",
                    ]
                )
            probe_payload = json.loads(probe_out.read_text(encoding="utf-8"))
            probe_report_text = probe_report.read_text(encoding="utf-8")

        self.assertEqual(probe_exit, 0)
        self.assertEqual(
            probe_payload["mode"],
            "bounded_storage_headroom_probe",
        )
        self.assertIn("Bounded Storage Headroom Probe", probe_report_text)


if __name__ == "__main__":
    unittest.main()
