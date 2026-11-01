"""Executes scripts/ops/frozen_binding_guard.ps1 (Test-FrozenBindingHead) against fake git repositories.

Guards: ruling R14 (master 2026-11-01) and its S1 ruling: B-1 Clarification 3 section 5 permits exactly two changed
lines in one head, the scorer's entry constant and the wrapper's pin, set to the same value, and nothing else; the
registry is judged as it is at the merge base and may only grow by pure additions; records are frozen for good,
code pins until the release record exists.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "scripts" / "ops" / "frozen_binding_guard.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")

pytestmark = [
    pytest.mark.skipif(sys.platform != "win32" or POWERSHELL is None or shutil.which("git") is None,
                       reason="Windows PowerShell 5.1 and git are required"),
    pytest.mark.spawns,
]

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@x", "GIT_CONFIG_NOSYSTEM": "1"}

DRIVER = """param([string]$Guard, [string]$Repo, [string]$Base, [string]$Tip)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. $Guard
$r = Test-FrozenBindingHead -Repo $Repo -Base $Base -Tip $Tip
[pscustomobject]@{ Ok = $r.Ok; Refusals = @($r.Refusals); Warnings = @($r.Warnings);
    SuiteChecked = @($r.SuiteChecked); ActiveHolds = @($r.ActiveHolds); RegistryPresent = $r.RegistryPresent } |
    ConvertTo-Json -Depth 4 -Compress
