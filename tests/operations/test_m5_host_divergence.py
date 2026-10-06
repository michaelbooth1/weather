"""M5 pilot: tips the CI Windows lane plus the preflight cannot vouch for.

Guards: Swarm L M5 (owner 2026-10-05, PILOT_FIRST shadow dual run): a tip that adds or
changes a host-divergent test (identity, ACL, Task Scheduler; the 10-04 WORKGROUP\\micha
class), a Windows-only test in no CI shard, or a hash-pinned file is disqualified.
"""
from __future__ import annotations

import json
import os
import subprocess

import pytest

from weather.operations import m5_host_divergence as m5

pytestmark = pytest.mark.spawns

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@x", "GIT_CONFIG_NOSYSTEM": "1"}
WIN_ONLY = 'import sys\nimport pytest\npytestmark = pytest.mark.skipif(sys.platform != "win32", reason="w")\n'


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            env=dict(os.environ, **GIT_ENV))
    assert result.returncode == 0, result.stderr
    return result.stdout.decode().strip()


@pytest.fixture()
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "master")
    files = {
        "tests/test_plain.py": "def test_a():\n    assert True\n",
        "tests/test_task.py": "def test_t():\n    assert 'Get-ScheduledTask'\n",
        "tests/test_win_sharded.py": WIN_ONLY,
        "tests/test_win_loose.py": WIN_ONLY,
        ".github/workflows/windows-qualification.yml": "files: >-\n  tests/test_win_sharded.py\n",
        "src/pins.py": 'PIN = {"src/frozen.txt": "' + "b" * 64 + '"}\n',
        "src/frozen.txt": "x\n",
        "src/free.py": "X = 1\n",
    }
    for path, text in files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def tip(repo, edits):
    git(repo, "checkout", "-q", "-B", "work", "master")
    for path, text in edits.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "tip")
    return m5.classify_tip(repo, "master", "work")


def test_enumeration_lists_host_divergent_and_unsharded_windows_tests(repo):
    result = m5.enumerate_tests(repo, "master")
    assert result["host_divergent_api"] == ["tests/test_task.py"]
    assert result["windows_only_unsharded"] == ["tests/test_win_loose.py"]


def test_a_plain_tip_is_eligible(repo):
    verdict = tip(repo, {"src/free.py": "X = 2\n", "tests/test_plain.py": "def test_a():\n    assert 1\n"})
    assert verdict["eligible"] is True and verdict["disqualifiers"] == []
    assert verdict["grants"].startswith("NOTHING")


@pytest.mark.parametrize(("edits", "kind"), [
    ({"tests/test_task.py": "def test_t():\n    assert 'Register-ScheduledTask'\n"}, "host_divergent_api"),
    ({"tests/test_new_acl.py": "def test_n():\n    assert 'icacls'\n"}, "host_divergent_api"),
    ({"tests/test_win_loose.py": WIN_ONLY + "\n"}, "windows_only_unsharded"),
    ({"src/frozen.txt": "y\n"}, "hash_pinned"),
])
def test_disqualifiers(repo, edits, kind):
    verdict = tip(repo, edits)
    assert verdict["eligible"] is False
    assert [d["kind"] for d in verdict["disqualifiers"]] == [kind]


def test_a_script_bound_by_a_runtime_hash_check_disqualifies(repo):
    """register_health_watchdog.ps1 binds status.ps1 through a parameter, with no literal."""
    binder = ("param([string]$ExpectedStatusScriptSha256)\n"
              "$p = Join-Path $PSScriptRoot 'status.ps1'\n"
              "if ((Get-FileHash -LiteralPath $p).Hash -ne $ExpectedStatusScriptSha256) { throw 'x' }\n")
    tip(repo, {"scripts/ops/register.ps1": binder, "scripts/ops/status.ps1": "'v1'\n",
               "scripts/ops/free.ps1": "'v1'\n"})
    git(repo, "checkout", "-q", "-B", "master", "work")
    verdict = tip(repo, {"scripts/ops/status.ps1": "'v2'\n", "scripts/ops/free.ps1": "'v2'\n"})
    assert verdict["disqualifiers"] == [{"path": "scripts/ops/status.ps1", "kind": "hash_bound_script"}]


def test_sharded_windows_test_does_not_disqualify(repo):
    assert tip(repo, {"tests/test_win_sharded.py": WIN_ONLY + "\n"})["eligible"] is True


def test_cli(repo, tmp_path, capsys):
    tip(repo, {"src/free.py": "X = 3\n"})
    assert m5.main(["--repo-root", str(repo), "--base", "master", "--head", "work"]) == 0
    tip(repo, {"src/frozen.txt": "z\n"})
    out = tmp_path / "m5.json"
    assert m5.main(["--repo-root", str(repo), "--base", "master", "--head", "work", "--json", str(out)]) == 1
    assert json.loads(out.read_text())["disqualifiers"][0]["kind"] == "hash_pinned"
    assert m5.main(["--repo-root", str(repo), "--enumerate", "master"]) == 0
    assert m5.main(["--repo-root", str(repo), "--enumerate", "nope"]) == 2
    capsys.readouterr()
