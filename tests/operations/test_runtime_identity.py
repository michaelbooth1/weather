import tempfile
import unittest
from pathlib import Path

from weather.runtime_identity import (
    current_identity_for,
    get_runtime_identity,
    identities_match,
    source_tree_fingerprint,
)


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

    def test_scoped_identity_ignores_out_of_scope_changes(self):
        # A scoped (loaded-modules) identity only re-adopts when files the loop
        # imports change; a commit to an unrelated module must NOT flip it stale,
        # so collection cadence is not torn down by unrelated commits.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "in_scope.py").write_text("x = 1\n", encoding="utf-8")
            (root / "out_of_scope.py").write_text("y = 1\n", encoding="utf-8")

            ident = get_runtime_identity(root, scope_files=["in_scope.py"])
            self.assertEqual(ident["source_scope"], "loaded_modules")
            self.assertEqual(ident["source_scope_files"], ["in_scope.py"])

            # Change an out-of-scope file: still current.
            (root / "out_of_scope.py").write_text("y = 999\n", encoding="utf-8")
            self.assertTrue(identities_match(ident, current_identity_for(ident, root)))

            # Change the in-scope file: now stale.
            (root / "in_scope.py").write_text("x = 2\n", encoding="utf-8")
            self.assertFalse(identities_match(ident, current_identity_for(ident, root)))

    def test_legacy_whole_tree_identity_has_no_scope_and_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("print('ok')\n", encoding="utf-8")

            whole = get_runtime_identity(root)
            self.assertNotIn("source_scope", whole)
            self.assertNotIn("source_scope_files", whole)

            # current_identity_for a legacy identity recomputes the whole tree.
            current = current_identity_for(whole, root)
            self.assertNotIn("source_scope_files", current)
            self.assertTrue(identities_match(whole, current))

            # Whole-tree staleness behaviour is preserved: any source change is stale.
            (root / "app.py").write_text("print('changed')\n", encoding="utf-8")
            self.assertFalse(identities_match(whole, current_identity_for(whole, root)))

    def test_scoped_identity_detects_deleted_scope_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "in_scope.py").write_text("x = 1\n", encoding="utf-8")
            ident = get_runtime_identity(root, scope_files=["in_scope.py"])
            (root / "in_scope.py").unlink()
            self.assertFalse(identities_match(ident, current_identity_for(ident, root)))


if __name__ == "__main__":
    unittest.main()
