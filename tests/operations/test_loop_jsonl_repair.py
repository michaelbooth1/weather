import json
import tempfile
import unittest
from pathlib import Path

from weather.operations.loop_jsonl_repair import audit_paths, repair_paths
from weather.operations.supervisor import jsonl_integrity


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


if __name__ == "__main__":
    unittest.main()
