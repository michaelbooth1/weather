import tempfile
import unittest
from pathlib import Path

from weather.operations.cleanup_preflight import (
    build_cleanup_preflight,
    cleanup_manifest_for_paths,
)


def write(path: Path, text: str = "x\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def review() -> dict:
    return {
        "approved": True,
        "approved_by": "unit-test",
        "approved_at_utc": "2026-06-23T00:00:00+00:00",
        "note": "reviewed cleanup manifest for unit test",
    }


class CleanupPreflightTests(unittest.TestCase):
    def test_canonical_cleanup_passes_with_reviewed_manifest_and_current_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            snapshot = write(data_root / "snapshots/event/snapshots.jsonl", "{}\n")
            manifest = cleanup_manifest_for_paths(
                [snapshot],
                root=data_root,
                deletion_reason="delete canonical snapshot after operator review",
                operator_review=review(),
            )

            preflight = build_cleanup_preflight(manifest, root=data_root)

        self.assertEqual(preflight["status"], "PASS")
        self.assertTrue(preflight["delete_permission"])

    def test_cleanup_blocks_missing_operator_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            snapshot = write(data_root / "snapshots/event/snapshots.jsonl", "{}\n")
            manifest = cleanup_manifest_for_paths(
                [snapshot],
                root=data_root,
                deletion_reason="delete canonical snapshot",
                operator_review={"approved": False},
            )

            preflight = build_cleanup_preflight(manifest, root=data_root)

        self.assertEqual(preflight["status"], "BLOCK")
        self.assertIn("operator_review", {
            check["check"]
            for check in preflight["checks"]
            if check["status"] == "BLOCK"
        })

    def test_projection_cleanup_requires_rebuild_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            projection = write(data_root / "backtest/active_variant_shadow_long.csv", "a\n1\n")
            manifest = cleanup_manifest_for_paths(
                [projection],
                root=data_root,
                deletion_reason="delete rebuildable projection",
                operator_review=review(),
            )
            manifest["candidates"][0]["rebuild_source"] = ""

            preflight = build_cleanup_preflight(manifest, root=data_root)

        self.assertEqual(preflight["status"], "BLOCK")
        checks = preflight["candidates"][0]["checks"]
        self.assertIn("rebuild_source", {row["check"] for row in checks if row["status"] == "BLOCK"})

    def test_shared_forecast_cas_cleanup_remains_disabled_after_operator_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            digest = "a" * 64
            shared_blob = write(
                data_root
                / "forecast_payload_cas"
                / "sha256"
                / digest[:2]
                / f"{digest}.blob",
                "shared bytes",
            )
            manifest = cleanup_manifest_for_paths(
                [shared_blob],
                root=data_root,
                deletion_reason="purported reviewed shared CAS cleanup",
                operator_review=review(),
            )
            # A manifest cannot evade the artifact-specific gate by claiming
            # that the resolved CAS file belongs to another canonical family.
            manifest["candidates"][0]["data_path"] = (
                "snapshots/event/snapshots.jsonl"
            )
            manifest["candidates"][0]["artifact_family"] = "snapshot_jsonl_evidence"

            preflight = build_cleanup_preflight(manifest, root=data_root)

        self.assertEqual(preflight["status"], "BLOCK")
        self.assertFalse(preflight["delete_permission"])
        candidate = preflight["candidates"][0]
        self.assertEqual(candidate["artifact_family"], "shared_forecast_payload_cas")
        self.assertIn(
            "shared_forecast_payload_gc_disabled",
            {
                row["check"]
                for row in candidate["checks"]
                if row["status"] == "BLOCK"
            },
        )
        self.assertIn(
            "data_path",
            {
                row["check"]
                for row in candidate["checks"]
                if row["status"] == "BLOCK"
            },
        )
        self.assertIn(
            "artifact_family",
            {
                row["check"]
                for row in candidate["checks"]
                if row["status"] == "BLOCK"
            },
        )

    def test_shared_cas_gate_cannot_be_erased_by_inner_cleanup_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            digest = "b" * 64
            shared_blob = write(
                data_root
                / "forecast_payload_cas"
                / "sha256"
                / digest[:2]
                / f"{digest}.blob",
                "shared bytes",
            )
            inner_root = shared_blob.parent
            manifest = cleanup_manifest_for_paths(
                [shared_blob],
                root=inner_root,
                deletion_reason="attempted inner-root CAS cleanup",
                operator_review=review(),
            )
            candidate = manifest["candidates"][0]
            candidate["data_path"] = "snapshots/event/snapshots.jsonl"
            candidate["storage_class"] = "canonical_evidence"
            candidate["artifact_family"] = "snapshot_jsonl_evidence"

            preflight = build_cleanup_preflight(manifest, root=inner_root)

        self.assertEqual(preflight["status"], "BLOCK")
        self.assertFalse(preflight["delete_permission"])
        candidate = preflight["candidates"][0]
        self.assertEqual(candidate["artifact_family"], "shared_forecast_payload_cas")
        self.assertIn(
            "shared_forecast_payload_gc_disabled",
            {
                row["check"]
                for row in candidate["checks"]
                if row["status"] == "BLOCK"
            },
        )


    def test_storage_5f_5g_candidates_classify_as_rebuildable_projections(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            run = data_root / "mm_runs/2026-09-01/run-1"
            write(run / "quote_intents_long.csv", "a\n1\n")
            write(run / "model_variant_quote_intents_long.csv", "a\n1\n")
            manifest_file = write(run / "mm_scoring_projection_manifest.json", "{}\n")
            paths = [
                write(run / "mm_scoring_projection.csv", "a\n1\n"),
                write(run / "model_variant_mm_scoring_projection.csv", "a\n1\n"),
                write(data_root / "backtest/active_variant_shadow_attribution.jsonl", "{}\n"),
            ]
            manifest = cleanup_manifest_for_paths(
                paths,
                root=data_root,
                deletion_reason="storage 5f/5g disk relief",
                operator_review=review(),
            )

            preflight = build_cleanup_preflight(manifest, root=data_root)
            retained = cleanup_manifest_for_paths(
                [manifest_file],
                root=data_root,
                deletion_reason="unit test",
                operator_review=review(),
            )["candidates"][0]

        self.assertEqual(preflight["status"], "PASS")
        self.assertEqual(
            [(row["storage_class"], row["artifact_family"]) for row in preflight["candidates"]],
            [
                ("analysis_projection", "mm_scoring_projection"),
                ("analysis_projection", "mm_scoring_projection"),
                ("analysis_projection", "backtest_row_exports"),
            ],
        )
        self.assertIn("quote_intents_long.csv", manifest["candidates"][0]["rebuild_source"])
        self.assertEqual(retained["storage_class"], "canonical_evidence")
        self.assertEqual(retained["artifact_family"], "mm_scoring_projection_manifest")


if __name__ == "__main__":
    unittest.main()
