"""Executes scripts/ops/frozen_binding_guard.ps1 (Test-FrozenBindingHead) against fake git repositories.

Guards: ruling R14 (master 2026-11-01) and its S1 ruling: B-1 Clarification 3 section 5 permits exactly two changed
lines in one head, the scorer's entry constant and the wrapper's pin, set to the same value, and nothing else; the
registry is judged as it is at the merge base and may only grow by pure additions; records are frozen for good,
code pins until the release record exists. Master's strict S1 ruling (2026-11-01): besides the two lines the S1
head may add at most one new file, matching docs/research/**/b1-clarification-7-*.md. The release record ruling:
B's rule sha, a committed receipt_path made non-text by an exact .gitattributes line (-text or binary) whose
exact bytes hash to receipt_sha256, a DECISION_LOG row, and for an
abandonment a row naming an owner abandonment.
"""
from __future__ import annotations

import hashlib
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
        "s1_companion_glob": "docs/research/**/b1-clarification-7-*.md",
        "warn": ["scripts/export.ps1"],
        "release_record": "docs/record/b-look-record.md",
        "record_rule_sha256": "1" * 64,
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
    ".gitattributes": "* text=auto eol=lf\n",  # as in the real repository: a CRLF receipt would be normalised
    "docs/operations/DECISION_LOG.md": ("# log\n| 2026-10-28 | **B-1 bound.** |\n"
                                        "| 2099-02-01 | **B-1 abandoned (owner).** The owner abandons B-1. |\n"
                                        "| 2099-03-01 | **MASTER RULING, not an owner decision: B-1 abandoned.** |\n"
                                        "| 2099-04-01 | **Owner approves a pilot.** |\n"),
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
    files[CL7] = "clarification 7\n"
    out = _judge(repo, files)
    assert out["Ok"] is True, out
    assert sorted(out["SuiteChecked"]) == ["src/scorer.py", "src/wrapper.py"]  # type: ignore[arg-type]


def test_s1_edit_alone_passes(repo: Path):
    out = _judge(repo, _s1())
    assert out["Ok"] is True and len(out["SuiteChecked"]) == 2, out  # type: ignore[arg-type]


CL7 = "docs/research/y/b1-clarification-7-s1-2026-11-22.md"


@pytest.mark.parametrize(("extra", "fragment"), [
    ({CL7.replace("-7-", "-8-"): "eight\n"}, "touches another path: docs/research/y/b1-clarification-8-"),
    ({CL7.replace("-7-", "-70-"): "seventy\n"}, "touches another path: docs/research/y/b1-clarification-70-"),
    ({"docs/y/b1-clarification-7-s1.md": "outside research\n"}, "touches another path: docs/y/b1-clarification-7-"),
    ({CL7: "one\n", CL7.replace("s1-", "s1b-"): "two\n"}, "adds 2 files matching"),
    ({CL7: "one\n", "docs/new.md": "new\n"}, "touches another path: docs/new.md (A)"),
    ({"docs/x/b1-clarification-1-a.md": "edited\n"}, "touches another path: docs/x/b1-clarification-1-a.md (M)"),
], ids=["other-number", "number-prefix", "outside-research", "two-new-files", "clarification-plus-other",
        "modify-existing-clarification"])
def test_strict_s1_head_refuses(repo: Path, extra: dict[str, str | None], fragment: str):
    files = _s1()
    files.update(extra)
    _only(_judge(repo, files), fragment)


def test_strict_s1_head_refuses_a_modify_of_an_existing_clarification_7(repo: Path):
    files = _s1()
    files[CL7] = "edited\n"
    _only(_judge(repo, files, base_files={CL7: "existing\n"}), f"touches another path: {CL7} (M)")


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


RECORD = "docs/record/b-look-record.md"
RECEIPT = "docs/record/b_look_receipt.json"
RECEIPT_TEXT = '{\r\n  "look": "b"\r\n}\r\n'  # CRLF kept: the fake repo has no attributes and autocrlf off
RECEIPT_SHA = hashlib.sha256(RECEIPT_TEXT.encode("utf-8")).hexdigest()
GOOD_RECORD = (f"# record\nrule_sha256: {'1' * 64}\nreceipt_path: {RECEIPT}\nreceipt_sha256: {RECEIPT_SHA}\n"
               "decision_log_row: 2026-10-28\n")


ATTRIBUTES = "* text=auto eol=lf\n" + f"{RECEIPT} -text\n"
ATTRIBUTE_MESSAGE = f"B-1: receipt must be committed byte-exact: add '{RECEIPT} -text' to .gitattributes in the same head"


