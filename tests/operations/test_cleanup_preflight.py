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


if __name__ == "__main__":
    unittest.main()
