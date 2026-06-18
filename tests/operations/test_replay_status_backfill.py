import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.operations.replay_status_backfill import build_backfill_payload, write_outputs


SLUG = "highest-temperature-in-nyc-on-june-16-2026"


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _write_source_status(path):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["snapshot_id", "source", "ok", "stale", "status"])
        writer.writeheader()
        writer.writerow({
            "snapshot_id": "snap-1",
            "source": "wu_current",
            "ok": "True",
            "stale": "False",
            "status": "fresh",
        })


class TestReplayStatusBackfill(unittest.TestCase):
    def test_backfill_writes_canonical_status_for_settled_folder_with_replay_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshots"
            folder = root / SLUG
            folder.mkdir(parents=True)
            snapshot = {
                "snapshot_id": "snap-1",
                "captured_at_utc": "2026-06-16T18:00:00+00:00",
                "captured_at_local": "2026-06-16T14:00:00-04:00",
                "event_slug": SLUG,
            }
            _write_jsonl(folder / "snapshots.jsonl", [snapshot])
            _write_jsonl(folder / "replay_inputs.jsonl", [{
                **snapshot,
                "schema_version": "toronto_replay_inputs_v0.1",
                "sources": {"wu_current": {"ok": True, "stale": False, "data": {}}},
            }])
            _write_source_status(folder / "source_status_long.csv")

            payload = build_backfill_payload(snapshots_root=root, as_of="2026-06-17")
            json_out, report_out = write_outputs(
                payload,
                json_out=Path(tmp) / "backtest" / "replay_status_backfill.json",
                report_out=Path(tmp) / "backtest" / "replay_status_backfill.md",
            )
            rows = list(csv.DictReader((folder / "replay_input_status_long.csv").open(encoding="utf-8", newline="")))
            json_exists = json_out.exists()
            report_exists = report_out.exists()

        self.assertTrue(json_exists)
        self.assertTrue(report_exists)
        self.assertEqual(payload["summary"]["written_folder_count"], 1)
        self.assertEqual(payload["summary"]["training_ready_folder_count"], 1)
        self.assertEqual(payload["folders"][0]["folder_status"], "captured")
        self.assertTrue(payload["folders"][0]["training_ready"])
        self.assertEqual(rows[0]["replay_input_status"], "captured")
        self.assertEqual(rows[0]["replay_input_source"], "replay_inputs.jsonl")

    def test_backfill_marks_snapshot_only_folder_evaluation_only_not_training_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshots"
            folder = root / SLUG
            folder.mkdir(parents=True)
            _write_jsonl(folder / "snapshots.jsonl", [{
                "snapshot_id": "snap-1",
                "captured_at_utc": "2026-06-16T18:00:00+00:00",
                "captured_at_local": "2026-06-16T14:00:00-04:00",
                "event_slug": SLUG,
            }])

            payload = build_backfill_payload(snapshots_root=root, as_of="2026-06-17")

        self.assertEqual(payload["summary"]["written_folder_count"], 1)
        self.assertEqual(payload["summary"]["evaluation_only_folder_count"], 1)
        self.assertEqual(payload["summary"]["training_ready_folder_count"], 0)
        self.assertEqual(payload["folders"][0]["folder_status"], "evaluation_only")
        self.assertFalse(payload["folders"][0]["training_ready"])


if __name__ == "__main__":
    unittest.main()
