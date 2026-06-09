import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from historical_backfill_runner import item_key, run_plan, status_summary


def write_plan(path, items):
    payload = {
        "schema_version": "historical_backfill_plan_v1",
        "scope": "test",
        "start_date": "2026-06-01",
        "end_date": "2026-06-01",
        "sources": sorted({item["source"] for item in items}),
        "market_count": len({item["market_id"] for item in items}),
        "queue_count": len(items),
        "queue": items,
    }
    Path(path).write_text(json.dumps(payload), encoding="utf-8")


def queue_item(source, market_id, command):
    return {
        "source": source,
        "market_id": market_id,
        "station": "TEST",
        "unit": "F",
        "detail": {"kind": "smoke"},
        "command": command,
    }


class TestHistoricalBackfillRunner(unittest.TestCase):
    def test_successful_items_are_recorded_and_skipped_on_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "plan.json"
            state = root / "runs.jsonl"
            summary = root / "summary.json"
            item = queue_item("ghcnh", "nyc", [sys.executable, "-c", "print('ok')"])
            write_plan(plan, [item])

            first = run_plan(plan, state, summary, max_items=1)
            second = run_plan(plan, state, summary, max_items=1)
            status = status_summary(plan, state)

            self.assertEqual(first["success_count"], 1)
            self.assertEqual(second["selected_count"], 0)
            self.assertEqual(second["skipped_succeeded_count"], 1)
            self.assertEqual(status["success_count"], 1)
            self.assertEqual(status["remaining_count"], 0)
            self.assertEqual(len(state.read_text(encoding="utf-8").strip().splitlines()), 1)

    def test_failed_items_remain_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "plan.json"
            state = root / "runs.jsonl"
            item = queue_item("wu", "nyc", [sys.executable, "-c", "import sys; print('bad'); sys.exit(3)"])
            write_plan(plan, [item])

            result = run_plan(plan, state, root / "summary.json", max_items=1, fail_fast=True)
            status = status_summary(plan, state)

            self.assertEqual(result["failed_count"], 1)
            self.assertEqual(status["failed_count"], 1)
            self.assertEqual(status["remaining_count"], 1)

    def test_dry_run_filters_without_writing_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "plan.json"
            state = root / "runs.jsonl"
            wu_item = queue_item("wu", "nyc", [sys.executable, "-c", "print('wu')"])
            ghcnh_item = queue_item("ghcnh", "toronto", [sys.executable, "-c", "print('ghcnh')"])
            write_plan(plan, [wu_item, ghcnh_item])

            result = run_plan(
                plan,
                state,
                root / "summary.json",
                max_items=1,
                dry_run=True,
                sources=["wu"],
                markets=["nyc"],
            )

            self.assertEqual(result["selected_count"], 1)
            self.assertEqual(result["rows"][0]["item_key"], item_key(wu_item))
            self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main()