"""

S0_SCORER = "import x\nENTRY = UNRECORDED\nTAIL = 1\n"
S0_WRAPPER = "PIN_UNSET = 'unset'\nPIN = PIN_UNSET\nACCEPT = False\n"
SHA_A = "a" * 64
SHA_B = "b" * 64


def _registry(**extra: object) -> dict[str, object]:
    hold = {
        "id": "B-1",
        "records": {"docs/rule.md": "1" * 64},
        "record_globs": ["docs/**/b1-clarification-*.md"],
        "frozen_prefixes": ["docs/bound/"],
        "release_binding": "docs/bound/release-binding.json",
        "code": {"src/scorer.py": "2" * 64, "src/wrapper.py": "3" * 64, "src/pinned.py": "4" * 64},
        "s1_edit": {
            "src/scorer.py": {"s0_line": "ENTRY = UNRECORDED", "constant": "ENTRY"},
            "src/wrapper.py": {"s0_line": "PIN = PIN_UNSET", "constant": "PIN", "equals": "src/scorer.py"},
        },
        "warn": ["scripts/export.ps1"],
        "release_record": "docs/record/b-look-record.md",
    }
    hold.update(extra)
    return {"schema": "frozen_bindings/1", "holds": [hold]}


BASE_FILES = {
    "docs/rule.md": "# rule\n",
    "docs/bound/plan.md": "plan\n",
    "docs/bound/release-binding.json": json.dumps({"files": {"src/released.py": "5" * 64}}) + "\n",
    "docs/x/b1-clarification-1-a.md": "c1\n",
    "docs/other.md": "other\n",
    "src/scorer.py": S0_SCORER,
    "src/wrapper.py": S0_WRAPPER,
    "src/pinned.py": "pinned = 1\n",
    "src/released.py": "released = 1\n",
    "src/free.py": "free = 1\n",
    "scripts/export.ps1": "'export'\n",
    "config/frozen_bindings.json": json.dumps(_registry(), indent=1) + "\n",
}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                            env=dict(os.environ, **GIT_ENV))
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr.strip()}"
    return result.stdout.strip()


def _write(repo: Path, files: dict[str, str | None]) -> None:
    for rel, text in files.items():
        path = repo / rel
        if text is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))


def _commit(repo: Path, files: dict[str, str | None], message: str) -> str:
    _write(repo, files)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "master")
    _git(root, "config", "core.autocrlf", "false")
    _commit(root, dict(BASE_FILES), "base")
    (tmp_path / "driver.ps1").write_text(DRIVER, encoding="utf-8")
    return root


def _judge(repo: Path, tip_files: dict[str, str | None], base_files: dict[str, str | None] | None = None
           ) -> dict[str, object]:
    if base_files:
        _commit(repo, base_files, "base change")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "head")
    tip = _commit(repo, tip_files, "head")
    _git(repo, "checkout", "-q", "master")
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
         str(repo.parent / "driver.ps1"), "-Guard", str(GUARD), "-Repo", str(repo), "-Base", base, "-Tip", tip],
        capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    for key in ("Refusals", "Warnings", "SuiteChecked", "ActiveHolds"):
        out[key] = out[key] or []
    return out


def _s1(scorer: str = SHA_A, wrapper: str = SHA_A) -> dict[str, str | None]:
    return {"src/scorer.py": S0_SCORER.replace("ENTRY = UNRECORDED", f'ENTRY = "{scorer}"'),
            "src/wrapper.py": S0_WRAPPER.replace("PIN = PIN_UNSET", f'PIN = "{wrapper}"')}


def _only(out: dict[str, object], fragment: str) -> None:
    assert out["Ok"] is False, out
    assert any(fragment in r for r in out["Refusals"]), out  # type: ignore[union-attr]


def test_unrelated_change_passes(repo: Path):
    out = _judge(repo, {"src/free.py": "free = 2\n", "docs/other.md": "edited\n"})
    assert out["Ok"] is True and out["Refusals"] == [] and out["ActiveHolds"] == ["B-1"], out
    assert out["SuiteChecked"] == []


def test_s1_edit_with_equal_values_passes_as_suite_checked(repo: Path):
    files = _s1()
    files["docs/y/b1-clarification-7-s1-2026-11-22.md"] = "clarification 7\n"
    out = _judge(repo, files)
    assert out["Ok"] is True, out
    assert sorted(out["SuiteChecked"]) == ["src/scorer.py", "src/wrapper.py"]  # type: ignore[arg-type]


def test_s1_edit_with_unequal_values_refuses(repo: Path):
    _only(_judge(repo, _s1(wrapper=SHA_B)), "the S1 edit sets unequal values")


@pytest.mark.parametrize("rel", ["src/scorer.py", "src/wrapper.py"])
def test_s1_edit_with_a_third_changed_line_refuses(repo: Path, rel: str):
    files = _s1()
    text = files[rel]
    assert text is not None
    files[rel] = text.replace("TAIL = 1", "TAIL = 2").replace("ACCEPT = False", "ACCEPT = True")
    _only(_judge(repo, files), f"S1 edit of {rel} changes 2 lines")


@pytest.mark.parametrize("extra", ["src/free.py", "docs/other.md"])
def test_s1_head_with_an_extra_file_refuses(repo: Path, extra: str):
    files = _s1()
    files[extra] = "extra\n"
    _only(_judge(repo, files), f"the S1 head touches another path: {extra} (M)")


def test_s1_edit_of_one_file_only_refuses(repo: Path):
    files = _s1()
    del files["src/wrapper.py"]
    _only(_judge(repo, files), "the S1 edit must also change src/wrapper.py")


def test_s1_edit_not_a_hex_literal_refuses(repo: Path):
    _only(_judge(repo, _s1(scorer="A" * 64, wrapper="A" * 64)), "does not set ENTRY to a quoted 64-hex value")


def test_second_s1_edit_refuses(repo: Path):
    # The base is already at S1: changing the value again is not the S0 line.
    out = _judge(repo, _s1(scorer=SHA_B, wrapper=SHA_B), base_files=_s1())
    _only(out, "which is not the S0 line")


def test_s1_edit_line_count_change_refuses(repo: Path):
    files = _s1()
    files["src/scorer.py"] = files["src/scorer.py"] + "NEW = 1\n"  # type: ignore[operator]
    _only(_judge(repo, files), "changes the line count")


@pytest.mark.parametrize(("files", "fragment"), [
    ({"src/pinned.py": "pinned = 2\n"}, "code pin src/pinned.py is changed (M)"),
    ({"src/pinned.py": None}, "code pin src/pinned.py is changed (D)"),
    ({"src/released.py": "released = 2\n"}, "release file src/released.py is changed (M)"),
    ({"docs/rule.md": "# edited\n"}, "record docs/rule.md is changed (M)"),
    ({"docs/x/b1-clarification-1-a.md": None}, "record docs/x/b1-clarification-1-a.md is changed (D)"),
    ({"docs/bound/new.md": "new\n"}, "docs/bound/new.md is under the frozen prefix docs/bound/ (A)"),
    ({"src/scorer.py": None}, "S1-edit file src/scorer.py is changed (D), not modified"),
], ids=["code", "code-delete", "release-file", "record", "clarification-delete", "prefix-add", "s1-file-delete"])
def test_refusals(repo: Path, files: dict[str, str | None], fragment: str):
    _only(_judge(repo, files), fragment)


def test_new_clarification_passes(repo: Path):
    out = _judge(repo, {"docs/z/b1-clarification-6-look-chain-2026-11-25.md": "six\n"})
    assert out["Ok"] is True, out


def test_warn_path_warns_without_refusing(repo: Path):
    out = _judge(repo, {"scripts/export.ps1": "'changed'\n"})
    assert out["Ok"] is True, out
    assert out["Warnings"] == ["B-1: warn path scripts/export.ps1 is changed (M)"]


def test_present_release_record_releases_code_but_not_records(repo: Path):
    record = {"docs/record/b-look-record.md": "decision_log_row: 2026-12-14\n"}
    out = _judge(repo, {"src/pinned.py": "after B\n", "src/released.py": "after B\n"}, base_files=record)
    assert out["Ok"] is True and out["ActiveHolds"] == [], out
    _git(repo, "branch", "-D", "head")
    _only(_judge(repo, {"docs/rule.md": "# edited\n"}), "record docs/rule.md is changed (M)")
    _git(repo, "branch", "-D", "head")
    _only(_judge(repo, {"docs/record/b-look-record.md": None}), "the release record docs/record/b-look-record.md")


def test_registry_pure_addition_passes(repo: Path):
    registry = _registry()
    hold = registry["holds"][0]  # type: ignore[index]
    hold["record_globs"].append("docs/**/pt1-clarification-*.md")
    registry["holds"].append({"id": "PT-1", "records": {}, "code": {},  # type: ignore[union-attr]
                              "release_record": "docs/record/pt1.md"})
    out = _judge(repo, {"config/frozen_bindings.json": json.dumps(registry, indent=1) + "\n"})
    assert out["Ok"] is True, out


@pytest.mark.parametrize("mutate", ["edit-pin", "drop-glob", "drop-code", "reorder-holds"])
def test_registry_change_other_than_addition_refuses(repo: Path, mutate: str):
    registry = _registry()
    hold = registry["holds"][0]  # type: ignore[index]
    if mutate == "edit-pin":
        hold["code"]["src/pinned.py"] = "6" * 64
    if mutate == "drop-glob":
        hold["record_globs"] = []
    if mutate == "drop-code":
        del hold["code"]["src/pinned.py"]
    if mutate == "reorder-holds":
        registry["holds"] = [{"id": "PT-1", "release_record": "docs/record/pt1.md"}, hold]
    out = _judge(repo, {"config/frozen_bindings.json": json.dumps(registry, indent=1) + "\n"})
    _only(out, "changes other than by pure additions")


def test_registry_delete_refuses(repo: Path):
    _only(_judge(repo, {"config/frozen_bindings.json": None}), "config/frozen_bindings.json is deleted")


def test_tip_registry_cannot_loosen_its_own_judgement(repo: Path):
    # Judged by the base registry: removing the code pin in the same head does not admit the code change.
    registry = _registry()
    del registry["holds"][0]["code"]["src/pinned.py"]  # type: ignore[index]
    out = _judge(repo, {"config/frozen_bindings.json": json.dumps(registry) + "\n", "src/pinned.py": "x\n"})
    _only(out, "code pin src/pinned.py is changed (M)")


@pytest.mark.parametrize("text", ["{ not json\n", '{"schema": "frozen_bindings/0", "holds": [{"id": "x"}]}\n',
                                  '{"schema": "frozen_bindings/1", "holds": []}\n'],
                         ids=["not-json", "wrong-schema", "no-holds"])
def test_malformed_base_registry_refuses(repo: Path, text: str):
    out = _judge(repo, {"docs/other.md": "edited\n"}, base_files={"config/frozen_bindings.json": text})
    _only(out, "frozen-binding guard: registry config/frozen_bindings.json at")


def test_absent_base_registry_means_no_holds(repo: Path):
    out = _judge(repo, {"src/pinned.py": "x\n", "docs/rule.md": "y\n"},
                 base_files={"config/frozen_bindings.json": None})
    assert out["Ok"] is True and out["RegistryPresent"] is False, out


def test_unknown_commit_refuses(repo: Path, tmp_path: Path):
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
         str(tmp_path / "driver.ps1"), "-Guard", str(GUARD), "-Repo", str(repo), "-Base", "0" * 40, "-Tip", "HEAD"],
        capture_output=True, text=True, timeout=120)
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["Ok"] is False and "is not a commit" in out["Refusals"][0], out
