import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.promotion.promotion_refresh import promotion_readiness, write_report
from weather.reporting.serving_gates.runtime_identity_evidence import build_runtime_identity_evidence, main


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_mixed_june21_snapshot_fixture(snapshots_root):
    folder = Path(snapshots_root) / "highest-temperature-in-toronto-on-june-21-2026"
    folder.mkdir(parents=True)
    path = folder / "snapshots_long.csv"
    fieldnames = [
        "snapshot_id",
        "market_id",
        "target_date",
        "runtime_identity_schema_version",
        "runtime_git_branch",
        "runtime_git_commit",
        "runtime_git_dirty",
        "runtime_dirty_fingerprint",
        "runtime_source_fingerprint",
        "runtime_code_state",
    ]
    rows = [
        ("5b6f5af2d396", "source-a", 1337),
        ("2e3672d99680", "source-b", 1109),
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        offset = 0
        for commit, source, count in rows:
            for index in range(count):
                writer.writerow({
                    "snapshot_id": f"s{offset + index}",
                    "market_id": "toronto",
                    "target_date": "2026-06-21",
                    "runtime_identity_schema_version": "runtime_identity_v0.1",
                    "runtime_git_branch": "master",
                    "runtime_git_commit": commit,
                    "runtime_git_dirty": "False",
                    "runtime_dirty_fingerprint": "",
                    "runtime_source_fingerprint": source,
                    "runtime_code_state": "current",
                })
            offset += count
    return path


def write_runtime_snapshot_rows(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "snapshot_id",
        "market_id",
        "target_date",
        "event_slug",
        "runtime_git_commit",
        "runtime_git_dirty",
        "runtime_source_fingerprint",
        "runtime_code_state",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def runtime_snapshot_row(snapshot_id, commit, *, target_date="", event_slug=""):
    return {
        "snapshot_id": snapshot_id,
        "market_id": "toronto",
        "target_date": target_date,
        "event_slug": event_slug,
        "runtime_git_commit": commit,
        "runtime_git_dirty": "False",
        "runtime_source_fingerprint": f"source-{commit}",
        "runtime_code_state": "current",
    }


class TestRuntimeIdentityEvidence(unittest.TestCase):
    def test_blank_target_dates_from_unrelated_event_folders_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "snapshots"
            requested_slug = "highest-temperature-in-toronto-on-june-21-2026"
            unrelated_slug = "highest-temperature-in-toronto-on-june-20-2026"
            write_runtime_snapshot_rows(
                snapshots / requested_slug / "snapshots_long.csv",
                [runtime_snapshot_row("requested", "commit-requested", event_slug=requested_slug)],
            )
            write_runtime_snapshot_rows(
                snapshots / unrelated_slug / "snapshots_long.csv",
                [runtime_snapshot_row("unrelated", "commit-unrelated", event_slug=unrelated_slug)],
            )

            payload = build_runtime_identity_evidence(
                snapshots_root=snapshots,
                target_date="2026-06-21",
                mm_runs_root=root / "mm_runs",
                taker_runs_root=root / "taker_runs",
                reconciliation_path=root / "backtest" / "runtime_identity_reconciliation.json",
            )

        scope = payload["snapshots"]["target_date_scope"]
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["runtime_identity_count"], 1)
        self.assertEqual(payload["snapshot_row_count"], 1)
        self.assertEqual(payload["snapshots"]["segments"][0]["runtime_git_commit"], "commit-requested")
        self.assertEqual(scope["scanned_snapshot_row_count"], 2)
        self.assertEqual(scope["excluded_snapshot_row_count"], 1)
        self.assertEqual(
            scope["excluded_by_reason"]["missing_target_date_enclosing_event_date_mismatch"],
            1,
        )

    def test_blank_target_date_uses_matching_registered_event_folder_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "snapshots"
            slug = "highest-temperature-in-toronto-on-june-21-2026"
            write_runtime_snapshot_rows(
                snapshots / slug / "snapshots_long.csv",
                [runtime_snapshot_row("legacy", "commit-legacy")],
            )

            payload = build_runtime_identity_evidence(
                snapshots_root=snapshots,
                target_date="2026-06-21",
                mm_runs_root=root / "mm_runs",
                taker_runs_root=root / "taker_runs",
                reconciliation_path=root / "backtest" / "runtime_identity_reconciliation.json",
            )

        segment = payload["snapshots"]["segments"][0]
        scope = payload["snapshots"]["target_date_scope"]
        self.assertEqual(payload["snapshot_row_count"], 1)
        self.assertEqual(segment["target_dates"], ["2026-06-21"])
        self.assertEqual(scope["included_by_provenance"]["enclosing_event_folder"], 1)
        self.assertEqual(scope["excluded_snapshot_row_count"], 0)

    def test_blank_target_date_in_unparseable_folder_is_excluded_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "snapshots"
            write_runtime_snapshot_rows(
                snapshots / "legacy-unknown-event" / "snapshots_long.csv",
                [runtime_snapshot_row("unknown", "commit-unknown")],
            )

            payload = build_runtime_identity_evidence(
                snapshots_root=snapshots,
                target_date="2026-06-21",
                mm_runs_root=root / "mm_runs",
                taker_runs_root=root / "taker_runs",
                reconciliation_path=root / "backtest" / "runtime_identity_reconciliation.json",
            )

        scope = payload["snapshots"]["target_date_scope"]
        self.assertEqual(payload["snapshot_row_count"], 0)
        self.assertEqual(payload["runtime_identity_count"], 0)
        self.assertEqual(
            scope["excluded_by_reason"]["missing_target_date_unproven_enclosing_event_date"],
            1,
        )

    def test_june21_mixed_commits_block_unsegmented_model_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "snapshots"
            write_mixed_june21_snapshot_fixture(snapshots)
            write_json(
                root / "mm_runs" / "2026-06-21" / "mm-1" / "run_summary.json",
                {
                    "run_id": "mm-1",
                    "target_date": "2026-06-21",
                    "runtime_identity": {
                        "current_identity": {
                            "schema_version": "runtime_identity_v0.1",
                            "git_commit": "5b6f5af2d396",
                            "git_dirty": False,
                            "source_fingerprint": "source-a",
                        }
                    },
                },
            )
            write_json(
                root / "taker_runs" / "2026-06-21" / "taker-1" / "run_summary.json",
                {
                    "run_id": "taker-1",
                    "target_date": "2026-06-21",
                    "runtime_identity": {
                        "schema_version": "runtime_identity_v0.1",
                        "git_commit": "2e3672d99680",
                        "git_dirty": False,
                        "source_fingerprint": "source-b",
                    },
                },
            )

            payload = build_runtime_identity_evidence(
                snapshots_root=snapshots,
                target_date="2026-06-21",
                mm_runs_root=root / "mm_runs",
                taker_runs_root=root / "taker_runs",
                reconciliation_path=root / "backtest" / "runtime_identity_reconciliation.json",
            )

        self.assertEqual(payload["status"], "BLOCK")
        self.assertFalse(payload["broad_claim_allowed"])
        self.assertFalse(payload["promotion_claim_allowed"])
        self.assertTrue(payload["mixed_runtime_identity"])
        self.assertEqual(payload["runtime_identity_count"], 2)
        self.assertEqual(payload["snapshot_row_count"], 2446)
        self.assertEqual(payload["blocking_reason"], "mixed_runtime_identity_unsegmented")
        by_commit = {
            row["runtime_git_commit"]: row["row_count"]
            for row in payload["snapshots"]["segments"]
        }
        self.assertEqual(by_commit["5b6f5af2d396"], 1337)
        self.assertEqual(by_commit["2e3672d99680"], 1109)
        self.assertEqual(payload["trading_runs"]["market_making"][0]["run_count"], 1)
        self.assertEqual(payload["trading_runs"]["taker"][0]["run_count"], 1)

    def test_reconciliation_can_explicitly_allow_mixed_runtime_aggregation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "snapshots"
            write_mixed_june21_snapshot_fixture(snapshots)
            reconciliation = root / "backtest" / "runtime_identity_reconciliation.json"
            write_json(
                reconciliation,
                {
                    "target_date": "2026-06-21",
                    "status": "PASS",
                    "allow_mixed_runtime_aggregation": True,
                },
            )

            payload = build_runtime_identity_evidence(
                snapshots_root=snapshots,
                target_date="2026-06-21",
                mm_runs_root=root / "mm_runs",
                taker_runs_root=root / "taker_runs",
                reconciliation_path=reconciliation,
            )

        self.assertEqual(payload["status"], "PASS")
        self.assertTrue(payload["broad_claim_allowed"])
        self.assertTrue(payload["promotion_claim_allowed"])
        self.assertTrue(payload["reconciliation_allowed"])
        self.assertEqual(payload["reconciliation_status"], "PASS")

    def test_cli_generates_blocked_report_without_nonzero_exit_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "snapshots"
            write_mixed_june21_snapshot_fixture(snapshots)

            exit_code = main([
                "--snapshots-root", str(snapshots),
                "--target-date", "2026-06-21",
                "--mm-runs-root", str(root / "mm_runs"),
                "--taker-runs-root", str(root / "taker_runs"),
                "--reconciliation", str(root / "backtest" / "runtime_identity_reconciliation.json"),
                "--json-out", str(root / "runtime.json"),
                "--report-out", str(root / "runtime.md"),
            ])
            report_text = (root / "runtime.md").read_text(encoding="utf-8")
            json_exists = (root / "runtime.json").exists()

        self.assertEqual(exit_code, 0)
        self.assertTrue(json_exists)
        self.assertIn("Status: **BLOCK**", report_text)

    def test_promotion_readiness_blocks_mixed_runtime_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "snapshots"
            path = write_mixed_june21_snapshot_fixture(snapshots)
            manifest = {
                "entries": [
                    {
                        "snapshot_tape_path": str(path),
                        "snapshot_ids": [f"s{index}" for index in range(2446)],
                        "market_id": "toronto",
                        "target_date": "2026-06-21",
                    }
                ]
            }
            evidence = build_runtime_identity_evidence(
                snapshot_manifest=manifest,
                mm_runs_root=root / "mm_runs",
                taker_runs_root=root / "taker_runs",
                reconciliation_path=root / "backtest" / "runtime_identity_reconciliation.json",
            )

            readiness = promotion_readiness(
                {"aggregate": {}},
                {},
                {"family_unit": "F", "markets": []},
                runtime_identity_evidence=evidence,
            )
            report_path = write_report(
                root / "promotion.md",
                {
                    "family_unit": "F",
                    "generated_at_utc": "2026-06-22T00:00:00+00:00",
                    "corpus": {},
                    "candidate": {"aggregate": {}},
                    "decisions": {},
                    "readiness": readiness,
                    "runtime_identity_evidence": evidence,
                },
            )
            report_text = report_path.read_text(encoding="utf-8")

        blockers = {row["category"]: row for row in readiness["blockers"]}
        self.assertEqual(evidence["snapshots"]["scope"], "promotion_manifest")
        self.assertIn("runtime_identity", blockers)
        self.assertEqual(blockers["runtime_identity"]["severity"], "block")
        self.assertIn("mixed runtime identities", blockers["runtime_identity"]["detail"])
        self.assertIn("## Runtime Identity Evidence", report_text)
        self.assertIn("2e3672d99680", report_text)


if __name__ == "__main__":
    unittest.main()
