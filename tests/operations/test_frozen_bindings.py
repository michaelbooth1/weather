"""Frozen bindings: every hold in ``config/frozen_bindings.json`` holds in this checkout.

Guards: ruling R14 (master 2026-11-01; review items 14 and 27). B-1's frozen files are guarded in the repository
and released by B's committed look record (``release_record``), never by a date. Records are frozen permanently;
code pins (and the files of ``release_binding``) only while the hold is active, i.e. while its release record is
absent. The only permitted change of the code pins is the ``s1_edit`` of B-1 Clarification 3 section 5 (master's
R14 ruling, 2026-11-01): exactly two changed lines, ``b_scorer.py``'s ``MG1_LOOK_ENTRY_SHA256`` (as judged by
``b_scorer_entry_edit.s1_problems``) and the look wrapper's ``MG1_LOOK_ENTRY_PIN``, both set to the same value, and
nothing else in either file. At S1 the MG-1 registry entry in ``mg1_reserved_window.py`` must equal the recorded
``MG1_LOOK_ENTRY_SHA256``. The S1 commit is strict (master, 2026-11-01): besides the two lines it may add at most
one new file, matching ``s1_companion_glob`` (``docs/research/**/b1-clarification-7-*.md``), and nothing else
(``s1_commit_problems`` pins that rule; the guard applies it to the commit). A present release record is checked
for B's rule sha, a committed ``receipt_path`` made non-text by ``.gitattributes`` (exact path, ``-text`` or
``binary``) whose raw bytes hash to ``receipt_sha256``, and a DECISION_LOG row;
an abandonment record's row must name an owner abandonment. The git-diff side (no modify or delete of a record,
additions only to the registry, the strict S1 head) is ``scripts/ops/frozen_binding_guard.ps1``.

Stdlib plus ``weather.calibration.b_scorer_entry_edit`` only, so it runs in every suite, host included. It reads no
``data/``.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from weather.calibration import b_scorer_entry_edit

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = "config/frozen_bindings.json"
DECISION_LOG = "docs/operations/DECISION_LOG.md"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SCORER_JUDGE = "weather.calibration.b_scorer_entry_edit.s1_problems"
RECORD_FIELD = re.compile(r"^(?P<key>[a-z0-9_]+):[ \t]*(?P<value>\S.*?)[ \t]*$", re.M)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _assignment(constant: str) -> re.Pattern[bytes]:
    return re.compile(rb"^" + re.escape(constant.encode()) + rb" = (?P<value>[^\r\n]*)(?P<eol>\r?\n)?", re.M)


def _git_glob(root: Path, pattern: str) -> list[str]:
    """Repo-relative POSIX paths matching a ``docs/**/name-*.md`` style glob (``**`` spans directories)."""
    head, _, tail = pattern.partition("**/")
    base = root / head
    if not base.is_dir():
        return []
    return sorted(p.relative_to(root).as_posix() for p in base.rglob(tail) if p.is_file())


def _literal_sha(value: bytes) -> str | None:
    match = re.fullmatch(rb'"([0-9a-f]{64})"', value)
    return match.group(1).decode() if match else None


def registry_problems(registry: dict) -> list[str]:
    problems = []
    if registry.get("schema") != "frozen_bindings/1":
        problems.append(f"registry schema {registry.get('schema')!r} is not frozen_bindings/1")
    holds = registry.get("holds")
    if not isinstance(holds, list) or not holds:
        return problems + ["registry has no holds"]
    ids = [h.get("id") for h in holds]
    if len(set(ids)) != len(ids) or not all(isinstance(i, str) and i for i in ids):
        problems.append(f"hold ids are not unique non-empty strings: {ids}")
    for hold in holds:
        for key in ("records", "code"):
            for path, sha in (hold.get(key) or {}).items():
                if not isinstance(sha, str) or not HEX64.match(sha):
                    problems.append(f"{hold.get('id')}: {key} {path} pin {sha!r} is not 64 lowercase hex")
        for path in hold.get("s1_edit") or {}:
            if path not in (hold.get("code") or {}):
                problems.append(f"{hold.get('id')}: s1_edit {path} is not a code pin")
        if not isinstance(hold.get("release_record"), str) or not hold["release_record"]:
            problems.append(f"{hold.get('id')}: no release_record")
        rule = hold.get("record_rule_sha256")
        if rule is not None and rule not in (hold.get("records") or {}).values():
            problems.append(f"{hold.get('id')}: record_rule_sha256 {rule!r} is not a record pin")
        if hold.get("s1_companion_glob") is not None and not isinstance(hold["s1_companion_glob"], str):
            problems.append(f"{hold.get('id')}: s1_companion_glob is not a string")
    return problems


RECORD_KEYS = ("rule_sha256", "receipt_path", "receipt_sha256", "decision_log_row", "b_abandonment")
RECEIPT_PATH = re.compile(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$")


def owner_abandonment_rows(decision_log: str, row: str) -> list[str]:
    """DL rows of date ``row`` that name an owner abandonment (master's R14 ruling 2026-11-01, constraint 3).

    A simple textual test: the row contains the word ``owner`` and ``abandon``, and not ``not an owner
    decision`` (the marker of master rulings), case-insensitive."""
    return [line for line in decision_log.splitlines() if line.startswith(f"| {row} |")
            and re.search(r"\bowner\b", line, re.I) and re.search("abandon", line, re.I)
            and not re.search("not an owner decision", line, re.I)]


def receipt_attribute_problem(gitattributes: str, path: str) -> str | None:
    """The receipt must be committed byte-exact (master, 2026-11-01): ``.gitattributes`` makes ``path`` non-text.

    Exact path only: a line whose pattern is ``path`` or ``/path`` with ``-text`` or ``binary``, and no later line
    (any pattern) that sets text again (``text``, ``text=...`` or ``!text``). Fail-closed: put the line last."""
    exact_at = None
    for index, line in enumerate(gitattributes.splitlines()):
        tokens = line.split()
        if not tokens or tokens[0].startswith(("#", "[attr]")):
            continue
        sets_text = any(t == "text" or t.startswith("text=") or t == "!text" for t in tokens[1:])
        if tokens[0] in (path, "/" + path) and ("-text" in tokens[1:] or "binary" in tokens[1:]) and not sets_text:
            exact_at = index
        elif sets_text:
            exact_at = None
    if exact_at is None:
        return f"receipt must be committed byte-exact: add '{path} -text' to .gitattributes in the same head"
    return None


def record_problems(text: str, hold: dict, decision_log: str, root: Path) -> list[str]:
    """A present release record (master's R14 ruling 2026-11-01): a look record carries rule_sha256 (B's rule sha,
    the hold's record_rule_sha256), receipt_path (repo-relative, committed) and receipt_sha256 over that file's
    bytes exactly as written, plus decision_log_row; an abandonment carries b_abandonment and a decision_log_row
    whose DL row names an owner abandonment."""
    problems = []
    fields: dict[str, str] = {}
    for m in RECORD_FIELD.finditer(text):
        if m.group("key") not in RECORD_KEYS:
            continue
        if m.group("key") in fields:
            problems.append(f"release record field {m.group('key')} appears more than once")
        fields[m.group("key")] = m.group("value")
    row = fields.get("decision_log_row", "")
    has_row = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", row)) and any(
        line.startswith(f"| {row} |") for line in decision_log.splitlines())
    if not has_row:
        problems.append(f"release record decision_log_row {row!r} names no DECISION_LOG row")
    if "b_abandonment" in fields:
        if has_row and not owner_abandonment_rows(decision_log, row):
            problems.append(f"release record b_abandonment: no DECISION_LOG row of {row} names an owner abandonment")
        return problems
    rule = hold.get("record_rule_sha256")
    if not rule or fields.get("rule_sha256") != rule:
        problems.append(f"release record rule_sha256 {fields.get('rule_sha256')!r} is not B's rule sha {rule!r}")
    receipt_sha = fields.get("receipt_sha256", "")
    if not HEX64.match(receipt_sha):
        problems.append(f"release record receipt_sha256 {receipt_sha!r} is not 64 lowercase hex")
    receipt_path = fields.get("receipt_path", "")
    if not RECEIPT_PATH.match(receipt_path) or {".", ".."} & set(receipt_path.split("/")):
        problems.append(f"release record receipt_path {receipt_path!r} is not a repo-relative path")
    elif not (root / receipt_path).is_file():
        problems.append(f"release record receipt_path {receipt_path} is not in the checkout")
    elif attribute := receipt_attribute_problem(
            (root / ".gitattributes").read_text(encoding="utf-8") if (root / ".gitattributes").is_file() else "",
            receipt_path):
        problems.append(attribute)  # checked before the sha: a normalised blob must not read as a bare mismatch
    elif _sha((root / receipt_path).read_bytes()) != receipt_sha:  # raw bytes: no line-ending normalisation
        problems.append(f"release record receipt_sha256 is not the sha256 of the bytes of {receipt_path}")
    return problems


def _glob_regex(pattern: str) -> re.Pattern[str]:
    """The guard's glob: ``**/`` spans zero or more directories, ``*`` stays inside one segment."""
    escaped = re.escape(pattern).replace(r"\*\*/", "(?:.+/)?").replace(r"\*", "[^/]*")
    return re.compile(f"^{escaped}$")


def s1_commit_problems(hold: dict, changes: list[tuple[str, str]]) -> list[str]:
    """The strict S1 commit (master's R14 ruling 2026-11-01, (b)), over ``(status, path)`` name-status pairs.

    Every s1_edit file is modified; besides them at most one path, an addition matching s1_companion_glob. The
    guard applies this rule to the real commit; the suite cannot see commits, so it pins the rule here."""
    s1_paths = set(hold.get("s1_edit") or {})
    companion = _glob_regex(hold["s1_companion_glob"]) if hold.get("s1_companion_glob") else None
    problems = [f"the S1 edit must also change {p}" for p in sorted(s1_paths - {p for s, p in changes if s == "M"})]
    companions = []
    for status, path in changes:
        if path in s1_paths:
            if status != "M":
                problems.append(f"S1-edit file {path} is changed ({status}), not modified")
        elif companion and status == "A" and companion.match(path):
            companions.append(path)
        else:
            problems.append(f"the S1 head touches another path: {path} ({status})")
    if len(companions) > 1:
        problems.append(f"the S1 head adds {len(companions)} files matching {hold.get('s1_companion_glob')}")
    return problems


def _s1_edit_problems(path: str, spec: dict, pin: str, data: bytes) -> tuple[list[str], str | None]:
    """``(problems, recorded)``: ``recorded`` is None at S0, the S1 value otherwise."""
    pattern = _assignment(spec["constant"])
    lines = pattern.findall(data)
    if len(lines) != 1:
        return [f"{path}: {len(lines)} {spec['constant']} assignment lines, not 1"], None
    match = pattern.search(data)
    s0 = data[:match.start()] + spec["s0_line"].encode() + (match.group("eol") or b"") + data[match.end():]
    if _sha(s0) != pin:
        return [f"{path}: rebuilt S0 sha {_sha(s0)} is not the pin {pin} (an edit beyond {spec['constant']})"], None
    if s0 == data:
        return [], None
    if spec.get("judge") == SCORER_JUDGE:
        problems, recorded = b_scorer_entry_edit.s1_problems(s0, data)
        return [f"{path}: {p}" for p in problems], recorded
    recorded = _literal_sha(match.group("value"))
    if recorded is None:
        return [f"{path}: S1 sets {spec['constant']} to {match.group('value')!r}, not a 64-hex string literal"], None
    return [], recorded


def hold_problems(root: Path, hold: dict, decision_log: str) -> list[str]:
    hid = hold["id"]
    problems = []
    for path, pin in (hold.get("records") or {}).items():
        file = root / path
        if not file.is_file():
            problems.append(f"{hid}: record {path} is missing")
        elif _sha(file.read_bytes()) != pin:
            problems.append(f"{hid}: record {path} sha {_sha(file.read_bytes())} is not {pin}")
        if pin not in decision_log:
            problems.append(f"{hid}: record pin {pin} is not in {DECISION_LOG}")
    for pattern in hold.get("record_globs") or []:
        if not _git_glob(root, pattern):
            problems.append(f"{hid}: no file matches record glob {pattern}")
    for prefix in hold.get("frozen_prefixes") or []:
        if not (root / prefix).is_dir():
            problems.append(f"{hid}: frozen prefix {prefix} is missing")
    record = root / hold["release_record"]
    if record.is_file():
        return problems + [f"{hid}: {p}" for p in record_problems(record.read_text(encoding="utf-8"), hold,
                                                                  decision_log, root)]
    # Active: the code pins hold.
    release = root / hold["release_binding"] if hold.get("release_binding") else None
    if release is not None:
        try:
            files = json.loads(release.read_text(encoding="utf-8"))["files"]
        except (OSError, ValueError, KeyError) as exc:
            files = {}
            problems.append(f"{hid}: release binding {hold['release_binding']} is unreadable: {exc}")
        for path, pin in files.items():
            file = root / path
            if not file.is_file() or _sha(file.read_bytes()) != pin:
                problems.append(f"{hid}: release file {path} differs from {hold['release_binding']}")
    edits = hold.get("s1_edit") or {}
    recorded: dict[str, str | None] = {}
    for path, pin in (hold.get("code") or {}).items():
        file = root / path
        if not file.is_file():
            problems.append(f"{hid}: code pin {path} is missing")
            continue
        data = file.read_bytes()
        if path in edits:
            found, recorded[path] = _s1_edit_problems(path, edits[path], pin, data)
            problems += [f"{hid}: {p}" for p in found]
        elif _sha(data) != pin:
            problems.append(f"{hid}: code pin {path} sha {_sha(data)} is not {pin}")
    for path, spec in edits.items():
        partner = spec.get("equals")
        if partner and path in recorded and partner in recorded and recorded[path] != recorded[partner]:
            problems.append(f"{hid}: {path} {spec['constant']} ({recorded[path]}) is not the value recorded in "
                            f"{partner} ({recorded[partner]}); the S1 commit sets both")
    entry = hold.get("mg1_entry")
    s1 = recorded.get(entry["constant_in"]) if entry else None
    if entry and s1 is not None:
        source = (root / entry["registry"]).read_text(encoding="utf-8")
        found = re.findall(r'^\s*"' + re.escape(entry["module"]) + r'":\s*"([0-9a-f]{64})"', source, re.M)
        if found != [s1]:
            problems.append(f"{hid}: at S1 the {entry['module']} entry in {entry['registry']} is {found}, "
                            f"not the recorded MG1_LOOK_ENTRY_SHA256 {s1}")
    return problems


def all_problems(root: Path) -> list[str]:
    registry = json.loads((root / REGISTRY).read_text(encoding="utf-8"))
    problems = registry_problems(registry)
    if problems:
        return problems
    decision_log = (root / DECISION_LOG).read_text(encoding="utf-8")
    for hold in registry["holds"]:
        problems += hold_problems(root, hold, decision_log)
    return problems


def test_every_frozen_binding_holds_in_this_checkout():
    assert all_problems(ROOT) == []


def test_b1_hold_pins_the_ruled_files():
    [b1] = [h for h in json.loads((ROOT / REGISTRY).read_text(encoding="utf-8"))["holds"] if h["id"] == "B-1"]
    assert b1["records"] == {"docs/operations/B_FORWARD_TEST_DESIGN.md":
                             "e8bad6e8ce9988180e41e5f9589e180326a8c1886f6043f182187de38a2a6030"}
    assert b1["record_globs"] == ["docs/**/b1-clarification-*.md"]
    assert b1["frozen_prefixes"] == ["docs/research/mg2-composite-binding-2026-10-25/"]
    assert b1["release_record"] == "docs/research/b-look-record/b-look-record.md"
    assert {p: s[:8] for p, s in b1["code"].items()} == {
        "src/weather/calibration/b_scorer.py": "f941628a",
        "src/weather/calibration/b_scorer_entry_edit.py": "a08c1eaa",
        "src/weather/calibration/b_look_wrapper.py": "a77617a4",
        "tests/calibration/test_b_look_end_to_end_s0_s1.py": "8c062d34",
        "src/weather/calibration/b_look_per_date.py": "a28d2e65",
        "src/weather/calibration/b_post_look_serial.py": "0c485d6e",
        "tests/calibration/test_b_look_per_date.py": "b54cd895",
        "tests/calibration/test_b_post_look_serial.py": "42976969",
    }
    assert len(json.loads((ROOT / b1["release_binding"]).read_text(encoding="utf-8"))["files"]) == 15
    assert b1["s1_edit"]["src/weather/calibration/b_scorer.py"]["judge"] == SCORER_JUDGE
    assert b1["s1_companion_glob"] == "docs/research/**/b1-clarification-7-*.md"
    assert b1["record_rule_sha256"] == b1["records"]["docs/operations/B_FORWARD_TEST_DESIGN.md"]


# ---- mutants on tmp copies ----

SCORER = "src/weather/calibration/b_scorer.py"
WRAPPER = "src/weather/calibration/b_look_wrapper.py"
MG1_REGISTRY = "src/weather/mg1_reserved_window.py"
RECORD = "docs/research/b-look-record/b-look-record.md"
S1_VALUE = "1" * 64


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    """A copy of exactly the files the registry reads, so mutants never touch the checkout."""
    registry = json.loads((ROOT / REGISTRY).read_text(encoding="utf-8"))
    paths = {REGISTRY, DECISION_LOG}
    for hold in registry["holds"]:
        paths |= set(hold.get("records") or {}) | set(hold.get("code") or {})
        for pattern in hold.get("record_globs") or []:
            paths |= set(_git_glob(ROOT, pattern))
        for prefix in hold.get("frozen_prefixes") or []:
            paths |= {p.relative_to(ROOT).as_posix() for p in (ROOT / prefix).rglob("*") if p.is_file()}
        if hold.get("release_binding"):
            paths |= set(json.loads((ROOT / hold["release_binding"]).read_text(encoding="utf-8"))["files"])
        if hold.get("mg1_entry"):
            paths.add(hold["mg1_entry"]["registry"])
    for rel in paths:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, tmp_path / rel)
    return tmp_path


def _s0(tree: Path, rel: str, constant: str, s0_line: str) -> None:
    """Put a copied s1_edit file back at S0 (the checkout may already be at S1)."""
    data = (tree / rel).read_bytes()
    (tree / rel).write_bytes(_assignment(constant).sub(lambda m: s0_line.encode() + (m.group("eol") or b""), data))


def _set(tree: Path, rel: str, constant: str, value: str) -> None:
    data = (tree / rel).read_bytes()
    (tree / rel).write_bytes(_assignment(constant).sub(
        lambda m: f"{constant} = {value}".encode() + (m.group("eol") or b""), data))


def _at_s0(tree: Path) -> None:
    _s0(tree, SCORER, "MG1_LOOK_ENTRY_SHA256", "MG1_LOOK_ENTRY_SHA256 = MG1_LOOK_ENTRY_UNRECORDED")
    _s0(tree, WRAPPER, "MG1_LOOK_ENTRY_PIN", "MG1_LOOK_ENTRY_PIN = PIN_UNSET")


def _at_s1(tree: Path, scorer: str = S1_VALUE, wrapper: str = S1_VALUE, entry: str = S1_VALUE) -> None:
    _at_s0(tree)
    _set(tree, SCORER, "MG1_LOOK_ENTRY_SHA256", f'"{scorer}"')
    _set(tree, WRAPPER, "MG1_LOOK_ENTRY_PIN", f'"{wrapper}"')
    source = (tree / MG1_REGISTRY).read_text(encoding="utf-8")
    source = re.sub(r'("weather\.calibration\.mg1_look":\s*")[0-9a-f]{64}"', lambda m: m.group(1) + entry + '"',
                    source)
    (tree / MG1_REGISTRY).write_text(source, encoding="utf-8", newline="\n")


def test_tree_copy_holds_at_s0_and_at_a_consistent_s1(tree: Path):
    _at_s0(tree)
    assert all_problems(tree) == []
    _at_s1(tree)
    assert all_problems(tree) == []


def test_edited_code_pin_fails(tree: Path):
    path = tree / "src/weather/calibration/b_look_per_date.py"
    path.write_bytes(path.read_bytes() + b"# edit\n")
    [problem] = all_problems(tree)
    assert "code pin src/weather/calibration/b_look_per_date.py sha" in problem


def test_missing_code_pin_fails(tree: Path):
    (tree / "tests/calibration/test_b_post_look_serial.py").unlink()
    assert all_problems(tree) == ["B-1: code pin tests/calibration/test_b_post_look_serial.py is missing"]


def test_edited_record_fails(tree: Path):
    path = tree / "docs/operations/B_FORWARD_TEST_DESIGN.md"
    path.write_bytes(path.read_bytes() + b"\n")
    [problem] = all_problems(tree)
    assert "record docs/operations/B_FORWARD_TEST_DESIGN.md sha" in problem


def test_record_pin_must_be_in_the_decision_log(tree: Path):
    log = tree / DECISION_LOG
    log.write_text(log.read_text(encoding="utf-8").replace("e8bad6e8ce99", "e8bad6e8XX99"), encoding="utf-8")
    assert all_problems(tree) == [
        "B-1: record pin e8bad6e8ce9988180e41e5f9589e180326a8c1886f6043f182187de38a2a6030 is not in "
        "docs/operations/DECISION_LOG.md"]


def test_edited_release_file_fails(tree: Path):
    path = tree / "src/weather/calibration/mg2_composite.py"
    path.write_bytes(path.read_bytes() + b"\n")
    assert all_problems(tree) == ["B-1: release file src/weather/calibration/mg2_composite.py differs from "
                                  "docs/research/mg2-composite-binding-2026-10-25/release-binding.json"]


def test_scorer_edit_beyond_the_constant_fails(tree: Path):
    _at_s0(tree)
    path = tree / SCORER
    path.write_bytes(path.read_bytes().replace(b'MG1_RECEIPT_TIME = "looked_at_utc"', b'MG1_RECEIPT_TIME = "x"'))
    [problem] = all_problems(tree)
    assert "rebuilt S0 sha" in problem and SCORER in problem


def test_scorer_s1_that_the_judge_refuses_fails(tree: Path):
    _at_s1(tree)
    _set(tree, SCORER, "MG1_LOOK_ENTRY_SHA256", f'"{"A" * 64}"')  # uppercase: not a 64-hex literal
    problems = all_problems(tree)
    assert any("not a 64-hex string literal" in p and SCORER in p for p in problems), problems


def test_scorer_constant_line_ending_change_fails(tree: Path):
    _at_s1(tree)
    path = tree / SCORER
    path.write_bytes(path.read_bytes().replace(f'"{S1_VALUE}"\n'.encode(), f'"{S1_VALUE}"\r\n'.encode()))
    # the rebuilt S0 keeps S1's line ending, so it no longer hashes to the pin
    assert any("rebuilt S0 sha" in p and SCORER in p for p in all_problems(tree))


def test_wrapper_edit_beyond_the_pin_fails(tree: Path):
    _at_s0(tree)
    path = tree / WRAPPER
    path.write_bytes(path.read_bytes().replace(b"ACCEPT_S0_CONTROL = False", b"ACCEPT_S0_CONTROL = True"))
    [problem] = all_problems(tree)
    assert "rebuilt S0 sha" in problem and WRAPPER in problem


def test_wrapper_pin_not_a_sha_literal_fails(tree: Path):
    _at_s1(tree)
    _set(tree, WRAPPER, "MG1_LOOK_ENTRY_PIN", "PIN_UNSET + 'x'")
    assert any("not a 64-hex string literal" in p and WRAPPER in p for p in all_problems(tree))


@pytest.mark.parametrize("rel", [SCORER, WRAPPER])
def test_a_third_changed_line_at_s1_fails(tree: Path, rel: str):
    _at_s1(tree)
    path = tree / rel
    path.write_bytes(path.read_bytes() + b"# a third changed line\n")
    problems = all_problems(tree)
    assert any("rebuilt S0 sha" in p and rel in p for p in problems), problems


@pytest.mark.parametrize("side", ["wrapper_left_at_s0", "scorer_left_at_s0", "values_differ"])
def test_scorer_and_wrapper_move_to_s1_together(tree: Path, side: str):
    _at_s1(tree, wrapper="2" * 64 if side == "values_differ" else S1_VALUE)
    if side == "wrapper_left_at_s0":
        _s0(tree, WRAPPER, "MG1_LOOK_ENTRY_PIN", "MG1_LOOK_ENTRY_PIN = PIN_UNSET")
    if side == "scorer_left_at_s0":
        _s0(tree, SCORER, "MG1_LOOK_ENTRY_SHA256", "MG1_LOOK_ENTRY_SHA256 = MG1_LOOK_ENTRY_UNRECORDED")
    [problem] = all_problems(tree)
    assert "the S1 commit sets both" in problem


def test_at_s1_the_mg1_registry_entry_must_equal_the_constant(tree: Path):
    _at_s1(tree, entry="3" * 64)
    [problem] = all_problems(tree)
    assert "weather.calibration.mg1_look entry" in problem and S1_VALUE in problem


def test_at_s0_the_mg1_registry_entry_is_not_checked(tree: Path):
    _at_s1(tree, entry="3" * 64)
    _at_s0(tree)
    assert all_problems(tree) == []


def _record(tree: Path, text: str) -> None:
    (tree / RECORD).parent.mkdir(parents=True, exist_ok=True)
    (tree / RECORD).write_text(text, encoding="utf-8")


RECEIPT_REL = "docs/research/b-look-record/b_look_receipt.json"
RECEIPT_BYTES = b'{\r\n  "look": "b"\r\n}\r\n'  # CRLF on purpose: the sha is over the bytes as written
RULE = "e8bad6e8ce9988180e41e5f9589e180326a8c1886f6043f182187de38a2a6030"
GOOD_RECORD = (f"# B look record\n\nrule_sha256: {RULE}\nreceipt_path: {RECEIPT_REL}\n"
               f"receipt_sha256: {_sha(RECEIPT_BYTES)}\ndecision_log_row: 2026-10-28\n")
ABANDON_ROW = "| 2099-02-01 | **B-1 abandoned (owner).** The owner abandons B-1. |\n"
MASTER_ROW = "| 2099-02-01 | **MASTER RULING, not an owner decision: B-1 abandoned.** |\n"
ABANDONMENT = "# B abandoned\n\nb_abandonment: B-1 abandoned\ndecision_log_row: 2099-02-01\n"


ATTRIBUTE_MESSAGE = (f"receipt must be committed byte-exact: add '{RECEIPT_REL} -text' to .gitattributes in the "
                     "same head")


def _receipt(tree: Path, data: bytes = RECEIPT_BYTES, attribute: str | None = f"{RECEIPT_REL} -text") -> None:
    (tree / RECEIPT_REL).parent.mkdir(parents=True, exist_ok=True)
    (tree / RECEIPT_REL).write_bytes(data)
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    if attribute is not None:
        attributes = attributes.rstrip("\n") + f"\n{attribute}\n"
    (tree / ".gitattributes").write_text(attributes, encoding="utf-8", newline="\n")


@pytest.mark.parametrize("attribute", [f"{RECEIPT_REL} -text", f"{RECEIPT_REL} binary", f"/{RECEIPT_REL} -text"],
                         ids=["minus-text", "binary", "anchored"])
def test_receipt_attribute_line_passes(tree: Path, attribute: str):
    _receipt(tree, attribute=attribute)
    _record(tree, GOOD_RECORD)
    assert all_problems(tree) == []


@pytest.mark.parametrize("attribute", [None, f"{RECEIPT_REL} -text\n*.json text", f"{RECEIPT_REL} text",
                                       "docs/research/b-look-record/*.json -text", "b_look_receipt.json -text"],
                         ids=["no-line", "overridden-later", "text-not-minus", "glob-not-exact", "basename"])
def test_receipt_without_a_byte_exact_attribute_refuses(tree: Path, attribute: str | None):
    _receipt(tree, attribute=attribute)
    _record(tree, GOOD_RECORD)
    problems = all_problems(tree)
    assert f"B-1: {ATTRIBUTE_MESSAGE}" in problems, problems
    assert not any("not the sha256 of the bytes" in p for p in problems), problems


def _log_row(tree: Path, row: str) -> None:
    log = tree / DECISION_LOG
    log.write_bytes(log.read_bytes() + b"\n" + row.encode("utf-8"))


def test_a_present_record_releases_the_code_pins(tree: Path):
    path = tree / "src/weather/calibration/b_look_per_date.py"
    path.write_bytes(path.read_bytes() + b"# after-B fix\n")
    _receipt(tree)
    _record(tree, GOOD_RECORD)
    assert all_problems(tree) == []


def test_a_present_record_still_holds_the_records(tree: Path):
    _receipt(tree)
    _record(tree, GOOD_RECORD)
    path = tree / "docs/operations/B_FORWARD_TEST_DESIGN.md"
    path.write_bytes(path.read_bytes() + b"\n")
    assert len(all_problems(tree)) == 1


def test_receipt_sha_is_over_the_bytes_as_written(tree: Path):
    _receipt(tree, RECEIPT_BYTES.replace(b"\r\n", b"\n"))  # normalised line endings: a different file
    _record(tree, GOOD_RECORD)
    assert any("not the sha256 of the bytes" in p for p in all_problems(tree))


def test_an_owner_abandonment_record_releases(tree: Path):
    _log_row(tree, ABANDON_ROW)
    _record(tree, ABANDONMENT)
    assert all_problems(tree) == []


@pytest.mark.parametrize("row", [MASTER_ROW, "| 2099-02-01 | **Owner approves a pilot.** |\n",
                                 "| 2099-02-01 | **B-1 abandoned by master.** |\n"],
                         ids=["master-ruling", "owner-not-abandonment", "abandonment-not-owner"])
def test_an_abandonment_must_cite_an_owner_decision(tree: Path, row: str):
    _log_row(tree, row)
    _record(tree, ABANDONMENT)
    problems = all_problems(tree)
    assert any("names an owner abandonment" in p for p in problems), problems


@pytest.mark.parametrize(("text", "fragment"), [
    (GOOD_RECORD.replace("e8bad6e8ce99", "00bad6e8ce99"), "is not B's rule sha"),
    (GOOD_RECORD.replace(f"rule_sha256: {RULE}\n", ""), "is not B's rule sha"),
    (GOOD_RECORD.replace(_sha(RECEIPT_BYTES), _sha(RECEIPT_BYTES)[:63]), "is not 64 lowercase hex"),
    (GOOD_RECORD.replace(_sha(RECEIPT_BYTES), _sha(RECEIPT_BYTES).upper()), "is not 64 lowercase hex"),
    (GOOD_RECORD.replace(_sha(RECEIPT_BYTES), "5" * 64), "not the sha256 of the bytes"),
    (GOOD_RECORD.replace(f"receipt_path: {RECEIPT_REL}\n", ""), "receipt_path '' is not a repo-relative path"),
    (GOOD_RECORD.replace(RECEIPT_REL, "C:/x/receipt.json"), "is not a repo-relative path"),
    (GOOD_RECORD.replace(RECEIPT_REL, "/docs/receipt.json"), "is not a repo-relative path"),
    (GOOD_RECORD.replace(RECEIPT_REL, "docs/../receipt.json"), "is not a repo-relative path"),
    (GOOD_RECORD.replace(RECEIPT_REL, "docs\\receipt.json"), "is not a repo-relative path"),
    (GOOD_RECORD.replace(RECEIPT_REL, "docs/research/b-look-record/missing.json"), "is not in the checkout"),
    (GOOD_RECORD + f"rule_sha256: {RULE}\n", "appears more than once"),
    (GOOD_RECORD.replace("2026-10-28", "2099-01-01"), "decision_log_row"),
    ("# B look record\n", "decision_log_row"),
    ("b_abandonment: yes\n", "decision_log_row"),
], ids=["wrong-rule", "no-rule", "short-receipt-sha", "upper-receipt-sha", "receipt-sha-mismatch",
        "no-receipt-path", "drive-path", "absolute-path", "dotdot-path", "backslash-path", "receipt-missing",
        "duplicate-field", "row-not-in-log", "empty", "abandonment-without-row"])
def test_a_malformed_record_fails(tree: Path, text: str, fragment: str):
    _receipt(tree)
    _record(tree, text)
    problems = all_problems(tree)
    assert any(fragment in p for p in problems), problems


# ---- the strict S1 commit (master's R14 ruling 2026-11-01, (b)) ----

def _b1() -> dict:
    [b1] = [h for h in json.loads((ROOT / REGISTRY).read_text(encoding="utf-8"))["holds"] if h["id"] == "B-1"]
    return b1


S1_PAIR = [("M", SCORER), ("M", WRAPPER)]
CL7 = "docs/research/b-look-s1-2026-11-22/b1-clarification-7-s1-entry-2026-11-22.md"


@pytest.mark.parametrize("extra", [[], [("A", CL7)]], ids=["two-lines-only", "with-clarification-7"])
def test_strict_s1_commit_passes(extra: list):
    assert s1_commit_problems(_b1(), S1_PAIR + extra) == []


@pytest.mark.parametrize(("extra", "fragment"), [
    ([("A", CL7.replace("clarification-7-", "clarification-8-"))], "touches another path"),
    ([("A", CL7.replace("clarification-7-", "clarification-70-"))], "touches another path"),
    ([("A", "docs/operations/b1-clarification-7-x.md")], "touches another path"),
    ([("A", CL7), ("A", CL7.replace("s1-entry", "s1-entry-b"))], "adds 2 files"),
    ([("A", CL7), ("A", "docs/other.md")], "touches another path: docs/other.md (A)"),
    ([("M", CL7)], "touches another path"),
    ([("M", "docs/README.md")], "touches another path: docs/README.md (M)"),
    ([("A", "src/free.py")], "touches another path: src/free.py (A)"),
], ids=["other-number", "number-prefix", "outside-research", "two-new-files", "clarification-plus-other",
        "modify-clarification-7", "modify-existing", "extra-new-file"])
def test_strict_s1_commit_refuses(extra: list, fragment: str):
    problems = s1_commit_problems(_b1(), S1_PAIR + extra)
    assert any(fragment in p for p in problems), problems


def test_strict_s1_commit_needs_both_files():
    assert s1_commit_problems(_b1(), [("M", SCORER)]) == [f"the S1 edit must also change {WRAPPER}"]


@pytest.mark.parametrize("mutate", ["schema", "no_holds", "short_pin", "edit_not_code", "duplicate_id"])
def test_a_malformed_registry_fails(tree: Path, mutate: str):
    path = tree / REGISTRY
    registry = json.loads(path.read_text(encoding="utf-8"))
    hold = registry["holds"][0]
    if mutate == "schema":
        registry["schema"] = "frozen_bindings/0"
    if mutate == "no_holds":
        registry["holds"] = []
    if mutate == "short_pin":
        hold["code"][SCORER] = "f941628a"
    if mutate == "edit_not_code":
        hold["s1_edit"]["src/x.py"] = {"constant": "X", "s0_line": "X = 1"}
    if mutate == "duplicate_id":
        registry["holds"].append(dict(hold))
    path.write_text(json.dumps(registry), encoding="utf-8")
    assert all_problems(tree)


def test_record_glob_matches_new_clarifications(tree: Path):
    new = tree / "docs/research/x-2026-11-02/b1-clarification-4-coverage-2026-11-02.md"
    new.parent.mkdir(parents=True)
    new.write_text("new\n", encoding="utf-8")
    assert "docs/research/x-2026-11-02/b1-clarification-4-coverage-2026-11-02.md" in _git_glob(
        tree, "docs/**/b1-clarification-*.md")
    assert all_problems(tree) == []
