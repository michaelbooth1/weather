"""WU token scanner and real Windows directory junctions (Defender finding S1, 2026-10-07).

Guards: OD15 (owner decision 2026-10-06) leak scan completeness and OD27 (2026-10-07): a junction
inside a scanned root is never silently skipped as CLEAN, and is never followed out of the
requested root; docs/operations/HISTORY_DATA_DESIGN.md "Page Access Token".
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys

import pytest

from weather.operations import wu_token_scan
from weather.operations.wu_token_scan import EXIT_CLEAN, EXIT_ERROR, EXIT_FOUND, exit_code_for, main, scan

pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(sys.platform != "win32", reason="directory junctions are Windows-only"),
]


@pytest.fixture
def token():
    return "FAKEKEY" + secrets.token_hex(16)


def _junction(link, target):
    """Create ``link`` -> ``target`` with ``mklink /J`` (no admin needed for junctions)."""
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert os.path.isdir(link)


def _leak_tree(tmp_path, token):
    root = tmp_path / "root"
    (root / "plain").mkdir(parents=True)
    (root / "plain" / "clean.log").write_text("clean apiKey=<redacted>\n", encoding="utf-8")
    real = tmp_path / "real"
    real.mkdir()
    (real / "leak.log").write_text(f"GET /v1/x?apiKey={token}&units=e\n", encoding="utf-8")
    _junction(root / "linked", real)
    return root


def _run(capsys, argv):
    code = main([str(item) for item in argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_junction_out_of_root_is_incomplete_not_clean(tmp_path, token, capsys):
    root = _leak_tree(tmp_path, token)

    code, out, err = _run(capsys, [root])

    payload = json.loads(out)
    assert code == EXIT_ERROR
    assert payload["status"] == "INCOMPLETE"
    assert payload["links_incomplete"] is True
    assert payload["skipped_links"] == 1
    assert payload["skipped_link_paths"] == [str(root / "linked")]
    assert payload["findings"] == []
    assert token not in out and token not in err


def test_follow_within_root_never_leaves_the_requested_root(tmp_path, token):
    root = _leak_tree(tmp_path, token)

    result = scan([root], link_policy="follow-within-root")

    assert result.findings == []
    assert result.followed_links == 0
    assert result.skipped_link_paths == [str(root / "linked")]
    assert exit_code_for(result) == EXIT_ERROR


def test_ignore_flag_waives_the_skipped_junction_explicitly(tmp_path, token, capsys):
    root = _leak_tree(tmp_path, token)

    code, out, _err = _run(capsys, [root, "--links", "ignore"])

    payload = json.loads(out)
    assert code == EXIT_CLEAN
    assert payload["skipped_link_paths"] == [str(root / "linked")]
    assert payload["links_incomplete"] is False


def test_follow_within_root_reads_a_junction_inside_the_root(tmp_path, token, capsys):
    root = tmp_path / "root"
    hidden = root / "archive" / "2026-06"
    hidden.mkdir(parents=True)
    (hidden / "leak.log").write_text(f"apiKey={token}\n", encoding="utf-8")
    _junction(root / "current", hidden)

    code, out, err = _run(capsys, [root, "--links", "follow-within-root"])

    payload = json.loads(out)
    assert code == EXIT_FOUND
    assert token not in out and token not in err
    assert payload["skipped_links"] == 0
    # Each real directory is walked once, through whichever path reaches it first.
    assert payload["followed_links"] == 1
    assert payload["finding_file_count"] == 1


def test_follow_within_root_finds_a_tree_reachable_only_through_the_junction(tmp_path, token):
    root = tmp_path / "root"
    root.mkdir()
    # The target sits inside the root under an excluded name, so only the junction reaches it.
    hidden = root / "node_modules" / "kept"
    hidden.mkdir(parents=True)
    (hidden / "leak.log").write_text(f"apiKey={token}\n", encoding="utf-8")
    _junction(root / "via", hidden)

    default = scan([root])
    followed = scan([root], link_policy="follow-within-root")

    assert default.findings == [] and exit_code_for(default) == EXIT_ERROR
    assert [os.path.basename(row["path"]) for row in followed.findings] == ["leak.log"]
    assert followed.followed_links == 1


def test_junction_cycle_terminates(tmp_path):
    root = tmp_path / "root"
    (root / "a").mkdir(parents=True)
    (root / "a" / "f.log").write_text("clean\n", encoding="utf-8")
    _junction(root / "a" / "loop", root)

    followed = scan([root], link_policy="follow-within-root")
    default = scan([root])

    assert followed.files_scanned == 1 and exit_code_for(followed) == EXIT_CLEAN
    assert default.skipped_link_paths == [str(root / "a" / "loop")]
    assert exit_code_for(default) == EXIT_ERROR


def test_mutant_ignoring_skipped_links_reports_clean(tmp_path, token, monkeypatch):
    """The pre-fix exit rule (links ignored) would call the leaking tree CLEAN."""
    root = _leak_tree(tmp_path, token)
    monkeypatch.setattr(wu_token_scan, "links_incomplete", lambda result: False)

    assert exit_code_for(scan([root])) == EXIT_CLEAN
