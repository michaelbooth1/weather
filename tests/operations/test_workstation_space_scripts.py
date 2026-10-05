"""Executes workstation_space_report.ps1 and workstation_space_clean.ps1 on fixture worktrees and folders.

Every path lives under tmp_path; nothing outside the fixture is listed for removal or touched.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT = REPO_ROOT / "scripts" / "ops" / "workstation_space_report.ps1"
CLEAN = REPO_ROOT / "scripts" / "ops" / "workstation_space_clean.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or POWERSHELL is None or shutil.which("git") is None,
    reason="Windows PowerShell 5.1 and git are required",
)

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@x", "GIT_CONFIG_NOSYSTEM": "1"}
OLD = time.time() - 3 * 86400


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                            env=dict(os.environ, **GIT_ENV))
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr.strip()}"
    return result.stdout.strip()


def _backdate(root: Path) -> None:
    """Make a tree look idle for three days without following any reparse point."""
    for dirpath, dirnames, filenames in os.walk(root, topdown=False, followlinks=False):
        for name in filenames + dirnames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path) or _is_junction(path):
                continue
            os.utime(path, (OLD, OLD))
        os.utime(dirpath, (OLD, OLD))


def _is_junction(path: str) -> bool:
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None:
        return bool(isjunction(path))
    try:
        return bool(os.lstat(path).st_file_attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return False


def _junction(link: Path, target: Path) -> None:
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def _ps_list(values: list[str]) -> str:
    return ",".join("'" + v.replace("'", "''") + "'" for v in values)


def _report(fx: dict, json_path: Path) -> dict:
    command = (f"& '{REPORT}' -RepoRoot '{fx['repo']}' -ScratchRoots {_ps_list([str(r) for r in fx['roots']])} "
               f"-UnreadableProcessPolicy ignore -JsonPath '{json_path}'")
    result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-Command", command], capture_output=True, text=True, timeout=300,
                            env=dict(os.environ, **GIT_ENV))
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(json_path.read_text(encoding="utf-8"))


def _clean(report_path: Path, receipt: Path, apply: bool) -> subprocess.CompletedProcess[str]:
    args = [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(CLEAN),
            "-FromReport", str(report_path), "-ReceiptPath", str(receipt)]
    if apply:
        args.append("-Apply")
    return subprocess.run(args, capture_output=True, text=True, timeout=300, env=dict(os.environ, **GIT_ENV))


def _by_path(report: dict) -> dict[str, dict]:
    return {Path(item["path"]).name: item for item in report["items"]}


def _sleeper(cwd: Path) -> subprocess.Popen:
    proc = subprocess.Popen([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", "Start-Sleep -Seconds 120"],
                            cwd=str(cwd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    return proc


@pytest.fixture()
def fx(tmp_path: Path) -> dict:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    (repo / ".gitignore").write_text("data/\n__pycache__/\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/master", base)

    wt, pt = tmp_path / "roots" / "wt", tmp_path / "roots" / "pt"
    wt.mkdir(parents=True)
    pt.mkdir(parents=True)
    _git(repo, "worktree", "add", "-q", "-b", "pushed", str(wt / "pushed"), "master")
    (wt / "pushed" / "__pycache__").mkdir()
    (wt / "pushed" / "__pycache__" / "x.pyc").write_bytes(b"cache")
    _git(repo, "worktree", "add", "-q", "-b", "unpushed", str(wt / "unpushed"), "master")
    (wt / "unpushed" / "b.txt").write_text("local only\n", encoding="utf-8")
    _git(wt / "unpushed", "add", "-A")
    _git(wt / "unpushed", "commit", "-q", "-m", "local")
    _git(repo, "worktree", "add", "-q", "-b", "locked", str(wt / "locked"), "master")
    _git(repo, "worktree", "lock", "--reason", "pinned deployment", str(wt / "locked"))
    _git(repo, "worktree", "add", "-q", "-b", "evidence", str(wt / "evidence"), "master")
    (wt / "evidence" / "data").mkdir()
    (wt / "evidence" / "data" / "tape.jsonl").write_text("{}\n", encoding="utf-8")

    for name in ("old", "old_recent_later", "old_busy_later", "nonrecursive", "busy"):
        (pt / name / "sub").mkdir(parents=True)
        (pt / name / "sub" / "f.txt").write_text("x" * 100, encoding="utf-8")
    (pt / "empty").mkdir()
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("must survive\n", encoding="utf-8")
    (pt / "withjunction").mkdir()
    (pt / "withjunction" / "f.txt").write_text("x", encoding="utf-8")
    _junction(pt / "withjunction" / "link", target)
    _junction(pt / "junction", target)

    _backdate(tmp_path / "roots")
    _backdate(repo / ".git" / "worktrees")
    (pt / "fresh").mkdir()
    (pt / "fresh" / "new.txt").write_text("just written\n", encoding="utf-8")
    return {"repo": repo, "roots": [wt, pt], "wt": wt, "pt": pt, "target": target, "tmp": tmp_path, "base": base}


def test_report_assigns_verdicts_and_changes_nothing(fx: dict) -> None:
    busy = _sleeper(fx["pt"] / "busy")
    try:
        report = _report(fx, fx["tmp"] / "report.json")
    finally:
        busy.kill()
        busy.wait()
    items = _by_path(report)
    verdict = {name: item["verdict"] for name, item in items.items()}

    assert report["schema"] == "workstation_space_report_v1"
    assert verdict["pushed"] == "SAFE" and items["pushed"]["pushed"] is True
    assert verdict["unpushed"] == "CHECK" and items["unpushed"]["pushed"] is False
    assert any("unpushed" in r for r in items["unpushed"]["reasons"])
    assert verdict["locked"] == "IN USE" and any("pinned deployment" in r for r in items["locked"]["reasons"])
    assert verdict["evidence"] == "CHECK" and items["evidence"]["ignored_not_cache"] == ["data/"]
    assert items["repo"]["kind"] == "main-worktree" and verdict["repo"] != "SAFE"
    assert verdict["old"] == "SAFE" and items["old"]["recursive"] is False
    assert items["old"]["size_complete"] is True and items["old"]["size_bytes"] == 100
    assert verdict["empty"] == "SAFE"
    assert verdict["fresh"] == "IN USE" and any("h ago" in r for r in items["fresh"]["reasons"])
    assert verdict["busy"] == "IN USE"
    assert [p["via"] for p in items["busy"]["processes"]] == ["cwd"]
    # The junction itself was just created, so it may also read as recent activity.
    assert verdict["withjunction"] != "SAFE" and any("reparse point inside" in r for r in items["withjunction"]["reasons"])
    assert items["junction"]["kind"] == "reparse" and verdict["junction"] != "SAFE"
    assert any("is a reparse point" in r for r in items["junction"]["reasons"])
    assert (fx["target"] / "keep.txt").exists()
    assert all(item["handles"] == "not-checked" for item in report["items"])


def test_clean_without_apply_lists_only(fx: dict) -> None:
    report_path = fx["tmp"] / "report.json"
    _report(fx, report_path)
    result = _clean(report_path, fx["tmp"] / "receipt.json", apply=False)

    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads((fx["tmp"] / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["mode"] == "list" and receipt["removed"] == []
    assert {Path(e["path"]).name for e in receipt["would_remove"]} == {"pushed", "empty"}
    refused = {Path(e["path"]).name: e["reason"] for e in receipt["refused"]}
    assert "not empty" in refused["old"]
    assert refused["unpushed"].startswith("report verdict CHECK")
    assert (fx["wt"] / "pushed").exists() and (fx["pt"] / "empty").exists()


def test_clean_apply_removes_only_still_safe_items(fx: dict) -> None:
    report_path = fx["tmp"] / "report.json"
    report = _report(fx, report_path)
    for item in report["items"]:
        name = Path(item["path"]).name
        if name in {"old", "old_recent_later", "old_busy_later", "withjunction"}:
            item["recursive"] = True
        if name in {"unpushed", "withjunction", "locked"}:
            item["verdict"] = "SAFE"  # a stale or hand-edited list must not bypass the fresh re-check
    report_path.write_text(json.dumps(report), encoding="utf-8")
    (fx["pt"] / "old_recent_later" / "sub" / "touched.txt").write_text("written after the report\n", encoding="utf-8")
    busy = _sleeper(fx["pt"] / "old_busy_later")
    try:
        result = _clean(report_path, fx["tmp"] / "receipt.json", apply=True)
    finally:
        busy.kill()
        busy.wait()

    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads((fx["tmp"] / "receipt.json").read_text(encoding="utf-8"))
    removed = {Path(e["path"]).name for e in receipt["removed"]}
    refused = {Path(e["path"]).name: e["reason"] for e in receipt["refused"]}
    assert receipt["mode"] == "apply" and receipt["failed"] == []
    assert removed == {"pushed", "old", "empty"}
    assert not (fx["wt"] / "pushed").exists() and not (fx["pt"] / "old").exists()
    assert _git(fx["repo"], "rev-parse", "pushed") == fx["base"]  # the branch is kept
    assert "unpushed" in refused["unpushed"] and (fx["wt"] / "unpushed" / "b.txt").exists()
    assert "IN USE" in refused["locked"] and (fx["wt"] / "locked").exists()
    assert "reparse point" in refused["withjunction"] and (fx["pt"] / "withjunction" / "f.txt").exists()
    assert "fresh re-check verdict IN USE" in refused["old_recent_later"]
    assert "process inside" in refused["old_busy_later"]
    assert (fx["pt"] / "old_recent_later").exists() and (fx["pt"] / "old_busy_later").exists()
    assert "not empty" in refused["nonrecursive"] and (fx["pt"] / "nonrecursive" / "sub" / "f.txt").exists()
    assert refused["junction"].startswith("report verdict") and "reparse point" in refused["junction"]
    assert (fx["target"] / "keep.txt").exists()


def test_clean_refuses_a_folder_outside_the_recorded_roots(fx: dict) -> None:
    report_path = fx["tmp"] / "report.json"
    report = _report(fx, report_path)
    outside = fx["tmp"] / "outside"
    outside.mkdir()
    _backdate(outside)
    report["items"].append({"kind": "folder", "path": str(outside), "verdict": "SAFE", "reasons": [], "recursive": True})
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result = _clean(report_path, fx["tmp"] / "receipt.json", apply=True)

    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads((fx["tmp"] / "receipt.json").read_text(encoding="utf-8"))
    refused = {Path(e["path"]).name: e["reason"] for e in receipt["refused"]}
    assert "no longer found" in refused["outside"] and outside.exists()


def test_clean_rejects_an_unusable_report(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema": "something_else"}', encoding="utf-8")
    result = _clean(bad, tmp_path / "receipt.json", apply=True)
    assert result.returncode == 2
    assert "unusable report" in json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))["error"]
