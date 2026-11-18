import tempfile
import unittest
from pathlib import Path

from weather.runtime_identity import (
    _git_head_identity,
    current_identity_for,
    get_runtime_identity,
    identities_match,
    source_tree_fingerprint,
)


class TestRuntimeIdentity(unittest.TestCase):
    def test_linked_worktree_reads_its_named_head_from_the_common_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / "main" / ".git"
            admin = main / "worktrees" / "topic"
            admin.mkdir(parents=True)
            work = root / "topic"
            work.mkdir()
            (work / ".git").write_text("gitdir: ../main/.git/worktrees/topic\n", encoding="utf-8")
            (admin / "HEAD").write_text("ref: refs/heads/team/topic\n", encoding="utf-8")
            (main / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            (admin / "commondir").write_text("../..\n", encoding="utf-8")
            (main / "packed-refs").write_text(
                "# pack-refs with: peeled\n" + "1" * 40 + " refs/heads/team/topic-other\n"
                + "2" * 40 + " refs/heads/team/topic\n^" + "3" * 40 + "\n", encoding="utf-8",
            )
            self.assertEqual(_git_head_identity(work), ("team/topic", "2" * 12))
            ref = main / "refs" / "heads" / "team" / "topic"
            ref.parent.mkdir(parents=True)
            ref.write_text("4" * 64 + "\n", encoding="utf-8")
            (admin / "commondir").write_text(str(main) + "\n", encoding="utf-8")
            identity = get_runtime_identity(work, scope_files=["missing.py"])
            self.assertEqual((identity["git_branch"], identity["git_commit"]), ("team/topic", "4" * 12))
            self.assertIsNone(identity["git_dirty"])
            self.assertIsNone(identity["dirty_fingerprint"])
            ref.write_text("bad ref contents\n", encoding="utf-8")
            self.assertEqual(_git_head_identity(work), ("team/topic", "unknown"))

    def test_detached_and_invalid_heads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git = root / ".git"
            git.mkdir()
            head = git / "HEAD"
            self.assertEqual(_git_head_identity(root), ("unknown", "unknown"))
            head.write_text("a" * 40 + "\n", encoding="utf-8")
            self.assertEqual(_git_head_identity(root), ("detached", "a" * 12))
            head.write_text("invalid-object-id\n", encoding="utf-8")
            self.assertEqual(_git_head_identity(root), ("unknown", "unknown"))
            head.write_text("ref: refs/heads/missing\n", encoding="utf-8")
            (git / "commondir").write_text("missing-dir\n", encoding="utf-8")
            self.assertEqual(_git_head_identity(root), ("missing", "unknown"))

    def test_worktree_private_ref_stays_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            admin = root / "admin"
            repo = root / "checkout"
            repo.mkdir()
            (repo / ".git").write_text("gitdir: ../admin\n", encoding="utf-8")
            ref = "refs/worktree/private"
            for base, oid in ((admin, "a" * 40), (root / "shared", "b" * 40)):
                target = base / ref
                target.parent.mkdir(parents=True)
                target.write_text(oid + "\n", encoding="utf-8")
            (admin / "commondir").write_text("../shared\n", encoding="utf-8")
            (admin / "HEAD").write_text("ref: " + ref + "\n", encoding="utf-8")
            self.assertEqual(_git_head_identity(repo), (ref, "a" * 12))

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
