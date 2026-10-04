"""Anti-regrowth ratchet for test modules, and the ratchet's own detector tests.

Guards: test-suite review K (2026-10-04) anti-regrowth PROPOSAL — no new unguarded test modules, .ps1 text
asserts without an execution twin (EF §10g: substring tests hid an inert kill path for 27 days), private
product imports, or unmarked git/PowerShell-spawning tests. Rules and baseline: tests/hygiene_ratchet.py.
"""

from __future__ import annotations

import ast
import json
from functools import lru_cache
from pathlib import Path

import pytest

from tests import hygiene_ratchet as ratchet

ROOTS = frozenset({"weather", "maker_core", "app"})


def facts(source: str) -> ratchet.ModuleFacts:
    return ratchet.analyse_source(source, ROOTS)


def count(source: str, rule: str) -> int:
    return facts(source).counts.get(rule, 0)


GUARDED = '"""Thing.\n\nGuards: EF §8d orphaned refresh child.\n"""\n'


@lru_cache(maxsize=1)
def _current() -> dict[str, dict[str, int]]:
    return ratchet.counts_by_rule(ratchet.scan())


# --------------------------------------------------------------------------------------- the ratchet
@pytest.mark.parametrize("rule", ratchet.RULES)
def test_no_rule_grows_beyond_its_baseline(rule: str) -> None:
    failures = ratchet.growth(_current(), ratchet.load_baseline())[rule]
    assert not failures, (
        f"{rule} grew ({ratchet.RULE_HELP[rule]}):\n  " + "\n  ".join(failures)
        + "\nLowering counts never fails; 'python -m tests.hygiene_ratchet --tighten' records a decrease."
    )


def test_baseline_file_is_canonical() -> None:
    baseline = ratchet.load_baseline()
    for rule, entries in baseline.items():
        assert list(entries) == sorted(entries), f"{rule} entries must be sorted"
    raw = json.loads(ratchet.BASELINE_PATH.read_text(encoding="utf-8"))
    assert list(raw["rules"]) == list(ratchet.RULES)


def test_this_module_complies_without_a_baseline_entry() -> None:
    rel = Path(__file__).resolve().relative_to(ratchet.REPO_ROOT).as_posix()
    baseline = ratchet.load_baseline()
    assert all(rel not in entries for entries in baseline.values())
    assert ratchet.analyse_source(Path(__file__).read_text(encoding="utf-8")).counts == {}


# ------------------------------------------------------------------------------------- guards rule
@pytest.mark.parametrize(
    ("docstring", "expected"),
    [
        (GUARDED, 0),
        ('"""Guards: contract docs/operations/X.md section 3."""\n', 0),
        ('"""Thing.\n\nguards:  release binding of serving manifests\n"""\n', 0),
        ('"""Thing.\n\nGuards: x\n"""\n', 1),
        ('"""Thing without the tag."""\n', 1),
        ("GUARDS = 'not a docstring line'\n", 1),
        ("", 1),
    ],
    ids=['tagged', 'contract', 'lowercase', 'too-short', 'untagged', 'constant-not-docstring', 'empty'],
)
def test_guards_declaration_needs_a_docstring_line(docstring: str, expected: int) -> None:
    assert count(docstring + "def test_a():\n    assert True\n", "guards_declaration") == expected


# ------------------------------------------------------------------------------ private import rule
@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("from weather.operations.status import _helper", 1),
        ("from weather.operations.status import _a, _b, public", 2),
        ("from weather._fixture_record import thing", 1),
        ("import weather.operations._internal", 1),
        ("from app.views import _render", 1),
        ("from weather import __version__", 0),
        ("from weather.operations.status import helper", 0),
        ("from tests.operations.test_x import _fixture", 0),
        ("from collections import _OrderedDictKeysView", 0),
        ("from . import _local", 0),
    ],
    ids=['private-name', 'two-private', 'private-module', 'import-private-module', 'app-private', 'dunder', 'public', 'tests-helper', 'stdlib', 'relative'],
)
def test_private_src_import_counts_each_private_name(line: str, expected: int) -> None:
    assert count(GUARDED + line + "\n", "private_src_import") == expected


def test_private_src_import_counts_function_level_imports() -> None:
    source = GUARDED + "def test_a():\n    from maker_core.quoting.policy import _gate\n    assert _gate\n"
    assert count(source, "private_src_import") == 1


