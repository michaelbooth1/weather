"""Frozen bindings: every hold in ``config/frozen_bindings.json`` holds in this checkout.

Guards: ruling R14 (master 2026-11-01; review items 14 and 27). B-1's frozen files are guarded in the repository
and released by B's committed look record (``release_record``), never by a date. Records are frozen permanently;
code pins (and the files of ``release_binding``) only while the hold is active, i.e. while its release record is
absent. The only permitted change of the code pins is the ``s1_edit`` of B-1 Clarification 3 section 5 (master's
R14 ruling, 2026-11-01): exactly two changed lines, ``b_scorer.py``'s ``MG1_LOOK_ENTRY_SHA256`` (as judged by
``b_scorer_entry_edit.s1_problems``) and the look wrapper's ``MG1_LOOK_ENTRY_PIN``, both set to the same value, and
nothing else in either file. At S1 the MG-1 registry entry in ``mg1_reserved_window.py`` must equal the recorded
``MG1_LOOK_ENTRY_SHA256``. The git-diff side (no modify or delete of a record, additions only to the registry, no
other file in the S1 head) is ``scripts/ops/frozen_binding_guard.ps1``.

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
    return problems


def record_problems(text: str, hold: dict, decision_log: str) -> list[str]:
    """A present release record: rule sha, receipt sha and DL row; or a master abandonment with its DL row."""
    fields = {m.group("key"): m.group("value") for m in RECORD_FIELD.finditer(text)}
    problems = []
    row = fields.get("decision_log_row", "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row) or f"| {row} |" not in decision_log:
        problems.append(f"release record decision_log_row {row!r} names no DECISION_LOG row")
    if "b_abandonment" in fields:
        return problems
    rule = fields.get("rule_sha256", "")
    if rule not in set((hold.get("records") or {}).values()):
        problems.append(f"release record rule_sha256 {rule!r} is not a record pin of hold {hold.get('id')}")
    if not HEX64.match(fields.get("receipt_sha256", "")):
        problems.append(f"release record receipt_sha256 {fields.get('receipt_sha256')!r} is not 64 hex")
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
                                                                  decision_log)]
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
    assert any("line ending changed" in p for p in all_problems(tree))


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


GOOD_RECORD = ("# B look record\n\nrule_sha256: e8bad6e8ce9988180e41e5f9589e180326a8c1886f6043f182187de38a2a6030\n"
               f"receipt_sha256: {'4' * 64}\ndecision_log_row: 2026-10-28\n")


def test_a_present_record_releases_the_code_pins(tree: Path):
    path = tree / "src/weather/calibration/b_look_per_date.py"
    path.write_bytes(path.read_bytes() + b"# after-B fix\n")
    _record(tree, GOOD_RECORD)
    assert all_problems(tree) == []


def test_a_present_record_still_holds_the_records(tree: Path):
    _record(tree, GOOD_RECORD)
    path = tree / "docs/operations/B_FORWARD_TEST_DESIGN.md"
    path.write_bytes(path.read_bytes() + b"\n")
    assert len(all_problems(tree)) == 1


def test_an_abandonment_record_releases(tree: Path):
    _record(tree, "# B abandoned\n\nb_abandonment: master abandons B-1\ndecision_log_row: 2026-10-28\n")
    assert all_problems(tree) == []


@pytest.mark.parametrize(("text", "fragment"), [
    (GOOD_RECORD.replace("e8bad6e8ce99", "00bad6e8ce99"), "rule_sha256"),
    (GOOD_RECORD.replace("4" * 64, "4" * 63), "receipt_sha256"),
    (GOOD_RECORD.replace("2026-10-28", "2099-01-01"), "decision_log_row"),
    ("# B look record\n", "decision_log_row"),
    ("b_abandonment: yes\n", "decision_log_row"),
], ids=["wrong-rule", "short-receipt", "row-not-in-log", "empty", "abandonment-without-row"])
def test_a_malformed_record_fails(tree: Path, text: str, fragment: str):
    _record(tree, text)
    problems = all_problems(tree)
    assert problems and all(fragment in p for p in problems), problems


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
