import tempfile
import unittest
from pathlib import Path

from weather.reporting.backtest_artifact_retention import (
    apply_cleanup_manifest,
    build_cleanup_manifest,
    build_payload,
    paired_evidence_for_cleanup,
    render_report,
)


class TestBacktestArtifactRetention(unittest.TestCase):
    def test_classifies_rebuildable_variant_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "candidate_shadow_variants.csv").write_text("x" * 32, encoding="utf-8")
            (root / "candidate_replay_report.md").write_text("keep", encoding="utf-8")
            (root / "promotion_corpus.json").write_text("{}", encoding="utf-8")

            payload = build_payload(
                root=root,
                min_free_bytes=0,
                large_file_bytes=16,
                top_n=10,
            )

        cleanup = {row["path"]: row for row in payload["cleanup_candidates"]}
        self.assertEqual(payload["status"], "PASS")
        self.assertIn("candidate_shadow_variants.csv", cleanup)
        self.assertEqual(
            cleanup["candidate_shadow_variants.csv"]["retention_action"],
            "review_delete_rebuildable",
        )
        retained = {row["path"]: row for row in payload["largest_files"]}
        self.assertFalse(retained["candidate_replay_report.md"]["safe_delete_candidate"])
        self.assertFalse(retained["promotion_corpus.json"]["safe_delete_candidate"])

    def test_blocks_when_free_space_below_reserve(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "small_report.md").write_text("keep", encoding="utf-8")

            payload = build_payload(
                root=root,
                min_free_bytes=10**18,
                large_file_bytes=16,
                top_n=10,
            )
            report = render_report(payload)

        self.assertEqual(payload["status"], "BLOCK")
        self.assertGreater(payload["disk"]["free_shortfall_bytes"], 0)
        self.assertIn("Free-space shortfall", report)

    def test_cleanup_manifest_deletes_only_rebuildable_artifacts_with_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            long_csv = root / "active_variant_shadow_long.csv"
            long_csv.write_text("x" * 32, encoding="utf-8")
            (root / "active_variant_shadow.json").write_text("{}", encoding="utf-8")
            (root / "active_variant_shadow_report.md").write_text("keep", encoding="utf-8")
            orphan_csv = root / "orphan_shadow_variants.csv"
            orphan_csv.write_text("x" * 32, encoding="utf-8")

            payload = build_payload(
                root=root,
                min_free_bytes=0,
                large_file_bytes=16,
                top_n=10,
            )
            by_path = {row["path"]: row for row in payload["cleanup_candidates"]}
            evidence = paired_evidence_for_cleanup(by_path["active_variant_shadow_long.csv"], root)
            manifest = build_cleanup_manifest(payload, root=root)
            applied = apply_cleanup_manifest(manifest)

            self.assertEqual(
                evidence,
                ["active_variant_shadow.json", "active_variant_shadow_report.md"],
            )
            self.assertEqual(applied["status"], "APPLIED")
            self.assertEqual(applied["deleted_count"], 1)
            self.assertFalse(long_csv.exists())
            self.assertTrue(orphan_csv.exists())
            self.assertTrue((root / "active_variant_shadow_report.md").exists())

    def test_cleanup_allows_known_pooled_variant_exports_with_pooled_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export = root / "source_state_ablation_shadow_variants.csv"
            export.write_text("x" * 32, encoding="utf-8")
            (root / "pooled_candidate_replay_report.md").write_text("keep", encoding="utf-8")
            (root / "promotion_corpus.json").write_text("{}", encoding="utf-8")

            payload = build_payload(
                root=root,
                min_free_bytes=0,
                large_file_bytes=16,
                top_n=10,
            )
            manifest = build_cleanup_manifest(payload, root=root)
            applied = apply_cleanup_manifest(manifest)

            self.assertEqual(applied["deleted_count"], 1)
            self.assertFalse(export.exists())
            self.assertTrue((root / "pooled_candidate_replay_report.md").exists())

    def test_cleanup_matches_renamed_variant_rows_to_export_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = root / "item35_market_bias_source_guard_variant_rows.csv"
            rows.write_text("x" * 32, encoding="utf-8")
            export = root / "item35_direct_band_all_market_market_bias_source_guard_variant_export.json"
            report = root / "item35_direct_band_all_market_market_bias_source_guard_variant_export_report.md"
            export.write_text("{}", encoding="utf-8")
            report.write_text("keep", encoding="utf-8")

            payload = build_payload(
                root=root,
                min_free_bytes=0,
                large_file_bytes=16,
                top_n=10,
            )
            by_path = {row["path"]: row for row in payload["cleanup_candidates"]}
            evidence = paired_evidence_for_cleanup(by_path[rows.name], root)
            manifest = build_cleanup_manifest(payload, root=root)
            applied = apply_cleanup_manifest(manifest)

            self.assertEqual(
                evidence,
                [export.name, report.name],
            )
            self.assertEqual(applied["deleted_count"], 1)
            self.assertFalse(rows.exists())
            self.assertTrue(export.exists())
            self.assertTrue(report.exists())

    def test_cleanup_accepts_reports_that_reference_rebuildable_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_export = root / "item35_density_bridge_shadow_variants_v0_2.csv"
            csv_export.write_text("x" * 32, encoding="utf-8")
            report = root / "item35_density_full_replay_v0_2_report.md"
            report.write_text(
                "Shadow variant CSV | data\\backtest\\item35_density_bridge_shadow_variants_v0_2.csv",
                encoding="utf-8",
            )

            payload = build_payload(
                root=root,
                min_free_bytes=0,
                large_file_bytes=16,
                top_n=10,
            )
            by_path = {row["path"]: row for row in payload["cleanup_candidates"]}
            evidence = paired_evidence_for_cleanup(by_path[csv_export.name], root)
            manifest = build_cleanup_manifest(payload, root=root)
            applied = apply_cleanup_manifest(manifest)

            self.assertEqual(evidence, [report.name])
            self.assertEqual(applied["deleted_count"], 1)
            self.assertFalse(csv_export.exists())
            self.assertTrue(report.exists())

    def test_cleanup_accepts_source_state_ablation_exports_with_replay_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_export = root / "item35_density_source_state_ablation_v0_2.csv"
            csv_export.write_text("x" * 32, encoding="utf-8")
            report = root / "item35_density_full_replay_v0_2_report.md"
            report.write_text(
                "Shadow variant CSV | data\\backtest\\item35_density_source_state_ablation_v0_2.csv",
                encoding="utf-8",
            )

            payload = build_payload(
                root=root,
                min_free_bytes=0,
                large_file_bytes=16,
                top_n=10,
            )
            by_path = {row["path"]: row for row in payload["cleanup_candidates"]}
            evidence = paired_evidence_for_cleanup(by_path[csv_export.name], root)
            manifest = build_cleanup_manifest(payload, root=root)
            applied = apply_cleanup_manifest(manifest)

            self.assertEqual(evidence, [report.name])
            self.assertEqual(applied["deleted_count"], 1)
            self.assertFalse(csv_export.exists())
            self.assertTrue(report.exists())

    def test_cleanup_does_not_use_retention_report_as_circular_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_export = root / "orphan_shadow_variants.csv"
            csv_export.write_text("x" * 32, encoding="utf-8")
            (root / "backtest_artifact_retention_report.md").write_text(
                "| orphan_shadow_variants.csv | review_delete_rebuildable |",
                encoding="utf-8",
            )

            payload = build_payload(
                root=root,
                min_free_bytes=0,
                large_file_bytes=16,
                top_n=10,
            )
            manifest = build_cleanup_manifest(payload, root=root)
            applied = apply_cleanup_manifest(manifest)

            self.assertEqual(applied["deleted_count"], 0)
            self.assertTrue(csv_export.exists())


if __name__ == "__main__":
    unittest.main()
