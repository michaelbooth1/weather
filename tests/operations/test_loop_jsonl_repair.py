import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from weather.operations.loop_jsonl_repair import audit_paths, repair_paths
from weather.operations.supervisor import jsonl_integrity, writer_lock_path


class TestLoopJsonlRepair(unittest.TestCase):
    def test_jsonl_integrity_samples_and_classifies_malformed_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loop.jsonl"
            path.write_text(
                '{"ok": true}\n'
                '{"partial": true\n'
                'Traceback (most recent call last):\n',
                encoding="utf-8",
            )

            result = jsonl_integrity(path, max_examples=5)

        self.assertEqual(result["valid_json_lines"], 1)
        self.assertEqual(result["malformed_lines"], 2)
        self.assertEqual(result["classification_counts"]["partial_json"], 1)
        self.assertEqual(result["classification_counts"]["console_text"], 1)
        self.assertEqual(result["examples"][0]["line"], 2)

    def test_repair_quarantines_malformed_lines_and_preserves_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loop.jsonl"
            path.write_text(
                '{"ok": true}\n'
                'not-json\n'
                '{"ok": 2}\n',
                encoding="utf-8",
            )

            before = audit_paths([path])
            after = repair_paths([path], backup=True)
            repaired_lines = path.read_text(encoding="utf-8").splitlines()
            quarantine = Path(after["repair"]["repaired"][0]["quarantine_path"])
            quarantine_rows = [json.loads(line) for line in quarantine.read_text(encoding="utf-8").splitlines()]
            backup_exists = Path(after["repair"]["repaired"][0]["backup_path"]).exists()

        self.assertEqual(before["status"], "WARN")
        self.assertEqual(after["status"], "PASS")
        self.assertEqual(repaired_lines, ['{"ok": true}', '{"ok": 2}'])
        self.assertTrue(backup_exists)
        self.assertEqual(quarantine_rows[0]["classification"], "non_json_text")

    def test_repair_refuses_malformed_managed_log_with_active_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "loop_console.log"
            status_path = root / "loop_status.json"
            log_path.write_text('{"ok": true}\nnot-json\n', encoding="utf-8")
            writer_lock_path(status_path).write_text(json.dumps({"pid": 1234}), encoding="utf-8")
            spec = SimpleNamespace(
                name="test_loop",
                console_log_path=log_path,
                status_path=status_path,
            )

            with (
                patch("weather.operations.loop_jsonl_repair.managed_loop_specs", return_value=(spec,)),
                patch("weather.operations.loop_jsonl_repair.pid_is_python", return_value=True),
            ):
                after = repair_paths([log_path], backup=True)

            repaired = after["repair"]["repaired"][0]
            repaired_lines = log_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(after["status"], "BLOCK")
        self.assertTrue(repaired["skipped"])
        self.assertEqual(repaired["reason"], "active_writer_lock")
        self.assertIsNone(repaired["backup_path"])
        self.assertIsNone(repaired["quarantine_path"])
        self.assertEqual(repaired_lines, ['{"ok": true}', "not-json"])


if __name__ == "__main__":
    unittest.main()