def _with_attributes(files: dict[str, str | None]) -> dict[str, str | None]:
    return {".gitattributes": ATTRIBUTES, **files} if RECEIPT in files else files


@pytest.mark.parametrize("line", [f"{RECEIPT} -text", f"{RECEIPT} binary", f"/{RECEIPT} -text"],
                         ids=["minus-text", "binary", "anchored"])
def test_adding_a_valid_look_record_passes(repo: Path, line: str):
    out = _judge(repo, {RECORD: GOOD_RECORD, RECEIPT: RECEIPT_TEXT, ".gitattributes": f"* text=auto eol=lf\n{line}\n"})
    assert out["Ok"] is True, out


@pytest.mark.parametrize("attributes", [None, ATTRIBUTES + "*.json text\n", f"* text=auto eol=lf\n{RECEIPT} text\n",
                                        "* text=auto eol=lf\ndocs/record/*.json -text\n"],
                         ids=["no-line", "overridden-later", "text-not-minus", "glob-not-exact"])
def test_receipt_without_a_byte_exact_attribute_refuses(repo: Path, attributes: str | None):
    files: dict[str, str | None] = {RECORD: GOOD_RECORD, RECEIPT: RECEIPT_TEXT}
    if attributes is not None:
        files[".gitattributes"] = attributes
    out = _judge(repo, files)
    assert out["Ok"] is False and ATTRIBUTE_MESSAGE in out["Refusals"], out  # type: ignore[operator]
    assert not any("not the sha256 of the bytes" in r for r in out["Refusals"]), out  # type: ignore[union-attr]


def test_adding_an_owner_abandonment_record_passes(repo: Path):
    out = _judge(repo, {RECORD: "b_abandonment: B-1 abandoned\ndecision_log_row: 2099-02-01\n"})
    assert out["Ok"] is True, out


@pytest.mark.parametrize(("files", "fragment"), [
    ({RECORD: GOOD_RECORD.replace("1" * 64, "2" * 64), RECEIPT: RECEIPT_TEXT}, "is not B's rule sha"),
    ({RECORD: GOOD_RECORD.replace(f"rule_sha256: {'1' * 64}\n", ""), RECEIPT: RECEIPT_TEXT}, "is not B's rule sha"),
    ({RECORD: GOOD_RECORD, RECEIPT: RECEIPT_TEXT.replace("\r\n", "\n")}, "is not the sha256 of the bytes"),
    ({RECORD: GOOD_RECORD.replace(RECEIPT_SHA, RECEIPT_SHA.upper()), RECEIPT: RECEIPT_TEXT}, "not 64 lowercase hex"),
    ({RECORD: GOOD_RECORD.replace(f"receipt_path: {RECEIPT}\n", ""), RECEIPT: RECEIPT_TEXT},
     "receipt_path '' is not a repo-relative path"),
    ({RECORD: GOOD_RECORD.replace(RECEIPT, "C:/x/r.json"), RECEIPT: RECEIPT_TEXT}, "is not a repo-relative path"),
    ({RECORD: GOOD_RECORD.replace(RECEIPT, "docs/../r.json"), RECEIPT: RECEIPT_TEXT}, "is not a repo-relative path"),
    ({RECORD: GOOD_RECORD}, f"receipt_path {RECEIPT} is not committed at the tip"),
    ({RECORD: GOOD_RECORD + "decision_log_row: 2026-10-28\n", RECEIPT: RECEIPT_TEXT}, "appears more than once"),
    ({RECORD: GOOD_RECORD.replace("2026-10-28", "2099-09-09"), RECEIPT: RECEIPT_TEXT}, "names no DECISION_LOG row"),
    ({RECORD: "b_abandonment: x\ndecision_log_row: 2099-03-01\n"}, "names an owner abandonment"),
    ({RECORD: "b_abandonment: x\ndecision_log_row: 2099-04-01\n"}, "names an owner abandonment"),
    ({RECORD: "b_abandonment: x\ndecision_log_row: 2026-10-28\n"}, "names an owner abandonment"),
    ({RECORD: "b_abandonment: x\n"}, "names no DECISION_LOG row"),
], ids=["wrong-rule", "no-rule", "receipt-normalised", "upper-receipt-sha", "no-receipt-path", "drive-path",
        "dotdot-path", "receipt-not-committed", "duplicate-field", "row-not-in-log", "abandonment-master-row",
        "abandonment-owner-not-abandon", "abandonment-not-owner", "abandonment-without-row"])
def test_adding_a_malformed_record_refuses(repo: Path, files: dict[str, str | None], fragment: str):
    _only(_judge(repo, _with_attributes(files)), fragment)


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