# --------------------------------------------------------------------------------- .ps1 text rule
PS1_READ = GUARDED + 'from pathlib import Path\nSCRIPT = Path("scripts/ops/guard.ps1")\n'


@pytest.mark.parametrize(
    "body",
    [
        'def test_a():\n    text = SCRIPT.read_text()\n    assert "Stop-Process" in text\n',
        'def test_a():\n    assert "Stop-Process" not in SCRIPT.read_text(encoding="utf-8")\n',
        'TEXT = SCRIPT.read_text()\ndef test_a():\n    assert TEXT.count("-WarnPercent") == 1\n',
        'import re\ndef test_a():\n    t = SCRIPT.read_text().lower()\n    assert re.search(r"kill", t)\n',
        'def body():\n    return SCRIPT.read_text()\ndef test_a():\n    assert "x" in body()\n',
        'def test_a():\n    with open("scripts/ops/x.ps1") as fh:\n        text = fh.read()\n    assert text.startswith("param")\n',
        'def test_a():\n    text = SCRIPT.read_text()\n    assert all(n in text for n in ("a", "b"))\n',
    ],
    ids=['in-local', 'not-in-inline', 'module-count', 'regex', 'helper-return', 'with-open', 'generator'],
)
def test_ps1_text_asserts_without_execution_are_counted(body: str) -> None:
    assert count(PS1_READ + body, "ps1_substring_without_execution") == 1


@pytest.mark.parametrize(
    "body",
    [
        # reads JSON, not script text
        'def test_a():\n    text = Path("x.json").read_text()\n    assert "k" in text\n',
        # asserts on the output of running the script, not on its text
        'import subprocess\ndef test_a():\n    r = subprocess.run(["python", str(SCRIPT)], capture_output=True, text=True)\n'
        '    assert "ok" in r.stdout\n',
        # a substring assert next to an execution twin in the same module
        'import subprocess\ndef test_text():\n    assert "Stop-Process" in SCRIPT.read_text()\n'
        'def test_exec():\n    subprocess.run(["powershell.exe", "-File", str(SCRIPT)], check=True)\n',
    ],
    ids=['json', 'script-output', 'execution-twin'],
)
def test_ps1_rule_ignores_other_text_and_modules_with_an_execution_twin(body: str) -> None:
    assert count(PS1_READ + body, "ps1_substring_without_execution") == 0


def test_shared_powershell_host_counts_as_execution() -> None:
    source = PS1_READ + (
        "from tests.powershell_host import run_powershell\n"
        'def test_text():\n    assert "x" in SCRIPT.read_text()\n'
        "def test_exec():\n    run_powershell(SCRIPT)\n"
    )
    assert count(source, "ps1_substring_without_execution") == 0


# -------------------------------------------------------------------------------- spawn marker rule
SPAWN_HEAD = GUARDED + "import subprocess\nimport sys\nimport pytest\n"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ('def test_a(tmp_path):\n    subprocess.run(["git", "init", str(tmp_path)], check=True)\n', 1),
        ('@pytest.mark.spawns\ndef test_a(tmp_path):\n    subprocess.run(["git", "init", str(tmp_path)])\n', 0),
        ('pytestmark = [pytest.mark.spawns]\ndef test_a(tmp_path):\n    subprocess.run(["git", "init"])\n', 0),
        ('pytestmark = pytest.mark.spawns\ndef test_a(tmp_path):\n    subprocess.run(["git", "init"])\n', 0),
        (
            '@pytest.mark.spawns\nclass TestX:\n    def test_a(self):\n        subprocess.run(["git", "status"])\n'
            '    def test_b(self):\n        subprocess.run(["powershell.exe", "-Command", "1"])\n',
            0,
        ),
        ('class TestX:\n    def test_a(self):\n        subprocess.run(["git", "status"])\n', 1),
        # a Python child is not a git/PowerShell spawn
        ('def test_a():\n    subprocess.run([sys.executable, "-c", "pass"], check=True)\n', 0),
        # through a same-module fixture
        (
            '@pytest.fixture\ndef repo(tmp_path):\n    subprocess.run(["git", "init", str(tmp_path)])\n    return tmp_path\n'
            "def test_a(repo):\n    assert repo\ndef test_b(tmp_path):\n    assert tmp_path\n",
            1,
        ),
        # through a generic helper called with a PowerShell command line
        (
            'POWERSHELL = "powershell.exe"\ndef run(cmd):\n    return subprocess.run(cmd, capture_output=True)\n'
            'def test_a():\n    run([POWERSHELL, "-File", "x.ps1"])\ndef test_b():\n    run([sys.executable, "-V"])\n',
            1,
        ),
        # an autouse spawning fixture makes every test spawn
        (
            '@pytest.fixture(autouse=True)\ndef repo(tmp_path):\n    subprocess.run(["git", "init", str(tmp_path)])\n'
            "def test_a():\n    pass\ndef test_b():\n    pass\n",
            2,
        ),
        # a parametrized test counts once
        (
            '@pytest.mark.parametrize("x", [1, 2, 3])\ndef test_a(x):\n    subprocess.run(["git", "--version"])\n',
            1,
        ),
    ],
    ids=['git-unmarked', 'decorator', 'pytestmark-list', 'pytestmark-single', 'class-mark', 'class-unmarked', 'python-child', 'fixture', 'generic-helper', 'autouse', 'parametrized'],
)
def test_spawning_tests_need_the_spawns_mark(body: str, expected: int) -> None:
    assert count(SPAWN_HEAD + body, "unmarked_spawning_test") == expected


