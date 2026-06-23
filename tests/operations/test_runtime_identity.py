import tempfile
import unittest
from pathlib import Path

from weather.runtime_identity import get_runtime_identity, source_tree_fingerprint


class TestRuntimeIdentity(unittest.TestCase):
    def test_runtime_identity_reads_head_without_git_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git_dir = root / ".git"
            ref = git_dir / "refs" / "heads" / "main"
            ref.parent.mkdir(parents=True)
            (root / "app.py").write_text("print('ok')\n", encoding="utf-8")
            (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            ref.write_text("1234567890abcdef1234567890abcdef12345678\n", encoding="utf-8")

            identity = get_runtime_identity(root)

        self.assertEqual(identity["git_branch"], "main")
        self.assertEqual(identity["git_commit"], "1234567890ab")
        self.assertIsNone(identity["git_dirty"])
        self.assertIsNone(identity["dirty_fingerprint"])
        self.assertEqual(identity["identity_source"], "git_filesystem")
        self.assertEqual(identity["source_file_count"], 1)

    def test_source_fingerprint_ignores_generated_tool_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("print('ok')\n", encoding="utf-8")
            tool = root / "tools" / "research" / "probe.py"
            tool.parent.mkdir(parents=True)
            tool.write_text("print('tool')\n", encoding="utf-8")

            before = source_tree_fingerprint(root)

            cache = tool.parent / "__pycache__" / "probe.cpython-311.pyc"
            cache.parent.mkdir(parents=True)
            cache.write_bytes(b"compiled bytecode")

            after = source_tree_fingerprint(root)

        self.assertEqual(after, before)
        self.assertEqual(after["file_count"], 2)


if __name__ == "__main__":
    unittest.main()
