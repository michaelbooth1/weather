"""The Windows qualification shards run every listed test exactly once.

Shards are rebalanced by time, so file lists move between them. These checks
prove by real pytest collection that no move can drop or duplicate a test: each
file is in exactly one shard, except test_status_script.py, whose two
``status_select`` expressions must partition its collected tests exactly and
must never filter another file in the same shard.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "windows-qualification.yml"
STATUS_FILE = "tests/operations/test_status_script.py"


def _shards() -> list[dict]:
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    shards: list[dict] = []
    in_files = False
    for line in lines:
        shard = re.match(r"^\s+- shard: (\S+)\s*$", line)
        if shard:
            shards.append({"name": shard.group(1), "status_select": None, "files": []})
            in_files = False
            continue
        if not shards:
            continue
        select = re.match(r"^\s+status_select: (.*)$", line)
        if select:
            value = select.group(1).strip()
            shards[-1]["status_select"] = "" if value == "''" else value
            in_files = False
            continue
        if re.match(r"^\s+files: >-\s*$", line):
            in_files = True
            continue
        if in_files:
            path = re.match(r"^\s+(tests/\S+\.py)\s*$", line)
            if path:
                shards[-1]["files"].append(path.group(1))
                continue
            in_files = False
            if re.match(r"^\s{4}\S", line):
                break
    return shards


def _job_select(status_select: str) -> str:
    # Mirrors the job env: format('({0}) or not test_status_script.py', ...).
    return f"({status_select}) or not test_status_script.py" if status_select else ""


def _collect(files: list[str], select: str) -> set[str]:
    command = [sys.executable, "-m", "pytest", "--collect-only", "-q",
               "-p", "no:cacheprovider", *files]
    if select:
        command += ["-k", select]
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    result = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True,
                            text=True, timeout=300, check=False)
    assert result.returncode in (0, 5), result.stdout[-2000:] + result.stderr[-2000:]
    return {line.strip() for line in result.stdout.splitlines() if "::" in line}


def test_workflow_matrix_lists_each_file_in_exactly_one_shard():
    shards = _shards()
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert len(shards) == 4
    assert len({shard["name"] for shard in shards}) == 4
    assert (
        "SHARD_SELECT: ${{ matrix.status_select && "
        "format('({0}) or not test_status_script.py', matrix.status_select) || '' }}"
    ) in workflow
    assert "if ($env:SHARD_SELECT) { $pytestArgs += @('-k', $env:SHARD_SELECT) }" in workflow
    seen: dict[str, str] = {}
    status_shards = []
    for shard in shards:
        assert shard["status_select"] is not None, shard["name"]
        assert shard["files"], shard["name"]
        assert len(shard["files"]) == len(set(shard["files"])), shard["name"]
        for file in shard["files"]:
            assert (REPO_ROOT / file).is_file(), file
            if file == STATUS_FILE:
                continue
            assert file not in seen, f"{file} is in {seen.get(file)} and {shard['name']}"
            seen[file] = shard["name"]
        if shard["status_select"]:
            assert STATUS_FILE in shard["files"], shard["name"]
            status_shards.append(shard)
        else:
            assert STATUS_FILE not in shard["files"], shard["name"]
    assert len(status_shards) == 2


def test_status_select_expressions_partition_status_tests_and_spare_other_files():
    status_shards = [shard for shard in _shards() if shard["status_select"]]
    files = sorted({file for shard in status_shards for file in shard["files"]})
    baseline = _collect(files, "")
    status_ids = {node for node in baseline if node.startswith(STATUS_FILE + "::")}
    assert status_ids
    selected = []
    for shard in status_shards:
        chosen = _collect(shard["files"], _job_select(shard["status_select"]))
        for file in shard["files"]:
            if file != STATUS_FILE:
                expected = {node for node in baseline if node.startswith(file + "::")}
                assert expected and expected <= chosen, f"{shard['name']} filtered {file}"
        selected.append({node for node in chosen if node.startswith(STATUS_FILE + "::")})
    first, second = selected
    assert first and second
    assert not first & second
    assert first | second == status_ids

