"""Tests for the H1 oracle-handout cut script (``tools/research/maker_replay_v2_h1_cut.py``).

Guards: gate spec v3.4 §1-§5 (accepted 2026-10-07) and the R1/R2/R4 rulings — source hash pins refuse before
reading, the §3 table matches the spec text, the §5 globs and the R4 fail-closed import refusal (string and split
forms), the R1 standalone-repository invariants, and the R2 byte-identical re-bind.

Synthetic fixtures only: no engine code, no data, no real cut. This module's name matches the §5 exclusion glob
``tests/operations/test_maker_replay_v2_*`` on purpose, so it never enters the oracle's filtered tree.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

from tools.research import maker_replay_v2_h1_cut as h1

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_V34 = REPO_ROOT / "docs" / "roadmap" / "maker-replay-v2-shadow-gate-spec-v3.4-DRAFT-2026-10-07.md"
PKG = "maker" + "_core"
GIT_IDENTITY = ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgSign=false")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *GIT_IDENTITY, *args], capture_output=True, text=True,
                            timeout=60)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


# --------------------------------------------------------------------------- §3/§4/§5 vs spec text


def _parse_section3(text: str) -> list[h1.Sub]:
    section = text.split("\n## 3. Substitution table", 1)[1].split("\n## 4. ", 1)[0]
    subs: list[dict] = []
    source = None
    in_block = False
    for line in section.split("\n"):
        header = re.match(r"^### 3\.\d+ .*\(`(D-shadow-gate-spec-[^`]+\.md)`\)\s*$", line)
        if header:
            source = header.group(1)
            continue
        if line.startswith("```"):
            in_block = not in_block
            continue
        if not in_block or not line.strip() or line.startswith("  = "):
            continue
        entry = re.match(r"^S(\d+)\s+l\.(\d+)(?:-(\d+))?\s+(.*)$", line)
        if entry:
            rest = entry.group(4)
            kind = ("withdrawn" if rest.startswith("[withdrawn") else "delete" if rest.startswith("delete")
                    else "span" if rest.startswith("replace span") else "lines" if rest.startswith("replace whole")
                    else "cell" if rest.startswith("replace the G2 row") else None)
            assert kind, line
            start = int(entry.group(2))
            row = {"id": f"S{entry.group(1)}", "source": source, "kind": kind, "start": start,
                   "end": int(entry.group(3) or start), "new": []}
            if kind == "cell":
                cell = re.search(r"between '(.*)' and '(.*)'\)\s*$", rest)
                row["left"], row["right"] = cell.group(1), cell.group(2)
            subs.append(row)
            continue
        for prefix, key in (("  - ", "old"), ("  first: ", "first")):
            if line.startswith(prefix):
                subs[-1][key] = line[len(prefix):]
                break
        else:
            if line.startswith("  + "):
                subs[-1]["new"].append(line[4:])
            elif re.match(r"^  last:\s+", line):
                value = re.sub(r"^  last:\s+", "", line)
                subs[-1]["last"] = "" if value == "(blank line)" else value
            else:
                raise AssertionError(f"unparsed table line: {line!r}")
    live = [s for s in subs if s["kind"] != "withdrawn"]
    assert len(subs) == 58
    return [h1.Sub(**{**s, "new": tuple(s["new"])}) for s in live]


def _text_block_after(text: str, marker: str) -> list[str]:
    tail = text.split(marker, 1)[1]
    block = tail.split("```text\n", 1)[1].split("```", 1)[0]
    return block.split()


def test_substitution_table_matches_spec_section3():
    parsed = _parse_section3(SPEC_V34.read_text(encoding="utf-8"))
    assert len(parsed) == 49
    assert tuple(parsed) == h1.V34_TABLE


def test_deny_lists_and_globs_match_spec():
    text = SPEC_V34.read_text(encoding="utf-8")
    assert set(_text_block_after(text, "**Denied Kernel identifiers (curated, explicit).**")) == h1.DENIED_IDENTIFIERS
    assert set(_text_block_after(text, "**Excluded on purpose.**")) == h1.EXCLUDED_IDENTIFIERS
    base = _text_block_after(text, "At the build-line commit it is cut from, it excludes")
    r4 = _text_block_after(text, "**Additional exclusions `[v3.4: ruling R4")
    assert list(h1.EXCLUSION_GLOBS) == base + r4


# --------------------------------------------------------------------------- hash pins


def test_verify_sha256_refuses_mismatch_and_abbreviated_pins():
    data = b"source text\n"
    assert h1.verify_sha256(data, _sha(data), "S") == _sha(data)
    with pytest.raises(h1.CutRefused, match="mismatch"):
        h1.verify_sha256(data + b" ", _sha(data), "S")
    with pytest.raises(h1.CutRefused, match="full lowercase"):
        h1.verify_sha256(data, _sha(data)[:12], "S")


@pytest.mark.parametrize(
    ("expected", "ok"),
    [("abcdef12" + "0" * 52 + "a3b1", True), ("abcdef12…a3b1", True), ("abcdef12…a3b2", False),
     ("abcdef1", True), ("abcdef0", False), ("abc", False)],
)
def test_hash_matches_abbreviations(expected, ok):
    assert h1.hash_matches("abcdef12" + "0" * 52 + "a3b1", expected) is ok


# --------------------------------------------------------------------------- §3 application


SOURCE = "alpha `old_name` here\n| G2 | old cell | `kernel.py:1-2` | tail\nline three\nline four\nline five\n"


def test_apply_substitutions_spans_cells_ranges():
    subs = [
        h1.Sub("S1", "x", "span", 1, 1, old="`old_name`", new=("the new name",)),
        h1.Sub("S2", "x", "cell", 2, 2, new=("new cell",), left="| G2 | ", right=" | `kernel.py:1-2`"),
        h1.Sub("S3", "x", "lines", 3, 3, new=("replaced three",)),
        h1.Sub("S4", "x", "delete", 4, 5, first="line four", last="line five"),
    ]
    out = h1.apply_substitutions(SOURCE.replace("\n", "\r\n"), subs)
    assert out == "alpha the new name here\n| G2 | new cell | `kernel.py:1-2` | tail\nreplaced three\n"


@pytest.mark.parametrize(
    ("sub", "message"),
    [
        (h1.Sub("S1", "x", "span", 1, 1, old="missing", new=("y",)), "exactly once"),
        (h1.Sub("S1", "x", "span", 3, 3, old="e", new=("y",)), "exactly once"),
        (h1.Sub("S1", "x", "lines", 5, 6, new=("y",)), "out of bounds"),
        (h1.Sub("S1", "x", "delete", 4, 5, first="line FOUR"), "first line"),
        (h1.Sub("S1", "x", "delete", 4, 5, last="line six"), "last line"),
        (h1.Sub("S1", "x", "cell", 2, 2, new=("y",), left="| G3 | ", right=" | "), "left marker"),
    ],
)
def test_apply_substitutions_fails_closed(sub, message):
    with pytest.raises(h1.CutRefused, match=message):
        h1.apply_substitutions(SOURCE, [sub])


def test_apply_substitutions_refuses_overlap_and_span_inside_range():
    with pytest.raises(h1.CutRefused, match="overlap"):
        h1.apply_substitutions(SOURCE, [h1.Sub("A", "x", "delete", 3, 4), h1.Sub("B", "x", "delete", 4, 5)])
    with pytest.raises(h1.CutRefused, match="inside"):
        h1.apply_substitutions(SOURCE, [h1.Sub("A", "x", "delete", 1, 2),
                                        h1.Sub("B", "x", "span", 1, 1, old="alpha", new=("b",))])


def test_section4_rules_each_fire():
    rules = {hit.rule for hit in h1.section4_hits("f", "```python\nx add_own\ny state.legs\n`a view_state b`\n")}
    assert rules == {"rule1:fenced-python", "rule2:add_own", "rule3:state-attribute", "rule4:view_state"}
    assert h1.section4_hits("f", "`my_view_state` and `portfolio` and `compose_book`, outside view_state\n") == []


def test_kernel_drift_refuses_unlisted_name():
    listed = b"MAX_OUTPUTS = 1\nclass Kernel:\n    def __init__(self):\n        pass\n    def add_own(self):\n        pass\n"
    assert h1.drift_check(listed) == {"names": 4, "unlisted": 0}
    with pytest.raises(h1.CutRefused, match="new_helper"):
        h1.drift_check(listed + b"def new_helper():\n    pass\n")


# --------------------------------------------------------------------------- §5 globs and R4 refusal


@pytest.mark.parametrize(
    ("path", "excluded"),
    [
        (f"src/{PKG}/replay/v2/kernel.py", True),
        (f"src/{PKG}/replay/bundle.py", True),
        (f"src/{PKG}/shadow/runner.py", True),
        (f"src/{PKG}/shadow/other.py", False),
        (f"src/{PKG}/live/a/b.py", True),
        ("src/weather/market/maker_replay_x.py", True),
        ("src/weather/market/maker_replay_x/y.py", False),
        (f"tests/{PKG}/fixtures/deep/x.json", True),
        (f"tests/{PKG}/fixtures", False),
        (f"tests/{PKG}/test_replay_v2.py", True),
        ("tests/operations/test_maker_replay_v2_anything.py", True),
        ("tests/operations/test_maker_replay_v1.py", False),
        ("docs/research/maker-replay-v2-engineering-plan-DRAFT.md", True),
        ("docs/roadmap/maker-replay-v2-shadow-gate-spec-v3.4-oracle-rulings-2026-10-07.md", True),
        ("docs/roadmap/agent-report-2026-10-mrv2-u3.md", True),
        ("tools/research/maker_replay_v2/dense.py", True),
        ("tools/research/maker_replay_v2_h1_cut.py", False),
        (f"src/{PKG}/contracts/__init__.py", False),
    ],
)
def test_exclusion_globs(path, excluded):
    assert h1.excluded_by(path) is excluded


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("a.py", f"import {PKG}.replay.v2\n"),
        ("a.py", f"import {PKG}.replay as r\n"),
        ("a.py", f"from {PKG}.replay.bundle import X\n"),
        ("a.py", f"from {PKG} import replay\n"),
        (f"src/{PKG}/quoting/a.py", "from ..replay import bundle\n"),
        ("a.py", f"import importlib\nm = importlib.import_module('{PKG}.replay.v2.kernel')\n"),
        ("a.py", f"m = __import__('{PKG}.replay')\n"),
        ("a.py", f"PATH = 'src/{PKG}/replay/v2'\n"),
        ("a.py", f"import importlib\nm = importlib.import_module('{PKG}' + '.rep' + 'lay')\n"),
        ("a.py", f"import importlib\nm = importlib.import_module('{PKG[:5]}' '{PKG[5:]}.replay')\n"),
        ("a.py", f"import importlib\nparts = ['{PKG}', 'replay']\nm = importlib.import_module('.'.join(parts))\n"),
        ("a.py", f"import importlib\nm = importlib.import_module('.replay', package='{PKG}')\n"),
        ("a.py", f"import {PKG}\nm = getattr({PKG}, 'replay')\n"),
        ("a.py", f"x = f'{PKG}.replay.{{name}}'\n"),
        ("a.py", "def broken(:\n    '" + PKG + ".replay'\n"),
        ("notes.md", f"See `{PKG}/replay/**` for the engine.\n"),
        ("run.ps1", f'$m = @("{PKG}.replay")\n'),
        ("blob.bin", b"\x00\xff".decode("latin-1") + f"{PKG}.replay"),
    ],
)
def test_import_refusal_catches(path, body):
    assert h1.refusal_reasons(path, body.encode("utf-8") if path != "blob.bin" else body.encode("latin-1"))


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("a.py", f"from {PKG}.contracts import portfolio\nfrom {PKG}.quoting import policy\n"),
        ("a.py", "MODE = 'replay'\nimport importlib\nm = importlib.import_module(name)\n"),
        ("a.py", f"from {PKG}.quoting import policy\nLABEL = 'replay'\n"),
        ("notes.md", "The replay engine is described in prose only.\n"),
    ],
)
def test_import_refusal_allows_unrelated(path, body):
    assert h1.refusal_reasons(path, body.encode("utf-8")) == []


# --------------------------------------------------------------------------- R1 standalone repository


def _entries(files: dict[str, bytes]) -> list[tuple[h1.TreeEntry, bytes]]:
    return [(h1.TreeEntry(path, "100644", ""), data) for path, data in files.items()]


@pytest.fixture
def standalone(tmp_path) -> Path:
    repo = tmp_path / "oracle-repo"
    h1.create_standalone_repo(repo, _entries({"a.txt": b"a\n", "dir/b.py": b"print(1)\n"}))
    return repo


@pytest.mark.spawns
def test_standalone_repo_meets_r1(standalone):
    report = h1.assert_r1_invariants(standalone)
    assert report["rev_list_all"] == 1 and report["refs"] == ["refs/heads/main"]
    assert (standalone / "dir" / "b.py").read_bytes() == b"print(1)\n"
    assert _git(standalone, "rev-list", "--parents", "-n", "1", "main").count(" ") == 0


@pytest.mark.spawns
def test_standalone_repo_is_deterministic(tmp_path):
    files = _entries({"a.txt": b"a\n"})
    first = h1.create_standalone_repo(tmp_path / "one", files)
    second = h1.create_standalone_repo(tmp_path / "two", files)
    assert first == second


@pytest.mark.spawns
def test_r1_refuses_remote(standalone):
    _git(standalone, "remote", "add", "origin", "https://example.invalid/repo.git")
    with pytest.raises(h1.CutRefused, match="remote"):
        h1.assert_r1_invariants(standalone)


@pytest.mark.spawns
def test_r1_refuses_alternates(standalone, tmp_path):
    (standalone / ".git" / "objects" / "info").mkdir(parents=True, exist_ok=True)
    (standalone / ".git" / "objects" / "info" / "alternates").write_text(str(tmp_path / "elsewhere"))
    with pytest.raises(h1.CutRefused, match="alternates"):
        h1.assert_r1_invariants(standalone)


@pytest.mark.spawns
def test_r1_refuses_second_commit(standalone):
    (standalone / "c.txt").write_text("c\n")
    _git(standalone, "add", "c.txt")
    _git(standalone, "commit", "-q", "-m", "second")
    with pytest.raises(h1.CutRefused, match="exactly 1"):
        h1.assert_r1_invariants(standalone)


@pytest.mark.spawns
def test_r1_refuses_other_ref_and_stray_object(standalone):
    _git(standalone, "update-ref", "refs/tags/extra", "main")
    with pytest.raises(h1.CutRefused, match="refs other than"):
        h1.assert_r1_invariants(standalone)
    _git(standalone, "update-ref", "-d", "refs/tags/extra")
    subprocess.run(["git", "-C", str(standalone), "hash-object", "-w", "--stdin"], input=b"stray", check=True,
                   capture_output=True)
    with pytest.raises(h1.CutRefused, match="not reachable"):
        h1.assert_r1_invariants(standalone)


@pytest.mark.spawns
def test_r1_refuses_packed_ref(standalone):
    head = _git(standalone, "rev-parse", "main")
    (standalone / ".git" / "packed-refs").write_bytes(f"# pack-refs with: peeled\n{head} refs/heads/other\n".encode())
    with pytest.raises(h1.CutRefused, match="packed-refs holds another ref"):
        h1.assert_r1_invariants(standalone)


# --------------------------------------------------------------------------- end-to-end cut and re-bind

CODE_PATHS = {
    "H-6": f"src/{PKG}/contracts/__init__.py",
    "H-7": f"src/{PKG}/contracts/conformance.py",
    "H-8": f"src/{PKG}/contracts/portfolio.py",
    "H-9": f"src/{PKG}/quoting/policy.py",
}
TEXT_89A = "docs/roadmap/handoff-89a.md"
SYN_TABLE = (h1.Sub("S1", "spec-a.md", "span", 2, 2, old="`add_own`", new=("own-leg composition",)),
             h1.Sub("S2", "spec-b.md", "delete", 3, 3, first="state.legs residue"))


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))


def _source_files() -> dict[str, str]:
    files = {path: f"# synthetic {item}\nVALUE = 1\n" for item, path in CODE_PATHS.items()}
    files.update({
        TEXT_89A: "# 89a contract (synthetic)\n",
        f"src/{PKG}/replay/v2/kernel.py": "class Kernel:\n    def __init__(self):\n        pass\n",
        f"tests/{PKG}/fixtures/expected.json": "{}\n",
        "docs/roadmap/maker-replay-v2-shadow-gate-spec-v9.md": "`add_own`\n",
        "README.md": "synthetic repository\n",
        ".gitattributes": "* text=auto eol=lf\n",
    })
    return files


@pytest.fixture
def cut_env(tmp_path):
    repo = tmp_path / "src-repo"
    _write_tree(repo, _source_files())
    _git(tmp_path, "init", "-q", str(repo))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    specs = tmp_path / "specs"
    _write_tree(specs, {"spec-a.md": "# A\nuses `add_own` here\n", "spec-b.md": "# B\nok\nstate.legs residue\n"})
    rulings = tmp_path / "rulings.md"
    rulings.write_text("# Rulings\nOD23: decide() unchanged.\n", encoding="utf-8")
    plan = {
        "schema": h1.PLAN_SCHEMA,
        "rev": "r-test",
        "spec_source_dir": str(specs),
        "build_line_commit": "HEAD",
        "spec_cuts": [
            {"id": "H-1", "source": "spec-a.md", "sha256": _sha((specs / "spec-a.md").read_bytes()),
             "handout_path": "spec/a.md"},
            {"id": "H-2", "source": "spec-b.md", "sha256": _sha((specs / "spec-b.md").read_bytes()),
             "handout_path": "spec/b.md",
             "expected_output_sha256": _sha(b"# B\nok\n")},
        ],
        "code_items": [{"id": item, "path": path,
                        "blob": h1.git_blob_id(f"# synthetic {item}\nVALUE = 1\n".encode())}
                       for item, path in CODE_PATHS.items()],
        "text_89a": {"id": "H-10", "path": TEXT_89A, "sha256": _sha(b"# 89a contract (synthetic)\n")},
        "rulings_sheet": {"id": "H-11", "file": str(rulings), "sha256": _sha(rulings.read_bytes())},
        "cover_prompt": None,
    }
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    return {"repo": repo, "plan": plan, "plan_file": plan_file, "tmp": tmp_path}


def _cut(env, out_name="out", plan=None):
    if plan is not None:
        env["plan_file"].write_text(json.dumps(plan), encoding="utf-8")
    return h1.run_cut(env["plan_file"], env["repo"], env["tmp"] / out_name, table=SYN_TABLE, mo1_skip=None)


@pytest.mark.spawns
def test_cut_end_to_end(cut_env):
    manifest, binding = _cut(cut_env)
    out = cut_env["tmp"] / "out"
    assert binding == _sha((out / h1.MANIFEST_NAME).read_bytes())
    assert manifest["bindable"] is False  # cover prompt placeholder
    by_id = {row["id"]: row for row in manifest["handout"]}
    assert (out / "handout" / "spec" / "a.md").read_text(encoding="utf-8") == "# A\nuses own-leg composition here\n"
    assert by_id["H-6"]["commit"] == manifest["build_line_commit"]
    repo = out / h1.REPO_DIR
    tracked = set(_git(repo, "ls-tree", "-r", "--name-only", "main").split())
    assert f"src/{PKG}/contracts/portfolio.py" in tracked and "README.md" in tracked
    assert not any("replay" in p or "fixtures" in p or "gate-spec" in p for p in tracked)
    assert manifest["filtered_tree"]["tree"] == _git(repo, "rev-parse", "main^{tree}")
    assert manifest["checks"]["kernel_drift"]["unlisted"] == 0
    _, again = _cut(cut_env, "out2")
    assert again == binding


@pytest.mark.spawns
def test_cut_refuses_source_hash_mismatch_without_output(cut_env):
    plan = cut_env["plan"]
    plan["spec_cuts"][0]["sha256"] = _sha(b"some other bytes")
    with pytest.raises(h1.CutRefused, match="H-1: SHA-256 mismatch"):
        _cut(cut_env, plan=plan)
    assert not (cut_env["tmp"] / "out").exists()


@pytest.mark.spawns
def test_cut_refuses_code_blob_mismatch(cut_env):
    plan = cut_env["plan"]
    plan["code_items"][3]["blob"] = "0" * 40
    with pytest.raises(h1.CutRefused, match="H-9: blob id mismatch"):
        _cut(cut_env, plan=plan)


@pytest.mark.spawns
def test_cut_refuses_import_in_filtered_tree(cut_env):
    repo = cut_env["repo"]
    _write_tree(repo, {"tools/helper.py": f"import importlib\nm = importlib.import_module('{PKG}' + '.replay')\n"})
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "leak")
    with pytest.raises(h1.CutRefused, match="tools/helper.py"):
        _cut(cut_env)
    assert not (cut_env["tmp"] / "out").exists()


@pytest.mark.spawns
def test_cut_refuses_section4_hit_in_rulings_sheet(cut_env):
    plan = cut_env["plan"]
    rulings = Path(plan["rulings_sheet"]["file"])
    rulings.write_text("# Rulings\nthe state.legs field\n", encoding="utf-8")
    plan["rulings_sheet"]["sha256"] = _sha(rulings.read_bytes())
    with pytest.raises(h1.CutRefused, match="§4 check"):
        _cut(cut_env, plan=plan)


@pytest.mark.spawns
def test_rebind_identical_and_differing(cut_env, capsys):
    _cut(cut_env)
    manifest_file = cut_env["tmp"] / "out" / h1.MANIFEST_NAME
    repo = cut_env["repo"]
    _write_tree(repo, {"README.md": "changed elsewhere\n"})
    _git(repo, "commit", "-q", "-am", "unrelated change")
    identical = _git(repo, "rev-parse", "HEAD")
    record, _ = h1.run_rebind(manifest_file, repo, identical)
    assert record["new_commit"] == identical and len(record["files"]) == 4
    _write_tree(repo, {CODE_PATHS["H-9"]: "# synthetic H-9\nVALUE = 2\n"})
    _git(repo, "commit", "-q", "-am", "policy change")
    assert h1.main(["rebind", "--manifest", str(manifest_file), "--repo", str(repo), "--commit", "HEAD"]) == 2
    err = capsys.readouterr().err
    assert "re-hand" in err and "H-9" in err and "H-6" not in err
