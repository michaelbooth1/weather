"""M13 pilot: the byte-exact EOF-newline-only class.

Guards: Swarm L M13 (owner 2026-10-05, PILOT_FIRST with the narrower predicate). No diff
flag set grants the class: re-indentation, whitespace inside Python triple-quoted strings
and PowerShell here-strings, YAML, scripts/ops and hash-pinned paths must all fall outside it.
"""
from __future__ import annotations

import json
import os
import subprocess

import pytest

from weather.operations import eof_newline_class as cls

pytestmark = pytest.mark.spawns

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@x", "GIT_CONFIG_NOSYSTEM": "1"}


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            env=dict(os.environ, **GIT_ENV))
    assert result.returncode == 0, result.stderr
    return result.stdout.decode().strip()


BASE_FILES = {
    "src/mod.py": b'def f():\n    return 1\nDOC = """a  \nb"""\n',
    "docs/a.md": b"# A\n\ntext",
    "docs/b.md": b"# B\n\n\n\n",
    "app/x.yml": b"a: 1",
    "scripts/ops/run.ps1": b"Write-Host hi",
    "src/pinned.txt": b"pinned",
    "src/pins.py": b'PIN = {"src/pinned.txt": "' + b"a" * 64 + b'"}\n',
    "tools/here.ps1": b"$x = @'\nline  \n'@\n",
}


@pytest.fixture()
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "master")
    for path, content in BASE_FILES.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def change(repo, edits, *, delete=(), add=None):
    git(repo, "checkout", "-q", "-B", "work", "master")
    for path, content in edits.items():
        (repo / path).write_bytes(content)
    for path in delete:
        (repo / path).unlink()
    for path, content in (add or {}).items():
        (repo / path).write_bytes(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "change")
    return cls.classify(repo, "master", "work")


def reasons(verdict):
    return {item["path"]: item["reason"] for item in verdict["files"]}


def test_byte_predicate():
    assert cls.eof_newline_only(b"a", b"a\n")
    assert cls.eof_newline_only(b"a\n\n\n", b"a\n")
    assert not cls.eof_newline_only(b"a\n", b"a\n")  # no change
    assert not cls.eof_newline_only(b"a  \n", b"a\n")  # trailing spaces are content
    assert not cls.eof_newline_only(b"a\n", b"a")  # removing the final newline


def test_adding_or_trimming_final_newlines_is_in_class(repo):
    verdict = change(repo, {"docs/a.md": b"# A\n\ntext\n", "docs/b.md": b"# B\n"})
    assert verdict["in_class"] is True, verdict
    assert all(item["in_class"] for item in verdict["files"])
    assert verdict["grants"].startswith("NOTHING")


@pytest.mark.parametrize(("edits", "path", "needle"), [
    # Re-indentation: hidden by `git diff -w`.
    ({"src/mod.py": b'def f():\n        return 1\nDOC = """a  \nb"""\n'}, "src/mod.py", "byte-exact"),
    # Whitespace inside a triple-quoted string: hidden by --ignore-space-at-eol.
    ({"src/mod.py": b'def f():\n    return 1\nDOC = """a\nb"""\n'}, "src/mod.py", "byte-exact"),
    # Whitespace inside a PowerShell here-string.
    ({"tools/here.ps1": b"$x = @'\nline\n'@\n"}, "tools/here.ps1", "byte-exact"),
    # Excluded paths even when the byte predicate holds.
    ({"app/x.yml": b"a: 1\n"}, "app/x.yml", "YAML"),
    ({"scripts/ops/run.ps1": b"Write-Host hi\n"}, "scripts/ops/run.ps1", "scripts/ops"),
    ({"src/pinned.txt": b"pinned\n"}, "src/pinned.txt", "pinned SHA-256"),
])
def test_mutants_fall_outside_the_class(repo, edits, path, needle):
    verdict = change(repo, {**edits, "docs/a.md": b"# A\n\ntext\n"})
    assert verdict["in_class"] is False
    assert needle in reasons(verdict)[path]
    assert reasons(verdict)["docs/a.md"] is None


def test_adds_deletes_and_empty_diffs_are_outside_the_class(repo):
    assert change(repo, {}, delete=["docs/a.md"])["in_class"] is False
    added = change(repo, {}, add={"docs/new.md": b"new\n"})
    assert added["in_class"] is False and "status A" in reasons(added)["docs/new.md"]
    empty = cls.classify(repo, "master", "master")
    assert empty["in_class"] is False and empty["reason"] == "no changed files"


def test_cli_exit_codes_and_json(repo, tmp_path, capsys):
    change(repo, {"docs/a.md": b"# A\n\ntext\n"})
    out = tmp_path / "verdict.json"
    assert cls.main(["--repo-root", str(repo), "--base", "master", "--head", "work", "--json", str(out)]) == 0
    assert json.loads(out.read_text())["schema"] == cls.SCHEMA
    change(repo, {"src/mod.py": b'def f():\n    return 2\nDOC = """a  \nb"""\n'})
    assert cls.main(["--repo-root", str(repo), "--base", "master", "--head", "work"]) == 1
    assert cls.main(["--repo-root", str(repo), "--base", "master", "--head", "no-such-ref"]) == 2
    capsys.readouterr()