def test_spawn_helper_modules_count_as_spawns() -> None:
    source = GUARDED + "from tests.git_template import clone_template\ndef test_a(tmp_path):\n    clone_template(tmp_path)\n"
    assert count(source, "unmarked_spawning_test") == 1


# --------------------------------------------------------------------------------- baseline logic
def test_growth_flags_only_counts_above_the_allowance() -> None:
    current = {rule: {} for rule in ratchet.RULES}
    current["private_src_import"] = {"tests/a.py": 3, "tests/b.py": 2, "tests/new.py": 1}
    baseline = {rule: {} for rule in ratchet.RULES}
    baseline["private_src_import"] = {"tests/a.py": 3, "tests/b.py": 5, "tests/gone.py": 4}
    failures = ratchet.growth(current, baseline)
    assert failures["private_src_import"] == ["tests/new.py: 1 > allowed 0"]
    current["private_src_import"]["tests/a.py"] = 4
    assert "tests/a.py: 4 > allowed 3" in ratchet.growth(current, baseline)["private_src_import"]


def test_tighten_only_lowers_and_drops_cleared_or_vanished_modules() -> None:
    current = {rule: {} for rule in ratchet.RULES}
    current["guards_declaration"] = {"tests/a.py": 1, "tests/new.py": 1}
    current["unmarked_spawning_test"] = {"tests/a.py": 2}
    baseline = {rule: {} for rule in ratchet.RULES}
    baseline["guards_declaration"] = {"tests/a.py": 1, "tests/fixed.py": 1}
    baseline["unmarked_spawning_test"] = {"tests/a.py": 5}
    out = ratchet.tightened(current, baseline)
    assert out["guards_declaration"] == {"tests/a.py": 1}
    assert out["unmarked_spawning_test"] == {"tests/a.py": 2}


@pytest.mark.parametrize(
    "payload",
    [
        {"schema": "other", "rules": {}},
        {"schema": ratchet.BASELINE_SCHEMA, "rules": {"guards_declaration": {}}},
        {"schema": ratchet.BASELINE_SCHEMA, "rules": {r: ({"tests/a.py": 0} if i == 0 else {}) for i, r in enumerate(ratchet.RULES)}},
        {"schema": ratchet.BASELINE_SCHEMA, "rules": {r: ({"tests/a.py": True} if i == 0 else {}) for i, r in enumerate(ratchet.RULES)}},
    ],
    ids=['schema', 'missing-rules', 'zero', 'bool'],
)
def test_malformed_baselines_are_refused(tmp_path: Path, payload: dict) -> None:
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        ratchet.load_baseline(path)


def test_raises_match_is_reported_as_guideline_not_rule() -> None:
    source = GUARDED + (
        "import pytest\ndef test_a():\n    with pytest.raises(ValueError, match='refused'):\n        int('x')\n"
        "    with pytest.raises(ValueError):\n        int('y')\n"
    )
    module = facts(source)
    assert module.raises_match == 1
    assert module.counts == {}


def test_every_detector_reads_the_ast_not_text() -> None:
    # A rule word inside a string must not trigger anything.
    source = GUARDED + 'NOTE = "from weather.x import _y; subprocess.run([\'git\']); open(\'a.ps1\').read()"\n'
    assert facts(source).counts == {}
    assert isinstance(ast.parse(source), ast.Module)
