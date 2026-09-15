"""Actual isolated Git history and working bytes, without production data."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from weather.operations.qualification import source
from weather.operations.qualification.records import QualificationError


@pytest.fixture
def checkout(tmp_path):
    git = Path(shutil.which("git"))
    repo = tmp_path / "checkout"
    repo.mkdir()
    def run(*args):
        result = subprocess.run([str(git), "-C", str(repo), *args], env=source.git_environment(),
                                capture_output=True, timeout=15, check=False)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        return result.stdout.decode("utf-8").strip()
    run("init", "-q")
    run("config", "user.name", "Qualification fixture")
    run("config", "user.email", "qualification@example.invalid")
    run("config", "core.autocrlf", "false")
    (repo / ".gitignore").write_text("__pycache__/\ndata/\n", encoding="utf-8")
    (repo / "example.py").write_text("value = 1\n", encoding="utf-8")
    run("add", "--", ".gitignore", "example.py")
    run("-c", "core.hooksPath=" + os.devnull, "commit", "--no-gpg-sign", "-qm", "baseline")
    baseline = run("rev-parse", "HEAD")
    (repo / "example.py").write_text("value = 2\n", encoding="utf-8")
    run("add", "--", "example.py")
    run("-c", "core.hooksPath=" + os.devnull, "commit", "--no-gpg-sign", "-qm", "candidate")
    return git, repo, baseline, run("rev-parse", "HEAD")


def test_source_and_baseline_have_complete_byte_inventories(checkout):
    git, repo, baseline, candidate = checkout
    identity = source.identity(git, repo, source=candidate, baseline=baseline)
    assert identity["commit"] == candidate and identity["baseline"] == baseline
    before = source.inventory(git, repo, baseline)
    after = source.inventory(git, repo, candidate, verify_working=True)
    assert [item["path"] for item in after["files"]] == [".gitignore", "example.py"]
    assert before["files"][1]["sha256"] != after["files"][1]["sha256"]
    assert source.clean_checkout(git, repo)


def test_wrong_head_and_working_byte_substitution_are_rejected(checkout):
    git, repo, baseline, candidate = checkout
    with pytest.raises(QualificationError, match="reviewed candidate"):
        source.identity(git, repo, source=baseline, baseline=candidate)
    (repo / "example.py").write_text("value = 3\n", encoding="utf-8")
    with pytest.raises(QualificationError, match="working bytes"):
        source.inventory(git, repo, candidate, verify_working=True)
    with pytest.raises(QualificationError, match="dirty"):
        source.clean_checkout(git, repo)


@pytest.mark.parametrize("directory", ["data", "__pycache__"])
def test_ignored_runtime_state_and_bytecode_cannot_enter_checkout(checkout, directory):
    git, repo, _, _ = checkout
    (repo / directory).mkdir()
    with pytest.raises(QualificationError):
        source.clean_checkout(git, repo)


def test_source_commands_ignore_ambient_git_config_and_replace_objects(checkout, monkeypatch):
    git, repo, baseline, candidate = checkout
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.fsmonitor")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "unreviewed-command")
    monkeypatch.setenv("GH_TOKEN", "fixture-token-never-forwarded")
    env = source.git_environment()
    assert "GIT_CONFIG_COUNT" not in env and "GH_TOKEN" not in env
    assert source.identity(git, repo, source=candidate, baseline=baseline)["commit"] == candidate
    assert "--no-replace-objects" in source.git_argv(git, repo, "status")
